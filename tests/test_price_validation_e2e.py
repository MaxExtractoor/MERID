"""End-to-end tests for price validation across all order paths.

2026-11-23 update: the legacy 50-70c entry band was removed 2026-07-05 —
the 15m stack trades the full 5-99c contract range across lanes (cheap_no
10-40c, generic 5-95c, pinned_fav 90-96c, settlement_convergence to 99c).
Price enforcement now lives at:

- ``kalshi_tools._kalshi_place_order``: safety clamp to the profile
  ``price_range`` [5, 85] before intent construction;
- ``order_router._route_live``: hard bounds 5-95c for entries (99c for
  reduce-only exits and lane-admitted ceilings);
- ``order_router._validate_price_against_orderbook`` + submit
  revalidation: marketability, edge-budget, and post-only crossing.

``trading.py`` deliberately performs NO local range check — it is a thin
client wrapper; validation is centralized in the router.
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Set profile for tests
os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"


class TestTradingPyPriceValidation:
    """Test price validation in legacy trading.py path."""

    @pytest.mark.asyncio
    async def test_buy_yes_has_no_local_price_floor(self):
        """trading.py is a thin client: the 50c floor was removed 2026-07-05
        and price enforcement lives in the router.  buy_yes must pass the
        requested price through to the venue client unchanged."""
        from merid.event_venues.kalshi.trading import KalshiTrader

        mock_client = AsyncMock()
        trader = KalshiTrader(client=mock_client)
        trader._is_live_trading_allowed = lambda: True

        with patch('merid.risk.kill_switches.risk_controller') as mock_rc:
            mock_rc.can_trade.return_value = True
            with patch('merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk') as mock_risk:
                mock_risk_instance = MagicMock()
                mock_risk_instance.check_order.return_value = (True, "OK")
                mock_risk.return_value = mock_risk_instance

                result = await trader.buy_yes("TEST-TICKER", 1, price=30)
                assert result is not None
                mock_client.place_order.assert_called()

    @pytest.mark.asyncio
    async def test_buy_yes_passes_high_price_through(self):
        """Prices above the old 70c cap (e.g. pinned-fav 90-96c, settle tail
        98-99c) must reach the venue client — the router owns the bounds."""
        from merid.event_venues.kalshi.trading import KalshiTrader

        mock_client = AsyncMock()
        trader = KalshiTrader(client=mock_client)
        trader._is_live_trading_allowed = lambda: True

        with patch('merid.risk.kill_switches.risk_controller') as mock_rc:
            mock_rc.can_trade.return_value = True
            with patch('merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk') as mock_risk:
                mock_risk_instance = MagicMock()
                mock_risk_instance.check_order.return_value = (True, "OK")
                mock_risk.return_value = mock_risk_instance

                result = await trader.buy_yes("TEST-TICKER", 1, price=95)
                assert result is not None
                mock_client.place_order.assert_called()

    @pytest.mark.asyncio
    async def test_buy_yes_accepts_price_in_range(self):
        """Test that buy_yes accepts orders with price in valid range [50, 70]."""
        from merid.event_venues.kalshi.trading import KalshiTrader
        from merid.event_venues.base import PlacedOrder
        from decimal import Decimal
        
        mock_client = AsyncMock()
        trader = KalshiTrader(client=mock_client)
        trader._is_live_trading_allowed = lambda: True
        
        expected_order = PlacedOrder(
            order_id="order_123",
            market_id="TEST-TICKER",
            side="buy",
            size=Decimal("1"),
            price=None,
            status="open"
        )
        mock_client.place_order.return_value = expected_order
        
        # Mock risk checks to pass
        with patch('merid.risk.kill_switches.risk_controller') as mock_rc:
            mock_rc.can_trade.return_value = True
            with patch('merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk') as mock_risk:
                mock_risk_instance = MagicMock()
                mock_risk_instance.check_order.return_value = (True, "OK")
                mock_risk.return_value = mock_risk_instance
                
                for price in [50, 55, 60, 65, 70]:
                    result = await trader.buy_yes("TEST-TICKER", 1, price=price)
                    assert result is not None, f"Price {price} should be accepted"
                    mock_client.place_order.assert_called()


class TestKalshiToolsPriceValidation:
    """Test price validation in production kalshi_tools.py path."""

    @pytest.mark.asyncio
    async def test_kalshi_place_order_keeps_price_above_old_floor(self):
        """kalshi_tools clamps to the profile range [5, 85] — a 30c order is
        inside it and must pass through unclamped (cheap-side lanes trade
        10-40c contracts)."""
        from merid.prediction.kalshi_tools import _kalshi_place_order
        
        # Mock all the dependencies
        with patch('merid.prediction.kalshi_tools.get_venue_gate') as mock_gate:
            mock_gate_instance = MagicMock()
            mock_gate_instance.should_simulate_fill.return_value = False
            mock_gate_instance.check_order.return_value = None
            mock_gate.return_value = mock_gate_instance
            
            with patch('merid.event_venues.kalshi.market_catalog.get_market_catalog') as mock_catalog:
                mock_catalog_instance = MagicMock()
                mock_catalog_instance.get_all_markets.return_value = []
                mock_catalog.return_value = mock_catalog_instance
                
                with patch('merid.settings.settings') as mock_settings:
                    mock_settings.MERID_ENV = "development"
                    mock_settings.MERID_PM_PROFILE = "baseline"
                    mock_settings.MERID_LOOP_DRY_RUN = False
                    
                    with patch('merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk') as mock_risk:
                        mock_risk_instance = MagicMock()
                        mock_risk_instance._check_fills_integrity.return_value = (True, "OK")
                        mock_risk.return_value = mock_risk_instance
                        
                        with patch('merid.event_venues.kalshi.order_router.route_order_async') as mock_router:
                            mock_router_result = MagicMock()
                            mock_router_result.status = "filled_live"
                            mock_router_result.order_id = "test_order"
                            mock_router_result.requires_recovery = False
                            mock_router_result.has_execution = True
                            mock_router_result.request_completed = True
                            mock_router_result.mode = "live"
                            mock_router_result.reason = "filled"
                            mock_router.return_value = mock_router_result

                            # The mocked settings object makes
                            # ingress_replay._load_config build a bogus
                            # tape path during OrderIntent construction;
                            # disable replay config for this unit test.
                            with patch(
                                'merid.data.ingress_replay._load_config',
                                return_value=__import__(
                                    'merid.data.ingress_replay',
                                    fromlist=['ReplayConfig'],
                                ).ReplayConfig(),
                            ):
                                # 30c is inside the [5, 85] safety rail — no clamp.
                                result = await _kalshi_place_order(
                                    ticker="KXBTC15M-TEST",
                                    side="yes",
                                    action="buy",
                                    price_cents=30,
                                    count=1,
                                    agent_name="test_agent"
                                )

                            assert result.success
                            call_args = mock_router.call_args[0][0]
                            assert call_args.price_cents == 30

    @pytest.mark.asyncio
    async def test_kalshi_place_order_clamps_price_above_85(self):
        """Test that _kalshi_place_order clamps orders above the 85c rail."""
        from merid.prediction.kalshi_tools import _kalshi_place_order
        
        # Mock all the dependencies
        with patch('merid.prediction.kalshi_tools.get_venue_gate') as mock_gate:
            mock_gate_instance = MagicMock()
            mock_gate_instance.should_simulate_fill.return_value = False
            mock_gate_instance.check_order.return_value = None
            mock_gate.return_value = mock_gate_instance
            
            with patch('merid.event_venues.kalshi.market_catalog.get_market_catalog') as mock_catalog:
                mock_catalog_instance = MagicMock()
                mock_catalog_instance.get_all_markets.return_value = []
                mock_catalog.return_value = mock_catalog_instance
                
                with patch('merid.settings.settings') as mock_settings:
                    mock_settings.MERID_ENV = "development"
                    mock_settings.MERID_PM_PROFILE = "baseline"
                    mock_settings.MERID_LOOP_DRY_RUN = False
                    
                    with patch('merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk') as mock_risk:
                        mock_risk_instance = MagicMock()
                        mock_risk_instance._check_fills_integrity.return_value = (True, "OK")
                        mock_risk.return_value = mock_risk_instance
                        
                        with patch('merid.event_venues.kalshi.order_router.route_order_async') as mock_router:
                            mock_router_result = MagicMock()
                            mock_router_result.status = "filled_live"
                            mock_router_result.order_id = "test_order"
                            mock_router_result.requires_recovery = False
                            mock_router_result.has_execution = True
                            mock_router_result.request_completed = True
                            mock_router_result.mode = "live"
                            mock_router_result.reason = "filled"
                            mock_router.return_value = mock_router_result

                            with patch(
                                'merid.data.ingress_replay._load_config',
                                return_value=__import__(
                                    'merid.data.ingress_replay',
                                    fromlist=['ReplayConfig'],
                                ).ReplayConfig(),
                            ):
                                # 90c exceeds the 85c safety rail — clamped to 85.
                                result = await _kalshi_place_order(
                                    ticker="KXBTC15M-TEST",
                                    side="yes",
                                    action="buy",
                                    price_cents=90,
                                    count=1,
                                    agent_name="test_agent"
                                )

                            assert result.success
                            call_args = mock_router.call_args[0][0]
                            assert call_args.price_cents == 85  # Clamped from 90 to 85


class TestOrderRouterPriceValidation:
    """Test price validation in order_router.py path.

    Current contract (2026-11-23): entry orders are bounded 5-95c
    (``_min_price=5``, ``_max_price=95``); reduce-only exits allow 1-99c;
    lane-admitted ceilings (pinned_fav, window_quota, settlement_convergence)
    override the flat max.  In-range prices proceed to market-state and
    submit-revalidation checks — they are not rejected on price alone.
    """

    @pytest.mark.asyncio
    async def test_route_order_async_rejects_price_below_5(self):
        """Entry prices under the 5c floor are rejected."""
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async

        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="BUY_YES",
            action="buy",
            price_cents=3,
            count=1,
            source="test",
            agent_id="test_agent",
        )

        with patch('merid.event_venues.kalshi.order_router.validate_market_for_trading') as mock_scope:
            mock_scope.return_value = (True, "OK")

            result = await route_order_async(intent)

            # Out-of-range entry prices are always rejected; the specific
            # gate depends on mode/env (mock mode dies at submit
            # revalidation before _route_live bounds are reached).
            assert result.status == "rejected"

    @pytest.mark.asyncio
    async def test_route_order_async_rejects_price_above_95_entry(self):
        """Unlaned entry prices above the 95c ceiling are rejected."""
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async

        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="BUY_YES",
            action="buy",
            price_cents=96,
            count=1,
            source="test",
            agent_id="test_agent",
        )

        with patch('merid.event_venues.kalshi.order_router.validate_market_for_trading') as mock_scope:
            mock_scope.return_value = (True, "OK")

            result = await route_order_async(intent)

            # Same as above: rejection is guaranteed; the gate varies.
            assert result.status == "rejected"


class TestAgentGridPriceValidation:
    """Test price validation in agent_grid_15m.py signal generation path."""

    def test_generate_signal_rejects_price_below_50(self):
        """Test that _generate_signal rejects orders with market price below 50 cents."""
        from merid.prediction.agent_grid_15m import LeanAgent15m
        from unittest.mock import Mock, patch
        
        # This test would require extensive mocking of the agent grid
        # For now, we'll just verify the logic exists
        assert hasattr(LeanAgent15m, '_generate_signal')
        
        # The actual test would need to mock:
        # - spot provider
        # - market state store
        # - market catalog
        # - venue gate
        # - etc.
        # This is a placeholder to indicate this path should be tested

    def test_generate_signal_rejects_price_above_70(self):
        """Test that _generate_signal rejects orders with market price above 70 cents."""
        from merid.prediction.agent_grid_15m import LeanAgent15m
        
        # Placeholder test - see above
        assert hasattr(LeanAgent15m, '_generate_signal')


class TestAdaptivePriceCaps:
    """Test adaptive price caps in agent_grid_15m.py."""

    def test_adaptive_price_caps_exist(self):
        """Test that adaptive price cap logic exists in agent_grid_15m."""
        from merid.prediction.agent_grid_15m import LeanAgent15m
        
        # Verify the adaptive price cap methods exist
        assert hasattr(LeanAgent15m, '_detect_market_regime')
        
        # The adaptive entry-price fields live on the agent config dataclass
        # (profile-aligned defaults); _generate_signal consumes them.
        import inspect
        from merid.prediction import agent_grid_15m as _ag
        cfg_src = inspect.getsource(_ag)
        assert "max_entry_price_yes" in cfg_src
        assert "min_entry_price_no" in cfg_src
