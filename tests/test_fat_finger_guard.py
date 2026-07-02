"""Tests for fat-finger limit validation in order submission."""
import pytest
from decimal import Decimal
from unittest.mock import Mock, patch, AsyncMock
from merid.prediction.kalshi_tools import _kalshi_place_order
from merid.guardrails.tools import ToolErrorCode


class TestFatFingerGuard:
    """Test fat-finger limit validation in kalshi_place_order."""

    @pytest.mark.asyncio
    async def test_order_within_max_order_size_accepted(self):
        """Test that orders within max_order_size are accepted."""
        with patch('merid.prediction.kalshi_tools._get_client') as mock_client, \
             patch('merid.prediction.kalshi_tools.get_venue_gate') as mock_gate, \
             patch('merid.settings.settings') as mock_settings:
            
            # Mock settings with max_order_size and required attributes
            mock_settings.MERID_MAX_ORDER_SIZE_USD = 1000.0
            mock_settings.MERID_LOOP_DRY_RUN = True
            mock_settings.MERID_ENV = "development"
            mock_settings.MERID_PM_PROFILE = "baseline"
            
            # Mock gate to simulate fills
            mock_gate.should_simulate_fill.return_value = True
            mock_gate.check_order.return_value = None
            
            # Order notional: 50 cents * 10 contracts = $5.00 (within $1000 limit)
            result = await _kalshi_place_order(
                ticker="KXBTC15M-26APR192030-30",
                side="yes",
                action="buy",
                price_cents=50,
                count=10,
                agent_name="BTC_15M",
            )
            
            assert result.success, f"Order should be accepted, got: {result}"
            assert result.payload.get("dry_run") == True

    @pytest.mark.asyncio
    async def test_order_exceeding_max_order_size_rejected(self):
        """Test that orders exceeding max_order_size are rejected."""
        with patch('merid.prediction.kalshi_tools.get_venue_gate') as mock_gate, \
             patch('merid.settings.settings') as mock_settings:
            
            # Mock settings with max_order_size and required attributes
            mock_settings.MERID_MAX_ORDER_SIZE_USD = 10.0
            mock_settings.MERID_LOOP_DRY_RUN = False
            mock_settings.MERID_ENV = "development"
            mock_settings.MERID_PM_PROFILE = "baseline"
            
            # Mock gate
            mock_gate.should_simulate_fill.return_value = False
            mock_gate.check_order.return_value = None
            
            # Order notional: 50 cents * 100 contracts = $50.00 (exceeds $10 limit)
            result = await _kalshi_place_order(
                ticker="KXBTC15M-26APR192030-30",
                side="yes",
                action="buy",
                price_cents=50,
                count=100,
                agent_name="BTC_15M",
            )
            
            assert not result.success, "Order should be rejected for exceeding max_order_size"
            assert result.error_code == ToolErrorCode.INVALID_INPUT
            assert "exceeds maximum allowed" in result.error_message.lower()
            assert "$50.00" in result.error_message
            assert "$10.00" in result.error_message

    @pytest.mark.asyncio
    async def test_fat_finger_guard_disabled_when_max_order_size_zero(self):
        """Test that fat-finger guard is disabled when max_order_size is 0 or None."""
        with patch('merid.prediction.kalshi_tools._get_client') as mock_client, \
             patch('merid.prediction.kalshi_tools.get_venue_gate') as mock_gate, \
             patch('merid.settings.settings') as mock_settings:
            
            # Mock settings with max_order_size = 0 (disabled) and required attributes
            mock_settings.MERID_MAX_ORDER_SIZE_USD = 0
            mock_settings.MERID_LOOP_DRY_RUN = True
            mock_settings.MERID_ENV = "development"
            mock_settings.MERID_PM_PROFILE = "baseline"
            
            # Mock gate to simulate fills
            mock_gate.should_simulate_fill.return_value = True
            mock_gate.check_order.return_value = None
            
            # Order notional: 50 cents * 1000 contracts = $500.00 (would exceed $10 limit if enabled)
            result = await _kalshi_place_order(
                ticker="KXBTC15M-26APR192030-30",
                side="yes",
                action="buy",
                price_cents=50,
                count=1000,
                agent_name="BTC_15M",
            )
            
            # Should be accepted since guard is disabled
            assert result.success, f"Order should be accepted when guard disabled, got: {result}"

    @pytest.mark.asyncio
    async def test_fat_finger_guard_disabled_when_max_order_size_none(self):
        """Test that fat-finger guard is disabled when max_order_size is None."""
        with patch('merid.prediction.kalshi_tools._get_client') as mock_client, \
             patch('merid.prediction.kalshi_tools.get_venue_gate') as mock_gate, \
             patch('merid.settings.settings') as mock_settings:
            
            # Mock settings without max_order_size attribute but with required attributes
            mock_settings.MERID_LOOP_DRY_RUN = True
            mock_settings.MERID_ENV = "development"
            mock_settings.MERID_PM_PROFILE = "baseline"
            # Don't set MERID_MAX_ORDER_SIZE_USD to simulate None
            
            # Mock gate to simulate fills
            mock_gate.should_simulate_fill.return_value = True
            mock_gate.check_order.return_value = None
            
            # Order notional: 50 cents * 1000 contracts = $500.00
            result = await _kalshi_place_order(
                ticker="KXBTC15M-26APR192030-30",
                side="yes",
                action="buy",
                price_cents=50,
                count=1000,
                agent_name="BTC_15M",
            )
            
            # Should be accepted since guard is disabled
            assert result.success, f"Order should be accepted when guard disabled, got: {result}"

    @pytest.mark.asyncio
    async def test_fat_finger_guard_exact_limit_accepted(self):
        """Test that orders exactly at max_order_size are accepted."""
        with patch('merid.prediction.kalshi_tools._get_client') as mock_client, \
             patch('merid.prediction.kalshi_tools.get_venue_gate') as mock_gate, \
             patch('merid.settings.settings') as mock_settings:
            
            # Mock settings with max_order_size and required attributes
            mock_settings.MERID_MAX_ORDER_SIZE_USD = 100.0
            mock_settings.MERID_LOOP_DRY_RUN = True
            mock_settings.MERID_ENV = "development"
            mock_settings.MERID_PM_PROFILE = "baseline"
            
            # Mock gate to simulate fills
            mock_gate.should_simulate_fill.return_value = True
            mock_gate.check_order.return_value = None
            
            # Order notional: 50 cents * 200 contracts = $100.00 (exactly at limit)
            result = await _kalshi_place_order(
                ticker="KXBTC15M-26APR192030-30",
                side="yes",
                action="buy",
                price_cents=50,
                count=200,
                agent_name="BTC_15M",
            )
            
            assert result.success, f"Order at exact limit should be accepted, got: {result}"
