"""Exit pipeline — the single bridge producers use to submit an exit.

Producer (monitor / stop candidate / hedge / manual)
    -> ``propose_exit`` (arbiter decides; one attempt minted)
    -> caller builds its OrderIntent and stamps ``exit_attempt_id``
    -> ``post_route_update`` (attempt lifecycle follows route outcome)

The router gate in ``route_order_async`` rejects any exit intent without
a live approved attempt, so this is not an optional convenience — it is
the only path to the wire for a position-reducing order.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, List, Optional

from merid.position_management.exit_arbiter import (
    ArbiterResult, AttemptState, ExitArbiter, ExitBook, ExitProposal,
    ProposalKind, get_exit_arbiter,
)

logger = logging.getLogger(__name__)

# Producer provenance — registered once here; a producer may only claim an
# authorization_source whose token it was issued.
_PRODUCER_TOKENS: dict = {}


def producer_token(issuer: str):
    """Fetch (register-once) the canonical producer token for a module."""
    tok = _PRODUCER_TOKENS.get(issuer)
    if tok is None:
        from merid.event_venues.kalshi.exit_authorization import (
            register_producer,
        )
        tok = register_producer(issuer)
        _PRODUCER_TOKENS[issuer] = tok
    return tok


# ---------------------------------------------------------------------------
# Context construction
# ---------------------------------------------------------------------------

@dataclass
class ExitContext:
    market_id: str
    generation_id: str
    held_side: str
    remaining_cc: int
    breakeven_floor_cents: int
    trail_giveback_cents: Optional[int] = None
    book: Optional[ExitBook] = None


def _generation_id_of(position: Any) -> Optional[str]:
    for attr in ("parent_entry_fill_id", "entry_fill_id",
                 "entry_intent_id", "client_order_id"):
        v = getattr(position, attr, None)
        if v:
            return str(v)
    return None


def _breakeven_floor_cents(position: Any) -> int:
    """Fee-adjusted no-loss floor for the held side (entry + round-trip
    fees).  Conservative fallback: entry price + 8c when the fee helper is
    unavailable."""
    entry = getattr(position, "entry_fill_price_cents", None) or getattr(
        position, "avg_entry_price_cents", None)
    if not entry:
        return 0
    try:
        from merid.event_venues.kalshi.fees import (
            min_profitable_exit_price_cents,
        )
        size = getattr(position, "size", None)
        floor = min_profitable_exit_price_cents(
            int(entry), size, gross_min_cents=0)
        if floor is not None:
            return int(floor)
    except Exception:
        pass
    return int(entry) + 8


def context_from_position(
    position: Any,
    *,
    snapshot: Optional[Any] = None,
    book: Optional[ExitBook] = None,
    remaining_cc: Optional[int] = None,
    generation_id: Optional[str] = None,
    trail_giveback_cents: Optional[int] = None,
) -> Optional[ExitContext]:
    """Build arbiter inputs from a Position (+ optional price snapshot).

    The book view is derived from ``snapshot.own_side_bid_cents`` —
    the executable bid the monitor already reprices exits to — with
    ``min_depth_own_side`` as available depth."""
    market_id = getattr(position, "market_id", None)
    side = getattr(position, "side", None)
    held = getattr(side, "value", side)
    if not market_id or not held:
        return None
    gen = generation_id or _generation_id_of(position)
    if not gen:
        return None
    if remaining_cc is None:
        try:
            remaining_cc = int(Decimal(str(getattr(position, "size", 0)))
                               * Decimal("100"))
        except Exception:
            return None
    if book is None and snapshot is not None:
        bid = getattr(snapshot, "own_side_bid_cents", None)
        if bid and 1 <= int(bid) <= 99:
            depth_cc = 0
            d = getattr(snapshot, "min_depth_own_side", None)
            if d is not None:
                try:
                    depth_cc = int(Decimal(str(d)) * Decimal("100"))
                except Exception:
                    depth_cc = 0
            if depth_cc <= 0:
                depth_cc = remaining_cc or 100  # single-level: assume qty
            book = ExitBook(
                held_side=str(held).lower(),
                liquidation_cents=int(bid),
                qty_cc=depth_cc,
                age_ms=int(getattr(snapshot, "book_age_ms", 0) or 0),
            )
    if book is None and snapshot is None:
        # Best-effort live book: same-side executable bid + age + depth from
        # the market-state store.  Unproven freshness is reported as stale
        # (never ratchets, never asserts marketability).
        try:
            from merid.event_venues.kalshi.market_state import (
                get_kalshi_market_state_store,
            )
            _st = get_kalshi_market_state_store()
            _state = (_st.get(market_id) if _st is not None
                      and hasattr(_st, "get") else None)
            if _state is not None:
                held_l = str(held).lower()
                _bid = getattr(
                    _state,
                    "best_bid_cents" if held_l == "yes" else "best_no_bid_cents",
                    None,
                )
                _age = None
                try:
                    from merid.position_management.position_monitor import (
                        _book_age_ms,
                    )
                    _age = _book_age_ms(_state)
                except Exception:
                    _age = None
                _depth = getattr(
                    _state,
                    "min_depth_yes" if held_l == "yes" else "min_depth_no",
                    0,
                ) or 0
                if _bid is not None and 1 <= int(_bid) <= 99:
                    try:
                        _dcc = int(Decimal(str(_depth)) * Decimal("100"))
                    except Exception:
                        _dcc = 0
                    book = ExitBook(
                        held_side=held_l,
                        liquidation_cents=int(_bid),
                        qty_cc=_dcc or int(remaining_cc or 100),
                        age_ms=(
                            int(_age) if _age is not None
                            else ExitArbiter.MAX_BOOK_AGE_MS + 1
                        ),
                    )
        except Exception:
            book = None
    if trail_giveback_cents is None:
        _tp_param = getattr(position, "trailing_param", None)
        if _tp_param is not None:
            try:
                trail_giveback_cents = max(1, int(round(float(_tp_param))))
            except Exception:
                trail_giveback_cents = None
        if trail_giveback_cents is None:
            try:
                import os as _os_ep
                trail_giveback_cents = max(
                    1,
                    int(_os_ep.environ.get("MERID_EXIT_PROFIT_SLIPPAGE_CENTS", "5")),
                )
            except Exception:
                trail_giveback_cents = 5
    return ExitContext(
        market_id=str(market_id),
        generation_id=str(gen),
        held_side=str(held).lower(),
        remaining_cc=int(remaining_cc or 0),
        breakeven_floor_cents=_breakeven_floor_cents(position),
        trail_giveback_cents=(
            int(trail_giveback_cents)
            if trail_giveback_cents is not None else None),
        book=book,
    )


# ---------------------------------------------------------------------------
# Proposal classification
# ---------------------------------------------------------------------------

_PROFIT_LOCK_REASONS = frozenset({
    "take_profit", "hard_profit_lock", "ratchet_trim", "scale_out",
    "auto_exit_99c", "extreme_profit", "dynamic_take_profit",
    "settlement_guard",
})
_TRAIL_REASONS = frozenset({"trail", "trailing_stop", "trailing_profit"})
_EMERGENCY_REASONS = frozenset({
    "hard_stop", "loss_cap", "risk", "manual", "position_monitor_manual",
    "market_expired", "expiry_liquidation", "stale_data",
    "position_mismatch", "emergency", "hard_risk", "operational_risk",
    "external_exit", "reconciliation", "reconcile",
})


def kind_for_reason(reason: Any, exit_class: Optional[str] = None) -> str:
    """Map a producer reason/classification onto ProposalKind."""
    r = str(getattr(reason, "value", reason) or "").lower()
    if (exit_class or "").strip().lower() == "emergency" \
            or r in _EMERGENCY_REASONS:
        return ProposalKind.EMERGENCY.value
    if r in _PROFIT_LOCK_REASONS:
        return ProposalKind.PROFIT_LOCK.value
    if r in _TRAIL_REASONS:
        return ProposalKind.TRAILING_PROFIT.value
    return ProposalKind.MODEL_EXIT.value


def proposal_from_intent(
    intent: Any,
    *,
    kind: Optional[str] = None,
    issuer: Optional[str] = None,
    fallback_kind: Optional[str] = None,
    proposal_id: Optional[str] = None,
) -> ExitProposal:
    """Translate an exit OrderIntent into an arbiter proposal.  The intent's
    structured authorization tuple is carried verbatim — classification,
    not privilege."""
    qty_cc = getattr(intent, "qty_cc", None)
    if qty_cc is None:
        cfp = getattr(intent, "count_fp", None)
        if cfp is not None:
            qty_cc = int(Decimal(str(cfp)) * Decimal("100"))
        else:
            qty_cc = int(Decimal(str(getattr(intent, "count", 0)))
                         * Decimal("100"))
    src = getattr(intent, "source", None) or getattr(
        intent, "agent_id", None)
    reason = getattr(intent, "exit_reason", None) or getattr(
        intent, "reason", None) or "exit"
    k = kind or kind_for_reason(
        reason, getattr(intent, "exit_class", None))
    # Classification only (never privilege): derive the emergency type from
    # the canonical reason map when the intent doesn't carry it — identical
    # to what normalize_order does downstream.  Authorization is decided
    # solely by the shared policy in the arbiter/firewall.
    etype = getattr(intent, "emergency_type", None)
    if etype is None and k == ProposalKind.EMERGENCY.value:
        try:
            from merid.event_venues.kalshi.order_intent_contract import (
                _REASON_TO_EMERGENCY_TYPE,
            )
            etype = _REASON_TO_EMERGENCY_TYPE.get(
                str(reason).lower().replace("exit_", ""))
            if etype is not None:
                intent.emergency_type = etype
        except Exception:
            pass
    producer_name = issuer or src
    return ExitProposal(
        kind=k,
        proposal_id=proposal_id or getattr(intent, "intent_id", None)
        or f"prop_{int(time.time() * 1000)}",
        limit_cents=int(getattr(intent, "price_cents", 0) or 0),
        qty_cc=int(qty_cc),
        reason=str(reason),
        authorization_source=(
            getattr(intent, "authorization_source", None) or src),
        emergency_type=etype,
        position_generation_id=getattr(
            intent, "position_generation_id", None),
        producer_issuer=producer_name,
        producer_token=(
            producer_token(producer_name) if producer_name else None),
        fallback_kind=fallback_kind,
    )


# ---------------------------------------------------------------------------
# Arbitrate + submit
# ---------------------------------------------------------------------------

@dataclass
class PreparedExit:
    approved: bool
    result: ArbiterResult
    denial: Optional[str] = None


def propose_exit(
    ctx: ExitContext,
    proposals: List[ExitProposal],
    *,
    arbiter: Optional[ExitArbiter] = None,
) -> ArbiterResult:
    """The decision call every exit producer must route through."""
    arb = arbiter or get_exit_arbiter()
    return arb.arbitrate(
        market_id=ctx.market_id,
        generation_id=ctx.generation_id,
        held_side=ctx.held_side,
        remaining_cc=ctx.remaining_cc,
        breakeven_floor_cents=ctx.breakeven_floor_cents,
        trail_giveback_cents=ctx.trail_giveback_cents,
        book=ctx.book,
        proposals=list(proposals),
    )


def approve_intent(
    intent: Any,
    ctx: ExitContext,
    *,
    kind: Optional[str] = None,
    issuer: Optional[str] = None,
    fallback_kind: Optional[str] = None,
    arbiter: Optional[ExitArbiter] = None,
) -> PreparedExit:
    """Arbitrate an exit OrderIntent.  On approval the intent is stamped
    with ``exit_attempt_id`` and repriced/qty'd to the approved decision —
    it then satisfies the router's arbiter gate."""
    # The generation the arbiter arbitrates for is authoritative — an
    # emergency claim binds to it, and the router gate keys the attempt by
    # ``{ticker}|{generation}``.
    if not getattr(intent, "position_generation_id", None):
        intent.position_generation_id = ctx.generation_id
    proposal = proposal_from_intent(
        intent, kind=kind, issuer=issuer, fallback_kind=fallback_kind)
    result = propose_exit(ctx, [proposal], arbiter=arbiter)
    if result.status != "submitted":
        denial = ";".join(f"{pid}:{why}" for pid, why in
                          (result.not_selected or [])) or result.status
        logger.info(
            "[EXIT-ARBITER] not submitted: ticker=%s status=%s floor=%dc "
            "denial=%s", ctx.market_id, result.status,
            result.floor_cents, denial,
        )
        return PreparedExit(approved=False, result=result, denial=denial)
    intent.exit_attempt_id = result.attempt.attempt_id
    intent.price_cents = int(result.submitted_limit_cents)
    eff_qty = Decimal(int(result.effective_qty_cc)) / Decimal("100")
    if getattr(intent, "count_fp", None) is not None:
        intent.count_fp = eff_qty
    intent.count = float(eff_qty)
    # Bind identity so reconcile can locate the order after a lost ack.
    arb = arbiter or get_exit_arbiter()
    arb.bind_attempt_identity(
        result.attempt.position_key,
        client_order_id=getattr(intent, "client_order_id", None) or "",
        decision_id=getattr(intent, "intent_id", None),
    )
    logger.info(
        "[EXIT-ARBITER] approved: ticker=%s attempt=%s kind=%s limit=%dc "
        "qty_cc=%d floor=%dc exception=%s",
        ctx.market_id, result.attempt.attempt_id, proposal.kind,
        result.submitted_limit_cents, result.effective_qty_cc,
        result.floor_cents, result.exception,
    )
    return PreparedExit(approved=True, result=result)


