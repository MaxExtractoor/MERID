"""Unit tests for the canonical executable-quote resolver.

resolve_executable_quote is the single source of truth for what "executable"
means across the entry stack, exit stack, and the hard-profit lock.  These
tests pin the trust gates, side-correctness, reciprocal derivation, VWAP/depth
semantics, and the one-sided-book shapes from the 2026-10-05 incident.
"""

import time
import types

from merid.event_venues.kalshi.executable_quote import (
    ExecutableQuote,
    QuotePurpose,
    QuoteUnavailable,
    QuoteUnavailableReason,
    resolve_executable_quote,
)


def _state(**over):
    base = dict(
        book_initialized=True,
        executable=True,
        data_quality="GOOD",
        data_source="WS_LIVE",
        live_sequence_confirmed=True,
        quote_owner="WS_FRESH_VERIFIED",
        book_health="VALID",
        book_consistency="GOOD",
        ws_last_seq=42,
        last_book_update_ts=time.monotonic(),
        seconds_to_expiry=300.0,
        # YES 60/62 book: yes bids 55..60, no bids 38..40 (no_ask=100-60=40)
        best_bid_cents=60,
        best_ask_cents=62,
        best_no_bid_cents=38,
        best_no_ask_cents=40,
        yes_bids=[(60, 3), (59, 2), (58, 5)],
        no_bids=[(38, 4), (37, 6)],
        min_depth_yes=3,
        min_depth_no=4,
        has_bid=True,
        has_no_bid=True,
        mid_cents=61,
        last_ws_bid_cents=None,
        last_ws_ask_cents=None,
        last_rest_bid_cents=None,
        last_rest_ask_cents=None,
        last_rest_quote_update_ts=0.0,
    )
    base.update(over)
    return types.SimpleNamespace(**base)


def test_exit_yes_resolves_direct_bid():
    q = resolve_executable_quote(
        "T", "yes", quantity=1, purpose=QuotePurpose.EXIT, state=_state()
    )
    assert isinstance(q, ExecutableQuote)
    assert q.best_bid_cents == 60
    assert q.best_ask_cents == 62
    assert q.vwap_cents == 60
    assert q.available_depth == 10   # full displayed YES-bid depth (3+2+5)
    assert q.best_level_size == 3    # size at the touched top level
    assert q.depth_sufficient is True
    assert q.derived_from_reciprocal is False
    assert q.book_sequence == 42


def test_exit_no_resolves_direct_bid():
    q = resolve_executable_quote(
        "T", "no", quantity=1, purpose=QuotePurpose.EXIT, state=_state()
    )
    assert isinstance(q, ExecutableQuote)
    assert q.best_bid_cents == 38          # NO bid direct
    assert q.best_ask_cents == 40          # NO ask = 100 - YES bid
    assert q.vwap_cents == 38


def test_exit_vwap_walks_ladder_for_size():
    q = resolve_executable_quote(
        "T", "yes", quantity=5, purpose=QuotePurpose.EXIT, state=_state()
    )
    assert isinstance(q, ExecutableQuote)
    # Sell 5 into YES bids: 3@60 + 2@59 -> 59.6
    assert abs(q.vwap_cents - 59.6) < 1e-9
    assert q.depth_sufficient is True
    # qty 20 exceeds displayed 10 contracts -> insufficient
    q2 = resolve_executable_quote(
        "T", "yes", quantity=20, purpose=QuotePurpose.EXIT, state=_state()
    )
    assert q2.depth_sufficient is False
    assert q2.available_depth == 10


def test_entry_buy_no_uses_reciprocal_ladder():
    """Buying NO hits the NO ask ladder = YES bids mapped 100-p."""
    q = resolve_executable_quote(
        "T", "no", quantity=3, purpose=QuotePurpose.ENTRY, state=_state()
    )
    assert isinstance(q, ExecutableQuote)
    # NO asks: YES bid 60 -> NO ask 40 (3 sz), 59 -> 41 (2 sz)
    assert q.best_ask_cents == 40
    assert abs(q.vwap_cents - 40.0) < 1e-9   # qty 3 all fills at the 40 level


