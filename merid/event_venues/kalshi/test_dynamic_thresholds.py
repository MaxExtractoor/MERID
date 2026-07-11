"""
Unit tests for dynamic threshold manager module.

Tests dynamic threshold calculation, regime-based adjustment, and profile integration.
"""

import pytest
import numpy as np
from unittest.mock import Mock, patch
from merid.event_venues.kalshi.dynamic_thresholds import (
    DynamicThresholdManager,
    DynamicThresholds,
    reset_dynamic_threshold_manager
)
from merid.event_venues.kalshi.regime_detector import (
    Regime,
    reset_regime_detector
)


class TestDynamicThresholdManager:
    """Test suite for DynamicThresholdManager."""
    
    def setup_method(self):
        """Reset singletons before each test."""
        reset_regime_detector()
        reset_dynamic_threshold_manager()
        self.manager = DynamicThresholdManager()
    
    def test_initialization(self):
        """Test manager initialization."""
        assert self.manager is not None
        assert self.manager.regime_detector is not None
    
    def test_get_current_thresholds_initial(self):
        """Test getting initial thresholds (canonical defaults)."""
        thresholds = self.manager.get_current_thresholds()
        
        assert thresholds.min_price_cents == 10
        assert thresholds.max_price_cents == 50
        assert thresholds.max_spread_cents == 30
        assert thresholds.min_spread_gate_cents == 30
        assert thresholds.regime == "MEAN_REVERSION"
    
    def test_get_price_range(self):
        """Test getting price range."""
        min_price, max_price = self.manager.get_price_range()
        
        assert min_price == 10
        assert max_price == 50
    
    def test_get_max_spread_cents(self):
        """Test getting max spread threshold."""
        max_spread = self.manager.get_max_spread_cents()
        
        assert max_spread == 30
    
    def test_get_min_spread_gate_cents(self):
        """Test getting min spread gate threshold."""
        min_gate = self.manager.get_min_spread_gate_cents()
        
        assert min_gate == 30
    
    def test_get_liquidity_thresholds(self):
        """Test getting liquidity thresholds."""
        min_volume, min_depth = self.manager.get_liquidity_thresholds()
        
        assert min_volume == 500
        assert min_depth == 100
    
    def test_get_regime(self):
        """Test getting current regime."""
        regime = self.manager.get_regime()
        
        assert regime == "MEAN_REVERSION"
    
    def test_get_position_size_multiplier(self):
        """Test getting position size multiplier."""
        multiplier = self.manager.get_position_size_multiplier()
        
        assert multiplier == 1.0
    
    def test_update_with_normal_regime(self):
        """Test threshold update with normal regime."""
        # Mock normal regime detection
        with patch.object(self.manager.regime_detector, 'update') as mock_update:
            mock_update.return_value = Mock(
                current=Regime.MEAN_REVERSION,
                atr_pct=1.5,
                correlation_score=0.5,
                order_flow_imbalance=0.3,
                confidence=0.8,
                periods_in_regime=5
            )
            
            with patch.object(self.manager.regime_detector, 'get_adjustment_factor') as mock_factors:
                mock_factors.return_value = {
                    "price_range_multiplier": 1.0,
                    "spread_multiplier": 1.0,
                    "position_size_multiplier": 1.0
                }
                
                thresholds = self.manager.update(
                    {"BTC": np.ones(15)},
                    {"BTC": np.ones(15)},
                    {"BTC": {"bid_depth": 100, "ask_depth": 100}}
                )
                
                assert thresholds.min_price_cents == 10
                assert thresholds.max_price_cents == 50
                assert thresholds.max_spread_cents == 30
                assert thresholds.regime == "MEAN_REVERSION"
    
    def test_update_with_crisis_regime(self):
        """Test threshold update with crisis regime."""
        # Mock crisis regime detection
        with patch.object(self.manager.regime_detector, 'update') as mock_update:
            mock_update.return_value = Mock(
                current=Regime.CRISIS,
                atr_pct=5.0,
                correlation_score=0.9,
                order_flow_imbalance=0.8,
                confidence=0.9,
                periods_in_regime=3
            )
            
            with patch.object(self.manager.regime_detector, 'get_adjustment_factor') as mock_factors:
                mock_factors.return_value = {
                    "price_range_multiplier": 1.9,
                    "spread_multiplier": 3.3,
                    "position_size_multiplier": 0.5
                }
                
                thresholds = self.manager.update(
                    {"BTC": np.ones(15)},
                    {"BTC": np.ones(15)},
                    {"BTC": {"bid_depth": 100, "ask_depth": 100}}
                )
                
                # Crisis regime: uses crisis config directly with multipliers applied
                # Crisis config: 5-95c, 100c spread
                # Multipliers: 1.9x price range, 3.3x spread
                # Implementation applies multipliers to crisis config values
                assert thresholds.min_price_cents == 9  # 5 * 1.9
                assert thresholds.max_price_cents == 180  # 95 * 1.9
                assert thresholds.max_spread_cents == 330  # 100 * 3.3
                assert thresholds.regime == "CRISIS"
    
    def test_fallback_canonical_config(self):
        """Test fallback canonical configuration when profile not available."""
        fallback = self.manager._get_fallback_canonical()
        
        assert fallback["price_range"]["min_cents"] == 10
        assert fallback["price_range"]["max_cents"] == 50
        assert fallback["spread"]["max_cents"] == 30
        assert fallback["spread"]["min_gate_cents"] == 30
        assert fallback["liquidity"]["min_volume_24h"] == 500
        assert fallback["liquidity"]["min_depth_top_of_book"] == 100
    
    def test_fallback_crisis_config(self):
        """Test fallback crisis configuration when profile not available."""
        fallback = self.manager._get_fallback_crisis()
        
        assert fallback["price_range"]["min_cents"] == 5
        assert fallback["price_range"]["max_cents"] == 95
        assert fallback["spread"]["max_cents"] == 100
        assert fallback["spread"]["min_gate_cents"] == 30
        assert fallback["liquidity"]["min_volume_24h"] == 500
        assert fallback["liquidity"]["min_depth_top_of_book"] == 100
    
    def test_thresholds_to_dict(self):
        """Test converting thresholds to dictionary."""
        thresholds = self.manager.get_current_thresholds()
        threshold_dict = thresholds.to_dict()
        
        assert "min_price_cents" in threshold_dict
        assert "max_price_cents" in threshold_dict
        assert "max_spread_cents" in threshold_dict
        assert "min_spread_gate_cents" in threshold_dict
        assert "min_volume" in threshold_dict
        assert "min_depth" in threshold_dict
        assert "regime" in threshold_dict
        assert "adjustment_factors" in threshold_dict


