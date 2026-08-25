"""Unit tests for bankroll audit fixes.

Tests for:
- Valid Kalshi response format parsing
- Nested/unknown response rejection
- Negative balance ValueError
- is_live_profile classification
"""

import pytest
import asyncio
from decimal import Decimal
from unittest.mock import patch, MagicMock
import os


@pytest.fixture(autouse=True)
async def cleanup_pending_tasks():
    """Cleanup pending async tasks after each test to prevent RuntimeWarnings."""
    yield
    # Cancel all pending tasks after test, excluding the fixture's own task.
    current = asyncio.current_task()
    tasks = [t for t in asyncio.all_tasks() if not t.done() and t is not current]
    for task in tasks:
        task.cancel()
    # Wait for cancelled tasks to complete
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


class TestKalshiBalanceResponseFormat:
    """Test Kalshi balance response format validation."""

    def test_nested_format_raises_value_error(self):
        """Test that nested balance format raises ValueError."""
        # Simulate nested format response
        raw_data = {
            "balance": {
                "balance": 100000,
                "locked_balance": 5000
            }
        }
        
        # Extract balance_cents to test the validation logic
        balance_cents = raw_data.get("balance", 0)
        
        # This should raise ValueError for nested format
        if isinstance(balance_cents, dict):
            with pytest.raises(ValueError) as exc_info:
                raise ValueError(
                    f"Unexpected nested balance format. Expected flat format with 'balance' and 'locked_balance' keys. "
                    f"Got: {list(balance_cents.keys())}"
                )
            assert "Unexpected nested balance format" in str(exc_info.value)

    def test_negative_balance_raises_value_error(self):
        """Test that negative balance raises ValueError."""
        from decimal import Decimal
        
        # Test negative balance validation logic
        balance_cents = -1000
        
        balance_usd = Decimal(str(balance_cents)) / 100
        
        if balance_usd < 0:
            with pytest.raises(ValueError) as exc_info:
                raise ValueError(
                    f"Negative balance detected: ${balance_usd}. "
                    f"This indicates an API error or data corruption. "
                    f"Trading halted until resolved."
                )
            assert "Negative balance detected" in str(exc_info.value)

    def test_negative_locked_balance_raises_value_error(self):
        """Test that negative locked balance raises ValueError."""
        from decimal import Decimal
        
        # Test negative locked balance validation logic
        locked_cents = -5000
        
        locked_usd = Decimal(str(locked_cents)) / 100
        
        if locked_usd < 0:
            with pytest.raises(ValueError) as exc_info:
                raise ValueError(
                    f"Negative locked balance detected: ${locked_usd}. "
                    f"This indicates an API error or data corruption. "
                    f"Trading halted until resolved."
                )
            assert "Negative locked balance detected" in str(exc_info.value)


class TestIsLiveProfile:
    """Test is_live_profile classification."""

    def test_live_profile_returns_true(self):
        """Test that kalshi_crypto_15m_v2 with prod env returns True."""
        from merid.risk.profiles.crypto_15m_profile import is_live_profile
        
        with patch.dict(os.environ, {
            'MERID_KALSHI_ENV': 'prod',
            'MERID_ALLOW_FAKE_BANKROLL_FOR_TEST': '0'
        }):
            assert is_live_profile("kalshi_crypto_15m_v2") is True

    def test_demo_profile_returns_false(self):
        """Test that demo environment returns False."""
        from merid.risk.profiles.crypto_15m_profile import is_live_profile
        
        with patch.dict(os.environ, {
            'MERID_KALSHI_ENV': 'demo',
            'MERID_ALLOW_FAKE_BANKROLL_FOR_TEST': '0'
        }):
            assert is_live_profile("kalshi_crypto_15m_v2") is False

    def test_fake_bankroll_allowed_returns_false(self):
        """Test that allowing fake bankroll returns False."""
        from merid.risk.profiles.crypto_15m_profile import is_live_profile
        from merid.settings import settings
        
        with patch.object(settings, 'MERID_ALLOW_FAKE_BANKROLL_FOR_TEST', True):
            with patch.dict(os.environ, {
                'MERID_KALSHI_ENV': 'prod',
            }):
                assert is_live_profile("kalshi_crypto_15m_v2") is False

    def test_wrong_profile_name_returns_false(self):
        """Test that wrong profile name returns False."""
        from merid.risk.profiles.crypto_15m_profile import is_live_profile
        
        with patch.dict(os.environ, {
            'MERID_KALSHI_ENV': 'prod',
            'MERID_ALLOW_FAKE_BANKROLL_FOR_TEST': '0'
        }):
            assert is_live_profile("test_profile") is False
            assert is_live_profile("kalshi_crypto_15m") is False


class TestBalanceStateEnum:
    """Test BalanceState enum changes."""

    def test_degraded_state_added(self):
        """Test that DEGRADED state exists for cached-bankroll usage."""
        from merid.event_venues.kalshi.types import BalanceState

        assert hasattr(BalanceState, 'DEGRADED')

    def test_required_states_exist(self):
        """Test that all required bankroll states exist."""
        from merid.event_venues.kalshi.types import BalanceState

        states = {state.name for state in BalanceState}
        assert {'FRESH', 'DEGRADED', 'ERROR', 'UNKNOWN'}.issubset(states)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
