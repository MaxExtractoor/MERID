"""
Cross-Layer Invariants Test Harness

Tests cross-layer invariants for diversity, exit coverage, and bias across
the entire MERID 15-minute Kalshi crypto trading system.

This test suite validates:
1. Signal diversity invariant across all 5 assets
2. Exit coverage invariant (every position has exit plan)
3. Bias invariant (no structural YES/NO bias)
4. Intent → thesis_side → Kalshi leg consistency
5. Position state invariants
6. Exit sizing invariants

Usage:
    pytest tests/test_cross_layer_invariants.py
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from typing import Dict, List

try:
    from merid.prediction.signal_terminology import StrategyIntent
    from merid.prediction.intent_contract import (
        build_entry_order,
        build_exit_order,
        ExposureLeg,
        ExitReason,
    )
    from merid.prediction.position_exit_invariants import (
        PositionExitManager,
        ExitPlanType,
        validate_position_state_invariant,
        validate_exit_sizing_invariant,
    )
    from merid.prediction.ta_intent_mapping import (
        TAIntentMapper,
        TASignal,
        TASignalType,
    )
    from merid.prediction.trade_contract import (
        TradeContract,
        ContractLayer,
        build_trade_contract_from_signal,
    )
except ImportError:
    pytest.skip("Required modules not available")


class TestCrossLayerDiversityInvariant:
    """Test suite for cross-layer signal diversity invariant."""
    
    def test_all_assets_generate_both_intents(self):
        """Test that all 5 assets can generate both bullish and bearish intents."""
        mapper = TAIntentMapper()
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        for asset in assets:
            # Test bullish signal with asset-specific velocity
            # Use higher velocity to ensure it passes the threshold
            velocity_multiplier = {
                "BTC": 2.0,
                "ETH": 2.5,
                "SOL": 3.0,
                "XRP": 2.5,
                "DOGE": 4.0,
            }.get(asset, 2.0)
            
            bullish_signal = TASignal(
                signal_type=TASignalType.MOMENTUM,
                asset=asset,
                direction="bullish",
                confidence=0.8,
                velocity=0.0001 * velocity_multiplier,
            )
            bullish_intent, _, _ = mapper.map_signal_to_intent(bullish_signal)
            assert bullish_intent == StrategyIntent.BULLISH_EVENT, f"{asset} should generate BULLISH_EVENT"
            
            # Test bearish signal
            bearish_signal = TASignal(
                signal_type=TASignalType.MOMENTUM,
                asset=asset,
                direction="bearish",
                confidence=0.8,
                velocity=-0.0001 * velocity_multiplier,
            )
            bearish_intent, _, _ = mapper.map_signal_to_intent(bearish_signal)
            assert bearish_intent == StrategyIntent.BEARISH_EVENT, f"{asset} should generate BEARISH_EVENT"
    
    def test_intent_to_thesis_side_to_leg_consistency(self):
        """Test intent → thesis_side → Kalshi leg consistency across all assets."""
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        for asset in assets:
            # Test BULLISH_EVENT → thesis_side=yes → YES leg
            bullish_contract = build_entry_order(
                intent=StrategyIntent.BULLISH_EVENT,
                asset=asset,
                ticker=f"KX{asset}15M-TEST",
                price_cents=50,
                magnitude=1,
            )
            assert bullish_contract.thesis_side.lower() == "yes"
            assert bullish_contract.target_leg.value == "yes"
            
            # Test BEARISH_EVENT → thesis_side=no → NO leg
            bearish_contract = build_entry_order(
                intent=StrategyIntent.BEARISH_EVENT,
                asset=asset,
                ticker=f"KX{asset}15M-TEST",
                price_cents=50,
                magnitude=1,
            )
            assert bearish_contract.thesis_side.lower() == "no"
            assert bearish_contract.target_leg.value == "no"


class TestCrossLayerExitCoverageInvariant:
    """Test suite for cross-layer exit coverage invariant."""
    
    def test_every_position_has_exit_plan(self):
        """Test that every position has exactly one active exit plan."""
        manager = PositionExitManager()
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        for asset in assets:
            # Create position
            position_id = f"{asset}-TEST-001"
            state = manager.get_or_create_position_state(
                position_id=position_id,
                market_id=f"KX{asset}15M-TEST",
                asset=asset,
                current_size=10,
                entry_price_cents=50.0,
                thesis_side="yes",
            )
            
            # Add exit plan
            success, _ = manager.add_exit_plan(
                position_id=position_id,
                plan_type=ExitPlanType.TAKE_PROFIT,
                trigger_price_cents=75.0,
                size_fraction=1.0,
            )
            assert success, f"{asset} should accept exit plan"
            
            # Validate invariant
            is_valid, error = validate_position_state_invariant(state)
            assert is_valid, f"{asset} position state should be valid: {error}"
    
    def test_exit_sizing_position_based(self):
        """Test that exit sizing is position-based, not bankroll-based."""
        manager = PositionExitManager()
        
        # Create position with size 10
        position_id = "BTC-TEST-001"
        state = manager.get_or_create_position_state(
            position_id=position_id,
            market_id="KXBTC15M-TEST",
            asset="BTC",
            current_size=10,
            entry_price_cents=50.0,
            thesis_side="yes",
        )
        
        # Add exit plan with 50% fraction
        manager.add_exit_plan(
            position_id=position_id,
            plan_type=ExitPlanType.TAKE_PROFIT,
            trigger_price_cents=75.0,
            size_fraction=0.5,
        )
        
        # Calculate exit size
        exit_size, error = manager.calculate_exit_size(position_id)
        assert exit_size == 5, f"Exit size should be 5 (50% of 10), got {exit_size}"
        assert error is None
        
        # Validate invariant
        is_valid, error = validate_exit_sizing_invariant(state, exit_size)
        assert is_valid, f"Exit sizing should be valid: {error}"
    
    def test_exit_size_cannot_exceed_position(self):
        """Test that exit size cannot exceed position size."""
        state = type('obj', (object,), {
            'current_size': 10,
            'position_id': 'TEST',
        })()
        
        # Try to exit more than position size
        is_valid, error = validate_exit_sizing_invariant(state, exit_size=15)
        assert not is_valid, "Exit size exceeding position should fail"
        assert "exceeds open position size" in error.lower()


class TestCrossLayerBiasInvariant:
    """Test suite for cross-layer bias invariant."""
    
    def test_no_structural_yes_bias(self):
        """Test that system is not structurally biased to YES."""
        # Test that both intents are possible
        mapper = TAIntentMapper()
        
        # BULLISH_EVENT should map to YES leg
        bullish_signal = TASignal(
            signal_type=TASignalType.MOMENTUM,
            asset="BTC",
            direction="bullish",
            confidence=0.8,
            velocity=0.0001,
        )
        bullish_intent, _, _ = mapper.map_signal_to_intent(bullish_signal)
        assert bullish_intent == StrategyIntent.BULLISH_EVENT
        
        # BEARISH_EVENT should map to NO leg (not YES)
        bearish_signal = TASignal(
            signal_type=TASignalType.MOMENTUM,
            asset="BTC",
            direction="bearish",
            confidence=0.8,
            velocity=-0.0001,
        )
        bearish_intent, _, _ = mapper.map_signal_to_intent(bearish_signal)
        assert bearish_intent == StrategyIntent.BEARISH_EVENT
    
    def test_per_asset_bias_correction(self):
        """Test that per-asset bias correction is applied."""
        mapper = TAIntentMapper()
        
        # SOL has bullish_bias_correction=0.05
        sol_signal = TASignal(
            signal_type=TASignalType.MOMENTUM,
            asset="SOL",
            direction="bullish",
            confidence=0.8,
            velocity=0.0002,
        )
        intent, confidence, _ = mapper.map_signal_to_intent(sol_signal)
        # Bias correction may reduce confidence below threshold, resulting in NEUTRAL
        if intent == StrategyIntent.BULLISH_EVENT:
            assert confidence < 0.8, "SOL bullish confidence should be reduced by bias correction"
            assert confidence == 0.75  # 0.8 - 0.05
        else:
            assert intent == StrategyIntent.NEUTRAL, "Bias correction may reduce to NEUTRAL"
        
        # DOGE has bearish_bias_correction=0.05
        doge_signal = TASignal(
            signal_type=TASignalType.MOMENTUM,
            asset="DOGE",
            direction="bearish",
            confidence=0.8,
            velocity=-0.0003,
        )
        intent, confidence, _ = mapper.map_signal_to_intent(doge_signal)
        # Bias correction may reduce confidence below threshold, resulting in NEUTRAL
        if intent == StrategyIntent.BEARISH_EVENT:
            assert confidence < 0.8, "DOGE bearish confidence should be reduced by bias correction"
            assert confidence == 0.75  # 0.8 - 0.05
        else:
            assert intent == StrategyIntent.NEUTRAL, "Bias correction may reduce to NEUTRAL"


class TestCrossLayerContractConsistency:
    """Test suite for cross-layer contract consistency."""
    
    def test_contract_layers_consistent(self):
        """Test that contract layers are consistent across all assets."""
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        for asset in assets:
            signal_data = {
                "strategy_intent": StrategyIntent.BULLISH_EVENT,
                "thesis_side": "yes",
                "kalshi_side": "yes",
                "kalshi_action": "buy",
                "price_cents": 50,
                "contracts": 1,
                "confidence": 0.8,
            }
            
            config_data = {
                "asset": asset,
                "market_id": f"KX{asset}15M-TEST",
            }
            
            market_data = {
                "spot_price": 50000.0 if asset == "BTC" else 3000.0,
            }
            
            # Build contract without requiring all layers
            from merid.prediction.trade_contract import ContractBuilder
            builder = ContractBuilder()
            contract = builder.build_from_signal(signal_data, config_data, market_data)
            
            # Validate only present layers
            from merid.prediction.trade_contract import ContractValidator
            validator = ContractValidator(require_all_layers=False)
            is_valid, errors = validator.validate_contract(contract)
            
            assert is_valid, f"{asset} contract should be valid: {errors}"
            assert contract.asset == asset
            assert contract.strategy_intent == StrategyIntent.BULLISH_EVENT
            assert contract.thesis_side == "yes"
    
    def test_cross_layer_intent_thesis_consistency(self):
        """Test that intent → thesis_side is consistent across layers."""
        signal_data = {
            "strategy_intent": StrategyIntent.BEARISH_EVENT,
            "thesis_side": "no",
            "kalshi_side": "no",
            "kalshi_action": "buy",
            "price_cents": 50,
            "contracts": 1,
            "confidence": 0.8,
        }
        
        config_data = {
            "asset": "BTC",
            "market_id": "KXBTC15M-TEST",
        }
        
        market_data = {"spot_price": 50000.0}
        
        # Build contract without requiring all layers
        from merid.prediction.trade_contract import ContractBuilder, ContractValidator
        builder = ContractBuilder()
        contract = builder.build_from_signal(signal_data, config_data, market_data)
        validator = ContractValidator(require_all_layers=False)
        is_valid, errors = validator.validate_contract(contract)
        
        assert is_valid, "Contract should be valid"
        assert contract.strategy_intent == StrategyIntent.BEARISH_EVENT
        assert contract.thesis_side == "no"
        assert contract.kalshi_side == "no"


class TestCrossLayerPriceRangeInvariant:
    """Test suite for cross-layer price range invariant."""
    
    def test_price_in_canonical_range(self):
        """Test that prices are in canonical 10-75c range."""
        valid_prices = [10, 25, 50, 75]
        invalid_prices = [5, 9, 76, 100]
        
        for price in valid_prices:
            signal_data = {
                "strategy_intent": StrategyIntent.BULLISH_EVENT,
                "thesis_side": "yes",
                "kalshi_side": "yes",
                "kalshi_action": "buy",
                "price_cents": price,
                "contracts": 1,
                "confidence": 0.8,
            }
            
            config_data = {"asset": "BTC", "market_id": "KXBTC15M-TEST"}
            market_data = {"spot_price": 50000.0}
            
            # Build contract without requiring all layers
            from merid.prediction.trade_contract import ContractBuilder, ContractValidator
            builder = ContractBuilder()
            contract = builder.build_from_signal(signal_data, config_data, market_data)
            validator = ContractValidator(require_all_layers=False)
            is_valid, errors = validator.validate_contract(contract)
            
            assert is_valid, f"Price {price}c should be valid: {errors}"
        
        for price in invalid_prices:
            signal_data = {
                "strategy_intent": StrategyIntent.BULLISH_EVENT,
                "thesis_side": "yes",
                "kalshi_side": "yes",
                "kalshi_action": "buy",
                "price_cents": price,
                "contracts": 1,
                "confidence": 0.8,
            }
            
            config_data = {"asset": "BTC", "market_id": "KXBTC15M-TEST"}
            market_data = {"spot_price": 50000.0}
            
            # Build contract without requiring all layers
            from merid.prediction.trade_contract import ContractBuilder, ContractValidator
            builder = ContractBuilder()
            contract = builder.build_from_signal(signal_data, config_data, market_data)
            validator = ContractValidator(require_all_layers=False)
            is_valid, errors = validator.validate_contract(contract)
            
            assert not is_valid, f"Price {price}c should be invalid"


class TestCrossLayerAssetCoverage:
    """Test suite for cross-layer asset coverage invariant."""
    
    def test_all_five_assets_supported(self):
        """Test that all 5 assets are supported across all layers."""
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        
        # TA intent mapper
        mapper = TAIntentMapper()
        for asset in assets:
            config = mapper.get_config(asset)
            assert config is not None, f"{asset} should have TA intent config"
        
        # Position exit manager
        manager = PositionExitManager()
        for asset in assets:
            state = manager.get_or_create_position_state(
                position_id=f"{asset}-TEST",
                market_id=f"KX{asset}15M-TEST",
                asset=asset,
                current_size=10,
                entry_price_cents=50.0,
                thesis_side="yes",
            )
            assert state.asset == asset
        
        # Trade contract
        for asset in assets:
            signal_data = {
                "strategy_intent": StrategyIntent.BULLISH_EVENT,
                "thesis_side": "yes",
                "kalshi_side": "yes",
                "kalshi_action": "buy",
                "price_cents": 50,
                "contracts": 1,
                "confidence": 0.8,
            }
            
            config_data = {"asset": asset, "market_id": f"KX{asset}15M-TEST"}
            market_data = {"spot_price": 50000.0}
            
            # Build contract without requiring all layers
            from merid.prediction.trade_contract import ContractBuilder, ContractValidator
            builder = ContractBuilder()
            contract = builder.build_from_signal(signal_data, config_data, market_data)
            validator = ContractValidator(require_all_layers=False)
            is_valid, errors = validator.validate_contract(contract)
            
            assert is_valid, f"{asset} contract should be valid: {errors}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
