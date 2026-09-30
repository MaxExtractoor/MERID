"""Conditional threshold-cell policy for the 15m Kalshi crypto lane.

A data-driven replacement for the uniform dynamic edge threshold inside the
specific asset x side x price-band x TTE-band cells where the settled
counterfactual frontier (``scripts/_threshold_frontier.py``, ~69.5k deduped
settled candidates, 2026-09) showed the generic gate suppressing cohorts with
positive fill-adjusted LCB net EV.

Semantics
---------
A matching cell's ``min_net_ev_cents`` *replaces* the base+convexity+FLB
formula output for that side — the cell is the single source of truth for the
required edge inside its region (the formula decomposition is still emitted in
telemetry for audit).  No cell applies below a 20c ask or to the YES side, and
no cell relaxes any other gate: the held-price floor, tail guards, evidence
policy, depth requirement, confidence gate, pi* cost basis, TTE entry cutoff,
and the downstream authoritative EV gate all still apply unchanged.

Bounds are inclusive on TTE (``120 <= tte <= 600``) and half-open on price
(``price_min <= ask < price_max``), matching the frontier bucketing.

Routing
-------
A decision whose selected side was admitted by a cell is stamped
``decision_lane = "threshold_cell"`` (and ``threshold_cell_id``), which the
agent-grid order-style block forces to a one-contract post-only maker order —
the same bounded treatment as the evidence escape lane.

Per-cell lane state machine
---------------------------
Each cell carries a persistent lane state in ``data/threshold_cell_lane.json``:

    PROVISIONAL -> OBSERVATION -> SUSPENDED -> (manual review)
                   OBSERVATION -> PROMOTED (manual only)

- PROVISIONAL: default; one contract, post-only, strict caps.
- OBSERVATION: reached after the first recorded fill; identical admission
  policy — the label marks that live execution data exists for the cell.
- SUSPENDED: fail-closed — the cell stops admitting until an operator resets
  it (``set_cell_state(cell_id, "PROVISIONAL")``).
- PROMOTED: manual promotion only; admission policy unchanged until a
  separate review widens it.

Automatic suspension (evaluated on every recorded fill / router reject):
  - rolling ``MERID_THRESHOLD_CELL_SUSPEND_MIN_FILLS`` (default 5) filled
    trades: mean realized net PnL < ``_SUSPEND_MEAN_PNL`` (default -1c);
  - rolling 5 fills with a 5s markout: median markout_5s <
    ``_SUSPEND_MARKOUT_MEDIAN`` (default -1c);
  - router reject/cross rate > ``_SUSPEND_REJECT_RATE`` (default 0.40) once the
    cell has ``_SUSPEND_REJECT_MIN`` (default 5) attempts;
  - mean (fill_time EV - candidate EV) < ``_SUSPEND_EV_DROP`` (default -1.5c)
    over the rolling window — passive fills landing materially worse than the
    price the decision economics assumed;
  - more than ``_SUSPEND_EXEC_FAILURES`` (default 2) execution/integrity
    failures recorded for the cell.

Caps (all independent):
  - ``MERID_THRESHOLD_CELL_DAILY_MAX_SUBMISSIONS`` (default 20): global lane
    submissions/day.  ``MERID_THRESHOLD_CELL_DAILY_MAX`` remains as a legacy
    alias.
  - ``MERID_THRESHOLD_CELL_DAILY_MAX_FILLS`` (default 3): filled trades per
    cell per UTC day — fills, not submissions, are the exposure.
  - ``MERID_THRESHOLD_CELL_MAX_OPEN_ORDERS`` (default 1): resting orders per
    cell, tracked via the fill-quality tracker.

Funnel counters
---------------
``bump_cell_funnel(stage, cell_id=None)`` counts per-day stage transitions:
matched, blocked_by_price_band, blocked_by_evidence, emitted,
allocator_rejected, router_rejected, submitted, filled.  Invariant for audit:
``matched > 0`` with ``emitted == 0`` means a hidden gate is silently
suppressing admitted cells.  Counters persist in the lane state file and are
emitted on every lifecycle event.

Lifecycle event log
-------------------
``emit_cell_lifecycle(stage, **fields)`` appends one JSONL record per stage to
``logs/threshold_cell_lifecycle.jsonl`` carrying the full correlation chain
(decision_id, candidate_id, intent_id, client_order_id, order_id,
position_id, threshold_cell_id) so a single candidate can be traced from
decision through settlement.

Kill switch: ``MERID_THRESHOLD_CELLS=0`` reverts to the legacy formula
everywhere without a deploy.
"""

from __future__ import annotations

import json
import logging
import os
import statistics
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

logger = logging.getLogger(__name__)


class ThresholdCell(NamedTuple):
    """One empirically-qualified admission cell.

    Price bounds are half-open (``price_min_cents <= ask < price_max_cents``);
    TTE bounds are inclusive (``tte_min_seconds <= tte <= tte_max_seconds``),
    matching the approved ``120 <= tte <= 600`` contract.
    """

    cell_id: str
    asset: str
    side: str  # "yes" | "no"
    price_min_cents: int
    price_max_cents: int
    tte_min_seconds: float
    tte_max_seconds: float
    min_net_ev_cents: float
    evidence: str  # provenance note for audit
    # Historical counterfactual LCB10 (net c/contract at the executable ask)
    # from the settled frontier study — prior evidence only, never mixed into
    # the live-fill evidence store.  Emitted on sparse-override records.
    historical_lcb10_cents: float = 0.0


