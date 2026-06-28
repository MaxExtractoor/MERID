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

import os
from typing import Any, Callable, Dict, List, Optional

from config.kalshi_universe import KALSHI_CRYPTO_PRODUCTS as _KCP
from merid.event_venues.kalshi.constants import ALL_CRYPTO_ASSETS
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.market_selector")

# P0 FIX: Import scope filter functions from correct module (config.trading_scope)
# trading_scope.py has convenience functions, not standalone is_allowed_asset/is_15m_series_ticker
try:
    from config.trading_scope import (
        validate_asset_for_trading,
        validate_series_ticker_for_trading,
    )
    TRADING_SCOPE_AVAILABLE = True
    logger.info("[SCOPE-FILTER] trading_scope import successful, scope filtering enabled")
except ImportError as e:
    TRADING_SCOPE_AVAILABLE = False
    # Fail-closed in production: functions always return False to reject everything
    def validate_asset_for_trading(asset: str) -> bool:
        return False
    
    def validate_series_ticker_for_trading(ticker: str) -> bool:
        return False
    
    logger.error(f"[SCOPE-FILTER] trading_scope import failed ({e}), scope filtering DISABLED - rejecting all tickers")

# Keep constants from market_constraints for backward compatibility
from merid.event_venues.kalshi.market_constraints import (
    ALLOWED_TIMEFRAMES,
    ALLOWED_UNDERLYINGS,
    SERIES_PREFIX as CRYPTO_SERIES_BASE,
    TIMEFRAME_SUFFIX as TIMEFRAME_SERIES_SUFFIX,
)

# ── Canonical Kalshi series prefixes per coin ─────────────────────────────
# Source: collector.py + Kalshi docs
# https://kalshi.com/category/crypto/frequency/fifteen_min
# Import from centralized config module (imported above as CRYPTO_SERIES_BASE)

# ── Timeframe → series suffix ─────────────────────────────────────────────
# Real Kalshi format: no dashes. 15m = "15M", hourly = "" (no suffix),
# daily = "D1", weekly = "W1", monthly = "M1".
# Import from centralized config module (imported above as TIMEFRAME_SERIES_SUFFIX)

ALL_COINS = list(ALL_CRYPTO_ASSETS)
# PRODUCTION AUDIT (Step 3): Only 15m timeframe allowed for trading
ALL_TIMEFRAMES = ["15m"]


