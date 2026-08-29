"""Stop-candidate execution reducer and replay hooks.

The reducer converts a validated ``StopCandidate`` into a reduce-only, bounded
exit order, keyed by position id/version, and idempotent against partial fills,
duplicate triggers, and retry races.  It is kept separate from the legacy
``maybe_submit_stop_candidate`` live path while it is being proven by the replay
harness; once the harness and canary pass it can be wired in.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional, Tuple

from utils.logger import get_logger

from merid.config.live_config import get_resolved_live_config
from merid.event_venues.kalshi.binary_price_space import (
    from_signed_yes_exposure,
    to_kalshi_side,
)
from merid.event_venues.kalshi.stop_candidate import (
    PRICE_STOP_TRIGGER_REASONS,
    STOP_MAX_SLIPPAGE_CENTS,
    StopCandidate,
    StopOrderInvariantError,
    evaluate_edge_stop,
    settlement_phase_allows_stop,
    stop_submission_enabled,
    validate_stop_order_invariants,
)

logger = get_logger("merid.event_venues.kalshi.stop_candidate_reducer")


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name, "").lower()
    return val in ("1", "true", "yes", "on") if val else default


# Default operational limits for the contingency sequence.
MAX_RETRY_ATTEMPTS = int(os.getenv("MERID_STOP_REDUCER_MAX_RETRY", "2"))
RETRY_BACKOFF_SECONDS = float(os.getenv("MERID_STOP_REDUCER_RETRY_BACKOFF", "0.5"))


@dataclass(frozen=True)
class ReducerResult:
    """Terminal outcome of a reducer attempt."""

    status: str  # submitted, duplicate, no_position, stale_position, escalated, rejected
    order_result: Optional[Any] = None
    intent: Optional[Any] = None
    reason: Optional[str] = None
    candidate_id: str = ""
    position_key: str = ""
    attempts: int = 0

    @property
    def terminal(self) -> bool:
        return self.status in {
            "submitted",
            "no_position",
            "stale_position",
            "escalated",
            "rejected",
            "duplicate",
        }


@dataclass
class StopCandidateAttemptRecord:
    """One reducer attempt for replay/audit."""

    attempt_id: str
    candidate_id: str
    position_key: str
    status: str
    reason: Optional[str]
    submitted_at: float
    order_result: Optional[Dict[str, Any]] = None
    intent: Optional[Dict[str, Any]] = None


# Default dependency functions (can be overridden in tests / replay).
async def _default_fetch_position(
    ticker: str, timeout: float = 1.0, fallback_to_cache: bool = True
) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    from merid.event_venues.kalshi.order_intent_contract import fetch_fresh_signed_yes_exposure

    return await fetch_fresh_signed_yes_exposure(ticker, timeout, fallback_to_cache)


async def _default_cancel_order(order_id: str) -> Any:
    from merid.event_venues.kalshi.client import get_kalshi_client

    client = get_kalshi_client()
    if client is None:
        raise RuntimeError("Kalshi client not available")
    return await client.cancel_order(order_id)


async def _default_get_open_orders(ticker: Optional[str] = None) -> List[Any]:
    from merid.event_venues.kalshi.client import get_kalshi_client

    client = get_kalshi_client()
    if client is None:
        return []
    return await client.get_open_orders(ticker)


async def _default_route_order(intent: Any) -> Any:
    from merid.event_venues.kalshi.order_router import route_order_async

    return await route_order_async(intent)


@dataclass
class StopCandidateExecutionReducer:
    """Reduce a validated StopCandidate to a single, bounded, reduce-only exit.

    The reducer is designed to be injected with fetch/cancel/submit callables so
    the replay harness can replace them with deterministic actors.
    """

    fetch_position: Callable[..., Awaitable[Tuple[Optional[int], Optional[int], Optional[str]]]] = field(
        default_factory=lambda: _default_fetch_position
    )
    get_open_orders: Callable[..., Awaitable[List[Any]]] = field(
        default_factory=lambda: _default_get_open_orders
    )
    cancel_order: Callable[..., Awaitable[Any]] = field(
        default_factory=lambda: _default_cancel_order
    )
    submit_order: Callable[..., Awaitable[Any]] = field(
        default_factory=lambda: _default_route_order
    )
    max_retry_attempts: int = MAX_RETRY_ATTEMPTS
    retry_backoff_seconds: float = RETRY_BACKOFF_SECONDS
    shadow_mode: bool = False

    _locks: Dict[str, asyncio.Lock] = field(default_factory=dict, repr=False)
    _attempts: Dict[str, List[StopCandidateAttemptRecord]] = field(default_factory=dict, repr=False)

    def position_key(self, candidate: StopCandidate) -> str:
        """Return a stable key for the position being exited.

        The key combines the ticker, the held side, and the absolute position
        size in centi-contracts.  A partial fill creates a new key (smaller
        size), which is the desired behavior: the reducer may close the
        remainder on a new trigger.
        """
        side = candidate.held_contract or from_signed_yes_exposure(candidate.position_from_exchange_cc)[0]
        qty = abs(candidate.position_from_exchange_cc)
        return f"{candidate.market_ticker}:{side}:{qty}"

    def _get_lock(self, position_key: str) -> asyncio.Lock:
        if position_key not in self._locks:
            self._locks[position_key] = asyncio.Lock()
        return self._locks[position_key]

    def _record(
        self,
        position_key: str,
        candidate: StopCandidate,
        status: str,
        reason: Optional[str],
        order_result: Optional[Any] = None,
        intent: Optional[Any] = None,
    ) -> None:
        """Append an attempt record for replay/audit."""
        record = StopCandidateAttemptRecord(
            attempt_id=f"sa-{uuid.uuid4().hex[:12]}",
            candidate_id=candidate.candidate_id,
            position_key=position_key,
            status=status,
            reason=reason,
            submitted_at=time.time(),
            order_result=_serialize(order_result) if order_result is not None else None,
            intent=_serialize_intent(intent) if intent is not None else None,
        )
        self._attempts.setdefault(position_key, []).append(record)
        logger.info(
            "[STOP-CANDIDATE-REDUCER] candidate=%s key=%s status=%s reason=%s",
            candidate.candidate_id,
            position_key,
            status,
            reason,
        )

    async def reduce(
        self,
        candidate: StopCandidate,
        *,
        force: bool = False,
        shadow_mode: bool = False,
    ) -> ReducerResult:
        """Convert ``candidate`` into one reduce-only exit order.

        Returns a terminal ``ReducerResult``.  The reducer guarantees at most one
        live submission per ``position_key`` at a time; duplicate concurrent
        triggers are rejected with ``status=duplicate``.

        ``shadow_mode=True`` runs the full position/validation pipeline but does
        not call cancel or submit.  It is used to confirm the intent matches the
        replay prediction before any real order is sent.
        """
        key = self.position_key(candidate)
        lock = self._get_lock(key)

        # In shadow mode the reducer still runs even though the live submission
        # flag is off, because the purpose is to produce and log the intent.
        if not shadow_mode and not force:
            try:
                resolved = get_resolved_live_config(allow_unresolved=True)
                if resolved.resolved and not resolved.stop_candidate_submission_enabled:
                    self._record(key, candidate, "rejected", "stop_candidate_submission_disabled_in_resolved_config")
                    return ReducerResult(
                        status="rejected",
                        reason="stop_candidate_submission_disabled_in_resolved_config",
                        candidate_id=candidate.candidate_id,
                        position_key=key,
                    )
            except Exception:
                pass
            if not stop_submission_enabled() or _env_bool("MERID_STOP_SUBMISSION_KILL", False):
                reason = (
                    "stop_candidate_submission_kill_switch"
                    if _env_bool("MERID_STOP_SUBMISSION_KILL", False)
                    else "stop_candidate_submission_disabled"
                )
                self._record(key, candidate, "rejected", reason)
                return ReducerResult(
                    status="rejected",
                    reason=reason,
                    candidate_id=candidate.candidate_id,
                    position_key=key,
                )

        async with lock:
            # Idempotency: if another attempt for this position version is already
            # in flight under this same lock, this must be a duplicate.  The lock
            # itself serializes per key, so any concurrent call is blocked here;
            # the first one through makes the submission.  We still check explicit
            # in_flight attempts to surface a clear duplicate reason.
            if self._has_in_flight_attempt(key):
                self._record(key, candidate, "duplicate", "stop_candidate_position_version_in_flight")
                return ReducerResult(
                    status="duplicate",
                    reason="stop_candidate_position_version_in_flight",
                    candidate_id=candidate.candidate_id,
                    position_key=key,
                )

            return await self._reduce_locked(candidate, key, shadow_mode=shadow_mode)

    def _has_in_flight_attempt(self, position_key: str) -> bool:
        """Return True if there is an attempt for ``position_key`` with no terminal order result.

        Because this is called inside the position lock, "in flight" means an
        attempt record exists that was created during the current process but has
        not yet been completed.  After restart there are no in-memory records, so
        the reducer falls back to querying open orders before submitting.
        """
        for attempt in self._attempts.get(position_key, []):
            if attempt.status == "in_flight":
                return True
        return False

    def _has_submitted_for_position(self, position_key: str) -> bool:
        """Return True if this position version already produced a live submission.

        A successful submission (``status="submitted"``) means a venue-bound exit
        was accepted or filled for this position version.  Subsequent triggers for
        the same version are treated as duplicates to avoid double-sells.  A
        partial fill changes the position size and therefore the key, so the
        remainder is still eligible to exit.
        """
        for attempt in self._attempts.get(position_key, []):
            if attempt.status == "submitted":
                return True
        return False

    async def _reduce_locked(
        self,
        candidate: StopCandidate,
        key: str,
        shadow_mode: bool = False,
    ) -> ReducerResult:
        """Core reduction logic; must be called under the position lock."""
        # Idempotency: if a submission for this position version is already in
        # flight or has already been accepted by the venue, this is a duplicate.
        if self._has_in_flight_attempt(key):
            self._record(key, candidate, "duplicate", "stop_candidate_position_version_in_flight")
            return ReducerResult(
                status="duplicate",
                reason="stop_candidate_position_version_in_flight",
                candidate_id=candidate.candidate_id,
                position_key=key,
            )
        if self._has_submitted_for_position(key):
            self._record(key, candidate, "duplicate", "stop_candidate_position_version_already_submitted")
            return ReducerResult(
                status="duplicate",
                reason="stop_candidate_position_version_already_submitted",
                candidate_id=candidate.candidate_id,
                position_key=key,
            )

        # Mark an in_flight record so concurrent calls inside the same lock see a
        # duplicate.  (The lock itself prevents true concurrency, but this gives
        # the replay harness a durable view of the attempt lifecycle.)
        in_flight_id = f"sa-{uuid.uuid4().hex[:12]}"
        in_flight = StopCandidateAttemptRecord(
            attempt_id=in_flight_id,
            candidate_id=candidate.candidate_id,
            position_key=key,
            status="in_flight",
            reason=None,
            submitted_at=time.time(),
        )
        self._attempts.setdefault(key, []).append(in_flight)

        # 1. Fetch open orders and cancel any conflicting exit for this ticker.
        #    In the contingency sequence, cancel-before-refresh prevents the
        #    reducer from submitting a second exit while an old stop order is
        #    still resting (e.g. after a restart or a race).  In shadow mode we
        #    skip this because no order will be submitted.
        if not shadow_mode:
            try:
                open_orders = await self.get_open_orders(candidate.market_ticker)
                held_side = candidate.held_contract or from_signed_yes_exposure(candidate.position_from_exchange_cc)[0]
                for order in open_orders:
                    order_side = getattr(order, "side", None) or getattr(order, "contract", None)
                    action = getattr(order, "action", "sell")
                    ticker = getattr(order, "market_id", None) or getattr(order, "ticker", None)
                    if (
                        ticker == candidate.market_ticker
                        and action == "sell"
                        and order_side == held_side
                    ):
                        order_id = getattr(order, "order_id", None)
                        if order_id:
                            logger.info(
                                "[STOP-CANDIDATE-REDUCER] cancelling conflicting open order %s for %s",
                                order_id,
                                key,
                            )
                            await self.cancel_order(order_id)
            except Exception as exc:
                self._complete_attempt(key, in_flight_id, "escalated", f"cancel_conflicting_orders_failed:{exc}")
                return ReducerResult(
                    status="escalated",
                    reason=f"cancel_conflicting_orders_failed:{exc}",
                    candidate_id=candidate.candidate_id,
                    position_key=key,
                    attempts=len(self._attempts.get(key, [])),
                )

        # 2. Authoritative position refresh.
        try:
            exchange_position_cc, avg_price_cents, position_side = await self.fetch_position(
                candidate.market_ticker, timeout=1.0, fallback_to_cache=True
            )
        except Exception as exc:
            self._complete_attempt(key, in_flight_id, "escalated", f"position_refresh_failed:{exc}")
            return ReducerResult(
                status="escalated",
                reason=f"position_refresh_failed:{exc}",
                candidate_id=candidate.candidate_id,
                position_key=key,
                attempts=len(self._attempts.get(key, [])),
            )

        if exchange_position_cc is None:
            self._complete_attempt(key, in_flight_id, "escalated", "position_refresh_unavailable")
            return ReducerResult(
                status="escalated",
                reason="position_refresh_unavailable",
                candidate_id=candidate.candidate_id,
                position_key=key,
                attempts=len(self._attempts.get(key, [])),
            )

        if exchange_position_cc == 0:
            self._complete_attempt(key, in_flight_id, "no_position", "exchange_position_flat")
            return ReducerResult(
                status="no_position",
                reason="exchange_position_flat",
                candidate_id=candidate.candidate_id,
                position_key=key,
                attempts=len(self._attempts.get(key, [])),
            )

        # The candidate side must match the authoritative position sign.  If the
        # position has flipped, the candidate is stale and must not be used.
        candidate_side = candidate.held_contract or from_signed_yes_exposure(candidate.position_from_exchange_cc)[0]
        fresh_side, fresh_qty = from_signed_yes_exposure(exchange_position_cc)
        if candidate_side != fresh_side or fresh_qty <= 0:
            self._complete_attempt(
                key,
                in_flight_id,
                "stale_position",
                f"position_sign_changed:candidate={candidate_side}:fresh={fresh_side}:qty={fresh_qty}",
            )
            return ReducerResult(
                status="stale_position",
                reason=f"position_sign_changed:candidate={candidate_side}:fresh={fresh_side}:qty={fresh_qty}",
                candidate_id=candidate.candidate_id,
                position_key=key,
                attempts=len(self._attempts.get(key, [])),
            )

        # 3. Settlement / phase gating.
        allowed, gate_reason = settlement_phase_allows_stop(
            candidate.seconds_to_expiry,
            candidate.trigger_reason,
            candidate.consecutive_edge_below,
        )
        if not allowed:
            self._complete_attempt(key, in_flight_id, "rejected", f"settlement_gate:{gate_reason}")
            return ReducerResult(
                status="rejected",
                reason=f"settlement_gate:{gate_reason}",
                candidate_id=candidate.candidate_id,
                position_key=key,
                attempts=len(self._attempts.get(key, [])),
            )

        # Edge gating (price/operational stops bypass the model-fair check).
        is_price_stop = candidate.trigger_reason in PRICE_STOP_TRIGGER_REASONS
        if not is_price_stop:
            if candidate.fair_value_cents is None:
                self._complete_attempt(key, in_flight_id, "rejected", "stop_candidate_no_fair_value")
                return ReducerResult(
                    status="rejected",
                    reason="stop_candidate_no_fair_value",
                    candidate_id=candidate.candidate_id,
                    position_key=key,
                    attempts=len(self._attempts.get(key, [])),
                )
            if not evaluate_edge_stop(
                candidate.fair_value_cents,
                candidate.executable_exit_cents,
                candidate.total_exit_cost_cents,
                candidate.hysteresis_cents,
            ):
                self._complete_attempt(key, in_flight_id, "rejected", "stop_candidate_edge_not_breached")
                return ReducerResult(
                    status="rejected",
                    reason="stop_candidate_edge_not_breached",
                    candidate_id=candidate.candidate_id,
                    position_key=key,
                    attempts=len(self._attempts.get(key, [])),
                )

        # 4. Build the bounded IOC exit intent and its canonical contract.
        intent, canonical, build_reason = self._build_exit_intent(
            candidate, exchange_position_cc, avg_price_cents, fresh_side
        )
        if intent is None or canonical is None:
            self._complete_attempt(key, in_flight_id, "rejected", build_reason)
            return ReducerResult(
                status="rejected",
                reason=build_reason,
                candidate_id=candidate.candidate_id,
                position_key=key,
                attempts=len(self._attempts.get(key, [])),
            )

        # 5. Validate stop invariants against the canonical contract.
        try:
            market_close_time = None
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store

            store = get_kalshi_market_state_store()
            kalshi = store.get(candidate.market_ticker)
            if kalshi and getattr(kalshi, "expected_expiration_time", None):
                try:
                    market_close_time = datetime.fromisoformat(str(kalshi.expected_expiration_time))
                    if market_close_time.tzinfo is None:
                        market_close_time = market_close_time.replace(tzinfo=timezone.utc)
                except Exception:
                    pass
            validate_stop_order_invariants(
                canonical,
                exchange_position_cc=exchange_position_cc,
                market_close_time=market_close_time,
                quote_age_ms=candidate.quote_age_ms,
                position_snapshot_age_ms=candidate.position_snapshot_age_ms,
                seconds_to_expiry=candidate.seconds_to_expiry,
            )
        except StopOrderInvariantError as exc:
            self._complete_attempt(key, in_flight_id, "rejected", f"stop_order_invariant:{exc}")
            return ReducerResult(
                status="rejected",
                reason=f"stop_order_invariant:{exc}",
                candidate_id=candidate.candidate_id,
                position_key=key,
                attempts=len(self._attempts.get(key, [])),
            )

        # Shadow mode: the intent is valid, but we stop before any outbound
        # cancel or submit.  Record it and return so the canary can compare
        # against replay predictions.
        if shadow_mode:
            self._complete_attempt(key, in_flight_id, "shadow", None, None, intent)
            return ReducerResult(
                status="shadow",
                intent=intent,
                reason=None,
                candidate_id=candidate.candidate_id,
                position_key=key,
                attempts=len(self._attempts.get(key, [])),
            )

        # 6. Submit with a bounded retry loop.
        last_result: Optional[Any] = None
        for attempt in range(1, self.max_retry_attempts + 1):
            try:
                last_result = await self.submit_order(intent)
            except Exception as exc:
                last_result = None
                last_reason = f"submit_exception:{exc}"
                logger.warning(
                    "[STOP-CANDIDATE-REDUCER] submit attempt %d/%d failed for %s: %s",
                    attempt,
                    self.max_retry_attempts,
                    key,
                    exc,
                )
                if attempt < self.max_retry_attempts:
                    await asyncio.sleep(self.retry_backoff_seconds)
                    # Re-fetch position before retry so we do not resubmit against a
                    # stale size.
                    try:
                        exchange_position_cc, avg_price_cents, _ = await self.fetch_position(
                            candidate.market_ticker, timeout=1.0, fallback_to_cache=True
                        )
                        if exchange_position_cc is None or exchange_position_cc == 0:
                            self._complete_attempt(
                                key,
                                in_flight_id,
                                "no_position",
                                f"position_flat_during_retry:attempt={attempt}",
                            )
                            return ReducerResult(
                                status="no_position",
                                reason=f"position_flat_during_retry:attempt={attempt}",
                                candidate_id=candidate.candidate_id,
                                position_key=key,
                                attempts=attempt,
                            )
                        fresh_side, fresh_qty = from_signed_yes_exposure(exchange_position_cc)
                        if candidate_side != fresh_side or fresh_qty <= 0:
                            self._complete_attempt(
                                key,
                                in_flight_id,
                                "stale_position",
                                f"position_sign_changed_during_retry:attempt={attempt}",
                            )
                            return ReducerResult(
                                status="stale_position",
                                reason=f"position_sign_changed_during_retry:attempt={attempt}",
                                candidate_id=candidate.candidate_id,
                                position_key=key,
                                attempts=attempt,
                            )
                        # Rebuild intent with the new position size.
                        intent, _, build_reason = self._build_exit_intent(
                            candidate, exchange_position_cc, avg_price_cents, fresh_side
                        )
                        if intent is None:
                            self._complete_attempt(
                                key,
                                in_flight_id,
                                "rejected",
                                f"rebuild_intent_failed_during_retry:{build_reason}",
                            )
                            return ReducerResult(
                                status="rejected",
                                reason=f"rebuild_intent_failed_during_retry:{build_reason}",
                                candidate_id=candidate.candidate_id,
                                position_key=key,
                                attempts=attempt,
                            )
                    except Exception as refresh_exc:
                        self._complete_attempt(key, in_flight_id, "escalated", f"retry_refresh_failed:{refresh_exc}")
                        return ReducerResult(
                            status="escalated",
                            reason=f"retry_refresh_failed:{refresh_exc}",
                            candidate_id=candidate.candidate_id,
                            position_key=key,
                            attempts=attempt,
                        )
                continue

            if last_result is not None:
                status = _result_status(last_result)
                if status in ("filled_live", "partial_live", "filled_mock", "filled_paper", "submitted_live", "resting"):
                    self._complete_attempt(key, in_flight_id, "submitted", None, last_result, intent)
                    return ReducerResult(
                        status="submitted",
                        order_result=last_result,
                        intent=intent,
                        candidate_id=candidate.candidate_id,
                        position_key=key,
                        attempts=attempt,
                    )

            if attempt < self.max_retry_attempts:
                await asyncio.sleep(self.retry_backoff_seconds)
                last_reason = f"retry_after_unfilled_attempt:{attempt}"
            else:
                last_reason = f"max_retry_exceeded:status={_result_status(last_result)}"

        # After exhausting retries, escalate rather than leave the position unprotected.
        self._complete_attempt(
            key,
            in_flight_id,
            "escalated",
            last_reason or "max_retry_exceeded",
            last_result,
            intent,
        )
        return ReducerResult(
            status="escalated",
            order_result=last_result,
            intent=intent,
            reason=last_reason or "max_retry_exceeded",
            candidate_id=candidate.candidate_id,
            position_key=key,
            attempts=self.max_retry_attempts,
        )

    def _build_exit_intent(
        self,
        candidate: StopCandidate,
        exchange_position_cc: int,
        position_avg_price_cents: Optional[int],
        held_side: Literal["yes", "no"],
    ) -> Tuple[Optional[Any], Optional[Any], str]:
        """Return (OrderIntent, canonical, reason).  reason="ok" on success."""
        from merid.event_venues.kalshi.order_intent_contract import (
            OrderIntentValidationError,
            normalize_order,
        )
        from merid.event_venues.kalshi.order_router import OrderIntent
        from merid.event_venues.kalshi.position_cache import get_position_cache

        fresh_qty = abs(exchange_position_cc)
        candidate_qty = abs(candidate.position_from_exchange_cc)
        qty_cc = min(candidate_qty, fresh_qty)
        if qty_cc <= 0:
            return None, None, "stop_candidate_no_held_position"

        # Whole contracts only for the order count; fractional remainders are not
        # submitted.  This is consistent with the existing stop path.
        if qty_cc % 100 != 0:
            return None, None, "stop_candidate_fractional_qty"

        held_contracts = qty_cc // 100

        exit_bid = candidate.executable_exit_cents
        if exit_bid is None or not (1 <= exit_bid <= 99):
            from merid.event_venues.kalshi.stop_candidate import _get_executable_exit_cents, _get_market_state

            kalshi, unified = _get_market_state(candidate.market_ticker)
            exit_bid = _get_executable_exit_cents(unified or kalshi, held_side)
            if exit_bid is None or not (1 <= exit_bid <= 99):
                return None, None, "stop_candidate_no_executable_price"

        exit_price = max(1, exit_bid - STOP_MAX_SLIPPAGE_CENTS)

        kalshi_side = to_kalshi_side(held_side, "sell")
        pre_contracts = fresh_qty // 100

        # Resolve durable parentage from the local cache.
        parentage_status = "UNKNOWN"
        parent_entry_fill_id: Optional[str] = None
        parent_entry_order_id: Optional[str] = None
        parent_entry_signal_id: Optional[str] = None
        exit_policy_id = f"stop_candidate_reducer:{candidate.candidate_id}"
        try:
            cache = get_position_cache()
            if cache is not None:
                cached_position = cache.get_position(candidate.market_ticker)
                if cached_position is not None:
                    if getattr(cached_position, "exit_policy_id", None):
                        exit_policy_id = cached_position.exit_policy_id
                    if getattr(cached_position, "entry_fill_id", None):
                        parent_entry_fill_id = cached_position.entry_fill_id
                        parentage_status = "CANONICAL_FILL"
                    if getattr(cached_position, "entry_order_id", None):
                        parent_entry_order_id = cached_position.entry_order_id
                        if parentage_status == "UNKNOWN":
                            parentage_status = "ORDER_LINKED"
                    elif getattr(cached_position, "client_order_id", None):
                        parent_entry_order_id = cached_position.client_order_id
                        if parentage_status == "UNKNOWN":
                            parentage_status = "ORDER_LINKED"
                    if getattr(cached_position, "entry_signal_id", None):
                        parent_entry_signal_id = cached_position.entry_signal_id
        except Exception:
            pass

        from merid.event_venues.kalshi.stop_candidate import _STOP_TRIGGER_TO_EXIT_REASON

        exit_reason = _STOP_TRIGGER_TO_EXIT_REASON.get(candidate.trigger_reason, "STOP_LOSS")

        intent = OrderIntent(
            ticker=candidate.market_ticker,
            side=held_side,
            action="sell",
            price_cents=exit_price,
            count=held_contracts,
            order_type="limit",
            time_in_force="ioc",
            source="stop_candidate_reducer",
            agent_id="stop_candidate_reducer",
            kalshi_side=kalshi_side,
            reduce_only=True,
            entry_or_exit="exit",
            exit_reason=exit_reason,
            exit_policy_id=exit_policy_id,
            pre_position_size=pre_contracts,
            expected_post_position_size=max(0, pre_contracts - held_contracts),
            reason=f"stop_loss:{candidate.trigger_reason}:{candidate.candidate_id}",
            rationale=f"stop_candidate_reducer:{candidate.trigger_reason}:{candidate.candidate_id}",
            parentage_status=parentage_status,
            parent_entry_fill_id=parent_entry_fill_id,
            parent_entry_order_id=parent_entry_order_id,
            parent_entry_signal_id=parent_entry_signal_id,
            snapshot_age_ms=float(candidate.quote_age_ms or 0),
        )

        try:
            from merid.event_venues.kalshi.order_intent_contract import validate_canonical_intent

            canonical = normalize_order(
                intent,
                exchange_position_cc=exchange_position_cc,
                position_avg_price_cents=position_avg_price_cents,
                position_side=held_side,
            )
            validate_canonical_intent(
                canonical,
                exchange_position_cc=exchange_position_cc,
                position_avg_price_cents=position_avg_price_cents,
            )
            return intent, canonical, "ok"
        except Exception as exc:
            return None, None, f"stop_candidate_canonical_validation_failed:{exc}"

    def _complete_attempt(
        self,
        position_key: str,
        attempt_id: str,
        status: str,
        reason: Optional[str],
        order_result: Optional[Any] = None,
        intent: Optional[Any] = None,
    ) -> None:
        """Update the in_flight attempt record to its terminal state."""
        for attempt in self._attempts.get(position_key, []):
            if attempt.attempt_id == attempt_id:
                attempt.status = status
                attempt.reason = reason
                attempt.order_result = _serialize(order_result) if order_result is not None else None
                attempt.intent = _serialize_intent(intent) if intent is not None else None
                break


def _result_status(result: Any) -> str:
    """Safe status extraction from an ``OrderResult`` or dict."""
    if result is None:
        return "none"
    return getattr(result, "status", None) or result.get("status", "unknown") if isinstance(result, dict) else getattr(result, "status", "unknown")


def _serialize(obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {}
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
    return {"repr": repr(obj)}


def _serialize_intent(intent: Any) -> Dict[str, Any]:
    d = _serialize(intent)
    # Include the canonical contract name for replay clarity.
    d.setdefault("contract", getattr(intent, "contract", None))
    return d


async def reduce_stop_candidate(
    candidate: StopCandidate,
    *,
    force: bool = False,
    **reducer_kwargs: Any,
) -> ReducerResult:
    """Convenience entry point using the default reducer singleton."""
    reducer = StopCandidateExecutionReducer(**reducer_kwargs)
    return await reducer.reduce(candidate, force=force)
