"""Single-shot operator view: gates, spot venues, risk — complements per-subsystem health APIs."""

from __future__ import annotations

import os
import time
from typing import Any, Dict

SNAPSHOT_SCHEMA_VERSION = 1


def build_risk_posture_snapshot() -> Dict[str, Any]:
    """Aggregate risk/gate posture for dashboards and audits (best-effort, no secrets)."""
    ts = time.time()
    snap: Dict[str, Any] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "timestamp": ts,
        "execution_gate": None,
        "risk_controller": None,
        "venue_gate": None,
        "kalshi_risk": None,
        "spot": None,
        "execution_guard": None,
        "ci_hints": {
            "MERID_CI_LAST_KALSHI_P0": os.environ.get("MERID_CI_LAST_KALSHI_P0"),
            "MERID_CI_LAST_KALSHI_LIVE_READY": os.environ.get("MERID_CI_LAST_KALSHI_LIVE_READY"),
        },
    }

    try:
        from core.execution_gate import check_execution_gate

        _eg = check_execution_gate()
        snap["execution_gate"] = _eg.to_dict()
    except Exception as exc:
        snap["execution_gate"] = {"error": str(exc)}

    try:
        from merid.risk.kill_switches import risk_controller as _rc

        snap["risk_controller"] = {
            "can_trade": _rc.can_trade(),
            "kill_reason": _rc.get_kill_reason(),
        }
    except Exception as exc:
        snap["risk_controller"] = {"error": str(exc)}

    try:
        from merid.prediction.venue_gate import get_venue_gate

        _vg = get_venue_gate()
        snap["venue_gate"] = {
            "live_enabled": _vg.live_enabled,
            "mode": _vg.mode.value if hasattr(_vg.mode, "value") else str(_vg.mode),
            "is_live": _vg.is_live,
        }
    except Exception as exc:
        snap["venue_gate"] = {"error": str(exc)}

    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk

        _kr = get_kalshi_risk()
        _kr._sync_pnl_from_ledger()
        _st = _kr.state

        # BANKROLL UNIFICATION: Fetch from v2 unified service for comparison
        _effective_usd = None
        _live_usd = None
        try:
            from merid.event_venues.kalshi import get_equity_for_risk_calc_sync, get_summary_sync
            _effective_usd = get_equity_for_risk_calc_sync()
            _summary = get_summary_sync()
            if _effective_usd:
                _effective_usd = round(_effective_usd, 2)
            if _summary and _summary.equity_usd is not None:
                _live_usd = round(float(_summary.equity_usd), 2)
        except Exception:
            pass

        snap["kalshi_risk"] = {
            "kill_switch_active": bool(_kr.kill_switch_active),
            "kill_switch_reason": getattr(_st, "kill_switch_reason", None),
            "daily_pnl_usd": getattr(_st, "daily_pnl_usd", None),
            "current_equity_usd": getattr(_st, "current_equity_usd", None),
            # Unified bankroll data for observability
            "effective_bankroll_usd": _effective_usd,
            "live_venue_balance_usd": _live_usd,
            "bankroll_source": "unified_bankroll_service" if _effective_usd else "kalshi_risk_manager",
        }
    except Exception as exc:
        snap["kalshi_risk"] = {"error": str(exc)}

    try:
        from merid.trading.crypto_spot_service import get_crypto_spot_service

        _svc = get_crypto_spot_service()
        _vh = _svc.venue_health_snapshot()
        snap["spot"] = {
            "venue_health": _vh,
            "any_degraded": any(str(v).lower() == "degraded" for v in _vh.values()),
        }
    except Exception as exc:
        snap["spot"] = {"error": str(exc)}

    try:
        from merid.execution_guard import get_execution_guard

        _sum = get_execution_guard().summary()
        snap["execution_guard"] = {
            "global_kill_switch": _sum.get("global_kill_switch"),
            "global_kill_reason": _sum.get("global_kill_reason"),
            "domain_caps": _sum.get("domain_caps"),
            "asset_caps": _sum.get("asset_caps"),
        }
    except Exception as exc:
        snap["execution_guard"] = {"error": str(exc)}

    return snap
