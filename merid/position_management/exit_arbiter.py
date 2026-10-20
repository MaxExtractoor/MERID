"""Position-owned exit arbiter — one decision, one attempt, per generation.

This is the single point where competing exit proposals (profit lock,
trailing profit, model exit, authorized emergency) are reduced to **one**
approved exit attempt per position generation.  Producers propose; the
arbiter arbitrates; the enforcing firewall re-validates; the router
transmits only approval-bound orders.

Inputs per arbitration call:

- current position generation + remaining quantity
- an *executable* book view for the held side (liquidation proceeds)
- the persisted generation-scoped trail state (high-watermark + lock)
- zero or more ``ExitProposal`` records
- the current ``ExitAttempt`` state for the generation

Output (``ArbiterResult``):

- one selected proposal (or none), its effective limit/qty
- the four economics kept distinct:
    ``trigger_value`` (what the proposal asked for),
    ``executable_value`` (what the book can actually pay now),
    ``min_acceptable`` (the floor / emergency bound),
    ``submitted_limit`` (what the order will carry)
- an explicit ``exception`` record when an authorized emergency overrode
  the floor
- one ``ExitAttempt`` in ``SUBMITTING`` (or an explanation of why nothing
  may be submitted)
- per-proposal reasons for every proposal not selected

Order-attempt lifecycle (tracked separately from policy history)::

    IDLE ──select──> SUBMITTING ──ack──> WORKING_OR_PARTIALLY_FILLED
                        │                        │
                        ├─lost ack──> ACK_UNKNOWN │
                        │                        ├─fill all──> FLAT
                        └─reconcile──> RECONCILING <─┘
                                          │
                       alive ──> WORKING_OR_PARTIALLY_FILLED
                       dead  ──> RETRY_ELIGIBLE ──next decision──> SUBMITTING
                       filled ──> FLAT

"Confirmed dead" (``ReconcileEvidence``) contract
-------------------------------------------------

``ACK_UNKNOWN`` / ``RECONCILING`` attempts are only released to
``RETRY_ELIGIBLE`` on *positive* evidence:

- exchange order lookup (by order_id, or orders list filtered by
  ``client_order_id``) returns a **terminal** status with ``filled==0``
  → confirmed dead, retry permitted.
- terminal with ``0 < filled < qty`` → apply fills, residual may
  re-arbitrate.
- terminal with ``filled >= qty`` → FLAT (after ledger/position
  reconciliation).
- order found **not terminal** → still working; no replacement.
- order not found / lookup inconclusive → **still unresolved**, no
  replacement.  A timeout, an empty cache, or a failed lookup is never
  proof that an order did not execute.
- exception: an attempt that never received a ``client_order_id`` cannot
  have reached the wire (identity binds before serialization) —
  ``evidence_source="local_no_transmit"`` is the only not-found proof.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Order-attempt lifecycle
# ---------------------------------------------------------------------------

class AttemptState(str, Enum):
    IDLE = "IDLE"
    SUBMITTING = "SUBMITTING"
    ACK_UNKNOWN = "ACK_UNKNOWN"
    WORKING_OR_PARTIALLY_FILLED = "WORKING_OR_PARTIALLY_FILLED"
    RECONCILING = "RECONCILING"
    RETRY_ELIGIBLE = "RETRY_ELIGIBLE"
    FLAT = "FLAT"


# States in which the exchange may still hold or have filled the order — a
# replacement attempt is forbidden until reconciliation proves it dead.
_UNRESOLVED_STATES = frozenset({
    AttemptState.SUBMITTING,
    AttemptState.ACK_UNKNOWN,
    AttemptState.WORKING_OR_PARTIALLY_FILLED,
    AttemptState.RECONCILING,
})

# States that require an order-status observation before any replacement.
_MUST_RECONCILE_STATES = frozenset({
    AttemptState.ACK_UNKNOWN,
    AttemptState.RECONCILING,
    AttemptState.WORKING_OR_PARTIALLY_FILLED,
})

# A SUBMITTING attempt is legitimately transient — the route call is
# in-flight.  If it outlives the route timeout without post_route_update
# landing (timeout/exception paths that returned early, or a wedged route
# coroutine), the submission outcome is unknown and must be reconciled
# exactly like a lost ack.  Default 30s > MERID_EXIT_ROUTE_TIMEOUT_S (20s)
# so an in-flight call is never disturbed; override via env only with a
# value above the route timeout.
def _submitting_stale_s() -> float:
    try:
        return float(os.environ.get("MERID_EXIT_SUBMITTING_STALE_S", "30"))
    except Exception:
        return 30.0


class ProposalKind(str, Enum):
    PROFIT_LOCK = "profit_lock"
    TRAILING_PROFIT = "trailing_profit"
    MODEL_EXIT = "model_exit"
    EMERGENCY = "emergency"


# Ordinary kinds a denied emergency may *explicitly* fall back to (the
# fallback is itself a valid ordinary policy, not a silent conversion).
_ORDINARY_FALLBACK_KINDS = frozenset({
    ProposalKind.PROFIT_LOCK.value,
    ProposalKind.TRAILING_PROFIT.value,
    ProposalKind.MODEL_EXIT.value,
})


# ---------------------------------------------------------------------------
# Proposals, evidence, decisions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExitProposal:
    """A producer's exit request.

    ``limit_cents`` is the *trigger value*: the held-side sell limit the
    producer wants (for emergencies, the minimum acceptable price — the
    worst fill they will accept, not a request for that price).
    ``producer_token`` is provenance from the shared authorization
    registry; ``fallback_kind`` is the only way a denied emergency may be
    re-evaluated as an ordinary proposal (an explicit, separately valid
    ordinary justification — without it a failed emergency is rejected).
    """

    kind: str                       # ProposalKind value
    proposal_id: str
    limit_cents: int                # trigger value
    qty_cc: int
    reason: str
    authorization_source: Optional[str] = None
    emergency_type: Optional[str] = None
    position_generation_id: Optional[str] = None
    producer_token: Optional[Any] = None
    producer_issuer: Optional[str] = None  # registered producing module
    fallback_kind: Optional[str] = None  # ordinary justification if denied
    source_ts: float = 0.0


@dataclass(frozen=True)
class ReconcileEvidence:
    """What the exchange actually reported about an attempt's order.

    ``order_found=False`` is never proof of death: the lookup may have
    failed or the order may never have transmitted.  ``source`` records
    how the order was located: ``order_id`` / ``client_order_id`` /
    ``local_no_transmit`` (attempt never had a coid — provably not sent).
    """

    order_found: bool
    terminal: bool                # venue-terminal status (filled/canceled)
    filled_cc: int = 0
    source: str = "order_id"      # "order_id"|"client_order_id"|"local_no_transmit"|"none"


@dataclass
class ExitAttempt:
    """One approved order-attempt.  Kept durable so a restart reconciles it
    rather than duplicating it.  ``fill_ids`` dedupe fill delivery."""

    attempt_id: str
    position_key: str
    generation_id: str
    state: AttemptState
    proposal_kind: str
    proposal_id: str
    limit_cents: int
    qty_cc: int
    filled_cc: int = 0
    exception: Optional[str] = None
    client_order_id: Optional[str] = None
    order_id: Optional[str] = None
    decision_id: Optional[str] = None
    created_ts: float = 0.0
    updated_ts: float = 0.0
    history: List[Dict[str, Any]] = field(default_factory=list)
    fill_ids: List[str] = field(default_factory=list)

    def transition(self, to: AttemptState, note: str) -> None:
        self.history.append({
            "ts": time.time(), "from": self.state.value,
            "to": to.value, "note": note,
        })
        self.state = to
        self.updated_ts = time.time()

    def to_dict(self) -> Dict[str, Any]:
        d = dict(self.__dict__)
        d["state"] = self.state.value
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExitAttempt":
        d = dict(d)
        d["state"] = AttemptState(d["state"])
        d.setdefault("history", [])
        d.setdefault("fill_ids", [])
        return cls(**d)


@dataclass
class ArbiterResult:
    status: str                      # "submitted"|"held"|"held_unmarketable"|
                                     # "in_flight"|"reconcile_required"|
                                     # "flat"|"rejected"
    floor_cents: int                 # applicable minimum-proceeds floor
    floor_source: str                # "breakeven"|"trail_lock"|"ratcheted"
    high_watermark_cents: Optional[int] = None
    selected: Optional[ExitProposal] = None
    # The four economics, kept distinct — never conflate request with book:
    trigger_value_cents: Optional[int] = None     # proposal's ask
    executable_value_cents: Optional[int] = None  # book can pay now
    min_acceptable_cents: Optional[int] = None    # floor / emergency bound
    submitted_limit_cents: Optional[int] = None   # what the order carries
    effective_qty_cc: Optional[int] = None
    exception: Optional[str] = None  # e.g. "emergency:POSITION_LOSS_BUDGET"
    attempt: Optional[ExitAttempt] = None
    not_selected: List[Tuple[str, str]] = field(default_factory=list)
    # Emergency proposals denied authorization and rejected (or explicitly
    # re-evaluated as ordinary via fallback_kind).
    denied_exceptions: List[Tuple[str, str]] = field(default_factory=list)
    book_note: Optional[str] = None


@dataclass(frozen=True)
class ExitBook:
    """Executable book view for liquidating the held side.

    ``held_side`` is the outcome this book sells ("yes"|"no");
    ``liquidation_cents`` is the achievable proceeds per contract for the
    exit qty (VWAP over available depth) — the *executable* value, which
    may differ from any proposal's trigger value."""

    held_side: str
    liquidation_cents: int
    qty_cc: int
    age_ms: int


