"""Halt diagnosis endpoint — unified status for all P0/P1 halt conditions.

Per Halt Conditions Audit: provides a single "halt diagnosis" surface explaining
current halt state and resolution steps.

Endpoint: GET /api/v1/system/halt-diagnosis
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status

from utils.logger import get_logger

logger = get_logger("web.api.halt_diagnosis")

router = APIRouter()


@router.get("/api/v1/system/halt-diagnosis")
async def get_halt_diagnosis() -> Dict[str, Any]:
    """Get comprehensive halt diagnosis — unified status for all P0/P1 conditions.
    
    Returns:
        Dict with:
        - gate_state: ACTIVE / LIMITED / BLOCKED
        - kill_switch: state, reason, timestamp
        - phantom_kill: armed, reason, positions
        - reconciliation: status, last_run, discrepancies
        - ws_health: status, failover_mode
        - price_feed: major_crypto_status, alt_crypto_status
        - kalshi_client: status, auth_ok, circuit_breaker
        - next_steps: list of operator actions to resolve
    """
    diagnosis: Dict[str, Any] = {
        "timestamp": time.time(),
        "gate_state": "unknown",
        "kill_switch": {},
        "phantom_kill": {},
        "reconciliation": {},
        "ws_health": {},
        "price_feed": {},
        "kalshi_client": {},
        "next_steps": [],
    }
    
    # 1. Execution gate state
    try:
        from core.execution_gate import check_execution_gate, GateState
        gate = check_execution_gate()
        diagnosis["gate_state"] = gate.gate_state
        diagnosis["execution_blocked"] = gate.blocked
        diagnosis["safe_to_trade"] = gate.safe_to_trade
        diagnosis["gate_reasons"] = [
            {
                "source": r.source,
                "severity": r.severity,
                "message": r.message,
                "hint": r.hint,
            }
            for r in gate.reasons
        ]
    except Exception as exc:
        logger.warning("Halt diagnosis: gate check failed: %s", exc)
        diagnosis["gate_state"] = "error"
        diagnosis["gate_error"] = str(exc)
    
    # 2. Kill switch status
    try:
        from merid.risk.kill_switches import risk_controller, KillSwitchState
        ks_state = risk_controller.get_state()
        diagnosis["kill_switch"] = {
            "active": ks_state == KillSwitchState.TRIGGERED,
            "state": ks_state.value,
            "reason": risk_controller.get_kill_reason(),
            "timestamp": risk_controller._kill_timestamp.isoformat() if risk_controller._kill_timestamp else None,
            "error_budget": risk_controller.get_error_budget_status(),
        }
    except Exception as exc:
        logger.warning("Halt diagnosis: kill switch check failed: %s", exc)
        diagnosis["kill_switch"] = {"error": str(exc)}
    
    # 3. Phantom kill switch
    try:
        from merid.reconciliation import get_phantom_kill_status
        phantom = get_phantom_kill_status()
        diagnosis["phantom_kill"] = phantom
    except Exception as exc:
        logger.warning("Halt diagnosis: phantom kill check failed: %s", exc)
        diagnosis["phantom_kill"] = {"error": str(exc)}
    
    # 4. Reconciliation status
    try:
        from merid.reconciliation import (
            get_reconciliation_status,
            has_critical_discrepancies,
            get_last_reconciliation_ts,
        )
        recon_status = get_reconciliation_status()
        diagnosis["reconciliation"] = {
            "status": "critical" if recon_status.get("execution_gate_blocked") else "ok",
            "last_run_ts": get_last_reconciliation_ts(),
            "last_run_ago_sec": time.time() - get_last_reconciliation_ts() if get_last_reconciliation_ts() else None,
            "discrepancy_count": recon_status.get("discrepancy_count", 0),
            "critical_count": recon_status.get("critical_count", 0),
            "execution_gate_blocked": recon_status.get("execution_gate_blocked", True),
        }
    except Exception as exc:
        logger.warning("Halt diagnosis: reconciliation check failed: %s", exc)
        diagnosis["reconciliation"] = {"error": str(exc)}
    
    # 5. WebSocket health
    try:
        from merid.event_venues.kalshi.ws import get_ws_bridge
        ws = get_ws_bridge()
        ws_status = ws.get_status() if hasattr(ws, "get_status") else {}
        diagnosis["ws_health"] = {
            "connected": ws_status.get("connected", False),
            "status": ws_status.get("status", "unknown"),
            "last_message_ago_sec": ws_status.get("last_message_ago_sec"),
            "failover_mode": ws_status.get("failover_mode", False),
            "reconnect_count": ws_status.get("reconnect_count", 0),
        }
    except Exception as exc:
        logger.debug("Halt diagnosis: WS health check failed: %s", exc)
        diagnosis["ws_health"] = {"error": str(exc), "status": "unknown"}
    
    # 6. Price feed status
    try:
        from core.execution_gate import check_price_feed_staleness
        feed_result = check_price_feed_staleness()
        diagnosis["price_feed"] = {
            "safe_to_trade": feed_result.get("safe_to_trade", False),
            "stale_count": len(feed_result.get("stale_symbols", [])),
            "critical_count": feed_result.get("critical_count", 0),
            "stale_symbols": [s.get("symbol") for s in feed_result.get("stale_symbols", [])][:10],
            "groups": feed_result.get("groups", {}),
        }
    except Exception as exc:
        logger.warning("Halt diagnosis: price feed check failed: %s", exc)
        diagnosis["price_feed"] = {"error": str(exc)}
    
    # 7. Kalshi client status
    try:
        from merid.event_venues.kalshi.client import get_kalshi_client
        client = get_kalshi_client()
        client_status = client.get_status() if hasattr(client, "get_status") else {}
        diagnosis["kalshi_client"] = {
            "authenticated": client_status.get("authenticated", False),
            "circuit_breaker": client_status.get("circuit_breaker", "unknown"),
            "request_count": client_status.get("request_count", 0),
            "error_count": client_status.get("error_count", 0),
        }
    except Exception as exc:
        logger.debug("Halt diagnosis: Kalshi client check failed: %s", exc)
        diagnosis["kalshi_client"] = {"error": str(exc), "status": "unknown"}
    
    # 8. Compute next steps for operator
    diagnosis["next_steps"] = _compute_next_steps(diagnosis)
    
    # 9. Overall health summary
    diagnosis["summary"] = _compute_summary(diagnosis)
    
    return diagnosis


def _compute_next_steps(diagnosis: Dict[str, Any]) -> List[Dict[str, str]]:
    """Compute operator next steps based on diagnosis."""
    steps: List[Dict[str, str]] = []
    
    # Kill switch triggered
    if diagnosis.get("kill_switch", {}).get("active"):
        reason = diagnosis["kill_switch"].get("reason", "unknown")
        steps.append({
            "priority": "P0",
            "action": "Reset kill switch via Mode & Safety panel",
            "detail": f"Kill switch active: {reason}",
            "hint": "Navigate to Mode & Safety panel and click 'Reset Kill Switch' after investigating the trigger cause.",
        })
    
    # Phantom kill armed
    if diagnosis.get("phantom_kill", {}).get("armed"):
        positions = diagnosis["phantom_kill"].get("positions", [])
        steps.append({
            "priority": "P0",
            "action": "Clear phantom kill switch after reconciliation review",
            "detail": f"{len(positions)} phantom position(s) detected",
            "hint": f"Review reconciliation discrepancies, then call clear_phantom_kill_switch() with operator reason. Positions: {', '.join(positions[:3])}",
        })
    
    # Reconciliation blocked
    if diagnosis.get("reconciliation", {}).get("execution_gate_blocked"):
        critical = diagnosis["reconciliation"].get("critical_count", 0)
        steps.append({
            "priority": "P1",
            "action": "Run reconciliation or force-align positions",
            "detail": f"Reconciliation blocked: {critical} critical discrepancies",
            "hint": "Wait for next reconciliation cycle or trigger manual run from System settings.",
        })
    
    # Price feed critical
    critical_feed = diagnosis.get("price_feed", {}).get("critical_count", 0)
    if critical_feed > 0:
        steps.append({
            "priority": "P0",
            "action": "Check major crypto price feed connectivity",
            "detail": f"{critical_feed} critical price feed(s) stale",
            "hint": "Check CoinGecko/Coinbase connectivity in Venue Health Grid.",
        })
    
    # WS failed
    ws_status = diagnosis.get("ws_health", {}).get("status", "unknown")
    if ws_status == "failed":
        steps.append({
            "priority": "P1",
            "action": "Check Kalshi WebSocket connectivity",
            "detail": "WebSocket connection failed",
            "hint": "System will failover to REST polling. Check Kalshi API status page.",
        })
    
    # Kalshi auth failure
    if not diagnosis.get("kalshi_client", {}).get("authenticated", True):
        steps.append({
            "priority": "P0",
            "action": "Check Kalshi API credentials",
            "detail": "Kalshi client not authenticated",
            "hint": "Verify KALSHI_API_KEY and KALSHI_PRIVATE_KEY_PATH in .env",
        })
    
    # Gate LIMITED
    if diagnosis.get("gate_state") == "limited":
        steps.append({
            "priority": "P2",
            "action": "Review warning conditions",
            "detail": "Execution gate in LIMITED mode (reduce-only)",
            "hint": "Gate allows position reduction but blocks new entries. Review gate_reasons.",
        })
    
    # If everything looks good but gate is still blocked
    if not steps and diagnosis.get("execution_blocked"):
        steps.append({
            "priority": "P1",
            "action": "Review gate reasons for unknown block",
            "detail": "Gate blocked but no recognized condition found",
            "hint": "Check gate_reasons array for details.",
        })
    
    # If all clear
    if not steps:
        steps.append({
            "priority": "INFO",
            "action": "No action required",
            "detail": "All P0/P1 halt conditions clear",
            "hint": "System healthy — continue normal monitoring.",
        })
    
    return steps


def _compute_summary(diagnosis: Dict[str, Any]) -> str:
    """Compute human-readable summary of halt state."""
    parts: List[str] = []
    
    gate = diagnosis.get("gate_state", "unknown")
    if gate == "blocked":
        parts.append("EXECUTION BLOCKED")
    elif gate == "limited":
        parts.append("REDUCED MODE")
    elif gate == "clear":
        parts.append("OPERATIONAL")
    else:
        parts.append(f"STATE: {gate}")
    
    if diagnosis.get("kill_switch", {}).get("active"):
        parts.append("KILL SWITCH ACTIVE")
    
    if diagnosis.get("phantom_kill", {}).get("armed"):
        parts.append("PHANTOM KILL ARMED")
    
    return " | ".join(parts) if parts else "UNKNOWN"
