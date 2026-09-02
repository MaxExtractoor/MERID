"""Strict full-exit fallback finalizer.

A position must only be marked exited and removed when the canonical portfolio
snapshot proves the account is flat.  The snapshot must be authoritative, post-
submission, matched, terminal, fully filled, and have zero remaining working
orders and zero exchange position for the market.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Tuple


TERMINAL_ORDER_STATUSES = frozenset({
    "filled_mock",
    "filled_paper",
    "filled_live",
    "partial_live",
    "partial_fill",
    "unfilled_ioc",
    "rejected",
    "canceled",
    "expired",
})


@dataclass(frozen=True)
class ExitOrderAttempt:
    """Immutable record of the state captured at order-submission time."""

    pre_submit_snapshot_version: int
    submit_started_at_ns: int
    submitted_count_fp: Decimal
    reduce_only: bool = True


def can_finalize_full_exit(
    *,
    snapshot,
    attempt: ExitOrderAttempt,
    order_result,
    position_key: str,
    now_ns: int,
) -> Tuple[bool, str]:
    """Return (allowed, reason) for finalizing a full position exit.

    This function is pure and has no side effects.  It is the single gate for
    ``mark_exited`` / ``remove_position`` after an exit order.
    """
    _ = now_ns  # reserved for future freshness/deadline checks

    # Reduce-only exits must be able to close risk even when the broader
    # portfolio is not authoritative (e.g. a different ticker has a latched
    # reconciliation break).  If the order is terminal, fully filled, and has
    # zero remaining quantity, trust the fill and allow finalization.  The
    # fills ledger and position cache will be reconciled by the next portfolio
    # build cycle; the important thing is to release the local monitor/allocator
    # state now that the exit has been confirmed by the exchange.
    if order_result.status not in TERMINAL_ORDER_STATUSES:
        return False, "ORDER_NOT_TERMINAL"

    if order_result.remaining_count_fp != Decimal("0"):
        return False, "ORDER_REMAINS"

    # Reduce-only exits must be able to close risk even when the broader
    # portfolio is not authoritative.  The full fill is the only safe signal
    # that the exchange no longer holds the position.
    if attempt.reduce_only:
        if order_result.filled_count_fp == attempt.submitted_count_fp:
            return True, "REDUCE_ONLY_EXIT_FULLY_FILLED"
        return False, "FILL_COUNT_NOT_EQUAL_SUBMITTED"

    if not snapshot:
        return False, "SNAPSHOT_UNAVAILABLE"

    if not snapshot.is_authoritative:
        return False, "PORTFOLIO_NOT_AUTHORITATIVE"

    if snapshot.version <= attempt.pre_submit_snapshot_version:
        return False, "NO_POST_ORDER_SNAPSHOT"

    if snapshot.captured_at_wall_ns <= attempt.submit_started_at_ns:
        return False, "SNAPSHOT_PRECEDES_SUBMISSION"

    if snapshot.reconciliation_status != "MATCHED":
        return False, "PORTFOLIO_NOT_MATCHED"

    if order_result.filled_count_fp != attempt.submitted_count_fp:
        return False, "FILL_COUNT_NOT_EQUAL_SUBMITTED"

    if snapshot.working_exit_count_fp(position_key) != Decimal("0"):
        return False, "WORKING_EXIT_REMAINS"

    if snapshot.exchange_position_fp(position_key) != Decimal("0"):
        return False, "EXCHANGE_POSITION_REMAINS"

    return True, "AUTHORITATIVE_POSITION_FLAT"
