"""Tests for portfolio/manager.py."""
import pytest
import time
from unittest.mock import Mock, patch
from portfolio.manager import (
    AllocationStrategy, PositionSizingMethod, PortfolioAsset, RebalanceOrder,
    PortfolioSnapshot, PortfolioManager, get_portfolio_manager, _portfolio_manager
)


class TestAllocationStrategy:
    """Test AllocationStrategy enum."""

    def test_strategy_values(self):
        """Test allocation strategy enum values."""
        assert AllocationStrategy.EQUAL_WEIGHT.value == "equal_weight"
        assert AllocationStrategy.MARKET_CAP.value == "market_cap"
        assert AllocationStrategy.RISK_PARITY.value == "risk_parity"
        assert AllocationStrategy.MOMENTUM.value == "momentum"
        assert AllocationStrategy.CUSTOM.value == "custom"


class TestPositionSizingMethod:
    """Test PositionSizingMethod enum."""

    def test_sizing_method_values(self):
        """Test position sizing method enum values."""
        assert PositionSizingMethod.FIXED_AMOUNT.value == "fixed_amount"
        assert PositionSizingMethod.FIXED_PERCENT.value == "fixed_percent"
        assert PositionSizingMethod.KELLY_CRITERION.value == "kelly_criterion"
        assert PositionSizingMethod.VOLATILITY_ADJUSTED.value == "volatility_adjusted"
        assert PositionSizingMethod.ATR_BASED.value == "atr_based"


class TestPortfolioAsset:
    """Test PortfolioAsset dataclass."""

    def test_creation(self):
        """Test PortfolioAsset creation."""
        asset = PortfolioAsset(
            symbol="BTC/USD",
            quantity=1.5,
            avg_cost=50000.0,
            current_price=55000.0
        )
        assert asset.symbol == "BTC/USD"
        assert asset.quantity == 1.5
        assert asset.avg_cost == 50000.0
        assert asset.current_price == 55000.0

    def test_to_dict(self):
        """Test PortfolioAsset to_dict."""
        asset = PortfolioAsset(
            symbol="ETH/USD",
            quantity=2.0,
            avg_cost=50000.0,
            current_price=55000.0,
            target_weight=0.5,
            current_weight=0.55,
            pnl=10000.0,
            pnl_pct=10.0
        )
        d = asset.to_dict()
        assert d["symbol"] == "ETH/USD"
        assert d["quantity"] == 2.0
        assert d["market_value"] == 110000.0
        assert d["pnl"] == 10000.0


class TestRebalanceOrder:
    """Test RebalanceOrder dataclass."""

    def test_creation(self):
        """Test RebalanceOrder creation."""
        order = RebalanceOrder(
            symbol="BTC/USD",
            action="buy",
            quantity=0.5,
            current_weight=0.45,
            target_weight=0.5,
            weight_diff=0.05,
            estimated_value=5000.0
        )
        assert order.symbol == "BTC/USD"
        assert order.action == "buy"
        assert order.weight_diff == 0.05


class TestPortfolioManagerInitialization:
    """Test PortfolioManager initialization."""

    def test_default_initialization(self):
        """Test default portfolio manager initialization."""
        manager = PortfolioManager()
        assert manager._initial_capital == 100000.0
        assert manager._cash == 100000.0
        assert manager._assets == {}
        assert manager._allocation_strategy == AllocationStrategy.EQUAL_WEIGHT

    def test_custom_initial_capital(self):
        """Test portfolio manager with custom initial capital."""
        manager = PortfolioManager(initial_capital=50000.0)
        assert manager._initial_capital == 50000.0
        assert manager._cash == 50000.0


