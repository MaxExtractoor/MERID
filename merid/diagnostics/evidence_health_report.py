"""Reserve/gate evidence-health report (WP6, 2026-11-12).

Distinct from ``merid.prediction.evidence_health``: that module tiers the
``live_entry_evidence.json`` artifact by age for admission gating.  This
module is the ops-facing *report* answering "is old evidence still
driving the current policy?" across every reserve and gate — bankroll
freshness, slot-allocator reservations, window-plan budget, capital
sleeve, scalp return model, market-state store, and hedge policy.

For each source it reports:

    sample_count, oldest/newest observation, epoch mix, last update,
    effective value, fallback reason, expiry/recheck time

This answers "is old evidence still driving the current policy?" without
requiring a manual consumer trace.  Every collector degrades gracefully —
a broken source reports ``unavailable`` with its reason rather than
raising or fabricating values.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.diagnostics.evidence_health_report")


def _iso(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except Exception:
        return None


def _age_s(ts: Optional[float], now: float) -> Optional[float]:
    if ts is None:
        return None
    try:
        return round(now - float(ts), 3)
    except Exception:
        return None


def _base(source: str, now: float) -> Dict[str, Any]:
    return {
        "source": source,
        "status": "unavailable",
        "sample_count": None,
        "oldest_observation_ts": None,
        "newest_observation_ts": None,
        "oldest_observation_age_s": None,
        "newest_observation_age_s": None,
        "epoch_mix": None,
        "last_update_ts": None,
        "last_update_age_s": None,
        "effective_value": {},
        "fallback_reason": None,
        "expiry_or_recheck_ts": None,
        "details": {},
        "generated_at": _iso(now),
    }


def _collect_bankroll(now: float) -> Dict[str, Any]:
    """Versioned bankroll snapshot — the equity basis for all sizing."""
    out = _base("bankroll_snapshot", now)
    try:
        from merid.event_venues.kalshi.bankroll_service_v2 import get_summary_sync

        summary = get_summary_sync(caller_module="evidence_health")
        if summary is None:
            out["fallback_reason"] = "no_bankroll_summary"
            out["details"]["note"] = "bankroll service has never produced a summary"
            return out

        as_of_ts = summary.as_of.timestamp() if summary.as_of else None
        state = getattr(summary.state, "value", str(summary.state))
        out.update({
            "status": "ok" if state == "fresh" else "degraded",
            "sample_count": 1,
            "oldest_observation_ts": as_of_ts,
            "newest_observation_ts": as_of_ts,
            "oldest_observation_age_s": _age_s(as_of_ts, now),
            "newest_observation_age_s": _age_s(as_of_ts, now),
            "last_update_ts": as_of_ts,
            "last_update_age_s": _age_s(as_of_ts, now),
            "effective_value": {
                "equity_usd": str(summary.equity_usd) if summary.equity_usd is not None else None,
                "available_cash_usd": str(summary.available_cash_usd) if summary.available_cash_usd is not None else None,
                "state": state,
                "using_cached": bool(getattr(summary, "using_cached", False)),
                "max_position_usd": str(summary.max_position_usd) if summary.max_position_usd is not None else None,
            },
            "fallback_reason": getattr(summary, "last_error_reason", None),
            "details": {
                "source": getattr(summary, "source", None),
                "consecutive_timeout_count": getattr(summary, "consecutive_timeout_count", None),
                "consecutive_error_count": getattr(summary, "consecutive_error_count", None),
            },
        })
        # Recheck time = staleness window boundary when knowable.
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service

            svc = get_bankroll_service()
            stale_after = getattr(svc, "_bankroll_stale_after_seconds", None)
            if as_of_ts is not None and stale_after:
                out["expiry_or_recheck_ts"] = as_of_ts + float(stale_after)
                out["details"]["stale_after_s"] = float(stale_after)
        except Exception:
            pass
        return out
    except Exception as exc:
        out["fallback_reason"] = f"collector_error:{type(exc).__name__}"
        return out


def _collect_slot_allocator(now: float) -> Dict[str, Any]:
    """Global slot allocator — working-order/position reservation state."""
    out = _base("slot_allocator", now)
    try:
        from merid.risk.global_slot_allocator import get_global_slot_allocator

        summary = get_global_slot_allocator().get_summary()
        slots = summary.get("slots") or []
        entry_times = [s.get("entry_time") for s in slots if s.get("entry_time")]
        oldest = min(entry_times) if entry_times else None
        newest = max(entry_times) if entry_times else None
        out.update({
            "status": "ok",
            "sample_count": len(slots),
            "oldest_observation_ts": oldest,
            "newest_observation_ts": newest,
            "oldest_observation_age_s": _age_s(oldest, now),
            "newest_observation_age_s": _age_s(newest, now),
            "last_update_ts": newest,
            "last_update_age_s": _age_s(newest, now),
            "effective_value": {
                "total_exposure_usd": summary.get("total_exposure_usd"),
                "available_exposure_usd": summary.get("available_exposure_usd"),
                "total_requests": summary.get("total_requests"),
                "total_allocations": summary.get("total_allocations"),
                "total_rejections": summary.get("total_rejections"),
                "total_releases": summary.get("total_releases"),
            },
            "details": {"slot_count": summary.get("slot_count")},
        })
        return out
    except Exception as exc:
        out["fallback_reason"] = f"collector_error:{type(exc).__name__}"
        return out


def _collect_window_plan(now: float) -> Dict[str, Any]:
    """Window-plan budget reservation policy (config-level evidence)."""
    out = _base("window_plan", now)
    try:
        from merid.prediction import window_plan as wp

        enabled = bool(wp.plan_enabled())
        out.update({
            "status": "ok" if enabled else "disabled",
            "sample_count": 1,
            "last_update_ts": now,
            "last_update_age_s": 0.0,
            "effective_value": {
                "enabled": enabled,
                "budget_usd": str(wp.plan_budget_usd()),
                "max_contracts_cc": wp.plan_max_contracts_cc(),
                "max_submissions": wp.plan_max_submissions(),
                "order_cap_usd": str(wp.plan_order_cap_usd()),
                "max_qty_cc": wp.plan_max_qty_cc(),
                "min_qty_cc": wp.plan_min_qty_cc(),
                "per_asset_cap_usd": str(wp.plan_per_asset_cap_usd()),
                "corr_cap_usd": str(wp.plan_corr_cap_usd()),
                "lift_sizing": wp.plan_lift_sizing(),
                "enforce_basket_leader": wp.plan_enforce_basket_leader(),
            },
            "expiry_or_recheck_ts": now + float(wp.plan_pending_ttl_s()),
            "details": {"pending_ttl_s": float(wp.plan_pending_ttl_s())},
        })
        return out
    except Exception as exc:
        out["fallback_reason"] = f"collector_error:{type(exc).__name__}"
        return out


def _collect_capital_sleeve(now: float) -> Dict[str, Any]:
    """Strategy capital sleeve — the equity basis intended for Kelly."""
    out = _base("capital_sleeve", now)
    try:
        from merid.risk.capital_sleeve import compute_capital_sleeve

        snap = compute_capital_sleeve()
        as_of_ts = snap.as_of.timestamp() if snap.as_of else None
        out.update({
            "status": "ok" if snap.state == "ok" else "degraded",
            "sample_count": 1,
            "oldest_observation_ts": as_of_ts,
            "newest_observation_ts": as_of_ts,
            "oldest_observation_age_s": _age_s(as_of_ts, now),
            "newest_observation_age_s": _age_s(as_of_ts, now),
            "last_update_ts": as_of_ts,
            "last_update_age_s": _age_s(as_of_ts, now),
            "effective_value": {
                "state": snap.state,
                "sleeve_equity_usd": snap.sleeve_equity_usd,
                "backed_equity_usd": snap.backed_equity_usd,
                "effective_equity_usd": snap.effective_equity_usd,
                "equity_total_usd": snap.equity_total_usd,
                "cash_trading_shard_usd": snap.cash_trading_shard_usd,
                "open_exposure_usd": snap.open_exposure_usd,
                "non_strategy_reserve_usd": snap.non_strategy_reserve_usd,
            },
            "fallback_reason": None if snap.state == "ok" else snap.state,
            "details": {"components": snap.components},
        })
        return out
    except Exception as exc:
        out["fallback_reason"] = f"collector_error:{type(exc).__name__}"
        return out


def _collect_return_model(now: float) -> Dict[str, Any]:
    """Scalp return model — must be unvalidated/absent until Release 2."""
    out = _base("scalp_return_model", now)
    try:
        from merid.risk.scalp_return_model import get_active_return_model

        model = get_active_return_model()
        if model is None:
            out.update({
                "status": "unvalidated",
                "fallback_reason": "no_active_return_model",
                "details": {"note": "expected until the empirical scalp-return model is validated (Release 2)"},
            })
            return out
        out.update({
            "status": "ok",
            "sample_count": getattr(model, "sample_count", None),
            "effective_value": {
                "model_id": getattr(model, "model_id", None),
                "version": getattr(model, "version", None),
            },
            "details": {"note": "active model present — verify validation provenance before sizing"},
        })
        return out
    except Exception as exc:
        out["fallback_reason"] = f"collector_error:{type(exc).__name__}"
        return out


def _collect_market_state(now: float) -> Dict[str, Any]:
    """Market-state store freshness across registered tickers."""
    out = _base("market_state_store", now)
    try:
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store

        store = get_kalshi_market_state_store()
        states = getattr(store, "_states", {}) or {}
        ts_values = []
        for st in states.values():
            for attr in ("last_update_ts", "updated_at_ts", "timestamp", "ts"):
                v = getattr(st, attr, None)
                if isinstance(v, (int, float)) and v > 0:
                    ts_values.append(float(v))
                    break
        if not ts_values:
            out["sample_count"] = len(states)
            out["fallback_reason"] = "no_timestamps_on_states" if states else "empty_store"
            out["details"]["registered_tickers"] = len(states)
            return out
        oldest, newest = min(ts_values), max(ts_values)
        out.update({
            "status": "ok",
            "sample_count": len(ts_values),
            "oldest_observation_ts": oldest,
            "newest_observation_ts": newest,
            "oldest_observation_age_s": _age_s(oldest, now),
            "newest_observation_age_s": _age_s(newest, now),
            "last_update_ts": newest,
            "last_update_age_s": _age_s(newest, now),
            "effective_value": {"registered_states": len(states)},
        })
        return out
    except Exception as exc:
        out["fallback_reason"] = f"collector_error:{type(exc).__name__}"
        return out


def _collect_hedge_policy(now: float) -> Dict[str, Any]:
    """Hedge producer policy state — entries gated, exits live."""
    out = _base("hedge_policy", now)
    try:
        from merid.hedging.config import get_hedge_config

        cfg = get_hedge_config()
        out.update({
            "status": "ok",
            "sample_count": 1,
            "last_update_ts": now,
            "last_update_age_s": 0.0,
            "effective_value": {
                "hedging_enabled": bool(cfg.enabled),
                "entries_enabled": bool(getattr(cfg, "entries_enabled", False)),
                "cross_asset_enabled": bool(cfg.cross_asset_enabled),
                "auto_exit_enabled": bool(getattr(cfg.auto_exit, "enabled", False)),
                "timeframes": sorted(cfg.timeframes.keys()),
            },
            "fallback_reason": (
                None if not cfg.entries_enabled
                else "entries_enabled_requires_shared_accounting"
            ),
            "details": {
                "note": "hedge entries gated off pending shared authorization/reservation accounting; exits unaffected",
            },
        })
        return out
    except Exception as exc:
        out["fallback_reason"] = f"collector_error:{type(exc).__name__}"
        return out


_COLLECTORS: Dict[str, Callable[[float], Dict[str, Any]]] = {
    "bankroll_snapshot": _collect_bankroll,
    "slot_allocator": _collect_slot_allocator,
    "window_plan": _collect_window_plan,
    "capital_sleeve": _collect_capital_sleeve,
    "scalp_return_model": _collect_return_model,
    "market_state_store": _collect_market_state,
    "hedge_policy": _collect_hedge_policy,
}


def build_evidence_health_report(
    sources: Optional[list] = None,
) -> Dict[str, Any]:
    """Build the evidence-health report across all reserves and gates.

    Args:
        sources: optional subset of collector names; default = all.
    """
    now = time.time()
    names = sources or list(_COLLECTORS.keys())
    report: Dict[str, Any] = {
        "generated_at_epoch": now,
        "generated_at": _iso(now),
        "sources": {},
    }
    for name in names:
        collector = _COLLECTORS.get(name)
        if collector is None:
            entry = _base(name, now)
            entry["fallback_reason"] = "unknown_source"
            report["sources"][name] = entry
            continue
        try:
            report["sources"][name] = collector(now)
        except Exception as exc:  # collector contract: never raise
            entry = _base(name, now)
            entry["fallback_reason"] = f"collector_error:{type(exc).__name__}"
            report["sources"][name] = entry
    return report


def format_evidence_health_text(report: Dict[str, Any]) -> str:
    """Human-readable rendering for ops review / logs."""
    lines = [
        f"Evidence health @ {_iso(report.get('generated_at_epoch'))}",
        "=" * 72,
    ]
    for name, src in (report.get("sources") or {}).items():
        lines.append(f"[{src.get('status', '?').upper()}] {name}")
        ev = src.get("effective_value") or {}
        for k, v in ev.items():
            lines.append(f"    {k}: {v}")
        sc = src.get("sample_count")
        lines.append(
            f"    samples={sc} oldest_age={src.get('oldest_observation_age_s')}s "
            f"newest_age={src.get('newest_observation_age_s')}s "
            f"last_update_age={src.get('last_update_age_s')}s"
        )
        if src.get("fallback_reason"):
            lines.append(f"    fallback_reason: {src['fallback_reason']}")
        if src.get("expiry_or_recheck_ts"):
            lines.append(f"    recheck_at: {_iso(src['expiry_or_recheck_ts'])}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover - manual ops entry point
    rep = build_evidence_health_report()
    print(format_evidence_health_text(rep))
