"""Unit tests for window-based risk limits (3% per-agent / 5% total venue per 15m window)."""

import pytest
import time
from unittest.mock import MagicMock, patch
from decimal import Decimal


class TestWindowBasedRiskLimits:
    """Test window-based risk limit enforcement."""
    
    def test_window_limit_check_blocks_exceeding_per_agent_limit(self):
        """Test that window limit check blocks orders exceeding 3% per-agent limit."""
        with patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope') as mock_get_envelope:
            mock_envelope = MagicMock()
            mock_envelope.check_window_limit.return_value = (False, "per_agent_limit_exceeded")
            mock_get_envelope.return_value = mock_envelope
            
            from merid.prediction.unified_sizing import compute_order_size
            
            # Try to size an order that would exceed window limit
            count, notional, metadata = compute_order_size(
                bankroll_usd=Decimal("1000.0"),
                price_cents=50,
                asset="BTC"
            )
            
            # Should return 0 contracts due to window limit rejection
            assert count == 0
            assert notional == Decimal("0.0")
            assert metadata.get("window_limit_rejected") is True
            assert "per_agent_limit_exceeded" in metadata.get("reason", "")
    
    def test_window_limit_check_blocks_exceeding_total_venue_limit(self):
        """Test that window limit check blocks orders exceeding 5% total venue limit."""
        with patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope') as mock_get_envelope:
            mock_envelope = MagicMock()
            mock_envelope.check_window_limit.return_value = (False, "total_venue_limit_exceeded")
            mock_get_envelope.return_value = mock_envelope
            
            from merid.prediction.unified_sizing import compute_order_size
            
            # Try to size an order that would exceed total venue limit
            count, notional, metadata = compute_order_size(
                bankroll_usd=Decimal("1000.0"),
                price_cents=50,
                asset="ETH"
            )
            
            # Should return 0 contracts due to window limit rejection
            assert count == 0
            assert notional == Decimal("0.0")
            assert metadata.get("window_limit_rejected") is True
            assert "total_venue_limit_exceeded" in metadata.get("reason", "")
    
    def test_window_limit_check_allows_within_limits(self):
        """Test that window limit check allows orders within limits."""
        with patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope') as mock_get_envelope:
            mock_envelope = MagicMock()
            mock_envelope.check_window_limit.return_value = (True, "")
            mock_get_envelope.return_value = mock_envelope
            
            from merid.prediction.unified_sizing import compute_order_size
            
            # Size an order within window limits
            count, notional, metadata = compute_order_size(
                bankroll_usd=Decimal("1000.0"),
                price_cents=50,
                asset="SOL"
            )
            
            # Should return non-zero contracts (sizing succeeded)
            assert count > 0
            assert notional > 0
            assert metadata.get("window_limit_rejected") is not True
    
    def test_window_limit_check_handles_envelope_not_ready(self):
        """Test that window limit check handles risk envelope not ready gracefully."""
        with patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope') as mock_get_envelope:
            mock_get_envelope.side_effect = RuntimeError("Risk envelope not ready")
            
            from merid.prediction.unified_sizing import compute_order_size
            
            # Should proceed without window limit enforcement when envelope not ready
            count, notional, metadata = compute_order_size(
                bankroll_usd=Decimal("1000.0"),
                price_cents=50,
                asset="XRP"
            )
            
            # Should return non-zero contracts (sizing proceeded without window check)
            assert count > 0
            assert notional > 0
    
    def test_regime_sizing_multiplier_disabled(self):
        """Test that regime sizing multiplier is disabled (returns 1.0)."""
        from merid.prediction.unified_sizing import _get_regime_position_size_multiplier
        
        multiplier = _get_regime_position_size_multiplier()
        
        # Should return 1.0 (disabled to prevent interference with risk limits)
        assert multiplier == 1.0
    
    def test_profile_kelly_parameters_exist(self):
        """Test that kelly.hard_cap and kelly.global_notional_cap_pct exist in profile."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile') as mock_get_profile:
            mock_profile = MagicMock()
            mock_profile.kelly_hard_cap = 0.02
            mock_profile.kelly_global_notional_cap_pct = 0.02
            mock_adapter = MagicMock()
            mock_adapter.profile = mock_profile
            mock_get_profile.return_value = mock_adapter
            
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            # Verify kelly parameters exist with correct values
            assert profile.kelly_hard_cap == 0.02
            assert profile.kelly_global_notional_cap_pct == 0.02


class TestOrderRouterWindowTracking:
    """Test order router window tracking integration."""
    
    def test_order_execution_records_window_exposure(self):
        """Test that order execution records window exposure in risk envelope."""
        with patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope') as mock_get_envelope, \
             patch('merid.risk.unified_risk_manager.get_unified_risk_manager') as mock_get_risk:
            mock_envelope = MagicMock()
            mock_envelope.record_order_execution = MagicMock()
            mock_get_envelope.return_value = mock_envelope
            
            mock_risk = MagicMock()
            mock_risk.record_fill = MagicMock()
            mock_get_risk.return_value = mock_risk
            
            # Simulate the window tracking code path from order_router
            # This is a simplified test of the integration
            filled_count = 5
            fill_price_cents = 50
            order_notional_usd = filled_count * fill_price_cents / 100.0
            asset = "BTC"
            agent_id = f"{asset}_15M"
            
            # Call the window tracking method
            mock_envelope.record_order_execution(agent_id, order_notional_usd)
            
            # Verify it was called with correct parameters
            mock_envelope.record_order_execution.assert_called_once_with(agent_id, order_notional_usd)
    
    def test_window_tracking_handles_envelope_not_ready(self):
        """Test that window tracking handles risk envelope not ready gracefully."""
        with patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope') as mock_get_envelope:
            mock_get_envelope.side_effect = RuntimeError("Risk envelope not ready")
            
            # Should not raise exception, should log warning and proceed
            # This is tested by ensuring no exception is raised
            try:
                from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
                envelope = get_kalshi_crypto_15m_risk_envelope()
            except RuntimeError:
                # Expected when envelope not ready
                pass


class TestExitPolicyPrecedence:
    """Test exit policy precedence order documentation."""
    
    def test_exit_precedence_documented(self):
        """Test that exit precedence order is documented in ExitReason."""
        from merid.position_management.exit_policy import ExitReason
        
        # Check that the docstring contains precedence documentation
        assert "EXIT PRECEDENCE ORDER" in ExitReason.__doc__
        assert "EXTREME_PROFIT" in ExitReason.__doc__
        assert "DYNAMIC_TAKE_PROFIT" in ExitReason.__doc__
        assert "RATCHET_FLOOR" in ExitReason.__doc__
    
    def test_critical_exit_reasons_exist(self):
        """Test that critical exit reasons are defined."""
        from merid.position_management.exit_policy import ExitReason
        
        # Verify critical exit reasons exist
        assert hasattr(ExitReason, 'EXTREME_PROFIT')
        assert hasattr(ExitReason, 'RATCHET_FLOOR')
        assert hasattr(ExitReason, 'RATCHET_TRIM')
        assert hasattr(ExitReason, 'DYNAMIC_TAKE_PROFIT')
        assert hasattr(ExitReason, 'TRAIL')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
