"""Test integration of top 3 gate with window-based risk limits.

CRITICAL FIX (2026-07-07): Added window limit check to top3_batch_manager.py
to unify top 3 gate with window limits, preventing venue window bottleneck.
"""

import pytest
import time
from unittest.mock import MagicMock, patch


class TestTop3WindowIntegration:
    """Test top 3 gate integration with window limits."""
    
    def test_top3_gate_checks_window_limit(self):
        """Test that top 3 gate checks window limits before allowing positions."""
        with patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope') as mock_get_envelope:
            mock_envelope = MagicMock()
            mock_envelope.check_window_limit.return_value = (False, "per_agent_window_limit")
            mock_get_envelope.return_value = mock_envelope
            
            from merid.trading.top3_batch_manager import get_top3_batch_manager
            from merid.trading.top3_edge_allocator import Top3Batch, Top3Allocation, BatchStatus
            
            # Create a mock batch
            batch = Top3Batch(
                batch_id="test_batch",
                cycle_ts=time.time(),
                allocations=[
                    Top3Allocation(asset="BTC", target_notional=3000, weight=0.5),
                    Top3Allocation(asset="ETH", target_notional=2000, weight=0.3),
                    Top3Allocation(asset="SOL", target_notional=1000, weight=0.2),
                ],
                status=BatchStatus.ACTIVE,
            )
            
            # Mock the batch manager to return our test batch
            batch_mgr = get_top3_batch_manager()
            batch_mgr._current_batch = batch
            
            # Try to open a position - should be rejected by window limit
            allowed, reason, allocation = batch_mgr.can_open_new_position(
                asset="BTC",
                requested_notional=1000  # $10
            )
            
            # Should be rejected due to window limit
            assert allowed is False
            assert "WINDOW_LIMIT_EXCEEDED" in reason
            assert allocation is None
    
    def test_top3_gate_allows_within_window_limit(self):
        """Test that top 3 gate allows positions within window limits."""
        with patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope') as mock_get_envelope:
            mock_envelope = MagicMock()
            mock_envelope.check_window_limit.return_value = (True, "")
            mock_get_envelope.return_value = mock_envelope
            
            from merid.trading.top3_batch_manager import get_top3_batch_manager
            from merid.trading.top3_edge_allocator import Top3Batch, Top3Allocation, BatchStatus
            
            # Create a mock batch
            batch = Top3Batch(
                batch_id="test_batch",
                cycle_ts=time.time(),
                allocations=[
                    Top3Allocation(asset="BTC", target_notional=3000, weight=0.5),
                    Top3Allocation(asset="ETH", target_notional=2000, weight=0.3),
                    Top3Allocation(asset="SOL", target_notional=1000, weight=0.2),
                ],
                status=BatchStatus.ACTIVE,
            )
            
            # Mock the batch manager to return our test batch
            batch_mgr = get_top3_batch_manager()
            batch_mgr._current_batch = batch
            
            # Try to open a position - should be allowed
            allowed, reason, allocation = batch_mgr.can_open_new_position(
                asset="BTC",
                requested_notional=1000  # $10
            )
            
            # Should be allowed (within window limit)
            assert allowed is True
            assert reason == ""
            assert allocation is not None
            assert allocation.asset == "BTC"
    
    def test_top3_gate_fail_open_on_window_check_failure(self):
        """Test that top 3 gate fails-open if window check infrastructure fails."""
        with patch('merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope') as mock_get_envelope:
            mock_envelope.side_effect = Exception("Infrastructure failure")
            mock_get_envelope.return_value = mock_envelope
            
            from merid.trading.top3_batch_manager import get_top3_batch_manager
            from merid.trading.top3_edge_allocator import Top3Batch, Top3Allocation, BatchStatus
            
            # Create a mock batch
            batch = Top3Batch(
                batch_id="test_batch",
                cycle_ts=time.time(),
                allocations=[
                    Top3Allocation(asset="BTC", target_notional=3000, weight=0.5),
                ],
                status=BatchStatus.ACTIVE,
            )
            
            # Mock the batch manager to return our test batch
            batch_mgr = get_top3_batch_manager()
            batch_mgr._current_batch = batch
            
            # Try to open a position - should be allowed (fail-open)
            allowed, reason, allocation = batch_mgr.can_open_new_position(
                asset="BTC",
                requested_notional=1000
            )
            
            # Should be allowed (fail-open on infrastructure failure)
            assert allowed is True
            assert allocation is not None
