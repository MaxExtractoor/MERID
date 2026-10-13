"""Lane accounting for the marginal-band release cohort (2026-10-12).

The ``EDGE_BELOW_DYNAMIC_THRESHOLD`` marginal-release band admits candidates
whose net edge falls <=1c short of the stacked dynamic threshold, restricted
to the cohorts the settled counterfactual actually favored: NO side,
SOL/DOGE/XRP, outside the final TTE tail, taker (or empirical marginal
maker) route.  Cohort membership is decided in
``trade_decision.compute_trade_decision`` — this module owns everything that
must survive past the decision:

- **exposure caps** — one admission per asset per 15m window, a per-asset
  daily submission cap, and a lane-wide daily submission cap;
- **self-suspension** — the lane fails closed for the rest of the UTC day
  once it books ``MERID_MBAND_SUSPEND_CONSEC_LOSSES`` consecutive settled
  losses, ``MERID_MBAND_SUSPEND_DAILY_LOSS_CENTS`` of cumulative realized
  loss, or ``MERID_MBAND_SUSPEND_COHERENCE_FAILURES`` pre-wire router
  rejects (edge decayed / not marketable / spread too wide — the wire-time
  coherence checks doing their job, but repeatedly = the band's edge is
  systematically stale at submit time);
- **decision attribution** — ``record_submission`` persists
  decision_id -> lane metadata so ``_attribute_settlement`` can feed
  realized P&L back into the suspension counters across restarts.

State lives in ``data/marginal_band_lane.json`` and rolls on UTC day
boundaries (suspension included — a suspended lane re-opens next day under
the same counters discipline the other bounded lanes use).

All functions are fail-open: a bookkeeping error must never crash the
trading path.  Kill switch: ``MERID_MBAND_LANE_ENABLED=0`` makes every gate
read as closed.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

MERID_MBAND_LANE_ENABLED = os.environ.get(
    "MERID_MBAND_LANE_ENABLED", "1"
).strip().lower() in ("1", "true", "yes")

MERID_MBAND_DAILY_FILE = os.environ.get(
    "MERID_MBAND_DAILY_FILE", "data/marginal_band_lane.json"
)

# Exposure caps: one admitted submission per asset per window (the 15m
# ticker IS the window identity), per-asset daily cap, lane-wide daily cap.
MERID_MBAND_DAILY_CAP = int(os.environ.get("MERID_MBAND_DAILY_CAP", "8"))
MERID_MBAND_PER_ASSET_DAILY_CAP = int(
    os.environ.get("MERID_MBAND_PER_ASSET_DAILY_CAP", "4")
)

# Self-suspension triggers (UTC-day scoped):
#  - consecutive settled losses >= MERID_MBAND_SUSPEND_CONSEC_LOSSES
#  - cumulative realized loss <= -MERID_MBAND_SUSPEND_DAILY_LOSS_CENTS
#  - pre-wire coherence rejects >= MERID_MBAND_SUSPEND_COHERENCE_FAILURES
MERID_MBAND_SUSPEND_CONSEC_LOSSES = int(
    os.environ.get("MERID_MBAND_SUSPEND_CONSEC_LOSSES", "2")
)
MERID_MBAND_SUSPEND_DAILY_LOSS_CENTS = float(
    os.environ.get("MERID_MBAND_SUSPEND_DAILY_LOSS_CENTS", "75.0")
)
MERID_MBAND_SUSPEND_COHERENCE_FAILURES = int(
    os.environ.get("MERID_MBAND_SUSPEND_COHERENCE_FAILURES", "3")
)

_state_lock = threading.RLock()
_STATE_CACHE: Optional[Dict[str, Any]] = None
_STATE_CACHE_PATH: Optional[str] = None


def _utc_day(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat()


def _default_state(now: float) -> Dict[str, Any]:
    return {
        "date": _utc_day(now),
        "count": 0,
        # per-asset daily submission counts: {"SOL": n}
        "assets": {},
        # per-asset window dedupe: {"SOL": "KXSOL15M-..."} — ticker is the
        # window identity, so a recorded ticker means the asset already
        # consumed its slot for this 15m window.
        "windows": {},
        # decision_id -> submission meta for settlement/coherence joins.
        # Durable across restarts like threshold_cells.decision_cell_map.
        "open": {},
        "realized_pnl_cents": 0.0,
        "consecutive_losses": 0,
        "coherence_failures": 0,
        "suspended": False,
        "suspend_reason": None,
    }


def _roll_daily_locked(st: Dict[str, Any], now: float) -> None:
    """Reset day-scoped fields when the UTC day moved (incl. suspension)."""
    if st.get("date") == _utc_day(now):
        return
    open_map = st.get("open") if isinstance(st.get("open"), dict) else {}
    st.clear()
    st.update(_default_state(now))
    st["open"] = open_map


def _load_state(now: Optional[float] = None, path: Optional[str] = None) -> Dict[str, Any]:
    global _STATE_CACHE, _STATE_CACHE_PATH
    now = time.time() if now is None else float(now)
    p = path or MERID_MBAND_DAILY_FILE
    with _state_lock:
        if _STATE_CACHE is not None and _STATE_CACHE_PATH == p:
            _roll_daily_locked(_STATE_CACHE, now)
            return _STATE_CACHE
        rec: Dict[str, Any] = {}
        try:
            with open(p, encoding="utf-8") as f:
                rec = json.load(f)
        except Exception:
            rec = {}
        st = _default_state(now)
        if isinstance(rec.get("open"), dict):
            st["open"] = rec["open"]
        if rec.get("date") == st["date"]:
            for k in ("count", "consecutive_losses", "coherence_failures"):
                if isinstance(rec.get(k), int):
                    st[k] = rec[k]
            for k in ("assets", "windows"):
                if isinstance(rec.get(k), dict):
                    st[k] = rec[k]
            if isinstance(rec.get("realized_pnl_cents"), (int, float)):
                st["realized_pnl_cents"] = float(rec["realized_pnl_cents"])
            st["suspended"] = bool(rec.get("suspended"))
            st["suspend_reason"] = rec.get("suspend_reason")
        _STATE_CACHE = st
        _STATE_CACHE_PATH = p
        return _STATE_CACHE


def _persist_state_locked(path: str, state: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(state, default=str, separators=(",", ":")))
        os.replace(tmp, path)
    except Exception as exc:
        logger.debug("[MBAND-LANE] state persist failed: %s", exc)


def _save_state(path: Optional[str] = None) -> None:
    with _state_lock:
        if _STATE_CACHE is not None:
            _persist_state_locked(
                path or _STATE_CACHE_PATH or MERID_MBAND_DAILY_FILE, _STATE_CACHE
            )


def reset_lane_state_cache() -> None:
    """Test helper: drop the in-memory state cache."""
    global _STATE_CACHE, _STATE_CACHE_PATH
    with _state_lock:
        _STATE_CACHE = None
        _STATE_CACHE_PATH = None


# ---------------------------------------------------------------------------
# Gate reads
# ---------------------------------------------------------------------------

def lane_status() -> Dict[str, Any]:
    st = _load_state()
    return {
        "enabled": MERID_MBAND_LANE_ENABLED,
        "date": st.get("date"),
        "count": int(st.get("count") or 0),
        "daily_cap": MERID_MBAND_DAILY_CAP,
        "per_asset_daily_cap": MERID_MBAND_PER_ASSET_DAILY_CAP,
        "realized_pnl_cents": float(st.get("realized_pnl_cents") or 0.0),
        "consecutive_losses": int(st.get("consecutive_losses") or 0),
        "coherence_failures": int(st.get("coherence_failures") or 0),
        "suspended": bool(st.get("suspended")),
        "suspend_reason": st.get("suspend_reason"),
        "open": len(st.get("open") or {}),
    }


def window_open(asset: str, ticker: str) -> bool:
    """True when the asset has not consumed a marginal-band slot this window."""
    st = _load_state()
    return (st.get("windows") or {}).get(str(asset).upper()) != ticker


def under_daily_cap(asset: Optional[str] = None) -> bool:
    st = _load_state()
    if int(st.get("count") or 0) >= MERID_MBAND_DAILY_CAP:
        return False
    if asset is not None:
        per = int((st.get("assets") or {}).get(str(asset).upper()) or 0)
        if per >= MERID_MBAND_PER_ASSET_DAILY_CAP:
            return False
    return True


def suppression_reason(asset: str, ticker: str) -> Optional[str]:
    """Why a marginal-band emission must be suppressed, else None.

    Ordered so the most informative cause wins: lane disabled, suspension,
    then budget exhaustion (daily lane cap, per-asset cap, window dedupe).
    """
    if not MERID_MBAND_LANE_ENABLED:
        return "lane_disabled"
    st = _load_state()
    if st.get("suspended"):
        return f"suspended:{st.get('suspend_reason') or 'unknown'}"
    if int(st.get("count") or 0) >= MERID_MBAND_DAILY_CAP:
        return "daily_cap"
    per = int((st.get("assets") or {}).get(str(asset).upper()) or 0)
    if per >= MERID_MBAND_PER_ASSET_DAILY_CAP:
        return "per_asset_daily_cap"
    if (st.get("windows") or {}).get(str(asset).upper()) == ticker:
        return "window_consumed"
    return None


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

def record_submission(
    *,
    asset: str,
    ticker: str,
    decision_id: Optional[str],
    side: Optional[str],
) -> int:
    """Consume the asset's window slot + daily budgets; bind the decision.

    Returns the lane's day submission count after recording.
    """
    a = str(asset).upper()
    with _state_lock:
        st = _load_state()
        (st.setdefault("windows", {}))[a] = ticker
        assets = st.setdefault("assets", {})
        assets[a] = int(assets.get(a) or 0) + 1
        st["count"] = int(st.get("count") or 0) + 1
        if decision_id:
            st.setdefault("open", {})[str(decision_id)] = {
                "asset": a,
                "ticker": ticker,
                "side": side,
                "ts": time.time(),
            }
        _save_state()
        return int(st.get("count") or 0)


def marginal_band_for_decision(decision_id: str) -> Optional[Dict[str, Any]]:
    """Return the lane submission bound to ``decision_id`` (or None)."""
    if not decision_id:
        return None
    st = _load_state()
    meta = (st.get("open") or {}).get(str(decision_id))
    return dict(meta) if isinstance(meta, dict) else None


def _evaluate_suspension_locked(st: Dict[str, Any]) -> None:
    if st.get("suspended"):
        return
    if int(st.get("consecutive_losses") or 0) >= MERID_MBAND_SUSPEND_CONSEC_LOSSES:
        st["suspended"] = True
        st["suspend_reason"] = (
            f"consecutive_losses>={MERID_MBAND_SUSPEND_CONSEC_LOSSES}"
        )
        return
    if (
        float(st.get("realized_pnl_cents") or 0.0)
        <= -MERID_MBAND_SUSPEND_DAILY_LOSS_CENTS
    ):
        st["suspended"] = True
        st["suspend_reason"] = (
            f"daily_loss<=-{MERID_MBAND_SUSPEND_DAILY_LOSS_CENTS}c"
        )
        return
    if (
        int(st.get("coherence_failures") or 0)
        >= MERID_MBAND_SUSPEND_COHERENCE_FAILURES
    ):
        st["suspended"] = True
        st["suspend_reason"] = (
            f"coherence_failures>={MERID_MBAND_SUSPEND_COHERENCE_FAILURES}"
        )


def record_settlement(
    *,
    decision_id: str,
    net_pnl_cents: float,
) -> None:
    """Feed realized P&L for a marginal-band fill into the lane state.

    Wired from ``decision_audit_ledger._attribute_settlement`` — the same
    hook the threshold-cell/provisional lanes use, so lane outcomes see the
    identical settle-leg - fill - fee math.
    """
    if not decision_id:
        return
    try:
        with _state_lock:
            st = _load_state()
            open_map = st.setdefault("open", {})
            meta = open_map.pop(str(decision_id), None)
            if meta is None:
                return
            pnl = float(net_pnl_cents)
            st["realized_pnl_cents"] = (
                float(st.get("realized_pnl_cents") or 0.0) + pnl
            )
            if pnl < 0.0:
                st["consecutive_losses"] = int(st.get("consecutive_losses") or 0) + 1
            else:
                st["consecutive_losses"] = 0
            _evaluate_suspension_locked(st)
            _save_state()
        if st.get("suspended"):
            logger.warning(
                "[MBAND-LANE] SUSPENDED asset=%s ticker=%s net_pnl=%.1fc "
                "day_pnl=%.1fc reason=%s",
                meta.get("asset"), meta.get("ticker"), pnl,
                float(st.get("realized_pnl_cents") or 0.0),
                st.get("suspend_reason"),
            )
        else:
            logger.info(
                "[MBAND-LANE] settlement asset=%s ticker=%s net_pnl=%.1fc "
                "day_pnl=%.1fc consec_losses=%d",
                meta.get("asset"), meta.get("ticker"), pnl,
                float(st.get("realized_pnl_cents") or 0.0),
                int(st.get("consecutive_losses") or 0),
            )
    except Exception as exc:
        logger.debug("[MBAND-LANE] record_settlement failed for %s: %s", decision_id, exc)


def record_coherence_failure(
    *,
    decision_id: Optional[str],
    reason: str,
    asset: Optional[str] = None,
    ticker: Optional[str] = None,
) -> None:
    """Count a pre-wire router reject against the lane's suspension budget.

    Revalidation outcomes (edge decayed, not_marketable, spread_too_wide)
    count here *by design* — the marginal band exists to measure whether
    near-miss edge survives to the wire; a lane whose admissions keep
    decaying before submit is exactly the failure mode the suspension rule
    exists to stop.
    """
    try:
        with _state_lock:
            st = _load_state()
            st["coherence_failures"] = int(st.get("coherence_failures") or 0) + 1
            if decision_id:
                # Release the decision binding — a pre-wire reject never
                # fills, so no settlement attribution will need it.
                meta = (st.setdefault("open", {})).pop(str(decision_id), None)
                asset = asset or (meta or {}).get("asset")
                ticker = ticker or (meta or {}).get("ticker")
            _evaluate_suspension_locked(st)
            _save_state()
        logger.info(
            "[MBAND-LANE] coherence failure asset=%s ticker=%s reason=%s "
            "failures=%d suspended=%s",
            asset, ticker, str(reason)[:80],
            int(st.get("coherence_failures") or 0), st.get("suspended"),
        )
    except Exception as exc:
        logger.debug("[MBAND-LANE] record_coherence_failure failed: %s", exc)
