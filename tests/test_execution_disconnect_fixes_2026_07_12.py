"""Regression tests for the 2026-07-12 execution pipeline disconnect fixes.

Root cause of "hundreds of order attempts, zero executions" over a 7h session:

1. post_only contradiction: loop_15m built marketable intents (aggressiveness>0,
   post_only=False) but apply_maker_taker_policy overrode post_only=True whenever
   edge < threshold, so orders either rested unfilled forever or were rejected by
   Kalshi as "post-only cross" after the marketable-limit price adjustment.
2. Order stacking: with the 5s duplicate window, the 15m loop (5s cadence) would
   stack a fresh resting GTC order onto the book each window expiry; there was no
   guard checking for an existing live resting order.
3. Fill accounting: the immediate-fill sanity path passed undefined `_ctx` kwargs
   (NameError) and omitted required ticker/side args, silently disabling
   duplicate-fill/overfill detection on every live fill.
4. requested_count: reconciliation trusted Kalshi's response `size` verbatim;
   Kalshi returns 0/None for accepted orders, corrupting fill-pct and
   filled/partial status classification.

Fixes under test:
- merid/event_venues/kalshi/maker_taker_integration.py: policy post_only only
  applies to resting intents (aggressiveness == 0).
- merid/event_venues/kalshi/order_router.py: _effective_post_only,
  _resolve_requested_count, _check_open_resting_order + wiring.
- merid/event_venues/kalshi/resting_order_monitor.py: find_open_order.
"""

import pytest

from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    _check_open_resting_order,
    _effective_post_only,
    _resolve_requested_count,
)
from merid.event_venues.kalshi.resting_order_monitor import (
    RestingOrderMonitor,
    RestingOrderRecord,
)


def _make_intent(**overrides) -> OrderIntent:
    """Build a minimal valid OrderIntent for router unit tests."""
    kwargs = dict(
        ticker="KXBTC15M-26JUL121500-00",
        side="BUY_YES",
        action="buy",
        price_cents=50,
        count=1,
        edge_pct=3.0,
    )
    kwargs.update(overrides)
    return OrderIntent(**kwargs)


def _make_record(**overrides) -> RestingOrderRecord:
    kwargs = dict(
        kalshi_order_id="order-abc-123",
        ticker="KXBTC15M-26JUL121500-00",
        side="BUY_YES",
        action="buy",
        original_size=1,
        remaining_size=1,
        price_cents=50,
        status="open",
    )
    kwargs.update(overrides)
    return RestingOrderRecord(**kwargs)


# ---------------------------------------------------------------------------
# FIX 1/2: post_only must never be sent for marketable orders
# ---------------------------------------------------------------------------

class TestEffectivePostOnly:
    def test_resting_intent_keeps_post_only(self):
        assert _effective_post_only(post_only=True, aggressiveness=0.0) is True

    def test_marketable_intent_never_post_only(self):
        assert _effective_post_only(post_only=True, aggressiveness=0.5) is False
        assert _effective_post_only(post_only=True, aggressiveness=1.0) is False

    def test_post_only_false_stays_false(self):
        assert _effective_post_only(post_only=False, aggressiveness=0.0) is False
        assert _effective_post_only(post_only=False, aggressiveness=0.7) is False

    def test_none_aggressiveness_treated_as_resting(self):
        assert _effective_post_only(post_only=True, aggressiveness=None) is True


