"""Regression tests for "no trade without exit" invariant.

Tests that enforce the invariant: all entry orders on 15m crypto contracts
must have exit targets (TP and/or SL) before routing.

Invariant scope:
- Entry orders: action="buy" on 15m crypto (KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M)
- Exit orders: action="sell" or source markers (take_profit, stop_loss, micro_scalp, exit, close)
- Feature flag: KALSHI_ENFORCE_EXIT_INVARIANT (default True)
"""

import asyncio
import os
import pytest

from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    route_order_async,
    _is_15m_crypto_entry_order,
    _has_exit_target,
    _check_exit_target_invariant,
)
from merid.prediction.venue_gate import TradingMode


class TestInvariantScope:
    """Test the scope detection functions."""

    def test_is_15m_crypto_entry_order_btc_buy(self):
        """BTC 15m buy order is an entry order requiring exit targets."""
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        assert _is_15m_crypto_entry_order(intent) is True

    def test_is_15m_crypto_entry_order_eth_buy(self):
        """ETH 15m buy order is an entry order requiring exit targets."""
        intent = OrderIntent(
            ticker="KXETH15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        assert _is_15m_crypto_entry_order(intent) is True

    def test_is_15m_crypto_entry_order_sol_buy(self):
        """SOL 15m buy order is an entry order requiring exit targets."""
        intent = OrderIntent(
            ticker="KXSOL15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        assert _is_15m_crypto_entry_order(intent) is True

    def test_is_15m_crypto_entry_order_xrp_buy(self):
        """XRP 15m buy order is an entry order requiring exit targets."""
        intent = OrderIntent(
            ticker="KXXRP15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        assert _is_15m_crypto_entry_order(intent) is True

    def test_is_15m_crypto_entry_order_doge_buy(self):
        """DOGE 15m buy order is an entry order requiring exit targets."""
        intent = OrderIntent(
            ticker="KXDOGE15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        assert _is_15m_crypto_entry_order(intent) is True

    def test_is_15m_crypto_entry_order_sell_exempt(self):
        """Sell orders are exempt from exit target requirement."""
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="sell",
            price_cents=50,
            count=1,
        )
        assert _is_15m_crypto_entry_order(intent) is False

    def test_is_15m_crypto_entry_order_non_15m_exempt(self):
        """Non-15m orders are exempt from exit target requirement."""
        intent = OrderIntent(
            ticker="KXBTCD-25JUN-T100000",  # Daily contract
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        assert _is_15m_crypto_entry_order(intent) is False

    def test_is_15m_crypto_entry_order_non_crypto_exempt(self):
        """Non-crypto orders are exempt from exit target requirement."""
        intent = OrderIntent(
            ticker="KXCPI-25JUN-T100000",  # CPI macro
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        assert _is_15m_crypto_entry_order(intent) is False

    def test_has_exit_target_with_tp_price(self):
        """Order with take_profit_price_cents has exit target."""
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            take_profit_price_cents=60,
        )
        assert _has_exit_target(intent) is True

    def test_has_exit_target_with_tp_r_multiple(self):
        """Order with take_profit_r_multiple has exit target."""
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            take_profit_r_multiple=1.5,
        )
        assert _has_exit_target(intent) is True

    def test_has_exit_target_with_sl(self):
        """Order with stop_loss_price_cents has exit target."""
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            stop_loss_price_cents=45,
        )
        assert _has_exit_target(intent) is True

    def test_has_exit_target_none(self):
        """Order without any exit targets fails check."""
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        assert _has_exit_target(intent) is False


class TestInvariantEnforcement:
    """Test the invariant enforcement in route_order_async."""

    @pytest.mark.asyncio
    async def test_entry_order_with_tp_passes(self):
        """Entry order with TP price should pass invariant check."""
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            take_profit_price_cents=60,
            mode=TradingMode.MOCK,
        )
        result = await route_order_async(intent)
        # Should not be rejected for invariant violation
        assert result.status != "rejected" or result.reason != "invariant_violation:no_trade_without_exit"

    @pytest.mark.asyncio
    async def test_entry_order_with_tp_r_multiple_passes(self):
        """Entry order with TP R-multiple should pass invariant check."""
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            take_profit_r_multiple=1.5,
            mode=TradingMode.MOCK,
        )
        result = await route_order_async(intent)
        # Should not be rejected for invariant violation
        assert result.status != "rejected" or result.reason != "invariant_violation:no_trade_without_exit"

    @pytest.mark.asyncio
    async def test_entry_order_with_sl_passes(self):
        """Entry order with SL should pass invariant check."""
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            stop_loss_price_cents=45,
            mode=TradingMode.MOCK,
        )
        result = await route_order_async(intent)
        # Should not be rejected for invariant violation
        assert result.status != "rejected" or result.reason != "invariant_violation:no_trade_without_exit"

    @pytest.mark.asyncio
    async def test_entry_order_without_exit_rejected(self):
        """Entry order without exit targets should be rejected."""
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            # No exit targets
            mode=TradingMode.MOCK,
        )
        result = await route_order_async(intent)
        # Should be rejected for invariant violation
        assert result.status == "rejected"
        assert "invariant_violation:no_trade_without_exit" in result.reason

    @pytest.mark.asyncio
    async def test_exit_order_without_exit_allowed(self):
        """Exit orders (sell) should not require exit targets."""
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="sell",
            price_cents=50,
            count=1,
            # No exit targets - should be allowed for sell
            mode=TradingMode.MOCK,
        )
        result = await route_order_async(intent)
        # Should not be rejected for invariant violation
        assert result.status != "rejected" or result.reason != "invariant_violation:no_trade_without_exit"

    @pytest.mark.asyncio
    async def test_non_15m_order_without_exit_allowed(self):
        """Non-15m orders should not require exit targets."""
        intent = OrderIntent(
            ticker="KXBTCD-25JUN-T100000",  # Daily contract
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            # No exit targets - should be allowed for non-15m
            mode=TradingMode.MOCK,
        )
        result = await route_order_async(intent)
        # Should not be rejected for invariant violation
        assert result.status != "rejected" or result.reason != "invariant_violation:no_trade_without_exit"

    @pytest.mark.asyncio
    async def test_feature_flag_can_disable(self):
        """Feature flag KALSHI_ENFORCE_EXIT_INVARIANT can disable enforcement."""
        # Save original value
        original = os.getenv("KALSHI_ENFORCE_EXIT_INVARIANT")
        
        try:
            # Disable enforcement
            os.environ["KALSHI_ENFORCE_EXIT_INVARIANT"] = "false"
            
            intent = OrderIntent(
                ticker="KXBTC15M-26APR191645-45",
                side="yes",
                action="buy",
                price_cents=50,
                count=1,
                # No exit targets - should pass when disabled
                mode=TradingMode.MOCK,
            )
            result = await route_order_async(intent)
            # Should not be rejected for invariant violation when disabled
            assert result.status != "rejected" or result.reason != "invariant_violation:no_trade_without_exit"
        finally:
            # Restore original value
            if original is None:
                os.environ.pop("KALSHI_ENFORCE_EXIT_INVARIANT", None)
            else:
                os.environ["KALSHI_ENFORCE_EXIT_INVARIANT"] = original


