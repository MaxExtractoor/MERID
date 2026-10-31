"""Submit-time entry EV revalidation — the final gate before transport.

Answers, at the FINAL permitted price and quantity, using a valid current
book and a sufficiently current settlement-probability estimate:

    does this entry still meet the required net edge?

It does not merely make an old candidate marketable — it recomputes the
actual proposed trade:

    EV_order = q * p_held - C_acquisition - F_entry - R
    EV_per_contract = EV_order / q

Two execution-cost checks are kept distinct:
  - ``expected_cost_cents`` — cost of the eligible quantity walking the
    CURRENT depth (favorable snapshot).
  - ``worst_cost_cents`` — cost if every filled contract pays the final
    limit (the bound the wire actually permits).

A favorable snapshot never justifies a limit that permits execution
outside economic policy: the reprice bound is derived from the required
edge, and a proposed limit above it is ``submit_reapproval_required`` —
the approval-binding layer rejects reuse of a stale approval after
protected economics change, so this gate never silently mutates them.

Freshness thresholds are deliberately lenient defaults — the latency
instrumentation must show the true eval->submit distribution before
they are tightened.  Ages are emitted on every decision regardless.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Outcomes
SUBMIT_EDGE_VALID = "submit_edge_valid"
SUBMIT_EDGE_LOST = "submit_edge_lost"
SUBMIT_PROBABILITY_STALE = "submit_probability_stale"
SUBMIT_BOOK_INVALID = "submit_book_invalid"
SUBMIT_BOOK_STALE = "submit_book_stale"
SUBMIT_DEPTH_INSUFFICIENT = "submit_depth_insufficient"
SUBMIT_RISK_CHANGED = "submit_risk_changed"
SUBMIT_MARKET_NOT_TRADABLE = "submit_market_not_tradable"
SUBMIT_REAPPROVAL_REQUIRED = "submit_reapproval_required"
SUBMIT_DEPTH_UNRELIABLE = "submit_depth_unreliable"


def _env_ms(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except Exception:
        return default


@dataclass
class AcquisitionBook:
    """Held-side ask depth: (price_cents, qty_cc) ascending by price,
    plus provenance.  Built from market-state (or injected in tests).

    ``own_levels`` maps held-side ask price -> own resting qty in cc, from
    the ownership overlay: an own sell@a or own buy-opposite@(100-a) sits on
    this ladder.  ``own_evidence_complete`` is False when own-order
    attribution could not be performed (missing ticker / registry failure) —
    depth-dependent decisions must not treat an unresolved overlay as an
    empty one."""
    levels: List[Tuple[int, int]]          # (price_cents, qty_cc) asc
    book_age_ms: Optional[int] = None
    book_sequence: Optional[int] = None
    receipt_ts_utc: Optional[float] = None
    own_levels: dict = field(default_factory=dict)
    own_unattributable: int = 0
    own_evidence_complete: bool = True


@dataclass
class SubmitRevalidationInput:
    candidate_id: str
    held_side: str                          # "yes" | "no"
    qty_cc: int
    proposed_limit_cents: int               # final permitted price
    p_held_cents: Decimal                   # settlement prob estimate, cents
    prob_est_ts: Optional[float]            # estimate timestamp (utc epoch s)
    model_version: Optional[str] = None
    book: Optional[AcquisitionBook] = None
    fee_per_contract_cents: Decimal = Decimal("0")
    reserves_per_contract_cents: Decimal = Decimal("0")
    required_edge_per_contract_cents: Decimal = Decimal("0")
    market_trading: bool = True
    resize_allowed: bool = False            # strategy policy
    post_only: bool = False                 # resting (maker) limit order
    # self-trade-prevention policy the order will serialize; the depth
    # simulator must use the same policy or it is pricing a different trade.
    self_trade_prevention: str = "taker_at_cross"
    # freshness thresholds (lenient pending measured distributions)
    max_prob_age_ms: int = field(
        default_factory=lambda: _env_ms(
            "MERID_SUBMIT_PROB_MAX_AGE_MS", 30000))
    max_book_age_ms: int = field(
        default_factory=lambda: _env_ms(
            "MERID_SUBMIT_BOOK_MAX_AGE_MS", 5000))


@dataclass
class SubmitDecision:
    outcome: str
    reason: str = ""
    permitted_limit_cents: Optional[int] = None
    permitted_qty_cc: int = 0
    max_price_cents: Optional[int] = None
    ev_order_cents: Optional[Decimal] = None
    ev_per_contract_cents: Optional[Decimal] = None
    expected_cost_cents: Optional[Decimal] = None
    worst_cost_cents: Optional[Decimal] = None
    prob_age_ms: Optional[int] = None
    book_age_ms: Optional[int] = None
    eligible_qty_cc: int = 0

    @property
    def valid(self) -> bool:
        return self.outcome == SUBMIT_EDGE_VALID


def _walk_book(levels: List[Tuple[int, int]], limit_cents: int,
               want_cc: int) -> Tuple[int, Decimal]:
    """Eligible qty (cc) at price <= limit and expected cost (cents,
    Decimal) walking depth lowest-first."""
    eligible = 0
    cost = Decimal("0")
    for price, qty in sorted(levels, key=lambda l: l[0]):
        if price > limit_cents or eligible >= want_cc:
            break
        take = min(qty, want_cc - eligible)
        eligible += take
        cost += Decimal(price) * Decimal(take) / Decimal(100)
    return eligible, cost


def _walk_book_owned(
    levels: List[Tuple[int, int]],
    own_levels: dict,
    limit_cents: int,
    want_cc: int,
    stp: str = "taker_at_cross",
) -> Tuple[int, Decimal, bool]:
    """Self-trade-prevention-aware variant of ``_walk_book``.

    ``own_levels`` maps price_cents -> own resting qty_cc on this ladder
    (public sizes already include it).  Policies:

    - ``taker_at_cross``: matching halts before the first own-touching
      level — queue position inside a mixed level is unknowable, so the
      conservative bound takes no fills at that level.
    - ``maker``: own resting orders are canceled and skipped; external
      depth continues.

    Returns ``(eligible_cc, expected_cost_cents, own_book_anomaly)``.
    ``own_book_anomaly`` is True when own qty exceeds a level's public
    size — a registry/public-book desync; the depth estimate must not
    authorize execution from that estimate.
    """
    eligible = 0
    cost = Decimal("0")
    anomaly = False
    for price, qty in sorted(levels, key=lambda l: l[0]):
        if price > limit_cents or eligible >= want_cc:
            break
        own = int((own_levels or {}).get(price, 0) or 0)
        external = qty - own
        if external < 0:
            anomaly = True
            external = 0
        if own > 0 and stp == "taker_at_cross":
            break
        take = min(external, want_cc - eligible)
        if take > 0:
            eligible += take
            cost += Decimal(price) * Decimal(take) / Decimal(100)
    return eligible, cost, anomaly


def revalidate_entry(inp: SubmitRevalidationInput) -> SubmitDecision:
    """Recompute the proposed entry's economics at submit time."""
    d = SubmitDecision(outcome=SUBMIT_EDGE_LOST)

    if not inp.market_trading:
        d.outcome = SUBMIT_MARKET_NOT_TRADABLE
        d.reason = "market_not_trading"
        return d
    if inp.qty_cc <= 0 or not (1 <= inp.proposed_limit_cents <= 99):
        d.outcome = SUBMIT_BOOK_INVALID
        d.reason = f"bad_order_shape:qty={inp.qty_cc} limit={inp.proposed_limit_cents}"
        return d

    # --- freshness -----------------------------------------------------
    now = time.time()
    if inp.prob_est_ts is not None:
        # prob_est_ts may be wall or monotonic depending on producer;
        # pick the clock that yields a sane (non-huge-negative) age.
        est = float(inp.prob_est_ts)
        d.prob_age_ms = max(0, int((
            (time.monotonic() if est < 1e9 else now) - est) * 1000))
        if d.prob_age_ms > inp.max_prob_age_ms:
            d.outcome = SUBMIT_PROBABILITY_STALE
            d.reason = f"prob_age_ms={d.prob_age_ms}>{inp.max_prob_age_ms}"
            return d
    book = inp.book
    if book is None or not book.levels:
        d.outcome = SUBMIT_BOOK_INVALID
        d.reason = "no_book_levels"
        return d
    if book.book_age_ms is not None:
        d.book_age_ms = int(book.book_age_ms)
        if d.book_age_ms > inp.max_book_age_ms:
            d.outcome = SUBMIT_BOOK_STALE
            d.reason = f"book_age_ms={d.book_age_ms}>{inp.max_book_age_ms}"
            return d

    # --- economic bound (reprice only within it) ------------------------
    # max acquisition price consistent with the required net edge:
    #   price + fee + reserve + required_edge <= p_held
    max_price = int(
        inp.p_held_cents
        - inp.fee_per_contract_cents
        - inp.reserves_per_contract_cents
        - inp.required_edge_per_contract_cents)
    d.max_price_cents = max_price
    if inp.proposed_limit_cents > max_price:
        # The wire would permit fills at prices that violate policy.
        d.outcome = SUBMIT_REAPPROVAL_REQUIRED
        d.reason = (f"limit={inp.proposed_limit_cents}>"
                    f"max_price={max_price}")
        return d
    effective_limit = min(inp.proposed_limit_cents, max_price)
    d.permitted_limit_cents = effective_limit

    # --- eligible depth + acquisition cost ------------------------------
    if inp.post_only:
        # 2026-10-21: resting (maker/post-only) orders do not walk the ask
        # book — the fill price is the limit itself, so acquisition cost is
        # the limit and "depth" is the wrong frame.  The earlier taker walk
        # rejected every non-crossing maker bid on a coherent book
        # (no asks at-or-below the bid -> submit_depth_insufficient; live:
        # XRP BUY_YES@90 post-only).  What actually binds a resting order:
        #   * book validity + freshness (checked above),
        #   * the max_price bound (checked above),
        #   * non-crossing validity — a resting buy at-or-above the best
        #     ask is immediately marketable; the exchange rejects/cancels
        #     it under post_only, and crossing economics are a different
        #     admission contract -> reapproval, not a silent rewrite,
        #   * the EV floor below, computed at the limit.
        # The adverse-selection cost of resting is priced upstream in the
        # lane's own reserves (ASR), not by consuming depth.
        best_ask = book.levels[0][0]
        if effective_limit >= best_ask:
            d.outcome = SUBMIT_REAPPROVAL_REQUIRED
            d.reason = (f"post_only_crosses:limit={effective_limit}"
                        f">=best_ask={best_ask}")
            return d
        permitted_cc = inp.qty_cc
        expected_cost = (
            Decimal(effective_limit) * Decimal(permitted_cc) / Decimal(100)
        )
        d.eligible_qty_cc = permitted_cc
        d.expected_cost_cents = expected_cost
        d.permitted_qty_cc = permitted_cc
    else:
        # Depth-dependent decision: the own-liquidity overlay must be
        # resolved before the walk.  An incomplete overlay (ticker
        # unresolved, unattributable own orders) is not an empty one —
        # refuse to authorize from a depth estimate that may include our
        # own resting quantity.
        if not getattr(book, "own_evidence_complete", True):
            d.outcome = SUBMIT_DEPTH_UNRELIABLE
            d.reason = "own_overlay_incomplete"
            return d
        if getattr(book, "own_unattributable", 0):
            d.outcome = SUBMIT_DEPTH_UNRELIABLE
            d.reason = f"own_unattributable={book.own_unattributable}"
            return d
        eligible_cc, expected_cost, own_anomaly = _walk_book_owned(
            book.levels, getattr(book, "own_levels", None) or {},
            effective_limit, inp.qty_cc,
            stp=inp.self_trade_prevention)
        if own_anomaly:
            d.outcome = SUBMIT_DEPTH_UNRELIABLE
            d.reason = "own_gt_public_level"
            return d
        d.eligible_qty_cc = eligible_cc
        d.expected_cost_cents = expected_cost
        if eligible_cc <= 0:
            d.outcome = SUBMIT_DEPTH_INSUFFICIENT
            d.reason = f"no_depth_at_or_below:{effective_limit}c"
            return d
        permitted_cc = inp.qty_cc
        if eligible_cc < inp.qty_cc:
            if not inp.resize_allowed:
                d.outcome = SUBMIT_DEPTH_INSUFFICIENT
                d.reason = (f"partial_depth:{eligible_cc}<{inp.qty_cc}cc "
                            f"at<={effective_limit}c resize_not_permitted")
                return d
            permitted_cc = eligible_cc
            # resized order: recompute expected cost for the permitted qty
            # with the same ownership overlay — the non-own walk would
            # re-credit our own resting quantity as external fills.
            _, expected_cost, _ = _walk_book_owned(
                book.levels, getattr(book, "own_levels", None) or {},
                effective_limit, permitted_cc,
                stp=inp.self_trade_prevention)
            d.expected_cost_cents = expected_cost
        d.permitted_qty_cc = permitted_cc

    q_contracts = Decimal(permitted_cc) / Decimal(100)
    # Worst permitted cost: every filled contract pays the final limit.
    d.worst_cost_cents = Decimal(effective_limit) * q_contracts

    # --- EV --------------------------------------------------------------
    fee_total = inp.fee_per_contract_cents * q_contracts
    reserves_total = inp.reserves_per_contract_cents * q_contracts
    ev_order = (inp.p_held_cents * q_contracts
                - expected_cost - fee_total - reserves_total)
    d.ev_order_cents = ev_order
    d.ev_per_contract_cents = ev_order / q_contracts if q_contracts else None

    if (ev_order <= 0 and inp.required_edge_per_contract_cents >= 0) or (
        d.ev_per_contract_cents is not None
        and d.ev_per_contract_cents < inp.required_edge_per_contract_cents
    ):
        d.outcome = SUBMIT_EDGE_LOST
        d.reason = (f"ev_per_contract="
                    f"{d.ev_per_contract_cents}<{inp.required_edge_per_contract_cents}")
        return d

    d.outcome = SUBMIT_EDGE_VALID
    d.reason = "ok"
    return d


