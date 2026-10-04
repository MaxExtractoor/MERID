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
  * duplicate lookups honoring the venue status: terminal orders are
    rejected, not treated as resting.
"""
from __future__ import annotations

import inspect

import merid.event_venues.kalshi.order_router as _or


def test_terminal_order_statuses_cover_observed_states():
    assert "canceled" in _or.TERMINAL_ORDER_STATUSES
    assert "cancelled" in _or.TERMINAL_ORDER_STATUSES
    assert "expired" in _or.TERMINAL_ORDER_STATUSES
    assert "rejected" in _or.TERMINAL_ORDER_STATUSES


def test_duplicate_lookup_rejects_terminal_before_resting():
    """The terminal-status check must precede the 'confirmed resting' path.

    Source-order regression guard: the duplicate block must consult
    TERMINAL_ORDER_STATUSES and return a rejected OrderResult before any
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


def test_post_only_reprice_mints_fresh_wire_coid():
    """The bounded post-only reprice must not reuse the consumed coid."""
    src = inspect.getsource(_or)
    assert 'f"{intent.client_order_id}r1"' in src, (
        "reprice must mint a fresh wire client_order_id with the r1 suffix"
    )
    assert "reprice_of_client_order_id" in src, (
        "retry metadata must preserve the original intent-level coid"
    )
    # The flag that bounds the retry to exactly once must still exist.
    assert "_post_only_repriced_once" in src
