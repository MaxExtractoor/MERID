"""
15m Health Snapshot - Observability Layer

This module provides a structured health snapshot that mirrors the scenario
categories tested in tests/15m_scenario_tests/. This allows production issues
to be mapped back to tested scenarios.

Usage:
    from merid.monitoring.health_snapshot import get_health_snapshot, HealthSnapshot
    
    snapshot = get_health_snapshot()
    logger.info(f"[HEALTH-SNAPSHOT] {snapshot.to_json()}")
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import time
import json

from merid.data.ingress_replay import replay_time
from utils.logger import get_logger

logger = get_logger("merid.monitoring.health_snapshot")


@dataclass
class WsHealth:
    """WebSocket health metrics."""
    connection_state: str  # CONNECTED, DISCONNECTED, RECONNECTING
    latency_ms: float  # Current latency in milliseconds
    last_heartbeat_ts: float  # Unix timestamp of last heartbeat
    heartbeat_age_s: float  # Age of last heartbeat in seconds
    is_connected: bool  # Whether WS is currently connected
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SpotHealth:
    """Spot service health metrics."""
    last_update_age_s: float  # Age of last spot update in seconds
    service_running: bool  # Whether spot service is running
    freshness_threshold_s: float  # Configured freshness threshold
    is_stale: bool  # Whether spot is considered stale
    stale_reason: Optional[str]  # Reason if stale (e.g., "age > 60s")
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BookHealth:
    """Orderbook health metrics."""
    book_consistency: str  # GOOD, SUSPECT
    suspect_reason: Optional[str]  # Reason if SUSPECT (e.g., "queue_overflow")
    last_update_age_s: float  # Age of last book update in seconds
    has_bids: bool  # Whether book has bids
    has_asks: bool  # Whether book has asks
    is_dual_sided: bool  # Whether book is dual-sided
    best_bid_cents: Optional[int]  # Best bid price in cents
    best_ask_cents: Optional[int]  # Best ask price in cents
    spread_cents: Optional[int]  # Spread in cents
    spread_pct: Optional[float]  # Spread as percentage of mid
    is_stale: bool  # Whether book is considered stale
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RiskHealth:
    """Risk environment health metrics."""
    utilization_pct: float  # Risk budget utilization (0.0 to 1.0)
    has_capacity: bool  # Whether risk budget has capacity
    is_exhausted: bool  # Whether risk budget is exhausted
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GateDecision:
    """Gate decision metrics."""
    spot_age: str  # PASS, FAIL
    book_freshness: str  # PASS, FAIL
    liquidity: str  # PASS, FAIL
    data_quality: str  # PASS, FAIL
    edge: str  # PASS, FAIL
    risk: str  # PASS, FAIL
    overall: str  # PASS, REJECT
    reason: Optional[str]  # Reason if REJECT
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HealthSnapshot:
    """Complete 15m health snapshot.
    
    This mirrors the scenario categories tested in tests/15m_scenario_tests/:
    - WS health (test_ws_scenarios.py)
    - Spot health (test_spot_scenarios.py)
    - Book health (test_book_scenarios.py)
    - Risk health (test_book_scenarios.py - risk budget exhausted scenario)
    - Gate decisions (all scenario tests)
    """
    timestamp: str  # ISO 8601 timestamp
    ws: WsHealth
    spot: SpotHealth
    book: BookHealth
    risk: RiskHealth
    gates: GateDecision
    quarantine_path: str = "unknown"  # active / inactive / unknown
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot to dictionary for logging/serialization."""
        return {
            "timestamp": self.timestamp,
            "ws": self.ws.to_dict(),
            "spot": self.spot.to_dict(),
            "book": self.book.to_dict(),
            "risk": self.risk.to_dict(),
            "gates": self.gates.to_dict(),
            "quarantine_path": self.quarantine_path,
        }
    
    def to_json(self) -> str:
        """Convert snapshot to JSON string."""
        return json.dumps(self.to_dict(), indent=2)
    
    def to_summary(self) -> str:
        """Generate a human-readable summary for logging."""
        lines = [
            f"[HEALTH-SNAPSHOT] {self.timestamp}",
            f"  WS: state={self.ws.connection_state}, latency={self.ws.latency_ms:.0f}ms, age={self.ws.heartbeat_age_s:.0f}s",
            f"  Spot: age={self.spot.last_update_age_s:.0f}s, stale={self.spot.is_stale}",
            f"  Book: consistency={self.book.book_consistency}, dual_sided={self.book.is_dual_sided}, age={self.book.last_update_age_s:.0f}s",
            f"  Risk: utilization={self.risk.utilization_pct:.1%}, exhausted={self.risk.is_exhausted}",
            f"  Gates: overall={self.gates.overall}, reason={self.gates.reason or 'none'}",
            f"  Quarantine: path={self.quarantine_path}",
        ]
        return "\n".join(lines)
    
    def map_to_scenario(self) -> Optional[str]:
        """Map current health to a scenario test category.
        
        Returns the name of the closest matching scenario test, or None if no match.
        This helps map production issues back to tested scenarios.
        """
        # WS scenarios
        if self.ws.connection_state == "DISCONNECTED":
            return "test_ws_down_scenario"
        if self.ws.latency_ms > 5000:
            return "test_ws_high_latency_scenario"
        if self.ws.connection_state == "RECONNECTING":
            return "test_ws_reconnect_scenario"
        
        # Spot scenarios
        if self.spot.is_stale and self.spot.last_update_age_s > 60:
            return "test_spot_stale_scenario"
        if self.spot.last_update_age_s >= 60:
            return "test_spot_boundary_60s_scenario"
        if self.spot.last_update_age_s >= 30:
            return "test_spot_boundary_30s_scenario"
        if not self.spot.service_running:
            return "test_spot_service_restart_scenario"
        if self.spot.last_update_age_s > 1000:  # Effectively missing
            return "test_spot_missing_scenario"
        
        # Book scenarios
        if self.book.book_consistency == "SUSPECT":
            if self.book.suspect_reason == "queue_overflow":
                return "test_suspect_book_queue_overflow_scenario"
            return "test_suspect_book_recovery_scenario"
        if not self.book.is_dual_sided:
            if not self.book.has_bids:
                return "test_one_sided_book_no_bids_scenario"
            if not self.book.has_asks:
                return "test_one_sided_book_no_asks_scenario"
        if self.book.is_stale:
            return "test_book_stale_scenario"
        if self.book.spread_pct and self.book.spread_pct > 10:  # Wide spread
            return "test_wide_spread_scenario"
        
        # Risk scenarios
        if self.risk.is_exhausted:
            return "test_risk_budget_exhausted_scenario"
        
        # Gate scenarios
        if self.gates.overall == "REJECT":
            if self.gates.reason == "spot_stale":
                return "test_spot_stale_scenario"
            if self.gates.reason == "book_stale":
                return "test_book_stale_scenario"
            if self.gates.reason == "insufficient_liquidity":
                return "test_one_sided_book_no_bids_scenario"
            if self.gates.reason == "book_suspect":
                return "test_suspect_book_queue_overflow_scenario"
            if self.gates.reason == "edge_insufficient":
                return "test_wide_spread_scenario"
            if self.gates.reason == "risk_budget_exhausted":
                return "test_risk_budget_exhausted_scenario"
        
        # Healthy scenario
        if (self.ws.connection_state == "CONNECTED" and 
            not self.spot.is_stale and 
            self.book.book_consistency == "GOOD" and 
            self.book.is_dual_sided and
            self.gates.overall == "PASS"):
            return "test_dual_sided_book_good_edge_scenario"
        
        return None


