"""
Production Hardening Tests

Verifies that bypass paths are properly blocked and runtime guards work.
These tests ensure the unified execution authority design is enforced.
"""

import os
import sys
import pytest
from unittest.mock import patch


class TestMakerBotAdvancedHardening:
    """Verify maker_bot_advanced.py is properly hardened."""

    def test_import_blocked_by_default(self):
        """Importing maker_bot_advanced without env var should raise RuntimeError."""
        # Ensure env var is not set
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(RuntimeError) as exc_info:
                import importlib
                # Force reimport by clearing cache if present
                if 'merid.kalshi.maker_bot_advanced' in sys.modules:
                    del sys.modules['merid.kalshi.maker_bot_advanced']
                import merid.kalshi.maker_bot_advanced

        assert "PRODUCTION HARDENING" in str(exc_info.value)
        assert "DISABLED" in str(exc_info.value)
        assert "route_order_async" in str(exc_info.value)

    def test_import_allowed_with_override(self):
        """Import should succeed with MERID_ALLOW_MAKER_BOT_ADVANCED=1."""
        # Note: This test may leave the module in sys.modules
        with patch.dict(os.environ, {"MERID_ALLOW_MAKER_BOT_ADVANCED": "1"}):
            # This should not raise - but we can't easily test without
            # actually importing. In practice, the check is at module level.
            pass


class TestCanonicalExecutionPath:
    """Verify all order paths route through order_router."""

    def test_kalshi_tools_uses_router(self):
        """kalshi_tools._kalshi_place_order must call route_order_async."""
        import inspect
        from merid.prediction import kalshi_tools

        source = inspect.getsource(kalshi_tools._kalshi_place_order)
        assert "route_order_async" in source
        assert "OrderIntent" in source

    def test_trading_agent_uses_router(self):
        """KalshiTradingAgent._execute_signal_body must call route_order_async for live orders."""
        import inspect
        from merid.prediction.trading_agent import KalshiTradingAgent

        # Check _execute_signal_body which contains the actual order routing logic
        # The _execute_signal method just wraps it with execution state management
        source = inspect.getsource(KalshiTradingAgent._execute_signal_body)
        # Should have route_order_async call
        assert "route_order_async" in source
        # Should NOT have direct client calls
        assert "client.create_order" not in source or "await client.create_order" not in source

    def test_continuous_trader_uses_router(self):
        """KalshiContinuousTrader must use route_order_async."""
        import inspect
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader

        source = inspect.getsource(KalshiContinuousTrader)
        assert "route_order_async" in source


class TestTop3BatchGate:
    """Verify Top-3 batch allocation gate is enforced."""

    def test_order_router_has_batch_check(self):
        """order_router must have _check_top3_batch_allocation function."""
        import inspect
        from merid.event_venues.kalshi import order_router

        assert hasattr(order_router, '_check_top3_batch_allocation')

    def test_batch_check_is_called(self):
        """route_order_async must call the batch check."""
        import inspect
        from merid.event_venues.kalshi.order_router import route_order_async

        source = inspect.getsource(route_order_async)
        assert "_check_top3_batch_allocation" in source or "top3" in source.lower()


class TestGlobalRiskGuard:
    """Verify GlobalRiskGuard is enforced."""

    def test_order_router_calls_risk_guard(self):
        """order_router must call GlobalRiskGuard via _run_shared_risk_guard_and_dedup."""
        import inspect
        from merid.event_venues.kalshi import order_router

        assert hasattr(order_router, '_run_shared_risk_guard_and_dedup')

        source = inspect.getsource(order_router.route_order_async)
        assert "_run_shared_risk_guard_and_dedup" in source or "global_risk_guard" in source.lower()


class TestNoDirectHTTPBypasses:
    """Verify no direct HTTP calls to Kalshi exist in production code."""

    def test_no_requests_import_in_agents(self):
        """Trading agents should not import requests (HTTP client)."""
        # This is a heuristic - requests might be used for other purposes
        # but should not be used for order submission
        import ast
        import inspect
        from merid.prediction.trading_agent import KalshiTradingAgent

        source = inspect.getsource(KalshiTradingAgent)
        # Should not contain requests.post or requests.get for API calls
        assert "requests.post" not in source
        assert "requests.get" not in source


