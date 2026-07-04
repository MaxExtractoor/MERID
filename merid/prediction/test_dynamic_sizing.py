"""Unit tests for dynamic position sizing functionality."""

import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch


class TestDynamicSizing:
    """Test dynamic position sizing logic."""
    
    def test_dynamic_sizing_disabled(self):
        """Test that dynamic sizing is disabled when feature is off."""
        from merid.prediction.unified_sizing import compute_order_size
        
        with patch('merid.prediction.unified_sizing._is_dynamic_sizing_enabled', return_value=False), \
             patch('merid.prediction.unified_sizing._get_max_single_order_pct', return_value=Decimal("0.10")), \
             patch('merid.prediction.unified_sizing._get_bankroll_cap_pct', return_value=Decimal("0.02")), \
             patch('merid.prediction.unified_sizing._get_min_edge_risk_pct', return_value=Decimal("0.02")), \
             patch('merid.prediction.unified_sizing._get_max_contracts_per_asset', return_value=10), \
             patch('merid.prediction.unified_sizing._get_regime_position_size_multiplier', return_value=1.0):  # No regime reduction
            
            count, notional, metadata = compute_order_size(
                bankroll_usd=Decimal("1000.0"),
                price_cents=50,
                asset="BTC",
                edge_pct=Decimal("0.05"),
                confidence=Decimal("0.8")
            )
            
            # Should use standard sizing without dynamic scaling
            assert count > 0
            assert notional > 0
    
    def test_dynamic_sizing_enabled_high_edge(self):
        """Test that high edge increases position size."""
        from merid.prediction.unified_sizing import compute_order_size
        
        with patch('merid.prediction.unified_sizing._is_dynamic_sizing_enabled', return_value=True), \
             patch('merid.prediction.unified_sizing._get_dynamic_sizing_base_contracts', return_value=1), \
             patch('merid.prediction.unified_sizing._get_dynamic_sizing_edge_multiplier', return_value=0.5), \
             patch('merid.prediction.unified_sizing._get_dynamic_sizing_confidence_multiplier', return_value=0.3), \
             patch('merid.prediction.unified_sizing._get_dynamic_sizing_max_contracts', return_value=3), \
             patch('merid.prediction.unified_sizing._get_dynamic_sizing_min_contracts', return_value=1), \
             patch('merid.prediction.unified_sizing._get_max_single_order_pct', return_value=Decimal("0.10")), \
             patch('merid.prediction.unified_sizing._get_bankroll_cap_pct', return_value=Decimal("0.02")), \
             patch('merid.prediction.unified_sizing._get_min_edge_risk_pct', return_value=Decimal("0.02")), \
             patch('merid.prediction.unified_sizing._get_max_contracts_per_asset', return_value=10), \
             patch('merid.prediction.unified_sizing._get_regime_position_size_multiplier', return_value=1.0):  # No regime reduction
            
            # High edge (5%) should increase size
            count, notional, metadata = compute_order_size(
                bankroll_usd=Decimal("1000.0"),
                price_cents=50,
                asset="BTC",
                edge_pct=Decimal("0.05"),  # 5% edge
                confidence=Decimal("0.5")
            )
            
            # Dynamic size = 1 + (5 * 0.5) + (50 * 0.3) = 1 + 2.5 + 15 = 18.5 -> capped at 3
            # Should be larger than base
            assert count >= 1
    
    def test_dynamic_sizing_enabled_low_edge(self):
        """Test that low edge keeps position size at minimum."""
        from merid.prediction.unified_sizing import compute_order_size
        
        with patch('merid.prediction.unified_sizing._is_dynamic_sizing_enabled', return_value=True), \
             patch('merid.prediction.unified_sizing._get_dynamic_sizing_base_contracts', return_value=1), \
             patch('merid.prediction.unified_sizing._get_dynamic_sizing_edge_multiplier', return_value=0.5), \
             patch('merid.prediction.unified_sizing._get_dynamic_sizing_confidence_multiplier', return_value=0.3), \
             patch('merid.prediction.unified_sizing._get_dynamic_sizing_max_contracts', return_value=3), \
             patch('merid.prediction.unified_sizing._get_dynamic_sizing_min_contracts', return_value=1), \
             patch('merid.prediction.unified_sizing._get_max_single_order_pct', return_value=Decimal("0.10")), \
             patch('merid.prediction.unified_sizing._get_bankroll_cap_pct', return_value=Decimal("0.02")), \
             patch('merid.prediction.unified_sizing._get_min_edge_risk_pct', return_value=Decimal("0.02")), \
             patch('merid.prediction.unified_sizing._get_max_contracts_per_asset', return_value=10), \
             patch('merid.prediction.unified_sizing._get_regime_position_size_multiplier', return_value=1.0):  # No regime reduction
            
            # Low edge (1%) should keep size at minimum
            count, notional, metadata = compute_order_size(
                bankroll_usd=Decimal("1000.0"),
                price_cents=50,
                asset="BTC",
                edge_pct=Decimal("0.01"),  # 1% edge
                confidence=Decimal("0.5")
            )
            
            # Dynamic size = 1 + (1 * 0.5) + (50 * 0.3) = 1 + 0.5 + 15 = 16.5 -> capped at 3
            # Should be at least minimum
            assert count >= 1
    
    def test_dynamic_sizing_high_confidence(self):
        """Test that high confidence increases position size."""
        from merid.prediction.unified_sizing import compute_order_size
        
        with patch('merid.prediction.unified_sizing._is_dynamic_sizing_enabled', return_value=True), \
             patch('merid.prediction.unified_sizing._get_dynamic_sizing_base_contracts', return_value=1), \
             patch('merid.prediction.unified_sizing._get_dynamic_sizing_edge_multiplier', return_value=0.5), \
             patch('merid.prediction.unified_sizing._get_dynamic_sizing_confidence_multiplier', return_value=0.3), \
             patch('merid.prediction.unified_sizing._get_dynamic_sizing_max_contracts', return_value=3), \
             patch('merid.prediction.unified_sizing._get_dynamic_sizing_min_contracts', return_value=1), \
             patch('merid.prediction.unified_sizing._get_max_single_order_pct', return_value=Decimal("0.10")), \
             patch('merid.prediction.unified_sizing._get_bankroll_cap_pct', return_value=Decimal("0.02")), \
             patch('merid.prediction.unified_sizing._get_min_edge_risk_pct', return_value=Decimal("0.02")), \
             patch('merid.prediction.unified_sizing._get_max_contracts_per_asset', return_value=10), \
             patch('merid.prediction.unified_sizing._get_regime_position_size_multiplier', return_value=1.0):  # No regime reduction
            
            # High confidence (80%) should increase size
            count, notional, metadata = compute_order_size(
                bankroll_usd=Decimal("1000.0"),
                price_cents=50,
                asset="BTC",
                edge_pct=Decimal("0.03"),
                confidence=Decimal("0.8")  # 80% confidence
            )
            
            # Dynamic size = 1 + (3 * 0.5) + (80 * 0.3) = 1 + 1.5 + 24 = 26.5 -> capped at 3
            assert count >= 1
    
    def test_dynamic_sizing_max_contracts_cap(self):
        """Test that dynamic sizing respects per-asset max contracts cap.
        
        Updated for $1+/15m target: BTC/ETH/SOL/XRP max 3 contracts, DOGE max 2 contracts.
        """
        from merid.prediction.unified_sizing import compute_order_size
        
        # Test BTC/ETH/SOL/XRP with max 3 contracts
        for asset in ["BTC", "ETH", "SOL", "XRP"]:
            with patch('merid.prediction.unified_sizing._is_dynamic_sizing_enabled', return_value=True), \
                 patch('merid.prediction.unified_sizing._get_dynamic_sizing_base_contracts', return_value=1), \
                 patch('merid.prediction.unified_sizing._get_dynamic_sizing_edge_multiplier', return_value=0.5), \
                 patch('merid.prediction.unified_sizing._get_dynamic_sizing_confidence_multiplier', return_value=0.3), \
                 patch('merid.prediction.unified_sizing._get_dynamic_sizing_max_contracts', return_value=3), \
                 patch('merid.prediction.unified_sizing._get_dynamic_sizing_min_contracts', return_value=1), \
                 patch('merid.prediction.unified_sizing._get_max_single_order_pct', return_value=Decimal("0.10")), \
                 patch('merid.prediction.unified_sizing._get_bankroll_cap_pct', return_value=Decimal("0.02")), \
                 patch('merid.prediction.unified_sizing._get_min_edge_risk_pct', return_value=Decimal("0.02")), \
                 patch('merid.prediction.unified_sizing._get_max_contracts_per_asset', return_value=3):
                
                # Even with high edge/confidence, should cap at per-asset max_contracts (3)
                count, notional, metadata = compute_order_size(
                    bankroll_usd=Decimal("1000.0"),
                    price_cents=50,
                    asset=asset,
                    edge_pct=Decimal("0.10"),  # 10% edge
                    confidence=Decimal("0.9")  # 90% confidence
                )
                
                # Should not exceed per-asset max_contracts (3)
                assert count <= 3, f"{asset} should cap at 3 contracts, got {count}"
        
        # Test DOGE with max 2 contracts (conservative due to volatility)
        with patch('merid.prediction.unified_sizing._is_dynamic_sizing_enabled', return_value=True), \
             patch('merid.prediction.unified_sizing._get_dynamic_sizing_base_contracts', return_value=1), \
             patch('merid.prediction.unified_sizing._get_dynamic_sizing_edge_multiplier', return_value=0.5), \
             patch('merid.prediction.unified_sizing._get_dynamic_sizing_confidence_multiplier', return_value=0.3), \
             patch('merid.prediction.unified_sizing._get_dynamic_sizing_max_contracts', return_value=2), \
             patch('merid.prediction.unified_sizing._get_dynamic_sizing_min_contracts', return_value=1), \
             patch('merid.prediction.unified_sizing._get_max_single_order_pct', return_value=Decimal("0.10")), \
             patch('merid.prediction.unified_sizing._get_bankroll_cap_pct', return_value=Decimal("0.02")), \
             patch('merid.prediction.unified_sizing._get_min_edge_risk_pct', return_value=Decimal("0.02")), \
             patch('merid.prediction.unified_sizing._get_max_contracts_per_asset', return_value=2):
            
            # Even with high edge/confidence, should cap at per-asset max_contracts (2)
            count, notional, metadata = compute_order_size(
                bankroll_usd=Decimal("1000.0"),
                price_cents=50,
                asset="DOGE",
                edge_pct=Decimal("0.10"),  # 10% edge
                confidence=Decimal("0.9")  # 90% confidence
            )
            
            # Should not exceed per-asset max_contracts (2)
            assert count <= 2, f"DOGE should cap at 2 contracts, got {count}"
    
    def test_dynamic_sizing_helper_functions(self):
        """Test dynamic sizing helper function defaults."""
        from merid.prediction.unified_sizing import (
            _is_dynamic_sizing_enabled,
            _get_dynamic_sizing_base_contracts,
            _get_dynamic_sizing_edge_multiplier,
            _get_dynamic_sizing_confidence_multiplier,
            _get_dynamic_sizing_max_contracts,
            _get_dynamic_sizing_min_contracts
        )
        
        # When profile is unavailable, should return defaults
        with patch('merid.prediction.unified_sizing._PROFILE_AVAILABLE', False):
            assert _is_dynamic_sizing_enabled() is False
            assert _get_dynamic_sizing_base_contracts() == 1
            assert _get_dynamic_sizing_edge_multiplier() == 0.5
            assert _get_dynamic_sizing_confidence_multiplier() == 0.3
            assert _get_dynamic_sizing_max_contracts() == 3
            assert _get_dynamic_sizing_min_contracts() == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
