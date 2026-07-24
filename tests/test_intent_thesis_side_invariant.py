"""
Intent → Thesis Side Mapping Invariant Test Harness

Tests that strategy intent maps correctly to thesis_side for Kalshi 15-minute
Up/Down markets across BTC/ETH/SOL/XRP/DOGE.

Invariant Mapping (2026-07-23 CORRECTED):
- BULLISH_EVENT → thesis_side = YES (bet on event occurring: "up in 15m")
- BEARISH_EVENT → thesis_side = NO (bet against event occurring: "not up in 15m")

This invariant ensures that:
1. The system is not structurally biased to YES
2. Intent → thesis_side mapping is deterministic and testable
3. Exit orders use the correct thesis_side from position state

Usage:
    pytest tests/test_intent_thesis_side_invariant.py
    pytest tests/test_intent_thesis_side_invariant.py::TestIntentThesisSideMapping::test_entry_mapping
"""

from __future__ import annotations

import pytest
from typing import Dict, Optional

try:
    from merid.prediction.signal_terminology import StrategyIntent
    from merid.prediction.intent_contract import (
        build_entry_order,
        build_exit_order,
        ExposureLeg,
        ExitReason,
        validate_intent_exposure_consistency,
    )
except ImportError:
    pytest.skip("Required modules not available")


