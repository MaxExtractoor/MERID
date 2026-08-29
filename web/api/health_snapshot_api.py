"""
Health Snapshot API Endpoint

Provides a REST endpoint for the 15m health snapshot, allowing
external monitoring systems to query the current health state.

This maps production health to the scenario categories tested in
tests/15m_scenario_tests/.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any
from utils.logger import get_logger

logger = get_logger("web.api.health_snapshot_api")

router = APIRouter(prefix="/api/v1/health-snapshot", tags=["health-snapshot"])


class WsHealthModel(BaseModel):
    """WebSocket health metrics."""
    connection_state: str
    latency_ms: float
    heartbeat_age_s: float
    is_connected: bool


class SpotHealthModel(BaseModel):
    """Spot service health metrics."""
    last_update_age_s: float
    service_running: bool
    is_stale: bool
    stale_reason: Optional[str]


class BookHealthModel(BaseModel):
    """Orderbook health metrics."""
    book_consistency: str
    suspect_reason: Optional[str]
    last_update_age_s: float
    is_dual_sided: bool
    best_bid_cents: Optional[int]
    best_ask_cents: Optional[int]
    spread_cents: Optional[int]
    spread_pct: Optional[float]
    is_stale: bool


class RiskHealthModel(BaseModel):
    """Risk environment health metrics."""
    utilization_pct: float
    has_capacity: bool
    is_exhausted: bool


class GateDecisionModel(BaseModel):
    """Gate decision metrics."""
    spot_age: str
    book_freshness: str
    liquidity: str
    data_quality: str
    edge: str
    risk: str
    overall: str
    reason: Optional[str]


class TradingHealthModel(BaseModel):
    """Trading/execution health for the current 15m window."""
    status: str = "unknown"  # watching | no_candidates | executing | error | unknown
    last_cycle_ts: Optional[str] = None
    last_cycle_age_s: Optional[float] = None
    candidates_last_cycle: int = 0
    executed_last_cycle: int = 0
    rejection_breakdown: Dict[str, int] = {}
    open_orders: int = 0
    open_positions: int = 0
    loop_error_count: int = 0


class HealthSnapshotModel(BaseModel):
    """Complete 15m health snapshot."""
    timestamp: str
    ws: WsHealthModel
    spot: SpotHealthModel
    book: BookHealthModel
    risk: RiskHealthModel
    gates: GateDecisionModel
    quarantine_path: str = "unknown"  # active / inactive / unknown
    scenario_mapping: Optional[str] = None
    trading: Optional[TradingHealthModel] = None


@router.get("/", response_model=HealthSnapshotModel)
async def get_health_snapshot(request: Request):
    """Get the current 15m health snapshot.
    
    Returns a structured health snapshot that mirrors the scenario
    categories tested in tests/15m_scenario_tests/. This allows
    production issues to be mapped back to tested scenarios.
    
    Returns:
        HealthSnapshotModel with current health metrics
    """
    try:
        from merid.monitoring.health_snapshot import get_health_snapshot, log_health_snapshot
        from dataclasses import asdict
        
        # Get app state to access 15m components
        app = request.app
        state = app.state
        
        # Extract components from app.state
        ws_bridge = getattr(state, 'ws_bridge', None)
        spot_service = getattr(state, 'unified_spot', None)
        market_state_store = getattr(state, 'market_state_store', None)
        bankroll = getattr(state, 'bankroll', None)
        
        # Log component availability for debugging
        logger.info(
            f"[HEALTH-SNAPSHOT-API] Component availability: "
            f"ws_bridge={ws_bridge is not None}, "
            f"spot_service={spot_service is not None}, "
            f"market_state_store={market_state_store is not None}, "
            f"bankroll={bankroll is not None}"
        )
        
        # Also write to diagnostic file for visibility
        try:
            from pathlib import Path
            from datetime import datetime, timezone
            diag_path = Path(__file__).parent / "health_diagnostic.txt"
            with open(diag_path, "a") as f:
                f.write(f"[{datetime.now(timezone.utc)}] [HEALTH-SNAPSHOT-API] Component availability: ws_bridge={ws_bridge is not None}, spot_service={spot_service is not None}, market_state_store={market_state_store is not None}, bankroll={bankroll is not None}\n")
                f.flush()
        except Exception:
            pass
        
        # Create a mock gate decision for now (in real implementation, this would come from the agent grid)
        class MockGateDecision:
            spot_age = "PASS"
            book_freshness = "PASS"
            liquidity = "PASS"
            data_quality = "PASS"
            edge = "PASS"
            risk = "PASS"
            overall = "PASS"
            reason = None
        
        gate_decision = MockGateDecision()
        
        # Collect health snapshot - be lenient, collect what we can
        missing_components = []
        if not ws_bridge:
            missing_components.append("ws_bridge")
        if not spot_service:
            missing_components.append("spot_service")
        if not market_state_store:
            missing_components.append("market_state_store")
        if not bankroll:
            missing_components.append("bankroll")
        
        if missing_components:
            logger.warning(f"[HEALTH-SNAPSHOT-API] Missing components: {missing_components}, returning partial snapshot")
        
        # Try to collect snapshot even if some components are missing
        try:
            logger.info("[HEALTH-SNAPSHOT-API] About to call get_health_snapshot")
            snapshot = get_health_snapshot(
                ws_bridge=ws_bridge,
                spot_service=spot_service,
                market_state_store=market_state_store,
                risk_env=bankroll,
                gate_decision=gate_decision,
            )
            logger.info("[HEALTH-SNAPSHOT-API] get_health_snapshot completed successfully")
            
            # Convert to dict and add scenario mapping
            snapshot_dict = snapshot.to_dict()
            snapshot_dict["scenario_mapping"] = snapshot.map_to_scenario()

            # Augment with live trading/execution status.
            try:
                loop = getattr(state, "kalshi_15m_loop", None)
                agent_grid = getattr(state, "agent_grid_15m", None)
                position_cache = getattr(state, "position_cache", None)

                last_cycle_ts = getattr(loop, "last_cycle_ts", None)
                last_cycle_age_s = None
                if last_cycle_ts is not None:
                    from datetime import datetime, timezone
                    last_cycle_age_s = (datetime.now(timezone.utc) - last_cycle_ts).total_seconds()
                    last_cycle_ts = last_cycle_ts.isoformat()

                executed = getattr(loop, "_last_tick_executed", 0) if loop else 0
                candidates = getattr(loop, "_last_tick_total_candidates", 0) if loop else 0
                rejection_breakdown = getattr(loop, "_last_tick_rejection_breakdown", {}) if loop else {}

                if loop is None:
                    status = "unknown"
                elif executed > 0:
                    status = "executing"
                elif candidates == 0:
                    status = "no_candidates"
                else:
                    status = "candidates_pending"

                open_orders = 0
                if agent_grid is not None:
                    open_orders = len(getattr(agent_grid, "_last_open_orders", []))

                open_positions = 0
                if position_cache is not None:
                    try:
                        all_positions = position_cache.get_all_positions(validate_freshness=False)
                        open_positions = sum(1 for p in all_positions.values() if getattr(p, "contracts", 0) > 0)
                    except Exception:
                        pass

                snapshot_dict["trading"] = {
                    "status": status,
                    "last_cycle_ts": last_cycle_ts,
                    "last_cycle_age_s": last_cycle_age_s,
                    "candidates_last_cycle": candidates,
                    "executed_last_cycle": executed,
                    "rejection_breakdown": rejection_breakdown,
                    "open_orders": open_orders,
                    "open_positions": open_positions,
                    "loop_error_count": getattr(loop, "error_count", 0) if loop else 0,
                }
            except Exception as trading_err:
                logger.warning("[HEALTH-SNAPSHOT-API] Failed to collect trading status: %s", trading_err)

            logger.info(f"[HEALTH-SNAPSHOT-API] Returning snapshot with book_consistency={snapshot_dict.get('book', {}).get('book_consistency')}")
            return snapshot_dict
        except Exception as e:
            logger.error(f"[HEALTH-SNAPSHOT-API] Error collecting snapshot: {e}, returning placeholder", exc_info=True)
            # Return placeholder if collection fails
            return {
                "timestamp": "2026-06-05T00:00:00Z",
                "ws": {
                    "connection_state": "UNKNOWN",
                    "latency_ms": 0.0,
                    "heartbeat_age_s": 0.0,
                    "is_connected": False
                },
                "spot": {
                    "last_update_age_s": 0.0,
                    "service_running": False,
                    "is_stale": False,
                    "stale_reason": None
                },
                "book": {
                    "book_consistency": "UNKNOWN",
                    "suspect_reason": None,
                    "last_update_age_s": 0.0,
                    "is_dual_sided": False,
                    "best_bid_cents": None,
                    "best_ask_cents": None,
                    "spread_cents": None,
                    "spread_pct": None,
                    "is_stale": False
                },
                "risk": {
                    "utilization_pct": 0.0,
                    "has_capacity": True,
                    "is_exhausted": False
                },
                "gates": {
                    "spot_age": "UNKNOWN",
                    "book_freshness": "UNKNOWN",
                    "liquidity": "UNKNOWN",
                    "data_quality": "UNKNOWN",
                    "edge": "UNKNOWN",
                    "risk": "UNKNOWN",
                    "overall": "UNKNOWN",
                    "reason": None
                },
                "scenario_mapping": None
            }
    except Exception as e:
        logger.error(f"[HEALTH-SNAPSHOT-API] Error collecting health snapshot: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary")
async def get_health_summary():
    """Get a human-readable health summary.
    
    Returns a simple text summary of the current health state,
    suitable for quick checks or alerting.
    
    Returns:
        Dict with summary information
    """
    try:
        # Placeholder - would collect actual health snapshot
        return {
            "status": "unknown",
            "message": "Health snapshot collection not yet integrated",
            "timestamp": "2026-06-05T00:00:00Z",
        }
    except Exception as e:
        logger.error(f"[HEALTH-SNAPSHOT-API] Error collecting health summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scenario")
async def get_mapped_scenario():
    """Get the scenario test that matches current health.
    
    Returns the name of the closest matching scenario test from
    tests/15m_scenario_tests/, or None if no match.
    
    This helps map production issues back to tested scenarios.
    
    Returns:
        Dict with scenario mapping information
    """
    try:
        # Placeholder - would collect actual health snapshot and map to scenario
        return {
            "scenario": None,
            "message": "Health snapshot collection not yet integrated",
            "timestamp": "2026-06-05T00:00:00Z",
        }
    except Exception as e:
        logger.error(f"[HEALTH-SNAPSHOT-API] Error mapping to scenario: {e}")
        raise HTTPException(status_code=500, detail=str(e))
