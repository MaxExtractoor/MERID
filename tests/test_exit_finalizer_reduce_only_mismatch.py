"""Reduce-only exit finalization must work when the broader portfolio is not authoritative."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from merid.event_venues.kalshi.exit_finalizer import (
    ExitOrderAttempt,
    can_finalize_full_exit,
)


@dataclass
class _FakeSnapshot:
    """Minimal snapshot stand-in for finalizer tests."""

    is_authoritative: bool = False
    reconciliation_status: str = "MISMATCH"
    version: int = 1
    captured_at_wall_ns: int = 2

    def working_exit_count_fp(self, position_key: str) -> Decimal:
        return Decimal("0")

    def exchange_position_fp(self, position_key: str) -> Decimal:
        return Decimal("0")


class _FakeOrderResult:
    """Mutable OrderResult stand-in for finalizer tests."""

    def __init__(
        self,
        *,
        status: str,
        filled_count_fp: Decimal,
        remaining_count_fp: Decimal,
    ) -> None:
        self.status = status
        self._filled_count_fp = filled_count_fp
        self._remaining_count_fp = remaining_count_fp

    @property
    def filled_count_fp(self) -> Decimal:
        return self._filled_count_fp

    @property
    def remaining_count_fp(self) -> Decimal:
        return self._remaining_count_fp


@pytest.mark.parametrize("status", ["filled_live", "filled_paper", "filled_mock"])
def test_reduce_only_full_exit_ignores_non_authoritative_snapshot(status):
    """A full reduce-only fill finalizes even when portfolio is not authoritative."""
    attempt = ExitOrderAttempt(
        pre_submit_snapshot_version=1,
        submit_started_at_ns=1,
        submitted_count_fp=Decimal("1"),
        reduce_only=True,
    )
    result = _FakeOrderResult(
        status=status,
        filled_count_fp=Decimal("1"),
        remaining_count_fp=Decimal("0"),
    )
    snapshot = _FakeSnapshot(
        is_authoritative=False,
        reconciliation_status="MISMATCH",
        version=2,
        captured_at_wall_ns=2,
    )
    allowed, reason = can_finalize_full_exit(
        snapshot=snapshot,
        attempt=attempt,
        order_result=result,
        position_key="KXBTC15M-TEST",
        now_ns=2,
    )
    assert allowed is True
    assert "REDUCE_ONLY_EXIT_FULLY_FILLED" in reason


def test_non_reduce_still_requires_authoritative_snapshot():
    """Non-reduce full exits still require an authoritative portfolio snapshot."""
    attempt = ExitOrderAttempt(
        pre_submit_snapshot_version=1,
        submit_started_at_ns=1,
        submitted_count_fp=Decimal("1"),
        reduce_only=False,
    )
    result = _FakeOrderResult(
        status="filled_live",
        filled_count_fp=Decimal("1"),
        remaining_count_fp=Decimal("0"),
    )
    snapshot = _FakeSnapshot(
        is_authoritative=False,
        reconciliation_status="MISMATCH",
        version=2,
        captured_at_wall_ns=2,
    )
    allowed, reason = can_finalize_full_exit(
        snapshot=snapshot,
        attempt=attempt,
        order_result=result,
        position_key="KXBTC15M-TEST",
        now_ns=2,
    )
    assert allowed is False
    assert "PORTFOLIO_NOT_AUTHORITATIVE" in reason


def test_reduce_only_partial_fill_does_not_finalize():
    """A partial reduce-only fill is not enough to finalize without authority."""
    attempt = ExitOrderAttempt(
        pre_submit_snapshot_version=1,
        submit_started_at_ns=1,
        submitted_count_fp=Decimal("2"),
        reduce_only=True,
    )
    result = _FakeOrderResult(
        status="partial_live",
        filled_count_fp=Decimal("1"),
        remaining_count_fp=Decimal("1"),
    )
    snapshot = _FakeSnapshot(
        is_authoritative=False,
        reconciliation_status="MISMATCH",
        version=2,
        captured_at_wall_ns=2,
    )
    allowed, reason = can_finalize_full_exit(
        snapshot=snapshot,
        attempt=attempt,
        order_result=result,
        position_key="KXBTC15M-TEST",
        now_ns=2,
    )
    assert allowed is False
    assert "ORDER_REMAINS" in reason


def test_reduce_only_unfilled_ioc_does_not_finalize():
    """A zero-fill IOC reduce-only order is terminal but does not finalize."""
    attempt = ExitOrderAttempt(
        pre_submit_snapshot_version=1,
        submit_started_at_ns=1,
        submitted_count_fp=Decimal("1"),
        reduce_only=True,
    )
    result = _FakeOrderResult(
        status="unfilled_ioc",
        filled_count_fp=Decimal("0"),
        remaining_count_fp=Decimal("0"),
    )
    snapshot = _FakeSnapshot(
        is_authoritative=False,
        reconciliation_status="MISMATCH",
        version=2,
        captured_at_wall_ns=2,
    )
    allowed, reason = can_finalize_full_exit(
        snapshot=snapshot,
        attempt=attempt,
        order_result=result,
        position_key="KXBTC15M-TEST",
        now_ns=2,
    )
    assert allowed is False
    assert "FILL_COUNT_NOT_EQUAL_SUBMITTED" in reason
