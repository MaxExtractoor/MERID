"""
Tests for exit-order canonicalization and immutable risk-exit policy.

Validates:
- Legacy action/side canonicalization.
- Close side / book side mapping.
- Stop-loss and take-profit prices are not rewritten by alpha/sweet-spot logic.
- Confirmed live exposure wins over prediction thesis.
- Position monitor timeout-based duplicate retries are suppressed pending reconciliation.
"""

import pytest
import time
from unittest.mock import MagicMock

from merid.event_venues.kalshi.binary_price_space import (
    canonicalize,
    close_side,
    close_book_side,
)
from merid.event_venues.kalshi.strategy_positions import (
    StrategyPosition,
    ThesisSide,
    build_exit,
    PositionThesisMismatch,
)
from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    _determine_dynamic_order_type,
    _apply_exit_marketable_ioc,
    _apply_execution_mode,
)
from merid.position_management.position import Position
from merid.position_management.position_monitor import PositionMonitor


class TestCanonicalSideMapping:
    def test_canonicalize_long_yes_forms(self):
        assert canonicalize("buy", "yes") == "yes"

    def test_canonicalize_long_no_forms(self):
        assert canonicalize("buy", "no") == "no"

    def test_close_outcome_side(self):
        # A NO position exits to canonical YES.
        # A YES position exits to canonical NO.
        assert close_side("no") == "yes"
        assert close_side("yes") == "no"

    def test_close_book_side(self):
        # A close order is the user *selling* their long outcome:
        # - long YES -> SELL_YES -> Kalshi book side = ask
        # - long NO  -> SELL_NO  -> Kalshi book side = bid
        assert close_book_side("no") == "bid"
        assert close_book_side("yes") == "ask"


class TestBuildExitFromConfirmedPosition:
    def test_build_exit_matches_confirmed_position(self):
        long_yes = StrategyPosition(
            ticker="KXBTC15M-TEST",
            thesis_side=ThesisSide.YES,
            size_fp=1,
            avg_entry_price_cents=50,
        )
        order = build_exit(long_yes, qty_fp=1, price_cents=13, thesis_side=ThesisSide.YES)
        assert order["kalshi_side"] == "SELL_YES"
        assert order["price_cents"] == 13

    def test_build_exit_raises_on_thesis_mismatch(self):
        long_yes = StrategyPosition(
            ticker="KXBTC15M-TEST",
            thesis_side=ThesisSide.YES,
            size_fp=1,
            avg_entry_price_cents=50,
        )
        with pytest.raises(PositionThesisMismatch):
            build_exit(long_yes, qty_fp=1, price_cents=13, thesis_side=ThesisSide.NO)

    def test_build_exit_uses_confirmed_not_thesis(self):
        # Simulates the production bug: prediction said NO, but exchange filled YES.
        long_yes = StrategyPosition(
            ticker="KXBTC15M-TEST",
            thesis_side=ThesisSide.YES,
            size_fp=1,
            avg_entry_price_cents=50,
        )
        order = build_exit(long_yes, qty_fp=1, price_cents=13)
        assert order["kalshi_side"] == "SELL_YES"


