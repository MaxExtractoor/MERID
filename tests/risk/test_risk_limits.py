"""Risk limit enforcement tests for MERID trading system.

Tests daily loss limits, per-symbol exposure caps, and notional limits.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal

from merid.execution.router import ExecutionRouter, TraderIdentity, TradeIntent
from merid.execution.base import TradeResult, TradeSideLiteral
from merid.execution.portfolio import PortfolioAggregator
from trading.adapters.base import TradeRequest
from trading.config.runtime_config import (
    GlobalTradingMode,
    TradingRuntimeConfig,
    VenueMode,
)
from trading.guards.trading_guard import (
    TradingGuard,
    TradingGuardConfig,
    GuardDecision,
    GuardDecisionStatus,
)


@pytest.fixture
def trader():
    return TraderIdentity(trader_type="agent", trader_id="test-agent-001")


@pytest.fixture
def mock_executor():
    executor = MagicMock()
    executor.execute_trade = AsyncMock(return_value=TradeResult(
        success=True,
        venue="kalshi",
        symbol="BTC-USD",
        side="buy",
        size=1.0,
        price=50000.0,
    ))
    return executor


@pytest.fixture
def router(mock_executor):
    return ExecutionRouter(executors={"kalshi": mock_executor})


@pytest.fixture
def portfolio():
    """Create fresh PortfolioAggregator for each test."""
    return PortfolioAggregator()


@pytest.fixture
def test_venue_config():
    """Create a valid test venue configuration."""
    config = TradingRuntimeConfig()
    # Set live mode and disable spectator so tests can get ALLOW decisions
    config.update_global_mode(mode="live", spectator_mode=False, allow_live_trades=True)
    config.upsert_venue(
        "test_venue",
        {
            "label": "Test Venue",
            "mode": "live",
            "max_notional_usd": 50000.0,
        },
    )
    return config


class TestDailyLossLimits:
    """Test daily loss limit enforcement."""

    def test_blocks_order_when_daily_loss_exceeded(self, portfolio, test_venue_config):
        """Verify orders blocked when daily loss limit hit."""
        config = TradingGuardConfig(
            allow_live_trades=True,
            max_daily_loss_usd=10000.0,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        # Simulate a big loss
        portfolio.record_trade_pnl(-15000.0)

        request = TradeRequest(
            venue="test_venue",
            symbol="BTC-USD",
            side="buy",
            quantity=1.0,
            price=50000.0,
            notional_usd=50000.0,
            live=True,
            metadata={},
        )

        decision = guard.evaluate(request, vpn_connected=True, portfolio_aggregator=portfolio)

        assert decision.status == GuardDecisionStatus.BLOCK
        assert "Daily loss limit exceeded" in decision.reason
        assert decision.metadata["daily_loss"] == -15000.0
        assert decision.metadata["max_daily_loss"] == 10000.0

    def test_allows_order_when_daily_loss_below_limit(self, portfolio, test_venue_config):
        """Verify orders allowed when under daily loss limit."""
        config = TradingGuardConfig(
            allow_live_trades=True,
            max_daily_loss_usd=10000.0,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        # Small loss, still within limit
        portfolio.record_trade_pnl(-5000.0)

        request = TradeRequest(
            venue="test_venue",
            symbol="BTC-USD",
            side="buy",
            quantity=0.1,
            price=50000.0,
            notional_usd=5000.0,
            live=True,
            metadata={},
        )

        decision = guard.evaluate(request, vpn_connected=True, portfolio_aggregator=portfolio)

        assert decision.status == GuardDecisionStatus.ALLOW

    def test_allows_order_when_daily_pnl_positive(self, portfolio, test_venue_config):
        """Verify orders allowed when daily P&L is positive."""
        config = TradingGuardConfig(
            allow_live_trades=True,
            max_daily_loss_usd=10000.0,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        # Profitable day
        portfolio.record_trade_pnl(5000.0)

        request = TradeRequest(
            venue="test_venue",
            symbol="BTC-USD",
            side="buy",
            quantity=0.1,
            price=50000.0,
            notional_usd=5000.0,
            live=True,
            metadata={},
        )

        decision = guard.evaluate(request, vpn_connected=True, portfolio_aggregator=portfolio)

        assert decision.status == GuardDecisionStatus.ALLOW


class TestPerSymbolLimits:
    """Test per-symbol exposure caps."""

    def test_blocks_order_when_symbol_limit_exceeded(self, portfolio, test_venue_config):
        """Verify order blocked when per-symbol exposure exceeds cap."""
        config = TradingGuardConfig(
            allow_live_trades=True,
            max_per_symbol_exposure_usd=10000.0,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        # Already have exposure in BTC
        portfolio.update_symbol_exposure("BTC-USD", 8000.0)

        request = TradeRequest(
            venue="test_venue",
            symbol="BTC-USD",
            side="buy",
            quantity=0.1,
            price=50000.0,
            notional_usd=5000.0,
            live=True,
            metadata={},
        )

        decision = guard.evaluate(request, vpn_connected=True, portfolio_aggregator=portfolio)

        assert decision.status == GuardDecisionStatus.BLOCK
        assert "Per-symbol exposure limit exceeded" in decision.reason
        assert decision.metadata["symbol_exposure"] == 8000.0
        assert decision.metadata["max_symbol_exposure"] == 10000.0

    def test_allows_order_when_symbol_within_limit(self, portfolio, test_venue_config):
        """Verify order allowed when per-symbol exposure within cap."""
        config = TradingGuardConfig(
            allow_live_trades=True,
            max_per_symbol_exposure_usd=10000.0,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        # Some exposure but still room
        portfolio.update_symbol_exposure("BTC-USD", 3000.0)

        request = TradeRequest(
            venue="test_venue",
            symbol="BTC-USD",
            side="buy",
            quantity=0.1,
            price=50000.0,
            notional_usd=5000.0,
            live=True,
            metadata={},
        )

        decision = guard.evaluate(request, vpn_connected=True, portfolio_aggregator=portfolio)

        assert decision.status == GuardDecisionStatus.ALLOW

    def test_symbol_exposure_tracked_separately(self, portfolio, test_venue_config):
        """Verify each symbol's exposure is tracked independently."""
        config = TradingGuardConfig(
            allow_live_trades=True,
            max_per_symbol_exposure_usd=10000.0,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        # Heavy exposure in BTC
        portfolio.update_symbol_exposure("BTC-USD", 15000.0)

        # But ETH should still be allowed
        request = TradeRequest(
            venue="test_venue",
            symbol="ETH-USD",
            side="buy",
            quantity=1.0,
            price=3000.0,
            notional_usd=3000.0,
            live=True,
            metadata={},
        )

        decision = guard.evaluate(request, vpn_connected=True, portfolio_aggregator=portfolio)

        assert decision.status == GuardDecisionStatus.ALLOW


class TestNotionalLimits:
    """Test max notional USD limits."""

    def test_allows_order_within_notional_limit(self, test_venue_config):
        """Verify order allowed when within notional limit."""
        config = TradingGuardConfig(
            max_notional_usd=100000.0,
            allow_live_trades=True,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        request = TradeRequest(
            venue="test_venue",
            symbol="BTC-USD",
            side="buy",
            quantity=0.1,
            price=50000.0,
            notional_usd=5000.0,
            live=True,
            metadata={},
        )

        decision = guard.evaluate(request, vpn_connected=True)

        assert decision.status == GuardDecisionStatus.ALLOW


class TestMaxOpenOrders:
    """Test max open orders limit."""

    def test_blocks_order_when_max_open_orders_reached(self, portfolio, test_venue_config):
        """Verify order blocked when max open orders limit reached."""
        config = TradingGuardConfig(
            allow_live_trades=True,
            max_open_orders=3,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        # At limit
        for _ in range(3):
            portfolio.increment_open_orders()

        request = TradeRequest(
            venue="test_venue",
            symbol="BTC-USD",
            side="buy",
            quantity=0.1,
            price=50000.0,
            notional_usd=5000.0,
            live=True,
            metadata={},
        )

        decision = guard.evaluate(request, vpn_connected=True, portfolio_aggregator=portfolio)

        assert decision.status == GuardDecisionStatus.BLOCK
        assert "Max open orders limit reached" in decision.reason
        assert decision.metadata["open_orders"] == 3
        assert decision.metadata["max_open_orders"] == 3

    def test_allows_order_when_under_max_open_orders(self, portfolio, test_venue_config):
        """Verify order allowed when under max open orders limit."""
        config = TradingGuardConfig(
            allow_live_trades=True,
            max_open_orders=10,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        # Some orders but under limit
        for _ in range(5):
            portfolio.increment_open_orders()

        request = TradeRequest(
            venue="test_venue",
            symbol="BTC-USD",
            side="buy",
            quantity=0.1,
            price=50000.0,
            notional_usd=5000.0,
            live=True,
            metadata={},
        )

        decision = guard.evaluate(request, vpn_connected=True, portfolio_aggregator=portfolio)

        assert decision.status == GuardDecisionStatus.ALLOW


class TestKillSwitchAndLockdown:
    """Test kill switch and lockdown interaction with TradingGuard."""

    def test_guard_blocks_when_trading_suite_disabled(self, test_venue_config):
        """Verify guard blocks when trading suite is disabled."""
        config = TradingGuardConfig(
            enable_trading_suite=False,
            allow_live_trades=True,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        request = TradeRequest(
            venue="test_venue",
            symbol="BTC-USD",
            side="buy",
            quantity=0.1,
            price=50000.0,
            notional_usd=5000.0,
            live=True,
            metadata={},
        )

        decision = guard.evaluate(request, vpn_connected=True)

        assert decision.status == GuardDecisionStatus.BLOCK
        assert "Trading suite disabled" in decision.reason

    def test_guard_blocks_when_live_trades_disabled(self, test_venue_config):
        """Verify guard blocks when live trading is disabled."""
        config = TradingGuardConfig(
            allow_live_trades=False,
            max_notional_usd=100000.0,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        request = TradeRequest(
            venue="test_venue",
            symbol="BTC-USD",
            side="buy",
            quantity=1.0,
            price=50000.0,
            notional_usd=1000.0,
            live=True,
            metadata={},
        )

        decision = guard.evaluate(request, vpn_connected=True)

        assert decision.status == GuardDecisionStatus.REQUIRE_CONFIRMATION
        assert "Live trades disabled" in decision.reason

    def test_guard_simulates_when_global_mode_offline(self, test_venue_config):
        """Verify guard simulates when global mode is OFFLINE."""
        test_venue_config.update_global_mode(mode="offline")

        config = TradingGuardConfig(
            allow_live_trades=True,
            max_notional_usd=100000.0,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        request = TradeRequest(
            venue="test_venue",
            symbol="BTC-USD",
            side="buy",
            quantity=0.1,
            price=50000.0,
            notional_usd=5000.0,
            live=True,
            metadata={},
        )

        decision = guard.evaluate(request, vpn_connected=True)

        assert decision.status == GuardDecisionStatus.SIMULATE
        assert "mock" in decision.reason.lower()

    def test_guard_blocks_disabled_venue(self, test_venue_config):
        """Verify guard blocks orders to disabled venues."""
        test_venue_config.upsert_venue(
            "disabled_venue",
            {"label": "Disabled", "mode": "disabled"},
        )

        config = TradingGuardConfig(
            allow_live_trades=True,
            max_notional_usd=100000.0,
        )
        guard = TradingGuard(config=config, runtime_config=test_venue_config)

        request = TradeRequest(
            venue="disabled_venue",
            symbol="BTC-USD",
            side="buy",
            quantity=0.1,
            price=50000.0,
            notional_usd=5000.0,
            live=True,
            metadata={},
        )

        decision = guard.evaluate(request, vpn_connected=True)

        assert decision.status == GuardDecisionStatus.BLOCK
        assert "disabled" in decision.reason


class TestPortfolioAggregator:
    """Test PortfolioAggregator tracking functionality."""

    def test_daily_pnl_tracking(self):
        """Verify daily P&L is tracked correctly."""
        portfolio = PortfolioAggregator()

        portfolio.record_trade_pnl(1000.0)
        portfolio.record_trade_pnl(-500.0)
        portfolio.record_trade_pnl(2000.0)

        assert portfolio.daily_pnl == 2500.0

    def test_daily_pnl_reset(self):
        """Verify daily P&L reset works."""
        portfolio = PortfolioAggregator()

        portfolio.record_trade_pnl(1000.0)
        portfolio.reset_daily_pnl()

        assert portfolio.daily_pnl == 0.0

    def test_symbol_exposure_tracking(self):
        """Verify symbol exposure is tracked correctly."""
        portfolio = PortfolioAggregator()

        portfolio.update_symbol_exposure("BTC-USD", 5000.0)
        portfolio.update_symbol_exposure("BTC-USD", 3000.0)
        portfolio.update_symbol_exposure("ETH-USD", 4000.0)

        assert portfolio.get_symbol_exposure("BTC-USD") == 8000.0
        assert portfolio.get_symbol_exposure("ETH-USD") == 4000.0
        assert portfolio.get_symbol_exposure("SOL-USD") == 0.0

    def test_open_orders_tracking(self):
        """Verify open orders counter works correctly."""
        portfolio = PortfolioAggregator()

        for _ in range(5):
            portfolio.increment_open_orders()

        assert portfolio.open_orders_count == 5

        portfolio.decrement_open_orders()
        portfolio.decrement_open_orders()

        assert portfolio.open_orders_count == 3

        # Should not go below 0
        for _ in range(10):
            portfolio.decrement_open_orders()

        assert portfolio.open_orders_count == 0