class TestPortfolioManagerProperties:
    """Test PortfolioManager properties."""

    def test_total_value_empty(self):
        """Test total value with empty portfolio."""
        manager = PortfolioManager(initial_capital=100000.0)
        assert manager.total_value == 100000.0

    def test_total_value_with_positions(self):
        """Test total value with positions."""
        manager = PortfolioManager(initial_capital=100000.0)
        manager.add_position("BTC/USD", 1.0, 50000.0)
        assert manager.total_value == 100000.0  # Cash + invested

    def test_invested_value(self):
        """Test invested value calculation."""
        manager = PortfolioManager(initial_capital=100000.0)
        manager.add_position("BTC/USD", 1.0, 50000.0)
        assert manager.invested_value == 50000.0

    def test_pnl_calculation(self):
        """Test P&L calculation."""
        manager = PortfolioManager(initial_capital=100000.0)
        manager.add_position("BTC/USD", 1.0, 50000.0)
        manager.update_price("BTC/USD", 55000.0)
        assert manager.pnl == 5000.0
        assert manager.pnl_pct == 5.0


class TestPortfolioManagerPositionManagement:
    """Test PortfolioManager position management."""

    def test_add_new_position(self):
        """Test adding a new position."""
        manager = PortfolioManager(initial_capital=100000.0)
        manager.add_position("BTC/USD", 1.0, 50000.0)
        
        assert "BTC/USD" in manager._assets
        assert manager._assets["BTC/USD"].quantity == 1.0
        assert manager._assets["BTC/USD"].avg_cost == 50000.0
        assert manager._cash == 50000.0

    def test_add_to_existing_position(self):
        """Test adding to existing position."""
        manager = PortfolioManager(initial_capital=100000.0)
        manager.add_position("BTC/USD", 1.0, 50000.0)
        manager.add_position("BTC/USD", 0.5, 55000.0)
        
        asset = manager._assets["BTC/USD"]
        assert asset.quantity == 1.5
        # Avg cost should be weighted average
        assert asset.avg_cost == (50000.0 + 27500.0) / 1.5

    def test_remove_position(self):
        """Test removing from position."""
        manager = PortfolioManager(initial_capital=100000.0)
        manager.add_position("BTC/USD", 1.0, 50000.0)
        pnl = manager.remove_position("BTC/USD", 0.5, 55000.0)
        
        assert pnl == 2500.0  # (55000 - 50000) * 0.5
        assert manager._assets["BTC/USD"].quantity == 0.5
        assert manager._cash == 50000.0 + 27500.0

    def test_remove_entire_position(self):
        """Test removing entire position."""
        manager = PortfolioManager(initial_capital=100000.0)
        manager.add_position("BTC/USD", 1.0, 50000.0)
        manager.remove_position("BTC/USD", 1.0, 55000.0)
        
        assert "BTC/USD" not in manager._assets

    def test_remove_nonexistent_position(self):
        """Test removing from non-existent position."""
        manager = PortfolioManager(initial_capital=100000.0)
        pnl = manager.remove_position("BTC/USD", 1.0, 50000.0)
        
        assert pnl == 0.0


class TestPortfolioManagerPriceUpdates:
    """Test PortfolioManager price updates."""

    def test_update_price(self):
        """Test updating asset price."""
        manager = PortfolioManager(initial_capital=100000.0)
        manager.add_position("BTC/USD", 1.0, 50000.0)
        manager.update_price("BTC/USD", 55000.0)
        
        asset = manager._assets["BTC/USD"]
        assert asset.current_price == 55000.0
        assert asset.pnl == 5000.0
        assert asset.pnl_pct == 10.0

    def test_update_price_nonexistent(self):
        """Test updating price for non-existent asset."""
        manager = PortfolioManager(initial_capital=100000.0)
        manager.update_price("BTC/USD", 55000.0)  # Should not raise