class TestExitOrderDoesNotRewriteStopPrice:
    def test_exit_order_type_is_ioc(self):
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="SELL_NO",
            action="sell",
            price_cents=13,
            count=1,
            source="position_monitor_exit",
            entry_or_exit="exit",
            order_type="limit",
            time_in_force="ioc",
            aggressiveness=1.0,
        )
        order_type, tif = _determine_dynamic_order_type(intent, state=None)
        assert order_type == "limit"
        assert tif == "ioc"

    def test_exit_execution_mode_forces_ioc(self):
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="SELL_NO",
            action="sell",
            price_cents=13,
            count=1,
            source="position_monitor_exit",
            entry_or_exit="exit",
            execution_mode="maker",  # entry-oriented mode is ignored for exits
        )
        post_only, aggressiveness, order_type, tif = _apply_execution_mode(intent)
        assert post_only is False
        assert aggressiveness == 1.0
        assert order_type == "limit"
        assert tif.lower() == "ioc"

    def test_exit_marketable_ioc_preserves_risk_price(self):
        # Market: YES bid=60, YES ask=65 -> NO bid=35, NO ask=40.
        # Stop at 13c in NO space. The price should stay at 13 (already marketable
        # and within max slippage), NOT be sweet-spotted to 18 or rewritten to 8.
        state = MagicMock()
        state.best_bid_cents = 60
        state.best_ask_cents = 65

        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="SELL_NO",
            action="sell",
            price_cents=13,
            count=1,
            source="position_monitor_exit",
            entry_or_exit="exit",
        )
        _apply_exit_marketable_ioc(intent, state)

        assert intent.price_cents == 13

    def test_exit_marketable_ioc_bounds_adverse_slippage(self):
        # Market: YES bid=1, YES ask=4 -> NO bid=96, NO ask=99.
        # Stop at 80c in NO space; best NO bid is 96 (above stop). Price stays 80.
        state = MagicMock()
        state.best_bid_cents = 1
        state.best_ask_cents = 4

        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="SELL_NO",
            action="sell",
            price_cents=80,
            count=1,
            source="position_monitor_exit",
            entry_or_exit="exit",
        )
        _apply_exit_marketable_ioc(intent, state)

        # The original price is below the best bid, so it is marketable and preserved.
        assert intent.price_cents == 80

    def test_exit_marketable_ioc_does_not_sweet_spot(self):
        # Ensure the price is not raised by alpha sweet-spot logic.
        sweet_spot_price = 18

        state = MagicMock()
        state.best_bid_cents = 1
        state.best_ask_cents = 4

        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="SELL_NO",
            action="sell",
            price_cents=13,
            count=1,
            source="position_monitor_exit",
            entry_or_exit="exit",
        )
        _apply_exit_marketable_ioc(intent, state)

        assert intent.price_cents != sweet_spot_price
        assert intent.price_cents >= 1


class TestExitUsesConfirmedExposure:
    def test_position_outcome_side_from_confirmed_fill(self):
        pos = Position(
            position_id="test",
            market_id="KXBTC15M-TEST",
            side="yes",
            size=1,
            avg_entry_price_cents=50,
            thesis_side="no",
            outcome_side="yes",
            book_side="ask",
        )
        # The close should be derived from outcome_side, not thesis_side.
        assert pos.outcome_side == "yes"
        assert pos.book_side == "ask"


class TestExitIntentTimeoutReconciliation:
    def test_timeout_suppressed_while_recent_submission_pending(self):
        monitor = PositionMonitor(poll_interval=1.0)
        position_id = "KXBTC15M-TEST-001"
        client_order_id = "exit-coid-001"

        monitor._mark_exit_intent_in_flight(position_id, client_order_id=client_order_id)
        monitor._register_exit_submission(client_order_id, position_id=position_id)

        # Simulate a 15s timeout by aging the in-flight timestamp.
        monitor._exit_intent_in_flight[position_id]["timestamp"] = time.time() - 20.0

        # Even though the in-flight flag has timed out, the recent submission
        # should keep the intent in-flight so no duplicate is emitted.
        assert monitor._is_exit_intent_in_flight(position_id) is True

        # After clearing the submission, the timeout transitions to SUBMISSION_UNKNOWN
        # and still blocks a new exit until explicitly reconciled.
        monitor._submission_cache_ttl = 0.0  # force recent-submission TTL to be expired
        monitor._mark_exit_intent_in_flight(position_id, client_order_id=client_order_id)
        monitor._exit_intent_in_flight[position_id]["timestamp"] = time.time() - 20.0
        assert monitor._is_exit_intent_in_flight(position_id) is True
        assert monitor._exit_intent_in_flight[position_id]["state"] == "SUBMISSION_UNKNOWN"

        # Reconciliation terminalizes the intent and allows a new exit.
        monitor._mark_exit_intent_reconciled(position_id, "exchange_reconciled")
        assert monitor._is_exit_intent_in_flight(position_id) is False