def test_entry_buy_yes_uses_reciprocal_ladder():
    q = resolve_executable_quote(
        "T", "yes", quantity=5, purpose=QuotePurpose.ENTRY, state=_state()
    )
    assert isinstance(q, ExecutableQuote)
    # YES asks: NO bid 38 -> YES ask 62 (4 sz), 37 -> 63 (6 sz)
    assert q.best_ask_cents == 62
    assert abs(q.vwap_cents - ((62 * 4 + 63 * 1) / 5)) < 1e-9


def test_untrusted_quality_rejected():
    q = resolve_executable_quote(
        "T", "yes", purpose=QuotePurpose.EXIT, state=_state(data_quality="STALE")
    )
    assert isinstance(q, QuoteUnavailable)
    assert q.reason == QuoteUnavailableReason.BOOK_QUALITY_NOT_TRUSTED
    assert q.observed_bid_cents == 60  # witnessed bid is still reported


def test_non_executable_book_rejected():
    q = resolve_executable_quote(
        "T", "no", purpose=QuotePurpose.EXIT, state=_state(executable=False)
    )
    assert isinstance(q, QuoteUnavailable)
    assert q.reason == QuoteUnavailableReason.BOOK_NOT_EXECUTABLE
    assert q.observed_bid_cents == 38


def test_stale_book_rejected_with_freshness_gate():
    q = resolve_executable_quote(
        "T",
        "yes",
        purpose=QuotePurpose.EXIT,
        required_freshness_ms=1000,
        state=_state(last_book_update_ts=time.monotonic() - 60.0),
    )
    assert isinstance(q, QuoteUnavailable)
    assert q.reason == QuoteUnavailableReason.QUOTE_STALE


def test_unconfirmed_bootstrap_rejected():
    q = resolve_executable_quote(
        "T",
        "yes",
        purpose=QuotePurpose.EXIT,
        state=_state(
            data_source="BOOTSTRAP_VALID_BUT_UNCONFIRMED",
            live_sequence_confirmed=False,
        ),
    )
    assert isinstance(q, QuoteUnavailable)
    assert q.reason == QuoteUnavailableReason.BOOK_UNCONFIRMED_SEQUENCE


def test_one_sided_incident_book_no_bid_99():
    """The BTC-NO incident shape: YES bid absent, YES ask=1c -> NO bid=99c.

    The reciprocal-derived effective bid is executable even though the held
    side's own ladder field is empty.
    """
    state = _state(
        best_bid_cents=None,
        best_ask_cents=1,
        best_no_bid_cents=99,
        best_no_ask_cents=None,
        yes_bids=[],
        no_bids=[],
        min_depth_yes=0,
        min_depth_no=100,
        has_bid=False,
        has_no_bid=True,
    )
    q = resolve_executable_quote(
        "KXBTC15M-X", "no", purpose=QuotePurpose.EXIT, state=state
    )
    assert isinstance(q, ExecutableQuote)
    assert q.best_bid_cents == 99
    assert q.best_ask_cents is None


def test_missing_held_bid_returns_structured_unavailable():
    state = _state(best_bid_cents=None, yes_bids=[])
    q = resolve_executable_quote(
        "T", "yes", purpose=QuotePurpose.EXIT, state=state
    )
    assert isinstance(q, QuoteUnavailable)
    assert q.reason == QuoteUnavailableReason.HELD_SIDE_BID_UNAVAILABLE


def test_no_state_returns_missing():
    q = resolve_executable_quote("T", "yes", purpose=QuotePurpose.EXIT, state=None)
    assert isinstance(q, QuoteUnavailable)
    assert q.reason == QuoteUnavailableReason.STATE_MISSING