# ---------------------------------------------------------------------------
# Reconciliation — "confirmed dead" evidence contract
# ---------------------------------------------------------------------------
#
# An unknown submission outcome (ACK_UNKNOWN / SUBMITTING-after-restart /
# RECONCILING) is resolved ONLY by exchange observation, never by timeout
# or cache absence.  Discovery order:
#
#   1. attempt.order_id        -> GET /portfolio/orders/{order_id}
#   2. attempt.client_order_id -> GET /portfolio/orders?client_order_id=...
#      (Kalshi's idempotency key; response filtered locally by coid)
#   3. neither                 -> local_no_transmit: the intent never
#      reached the wire (rejected before transport); safe to retry
#
# Observation -> action contract:
#   found + terminal + filled==0          -> confirmed dead -> RETRY_ELIGIBLE
#   found + terminal + 0<filled<qty       -> fills applied -> RETRY_ELIGIBLE
#   found + terminal + filled>=qty        -> FLAT (ledger/position recon)
#   found + non-terminal                  -> WORKING; no replacement
#   found + unrecognised status           -> stays RECONCILING (≠ dead)
#   not found / lookup failed             -> stays RECONCILING (≠ dead)
#
_TERMINAL_ORDER_STATUSES = frozenset({
    "filled", "executed", "cancelled", "canceled", "rejected", "expired",
})
_ACTIVE_ORDER_STATUSES = frozenset({
    "pending", "resting", "open", "live", "partially_filled", "queued",
    "untriggered",
})

