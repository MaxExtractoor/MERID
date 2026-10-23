"""Same-event forecast telemetry envelopes (P1a audit instrumentation).

One ``forecast_event_id`` is minted at evaluation entry and carried through
every probability transformation of a single ``compute_trade_decision``
evaluation.  On finalize, one compact JSONL event is appended — completed,
partial (early return), or failed (exception).  This replaces the historical
minute-bucket proximity joins between independent stage logs: every stage
value in an event belongs to the same evaluation by construction.

The stage chain is populated from the decision's ``indicators`` dict, which
the production path already fills at each transformation boundary.  Stage
fields that never ran stay ``None`` and are listed in ``stage_coverage`` —
missing stages never silently become fallback probabilities.

Side-effect suppression
-----------------------
``suppress_side_effects()`` marks the calling thread so shadow evaluations
can run the *same* production chain without writing model-calibration /
EPC-observation / state-checksum records or advancing the canary counter.
Artifact caches that only memoize read results are unaffected.

Emission is best-effort and never raises: telemetry failures are counted in
``counters()`` and must never alter trading behavior.

``MERID_FORECAST_EVENT_LOG_ENABLED=0`` disables emission entirely;
``MERID_FORECAST_EVENT_LOG_PATH`` overrides the destination.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.forecast_event")

_ROOT = Path(__file__).resolve().parents[2]
_lock = threading.Lock()
# ContextVar (not threading.local): the suppression scope must follow the
# logical evaluation context through asyncio tasks, never bleed between
# tasks sharing a thread.  Threads each get an independent default context,
# so worker-thread evaluations stay unsuppressed unless they opt in.
_suppression_var: ContextVar = ContextVar(
    "forecast_event_side_effect_suppression", default=frozenset())

_counters: Dict[str, int] = {
    "emitted": 0,
    "emit_failed": 0,
    "completed": 0,
    "partial": 0,
    "failed": 0,
    "dropped_disabled": 0,
}

SCHEMA_VERSION = 2

# Early-return reasons that mean the candidate inputs themselves failed
# integrity checks (not strategy screens).  Everything else that stops the
# chain before probabilities is a strategy/admission screen.
_INPUT_INVALID_REASONS = frozenset({
    "expired_or_no_time",
    "non_finite_yes_score",
    "non_finite_no_score",
    "non_finite_p_yes_model",
    "non_finite_p_no_model",
    "invalid_executable_asks",
    "bachelier_vol_resolution_failed",
})


def enabled() -> bool:
    v = os.environ.get("MERID_FORECAST_EVENT_LOG_ENABLED", "1").strip().lower()
    return v in ("1", "true", "yes", "on")


def log_path() -> Path:
    p = os.environ.get("MERID_FORECAST_EVENT_LOG_PATH")
    return Path(p) if p else _ROOT / "logs" / "forecast_events.jsonl"


def counters() -> Dict[str, int]:
    with _lock:
        return dict(_counters)


def reset_for_tests() -> None:
    with _lock:
        for k in _counters:
            _counters[k] = 0


# ---------------------------------------------------------------------------
# side-effect suppression (shadow evaluations)
# ---------------------------------------------------------------------------

@contextmanager
def suppress_side_effects() -> Iterator[None]:
    """Suppress durable telemetry/checksum side effects in this context.

    ContextVar-scoped: nested contexts compose, exceptions restore the
    prior state, and plain worker threads see the default empty context.
    Verified dispatch model (2026-10): the decision path is synchronous
    inside ``asyncio.gather`` tasks — no ``to_thread``/``run_in_executor``
    anywhere in ``agent_grid_15m`` or ``trade_decision``, so the context
    cannot leak to sibling tasks (sync code never yields).

    UNSUPPORTED transition: ``asyncio.to_thread`` copies the *current*
    Context into the worker — a shadow suppression entered before such a
    dispatch would travel with it, and a production eval dispatched while
    suppression is active would be wrongly suppressed.  If executor
    dispatch is ever added to this path, suppression must be scoped INSIDE
    the dispatched callable, not around the dispatch call site.
    """
    token = _suppression_var.set(_suppression_var.get() | {"side_effects"})
    try:
        yield
    finally:
        _suppression_var.reset(token)


def side_effects_suppressed() -> bool:
    return "side_effects" in _suppression_var.get()


# ---------------------------------------------------------------------------
# scheduled contract boundary
# ---------------------------------------------------------------------------

def scheduled_close_from_ticker(ticker: Optional[str]) -> Optional[float]:
    """Scheduled close (epoch s, UTC) parsed from a Kalshi 15m ticker.

    Delegates to ``expiry_fallback.parse_kalshi_15m_window_end_utc`` — the
    canonical parser and single source of truth.  The embedded datetime is
    the 15m window END in **America/New_York** (Kalshi's crypto event
    timezone), converted to UTC via ZoneInfo so DST transitions are handled
    — verified against venue ``close_time`` by
    ``analysis.forecast_audit.boundary_verify`` (sampled KX*15M tickers
    matched close_time to <1s; the contractual observation endpoint
    ``expected_expiration_time`` is a separate field ~300s later).

    Returns ``None`` when the name does not parse; callers fall back to a
    *flagged* reconstruction.
    """
    if not ticker:
        return None
    try:
        from merid.event_venues.kalshi.expiry_fallback import (
            parse_kalshi_15m_window_end_utc,
        )
        dt = parse_kalshi_15m_window_end_utc(str(ticker))
        return float(dt.timestamp()) if dt is not None else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# event builder
# ---------------------------------------------------------------------------

def _event_id(evaluation_id: str) -> str:
    return f"fev_{hashlib.sha256(evaluation_id.encode()).hexdigest()[:24]}"


def _record_id(evaluation_id: str, content: str) -> str:
    """Stable retransmission key: same evaluation re-sent -> same record.

    Two DIFFERENT evaluations never share a record_id; conflicting
    envelopes under one record_id are a data-integrity signal the runner
    reports rather than silently deduping.
    """
    return "rec_" + hashlib.sha256(
        f"{evaluation_id}|{content}".encode("utf-8")
    ).hexdigest()[:24]


_file_hash_cache: Dict[str, Dict[str, Any]] = {}


def _sha256_file(path: Optional[str]) -> Optional[str]:
    """sha256 of an artifact file, cached by (path, mtime, size).

    Hashing runs once per artifact version, not once per event — the
    mtime/size key invalidates when a new artifact lands.
    """
    if not path:
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    c = _file_hash_cache.get(path)
    if c and c.get("mtime") == st.st_mtime and c.get("size") == st.st_size:
        return c.get("sha")
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        sha = h.hexdigest()[:24]
    except Exception:
        return None
    _file_hash_cache[path] = {"mtime": st.st_mtime, "size": st.st_size, "sha": sha}
    return sha


def _content_hash(event: Dict[str, Any]) -> str:
    """Hash of the semantically meaningful envelope (excludes ids/timestamps)."""
    fields = {k: v for k, v in event.items()
              if k not in ("forecast_event_id", "record_id", "content_hash",
                           "evaluation_start_ts", "evaluation_end_ts",
                           "scheduling_delay_s")}
    return hashlib.sha256(
        json.dumps(fields, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def begin_event(
    kwargs: Dict[str, Any],
    *,
    evaluation_source: str = "production",
    scheduled_horizon_s: Optional[int] = None,
    scheduled_target_ts: Optional[float] = None,
    opportunity_id: Optional[str] = None,
    evaluation_id: Optional[str] = None,
    attempt_index: int = 0,
    execution_inputs: Optional[str] = None,
    max_delay_s: Optional[float] = None,
    artifact_paths: Optional[Dict[str, Optional[str]]] = None,
) -> Optional[Dict[str, Any]]:
    """Create the in-memory event trace at evaluation entry.

    Identity is three-part: ``opportunity_id`` (what was due: contract +
    horizon + experiment, stable across attempts), ``evaluation_id``
    (this computation attempt — unique per call), ``record_id``
    (retransmission key for this exact envelope).  Returns ``None`` when
    telemetry is disabled.
    """
    if not enabled():
        return None
    ticker = kwargs.get("ticker")
    tte = kwargs.get("seconds_to_expiry")
    close_ts = scheduled_close_from_ticker(ticker)
    boundary_source = "ticker_parsed_et" if close_ts is not None else None
    if close_ts is None and isinstance(tte, (int, float)):
        close_ts = time.time() + float(tte)
        boundary_source = "reconstructed_tte"
    if close_ts is None:
        boundary_source = "unresolved"
    opp = opportunity_id or str(kwargs.get("decision_id") or "")
    eid = evaluation_id or str(kwargs.get("decision_id") or uuid.uuid4().hex)
    arts = artifact_paths or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "forecast_event_id": _event_id(eid),
        "evaluation_id": eid,
        "record_id": None,  # set at emit, when the envelope is complete
        "content_hash": None,
        "attempt_index": attempt_index,
        "market_ticker": ticker,
        "asset": kwargs.get("asset"),
        "opportunity_id": opp,
        "scheduled_horizon_s": scheduled_horizon_s,
        "evaluation_source": evaluation_source,
        "execution_inputs": execution_inputs or "actual",
        # timing
        "scheduled_target_ts": scheduled_target_ts,
        "actual_evaluation_ts": None,  # set at finalize (eval end clock)
        "maximum_permitted_delay_s": max_delay_s,
        "scheduling_delay_s": (
            None if scheduled_target_ts is None
            else round(time.time() - float(scheduled_target_ts), 3)
        ),
        "opportunity_status": None,  # emitted|late|missed|invalid_input|unavailable
        "evaluation_start_ts": time.time(),
        "feature_snapshot_ts": None,
        "latest_input_receive_ts": None,
        "book_event_ts": None,
        "book_receive_ts": None,
        "evaluation_end_ts": None,
        "seconds_to_expiry_at_eval": (
            float(tte) if isinstance(tte, (int, float)) else None
        ),
        "scheduled_contract_close_ts": close_ts,
        "boundary_source": boundary_source,
        # probability chain — filled at finalize from decision indicators
        "raw_p_yes": None,
        "source_selected_p_yes": None,
        "market_anchor_prob_used": None,
        "market_anchor_weight": None,
        "post_anchor_p_yes": None,
        "post_walkforward_p_yes": None,
        "post_epc_p_yes": None,
        "post_tail_p_yes": None,
        "post_stream_p_yes": None,
        "final_p_yes": None,
        "final_p_no_for_no": None,
        # provenance
        "code_build_hash": kwargs.get("build_sha"),
        "model_artifact_hash": None,
        "walkforward_artifact_hash": _sha256_file(arts.get("walkforward")),
        "epc_artifact_hash": _sha256_file(arts.get("epc")),
        "tail_artifact_hash": _sha256_file(arts.get("tail")),
        "q0_artifact_hash": _sha256_file(arts.get("q0")),
        "effective_config_hash": None,
        # validity / policy
        "input_validity": "unassessed",
        "forecast_availability": "unavailable",
        "admission_result": "unavailable",
        "admission_reason": None,
        "policy_version": kwargs.get("policy_version"),
        # lifecycle
        "terminal_state": "open",
        "terminal_reason": None,
        "stage_coverage": {},
        "arms": None,
    }


_STAGE_MAP = {
    "raw_p_yes": "p_yes_raw",
    "source_selected_p_yes": "p_yes_pre_anchor",
    "market_anchor_prob_used": "market_anchor_prob",
    "market_anchor_weight": "market_anchor_weight",
    "post_anchor_p_yes": "p_yes_post_anchor",
    "post_walkforward_p_yes": "fe_post_walkforward_p_yes",
    "post_epc_p_yes": "fe_post_epc_p_yes",
    "post_tail_p_yes": "fe_post_tail_p_yes",
    "post_stream_p_yes": "fe_post_stream_p_yes",
    "final_p_yes": "fe_final_p_yes",
    "final_p_no_for_no": "fe_final_p_no_for_no",
}


def _emit(event: Dict[str, Any]) -> None:
    try:
        event["content_hash"] = _content_hash(event)
        event["record_id"] = _record_id(
            str(event.get("evaluation_id")), str(event["content_hash"]))
        event["actual_evaluation_ts"] = event.get("evaluation_end_ts") or time.time()
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock, open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
        with _lock:
            _counters["emitted"] += 1
            _counters[event.get("terminal_state", "partial")] = (
                _counters.get(event.get("terminal_state", "partial"), 0) + 1
            )
    except Exception as exc:  # telemetry must never break trading
        with _lock:
            _counters["emit_failed"] += 1
        logger.debug("[FORECAST-EVENT] emit failed: %s", exc)


def opportunity_log_path() -> Path:
    p = os.environ.get("MERID_FORECAST_OPP_LOG_PATH")
    return Path(p) if p else _ROOT / "logs" / "forecast_opportunities.jsonl"


def log_opportunity(row: Dict[str, Any]) -> None:
    """Append one scheduled-opportunity accounting row (best-effort).

    Rows are the expected-opportunity ledger: written when an opportunity
    is REGISTERED (before its target is crossed) and again when it is
    resolved as emitted / late / missed / invalid_input / unavailable.
    The runner reconciles registrations to resolutions; silence is never
    counted as a completed opportunity.
    """
    if not enabled():
        return
    try:
        row.setdefault("record_type", "opportunity")
        path = opportunity_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock, open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, default=str) + "\n")
    except Exception as exc:
        with _lock:
            _counters["emit_failed"] += 1
        logger.debug("[FORECAST-OPP] emit failed: %s", exc)


def emit_event(event: Dict[str, Any]) -> None:
    """Append a populated event to the JSONL sink (best-effort)."""
    _emit(event)


def finalize_from_decision(event: Optional[Dict[str, Any]], decision: Any) -> None:
    """Finalize and emit the event from the returned TradeDecision.

    Called for every return path — completed evaluations and all ``_no_trade``
    early returns alike (a decision object is always returned).
    """
    if event is None:
        return
    try:
        populate_from_decision(event, decision)
        _emit(event)
    except Exception as exc:  # never break trading for telemetry
        with _lock:
            _counters["emit_failed"] += 1
        logger.debug("[FORECAST-EVENT] finalize failed: %s", exc)


def populate_from_decision(event: Dict[str, Any], decision: Any) -> None:
    """Fill the event's stage/validity/admission fields from a decision.

    Missing stage keys stay ``None`` and are flagged in ``stage_coverage`` —
    a stage that never ran must never read as a fallback probability.
    """
    ind = getattr(decision, "indicators", None) or {}
    for field, key in _STAGE_MAP.items():
        v = ind.get(key)
        event[field] = float(v) if isinstance(v, (int, float)) else None
        event["stage_coverage"][field] = event[field] is not None
    event["evaluation_end_ts"] = time.time()
    reason = getattr(decision, "no_trade_reason", None)
    ran_chain = event["post_anchor_p_yes"] is not None or (
        event["raw_p_yes"] is not None
    )
    if reason in _INPUT_INVALID_REASONS:
        event["input_validity"] = "invalid"
    elif reason is not None and not ran_chain:
        event["input_validity"] = "unassessed"
    else:
        event["input_validity"] = "valid"
    event["forecast_availability"] = (
        "available" if event["final_p_yes"] is not None else "unavailable"
    )
    event["admission_result"] = str(getattr(decision, "decision", "")).lower() or "no_trade"
    event["admission_reason"] = reason
    event["terminal_state"] = "completed" if reason is None else "partial"
    event["terminal_reason"] = reason or "completed"
    cfg = getattr(decision, "config_hash", None)
    if cfg:
        event["effective_config_hash"] = cfg
    bsha = getattr(decision, "build_sha", None)
    if bsha:
        event["code_build_hash"] = bsha
    # Opportunity status: late evaluation stays diagnostic but is excluded
    # from the confirmatory horizon by the runner.
    delay = event.get("scheduling_delay_s")
    maxd = event.get("maximum_permitted_delay_s")
    if event["input_validity"] == "invalid":
        event["opportunity_status"] = "invalid_input"
    elif event["forecast_availability"] != "available":
        event["opportunity_status"] = "unavailable"
    elif (
        maxd is not None and delay is not None and float(delay) > float(maxd)
    ):
        event["opportunity_status"] = "late"
    else:
        event["opportunity_status"] = "emitted"


def finalize_exception(event: Optional[Dict[str, Any]], exc: BaseException) -> None:
    """Finalize and emit a ``failed`` event when evaluation raises."""
    if event is None:
        return
    try:
        event["evaluation_end_ts"] = time.time()
        event["terminal_state"] = "failed"
        event["terminal_reason"] = f"{type(exc).__name__}:{exc}"[:200]
        event["opportunity_status"] = "unavailable"
        _emit(event)
    except Exception:
        with _lock:
            _counters["emit_failed"] += 1