def get_health_snapshot(
    ws_bridge,
    spot_service,
    market_state_store,
    risk_env,
    gate_decision,
) -> HealthSnapshot:
    """Collect a health snapshot from 15m stack components.
    
    Args:
        ws_bridge: WebSocket bridge instance
        spot_service: Unified spot service instance
        market_state_store: Market state store instance
        risk_env: Risk environment instance
        gate_decision: Current gate decision object
    
    Returns:
        HealthSnapshot with current health metrics
    """
    # Use the same clock source the WS bridge uses for its last-message timestamp.
    # This keeps the heartbeat age correct whether the process is in replay or live.
    now = replay_time()
    now_dt = datetime.now(timezone.utc)
    
    # Collect WS health
    # NOTE: 15m lean stack uses KalshiWebSocketBridge (merid.event_venues.kalshi.ws_bridge)
    if hasattr(ws_bridge, 'stats'):
        stats = ws_bridge.stats()
        connection_state = 'CONNECTED' if stats.get('connected', False) else 'DISCONNECTED'
        last_message_at = stats.get('last_message_time', None)
        # last_message_at is already in seconds (replay_time() or time.time()).
        heartbeat_age_s = (now - last_message_at) if last_message_at else 999999
        last_heartbeat_ts = last_message_at if last_message_at else 0
        is_connected = stats.get('connected', False)
    else:
        # Fallback for bridge without stats() method
        logger.warning("[HEALTH-SNAPSHOT] Bridge missing stats() method, using health_status()")
        health = ws_bridge.get_health_status()
        connection_state = health.get('bridge_status', 'UNKNOWN')
        last_message_at = health.get('last_message_at', None)
        heartbeat_age_s = (now - last_message_at) if last_message_at else 999999
        last_heartbeat_ts = last_message_at if last_message_at else 0
        is_connected = health.get('bridge_status') == 'ALIVE'
        is_running = ws_bridge.is_running() if hasattr(ws_bridge, 'is_running') else False
        last_message_at = getattr(ws_bridge, '_last_message_at', None)
        
        # Determine connection state
        if is_running and connection_state == 'CONNECTED':
            connection_state = 'CONNECTED'
        elif is_running and connection_state == 'RECONNECTING':
            connection_state = 'RECONNECTING'
        else:
            connection_state = 'DISCONNECTED'
        
        # Calculate heartbeat age
        if last_message_at:
            heartbeat_age_s = now - last_message_at
            last_heartbeat_ts = last_message_at
        else:
            heartbeat_age_s = 9999.0
            last_heartbeat_ts = now
        is_connected = is_running and connection_state == 'CONNECTED'
    
    ws_health = WsHealth(
        connection_state=connection_state,
        latency_ms=0.0,  # WS bridge doesn't expose latency directly
        last_heartbeat_ts=last_heartbeat_ts,
        heartbeat_age_s=heartbeat_age_s,
        is_connected=is_connected,
    )
    
    # Collect spot health
    spot_age = getattr(spot_service, 'last_update_age', 0.0)
    spot_threshold = getattr(spot_service, '_freshness_threshold_s', 30.0)
    spot_health = SpotHealth(
        last_update_age_s=spot_age,
        service_running=getattr(spot_service, '_running', False),
        freshness_threshold_s=spot_threshold,
        is_stale=spot_age > 60.0,  # Hard fail threshold
        stale_reason="age > 60s" if spot_age > 60.0 else None,
    )
    
    # Collect book health (from a sample market state)
    book_health = BookHealth(
        book_consistency="UNKNOWN",
        suspect_reason=None,
        last_update_age_s=0.0,
        has_bids=False,
        has_asks=False,
        is_dual_sided=False,
        best_bid_cents=None,
        best_ask_cents=None,
        spread_cents=None,
        spread_pct=None,
        is_stale=False,
    )
    
    # Try to get book health from market state store
    try:
        # Get a sample market state (e.g., BTC)
        catalog = getattr(market_state_store, '_catalog', None)
        if catalog:
            active_tickers = catalog.get_active_tickers()
            if active_tickers:
                sample_ticker = active_tickers[0]
                state = market_state_store.get_state(sample_ticker)
                if state:
                    book_age = now - state.last_update_ts
                    has_bids = len(state.bids) > 0
                    has_asks = len(state.asks) > 0
                    best_bid = state.best_bid_cents if has_bids else None
                    best_ask = state.best_ask_cents if has_asks else None
                    spread = (best_ask - best_bid) if (best_bid and best_ask) else None
                    mid = (best_bid + best_ask) / 2 if (best_bid and best_ask) else None
                    spread_pct = (spread / mid * 100) if (spread and mid) else None
                    
                    book_consistency = getattr(state, 'book_consistency', 'UNKNOWN')
                    suspect_reason = getattr(state, 'suspect_reason', None)
                    
                    book_health = BookHealth(
                        book_consistency=book_consistency,
                        suspect_reason=suspect_reason,
                        last_update_age_s=book_age,
                        has_bids=has_bids,
                        has_asks=has_asks,
                        is_dual_sided=has_bids and has_asks,
                        best_bid_cents=best_bid,
                        best_ask_cents=best_ask,
                        spread_cents=spread,
                        spread_pct=spread_pct,
                        is_stale=book_age > 10.0,  # Book stale threshold
                    )
    except Exception as e:
        # If we can't get book health, keep defaults
        pass
    
    # Cross-layer consistency: if WS is disconnected, mark book as SUSPECT
    # This must be OUTSIDE the try/except to ensure it always runs
    if not ws_health.is_connected:
        logger.info("[HEALTH-SNAPSHOT] Overriding book_consistency to SUSPECT due to WS disconnected")
        book_health = BookHealth(
            book_consistency="SUSPECT",
            suspect_reason="ws_disconnected",
            last_update_age_s=book_health.last_update_age_s if book_health else 0.0,
            has_bids=book_health.has_bids if book_health else False,
            has_asks=book_health.has_asks if book_health else False,
            is_dual_sided=book_health.is_dual_sided if book_health else False,
            best_bid_cents=book_health.best_bid_cents if book_health else None,
            best_ask_cents=book_health.best_ask_cents if book_health else None,
            spread_cents=book_health.spread_cents if book_health else None,
            spread_pct=book_health.spread_pct if book_health else None,
            is_stale=True,  # Force stale when WS disconnected
        )
    
    # Collect risk health
    try:
        utilization = risk_env.utilization() if hasattr(risk_env, 'utilization') else 0.0
        has_capacity = risk_env.has_capacity() if hasattr(risk_env, 'has_capacity') else True
    except Exception:
        utilization = 0.0
        has_capacity = True
    
    risk_health = RiskHealth(
        utilization_pct=utilization,
        has_capacity=has_capacity,
        is_exhausted=not has_capacity,
    )
    
    # Collect gate decision
    gate_health = GateDecision(
        spot_age=getattr(gate_decision, 'spot_age', 'UNKNOWN'),
        book_freshness=getattr(gate_decision, 'book_freshness', 'UNKNOWN'),
        liquidity=getattr(gate_decision, 'liquidity', 'UNKNOWN'),
        data_quality=getattr(gate_decision, 'data_quality', 'UNKNOWN'),
        edge=getattr(gate_decision, 'edge', 'UNKNOWN'),
        risk=getattr(gate_decision, 'risk', 'UNKNOWN'),
        overall=getattr(gate_decision, 'overall', 'UNKNOWN'),
        reason=getattr(gate_decision, 'reason', None),
    )

    # 2026-08-29: Assert the stuck-position quarantine path is active.
    quarantine_path = "unknown"
    try:
        from merid.event_venues.kalshi.position_cache import get_position_cache
        position_cache = get_position_cache()
        quarantine_path = "active" if position_cache.quarantine_path_active else "inactive"
    except Exception as exc:
        logger.warning("[HEALTH-SNAPSHOT] Could not read quarantine path state: %s", exc)

    return HealthSnapshot(
        timestamp=now_dt.isoformat(),
        ws=ws_health,
        spot=spot_health,
        book=book_health,
        risk=risk_health,
        gates=gate_health,
        quarantine_path=quarantine_path,
    )


def log_health_snapshot(snapshot: HealthSnapshot, logger):
    """Log health snapshot in a structured format.
    
    This logs both a human-readable summary and the full JSON snapshot
    for production debugging and mapping to scenario tests.
    """
    # Log human-readable summary
    logger.info(snapshot.to_summary())
    
    # Log scenario mapping
    scenario = snapshot.map_to_scenario()
    if scenario:
        logger.info(f"[HEALTH-SCENARIO-MAP] Current state maps to scenario: {scenario}")
    else:
        logger.info("[HEALTH-SCENARIO-MAP] Current state does not map to a specific scenario")
    
    # Log full JSON snapshot (at debug level to avoid log spam)
    logger.debug(f"[HEALTH-SNAPSHOT-JSON] {snapshot.to_json()}")