# ---------------------------------------------------------------------------
# Plumbing: intent + live market-state -> SubmitRevalidationInput
# ---------------------------------------------------------------------------

def _held_side_of(intent) -> Optional[str]:
    side = str(getattr(intent, "side", "") or "").lower()
    if side in ("yes", "no"):
        return side
    # Canonical intents carry Kalshi-formatted side (BUY_YES / SELL_NO etc.) —
    # the held outcome is the suffix.  Without this every entry intent fails
    # closed with submit_inputs_missing.
    for token in ("_yes", "_no"):
        if side.endswith(token):
            return token[1:]
    return None


def acquisition_book_from_state(state, held_side: str,
                                want_levels: int = 10,
                                ticker=None,
                                own_orders=None) -> Optional[AcquisitionBook]:
    """Build held-side ask depth from KalshiMarketState.

    Kalshi's YES-centric book: held=YES acquires against no_bids
    (yes_ask = 100 - no_bid); held=NO acquires against yes_bids.

    ``ticker`` identifies the market for the own-liquidity overlay; when
    omitted the state's ``ticker`` is used.  Without a resolvable ticker
    own-order attribution cannot run and ``own_evidence_complete`` is
    False — ``revalidate_entry`` then refuses depth-dependent taker
    submissions rather than assuming an empty own book.
    """
    if state is None:
        return None
    if ticker is None:
        ticker = getattr(state, "ticker", None)
    held = held_side.lower()
    bids = (getattr(state, "no_bids", None) if held == "yes"
            else getattr(state, "yes_bids", None)) or []
    levels: List[Tuple[int, int]] = []
    for lvl in bids[:want_levels]:
        px = getattr(lvl, "price_cents", None)
        if px is None and isinstance(lvl, (list, tuple)) and len(lvl) >= 2:
            px, sz = lvl[0], lvl[1]
        else:
            sz = getattr(lvl, "size", 0)
        if px is None:
            continue
        ask = 100 - int(px)
        try:
            qty_cc = int(Decimal(str(sz)) * Decimal("100"))
        except Exception:
            qty_cc = 0
        if 1 <= ask <= 99 and qty_cc > 0:
            levels.append((ask, qty_cc))
    if not levels:
        # Fallback: single-level top-of-book view.
        ask_attr = "best_ask_cents" if held == "yes" else "best_no_ask_cents"
        ask = getattr(state, ask_attr, None)
        if ask is not None and 1 <= int(ask) <= 99:
            qty = getattr(state, "top_of_book_size", 0) or 0
            try:
                qty_cc = int(Decimal(str(qty)) * Decimal("100"))
            except Exception:
                qty_cc = 0
            if qty_cc > 0:
                levels = [(int(ask), qty_cc)]
    if not levels:
        return None
    age_ms = None
    ts = getattr(state, "last_book_update_ts", None)
    if ts:
        # last_book_update_ts is stamped with time.monotonic() by the
        # store (market_state._sync_book_fields).  Compare against the same
        # clock — mixing clocks would yield a negative/huge age and either
        # hide staleness or reject every book.  If a wall-clock timestamp
        # ever appears (ts >> monotonic range), fall back to wall math.
        ts_f = float(ts)
        if ts_f < 1e9:
            age_ms = max(0, int((time.monotonic() - ts_f) * 1000))
        else:
            age_ms = max(0, int((time.time() - ts_f) * 1000))
    seq = getattr(state, "ws_last_seq", None) or getattr(
        state, "book_sequence", None)
    own_cc: dict = {}
    own_unattr = 0
    own_complete = True
    if ticker:
        try:
            from merid.event_venues.kalshi.executable_quote import (
                QuotePurpose,
                _own_qty_by_level,
            )
            _own_map, _own_unattr = _own_qty_by_level(
                str(ticker), held, QuotePurpose.ENTRY,
                own_orders=own_orders)
            own_cc = {p: int(q) * 100 for p, q in _own_map.items() if q}
            own_unattr = _own_unattr
        except Exception:
            # Registry failure is not an empty overlay — fail closed.
            own_complete = False
    else:
        own_complete = False
    return AcquisitionBook(levels=sorted(levels, key=lambda l: l[0]),
                           book_age_ms=age_ms, book_sequence=seq,
                           own_levels=own_cc,
                           own_unattributable=own_unattr,
                           own_evidence_complete=own_complete)


