"""
Unified Trade Contract Abstraction Test Harness

Tests that the Trade Contract abstraction ensures consistency across
configuration, data, signals, intent, candidate, order, execution, ledger, and exit layers.

Usage:
    pytest tests/test_trade_contract.py
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

try:
    from merid.prediction.trade_contract import (
        TradeContract,
        ContractLayer,
        LayerData,
        ContractValidator,
        ContractBuilder,
        build_trade_contract_from_signal,
    )
    from merid.prediction.signal_terminology import StrategyIntent
except ImportError:
    pytest.skip("Required modules not available")


class TestTradeContract:
    """Test suite for Trade Contract."""
    
    def test_create_contract(self):
        """Test creating a basic trade contract."""
        contract = TradeContract(
            contract_id="TEST-001",
            asset="BTC",
            market_id="KXBTC15M-TEST",
            strategy_intent=StrategyIntent.BULLISH_EVENT,
            thesis_side="yes",
            kalshi_side="yes",
            kalshi_action="buy",
            price_cents=50,
            contracts=1,
        )
        
        assert contract.contract_id == "TEST-001"
        assert contract.asset == "BTC"
        assert contract.strategy_intent == StrategyIntent.BULLISH_EVENT
        assert contract.thesis_side == "yes"
    
    def test_add_layer_data(self):
        """Test adding layer data to contract."""
        contract = TradeContract(
            contract_id="TEST-001",
            asset="BTC",
            market_id="KXBTC15M-TEST",
            strategy_intent=StrategyIntent.BULLISH_EVENT,
            thesis_side="yes",
            kalshi_side="yes",
            kalshi_action="buy",
            price_cents=50,
            contracts=1,
        )
        
        config_data = {"asset": "BTC", "market_id": "KXBTC15M-TEST"}
        contract.add_layer_data(ContractLayer.CONFIG, config_data)
        
        layer_data = contract.get_layer_data(ContractLayer.CONFIG)
        assert layer_data is not None
        assert layer_data.data == config_data
    
    def test_validate_layer_missing_data(self):
        """Test that missing layer data fails validation."""
        contract = TradeContract(
            contract_id="TEST-001",
            asset="BTC",
            market_id="KXBTC15M-TEST",
            strategy_intent=StrategyIntent.BULLISH_EVENT,
            thesis_side="yes",
            kalshi_side="yes",
            kalshi_action="buy",
            price_cents=50,
            contracts=1,
        )
        
        # Add incomplete CONFIG data
        contract.add_layer_data(ContractLayer.CONFIG, {"asset": "BTC"})  # Missing market_id
        
        is_valid, errors = contract.validate_layer(ContractLayer.CONFIG)
        assert not is_valid
        assert "missing 'market_id'" in " ".join(errors)
    
    def test_validate_invalid_thesis_side(self):
        """Test that invalid thesis_side fails validation."""
        contract = TradeContract(
            contract_id="TEST-001",
            asset="BTC",
            market_id="KXBTC15M-TEST",
            strategy_intent=StrategyIntent.BULLISH_EVENT,
            thesis_side="yes",
            kalshi_side="yes",
            kalshi_action="buy",
            price_cents=50,
            contracts=1,
        )
        
        # Add INTENT data with invalid thesis_side
        contract.add_layer_data(ContractLayer.INTENT, {"thesis_side": "invalid"})
        
        is_valid, errors = contract.validate_layer(ContractLayer.INTENT)
        assert not is_valid
        assert "invalid thesis_side" in " ".join(errors)
    
    def test_cross_layer_intent_thesis_consistency(self):
        """Test cross-layer intent → thesis_side consistency."""
        contract = TradeContract(
            contract_id="TEST-001",
            asset="BTC",
            market_id="KXBTC15M-TEST",
            strategy_intent=StrategyIntent.BULLISH_EVENT,
            thesis_side="yes",
            kalshi_side="yes",
            kalshi_action="buy",
            price_cents=50,
            contracts=1,
        )
        
        # Add SIGNAL data with BULLISH_EVENT
        contract.add_layer_data(ContractLayer.SIGNAL, {"strategy_intent": StrategyIntent.BULLISH_EVENT})
        
        # Add INTENT data with thesis_side=no (inconsistent!)
        contract.add_layer_data(ContractLayer.INTENT, {"thesis_side": "no"})
        
        is_valid, errors = contract.validate_cross_layer_consistency()
        assert not is_valid
        assert "BULLISH_EVENT requires thesis_side=yes" in " ".join(errors)
    
    def test_cross_layer_price_range_validation(self):
        """Test that price out of canonical range fails validation."""
        contract = TradeContract(
            contract_id="TEST-001",
            asset="BTC",
            market_id="KXBTC15M-TEST",
            strategy_intent=StrategyIntent.BULLISH_EVENT,
            thesis_side="yes",
            kalshi_side="yes",
            kalshi_action="buy",
            price_cents=50,
            contracts=1,
        )
        
        # Add ORDER data with price out of range
        contract.add_layer_data(ContractLayer.ORDER, {"price_cents": 100})  # Above 75c
        
        is_valid, errors = contract.validate_cross_layer_consistency()
        assert not is_valid
        assert "out of canonical range" in " ".join(errors)


class TestContractValidator:
    """Test suite for Contract Validator."""
    
    def test_validate_complete_contract(self):
        """Test validating a complete contract."""
        contract = TradeContract(
            contract_id="TEST-001",
            asset="BTC",
            market_id="KXBTC15M-TEST",
            strategy_intent=StrategyIntent.BULLISH_EVENT,
            thesis_side="yes",
            kalshi_side="yes",
            kalshi_action="buy",
            price_cents=50,
            contracts=1,
        )
        
        # Add all required layers
        contract.add_layer_data(ContractLayer.CONFIG, {"asset": "BTC", "market_id": "KXBTC15M-TEST"})
        contract.add_layer_data(ContractLayer.SIGNAL, {"strategy_intent": StrategyIntent.BULLISH_EVENT, "confidence": 0.8})
        contract.add_layer_data(ContractLayer.INTENT, {"thesis_side": "yes"})
        contract.add_layer_data(ContractLayer.ORDER, {"kalshi_side": "yes", "kalshi_action": "buy", "price_cents": 50})
        
        validator = ContractValidator(require_all_layers=False)
        is_valid, errors = validator.validate_contract(contract)
        assert is_valid
        assert len(errors) == 0
    
    def test_validate_missing_required_layer(self):
        """Test that missing required layer fails validation."""
        contract = TradeContract(
            contract_id="TEST-001",
            asset="BTC",
            market_id="KXBTC15M-TEST",
            strategy_intent=StrategyIntent.BULLISH_EVENT,
            thesis_side="yes",
            kalshi_side="yes",
            kalshi_action="buy",
            price_cents=50,
            contracts=1,
        )
        
        # Add only CONFIG layer (missing SIGNAL, INTENT, ORDER)
        contract.add_layer_data(ContractLayer.CONFIG, {"asset": "BTC", "market_id": "KXBTC15M-TEST"})
        
        validator = ContractValidator(require_all_layers=True)
        is_valid, errors = validator.validate_contract(contract)
        assert not is_valid
        assert any("missing" in error.lower() for error in errors)


class TestContractBuilder:
    """Test suite for Contract Builder."""
    
    def test_build_from_signal(self):
        """Test building contract from signal data."""
        builder = ContractBuilder()
        
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
            "asset": "BTC",
            "market_id": "KXBTC15M-TEST",
        }
        
        market_data = {
            "spot_price": 50000.0,
            "yes_price": 50,
            "no_price": 50,
        }
        
        contract = builder.build_from_signal(signal_data, config_data, market_data)
        
        assert contract.asset == "BTC"
        assert contract.strategy_intent == StrategyIntent.BULLISH_EVENT
        assert contract.thesis_side == "yes"
        assert contract.price_cents == 50
        
        # Check layers were added
        assert contract.get_layer_data(ContractLayer.CONFIG) is not None
        assert contract.get_layer_data(ContractLayer.DATA) is not None
        assert contract.get_layer_data(ContractLayer.SIGNAL) is not None
        assert contract.get_layer_data(ContractLayer.INTENT) is not None
        assert contract.get_layer_data(ContractLayer.ORDER) is not None


class TestBuildTradeContractFromSignal:
    """Test suite for build_trade_contract_from_signal function."""
    
    def test_build_and_validate(self):
        """Test building and validating contract in one step."""
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
            "asset": "BTC",
            "market_id": "KXBTC15M-TEST",
        }
        
        market_data = {
            "spot_price": 50000.0,
        }
        
        # Build contract manually with custom validator
        from merid.prediction.trade_contract import ContractBuilder, ContractValidator
        builder = ContractBuilder()
        contract = builder.build_from_signal(signal_data, config_data, market_data)
        validator = ContractValidator(require_all_layers=False)
        is_valid, errors = validator.validate_contract(contract)
        
        assert contract is not None
        assert is_valid
        assert len(errors) == 0
    
    def test_build_with_invalid_price(self):
        """Test that invalid price fails validation."""
        signal_data = {
            "strategy_intent": StrategyIntent.BULLISH_EVENT,
            "thesis_side": "yes",
            "kalshi_side": "yes",
            "kalshi_action": "buy",
            "price_cents": 100,  # Out of range
            "contracts": 1,
            "confidence": 0.8,
        }
        
        config_data = {
            "asset": "BTC",
            "market_id": "KXBTC15M-TEST",
        }
        
        market_data = {
            "spot_price": 50000.0,
        }
        
        contract, (is_valid, errors) = build_trade_contract_from_signal(signal_data, config_data, market_data)
        
        assert contract is not None
        assert not is_valid
        assert len(errors) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