class TestDynamicThresholds:
    """Test suite for DynamicThresholds dataclass."""
    
    def test_dynamic_thresholds_creation(self):
        """Test creating DynamicThresholds instance."""
        thresholds = DynamicThresholds(
            min_price_cents=10,
            max_price_cents=50,
            max_spread_cents=30,
            min_spread_gate_cents=30,
            min_volume=500,
            min_depth=100,
            regime="MEAN_REVERSION",
            adjustment_factors={
                "price_range_multiplier": 1.0,
                "spread_multiplier": 1.0,
                "position_size_multiplier": 1.0
            }
        )
        
        assert thresholds.min_price_cents == 10
        assert thresholds.max_price_cents == 50
        assert thresholds.max_spread_cents == 30
        assert thresholds.regime == "MEAN_REVERSION"
    
    def test_dynamic_thresholds_to_dict(self):
        """Test converting DynamicThresholds to dictionary."""
        thresholds = DynamicThresholds(
            min_price_cents=10,
            max_price_cents=50,
            max_spread_cents=30,
            min_spread_gate_cents=30,
            min_volume=500,
            min_depth=100,
            regime="MEAN_REVERSION",
            adjustment_factors={
                "price_range_multiplier": 1.0,
                "spread_multiplier": 1.0,
                "position_size_multiplier": 1.0
            }
        )
        
        threshold_dict = thresholds.to_dict()
        
        assert threshold_dict["min_price_cents"] == 10
        assert threshold_dict["max_price_cents"] == 50
        assert threshold_dict["max_spread_cents"] == 30
        assert threshold_dict["regime"] == "MEAN_REVERSION"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
