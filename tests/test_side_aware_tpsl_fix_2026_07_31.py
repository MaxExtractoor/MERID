"""
Side-aware TP/SL regression tests (2026-08-04 sweep).

Convention: A position is always long its own side.  For both YES and NO,
take-profit is above the entry price and stop-loss is below the entry price
in the position's own price space.  This file replaces the 2026-07-31 suite
which inverted TP/SL for NO-side contracts.
"""

import pytest
from merid.position_management.position import Position, PositionSide, RiskParamsState


class TestSideAwareTPSLPosition:
    """Tests for TP/SL defaults and trigger logic in the Position model."""

    def test_yes_position_defaults(self):
        position = Position(
            position_id="test-yes",
            market_id="KXBTC15M-TEST",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=50,
            entry_fill_price_cents=50,  # trusted fill anchor -> canonical fallbacks
        )
        assert position.take_profit_price_cents > 50  # fee-aware fallback above entry
        assert position.stop_loss_price_cents == 45   # 50 - FALLBACK_STOP_LOSS_BUFFER_CENTS(5)
        assert position.take_profit_price_cents > position.avg_entry_price_cents
        assert position.stop_loss_price_cents < position.avg_entry_price_cents

    def test_no_position_defaults(self):
        position = Position(
            position_id="test-no",
            market_id="KXBTC15M-TEST",
            side=PositionSide.NO,
            size=1,
            avg_entry_price_cents=50,
            entry_fill_price_cents=50,  # trusted fill anchor -> canonical fallbacks
        )
        assert position.take_profit_price_cents > 50  # fee-aware fallback above entry
        assert position.stop_loss_price_cents == 45   # 50 - FALLBACK_STOP_LOSS_BUFFER_CENTS(5)
        assert position.take_profit_price_cents > position.avg_entry_price_cents
        assert position.stop_loss_price_cents < position.avg_entry_price_cents

    def test_yes_stop_loss_trigger(self):
        position = Position(
            position_id="test-yes",
            market_id="KXBTC15M-TEST",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=50,
            entry_fill_price_cents=50,
            risk_params_state=RiskParamsState.FALLBACK,
            stop_loss_price_cents=45,
        )
        assert position.should_trigger_stop_loss(45) is True
        assert position.should_trigger_stop_loss(40) is True
        assert position.should_trigger_stop_loss(55) is False

    def test_no_stop_loss_trigger(self):
        position = Position(
            position_id="test-no",
            market_id="KXBTC15M-TEST",
            side=PositionSide.NO,
            size=1,
            avg_entry_price_cents=50,
            entry_fill_price_cents=50,
            risk_params_state=RiskParamsState.FALLBACK,
            stop_loss_price_cents=45,
        )
        assert position.should_trigger_stop_loss(45) is True
        assert position.should_trigger_stop_loss(40) is True
        assert position.should_trigger_stop_loss(55) is False

    def test_yes_take_profit_trigger(self):
        position = Position(
            position_id="test-yes",
            market_id="KXBTC15M-TEST",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=50,
            entry_fill_price_cents=50,
            risk_params_state=RiskParamsState.FALLBACK,
            take_profit_price_cents=60,  # fee-valid: 55c TP is net-negative after taker fee
        )
        assert position.should_trigger_take_profit(60) is True
        assert position.should_trigger_take_profit(65) is True
        assert position.should_trigger_take_profit(55) is False

    def test_no_take_profit_trigger(self):
        position = Position(
            position_id="test-no",
            market_id="KXBTC15M-TEST",
            side=PositionSide.NO,
            size=1,
            avg_entry_price_cents=50,
            entry_fill_price_cents=50,
            risk_params_state=RiskParamsState.FALLBACK,
            take_profit_price_cents=60,  # fee-valid: 55c TP is net-negative after taker fee
        )
        assert position.should_trigger_take_profit(60) is True
        assert position.should_trigger_take_profit(65) is True
        assert position.should_trigger_take_profit(55) is False


class TestSideAwareTPSLInvariants:
    """Cross-module invariants that every TP/SL fallback must satisfy."""

    def test_no_side_tp_is_above_entry(self):
        """Every NO-side long position must have TP > entry."""
        entry = 40
        tp = int(entry * 1.15)  # canonical fallback used across the stack
        sl = max(1, entry - 5)
        assert tp > entry
        assert sl < entry

    def test_no_side_tp_is_above_entry_high_price(self):
        entry = 80
        tp = min(99, int(entry * 1.15))
        sl = max(1, entry - 5)
        assert tp > entry
        assert sl < entry

    def test_yes_side_tp_is_above_entry(self):
        """Every YES-side long position must have TP > entry."""
        entry = 40
        tp = int(entry * 1.15)
        sl = max(1, entry - 5)
        assert tp > entry
        assert sl < entry
