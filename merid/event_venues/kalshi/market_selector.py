"""Kalshi Market Selector — Maps agents to specific Kalshi prediction market series.

Each agent subscribes to a specific Kalshi series defined by coin + frequency.
Series codes follow the Kalshi convention (verified from kalshi.com/category/crypto):
  - KXBTC15M  → BTC 15-minute (series_ticker on Kalshi API)
  - KXBTC     → BTC hourly (no suffix)
  - KXBTCD1   → BTC daily
  - KXBTCW1   → BTC weekly

Usage::

    from merid.event_venues.kalshi.market_selector import (
        get_agent_market_tickers,
        resolve_series_ticker,
        AGENT_SERIES_MAP,
    )

    tickers = await get_agent_market_tickers("BTC_15M")
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from config.kalshi_universe import KALSHI_CRYPTO_PRODUCTS as _KCP
from merid.event_venues.kalshi.constants import ALL_CRYPTO_ASSETS
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.market_selector")

# ── Canonical Kalshi series prefixes per coin ─────────────────────────────
# Source: collector.py + Kalshi docs
# https://kalshi.com/category/crypto/frequency/fifteen_min

CRYPTO_SERIES_BASE: Dict[str, str] = {
    "BTC": "KXBTC",
    "ETH": "KXETH",
    "SOL": "KXSOL",
    "XRP": "KXXRP",
    "DOGE": "KXDOGE",
}

# ── Timeframe → series suffix ─────────────────────────────────────────────
# Real Kalshi format: no dashes. 15m = "15M", hourly = "" (no suffix),
# daily = "D1", weekly = "W1", monthly = "M1".

TIMEFRAME_SERIES_SUFFIX: Dict[str, str] = {
    "15m": "15M",
    "1h": "",          # hourly = base series, no suffix
    "hourly": "",
    "daily": "D1",
    "weekly": "W1",
    "monthly": "M1",
}

ALL_COINS = list(ALL_CRYPTO_ASSETS)
ALL_TIMEFRAMES = ["15m", "1h", "daily", "weekly", "monthly"]


def resolve_series_ticker(coin: str, timeframe: str) -> str:
    """Build the Kalshi series ticker for a coin + timeframe.

    Examples:
        resolve_series_ticker("BTC", "15m")     → "KXBTC15M"
        resolve_series_ticker("ETH", "1h")      → "KXETH"
        resolve_series_ticker("SOL", "daily")   → "KXSOLD1"
        resolve_series_ticker("DOGE", "weekly") → "KXDOGEW1"
        resolve_series_ticker("BTC", "monthly") → "KXBTCM1"
    """
    base = CRYPTO_SERIES_BASE.get(coin.upper())
    if not base:
        raise ValueError(f"Unknown coin: {coin}. Known: {sorted(CRYPTO_SERIES_BASE)}")
    suffix = TIMEFRAME_SERIES_SUFFIX.get(timeframe.lower(), "")
    return f"{base}{suffix}"


def resolve_series_tickers_multi(
    coins: List[str],
    timeframes: List[str],
) -> List[str]:
    """Build series tickers for multiple coins × timeframes."""
    result = []
    for coin in coins:
        for tf in timeframes:
            try:
                result.append(resolve_series_ticker(coin, tf))
            except ValueError:
                pass
    return result


# ── Agent → Series mapping ────────────────────────────────────────────────
# Each agent maps to one or more Kalshi series tickers.
# The catalog uses these to discover live market IDs.

AGENT_SERIES_MAP: Dict[str, List[str]] = {
    # Per-coin 15m markets — from KALSHI_CRYPTO_PRODUCTS (canonical)
    "BTC_15M":    _KCP.get("BTC_15M",   ["KXBTC15M"]),
    "ETH_15M":    _KCP.get("ETH_15M",   ["KXETH15M"]),
    "SOL_15M":    _KCP.get("SOL_15M",   ["KXSOL15M"]),
    "XRP_15M":    _KCP.get("XRP_15M",   ["KXXRP15M"]),
    "DOGE_15M":   _KCP.get("DOGE_15M",  ["KXDOGE15M"]),

    # Per-coin hourly markets — from KALSHI_CRYPTO_PRODUCTS (canonical)
    "BTC_HOURLY":  _KCP.get("BTC_1H",   ["KXBTC"]),
    "ETH_HOURLY":  _KCP.get("ETH_1H",   ["KXETH"]),
    "SOL_HOURLY":  _KCP.get("SOL_1H",   ["KXSOL"]),
    "XRP_HOURLY":  _KCP.get("XRP_1H",   ["KXXRP"]),
    "DOGE_HOURLY": _KCP.get("DOGE_1H",  ["KXDOGE"]),

    # Daily and weekly series — price-level markets, canonical format TBD, unchanged
    "BTC_DAILY":  [resolve_series_ticker("BTC", "daily")],
    "BTC_WEEKLY": [resolve_series_ticker("BTC", "weekly")],

    "ETH_DAILY":  [resolve_series_ticker("ETH", "daily")],
    "ETH_WEEKLY": [resolve_series_ticker("ETH", "weekly")],

    "SOL_DAILY":  [resolve_series_ticker("SOL", "daily")],
    "SOL_WEEKLY": [resolve_series_ticker("SOL", "weekly")],

    "XRP_DAILY":  [resolve_series_ticker("XRP", "daily")],
    "XRP_WEEKLY": [resolve_series_ticker("XRP", "weekly")],

    "DOGE_DAILY":  [resolve_series_ticker("DOGE", "daily")],
    "DOGE_WEEKLY": [resolve_series_ticker("DOGE", "weekly")],

    # Market-making across all 15m crypto
    "CRYPTO_15M_MM": resolve_series_tickers_multi(ALL_COINS, ["15m"]),

    # Arbitrage scanner: all crypto markets, all frequencies
    "KALSHI_ARB_SCANNER": resolve_series_tickers_multi(ALL_COINS, ALL_TIMEFRAMES),

    # Directional macro — crypto daily only for now
    "MACRO_DIRECTIONAL": resolve_series_tickers_multi(ALL_COINS, ["daily"]),

    # Non-crypto directional agents — empty until those markets are wired
    "FINANCIALS_DIRECTIONAL": [],
    "POLITICS_DIRECTIONAL": [],
    "CLIMATE_DIRECTIONAL": [],
    "SPORTS_DIRECTIONAL": [],
    "TECH_DIRECTIONAL": [],

    # Sentiment agents: contrarian uses short timeframes
    "SENTIMENT_CONTRARIAN_CRYPTO": resolve_series_tickers_multi(
        ALL_COINS, ["15m", "1h"],
    ),
    "SENTIMENT_CONTRARIAN_MACRO": [],  # fill when non-crypto markets added

    # Regime switch uses longer timeframes
    "SENTIMENT_REGIME_SWITCH_CRYPTO": resolve_series_tickers_multi(
        ALL_COINS, ["daily", "weekly"],
    ),
    "SENTIMENT_REGIME_SWITCH_FINANCIALS": [],

    # Vol breakout: short timeframes
    "SENTIMENT_VOL_BREAKOUT_CRYPTO": resolve_series_tickers_multi(
        ALL_COINS, ["15m", "1h"],
    ),
    "SENTIMENT_VOL_BREAKOUT_GLOBAL": [],

    # Catch-all: every crypto series
    "KALSHI_CATCH_ALL": resolve_series_tickers_multi(ALL_COINS, ALL_TIMEFRAMES),
}


# ── Market discovery via catalog ──────────────────────────────────────────

async def get_agent_market_tickers(
    agent_name: str,
    *,
    series_tickers: Optional[List[str]] = None,
    min_volume: float = 0,
) -> List[str]:
    """Resolve an agent's series → live Kalshi market IDs via the catalog.

    1. Look up the agent's series tickers from AGENT_SERIES_MAP (or use provided)
    2. For each series, query the catalog for matching markets
    3. Return deduplicated list of market IDs (highest volume first)

    Args:
        agent_name: Agent name (e.g., "BTC_15M").
        series_tickers: Optional list of series tickers to use (defaults to AGENT_SERIES_MAP lookup).
        min_volume: Optional minimum volume filter.

    Returns:
        List of Kalshi market ticker strings.
    """
    # FIX 1: Use passed series_tickers, fallback to AGENT_SERIES_MAP
    series_list = series_tickers if series_tickers is not None else AGENT_SERIES_MAP.get(agent_name)
    
    if not series_list:
        logger.warning(f"No series configured for agent {agent_name}")
        return []

    if not series_list:
        logger.debug("Agent %s has empty series list (non-crypto)", agent_name)
        return []

    from merid.event_venues.kalshi.market_catalog import get_market_catalog
    catalog = get_market_catalog()

    # Ensure catalog is populated
    if not catalog.get_all_markets():
        await catalog.refresh()

    seen: set = set()
    results: list = []
    per_series_counts: Dict[str, int] = {}

    for series_ticker in series_list:
        # Search catalog for markets matching this series
        per_count = 0
        for cm in catalog.get_all_markets():
            raw = cm.market.raw_data or {}
            mkt_series = raw.get("series_ticker", "") or ""
            mkt_event = raw.get("event_ticker", "") or ""
            mkt_id = cm.market.market_id or ""

            # Match by series_ticker, event_ticker prefix, or market_id prefix
            matches = (
                mkt_series.upper().startswith(series_ticker.upper())
                or mkt_event.upper().startswith(series_ticker.upper())
                or mkt_id.upper().startswith(series_ticker.upper())
            )

            if matches:
                per_count += 1

            # Only include markets that pass the volume filter and are unseen
            if matches and mkt_id not in seen:
                vol = float(cm.market.volume) if cm.market.volume else 0
                if vol >= min_volume:
                    seen.add(mkt_id)
                    results.append((vol, mkt_id))

        per_series_counts[series_ticker] = per_count

    # Sort by volume descending
    results.sort(key=lambda x: x[0], reverse=True)
    tickers = [t for _, t in results]

    # Human-friendly summary log (keeps previous info but adds a clear
    # 'Series resolution' line to make debugging easier in logs).
    logger.info(
        "Agent %s: resolved %d series → %d live markets",
        agent_name, len(series_list), len(tickers),
    )

    # Fallback: if the in-memory catalog search yields nothing for the
    # requested series, attempt the Kalshi series-based discovery path
    # which queries the /series endpoint and then markets per-series.
    # This catches cases where the cached ticker index may be missing
    # series_ticker fields or when the REST series API exposes markets
    # not present in the cached listing.
    if not tickers and series_list:
        try:
            # Use the catalog's complementary discovery path
            _cms = await catalog.discover_crypto_via_series(min_volume=min_volume)
            if _cms:
                # deduplicate and preserve volume-sorted order from discovery
                _seen = set(tickers)
                for cm in _cms:
                    if cm.market.market_id not in _seen:
                        tickers.append(cm.market.market_id)
                        _seen.add(cm.market.market_id)
                logger.info(
                    "Series resolution: %s → %d markets from %d series",
                    agent_name, len(tickers), len(series_list),
                )
        except Exception as _exc:
            logger.debug("Series-discovery fallback failed for %s: %s", agent_name, _exc)

    # If nothing resolved, dump per-series counts for diagnostics
    if not tickers:
        try:
            logger.warning(
                "Series resolution detailed: agent=%s, series_counts=%s, catalog_markets=%d",
                agent_name, {k: int(v) for k, v in per_series_counts.items()}, len(catalog.get_all_markets()),
            )
        except Exception:
            # Best-effort: don't raise from logging
            pass

    return tickers


async def enable_kalshi_agent(agent_name: str, series_tickers: Optional[List[str]] = None) -> Dict[str, Any]:
    """Subscribe an agent to its Kalshi prediction markets.

    1. Resolve market IDs via get_agent_market_tickers
    2. Subscribe via WS bridge for live orderbook/trade data
    3. Return summary of what was subscribed

    Args:
        agent_name: Agent name (e.g., "BTC_15M").
        series_tickers: Optional list of series tickers to use instead of AGENT_SERIES_MAP lookup.

    Returns:
        Dict with agent_name, series, market_ids, subscribed count.
    """
    series_list = series_tickers if series_tickers is not None else AGENT_SERIES_MAP.get(agent_name, [])
    market_ids = await get_agent_market_tickers(agent_name, series_tickers=series_list)

    if not market_ids:
        logger.info(
            "enable_kalshi_agent(%s): no markets to subscribe (series=%s)",
            agent_name, series_list,
        )
        return {
            "agent_name": agent_name,
            "series": series_list,
            "market_ids": [],
            "subscribed": 0,
        }

    # Subscribe via WS bridge for live data
    ws_subscribed = 0
    try:
        from merid.event_venues.kalshi.ws_bridge import get_ws_bridge
        bridge = get_ws_bridge()
        if bridge.is_running():
            await bridge.subscribe(market_ids)
            ws_subscribed = len(market_ids)
        else:
            await bridge.start(tickers=market_ids)
            ws_subscribed = len(market_ids)
        logger.info(
            "enable_kalshi_agent(%s): WS subscribed to %d markets",
            agent_name, ws_subscribed,
        )
    except Exception as exc:
        logger.warning(
            "enable_kalshi_agent(%s): WS subscribe failed: %s", agent_name, exc,
        )

    return {
        "agent_name": agent_name,
        "series": series_list,
        "market_ids": market_ids,
        "subscribed": ws_subscribed,
    }


def validate_agent_series_map() -> List[str]:
    """Validate all series tickers in AGENT_SERIES_MAP for correctness.
    
    Returns:
        List of validation issues found (empty if all valid).
    """
    issues: List[str] = []
    
    for agent_name, series_list in AGENT_SERIES_MAP.items():
        if not series_list:
            continue  # Empty is valid for some agents
        
        for series_ticker in series_list:
            # Check format
            if not series_ticker.startswith('KX'):
                issues.append(f"{agent_name}: Invalid series format '{series_ticker}'")
            
            # Check for asset mismatches
            agent_upper = agent_name.upper()
            series_upper = series_ticker.upper()
            
            # DOGE should not map to XRP
            if 'DOGE' in agent_upper and 'XRP' in series_upper:
                issues.append(f"CRITICAL: {agent_name} mapped to XRP series: {series_ticker}")
            
            # XRP should not map to DOGE
            if 'XRP' in agent_upper and 'DOGE' in series_upper:
                issues.append(f"CRITICAL: {agent_name} mapped to DOGE series: {series_ticker}")
            
            # BTC should not map to other assets
            if 'BTC' in agent_upper and not any(x in series_upper for x in ['BTC', 'BITCOIN']):
                if any(x in series_upper for x in ['ETH', 'SOL', 'XRP', 'DOGE']):
                    issues.append(f"CRITICAL: {agent_name} mapped to wrong asset series: {series_ticker}")
            
            # Weekly agents shouldn't map to 15M series
            if 'WEEKLY' in agent_upper and '15M' in series_upper:
                issues.append(f"WARNING: {agent_name} (weekly) mapped to 15min series: {series_ticker}")
            
            # 15M agents shouldn't map to weekly series
            if '15M' in agent_upper and any(x in series_upper for x in ['W1', 'D1']):
                issues.append(f"WARNING: {agent_name} (15M) mapped to long-term series: {series_ticker}")
    
    return issues


# Run validation on module import
_validation_issues = validate_agent_series_map()
if _validation_issues:
    logger.error("AGENT_SERIES_MAP validation failed:")
    for issue in _validation_issues:
        logger.error(f"  - {issue}")
else:
    logger.info(f"Validated {len(AGENT_SERIES_MAP)} agent series mappings - all correct")
