"""Configurable Theme keyword, sector, and industry weights."""

from __future__ import annotations

from collections.abc import Mapping


# Keyword weights are intentionally data-only so they can be tuned without
# changing the classifier algorithm. Matching is case-insensitive substring
# matching and each term contributes at most once per source field.
THEME_KEYWORDS: dict[str, dict[str, float]] = {
    "AI Memory / HBM": {
        "hbm": 10,
        "high bandwidth memory": 10,
        "dram": 8,
        "memory": 7,
        "ai memory": 10,
        "nand": 6,
    },
    "NAND / Storage": {
        "nand": 10,
        "flash memory": 9,
        "solid state": 9,
        "ssd": 9,
        "storage": 8,
        "data storage": 8,
    },
    "Optical / Photonics": {
        "optical": 9,
        "photonics": 10,
        "laser": 8,
        "transceiver": 10,
        "optical communication": 10,
        "fiber optic": 9,
    },
    "AI Networking": {
        "networking": 8,
        "ethernet": 9,
        "serdes": 10,
        "connectivity": 7,
        "switching": 8,
        "data center interconnect": 10,
        "network switch": 9,
    },
    "ASIC / Custom Silicon": {
        "asic": 10,
        "custom silicon": 10,
        "accelerator": 9,
        "custom chip": 10,
        "application-specific": 9,
    },
    "AI Server": {
        "ai server": 10,
        "server": 7,
        "rack-scale": 9,
        "compute platform": 8,
        "gpu server": 10,
    },
    "Semiconductor Equipment": {
        "semiconductor equipment": 10,
        "semiconductor manufacturing equipment": 10,
        "wafer fabrication": 9,
        "lithography": 10,
        "deposition": 8,
        "etch": 8,
        "metrology": 8,
    },
    "Foundry / CPU": {
        "foundry": 10,
        "cpu": 9,
        "processor": 8,
        "microprocessor": 9,
        "semiconductor manufacturing": 8,
    },
    "Data Center Power": {
        "data center power": 10,
        "ups": 8,
        "power management": 9,
        "cooling": 8,
        "thermal management": 9,
        "power distribution": 8,
    },
    "Cloud / AI Infrastructure": {
        "cloud": 7,
        "cloud computing": 10,
        "ai infrastructure": 10,
        "data center": 8,
        "infrastructure software": 8,
        "machine learning platform": 9,
    },
    "Nuclear": {
        "nuclear": 10,
        "uranium": 10,
        "reactor": 9,
        "nuclear power": 10,
    },
    "Utilities": {
        "utility": 8,
        "utilities": 8,
        "electric utility": 10,
        "regulated utility": 9,
        "power generation": 7,
    },
    "Energy": {
        "oil": 8,
        "natural gas": 9,
        "crude": 8,
        "petroleum": 8,
        "refining": 8,
        "energy": 6,
    },
    "Financials": {
        "bank": 8,
        "banking": 8,
        "insurance": 8,
        "asset management": 8,
        "financial services": 8,
        "brokerage": 8,
    },
    "FinTech": {
        "fintech": 10,
        "digital payments": 10,
        "payments platform": 9,
        "online lending": 9,
        "financial technology": 10,
    },
    "Cybersecurity": {
        "cybersecurity": 10,
        "cyber security": 10,
        "endpoint security": 9,
        "threat detection": 9,
        "identity security": 9,
        "security software": 8,
    },
    "Robotics": {
        "robotics": 10,
        "robot": 9,
        "automation": 8,
        "autonomous system": 9,
        "industrial automation": 9,
    },
    "Defense": {
        "defense": 9,
        "defence": 9,
        "military": 9,
        "aerospace and defense": 10,
        "missile": 10,
    },
    "Space": {
        "space": 9,
        "satellite": 9,
        "launch vehicle": 10,
        "orbital": 8,
        "spacecraft": 10,
    },
    "Biotechnology": {
        "biotech": 10,
        "biotechnology": 10,
        "gene therapy": 10,
        "genomics": 9,
        "biopharmaceutical": 9,
    },
    "Healthcare": {
        "healthcare": 8,
        "medical device": 9,
        "pharmaceutical": 8,
        "diagnostics": 8,
        "health services": 8,
    },
    "Consumer Staples": {
        "consumer staples": 10,
        "household products": 9,
        "beverages": 8,
        "food products": 8,
        "personal care": 8,
    },
    "Consumer Discretionary": {
        "consumer discretionary": 10,
        "retail": 7,
        "e-commerce": 8,
        "automotive": 8,
        "restaurants": 8,
    },
    "Travel": {
        "travel": 10,
        "airline": 9,
        "hotel": 9,
        "hospitality": 9,
        "cruise": 9,
        "booking": 8,
    },
    "Crypto Infrastructure": {
        "cryptocurrency": 10,
        "crypto": 10,
        "bitcoin": 10,
        "blockchain": 9,
        "digital asset": 9,
        "crypto exchange": 10,
    },
    "Other": {},
}


# Sector and industry weights provide explicit fallback evidence and are
# applied with higher source priority than a business-name match.
SECTOR_THEME_WEIGHTS: dict[str, dict[str, float]] = {
    "technology": {
        "Cloud / AI Infrastructure": 6,
        "AI Server": 5,
        "Cybersecurity": 5,
    },
    "financial services": {"Financials": 10, "FinTech": 4},
    "energy": {"Energy": 10, "Nuclear": 4},
    "utilities": {"Utilities": 10, "Nuclear": 4},
    "healthcare": {"Healthcare": 9, "Biotechnology": 5},
    "consumer defensive": {"Consumer Staples": 10},
    "consumer cyclical": {"Consumer Discretionary": 10, "Travel": 3},
    "industrials": {"Robotics": 4, "Defense": 4},
    "communication services": {"Cloud / AI Infrastructure": 4},
    "basic materials": {"Energy": 3},
    "real estate": {"Cloud / AI Infrastructure": 2},
}


INDUSTRY_THEME_WEIGHTS: dict[str, dict[str, float]] = {
    "semiconductors": {
        "AI Memory / HBM": 5,
        "AI Networking": 4,
        "ASIC / Custom Silicon": 4,
        "Foundry / CPU": 4,
    },
    "semiconductor equipment & materials": {"Semiconductor Equipment": 10},
    "semiconductor equipment": {"Semiconductor Equipment": 10},
    "software - infrastructure": {"Cloud / AI Infrastructure": 8, "Cybersecurity": 4},
    "software - application": {"Cloud / AI Infrastructure": 5, "Cybersecurity": 3},
    "banks - diversified": {"Financials": 10},
    "banks - regional": {"Financials": 10},
    "oil & gas integrated": {"Energy": 10},
    "oil & gas e&p": {"Energy": 10},
    "utilities - regulated electric": {"Utilities": 10},
    "biotechnology": {"Biotechnology": 10},
    "medical devices": {"Healthcare": 10},
    "aerospace & defense": {"Defense": 10, "Space": 4},
    "travel services": {"Travel": 10},
    "capital markets": {"Financials": 8, "FinTech": 3},
}


SOURCE_WEIGHTS: Mapping[str, float] = {
    "sector": 5.0,
    "industry": 4.0,
    "business_summary": 2.0,
    "company_name": 1.0,
}


def all_keyword_themes() -> set[str]:
    """Return every Theme referenced by the classifier dictionaries."""

    names = set(THEME_KEYWORDS)
    for mapping in (SECTOR_THEME_WEIGHTS, INDUSTRY_THEME_WEIGHTS):
        for values in mapping.values():
            names.update(values)
    return names
