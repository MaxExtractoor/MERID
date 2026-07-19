"""Market Selection Filter — Liquidity, spread, and overlap checks.

Filters Kalshi crypto hourly markets by quality criteria before
attaching agents:

1. **Liquidity floor**: Minimum volume / open interest
2. **Spread threshold**: Max bid-ask spread in cents
3. **Overlap detection**: Groups temporally overlapping brackets on the
   same underlying into a single risk bucket
4. **Settlement recency**: Prefer markets settling soon for tighter pricing

Usage::

    filt = MarketFilter(config)
    candidates = filt.filter_markets(markets)
    groups = filt.group_overlapping(candidates)
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.market_filter")


# ═══════════════════════════════════════════════════════════════════════════
# Tiered Min-Edge Grid — Asset/Timeframe Specific Thresholds
# ═══════════════════════════════════════════════════════════════════════════

# Shorter timeframes and noisier assets (SOL/XRP/DOGE) get higher min-edges.
# Longer tenors can tolerate slightly lower min-edges.
# TIGHTENED: Increased edge thresholds for higher conviction trades only
# Global hard floor: 0.08 (nothing slips below this).
MIN_EDGE_GRID: Dict[str, Dict[str, Decimal]] = {
    "BTC": {
        "15m":     Decimal("0.12"),  # Increased from 0.10 for higher conviction
        "1h":      Decimal("0.10"),  # Increased from 0.08
        "daily":   Decimal("0.09"),  # Increased from 0.08
        "weekly":  Decimal("0.08"),  # Increased from 0.07
        "monthly": Decimal("0.07"),  # Increased from 0.06
        "annual":  Decimal("0.06"),  # Increased from 0.05
    },
    "ETH": {
        "15m":     Decimal("0.13"),  # Increased from 0.11
        "1h":      Decimal("0.11"),  # Increased from 0.09
        "daily":   Decimal("0.10"),  # Increased from 0.09
        "weekly":  Decimal("0.09"),  # Increased from 0.08
        "monthly": Decimal("0.08"),  # Increased from 0.07
        "annual":  Decimal("0.07"),  # Increased from 0.06
    },
    "SOL": {
        "15m":     Decimal("0.15"),  # Increased from 0.13
        "1h":      Decimal("0.12"),  # Increased from 0.10
        "daily":   Decimal("0.11"),  # Increased from 0.10
        "weekly":  Decimal("0.10"),  # Increased from 0.09
        "monthly": Decimal("0.09"),  # Increased from 0.08
        "annual":  Decimal("0.08"),  # Increased from 0.07
    },
    "XRP": {
        "15m":     Decimal("0.16"),  # Increased from 0.14
        "1h":      Decimal("0.13"),  # Increased from 0.11
        "daily":   Decimal("0.12"),  # Increased from 0.11
        "weekly":  Decimal("0.11"),  # Increased from 0.10
        "monthly": Decimal("0.10"),  # Increased from 0.09
        "annual":  Decimal("0.09"),  # Increased from 0.08
    },
    "DOGE": {
        "15m":     Decimal("0.17"),  # Increased from 0.15
        "1h":      Decimal("0.14"),  # Increased from 0.12
        "daily":   Decimal("0.13"),  # Increased from 0.12
        "weekly":  Decimal("0.12"),  # Increased from 0.11
        "monthly": Decimal("0.11"),  # Increased from 0.10
        "annual":  Decimal("0.10"),  # Increased from 0.09
    },
}

# Global hard floor — no trade slips below this regardless of asset/tf
MIN_EDGE_GLOBAL_FLOOR: Decimal = Decimal("0.08")


# ═══════════════════════════════════════════════════════════════════════════
# Tiered Max Price Grid — Asset/Timeframe Specific Max Prices (in cents)
# ═══════════════════════════════════════════════════════════════════════════

# Shorter timeframes get tighter price caps (avoid near-certain contracts).
# Longer tenors can trade higher probabilities (still protected by min-edge).
# Dust floor (global min_price_cents) kept at ~10c to avoid near-zero contracts.
MAX_PRICE_GRID: Dict[str, Dict[str, int]] = {
    "BTC": {
        "15m":     40,
        "1h":      50,
        "daily":   60,
        "weekly":  65,
        "monthly": 70,
        "annual":  80,  # Annual: longest tenor → can trade near-certainty contracts
    },
    "ETH": {
        "15m":     38,
        "1h":      48,
        "daily":   58,
        "weekly":  63,
        "monthly": 68,
        "annual":  78,
    },
    "SOL": {
        "15m":     35,
        "1h":      45,
        "daily":   55,
        "weekly":  60,
        "monthly": 65,
        "annual":  75,
    },
    "XRP": {
        "15m":     32,
        "1h":      42,
        "daily":   52,
        "weekly":  58,
        "monthly": 63,
        "annual":  72,
    },
    "DOGE": {
        "15m":     30,
        "1h":      40,
        "daily":   50,
        "weekly":  55,
        "monthly": 60,
        "annual":  70,
    },
}

# Global fallback if asset/tf not found — replaced by tiered grid
MAX_PRICE_GLOBAL_FALLBACK: int = 35  # cents (legacy default)


def get_tiered_max_price(asset: str, series_ticker: str) -> int:
    """Get the max price cap (in cents) for a given asset and series.
    
    Args:
        asset: Underlying asset (BTC, ETH, SOL, XRP, DOGE)
        series_ticker: Full series ticker (e.g., KXBTC15M-26MAR250115-15)
    
    Returns:
        int max price in cents, with MAX_PRICE_GLOBAL_FALLBACK as default.
    """
    asset_upper = asset.upper()
    tf_bucket = get_series_timeframe_bucket(series_ticker)
    
    # Lookup tiered max price
    asset_grid = MAX_PRICE_GRID.get(asset_upper, {})
    return asset_grid.get(tf_bucket, MAX_PRICE_GLOBAL_FALLBACK)


# ═══════════════════════════════════════════════════════════════════════════
# Asset Coverage Invariants — Enforce exact 5-asset grid match
# ═══════════════════════════════════════════════════════════════════════════

from merid.event_venues.kalshi.constants import assert_exact_assets

# Canonical 6-timeframe set — all grids must cover every bucket
CANONICAL_TIMEFRAMES_SET: frozenset = frozenset({"15m", "1h", "daily", "weekly", "monthly", "annual"})

# Validate that all tiered grids cover exactly the 5-asset crypto universe
assert_exact_assets(set(MIN_EDGE_GRID.keys()), "MIN_EDGE_GRID")
assert_exact_assets(set(MAX_PRICE_GRID.keys()), "MAX_PRICE_GRID")

# Validate that every asset row contains all 6 timeframe buckets
for _g_name, _g_dict in (("MIN_EDGE_GRID", MIN_EDGE_GRID), ("MAX_PRICE_GRID", MAX_PRICE_GRID)):
    for _asset, _tf_row in _g_dict.items():
        _missing = CANONICAL_TIMEFRAMES_SET - set(_tf_row.keys())
        if _missing:
            raise AssertionError(f"{_g_name}[{_asset}] is missing timeframes: {sorted(_missing)}")


# ═══════════════════════════════════════════════════════════════════════════
# Contract Price Bands — Per-Asset/Timeframe (min, max) as fractions [0,1]
# ═══════════════════════════════════════════════════════════════════════════
# These set ABSOLUTE outer bounds on what mid-price (probability) a contract
# must sit in for us to trade it. They are applied BEFORE edge and sizing so
# we never size into near-zero (dust) or near-certain (illiquid) contracts.
#
# Values are fractions: 0.10 = 10¢, 0.90 = 90¢ out of $1 per contract.
# Wider bands for more-volatile / longer-tenor markets; tighter for BTC short.
# Fallback: PRICE_BANDS_DEFAULT is used when (asset, timeframe) not present.
#
# Design rationale:
# - BTC short-tenor: 10-90¢ — liquid mid-curve range
# - BTC longer-tenor: 15-85¢ — narrower to avoid near-certain daily/weekly calls
# - ETH: slightly wider lower bound (8¢) — can trade near-zero-prob ETH options
# - SOL/XRP: 5¢ lower — wider probability range, more volatile assets
# - DOGE: 3¢ lower — extremes still viable given volatility profile
PRICE_BANDS: Dict[Tuple[str, str], Tuple[float, float]] = {
    # BTC — tightest bands (most liquid, tightest spreads)
    ("BTC", "15m"):     (0.10, 0.90),
    ("BTC", "1h"):      (0.10, 0.90),
    ("BTC", "daily"):   (0.15, 0.85),
    ("BTC", "weekly"):  (0.15, 0.85),
    ("BTC", "monthly"): (0.15, 0.85),
    ("BTC", "annual"):  (0.20, 0.80),  # Annual: wider low-end, tighter upper (near-certain excluded)
    # ETH — slightly wider lower bound
    ("ETH", "15m"):     (0.08, 0.92),
    ("ETH", "1h"):      (0.08, 0.92),
    ("ETH", "daily"):   (0.12, 0.88),
    ("ETH", "weekly"):  (0.12, 0.88),
    ("ETH", "monthly"): (0.12, 0.88),
    ("ETH", "annual"):  (0.15, 0.85),
    # SOL — wider, more volatile
    ("SOL", "15m"):     (0.05, 0.95),
    ("SOL", "1h"):      (0.05, 0.95),
    ("SOL", "daily"):   (0.08, 0.92),
    ("SOL", "weekly"):  (0.08, 0.92),
    ("SOL", "monthly"): (0.08, 0.92),
    ("SOL", "annual"):  (0.10, 0.90),
    # XRP — same profile as SOL
    ("XRP", "15m"):     (0.05, 0.95),
    ("XRP", "1h"):      (0.05, 0.95),
    ("XRP", "daily"):   (0.08, 0.92),
    ("XRP", "weekly"):  (0.08, 0.92),
    ("XRP", "monthly"): (0.08, 0.92),
    ("XRP", "annual"):  (0.10, 0.90),
    # DOGE — widest, most speculative
    ("DOGE", "15m"):     (0.03, 0.97),
    ("DOGE", "1h"):      (0.03, 0.97),
    ("DOGE", "daily"):   (0.03, 0.97),
    ("DOGE", "weekly"):  (0.03, 0.97),
    ("DOGE", "monthly"): (0.03, 0.97),
    ("DOGE", "annual"):  (0.05, 0.95),
}

# Conservative fallback when (asset, timeframe) is not in PRICE_BANDS
PRICE_BANDS_DEFAULT: Tuple[float, float] = (0.05, 0.95)

assert_exact_assets({k[0] for k in PRICE_BANDS.keys()}, "PRICE_BANDS")

# Validate PRICE_BANDS covers all 6 timeframes for each asset
_pb_by_asset: Dict[str, set] = {}
for (_pb_asset, _pb_tf) in PRICE_BANDS.keys():
    _pb_by_asset.setdefault(_pb_asset, set()).add(_pb_tf)
for _pb_asset, _pb_tfs in _pb_by_asset.items():
    _missing_pb = CANONICAL_TIMEFRAMES_SET - _pb_tfs
    if _missing_pb:
        raise AssertionError(f"PRICE_BANDS[{_pb_asset}] is missing timeframes: {sorted(_missing_pb)}")


def get_price_band(asset: str, series_ticker: str) -> Tuple[float, float]:
    """Return the (min_price_frac, max_price_frac) band for a given asset + series.

    Both values are fractions in [0, 1] — multiply by 100 to get cents.

    Args:
        asset: Underlying asset symbol (BTC, ETH, SOL, XRP, DOGE)
        series_ticker: Full or partial Kalshi series ticker

    Returns:
        (min_frac, max_frac) — e.g. (0.10, 0.90) for BTC 15m
    """
    asset_upper = asset.upper()
    tf_bucket = get_series_timeframe_bucket(series_ticker)
    return PRICE_BANDS.get((asset_upper, tf_bucket), PRICE_BANDS_DEFAULT)


# ═══════════════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════════════

def get_series_timeframe_bucket(series_ticker: str) -> str:
    """Map Kalshi series ticker to canonical timeframe for validation.
    
    Handles formats:
    - KXBTC15M-... → 15m
    - KXETH-... (hourly) → 1h
    - KXBTCD1-... → daily
    - KXBTCW1-... → weekly
    - KXBTC1M-... → monthly
    - KXBTCY-... (annual) → annual
    """
    if not series_ticker:
        return "1h"  # Default fallback
    
    upper = series_ticker.upper()
    
    # Check series prefix (before first dash) to handle full market tickers
    series_part = upper.split("-")[0] if "-" in upper else upper
    
    # Annual series (Y suffix for yearly/annual)
    if series_part.endswith("Y"):
        return "annual"
    
    # 15-minute series
    if "15M" in series_part:
        return "15m"
    
    # Daily
    if "D1" in series_part:
        return "daily"
    
    # Weekly
    if "W1" in series_part:
        return "weekly"
    
    # Monthly
    if "1M" in series_part:
        return "monthly"
    
    # Hourly (default — most common format like KXBTC-...)
    return "1h"


def get_tiered_min_edge(asset: str, series_ticker: str) -> Decimal:
    """Get the min-edge threshold for a given asset and series.
    
    Args:
        asset: Underlying asset (BTC, ETH, SOL, XRP, DOGE)
        series_ticker: Full series ticker (e.g., KXBTC15M-26MAR250115-15)
    
    Returns:
        Decimal min-edge, clamped to MIN_EDGE_GLOBAL_FLOOR minimum.
    """
    asset_upper = asset.upper()
    tf_bucket = get_series_timeframe_bucket(series_ticker)

    _profile = os.getenv("KALSHI_CT_PROFILE", "modern_tradeable_kalshi_v1").strip().lower() or "modern_tradeable_kalshi_v1"
    if _profile == "initial_live":
        from config.kalshi_ct_risk_profiles import initial_live_min_edge

        return initial_live_min_edge(asset_upper, tf_bucket)

    if _profile == "modern_tradeable_kalshi_v1":
        # Use crypto_threshold_matrix.yaml schema v2 with per-asset, per-timeframe edge_grid
        # LEGACY REMOVAL: crypto_threshold_matrix moved to archive/legacy/ during 15m stack cleanup
        try:
            from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS

            if asset_upper in ACTIVE_CRYPTO_ASSETS:
                # cell = get_crypto_thresholds(asset_upper, tf_bucket)
                cell = None
                # Use directional_min_edge from the matrix (matches modern_tradeable_kalshi_v1 profile)
                tiered_min = cell.directional_min_edge
                _floor = cell.tier_min_edge_floor
                return max(tiered_min, _floor)
        except Exception as e:
            logger.debug(f"Matrix tier lookup failed: {e}")
        # Fallback to production grid if matrix lookup fails

    # Lookup tiered threshold (production / legacy path)
    asset_grid = MIN_EDGE_GRID.get(asset_upper, {})
    tiered_min = asset_grid.get(tf_bucket, Decimal("0.08"))  # Default 0.08 if not found

    try:
        # LEGACY REMOVAL: crypto_edge_production moved to archive/legacy/ during 15m stack cleanup
        # from merid.prediction.crypto_edge_production import tiered_min_edge_multiplier
        pass
    except Exception as e:
        logger.debug(f"Tier multiplier failed: {e}")

    # Crypto: blend with shared PM matrix (modern profile lowers bar vs inventory grid)
    _floor = MIN_EDGE_GLOBAL_FLOOR
    try:
        from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS
        # LEGACY REMOVAL: crypto_edge_production moved to archive/legacy/ during 15m stack cleanup
        # from merid.prediction.crypto_edge_production import (
        #     crypto_tier_min_edge_floor,
        #     integrate_crypto_tiered_min_edge,
        # )

        if asset_upper in ACTIVE_CRYPTO_ASSETS:
            # tiered_min = integrate_crypto_tiered_min_edge(asset_upper, tf_bucket, tiered_min)
            # _floor = crypto_tier_min_edge_floor(asset_upper, tf_bucket)
            pass
    except Exception as e:
        logger.debug(f"Crypto tier integration failed: {e}")

    return max(tiered_min, _floor)


def log_tiered_grid_inspector(
    series_tickers: List[str],
    assets: Optional[List[str]] = None,
    log_live_candidates: bool = False,
    live_candidates: Optional[List[MarketCandidate]] = None,
) -> None:
    """Debug helper: Print tiered grid configuration for asset/series combos.
    
    Use this at startup or in dry-run mode to verify your MIN_EDGE_GRID and
    MAX_PRICE_GRID resolve correctly for each (asset, series) you trade.
    
    Args:
        series_tickers: List of series tickers to inspect (e.g., ["KXBTC15M", "KXBTC", "KXBTCD1"])
        assets: Optional list of assets (defaults to BTC, ETH, SOL, XRP, DOGE)
        log_live_candidates: If True, also log mid_price_cents for live candidates
        live_candidates: Optional list of MarketCandidate to show live prices against thresholds
    
    Example output:
        [GRID INSPECTOR] BTC/KXBTC15M → bucket=15m | min_edge=0.10 | max_price=40c
        [GRID INSPECTOR] BTC/KXBTC → bucket=D1 | min_edge=0.08 | max_price=60c
        [GRID INSPECTOR] DOGE/KXDOGE15M → bucket=15m | min_edge=0.15 | max_price=30c
    """
    assets = assets or list(ACTIVE_CRYPTO_ASSETS)
    
    logger.info("=" * 80)
    logger.info("[GRID INSPECTOR] Tiered Grid Configuration Check")
    logger.info("=" * 80)
    
    for asset in assets:
        for series in series_tickers:
            # Only process series that match this asset
            if not series.upper().startswith(f"KX{asset}") and not series.upper().startswith(f"KXXRP"):
                continue
            if asset == "XRP" and not series.upper().startswith("KXXRP"):
                continue
            
            bucket = get_series_timeframe_bucket(series)
            min_edge = get_tiered_min_edge(asset, series)
            max_price = get_tiered_max_price(asset, series)
            
            logger.info(
                "[GRID INSPECTOR] %s/%s → bucket=%s | min_edge=%.2f | max_price=%dc",
                asset, series, bucket, float(min_edge), max_price,
            )
    
    # Optional: show live candidates against thresholds
    if log_live_candidates and live_candidates:
        logger.info("-" * 80)
        logger.info("[GRID INSPECTOR] Live Candidates vs Thresholds (first 5):")
        for c in live_candidates[:5]:
            asset = c.underlying.upper()
            series = c.ticker.split("-")[0] if "-" in c.ticker else c.ticker
            bucket = get_series_timeframe_bucket(c.ticker)
            min_edge = get_tiered_min_edge(asset, c.ticker)
            max_price = get_tiered_max_price(asset, c.ticker)
            mid_price = c.mid_price_cents
            
            edge_status = "✓" if mid_price <= max_price else "✗ PRICE"
            
            logger.info(
                "[GRID INSPECTOR] %s → bucket=%s | mid=%dc | max=%dc | min_edge=%.2f | %s",
                c.ticker, bucket, mid_price, max_price, float(min_edge), edge_status,
            )
    
    logger.info("=" * 80)


# ═══════════════════════════════════════════════════════════════════════════
# Canonical Group Key Mapper — Asset/Horizon/Overlap Group Identification
# ═══════════════════════════════════════════════════════════════════════════

def generate_group_id(asset: str, timeframe: str, expiry_ts: float) -> str:
    """Generate a canonical group ID for per-(asset, horizon, overlap-window) risk bucketing.
    
    This creates deterministic group keys like:
    - BTC-15m-2026-03-27T15:00 (15m Up/Down window)
    - ETH-1h-2026-03-27T16:00 (hourly window)
    - SOL-D1-2026-03-27 (daily close)
    - XRP-W1-2026-W13 (weekly bracket)
    - DOGE-1M-2026-03 (monthly bracket)
    
    These group IDs are used for:
    - Group-level exposure aggregation in kalshi_risk.py
    - Single-alert-per-breach enforcement (cooldown keyed by group_id)
    - Per-asset/timeframe risk caps
    - Lifecycle alignment (DISCOVER→ANALYZE→CONSENSUS→SIZE→EXECUTE→MONITOR→PROMOTE→PROTECT)
    
    Args:
        asset: Underlying asset symbol (BTC, ETH, SOL, XRP, DOGE)
        timeframe: Timeframe bucket (15m, 1h, D1, W1, 1M)
        expiry_ts: Expiry timestamp (epoch seconds)
    
    Returns:
        Canonical group ID string for risk aggregation.
    """
    from datetime import datetime, timezone
    
    asset_upper = asset.upper()
    tf_normalized = _normalize_timeframe(timeframe)
    
    # Convert expiry timestamp to ISO date/time
    if expiry_ts > 0:
        expiry_dt = datetime.fromtimestamp(float(expiry_ts), tz=timezone.utc)
        
        # Format based on timeframe granularity
        if tf_normalized == "15m":
            # Round to 15-minute boundary
            minute_bucket = (expiry_dt.minute // 15) * 15
            rounded_dt = expiry_dt.replace(minute=minute_bucket, second=0, microsecond=0)
            expiry_str = rounded_dt.strftime("%Y-%m-%dT%H:%M")
        elif tf_normalized == "1h":
            # Hour precision
            expiry_str = expiry_dt.strftime("%Y-%m-%dT%H:00")
        elif tf_normalized == "daily":
            # Daily precision
            expiry_str = expiry_dt.strftime("%Y-%m-%d")
        elif tf_normalized == "weekly":
            # Week number
            expiry_str = f"{expiry_dt.year}-W{expiry_dt.isocalendar()[1]:02d}"
        elif tf_normalized == "monthly":
            # Month precision
            expiry_str = expiry_dt.strftime("%Y-%m")
        elif tf_normalized == "annual":
            # Year only
            expiry_str = expiry_dt.strftime("%Y")
        else:
            # Default to daily
            expiry_str = expiry_dt.strftime("%Y-%m-%d")
    else:
        expiry_str = "unknown"
    
    return f"{asset_upper}-{tf_normalized}-{expiry_str}"


def _normalize_timeframe(timeframe: str) -> str:
    """Normalize various timeframe strings to canonical bucket names.
    
    Returns lowercase canonical forms to match get_series_timeframe_bucket().
    """
    tf_lower = timeframe.lower()
    
    # 15-minute variants
    if tf_lower in ("15m", "15min", "15-minute", "15 minute", "15minutely"):
        return "15m"
    
    # Hourly variants
    if tf_lower in ("1h", "hourly", "hour", "1-hour", "1 hour", "h1"):
        return "1h"
    
    # Daily variants
    if tf_lower in ("d1", "daily", "day", "1d", "d"):
        return "daily"
    
    # Weekly variants
    if tf_lower in ("w1", "weekly", "week", "1w", "w"):
        return "weekly"
    
    # Monthly variants
    if tf_lower in ("1m", "monthly", "month", "mo", "1mo"):
        return "monthly"
    
    # Annual variants
    if tf_lower in ("y", "annual", "yearly", "year", "1y"):
        return "annual"
    
    # Default fallback (pass through normalized)
    return tf_lower


def extract_asset_from_ticker(ticker: str) -> Optional[str]:
    """Extract asset symbol from Kalshi ticker.
    
    Handles formats:
    - KXBTC-26MAR2501-T80199.99 → BTC
    - KXETH15M-26MAR250115-15 → ETH
    - KXSOL-26MAR2501-T180.00 → SOL
    - KXXRP-26MAR2501-T2.50 → XRP
    - KXDOGE-26MAR2501-T0.25 → DOGE
    """
    if not ticker:
        return None
    
    upper = ticker.upper()
    
    # Check for each asset in priority order (BTC before BTCD, etc.)
    assets = list(ACTIVE_CRYPTO_ASSETS)
    for asset in assets:
        # Match KXBTC, KXBTC15M, KXBTCD1, etc.
        if f"KX{asset}" in upper or f"KX{asset}15M" in upper or f"KX{asset}D1" in upper:
            return asset
        if f"KX{asset}W1" in upper or f"KX{asset}1M" in upper or f"KX{asset}1H" in upper:
            return asset
    
    return None


def parse_expiry_from_ticker(ticker: str, market: Optional[dict] = None) -> float:
    """Parse expiry timestamp from Kalshi ticker format.
    
    Handles formats:
    - KXBTC-26MAR2501-T80199.99 → parses 26MAR2501 as epoch
    - KXBTC15M-26MAR250115-15 → parses 26MAR250115 as epoch  
    - ISO format: 2026-03-27T20:00:00 from market['expiration_time']
    
    Args:
        ticker: Kalshi market ticker
        market: Optional market dict with 'expiration_time' as ISO string fallback
    
    Returns:
        Epoch timestamp (float) or 0.0 if parsing fails.
    """
    if not ticker:
        # Fallback to market data if available
        if market and market.get('expiration_time'):
            try:
                exp_str = market['expiration_time']
                dt = datetime.fromisoformat(exp_str.replace('Z', '+00:00'))
                return dt.timestamp()
            except (ValueError, TypeError):
                pass
        return 0.0
    
    # Try ISO format from market data first (most reliable)
    if market and market.get('expiration_time'):
        try:
            exp_str = market['expiration_time']
            dt = datetime.fromisoformat(exp_str.replace('Z', '+00:00'))
            return dt.timestamp()
        except (ValueError, TypeError):
            pass
    
    # Try to extract date pattern from ticker: DDMMMYY or DDMMMYYYY followed by HHMM
    # Examples: 26MAR2501, 26MAR250115, 26MAR202501, etc.
    # Handles formats like:
    #   - KXBTC-26MAR2501-T80199.99 → date surrounded by dashes
    #   - KXXRP15M-26APR141315-15 → date followed by dash and strike price
    #   - KXBTC26MAR2501T80199 → no dashes around date
    upper_ticker = ticker.upper()
    
    # Primary pattern: date surrounded by dashes OR date followed by dash and digits (strike)
    match = re.search(r"-(\d{1,2}[A-Z]{3}(?:\d{2})?(?:\d{2})?(?:\d{2,4})?)(?:-\d|$)", upper_ticker)
    if not match:
        # Try pattern with just surrounding dashes (original pattern for backward compatibility)
        match = re.search(r"-(\d{1,2}[A-Z]{3}(?:\d{2})?(?:\d{2})?(?:\d{2,4})?)-", upper_ticker)
    if not match:
        # Try alternate format without dashes: KXBTC26MAR2501T80199
        match = re.search(r"KX[A-Z]+(\d{1,2}[A-Z]{3}\d{2,4})", upper_ticker)
    
    if match:
        date_str = match.group(1)
        try:
            # CRITICAL FIX (2026-07-19): Kalshi ticker dates are YEAR-FIRST in
            # US Eastern time: YYMMMDDHHMM (e.g., 26JUL190030 = 2026-JUL-19 00:30 ET).
            # Previous day-first (%d%b%y...) parsing decoded 26JUL190030 as
            # 2019-07-26, making ALL live markets appear expired and settled
            # markets appear live - corrupting expiry validation, group IDs,
            # and position/settlement detection end-to-end.
            from zoneinfo import ZoneInfo
            _ET = ZoneInfo("America/New_York")
            year_first_formats = [
                ("%y%b%d%H%M", _ET),   # 26JUL190030 -> 2026-07-19 00:30 ET
                ("%y%b%d%H", _ET),     # 26MAR2501   -> 2026-03-25 01:00 ET
                ("%y%b%d", _ET),       # 26MAR25     -> 2026-03-25 ET
            ]
            for fmt, tz in year_first_formats:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    dt = dt.replace(tzinfo=tz)
                    return dt.timestamp()
                except ValueError:
                    continue
            # Legacy fallback: day-first UTC formats (non-standard tickers)
            legacy_formats = [
                "%d%b%Y%H%M",      # 26MAR20250115
                "%d%b%Y",          # 26MAR2025
            ]
            for fmt in legacy_formats:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    dt = dt.replace(tzinfo=timezone.utc)
                    return dt.timestamp()
                except ValueError:
                    continue
        except Exception as e:
            logger.debug(f"Timestamp parsing failed: {e}")

    # Final fallback: try direct ISO format parsing from ticker itself
    # Some tickers may embed ISO timestamp
    iso_match = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", ticker)
    if iso_match:
        try:
            dt = datetime.fromisoformat(iso_match.group(1).replace('Z', '+00:00'))
            dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except (ValueError, TypeError):
            pass
    
    return 0.0


def is_expiry_valid(expiry_ts: float, buffer_seconds: float = 60.0) -> bool:
    """Check if expiry timestamp is valid (in the future with buffer).
    
    Args:
        expiry_ts: Epoch timestamp to check
        buffer_seconds: Minimum seconds before expiry to consider valid (default 60s)
    
    Returns:
        True if expiry is in the future by at least buffer_seconds
    """
    if expiry_ts <= 0:
        return False
    now_ts = datetime.now(timezone.utc).timestamp()
    return expiry_ts > (now_ts + buffer_seconds)


def canonicalize_group_components(
    ticker: str,
    *,
    timeframe: str | None = None,
    expiry_ts: float | None = None,
    market: Optional[dict] = None,
) -> tuple[str, str, float]:
    """Canonicalize group ID components from ticker.
    
    Returns normalized (asset, timeframe, expiry_ts) tuple for consistent
    group ID generation across all code paths.
    
    Args:
        ticker: Kalshi market ticker
        timeframe: Optional override (uses get_series_timeframe_bucket if not provided)
        expiry_ts: Optional override (parses from ticker/market if not provided)
        market: Optional market dict for expiry fallback
    
    Returns:
        Tuple of (asset.upper(), timeframe.lower(), expiry_ts or 0.0)
        If expiry is in the past AND was parsed (not explicitly provided), returns 0.0
        to trigger GTC/IOC fallback. Explicit overrides are always respected.
    """
    asset = extract_asset_from_ticker(ticker) or ""
    tf = timeframe or get_series_timeframe_bucket(ticker)
    
    # Determine expiry with fallback chain
    if expiry_ts is not None:
        # Explicit override - respect it without validation
        exp = expiry_ts
    else:
        # Parse from ticker/market and validate
        exp = parse_expiry_from_ticker(ticker, market)
        if exp == 0.0 and market:
            exp = parse_expiry_from_ticker("", market)  # Try market-only fallback
        
        # Validate parsed expiry is in the future (otherwise triggers GTC/IOC fallback)
        if exp > 0 and not is_expiry_valid(exp):
            exp = 0.0
    
    return asset.upper(), tf.lower(), exp


def group_id_from_ticker(
    ticker: str,
    *,
    timeframe: str | None = None,
    expiry_ts: float | None = None,
    market: Optional[dict] = None,
) -> str:
    """Generate canonical group ID from ticker with consistent normalization.
    
    This is the single source of truth for group ID generation across
    order_router, trading, and risk manager code paths.
    
    Args:
        ticker: Kalshi market ticker
        timeframe: Optional override (uses get_series_timeframe_bucket if not provided)
        expiry_ts: Optional override (parses from ticker/market if not provided)
        market: Optional market dict for expiry fallback
    
    Returns:
        Canonical group ID string (e.g., "BTC-15m-2026-03-27T15:00")
        If expiry is in the past, uses 0.0 which produces "unknown" suffix.
    """
    asset, tf, exp = canonicalize_group_components(
        ticker, timeframe=timeframe, expiry_ts=expiry_ts, market=market
    )
    if not asset:
        return ""  # Cannot form valid group ID without asset
    return generate_group_id(asset, tf, exp)


# ── Configuration ────────────────────────────────────────────────────────

@dataclass
class MarketFilterConfig:
    """Quality gates for market selection."""

    # Minimum volume (contracts traded) to consider a market
    min_volume: int = 50

    # Minimum open interest (contracts outstanding)
    min_open_interest: int = 10

    # Maximum bid-ask spread in cents (e.g. 8 = max 8c spread)
    # 2026-07-11: Use dynamic threshold manager for regime-aware spread thresholds
    max_spread_cents: int = 75  # Fallback, will be overridden by dynamic thresholds

    # Minimum best-bid price (filter out near-zero contracts)
    # 2026-07-11: Canonical price band (10c) - aligned with GlobalSlotAllocator
    min_price_cents: int = 10

    # Maximum best-bid price (filter out near-certain contracts)
    # 2026-07-12: Canonical price band (75c) - expanded for market conditions
    max_price_cents: int = 75

    # Only include markets for these underlyings.
    # Empty list = allow all underlyings (full Kalshi platform coverage).
    allowed_underlyings: List[str] = field(
        default_factory=lambda: []
    )

    # Only include these timeframes.
    # Empty list = allow all timeframes (daily, weekly, monthly, etc.).
    allowed_timeframes: List[str] = field(
        default_factory=lambda: []
    )

    # Overlap window: markets within this many seconds of each other
    # are considered overlapping (same risk bucket)
    overlap_window_seconds: int = 3600


DEFAULT_FILTER_CONFIG = MarketFilterConfig()


# ── Market candidate ─────────────────────────────────────────────────────

@dataclass
class MarketCandidate:
    """A market that has passed or is being evaluated by the filter."""
    ticker: str
    underlying: str         # e.g. "BTC", "ETH"
    timeframe: str          # e.g. "hourly", "15m"
    expiry_ts: float = 0.0  # epoch seconds
    volume: int = 0
    open_interest: int = 0
    best_bid_cents: int = 0
    best_ask_cents: int = 0
    spread_cents: int = 0
    mid_price_cents: int = 0
    category: str = ""
    # Fields for spot/strike enrichment (used by continuous trader)
    spot: float = 0.0
    strike: float = 0.0
    is_directional: bool = False
    # Group ID for risk aggregation (asset-timeframe-overlap window)
    group_id: str = ""  # e.g., "BTC-15m-2026-03-27T15:00"
    # Orderbook + edge enrichment (continuous trader, selectors, dry-run tracing)
    best_yes_bid: Optional[float] = None
    best_yes_ask: Optional[float] = None
    best_no_bid: Optional[float] = None
    best_no_ask: Optional[float] = None
    model_yes_prob: Optional[Decimal] = None
    implied_yes_prob: Optional[Decimal] = None
    yes_edge: Optional[Decimal] = None
    no_edge: Optional[Decimal] = None
    best_side: str = ""
    best_edge: Decimal = field(default_factory=lambda: Decimal("0"))
    limit_price_cents: int = 0

    @property
    def has_book(self) -> bool:
        return self.best_bid_cents > 0 and self.best_ask_cents > 0

    @property
    def asset(self) -> str:
        """Alias for underlying - used by continuous trader and other consumers."""
        return self.underlying

    @property
    def close_time(self) -> str:
        """ISO8601 expiry for time-to-expiry / edge models; empty when unknown."""
        ts = float(self.expiry_ts or 0.0)
        if ts <= 0:
            return ""
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "underlying": self.underlying,
            "timeframe": self.timeframe,
            "expiry_ts": self.expiry_ts,
            "volume": self.volume,
            "open_interest": self.open_interest,
            "best_bid_cents": self.best_bid_cents,
            "best_ask_cents": self.best_ask_cents,
            "spread_cents": self.spread_cents,
            "mid_price_cents": self.mid_price_cents,
            "spot": self.spot,
            "strike": self.strike,
            "is_directional": self.is_directional,
            "group_id": self.group_id,
            "best_side": self.best_side,
            "best_edge": str(self.best_edge),
            "limit_price_cents": self.limit_price_cents,
        }


@dataclass
class FilterResult:
    """Result of filtering a set of markets."""
    total_input: int = 0
    passed: int = 0
    rejected_volume: int = 0
    rejected_oi: int = 0
    rejected_spread: int = 0
    rejected_price: int = 0
    rejected_underlying: int = 0
    rejected_timeframe: int = 0
    candidates: List[MarketCandidate] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_input": self.total_input,
            "passed": self.passed,
            "rejected_volume": self.rejected_volume,
            "rejected_oi": self.rejected_oi,
            "rejected_spread": self.rejected_spread,
            "rejected_price": self.rejected_price,
            "rejected_underlying": self.rejected_underlying,
            "rejected_timeframe": self.rejected_timeframe,
            "candidates": [c.to_dict() for c in self.candidates],
        }


# ── Overlap group ────────────────────────────────────────────────────────

@dataclass
class OverlapGroup:
    """Group of temporally overlapping markets on the same underlying."""
    underlying: str
    markets: List[MarketCandidate] = field(default_factory=list)
    combined_volume: int = 0
    combined_oi: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "underlying": self.underlying,
            "market_count": len(self.markets),
            "tickers": [m.ticker for m in self.markets],
            "combined_volume": self.combined_volume,
            "combined_oi": self.combined_oi,
        }


# ── Market filter ────────────────────────────────────────────────────────

class MarketFilter:
    """Filters and groups Kalshi crypto markets by quality criteria."""

    def __init__(self, config: Optional[MarketFilterConfig] = None) -> None:
        self._config = config or DEFAULT_FILTER_CONFIG

    @property
    def config(self) -> MarketFilterConfig:
        return self._config

    def evaluate(self, market: MarketCandidate) -> Tuple[bool, str]:
        """Evaluate a single market against all quality gates.

        Returns:
            (passed, rejection_reason) — reason is empty if passed.
        """
        cfg = self._config

        # Underlying check — empty list means allow all underlyings
        if cfg.allowed_underlyings and market.underlying.upper() not in [u.upper() for u in cfg.allowed_underlyings]:
            return False, f"underlying {market.underlying} not allowed"

        # Timeframe check — empty list means allow all timeframes
        if market.timeframe and cfg.allowed_timeframes:
            if market.timeframe.lower() not in [t.lower() for t in cfg.allowed_timeframes]:
                return False, f"timeframe {market.timeframe} not allowed"

        # Volume floor
        if market.volume < cfg.min_volume:
            return False, f"volume {market.volume} < {cfg.min_volume}"

        # Open interest floor
        if market.open_interest < cfg.min_open_interest:
            return False, f"OI {market.open_interest} < {cfg.min_open_interest}"

        # Spread check (only if book data available)
        if market.has_book:
            spread = market.best_ask_cents - market.best_bid_cents
            if spread > cfg.max_spread_cents:
                return False, f"spread {spread}c > {cfg.max_spread_cents}c"

        # Price range check
        mid = market.mid_price_cents
        if mid > 0:
            if mid < cfg.min_price_cents:
                return False, f"price {mid}c < {cfg.min_price_cents}c"
            if mid > cfg.max_price_cents:
                return False, f"price {mid}c > {cfg.max_price_cents}c"

        return True, ""

    def filter_markets(
        self, markets: List[MarketCandidate],
    ) -> FilterResult:
        """Filter a list of markets and return qualifying candidates.

        Args:
            markets: Raw market candidates to evaluate.

        Returns:
            FilterResult with passed candidates and rejection counts.
        """
        result = FilterResult(total_input=len(markets))
        cfg = self._config

        for market in markets:
            passed, reason = self.evaluate(market)
            if passed:
                result.candidates.append(market)
                result.passed += 1
            else:
                if "volume" in reason:
                    result.rejected_volume += 1
                elif "OI" in reason:
                    result.rejected_oi += 1
                elif "spread" in reason:
                    result.rejected_spread += 1
                elif "price" in reason:
                    result.rejected_price += 1
                elif "underlying" in reason:
                    result.rejected_underlying += 1
                elif "timeframe" in reason:
                    result.rejected_timeframe += 1

        return result

    def group_overlapping(
        self, markets: List[MarketCandidate],
    ) -> List[OverlapGroup]:
        """Group temporally overlapping markets by underlying.

        Markets on the same underlying with expiry times within
        `overlap_window_seconds` of each other are grouped together.
        These groups represent a single combined risk bucket.

        Args:
            markets: Filtered market candidates (should already pass quality gates).

        Returns:
            List of OverlapGroup, each containing markets that overlap.
        """
        window = self._config.overlap_window_seconds

        # Group by underlying first
        by_underlying: Dict[str, List[MarketCandidate]] = {}
        for m in markets:
            key = m.underlying.upper()
            by_underlying.setdefault(key, []).append(m)

        groups: List[OverlapGroup] = []

        for underlying, mkts in by_underlying.items():
            # Sort by expiry
            sorted_mkts = sorted(mkts, key=lambda m: m.expiry_ts)

            current_group: Optional[OverlapGroup] = None

            for m in sorted_mkts:
                if current_group is None:
                    current_group = OverlapGroup(underlying=underlying)
                    current_group.markets.append(m)
                else:
                    # Check if this market overlaps with the last in the group
                    last_expiry = current_group.markets[-1].expiry_ts
                    if m.expiry_ts > 0 and last_expiry > 0 and abs(m.expiry_ts - last_expiry) <= window:
                        current_group.markets.append(m)
                    else:
                        # Finalize current group
                        current_group.combined_volume = sum(x.volume for x in current_group.markets)
                        current_group.combined_oi = sum(x.open_interest for x in current_group.markets)
                        groups.append(current_group)
                        current_group = OverlapGroup(underlying=underlying)
                        current_group.markets.append(m)

            if current_group and current_group.markets:
                current_group.combined_volume = sum(x.volume for x in current_group.markets)
                current_group.combined_oi = sum(x.open_interest for x in current_group.markets)
                groups.append(current_group)

        return groups

    def summary(self, markets: List[MarketCandidate]) -> Dict[str, Any]:
        """Filter markets and return a full summary with overlap groups."""
        result = self.filter_markets(markets)
        groups = self.group_overlapping(result.candidates)
        return {
            "filter": result.to_dict(),
            "overlap_groups": [g.to_dict() for g in groups],
            "total_groups": len(groups),
        }


# ── Near-Spot Selection (post-quality filter) ───────────────────────────

@dataclass
class EnrichedCandidate:
    """MarketCandidate enriched with spot, strike, distance, and edge."""
    candidate: MarketCandidate
    spot: float
    strike: float
    distance_abs: float
    edge: Decimal
    direction: Direction  # ABOVE_SPOT, BELOW_SPOT, AT_SPOT, DIRECTIONAL

    @property
    def underlying(self) -> str:
        return self.candidate.underlying

    @property
    def timeframe(self) -> str:
        return self.candidate.timeframe


def parse_strike_from_ticker(ticker: str) -> Optional[float]:
    """Parse strike price from Kalshi ticker formats.

    Handles:
    - Threshold: KXBTC-26MAR2501-T80199.99 → 80199.99
    - Bracket: KXBTC-26MAR2501-B80150 → 80150.0
    - Legacy: KXBTC-26MAR-T95000 → 95000.0
    - Directional 15m: KXBTC15M-26MAR250015-15 → None (no strike)
    """
    # Primary: -T or -B followed by a number at end of ticker
    m = re.search(r"-[TB](\d+(?:\.\d+)?)$", ticker)
    if m:
        return float(m.group(1))
    return None


# ── Direction alignment with edge engine ────────────────────────────────

class Direction(str, Enum):
    """Market direction relative to spot — aligns with edge engine's YES/NO decision.
    
    Edge engine logic (from continuous trader):
    - For strike > spot (above spot): YES = "event happens" = price goes above strike
      → This is the natural "call" direction; model predicts YES probability
    - For strike < spot (below spot): NO = "event doesn't happen" = price stays below
      → This is the natural "put" direction; model predicts NO probability
    - Directional markets: indicator stack bias determines YES/NO preference
    
    Bucketing by direction ensures we pick best edge within each "moneyness" zone.
    """
    ABOVE_SPOT = "above"   # Strike > spot, natural YES bias (call/T)
    BELOW_SPOT = "below"   # Strike < spot, natural NO bias (put/B)
    AT_SPOT = "atm"        # Strike == spot (rare)
    DIRECTIONAL = "directional"  # Up/down markets without strikes


def infer_direction_from_strike(
    strike: float, 
    spot: float, 
    is_directional: bool = False,
    threshold_epsilon: float = 0.0001,
) -> Direction:
    """Infer market direction from strike vs spot — aligns with edge engine.

    The edge engine (_compute_edge in continuous trader) decides YES vs NO based on:
    - For strikes ABOVE spot: model predicts probability of reaching that strike
      → Natural YES play (you win if price goes above strike)
    - For strikes BELOW spot: model predicts probability of staying below
      → Natural NO play (you win if price stays below strike)
    - Directional markets: indicator stack determines bias

    Returns Direction.ABOVE_SPOT, BELOW_SPOT, AT_SPOT, or DIRECTIONAL.
    """
    if is_directional:
        return Direction.DIRECTIONAL
    
    diff = strike - spot
    if abs(diff) < threshold_epsilon:
        return Direction.AT_SPOT
    if diff > 0:
        return Direction.ABOVE_SPOT  # Natural YES side
    return Direction.BELOW_SPOT    # Natural NO side


# ── Sample ticker → strike mapping (for verification) ───────────────────

SAMPLE_TICKER_STRIKES: Dict[str, Optional[float]] = {
    # BTC patterns
    "KXBTC-26MAR2501-T80199.99": 80199.99,   # Threshold above spot
    "KXBTC-26MAR2501-B80150.00": 80150.00,   # Bracket below spot
    "KXBTC-15M-26MAR250115-15": None,        # 15m directional (no strike)
    "KXBTC15M-26MAR250115-15": None,         # Alternative 15m format
    
    # ETH patterns  
    "KXETH-26MAR2501-T4200.50": 4200.50,     # Threshold
    "KXETH-26MAR2501-B4100.00": 4100.00,     # Bracket
    "KXETH-1H-26MAR250101-01": None,         # 1h directional
    
    # SOL, XRP, DOGE patterns
    "KXSOL-26MAR2501-T180.00": 180.00,
    "KXXRP-26MAR2501-T2.50": 2.50,
    "KXDOGE-26MAR2501-T0.25": 0.25,
    "KXDOGE-26MAR2501-B0.20": 0.20,
    
    # Edge cases to reject (time markers, not strikes)
    "KXBTC15M-26MAR250015-15": None,         # -15 is time marker
    "KXETH1H-26MAR250101-01": None,          # -01 is time marker
}


def enrich_candidates(
    candidates: List[MarketCandidate],
    get_spot: Callable[[str], float],
    compute_edge: Callable[[MarketCandidate, float, float], Decimal],
) -> List[EnrichedCandidate]:
    """Enrich quality-filtered candidates with spot, strike, and distance.

    Args:
        candidates: Markets that passed quality filters.
        get_spot: Callable that returns spot price for underlying (e.g., BTC).
        compute_edge: Callable that returns edge given candidate, spot, strike.

    Returns:
        List of EnrichedCandidate with distance_abs and edge attached.
    """
    enriched: List[EnrichedCandidate] = []

    for c in candidates:
        spot = get_spot(c.underlying)
        if not spot or spot <= 0:
            logger.debug("Skipping %s: no spot for %s (got %r)", c.ticker, c.underlying, spot)
            continue

        strike = parse_strike_from_ticker(c.ticker)
        if strike is None:
            # Directional markets (up/down) - treat as zero distance
            strike = spot
            is_directional = True
        else:
            is_directional = False

        distance = abs(strike - spot)
        edge = compute_edge(c, spot, strike)
        direction = infer_direction_from_strike(strike, spot, is_directional)

        enriched.append(EnrichedCandidate(
            candidate=c,
            spot=spot,
            strike=strike,
            distance_abs=distance,
            edge=edge,
            direction=direction,
        ))

    return enriched


def select_near_spot_best_edge(
    candidates: List[MarketCandidate],
    get_spot: Callable[[str], float],
    compute_edge: Callable[[MarketCandidate, float, float], Decimal],
    max_per_bucket: int = 2,
    max_distance_pct: Optional[float] = None,
    min_edge: Optional[Decimal] = None,
    use_tiered_min_edge: bool = False,
    use_tiered_max_price: bool = False,
    use_price_bands: bool = False,
    per_asset_max_distance_pct: Optional[Dict[Tuple[str, str], float]] = None,
    dynamic_max_price_calc: Optional[Any] = None,  # DYNAMIC PRICING v10: Real-time calculator
) -> List[MarketCandidate]:
    """Select nearest-to-spot markets with best edge per (underlying, timeframe, direction).

    This function sits AFTER quality filters (liquidity, spread, etc.) and picks
    the "as close as possible on the money with best edge" contracts.

    Buckets by (underlying, timeframe, direction), filters by:
    - per_asset_max_distance_pct: per-(asset,tf) distance dict (e.g. {("BTC","15m"):0.20}).
      Falls back to max_distance_pct when key missing; None = no global limit.
    - max_distance_pct: global fallback when per_asset_max_distance_pct is None/missing.
    - min_edge: drop candidates with edge below threshold (e.g. Decimal("0.05"))
    - use_tiered_min_edge: when True, uses per-(asset,timeframe) thresholds from MIN_EDGE_GRID
    - use_tiered_max_price: when True, uses per-(asset,timeframe) max prices from MAX_PRICE_GRID
    - use_price_bands: when True, applies per-(asset,tf) PRICE_BANDS (min/max contract price)

    Then sorts by:
    1. Distance to spot (ascending - closest first)
    2. Edge (descending - best edge first)

    Then takes top `max_per_bucket` from each bucket.

    Args:
        candidates: Quality-filtered MarketCandidates.
        get_spot: Callable(underlying) -> spot price.
        compute_edge: Callable(candidate, spot, strike) -> Decimal edge.
        max_per_bucket: Max candidates to keep per (underlying, tf, dir) bucket.
        max_distance_pct: Global fallback max distance from spot as fraction.
                          None = no global limit (rely on per_asset_max_distance_pct).
        min_edge: Minimum edge threshold. None = no edge filter.
                  Ignored when use_tiered_min_edge=True.
        use_tiered_min_edge: When True, uses MIN_EDGE_GRID thresholds per asset/tf.
                             Falls back to global MIN_EDGE_GLOBAL_FLOOR if asset/tf not found.
        use_tiered_max_price: When True, uses MAX_PRICE_GRID max prices per asset/tf.
                              Rejects candidates with mid_price_cents > tiered max.
                              Falls back to MAX_PRICE_GLOBAL_FALLBACK if asset/tf not found.
        use_price_bands: When True, applies PRICE_BANDS (min AND max contract price)
                         per (asset, timeframe). Rejects outside-band candidates before
                         edge/sizing. Falls back to PRICE_BANDS_DEFAULT when not found.
        per_asset_max_distance_pct: Optional dict mapping (asset, timeframe) → max distance
                                    fraction. Overrides max_distance_pct per bucket.

    Returns:
        Final list of MarketCandidates to evaluate for sizing/execution.

    Example::

        quality = filter.filter_markets(raw_markets).candidates
        final = select_near_spot_best_edge(
            quality,
            get_spot=lambda u: spot_stack.get(u, 0),
            compute_edge=lambda c, s, k: edge_engine.compute(c, s, k),
            max_per_bucket=2,
            max_distance_pct=0.125,  # ±12.5% band
            use_tiered_min_edge=True,  # Use asset/tf specific thresholds
            use_tiered_max_price=True,  # Use asset/tf specific max prices
        )
        # final now contains ~1-2 nearest strikes per (asset, tf, dir)
    """
    if not candidates:
        return []

    # Step 1: Enrich with spot, strike, distance, edge
    enriched = enrich_candidates(candidates, get_spot, compute_edge)
    logger.info("Enriched %d candidates with spot/strike/edge", len(enriched))

    # Step 1a: Pre-scan price_bands to find buckets that would be zeroed.
    # Safe-fallback: if ALL candidates in a (asset, tf) bucket would be dropped
    # by the price_band filter, skip the filter for that bucket entirely and warn.
    # This prevents a misconfigured or market-regime-shifted band from silently
    # zeroing an entire asset/timeframe (the "all-market dropout" bug).
    _price_bands_skip_buckets: set = set()
    if use_price_bands:
        from collections import defaultdict as _dd
        _bucket_total: Dict[tuple, int] = _dd(int)
        _bucket_pass: Dict[tuple, int] = _dd(int)
        for _e in enriched:
            _key = (_e.underlying.upper(), get_series_timeframe_bucket(_e.candidate.ticker))
            _bucket_total[_key] += 1
            _bmin, _bmax = get_price_band(_e.underlying.upper(), _e.candidate.ticker)
            _mid = _e.candidate.mid_price_cents
            if _mid > 0 and round(_bmin * 100) <= _mid <= round(_bmax * 100):
                _bucket_pass[_key] += 1
        for _key, _total in _bucket_total.items():
            if _bucket_pass.get(_key, 0) == 0:
                _price_bands_skip_buckets.add(_key)
                logger.warning(
                    "price_bands safe-fallback: all %d candidates in bucket (%s/%s) "
                    "fall outside band — filter bypassed for this bucket",
                    _total, _key[0], _key[1],
                )

    # Step 1b: Apply distance, edge, and price filters
    filtered: List[EnrichedCandidate] = []
    dropped_distance = 0
    dropped_edge = 0
    dropped_price = 0
    dropped_price_band = 0

    for e in enriched:
        asset_upper = e.underlying.upper()
        tf_bucket = get_series_timeframe_bucket(e.candidate.ticker)

        # Distance filter: per-asset/tf band first, fall back to global max_distance_pct
        if per_asset_max_distance_pct is not None:
            effective_dist_pct = per_asset_max_distance_pct.get(
                (asset_upper, tf_bucket), max_distance_pct
            )
        else:
            effective_dist_pct = max_distance_pct

        if effective_dist_pct is not None and effective_dist_pct > 0 and e.spot > 0:
            max_dist_abs = effective_dist_pct * e.spot
            if e.distance_abs > max_dist_abs:
                dropped_distance += 1
                logger.debug(
                    "Dropping %s: distance %.2f > max %.2f (%.1f%% of spot %.2f) [%s/%s band]",
                    e.candidate.ticker, e.distance_abs, max_dist_abs,
                    effective_dist_pct * 100, e.spot, asset_upper, tf_bucket,
                )
                continue

        # Contract price band filter (per-asset/tf, applied BEFORE edge/sizing)
        # Skipped for buckets identified in the pre-scan as would-be-zeroed.
        if use_price_bands and (asset_upper, tf_bucket) not in _price_bands_skip_buckets:
            band_min, band_max = get_price_band(asset_upper, e.candidate.ticker)
            # Use round() to avoid float precision issues (e.g. 0.08*100 = 7.9999… → 7)
            band_min_cents = round(band_min * 100)
            band_max_cents = round(band_max * 100)
            mid_price = e.candidate.mid_price_cents
            if mid_price <= 0:
                # Degenerate book — no bid and no ask, can't price the contract
                dropped_price_band += 1
                logger.debug(
                    "Dropping %s: mid_price=%dc (degenerate book) [%s/%s]",
                    e.candidate.ticker, mid_price, asset_upper, tf_bucket,
                )
                continue
            if mid_price < band_min_cents or mid_price > band_max_cents:
                dropped_price_band += 1
                logger.debug(
                    "Dropping %s: mid_price %dc outside price_band=(%dc, %dc) [%s/%s]",
                    e.candidate.ticker, mid_price, band_min_cents, band_max_cents,
                    asset_upper, tf_bucket,
                )
                continue
            logger.debug(
                "  %s: price_band=(%dc, %dc) mid=%dc PASS [%s/%s]",
                e.candidate.ticker, band_min_cents, band_max_cents, mid_price,
                asset_upper, tf_bucket,
            )

        # Max price filter: tiered max price cap (legacy upper bound, still active)
        # DYNAMIC PRICING v10: Use real-time calculator if provided, else fall back to static grid
        if use_tiered_max_price:
            # Try dynamic calculator first (WebSocket-driven, ATR-adjusted)
            if dynamic_max_price_calc is not None:
                try:
                    max_price_cents = dynamic_max_price_calc.calculate(
                        asset=e.underlying,
                        ticker=e.candidate.ticker,
                        timeframe=tf_bucket,
                    )
                except Exception:
                    # Fallback to static grid on calculator error
                    max_price_cents = get_tiered_max_price(e.underlying, e.candidate.ticker)
            else:
                # Static tiered pricing (no WebSocket data available)
                max_price_cents = get_tiered_max_price(e.underlying, e.candidate.ticker)
            
            mid_price = e.candidate.mid_price_cents
            if mid_price > 0 and mid_price > max_price_cents:
                dropped_price += 1
                logger.debug(
                    "Dropping %s: mid_price %dc > max %dc (%s/%s) [dynamic=%s]",
                    e.candidate.ticker, mid_price, max_price_cents,
                    e.underlying.upper(), tf_bucket,
                    dynamic_max_price_calc is not None,
                )
                continue

        # Edge filter: minimum edge threshold
        if use_tiered_min_edge:
            # Per-asset/timeframe tiered threshold from MIN_EDGE_GRID
            candidate_min_edge = get_tiered_min_edge(e.underlying, e.candidate.ticker)
            if e.edge < candidate_min_edge:
                dropped_edge += 1
                logger.debug(
                    "Dropping %s: edge %.4f < tiered min %.4f (%s/%s)",
                    e.candidate.ticker, e.edge, candidate_min_edge,
                    e.underlying.upper(), tf_bucket,
                )
                continue
        elif min_edge is not None:
            if e.edge < min_edge:
                dropped_edge += 1
                logger.debug(
                    "Dropping %s: edge %.4f < flat min %.4f",
                    e.candidate.ticker, e.edge, min_edge,
                )
                continue

        filtered.append(e)

    if dropped_distance or dropped_edge or dropped_price or dropped_price_band:
        logger.info(
            "Post-enrichment filters: dropped %d (distance), %d (edge), %d (max_price), "
            "%d (price_band), kept %d",
            dropped_distance, dropped_edge, dropped_price, dropped_price_band, len(filtered),
        )

    enriched = filtered
    if not enriched:
        logger.warning("All candidates dropped by distance/edge filters")
        return []

    # Step 2: Bucket by (underlying, timeframe, direction)
    buckets: Dict[Tuple[str, str, Direction], List[EnrichedCandidate]] = {}
    for e in enriched:
        key = (e.underlying.upper(), e.timeframe.lower(), e.direction)
        buckets.setdefault(key, []).append(e)

    # Step 3: Per bucket, sort by distance (asc), then edge (desc), take top N
    final: List[MarketCandidate] = []
    stats_by_bucket: Dict[str, int] = {}

    for (underlying, tf, direction), bucket in buckets.items():
        # Sort: closest to spot first, then best edge
        bucket.sort(key=lambda x: (x.distance_abs, -x.edge))

        selected = bucket[:max_per_bucket]
        for s in selected:
            final.append(s.candidate)

        bucket_key = f"{underlying}/{tf}/{direction.value}"
        stats_by_bucket[bucket_key] = len(selected)

        logger.debug(
            "Bucket %s: %d candidates, selected %d (nearest: %s @ %.2f from %.2f)",
            bucket_key,
            len(bucket),
            len(selected),
            selected[0].candidate.ticker if selected else "none",
            selected[0].distance_abs if selected else 0,
            selected[0].spot if selected else 0,
        )

    logger.info(
        "Near-spot selection: %d buckets, %d final candidates from %d enriched",
        len(buckets), len(final), len(enriched),
    )
    return final


class NearSpotSelector:
    """Stateful selector that caches spot lookups for batch enrichment.

    Usage::
        selector = NearSpotSelector(spot_source=spot_stack.get)
        final = selector.select_near_spot(candidates, edge_fn, max_per_bucket=2)
    """

    def __init__(self, spot_source: Callable[[str], float]) -> None:
        self._get_spot = spot_source
        self._spot_cache: Dict[str, float] = {}
        self._cycle_count: int = 0

    def _cached_spot(self, underlying: str) -> float:
        if underlying not in self._spot_cache:
            self._spot_cache[underlying] = self._get_spot(underlying)
        return self._spot_cache[underlying]

    def select_near_spot(
        self,
        candidates: List[MarketCandidate],
        compute_edge: Callable[[MarketCandidate, float, float], Decimal],
        max_per_bucket: int = 2,
        max_distance_pct: Optional[float] = None,
        min_edge: Optional[Decimal] = None,
        use_tiered_min_edge: bool = False,
        use_tiered_max_price: bool = False,
        use_price_bands: bool = False,
        per_asset_max_distance_pct: Optional[Dict[Tuple[str, str], float]] = None,
    ) -> List[MarketCandidate]:
        """Select nearest-to-spot with best edge, caching spot lookups."""
        self._cycle_count += 1
        self._spot_cache.clear()
        return select_near_spot_best_edge(
            candidates,
            get_spot=self._cached_spot,
            compute_edge=compute_edge,
            max_per_bucket=max_per_bucket,
            max_distance_pct=max_distance_pct,
            min_edge=min_edge,
            use_tiered_min_edge=use_tiered_min_edge,
            use_tiered_max_price=use_tiered_max_price,
            use_price_bands=use_price_bands,
            per_asset_max_distance_pct=per_asset_max_distance_pct,
        )

    def log_cycle_summary(
        self,
        enriched: List[EnrichedCandidate],
        final: List[MarketCandidate],
        assets: Optional[List[str]] = None,
    ) -> None:
        """Log summary stats per cycle to confirm ATM hugging.

        Logs: bucket count, avg distance per asset, top/median edge per asset.
        """
        if not enriched:
            logger.info("[NearSpot cycle=%d] No enriched candidates", self._cycle_count)
            return

        # Group by asset
        by_asset: Dict[str, List[EnrichedCandidate]] = {}
        for e in enriched:
            by_asset.setdefault(e.underlying.upper(), []).append(e)

        # Distance and edge stats per asset
        lines: List[str] = []
        for asset in (assets or sorted(by_asset.keys())):
            asset_enriched = by_asset.get(asset, [])
            if not asset_enriched:
                continue

            distances = [e.distance_abs for e in asset_enriched]
            edges = [float(e.edge) for e in asset_enriched]

            avg_dist = sum(distances) / len(distances) if distances else 0.0
            max_edge = max(edges) if edges else 0.0
            median_edge = sorted(edges)[len(edges) // 2] if edges else 0.0

            # Count directional buckets for this asset
            asset_buckets = set(
                (e.underlying.upper(), e.timeframe.lower(), e.direction)
                for e in asset_enriched
            )

            lines.append(
                f"{asset}: buckets={len(asset_buckets)}, "
                f"avg_dist={avg_dist:.2f}, max_edge={max_edge:.4f}, median_edge={median_edge:.4f}"
            )

        logger.info(
            "[NearSpot cycle=%d] final=%d enriched=%d | %s",
            self._cycle_count,
            len(final),
            len(enriched),
            " | ".join(lines),
        )
