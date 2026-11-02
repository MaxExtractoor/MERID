"""Regression guards for the 2026-10-04 duplicate-order wire bugs.

Observed live (KXETH15M-26OCT032245-45):
  1. post-only bid @32c crossed a moved ask -> Kalshi 400 post_only cross
  2. reprice resubmitted with the SAME client_order_id -> 409 duplicate
  3. duplicate lookup returned the original order with status=canceled
  4. the handler logged "confirmed resting" and recorded submitted_live —
     a dead order masquerading as a live one.

Fixes under test:
  * the reprice leg mints a fresh wire client_order_id (``r1`` suffix)
    while the intent-level coid stays canonical,
  * terminal duplicate lookups are not treated as resting or zero-fill
    rejections; their fills must be reconciled.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

import merid.event_venues.kalshi.order_router as _or
from merid.loop_15m import _confirmed_submission
from merid.prediction.trading_mode import TradingMode
import pytest


def test_terminal_order_statuses_cover_observed_states():
    assert "canceled" in _or.TERMINAL_ORDER_STATUSES
    assert "cancelled" in _or.TERMINAL_ORDER_STATUSES
    assert "expired" in _or.TERMINAL_ORDER_STATUSES
    assert "rejected" in _or.TERMINAL_ORDER_STATUSES
    assert "filled" in _or.TERMINAL_ORDER_STATUSES
    assert "executed" in _or.TERMINAL_ORDER_STATUSES


def test_duplicate_lookup_reconciles_terminal_before_resting():
    """The terminal-status check must precede the 'confirmed resting' path.

    Source-order regression guard: the duplicate block must consult
    TERMINAL_ORDER_STATUSES and return a recovery result before any
    code that logs or marks the order as resting/submitted.
    """
    src = inspect.getsource(_or)
    dup_marker = "KALSHI_DUPLICATE_LOOKUP"
    terminal_marker = "TERMINAL_ORDER_STATUSES"
    rejected_marker = "duplicate_order_terminal"
    resting_pos = src.find(dup_marker)
    terminal_pos = src.find(terminal_marker, src.find("is_duplicate_error"))
    rejected_pos = src.find(rejected_marker)
    assert resting_pos > 0 and terminal_pos > 0 and rejected_pos > 0
    assert terminal_pos < resting_pos, (
        "terminal-status check must run before the resting-confirm path"
    )
    assert rejected_pos < resting_pos
    terminal_branch = src[terminal_pos:resting_pos]
    assert "return _duplicate_terminal_recovery_result(" in terminal_branch
    assert "_release_allocated_slot(intent)" not in terminal_branch


@pytest.mark.parametrize(
    ("status", "filled_size"),
    [("canceled", "0.25"), ("canceled", "0"), ("filled", "1.00"),
     ("expired", None), ("rejected", None)],
)
def test_terminal_duplicate_keeps_fill_outcome_unresolved(status, filled_size):
    order = SimpleNamespace(order_id="exchange-order-1", status=status, filled_size=filled_size)
    result = _or._duplicate_terminal_recovery_result(order, TradingMode.LIVE, 10.0)
    assert result.status == "duplicate_unknown"
    assert result.requires_recovery
    assert result.submission_certainty == "unknown"
    assert not result.has_execution
    assert not _confirmed_submission(result)
    assert "exchange-order-1" in result.reason


def test_terminal_duplicate_keeps_exit_arbiter_in_reconciliation():
    from merid.position_management.exit_pipeline import post_route_update

    order = SimpleNamespace(order_id="exchange-order-1", status="canceled", filled_size="0.25")
    result = _or._duplicate_terminal_recovery_result(order, TradingMode.LIVE, 10.0)
    arbiter = MagicMock()
    post_route_update("position-1", result, arbiter=arbiter)
    arbiter.mark_ack_unknown.assert_called_once_with(
        "position-1", note="route_duplicate_unknown"
    )
    arbiter.resolve_reconcile.assert_not_called()


def test_post_only_reprice_mints_fresh_wire_coid():
    """The bounded post-only reprice must not reuse the consumed coid."""
    src = inspect.getsource(_or)
    assert '_prepare_retry_wire_attempt(intent, create_request, _rt_old_res, "reprice")' in src
    assert "reprice_of_client_order_id" in src, (
        "retry metadata must preserve the original intent-level coid"
    )
    # The flag that bounds the retry to exactly once must still exist.
    assert "_post_only_repriced_once" in src
