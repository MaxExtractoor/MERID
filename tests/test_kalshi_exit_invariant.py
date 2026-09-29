"""Regression tests for the position lifecycle invariant.

Contract (profit_only_v1): all entry orders on 15m crypto contracts must carry
a valid PositionLifecyclePlan.  A plan is a lifecycle contract, not an armed
exit order - HOLD_TO_SETTLEMENT is a complete legal plan, loss-triggered exits
are disabled by policy, and profit exits (resting TP / profit-lock trail) are
optional components that never gate entry.

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
        """Bare entry order derives a HOLD_TO_SETTLEMENT plan and passes.

        Under profit_only_v1, an entry with no armed TP/SL is a valid
        HOLD_TO_SETTLEMENT lifecycle plan - settlement is the exit.  It must
        NOT be rejected by the lifecycle invariant (this is the
        no_trade_without_exit defect fix: the ETH BUY_NO@35c +4.4% entry was
        wrongly rejected).
        """
        import time as _time
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            # No exit targets -> valid HOLD_TO_SETTLEMENT plan
            mode=TradingMode.MOCK,
        )
        result = _check_exit_target_invariant(intent, _time.monotonic(), TradingMode.MOCK)
        # Invariant passes - a valid plan was derived and attached
        assert result is None
        assert intent.lifecycle_plan is not None
        assert intent.lifecycle_plan["exit_mode"] == "HOLD_TO_SETTLEMENT"
        assert intent.lifecycle_plan["stop_loss_enabled"] is False
        assert intent.lifecycle_plan["hold_to_settlement_enabled"] is True

    def test_explicit_hold_to_settlement_plan_passes(self):
        """An explicit HOLD_TO_SETTLEMENT lifecycle plan is valid."""
        import time as _time
        intent = OrderIntent(
            ticker="KXETH15M-26SEP291215-15",
            side="no",
            action="buy",
            price_cents=35,
            count=1,
            lifecycle_plan={
                "policy_id": "profit_only_v1",
                "exit_mode": "HOLD_TO_SETTLEMENT",
                "stop_loss_enabled": False,
                "hold_to_settlement_enabled": True,
            },
            mode=TradingMode.MOCK,
        )
        assert _check_exit_target_invariant(intent, _time.monotonic(), TradingMode.MOCK) is None

    def test_explicit_tp_plus_trail_plan_passes(self):
        """An explicit TAKE_PROFIT_PLUS_PROFIT_TRAIL plan is valid (the ETH 35c example)."""
        import time as _time
        intent = OrderIntent(
            ticker="KXETH15M-26SEP291215-15",
            side="no",
            action="buy",
            price_cents=35,
            count=1,
            lifecycle_plan={
                "policy_id": "profit_only_v1",
                "exit_mode": "TAKE_PROFIT_PLUS_PROFIT_TRAIL",
                "stop_loss_enabled": False,
                "hold_to_settlement_enabled": True,
                "take_profit_enabled": True,
                "take_profit_price_cents": 43,
                "profit_trail_enabled": True,
                "trail_activation_price_cents": 40,
                "trail_floor_price_cents": 37,
                "trail_distance_cents": 2,
            },
            mode=TradingMode.MOCK,
        )
        assert _check_exit_target_invariant(intent, _time.monotonic(), TradingMode.MOCK) is None
        assert intent.lifecycle_plan["exit_mode"] == "TAKE_PROFIT_PLUS_PROFIT_TRAIL"

    def test_explicit_plan_with_stop_loss_rejected(self):
        """An explicit lifecycle plan claiming an enabled stop-loss is a
        contract violation under profit_only_v1 and must be rejected."""
        import time as _time
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            lifecycle_plan={
                "policy_id": "profit_only_v1",
                "exit_mode": "TAKE_PROFIT_ONLY",
                "stop_loss_enabled": True,  # VIOLATION: loss exits disabled by policy
                "take_profit_enabled": True,
                "take_profit_price_cents": 60,
            },
            mode=TradingMode.MOCK,
        )
        result = _check_exit_target_invariant(intent, _time.monotonic(), TradingMode.MOCK)
        assert result is not None and result.status == "rejected"
        assert "invariant_violation:invalid_lifecycle_plan:stop_loss_enabled" in result.reason

    def test_explicit_plan_bad_mode_rejected(self):
        """An explicit plan with an unrecognized exit_mode is rejected."""
        import time as _time
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            lifecycle_plan={
                "exit_mode": "STOP_LOSS_TRAILING",
                "stop_loss_enabled": False,
            },
            mode=TradingMode.MOCK,
        )
        result = _check_exit_target_invariant(intent, _time.monotonic(), TradingMode.MOCK)
        assert result is not None and result.status == "rejected"
        assert "invariant_violation:invalid_lifecycle_plan:invalid_exit_mode" in result.reason

    def test_upstream_armed_stop_loss_stripped_not_blocked(self):
        """An entry arriving with an armed upstream SL is normalized, not blocked.

        profit_only_v1 keeps loss exits disabled: the router strips the armed
        SL fields, attaches a valid derived plan, and the entry proceeds.
        """
        import time as _time
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            take_profit_price_cents=60,
            stop_loss_price_cents=45,
            stop_loss_enabled=True,
            mode=TradingMode.MOCK,
        )
        result = _check_exit_target_invariant(intent, _time.monotonic(), TradingMode.MOCK)
        # Not rejected by the lifecycle invariant
        assert result is None
        # Armed SL fields are stripped; plan records SL disabled
        assert intent.stop_loss_price_cents is None
        assert intent.stop_loss_enabled is False
        assert intent.lifecycle_plan is not None
        assert intent.lifecycle_plan["stop_loss_enabled"] is False
        assert intent.lifecycle_plan["exit_mode"] == "TAKE_PROFIT_ONLY"

    def test_hold_to_settlement_policy_mode_passes(self):
        """exit_policy dict mode=HOLD_TO_SETTLEMENT yields a valid plan even
        if stray exit fields are present."""
        import time as _time
        intent = OrderIntent(
            ticker="KXETH15M-26SEP291215-15",
            side="no",
            action="buy",
            price_cents=35,
            count=1,
            exit_policy={"mode": "HOLD_TO_SETTLEMENT", "stop_loss_enabled": False},
            mode=TradingMode.MOCK,
        )
        assert _check_exit_target_invariant(intent, _time.monotonic(), TradingMode.MOCK) is None
        assert intent.lifecycle_plan["exit_mode"] == "HOLD_TO_SETTLEMENT"

    def test_derived_trail_params_use_asset_defaults(self):
        """A policy with trailing_enabled derives PROFIT_TRAIL params with a
        fee-aware floor above entry (profit-lock, never a loss exit)."""
        import time as _time
        intent = OrderIntent(
            ticker="KXETH15M-26SEP291215-15",
            side="no",
            action="buy",
            price_cents=35,
            count=1,
            exit_policy={
                "mode": "ACTIVE_MANAGEMENT",
                "stop_loss_enabled": False,
                "take_profit_enabled": False,
                "trailing_enabled": True,
            },
            mode=TradingMode.MOCK,
        )
        assert _check_exit_target_invariant(intent, _time.monotonic(), TradingMode.MOCK) is None
        plan = intent.lifecycle_plan
        assert plan["exit_mode"] == "PROFIT_TRAIL_ONLY"
        assert plan["profit_trail_enabled"] is True
        # ETH: activation +4c over entry
        assert plan["trail_activation_price_cents"] == 39
        # floor >= entry + min locked profit (fee-aware)
        assert plan["trail_floor_price_cents"] is not None
        assert plan["trail_floor_price_cents"] > 35
        assert plan["trail_distance_cents"] == 2

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

    def test_compliance_metric_emitted(self):
        """Compliance metric should be emitted when the plan is valid."""
        import time as _time
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
        with patch('merid.metrics.kalshi_metrics.kalshi_exit_invariant_compliant_total',
                   create=True) as mock_metric:
            mock_metric.labels.return_value.inc.return_value = None
            _check_exit_target_invariant(intent, _time.monotonic(), TradingMode.MOCK)
            # Verify metric was called
            assert mock_metric.labels.called

    def test_violation_metric_emitted(self):
        """Violation metric should be emitted for an invalid lifecycle plan."""
        import time as _time
        from unittest.mock import patch
        
        intent = OrderIntent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            # Explicit plan claiming an enabled stop-loss -> contract violation
            lifecycle_plan={"exit_mode": "TAKE_PROFIT_ONLY", "stop_loss_enabled": True,
                            "take_profit_enabled": True, "take_profit_price_cents": 60},
            mode=TradingMode.MOCK,
        )
        
        # Mock the metric at its import location (merid.metrics.kalshi_metrics)
        with patch('merid.metrics.kalshi_metrics.kalshi_exit_invariant_violations',
                   create=True) as mock_metric:
            mock_metric.labels.return_value.inc.return_value = None
            _check_exit_target_invariant(intent, _time.monotonic(), TradingMode.MOCK)
            # Verify metric was called
            assert mock_metric.labels.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
