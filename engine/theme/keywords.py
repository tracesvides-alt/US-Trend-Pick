"""Theme vocabulary and source-priority weights for the auto classifier."""

from __future__ import annotations

from collections.abc import Mapping


# These are compatibility aliases for snapshots created before the Theme
# taxonomy was narrowed. They are never emitted by the current classifier.
LEGACY_THEME_ALIASES: dict[str, str] = {
    "Cloud / AI Infrastructure": "AI Cloud / Compute Infrastructure",
    "AI Server": "AI Server / Compute",
    "Data Center Power": "Data Center Power / Cooling",
    "Utilities": "Utilities / Grid",
    "Robotics": "Robotics / Automation",
    "Foundry / CPU": "Foundry / CPU / GPU",
}

# The old Cloud Theme was intentionally broad (for example, it included
# generic data-center demand language). Existing assignments under that name
# must be re-evaluated once against the narrowed classifier instead of being
# held by the normal two-snapshot stability rule.
LEGACY_RECLASSIFICATION_THEMES = frozenset({"Cloud / AI Infrastructure"})


# A domain-specific product or service term is intentionally much stronger
# than a broad demand/end-market term. Matching is case-insensitive and each
# term contributes at most once per source field.
THEME_KEYWORDS: dict[str, dict[str, float]] = {
    "AI Memory / HBM": {
        "hbm": 32,
        "high bandwidth memory": 34,
        "dram": 30,
        "dynamic random access memory": 32,
        "ai memory": 32,
        "memory chip": 26,
        "memory": 16,
        "nand": 8,
    },
    "NAND / Storage": {
        "nand": 34,
        "nand flash": 36,
        "flash memory": 34,
        "solid state": 30,
        "solid-state": 30,
        "ssd": 32,
        "storage": 24,
        "data storage": 28,
        "enterprise storage": 30,
    },
    "Optical / Photonics": {
        "optical communication": 36,
        "optical components": 36,
        "optical": 30,
        "photonics": 36,
        "laser": 32,
        "transceiver": 36,
        "coherent": 34,
        "wavelength": 32,
        "fiber optic": 32,
        "fiber optics": 32,
    },
    "AI Networking": {
        "networking silicon": 38,
        "data center interconnect": 38,
        "serdes": 40,
        "ethernet": 30,
        "network switch": 34,
        "switching": 30,
        "interconnect": 32,
        "connectivity": 20,
        "dsp": 24,
        "networking": 12,
    },
    "ASIC / Custom Silicon": {
        "custom silicon": 38,
        "application-specific integrated circuit": 38,
        "application-specific": 32,
        "custom chip": 36,
        "asic": 40,
        "accelerator chip": 34,
        "accelerator": 24,
    },
    "AI Server / Compute": {
        "ai server": 36,
        "gpu server": 38,
        "rack-scale": 34,
        "compute platform": 24,
        "server systems": 28,
        "server": 18,
    },
    "Semiconductor Equipment": {
        "semiconductor equipment": 40,
        "semiconductor manufacturing equipment": 42,
        "wafer fabrication": 36,
        "wafer fab": 36,
        "lithography": 40,
        "deposition": 34,
        "etch": 34,
        "metrology": 34,
        "process control": 28,
        "inspection equipment": 34,
    },
    "Foundry / CPU / GPU": {
        "foundry": 38,
        "cpu": 34,
        "gpu chip": 36,
        "graphics processor": 36,
        "processor": 26,
        "microprocessor": 34,
        "semiconductor manufacturing": 24,
        "chip design": 28,
    },
    "Data Center Power / Cooling": {
        "data center power": 42,
        "power distribution": 38,
        "power management": 34,
        "ups": 38,
        "uninterruptible power": 38,
        "backup power": 34,
        "thermal management": 38,
        "liquid cooling": 40,
        "cooling systems": 36,
        "cooling": 28,
        "switchgear": 34,
    },
    "AI Cloud / Compute Infrastructure": {
        # These combinations describe a company selling compute capacity,
        # not a company merely selling a product into an AI data center.
        "gpu cloud": 46,
        "ai compute": 46,
        "gpu infrastructure": 44,
        "compute capacity": 46,
        "gpu-as-a-service": 48,
        "gpu as a service": 48,
        "ai cloud platform": 48,
        "hyperscale ai compute infrastructure": 50,
        "ai cloud infrastructure": 44,
        "cloud compute": 40,
        "bare metal gpu": 44,
        "compute infrastructure": 1,
        "cloud computing": 1,
        # Generic demand terms are deliberately weak and cannot establish
        # classification without domain-specific evidence.
        "artificial intelligence": 1,
        "ai": 1,
        "cloud": 1,
        "data center": 1,
        "infrastructure": 1,
        "platform": 1,
    },
    "Cybersecurity": {
        "cybersecurity": 42,
        "cyber security": 42,
        "endpoint security": 44,
        "threat detection": 40,
        "identity protection": 38,
        "identity security": 38,
        "security operations": 42,
        "zero trust": 38,
        "threat intelligence": 40,
        "security software": 30,
    },
    "Enterprise Software / AI Software": {
        "enterprise software": 28,
        "business software": 26,
        "software as a service": 28,
        "saas": 24,
        "workflow automation": 28,
        "developer tools": 24,
        "ai software": 30,
        "machine learning software": 30,
        "data analytics software": 26,
        "machine learning platform": 26,
        "software": 12,
        "digital transformation": 1,
        "artificial intelligence": 1,
        "ai": 1,
        "platform": 1,
    },
    "Nuclear": {
        "nuclear power": 42,
        "nuclear": 38,
        "uranium": 42,
        "reactor": 38,
        "small modular reactor": 44,
    },
    "Utilities / Grid": {
        "electric utility": 38,
        "regulated utility": 36,
        "electric grid": 36,
        "power grid": 34,
        "grid infrastructure": 32,
        "power generation": 26,
        "utilities": 28,
        "utility": 28,
    },
    "Energy": {
        "oil": 30,
        "natural gas": 34,
        "crude": 30,
        "petroleum": 30,
        "refining": 32,
        "oil & gas": 36,
        "energy": 14,
    },
    "Financials": {
        "bank": 30,
        "banking": 30,
        "insurance": 30,
        "asset management": 30,
        "financial services": 28,
        "brokerage": 30,
    },
    "FinTech": {
        "fintech": 40,
        "digital payments": 40,
        "payments platform": 38,
        "online lending": 36,
        "financial technology": 40,
        "mobile payments": 38,
    },
    "Robotics / Automation": {
        "robotics": 40,
        "robot": 34,
        "industrial automation": 38,
        "factory automation": 38,
        "autonomous system": 36,
        "automation": 26,
    },
    "Defense": {
        "aerospace and defense": 42,
        "aerospace & defense": 42,
        "defense systems": 40,
        "defense": 34,
        "defence": 34,
        "military": 34,
        "missile": 42,
    },
    "Space": {
        "launch vehicle": 44,
        "spacecraft": 44,
        "satellite": 36,
        "orbital": 34,
        "space": 26,
    },
    "Biotechnology": {
        "gene therapy": 42,
        "biopharmaceutical": 40,
        "biotechnology": 40,
        "biotech": 38,
        "genomics": 38,
    },
    "Healthcare": {
        "medical device": 38,
        "healthcare services": 34,
        "pharmaceutical": 34,
        "diagnostics": 34,
        "health services": 32,
        "healthcare": 22,
    },
    "Consumer Staples": {
        "consumer staples": 38,
        "household products": 36,
        "personal care": 34,
        "beverages": 30,
        "food products": 30,
    },
    "Consumer Discretionary": {
        "consumer discretionary": 38,
        "e-commerce": 34,
        "automotive": 34,
        "restaurants": 34,
        "retail": 24,
    },
    "Travel": {
        "travel": 38,
        "airline": 38,
        "hotel": 38,
        "hospitality": 36,
        "cruise": 38,
        "booking": 34,
    },
    "Crypto Infrastructure": {
        "cryptocurrency": 42,
        "crypto exchange": 44,
        "digital asset": 40,
        "blockchain": 34,
        "bitcoin": 34,
        "crypto": 28,
    },
    "Other": {},
}