class TestMakerTakerIntegrationPostOnly:
    """The policy layer must not flip marketable intents back to post_only."""

    def test_marketable_intent_keeps_post_only_false_when_policy_says_maker(self):
        from merid.event_venues.kalshi.maker_taker_integration import apply_maker_taker_policy

        # Low edge -> AGGRESSIVE_CONVICTION policy recommends MAKER (post_only=True).
        # Marketable intent (aggressiveness > 0) must stay post_only=False.
        intent = _make_intent(edge_pct=0.5, aggressiveness=0.5, post_only=False)
        apply_maker_taker_policy(intent)

        assert intent.post_only is False, (
            "Marketable intent was flipped to post_only=True - this recreates the "
            "resting-order execution disconnect"
        )

    def test_resting_intent_receives_policy_post_only(self):
        from merid.event_venues.kalshi.maker_taker_integration import apply_maker_taker_policy

        # Low edge, resting intent (aggressiveness == 0) -> policy maker decision applies.
        intent = _make_intent(edge_pct=0.5, aggressiveness=0.0, post_only=False)
        apply_maker_taker_policy(intent)

        assert intent.post_only is True, (
            "Resting intent should receive the policy's maker/post_only decision"
        )

    def test_policy_metadata_enrichment_still_applied(self):
        from merid.event_venues.kalshi.maker_taker_integration import apply_maker_taker_policy

        intent = _make_intent(edge_pct=0.5, aggressiveness=0.5)
        apply_maker_taker_policy(intent)

        assert intent.expected_role is not None
        assert intent.fee_type is not None


# ---------------------------------------------------------------------------
# FIX 3: anti-stacking open-order guard
# ---------------------------------------------------------------------------

class TestFindOpenOrder:
    def test_finds_live_order_by_ticker(self):
        monitor = RestingOrderMonitor()
        monitor._resting_orders["order-abc-123"] = _make_record()

        assert monitor.find_open_order("KXBTC15M-26JUL121500-00") == "order-abc-123"

    def test_match_is_case_insensitive(self):
        monitor = RestingOrderMonitor()
        monitor._resting_orders["order-abc-123"] = _make_record()

        assert (
            monitor.find_open_order(
                "kxbtc15m-26jul121500-00", side="buy_yes", action="BUY"
            )
            == "order-abc-123"
        )

    def test_side_and_action_filters(self):
        monitor = RestingOrderMonitor()
        monitor._resting_orders["order-abc-123"] = _make_record()

        assert (
            monitor.find_open_order(
                "KXBTC15M-26JUL121500-00", side="BUY_NO", action="buy"
            )
            is None
        )
        assert (
            monitor.find_open_order(
                "KXBTC15M-26JUL121500-00", side="BUY_YES", action="sell"
            )
            is None
        )

    def test_terminal_status_not_matched(self):
        monitor = RestingOrderMonitor()
        for status in ("filled", "canceled", "expired", "rejected"):
            monitor._resting_orders = {
                "order-abc-123": _make_record(status=status)
            }
            assert monitor.find_open_order("KXBTC15M-26JUL121500-00") is None, (
                f"Terminal status {status!r} must not block new submissions"
            )

    def test_zero_remaining_not_matched(self):
        monitor = RestingOrderMonitor()
        record = _make_record()
        # Simulate portfolio sync draining the order (post_init resets 0 at
        # construction time, so mutate after construction like _sync_order_status)
        record.remaining_size = 0
        monitor._resting_orders["order-abc-123"] = record

        assert monitor.find_open_order("KXBTC15M-26JUL121500-00") is None

    def test_unregistered_order_not_matched(self):
        monitor = RestingOrderMonitor()
        monitor._resting_orders["order-abc-123"] = _make_record()
        monitor.unregister_order("order-abc-123")

        assert monitor.find_open_order("KXBTC15M-26JUL121500-00") is None


