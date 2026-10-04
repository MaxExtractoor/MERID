"""Durable residual-exposure state machine for rejected protective exits.

2026-10-04: a non-executable protective exit leaves live binary tail risk.
The implicit "next monitor cycle emits a fresh candidate" loop is not a
state machine — it cannot dedupe degraded intents across cycles, does not
remember failed attempts, and has no explicit time-to-settlement
termination.  This module owns a persisted per-position-epoch residual
record so exactly one governed exit workflow exists per residual exposure.

Identity: ``market_ticker : held_side : position_epoch`` where the epoch is
the entry fill/order id when resolvable (a flat->new position opens a new
epoch).  Records persist to ``data/stop_residuals.json`` so a restart
reloads in-flight decisions and preserves idempotency.

Status flow::

    PRIMARY_REJECTED -> REEVALUATING
      -> DEGRADED_EXIT_SIMULATED   (approved, live submission gated off)
      -> DEGRADED_EXIT_SUBMITTED   (degraded IOC routed)
         -> PARTIALLY_FILLED       (residual qty remains; next eval re-uses
                                   the same record — no second dg1 intent
                                   beyond the attempt budget)
      -> HOLD_APPROVED             (fair value positively justifies holding)
      -> RESIDUAL_EXIT_DATA_UNAVAILABLE (cannot make a reliable decision)
      -> RESIDUAL_RISK_BREACH      (attempt budget exhausted / terminal risk)
      -> SETTLED                   (position flat / expiry reached)

HOLD_APPROVED means the system positively concluded hold > exit.  Missing
fair value, malformed VWAP, vanished depth, or divergent book state are NOT
holds — they are RESIDUAL_EXIT_DATA_UNAVAILABLE.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.residual_exit")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# One degraded attempt per residual by default — the primary stop already
# failed; looping degraded IOCs is book-sweeping by another name.
DEGRADED_MAX_ATTEMPTS = _env_int("MERID_STOP_DEGRADED_MAX_ATTEMPTS", 1)

# |fresh_bid - firewall_vwap| beyond this means the rejection-time book no
# longer describes reality: the VWAP is stale evidence, not a decision input.
DEGRADED_MAX_VWAP_DIVERGENCE_CENTS = _env_int(
    "MERID_STOP_DEGRADED_MAX_VWAP_DIVERGENCE_C", 5
)


class ResidualStatus(str, Enum):
    PRIMARY_REJECTED = "PRIMARY_REJECTED"
    REEVALUATING = "REEVALUATING"
    DEGRADED_EXIT_SIMULATED = "DEGRADED_EXIT_SIMULATED"
    DEGRADED_EXIT_SUBMITTED = "DEGRADED_EXIT_SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    HOLD_APPROVED = "HOLD_APPROVED"
    DATA_UNAVAILABLE = "RESIDUAL_EXIT_DATA_UNAVAILABLE"
    RISK_BREACH = "RESIDUAL_RISK_BREACH"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"


# Statuses that end the residual's right to emit orders.  HOLD_APPROVED is
# terminal per evaluation but a LATER candidate (fresh candidate_id) may
# reopen the residual if economics change — handled via reopen().
_TERMINAL_STATUSES = frozenset({
    ResidualStatus.RISK_BREACH.value,
    ResidualStatus.SETTLED.value,
    ResidualStatus.CLOSED.value,
})


@dataclass
class ResidualRecord:
    """Durable per-position-epoch residual-exposure state."""

    residual_id: str
    ticker: str
    held_side: str
    position_epoch: str
    status: str = ResidualStatus.PRIMARY_REJECTED.value
    original_quantity_cc: int = 0
    remaining_quantity_cc: int = 0
    trigger_id: str = ""
    trigger_reason: str = ""
    primary_client_order_id: Optional[str] = None
    degraded_client_order_ids: List[str] = field(default_factory=list)
    degraded_attempt_number: int = 0
    first_trigger_at: float = 0.0
    last_evaluated_at: float = 0.0
    settlement_deadline: Optional[float] = None
    normal_stop_limit_cents: Optional[int] = None
    firewall_vwap_cents: Optional[int] = None
    model_fair_value_cents: Optional[int] = None
    fresh_bid_cents: Optional[int] = None
    selected_degraded_limit_cents: Optional[int] = None
    decision_reason: str = ""
    venue_acknowledged_quantity: int = 0
    reconciled_quantity_cc: int = 0
    policy: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = dict(self.__dict__)
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ResidualRecord":
        known = {f.name for f in ResidualRecord.__dataclass_fields__.values()}
        return ResidualRecord(**{k: v for k, v in d.items() if k in known})


def _residual_id(ticker: str, held_side: str, position_epoch: str) -> str:
    return f"{ticker}:{held_side}:{position_epoch}"


class ResidualExitTracker:
    """Durable, idempotent owner of residual-exposure workflows."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or self._default_path()
        self._lock = threading.Lock()
        self._records: Dict[str, ResidualRecord] = {}
        self._load()

    @staticmethod
    def _default_path() -> Path:
        return Path(__file__).resolve().parents[3] / "data" / "stop_residuals.json"

    def _load(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for rid, rd in (data.get("records") or {}).items():
                    self._records[rid] = ResidualRecord.from_dict(rd)
        except Exception as exc:
            logger.warning("[RESIDUAL-EXIT] failed to load %s: %s", self._path, exc)

    def _persist_locked(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "records": {rid: r.to_dict() for rid, r in self._records.items()}
            }
            # Atomic-ish replace so a crash mid-write cannot corrupt state.
            fd, tmp = tempfile.mkstemp(
                dir=str(self._path.parent), suffix=".tmp", prefix="stop_residuals_"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f)
                os.replace(tmp, self._path)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except Exception as exc:
            logger.warning("[RESIDUAL-EXIT] failed to persist: %s", exc)

    def get_or_create(
        self,
        ticker: str,
        held_side: str,
        position_epoch: str,
        *,
        trigger_id: str,
        trigger_reason: str,
        quantity_cc: int,
        settlement_deadline: Optional[float] = None,
    ) -> ResidualRecord:
        """Return the live residual for this position epoch, creating it on
        the first rejected protective exit.  A record in a terminal status is
        reopened only when the SAME epoch still shows live exposure — a fresh
        position opens a fresh epoch and therefore a fresh record."""
        rid = _residual_id(ticker, held_side, position_epoch)
        with self._lock:
            rec = self._records.get(rid)
            now = time.time()
            if rec is None:
                rec = ResidualRecord(
                    residual_id=rid,
                    ticker=ticker,
                    held_side=held_side,
                    position_epoch=position_epoch,
                    status=ResidualStatus.PRIMARY_REJECTED.value,
                    original_quantity_cc=quantity_cc,
                    remaining_quantity_cc=quantity_cc,
                    trigger_id=trigger_id,
                    trigger_reason=trigger_reason,
                    first_trigger_at=now,
                    last_evaluated_at=now,
                    settlement_deadline=settlement_deadline,
                )
                self._records[rid] = rec
                self._persist_locked()
                return rec

            rec.last_evaluated_at = now
            rec.remaining_quantity_cc = quantity_cc
            if rec.status in _TERMINAL_STATUSES:
                # Live exposure persists past a terminal evaluation — reopen
                # into REEVALUATING so the position keeps an explicit owner
                # rather than silently drifting.
                rec.status = ResidualStatus.REEVALUATING.value
                rec.history.append(
                    {"at": now, "event": "reopened", "reason": "live_exposure"}
                )
            self._persist_locked()
            return rec

    def may_attempt_degraded(self, rec: ResidualRecord) -> Tuple[bool, str]:
        """Idempotency + attempt budget gate for the degraded IOC."""
        if rec.status in (ResidualStatus.SETTLED, ResidualStatus.CLOSED):
            return False, "residual_closed"
        if rec.status == ResidualStatus.DEGRADED_EXIT_SUBMITTED:
            return False, "degraded_already_submitted"
        if rec.degraded_attempt_number >= DEGRADED_MAX_ATTEMPTS:
            return False, "degraded_attempt_budget_exhausted"
        return True, "ok"

    def transition(
        self,
        rec: ResidualRecord,
        status: ResidualStatus,
        *,
        reason: str = "",
        **fields: Any,
    ) -> ResidualRecord:
        with self._lock:
            now = time.time()
            rec.status = status.value
            rec.decision_reason = reason
            rec.last_evaluated_at = now
            for k, v in fields.items():
                if hasattr(rec, k):
                    setattr(rec, k, v)
            rec.history.append(
                {"at": now, "event": status.value, "reason": reason}
            )
            self._persist_locked()
            return rec

    def record_degraded_submission(
        self,
        rec: ResidualRecord,
        *,
        client_order_id: str,
        limit_cents: int,
    ) -> ResidualRecord:
        with self._lock:
            rec.degraded_attempt_number += 1
            rec.degraded_client_order_ids.append(client_order_id)
        return self.transition(
            rec,
            ResidualStatus.DEGRADED_EXIT_SUBMITTED,
            reason="degraded_ioc_submitted",
            selected_degraded_limit_cents=limit_cents,
        )


_tracker: Optional[ResidualExitTracker] = None
_tracker_lock = threading.Lock()


def get_residual_exit_tracker(path: Optional[Path] = None) -> ResidualExitTracker:
    global _tracker
    with _tracker_lock:
        if _tracker is None or path is not None:
            _tracker = ResidualExitTracker(path)
        return _tracker


def reset_residual_exit_tracker_for_tests() -> None:
    global _tracker
    with _tracker_lock:
        _tracker = None
