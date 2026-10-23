"""Scheduled-shadow forecast opportunities (P1a).

For each active contract, an opportunity is scheduled at fixed horizons
before the venue-authoritative contract close (parsed from the ticker name —
see ``forecast_event.scheduled_close_from_ticker``).  When the production
evaluation loop first observes the clock past a scheduled target, the shadow
evaluator runs the *unchanged* production probability chain on the same
point-in-time input bundle under ``suppress_side_effects()`` — no order-decision
ledger, model-calibration log, EPC observation log, state checksum,
rejection log, cell funnel, or canary counter writes.  It submits nothing
and mutates no production state: artifact caches it touches are read-only.

Each emitted event carries ``evaluation_source="scheduled_shadow"``, its own
``forecast_event_id``/``opportunity_id``, explicit ``scheduling_delay_s``
(a crossed target is evaluated on first observation — never silently
backfilled), and the five frozen ablation arms computed from the same
decision's stage values:

  M   exact market anchor used by the event
  Q0  frozen past-fit market-only calibrator (``MERID_Q0_CALIBRATOR_PATH``)
  P   unchanged production chain output
  A   raw -> market anchor -> walk-forward output
  R   raw probability (diagnostic)

``MERID_SCHEDULED_SHADOW_ENABLED=0`` disables;
``MERID_SHADOW_HORIZONS_S="600,300,120,60"`` overrides the schedule.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from merid.prediction import forecast_event as _fe
from utils.logger import get_logger

logger = get_logger("merid.prediction.shadow_evaluator")

_lock = threading.Lock()
# (ticker, horizon) -> {"target": ts, "attempts": n, "status": str}.
# In-process only; the durable accounting is the opportunity ledger
# (forecast_opportunities.jsonl), which records registrations and
# resolutions so a restart re-derives state without losing evidence that
# a second computation attempt occurred.
_opportunities: Dict[Tuple[str, int], Dict[str, Any]] = {}
_q0_cache: Dict[str, Any] = {"path": None, "mtime": None, "tables": None}

EXPERIMENT_ID = "forecast_ablation_v1"


def max_permitted_delay_s() -> float:
    """Upper bound on scheduling delay for an in-horizon observation."""
    return float(os.environ.get("MERID_SHADOW_MAX_DELAY_S", "30"))


def enabled() -> bool:
    v = os.environ.get("MERID_SCHEDULED_SHADOW_ENABLED", "1").strip().lower()
    return v in ("1", "true", "yes", "on")


def scheduled_horizons() -> List[int]:
    raw = os.environ.get("MERID_SHADOW_HORIZONS_S", "600,300,120,60")
    out: List[int] = []
    for tok in raw.split(","):
        try:
            h = int(tok.strip())
        except ValueError:
            continue
        if h > 0:
            out.append(h)
    return sorted(set(out), reverse=True) or [600, 300, 120, 60]


def emitted_opportunities() -> Dict[str, Any]:
    """{ticker:horizon -> {target, attempts, status}} accounting view."""
    with _lock:
        return {
            f"{t}:h{h}": dict(rec) for (t, h), rec in _opportunities.items()
        }


def reset_for_tests() -> None:
    with _lock:
        _opportunities.clear()
        _q0_cache.update(path=None, mtime=None, tables=None)


# ---------------------------------------------------------------------------
# frozen Q0 calibrator (market-only logistic comparator)
# ---------------------------------------------------------------------------

def _q0_tables() -> Dict[str, List[List[float]]]:
    """Load the frozen Q0 artifact: {asset|horizon -> [[p_market, q0], ...]}."""
    path = os.environ.get("MERID_Q0_CALIBRATOR_PATH")
    if not path:
        return {}
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    with _lock:
        if _q0_cache["path"] == path and _q0_cache["mtime"] == mtime:
            return _q0_cache["tables"] or {}
        tables: Dict[str, List[List[float]]] = {}
        try:
            art = json.loads(Path(path).read_text(encoding="utf-8"))
            if art.get("schema") != "q0_calibrator/v1":
                raise ValueError(f"unexpected schema {art.get('schema')!r}")
            for key, pts in (art.get("tables") or {}).items():
                tables[str(key)] = [[float(x), float(y)] for x, y in pts]
            _q0_cache.update(path=path, mtime=mtime, tables=tables)
        except Exception as exc:
            logger.warning("[SHADOW-Q0] failed to load %s: %s", path, exc)
            _q0_cache.update(path=path, mtime=mtime, tables={})
        return _q0_cache["tables"] or {}


def _q0_predict(asset: str, horizon_s: int, p_market: Optional[float]) -> Optional[float]:
    if p_market is None or not (0.0 < p_market < 1.0):
        return None
    pts = _q0_tables().get(f"{str(asset).upper()}|{int(horizon_s)}")
    if not pts:
        return None
    pts = sorted(pts)
    if p_market <= pts[0][0]:
        return pts[0][1]
    if p_market >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= p_market <= x1:
            w = 0.0 if x1 == x0 else (p_market - x0) / (x1 - x0)
            return y0 + w * (y1 - y0)
    return None


def _arms(decision: Any, asset: str, horizon_s: int) -> Dict[str, Any]:
    ind = getattr(decision, "indicators", None) or {}
    m = ind.get("market_anchor_prob")
    q0 = _q0_predict(asset, horizon_s, m)
    return {
        "M": float(m) if isinstance(m, (int, float)) else None,
        "Q0": q0,
        "P": (float(ind["fe_final_p_yes"])
              if isinstance(ind.get("fe_final_p_yes"), (int, float)) else None),
        "A": (float(ind["fe_post_walkforward_p_yes"])
              if isinstance(ind.get("fe_post_walkforward_p_yes"), (int, float)) else None),
        "R": (float(ind["p_yes_raw"])
              if isinstance(ind.get("p_yes_raw"), (int, float)) else None),
        "q0_status": "ok" if q0 is not None else "artifact_missing_or_out_of_range",
    }


# ---------------------------------------------------------------------------
# scheduled opportunity driver
# ---------------------------------------------------------------------------

def shadow_time_budget_ms() -> float:
    """Per-cycle wall-clock budget for shadow evaluations.

    Bounds the lag the hook adds to the production cycle.  Due horizons not
    attempted inside the budget resolve as ``deferred`` — visible in the
    opportunity ledger, never silently skipped.
    """
    return float(os.environ.get("MERID_SHADOW_TIME_BUDGET_MS", "500"))


def maybe_emit_scheduled(
    *,
    ticker: Optional[str],
    asset: str,
    base_kwargs: Dict[str, Any],
    now: Optional[float] = None,
    call_decision: Optional[Callable[..., Any]] = None,
    time_budget_ms: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Emit due scheduled-shadow opportunities for one contract evaluation.

    ``base_kwargs`` is the exact production input bundle for
    ``compute_trade_decision`` (book, spot, strike, TTE, data/regime state,
    artifacts resolved the same way).  Only the ``decision_id``, ``route``,
    and forecast-event fields are overridden.  Returns emitted events.

    The hook is driven by the production loop's cadence: an opportunity is
    evaluated on the first observation at/after its scheduled target, and
    ``scheduling_delay_s`` is recorded explicitly.  Contracts the loop never
    reaches produce no events — expected-vs-emitted accounting comes from
    ``emitted_opportunities()`` plus the contract universe, not from silence.
    """
    if not enabled() or not ticker:
        return []
    close_ts = _fe.scheduled_close_from_ticker(ticker)
    if close_ts is None:
        return []  # no verified schedule -> cannot form the opportunity
    now_ts = float(now if now is not None else time.time())
    if call_decision is None:
        from merid.prediction.trade_decision import compute_trade_decision
        call_decision = compute_trade_decision

    max_delay = max_permitted_delay_s()
    budget_ms = (shadow_time_budget_ms() if time_budget_ms is None
                 else float(time_budget_ms))
    hook_t0 = time.perf_counter()
    out: List[Dict[str, Any]] = []
    for h in scheduled_horizons():
        target = close_ts - float(h)
        key = (str(ticker), int(h))
        opp = f"{EXPERIMENT_ID}|{ticker}|h{h}|{int(target)}"
        with _lock:
            rec = _opportunities.get(key)
            if rec is None:
                # Register the opportunity at first sight.  When sighted
                # before the target this is the expected-opportunity record;
                # when sighted late, registration still records that the
                # opportunity existed (delay is scored at evaluation).
                rec = {"target": target, "attempts": 0,
                       "status": "scheduled", "opportunity_id": opp}
                _opportunities[key] = rec
                _fe.log_opportunity({
                    "opportunity_id": opp, "market_ticker": ticker,
                    "asset": asset, "scheduled_horizon_s": int(h),
                    "scheduled_target_ts": target,
                    "maximum_permitted_delay_s": max_delay,
                    "registered_ts": now_ts,
                    "registered_after_target": now_ts >= target,
                    "scheduled_contract_close_ts": close_ts,
                    "boundary_source": "ticker_parsed_et",
                    "status": "scheduled",
                    "experiment_id": EXPERIMENT_ID,
                    "cohort_scope": "conditional_on_reaching_eval_hook",
                })
            if rec["status"] != "scheduled":
                continue
            if now_ts < target:
                continue  # registered, not yet due
            if now_ts > close_ts:
                rec["status"] = "missed"
                _fe.log_opportunity({
                    "opportunity_id": opp, "market_ticker": ticker,
                    "scheduled_horizon_s": int(h),
                    "scheduled_target_ts": target,
                    "resolved_ts": now_ts,
                    "status": "missed",
                    "experiment_id": EXPERIMENT_ID,
                })
                continue
            elapsed_ms = (time.perf_counter() - hook_t0) * 1e3
            if elapsed_ms > budget_ms:
                # Per-cycle budget exhausted BEFORE attempting: the due
                # opportunity stays 'scheduled' (retried next cycle — likely
                # resolving 'late'), and the deferral is a visible ledger
                # row rather than a silent skip.
                _fe.log_opportunity({
                    "opportunity_id": opp, "market_ticker": ticker,
                    "scheduled_horizon_s": int(h),
                    "scheduled_target_ts": target,
                    "resolved_ts": now_ts,
                    "status": "deferred",
                    "elapsed_hook_ms": round(elapsed_ms, 1),
                    "budget_ms": budget_ms,
                    "experiment_id": EXPERIMENT_ID,
                })
                continue
            rec["status"] = "evaluating"

        delay = now_ts - target
        with _lock:
            rec["attempts"] += 1
            attempt_n = rec["attempts"]
        eid = f"{opp}|attempt{attempt_n}|{uuid.uuid4().hex[:12]}"
        kwargs = dict(base_kwargs)
        kwargs["decision_id"] = eid
        # Standardized shadow execution inputs (taker/ask) — declared, not
        # silently the deployed pass; see manifest estimands.
        kwargs["entry_price_basis"] = "ask"
        kwargs["route"] = "taker"
        out.append({
            "ticker": ticker,
            "scheduled_horizon_s": int(h),
            "scheduled_target_ts": target,
            "opportunity_id": opp,
            "attempt_index": attempt_n,
            "scheduling_delay_s": round(delay, 3),
        })
        try:
            with _fe.suppress_side_effects():
                call_decision(
                    forecast_event_source="scheduled_shadow",
                    scheduled_horizon_s=int(h),
                    scheduled_target_ts=target,
                    forecast_opportunity_id=opp,
                    evaluation_id=eid,
                    attempt_index=attempt_n,
                    execution_inputs="standardized_taker_ask",
                    max_delay_s=max_delay,
                    forecast_arms_fn=lambda d, _a=asset, _h=int(h): _arms(d, _a, _h),
                    **kwargs,
                )
            status = "late" if delay > max_delay else "emitted"
        except Exception as exc:
            status = "unavailable"
            logger.debug(
                "[SHADOW] eval failed ticker=%s h=%ds: %s", ticker, h, exc
            )
        with _lock:
            rec["status"] = status
        _fe.log_opportunity({
            "opportunity_id": opp, "market_ticker": ticker,
            "scheduled_horizon_s": int(h),
            "scheduled_target_ts": target,
            "resolved_ts": time.time(),
            "scheduling_delay_s": round(delay, 3),
            "maximum_permitted_delay_s": max_delay,
            "attempt_index": attempt_n,
            "status": status,
            "experiment_id": EXPERIMENT_ID,
        })
    return out
