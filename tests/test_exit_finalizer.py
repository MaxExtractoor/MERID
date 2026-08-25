"""Tests for the strict full-exit finalizer.

These tests enforce that a position is only marked flat when the canonical
portfolio snapshot is authoritative, post-submission, matched, terminal, fully
filled, and proves zero remaining exposure.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from merid.event_venues.kalshi.canonical_portfolio import (
    CanonicalFill,
    CanonicalOrder,
    CanonicalPortfolioSnapshot,
    CanonicalPosition,
    ReconciliationReason,
    ReconciliationStatus,
    SourceCompleteness,
)
from merid.event_venues.kalshi.exit_finalizer import (
    ExitOrderAttempt,
    can_finalize_full_exit,
)


@dataclass
class _FakeOrderResult:
    """Minimal OrderResult stand-in for finalizer tests."""

    status: str
    fill: dict | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            "filled_mock",
            "filled_paper",
            "filled_live",
            "partial_live",
            "partial_fill",
            "unfilled_ioc",
            "rejected",
            "canceled",
            "expired",
        }

    @property
    def filled_count_fp(self) -> Decimal:
        if not self.fill:
            return Decimal("0")
        return Decimal(self.fill.get("executed_quantity_cc", 0)) / Decimal("100")

    @property
    def remaining_count_fp(self) -> Decimal:
        if not self.fill:
            return Decimal("0")
        return Decimal(self.fill.get("remaining_quantity_cc", 0)) / Decimal("100")


def _make_snapshot(
    *,
    version: int = 1,
    wall_ns: int = 1_000_000,
    status: str = ReconciliationStatus.MATCHED,
    reason: str = ReconciliationReason.MATCHED,
    positions: dict | None = None,
    working_orders: dict | None = None,
    pagination_complete: bool = True,
    positions_complete: bool = True,
) -> CanonicalPortfolioSnapshot:
    """Build a snapshot with controlled parameters."""
    pos_complete = SourceCompleteness(
        source="exchange_rest",
        complete=positions_complete,
        records_fetched=1,
        request_started_ns=wall_ns - 1000,
        request_completed_ns=wall_ns,
    )
    return CanonicalPortfolioSnapshot(
        version=version,
        captured_at_wall_ns=wall_ns,
        captured_at_mono_ns=wall_ns,
        positions_by_ticker=positions or {},
        working_orders_by_id=working_orders or {},
        pending_fills_by_id={},
        exchange_exposure_cc=0,
        local_ledger_exposure_cc=0,
        reserved_exposure_cc=0,
        reconciliation_status=status,
        reconciliation_reason=reason,
        pagination_complete=pagination_complete,
        positions_source_complete=pos_complete,
        fills_source_complete=SourceCompleteness(source="ws_fills", complete=True, records_fetched=0),
        orders_source_complete=SourceCompleteness(source="exchange_rest_orders", complete=True, records_fetched=0),
        source="test",
        source_age_ms=0,
        private_ws_healthy=True,
    )


def _base_attempt():
    return ExitOrderAttempt(
        pre_submit_snapshot_version=0,
        submit_started_at_ns=0,
        submitted_count_fp=Decimal("1.00"),
    )


def test_finalize_full_exit_success():
    """Terminal, fully filled, fresh authoritative flat snapshot finalizes."""
    ticker = "KXBTC15M-26AUG192030-30"
    snapshot = _make_snapshot(version=2, wall_ns=2_000_000)
    attempt = ExitOrderAttempt(
        pre_submit_snapshot_version=1,
        submit_started_at_ns=1_000_000,
        submitted_count_fp=Decimal("1.00"),
    )
    result = _FakeOrderResult(
        status="filled_live",
        fill={"executed_quantity_cc": 100, "remaining_quantity_cc": 0},
    )

    allowed, reason = can_finalize_full_exit(
        snapshot=snapshot,
        attempt=attempt,
        order_result=result,
        position_key=ticker,
        now_ns=3_000_000,
    )
    assert allowed is True
    assert reason == "AUTHORITATIVE_POSITION_FLAT"


def test_finalize_rejects_not_authoritative():
    """MATCHED but incomplete pagination is not authoritative."""
    ticker = "KXBTC15M-26AUG192030-30"
    snapshot = _make_snapshot(
        version=2,
        wall_ns=2_000_000,
        pagination_complete=False,
        positions_complete=False,
    )
    result = _FakeOrderResult(
        status="filled_live",
        fill={"executed_quantity_cc": 100, "remaining_quantity_cc": 0},
    )

    allowed, reason = can_finalize_full_exit(
        snapshot=snapshot,
        attempt=_base_attempt(),
        order_result=result,
        position_key=ticker,
        now_ns=3_000_000,
    )
    assert allowed is False
    assert reason == "PORTFOLIO_NOT_AUTHORITATIVE"


def test_finalize_rejects_stale_snapshot_version():
    """A snapshot older than the submission cannot finalize the exit."""
    ticker = "KXBTC15M-26AUG192030-30"
    snapshot = _make_snapshot(version=1, wall_ns=2_000_000)
    attempt = ExitOrderAttempt(
        pre_submit_snapshot_version=1,
        submit_started_at_ns=1_000_000,
        submitted_count_fp=Decimal("1.00"),
    )
    result = _FakeOrderResult(
        status="filled_live",
        fill={"executed_quantity_cc": 100, "remaining_quantity_cc": 0},
    )

    allowed, reason = can_finalize_full_exit(
        snapshot=snapshot,
        attempt=attempt,
        order_result=result,
        position_key=ticker,
        now_ns=3_000_000,
    )
    assert allowed is False
    assert reason == "NO_POST_ORDER_SNAPSHOT"


def test_finalize_rejects_snapshot_preceding_submission():
    """A snapshot captured before the order was submitted is stale."""
    ticker = "KXBTC15M-26AUG192030-30"
    snapshot = _make_snapshot(version=2, wall_ns=1_000_000)
    attempt = ExitOrderAttempt(
        pre_submit_snapshot_version=1,
        submit_started_at_ns=2_000_000,
        submitted_count_fp=Decimal("1.00"),
    )
    result = _FakeOrderResult(
        status="filled_live",
        fill={"executed_quantity_cc": 100, "remaining_quantity_cc": 0},
    )

    allowed, reason = can_finalize_full_exit(
        snapshot=snapshot,
        attempt=attempt,
        order_result=result,
        position_key=ticker,
        now_ns=3_000_000,
    )
    assert allowed is False
    assert reason == "SNAPSHOT_PRECEDES_SUBMISSION"


def test_finalize_rejects_not_matched():
    """A MISMATCH/UNKNOWN/STALE snapshot cannot finalize."""
    ticker = "KXBTC15M-26AUG192030-30"
    snapshot = _make_snapshot(
        version=2,
        wall_ns=2_000_000,
        status=ReconciliationStatus.MISMATCH,
        reason=ReconciliationReason.MISMATCH_POSITION,
    )
    result = _FakeOrderResult(
        status="filled_live",
        fill={"executed_quantity_cc": 100, "remaining_quantity_cc": 0},
    )

    allowed, reason = can_finalize_full_exit(
        snapshot=snapshot,
        attempt=_base_attempt(),
        order_result=result,
        position_key=ticker,
        now_ns=3_000_000,
    )
    assert allowed is False
    assert reason == "PORTFOLIO_NOT_AUTHORITATIVE"


def test_finalize_rejects_non_terminal_order():
    """A resting or in-flight order cannot finalize."""
    ticker = "KXBTC15M-26AUG192030-30"
    snapshot = _make_snapshot(version=2, wall_ns=2_000_000)
    result = _FakeOrderResult(status="resting")

    allowed, reason = can_finalize_full_exit(
        snapshot=snapshot,
        attempt=_base_attempt(),
        order_result=result,
        position_key=ticker,
        now_ns=3_000_000,
    )
    assert allowed is False
    assert reason == "ORDER_NOT_TERMINAL"


def test_finalize_rejects_fill_less_than_submitted():
    """A partial fill against the submitted count cannot finalize."""
    ticker = "KXBTC15M-26AUG192030-30"
    snapshot = _make_snapshot(version=2, wall_ns=2_000_000)
    attempt = ExitOrderAttempt(
        pre_submit_snapshot_version=1,
        submit_started_at_ns=1_000_000,
        submitted_count_fp=Decimal("1.00"),
    )
    result = _FakeOrderResult(
        status="partial_live",
        fill={"executed_quantity_cc": 49, "remaining_quantity_cc": 0},
    )

    allowed, reason = can_finalize_full_exit(
        snapshot=snapshot,
        attempt=attempt,
        order_result=result,
        position_key=ticker,
        now_ns=3_000_000,
    )
    assert allowed is False
    assert reason == "FILL_COUNT_NOT_EQUAL_SUBMITTED"


def test_finalize_rejects_remaining_quantity():
    """A terminal order with remaining quantity cannot finalize."""
    ticker = "KXBTC15M-26AUG192030-30"
    snapshot = _make_snapshot(version=2, wall_ns=2_000_000)
    attempt = ExitOrderAttempt(
        pre_submit_snapshot_version=1,
        submit_started_at_ns=1_000_000,
        submitted_count_fp=Decimal("1.00"),
    )
    result = _FakeOrderResult(
        status="partial_live",
        fill={"executed_quantity_cc": 100, "remaining_quantity_cc": 40},
    )

    allowed, reason = can_finalize_full_exit(
        snapshot=snapshot,
        attempt=attempt,
        order_result=result,
        position_key=ticker,
        now_ns=3_000_000,
    )
    assert allowed is False
    assert reason == "ORDER_REMAINS"


def test_finalize_rejects_working_order_remaining():
    """A working order for the same market blocks finalization."""
    ticker = "KXBTC15M-26AUG192030-30"
    order = CanonicalOrder(
        order_id="ord-2",
        client_order_id=None,
        ticker=ticker,
        side="yes",
        action="sell",
        quantity_fp=Decimal("0.50"),
        filled_quantity_fp=Decimal("0"),
        remaining_quantity_fp=Decimal("0.50"),
        price_cents=50,
        status="resting",
        source="exchange_rest",
        timestamp=0.0,
    )
    snapshot = _make_snapshot(
        version=2,
        wall_ns=2_000_000,
        working_orders={"ord-2": order},
    )
    attempt = ExitOrderAttempt(
        pre_submit_snapshot_version=1,
        submit_started_at_ns=1_000_000,
        submitted_count_fp=Decimal("1.00"),
    )
    result = _FakeOrderResult(
        status="filled_live",
        fill={"executed_quantity_cc": 100, "remaining_quantity_cc": 0},
    )

    allowed, reason = can_finalize_full_exit(
        snapshot=snapshot,
        attempt=attempt,
        order_result=result,
        position_key=ticker,
        now_ns=3_000_000,
    )
    assert allowed is False
    assert reason == "WORKING_EXIT_REMAINS"


def test_finalize_rejects_remaining_exchange_position():
    """A non-zero exchange position cannot finalize."""
    ticker = "KXBTC15M-26AUG192030-30"
    position = CanonicalPosition(
        ticker=ticker,
        market_id=ticker,
        outcome="yes",
        quantity_fp=Decimal("0.10"),
        avg_entry_price_cents=50,
        entry_order_id=None,
        entry_fill_id=None,
        provenance="exchange_rest",
        timestamp=0.0,
        yes_exposure_cc=10,
    )
    snapshot = _make_snapshot(
        version=2,
        wall_ns=2_000_000,
        positions={ticker: position},
    )
    attempt = ExitOrderAttempt(
        pre_submit_snapshot_version=1,
        submit_started_at_ns=1_000_000,
        submitted_count_fp=Decimal("1.00"),
    )
    result = _FakeOrderResult(
        status="filled_live",
        fill={"executed_quantity_cc": 100, "remaining_quantity_cc": 0},
    )

    allowed, reason = can_finalize_full_exit(
        snapshot=snapshot,
        attempt=attempt,
        order_result=result,
        position_key=ticker,
        now_ns=3_000_000,
    )
    assert allowed is False
    assert reason == "EXCHANGE_POSITION_REMAINS"


def test_finalize_allows_zero_fill_zero_remaining():
    """An unfilled IOC (filled=0, remaining=0) is terminal but not a close."""
    ticker = "KXBTC15M-26AUG192030-30"
    snapshot = _make_snapshot(version=2, wall_ns=2_000_000)
    attempt = ExitOrderAttempt(
        pre_submit_snapshot_version=1,
        submit_started_at_ns=1_000_000,
        submitted_count_fp=Decimal("1.00"),
    )
    result = _FakeOrderResult(
        status="unfilled_ioc",
        fill={"executed_quantity_cc": 0, "remaining_quantity_cc": 0},
    )

    allowed, reason = can_finalize_full_exit(
        snapshot=snapshot,
        attempt=attempt,
        order_result=result,
        position_key=ticker,
        now_ns=3_000_000,
    )
    assert allowed is False
    assert reason == "FILL_COUNT_NOT_EQUAL_SUBMITTED"


def test_finalize_compares_to_submitted_not_requested():
    """A reduce-only clipped exit must compare fill to the submitted count."""
    ticker = "KXBTC15M-26AUG192030-30"
    snapshot = _make_snapshot(version=2, wall_ns=2_000_000)
    attempt = ExitOrderAttempt(
        pre_submit_snapshot_version=1,
        submit_started_at_ns=1_000_000,
        submitted_count_fp=Decimal("0.49"),
    )
    result = _FakeOrderResult(
        status="filled_live",
        fill={"executed_quantity_cc": 49, "remaining_quantity_cc": 0},
    )

    allowed, reason = can_finalize_full_exit(
        snapshot=snapshot,
        attempt=attempt,
        order_result=result,
        position_key=ticker,
        now_ns=3_000_000,
    )
    assert allowed is True
    assert reason == "AUTHORITATIVE_POSITION_FLAT"


def test_finalize_full_exit_no_position_positive():
    """A full fill while the exchange position remains positive is not flat."""
    ticker = "KXBTC15M-26AUG192030-30"
    position = CanonicalPosition(
        ticker=ticker,
        market_id=ticker,
        outcome="yes",
        quantity_fp=Decimal("0.10"),
        avg_entry_price_cents=50,
        entry_order_id=None,
        entry_fill_id=None,
        provenance="exchange_rest",
        timestamp=0.0,
        yes_exposure_cc=10,
    )
    snapshot = _make_snapshot(
        version=2,
        wall_ns=2_000_000,
        positions={ticker: position},
    )
    attempt = ExitOrderAttempt(
        pre_submit_snapshot_version=1,
        submit_started_at_ns=1_000_000,
        submitted_count_fp=Decimal("1.00"),
    )
    result = _FakeOrderResult(
        status="filled_live",
        fill={"executed_quantity_cc": 100, "remaining_quantity_cc": 0},
    )

    allowed, reason = can_finalize_full_exit(
        snapshot=snapshot,
        attempt=attempt,
        order_result=result,
        position_key=ticker,
        now_ns=3_000_000,
    )
    assert allowed is False
    assert reason == "EXCHANGE_POSITION_REMAINS"


def test_finalize_full_exit_no_position_remains_negative():
    """A full fill while a long-NO position remains must not finalize."""
    ticker = "KXBTC15M-26AUG192030-30"
    position = CanonicalPosition(
        ticker=ticker,
        market_id=ticker,
        outcome="no",
        quantity_fp=Decimal("0.10"),
        avg_entry_price_cents=50,
        entry_order_id=None,
        entry_fill_id=None,
        provenance="exchange_rest",
        timestamp=0.0,
        yes_exposure_cc=-10,
    )
    snapshot = _make_snapshot(
        version=2,
        wall_ns=2_000_000,
        positions={ticker: position},
    )
    attempt = ExitOrderAttempt(
        pre_submit_snapshot_version=1,
        submit_started_at_ns=1_000_000,
        submitted_count_fp=Decimal("1.00"),
    )
    result = _FakeOrderResult(
        status="filled_live",
        fill={"executed_quantity_cc": 100, "remaining_quantity_cc": 0},
    )

    allowed, reason = can_finalize_full_exit(
        snapshot=snapshot,
        attempt=attempt,
        order_result=result,
        position_key=ticker,
        now_ns=3_000_000,
    )
    assert allowed is False
    assert reason == "EXCHANGE_POSITION_REMAINS"


def test_finalize_full_exit_no_position_zero():
    """A terminal full fill for a long-NO position reaches exactly zero."""
    ticker = "KXBTC15M-26AUG192030-30"
    position = CanonicalPosition(
        ticker=ticker,
        market_id=ticker,
        outcome="no",
        quantity_fp=Decimal("0"),
        avg_entry_price_cents=50,
        entry_order_id=None,
        entry_fill_id=None,
        provenance="exchange_rest",
        timestamp=0.0,
        yes_exposure_cc=0,
    )
    snapshot = _make_snapshot(version=2, wall_ns=2_000_000, positions={ticker: position})
    attempt = ExitOrderAttempt(
        pre_submit_snapshot_version=1,
        submit_started_at_ns=1_000_000,
        submitted_count_fp=Decimal("1.00"),
    )
    result = _FakeOrderResult(
        status="filled_live",
        fill={"executed_quantity_cc": 100, "remaining_quantity_cc": 0},
    )

    allowed, reason = can_finalize_full_exit(
        snapshot=snapshot,
        attempt=attempt,
        order_result=result,
        position_key=ticker,
        now_ns=3_000_000,
    )
    assert allowed is True
    assert reason == "AUTHORITATIVE_POSITION_FLAT"


def test_finalize_full_exit_pagination_incomplete():
    """A full fill with an incomplete paginated source is not authoritative."""
    ticker = "KXBTC15M-26AUG192030-30"
    snapshot = _make_snapshot(
        version=2,
        wall_ns=2_000_000,
        pagination_complete=False,
        positions_complete=False,
    )
    attempt = ExitOrderAttempt(
        pre_submit_snapshot_version=1,
        submit_started_at_ns=1_000_000,
        submitted_count_fp=Decimal("1.00"),
    )
    result = _FakeOrderResult(
        status="filled_live",
        fill={"executed_quantity_cc": 100, "remaining_quantity_cc": 0},
    )

    allowed, reason = can_finalize_full_exit(
        snapshot=snapshot,
        attempt=attempt,
        order_result=result,
        position_key=ticker,
        now_ns=3_000_000,
    )
    assert allowed is False
    assert reason == "PORTFOLIO_NOT_AUTHORITATIVE"


def test_finalize_rejects_when_snapshot_version_unchanged():
    """No post-order snapshot means version did not advance."""
    ticker = "KXBTC15M-26AUG192030-30"
    snapshot = _make_snapshot(version=1, wall_ns=2_000_000)
    attempt = ExitOrderAttempt(
        pre_submit_snapshot_version=1,
        submit_started_at_ns=1_000_000,
        submitted_count_fp=Decimal("1.00"),
    )
    result = _FakeOrderResult(
        status="filled_live",
        fill={"executed_quantity_cc": 100, "remaining_quantity_cc": 0},
    )

    allowed, reason = can_finalize_full_exit(
        snapshot=snapshot,
        attempt=attempt,
        order_result=result,
        position_key=ticker,
        now_ns=3_000_000,
    )
    assert allowed is False
    assert reason == "NO_POST_ORDER_SNAPSHOT"
