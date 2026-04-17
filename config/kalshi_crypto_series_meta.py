"""
Canonical Kalshi crypto series metadata (single source of truth).

Resolves audit finding 1.1: hourly tickers must match Kalshi (KXBTC not KXBTCH1)
across crypto_spot_kalshi_config, kalshi_universe, and market inference.

Verification: scripts/verify_kalshi_series_meta.py (optional CI) against Series API.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Literal, Optional, Tuple


class AssetSymbol(str, Enum):
    """Canonical crypto asset symbols for Kalshi markets."""
    BTC = "BTC"
    ETH = "ETH"
    SOL = "SOL"
    XRP = "XRP"
    DOGE = "DOGE"


TimeframeKey = Literal["15m", "1h", "daily", "weekly", "monthly", "annual"]


@dataclass(frozen=True)
class SeriesMeta:
    """One traded crypto series on Kalshi."""

    asset: str  # Asset symbol (BTC, ETH, SOL, XRP, DOGE)
    timeframe: TimeframeKey
    series_ticker: str
    expected_api_frequency: str
    settlement_source_hint: str
    category: str = "crypto"
    supports_basis: bool = True
    supports_trend: bool = True


# Hourly = bare ticker (KXBTC), per kalshi.com / internal universe — not KXBTCH1.
SERIES_META_LIST: Tuple[SeriesMeta, ...] = (
    SeriesMeta("BTC", "15m", "KXBTC15M", "15m", "cfb_rti_btc"),
    SeriesMeta("BTC", "1h", "KXBTC", "hourly", "cfb_rti_btc"),
    SeriesMeta("BTC", "daily", "KXBTCD1", "daily", "cfb_rti_btc"),
    SeriesMeta("BTC", "weekly", "KXBTCW1", "weekly", "cfb_rti_btc"),
    SeriesMeta("ETH", "15m", "KXETH15M", "15m", "cfb_rti_eth"),
    SeriesMeta("ETH", "1h", "KXETH", "hourly", "cfb_rti_eth"),
    SeriesMeta("ETH", "daily", "KXETHD1", "daily", "cfb_rti_eth"),
    SeriesMeta("ETH", "weekly", "KXETHW1", "weekly", "cfb_rti_eth"),
    SeriesMeta("SOL", "15m", "KXSOL15M", "15m", "cfb_rti_sol"),
    SeriesMeta("SOL", "1h", "KXSOL", "hourly", "cfb_rti_sol"),
    SeriesMeta("SOL", "daily", "KXSOLD1", "daily", "cfb_rti_sol"),
    SeriesMeta("SOL", "weekly", "KXSOLW1", "weekly", "cfb_rti_sol"),
    SeriesMeta("XRP", "15m", "KXXRP15M", "15m", "cfb_rti_xrp"),
    SeriesMeta("XRP", "1h", "KXXRP", "hourly", "cfb_rti_xrp"),
    SeriesMeta("XRP", "daily", "KXXRPD1", "daily", "cfb_rti_xrp"),
    SeriesMeta("XRP", "weekly", "KXXRPW1", "weekly", "cfb_rti_xrp"),
    SeriesMeta("DOGE", "15m", "KXDOGE15M", "15m", "cfb_rti_doge"),
    SeriesMeta("DOGE", "1h", "KXDOGE", "hourly", "cfb_rti_doge"),
    SeriesMeta("DOGE", "daily", "KXDOGED1", "daily", "cfb_rti_doge"),
    SeriesMeta("DOGE", "weekly", "KXDOGEW1", "weekly", "cfb_rti_doge"),
    SeriesMeta("BTC", "monthly", "KXBTC1M", "monthly", "cfb_rti_btc"),
    SeriesMeta("ETH", "monthly", "KXETH1M", "monthly", "cfb_rti_eth"),
    SeriesMeta("SOL", "monthly", "KXSOL1M", "monthly", "cfb_rti_sol"),
    SeriesMeta("XRP", "monthly", "KXXRP1M", "monthly", "cfb_rti_xrp"),
    SeriesMeta("DOGE", "monthly", "KXDOGE1M", "monthly", "cfb_rti_doge"),
    SeriesMeta("BTC", "annual", "KXBTCY", "annual", "cfb_rti_btc"),
    SeriesMeta("ETH", "annual", "KXETHY", "annual", "cfb_rti_eth"),
    SeriesMeta("SOL", "annual", "KXSOLY", "annual", "cfb_rti_sol"),
    SeriesMeta("XRP", "annual", "KXXRPY", "annual", "cfb_rti_xrp"),
    SeriesMeta("DOGE", "annual", "KXDOGEY", "annual", "cfb_rti_doge"),
)

SERIES_META_BY_KEY: Dict[Tuple[str, TimeframeKey], SeriesMeta] = {
    (str(m.asset), m.timeframe): m for m in SERIES_META_LIST
}

SERIES_META_BY_TICKER: Dict[str, SeriesMeta] = {
    m.series_ticker.upper(): m for m in SERIES_META_LIST
}


def get_series_meta(asset: str | AssetSymbol, timeframe: TimeframeKey) -> Optional[SeriesMeta]:
    asset_str = asset.value if isinstance(asset, AssetSymbol) else str(asset)
    return SERIES_META_BY_KEY.get((asset_str.upper(), timeframe))


def resolve_series_ticker_from_meta(asset: str | AssetSymbol, timeframe: TimeframeKey) -> Optional[str]:
    m = get_series_meta(asset, timeframe)
    return m.series_ticker if m else None


def build_kalshi_crypto_products() -> Dict[str, List[str]]:
    """Shape expected by config.kalshi_universe.KALSHI_CRYPTO_PRODUCTS.

    Includes all timeframes (15m, 1h, daily, weekly, monthly, annual) so that all
    crypto series are discoverable by the WS bridge and trading agents.
    """
    out: Dict[str, List[str]] = {}
    for m in SERIES_META_LIST:
        if m.timeframe == "15m":
            key = f"{m.asset}_15M"
        elif m.timeframe == "1h":
            key = f"{m.asset}_1H"
        elif m.timeframe == "daily":
            key = f"{m.asset}_DAILY"
        elif m.timeframe == "weekly":
            key = f"{m.asset}_WEEKLY"
        elif m.timeframe == "monthly":
            key = f"{m.asset}_MONTHLY"
        elif m.timeframe == "annual":
            key = f"{m.asset}_ANNUAL"
        else:
            continue
        out.setdefault(key, []).append(m.series_ticker)
    return out


def all_series_tickers() -> List[str]:
    return [m.series_ticker for m in SERIES_META_LIST]


def infer_asset_timeframe_from_ticker(series_ticker: str) -> Tuple[str, str]:
    """Map exact series ticker to (asset, timeframe) or ("UNK", "UNK")."""
    if not series_ticker:
        return "UNK", "UNK"
    cleaned = series_ticker.strip().upper()
    meta = SERIES_META_BY_TICKER.get(cleaned)
    if meta:
        return str(meta.asset), meta.timeframe
    return "UNK", "UNK"


def canonical_timeframe_from_series_ticker(series_ticker: str) -> Optional[str]:
    """Single source for catalog/UI: map Kalshi ``series_ticker`` → ``15m``/``1h``/``daily``/…

    Order: exact ``SERIES_META_BY_TICKER`` match, then dashed UPDOWN suffixes, then
    compact legacy suffixes (incl. ``H1`` hour style seen in older docs).
    """
    if not series_ticker:
        return None
    upper = series_ticker.strip().upper()
    meta = SERIES_META_BY_TICKER.get(upper)
    if meta:
        return meta.timeframe

    if "-" in upper:
        suffix = upper.split("-")[-1]
        if suffix == "15M":
            return "15m"
        if suffix in ("1H", "H1"):
            return "1h"
        if suffix in ("1D", "D1"):
            return "daily"
        if suffix in ("1W", "W1"):
            return "weekly"
        if suffix in ("1MO", "M1"):
            return "monthly"

    if upper.endswith("15M"):
        return "15m"
    if upper.endswith("H1"):
        return "1h"
    if upper.endswith("D1"):
        return "daily"
    if upper.endswith("W1"):
        return "weekly"
    if upper.endswith("M1"):
        return "monthly"
    return None


def list_assets_for_canonical_timeframe(tf: TimeframeKey) -> List[str]:
    """Assets that have a row in ``SERIES_META_LIST`` for this timeframe (e.g. all 15m cryptos)."""
    return sorted({str(m.asset) for m in SERIES_META_LIST if m.timeframe == tf})


CRYPTO_LANE_15M_SYMBOLS: Tuple[str, ...] = tuple(list_assets_for_canonical_timeframe("15m"))

_SERIES_PREFIXES_RT_SORTED: Tuple[str, ...] = tuple(
    sorted({m.series_ticker.upper() for m in SERIES_META_LIST}, key=len, reverse=True)
)


def infer_asset_from_kalshi_market_ticker(ticker: str) -> Optional[str]:
    """Map a full market ticker (e.g. KXBTC15M-...) to asset using series prefix."""
    if not ticker:
        return None
    u = ticker.strip().upper()
    for prefix in _SERIES_PREFIXES_RT_SORTED:
        if u.startswith(prefix):
            meta = SERIES_META_BY_TICKER.get(prefix)
            return str(meta.asset) if meta else None
    return None


# RTI-settled series prefixes (15m and 1h only)
_RTI_SERIES_PREFIXES: Tuple[str, ...] = tuple(
    sorted({m.series_ticker.upper() for m in SERIES_META_LIST if m.timeframe in ("15m", "1h")}, key=len, reverse=True)
)


def is_rti_settled_kalshi_crypto_ticker(ticker: str) -> bool:
    """True if ticker belongs to a Kalshi crypto series that settles on CFB RTI.
    
    Only 15m and 1h timeframes use RTI (Real-Time Index) settlement.
    Daily, weekly, monthly timeframes use reference rate settlement.
    """
    if not ticker:
        return False
    u = ticker.strip().upper()
    for prefix in _RTI_SERIES_PREFIXES:
        if u.startswith(prefix):
            # Ensure we don't match daily/weekly/monthly variants that share prefix
            # e.g., "KXBTC" should match "KXBTC-..." but not "KXBTCD1" (daily)
            next_char = u[len(prefix)] if len(u) > len(prefix) else ''
            # If next char is a letter (A-Z), it's likely a daily/weekly variant
            # e.g., KXBTCD1, KXBTCW1, KXBTCM1
            if next_char.isalpha():
                continue  # Skip - this is daily/weekly/monthly, not RTI
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════════
# Runtime Guard — Fail fast if enum reintroduced into SeriesMeta
# ═══════════════════════════════════════════════════════════════════════════

for _guard_m in SERIES_META_BY_KEY.values():
    assert isinstance(_guard_m.asset, str), (
        f"SeriesMeta.asset must be str, got {type(_guard_m.asset)}. "
        f"Do not use AssetSymbol enum in SeriesMeta — use plain strings."
    )
    assert _guard_m.asset.isupper(), (
        f"SeriesMeta.asset must be uppercase, got {_guard_m.asset!r}"
    )
