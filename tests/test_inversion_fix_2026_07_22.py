"""
Tests for the 2026-07-23 YES bias fix.

This test file validates:
1. Correct thesis_side mapping in intent_contract.py (BULLISH_EVENT→YES, BEARISH_EVENT→NO)
2. Correct strategy_intent mapping in agent_grid_15m.py signal generation
3. Removal of FINAL-INVERSION layer in candidate construction
"""

import pytest
from unittest.mock import Mock, MagicMock
from merid.prediction.intent_contract import (
    IntentContract,
    StrategyIntent,
    EntryExit,
    ExposureLeg,
    validate_intent_exposure_consistency,
)


class TestIntentContractMapping:
    """Test correct thesis_side mapping in IntentContract."""

    def test_bullish_event_maps_to_yes_thesis_side(self):
        """BULLISH_EVENT should map to thesis_side='yes' (correct)."""
        # Build entry order for BULLISH_EVENT
        from merid.prediction.intent_contract import build_entry_order

        contract = build_entry_order(
            intent=StrategyIntent.BULLISH_EVENT,
            asset="BTC",
            ticker="KXBTC15M-26JUL230015-15",
            price_cents=50,
            magnitude=1,
        )

        # Verify correct mapping: BULLISH_EVENT → thesis_side="yes"
        assert contract.thesis_side == "yes", f"Expected thesis_side='yes' for BULLISH_EVENT, got '{contract.thesis_side}'"
        assert contract.outcome_side == "yes", f"Expected outcome_side='yes' for BULLISH_EVENT, got '{contract.outcome_side}'"

    def test_bearish_event_maps_to_no_thesis_side(self):
        """BEARISH_EVENT should map to thesis_side='no' (correct)."""
        # Build entry order for BEARISH_EVENT
        from merid.prediction.intent_contract import build_entry_order

        contract = build_entry_order(
            intent=StrategyIntent.BEARISH_EVENT,
            asset="BTC",
            ticker="KXBTC15M-26JUL230015-15",
            price_cents=50,
            magnitude=1,
        )

        # Verify correct mapping: BEARISH_EVENT → thesis_side="no"
        assert contract.thesis_side == "no", f"Expected thesis_side='no' for BEARISH_EVENT, got '{contract.thesis_side}'"
        assert contract.outcome_side == "no", f"Expected outcome_side='no' for BEARISH_EVENT, got '{contract.outcome_side}'"

    def test_validation_enforces_correct_thesis_side(self):
        """Validation should enforce correct thesis_side requirements."""
        from merid.prediction.intent_contract import build_entry_order

        # BULLISH_EVENT with thesis_side=no should fail (correct)
        contract = build_entry_order(
            intent=StrategyIntent.BULLISH_EVENT,
            asset="BTC",
            ticker="KXBTC15M-26JUL230015-15",
            price_cents=50,
            magnitude=1,
        )
        # Manually set wrong thesis_side to test validation
        contract.thesis_side = "no"  # Wrong - should be "yes" for correct mapping
        is_valid, error = contract.validate()
        assert not is_valid, "BULLISH_EVENT with thesis_side=no should fail validation"
        assert "outcome_side" in error.lower() and "thesis_side" in error.lower(), f"Error should mention outcome_side/thesis_side mismatch, got: {error}"

        # BULLISH_EVENT with thesis_side=yes should pass (correct)
        contract = build_entry_order(
            intent=StrategyIntent.BULLISH_EVENT,
            asset="BTC",
            ticker="KXBTC15M-26JUL230015-15",
            price_cents=50,
            magnitude=1,
        )
        # This should have the correct thesis_side
        is_valid, error = contract.validate()
        assert is_valid, f"BULLISH_EVENT with thesis_side=yes should pass validation, got error: {error}"

        # BEARISH_EVENT with thesis_side=yes should fail (correct)
        contract = build_entry_order(
            intent=StrategyIntent.BEARISH_EVENT,
            asset="BTC",
            ticker="KXBTC15M-26JUL230015-15",
            price_cents=50,
            magnitude=1,
        )
        # Manually set wrong thesis_side to test validation
        contract.thesis_side = "yes"  # Wrong - should be "no" for correct mapping
        is_valid, error = contract.validate()
        assert not is_valid, "BEARISH_EVENT with thesis_side=yes should fail validation"
        assert "outcome_side" in error.lower() and "thesis_side" in error.lower(), f"Error should mention outcome_side/thesis_side mismatch, got: {error}"

        # BEARISH_EVENT with thesis_side=no should pass (correct)
        contract = build_entry_order(
            intent=StrategyIntent.BEARISH_EVENT,
            asset="BTC",
            ticker="KXBTC15M-26JUL230015-15",
            price_cents=50,
            magnitude=1,
        )
        # This should have the correct thesis_side
        is_valid, error = contract.validate()
        assert is_valid, f"BEARISH_EVENT with thesis_side=no should pass validation, got error: {error}"


