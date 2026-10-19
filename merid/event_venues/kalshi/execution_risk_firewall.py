"""Kalshi Execution Risk Firewall — final, stateful gate before venue submission.

All exit orders submitted through ``route_order_async`` must carry a
``FirewallDecision`` produced by this module.  The firewall recomputes the
order from current, authoritative state and rejects any exit whose quantity,
price, P&L, or identity cannot be reconciled.

Design notes:
- This is a singleton. It intentionally re-fetches the authoritative position
  and book rather than trusting the caller's precomputed metadata.
- It operates on ``CanonicalOrderIntent`` (centi-contracts, signed-YES).
- Enforcement is fail-closed in production; in test/dev it defaults to
  ``observe_only`` unless explicitly configured.
- The venue client validates a firewall approval token before any outbound
  order request.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from utils.logger import get_logger
from merid.event_venues.kalshi import exit_authorization as _xa

if TYPE_CHECKING:
    from merid.event_venues.kalshi.order_intent_contract import CanonicalOrderIntent

logger = get_logger("merid.event_venues.kalshi.execution_risk_firewall")


# ── Configuration defaults ──────────────────────────────────────────────────


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _max_exit_adverse_pnl_cents(default: int = 5000) -> int:
    """Adverse-PnL budget for risk-reducing exits, distinct from the entry budget."""
    return _env_int("MERID_MAX_EXIT_ADVERSE_PNL_CENTS", default)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# ── Data objects ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BookDepth:
    """Executable depth for an exit at the requested size."""

    vwap_cents: int
    available_qty_cc: int
    levels: List[Tuple[int, int]]  # (price_cents, qty_cc)
    best_bid_cents: int
    best_ask_cents: Optional[int]
    book_age_ms: int
    book_sequence: Optional[int]
    # Price of the deepest level the requested quantity must consume.
    # A limit at this price is guaranteed to fill the whole request (IOC
    # semantics), whereas ``vwap_cents`` is only the average — a sell limit
    # exactly at VWAP can still leave the marginal fills unexecuted.
    marginal_price_cents: Optional[int] = None


@dataclass(frozen=True)
class PositionSnapshot:
    """Fresh, canonical position used by the firewall."""

    position_cc: int
    side: Optional[str]
    avg_price_cents: Optional[int]
    version: str
    snapshot_age_ms: int
    parent_entry_fill_id: Optional[str] = None


@dataclass(frozen=True)
class FirewallDecision:
    """Immutable approval/rejection decision persisted before any network call."""

    decision_id: str
    client_order_id: str
    status: str  # "approved" | "rejected" | "observe_only"
    reason: str
    market_ticker: str
    contract: str
    action: str
    qty_cc: int
    approved_limit_cents: int
    expected_position_before: int
    expected_position_after: int
    expected_realized_pnl_cents: Optional[int]
    exchange_position_cc: int
    position_version: str
    book_age_ms: int
    book_sequence: Optional[int]
    vwap_cents: int
    available_depth_cc: int
    parent_entry_fill_id: Optional[str] = None
    emergency: bool = False
    # Approval binding (2026-10-17): the economics the approval covers.  The
    # venue client rejects an order carrying this token when any bound field
    # differs — approval is of THIS order, not a reusable capability.
    time_in_force: str = ""
    reduce_only: bool = True
    exchange_index: Optional[int] = None
    intent_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["created_at"] = self.created_at
        return d


class ExecutionRiskFirewallError(Exception):
    """Unexpected internal firewall failure."""


class ExecutionRiskFirewall:
    """Process-wide final risk gate for Kalshi exits."""

    _instance: Optional["ExecutionRiskFirewall"] = None
    _lock: Optional[asyncio.Lock] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
            cls._lock = asyncio.Lock()
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._decisions: Dict[str, FirewallDecision] = {}
        self._initialized = True
        logger.info("[FIREWALL] Initialized")

    # ── Public API ──────────────────────────────────────────────────────────

    @classmethod
    def get_instance(cls) -> "ExecutionRiskFirewall":
        return cls()

    @classmethod
    def reset_for_test(cls) -> None:
        """Clear in-memory decisions; tests use this for isolation."""
        inst = cls._instance
        if inst is not None:
            inst._decisions.clear()

    def is_exit(self, canonical: "CanonicalOrderIntent") -> bool:
        return canonical.purpose == "close" or bool(canonical.reduce_only)

    async def validate_exit(
        self,
        canonical: "CanonicalOrderIntent",
        original_intent: Optional[Any] = None,
    ) -> FirewallDecision:
        """Return an approved/rejected decision for an exit order.

        This is the non-negotiable contract:
            canonical intent
            -> resolve canonical position
            -> fetch fresh exchange position
            -> verify position version
            -> fetch fresh executable book plus depth
            -> recompute exit action, quantity, price, fees, P&L
            -> apply loss/slippage/expiry policy
            -> persist approved/rejected decision
        """
        t0 = time.monotonic()
        ticker = canonical.market_ticker

        # 0. Market liveness and pre-close deadline for all exits.
        # A non-open market or a market inside the liveness reserve is not tradable,
        # so we fail closed before any position or book check.
        if not self._market_active_and_before_deadline(ticker):
            return self._rejected("market_not_active_or_after_deadline", canonical)

        # CRITICAL FIX (2026-09-01): Reject the exit if there is already an unresolved
        # exit attempt for this ticker in flight.  This prevents the duplicate-exit race
        # that produced the 2026-09-01 KXSOL unmatched fill: the first create-order ack
        # was lost, the local position snapshot was still stale, and a second exit was
        # approved and submitted before the first fill was ingested.
        _in_flight = self._has_in_flight_exit(canonical)
        if _in_flight is not None:
            return self._rejected(
                f"in_flight_exit:client_order_id={_in_flight.client_order_id}:status={_in_flight.status}",
                canonical,
            )

        # 1. Fresh exchange position (authoritative).
        pos = await self._fetch_position(ticker)
        if pos is None or pos.snapshot_age_ms > self._max_position_age_ms():
            stale_reason = (
                f"stale_position_snapshot:age_ms={pos.snapshot_age_ms}"
                if pos is not None
                else "position_snapshot_unavailable"
            )

            # Reduce-only fallback: a bounded, reduce-only exit may use the immutable
            # local fills ledger when the exchange/cache snapshot is stale or missing.
            if self._is_reduce_only_fallback_eligible(canonical):
                local_pos = self._fetch_local_position(ticker)
                if local_pos is None or not self._local_position_supports_exit(
                    local_pos, canonical
                ):
                    return self._rejected(
                        f"reduce_only_fallback:no_local_position:{stale_reason}",
                        canonical,
                    )
                logger.warning(
                    "[FIREWALL-REDUCE-ONLY-FALLBACK] ticker=%s intent_id=%s "
                    "qty_cc=%d limit_cents=%d local_position_cc=%d local_side=%s "
                    "original_reason=%s",
                    ticker,
                    canonical.intent_id,
                    canonical.qty_cc,
                    canonical.limit_cents,
                    local_pos.position_cc,
                    local_pos.side or "none",
                    stale_reason,
                )
                pos = local_pos
            else:
                return self._rejected(stale_reason, canonical)

        # 2. Canonical quantity invariants (centi-contracts only).
        qty_cc = canonical.qty_cc
        if qty_cc <= 0:
            return self._rejected(f"non_positive_qty:qty_cc={qty_cc}", canonical)
        if qty_cc > abs(pos.position_cc):
            return self._rejected(
                f"over_close:qty_cc={qty_cc}:position_cc={pos.position_cc}", canonical
            )

        # 3. Exit must reduce absolute exposure and must not flip sign.
        from merid.event_venues.kalshi.binary_price_space import yes_delta

        order_yes_delta = yes_delta(canonical.action, canonical.contract, qty_cc)
        if pos.position_cc > 0 and order_yes_delta >= 0:
            return self._rejected(f"not_exit_long_yes:delta={order_yes_delta}", canonical)
        if pos.position_cc < 0 and order_yes_delta <= 0:
            return self._rejected(f"not_exit_long_no:delta={order_yes_delta}", canonical)

        expected_after = pos.position_cc + order_yes_delta
        if expected_after != 0 and (expected_after > 0) != (pos.position_cc > 0):
            return self._rejected(f"position_flip:after={expected_after}", canonical)

        # 4. Re-validate the canonical contract with the fresh position.
        try:
            canonical = self._re_validate(canonical, pos)
        except Exception as exc:
            return self._rejected(f"canonical_re_validation_failed:{exc}", canonical)

        # 5. Fresh executable book and depth.
        book = self._fetch_book(canonical)
        if book is None:
            return self._rejected("book_unavailable", canonical)
        if book.book_age_ms > self._max_quote_age_ms():
            return self._rejected(f"stale_book:age_ms={book.book_age_ms}", canonical)

        # 6. Depth must cover the requested quantity.  For a forced/safety
        # exit, a partial close strictly dominates a deferred full close —
        # resize to the visible depth and let the residual position re-fire
        # its trigger next tick.  Discretionary exits keep the hard reject.
        if book.available_qty_cc < qty_cc:
            if self._is_forced_exit(original_intent, canonical, pos) and book.available_qty_cc > 0:
                new_qty_cc = int(book.available_qty_cc)
                logger.warning(
                    "[FIREWALL-RESIZE-FORCED-EXIT] ticker=%s intent_id=%s "
                    "qty_cc=%d -> %d (book depth shortfall) - partial close "
                    "approved, residual re-triggers next tick",
                    ticker, canonical.intent_id, qty_cc, new_qty_cc,
                )
                canonical = replace(canonical, qty_cc=new_qty_cc)
                qty_cc = new_qty_cc
                order_yes_delta = yes_delta(canonical.action, canonical.contract, qty_cc)
                expected_after = pos.position_cc + order_yes_delta
            else:
                return self._rejected(
                    f"insufficient_depth:requested={qty_cc}:available={book.available_qty_cc}",
                    canonical,
                )

        # 7. Limit must be executable at the requested size (VWAP check).
        if not self._limit_executable(canonical, book):
            # 2026-10-16 (loss audit): a forced/safety exit must not wedge on a
            # limit that sits inside the book's walk — the BTC hard stop at
            # limit=44 vs vwap=43 was deferred ~15s and filled -4c worse.
            # Reprice to the depth-aware marginal level (the deepest level the
            # full quantity needs): for a sell, limit <= marginal guarantees
            # the IOC consumes every needed level.  Steps 8-9 still run on the
            # repriced limit, and the slippage bound (vwap vs best_bid) is
            # enforced independently of the limit, so this cannot widen the
            # loss budget — it only stops a *rejection* from bleeding the
            # position further while the book falls.
            if (
                _env_bool("MERID_FIREWALL_FORCED_EXIT_REPRICE", True)
                and self._is_forced_exit(original_intent, canonical, pos)
                and book.marginal_price_cents is not None
            ):
                _old_limit = int(canonical.limit_cents)
                if canonical.action == "sell":
                    _new_limit = max(
                        1, min(_old_limit, int(book.marginal_price_cents))
                    )
                else:
                    _new_limit = min(
                        99, max(_old_limit, int(book.marginal_price_cents))
                    )
                logger.warning(
                    "[FIREWALL-REPRICE-FORCED-EXIT] ticker=%s intent_id=%s "
                    "limit=%dc -> %dc (vwap=%dc marginal=%dc depth_cc=%d) - "
                    "forced exit repriced to executable depth, not rejected",
                    ticker,
                    canonical.intent_id,
                    _old_limit,
                    _new_limit,
                    book.vwap_cents,
                    book.marginal_price_cents,
                    book.available_qty_cc,
                )
                canonical = replace(canonical, limit_cents=_new_limit)
            else:
                return self._rejected(
                    f"limit_not_executable:limit={canonical.limit_cents}:vwap={book.vwap_cents}",
                    canonical,
                )

        # 8. Recompute expected realized PnL from fresh state.
        from merid.event_venues.kalshi.order_intent_contract import (
            compute_expected_realized_pnl_cents,
        )

        fee_cents = self._estimate_fee_cents(canonical.limit_cents, qty_cc)
        expected_pnl = compute_expected_realized_pnl_cents(
            purpose="close",
            qty_cc=qty_cc,
            limit_cents=canonical.limit_cents,
            contract=canonical.contract,
            position_before=pos.position_cc,
            position_avg_price_cents=pos.avg_price_cents,
            position_side=pos.side,
            fee_cents=fee_cents,
        )

        # 9. Loss / slippage policy.
        allowed, policy_reason = self._apply_loss_policy(
            canonical, pos, book, expected_pnl, original_intent
        )
        # (step 9 delegates structured emergency checks with the live
        # position snapshot so the generation binding is enforced)
        if not allowed:
            return self._rejected(policy_reason, canonical)

        # 10. Parent entry linkage.
        parent = self._resolve_parent_entry_fill_id(canonical, original_intent, pos)
        if _env_bool("MERID_REQUIRE_EXIT_PARENTAGE", False) and not parent:
            if not self._is_safety_or_manual_exit(original_intent, canonical, pos):
                return self._rejected("missing_parent_entry_fill_id", canonical)

        # 11. Approve with a clamped worst-case limit and deterministic client order id.
        approved_limit = self._clamp_exit_limit(canonical, book)

        # 11a. Minimum-proceeds floor for ordinary profit exits (2026-10-17).
        # A voluntary profit-taking exit may not submit below the position's
        # fee-adjusted breakeven floor (held-side entry + entry fee + exit
        # fee).  IOC semantics make the clamp safe: quantity that cannot fill
        # at >= floor is canceled, and the residual rides to settlement — the
        # floor is a submission invariant, never a guaranteed fill.
        # Emergency / operational exits are exempt and may deliberately
        # realize a loss.  When the floor itself is unattainable (> 99c) the
        # honest answer is to hold, so the exit is rejected rather than
        # submitted below it.
        _min_proceeds_exempt = self._is_min_proceeds_exempt(
            original_intent, canonical, pos
        )
        if not _min_proceeds_exempt:
            _entry_c = pos.avg_price_cents
            if _entry_c is not None and 1 <= int(_entry_c) <= 99:
                _floor = self._fee_adjusted_floor_cents(
                    int(_entry_c), approved_limit
                )
                # The required floor is max(breakeven, persisted trail lock):
                # a trail that already locked a gain must not be allowed to
                # submit near breakeven (entry+fees is only the *minimum*
                # profit bound, not the locked-profit level).
                _trail_lock = self._persisted_trail_lock_cents(
                    ticker,
                    generation_id=parent,
                    held_outcome=pos.side if pos else None,
                )
                if _trail_lock is not None:
                    _floor = _trail_lock if _floor is None else max(_floor, _trail_lock)
                if _floor is not None and not (1 <= _floor <= 99):
                    return self._rejected(
                        f"min_proceeds_unattainable:floor={_floor}:entry={int(_entry_c)}",
                        canonical,
                    )
                if _floor is not None:
                    # Held-side-equivalent proceeds: a sell realizes its limit
                    # directly; a YES-form buy closing a NO position realizes
                    # 100 - limit.  Enforce the floor in held-side space.
                    if canonical.action == "sell" and approved_limit < _floor:
                        logger.warning(
                            "[MIN-PROCEEDS-FLOOR] ticker=%s intent_id=%s "
                            "approved_limit=%dc -> %dc (entry=%dc fee-adjusted "
                            "floor; unfilled quantity cancels, residual rides "
                            "to settlement)",
                            ticker, canonical.intent_id,
                            approved_limit, _floor, int(_entry_c),
                        )
                        approved_limit = _floor
                    elif canonical.action == "buy" and approved_limit > 100 - _floor:
                        logger.warning(
                            "[MIN-PROCEEDS-FLOOR] ticker=%s intent_id=%s "
                            "approved_limit=%dc -> %dc (YES-form close; "
                            "held-equivalent floor=%dc entry=%dc; unfilled "
                            "quantity cancels, residual rides to settlement)",
                            ticker, canonical.intent_id,
                            approved_limit, 100 - _floor, _floor, int(_entry_c),
                        )
                        approved_limit = 100 - _floor

        coid = self._deterministic_coid(canonical, pos, approved_limit, parent)
        decision_id = f"firewall_{uuid.uuid4().hex}"

        decision = FirewallDecision(
            decision_id=decision_id,
            client_order_id=coid,
            status="approved",
            reason="approved_by_firewall",
            market_ticker=ticker,
            contract=canonical.contract,
            action=canonical.action,
            qty_cc=qty_cc,
            approved_limit_cents=approved_limit,
            expected_position_before=pos.position_cc,
            expected_position_after=expected_after,
            expected_realized_pnl_cents=expected_pnl,
            exchange_position_cc=pos.position_cc,
            position_version=pos.version,
            book_age_ms=book.book_age_ms,
            book_sequence=book.book_sequence,
            vwap_cents=book.vwap_cents,
            available_depth_cc=book.available_qty_cc,
            parent_entry_fill_id=parent,
            emergency=_min_proceeds_exempt,
            time_in_force=str(getattr(canonical, "time_in_force", "") or ""),
            reduce_only=bool(getattr(canonical, "reduce_only", False)),
            exchange_index=getattr(canonical, "exchange_index", None),
            intent_id=getattr(canonical, "intent_id", None),
            raw={
                "latency_ms": round((time.monotonic() - t0) * 1000, 2),
                "fee_cents": fee_cents,
                "policy_max_adverse_cents": self._max_adverse_pnl_cents(),
                "policy_max_slippage_cents": self._max_slippage_cents(),
            },
        )
        self._persist_decision(decision)

        if self._is_enforced():
            return decision
        # Observe-only mode: return an approved decision but log that it would
        # have enforced. The caller treats the decision as approved.
        return decision

    # ── Token store / enforcement state ─────────────────────────────────────

    def is_enforced(self) -> bool:
        return self._is_enforced()

    def get_decision(self, client_order_id: str) -> Optional[FirewallDecision]:
        return self._decisions.get(client_order_id)

    def consume_decision(self, client_order_id: str) -> Optional[FirewallDecision]:
        """Return and clear the decision for this coid; the venue client
        consumes it exactly once.  2026-10-16 audit: the previous get()
        left every decision resident forever — the map grew unbounded over
        a run and a stale coid could be re-read after routing."""
        return self._decisions.pop(client_order_id, None)

    @staticmethod
    def approval_mismatches(order: Any, decision: "FirewallDecision") -> List[str]:
        """Protected-field binding between an approved decision and the order
        carrying its token.  The approval covers THIS order — any
        post-approval mutation of market, outcome/action, quantity, limit
        price, reduce_only, time-in-force, or exchange shard is a rejection.
        Position generation is bound transitively through client_order_id
        (it is derived from the resolved generation); account scope is bound
        by the authenticated client credential (orders carry no per-order
        account field).  Returns the list of ``field:got!=approved``
        mismatches (empty == bound)."""
        mismatches: List[str] = []
        if getattr(order, "market_id", None) != decision.market_ticker:
            mismatches.append(
                f"market:{getattr(order, 'market_id', None)}!={decision.market_ticker}")
        if (getattr(order, "outcome_id", None) or "").lower() != (decision.contract or "").lower():
            mismatches.append(
                f"contract:{getattr(order, 'outcome_id', None)}!={decision.contract}")
        if (getattr(order, "side", None) or "").lower() != (decision.action or "").lower():
            mismatches.append(
                f"action:{getattr(order, 'side', None)}!={decision.action}")
        try:
            qty_cc = int((Decimal(str(getattr(order, "size", ""))) * Decimal("100")).to_integral_value())
        except Exception:
            qty_cc = -1
        if qty_cc != decision.qty_cc:
            mismatches.append(f"qty_cc:{qty_cc}!={decision.qty_cc}")
        try:
            price_c = int((Decimal(str(getattr(order, "price", ""))) * Decimal("100")).to_integral_value())
        except Exception:
            price_c = -1
        if price_c != decision.approved_limit_cents:
            mismatches.append(
                f"price_c:{price_c}!={decision.approved_limit_cents}")
        if bool(getattr(order, "reduce_only", False)) != bool(decision.reduce_only):
            mismatches.append(
                f"reduce_only:{getattr(order, 'reduce_only', None)}!={decision.reduce_only}")
        try:
            from merid.event_venues.kalshi.client import (
                merid_time_in_force_to_kalshi_api,
            )
            tif_w = merid_time_in_force_to_kalshi_api(
                getattr(order, "time_in_force", None) or "GTC")
            tif_d = merid_time_in_force_to_kalshi_api(
                decision.time_in_force or "GTC")
        except Exception:
            tif_w = tif_d = "__norm_error__"
        if tif_w != tif_d:
            mismatches.append(f"tif:{tif_w}!={tif_d}")
        if decision.exchange_index is not None and (
            getattr(order, "exchange_index", None) != decision.exchange_index
        ):
            mismatches.append(
                f"exchange_index:{getattr(order, 'exchange_index', None)}"
                f"!={decision.exchange_index}")
        return mismatches

    # ── Internals ───────────────────────────────────────────────────────────

    def _is_enforced(self) -> bool:
        """Fail-closed in production; observe-only by default elsewhere."""
        explicit = os.getenv("MERID_EXIT_FIREWALL_OBSERVE_ONLY", "").lower()
        if explicit in ("1", "true", "yes"):
            return False
        if explicit in ("0", "false", "no"):
            return True
        try:
            from merid.settings import settings

            return bool(settings.is_production)
        except Exception:
            return False

    def _rejected(self, reason: str, canonical: "CanonicalOrderIntent") -> FirewallDecision:
        coid = self._deterministic_coid(canonical, None, canonical.limit_cents, None)
        decision = FirewallDecision(
            decision_id=f"firewall_{uuid.uuid4().hex}",
            client_order_id=coid,
            status="rejected" if self._is_enforced() else "observe_only",
            reason=f"firewall_rejected:{reason}",
            market_ticker=canonical.market_ticker,
            contract=canonical.contract,
            action=canonical.action,
            qty_cc=canonical.qty_cc,
            approved_limit_cents=canonical.limit_cents,
            expected_position_before=0,
            expected_position_after=0,
            expected_realized_pnl_cents=None,
            exchange_position_cc=0,
            position_version="",
            book_age_ms=-1,
            book_sequence=None,
            vwap_cents=-1,
            available_depth_cc=-1,
            parent_entry_fill_id=None,
            emergency=False,
            raw={"rejection_reason": reason},
        )
        self._persist_decision(decision)
        return decision

    async def _fetch_position(self, ticker: str) -> Optional[PositionSnapshot]:
        from merid.event_venues.kalshi.order_intent_contract import (
            fetch_fresh_signed_yes_exposure,
        )

        try:
            exchange_position_cc, position_avg_price_cents, position_side = (
                await fetch_fresh_signed_yes_exposure(
                    ticker, timeout=1.0, fallback_to_cache=True
                )
            )
        except Exception as exc:
            logger.warning(
                "[FIREWALL] fetch_fresh_signed_yes_exposure failed for %s: %s",
                ticker,
                exc,
            )
            return None

        if exchange_position_cc is None:
            return None

        from merid.event_venues.kalshi.position_cache import get_position_cache

        cache = get_position_cache()
        cached = cache.get_position(ticker) if cache else None

        version_parts = [
            str(exchange_position_cc),
            str(position_avg_price_cents or 0),
            str(position_side or "none"),
        ]
        parent_entry_fill_id: Optional[str] = None
        if cached is not None:
            version_parts.extend(
                [
                    str(getattr(cached, "quantity_cc", 0)),
                    str(getattr(cached, "avg_price_cents", "") or ""),
                    str(getattr(cached, "entry_fill_id", "") or ""),
                ]
            )
            # CRITICAL FIX (2026-08-22): Only the canonical fill_id is a parent
            # fill_id.  Order/intent/signal ids are kept in their own fields on
            # the OrderIntent and must not be promoted into parent_entry_fill_id.
            parent_entry_fill_id = getattr(cached, "entry_fill_id", None)
            if parent_entry_fill_id and isinstance(parent_entry_fill_id, str):
                parent_entry_fill_id = parent_entry_fill_id.strip() or None

        version = hashlib.sha256(
            json.dumps(version_parts, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

        snapshot_age_ms = 0
        if cached is not None and getattr(cached, "last_update_ts", None):
            snapshot_age_ms = int((time.time() - cached.last_update_ts) * 1000)
        elif cache is not None and hasattr(cache, "_last_exchange_sync_time"):
            sync_time = cache._last_exchange_sync_time.get(ticker)
            if sync_time:
                snapshot_age_ms = int((time.time() - sync_time) * 1000)

        return PositionSnapshot(
            position_cc=exchange_position_cc,
            side=position_side,
            avg_price_cents=position_avg_price_cents,
            version=version,
            snapshot_age_ms=snapshot_age_ms,
            parent_entry_fill_id=parent_entry_fill_id,
        )

    def _re_validate(
        self, canonical: "CanonicalOrderIntent", pos: PositionSnapshot
    ) -> "CanonicalOrderIntent":
        """Re-validate the intent with the fresh position snapshot.

        Updates expected_position_before/after and expected realized PnL using
        the live exchange position, then re-runs the canonical validation.
        Raises ``OrderIntentValidationError`` if the order is no longer valid.
        """
        from merid.event_venues.kalshi.order_intent_contract import (
            compute_expected_realized_pnl_cents,
            validate_canonical_intent,
            OrderIntentValidationError,
        )

        expected_before = pos.position_cc
        expected_after = expected_before + canonical.yes_delta()
        fee_cents = self._estimate_fee_cents(canonical.limit_cents, canonical.qty_cc)
        expected_pnl = compute_expected_realized_pnl_cents(
            purpose="close",
            qty_cc=canonical.qty_cc,
            limit_cents=canonical.limit_cents,
            contract=canonical.contract,
            position_before=expected_before,
            position_avg_price_cents=pos.avg_price_cents,
            position_side=pos.side,
            fee_cents=fee_cents,
        )

        fresh = replace(
            canonical,
            expected_position_before=expected_before,
            expected_position_after=expected_after,
            expected_realized_pnl_cents=expected_pnl,
        )
        # _re_validate is only used for exits; use the permissive exit budget.
        validate_canonical_intent(
            fresh,
            exchange_position_cc=pos.position_cc,
            position_avg_price_cents=pos.avg_price_cents,
            max_adverse_pnl_cents=_max_exit_adverse_pnl_cents(),
        )
        return fresh

    def _fetch_book(self, canonical: "CanonicalOrderIntent") -> Optional[BookDepth]:
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store

        store = get_kalshi_market_state_store()
        if store is None:
            return None

        state = store.get_unified(canonical.market_ticker) or store.get(canonical.market_ticker)
        if state is None:
            return None

        # Try the unified OrderbookSnapshot first, then KalshiMarketState raw ladders.
        book = getattr(state, "book", None)
        if book is not None:
            ts = getattr(book, "ts", 0) or 0
            seq = getattr(book, "seq", None)
        else:
            ts = getattr(state, "last_book_update_ts", 0) or 0
            seq = getattr(state, "book_sequence", None)

        # For a SELL the executable side is the held contract's bids.
        # For a BUY the executable side is the opposite contract's bids, translated
        # through YES+NO=100 to the held contract's ask (Kalshi binary duality).
        is_buy = canonical.action == "buy"
        if is_buy:
            source_contract = "no" if canonical.contract == "yes" else "yes"
        else:
            source_contract = canonical.contract

        raw_levels: List[Any] = []
        if book is not None:
            raw_levels = list(getattr(book, f"{source_contract}_bids", []) or [])
        else:
            raw_levels = list(getattr(state, f"{source_contract}_bids", []) or [])

        if not raw_levels:
            return None

        # Normalize to (contract_price_cents, size_contracts), best first.
        # For BUY, derive the held-contract price from the opposite-side bid.
        def _price(p: int) -> int:
            return (100 - int(p)) if is_buy else int(p)

        levels: List[Tuple[int, int]] = []
        for lvl in raw_levels:
            if isinstance(lvl, tuple) and len(lvl) >= 2:
                price, size = int(lvl[0]), int(lvl[1])
            elif hasattr(lvl, "price_cents") and hasattr(lvl, "size"):
                price, size = int(lvl.price_cents), int(lvl.size)
            else:
                continue
            if size > 0:
                levels.append((_price(price), size))

        if not levels:
            return None

        # Walk the book to fill the requested quantity (in contracts).
        requested_contracts = Decimal(canonical.qty_cc) / Decimal("100")
        remaining = requested_contracts
        filled_value = Decimal(0)
        available_cc = 0
        walked_levels: List[Tuple[int, int]] = []

        for price, size in levels:
            take_contracts = min(Decimal(size), remaining)
            if take_contracts <= 0:
                break
            filled_value += take_contracts * Decimal(price)
            remaining -= take_contracts
            take_cc = int(take_contracts * Decimal("100"))
            available_cc += take_cc
            walked_levels.append((price, take_cc))
            if remaining <= 0:
                break

        filled_contracts = requested_contracts - remaining
        if filled_contracts <= 0:
            return None

        # VWAP rounding must err against the exit's proceeds: a SELL
        # underestimates (FLOOR) so executability is judged on the worst-case
        # fill price; a BUY overestimates cost (CEIL). 2026-10-16 audit:
        # unconditional CEILING overstated sell-side VWAP by up to 1c.
        _vwap_round = ROUND_CEILING if canonical.action == "buy" else ROUND_FLOOR
        vwap_cents = int(
            (filled_value / filled_contracts).to_integral_value(rounding=_vwap_round)
        )

        # A book with no timestamp is UNKNOWN-stale, not fresh: market_state
        # treats ts<=0 as infinitely old, and reading it as age 0 here let an
        # uninitialized book pass the staleness check (2026-10-16 audit).
        if ts > 0:
            book_age_ms = max(0, int((time.monotonic() - ts) * 1000))
        else:
            book_age_ms = 2**31 - 1

        best_bid = levels[0][0] if not is_buy else None
        best_ask = levels[0][0] if is_buy else None
        # Deepest level consumed by the requested quantity — the price an
        # aggressive limit must reach to guarantee the full fill.
        marginal_price = walked_levels[-1][0] if walked_levels else None

        return BookDepth(
            vwap_cents=vwap_cents,
            available_qty_cc=available_cc,
            levels=walked_levels,
            best_bid_cents=best_bid,
            best_ask_cents=best_ask,
            book_age_ms=book_age_ms,
            book_sequence=seq,
            marginal_price_cents=marginal_price,
        )

    def _limit_executable(self, canonical: "CanonicalOrderIntent", book: BookDepth) -> bool:
        if canonical.action == "sell":
            return book.vwap_cents >= canonical.limit_cents
        return book.vwap_cents <= canonical.limit_cents

    def _apply_loss_policy(
        self,
        canonical: "CanonicalOrderIntent",
        pos: PositionSnapshot,
        book: BookDepth,
        expected_pnl: Optional[int],
        original_intent: Optional[Any] = None,
    ) -> Tuple[bool, str]:
        # Exits are risk-reducing and use a separate, permissive adverse-PnL
        # budget so that closing an underwater position is not blocked by the
        # tight entry budget (default 3 cents).
        if getattr(canonical, "purpose", None) == "close":
            max_adverse = _max_exit_adverse_pnl_cents()
        else:
            max_adverse = self._max_adverse_pnl_cents()
        # Forced exits (safety, stop, expiry, manual) are allowed to close at an
        # inherent loss; only discretionary profit exits are bound by the adverse
        # PnL budget.
        if not self._is_forced_exit(original_intent, canonical, pos):
            if expected_pnl is not None and expected_pnl < -max_adverse:
                return False, f"adverse_pnl:predicted={expected_pnl}:max=-{max_adverse}"
        elif expected_pnl is not None and expected_pnl < -max_adverse:
            logger.info(
                "[FIREWALL-FORCED-EXIT] ticker=%s reason=%s expected_pnl=%dc - "
                "adverse-PnL bound bypassed for forced exit",
                canonical.market_ticker,
                canonical.reason,
                expected_pnl,
            )

        max_slippage = self._max_slippage_cents()
        # The VWAP is the actual executable price across the requested size. It
        # must stay within the slippage budget of the best quote.
        if canonical.action == "sell":
            worst_acceptable = book.best_bid_cents - max_slippage
            if book.vwap_cents < worst_acceptable:
                return False, (
                    f"slippage_exceeded:vwap={book.vwap_cents}:"
                    f"best_bid={book.best_bid_cents}:slippage={max_slippage}"
                )
        else:
            # Buy exit: the worst price to pay is best_ask + slippage.
            if book.best_ask_cents is None:
                return False, "best_ask_unavailable_for_buy_exit"
            worst_acceptable = book.best_ask_cents + max_slippage
            if book.vwap_cents > worst_acceptable:
                return False, (
                    f"slippage_exceeded:vwap={book.vwap_cents}:"
                    f"best_ask={book.best_ask_cents}:slippage={max_slippage}"
                )

        return True, ""

    def _estimate_fee_cents(self, limit_cents: int, qty_cc: int) -> int:
        # Exact taker fee in cents for fractional contract counts.
        # fee_cents = ceil(rate * C * P * (1 - P) * 100)
        # where C is the contract count, P is the limit price in dollars.
        from config.kalshi_fee_schedule import get_active_fee_schedule

        contracts = Decimal(qty_cc) / Decimal("100")
        if contracts <= 0:
            return 0

        p = Decimal(limit_cents) / Decimal("100")
        parabolic = p * (Decimal("1") - p)
        rate = Decimal(str(get_active_fee_schedule().taker_rate))
        fee_exact = rate * contracts * parabolic * Decimal("100")
        fee = int(fee_exact.to_integral_value(rounding=ROUND_CEILING))
        return max(0, fee)

    def _is_forced_exit(
        self,
        original_intent: Optional[Any],
        canonical: "CanonicalOrderIntent",
        pos: Optional[PositionSnapshot] = None,
    ) -> bool:
        """Return True for exits that must bypass the adverse-PnL bound.

        Forced exits include manual operator close, safety/stop reasons, expiry
        liquidation, and time exits.  These are allowed to close at an inherent
        loss (the position is already underwater or the market is closing), but
        they are still subject to slippage and quantity invariants.
        """
        if self._manual_close_authorized(original_intent, canonical):
            return True
        # Structured authorization only (2026-10-17): a free-text reason may
        # describe a forced exit but can no longer *authorize* a deliberate
        # loss.  The adverse-PnL bound is bypassed only by the validated
        # exit_class/emergency_type/authorization_source/generation tuple.
        return self._structured_emergency_authorized(
            original_intent, canonical, pos
        )

    def _is_safety_or_manual_exit(
        self,
        original_intent: Optional[Any],
        canonical: "CanonicalOrderIntent",
        pos: Optional[PositionSnapshot] = None,
    ) -> bool:
        """Return True for safety/time-to-expiry/operator exits that may lack a fill id."""
        if self._manual_close_authorized(original_intent, canonical):
            return True
        _pstatus = (
            getattr(canonical, "parentage_status", None)
            or getattr(original_intent, "parentage_status", None)
        )
        if canonical.reduce_only and _pstatus in (
            "CANONICAL_FILL",
            "ORDER_LINKED",
            "SIGNAL_ONLY",
            "UNKNOWN",
        ):
            # Reduce-only safety exits for unknown/weak provenance are allowed.
            # Discretionary profit exits are blocked upstream by ExitPolicy/
            # PositionMonitor quarantine.  2026-10-17: free-text reasons no
            # longer authorize — the same structured model applies (class +
            # issuing source + generation consistency).  ``emergency_type``
            # is not required here: this check grants identity tolerance, not
            # loss-taking authority, which stays behind the full tuple.
            if self._structured_emergency_authorized(original_intent, canonical, pos):
                return True
            return self._structured_operational_authorized(
                original_intent, canonical, pos
            )
        return False

    def _resolve_parent_entry_fill_id(
        self,
        canonical: "CanonicalOrderIntent",
        original_intent: Optional[Any],
        pos: PositionSnapshot,
    ) -> Optional[str]:
        if canonical.parent_entry_fill_id:
            return canonical.parent_entry_fill_id
        if original_intent is not None and getattr(
            original_intent, "parent_entry_fill_id", None
        ):
            return original_intent.parent_entry_fill_id
        return pos.parent_entry_fill_id

    def _clamp_exit_limit(
        self, canonical: "CanonicalOrderIntent", book: BookDepth
    ) -> int:
        # For a sell exit we receive at least the limit; the VWAP is the worst
        # case we can guarantee. Clamp the approved limit to the VWAP so the
        # venue order is always within the firewall's bound.
        if canonical.action == "sell":
            return min(canonical.limit_cents, book.vwap_cents)
        return max(canonical.limit_cents, book.vwap_cents)

    # Emergency authorization tables live in the shared, versioned policy
    # module so the arbiter (proposal-time) and this firewall (submit-time)
    # evaluate identical rules — see merid/event_venues/kalshi/
    # exit_authorization.py (policy version exit-auth-v1).
    _LOSS_AUTHORIZED_EMERGENCY_TYPES = _xa.LOSS_AUTHORIZED_EMERGENCY_TYPES
    _EMERGENCY_TYPE_ISSUERS = _xa.EMERGENCY_TYPE_ISSUERS
    _OPERATIONAL_EXIT_ISSUERS = _xa.OPERATIONAL_EXIT_ISSUERS
    _MANUAL_CLOSE_ISSUERS = _xa.MANUAL_CLOSE_ISSUERS

    def _manual_close_authorized(
        self,
        original_intent: Optional[Any],
        canonical: "CanonicalOrderIntent",
    ) -> bool:
        """The operator manual-close flag is honored only from an operator
        issuer — an arbitrary producer cannot set the bit on its own intent
        to mint emergency authority."""
        if original_intent is None or not getattr(
            original_intent, "is_manual_emergency_close", False
        ):
            return False
        src = (
            getattr(original_intent, "authorization_source", None)
            or getattr(original_intent, "source", None)
            or getattr(original_intent, "agent_id", None)
            or getattr(canonical, "authorization_source", None)
            or ""
        ).strip()
        return src in self._MANUAL_CLOSE_ISSUERS

    def _is_min_proceeds_exempt(
        self,
        original_intent: Optional[Any],
        canonical: "CanonicalOrderIntent",
        pos: Optional[PositionSnapshot] = None,
    ) -> bool:
        """True only when the exit carries *structured* emergency
        authorization — never because the free-text reason names one.

        Required authorization tuple (validated here, independent of
        ``reason``):
          - ``exit_class`` in {emergency, operational}
          - ``emergency_type`` in ``_LOSS_AUTHORIZED_EMERGENCY_TYPES``
          - non-empty ``authorization_source`` (the controller that issued
            the exception — an exemption with no issuer is denied)
          - ``position_generation_id`` consistent with the position's
            resolved entry-fill generation when both are known

        ``is_manual_emergency_close`` on the original intent remains a
        separately-authorized operator path, honored only from an operator
        issuer.  Everything else — including a bare ``reason="hard_stop"`` —
        is an ordinary exit and carries the min-proceeds submission
        invariant.
        """
        if self._manual_close_authorized(original_intent, canonical):
            return True
        return self._structured_emergency_authorized(
            original_intent, canonical, pos, denied_log_tag="MIN-PROCEEDS"
        )

    def _structured_emergency_authorized(
        self,
        original_intent: Optional[Any],
        canonical: "CanonicalOrderIntent",
        pos: Optional[PositionSnapshot] = None,
        denied_log_tag: str = "EMERGENCY-AUTH",
    ) -> bool:
        """Validate the structured emergency-authorization tuple.

        This is authorization, not classification.  Required, all evaluated
        independently of ``reason``:
          - ``exit_class`` in {emergency, operational}
          - ``emergency_type`` in ``_LOSS_AUTHORIZED_EMERGENCY_TYPES``
          - ``authorization_source`` in the type's issuer allowlist
            (``_EMERGENCY_TYPE_ISSUERS``) — a producer cannot manufacture an
            emergency type outside its scope
          - ``position_generation_id`` non-empty AND equal to the position's
            resolved generation — two empty fields do not count as
            "consistent", and a position with no resolvable generation
            cannot receive loss-taking authority at all
          - requested quantity does not exceed the position's remaining
            quantity (the exception binds to this generation's exposure,
            not an arbitrary size)
        """
        def _field(name: str) -> Optional[str]:
            for src in (canonical, original_intent):
                v = getattr(src, name, None) if src is not None else None
                if v is not None and str(v).strip():
                    return str(v).strip()
            return None

        exit_class = (_field("exit_class") or "").lower()
        etype = (_field("emergency_type") or "").upper()
        source = _field("authorization_source")
        gen = _field("position_generation_id") or getattr(
            canonical, "parent_entry_fill_id", None
        )
        pos_gen = (
            getattr(pos, "parent_entry_fill_id", None) if pos is not None else None
        )

        issuer_scope = self._EMERGENCY_TYPE_ISSUERS.get(etype, frozenset())
        gen_bound = bool(gen) and bool(pos_gen) and gen == pos_gen
        qty_bound = pos is not None and canonical.qty_cc <= abs(
            getattr(pos, "position_cc", 0) or 0
        )

        authorized = (
            exit_class in ("emergency", "operational")
            and etype in self._LOSS_AUTHORIZED_EMERGENCY_TYPES
            and bool(source)
            and source in issuer_scope
            and gen_bound
            and qty_bound
        )
        if not authorized and (exit_class or etype or source):
            logger.warning(
                "[%s-EXEMPT-DENIED] intent=%s exit_class=%s "
                "emergency_type=%s source=%s gen=%s - structured emergency "
                "authorization incomplete; ordinary bounds apply",
                denied_log_tag,
                getattr(canonical, "intent_id", None),
                exit_class or None, etype or None, source, gen,
            )
        return authorized

    def _structured_operational_authorized(
        self,
        original_intent: Optional[Any],
        canonical: "CanonicalOrderIntent",
        pos: Optional[PositionSnapshot] = None,
    ) -> bool:
        """Structured authorization for identity-tolerance exemptions (e.g.
        the missing-parent-entry-fill bypass for safety exits).

        Same model as ``_structured_emergency_authorized`` minus
        ``emergency_type``: the caller is asking to proceed despite weak
        provenance, not to take a loss.  Requires a declared operational /
        emergency class and a non-empty issuing source; generation is
        enforced only when both sides are known (this path exists precisely
        for exits whose parent linkage is UNKNOWN).
        """
        def _field(name: str) -> Optional[str]:
            for src in (canonical, original_intent):
                v = getattr(src, name, None) if src is not None else None
                if v is not None and str(v).strip():
                    return str(v).strip()
            return None

        exit_class = (_field("exit_class") or "").lower()
        source = _field("authorization_source")
        gen = _field("position_generation_id") or getattr(
            canonical, "parent_entry_fill_id", None
        )
        pos_gen = (
            getattr(pos, "parent_entry_fill_id", None) if pos is not None else None
        )
        return (
            exit_class in ("emergency", "operational")
            and bool(source)
            and source in self._OPERATIONAL_EXIT_ISSUERS
            # Generation consistency only when both are known — this path
            # exists precisely for UNKNOWN-parentage exits, and it grants no
            # loss-taking authority regardless.
            and (not gen or not pos_gen or gen == pos_gen)
        )

    def _fee_adjusted_floor_cents(
        self, entry_cents: int, proposed_limit_cents: int
    ) -> Optional[int]:
        """Fee-adjusted breakeven exit floor in held-side cents.

        floor = held-side entry + per-contract entry fee + per-contract exit
        fee at the proposed limit.  ``MERID_MIN_PROCEEDS_FEE_ADJUST=0`` reverts
        to the plain entry-price floor.
        """
        if not _env_bool("MERID_MIN_PROCEEDS_FEE_ADJUST", True):
            return entry_cents
        try:
            from merid.event_venues.kalshi.parabolic_fees import (
                kalshi_fee_cents_exact,
            )
            entry_fee = float(
                kalshi_fee_cents_exact(entry_cents / 100.0, 1, "taker")
            )
            exit_fee = float(
                kalshi_fee_cents_exact(proposed_limit_cents / 100.0, 1, "taker")
            )
            return int(math.ceil(entry_cents + entry_fee + exit_fee))
        except Exception:
            return entry_cents

    def _persisted_trail_lock_cents(
        self,
        ticker: str,
        generation_id: Optional[str] = None,
        held_outcome: Optional[str] = None,
    ) -> Optional[int]:
        """Held-side locked-profit price floor from the durable exit-state
        store (``ratchet_floor_price_cents``), or None.

        The lookup is lifecycle-exact: it requires the position's generation
        id (resolved ``parent_entry_fill_id``) and, when the record carries
        one, a matching ``held_outcome``.  A generationless lookup returns
        None rather than borrowing the newest live record for the ticker —
        an archived prior generation's locked floor must never leak into a
        new trade.
        """
        try:
            from merid.position_management.position_exit_state import (
                get_exit_state_store,
            )
            rec = get_exit_state_store().find_record(
                ticker,
                generation_id=generation_id,
                held_outcome=held_outcome,
                require_generation=True,
            )
            if not rec:
                return None
            lock = rec.get("ratchet_floor_price_cents")
            if lock is None:
                return None
            lock = int(lock)
            return lock if 1 <= lock <= 99 else None
        except Exception:
            return None

    def _deterministic_coid(
        self,
        canonical: "CanonicalOrderIntent",
        pos: Optional[PositionSnapshot],
        limit_cents: int,
        parent: Optional[str],
    ) -> str:
        # Prefer the already-finalized wire client_order_id when present so the
        # firewall decision record matches the actual venue idempotency key.
        if canonical.client_order_id:
            return canonical.client_order_id

        payload = {
            "ticker": canonical.market_ticker,
            "contract": canonical.contract,
            "action": canonical.action,
            "qty_cc": canonical.qty_cc,
            "limit_cents": limit_cents,
            "position_cc": pos.position_cc if pos else 0,
            "position_version": pos.version if pos else "",
            "parent_entry_fill_id": parent or "",
            "intent_id": canonical.intent_id or "",
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()
        base = f"ex_{canonical.market_ticker}_{canonical.contract}_{digest[:20]}"
        if len(base) > 63:
            base = f"ex_{digest[:32]}_{digest[32:60]}"
        return base[:63]

    def _persist_decision(self, decision: FirewallDecision) -> None:
        self._decisions[decision.client_order_id] = decision
        # Bound the token map — drop anything older than an hour.  Decisions
        # are consumed on route; survivors are wedges the sweeper owns.
        try:
            if len(self._decisions) > 512:
                cutoff = time.time() - 3600.0
                for k in [k for k, d in self._decisions.items()
                          if d.created_at < cutoff]:
                    self._decisions.pop(k, None)
        except Exception:
            pass
        try:
            # 2026-09-30: quarantine test writes — pytest runs must never
            # append to the production decision ledger.
            _payload = decision.to_dict()
            _is_test = os.environ.get("PYTEST_CURRENT_TEST") is not None
            _payload["is_test"] = bool(_is_test)
            _payload.setdefault("environment", os.environ.get("MERID_ENV", "production"))
            _log_dir = os.environ.get("MERID_ORDER_DECISIONS_DIR") or "logs"
            os.makedirs(_log_dir, exist_ok=True)
            _fname = "order_decisions_test.jsonl" if _is_test else "order_decisions.jsonl"
            with open(os.path.join(_log_dir, _fname), "a") as f:
                f.write(json.dumps(_payload, default=str, sort_keys=True) + "\n")
        except Exception as exc:
            logger.debug("[FIREWALL] persist_decision failed: %s", exc)

    def _max_quote_age_ms(self) -> int:
        # Aligned with loop_15m / position_monitor quote-age gating (10s default).
        return _env_int("MERID_EXIT_MAX_QUOTE_AGE_MS", 10000)

    def _max_position_age_ms(self) -> int:
        # Exchange-position snapshots may be as stale as the REST refresh cycle;
        # use the same 10s default as quote age to avoid false-positive rejections.
        return _env_int("MERID_EXIT_MAX_POSITION_AGE_MS", 10000)

    def _exit_liveness_reserve_seconds(self) -> int:
        # Minimum seconds-to-expiry required before an exit is allowed to proceed.
        # This prevents a stale-snapshot exception from submitting an order after
        # Kalshi has already closed the market.  25s is a conservative initial
        # production value that exceeds the ~13s post-close incident path; it
        # should be tightened once p99 submission latency is measured.
        return _env_int("MERID_EXIT_LIVENESS_RESERVE_SECONDS", 25)

    def _is_reduce_only_fallback_eligible(
        self, canonical: "CanonicalOrderIntent"
    ) -> bool:
        return (
            canonical.purpose == "close"
            and bool(canonical.reduce_only)
            and canonical.qty_cc > 0
            and not canonical.allow_short
        )

    def _in_flight_exit_lookback_seconds(self) -> float:
        return _env_float("MERID_EXIT_IN_FLIGHT_LOOKBACK_SECONDS", 120.0)

    def _has_in_flight_exit(
        self, canonical: "CanonicalOrderIntent"
    ) -> Optional[Any]:
        """Detect an unresolved exit attempt for the same ticker within the lookback.

        Returns the most recent matching ``OrderAttemptRecord`` or ``None``.
        This is intentionally defensive: it also rejects an ``ACKNOWLEDGED`` resting
        exit because two concurrent exits can over-close a position.
        """
        try:
            from merid.event_venues.kalshi.order_attempt_store import OrderAttemptStore

            lookback = self._in_flight_exit_lookback_seconds()
            attempts = OrderAttemptStore().get_unresolved(lookback_seconds=lookback)
            if not attempts:
                return None

            # get_unresolved returns oldest-first; the newest unresolved is the
            # relevant one because it is most likely to still be in flight.
            for attempt in reversed(attempts):
                if self._attempt_is_exit_for(attempt, canonical.market_ticker):
                    return attempt
            return None
        except Exception as exc:
            # Fail-open is the intended fallback, but silently degrading the
            # duplicate-exit guard is exactly the 2026-09-01 incident class —
            # make it loud so the wedge is visible in telemetry.
            logger.warning(
                "[FIREWALL-INFLIGHT-CHECK-FAILED] ticker=%s intent_id=%s "
                "duplicate-exit dedup unavailable, proceeding fail-open: %s",
                canonical.market_ticker, canonical.intent_id, exc,
            )
            return None

    def _attempt_is_exit_for(
        self, attempt: Any, ticker: str
    ) -> bool:
        """Return True when an unresolved attempt is an exit for ``ticker``."""
        # If the payload contains an explicit ticker, prefer it.
        try:
            if attempt.payload_json:
                payload = json.loads(attempt.payload_json) if isinstance(attempt.payload_json, str) else attempt.payload_json
            else:
                payload = {}
        except Exception:
            payload = {}

        attempt_ticker = (
            payload.get("ticker")
            or payload.get("market_ticker")
            or payload.get("market_id")
            or ""
        )

        # Fall back to the client_tag / intent_id naming convention used by the router.
        is_exit = (
            payload.get("entry_or_exit") == "exit"
            or payload.get("is_exit") is True
            or (attempt.intent_id or "").startswith("intent_exit_")
            or (attempt.client_tag or "").startswith("exit_")
        )

        # When the payload contains a ticker, it must match exactly.  When it does
        # not, we require a strong exit label match and assume the caller already
        # scoped by the canonical ticker.
        if attempt_ticker:
            return attempt_ticker == ticker and is_exit
        return is_exit and (ticker in (attempt.intent_id or "") or ticker in (attempt.client_tag or ""))

    def _market_active_and_before_deadline(self, ticker: str) -> bool:
        try:
            from merid.event_venues.kalshi.market_state import (
                get_kalshi_market_state_store,
            )

            store = get_kalshi_market_state_store()
            if store is None:
                return False
            state = store.get_unified(ticker) or store.get(ticker)
            if state is None:
                return False
            if getattr(state, "status", "open").lower() != "open":
                return False

            seconds_to_expiry = getattr(state, "seconds_to_expiry", None)

            # If Kalshi did not publish a seconds_to_expiry, derive it from the
            # authoritative close/expiry time when one is available.  For
            # reduce-only exits this is the required fallback; for any exit it
            # is the canonical no-submission-after-close guard.
            if seconds_to_expiry is None or not isinstance(seconds_to_expiry, (int, float)):
                expiry_str = (
                    getattr(state, "expected_expiration_time", None)
                    or getattr(state, "expiration_time", None)
                )
                if not expiry_str:
                    # Missing both TTE and a close time: fail closed rather than
                    # submit into an unknown market state.
                    logger.warning(
                        "[FIREWALL-LIVENESS] %s has no expiry metadata; rejecting submission",
                        ticker,
                    )
                    return False
                try:
                    expiry_dt = datetime.fromisoformat(
                        str(expiry_str).replace("Z", "+00:00")
                    )
                    if expiry_dt.tzinfo is None:
                        expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
                    seconds_to_expiry = (expiry_dt - datetime.now(timezone.utc)).total_seconds()
                except Exception as parse_exc:
                    logger.warning(
                        "[FIREWALL-LIVENESS] %s could not parse expiry=%r: %s",
                        ticker,
                        expiry_str,
                        parse_exc,
                    )
                    return False

            return seconds_to_expiry > self._exit_liveness_reserve_seconds()
        except Exception as exc:
            logger.debug(
                "[FIREWALL] market liveness check failed for %s: %s", ticker, exc
            )
            return False

    def _fetch_local_position(self, ticker: str) -> Optional[PositionSnapshot]:
        """Build a position snapshot from the immutable local fills ledger."""
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        from merid.event_venues.kalshi.position_cache import get_position_cache
        from merid.event_venues.kalshi.binary_price_space import from_signed_yes_exposure

        try:
            ledger = get_fills_ledger()
            if ledger is not None:
                pos_dict = ledger.compute_position_from_fills(ticker)
                if pos_dict:
                    signed_yes = pos_dict.get("signed_yes_exposure", 0)
                    if signed_yes == 0:
                        return None
                    side = pos_dict.get("side")
                    if side is None:
                        side, _ = from_signed_yes_exposure(signed_yes)
                    avg_price = pos_dict.get("avg_price_cents")
                    payload = f"{ticker}:{signed_yes}:{avg_price or 0}"
                    version = hashlib.sha256(
                        payload.encode("utf-8")
                    ).hexdigest()[:16]
                    return PositionSnapshot(
                        position_cc=signed_yes,
                        side=side,
                        avg_price_cents=avg_price,
                        version=f"fills_ledger:{version}",
                        snapshot_age_ms=0,
                        parent_entry_fill_id=None,
                    )
        except Exception as exc:
            logger.warning(
                "[FIREWALL-LOCAL-POS] fills_ledger fallback failed for %s: %s",
                ticker,
                exc,
            )

        try:
            cache = get_position_cache()
            if cache is not None:
                cached = cache.get_position(ticker)
                if cached is not None:
                    qty = cached._yes_exposure()
                    if qty == 0:
                        return None
                    side = getattr(cached, "side", None) or getattr(
                        cached, "thesis_side", None
                    )
                    if side is None:
                        side, _ = from_signed_yes_exposure(qty)
                    return PositionSnapshot(
                        position_cc=qty,
                        side=side,
                        avg_price_cents=getattr(cached, "avg_price_cents", None),
                        version=f"position_cache:{getattr(cached, 'position_version', '')}",
                        snapshot_age_ms=0,
                        parent_entry_fill_id=getattr(cached, "entry_fill_id", None),
                    )
        except Exception as exc:
            logger.warning(
                "[FIREWALL-LOCAL-POS] position_cache fallback failed for %s: %s",
                ticker,
                exc,
            )

        return None

    def _local_position_supports_exit(
        self, local_pos: PositionSnapshot, canonical: "CanonicalOrderIntent"
    ) -> bool:
        if local_pos.position_cc == 0 or local_pos.side is None:
            return False
        order_delta = canonical.yes_delta()
        if order_delta == 0:
            return False
        # Reduce-only: order delta must oppose the local position and not exceed it.
        if order_delta * local_pos.position_cc >= 0:
            return False
        if abs(order_delta) > abs(local_pos.position_cc):
            return False
        return True

    def _max_adverse_pnl_cents(self) -> int:
        return _env_int("MERID_MAX_ADVERSE_PNL_CENTS", 3)

    def _max_slippage_cents(self) -> int:
        return _env_int("MERID_EXIT_MAX_SLIPPAGE_CENTS", 3)