# client_order_id prefixes whose orders are submit-time-validated as
# immediate-only (stop candidates hard-code time_in_force="ioc" and the
# StopOrderInvariantError check rejects non-IOC/FOK before the wire).
_IOC_COID_PREFIXES = ("stopcand_",)


def _ioc_dead_after_s() -> float:
    try:
        return float(os.environ.get("MERID_EXIT_IOC_DEAD_AFTER_S", "90"))
    except Exception:
        return 90.0


def _reconcile_stuck_alert_s() -> float:
    try:
        return float(os.environ.get("MERID_EXIT_RECONCILE_STUCK_S", "180"))
    except Exception:
        return 180.0


def _market_dead_after_s() -> float:
    """Margin past the ticker-embedded window end before a closed market's
    orders may be inferred terminal (covers clock skew / close lag)."""
    try:
        return float(os.environ.get("MERID_EXIT_MARKET_DEAD_AFTER_S", "120"))
    except Exception:
        return 120.0


def _market_is_terminal(market_id: Optional[str]) -> bool:
    """True when the attempt's market is provably past close — every order
    on it is terminal by construction.

    Kalshi cancels all resting orders when a market closes and begins
    settlement, so a market whose window end has passed (plus margin)
    cannot host a working or fillable order.  An unfindable order on a
    closed market is therefore dead evidence — the same inference class
    as ``ioc_terminal_inferred``, keyed on market lifecycle instead of
    the order's time-in-force.

    For KX*15M tickers the window end is embedded in the market id
    itself (``parse_kalshi_15m_window_end_utc``) — deterministic, no
    feed dependency.  An unparseable market id stays inconclusive
    (fail-closed).
    """
    mid = str(market_id or "").strip()
    if not mid:
        return False
    try:
        from merid.event_venues.kalshi.expiry_fallback import (
            parse_kalshi_15m_window_end_utc,
        )
        end_utc = parse_kalshi_15m_window_end_utc(mid)
    except Exception:
        end_utc = None
    if end_utc is None:
        return False
    try:
        return time.time() > end_utc.timestamp() + _market_dead_after_s()
    except Exception:
        return False