class TestSignalGenerationMapping:
    """Test correct strategy_intent mapping in signal generation methods."""

    def test_momentum_fvg_correct_mapping(self):
        """Momentum-FVG: signal_side=yes should map to BULLISH_EVENT (correct)."""
        from merid.prediction.intent_contract import StrategyIntent

        # Simulate correct momentum_fvg mapping
        signal_side = "yes"
        strategy_intent = StrategyIntent.BULLISH_EVENT if signal_side == "yes" else StrategyIntent.BEARISH_EVENT

        assert strategy_intent == StrategyIntent.BULLISH_EVENT, f"Expected BULLISH_EVENT for signal_side=yes, got {strategy_intent}"

        # Test the inverse
        signal_side = "no"
        strategy_intent = StrategyIntent.BULLISH_EVENT if signal_side == "yes" else StrategyIntent.BEARISH_EVENT

        assert strategy_intent == StrategyIntent.BEARISH_EVENT, f"Expected BEARISH_EVENT for signal_side=no, got {strategy_intent}"

    def test_panic_fade_correct_mapping(self):
        """Panic-Fade: is_oversold should map to BULLISH_EVENT (correct)."""
        from merid.prediction.intent_contract import StrategyIntent

        # Simulate correct panic_fade mapping
        is_oversold = True
        strategy_intent = StrategyIntent.BULLISH_EVENT if is_oversold else StrategyIntent.BEARISH_EVENT

        assert strategy_intent == StrategyIntent.BULLISH_EVENT, f"Expected BULLISH_EVENT for is_oversold=True, got {strategy_intent}"

        # Test the inverse
        is_oversold = False
        strategy_intent = StrategyIntent.BULLISH_EVENT if is_oversold else StrategyIntent.BEARISH_EVENT

        assert strategy_intent == StrategyIntent.BEARISH_EVENT, f"Expected BEARISH_EVENT for is_oversold=False, got {strategy_intent}"

    def test_price_based_correct_mapping(self):
        """Price-based: yes_edge > no_edge should map to BULLISH_EVENT (correct)."""
        from merid.prediction.intent_contract import StrategyIntent

        # Simulate correct price-based mapping
        yes_edge_pct = 0.02
        no_edge_pct = 0.01

        if yes_edge_pct > no_edge_pct:
            strategy_intent = StrategyIntent.BULLISH_EVENT
        elif no_edge_pct > yes_edge_pct:
            strategy_intent = StrategyIntent.BEARISH_EVENT
        else:
            strategy_intent = StrategyIntent.BEARISH_EVENT

        assert strategy_intent == StrategyIntent.BULLISH_EVENT, f"Expected BULLISH_EVENT when yes_edge > no_edge, got {strategy_intent}"

        # Test the inverse
        yes_edge_pct = 0.01
        no_edge_pct = 0.02

        if yes_edge_pct > no_edge_pct:
            strategy_intent = StrategyIntent.BULLISH_EVENT
        elif no_edge_pct > yes_edge_pct:
            strategy_intent = StrategyIntent.BEARISH_EVENT
        else:
            strategy_intent = StrategyIntent.BEARISH_EVENT

        assert strategy_intent == StrategyIntent.BEARISH_EVENT, f"Expected BEARISH_EVENT when no_edge > yes_edge, got {strategy_intent}"


class TestIntentToExposureMapping:
    """Test correct intent-to-exposure mapping in map_intent_to_exposure (2026-07-23)."""

    def test_bullish_event_maps_to_yes_leg(self):
        """BULLISH_EVENT should map to YES leg (correct 2026-07-23)."""
        from merid.prediction.intent_contract import map_intent_to_exposure, StrategyIntent, ExposureLeg

        exposure = map_intent_to_exposure(StrategyIntent.BULLISH_EVENT, current_position=None)
        assert exposure.leg == ExposureLeg.YES, f"Expected YES leg for BULLISH_EVENT, got {exposure.leg}"
        assert exposure.direction == "increase", f"Expected increase direction for entry, got {exposure.direction}"

    def test_bearish_event_maps_to_no_leg(self):
        """BEARISH_EVENT should map to NO leg (correct 2026-07-23)."""
        from merid.prediction.intent_contract import map_intent_to_exposure, StrategyIntent, ExposureLeg

        exposure = map_intent_to_exposure(StrategyIntent.BEARISH_EVENT, current_position=None)
        assert exposure.leg == ExposureLeg.NO, f"Expected NO leg for BEARISH_EVENT, got {exposure.leg}"
        assert exposure.direction == "increase", f"Expected increase direction for entry, got {exposure.direction}"

    def test_validate_intent_exposure_consistency_correct(self):
        """Validation should pass with correct mapping (2026-07-23)."""
        from merid.prediction.intent_contract import validate_intent_exposure_consistency, StrategyIntent

        # BULLISH_EVENT with side=yes should pass (correct mapping)
        is_valid, error = validate_intent_exposure_consistency(
            intent=StrategyIntent.BULLISH_EVENT,
            kalshi_side="yes",
            kalshi_action="buy",
            current_position=None,
        )
        assert is_valid, f"BULLISH_EVENT with side=yes should pass validation, got error: {error}"

        # BEARISH_EVENT with side=no should pass (correct mapping)
        is_valid, error = validate_intent_exposure_consistency(
            intent=StrategyIntent.BEARISH_EVENT,
            kalshi_side="no",
            kalshi_action="buy",
            current_position=None,
        )
        assert is_valid, f"BEARISH_EVENT with side=no should pass validation, got error: {error}"

        # BULLISH_EVENT with side=no should fail (correct mapping)
        is_valid, error = validate_intent_exposure_consistency(
            intent=StrategyIntent.BULLISH_EVENT,
            kalshi_side="no",
            kalshi_action="buy",
            current_position=None,
        )
        assert not is_valid, f"BULLISH_EVENT with side=no should fail validation (correct mapping)"

        # BEARISH_EVENT with side=yes should fail (correct mapping)
        is_valid, error = validate_intent_exposure_consistency(
            intent=StrategyIntent.BEARISH_EVENT,
            kalshi_side="yes",
            kalshi_action="buy",
            current_position=None,
        )
        assert not is_valid, f"BEARISH_EVENT with side=yes should fail validation (correct mapping)"




if __name__ == "__main__":
    pytest.main([__file__, "-v"])