# ---------------------------------------------------------------------------
# Durable attempt store
# ---------------------------------------------------------------------------

def _default_attempts_path() -> Path:
    env = os.getenv("MERID_EXIT_ATTEMPTS_PATH", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "data" / "exit_attempts.json"


class ExitAttemptStore:
    """JSON-backed attempt ledger keyed by ``{market_id}|{generation_id}``.

    On load, every unresolved attempt is downgraded to ``RECONCILING`` —
    restart semantics are "reconcile, don't resubmit".  Writes are atomic
    (tmp + replace) under a lock."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or _default_attempts_path()
        self._lock = threading.Lock()
        self._positions: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._positions = {
                        str(k): v for k, v in
                        data.get("positions", {}).items()
                        if isinstance(v, dict)
                    }
        except Exception as exc:
            logger.critical(
                "[EXIT-ATTEMPTS] durable attempt file unreadable: %s (%s) — "
                "attempt states UNKNOWN; entries stay halted",
                self._path, exc,
            )
            self._positions = {}
            try:
                from merid.observability.live_runtime_state import (
                    get_live_runtime_state,
                )
                get_live_runtime_state().halt_entries(
                    "exit_attempt_store_corrupt", ["EXIT_ATTEMPTS_CORRUPT"],
                )
            except Exception:
                pass
            return
        # Restart rule: an unresolved attempt after load is "reconcile",
        # never "resubmit".
        for key, entry in self._positions.items():
            active = entry.get("active")
            if not isinstance(active, dict):
                continue
            try:
                st = AttemptState(active.get("state", "IDLE"))
            except ValueError:
                st = AttemptState.RECONCILING
            if st in _UNRESOLVED_STATES and st != AttemptState.RECONCILING:
                hist = active.setdefault("history", [])
                hist.append({
                    "ts": time.time(), "from": st.value,
                    "to": AttemptState.RECONCILING.value,
                    "note": "restart: unresolved attempt must reconcile, not resubmit",
                })
                active["state"] = AttemptState.RECONCILING.value
                active["updated_ts"] = time.time()
                self._flush()

    # Closed attempts retained per position in the JSON ledger.  The file is
    # rewritten on every attempt transition, so unbounded closed history
    # makes each flush slower forever (observed: 737KB synchronous write on
    # the event loop per transition during the 2026-10-20 wedge — a
    # direct drain-lag contributor).  The SQL ``order_attempts`` store keeps
    # the full durable lifecycle; this ledger only needs recent depth for
    # restart reconcile and forensic review.
    _MAX_CLOSED_PER_POSITION = 50

    def _flush(self) -> None:
        try:
            with self._lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._path.with_suffix(".tmp")
                tmp.write_text(json.dumps(
                    {"schema_version": 1, "updated_at": time.time(),
                     "positions": self._positions},
                    separators=(",", ":"), default=str), encoding="utf-8")
                os.replace(tmp, self._path)
        except Exception as exc:
            logger.warning("[EXIT-ATTEMPTS] save failed: %s", exc)

    def get_active(self, position_key: str) -> Optional[ExitAttempt]:
        with self._lock:
            rec = self._positions.get(position_key)
            if not rec or not isinstance(rec.get("active"), dict):
                return None
            return ExitAttempt.from_dict(rec["active"])

    def next_attempt_seq(self, position_key: str) -> int:
        rec = self._positions.get(position_key)
        if not rec:
            return 1
        return int(rec.get("attempt_seq", 0)) + 1

    def save_active(self, attempt: ExitAttempt) -> None:
        """Atomically record the active attempt.  Refuses to overwrite a
        different attempt that is still unresolved — a replacement must
        first be reconciled through ``resolve_reconcile``."""
        with self._lock:
            rec = self._positions.setdefault(
                attempt.position_key,
                {"attempt_seq": 0, "active": None, "closed": []},
            )
            prev_active = rec.get("active")
            if prev_active and prev_active.get("attempt_id") != attempt.attempt_id \
                    and prev_active.get("state") not in (
                        AttemptState.FLAT.value, AttemptState.RETRY_ELIGIBLE.value,
                    ):
                raise RuntimeError(
                    f"[EXIT-ATTEMPTS] refusing to overwrite unresolved "
                    f"attempt {prev_active.get('attempt_id')} state="
                    f"{prev_active.get('state')}"
                )
            if prev_active and prev_active.get("attempt_id") != attempt.attempt_id:
                rec["closed"].append(prev_active)
                if len(rec["closed"]) > self._MAX_CLOSED_PER_POSITION:
                    del rec["closed"][:-self._MAX_CLOSED_PER_POSITION]
            try:
                seq = int(attempt.attempt_id.rsplit("#", 1)[-1])
                rec["attempt_seq"] = max(int(rec.get("attempt_seq", 0)), seq)
            except (ValueError, IndexError):
                pass
            rec["active"] = attempt.to_dict()
        self._flush()

    def clear_active(self, attempt: ExitAttempt) -> None:
        """Move a terminal attempt to history."""
        with self._lock:
            rec = self._positions.get(attempt.position_key)
            if not rec:
                return
            if rec.get("active", {}).get("attempt_id") == attempt.attempt_id:
                rec["closed"].append(rec["active"])
                if len(rec["closed"]) > self._MAX_CLOSED_PER_POSITION:
                    del rec["closed"][:-self._MAX_CLOSED_PER_POSITION]
                rec["active"] = None
        self._flush()


# ---------------------------------------------------------------------------
# Arbiter
# ---------------------------------------------------------------------------

class ExitArbiter:
    """One decision, one attempt, per position generation.

    ``_arb_lock`` serializes selection + attempt reservation: two
    concurrent calls can never both observe ``IDLE`` and mint parallel
    attempts for one generation."""

    MAX_BOOK_AGE_MS = 5_000
    MAX_PRICE_CENTS = 99

    def __init__(
        self,
        state_store: Optional[Any] = None,
        attempt_store: Optional[ExitAttemptStore] = None,
    ) -> None:
        from merid.position_management.position_exit_state import (
            PositionExitStateStore,
        )
        self._state_store = state_store or PositionExitStateStore()
        self._attempts = attempt_store or ExitAttemptStore()
        self._arb_lock = threading.RLock()

    @property
    def attempt_store(self) -> "ExitAttemptStore":
        return self._attempts

    # -- emergency authorization (defense in depth; the firewall re-checks
    #    the identical policy tables at submit time) ----------------------

    @staticmethod
    def _emergency_authorized(
        proposal: ExitProposal, generation_id: str,
    ) -> Optional[str]:
        """Return None when the emergency tuple is authorized for loss-taking,
        else a denial reason.  Delegates to the shared versioned policy."""
        from merid.event_venues.kalshi.exit_authorization import (
            authorize_emergency,
        )
        return authorize_emergency(
            emergency_type=proposal.emergency_type,
            authorization_source=proposal.authorization_source,
            position_generation_id=proposal.position_generation_id,
            expected_generation_id=generation_id,
            producer_issuer=proposal.producer_issuer,
            producer_token=proposal.producer_token,
        )

    # -- floor -----------------------------------------------------------

    def _persisted_floor(
        self, market_id: str, generation_id: str, held_side: str,
    ) -> Tuple[Optional[int], Optional[int], Optional[int]]:
        """(locked_floor, high_watermark, giveback) for the live generation."""
        rec = self._state_store.find_record(
            market_id, generation_id,
            held_outcome=held_side, require_generation=True,
        )
        if not rec:
            return None, None, None
        fl = rec.get("ratchet_floor_price_cents")
        hw = rec.get("high_watermark_cents")
        gb = rec.get("trail_giveback_cents")
        return (int(fl) if fl is not None else None,
                int(hw) if hw is not None else None,
                int(gb) if gb is not None else None)

    def _observe_executable(
        self,
        market_id: str,
        generation_id: str,
        held_side: str,
        book: Optional[ExitBook],
    ) -> Tuple[Optional[int], str]:
        """Update the generation's high-watermark from a *fresh, same-side,
        non-empty* executable book.  Returns (exec_liquidation, note).

        Observing the watermark is distinct from applying the giveback
        formula: the watermark is monotone (never decreases); the floor is
        ``watermark - trail_giveback_cents`` and is applied separately by
        the caller."""
        if book is None:
            return None, "no_book"
        if book.held_side != held_side:
            return None, f"book_side_mismatch:{book.held_side}!={held_side}"
        if book.age_ms > self.MAX_BOOK_AGE_MS:
            return None, f"book_stale:{book.age_ms}ms"
        if book.qty_cc <= 0 or book.liquidation_cents <= 0:
            return None, "book_empty"
        self._state_store.record_watermark(
            market_id, generation_id, held_side, book.liquidation_cents,
        )
        return book.liquidation_cents, "observed"

    # -- arbitration -----------------------------------------------------

    def arbitrate(
        self,
        *,
        market_id: str,
        generation_id: str,
        held_side: str,
        remaining_cc: int,
        breakeven_floor_cents: int = 0,
        trail_giveback_cents: Optional[int] = None,
        book: Optional[ExitBook] = None,
        proposals: List[ExitProposal] = (),
    ) -> ArbiterResult:
        """Reduce competing proposals to (at most) one approved attempt.

        ``breakeven_floor_cents`` is the fee-adjusted no-loss floor;
        ``trail_giveback_cents`` is the configured giveback applied to the
        generation's high-watermark: ``floor = max(breakeven,
        watermark - giveback)``.  When the caller does not restate it
        (``None``) the persisted generation giveback is reused — a caller
        cannot accidentally tighten the lock by omitting the parameter.
        The whole call is atomic — selection and attempt reservation
        cannot interleave with another arbitration."""
        with self._arb_lock:
            return self._arbitrate_locked(
                market_id=market_id, generation_id=generation_id,
                held_side=held_side, remaining_cc=remaining_cc,
                breakeven_floor_cents=breakeven_floor_cents,
                trail_giveback_cents=trail_giveback_cents,
                book=book, proposals=proposals,
            )

    def _arbitrate_locked(self, *, market_id, generation_id, held_side,
                          remaining_cc, breakeven_floor_cents,
                          trail_giveback_cents, book, proposals) -> ArbiterResult:
        position_key = f"{market_id}|{generation_id}"
        held_side = str(held_side).lower()

        # 1) Executable book -> high-watermark (monotone observation);
        #    floor = max(breakeven, watermark - giveback) [giveback formula
        #    applied here, distinct from the watermark update itself].
        exec_liq, book_note = self._observe_executable(
            market_id, generation_id, held_side, book,
        )
        persisted_floor, persisted_hw, persisted_giveback = (
            self._persisted_floor(market_id, generation_id, held_side)
        )
        # Giveback is generation policy: an explicit value is persisted;
        # a caller that doesn't restate it reuses the persisted value.
        if trail_giveback_cents is not None:
            giveback = int(trail_giveback_cents)
            if persisted_giveback != giveback:
                self._state_store.record_giveback(
                    market_id, generation_id, held_side, giveback,
                )
        else:
            giveback = int(persisted_giveback or 0)
        watermark = max(
            [v for v in (persisted_hw, exec_liq) if v is not None],
            default=None,
        )
        trail_floor = (
            (watermark - giveback) if watermark is not None
            else None
        )
        floor = max(
            [v for v in (int(breakeven_floor_cents or 0),
                         persisted_floor, trail_floor) if v is not None],
            default=0,
        )
        floor_source = (
            "ratcheted" if (trail_floor is not None and
                            trail_floor > (breakeven_floor_cents or 0))
            else ("trail_lock" if (persisted_floor or 0) >
                  (breakeven_floor_cents or 0) else "breakeven")
        )
        # Persist the computed floor (monotone — never decreases).
        if floor > (persisted_floor or 0):
            self._state_store.record_floor_ratchet(
                market_id, generation_id, held_side, floor,
            )

        # 2) Position flat -> attempt is done.
        attempt = self._attempts.get_active(position_key)
        if remaining_cc <= 0:
            if attempt is not None and attempt.state != AttemptState.FLAT:
                attempt.transition(AttemptState.FLAT, "position_flat")
                self._attempts.clear_active(attempt)
            return ArbiterResult(
                status="flat", floor_cents=floor, floor_source=floor_source,
                high_watermark_cents=watermark,
                executable_value_cents=exec_liq, book_note=book_note,
                not_selected=[(p.proposal_id, "position_flat")
                              for p in proposals],
            )

        # 3) Unresolved attempt gate — reconcile before replacement.
        if attempt is not None and attempt.state in _UNRESOLVED_STATES:
            _stale_submit = (
                attempt.state == AttemptState.SUBMITTING
                and time.time() - (
                    attempt.updated_ts or attempt.created_ts or 0.0)
                > _submitting_stale_s()
            )
            status = ("reconcile_required"
                      if attempt.state in _MUST_RECONCILE_STATES
                         or _stale_submit
                      else "in_flight")
            return ArbiterResult(
                status=status, floor_cents=floor, floor_source=floor_source,
                high_watermark_cents=watermark,
                executable_value_cents=exec_liq,
                attempt=attempt, book_note=book_note,
                not_selected=[
                    (p.proposal_id, f"attempt_in_flight:{attempt.state.value}")
                    for p in proposals
                ],
            )

        # 4) Validate proposals.  ``marketable`` = the trigger limit can
        #    fill on the current book (sell limit <= executable bid value).
        book_liq = exec_liq  # None when book unusable
        candidates: List[Tuple[ExitProposal, int, int, Optional[str], bool]] = []
        not_selected: List[Tuple[str, str]] = []
        denied: List[Tuple[str, str]] = []
        for p in proposals:
            eff_qty = min(int(p.qty_cc), remaining_cc)
            if eff_qty <= 0:
                not_selected.append((p.proposal_id, "zero_qty"))
                continue
            exception = None
            eff_limit = int(p.limit_cents)
            kind = p.kind
            if p.kind == ProposalKind.EMERGENCY.value:
                denial = self._emergency_authorized(p, generation_id)
                if denial is None:
                    exception = f"emergency:{(p.emergency_type or '').upper()}"
                    # The bound is the minimum acceptable fill, not a price
                    # request — submitted at the bound; the book decides the
                    # actual fill (price improvement upward).
                else:
                    denied.append((p.proposal_id, denial))
                    fb = (p.fallback_kind or "").strip()
                    if fb not in _ORDINARY_FALLBACK_KINDS:
                        # No independent ordinary justification — a failed
                        # emergency cannot silently liquidate at the floor.
                        not_selected.append(
                            (p.proposal_id,
                             f"emergency_denied:{denial}"))
                        continue
                    kind = fb
                    eff_limit = max(int(p.limit_cents), floor)
            else:
                eff_limit = max(int(p.limit_cents), floor)
            if eff_limit > self.MAX_PRICE_CENTS:
                not_selected.append(
                    (p.proposal_id, f"floor_unattainable:{eff_limit}c"))
                continue
            marketable = (book_liq is None) or (eff_limit <= book_liq)
            candidates.append((p, eff_limit, eff_qty, exception, marketable))

        if not candidates:
            return ArbiterResult(
                status="rejected", floor_cents=floor, floor_source=floor_source,
                high_watermark_cents=watermark,
                executable_value_cents=book_liq,
                not_selected=not_selected, denied_exceptions=denied,
                book_note=book_note,
            )

        # 5) One winner.  Marketability is evaluated on the CURRENT book —
        #    an unmarketable limit (limit > executable value) cannot beat
        #    an executable exit: it is a request for a price nobody pays.
        marketable = [c for c in candidates if c[4]]
        unmarketable = [c for c in candidates if not c[4]]
        for c in unmarketable:
            not_selected.append(
                (c[0].proposal_id,
                 f"unmarketable:{c[1]}c>book:{book_liq}c"))
        if not marketable and book_liq is not None:
            # Every proposal wants a price nobody currently pays.  Submitting
            # an unmarketable IOC just cancels — hold and record why.
            not_selected.sort(key=lambda t: t[0])
            return ArbiterResult(
                status="held_unmarketable", floor_cents=floor,
                floor_source=floor_source,
                high_watermark_cents=watermark,
                executable_value_cents=book_liq,
                not_selected=not_selected, denied_exceptions=denied,
                book_note=book_note,
            )
        pool = marketable if marketable else unmarketable

        authorized = [c for c in pool if c[3] is not None]
        if authorized:
            # Among authorized emergencies prefer the tightest bound (max
            # proceeds) then coverage; ties by proposal_id for determinism.
            winner = min(authorized,
                         key=lambda c: (-c[1], -c[2], c[0].proposal_id))
        else:
            # Best locked proceeds among executable proposals: highest
            # submitted limit, then kind priority, then id.  All fill at
            # the same book value — the limit is downside protection, and
            # the highest marketable limit is the most protective one.
            winner = min(
                pool,
                key=lambda c: (
                    -c[1], _kind_priority(c[0].kind), c[0].proposal_id,
                ),
            )
        for c in pool:
            if c is not winner:
                reason = ("lost_to_authorized_emergency" if authorized
                          else f"lower_limit:{c[1]}<{winner[1]}"
                          if c[1] < winner[1] else "lower_priority")
                not_selected.append((c[0].proposal_id, reason))
        not_selected.sort(key=lambda t: t[0])

        prop, eff_limit, eff_qty, exception, _m = winner
        min_acceptable = eff_limit if exception is None else int(
            prop.limit_cents)
        seq = self._attempts.next_attempt_seq(position_key)
        attempt = ExitAttempt(
            attempt_id=f"{position_key}#{seq}",
            position_key=position_key,
            generation_id=generation_id,
            state=AttemptState.SUBMITTING,
            proposal_kind=prop.kind,
            proposal_id=prop.proposal_id,
            limit_cents=eff_limit,
            qty_cc=eff_qty,
            exception=exception,
            created_ts=time.time(),
            updated_ts=time.time(),
            history=[{
                "ts": time.time(), "from": AttemptState.IDLE.value,
                "to": AttemptState.SUBMITTING.value,
                "note": f"selected:{prop.proposal_id} kind={prop.kind}",
            }],
        )
        self._attempts.save_active(attempt)
        return ArbiterResult(
            status="submitted", floor_cents=floor, floor_source=floor_source,
            high_watermark_cents=watermark,
            selected=prop,
            trigger_value_cents=int(prop.limit_cents),
            executable_value_cents=book_liq,
            min_acceptable_cents=min_acceptable,
            submitted_limit_cents=eff_limit,
            effective_qty_cc=eff_qty, exception=exception, attempt=attempt,
            not_selected=not_selected, denied_exceptions=denied,
            book_note=book_note,
        )

    # -- attempt lifecycle -----------------------------------------------

    def bind_attempt_identity(
        self, position_key: str, client_order_id: str,
        decision_id: Optional[str] = None,
        order_id: Optional[str] = None,
    ) -> Optional[ExitAttempt]:
        a = self._attempts.get_active(position_key)
        if a is None:
            return None
        if client_order_id:
            a.client_order_id = client_order_id
        if decision_id:
            a.decision_id = decision_id
        if order_id:
            a.order_id = order_id
        a.updated_ts = time.time()
        self._attempts.save_active(a)
        return a

    def mark_acked(self, position_key: str) -> Optional[ExitAttempt]:
        a = self._attempts.get_active(position_key)
        if a is None or a.state not in (
            AttemptState.SUBMITTING, AttemptState.ACK_UNKNOWN,
            AttemptState.RECONCILING,
        ):
            return a
        a.transition(AttemptState.WORKING_OR_PARTIALLY_FILLED, "order_acked")
        self._attempts.save_active(a)
        return a

    def mark_ack_unknown(self, position_key: str, note: str = "lost_ack") -> Optional[ExitAttempt]:
        a = self._attempts.get_active(position_key)
        if a is None or a.state != AttemptState.SUBMITTING:
            return a
        a.transition(AttemptState.ACK_UNKNOWN, note)
        self._attempts.save_active(a)
        return a

    def begin_reconcile(self, position_key: str) -> Optional[ExitAttempt]:
        a = self._attempts.get_active(position_key)
        if a is None or a.state not in _UNRESOLVED_STATES:
            return a
        a.transition(AttemptState.RECONCILING, "reconcile_begin")
        self._attempts.save_active(a)
        return a

    def resolve_reconcile(
        self, position_key: str, evidence: ReconcileEvidence,
    ) -> Optional[ExitAttempt]:
        """Reconciliation outcome per the confirmed-dead contract.

        - not found / inconclusive → stays RECONCILING (unknown ≠ dead)
        - found, not terminal → WORKING_OR_PARTIALLY_FILLED
        - found, terminal, filled>=qty → FLAT (after ledger/position recon)
        - found, terminal, 0<filled<qty → fills applied → RETRY_ELIGIBLE
        - found, terminal, filled==0 → confirmed dead → RETRY_ELIGIBLE
        - ``local_no_transmit`` (attempt never had a coid) → RETRY_ELIGIBLE
        """
        a = self._attempts.get_active(position_key)
        if a is None or a.state not in _UNRESOLVED_STATES:
            return a
        if not evidence.order_found:
            if evidence.source == "local_no_transmit" or (
                a.client_order_id is None and a.order_id is None
            ):
                a.transition(
                    AttemptState.RETRY_ELIGIBLE,
                    "reconciled:never_transmitted",
                )
                self._attempts.save_active(a)
            else:
                a.updated_ts = time.time()
                a.history.append({
                    "ts": time.time(), "from": a.state.value,
                    "to": a.state.value,
                    "note": "reconciled:inconclusive_lookup_still_unresolved",
                })
                self._attempts.save_active(a)
            return a
        a.filled_cc = max(a.filled_cc, int(evidence.filled_cc))
        if not evidence.terminal:
            a.transition(
                AttemptState.WORKING_OR_PARTIALLY_FILLED,
                "reconciled:still_working",
            )
            self._attempts.save_active(a)
        elif a.filled_cc >= a.qty_cc:
            a.transition(AttemptState.FLAT, "reconciled:filled")
            self._attempts.clear_active(a)
        else:
            note = (
                f"reconciled:order_dead_unfilled:{evidence.source}"
                if a.filled_cc == 0 else
                f"reconciled:terminal_partial:{a.filled_cc}/{a.qty_cc}:{evidence.source}")
            a.transition(AttemptState.RETRY_ELIGIBLE, note)
            self._attempts.save_active(a)
        return a

    def record_fill(
        self, position_key: str, fill_cc: int, fill_id: Optional[str] = None,
    ) -> Optional[ExitAttempt]:
        """Apply a fill to the active attempt (idempotent by ``fill_id``).
        Partial fills preserve protection for the residual — the floor
        lock is untouched and the attempt stays working until covered."""
        a = self._attempts.get_active(position_key)
        if a is None:
            return None
        if fill_id is not None:
            if fill_id in a.fill_ids:
                a.history.append({
                    "ts": time.time(), "from": a.state.value,
                    "to": a.state.value, "note": f"dup_fill_ignored:{fill_id}",
                })
                self._attempts.save_active(a)
                return a
            a.fill_ids.append(fill_id)
        a.filled_cc += int(fill_cc)
        if a.filled_cc >= a.qty_cc:
            a.transition(AttemptState.FLAT, f"filled:{a.filled_cc}/{a.qty_cc}")
            self._attempts.clear_active(a)
        else:
            if a.state == AttemptState.SUBMITTING:
                a.transition(
                    AttemptState.WORKING_OR_PARTIALLY_FILLED,
                    f"partial_fill:{a.filled_cc}/{a.qty_cc}",
                )
            else:
                a.updated_ts = time.time()
                a.history.append({
                    "ts": time.time(), "from": a.state.value,
                    "to": a.state.value,
                    "note": f"partial_fill:{a.filled_cc}/{a.qty_cc}",
                })
            self._attempts.save_active(a)
        return a

    def mark_flat(self, position_key: str, note: str = "position_closed") -> None:
        a = self._attempts.get_active(position_key)
        if a is not None and a.state != AttemptState.FLAT:
            a.transition(AttemptState.FLAT, note)
            self._attempts.clear_active(a)

    def positions_requiring_reconcile(self) -> List[str]:
        now = time.time()
        stale_s = _submitting_stale_s()
        keys: List[str] = []
        for key in self._attempts._positions:
            a = self._attempts.get_active(key)
            if a is None:
                continue
            if a.state in _MUST_RECONCILE_STATES:
                keys.append(key)
            elif (
                a.state == AttemptState.SUBMITTING
                and now - (a.updated_ts or a.created_ts or now) > stale_s
            ):
                # Wedged submission: post_route_update never landed.  Same
                # contract as a lost ack — reconcile by coid/order_id.
                keys.append(key)
        return keys

    def validate_attempt_token(
        self, position_key: str, attempt_id: Optional[str],
    ) -> Optional[ExitAttempt]:
        """Router-side gate: an exit intent may only ride a live, approved
        attempt for this generation.  Returns the attempt or None."""
        if not attempt_id:
            return None
        a = self._attempts.get_active(position_key)
        if a is None or a.attempt_id != attempt_id:
            return None
        if a.state != AttemptState.SUBMITTING:
            return None
        return a


_ARBITER: Optional["ExitArbiter"] = None
_ARBITER_LOCK = threading.Lock()


def get_exit_arbiter() -> ExitArbiter:
    global _ARBITER
    with _ARBITER_LOCK:
        if _ARBITER is None:
            _ARBITER = ExitArbiter()
        return _ARBITER


def _kind_priority(kind: str) -> int:
    return {
        ProposalKind.PROFIT_LOCK.value: 0,
        ProposalKind.TRAILING_PROFIT.value: 1,
        ProposalKind.MODEL_EXIT.value: 2,
        ProposalKind.EMERGENCY.value: 3,
    }.get(kind, 9)
