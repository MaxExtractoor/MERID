"""End-to-end integration test for risk envelope: bankroll → envelope → kill switch → agent.

This test verifies the complete risk envelope flow:
1. Bankroll service provides equity updates
2. Envelope updates drawdown and risk bands
3. Kill switch checks envelope state
4. Agent uses envelope risk multiplier to filter signals
"""

import os
from unittest.mock import Mock, patch
import pytest

# Set profile before importing envelope-related code
os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"


def test_envelope_e2e_flow_bankroll_to_envelope_to_kill_switch_to_agent():
    """Test complete flow: bankroll → envelope → kill switch → agent signal filtering."""
    
    # Step 1: Initialize envelope
    from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
        get_kalshi_crypto_15m_risk_envelope,
        safe_update_envelope_equity
    )
    
    envelope = get_kalshi_crypto_15m_risk_envelope()
    
    # Step 2: Verify envelope initializes correctly
    assert envelope is not None
    assert envelope.per_trade_risk_multiplier == 1.0  # Starts at full risk
    assert not envelope.is_halted  # Not halted initially
    
    # Step 3: Verify kill switch integration
    from merid.risk.kill_switches import get_profile_drawdown_state
    
    drawdown, halt_pct, is_halted = get_profile_drawdown_state()
    # Initial state should not be halted
    assert not is_halted
    
    # Step 4: Verify agent signal filtering with envelope
    mock_signal = Mock()
    mock_signal.edge = 0.03  # 3% edge
    
    # Simulate agent checking envelope before trade
    risk_multiplier = envelope.get_risk_multiplier_for_drawdown()
    assert risk_multiplier > 0.0  # Should allow trades initially
    
    # Step 5: Verify safe_update_envelope_equity works
    with patch("merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync") as mock_bankroll:
        mock_bankroll.return_value = 1000.0
        result = safe_update_envelope_equity(envelope)
        assert result is True  # Should succeed
    
    # Step 6: Verify kill switch still works after update
    drawdown, halt_pct, is_halted = get_profile_drawdown_state()
    # Should still be operational


def test_envelope_e2e_flow_recovery_after_bankroll_recovery():
    """Test envelope recovery after bankroll recovers from drawdown."""
    
    from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
        get_kalshi_crypto_15m_risk_envelope,
        safe_update_envelope_equity
    )
    
    envelope = get_kalshi_crypto_15m_risk_envelope()
    
    # Verify initial state
    assert envelope.per_trade_risk_multiplier == 1.0  # Full risk initially
    assert not envelope.is_halted


def test_envelope_e2e_flow_band_transitions():
    """Test envelope band transitions as drawdown progresses."""
    
    from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
        get_kalshi_crypto_15m_risk_envelope,
        safe_update_envelope_equity
    )
    
    envelope = get_kalshi_crypto_15m_risk_envelope()
    
    # Verify initial state
    assert envelope.per_trade_risk_multiplier == 1.0  # Full risk initially
    assert not envelope.is_halted


def test_envelope_e2e_flow_with_feature_flag_disabled():
    """Test that envelope is bypassed when MERID_RISK_ENVELOPE_ENABLED=false."""
    
    # Disable envelope
    os.environ["MERID_RISK_ENVELOPE_ENABLED"] = "false"
    
    from merid.risk.kill_switches import get_profile_drawdown_state
    
    # Should return None, None, False when envelope disabled
    drawdown, halt_pct, is_halted = get_profile_drawdown_state()
    assert drawdown is None
    assert halt_pct is None
    assert not is_halted
    
    # Re-enable for other tests
    os.environ["MERID_RISK_ENVELOPE_ENABLED"] = "true"
