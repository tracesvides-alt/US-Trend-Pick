"""Market Regime calculation built on the Base Ranking and price cache."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date
from math import ceil
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from engine.dates import measurement_date
from engine.ranking.momentum import adjusted_price_series

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_UNIVERSE_DIR = PROJECT_ROOT / "data" / "universe"
DEFAULT_BASE_DIR = PROJECT_ROOT / "data" / "results"
DEFAULT_CACHE_PATH = PROJECT_ROOT / "data" / "market_data" / "prices.parquet"
DEFAULT_METADATA_PATH = PROJECT_ROOT / "data" / "market_data" / "metadata.json"
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "data" / "results"

REGIME_WEIGHTS = {
    "nasdaq100_trend": 0.20,
    "sp500_trend": 0.15,
    "market_breadth": 0.25,
    "strategy_leadership": 0.20,
    "volatility_regime": 0.20,
}


class RegimeState:
    """String constants used for regime state and hysteresis."""

    RISK_ON = "RISK_ON"
    WARNING = "WARNING"
    RISK_OFF = "RISK_OFF"


@dataclass(frozen=True)
class TrendMetrics:
    score: float | None
    price: float | None
    dma50: float | None
    dma200: float | None
    dma50_slope_20d: float | None
    price_above_50dma: bool
    dma50_above_200dma: bool
    slope_positive: bool
    stage4: bool
    status: str


@dataclass(frozen=True)
class BreadthMetrics:
    score: float | None
    ratios: dict[str, float | None]
    member_counts: dict[str, int]
    missing_tickers: dict[str, list[str]]
    status: str


@dataclass(frozen=True)
class LeadershipMetrics:
    score: float | None
    leader_count: int
    leaders_median_20d_return: float | None
    sp500_20d_return: float | None
    excess_20d_return: float | None
    status: str


@dataclass(frozen=True)
class VolatilityMetrics:
    score: float | None
    current_20d_realized_vol: float | None
    historical_median_20d_realized_vol: float | None
    ratio: float | None
    status: str


def linear_score(value: float, points: list[tuple[float, float]]) -> float:
    """Linearly interpolate a descending or ascending piecewise score map."""

    if not np.isfinite(value):
        return float("nan")
    ordered = sorted(points)
    if value <= ordered[0][0]:
        return float(ordered[0][1])
    if value >= ordered[-1][0]:
        return float(ordered[-1][1])
    for (left_x, left_y), (right_x, right_y) in zip(ordered, ordered[1:]):
        if left_x <= value <= right_x:
            fraction = (value - left_x) / (right_x - left_x)
            return float(left_y + fraction * (right_y - left_y))
    return float("nan")


def calculate_trend(
    data: pd.DataFrame | pd.Series,
    dma50_window: int = 50,
    dma200_window: int = 200,
    slope_days: int = 20,
) -> TrendMetrics:
    """Calculate the three-part index trend score and Stage 4 flag."""

    prices = adjusted_price_series(data)
    if len(prices) < dma200_window + slope_days:
        return TrendMetrics(None, None, None, None, None, False, False, False, False, "INSUFFICIENT_HISTORY")
    dma50 = prices.rolling(dma50_window).mean()
    dma200 = prices.rolling(dma200_window).mean()
    price = float(prices.iloc[-1])
    current_50 = float(dma50.iloc[-1])
    current_200 = float(dma200.iloc[-1])
    previous_50 = float(dma50.iloc[-1 - slope_days])
    slope = current_50 - previous_50
    above_50 = price > current_50
    above_200 = current_50 > current_200
    slope_positive = slope > 0
    score = float(35 * above_50 + 40 * above_200 + 25 * slope_positive)
    stage4 = price < current_200 and current_50 < current_200
    return TrendMetrics(
        score,
        price,
        current_50,
        current_200,
        slope,
        above_50,
        above_200,
        slope_positive,
        stage4,
        "OK",
    )


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"true", "1", "yes", "y"}


def _price_above_dma(data: pd.DataFrame, window: int) -> bool | None:
    prices = adjusted_price_series(data)
    if len(prices) < window:
        return None
    dma = prices.rolling(window).mean().iloc[-1]
    if not np.isfinite(dma) or not np.isfinite(prices.iloc[-1]):
        return None
    return bool(prices.iloc[-1] > dma)


def calculate_breadth(
    universe: pd.DataFrame,
    price_data: pd.DataFrame,
    dma_window: int = 50,
) -> BreadthMetrics:
    """Calculate equal-weighted SPY, QQQ, and QQQJ constituent breadth."""

    groups = {
        ticker: rows
        for ticker, rows in price_data.assign(
            ticker=price_data["ticker"].astype(str).str.strip().str.upper()
        ).groupby("ticker")
    }
    ratios: dict[str, float | None] = {}
    member_counts: dict[str, int] = {}
    missing: dict[str, list[str]] = {}
    for source, column in (
        ("sp500", "source_spy"),
        ("nasdaq100", "source_qqq"),
        ("next100", "source_qqqj"),
    ):
        if column not in universe.columns:
            ratios[source] = None
            member_counts[source] = 0
            missing[source] = [f"missing {column} column"]
            continue
        members = sorted(
            set(
                universe.loc[universe[column].map(_as_bool), "ticker"]
                .dropna()
                .astype(str)
                .str.strip()
                .str.upper()
            )
        )
        member_counts[source] = len(members)
        values: list[bool] = []
        missing[source] = []
        for ticker in members:
            above = _price_above_dma(groups.get(ticker, pd.DataFrame()), dma_window)
            if above is None:
                missing[source].append(ticker)
            else:
                values.append(above)
        ratios[source] = float(np.mean(values)) if not missing[source] and values else None
    valid_ratios = [ratio for ratio in ratios.values() if ratio is not None]
    score = float(np.mean(valid_ratios) * 100.0) if len(valid_ratios) == 3 else None
    status = "OK" if score is not None else "INCOMPLETE"
    return BreadthMetrics(score, ratios, member_counts, missing, status)


def calculate_20d_return(
    data: pd.DataFrame | pd.Series,
    period: int = 20,
) -> float:
    """Calculate adjusted-price return over the latest 20 trading observations."""

    prices = adjusted_price_series(data)
    if len(prices) <= period:
        return float("nan")
    start = prices.iloc[-1 - period]
    end = prices.iloc[-1]
    if not np.isfinite(start) or not np.isfinite(end) or start <= 0:
        return float("nan")
    return float(end / start - 1.0)


def strategy_leadership_score(excess_20d_return: float) -> float:
    """Map leader excess return to the specified 0-100 leadership score."""

    return linear_score(
        excess_20d_return,
        [(-0.08, 0.0), (-0.03, 30.0), (0.0, 60.0), (0.02, 80.0), (0.05, 100.0)],
    )


def calculate_strategy_leadership(
    base_ranking: pd.DataFrame,
    price_data: pd.DataFrame,
    sp500_data: pd.DataFrame,
    top_fraction: float = 0.20,
) -> LeadershipMetrics:
    """Compare the neutral Base top-20% median 20D return with S&P500."""

    if base_ranking.empty or "ticker" not in base_ranking.columns:
        return LeadershipMetrics(None, 0, None, None, None, "INCOMPLETE")
    count = max(1, ceil(len(base_ranking) * top_fraction))
    leaders = base_ranking.sort_values(["base_rank", "ticker"]).head(count)
    groups = {
        ticker: rows
        for ticker, rows in price_data.assign(
            ticker=price_data["ticker"].astype(str).str.strip().str.upper()
        ).groupby("ticker")
    }
    leader_returns = [
        calculate_20d_return(groups[ticker])
        for ticker in leaders["ticker"].astype(str).str.strip().str.upper()
        if ticker in groups
    ]
    leader_returns = [value for value in leader_returns if np.isfinite(value)]
    sp500_return = calculate_20d_return(sp500_data)
    if len(leader_returns) != count or not np.isfinite(sp500_return):
        return LeadershipMetrics(None, count, None, sp500_return, None, "INCOMPLETE")
    median = float(np.median(leader_returns))
    excess = median - sp500_return
    return LeadershipMetrics(
        strategy_leadership_score(excess),
        count,
        median,
        sp500_return,
        excess,
        "OK",
    )


def volatility_score(ratio: float) -> float:
    """Map the NASDAQ100 volatility ratio to the specified score."""

    return linear_score(
        ratio,
        [(0.8, 100.0), (1.0, 90.0), (1.25, 70.0), (1.5, 50.0), (1.75, 25.0), (2.0, 0.0)],
    )


def calculate_volatility(
    data: pd.DataFrame | pd.Series,
    realized_window: int = 20,
    history_window: int = 252,
) -> VolatilityMetrics:
    """Calculate current/median 20D realized-volatility ratio."""

    prices = adjusted_price_series(data)
    returns = prices.pct_change(fill_method=None)
    realized = returns.rolling(realized_window).std(ddof=1) * np.sqrt(252.0)
    valid = realized.dropna()
    if len(valid) < history_window + 1:
        return VolatilityMetrics(None, None, None, None, "INSUFFICIENT_HISTORY")
    current = float(valid.iloc[-1])
    historical_median = float(valid.iloc[-history_window - 1 : -1].median())
    if historical_median <= 0 or not np.isfinite(current) or not np.isfinite(historical_median):
        return VolatilityMetrics(None, current, historical_median, None, "VOLATILITY_UNAVAILABLE")
    ratio = current / historical_median
    return VolatilityMetrics(volatility_score(ratio), current, historical_median, ratio, "OK")


def calculate_market_regime_score(component_scores: dict[str, float | None]) -> float | None:
    """Apply the 20/15/25/20/20 component weights."""

    if any(
        key not in component_scores
        or component_scores[key] is None
        or not np.isfinite(component_scores[key])
        for key in REGIME_WEIGHTS
    ):
        return None
    return float(sum(component_scores[key] * weight for key, weight in REGIME_WEIGHTS.items()))


def classify_regime(
    score: float,
    previous_state: str | None = None,
    nasdaq_stage4: bool = False,
    sp500_stage4: bool = False,
) -> str:
    """Classify score with hysteresis, then apply Stage 4 overrides."""

    if not np.isfinite(score):
        raise ValueError("score must be finite")
    if previous_state is None:
        if score >= 70:
            state = RegimeState.RISK_ON
        elif score <= 40:
            state = RegimeState.RISK_OFF
        else:
            state = RegimeState.WARNING
    elif previous_state == RegimeState.WARNING:
        if score >= 70:
            state = RegimeState.RISK_ON
        elif score <= 40:
            state = RegimeState.RISK_OFF
        else:
            state = RegimeState.WARNING
    elif previous_state == RegimeState.RISK_ON:
        state = RegimeState.WARNING if score < 60 else RegimeState.RISK_ON
    elif previous_state == RegimeState.RISK_OFF:
        state = RegimeState.WARNING if score >= 50 else RegimeState.RISK_OFF
    else:
        raise ValueError(f"unknown previous_state: {previous_state}")

    if nasdaq_stage4 and sp500_stage4:
        return RegimeState.RISK_OFF
    if nasdaq_stage4 and state == RegimeState.RISK_ON:
        return RegimeState.WARNING
    return state


def _latest_file(directory: str | Path, pattern: str) -> Path:
    files = sorted(Path(directory).glob(pattern))
    if not files:
        raise FileNotFoundError(f"No {pattern} found in {directory}")
    return files[-1]


def _load_base(path: str | Path | None = None) -> pd.DataFrame:
    base_path = Path(path) if path is not None else _latest_file(DEFAULT_BASE_DIR, "base-*.csv")
    return pd.read_csv(base_path)


def _load_universe(path: str | Path | None = None) -> pd.DataFrame:
    universe_path = Path(path) if path is not None else _latest_file(DEFAULT_UNIVERSE_DIR, "*.csv")
    return pd.read_csv(universe_path)


def _load_metadata(path: str | Path) -> dict[str, Any]:
    metadata_path = Path(path)
    if not metadata_path.exists():
        return {}
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def _groups(price_data: pd.DataFrame) -> dict[str, pd.DataFrame]:
    frame = price_data.copy()
    frame["ticker"] = frame["ticker"].astype(str).str.strip().str.upper()
    return {ticker: rows.reset_index(drop=True) for ticker, rows in frame.groupby("ticker")}


def _trend_dict(metrics: TrendMetrics) -> dict[str, Any]:
    return {
        "score": metrics.score,
        "price": metrics.price,
        "dma50": metrics.dma50,
        "dma200": metrics.dma200,
        "dma50_slope_20d": metrics.dma50_slope_20d,
        "price_above_50dma": metrics.price_above_50dma,
        "dma50_above_200dma": metrics.dma50_above_200dma,
        "slope_positive": metrics.slope_positive,
        "stage4": metrics.stage4,
        "status": metrics.status,
    }


def _breadth_dict(metrics: BreadthMetrics) -> dict[str, Any]:
    return {
        "score": metrics.score,
        "ratios": metrics.ratios,
        "member_counts": metrics.member_counts,
        "missing_tickers": metrics.missing_tickers,
        "status": metrics.status,
    }


def _leadership_dict(metrics: LeadershipMetrics) -> dict[str, Any]:
    return {
        "score": metrics.score,
        "leader_count": metrics.leader_count,
        "leaders_median_20d_return": metrics.leaders_median_20d_return,
        "sp500_20d_return": metrics.sp500_20d_return,
        "excess_20d_return": metrics.excess_20d_return,
        "status": metrics.status,
    }


def _volatility_dict(metrics: VolatilityMetrics) -> dict[str, Any]:
    return {
        "score": metrics.score,
        "current_20d_realized_vol": metrics.current_20d_realized_vol,
        "historical_median_20d_realized_vol": metrics.historical_median_20d_realized_vol,
        "ratio": metrics.ratio,
        "status": metrics.status,
    }


def calculate_regime_snapshot(
    universe: pd.DataFrame,
    base_ranking: pd.DataFrame,
    price_data: pd.DataFrame,
    benchmark_sources: dict[str, str],
    previous_state: str | None = None,
) -> dict[str, Any]:
    """Calculate a serializable Market Regime snapshot."""

    groups = _groups(price_data)
    sp500_ticker = str(benchmark_sources.get("sp500", "^GSPC")).strip().upper()
    nasdaq_ticker = str(benchmark_sources.get("nasdaq100", "^NDX")).strip().upper()
    sp500_data = groups.get(sp500_ticker, pd.DataFrame())
    nasdaq_data = groups.get(nasdaq_ticker, pd.DataFrame())
    nasdaq_trend = calculate_trend(nasdaq_data)
    sp500_trend = calculate_trend(sp500_data)
    breadth = calculate_breadth(universe, price_data)
    leadership = calculate_strategy_leadership(base_ranking, price_data, sp500_data)
    volatility = calculate_volatility(nasdaq_data)
    component_scores = {
        "nasdaq100_trend": nasdaq_trend.score,
        "sp500_trend": sp500_trend.score,
        "market_breadth": breadth.score,
        "strategy_leadership": leadership.score,
        "volatility_regime": volatility.score,
    }
    score = calculate_market_regime_score(component_scores)
    missing_reasons: dict[str, Any] = {}
    for name, status in (
        ("nasdaq100_trend", nasdaq_trend.status),
        ("sp500_trend", sp500_trend.status),
        ("market_breadth", breadth.status),
        ("strategy_leadership", leadership.status),
        ("volatility_regime", volatility.status),
    ):
        if status != "OK":
            missing_reasons[name] = status
    regime = (
        classify_regime(
            score,
            previous_state=previous_state,
            nasdaq_stage4=nasdaq_trend.stage4,
            sp500_stage4=sp500_trend.stage4,
        )
        if score is not None
        else None
    )
    return {
        "component_scores": component_scores,
        "component_weights": REGIME_WEIGHTS,
        "market_regime_score": score,
        "regime": regime,
        "previous_state": previous_state,
        "data_status": "COMPLETE" if not missing_reasons else "INCOMPLETE",
        "missing_reasons": missing_reasons,
        "benchmark_sources": {
            "sp500": sp500_ticker,
            "nasdaq100": nasdaq_ticker,
        },
        "nasdaq100_trend": _trend_dict(nasdaq_trend),
        "sp500_trend": _trend_dict(sp500_trend),
        "market_breadth": _breadth_dict(breadth),
        "strategy_leadership": _leadership_dict(leadership),
        "volatility_regime": _volatility_dict(volatility),
        "stage_override": {
            "nasdaq100_stage4": nasdaq_trend.stage4,
            "sp500_stage4": sp500_trend.stage4,
            "nasdaq100_risk_on_forbidden": nasdaq_trend.stage4,
            "risk_off_forced": nasdaq_trend.stage4 and sp500_trend.stage4,
        },
    }


def write_regime_output(
    snapshot: dict[str, Any],
    as_of: date,
    results_dir: str | Path = DEFAULT_RESULTS_DIR,
) -> Path:
    """Write the Market Regime JSON output."""

    directory = Path(results_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"regime-{as_of.isoformat()}.json"
    payload = {"as_of": as_of.isoformat(), **snapshot}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def run_market_regime(
    universe_path: str | Path | None = None,
    base_path: str | Path | None = None,
    cache_path: str | Path = DEFAULT_CACHE_PATH,
    metadata_path: str | Path = DEFAULT_METADATA_PATH,
    results_dir: str | Path = DEFAULT_RESULTS_DIR,
    previous_state: str | None = None,
    as_of: date | None = None,
) -> tuple[dict[str, Any], Path]:
    """Load existing Base/Cache artifacts and write the Regime JSON."""

    universe = _load_universe(universe_path)
    base_ranking = _load_base(base_path)
    prices = pd.read_parquet(cache_path)
    metadata = _load_metadata(metadata_path)
    snapshot = calculate_regime_snapshot(
        universe,
        base_ranking,
        prices,
        metadata.get("benchmark_sources", {}),
        previous_state=previous_state,
    )
    output_date = as_of or measurement_date()
    return snapshot, write_regime_output(snapshot, output_date, results_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Calculate US Trend Pick Market Regime")
    parser.add_argument(
        "--previous-state",
        choices=[RegimeState.RISK_ON, RegimeState.WARNING, RegimeState.RISK_OFF],
        default=None,
    )
    args = parser.parse_args()
    snapshot, output = run_market_regime(previous_state=args.previous_state)
    print(f"Market Regime Score: {snapshot['market_regime_score']}")
    print(f"Regime: {snapshot['regime']}")
    print(f"Data status: {snapshot['data_status']}")
    print(f"Component scores: {snapshot['component_scores']}")
    print(f"JSON: {output}")
    if snapshot["missing_reasons"]:
        print(f"Missing reasons: {snapshot['missing_reasons']}")


if __name__ == "__main__":
    main()