class TestOpenOrderGuard:
    @pytest.fixture(autouse=True)
    def _reset_monitor_singleton(self, monkeypatch):
        import merid.event_venues.kalshi.resting_order_monitor as rom

        monkeypatch.setattr(rom, "_monitor_instance", None)
        yield
        monkeypatch.setattr(rom, "_monitor_instance", None)

    def test_buy_rejected_when_live_order_exists(self):
        from merid.event_venues.kalshi.resting_order_monitor import get_resting_order_monitor

        monitor = get_resting_order_monitor()
        monitor._resting_orders["order-abc-123"] = _make_record()

        rejection = _check_open_resting_order(_make_intent())
        assert rejection is not None
        assert rejection.startswith("open_order_exists:")
        assert "order-abc-123" in rejection

    def test_buy_allowed_when_no_live_order(self):
        from merid.event_venues.kalshi.resting_order_monitor import get_resting_order_monitor

        get_resting_order_monitor()  # instantiate empty singleton
        assert _check_open_resting_order(_make_intent()) is None

    def test_sell_never_blocked(self):
        """Exits must never be blocked, even with a matching live record."""
        from merid.event_venues.kalshi.resting_order_monitor import get_resting_order_monitor

        monitor = get_resting_order_monitor()
        monitor._resting_orders["order-abc-123"] = _make_record(
            side="SELL_YES", action="sell"
        )

        intent = _make_intent(side="SELL_YES", action="sell")
        assert _check_open_resting_order(intent) is None

    def test_buy_allowed_after_order_filled(self):
        from merid.event_venues.kalshi.resting_order_monitor import get_resting_order_monitor

        monitor = get_resting_order_monitor()
        monitor._resting_orders["order-abc-123"] = _make_record(
            status="filled", remaining_size=0
        )

        assert _check_open_resting_order(_make_intent()) is None

    def test_different_ticker_not_blocked(self):
        from merid.event_venues.kalshi.resting_order_monitor import get_resting_order_monitor

        monitor = get_resting_order_monitor()
        monitor._resting_orders["order-abc-123"] = _make_record()

        intent = _make_intent(ticker="KXETH15M-26JUL121500-00")
        assert _check_open_resting_order(intent) is None


# ---------------------------------------------------------------------------
# FIX 4: requested_count fallback when venue omits size
# ---------------------------------------------------------------------------

class TestResolveRequestedCount:
    def test_venue_size_used_when_present(self):
        assert _resolve_requested_count(5, 1) == 5

    def test_zero_size_falls_back_to_intent_count(self):
        assert _resolve_requested_count(0, 3) == 3

    def test_none_size_falls_back_to_intent_count(self):
        assert _resolve_requested_count(None, 2) == 2

    def test_string_size_parsed(self):
        assert _resolve_requested_count("4", 1) == 4

    def test_garbage_size_falls_back(self):
        assert _resolve_requested_count("not-a-number", 7) == 7

    def test_negative_size_falls_back(self):
        assert _resolve_requested_count(-1, 2) == 2


# ---------------------------------------------------------------------------
# FIX 5: immediate-fill sanity accounting is callable (no undefined _ctx)
# ---------------------------------------------------------------------------

class TestSanityCheckerFillPath:
    def test_apply_fill_signature_matches_router_call(self):
        """The router's immediate-fill call must satisfy apply_fill's signature.

        Before the fix, the call site passed undefined `_ctx` kwargs and omitted
        required ticker/side, so every live fill raised and skipped sanity
        accounting (duplicate-fill/overfill detection dead in production).
        """
        from merid.event_venues.kalshi.position_sanity_checker import (
            get_position_sanity_checker,
        )

        checker = get_position_sanity_checker()
        checker.register_order_intent(
            client_order_id="coid-test-fill-path",
            ticker="KXBTC15M-26JUL121500-00",
            side="BUY_YES",
            intended_count=1,
        )

        ok, err = checker.apply_fill(
            order_id="order-test-fill-path",
            fill_id="order-test-fill-path-0",
            ticker="KXBTC15M-26JUL121500-00",
            side="BUY_YES",
            filled_count=1,
            price_cents=50,
            strategy_group="test",
        )

        assert err is None or "duplicate" not in str(err), (
            f"apply_fill unexpectedly failed: {err}"
        )

    def test_router_fill_block_has_no_ctx_reference(self):
        """Static regression: the undefined _ctx kwargs must not reappear."""
        import inspect
        import merid.event_venues.kalshi.order_router as order_router

        source = inspect.getsource(order_router)
        assert "_ctx.combined_score" not in source
        assert "_ctx.fg_regime" not in source
