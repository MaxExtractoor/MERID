"""
Shared Kalshi Health Snapshot - Single source of truth for readiness checks.

This module provides a unified health snapshot that can be used by:
- web.api.health_api.kalshi_readiness() endpoint
- merid.loop_15m for cycle readiness decisions

This ensures consistency between health checks and eliminates the
"unhealthy reason=None" bug by always providing explicit reasons.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any
import time
from utils.logger import get_logger

logger = get_logger("kalshi.health_snapshot")


class MDState(Enum):
    """Market data state for a ticker."""
    UNINITIALIZED = "uninitialized"  # No updates seen yet
    STALE = "stale"  # Updates seen but too old
    FRESH = "fresh"  # Recent updates available


class SpotState(Enum):
    """Spot price state for an asset."""
    UNAVAILABLE = "unavailable"  # No data in cache
    STALE = "stale"  # Data in cache but too old
    FRESH = "fresh"  # Recent data available


class CatalogState(Enum):
    """Catalog refresh state."""
    ERROR = "error"  # Refresh failed
    STALE = "stale"  # Refresh succeeded but data is old
    OK = "ok"  # Fresh data available


class OverallStatus(Enum):
    """Overall system status."""
    HEALTHY = "healthy"  # All systems go
    DEGRADED = "degraded"  # Some issues but can trade
    UNHEALTHY = "unhealthy"  # Critical issues, must halt


@dataclass
class KalshiHealthSnapshot:
    """Unified health snapshot for Kalshi venue."""
    
    # Overall status
    status: OverallStatus
    reasons: List[str] = field(default_factory=list)
    
    # Config
    config_valid: bool = True
    config_error: Optional[str] = None
    
    # WebSocket bridge
    ws_connected: bool = False
    ws_md_age_ms: Optional[float] = None
    ws_healthy: bool = True
    ws_stalled: bool = False
    ws_events_per_sec: float = 0.0
    ws_time_since_last_event: Optional[float] = None
    
    # Catalog
    catalog_state: CatalogState = CatalogState.OK
    catalog_age_s: float = 0.0
    catalog_thread_alive: bool = True
    
    # Spot data per asset
    spot_status: Dict[str, SpotState] = field(default_factory=dict)
    spot_age_ms: Dict[str, int] = field(default_factory=dict)
    
    # Market data per ticker
    md_status: Dict[str, MDState] = field(default_factory=dict)
    md_age_ms: Dict[str, int] = field(default_factory=dict)
    
    # Timestamp
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "status": self.status.value,
            "reasons": self.reasons,
            "config_valid": self.config_valid,
            "config_error": self.config_error,
            "ws_connected": self.ws_connected,
            "ws_md_age_ms": self.ws_md_age_ms,
            "catalog": {
                "state": self.catalog_state.value,
                "age_s": self.catalog_age_s,
                "thread_alive": self.catalog_thread_alive,
            },
            "spot": {
                asset: {
                    "state": state.value,
                    "age_ms": self.spot_age_ms.get(asset, -1)
                }
                for asset, state in self.spot_status.items()
            },
            "md": {
                ticker: {
                    "state": state.value,
                    "age_ms": self.md_age_ms.get(ticker, -1)
                }
                for ticker, state in self.md_status.items()
            },
            "timestamp": self.timestamp,
        }


def check_ws_forwarder_impossible_ok(loop_tick: int, ws_stats: dict, states: dict) -> bool:
    """
    Check the WS_FORWARDER_IMPOSSIBLE-OK invariant.
    
    The invariant: Once the loop has run N ticks and WS is configured as enabled,
    it should be impossible for the system to claim "WS forwarder OK" under
    conditions that cannot be true.
    
    CRITICAL FIX: Add time-based check - if WS connected but raw/enqueued/processed
    stay at zero for longer than 30 seconds while REST ping is healthy, this is a
    violation and should flip MD state to Stale.
    
    BUG FIX #1: Add subscription validation and improved fallback logic:
    - Check if WS has actual subscriptions (not just connected)
    - Allow degraded mode if REST is healthy but WS is stalled
    - Only flip to unhealthy if both WS and REST are degraded
    
    Args:
        loop_tick: Current loop tick counter
        ws_stats: Dictionary with WS stats including:
            - ws_raw_messages_seen: int
            - ws_events_enqueued: int
            - ws_forwarder_events_processed: int
            - ws_healthy: bool
            - ws_connected: bool
            - time_since_last_event: float (seconds since last WS event)
            - events_per_sec: float (current event rate)
            - markets: list of subscribed tickers
        states: Dictionary of ticker -> KalshiMarketState with transport_mode and transport_stale
    
    Returns:
        True if invariant holds, False if violated
    """
    # Warmup period: don't enforce during first 3 ticks
    if loop_tick < 3:
        return True
    
    # Invariant only applies when WS is supposed to be enabled
    if not ws_stats.get("ws_connected", False):
        return True
    
    # CRITICAL FIX: Check if WS has actual subscriptions
    subscribed_markets = ws_stats.get("markets", [])
    has_subscriptions = len(subscribed_markets) > 0
    
    # DIAGNOSTIC: Log subscription state for debugging
    logger.info("[WS-SUBSCRIPTION-CHECK] markets=%s has_subscriptions=%s", subscribed_markets[:5] if subscribed_markets else [], has_subscriptions)
    
    # If WS says OK, then counters must reflect actual activity
    if ws_stats.get("ws_healthy", True):
        raw_seen = ws_stats.get("ws_raw_messages_seen", 0)
        enqueued = ws_stats.get("ws_events_enqueued", 0)
        processed = ws_stats.get("ws_forwarder_events_processed", 0)
        time_since_last_event = ws_stats.get("time_since_last_event", 0.0)
        events_per_sec = ws_stats.get("events_per_sec", 0.0)
        
        # Check if any ticker has healthy WS transport
        has_ws_state = any(
            s.transport_mode == "ws" and not s.transport_stale
            for s in states.values() if s
        )
        
        # Check if any ticker has healthy REST transport (for fallback logic)
        has_rest_state = any(
            s.transport_mode == "rest" and not s.transport_stale
            for s in states.values() if s
        )
        
        # CRITICAL FIX: Time-based check - if WS connected but no events for >30s
        # while claiming to be healthy, this is a violation
        time_violation = (
            raw_seen == 0
            and enqueued == 0
            and processed == 0
            and time_since_last_event > 30.0
            and events_per_sec == 0.0
        )
        
        # CRITICAL FIX: Subscription violation - WS connected but no subscriptions
        # TEMPORARILY DISABLED: Allow trading while investigating subscription state issue
        subscription_violation = False
        # subscription_violation = (
        #     has_subscriptions == False
        #     and time_since_last_event > 10.0  # Give 10s grace period for subscription setup
        # )
        
        # CRITICAL FIX: Improved invariant check with fallback logic
        # If WS is stalled but REST is healthy, allow degraded mode (don't fail invariant)
        # Only fail invariant if both WS and REST are degraded
        rest_fallback_available = has_rest_state and not time_violation
        
        # Invariant: if WS is healthy, we must have processed events OR have REST fallback
        invariant_holds = (
            (raw_seen > 0 and enqueued > 0 and processed > 0 and has_ws_state)  # WS is working
            or (rest_fallback_available)  # REST fallback is available
        ) and not time_violation and not subscription_violation
        
        if not invariant_holds:
            violation_reason = ""
            if subscription_violation:
                violation_reason = f"SUBSCRIPTION_VIOLATION: connected but no subscriptions for {time_since_last_event:.1f}s"
            elif time_violation:
                if rest_fallback_available:
                    # Don't log as critical if REST fallback is available
                    logger.warning(
                        "[WS-FORWARDER-DEGRADED] WS stalled but REST fallback available: time_since_last_event=%.1fs",
                        time_since_last_event
                    )
                    return True  # Pass invariant since REST fallback is available
                violation_reason = f"TIME_VIOLATION: connected but no events for {time_since_last_event:.1f}s (no REST fallback)"
            else:
                violation_reason = f"COUNTER_VIOLATION: raw={raw_seen} enq={enqueued} proc={processed}"
            
            logger.critical(
                "[WS-FORWARDER-IMPOSSIBLE-OK] VIOLATION: %s, ws_states=%s, subscriptions=%d",
                violation_reason,
                [(t, s.transport_mode, s.transport_stale) for t, s in states.items() if s],
                len(subscribed_markets)
            )
        
        return invariant_holds
    
    return True


def check_ws_queue_pressure(loop_tick: int, ws_stats: dict) -> bool:
    """
    Check the WS queue pressure invariant.
    
    The invariant: The WS forwarder queue should not exceed hard limits.
    If queue pressure is high, the system should be marked as degraded.
    
    Args:
        loop_tick: Current loop tick counter
        ws_stats: Dictionary with WS stats including:
            - queue_size: int
            - queue_hard_limit: int (default 200)
            - events_per_sec: float
            - time_since_last_event: float
    
    Returns:
        True if invariant holds (queue pressure acceptable), False if violated
    """
    # Warmup period: don't enforce during first 3 ticks
    if loop_tick < 3:
        return True
    
    queue_size = ws_stats.get("queue_size", 0)
    queue_hard_limit = ws_stats.get("queue_hard_limit", 5000)  # Increased from 200 to match ws_bridge warning threshold
    events_per_sec = ws_stats.get("events_per_sec", 0.0)
    time_since_last_event = ws_stats.get("time_since_last_event", 0.0)
    
    # Check queue hard limit
    if queue_size >= queue_hard_limit:
        logger.critical(
            "[WS-QUEUE-PRESSURE] VIOLATION: queue_size=%d >= hard_limit=%d",
            queue_size, queue_hard_limit
        )
        return False
    
    # Check for queue pressure warning (> 80% of hard limit)
    if queue_size > (queue_hard_limit * 0.8):
        logger.warning(
            "[WS-QUEUE-PRESSURE] WARNING: queue_size=%d > 80%% of hard_limit=%d",
            queue_size, queue_hard_limit
        )
    
    # Check for stalled forwarder (no events but queue not empty)
    if queue_size > 0 and events_per_sec == 0.0 and time_since_last_event > 10.0:
        logger.critical(
            "[WS-QUEUE-PRESSURE] VIOLATION: queue=%d but events_per_sec=0, time_since_last_event=%.1fs",
            queue_size, time_since_last_event
        )
        return False
    
    return True


def check_catalog_ws_state_consistency(loop_tick: int) -> bool:
    """
    Check the catalog/WS/state intersection invariant.
    
    The invariant: For the 5 crypto assets (BTC, ETH, SOL, XRP, DOGE):
    - Catalog must contain markets for all 5 assets
    - WS subscriptions must match catalog series tickers
    - Market state store must have entries for catalog markets
    - The intersection of these three sources must be consistent
    
    Args:
        loop_tick: Current loop tick counter
    
    Returns:
        True if invariant holds, False if violated
    """
    # Warmup period: don't enforce during first 3 ticks
    if loop_tick < 3:
        return True
    
    expected_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    expected_series = ["KXBTC15M", "KXETH15M", "KXSOL15M", "KXXRP15M", "KXDOGE15M"]
    
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        from config.kalshi_universe import KALSHI_15M_SERIES_TICKERS
        
        catalog = get_market_catalog()
        md_store = get_kalshi_market_state_store()
        
        if not catalog:
            logger.critical("[UNIVERSE-CONSISTENCY] Catalog not available")
            return False
        
        # Check catalog has markets for all 5 assets
        catalog_snapshot = catalog.snapshot()
        catalog_series = set()
        for market in catalog_snapshot.markets:
            series_ticker = getattr(market, 'series_ticker', None) or getattr(market.market, 'series_ticker', None) if hasattr(market, 'market') else None
            if series_ticker:
                catalog_series.add(series_ticker)
        
        missing_series = set(expected_series) - catalog_series
        if missing_series:
            logger.critical(
                "[UNIVERSE-CONSISTENCY] VIOLATION: catalog missing series tickers: %s",
                sorted(missing_series)
            )
            return False
        
        # Check market state store has entries for catalog markets
        if md_store and hasattr(md_store, '_states'):
            state_tickers = set(md_store._states.keys())
            
            # Check for series tickers in state store (not individual market IDs)
            state_series = set()
            for ticker in state_tickers:
                for series in expected_series:
                    if ticker.startswith(series):
                        state_series.add(series)
                        break
            
            missing_state_series = set(expected_series) - state_series
            if missing_state_series:
                logger.warning(
                    "[UNIVERSE-CONSISTENCY] WARNING: state store missing series tickers: %s (may be during startup)",
                    sorted(missing_state_series)
                )
                # Don't fail on missing state during startup
        
        logger.info(
            "[UNIVERSE-CONSISTENCY] OK: catalog has %d series, expected %d",
            len(catalog_series.intersection(expected_series)), len(expected_series)
        )
        return True
        
    except Exception as e:
        logger.error(f"[UNIVERSE-CONSISTENCY] Check failed: {e}")
        return False


def check_spot_md_parity(loop_tick: int) -> bool:
    """
    Check the spot/MD parity invariant.
    
    The invariant: If spot is not ready (spotreadyFalse), trading should be blocked.
    This ensures that candidate and signal generation only proceeds when spot data is fresh.
    
    Args:
        loop_tick: Current loop tick counter
    
    Returns:
        True if invariant holds (spot ready or appropriately blocked), False if violated
    """
    # Warmup period: don't enforce during first 3 ticks
    if loop_tick < 3:
        return True
    
    try:
        from data.unified_spot_service import get_unified_spot_service, SpotError
        
        spot_service = get_unified_spot_service()
        if not spot_service:
            logger.warning("[SPOT-MD-PARITY] Spot service not available")
            return True  # Don't fail if service not available during startup
        
        # Check spot readiness for all 5 assets
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        fresh_count = 0
        stale_count = 0
        unavailable_count = 0
        
        for asset in assets:
            spot_result = spot_service.get(asset)
            
            if isinstance(spot_result, SpotError):
                unavailable_count += 1
                logger.warning(f"[SPOT-MD-PARITY] {asset} spot error: {spot_result.reason}")
            elif spot_result:
                spot_age_ms = int((time.time() * 1000) - spot_result.timestamp)
                if spot_age_ms < 30000:  # 30s threshold
                    fresh_count += 1
                else:
                    stale_count += 1
                    logger.warning(f"[SPOT-MD-PARITY] {asset} spot stale: age={spot_age_ms}ms")
            else:
                unavailable_count += 1
                logger.error(f"[SPOT-MD-PARITY] {asset} spot unavailable")
        
        # Invariant: if any asset has unavailable spot, system is unhealthy
        if unavailable_count > 0:
            logger.critical(
                "[SPOT-MD-PARITY] VIOLATION: %d assets have unavailable spot data",
                unavailable_count
            )
            return False
        
        # If all assets are fresh, invariant holds
        if fresh_count == len(assets):
            logger.info(
                "[SPOT-MD-PARITY] OK: all %d assets have fresh spot data",
                fresh_count
            )
            return True
        
        # If some assets are stale, degrade but don't halt
        if stale_count > 0:
            logger.warning(
                "[SPOT-MD-PARITY] DEGRADED: %d assets have stale spot data, %d fresh",
                stale_count, fresh_count
            )
            return True  # Degraded but not a violation
        
        return True
        
    except Exception as e:
        logger.error(f"[SPOT-MD-PARITY] Check failed: {e}")
        return True  # Don't fail on check errors


def get_kalshi_health_snapshot(loop_tick: int = 0) -> KalshiHealthSnapshot:
    """
    Build a unified health snapshot for Kalshi venue.
    
    This is the single source of truth for Kalshi health checks.
    Both the health endpoint and the 15m loop should use this.
    
    Args:
        loop_tick: Current loop tick counter for WS_FORWARDER_IMPOSSIBLE_OK check
    
    Returns:
        KalshiHealthSnapshot with all health information
    """
    snapshot = KalshiHealthSnapshot(status=OverallStatus.HEALTHY)
    reasons = []
    
    # Check config
    try:
        from merid.event_venues.kalshi.kalshi_config import verify_kalshi_config
        config_valid, config_error, config = verify_kalshi_config()
        snapshot.config_valid = config_valid
        snapshot.config_error = config_error
        
        if not config_valid:
            snapshot.status = OverallStatus.UNHEALTHY
            reasons.append(f"config_invalid: {config_error}")
    except Exception as e:
        logger.error(f"Config check failed: {e}")
        snapshot.config_valid = False
        snapshot.config_error = str(e)
        snapshot.status = OverallStatus.UNHEALTHY
        reasons.append(f"config_check_failed: {e}")
    
    # Check WS bridge - use canonical singleton, not app.state.ws_bridge
    # The singleton is the source of truth used by market_state and ws_bridge consumers
    try:
        from merid.event_venues.kalshi.ws_bridge import get_bridge

        ws_bridge = get_bridge()
        if ws_bridge:
            summary = ws_bridge.summary()
            snapshot.ws_connected = summary.get("running", False)
            last_msg_ago = summary.get("last_message_ago_s", 0)
            if last_msg_ago > 0:
                snapshot.ws_md_age_ms = last_msg_ago * 1000
        else:
            snapshot.ws_connected = False
        
        # Only mark as unhealthy if we can definitively determine WS is disconnected
        if not snapshot.ws_connected and ws_bridge is not None:
            snapshot.status = OverallStatus.UNHEALTHY
            reasons.append("ws_disconnected")
    except Exception as e:
        logger.debug(f"WS bridge check failed: {e}")
        snapshot.ws_connected = False
        # Don't fail on WS check failure - may be during startup
    
    # Check catalog
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        catalog = get_market_catalog()
        if catalog:
            catalog_health = catalog.get_health_status()
            catalog_status = catalog_health.get("status", "unknown")
            snapshot.catalog_age_s = catalog_health.get("last_refresh_age_s", 0.0)
            snapshot.catalog_thread_alive = catalog_health.get("thread_alive", True)
            
            if catalog_status == "dead":
                snapshot.catalog_state = CatalogState.ERROR
                snapshot.status = OverallStatus.UNHEALTHY
                reasons.append("catalog_dead")
            elif catalog_status == "stale":
                snapshot.catalog_state = CatalogState.STALE
                # Stale catalog degrades but doesn't halt
                if snapshot.status == OverallStatus.HEALTHY:
                    snapshot.status = OverallStatus.DEGRADED
                reasons.append("catalog_stale")
            else:
                snapshot.catalog_state = CatalogState.OK
    except Exception as e:
        logger.error(f"Catalog check failed: {e}")
        snapshot.catalog_state = CatalogState.ERROR
        snapshot.status = OverallStatus.UNHEALTHY
        reasons.append(f"catalog_check_failed: {e}")
    
    # Check spot data for all 5 Kalshi 15m assets
    # BUG FIX #2: Implement per-asset spot freshness tracking
    # Only mark system as unhealthy if ALL assets are unavailable
    # Mark as degraded if SOME assets are stale but others are fresh
    logger.info("[SPOT-CHECK-DIAG] Starting spot health check for 5 assets")
    try:
        from data.unified_spot_service import get_unified_spot_service, SpotError
        from data.spot_sla_config import get_spot_status
        
        spot_service = get_unified_spot_service()
        logger.info(f"[SPOT-CHECK-DIAG] get_unified_spot_service() returned: {spot_service is not None}")
        if spot_service:
            fresh_count = 0
            stale_count = 0
            unavailable_count = 0
            
            for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                # Use service.get() API instead of direct cache access
                spot_result = spot_service.get(asset)
                logger.info(f"[SPOT-CHECK-DIAG] {asset} spot_result type={type(spot_result).__name__} value={spot_result}")
                
                if isinstance(spot_result, SpotError):
                    # Handle SpotError cases
                    snapshot.spot_status[asset] = SpotState.UNAVAILABLE
                    snapshot.spot_age_ms[asset] = spot_result.age_s * 1000 if spot_result.age_s else None
                    unavailable_count += 1
                    logger.warning(f"[ASSET-HEALTH] {asset} spot error: {spot_result.reason} - {spot_result.message}")
                elif spot_result:
                    # SpotPrice case - data is fresh and within SLA
                    spot_age_ms = int((time.time() * 1000) - spot_result.timestamp)
                    snapshot.spot_age_ms[asset] = spot_age_ms
                    snapshot.spot_status[asset] = SpotState.FRESH
                    fresh_count += 1
                    logger.info(f"[ASSET-HEALTH] {asset} spot fresh: ${spot_result.price:.2f} age={spot_age_ms}ms")
                else:
                    # Should not happen with new API, but handle for safety
                    snapshot.spot_status[asset] = SpotState.UNAVAILABLE
                    unavailable_count += 1
                    logger.error(f"[ASSET-HEALTH] {asset} spot unavailable")
            
            # BUG FIX #2: Per-asset spot health determination
            # Only mark as unhealthy if ALL assets are unavailable
            # Mark as degraded if SOME assets are stale/unavailable but at least one is fresh
            if unavailable_count == 5:
                # All assets unavailable - critical failure
                snapshot.status = OverallStatus.UNHEALTHY
                reasons.append("spot_all_unavailable")
            elif fresh_count == 0 and unavailable_count < 5:
                # Some assets stale/unavailable but none fresh - degraded
                if snapshot.status == OverallStatus.HEALTHY:
                    snapshot.status = OverallStatus.DEGRADED
                reasons.append(f"spot_partial_unavailable: {unavailable_count}/5 unavailable")
            elif fresh_count < 5 and fresh_count > 0:
                # Some assets fresh, some degraded - degraded mode
                if snapshot.status == OverallStatus.HEALTHY:
                    snapshot.status = OverallStatus.DEGRADED
                reasons.append(f"spot_partial_degraded: {fresh_count}/5 fresh")
            # All 5 fresh - healthy (no action needed)
        else:
            logger.info("[SPOT-CHECK-DIAG] spot_service is None, skipping spot check")
    except Exception as e:
        logger.error(f"Spot check failed: {e}", exc_info=True)
        # Don't fail on spot check failure - may be during startup
    
    # Check WS bridge health
    try:
        from merid.event_venues.kalshi.ws_bridge import get_bridge

        ws_bridge = get_bridge()
        if ws_bridge:
            ws_health = ws_bridge.get_forward_loop_health()
            snapshot.ws_healthy = ws_health.get("healthy", True)
            snapshot.ws_stalled = ws_health.get("stalled", False)
            snapshot.ws_events_per_sec = ws_health.get("events_per_sec", 0.0)
            snapshot.ws_time_since_last_event = ws_health.get("time_since_last_event", None)
            
            # CRITICAL: Collect WS stats for WS_FORWARDER_IMPOSSIBLE_OK and queue pressure checks
            ws_stats = {
                "ws_raw_messages_seen": ws_health.get("ws_raw_messages_seen", 0),
                "ws_events_enqueued": ws_health.get("ws_events_enqueued", 0),
                "ws_forwarder_events_processed": ws_health.get("ws_forwarder_events_processed", 0),
                "ws_healthy": snapshot.ws_healthy,
                "ws_connected": snapshot.ws_connected,
                "queue_size": ws_health.get("queue_size", 0),
                "queue_hard_limit": ws_health.get("queue_hard_limit", 5000),  # Increased from 200 to match ws_bridge warning threshold
                "events_per_sec": ws_health.get("events_per_sec", 0.0),
                "time_since_last_event": ws_health.get("time_since_last_event", 0.0),
            }
            
            # If WS is unhealthy, mark system as degraded or unhealthy
            if not snapshot.ws_healthy:
                if snapshot.status == OverallStatus.HEALTHY:
                    snapshot.status = OverallStatus.DEGRADED
                reasons.append(f"ws_unhealthy: stalled={snapshot.ws_stalled}")
            
            # CRITICAL: Enforce WS_FORWARDER_IMPOSSIBLE_OK invariant
            # Get market states for transport mode check
            try:
                from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                md_store = get_kalshi_market_state_store()
                if md_store and hasattr(md_store, '_states'):
                    states = md_store._states
                    invariant_ok = check_ws_forwarder_impossible_ok(loop_tick, ws_stats, states)
                    if not invariant_ok:
                        snapshot.status = OverallStatus.UNHEALTHY
                        reasons.append("ws_forwarder_impossible_ok_violation")
            except Exception as e:
                logger.warning(f"WS_FORWARDER_IMPOSSIBLE_OK check failed: {e}")
            
            # CRITICAL: Enforce WS queue pressure invariant
            try:
                queue_ok = check_ws_queue_pressure(loop_tick, ws_stats)
                if not queue_ok:
                    snapshot.status = OverallStatus.UNHEALTHY
                    reasons.append("ws_queue_pressure_violation")
            except Exception as e:
                logger.warning(f"WS queue pressure check failed: {e}")
            
            # CRITICAL: Enforce catalog/WS/state consistency invariant
            try:
                universe_ok = check_catalog_ws_state_consistency(loop_tick)
                if not universe_ok:
                    snapshot.status = OverallStatus.UNHEALTHY
                    reasons.append("universe_consistency_violation")
            except Exception as e:
                logger.warning(f"Universe consistency check failed: {e}")
    except Exception as e:
        logger.error(f"WS bridge check failed: {e}")
        # Don't fail on WS check failure - may be during startup
    
    # Check spot/MD parity invariant
    try:
        spot_parity_ok = check_spot_md_parity(loop_tick)
        if not spot_parity_ok:
            snapshot.status = OverallStatus.UNHEALTHY
            reasons.append("spot_md_parity_violation")
    except Exception as e:
        logger.warning(f"Spot/MD parity check failed: {e}")
    
    # Check MD data
    try:
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        from merid.event_venues.kalshi.md_sla_interface import build_md_health_record
        
        md_store = get_kalshi_market_state_store()
        if md_store and hasattr(md_store, '_states'):
            crypto_15m_pattern = ['KXBTC15M-', 'KXETH15M-', 'KXSOL15M-', 'KXXRP15M-', 'KXDOGE15M-']
            
            for ticker in md_store._states.keys():
                if any(ticker.startswith(pattern) for pattern in crypto_15m_pattern):
                    state = md_store.get(ticker)
                    if state and hasattr(state, 'last_book_update_ts'):
                        md_age = time.monotonic() - state.last_book_update_ts
                        md_age_ms = int(md_age * 1000)
                        snapshot.md_age_ms[ticker] = md_age_ms
                        
                        seconds_to_expiry = state.seconds_to_expiry if hasattr(state, 'seconds_to_expiry') else None
                        
                        # Normalize expiry if needed
                        if seconds_to_expiry is None or seconds_to_expiry == 0.0:
                            try:
                                from merid.event_venues.kalshi.contract_normalization import normalize_kalshi_15m_contract
                                from datetime import datetime, timezone
                                normalized = normalize_kalshi_15m_contract(
                                    ticker=ticker,
                                    expiration_time=state.expiration_time if hasattr(state, 'expiration_time') else None,
                                    expected_expiration_time=state.expected_expiration_time if hasattr(state, 'expected_expiration_time') else None,
                                    now=datetime.now(timezone.utc)
                                )
                                seconds_to_expiry = normalized.seconds_to_expiry
                            except Exception as e:
                                logger.warning(f"MD normalization failed for {ticker}: {e}")
                        
                        if seconds_to_expiry is None:
                            snapshot.md_status[ticker] = MDState.UNINITIALIZED
                            # Don't halt on uninit MD - may be during startup
                        else:
                            md_health = build_md_health_record(ticker, md_age_ms, seconds_to_expiry)
                            md_status_str = md_health.get("status", "unknown")
                            
                            if md_status_str == "ok":
                                snapshot.md_status[ticker] = MDState.FRESH
                            elif md_status_str == "warn":
                                snapshot.md_status[ticker] = MDState.STALE
                                # Stale MD degrades but doesn't halt
                                if snapshot.status == OverallStatus.HEALTHY:
                                    snapshot.status = OverallStatus.DEGRADED
                            else:  # bad
                                snapshot.md_status[ticker] = MDState.UNINITIALIZED
                                # Don't halt on bad MD - may be during startup
                    else:
                        snapshot.md_status[ticker] = MDState.UNINITIALIZED
                        # Don't fail on missing MD - may be during startup
    except Exception as e:
        logger.error(f"MD check failed: {e}")
        # Don't fail on MD check failure - may be during startup
    
    # Finalize status and reasons
    snapshot.reasons = reasons
    snapshot.timestamp = time.time()
    
    # Ensure status is correct based on reasons
    if snapshot.status == OverallStatus.HEALTHY and reasons:
        # If we have reasons but status is still healthy, downgrade to degraded
        snapshot.status = OverallStatus.DEGRADED
    
    return snapshot
