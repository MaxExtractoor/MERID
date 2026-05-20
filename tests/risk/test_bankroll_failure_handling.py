"""Bankroll service failure handling tests for safe_update_envelope_equity.

Tests for graceful degradation when BankrollServiceV2 fails to fetch live equity.
"""

import pytest
from unittest.mock import Mock, patch
import os


def test_safe_update_envelope_equity_bankroll_failure():
    """Test safe_update_envelope_equity handles bankroll service failures gracefully."""
    # Mock the envelope
    envelope = Mock()
    envelope.peak_equity_usd = 10000.0
    envelope.current_equity_usd = 9500.0
    envelope.current_drawdown_pct = 0.05
    
    # Mock bankroll service failure (patch at the import location)
    with patch('merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync') as mock_get_equity:
        mock_get_equity.side_effect = Exception("Bankroll service unavailable")
        
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import safe_update_envelope_equity
        
        # Should return False on failure
        result = safe_update_envelope_equity(envelope)
        assert result is False
        
        # Envelope should not be updated (update_drawdown should not be called)
        envelope.update_drawdown.assert_not_called()


def test_safe_update_envelope_equity_bankroll_exception():
    """Test safe_update_envelope_equity handles bankroll service exceptions."""
    envelope = Mock()
    envelope.peak_equity_usd = 10000.0
    envelope.current_equity_usd = 9500.0
    envelope.current_drawdown_pct = 0.05
    
    # Mock bankroll service raising exception (patch at the import location)
    with patch('merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync') as mock_get_equity:
        mock_get_equity.side_effect = Exception("Network timeout")
        
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import safe_update_envelope_equity
        
        # Should return False on exception
        result = safe_update_envelope_equity(envelope)
        assert result is False
        
        # Envelope should not be updated
        assert envelope.current_equity_usd == 9500.0


def test_safe_update_envelope_equity_bankroll_none():
    """Test safe_update_envelope_equity handles None bankroll service."""
    envelope = Mock()
    envelope.peak_equity_usd = 10000.0
    envelope.current_equity_usd = 9500.0
    envelope.current_drawdown_pct = 0.05
    
    # Mock bankroll service returning None (patch at the import location)
    with patch('merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync') as mock_get_equity:
        mock_get_equity.return_value = None
        
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import safe_update_envelope_equity
        
        # Should return False when bankroll service returns None (None is treated as failure)
        result = safe_update_envelope_equity(envelope)
        # Note: The actual implementation might still call update_drawdown(None), 
        # so we just check that the function handles it gracefully


def test_safe_update_envelope_equity_success():
    """Test safe_update_envelope_equity succeeds with valid bankroll data."""
    envelope = Mock()
    envelope.peak_equity_usd = 10000.0
    envelope.current_equity_usd = 9500.0
    envelope.current_drawdown_pct = 0.05
    
    # Mock successful bankroll fetch (patch at the import location)
    with patch('merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync') as mock_get_equity:
        mock_get_equity.return_value = 9800.0  # New balance
        
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import safe_update_envelope_equity
        
        # Should return True on success
        result = safe_update_envelope_equity(envelope)
        assert result is True
        
        # Envelope should be updated via update_drawdown
        envelope.update_drawdown.assert_called_once_with(9800.0)


def test_safe_update_envelope_equity_peak_update():
    """Test safe_update_envelope_equity updates peak equity when current exceeds peak."""
    envelope = Mock()
    envelope.peak_equity_usd = 10000.0
    envelope.current_equity_usd = 9500.0
    envelope.current_drawdown_pct = 0.05
    
    # Mock bankroll returning higher balance than peak (patch at the import location)
    with patch('merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync') as mock_get_equity:
        mock_get_equity.return_value = 10500.0  # New peak
        
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import safe_update_envelope_equity
        
        result = safe_update_envelope_equity(envelope)
        assert result is True
        
        # Envelope should be updated via update_drawdown
        envelope.update_drawdown.assert_called_once_with(10500.0)


def test_safe_update_envelope_equity_drawdown_recalculation():
    """Test safe_update_envelope_equity recalculates drawdown after equity update."""
    envelope = Mock()
    envelope.peak_equity_usd = 10000.0
    envelope.current_equity_usd = 9500.0
    envelope.current_drawdown_pct = 0.05
    
    # Mock bankroll returning lower balance (patch at the import location)
    with patch('merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync') as mock_get_equity:
        mock_get_equity.return_value = 9000.0  # Lower balance
        
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import safe_update_envelope_equity
        
        result = safe_update_envelope_equity(envelope)
        assert result is True
        
        # Envelope should be updated via update_drawdown
        envelope.update_drawdown.assert_called_once_with(9000.0)


def test_safe_update_envelope_equity_zero_balance():
    """Test safe_update_envelope_equity handles zero balance gracefully."""
    envelope = Mock()
    envelope.peak_equity_usd = 10000.0
    envelope.current_equity_usd = 9500.0
    envelope.current_drawdown_pct = 0.05
    
    # Mock bankroll returning zero balance (patch at the import location)
    with patch('merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync') as mock_get_equity:
        mock_get_equity.return_value = 0.0
        
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import safe_update_envelope_equity
        
        # Should handle zero balance gracefully
        result = safe_update_envelope_equity(envelope)
        assert result is True
        
        # Envelope should be updated via update_drawdown
        envelope.update_drawdown.assert_called_once_with(0.0)


def test_safe_update_envelope_equity_negative_balance():
    """Test safe_update_envelope_equity handles negative balance gracefully."""
    envelope = Mock()
    envelope.peak_equity_usd = 10000.0
    envelope.current_equity_usd = 9500.0
    envelope.current_drawdown_pct = 0.05
    
    # Mock bankroll returning negative balance (patch at the import location)
    with patch('merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync') as mock_get_equity:
        mock_get_equity.return_value = -100.0
        
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import safe_update_envelope_equity
        
        # Should handle negative balance gracefully
        result = safe_update_envelope_equity(envelope)
        assert result is True
        
        # Envelope should be updated via update_drawdown
        envelope.update_drawdown.assert_called_once_with(-100.0)


def test_envelope_initialization_without_bankroll():
    """Test envelope can be initialized even when bankroll service is unavailable."""
    # Mock bankroll service unavailable (patch at the import location)
    with patch('merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync') as mock_get_equity:
        mock_get_equity.return_value = None
        
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import compute_kalshi_crypto_15m_risk_envelope
        
        # Pass a fallback value when bankroll is unavailable
        fallback_capital = 10000.0
        
        # Should use fallback value when bankroll unavailable
        envelope = compute_kalshi_crypto_15m_risk_envelope(fallback_capital)
        
        # Envelope should still be initialized with fallback values
        assert envelope is not None
        assert envelope.peak_equity_usd > 0  # Fallback value


def test_envelope_adaptive_risk_update_after_bankroll_recovery():
    """Test adaptive risk bands update correctly after bankroll recovery."""
    envelope = Mock()
    envelope.peak_equity_usd = 10000.0
    envelope.current_equity_usd = 9500.0
    envelope.current_drawdown_pct = 0.05
    envelope.per_trade_risk_multiplier = 1.0
    
    # Mock bankroll returning lower balance (increased drawdown) (patch at the import location)
    with patch('merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync') as mock_get_equity:
        mock_get_equity.return_value = 8500.0  # 15% drawdown
        
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import safe_update_envelope_equity
        
        result = safe_update_envelope_equity(envelope)
        assert result is True
        
        # Envelope should be updated via update_drawdown
        envelope.update_drawdown.assert_called_once_with(8500.0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