class TestPortfolioManagerTargetWeights:
    """Test PortfolioManager target weights."""

    def test_set_target_weights(self):
        """Test setting target weights."""
        manager = PortfolioManager(initial_capital=100000.0)
        weights = {"BTC/USD": 0.6, "ETH/USD": 0.4}
        manager.set_target_weights(weights)
        
        assert manager._target_weights["BTC/USD"] == 0.6
        assert manager._target_weights["ETH/USD"] == 0.4

    def test_set_target_weights_normalization(self):
        """Test target weights normalization."""
        manager = PortfolioManager(initial_capital=100000.0)
        weights = {"BTC/USD": 60, "ETH/USD": 40}  # Sum = 100, not 1
        manager.set_target_weights(weights)
        
        assert manager._target_weights["BTC/USD"] == 0.6
        assert manager._target_weights["ETH/USD"] == 0.4


class TestPortfolioManagerRebalancing:
    """Test PortfolioManager rebalancing."""

    def test_calculate_rebalance_orders_no_targets(self):
        """Test rebalancing with no target weights."""
        manager = PortfolioManager(initial_capital=100000.0)
        orders = manager.calculate_rebalance_orders()
        assert orders == []

    def test_calculate_rebalance_orders_below_threshold(self):
        """Test rebalancing when drift is below threshold."""
        manager = PortfolioManager(initial_capital=100000.0)
        # Set up 2 assets at 50%/50% weights
        manager.add_position("BTC/USD", 1.0, 50000.0)  # 50% weight ($50k)
        manager.add_position("ETH/USD", 1.0, 50000.0)  # 50% weight ($50k)
        # Target: BTC=0.52 (2% drift), ETH=0.48 (2% drift) - sums to 1.0
        manager.set_target_weights({"BTC/USD": 0.52, "ETH/USD": 0.48})

        orders = manager.calculate_rebalance_orders()
        # Both drifts are 2%, below 5% threshold - no orders expected
        assert orders == []

    def test_calculate_rebalance_orders_buy(self):
        """Test rebalancing buy order."""
        manager = PortfolioManager(initial_capital=100000.0)
        manager.add_position("BTC/USD", 0.5, 50000.0)  # 25% weight
        manager._cash = 75000.0  # 75% cash
        # Set up weights that sum to 1.0 with a second asset
        manager.set_target_weights({"BTC/USD": 0.5, "ETH/USD": 0.5})  # Target 50% BTC

        with patch.object(manager, '_get_current_price', return_value=50000.0):
            orders = manager.calculate_rebalance_orders()

        btc_orders = [o for o in orders if o.symbol == "BTC/USD"]
        assert len(btc_orders) == 1
        assert btc_orders[0].action == "buy"
        assert btc_orders[0].weight_diff > 0

    def test_calculate_rebalance_orders_sell(self):
        """Test rebalancing sell order."""
        manager = PortfolioManager(initial_capital=100000.0)
        manager.add_position("BTC/USD", 1.5, 50000.0)  # 75% weight ($75k)
        manager._cash = 25000.0  # 25% cash
        # Set up weights that sum to 1.0 with a second asset to hold remaining
        manager.set_target_weights({"BTC/USD": 0.5, "ETH/USD": 0.5})  # Target 50% BTC

        with patch.object(manager, '_get_current_price', return_value=50000.0):
            orders = manager.calculate_rebalance_orders()

        btc_orders = [o for o in orders if o.symbol == "BTC/USD"]
        assert len(btc_orders) == 1
        assert btc_orders[0].action == "sell"
        assert btc_orders[0].weight_diff < 0


