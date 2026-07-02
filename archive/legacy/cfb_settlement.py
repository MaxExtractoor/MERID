"""CF Benchmarks settlement methodology for Kalshi crypto markets.

Codifies the TWAP partitioned-median settlement approach used by CF Benchmarks
to produce reference prices for Kalshi crypto contracts.  Provides structured
settlement parameters per asset and timeframe so the trading system can:

  - Know the settlement window for each product
  - Adjust trading behaviour near settlement (e.g. reduce-only)
  - Tag markets with their settlement source for observability
  - Validate that market resolution aligns with expected CFB methodology

Settlement methodology (docs.cfbenchmarks.com)
----------------------------------------------
1. **Relevant transactions**: CF ingests all spot trades for a given crypto pair
   on pre-qualified Constituent exchanges during a defined TWAP window.

2. **Partitioned medians**: The TWAP window is split into equal time bins; each
   bin produces a volume-weighted median price across all eligible exchanges —
   more robust than simple VWAP against outliers.

3. **Final settlement price**: Equally weighted average of per-bin
   volume-weighted medians → single transparent daily reference.

4. **Outlier detection**: Per-bin, any exchange deviating beyond tolerance from
   the cross-exchange median is excluded for that bin.

5. **Fallback**: If all exchanges flagged or data missing, prior-day published
   price is used (with a marker) and the failure is reported.

RTI-based products (Kalshi 15m/hourly)
--------------------------------------
CF applies a similar time-weighted average to its Real-Time Index (RTI) over a
short window before settlement time, producing Options Settlement Rates aligned
with EU BMR and CFTC-style rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple

# ── Settlement source identifiers ────────────────────────────────────────────

CFB_INDEX_BY_ASSET: Dict[str, str] = {
    "BTC": "BRTI",           # Bitcoin Real-Time Index
    "ETH": "ETHUSD_RTI",     # Ethereum Real-Time Index
    "SOL": "SOLUSD_RTI",     # Solana Real-Time Index
    "XRP": "XRPUSD_RTI",     # XRP Real-Time Index
    "DOGE": "DOGEUSD_RTI",   # Dogecoin Real-Time Index
}

# Reference rates (daily settlement — distinct from intraday RTI)
CFB_REFERENCE_RATE_BY_ASSET: Dict[str, str] = {
    "BTC": "BRR",            # Bitcoin Reference Rate
    "ETH": "ETHUSD_RR",
    "SOL": "SOLUSD_RR",
    "XRP": "XRPUSD_RR",
    "DOGE": "DOGEUSD_RR",
}


# ── Settlement window parameters ─────────────────────────────────────────────

@dataclass(frozen=True)
class CFBSettlementParams:
    """Settlement parameters for one (asset, timeframe) combination.

    Attributes
    ----------
    asset : str
        Crypto asset symbol (BTC, ETH, SOL, XRP, DOGE).
    timeframe : str
        Kalshi market timeframe (15m, 1h, daily, weekly).
    cfb_index : str
        CF Benchmarks index used for settlement (e.g. BRTI, ETHUSD_RTI).
    settlement_type : str
        'rti_twap' for intraday (15m/1h), 'reference_rate' for daily/weekly.
    twap_window_seconds : int
        Duration of the TWAP window in seconds before settlement time.
    twap_bins : int
        Number of equal time bins the TWAP window is partitioned into.
    bin_duration_seconds : int
        Duration of each bin (twap_window_seconds / twap_bins).
    outlier_tolerance_pct : float
        Per-bin exchange deviation tolerance (percentage) beyond which an
        exchange's trades are excluded from that bin's median.
    settlement_guard_seconds : int
        How many seconds before expiry the system should restrict new buys
        (aligned with settlement_execution_guard.py).
    constituent_exchanges : tuple
        Pre-qualified exchanges used by CF Benchmarks for this asset.
    """
    asset: str
    timeframe: str
    cfb_index: str
    settlement_type: Literal["rti_twap", "reference_rate"]
    twap_window_seconds: int
    twap_bins: int
    bin_duration_seconds: int = 0  # computed in __post_init__
    outlier_tolerance_pct: float = 5.0
    settlement_guard_seconds: int = 60
    constituent_exchanges: Tuple[str, ...] = (
        "coinbase", "bitstamp", "kraken", "itbit", "gemini", "lmax",
    )

    def __post_init__(self) -> None:
        if self.twap_bins > 0:
            object.__setattr__(
                self, "bin_duration_seconds",
                self.twap_window_seconds // self.twap_bins,
            )


# ── Per-timeframe settlement guard defaults ───────────────────────────
# P0-003: Timeframe-specific settlement guards aligned with Kalshi/CF methodology.
# Per Kalshi docs: crypto contracts settle using 60 seconds of CFB RTI observations
# at expiry. The settlement guard ensures we are not trading inside the last N
# seconds of that window.
#
# Source of truth: https://help.kalshi.com/en/articles/13823838-crypto-markets
# CF Benchmarks methodology: https://www.cfbenchmarks.com/
_SETTLEMENT_GUARD_BY_TIMEFRAME: Dict[str, int] = {
    "15m": 30,      # Tight guard for short-dated contracts
    "1h": 60,       # Standard guard for hourly
    "daily": 300,   # 5 min guard for daily (longer settlement window)
    "weekly": 300,  # 5 min guard for weekly
    "monthly": 300, # 5 min guard for monthly
    "annual": 300,  # 5 min guard for annual
}


def _get_settlement_guard_seconds(timeframe: str) -> int:
    """Return settlement guard seconds for a timeframe.

    P0-003: Per-timeframe settlement guard lookup with conservative defaults.
    """
    return _SETTLEMENT_GUARD_BY_TIMEFRAME.get(timeframe.lower(), 60)


# ── Per-asset, per-timeframe settlement configurations ───────────────────────
# Parameters are based on CF Benchmarks published methodology docs.
# Note: Kalshi's crypto contracts use 60 seconds of RTI observations at expiry
# (per Kalshi help docs), not the generalized 300s/1800s TWAP windows below.
# The TWAP parameters here are for MERID's internal modeling only.
#
# Source of truth for settlement: Kalshi help center + CF Benchmarks documentation.
# This implementation must remain aligned with those external sources.

def _make_settlement_params(asset: str, timeframe: str, cfb_index: str,
                            settlement_type: str, twap_window: int, twap_bins: int) -> CFBSettlementParams:
    """Factory with per-timeframe settlement guard (P0-003)."""
    return CFBSettlementParams(
        asset=asset,
        timeframe=timeframe,
        cfb_index=cfb_index,
        settlement_type=settlement_type,  # type: ignore[arg-type]
        twap_window_seconds=twap_window,
        twap_bins=twap_bins,
        settlement_guard_seconds=_get_settlement_guard_seconds(timeframe),
    )


_SETTLEMENT_PARAMS: List[CFBSettlementParams] = [
    # ── BTC ──
    _make_settlement_params("BTC", "15m",    "BRTI",        "rti_twap",        300,   5),
    _make_settlement_params("BTC", "1h",     "BRTI",        "rti_twap",        300,   5),
    _make_settlement_params("BTC", "daily",  "BRR",         "reference_rate", 1800,  12),
    _make_settlement_params("BTC", "weekly", "BRR",         "reference_rate", 1800,  12),
    # ── ETH ──
    _make_settlement_params("ETH", "15m",    "ETHUSD_RTI",  "rti_twap",        300,   5),
    _make_settlement_params("ETH", "1h",     "ETHUSD_RTI",  "rti_twap",        300,   5),
    _make_settlement_params("ETH", "daily",  "ETHUSD_RR",   "reference_rate", 1800,  12),
    _make_settlement_params("ETH", "weekly", "ETHUSD_RR",   "reference_rate", 1800,  12),
    # ── SOL ──
    _make_settlement_params("SOL", "15m",    "SOLUSD_RTI",  "rti_twap",        300,   5),
    _make_settlement_params("SOL", "1h",     "SOLUSD_RTI",  "rti_twap",        300,   5),
    _make_settlement_params("SOL", "daily",  "SOLUSD_RR",   "reference_rate", 1800,  12),
    _make_settlement_params("SOL", "weekly", "SOLUSD_RR",   "reference_rate", 1800,  12),
    # ── XRP ──
    _make_settlement_params("XRP", "15m",    "XRPUSD_RTI",  "rti_twap",        300,   5),
    _make_settlement_params("XRP", "1h",     "XRPUSD_RTI",  "rti_twap",        300,   5),
    _make_settlement_params("XRP", "daily",  "XRPUSD_RR",   "reference_rate", 1800,  12),
    _make_settlement_params("XRP", "weekly", "XRPUSD_RR",   "reference_rate", 1800,  12),
    # ── DOGE ──
    _make_settlement_params("DOGE", "15m",   "DOGEUSD_RTI", "rti_twap",        300,   5),
    _make_settlement_params("DOGE", "1h",    "DOGEUSD_RTI", "rti_twap",        300,   5),
    _make_settlement_params("DOGE", "daily", "DOGEUSD_RR",  "reference_rate", 1800,  12),
    _make_settlement_params("DOGE", "weekly","DOGEUSD_RR",  "reference_rate", 1800,  12),
]

# Indexed lookups
SETTLEMENT_BY_KEY: Dict[Tuple[str, str], CFBSettlementParams] = {
    (p.asset, p.timeframe): p for p in _SETTLEMENT_PARAMS
}

SETTLEMENT_BY_ASSET: Dict[str, List[CFBSettlementParams]] = {}
for _p in _SETTLEMENT_PARAMS:
    SETTLEMENT_BY_ASSET.setdefault(_p.asset, []).append(_p)


# ── Public API ────────────────────────────────────────────────────────────────

def get_settlement_params(asset: str, timeframe: str) -> Optional[CFBSettlementParams]:
    """Look up CF Benchmarks settlement parameters for an (asset, timeframe).

    Returns None if no settlement config exists (e.g. non-crypto or unknown
    timeframe like 'monthly' before Kalshi launches monthly crypto).
    """
    return SETTLEMENT_BY_KEY.get((asset.upper(), timeframe))


def get_settlement_guard_seconds(asset: str, timeframe: str) -> int:
    """Return the number of seconds before expiry to restrict new buys.

    P0-003: Uses per-timeframe settlement guard lookup. Falls back to 60s if
    no specific params are found.

    Per Kalshi docs: crypto contracts settle using 60 seconds of CFB RTI
    observations at expiry. This guard ensures we are not trading inside the
    last N seconds of that window.
    """
    p = get_settlement_params(asset, timeframe)
    if p:
        return p.settlement_guard_seconds
    # P0-003: Use per-timeframe default even when no full settlement params exist
    return _get_settlement_guard_seconds(timeframe)


def get_cfb_index(asset: str) -> Optional[str]:
    """Return the CF Benchmarks RTI index name for an asset."""
    return CFB_INDEX_BY_ASSET.get(asset.upper())


def get_cfb_reference_rate(asset: str) -> Optional[str]:
    """Return the CF Benchmarks Reference Rate name for an asset."""
    return CFB_REFERENCE_RATE_BY_ASSET.get(asset.upper())


def is_rti_settlement_type(asset: str, timeframe: str) -> bool:
    """True if (asset, timeframe) uses RTI-based TWAP settlement (intraday)."""
    p = get_settlement_params(asset, timeframe)
    return p is not None and p.settlement_type == "rti_twap"


def all_settlement_params() -> List[CFBSettlementParams]:
    """Return all configured settlement parameters."""
    return list(_SETTLEMENT_PARAMS)


def supported_assets() -> List[str]:
    """Return assets with CFB settlement configuration."""
    return sorted(SETTLEMENT_BY_ASSET.keys())


def supported_timeframes_for_asset(asset: str) -> List[str]:
    """Return timeframes with CFB settlement config for a given asset."""
    params = SETTLEMENT_BY_ASSET.get(asset.upper(), [])
    return [p.timeframe for p in params]