class TestIntentThesisSideMapping:
    """Test suite for intent → thesis_side mapping invariant."""
    
    def test_bullish_event_to_yes_thesis(self):
        """Test that BULLISH_EVENT maps to thesis_side=YES for entry orders."""
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            contract = build_entry_order(
                intent=StrategyIntent.BULLISH_EVENT,
                asset=asset,
                ticker=f"KX{asset}15M-TEST",
                price_cents=50,
                magnitude=1,
                rationale="Test bullish entry",
            )
            
            # Validate contract
            is_valid, error = contract.validate()
            assert is_valid, f"{asset} bullish entry contract invalid: {error}"
            
            # Check thesis_side mapping
            assert contract.thesis_side.lower() == "yes", (
                f"{asset}: BULLISH_EVENT should map to thesis_side=yes, got {contract.thesis_side}"
            )
            
            # Check outcome_side matches thesis_side
            assert contract.outcome_side.lower() == contract.thesis_side.lower(), (
                f"{asset}: outcome_side must match thesis_side"
            )
            
            # Check target leg is YES
            assert contract.target_leg == ExposureLeg.YES, (
                f"{asset}: BULLISH_EVENT should target YES leg"
            )
    
    def test_bearish_event_to_no_thesis(self):
        """Test that BEARISH_EVENT maps to thesis_side=NO for entry orders."""
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            contract = build_entry_order(
                intent=StrategyIntent.BEARISH_EVENT,
                asset=asset,
                ticker=f"KX{asset}15M-TEST",
                price_cents=50,
                magnitude=1,
                rationale="Test bearish entry",
            )
            
            # Validate contract
            is_valid, error = contract.validate()
            assert is_valid, f"{asset} bearish entry contract invalid: {error}"
            
            # Check thesis_side mapping
            assert contract.thesis_side.lower() == "no", (
                f"{asset}: BEARISH_EVENT should map to thesis_side=no, got {contract.thesis_side}"
            )
            
            # Check outcome_side matches thesis_side
            assert contract.outcome_side.lower() == contract.thesis_side.lower(), (
                f"{asset}: outcome_side must match thesis_side"
            )
            
            # Check target leg is NO
            assert contract.target_leg == ExposureLeg.NO, (
                f"{asset}: BEARISH_EVENT should target NO leg"
            )
    
    def test_exit_preserves_thesis_side(self):
        """Test that exit orders preserve the thesis_side of the position being closed."""
        # Test exiting YES position
        contract_yes = build_exit_order(
            current_position=ExposureLeg.YES,
            asset="BTC",
            ticker="KXBTC15M-TEST",
            price_cents=90,
            magnitude=1,
            exit_reason=ExitReason.EXIT_TP,
            rationale="Test exit YES",
        )
        
        is_valid, error = contract_yes.validate()
        assert is_valid, f"Exit YES contract invalid: {error}"
        assert contract_yes.thesis_side.lower() == "yes", (
            "Exit YES position should preserve thesis_side=yes"
        )
        
        # Test exiting NO position
        contract_no = build_exit_order(
            current_position=ExposureLeg.NO,
            asset="BTC",
            ticker="KXBTC15M-TEST",
            price_cents=10,
            magnitude=1,
            exit_reason=ExitReason.EXIT_SL,
            rationale="Test exit NO",
        )
        
        is_valid, error = contract_no.validate()
        assert is_valid, f"Exit NO contract invalid: {error}"
        assert contract_no.thesis_side.lower() == "no", (
            "Exit NO position should preserve thesis_side=no"
        )
    
    def test_intent_exposure_consistency_validation(self):
        """Test that validate_intent_exposure_consistency enforces correct mapping."""
        # BULLISH_EVENT with BUY YES should pass
        is_valid, error = validate_intent_exposure_consistency(
            intent=StrategyIntent.BULLISH_EVENT,
            kalshi_side="yes",
            kalshi_action="buy",
            current_position=None,
        )
        assert is_valid, f"BULLISH_EVENT + BUY YES should be valid: {error}"
        
        # BULLISH_EVENT with BUY NO should fail
        is_valid, error = validate_intent_exposure_consistency(
            intent=StrategyIntent.BULLISH_EVENT,
            kalshi_side="no",
            kalshi_action="buy",
            current_position=None,
        )
        assert not is_valid, "BULLISH_EVENT + BUY NO should fail"
        assert "leg mismatch" in error.lower() or "direction mismatch" in error.lower()
        
        # BEARISH_EVENT with BUY NO should pass
        is_valid, error = validate_intent_exposure_consistency(
            intent=StrategyIntent.BEARISH_EVENT,
            kalshi_side="no",
            kalshi_action="buy",
            current_position=None,
        )
        assert is_valid, f"BEARISH_EVENT + BUY NO should be valid: {error}"
        
        # BEARISH_EVENT with BUY YES should fail
        is_valid, error = validate_intent_exposure_consistency(
            intent=StrategyIntent.BEARISH_EVENT,
            kalshi_side="yes",
            kalshi_action="buy",
            current_position=None,
        )
        assert not is_valid, "BEARISH_EVENT + BUY YES should fail"
        assert "leg mismatch" in error.lower() or "direction mismatch" in error.lower()
    
    def test_entry_orders_must_use_buy_actions(self):
        """Test that entry orders always use BUY actions (never SELL)."""
        for intent in [StrategyIntent.BULLISH_EVENT, StrategyIntent.BEARISH_EVENT]:
            contract = build_entry_order(
                intent=intent,
                asset="BTC",
                ticker="KXBTC15M-TEST",
                price_cents=50,
                magnitude=1,
                rationale="Test entry action invariant",
            )
            
            # Entry orders must use BUY action
            assert contract.kalshi_payload.action == "buy", (
                f"Entry orders must use BUY action, got {contract.kalshi_payload.action} "
                f"for intent={intent}"
            )
    
    def test_exit_orders_can_use_sell_or_buy(self):
        """Test that exit orders can use direct SELL or equivalent opposite BUY."""
        # Direct exit: SELL YES
        contract_direct = build_exit_order(
            current_position=ExposureLeg.YES,
            asset="BTC",
            ticker="KXBTC15M-TEST",
            price_cents=90,
            magnitude=1,
            exit_reason=ExitReason.EXIT_TP,
            rationale="Direct exit",
        )
        assert contract_direct.kalshi_payload.action == "sell"
        assert contract_direct.kalshi_payload.side == "yes"
        
        # Equivalent exit: BUY NO (with prefer_liquidity_side)
        contract_equivalent = build_exit_order(
            current_position=ExposureLeg.YES,
            asset="BTC",
            ticker="KXBTC15M-TEST",
            price_cents=90,
            magnitude=1,
            exit_reason=ExitReason.EXIT_TP,
            rationale="Equivalent exit",
            prefer_liquidity_side="no",
        )
        assert contract_equivalent.kalshi_payload.action == "buy"
        assert contract_equivalent.kalshi_payload.side == "no"
        
        # Both should be valid
        is_valid_direct, _ = contract_direct.validate()
        is_valid_equivalent, _ = contract_equivalent.validate()
        assert is_valid_direct, "Direct exit should be valid"
        assert is_valid_equivalent, "Equivalent exit should be valid"
    
    def test_neutral_intent_cannot_build_entry(self):
        """Test that NEUTRAL intent cannot build entry orders."""
        with pytest.raises(ValueError, match="NEUTRAL intent"):
            build_entry_order(
                intent=StrategyIntent.NEUTRAL,
                asset="BTC",
                ticker="KXBTC15M-TEST",
                price_cents=50,
                magnitude=1,
                rationale="Test neutral entry",
            )
    
    def test_per_asset_consistency(self):
        """Test that mapping is consistent across all 5 assets."""
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        for asset in assets:
            # Test bullish
            bullish_contract = build_entry_order(
                intent=StrategyIntent.BULLISH_EVENT,
                asset=asset,
                ticker=f"KX{asset}15M-TEST",
                price_cents=50,
                magnitude=1,
                rationale="Test per-asset bullish",
            )
            assert bullish_contract.thesis_side.lower() == "yes"
            assert bullish_contract.target_leg == ExposureLeg.YES
            
            # Test bearish
            bearish_contract = build_entry_order(
                intent=StrategyIntent.BEARISH_EVENT,
                asset=asset,
                ticker=f"KX{asset}15M-TEST",
                price_cents=50,
                magnitude=1,
                rationale="Test per-asset bearish",
            )
            assert bearish_contract.thesis_side.lower() == "no"
            assert bearish_contract.target_leg == ExposureLeg.NO


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