def _attempt_is_ioc(attempt: Any) -> bool:
    """True when the attempt's order is provably immediate-only (IOC/FOK).

    Immediate-only orders cannot rest on the book, so "not found anywhere"
    after a bounded age is terminal evidence — unlike a resting order,
    where absence is ambiguous.  ``stopcand_`` coids are IOC by
    construction; a ``time_in_force`` marker on the record also counts.
    """
    tif = str(getattr(attempt, "time_in_force", "") or "").lower()
    if tif in ("ioc", "fok", "immediate_or_cancel", "fill_or_kill"):
        return True
    coid = str(getattr(attempt, "client_order_id", "") or "")
    if coid.startswith(_IOC_COID_PREFIXES):
        return True
    # Arbiter attempts carry proposal/decision ids rather than a payload:
    # ``stop_candidate:`` proposals submit IOC by construction.
    for marker in (
        getattr(attempt, "proposal_id", None),
        getattr(attempt, "decision_id", None),
    ):
        if str(marker or "").startswith("stop_candidate:"):
            return True
    return False


def _ioc_attempt_is_dead(attempt: Any) -> bool:
    """An immediate-only attempt old enough that it must be terminal."""
    if not _attempt_is_ioc(attempt):
        return False
    created = float(getattr(attempt, "created_ts", 0.0) or 0.0)
    return created > 0 and (time.time() - created) >= _ioc_dead_after_s()


