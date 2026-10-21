"""Submit-time revalidation for resting (post-only maker) orders.

2026-10-21 live blocker: every maker_bid pinned_fav intent died as
``submit_revalidation:submit_depth_insufficient`` (XRP BUY_YES@90c).  The
gate walked the held-side ASK book for depth at-or-below the limit — taker
semantics.  A post-only resting bid on a coherent book (bid<ask) has zero
asks at-or-below the bid by construction, so the gate rejected the entire
maker cohort.  For a resting order the fill price IS the limit: the checks
that bind are book freshness, the max_price bound, non-crossing validity,
and EV at the limit.
"""

from decimal import Decimal

from merid.execution.submit_revalidation import (
    AcquisitionBook,
    SUBMIT_DEPTH_INSUFFICIENT,
    SUBMIT_EDGE_LOST,
    SUBMIT_EDGE_VALID,
    SUBMIT_REAPPROVAL_REQUIRED,
    SubmitRevalidationInput,
    revalidate_entry,
)


def _book(ask_levels):
    """Ascending ask levels [(price_cents, qty_cc), ...]."""
    return AcquisitionBook(levels=sorted(ask_levels), book_age_ms=100)


def _mk(limit=86, qty_cc=300, post_only=True, p_held=Decimal("85"),
        req_edge=Decimal("-12"), fee=Decimal("0.2"),
        book=None):
    return SubmitRevalidationInput(
        candidate_id="cand_test",
        held_side="yes",
        qty_cc=qty_cc,
        proposed_limit_cents=limit,
        p_held_cents=p_held,
        prob_est_ts=None,
        book=book if book is not None else _book([(87, 10000), (89, 20000)]),
        fee_per_contract_cents=fee,
        reserves_per_contract_cents=Decimal("0"),
        required_edge_per_contract_cents=req_edge,
        post_only=post_only,
    )


def test_post_only_bid_below_ask_valid():
    """The live failure: post-only buy_yes@86 on book 85/87 — no asks at or
    below 86 — must validate at the limit, not die on the taker walk."""
    d = revalidate_entry(_mk())
    assert d.outcome == SUBMIT_EDGE_VALID, d.reason
    # Acquisition cost is the limit itself (no book walk).
    assert d.expected_cost_cents == Decimal(86) * Decimal(300) / Decimal(100)
    assert d.permitted_qty_cc == 300
    # EV per contract: 85 - 86 - 0.2 = -1.2 >= -12 floor.
    assert d.ev_per_contract_cents == Decimal("85") - Decimal("86") \
        - Decimal("0.2")


def test_post_only_crossing_book_needs_reapproval():
    """A resting buy at-or-above the best ask is immediately marketable —
    post_only would be rejected by the exchange.  Crossing economics are a
    different admission contract: reapproval, not a silent rewrite."""
    d = revalidate_entry(_mk(limit=87))  # ask book top is 87
    assert d.outcome == SUBMIT_REAPPROVAL_REQUIRED
    assert "post_only_crosses" in d.reason


def test_post_only_ev_floor_still_binds():
    """The lane floor still applies at the limit.  For a single-price fill
    ``ev_pc < req`` is algebraically the same inequality as
    ``limit > max_price`` (max_price = p - fee - reserves - req), so a
    required-edge violation surfaces as the reapproval bound — same floor,
    enforced before the wire, not silently rewritten."""
    d = revalidate_entry(_mk(req_edge=Decimal("0")))
    assert d.outcome == SUBMIT_REAPPROVAL_REQUIRED
    assert "max_price" in d.reason
    # And the valid side of the same floor: req=-12 passes at 86c.
    d2 = revalidate_entry(_mk(req_edge=Decimal("-12")))
    assert d2.outcome == SUBMIT_EDGE_VALID, d2.reason


def test_post_only_max_price_bound_still_binds():
    """limit above p_held - fee - reserves - required still reapproves."""
    # max_price = 85 - 0.2 - 0 - (-12) = 96.8 -> limit 97 exceeds.
    d = revalidate_entry(_mk(limit=97, book=_book([(98, 5000)])))
    assert d.outcome == SUBMIT_REAPPROVAL_REQUIRED
    assert "max_price" in d.reason


def test_taker_walk_unchanged():
    """Taker semantics preserved: asks at-or-below the limit are consumed;
    none -> depth insufficient."""
    # Book 85/87, taker limit 86 -> no asks <=86 -> insufficient (the old
    # structural behavior that killed the maker lane).
    d = revalidate_entry(_mk(post_only=False))
    assert d.outcome == SUBMIT_DEPTH_INSUFFICIENT
    # Taker limit at the ask: consumes it, EV at walked cost.
    d2 = revalidate_entry(_mk(limit=87, post_only=False))
    assert d2.outcome == SUBMIT_EDGE_VALID, d2.reason
    assert d2.expected_cost_cents == Decimal(87) * Decimal(300) / Decimal(100)
