"""Evidence-artifact health: tiered freshness states for the live evidence gate.

The entry evidence gate reads ``data/live_entry_evidence.json``, rebuilt by
the decision audit ledger (intended cadence 120s).  Before 2026-10-13 the
gate consumed whatever artifact was on disk with no age semantics — an
08:20 artifact silently drove decisions for eight hours after the refresh
query stopped completing.  This module turns artifact age into an explicit,
logged, queryable state:

    FRESH     age <= MERID_EVIDENCE_DEGRADED_AFTER_S (900s)
              normal gates, normal size.
    DEGRADED  age <= MERID_EVIDENCE_STALE_AFTER_S (3600s)
              cells still scored, but the required evidence margin rises by
              MERID_EVIDENCE_DEGRADED_MARGIN_C and size is capped at
              MERID_EVIDENCE_DEGRADED_MAX_CONTRACTS.
    STALE     age <= MERID_EVIDENCE_UNUSABLE_AFTER_S (10800s)
              stale cells are NOT scored (neither veto nor support); the side
              gets the missing-artifact verdict — bounded escape-lane
              fallback only, 1 contract.
    UNUSABLE  older, or artifact missing / unreadable
              evidence-dependent entries fail closed.  Lanes whose admission
              never depended on the artifact (settlement-convergence lane,
              current-build provisional lane) keep their own gates.

Operator override: ``MERID_EVIDENCE_OPERATOR_OVERRIDE_UNTIL`` (ISO-8601 or
epoch seconds).  While unexpired, an UNUSABLE artifact is held at STALE
(bounded fallback) instead of failing closed — labelled
``DISABLED_OPERATOR_OVERRIDE`` when the exporter is off — with a recurring
alert.  After expiry the age-based state applies again.  Live quotes,
position/exposure state, order reconciliation and loss/suspension controls
are independent of this module and never relaxed by it.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.evidence_health")

FRESH = "FRESH"
DEGRADED = "DEGRADED"
STALE = "STALE"
UNUSABLE = "UNUSABLE"

_STATE_ACTION = {
    FRESH: "allow",
    DEGRADED: "downsize",
    STALE: "fallback",
    UNUSABLE: "block",
}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def degraded_after_s() -> float:
    return _env_float("MERID_EVIDENCE_DEGRADED_AFTER_S", 900.0)


def stale_after_s() -> float:
    return _env_float("MERID_EVIDENCE_STALE_AFTER_S", 3600.0)


def unusable_after_s() -> float:
    return _env_float("MERID_EVIDENCE_UNUSABLE_AFTER_S", 10800.0)


def degraded_margin_c() -> float:
    return _env_float("MERID_EVIDENCE_DEGRADED_MARGIN_C", 1.0)


def degraded_max_contracts() -> int:
    return max(1, int(_env_float("MERID_EVIDENCE_DEGRADED_MAX_CONTRACTS", 1)))


def export_enabled() -> bool:
    return os.environ.get("MERID_LIVE_EVIDENCE_EXPORT", "1").strip().lower() in (
        "1", "true", "yes",
    )


def override_until() -> Optional[float]:
    """Parse MERID_EVIDENCE_OPERATOR_OVERRIDE_UNTIL (epoch or ISO-8601)."""
    raw = (os.environ.get("MERID_EVIDENCE_OPERATOR_OVERRIDE_UNTIL") or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            # Naive timestamps are ambiguous on a non-UTC host; refuse them
            # rather than silently shifting the expiry by the UTC offset.
            logger.error(
                "[EVIDENCE-HEALTH] MERID_EVIDENCE_OPERATOR_OVERRIDE_UNTIL=%r has "
                "no timezone; override ignored", raw,
            )
            return None
        return dt.timestamp()
    except ValueError:
        logger.error(
            "[EVIDENCE-HEALTH] unparseable MERID_EVIDENCE_OPERATOR_OVERRIDE_UNTIL=%r; "
            "override ignored", raw,
        )
        return None


# Refresh bookkeeping, written by the audit ledger's evidence exporter (same
# process).  Absent values mean "no attempt observed in this process".
_refresh_lock = threading.Lock()
_refresh_status: Dict[str, Any] = {
    "last_attempt_at": None,
    "last_success_at": None,
    "failure_streak": 0,
    "last_error": None,
}


def record_refresh_attempt(ts: Optional[float] = None) -> None:
    with _refresh_lock:
        _refresh_status["last_attempt_at"] = time.time() if ts is None else ts


def record_refresh_result(ok: bool, error: Optional[str] = None,
                          ts: Optional[float] = None) -> None:
    with _refresh_lock:
        if ok:
            _refresh_status["last_success_at"] = time.time() if ts is None else ts
            _refresh_status["failure_streak"] = 0
            _refresh_status["last_error"] = None
        else:
            _refresh_status["failure_streak"] = int(_refresh_status["failure_streak"]) + 1
            _refresh_status["last_error"] = error


def refresh_status() -> Dict[str, Any]:
    with _refresh_lock:
        return dict(_refresh_status)


@dataclass(frozen=True)
class EvidenceHealth:
    state: str
    mode: str
    age_s: Optional[float]
    artifact_exists: bool
    artifact_parse_ok: bool
    artifact_mtime: Optional[float]
    generated_at: Optional[float]
    last_refresh_attempt_at: Optional[float]
    last_refresh_success_at: Optional[float]
    refresh_failure_streak: int
    override_until: Optional[float]
    age_state: str

    @property
    def decision_action(self) -> str:
        return _STATE_ACTION[self.state]

    @property
    def margin_uplift_frac(self) -> float:
        return degraded_margin_c() / 100.0 if self.state == DEGRADED else 0.0

    @property
    def max_contracts(self) -> Optional[int]:
        """Per-order contract cap imposed by evidence health (None = no cap)."""
        if self.state == FRESH:
            return None
        if self.state == DEGRADED:
            return degraded_max_contracts()
        return 1

    @property
    def score_cells(self) -> bool:
        return self.state in (FRESH, DEGRADED) and self.artifact_parse_ok

    def detail(self) -> Dict[str, Any]:
        return {
            "evidence_state": self.state,
            "evidence_mode": self.mode,
            "evidence_age_seconds": (
                round(self.age_s, 1) if self.age_s is not None else None
            ),
            "age_state": self.age_state,
            "decision_action": self.decision_action,
            "artifact_exists": self.artifact_exists,
            "artifact_parse_ok": self.artifact_parse_ok,
            "artifact_mtime": self.artifact_mtime,
            "generated_at": self.generated_at,
            "last_refresh_attempt_at": self.last_refresh_attempt_at,
            "last_refresh_success_at": self.last_refresh_success_at,
            "refresh_failure_streak": self.refresh_failure_streak,
            "override_until": self.override_until,
        }


def _age_state(age_s: Optional[float], usable: bool) -> str:
    if not usable or age_s is None:
        return UNUSABLE
    if age_s <= degraded_after_s():
        return FRESH
    if age_s <= stale_after_s():
        return DEGRADED
    if age_s <= unusable_after_s():
        return STALE
    return UNUSABLE


def assess(
    artifact: Optional[Dict[str, Any]],
    *,
    artifact_mtime: Optional[float] = None,
    now: Optional[float] = None,
) -> EvidenceHealth:
    """Classify the loaded evidence artifact.

    ``artifact`` is what ``trade_decision._load_live_evidence`` returned: a
    parsed dict, or the ``{"artifact_missing": True}`` sentinel for an absent
    or unreadable file.  Age is measured from the artifact's ``generated_at``
    (when its data window was computed), falling back to file mtime.
    """
    now = time.time() if now is None else float(now)
    missing = artifact is None or bool(artifact.get("artifact_missing"))
    gen_at = None
    if not missing:
        try:
            gen_at = float(artifact.get("generated_at") or 0.0) or None
        except (TypeError, ValueError):
            gen_at = None
    basis = gen_at if gen_at is not None else artifact_mtime
    age_s = (now - basis) if (basis is not None and not missing) else None
    age_state = _age_state(age_s, usable=not missing)

    ov = override_until()
    override_active = ov is not None and now < ov
    state = age_state
    if override_active and age_state == UNUSABLE:
        state = STALE
    if override_active:
        mode = "OPERATOR_OVERRIDE" if export_enabled() else "DISABLED_OPERATOR_OVERRIDE"
    elif not export_enabled():
        mode = "EXPORT_DISABLED"
    else:
        mode = "NORMAL"

    rs = refresh_status()
    last_success = rs["last_success_at"]
    if gen_at is not None and (last_success is None or gen_at > last_success):
        last_success = gen_at
    health = EvidenceHealth(
        state=state,
        mode=mode,
        age_s=age_s,
        artifact_exists=not (artifact is None or (missing and artifact_mtime is None)),
        artifact_parse_ok=not missing,
        artifact_mtime=artifact_mtime,
        generated_at=gen_at,
        last_refresh_attempt_at=rs["last_attempt_at"],
        last_refresh_success_at=last_success,
        refresh_failure_streak=int(rs["failure_streak"]),
        override_until=ov,
        age_state=age_state,
    )
    _note_transition(health, now)
    return health


# One log per state transition, plus a recurring reminder while the system is
# running on a non-FRESH artifact so the condition cannot scroll out of view.
_transition_lock = threading.Lock()
_last: Dict[str, Any] = {"state": None, "mode": None, "alert_at": 0.0}


def _alert_every_s() -> float:
    return _env_float("MERID_EVIDENCE_HEALTH_ALERT_EVERY_S", 600.0)


def _note_transition(h: EvidenceHealth, now: float) -> None:
    with _transition_lock:
        changed = (h.state, h.mode) != (_last["state"], _last["mode"])
        due = h.state != FRESH and now - float(_last["alert_at"]) >= _alert_every_s()
        if not (changed or due):
            return
        prev = _last["state"]
        _last["state"], _last["mode"], _last["alert_at"] = h.state, h.mode, now
    level = {
        FRESH: logger.info,
        DEGRADED: logger.warning,
        STALE: logger.warning,
        UNUSABLE: logger.error,
    }[h.state]
    level(
        "[EVIDENCE_%s] %s evidence_state=%s prev=%s mode=%s age_s=%s age_state=%s "
        "action=%s artifact_parse_ok=%s last_refresh_success_at=%s "
        "refresh_failure_streak=%d override_until=%s",
        h.state,
        "transition" if changed else "still",
        h.state,
        prev,
        h.mode,
        f"{h.age_s:.0f}" if h.age_s is not None else "n/a",
        h.age_state,
        h.decision_action,
        h.artifact_parse_ok,
        h.last_refresh_success_at,
        h.refresh_failure_streak,
        h.override_until,
    )
    if h.mode in ("OPERATOR_OVERRIDE", "DISABLED_OPERATOR_OVERRIDE"):
        logger.warning(
            "[EVIDENCE_OPERATOR_OVERRIDE] active until %s (%.0fs left): UNUSABLE "
            "evidence held at STALE bounded-fallback; remove or let expire",
            h.override_until, (h.override_until or now) - now,
        )


def _reset_for_tests() -> None:
    with _transition_lock:
        _last.update({"state": None, "mode": None, "alert_at": 0.0})
    with _refresh_lock:
        _refresh_status.update({
            "last_attempt_at": None, "last_success_at": None,
            "failure_streak": 0, "last_error": None,
        })
