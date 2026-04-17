"""
Crypto Spot ↔ Kalshi Configuration

Canonical mapping of crypto assets to spot feeds and Kalshi market series.
Provides clean data structures for building unified "crypto surface" across
spot prices and Kalshi contracts, with explicit "near spot" band selection.

This module ensures:
- Each crypto asset has a defined spot source (CoinbasePriceFeed)
- Each asset/timeframe combo maps to exactly one Kalshi series
- All agents reference the same spot→series mapping
- "Near spot" selection is consistent and auditable

Example usage::

    from config.crypto_spot_kalshi_config import (
        CRYPTO_CONFIG,
        NEAR_SPOT_CONFIG,
        CryptoSurfaceEntry,
        KalshiMarketView,
        build_crypto_surface,
        select_markets_near_spot,
    )
    
    # Create CoinbasePriceFeed for spot prices
    from merid.execution.executors.coinbase import CoinbasePriceFeed
    spot_feed = CoinbasePriceFeed()
    
    # Fetch spot prices
    spot_prices = {
        "BTC": {"price": await spot_feed.get_price("BTC-USD"), "ts": datetime.now()},
        ...
    }
    
    # Build surface with Kalshi markets
    surface = build_crypto_surface(spot_prices, kalshi_markets_by_series)
    
    for entry in surface:
        near_spot = select_markets_near_spot(entry)
        log_markets_near_spot(entry, near_spot)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
import logging

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 1. CANONICAL CRYPTO CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

CRYPTO_CONFIG: Dict[str, Dict[str, Any]] = {
    "BTC": {
        "spot_source": "coinbase_price",  # CoinbasePriceFeed (read-only, no trading)
        "series": {
            "15M": "KXBTC15M",     # 15-minute up/down contract
            "1H":  "KXBTC",         # Hourly level/range contract (canonical: KXBTC not KXBTCH1)
            "1D":  "KXBTCD1",       # Daily level/range contract
        },
    },
    "ETH": {
        "spot_source": "coinbase_price",  # CoinbasePriceFeed (read-only, no trading)
        "series": {
            "15M": "KXETH15M",
            "1H":  "KXETH",         # Canonical: KXETH not KXETHH1
            "1D":  "KXETHD1",
        },
    },
    "SOL": {
        "spot_source": "coinbase_price",  # CoinbasePriceFeed (read-only, no trading)
        "series": {
            "15M": "KXSOL15M",
            "1H":  "KXSOL",         # Canonical: KXSOL not KXSOLH1
            "1D":  "KXSOLD1",
        },
    },
    "XRP": {
        "spot_source": "coinbase_price",  # CoinbasePriceFeed (read-only, no trading)
        "series": {
            "15M": "KXXRP15M",
            "1H":  "KXXRP",         # Canonical: KXXRP not KXXRPH1
            "1D":  "KXXRPD1",
        },
    },
    "DOGE": {
        "spot_source": "coinbase_price",  # CoinbasePriceFeed (read-only, no trading)
        "series": {
            "15M": "KXDOGE15M",     # Now available - matches canonical universe
            "1H":  "KXDOGE",        # Canonical: KXDOGE not KXDOGEH1
            "1D":  "KXDOGED1",
        },
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# 2. NEAR-SPOT BAND CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

NEAR_SPOT_CONFIG: Dict[Tuple[str, str], Dict[str, Any]] = {
    # BTC bands: tighter for short-term contracts (scalping), wider for longer-term
    ("BTC", "15M"):  {"pct_band": 2.0,  "max_markets": 10},
    ("BTC", "1H"):   {"pct_band": 1.5,  "max_markets": 8},
    ("BTC", "1D"):   {"pct_band": 1.0,  "max_markets": 5},
    
    # ETH: slightly wider bands (higher vol than BTC)
    ("ETH", "15M"):  {"pct_band": 2.5,  "max_markets": 10},
    ("ETH", "1H"):   {"pct_band": 2.0,  "max_markets": 8},
    ("ETH", "1D"):   {"pct_band": 1.5,  "max_markets": 5},
    
    # SOL: higher volatility
    ("SOL", "15M"):  {"pct_band": 3.0,  "max_markets": 10},
    ("SOL", "1H"):   {"pct_band": 2.5,  "max_markets": 8},
    ("SOL", "1D"):   {"pct_band": 2.0,  "max_markets": 5},
    
    # XRP: high volatility, wider bands
    ("XRP", "15M"):  {"pct_band": 3.0,  "max_markets": 10},
    ("XRP", "1H"):   {"pct_band": 2.5,  "max_markets": 8},
    ("XRP", "1D"):   {"pct_band": 2.0,  "max_markets": 5},
    
    # DOGE: highest volatility, widest bands
    ("DOGE", "1H"):  {"pct_band": 5.0,  "max_markets": 12},
    ("DOGE", "1D"):  {"pct_band": 4.0,  "max_markets": 10},
}

# ─────────────────────────────────────────────────────────────────────────────
# 3. DATA STRUCTURES
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class KalshiMarketView:
    """
    Single Kalshi contract view for "crypto surface" layer.
    
    Bridges Kalshi's contract terms with spot price reference:
    - market_id: unique contract identifier from Kalshi
    - target_price: reference level/mid from contract definition
    - status: market lifecycle (open, closed, expired, etc.)
    - expires_at: contract expiration timestamp
    """
    market_id: str           # e.g. "KXBTC15M-20260321-70000"
    title: str              # e.g. "BTC Up or Down - 15 minutes"
    yes_price: float        # Current YES side price (probability)
    no_price: float         # Current NO side price (probability)
    target_price: float     # Implied price from contract terms (e.g. strike level)
    status: str             # "open" | "closed" | "expired" | "suspended"
    expires_at: datetime    # Market expiration time
    
    # Optional enrichment
    quantity_yes: Optional[int] = None  # Available YES contracts
    quantity_no: Optional[int] = None   # Available NO contracts
    
    def mid_price(self) -> float:
        """Return mid between YES and NO."""
        return (self.yes_price + self.no_price) / 2.0
    
    def distance_to_spot(self, spot: float) -> float:
        """Compute % distance from target_price to spot."""
        if self.target_price == 0:
            return 0.0
        return abs(self.target_price - spot) / self.target_price * 100.0


@dataclass
class CryptoSurfaceEntry:
    """
    Single "tile" on the crypto surface: one asset + timeframe combo.
    
    Contains:
    - Spot price from CoinbasePriceFeed (read-only, no trading)
    - All open Kalshi markets for that asset/timeframe
    - Metadata for logging and routing
    """
    symbol: str                         # e.g. "BTC"
    timeframe: str                      # e.g. "15M", "1H", "1D"
    
    # Spot price
    spot_price: float                   # e.g. 70743.69
    spot_source: str                    # e.g. "coinbase_price" (NOT a trading venue)
    spot_ts: datetime                   # When spot was sampled
    
    # Kalshi series
    kalshi_series: str                  # e.g. "KXBTC15M"
    kalshi_markets: List[KalshiMarketView] = field(default_factory=list)
    
    def num_markets(self) -> int:
        return len(self.kalshi_markets)
    
    def open_markets(self) -> List[KalshiMarketView]:
        return [m for m in self.kalshi_markets if m.status == "open"]
    
    def __str__(self) -> str:
        return f"CryptoSurface({self.symbol}-{self.timeframe}, spot={self.spot_price:.2f}, {self.num_markets()} markets)"


@dataclass
class CryptoSurfaceSnapshot:
    """
    Complete snapshot of all crypto surfaces at a single point in time.
    """
    timestamp: datetime
    entries: List[CryptoSurfaceEntry] = field(default_factory=list)
    
    def get_entry(self, symbol: str, timeframe: str) -> Optional[CryptoSurfaceEntry]:
        for entry in self.entries:
            if entry.symbol == symbol and entry.timeframe == timeframe:
                return entry
        return None
    
    def __len__(self) -> int:
        return len(self.entries)

# ─────────────────────────────────────────────────────────────────────────────
# 4. BUILDERS & SELECTORS
# ─────────────────────────────────────────────────────────────────────────────


def build_crypto_surface(
    spot_snapshot: Dict[str, Dict[str, Any]],
    kalshi_markets_by_series: Dict[str, List[Any]],
) -> CryptoSurfaceSnapshot:
    """
    Build complete crypto surface from spot feeds + Kalshi series.
    
    Args:
        spot_snapshot: {"BTC": {"price": 70743.69, "ts": datetime, ...}, ...}
        kalshi_markets_by_series: {"KXBTC15M": [market_obj, ...], ...}
    
    Returns:
        CryptoSurfaceSnapshot with all asset/timeframe combos populated.
    """
    surface_entries = []
    
    for symbol, cfg in CRYPTO_CONFIG.items():
        if symbol not in spot_snapshot:
            logger.warning(f"Spot snapshot missing {symbol}; skipping")
            continue
        
        spot_data = spot_snapshot[symbol]
        spot_price = spot_data.get("price")
        spot_ts = spot_data.get("ts", datetime.now())
        spot_source = cfg["spot_source"]
        
        if spot_price is None:
            logger.warning(f"Spot price for {symbol} is None; skipping")
            continue
        
        for timeframe, series_ticker in cfg["series"].items():
            # Fetch markets for this series
            markets_for_series = kalshi_markets_by_series.get(series_ticker, [])
            market_views = [_to_market_view(m) for m in markets_for_series]
            
            entry = CryptoSurfaceEntry(
                symbol=symbol,
                timeframe=timeframe,
                spot_price=spot_price,
                spot_source=spot_source,
                spot_ts=spot_ts,
                kalshi_series=series_ticker,
                kalshi_markets=market_views,
            )
            surface_entries.append(entry)
    
    return CryptoSurfaceSnapshot(
        timestamp=datetime.now(),
        entries=surface_entries,
    )


def _to_market_view(raw_market: Any) -> KalshiMarketView:
    """
    Convert raw Kalshi market object to KalshiMarketView.
    
    Handles both dict and obj-based market representations.
    """
    # Support both dict and attribute-based objects
    def _get(obj, key, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)
    
    # Extract or compute target_price from contract terms
    target_price = _get(raw_market, "target_price")
    if target_price is None:
        # Try common aliases
        target_price = _get(raw_market, "strike_price")
    if target_price is None:
        target_price = _get(raw_market, "level")
    if target_price is None:
        # For range contracts, use midpoint
        range_min = _get(raw_market, "range_min")
        range_max = _get(raw_market, "range_max")
        if range_min is not None and range_max is not None:
            target_price = (range_min + range_max) / 2.0
    if target_price is None:
        target_price = 0.0  # Fallback
    
    return KalshiMarketView(
        market_id=_get(raw_market, "market_id", "UNKNOWN"),
        title=_get(raw_market, "title", ""),
        yes_price=_get(raw_market, "yes_price", 0.5),
        no_price=_get(raw_market, "no_price", 0.5),
        target_price=target_price,
        status=_get(raw_market, "status", "unknown"),
        expires_at=_get(raw_market, "expires_at", datetime.now()),
        quantity_yes=_get(raw_market, "quantity_yes"),
        quantity_no=_get(raw_market, "quantity_no"),
    )


def select_markets_near_spot(surface_entry: CryptoSurfaceEntry) -> List[KalshiMarketView]:
    """
    Select Kalshi markets within "near spot" band for an asset/timeframe.
    
    Prioritizes by distance from spot price, respects % band and max count.
    
    Args:
        surface_entry: CryptoSurfaceEntry from crypto surface
    
    Returns:
        List of KalshiMarketView ordered by distance from spot
    """
    key = (surface_entry.symbol, surface_entry.timeframe)
    
    if key not in NEAR_SPOT_CONFIG:
        logger.warning(
            f"No near-spot config for {key}; returning all open markets"
        )
        return [m for m in surface_entry.kalshi_markets if m.status == "open"]
    
    cfg = NEAR_SPOT_CONFIG[key]
    band_pct = cfg["pct_band"]
    max_markets = cfg["max_markets"]
    
    # Score all open markets by distance from spot
    candidates = [
        (m.distance_to_spot(surface_entry.spot_price), m)
        for m in surface_entry.kalshi_markets
        if m.status == "open"
    ]
    
    # Sort by distance
    candidates.sort(key=lambda x: x[0])
    
    # Filter by band and limit by max_markets
    selected = [
        m for d, m in candidates
        if d <= band_pct
    ][:max_markets]
    
    return selected


# ─────────────────────────────────────────────────────────────────────────────
# 5. LOGGING & AUDIT
# ─────────────────────────────────────────────────────────────────────────────


def log_markets_near_spot(
    surface_entry: CryptoSurfaceEntry,
    markets_near_spot: List[KalshiMarketView],
    selector: str = "top_by_distance",
) -> None:
    """
    Log near-spot market selection for audit trail.
    
    Creates consistent, parseable logs for verifying configurations.
    
    Args:
        surface_entry: The crypto surface entry being logged
        markets_near_spot: Selected markets from selector
        selector: Selection algorithm name (for logging)
    """
    key = (surface_entry.symbol, surface_entry.timeframe)
    cfg = NEAR_SPOT_CONFIG.get(key, {})
    band_pct = cfg.get("pct_band", "?")
    
    total_markets = len(surface_entry.open_markets())
    selected_count = len(markets_near_spot)
    
    logger.info(
        f"Scanning {total_markets} {surface_entry.symbol}-{surface_entry.timeframe} "
        f"Kalshi markets within ±{band_pct}% of spot {surface_entry.spot_price:.2f} "
        f"(series={surface_entry.kalshi_series}, status=open, selector={selector}); "
        f"selected {selected_count}."
    )
    
    # Log first 5 selected markets for verification
    for i, market in enumerate(markets_near_spot[:5]):
        distance = market.distance_to_spot(surface_entry.spot_price)
        logger.debug(
            f"  [{i+1}] {market.market_id}: target={market.target_price:.2f}, "
            f"distance={distance:.2f}%, mid={market.mid_price():.4f}, "
            f"expires={market.expires_at.isoformat()}"
        )
    
    if len(markets_near_spot) > 5:
        logger.debug(f"  ... and {len(markets_near_spot) - 5} more markets")


def log_crypto_surface_snapshot(snapshot: CryptoSurfaceSnapshot) -> None:
    """
    Log summary of entire crypto surface for audit.
    """
    logger.info(
        f"Crypto surface snapshot at {snapshot.timestamp.isoformat()}: "
        f"{len(snapshot)} asset/timeframe entries"
    )
    
    for entry in snapshot.entries:
        open_count = len(entry.open_markets())
        logger.debug(
            f"  {entry.symbol}-{entry.timeframe}: "
            f"spot={entry.spot_price:.2f} ({entry.spot_source}), "
            f"{open_count} open markets, series={entry.kalshi_series}"
        )


def get_config_consistency_report() -> Dict[str, Any]:
    """
    Audit CRYPTO_CONFIG and NEAR_SPOT_CONFIG for consistency.
    
    Returns dict with:
    - assets_defined: list of symbols in CRYPTO_CONFIG
    - timeframes_per_asset: mapping of asset → timeframes
    - near_spot_coverage: list of (asset, timeframe) with band config
    - issues: list of inconsistencies found (if any)
    """
    issues = []
    
    # All timeframes defined in CRYPTO_CONFIG
    asset_timeframes = {}
    for symbol, cfg in CRYPTO_CONFIG.items():
        asset_timeframes[symbol] = list(cfg["series"].keys())
    
    # All (asset, timeframe) in NEAR_SPOT_CONFIG
    near_spot_keys = set(NEAR_SPOT_CONFIG.keys())
    
    # Check: every (asset, timeframe) in CRYPTO_CONFIG has near-spot config
    for symbol, timeframes in asset_timeframes.items():
        for tf in timeframes:
            key = (symbol, tf)
            if key not in near_spot_keys:
                issues.append(f"Missing near-spot config for {key}")
    
    return {
        "assets_defined": list(CRYPTO_CONFIG.keys()),
        "timeframes_per_asset": asset_timeframes,
        "near_spot_coverage": list(near_spot_keys),
        "total_configs": len(near_spot_keys),
        "consistency_issues": issues,
    }


if __name__ == "__main__":
    # Quick self-test
    print("Crypto ↔ Kalshi Config Self-Test")
    print("=" * 60)
    
    report = get_config_consistency_report()
    print(f"\nDefined assets: {report['assets_defined']}")
    print(f"Timeframes per asset: {report['timeframes_per_asset']}")
    print(f"Near-spot band configs: {report['total_configs']}")
    
    if report["consistency_issues"]:
        print("\n⚠ Consistency issues found:")
        for issue in report["consistency_issues"]:
            print(f"  - {issue}")
    else:
        print("\n✓ All configs consistent")
    
    print("\nNear-spot band configuration:")
    for (symbol, timeframe), cfg in sorted(NEAR_SPOT_CONFIG.items()):
        print(f"  {symbol:6} {timeframe:3} → ±{cfg['pct_band']:4.1f}%, max {cfg['max_markets']:2} markets")