# Approved 2026-09-30 from the settled counterfactual frontier.  LCB10 = the
# ~10% lower confidence bound on mean net c/contract at the decision-time
# executable ask (taker-fee counterfactual — conservative vs post-only).
THRESHOLD_CELLS: List[ThresholdCell] = [
    # SOL NO mid band: frontier marginal band realized +14.4/+21.3/+18.7c mean
    # at 30-59c asks (LCB +8.8..+14.7); blocked cohort avg req was 6.4c.
    ThresholdCell(
        "sol_no_30_60_t120_600", "SOL", "no", 30, 60, 120.0, 600.0, 1.5,
        "frontier: SOL-NO 30-59c LCB10 +8.8..+14.7c; TTE120-300 LCB +14.1c",
        8.8,
    ),
    # SOL NO 60-79c: 70-79c bucket +10.3c (LCB +2.7) but 60-69c weak (-2.3c);
    # admitted at a higher bar.
    ThresholdCell(
        "sol_no_60_80_t120_600", "SOL", "no", 60, 80, 120.0, 600.0, 2.5,
        "frontier: SOL-NO 70-79c LCB +2.7c; 60-69c weak -> higher bar",
        2.7,
    ),
    # DOGE NO: 20-29c +7.7c (LCB +1.6) and 40-49c +9.5c (LCB +2.4); the 30-39c
    # cell was inconclusive (LCB -4.8) and is deliberately not qualified.
    # Note: the held-price floor (25c) still vetoes the 20-24c half of the
    # first cell — the cell relaxes only the edge gate.
    ThresholdCell(
        "doge_no_20_30_t120_600", "DOGE", "no", 20, 30, 120.0, 600.0, 2.0,
        "frontier: DOGE-NO 20-29c LCB +1.6c (held floor still applies <25c)",
        1.6,
    ),
    ThresholdCell(
        "doge_no_40_50_t120_600", "DOGE", "no", 40, 50, 120.0, 600.0, 2.0,
        "frontier: DOGE-NO 40-49c LCB +2.4c",
        2.4,
    ),
    # DOGE NO 70-89c: +22.2c (70-79, LCB +21.5) / +9.6c (80-89, LCB +6.2);
    # higher bar for the execution-sensitive upper band.
    ThresholdCell(
        "doge_no_70_90_t120_600", "DOGE", "no", 70, 90, 120.0, 600.0, 3.0,
        "frontier: DOGE-NO 70-89c LCB +6.2..+21.5c",
        6.2,
    ),
    # XRP NO 30-39c +9.8c (LCB +3.7) and 80-89c +5.8c (LCB +2.2); the 40-79c
    # middle was mixed and stays on the legacy formula.
    ThresholdCell(
        "xrp_no_30_40_t120_600", "XRP", "no", 30, 40, 120.0, 600.0, 2.5,
        "frontier: XRP-NO 30-39c LCB +3.7c",
        3.7,
    ),
    ThresholdCell(
        "xrp_no_80_90_t120_600", "XRP", "no", 80, 90, 120.0, 600.0, 2.5,
        "frontier: XRP-NO 80-89c LCB +2.2c",
        2.2,
    ),
]