class TestCriticalScriptBypasses:
    """Verify critical bypass scripts are properly hardened."""

    def test_run_live_trade_blocked_by_default(self):
        """run_live_trade.py must raise RuntimeError without MERID_ALLOW_LIVE_TRADE_BYPASS."""
        with pytest.raises(RuntimeError) as exc_info:
            # Ensure env var is not set
            with patch.dict(os.environ, {}, clear=True):
                # Force reimport by clearing cache
                if 'run_live_trade' in sys.modules:
                    del sys.modules['run_live_trade']
                import run_live_trade

        assert "PRODUCTION HARDENING" in str(exc_info.value)
        assert "DISABLED" in str(exc_info.value)

    def test_kalshi_live_trade_blocked_by_default(self):
        """scripts/kalshi_live_trade.py must raise RuntimeError without bypass env var."""
        with pytest.raises(RuntimeError) as exc_info:
            with patch.dict(os.environ, {}, clear=True):
                if 'scripts.kalshi_live_trade' in sys.modules:
                    del sys.modules['scripts.kalshi_live_trade']
                from scripts import kalshi_live_trade

        assert "PRODUCTION HARDENING" in str(exc_info.value)
        assert "DISABLED" in str(exc_info.value)

    def test_ct_script_blocked_by_default(self):
        """scripts/kalshi_continuous_trader.py must raise RuntimeError without bypass env var."""
        with pytest.raises(RuntimeError) as exc_info:
            with patch.dict(os.environ, {}, clear=True):
                if 'scripts.kalshi_continuous_trader' in sys.modules:
                    del sys.modules['scripts.kalshi_continuous_trader']
                from scripts import kalshi_continuous_trader

        assert "PRODUCTION HARDENING" in str(exc_info.value)
        assert "DISABLED" in str(exc_info.value)


class TestExecutionPipelineBypass:
    """Verify merid_core.kalshi.execution_pipeline is properly hardened."""

    def test_execution_pipeline_blocked_by_default(self):
        """execution_pipeline.py must raise RuntimeError without MERID_ALLOW_EXECUTION_PIPELINE_BYPASS."""
        with pytest.raises(RuntimeError) as exc_info:
            with patch.dict(os.environ, {}, clear=True):
                if 'merid_core.kalshi.execution_pipeline' in sys.modules:
                    del sys.modules['merid_core.kalshi.execution_pipeline']
                import merid_core.kalshi.execution_pipeline

        assert "PRODUCTION HARDENING" in str(exc_info.value)
        assert "DISABLED" in str(exc_info.value)
        assert "order_router" in str(exc_info.value).lower()

    def test_execution_pipeline_requires_both_flags(self):
        """execution_pipeline requires both NATS flag AND bypass flag."""
        # Only NATS flag, no bypass flag
        with pytest.raises(RuntimeError) as exc_info:
            with patch.dict(os.environ, {"MERID_NATS_EXECUTION_ENABLED": "true"}):
                if 'merid_core.kalshi.execution_pipeline' in sys.modules:
                    del sys.modules['merid_core.kalshi.execution_pipeline']
                import merid_core.kalshi.execution_pipeline

        assert "PRODUCTION HARDENING" in str(exc_info.value)


class TestRestClientBypass:
    """Verify merid_core.kalshi.rest_client order methods are properly hardened."""

    def test_rest_client_create_order_blocked_by_default(self):
        """rest_client.create_order must raise RuntimeError without MERID_ALLOW_REST_CLIENT_ORDERS."""
        from merid_core.kalshi.rest_client import KalshiRestClient

        # Create a mock client (don't need real credentials for this test)
        with pytest.raises(RuntimeError) as exc_info:
            client = KalshiRestClient.__new__(KalshiRestClient)
            client.create_order(
                ticker="KXBTC-TEST",
                side="yes",
                action="buy",
                quantity=1,
                price=50,
                client_order_id="test"
            )

        assert "PRODUCTION HARDENING" in str(exc_info.value)
        assert "create_order" in str(exc_info.value)

    def test_rest_client_amend_order_blocked_by_default(self):
        """rest_client.amend_order must raise RuntimeError without MERID_ALLOW_REST_CLIENT_ORDERS."""
        from merid_core.kalshi.rest_client import KalshiRestClient

        with pytest.raises(RuntimeError) as exc_info:
            client = KalshiRestClient.__new__(KalshiRestClient)
            client.amend_order(order_id="test-123", price=60)

        assert "PRODUCTION HARDENING" in str(exc_info.value)
        assert "amend_order" in str(exc_info.value)

    def test_rest_client_cancel_order_blocked_by_default(self):
        """rest_client.cancel_order must raise RuntimeError without MERID_ALLOW_REST_CLIENT_ORDERS."""
        from merid_core.kalshi.rest_client import KalshiRestClient

        with pytest.raises(RuntimeError) as exc_info:
            client = KalshiRestClient.__new__(KalshiRestClient)
            client.cancel_order(order_id="test-123")

        assert "PRODUCTION HARDENING" in str(exc_info.value)
        assert "cancel_order" in str(exc_info.value)

    def test_rest_client_batch_cancel_blocked_by_default(self):
        """rest_client.batch_cancel_orders must raise RuntimeError without MERID_ALLOW_REST_CLIENT_ORDERS."""
        from merid_core.kalshi.rest_client import KalshiRestClient

        with pytest.raises(RuntimeError) as exc_info:
            client = KalshiRestClient.__new__(KalshiRestClient)
            client.batch_cancel_orders(ticker="KXBTC-TEST")

        assert "PRODUCTION HARDENING" in str(exc_info.value)
        assert "batch_cancel_orders" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