def _alert_stuck_reconcile(arb: Any, position_key: str) -> None:
    """Escalate a reconcile that has stayed inconclusive too long.

    Does NOT resolve the attempt — a resting order's absence remains
    ambiguous — but operators must see a wedge forming instead of a silent
    ``RECONCILING`` row (the 2026-10-20 BTC wedge suppressed a LOSS_CAP for
    ~7min and rode −53c to settlement).  Alerts once per attempt.

    Re-fetches the active attempt: ``get_active`` returns a copy, and the
    caller's pre-``begin_reconcile`` copy is stale — persisting it would
    revert the RECONCILING transition.
    """
    attempt = arb.attempt_store.get_active(position_key)
    if attempt is None:
        return
    age = time.time() - float(getattr(attempt, "created_ts", 0.0) or 0.0)
    if age < _reconcile_stuck_alert_s():
        return
    for h in getattr(attempt, "history", []) or []:
        if str(h.get("note", "")).startswith("reconcile_stuck_alerted"):
            return
    logger.critical(
        "[EXIT-RECONCILE-STUCK] key=%s coid=%s order_id=%s state=%s "
        "age_s=%.0f — order lookup inconclusive for >%ss; exchange order "
        "may be resting-but-unlisted or the lookup may be degraded. "
        "Attempt stays RECONCILING; investigate manually.",
        position_key, getattr(attempt, "client_order_id", None),
        getattr(attempt, "order_id", None),
        getattr(getattr(attempt, "state", None), "value", "?"),
        age, _reconcile_stuck_alert_s(),
    )
    try:
        attempt.history.append({
            "ts": time.time(),
            "from": getattr(getattr(attempt, "state", None), "value", "?"),
            "to": getattr(getattr(attempt, "state", None), "value", "?"),
            "note": f"reconcile_stuck_alerted:age={int(age)}s",
        })
        arb.attempt_store.save_active(attempt)
    except Exception:
        pass


