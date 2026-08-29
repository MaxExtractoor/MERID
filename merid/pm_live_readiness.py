"""Single-call PM live readiness — env, grid boot, kill switch, execution gate, Redis.

Used by ``GET /api/v1/operator/pm-live-readiness`` so ops get one binary answer
plus structured checks (same semantics as the prod-go-live checklist).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def is_env_prod_live_pm() -> bool:
    """True when env matches the canonical production + live PM profile."""
    return (
        os.getenv("MERID_PM_PROFILE", "").strip().lower() == "production"
        and os.getenv("MERID_PM_TRADING_MODE", "").strip().lower() == "live"
        and _truthy("MERID_PM_LIVE_ENABLED")
        and os.getenv("MERID_KALSHI_WS_CLIENT", "").strip().lower() == "ws"
        and not _truthy("MERID_ENABLE_KALSHI_CT")
        and os.getenv("MERID_VALIDATION_MODE", "").strip() != "1"
        and not _truthy("KALSHI_TRADER_SMOKE_TEST")
        and _truthy("KALSHI_CONFIRM_LIVE")
        and os.getenv("KALSHI_ENV", "").strip().lower() == "live"
        and _truthy("MERID_ALLOW_LIVE_TRADES")
    )


def _redis_snapshot() -> Dict[str, Any]:
    try:
        from merid.infra.redis_resilient import redis_health

        return dict(redis_health())
    except Exception as exc:
        return {"enabled": False, "healthy": False, "reason": str(exc)}


def compute_pm_live_readiness() -> Dict[str, Any]:
    """Build readiness payload (no HTTP)."""
    notes: List[str] = []

    env_ok = is_env_prod_live_pm()
    if not env_ok:
        notes.append("env does not match prod+live PM checklist (see is_env_prod_live_pm fields in code)")

    grid_ok = False
    try:
        from merid.prediction.agent_grid_15m import get_agent_grid

        grid = get_agent_grid()
        # LeanAgentGrid15m doesn't have startup_health() - check if running
        grid_ok = bool(grid and grid._running)
    except Exception as exc:
        notes.append(f"agent grid check failed: {exc}")

    kill_ok = False
    kill_switch: Dict[str, Any] = {}
    try:
        from merid.risk.kill_switches import risk_controller

        kill_switch = {
            "can_trade": risk_controller.can_trade(),
            "active": not risk_controller.can_trade(),
            "reason": risk_controller.get_kill_reason(),
        }
        kill_ok = bool(kill_switch.get("can_trade"))
    except Exception as exc:
        kill_switch = {"error": str(exc)}
        notes.append(f"kill switch read failed: {exc}")

    gate_ok = False
    gate: Dict[str, Any] = {}
    try:
        from core.execution_gate import check_execution_gate

        st = check_execution_gate()
        gate = {
            "blocked": st.blocked,
            "safe_to_trade": st.safe_to_trade,
            "gate_state": st.gate_state,
            "critical_sources": sorted({r.source for r in st.reasons if r.severity == "critical"}),
            "warning_sources": sorted({r.source for r in st.reasons if r.severity == "warning"}),
        }
        gate_ok = bool(st.safe_to_trade) and not st.blocked
    except Exception as exc:
        gate = {"error": str(exc)}
        notes.append(f"execution gate failed: {exc}")

    vg_ok = False
    venue_gate: Dict[str, Any] = {}
    try:
        from merid.prediction.venue_gate import VenueGate

        vg = VenueGate()
        venue_gate = {
            "is_live": vg.is_live,
            "live_enabled": getattr(vg, "live_enabled", None),
            "mode": getattr(getattr(vg, "mode", None), "value", str(vg.mode)),
        }
        vg_ok = bool(vg.is_live)
        if not vg_ok:
            notes.append("VenueGate.is_live is false — check MERID_ALLOW_LIVE_TRADES / PM mode")
    except Exception as exc:
        venue_gate = {"error": str(exc)}
        notes.append(f"VenueGate read failed: {exc}")

    redis_info = _redis_snapshot()
    if redis_info.get("enabled") and not redis_info.get("healthy"):
        notes.append(f"redis degraded (non-blocking): {redis_info.get('reason', '')}")

    ready = all([env_ok, grid_ok, kill_ok, gate_ok, vg_ok])

    return {
        "ready_for_live_pm_trading": ready,
        "checks": {
            "env_prod_live": env_ok,
            "agent_grid_started": grid_ok,
            "kill_switch_can_trade": kill_ok,
            "execution_gate_clear": gate_ok,
            "venue_gate_live": vg_ok,
        },
        "redis": redis_info,
        "agent_grid_startup": grid_ok,
        "kill_switch": kill_switch,
        "execution_gate": gate,
        "venue_gate": venue_gate,
        "notes": notes,
    }