def resolve_series_ticker(coin: str, timeframe: str) -> str:
    """Build the Kalshi series ticker for a coin + timeframe.

    PRODUCTION AUDIT (Step 3): Only 15m timeframe and allowed assets (BTC/ETH/SOL/XRP/DOGE).

    Examples:
        resolve_series_ticker("BTC", "15m")     → "KXBTC15M"
        resolve_series_ticker("ETH", "15m")     → "KXETH15M"
        resolve_series_ticker("SOL", "15m")     → "KXSOL15M"
        resolve_series_ticker("XRP", "15m")     → "KXXRP15M"
        resolve_series_ticker("DOGE", "15m")    → "KXDOGE15M"
    """
    # PRODUCTION AUDIT: Enforce 15m timeframe only
    if timeframe.lower() != "15m":
        raise ValueError(
            f"Timeframe '{timeframe}' not allowed in production. Only '15m' is permitted."
        )
    
    # PRODUCTION AUDIT: Enforce allowed assets only
    allowed_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
    if coin.upper() not in allowed_assets:
        raise ValueError(
            f"Asset '{coin}' not allowed in production. Allowed: {sorted(allowed_assets)}"
        )
    
    base = CRYPTO_SERIES_BASE.get(coin.upper())
    if not base:
        raise ValueError(f"Unknown coin: {coin}. Known: {sorted(CRYPTO_SERIES_BASE)}")
    suffix = TIMEFRAME_SERIES_SUFFIX.get(timeframe.lower(), "")
    ticker = f"{base}{suffix}"
    
    # PRODUCTION AUDIT: Verify resulting ticker is in whitelist
    allowed_series = {"KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"}
    if ticker not in allowed_series:
        raise ValueError(
            f"Series ticker '{ticker}' not in production whitelist. Allowed: {sorted(allowed_series)}"
        )
    
    return ticker


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
    # PRODUCTION RESTRICTION: Only 5 15m crypto agents for BTC/ETH/SOL/XRP/DOGE 15m trading
    # All other agents have empty series lists (disabled for 15m crypto-only deployment)
    
    # Per-coin 15m markets — from KALSHI_CRYPTO_PRODUCTS (canonical)
    "BTC_15M":    _KCP.get("BTC_15M",   ["KXBTC15M"]),
    "ETH_15M":    _KCP.get("ETH_15M",   ["KXETH15M"]),
    "SOL_15M":    _KCP.get("SOL_15M",   ["KXSOL15M"]),
    "XRP_15M":    _KCP.get("XRP_15M",   ["KXXRP15M"]),
    "DOGE_15M":   _KCP.get("DOGE_15M",  ["KXDOGE15M"]),

    # DISABLED: Non-15m agents removed for 15m crypto-only deployment
    "BTC_DAILY":  [],
    "BTC_HOURLY":  [],
    "BTC_WEEKLY": [],
    "ETH_DAILY":  [],
    "ETH_HOURLY":  [],
    "ETH_WEEKLY": [],
    "SOL_DAILY":  [],
    "SOL_HOURLY":  [],
    "SOL_WEEKLY": [],
    "XRP_DAILY":  [],
    "XRP_HOURLY":  [],
    "XRP_WEEKLY": [],
    "DOGE_DAILY":  [],
    "DOGE_HOURLY":  [],
    "DOGE_WEEKLY": [],

    # DISABLED: Non-crypto agents removed for 15m crypto-only deployment
    "CRYPTO_15M_MM": [],
    "KALSHI_ARB_SCANNER": [],
    "MACRO_DIRECTIONAL": [],
    "FINANCIALS_DIRECTIONAL": [],
    "POLITICS_DIRECTIONAL": [],
    "CLIMATE_DIRECTIONAL": [],
    "SPORTS_DIRECTIONAL": [],
    "TECH_DIRECTIONAL": [],

    # DISABLED: Sentiment agents removed for 15m crypto-only deployment (sentiment stack deprecated)
    "SENTIMENT_CONTRARIAN_CRYPTO": [],
    "SENTIMENT_CONTRARIAN_MACRO": [],
    "SENTIMENT_REGIME_SWITCH_CRYPTO": [],
    "SENTIMENT_REGIME_SWITCH_FINANCIALS": [],
    "SENTIMENT_VOL_BREAKOUT_CRYPTO": [],
    "SENTIMENT_VOL_BREAKOUT_GLOBAL": [],
    "KALSHI_CATCH_ALL": [],
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

    # P1 FIX: Add timeout around catalog.refresh() to prevent indefinite blocking
    # Ensure catalog is populated
    if not catalog.get_all_markets():
        try:
            logger.info("[TICKER-RESOLUTION] Catalog empty, refreshing with 30s timeout")
            import asyncio
            await asyncio.wait_for(catalog.refresh(), timeout=30.0)
            logger.info("[TICKER-RESOLUTION] Catalog refresh completed")
        except asyncio.TimeoutError:
            logger.error("[TICKER-RESOLUTION] Catalog refresh timed out after 30s")
            return []  # Fail closed - no tickers
        except Exception as e:
            logger.error(f"[TICKER-RESOLUTION] Catalog refresh failed: {e}")
            return []

    seen: set = set()
    results: list = []
    per_series_counts: Dict[str, int] = {}

    for series_ticker in series_list:
        # Search catalog for markets matching this series
        per_count = 0
        for cm in catalog.get_all_markets():
            # CRITICAL FIX: CatalogMarket wraps EventMarket, so raw_data is on nested market.market
            if hasattr(cm, "market") and hasattr(cm.market, "raw_data"):
                raw = cm.market.raw_data or {}
            elif hasattr(cm, "raw_data"):
                raw = cm.raw_data or {}
            else:
                raw = {}
            
            mkt_series = raw.get("series_ticker", "") or ""
            mkt_event = raw.get("event_ticker", "") or ""
            
            # CRITICAL FIX: market_id is on nested EventMarket
            if hasattr(cm, "market") and hasattr(cm.market, "market_id"):
                mkt_id = cm.market.market_id or ""
            elif hasattr(cm, "market_id"):
                mkt_id = cm.market_id or ""
            else:
                mkt_id = ""

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
                # CRITICAL FIX: volume is on nested EventMarket
                if hasattr(cm, "market") and hasattr(cm.market, "volume"):
                    vol = float(cm.market.volume) if cm.market.volume else 0
                elif hasattr(cm, "volume"):
                    vol = float(cm.volume) if cm.volume else 0
                else:
                    vol = 0
                if vol >= min_volume:
                    seen.add(mkt_id)
                    results.append((vol, mkt_id))

        per_series_counts[series_ticker] = per_count

    # Sort by volume descending
    results.sort(key=lambda x: x[0], reverse=True)

    # WS-CAP-FIX: Limit markets per agent to prevent overwhelming the WS bridge (max 150 total)
    # Each agent should get at most 20 markets to allow 7-8 agents to run concurrently
    _MAX_MARKETS_PER_AGENT = int(os.getenv("MERID_MAX_MARKETS_PER_AGENT", "20"))
    if len(results) > _MAX_MARKETS_PER_AGENT:
        logger.warning(
            "Agent %s: resolved %d markets, limiting to top %d by volume to preserve WS quota",
            agent_name, len(results), _MAX_MARKETS_PER_AGENT,
        )
        results = results[:_MAX_MARKETS_PER_AGENT]

    tickers = [t for _, t in results]

    # Human-friendly summary log (keeps previous info but adds a clear
    # 'Series resolution' line to make debugging easier in logs).
    logger.info(
        "Agent %s: resolved %d series → %d live markets (cap=%d)",
        agent_name, len(series_list), len(tickers), _MAX_MARKETS_PER_AGENT,
    )

    # Fallback: if the in-memory catalog search yields nothing for the
    # requested series, attempt the Kalshi series-based discovery path
    # which queries the /series endpoint and then markets per-series.
    # This catches cases where the cached ticker index may be missing
    # series_ticker fields or when the REST series API exposes markets
    # not present in the cached listing.
    if not tickers and series_list:
        try:
            # PRODUCTION FIX (2026-05-01): Query specific series tickers via Kalshi REST API
            # The previous fallback did broad discovery without filtering by series.
            # Now we query each specific series ticker and extract its markets.
            _discovered_count = 0
            for series_ticker in series_list:
                try:
                    # Query Kalshi for this specific series
                    _series_markets = await catalog.get_markets_for_series(series_ticker)
                    if _series_markets:
                        for cm in _series_markets:
                            # CRITICAL FIX: market_id is on nested EventMarket
                            if hasattr(cm, "market") and hasattr(cm.market, "market_id"):
                                mkt_id = cm.market.market_id
                            elif hasattr(cm, "market_id"):
                                mkt_id = cm.market_id
                            else:
                                continue
                            
                            if mkt_id not in seen:
                                # CRITICAL FIX: volume is on nested EventMarket
                                if hasattr(cm, "market") and hasattr(cm.market, "volume"):
                                    vol = float(cm.market.volume) if cm.market.volume else 0
                                elif hasattr(cm, "volume"):
                                    vol = float(cm.volume) if cm.volume else 0
                                else:
                                    vol = 0
                                
                                if vol >= min_volume:
                                    seen.add(mkt_id)
                                    results.append((vol, mkt_id))
                                    _discovered_count += 1
                except Exception as _series_exc:
                    logger.debug(
                        "Series discovery failed for %s: %s", series_ticker, _series_exc
                    )
            
            # Re-sort by volume after adding discovered markets
            if _discovered_count > 0:
                results.sort(key=lambda x: x[0], reverse=True)
                # WS-CAP-FIX: Also apply cap to fallback discovery
                _MAX_MARKETS_PER_AGENT = int(os.getenv("MERID_MAX_MARKETS_PER_AGENT", "20"))
                if len(results) > _MAX_MARKETS_PER_AGENT:
                    logger.warning(
                        "Agent %s: REST API discovered %d markets, limiting to top %d by volume",
                        agent_name, len(results), _MAX_MARKETS_PER_AGENT,
                    )
                    results = results[:_MAX_MARKETS_PER_AGENT]
                tickers = [t for _, t in results]
                logger.info(
                    "Series resolution: %s → %d markets from %d series (via REST API, cap=%d)",
                    agent_name, len(tickers), len(series_list), _MAX_MARKETS_PER_AGENT,
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


# Track ticker subscriptions with refcounts to handle shared markets between agents
# Format: ticker -> set(agent_names)
# This ensures we only unsubscribe when the last agent drops a ticker
_TICKER_REFCOUNT: Dict[str, set] = {}
# Track each agent's current tickers for diff calculation
_AGENT_TICKER_TRACKING: Dict[str, set] = {}
# Lock for thread-safe access to tracking structures
import threading
_TRACKING_LOCK = threading.Lock()

def cleanup_agent_tickers(agent_name: str) -> List[str]:
    """Remove an agent from all ticker refcounts (call on agent restart/reload).
    
    Prevents stale agent IDs from leaking and blocking proper unsubscription.
    Returns list of tickers that were fully dropped (refcount reached 0).
    """
    with _TRACKING_LOCK:
        to_remove = []
        old_tickers = _AGENT_TICKER_TRACKING.get(agent_name, set()).copy()
        
        for ticker in old_tickers:
            if ticker in _TICKER_REFCOUNT:
                _TICKER_REFCOUNT[ticker].discard(agent_name)
                if not _TICKER_REFCOUNT[ticker]:
                    del _TICKER_REFCOUNT[ticker]
                    to_remove.append(ticker)
        
        # Remove agent from tracking
        if agent_name in _AGENT_TICKER_TRACKING:
            del _AGENT_TICKER_TRACKING[agent_name]
        
        if to_remove:
            logger.info(
                "[market-selector] Cleanup for agent %s: removed %d tickers (refcount reached 0)",
                agent_name, len(to_remove)
            )
        
        return to_remove

def _update_ticker_refcounts(agent_name: str, old_tickers: set, new_tickers: set) -> tuple:
    """Update refcounts and return (to_remove, to_add) ticker lists.
    
    Thread-safe refcount management:
    - Decrement refcount for tickers agent is dropping
    - Increment refcount for tickers agent is adding
    - Only unsubscribe when refcount reaches 0
    """
    with _TRACKING_LOCK:
        to_remove = []
        to_add = []
        
        # Process tickers agent is dropping
        for ticker in old_tickers - new_tickers:
            if ticker in _TICKER_REFCOUNT:
                _TICKER_REFCOUNT[ticker].discard(agent_name)
                if not _TICKER_REFCOUNT[ticker]:
                    # No agents want this ticker anymore
                    del _TICKER_REFCOUNT[ticker]
                    to_remove.append(ticker)
                    logger.debug(
                        "[market-selector] Ticker %s refcount reached 0 (dropped by agent %s)",
                        ticker, agent_name
                    )
                else:
                    # Other agents still want this ticker
                    logger.debug(
                        "[market-selector] Ticker %s still has %d agents: %s (dropped by %s)",
                        ticker, len(_TICKER_REFCOUNT[ticker]), _TICKER_REFCOUNT[ticker], agent_name
                    )
        
        # Process tickers agent is adding
        for ticker in new_tickers - old_tickers:
            if ticker not in _TICKER_REFCOUNT:
                _TICKER_REFCOUNT[ticker] = set()
            _TICKER_REFCOUNT[ticker].add(agent_name)
            to_add.append(ticker)
            logger.debug(
                "[market-selector] Ticker %s refcount now %d (added by agent %s): %s",
                ticker, len(_TICKER_REFCOUNT[ticker]), agent_name, _TICKER_REFCOUNT[ticker]
            )
        
        # Update agent's ticker tracking
        _AGENT_TICKER_TRACKING[agent_name] = new_tickers
        
        return to_remove, to_add

async def enable_kalshi_agent(agent_name: str, series_tickers: Optional[List[str]] = None) -> Dict[str, Any]:
    """Subscribe an agent to its Kalshi prediction markets.

    1. Resolve market IDs via get_agent_market_tickers
    2. Remove agent's old tickers from WS bridge (if no other agents want them)
    3. Subscribe via WS bridge for live orderbook/trade data
    4. Return summary of what was subscribed

    Uses refcount-based ticker tracking to safely handle shared markets between agents.

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

    # Calculate old vs new tickers using refcount tracking
    with _TRACKING_LOCK:
        old_tickers = _AGENT_TICKER_TRACKING.get(agent_name, set()).copy()
    new_tickers = set(market_ids)
    to_remove, to_add = _update_ticker_refcounts(agent_name, old_tickers, new_tickers)
    
    ws_subscribed = 0
    try:
        from merid.event_venues.kalshi.ws_bridge import get_bridge
        bridge = get_bridge()
        
        # CRITICAL FIX: Validate WS bridge is running AND connected before subscription
        if not bridge.is_running():
            logger.warning(
                "enable_kalshi_agent(%s): WS bridge not running - attempting to start",
                agent_name
            )
            await bridge.start(tickers=market_ids)
            ws_subscribed = len(market_ids)
        else:
            # Check if bridge is actually connected (not just running)
            health_status = bridge.get_health_status()
            if not health_status.get("connected", False):
                logger.warning(
                    "enable_kalshi_agent(%s): WS bridge running but not connected - subscription may fail",
                    agent_name
                )
            
            # Unsubscribe from tickers no longer wanted by any agent
            if to_remove:
                await bridge.unsubscribe(to_remove)
                logger.debug(
                    "enable_kalshi_agent(%s): unsubscribed from %d tickers (refcount reached 0)",
                    agent_name, len(to_remove)
                )
            
            # Subscribe to new tickers
            if to_add:
                await bridge.subscribe(to_add)
                ws_subscribed = len(to_add)
        
        logger.info(
            "enable_kalshi_agent(%s): WS subscribed to %d new markets (unsubscribed %d, total agent markets=%d)",
            agent_name, ws_subscribed, len(to_remove), len(new_tickers),
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