async def reconcile_attempt(
    position_key: str,
    client: Any,
    *,
    market_id: Optional[str] = None,
    arbiter: Optional[ExitArbiter] = None,
) -> Optional[str]:
    """Resolve an unresolved attempt via exchange order lookup.

    Returns the resulting attempt state string, or None when there is no
    active attempt.  The arbiter's ``resolve_reconcile`` applies the
    confirmed-dead contract; this function only produces the evidence.
    """
    arb = arbiter or get_exit_arbiter()
    attempt = arb.attempt_store.get_active(position_key)
    if attempt is None:
        return None
    arb.begin_reconcile(position_key)

    from merid.position_management.exit_arbiter import ReconcileEvidence

    order = None
    source = "inconclusive"
    if attempt.order_id:
        try:
            res = await client.get_order_result(attempt.order_id)
            if getattr(res, "success", False):
                order = res.unwrap_or(None)
                source = "exchange_order_lookup"
        except Exception as exc:
            logger.warning(
                "[EXIT-RECONCILE] order lookup failed key=%s: %s",
                position_key, exc)
    if order is None and attempt.client_order_id:
        try:
            # min_ts bounds the search window — Kalshi's orders list is
            # recency-ordered and a generous margin keeps the local coid
            # filter cheap even without server-side coid filtering.
            _coid_min_ts = (
                int(attempt.created_ts) - 120
                if getattr(attempt, "created_ts", 0) else None
            )
            res = await client.get_order_by_client_id_result(
                attempt.client_order_id, market_id=market_id,
                min_ts=_coid_min_ts)
            if getattr(res, "success", False):
                order = res.unwrap_or(None)
                source = "client_order_id_lookup"
        except Exception as exc:
            logger.warning(
                "[EXIT-RECONCILE] client-id lookup failed key=%s: %s",
                position_key, exc)

    if order is None:
        if attempt.order_id is None and attempt.client_order_id is None:
            arb.resolve_reconcile(position_key, ReconcileEvidence(
                order_found=False, terminal=True, filled_cc=0,
                source="local_no_transmit"))
        elif _ioc_attempt_is_dead(attempt):
            # IOC/FOK orders cannot rest: if every exchange view (resting,
            # executed, canceled) still can't see the order well past its
            # terminal-by-construction deadline, the order is dead — either
            # it never transmitted or it terminally processed off the live
            # orders feed (Kalshi ages terminal orders into /historical).
            # Unlike a resting order, a missing IOC is never "still working",
            # so releasing a fresh reduce-only attempt cannot stack exposure.
            arb.resolve_reconcile(position_key, ReconcileEvidence(
                order_found=True, terminal=True, filled_cc=0,
                source="ioc_terminal_inferred"))
        elif _market_is_terminal(
                market_id or position_key.split("|", 1)[0]):
            # Market close cancels every resting order — an unfindable
            # order on a closed market is dead by construction, same
            # inference class as ioc_terminal_inferred.  Without this path
            # any resting-limit attempt whose market expired wedged in
            # RECONCILING forever: the coid lookup only covers current
            # order views, and Kalshi ages terminal orders off them, so
            # for an expired market the lookup can never succeed
            # (observed 2026-10-27: 3 model_exit attempts 2-9 days old on
            # settled markets alerting every tick, 15k+ history entries).
            # The position itself is accounted independently by the
            # fills/settlement ledger, and no replacement proposal can be
            # minted for a closed market — releasing cannot stack exposure.
            arb.resolve_reconcile(position_key, ReconcileEvidence(
                order_found=True, terminal=True, filled_cc=0,
                source="market_terminal_inferred"))
        else:
            # Lookup inconclusive or order absent — absence is NOT proof
            # of death (a found-but-empty list may lag the wire).
            _alert_stuck_reconcile(arb, position_key)
            arb.resolve_reconcile(position_key, ReconcileEvidence(
                order_found=False, terminal=False, filled_cc=0,
                source="lookup_inconclusive"))
    else:
        status = str(getattr(order, "status", "") or "").lower()
        try:
            filled_cc = int(Decimal(str(
                getattr(order, "filled_size", 0) or 0)) * Decimal("100"))
        except Exception:
            filled_cc = 0
        if status in _TERMINAL_ORDER_STATUSES:
            arb.resolve_reconcile(position_key, ReconcileEvidence(
                order_found=True, terminal=True, filled_cc=filled_cc,
                source=source))
        elif status in _ACTIVE_ORDER_STATUSES:
            arb.resolve_reconcile(position_key, ReconcileEvidence(
                order_found=True, terminal=False, filled_cc=filled_cc,
                source=source))
        else:
            logger.warning(
                "[EXIT-RECONCILE] unrecognised order status key=%s "
                "status=%s — staying unresolved", position_key, status)
    att = arb.attempt_store.get_active(position_key)
    # Settled-market cleanup: a resolved attempt on a market past close can
    # never mint a replacement, so "RETRY_ELIGIBLE" is a dead active row.
    # Close it into bounded history (the store's load path sweeps the same
    # class of stragglers at restart).
    if att is not None and att.state == AttemptState.RETRY_ELIGIBLE:
        if _market_is_terminal(market_id or position_key.split("|", 1)[0]):
            arb.mark_flat(position_key, "market_settled")
            att = arb.attempt_store.get_active(position_key)
    return att.state.value if att is not None else "FLAT"