# Industry and sector are fallback evidence. Generic Technology and Software
# labels intentionally do not grant Cloud / Compute points.
SECTOR_THEME_WEIGHTS: dict[str, dict[str, float]] = {
    "technology": {"Enterprise Software / AI Software": 1},
    "financial services": {"Financials": 12, "FinTech": 2},
    "energy": {"Energy": 12, "Nuclear": 3},
    "utilities": {"Utilities / Grid": 14, "Nuclear": 2},
    "healthcare": {"Healthcare": 12, "Biotechnology": 5},
    "consumer defensive": {"Consumer Staples": 14},
    "consumer cyclical": {"Consumer Discretionary": 12, "Travel": 3},
    "industrials": {"Robotics / Automation": 2, "Defense": 2},
    "communication services": {"Enterprise Software / AI Software": 1},
}


INDUSTRY_THEME_WEIGHTS: dict[str, dict[str, float]] = {
    "semiconductors": {
        "AI Memory / HBM": 2,
        "AI Networking": 2,
        "ASIC / Custom Silicon": 2,
        "Foundry / CPU / GPU": 2,
    },
    "memory chips": {"AI Memory / HBM": 12},
    "data storage": {"NAND / Storage": 12},
    "communication equipment": {
        "Optical / Photonics": 5,
        "AI Networking": 5,
    },
    "electronic components": {
        "Optical / Photonics": 4,
        "Data Center Power / Cooling": 3,
    },
    "semiconductor equipment & materials": {"Semiconductor Equipment": 14},
    "semiconductor equipment": {"Semiconductor Equipment": 14},
    "software - infrastructure": {"Enterprise Software / AI Software": 6, "Cybersecurity": 2},
    "software - application": {"Enterprise Software / AI Software": 8},
    "cloud computing": {"AI Cloud / Compute Infrastructure": 10},
    "security software": {"Cybersecurity": 14},
    "cybersecurity": {"Cybersecurity": 14},
    "information technology services": {"Enterprise Software / AI Software": 5},
    "electrical equipment & parts": {"Data Center Power / Cooling": 5},
    "specialty industrial machinery": {
        "Data Center Power / Cooling": 3,
        "Robotics / Automation": 3,
    },
    "banks - diversified": {"Financials": 14},
    "banks - regional": {"Financials": 14},
    "oil & gas integrated": {"Energy": 14},
    "oil & gas e&p": {"Energy": 14},
    "utilities - regulated electric": {"Utilities / Grid": 14},
    "utilities - diversified": {"Utilities / Grid": 14},
    "biotechnology": {"Biotechnology": 14},
    "medical devices": {"Healthcare": 14},
    "aerospace & defense": {"Defense": 14, "Space": 3},
    "travel services": {"Travel": 14},
    "capital markets": {"Financials": 10, "FinTech": 2},
}


# These terms describe a broad end market and must not establish a Theme by
# themselves. Domain-specific phrases remain decisive.
GENERIC_KEYWORDS = frozenset(
    {
        "ai",
        "artificial intelligence",
        "cloud",
        "cloud computing",
        "compute infrastructure",
        "data center",
        "infrastructure",
        "digital transformation",
        "platform",
    }
)


SOURCE_WEIGHTS: Mapping[str, float] = {
    "product_service": 10.0,
    "industry": 8.0,
    "business_summary": 4.0,
    "sector": 2.0,
    "end_market": 1.0,
    "company_name": 1.0,
}


def canonical_theme_name(value: str | None) -> str | None:
    """Canonicalize a historical Theme name without creating new names."""

    if value is None:
        return None
    return LEGACY_THEME_ALIASES.get(value, value)


def all_keyword_themes() -> set[str]:
    """Return every current Theme referenced by classifier dictionaries."""

    names = set(THEME_KEYWORDS)
    for mapping in (SECTOR_THEME_WEIGHTS, INDUSTRY_THEME_WEIGHTS):
        for values in mapping.values():
            names.update(values)
    return names
