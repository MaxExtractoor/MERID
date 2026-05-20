"""Unit tests for config-based max_notional computation."""

import pytest
from unittest.mock import MagicMock, patch
from merid.guardrails.capabilities import _compute_kalshi_max_notional_from_config


class TestConfigBasedMaxNotional:
    """Test the config-based max_notional computation function."""

    def test_max_notional_from_config_success(self):
        """Test that max_notional is computed as per_trade_cap × max_concurrent."""
        with patch('merid.event_venues.kalshi.kalshi_risk.KalshiRiskConfig') as mock_config_class:
            mock_config = MagicMock()
            mock_config.max_single_order_notional_usd = 2500.0
            mock_config_class.return_value = mock_config
            
            max_notional = _compute_kalshi_max_notional_from_config()
            
            # Should be 2500.0 * 3 = 7500.0
            assert max_notional == 7500.0

    def test_max_notional_uses_config_default(self):
        """Test that default KalshiRiskConfig value is used."""
        with patch('merid.event_venues.kalshi.kalshi_risk.KalshiRiskConfig') as mock_config_class:
            mock_config = MagicMock()
            mock_config.max_single_order_notional_usd = 2500.0  # Default from kalshi_risk.py
            mock_config_class.return_value = mock_config
            
            max_notional = _compute_kalshi_max_notional_from_config()
            
            # Should be 2500.0 * 3 = 7500.0 (default config)
            assert max_notional == 7500.0

    def test_max_notional_different_per_trade_caps(self):
        """Test max_notional with different per-trade caps."""
        test_cases = [
            (500.0, 1500.0),   # $500 per trade × 3 = $1500
            (1000.0, 3000.0), # $1000 per trade × 3 = $3000
            (2500.0, 7500.0), # $2500 per trade × 3 = $7500 (default)
            (5000.0, 15000.0), # $5000 per trade × 3 = $15000
            (10000.0, 30000.0), # $10000 per trade × 3 = $30000
        ]
        
        for per_trade_cap, expected in test_cases:
            with patch('merid.event_venues.kalshi.kalshi_risk.KalshiRiskConfig') as mock_config_class:
                mock_config = MagicMock()
                mock_config.max_single_order_notional_usd = per_trade_cap
                mock_config_class.return_value = mock_config
                
                max_notional = _compute_kalshi_max_notional_from_config()
                assert max_notional == expected, f"Per-trade ${per_trade_cap}: expected ${expected}, got ${max_notional}"

    def test_max_notional_fail_safe_on_config_error(self):
        """Test that config error returns conservative $500 cap."""
        with patch('merid.event_venues.kalshi.kalshi_risk.KalshiRiskConfig') as mock_config_class:
            mock_config_class.side_effect = Exception("Config error")
            
            max_notional = _compute_kalshi_max_notional_from_config()
            
            # Should return fail-safe $500 cap
            assert max_notional == 500.0

    def test_max_notional_balance_guardrail_warning(self):
        """Test that balance guardrail logs warning when config cap exceeds cash."""
        with patch('merid.event_venues.kalshi.kalshi_risk.KalshiRiskConfig') as mock_config_class:
            mock_config = MagicMock()
            mock_config.max_single_order_notional_usd = 2500.0
            mock_config_class.return_value = mock_config
            
            # Mock balance fetch to return $1000 (less than config cap of $7500)
            mock_result = MagicMock()
            mock_result.success = True
            with patch('merid.event_venues.kalshi.bankroll_service.get_effective_bankroll_for_trading_sync') as mock_fetch:
                mock_fetch.return_value = (1000.0, mock_result)
                
                max_notional = _compute_kalshi_max_notional_from_config()
                
                # Should still return config cap ($7500), not balance-limited
                assert max_notional == 7500.0

    def test_max_notional_balance_guardrail_info(self):
        """Test that balance guardrail logs info when config cap is within cash."""
        with patch('merid.event_venues.kalshi.kalshi_risk.KalshiRiskConfig') as mock_config_class:
            mock_config = MagicMock()
            mock_config.max_single_order_notional_usd = 2500.0
            mock_config_class.return_value = mock_config
            
            # Mock balance fetch to return $10000 (more than config cap of $7500)
            mock_result = MagicMock()
            mock_result.success = True
            with patch('merid.event_venues.kalshi.bankroll_service.get_effective_bankroll_for_trading_sync') as mock_fetch:
                mock_fetch.return_value = (10000.0, mock_result)
                
                max_notional = _compute_kalshi_max_notional_from_config()
                
                # Should return config cap ($7500)
                assert max_notional == 7500.0

    def test_max_notional_balance_guardrail_optional(self):
        """Test that balance guardrail failure doesn't affect the cap."""
        with patch('merid.event_venues.kalshi.kalshi_risk.KalshiRiskConfig') as mock_config_class:
            mock_config = MagicMock()
            mock_config.max_single_order_notional_usd = 2500.0
            mock_config_class.return_value = mock_config
            
            # Mock balance fetch to fail
            with patch('merid.event_venues.kalshi.bankroll_service.get_effective_bankroll_for_trading_sync') as mock_fetch:
                mock_fetch.side_effect = Exception("Balance fetch error")
                
                max_notional = _compute_kalshi_max_notional_from_config()
                
                # Should still return config cap ($7500) despite balance check failure
                assert max_notional == 7500.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