async def sweep_reconcile_attempts(
    client: Any,
    *,
    arbiter: Optional[ExitArbiter] = None,
    max_per_sweep: int = 8,
) -> int:
    """Resolve every attempt the arbiter flags as needing reconciliation.

    Called at the top of each exit decision — exchange evidence must clear
    (or confirm) unresolved submissions before a fresh attempt may be
    minted.  Bounded per sweep; failures leave attempts unresolved.
    """
    arb = arbiter or get_exit_arbiter()
    done = 0
    for pkey in list(arb.positions_requiring_reconcile())[:max_per_sweep]:
        market_id = pkey.split("|", 1)[0]
        try:
            await reconcile_attempt(pkey, client, market_id=market_id,
                                    arbiter=arb)
            done += 1
        except Exception as exc:
            logger.warning(
                "[EXIT-RECONCILE-SWEEP] %s failed: %s", pkey, exc)
    return done


def post_route_update(
    position_key: str,
    order_result: Any,
    *,
    fill_cc: int = 0,
    fill_id: Optional[str] = None,
    arbiter: Optional[ExitArbiter] = None,
) -> None:
    """Advance the attempt lifecycle from the route outcome.

    - executed / has fills -> WORKING_OR_PARTIALLY_FILLED (+ record_fill)
    - submission_unknown / timeout -> ACK_UNKNOWN (reconcile required)
    - terminal reject before the wire -> order never transmitted ->
      RETRY_ELIGIBLE (next decision may resubmit)
    """
    arb = arbiter or get_exit_arbiter()
    status = str(getattr(order_result, "status", "") or "").lower()
    certainty = str(getattr(order_result, "submission_certainty", "") or "")
    # Land the exchange order_id on the attempt so reconcile's first
    # discovery path (GET /portfolio/orders/{order_id}) works for working
    # orders — before this, only the client_order_id path was available.
    _oid = getattr(order_result, "order_id", None)
    if _oid:
        try:
            arb.bind_attempt_identity(position_key, "", order_id=str(_oid))
        except Exception:
            pass
    if fill_cc > 0 or getattr(order_result, "has_execution", False):
        arb.mark_acked(position_key)
        if fill_cc > 0:
            arb.record_fill(position_key, fill_cc, fill_id=fill_id)
        # An IOC or terminal partial fill leaves no resting order on the book —
        # transition any remaining coverage to RETRY_ELIGIBLE so the next
        # poll can close the residual instead of waiting on WORKING forever.
        att = arb.attempt_store.get_active(position_key)
        if (
            att is not None
            and att.filled_cc < att.qty_cc
            and (
                status in ("unfilled_ioc", "canceled", "cancelled", "expired")
                or (
                    getattr(order_result, "is_terminal", False)
                    and not getattr(order_result, "is_resting", False)
                )
            )
        ):
            from merid.position_management.exit_arbiter import ReconcileEvidence
            arb.begin_reconcile(position_key)
            arb.resolve_reconcile(position_key, ReconcileEvidence(
                order_found=True, terminal=True, filled_cc=att.filled_cc,
                source=f"route_{status or 'terminal_partial'}"))
    elif status in ("accepted_live", "submitted_live", "resting"):
        # The venue ACKed the order — it exists on the exchange (the
        # route-unhandled fallthrough used to land these in ACK_UNKNOWN
        # with a misleading "unhandled" note).  mark_acked → WORKING keeps
        # the attempt in the must-reconcile set so the next sweep observes
        # the terminal state (an accepted IOC terminals within ~1s) instead
        # of claiming the outcome is unknown.
        arb.mark_acked(position_key)
    elif status == "submission_unknown" or certainty == "unknown" or getattr(
            order_result, "requires_recovery", False):
        arb.mark_ack_unknown(position_key, note=f"route_{status or 'unknown'}")
    elif status in ("unfilled_ioc", "canceled", "cancelled", "expired"):
        # 2026-10-19: an IOC exit that returned unfilled_ioc / canceled /
        # expired is confirmed terminal on the exchange with zero fill.
        # Previously post_route_update had no branch for unfilled_ioc,
        # leaving the arbiter attempt stuck in SUBMITTING forever and
        # suppressing all subsequent profit/stop exits for the position
        # (observed: KXBTC15M-26OCT182200-00 14 retries suppressed while bid
        # ran 57c->72c, then settled 0c).
        from merid.position_management.exit_arbiter import ReconcileEvidence
        arb.begin_reconcile(position_key)
        arb.resolve_reconcile(position_key, ReconcileEvidence(
            order_found=True, terminal=True, filled_cc=0,
            source=f"route_{status}"))
    elif status in ("rejected", "failed", "error"):
        from merid.position_management.exit_arbiter import ReconcileEvidence
        _transmitted = bool(getattr(order_result, "submission_attempted", False))
        arb.begin_reconcile(position_key)
        arb.resolve_reconcile(position_key, ReconcileEvidence(
            order_found=_transmitted, terminal=True, filled_cc=0,
            source=f"route_{status}" if _transmitted else "local_no_transmit"))
    elif status in ("not_submitted",):
        # ``not_submitted`` is the router's authoritative-empty verdict: the
        # in-router reconcile proved the order never landed on the exchange
        # (submission_attempted=True + empty coid lookup, or a pre-transmit
        # gate refusal with submission_attempted=False).  Either way the
        # attempt is confirmed dead — resolve RETRY_ELIGIBLE so the next
        # decision may mint a fresh attempt instead of wedging SUBMITTING.
        from merid.position_management.exit_arbiter import ReconcileEvidence
        arb.begin_reconcile(position_key)
        arb.resolve_reconcile(position_key, ReconcileEvidence(
            order_found=True, terminal=True, filled_cc=0,
            source="route_not_submitted_authoritative_empty"))
    elif status in ("duplicate", "duplicate_unknown"):
        # Router-level concurrent dedup: another in-flight route owns this
        # client_order_id and will drive its outcome.  The attempt's fate is
        # therefore UNKNOWN from this route — ACK_UNKNOWN keeps it in the
        # must-reconcile set so the worker observes the owning order.
        arb.mark_ack_unknown(position_key, note=f"route_{status}")
    else:
        # Safe default — any status this function does not recognise leaves
        # the submission outcome genuinely uncertain.  SUBMITTING is
        # unresolved but was historically left out of the reconcile set, so
        # an unhandled status wedged every later exit for the generation.
        # Mark ACK_UNKNOWN: unknown is not dead, but it MUST be reconciled.
        att = arb.attempt_store.get_active(position_key)
        if att is not None and att.state == AttemptState.SUBMITTING:
            logger.warning(
                "[EXIT-ARBITER] post_route_update: unhandled status=%s "
                "key=%s — marking ACK_UNKNOWN for reconcile",
                status or "<none>", position_key)
            arb.mark_ack_unknown(
                position_key, note=f"route_unhandled:{status or 'none'}")