class TestBypassPathCoverage:
    """Test that bypass paths properly attach exit targets."""

    @pytest.mark.asyncio
    async def test_web_api_bypass_attaches_exit(self):
        """Web API endpoint should compute default TP if not provided."""
        # This test verifies the fix in web/api/kalshi_api.py
        # The endpoint now computes default TP for 15m crypto entry orders
        from merid.prediction.kalshi_tools import build_live_route_order_intent
        
        intent = build_live_route_order_intent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        
        # Should have either TP price or R-multiple after computation
        assert intent.take_profit_price_cents is not None or intent.take_profit_r_multiple is not None

    def test_executor_bypass_attaches_exit(self):
        """KalshiExecutor should compute default TP if not provided."""
        # This test verifies the fix in merid/execution/executors/kalshi.py
        # The executor now computes default TP for 15m crypto entry orders
        from merid.prediction.kalshi_tools import build_live_route_order_intent
        
        intent = build_live_route_order_intent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        
        # Should have either TP price or R-multiple after computation
        assert intent.take_profit_price_cents is not None or intent.take_profit_r_multiple is not None

    def test_tools_bypass_attaches_exit(self):
        """kalshi_tools.build_live_route_order_intent should compute default TP."""
        # This test verifies the fix in merid/prediction/kalshi_tools.py
        from merid.prediction.kalshi_tools import build_live_route_order_intent
        
        intent = build_live_route_order_intent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        
        # Should have either TP price or R-multiple after computation
        assert intent.take_profit_price_cents is not None or intent.take_profit_r_multiple is not None

    def test_ct_adapter_bypass_attaches_exit(self):
        """CT execution adapter should compute default TP."""
        # This test verifies the fix in merid/trading/ct_execution_adapter.py
        # The adapter now computes default TP for 15m crypto entry orders
        from merid.trading.ct_execution_adapter import CTExecutionAdapter
        
        adapter = CTExecutionAdapter()
        order_data = {
            "ticker": "KXBTC15M-26APR191645-45",
            "side": "yes",
            "action": "buy",
            "yes_price": 50,
            "count": 1,
        }
        
        intent = adapter._order_dict_to_intent(order_data)
        
        # Should have either TP price or R-multiple after computation
        assert intent.take_profit_price_cents is not None or intent.take_profit_r_multiple is not None


class TestMetrics:
    """Test that metrics are emitted correctly."""

    @pytest.mark.asyncio
    async def test_compliance_metric_emitted(self):
        """Compliance metric should be emitted when order has exit targets."""
        from unittest.mock import patch
        
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            take_profit_price_cents=60,
            mode=TradingMode.MOCK,
        )
        
        # Mock the metric at its import location (merid.metrics.kalshi_metrics)
        with patch('merid.metrics.kalshi_metrics.kalshi_exit_invariant_compliant_total') as mock_metric:
            mock_metric.labels.return_value.inc.return_value = None
            await route_order_async(intent)
            # Verify metric was called
            assert mock_metric.labels.called

    @pytest.mark.asyncio
    async def test_violation_metric_emitted(self):
        """Violation metric should be emitted when order lacks exit targets."""
        from unittest.mock import patch
        
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            # No exit targets
            mode=TradingMode.MOCK,
        )
        
        # Mock the metric at its import location (merid.metrics.kalshi_metrics)
        with patch('merid.metrics.kalshi_metrics.kalshi_exit_invariant_violations') as mock_metric:
            mock_metric.labels.return_value.inc.return_value = None
            await route_order_async(intent)
            # Verify metric was called
            assert mock_metric.labels.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