class TestPortfolioManagerPositionSizing:
    """Test PortfolioManager position sizing."""

    def test_fixed_amount_sizing(self):
        """Test fixed amount position sizing."""
        manager = PortfolioManager(initial_capital=100000.0)
        manager._sizing_method = PositionSizingMethod.FIXED_AMOUNT
        size = manager.calculate_position_size("BTC/USD", 50000.0, 48000.0)
        
        assert size == 1000 / 50000.0  # $1000 per trade

    def test_fixed_percent_sizing(self):
        """Test fixed percent position sizing."""
        manager = PortfolioManager(initial_capital=100000.0)
        manager._sizing_method = PositionSizingMethod.FIXED_PERCENT
        size = manager.calculate_position_size("BTC/USD", 50000.0, 48000.0)
        
        assert size == 10000 / 50000.0  # 10% of portfolio

    def test_volatility_adjusted_sizing(self):
        """Test volatility adjusted position sizing."""
        manager = PortfolioManager(initial_capital=100000.0)
        manager._sizing_method = PositionSizingMethod.VOLATILITY_ADJUSTED
        size = manager.calculate_position_size("BTC/USD", 50000.0, 48000.0, risk_per_trade=0.02)
        
        # Risk amount = 2% of 100k = 2000, risk per unit = 2000, size = 1
        expected_size = (100000.0 * 0.02) / 2000.0
        assert size == expected_size

    def test_kelly_criterion_sizing(self):
        """Test Kelly criterion position sizing."""
        manager = PortfolioManager(initial_capital=100000.0)
        manager._sizing_method = PositionSizingMethod.KELLY_CRITERION
        size = manager.calculate_position_size("BTC/USD", 50000.0, 48000.0)
        
        # Kelly fraction should be between 0 and 0.25
        assert size > 0


class TestPortfolioManagerSnapshots:
    """Test PortfolioManager snapshots."""

    def test_take_snapshot(self):
        """Test taking portfolio snapshot."""
        manager = PortfolioManager(initial_capital=100000.0)
        manager.add_position("BTC/USD", 1.0, 50000.0)
        snapshot = manager.take_snapshot()
        
        assert isinstance(snapshot, PortfolioSnapshot)
        assert snapshot.total_value == 100000.0
        assert snapshot.cash == 50000.0
        assert snapshot.invested == 50000.0
        assert len(manager._snapshots) == 1

    def test_get_value_history(self):
        """Test getting value history."""
        manager = PortfolioManager(initial_capital=100000.0)
        manager.take_snapshot()
        history = manager.get_value_history()
        
        assert len(history) == 1
        assert history[0]["total_value"] == 100000.0


class TestPortfolioManagerSummary:
    """Test PortfolioManager summary methods."""

    def test_get_summary(self):
        """Test getting portfolio summary."""
        manager = PortfolioManager(initial_capital=100000.0)
        manager.add_position("BTC/USD", 1.0, 50000.0)
        summary = manager.get_summary()
        
        assert summary["total_value"] == 100000.0
        assert summary["cash"] == 50000.0
        assert summary["invested"] == 50000.0
        assert summary["num_positions"] == 1
        assert summary["allocation_strategy"] == "equal_weight"

    def test_get_holdings(self):
        """Test getting holdings."""
        manager = PortfolioManager(initial_capital=100000.0)
        manager.add_position("BTC/USD", 1.0, 50000.0)
        holdings = manager.get_holdings()
        
        assert len(holdings) == 1
        assert holdings[0]["symbol"] == "BTC/USD"

    def test_get_allocation(self):
        """Test getting allocation."""
        manager = PortfolioManager(initial_capital=100000.0)
        manager.add_position("BTC/USD", 1.0, 50000.0)
        manager.set_target_weights({"BTC/USD": 0.6, "ETH/USD": 0.4})
        allocation = manager.get_allocation()
        
        assert "BTC/USD" in allocation
        assert "ETH/USD" in allocation  # Target but not held
        assert allocation["BTC/USD"]["current_weight"] == 0.5
        assert allocation["ETH/USD"]["current_weight"] == 0


class TestGetPortfolioManager:
    """Test get_portfolio_manager function."""

    def setup_method(self):
        """Reset singleton before each test."""
        global _portfolio_manager
        import portfolio.manager as pm
        pm._portfolio_manager = None

    def test_singleton(self):
        """Test get_portfolio_manager returns singleton."""
        manager1 = get_portfolio_manager()
        manager2 = get_portfolio_manager()
        assert manager1 is manager2