def threshold_cells_enabled() -> bool:
    """Single kill switch: ``MERID_THRESHOLD_CELLS=0`` reverts to formula."""
    return os.environ.get("MERID_THRESHOLD_CELLS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def threshold_cell_maker_enabled() -> bool:
    """Lane-scoped post-only switch.

    ``MERID_ENTRY_MAKER_ENABLED`` stays off globally; this lane is an explicit
    instrumented post-only experiment.  ``MERID_THRESHOLD_CELL_MAKER=0``
    suppresses threshold-cell candidates entirely rather than coercing them to
    taker — a taker entry under cell economics is not the approved lane.
    """
    return os.environ.get("MERID_THRESHOLD_CELL_MAKER", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def resolve_threshold_cell(
    asset: str,
    side: str,
    price_cents: float,
    tte_seconds: Optional[float],
) -> Optional[ThresholdCell]:
    """Return the most specific matching cell, or None -> legacy formula.

    Specificity = narrower price span wins, so a future override cell can
    tighten a band inside a broader qualified cell without reordering the
    table.  TTE bounds are inclusive; price bounds are half-open.
    """
    if tte_seconds is None or not threshold_cells_enabled():
        return None
    asset_u = asset.upper()
    side_l = side.lower()
    px = float(price_cents)
    tte = float(tte_seconds)
    best: Optional[ThresholdCell] = None
    for cell in THRESHOLD_CELLS:
        if cell.asset != asset_u or cell.side != side_l:
            continue
        if not (cell.price_min_cents <= px < cell.price_max_cents):
            continue
        if not (cell.tte_min_seconds <= tte <= cell.tte_max_seconds):
            continue
        if best is None or (
            cell.price_max_cents - cell.price_min_cents
            < best.price_max_cents - best.price_min_cents
        ):
            best = cell
    return best


def explain_cell_miss(
    asset: str,
    side: str,
    price_cents: float,
    tte_seconds: Optional[float],
) -> Optional[str]:
    """Explain why no cell matched, or None when a cell would match.

    Only meaningful when the (asset, side) pair has configured cells —
    ``no_cells_for_asset_side`` is returned for pairs with none.  Explicit
    reasons keep near-boundary misses auditable instead of silently falling
    back to the generic formula.
    """
    asset_u = asset.upper()
    side_l = side.lower()
    candidates = [
        c for c in THRESHOLD_CELLS if c.asset == asset_u and c.side == side_l
    ]
    if not candidates:
        return "no_cells_for_asset_side"
    if not threshold_cells_enabled():
        return "threshold_cells_disabled"
    if tte_seconds is None:
        return "threshold_cell_tte_unknown"
    if price_cents is None:
        return "threshold_cell_price_unknown"
    # A real match is not a miss — resolve first so a covered point never
    # reports a spurious "unqualified gap" reason.
    if resolve_threshold_cell(asset_u, side_l, price_cents, tte_seconds) is not None:
        return None
    tte = float(tte_seconds)
    px = float(price_cents)
    lo_tte = min(c.tte_min_seconds for c in candidates)
    hi_tte = max(c.tte_max_seconds for c in candidates)
    if tte < lo_tte:
        return "threshold_cell_tte_below_min"
    if tte > hi_tte:
        return "threshold_cell_tte_above_max"
    lo_px = min(c.price_min_cents for c in candidates)
    hi_px = max(c.price_max_cents for c in candidates)
    if px < lo_px:
        return "threshold_cell_price_below_min"
    if px >= hi_px:
        return "threshold_cell_price_above_max"
    return "threshold_cell_price_in_unqualified_gap"


# ---------------------------------------------------------------------------
# Lane state file: caps, per-cell state machine, outcomes, funnel counters
# ---------------------------------------------------------------------------
# ``data/threshold_cell_lane.json`` carries a daily-scoped counter block plus
# durable per-cell state that survives restarts (suspension must not reset on
# redeploy).  Shape:
#   {
#     "date": "YYYY-MM-DD",                  # UTC day the counters belong to
#     "count": n,                            # legacy global submissions today
#     "submissions": {cell_id: n},
#     "fills_today": {cell_id: n},
#     "open_orders": {cell_id: [order_id]},
#     "router_attempts": {cell_id: n},
#     "router_rejects": {cell_id: n},
#     "cell_states": {cell_id: {"state": ..., "since_ts": ..., "reason": ...}},
#     "outcomes": {cell_id: [ {ts, net_pnl_cents, markout_5s_cents,
#                             fill_ev_cents, candidate_ev_cents,
#                             decision_id, kind} , ... ]},   # capped at 25
#     "decision_cell_map": {decision_id: cell_id},
#     "funnel": {stage: n, "by_cell": {cell_id: {stage: n}}},
#   }

CELL_STATE_PROVISIONAL = "PROVISIONAL"
CELL_STATE_OBSERVATION = "OBSERVATION"
CELL_STATE_SUSPENDED = "SUSPENDED"
CELL_STATE_PROMOTED = "PROMOTED"
CELL_STATES = (
    CELL_STATE_PROVISIONAL,
    CELL_STATE_OBSERVATION,
    CELL_STATE_SUSPENDED,
    CELL_STATE_PROMOTED,
)

FUNNEL_STAGES = (
    "matched",
    "blocked_by_price_band",
    "blocked_by_evidence",
    "sparse_override",
    "emitted",
    "allocator_rejected",
    "router_rejected",
    "submitted",
    "filled",
)

_state_lock = threading.Lock()
_STATE_CACHE: Optional[Dict[str, Any]] = None
_STATE_CACHE_PATH: Optional[str] = None

_LIFECYCLE_PATH_ENV = "MERID_THRESHOLD_CELL_LIFECYCLE_PATH"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except Exception:
        return default


def cell_daily_max() -> int:
    """Global lane submissions/day (legacy alias honored)."""
    v = os.environ.get("MERID_THRESHOLD_CELL_DAILY_MAX_SUBMISSIONS")
    if v is None:
        v = os.environ.get("MERID_THRESHOLD_CELL_DAILY_MAX", "15")
    try:
        return int(v)
    except Exception:
        return 15


def cell_daily_max_submissions_per_cell() -> int:
    """Per-cell candidate submissions/day — one cell must not consume the
    lane's whole exploration budget."""
    return _env_int("MERID_THRESHOLD_CELL_PER_CELL_MAX_SUBMISSIONS", 5)


def cell_daily_max_fills() -> int:
    """Per-cell filled trades/day — fills are the real exposure."""
    return _env_int("MERID_THRESHOLD_CELL_DAILY_MAX_FILLS", 2)


def cell_daily_max_fills_total() -> int:
    """Lane-wide filled trades/day across all cells."""
    return _env_int("MERID_THRESHOLD_CELL_DAILY_MAX_FILLS_TOTAL", 3)


def cell_max_open_orders() -> int:
    """Resting orders per cell — prevents duplicate race submissions."""
    return _env_int("MERID_THRESHOLD_CELL_MAX_OPEN_ORDERS", 1)


def _suspend_min_fills() -> int:
    return _env_int("MERID_THRESHOLD_CELL_SUSPEND_MIN_FILLS", 5)


def _suspend_mean_pnl() -> float:
    return _env_float("MERID_THRESHOLD_CELL_SUSPEND_MEAN_PNL_C", -1.0)


def _suspend_markout_median() -> float:
    return _env_float("MERID_THRESHOLD_CELL_SUSPEND_MARKOUT_MEDIAN_C", -1.0)


def _suspend_reject_rate() -> float:
    return _env_float("MERID_THRESHOLD_CELL_SUSPEND_REJECT_RATE", 0.40)


def _suspend_reject_min() -> int:
    return _env_int("MERID_THRESHOLD_CELL_SUSPEND_REJECT_MIN", 5)


def _suspend_ev_drop() -> float:
    return _env_float("MERID_THRESHOLD_CELL_SUSPEND_EV_DROP_C", -1.5)


def _suspend_exec_failures() -> int:
    return _env_int("MERID_THRESHOLD_CELL_SUSPEND_EXEC_FAILURES", 2)


def cell_state_path() -> str:
    return os.environ.get(
        "MERID_THRESHOLD_CELL_STATE_PATH", "data/threshold_cell_lane.json"
    )


def _utc_day(now: float) -> str:
    return datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat()


def _default_state(now: float) -> Dict[str, Any]:
    return {
        "date": _utc_day(now),
        "count": 0,
        "submissions": {},
        "fills_today": {},
        "open_orders": {},
        "router_attempts": {},
        "router_rejects": {},
        "router_consecutive_rejects": {},
        "cell_states": {},
        "outcomes": {},
        "decision_cell_map": {},
        "funnel": {s: 0 for s in FUNNEL_STAGES},
        "funnel_by_cell": {},
    }


def _load_state(now: Optional[float] = None, path: Optional[str] = None) -> Dict[str, Any]:
    """Load the lane state, rolling daily counters and seeding the cache."""
    global _STATE_CACHE, _STATE_CACHE_PATH
    now = time.time() if now is None else float(now)
    p = path or cell_state_path()
    with _state_lock:
        if _STATE_CACHE is not None and _STATE_CACHE_PATH == p:
            # Roll daily-scoped counters if the UTC day moved.
            if _STATE_CACHE.get("date") != _utc_day(now):
                _STATE_CACHE["date"] = _utc_day(now)
                _STATE_CACHE["count"] = 0
                _STATE_CACHE["submissions"] = {}
                _STATE_CACHE["fills_today"] = {}
                _STATE_CACHE["funnel"] = {s: 0 for s in FUNNEL_STAGES}
                _STATE_CACHE["funnel_by_cell"] = {}
                _persist_state_locked(p, _STATE_CACHE)
            return _STATE_CACHE
        rec: Dict[str, Any] = {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                rec = json.load(f)
        except Exception:
            rec = {}
        state = _default_state(now)
        # Durable keys that survive the daily roll.
        for k in ("cell_states", "outcomes", "decision_cell_map", "open_orders"):
            if isinstance(rec.get(k), dict):
                state[k] = rec[k]
        # Daily-scoped keys only count when the file is from today.
        if rec.get("date") == state["date"]:
            for k in (
                "count",
                "submissions",
                "fills_today",
                "router_attempts",
                "router_rejects",
                "router_consecutive_rejects",
            ):
                if isinstance(rec.get(k), (int, dict)):
                    state[k] = rec[k]
            if isinstance(rec.get("funnel"), dict):
                for s in FUNNEL_STAGES:
                    state["funnel"][s] = int(rec["funnel"].get(s) or 0)
            if isinstance(rec.get("funnel_by_cell"), dict):
                state["funnel_by_cell"] = rec["funnel_by_cell"]
        _STATE_CACHE = state
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
        logger.debug("[THRESHOLD-CELL] state persist failed: %s", exc)


def _save_state(path: Optional[str] = None) -> None:
    with _state_lock:
        if _STATE_CACHE is not None:
            _persist_state_locked(path or _STATE_CACHE_PATH or cell_state_path(), _STATE_CACHE)


def reset_cell_state_cache() -> None:
    """Test helper: drop the in-memory state cache."""
    global _STATE_CACHE, _STATE_CACHE_PATH
    with _state_lock:
        _STATE_CACHE = None
        _STATE_CACHE_PATH = None


# ---------------------------------------------------------------------------
# Per-cell state machine
# ---------------------------------------------------------------------------

def get_cell_state(cell_id: str) -> str:
    st = _load_state()
    rec = st.get("cell_states", {}).get(cell_id) or {}
    return str(rec.get("state") or CELL_STATE_PROVISIONAL)


def set_cell_state(cell_id: str, state: str, reason: Optional[str] = None) -> None:
    """Explicit state transition; PROMOTED is only reachable through here."""
    state = state.upper()
    if state not in CELL_STATES:
        raise ValueError(f"invalid threshold-cell state {state!r}")
    st = _load_state()
    rec = st["cell_states"].setdefault(cell_id, {})
    rec["state"] = state
    rec["since_ts"] = time.time()
    rec["reason"] = reason
    _save_state()
    logger.info(
        "[THRESHOLD-CELL-STATE] cell=%s -> %s reason=%s",
        cell_id, state, reason,
    )
    emit_cell_lifecycle(
        "state_transition",
        threshold_cell_id=cell_id,
        terminal_state=state,
        reason=reason,
    )


def _suspend_cell(cell_id: str, reason: str) -> None:
    if get_cell_state(cell_id) != CELL_STATE_SUSPENDED:
        logger.warning(
            "[THRESHOLD-CELL-SUSPEND] cell=%s reason=%s — lane fails closed",
            cell_id, reason,
        )
        set_cell_state(cell_id, CELL_STATE_SUSPENDED, reason)


# ---------------------------------------------------------------------------
# Counters / caps
# ---------------------------------------------------------------------------

def cell_submissions_today(
    path: Optional[str] = None, now: Optional[float] = None
) -> int:
    """Cell-lane submissions recorded for the current UTC day (global)."""
    st = _load_state(now, path)
    return int(st.get("count") or 0)


def cell_cap_remaining(path: Optional[str] = None, now: Optional[float] = None) -> int:
    return max(0, cell_daily_max() - cell_submissions_today(path, now))


def cell_fills_today(cell_id: str) -> int:
    st = _load_state()
    return int((st.get("fills_today") or {}).get(cell_id) or 0)


def cell_open_orders(cell_id: str) -> int:
    st = _load_state()
    return len((st.get("open_orders") or {}).get(cell_id) or [])


def record_cell_submission(
    path: Optional[str] = None,
    now: Optional[float] = None,
    cell_id: Optional[str] = None,
    decision_id: Optional[str] = None,
) -> int:
    """Increment today's lane submission counters; returns global count."""
    st = _load_state(now, path)
    st["count"] = int(st.get("count") or 0) + 1
    if cell_id:
        subs = st.setdefault("submissions", {})
        subs[cell_id] = int(subs.get(cell_id) or 0) + 1
        if decision_id:
            st.setdefault("decision_cell_map", {})[decision_id] = cell_id
    _save_state(path)
    return int(st["count"])


def bind_decision_cell(decision_id: str, cell_id: str) -> None:
    """Persist decision_id -> cell_id so settlement/exits can attribute PnL."""
    if not decision_id or not cell_id:
        return
    st = _load_state()
    st.setdefault("decision_cell_map", {})[decision_id] = cell_id
    _save_state()


def cell_for_decision(decision_id: str) -> Optional[str]:
    st = _load_state()
    return (st.get("decision_cell_map") or {}).get(decision_id)


def record_cell_order_open(cell_id: str, order_id: Optional[str]) -> None:
    if not cell_id or not order_id:
        return
    st = _load_state()
    opens = st.setdefault("open_orders", {}).setdefault(cell_id, [])
    if order_id not in opens:
        opens.append(order_id)
    # An accepted order breaks any consecutive router-reject run.
    st.setdefault("router_consecutive_rejects", {})[cell_id] = 0
    _save_state()


def record_cell_order_closed(cell_id: str, order_id: Optional[str]) -> None:
    if not cell_id or not order_id:
        return
    st = _load_state()
    opens = st.setdefault("open_orders", {}).setdefault(cell_id, [])
    if order_id in opens:
        opens.remove(order_id)
        _save_state()


def record_cell_router_attempt(cell_id: str) -> None:
    st = _load_state()
    att = st.setdefault("router_attempts", {})
    att[cell_id] = int(att.get(cell_id) or 0) + 1
    _save_state()


def record_cell_router_reject(cell_id: str) -> None:
    """Post-only cross/reprice/venue reject; feeds the reject-rate rule and
    the consecutive-reject emergency rule (two in a row -> suspend)."""
    if not cell_id:
        return
    st = _load_state()
    rej = st.setdefault("router_rejects", {})
    rej[cell_id] = int(rej.get(cell_id) or 0) + 1
    consec = st.setdefault("router_consecutive_rejects", {})
    consec[cell_id] = int(consec.get(cell_id) or 0) + 1
    _save_state()
    bump_cell_funnel("router_rejected", cell_id)
    _evaluate_suspension(cell_id)


def record_cell_exec_failure(cell_id: str, reason: str) -> None:
    """Integrity/execution failure (e.g. identity mismatch, coercion, missing
    fill attribution).  More than ``_suspend_exec_failures`` -> SUSPENDED."""
    if not cell_id:
        return
    st = _load_state()
    outs = st.setdefault("outcomes", {}).setdefault(cell_id, [])
    outs.append({
        "ts": time.time(),
        "kind": "exec_failure",
        "reason": str(reason)[:120],
    })
    _save_state()
    _evaluate_suspension(cell_id)


def record_cell_fill(
    cell_id: str,
    *,
    decision_id: Optional[str] = None,
    markout_5s_cents: Optional[float] = None,
    fill_ev_cents: Optional[float] = None,
    candidate_ev_cents: Optional[float] = None,
) -> None:
    """Record a live fill for the cell; drives fills/day cap + suspension.

    ``net_pnl_cents`` arrives later via :func:`record_cell_settlement` — fills
    and settlements are separate lifecycle stages.
    """
    if not cell_id:
        return
    st = _load_state()
    fills = st.setdefault("fills_today", {})
    fills[cell_id] = int(fills.get(cell_id) or 0) + 1
    outs = st.setdefault("outcomes", {}).setdefault(cell_id, [])
    outs.append({
        "ts": time.time(),
        "kind": "fill",
        "decision_id": decision_id,
        "markout_5s_cents": markout_5s_cents,
        "fill_ev_cents": fill_ev_cents,
        "candidate_ev_cents": candidate_ev_cents,
    })
    del outs[:-25]
    if decision_id:
        st.setdefault("decision_cell_map", {})[decision_id] = cell_id
    _save_state()
    bump_cell_funnel("filled", cell_id)
    # PROVISIONAL -> OBSERVATION once real fills exist for the cell.
    if get_cell_state(cell_id) == CELL_STATE_PROVISIONAL:
        set_cell_state(cell_id, CELL_STATE_OBSERVATION, "first_fill")
    _evaluate_suspension(cell_id)


def record_cell_markout(
    cell_id: str,
    decision_id: Optional[str],
    horizon_s: int,
    markout_cents: float,
) -> None:
    """Attach a post-fill markout to the cell's rolling outcome window.

    Marks the most recent fill row for this decision (or appends a bare
    markout row when the fill was recorded elsewhere) and re-evaluates the
    suspension rules — persistent negative 5s markouts are the primary
    adverse-selection signal for a passive lane.
    """
    if not cell_id:
        return
    st = _load_state()
    outs = st.setdefault("outcomes", {}).setdefault(cell_id, [])
    key = f"markout_{horizon_s}s_cents"
    for o in reversed(outs):
        if o.get("decision_id") == decision_id and o.get("kind") in ("fill", "settled"):
            o[key] = float(markout_cents)
            break
    else:
        outs.append({
            "ts": time.time(),
            "kind": "markout",
            "decision_id": decision_id,
            key: float(markout_cents),
        })
        del outs[:-25]
    _save_state()
    if horizon_s == 5:
        _evaluate_suspension(cell_id)


def record_cell_settlement(
    decision_id: str,
    net_pnl_cents: float,
    cell_id: Optional[str] = None,
) -> None:
    """Attach realized net PnL (exit or settlement join) to a cell's window."""
    cell_id = cell_id or cell_for_decision(decision_id)
    if not cell_id:
        return
    st = _load_state()
    outs = st.setdefault("outcomes", {}).setdefault(cell_id, [])
    # Prefer updating the fill record for this decision to a settlement row.
    for o in reversed(outs):
        if o.get("decision_id") == decision_id and o.get("kind") == "fill":
            o["net_pnl_cents"] = float(net_pnl_cents)
            o["kind"] = "settled"
            break
    else:
        outs.append({
            "ts": time.time(),
            "kind": "settled",
            "decision_id": decision_id,
            "net_pnl_cents": float(net_pnl_cents),
        })
        del outs[:-25]
    _save_state()
    _evaluate_suspension(cell_id)


def _evaluate_suspension(cell_id: str) -> None:
    """Fail-closed lane stop: any breached rule suspends the cell."""
    st = _load_state()
    if get_cell_state(cell_id) in (CELL_STATE_SUSPENDED, CELL_STATE_PROMOTED):
        return
    outs = list((st.get("outcomes") or {}).get(cell_id) or [])
    min_fills = _suspend_min_fills()

    # ── Pre-five emergency rules (2026-09-30): a newly-live lane cannot wait
    # for five fills to discover adverse selection.  Any of these suspends
    # the cell immediately.
    consec = int((st.get("router_consecutive_rejects") or {}).get(cell_id) or 0)
    if consec >= 2:
        _suspend_cell(
            cell_id,
            f"consecutive_router_rejects={consec} (post-only cross/stale "
            "revalidation twice in a row)",
        )
        return

    fills = [o for o in outs if o.get("kind") in ("fill", "settled")]
    if fills:
        first = fills[0]
        # First fill whose 5s markout is deeply negative: adverse selection.
        m5 = first.get("markout_5s_cents")
        if m5 is not None and float(m5) <= -3.0:
            _suspend_cell(
                cell_id,
                f"first_fill_markout_5s={float(m5):+.2f}c <= -3.00c",
            )
            return
        # Fill-time EV negative after revalidation: the passive fill landed
        # strictly worse than the decision economics allowed.
        fev = first.get("fill_ev_cents")
        if fev is not None and float(fev) < 0.0:
            _suspend_cell(
                cell_id,
                f"fill_ev_below_zero={float(fev):+.2f}c",
            )
            return
        # First settled trade lost more than expected edge + 2c stress.
        pnl = first.get("net_pnl_cents")
        cand = first.get("candidate_ev_cents")
        if pnl is not None and cand is not None:
            bound = -(float(cand) + 2.0)
            if float(pnl) < bound:
                _suspend_cell(
                    cell_id,
                    f"first_trade_pnl={float(pnl):+.2f}c < -(edge {float(cand):+.2f}c + 2c)",
                )
                return
    # Any fill (not just the first) with negative fill-time EV suspends.
    for o in fills:
        fev = o.get("fill_ev_cents")
        if fev is not None and float(fev) < 0.0:
            _suspend_cell(cell_id, f"fill_ev_below_zero={float(fev):+.2f}c")
            return

    # Rolling-N realized net PnL (settled outcomes only).
    net_pnls = [o["net_pnl_cents"] for o in outs if o.get("net_pnl_cents") is not None]
    if len(net_pnls) >= min_fills:
        window = net_pnls[-min_fills:]
        if (sum(window) / len(window)) < _suspend_mean_pnl():
            _suspend_cell(
                cell_id,
                f"rolling_{min_fills}_mean_net_pnl={sum(window)/len(window):+.2f}c < {_suspend_mean_pnl():+.2f}c",
            )
            return

    # Rolling-N 5s markout median (adverse-selection proxy).
    markouts = [
        o["markout_5s_cents"] for o in outs if o.get("markout_5s_cents") is not None
    ]
    if len(markouts) >= min_fills:
        med = statistics.median(markouts[-min_fills:])
        if med < _suspend_markout_median():
            _suspend_cell(
                cell_id,
                f"rolling_{min_fills}_median_markout_5s={med:+.2f}c < {_suspend_markout_median():+.2f}c",
            )
            return

    # Fill-time EV materially below candidate-time EV (passive fills landing
    # worse than the decision economics assumed).
    ev_drops = [
        float(o["fill_ev_cents"]) - float(o["candidate_ev_cents"])
        for o in outs
        if o.get("fill_ev_cents") is not None and o.get("candidate_ev_cents") is not None
    ]
    if len(ev_drops) >= min_fills:
        window = ev_drops[-min_fills:]
        if (sum(window) / len(window)) < _suspend_ev_drop():
            _suspend_cell(
                cell_id,
                f"rolling_{min_fills}_mean_ev_drop={sum(window)/len(window):+.2f}c < {_suspend_ev_drop():+.2f}c",
            )
            return

    # Router reject/cross rate.
    attempts = int((st.get("router_attempts") or {}).get(cell_id) or 0)
    rejects = int((st.get("router_rejects") or {}).get(cell_id) or 0)
    if attempts >= _suspend_reject_min():
        rate = rejects / float(attempts)
        if rate > _suspend_reject_rate():
            _suspend_cell(
                cell_id,
                f"router_reject_rate={rate:.2f} > {_suspend_reject_rate():.2f} (attempts={attempts})",
            )
            return

    # Execution/integrity failures.
    failures = sum(1 for o in outs if o.get("kind") == "exec_failure")
    if failures > _suspend_exec_failures():
        _suspend_cell(
            cell_id,
            f"exec_failures={failures} > {_suspend_exec_failures()}",
        )
        return


def cell_submissions_today_cell(cell_id: str) -> int:
    st = _load_state()
    return int((st.get("submissions") or {}).get(cell_id) or 0)


def cell_fills_today_total() -> int:
    st = _load_state()
    return sum(int(v or 0) for v in (st.get("fills_today") or {}).values())


def cell_admission(cell_id: str) -> Tuple[bool, Optional[str]]:
    """(allowed, block_reason) — all lane admission checks in one place.

    Fail-closed: SUSPENDED or an unknown state blocks; PROMOTED keeps the
    same caps until a separate review widens them.
    """
    if not threshold_cells_enabled():
        return False, "threshold_cells_disabled"
    state = get_cell_state(cell_id)
    if state == CELL_STATE_SUSPENDED:
        return False, "cell_suspended"
    if state not in CELL_STATES:
        return False, f"cell_state_unknown:{state}"
    if cell_fills_today(cell_id) >= cell_daily_max_fills():
        return False, "cell_fills_cap_exhausted"
    if cell_fills_today_total() >= cell_daily_max_fills_total():
        return False, "cell_fills_total_cap_exhausted"
    if cell_open_orders(cell_id) >= cell_max_open_orders():
        return False, "cell_open_order_exists"
    if cell_submissions_today_cell(cell_id) >= cell_daily_max_submissions_per_cell():
        return False, "cell_submissions_cap_exhausted"
    if cell_submissions_today() >= cell_daily_max():
        return False, "cap_exhausted"
    return True, None


def threshold_cell_sparse_override_enabled() -> bool:
    """``MERID_THRESHOLD_CELL_SPARSE_OVERRIDE=0`` restores strict evidence
    gating for cell-matched candidates (emergency off-switch)."""
    return os.environ.get(
        "MERID_THRESHOLD_CELL_SPARSE_OVERRIDE", "1"
    ).strip().lower() in ("1", "true", "yes", "on")


def may_bypass_sparse_evidence(
    cell_id: Optional[str],
    evidence_code: Optional[str],
    matching_hard_block: bool,
    net_ev_cents: Optional[float],
    effective_required_edge_cents: Optional[float],
) -> Tuple[bool, Optional[str]]:
    """Bounded sparse-evidence override for the threshold-cell lane.

    The lane exists to generate the first *live* fill evidence inside
    historically qualified cohorts — evidence the settled-outcome store can
    never contain while the gate blocks every entry.  The override admits a
    cell-matched candidate past ``SPARSE_MATCHED_INSUFFICIENT`` only.  Hard
    blocks (``MATCHING_TOXIC_CELL``), soft-penalty lanes, low-EV candidates,
    suspended/capped lanes, and unmatched inputs all keep their original
    rejection.  Returns (allowed, reason).
    """
    if not cell_id:
        return False, None
    if not threshold_cell_sparse_override_enabled():
        return False, "sparse_override_disabled"
    if matching_hard_block:
        return False, "matching_hard_block"
    if evidence_code != "SPARSE_MATCHED_INSUFFICIENT":
        return False, f"evidence_code_not_sparse:{evidence_code}"
    if net_ev_cents is None or effective_required_edge_cents is None:
        return False, "missing_ev_or_threshold"
    if float(net_ev_cents) < float(effective_required_edge_cents):
        return False, "ev_below_cell_threshold"
    state = get_cell_state(cell_id)
    if state not in (CELL_STATE_PROVISIONAL, CELL_STATE_OBSERVATION):
        return False, f"cell_state_{state.lower()}"
    allowed, block = cell_admission(cell_id)
    if not allowed:
        return False, block
    return True, None


# ---------------------------------------------------------------------------
# Funnel counters
# ---------------------------------------------------------------------------

def bump_cell_funnel(stage: str, cell_id: Optional[str] = None) -> None:
    """Increment a funnel stage counter (validated + persisted)."""
    if stage not in FUNNEL_STAGES:
        logger.debug("[THRESHOLD-CELL] unknown funnel stage %r", stage)
        return
    st = _load_state()
    st["funnel"][stage] = int(st["funnel"].get(stage) or 0) + 1
    if cell_id:
        per = st.setdefault("funnel_by_cell", {}).setdefault(cell_id, {})
        per[stage] = int(per.get(stage) or 0) + 1
    _save_state()


def funnel_counters() -> Dict[str, Any]:
    st = _load_state()
    return {
        "date": st.get("date"),
        "funnel": dict(st.get("funnel") or {}),
        "funnel_by_cell": dict(st.get("funnel_by_cell") or {}),
        "cell_states": {
            cid: dict(rec) for cid, rec in (st.get("cell_states") or {}).items()
        },
    }


# ---------------------------------------------------------------------------
# Lifecycle event log
# ---------------------------------------------------------------------------

def _lifecycle_path() -> str:
    return os.environ.get(
        _LIFECYCLE_PATH_ENV, "logs/threshold_cell_lifecycle.jsonl"
    )


def emit_cell_lifecycle(stage: str, **fields: Any) -> None:
    """Append one correlated lifecycle event to logs/threshold_cell_lifecycle.jsonl."""
    try:
        rec = {
            "event": "threshold_cell_lifecycle",
            "stage": stage,
            "ts": time.time(),
            "ts_utc": datetime.now(timezone.utc).isoformat(),
        }
        rec.update(fields)
        path = _lifecycle_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str, separators=(",", ":")) + "\n")
    except Exception as exc:
        logger.debug("[THRESHOLD-CELL] lifecycle emit failed: %s", exc)


# ---------------------------------------------------------------------------
# Startup containment assertion
# ---------------------------------------------------------------------------

def validate_cells_within_price_bands() -> List[Dict[str, Any]]:
    """Assert every approved cell is reachable inside the live band domain.

    A cell is reachable when at least one (price, tte) point inside its
    rectangle is admitted by ``classify_market_regime``.  Raises
    ``AssertionError`` listing unreachable cells — the lane must fail closed
    rather than deploy a cell that can never fire.  Returns per-cell coverage
    detail for the startup log.
    """
    from merid.event_venues.kalshi.market_regime import classify_market_regime

    report: List[Dict[str, Any]] = []
    unreachable: List[str] = []
    for cell in THRESHOLD_CELLS:
        covered: List[Dict[str, Any]] = []
        blocked: List[Dict[str, Any]] = []
        # Scan each price in the cell's half-open band; for each band regime
        # overlapping that price, intersect the TTE window with the cell's.
        for px in range(cell.price_min_cents, cell.price_max_cents):
            for tte in (cell.tte_min_seconds, cell.tte_max_seconds):
                regime = classify_market_regime(px, int(tte))
                if regime is not None:
                    covered.append({"price": px, "tte": tte, "band": regime.name})
                else:
                    blocked.append({"price": px, "tte": tte})
        reachable = bool(covered)
        report.append({
            "cell_id": cell.cell_id,
            "reachable": reachable,
            "covered_points": len(covered),
            "blocked_points": len(blocked),
        })
        if not reachable:
            unreachable.append(cell.cell_id)
    if unreachable:
        raise AssertionError(
            f"threshold cells outside the live price-band domain: {unreachable}"
        )
    return report