def input_from_intent(
    intent,
    *,
    state=None,
    market_trading: bool = True,
    now: Optional[float] = None,
) -> Optional[SubmitRevalidationInput]:
    """Map an OrderIntent + live market state onto the revalidation input.

    Returns None when the intent lacks the minimum economics to revalidate
    (caller must fail closed, not skip the gate)."""
    held = _held_side_of(intent)
    if held is None:
        return None
    try:
        qty_cc = int(Decimal(str(getattr(intent, "count_fp", None)
                                       if getattr(intent, "count_fp", None)
                                       is not None
                                       else getattr(intent, "count", 0)))
                     * Decimal("100"))
    except Exception:
        return None
    limit = getattr(intent, "price_cents", None)
    if limit is None:
        return None
    # probability: prefer selected-side estimate; fall back per side
    p = getattr(intent, "p_selected", None)
    if p is None:
        p = getattr(intent, "p_yes" if held == "yes" else "p_no", None)
    if p is None:
        p = getattr(intent, "model_prob", None)
    if p is None:
        return None
    p_dec = Decimal(str(p))
    # accept fraction (0..1) or cents (1..99) representations
    p_held_cents = p_dec * 100 if p_dec <= 1 else p_dec
    est_ts = (getattr(intent, "snapshot_ts", None)
              or getattr(intent, "decision_ts", None))
    # fee at proposed limit via exact parabolic schedule
    try:
        from merid.event_venues.kalshi.parabolic_fees import (
            kalshi_fee_cents_exact,
        )
        fee_per_contract = kalshi_fee_cents_exact(
            Decimal(limit) / Decimal(100), Decimal(1), "taker")
    except Exception:
        fee_per_contract = Decimal("0")
    req_edge = getattr(intent, "min_required_edge", None)
    try:
        req_edge_dec = Decimal(str(req_edge)) if req_edge is not None \
            else Decimal("0")
        if req_edge_dec <= 1:
            req_edge_dec *= 100
    except Exception:
        req_edge_dec = Decimal("0")
    if req_edge is None:
        # No stamped admission bound — apply the env default.  Bounded lanes
        # deliberately stamp negative floors (e.g. window_quota -25c); those
        # must survive rather than being clobbered to a positive default.
        try:
            req_edge_dec = Decimal(os.environ.get(
                "MERID_SUBMIT_REQUIRED_EDGE_CENTS", "1.5"))
        except Exception:
            req_edge_dec = Decimal("1.5")
    # The depth simulator must use the same self-trade-prevention policy
    # the router serializes; anything else prices a different trade.
    # Reuse the canonical wire resolver — it honors an explicit field,
    # else maps liquidity_role, else defaults taker_at_cross.
    try:
        from merid.event_venues.kalshi.order_router import (
            _resolve_self_trade_prevention_type,
        )
        stp = _resolve_self_trade_prevention_type(intent)
    except Exception:
        stp = str(getattr(intent, "self_trade_prevention_type", None)
                  or "taker_at_cross").lower()
    if stp not in ("taker_at_cross", "maker"):
        stp = "taker_at_cross"
    book = acquisition_book_from_state(
        state, held, ticker=getattr(intent, "ticker", None)) \
        if state is not None else None
    return SubmitRevalidationInput(
        candidate_id=str(getattr(intent, "intent_id", None)
                         or getattr(intent, "client_order_id", None) or ""),
        held_side=held,
        qty_cc=qty_cc,
        proposed_limit_cents=int(limit),
        p_held_cents=p_held_cents,
        prob_est_ts=float(est_ts) if est_ts else None,
        model_version=str(getattr(intent, "entry_model", None)
                          or getattr(intent, "entry_model_version", None)
                          or ""),
        book=book,
        fee_per_contract_cents=fee_per_contract,
        reserves_per_contract_cents=Decimal(
            os.environ.get("MERID_SUBMIT_RESERVE_CENTS", "0")),
        required_edge_per_contract_cents=req_edge_dec,
        market_trading=market_trading,
        resize_allowed=os.environ.get(
            "MERID_SUBMIT_RESIZE_ALLOWED", "0").strip() in ("1", "true"),
        post_only=bool(getattr(intent, "post_only", False))
        or str(getattr(intent, "execution_mode", "") or "").lower()
        in ("maker", "passive_quote"),
        self_trade_prevention=stp,
    )
