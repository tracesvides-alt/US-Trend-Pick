"""Cross-sectional percentile scoring used by the ranking engine."""

from __future__ import annotations

import pandas as pd


def percentile_score(values: pd.Series) -> pd.Series:
    """Convert higher-is-better values to the specified 0-100 percentile.

    Ties receive their average descending rank. A one-item population is
    assigned 100 because the stated formula has an undefined denominator for
    N=1 and that item is necessarily the population leader.
    """

    numeric = pd.to_numeric(values, errors="coerce").astype(float)
    population = int(numeric.notna().sum())
    result = pd.Series(float("nan"), index=numeric.index, dtype="float64")
    if population == 0:
        return result
    ranks = numeric.rank(method="average", ascending=False)
    if population == 1:
        result.loc[numeric.notna()] = 100.0
        return result
    result = 100.0 * (population - ranks) / (population - 1)
    return result.where(numeric.notna())

