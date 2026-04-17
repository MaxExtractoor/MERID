"""Tests for multi_asset/asset_manager.py - Multi-Asset Management."""
import pytest
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from dataclasses import asdict

from multi_asset.asset_manager import (
    AssetClass,
    AssetStatus,
    AssetDefinition,
    AssetData,
    AssetMetrics,
    AssetManager,
)


class TestAssetClass:
    """Test AssetClass enum."""

    def test_equity_class(self):
        """Test equity asset class."""
        assert AssetClass.EQUITY.value == "equity"

    def test_fixed_income_class(self):
        """Test fixed income asset class."""
        assert AssetClass.FIXED_INCOME.value == "fixed_income"

    def test_commodity_class(self):
        """Test commodity asset class."""
        assert AssetClass.COMMODITY.value == "commodity"

    def test_currency_class(self):
        """Test currency asset class."""
        assert AssetClass.CURRENCY.value == "currency"

    def test_crypto_class(self):
        """Test crypto asset class."""
        assert AssetClass.CRYPTO.value == "crypto"

    def test_all_classes(self):
        """Test all asset classes are defined."""
        classes = [c.value for c in AssetClass]
        assert "equity" in classes
        assert "crypto" in classes
        assert "commodity" in classes


class TestAssetStatus:
    """Test AssetStatus enum."""

    def test_active_status(self):
        """Test active status."""
        assert AssetStatus.ACTIVE.value == "active"

    def test_inactive_status(self):
        """Test inactive status."""
        assert AssetStatus.INACTIVE.value == "inactive"

    def test_suspended_status(self):
        """Test suspended status."""
        assert AssetStatus.SUSPENDED.value == "suspended"

    def test_delisted_status(self):
        """Test delisted status."""
        assert AssetStatus.DELISTED.value == "delisted"


class TestAssetDefinition:
    """Test AssetDefinition dataclass."""

    def test_equity_definition(self):
        """Test equity asset definition."""
        asset = AssetDefinition(
            symbol="AAPL",
            name="Apple Inc.",
            asset_class=AssetClass.EQUITY,
            exchange="NASDAQ",
            currency="USD",
            sector="Technology",
            region="US",
            market_cap=3000000000000,
        )
        assert asset.symbol == "AAPL"
        assert asset.asset_class == AssetClass.EQUITY
        assert asset.status == AssetStatus.ACTIVE

    def test_crypto_definition(self):
        """Test crypto asset definition."""
        asset = AssetDefinition(
            symbol="BTC/USD",
            name="Bitcoin",
            asset_class=AssetClass.CRYPTO,
            exchange="Binance",
            currency="USD",
            tick_size=0.01,
            min_order_size=0.0001,
        )
        assert asset.asset_class == AssetClass.CRYPTO
        assert asset.min_order_size == 0.0001

    def test_commodity_definition(self):
        """Test commodity asset definition."""
        asset = AssetDefinition(
            symbol="GC",
            name="Gold Futures",
            asset_class=AssetClass.COMMODITY,
            exchange="COMEX",
            currency="USD",
            multiplier=100,
            tick_size=0.1,
        )
        assert asset.asset_class == AssetClass.COMMODITY
        assert asset.multiplier == 100

    def test_forex_definition(self):
        """Test forex asset definition."""
        asset = AssetDefinition(
            symbol="EUR/USD",
            name="Euro/US Dollar",
            asset_class=AssetClass.CURRENCY,
            exchange="FOREX",
            currency="USD",
            tick_size=0.0001,
        )
        assert asset.asset_class == AssetClass.CURRENCY


class TestAssetData:
    """Test AssetData dataclass."""

    def test_basic_data(self):
        """Test basic asset data."""
        data = AssetData(
            symbol="AAPL",
            timestamp=1000.0,
            price=175.50,
            volume=50000000,
        )
        assert data.symbol == "AAPL"
        assert data.price == 175.50

    def test_full_ohlcv_data(self):
        """Test full OHLCV data."""
        data = AssetData(
            symbol="BTC/USD",
            timestamp=1000.0,
            price=50000.0,
            volume=1000000000,
            bid=49990.0,
            ask=50010.0,
            open=49000.0,
            high=51000.0,
            low=48500.0,
            close=50000.0,
            volatility=0.03,
            beta=1.2,
        )
        assert data.high > data.low
        assert data.bid < data.ask

    def test_data_with_metadata(self):
        """Test asset data with metadata."""
        data = AssetData(
            symbol="GC",
            timestamp=1000.0,
            price=1950.0,
            volume=100000,
            metadata={"contract": "GCM24", "expiry": "2024-06-28"},
        )
        assert data.metadata["contract"] == "GCM24"


class TestAssetMetrics:
    """Test AssetMetrics dataclass."""

    def test_positive_metrics(self):
        """Test positive performance metrics."""
        metrics = AssetMetrics(
            symbol="AAPL",
            asset_class=AssetClass.EQUITY,
            return_1d=0.02,
            return_1w=0.05,
            return_1m=0.10,
            return_ytd=0.25,
            volatility_1m=0.20,
            sharpe_ratio=1.5,
            max_drawdown=0.10,
            beta=1.1,
            correlation_to_market=0.85,
            liquidity_score=0.95,
            risk_score=0.3,
            timestamp=1000.0,
        )
        assert metrics.return_1m > 0
        assert metrics.sharpe_ratio > 1

    def test_negative_metrics(self):
        """Test negative performance metrics."""
        metrics = AssetMetrics(
            symbol="XYZ",
            asset_class=AssetClass.EQUITY,
            return_1d=-0.05,
            return_1w=-0.10,
            return_1m=-0.15,
            return_ytd=-0.30,
            volatility_1m=0.40,
            sharpe_ratio=-0.5,
            max_drawdown=0.35,
            beta=1.5,
            correlation_to_market=0.90,
            liquidity_score=0.50,
            risk_score=0.8,
            timestamp=1000.0,
        )
        assert metrics.return_1m < 0
        assert metrics.risk_score > 0.5


class TestAssetManager:
    """Test AssetManager class."""

    @pytest.fixture
    def manager_config(self):
        """Create manager config."""
        return {
            "max_assets": 100,
            "data_retention_days": 30,
            "update_interval": 60,
        }

    @pytest.fixture
    def asset_manager(self, manager_config):
        """Create asset manager instance."""
        return AssetManager(manager_config)

    def test_manager_creation(self, asset_manager):
        """Test creating manager."""
        assert asset_manager is not None
        assert asset_manager.asset_registry == {}

    def test_register_asset(self, asset_manager):
        """Test registering an asset."""
        asset = AssetDefinition(
            symbol="AAPL",
            name="Apple Inc.",
            asset_class=AssetClass.EQUITY,
            exchange="NASDAQ",
            currency="USD",
        )
        asset_manager.asset_registry["AAPL"] = asset
        
        assert "AAPL" in asset_manager.asset_registry

    def test_register_multiple_assets(self, asset_manager):
        """Test registering multiple assets."""
        assets = [
            AssetDefinition("AAPL", "Apple", AssetClass.EQUITY, "NASDAQ", "USD"),
            AssetDefinition("BTC/USD", "Bitcoin", AssetClass.CRYPTO, "Binance", "USD"),
            AssetDefinition("GC", "Gold", AssetClass.COMMODITY, "COMEX", "USD"),
        ]
        
        for asset in assets:
            asset_manager.asset_registry[asset.symbol] = asset
        
        assert len(asset_manager.asset_registry) == 3

    def test_asset_data_storage(self, asset_manager):
        """Test asset data storage."""
        from collections import deque
        asset_manager.asset_data["AAPL"] = deque(maxlen=1000)
        
        data = AssetData(symbol="AAPL", timestamp=1000.0, price=175.0, volume=1000000)
        asset_manager.asset_data["AAPL"].append(data)
        
        assert len(asset_manager.asset_data["AAPL"]) == 1

    def test_asset_metrics_storage(self, asset_manager):
        """Test asset metrics storage."""
        metrics = AssetMetrics(
            symbol="AAPL",
            asset_class=AssetClass.EQUITY,
            return_1d=0.01,
            return_1w=0.03,
            return_1m=0.08,
            return_ytd=0.20,
            volatility_1m=0.18,
            sharpe_ratio=1.2,
            max_drawdown=0.08,
            beta=1.0,
            correlation_to_market=0.80,
            liquidity_score=0.90,
            risk_score=0.25,
            timestamp=1000.0,
        )
        asset_manager.asset_metrics["AAPL"] = metrics
        
        assert "AAPL" in asset_manager.asset_metrics


class TestCrossAssetAnalysis:
    """Test cross-asset analysis functionality."""

    def test_correlation_matrix(self):
        """Test correlation matrix calculation."""
        np.random.seed(42)
        n = 100
        
        # Generate correlated returns
        btc_returns = np.random.randn(n) * 0.03
        eth_returns = btc_returns * 0.8 + np.random.randn(n) * 0.02
        gold_returns = np.random.randn(n) * 0.01
        
        returns = np.column_stack([btc_returns, eth_returns, gold_returns])
        corr_matrix = np.corrcoef(returns.T)
        
        # BTC-ETH should be highly correlated
        assert corr_matrix[0, 1] > 0.5
        # BTC-Gold should be less correlated
        assert abs(corr_matrix[0, 2]) < 0.5

    def test_portfolio_weights(self):
        """Test portfolio weight calculation."""
        assets = {"BTC": 50000, "ETH": 30000, "GOLD": 20000}
        total = sum(assets.values())
        
        weights = {k: v / total for k, v in assets.items()}
        
        assert weights["BTC"] == 0.5
        assert sum(weights.values()) == pytest.approx(1.0)

    def test_asset_class_allocation(self):
        """Test asset class allocation."""
        portfolio = {
            "AAPL": {"class": "equity", "value": 30000},
            "GOOGL": {"class": "equity", "value": 20000},
            "BTC": {"class": "crypto", "value": 25000},
            "GC": {"class": "commodity", "value": 15000},
            "EUR/USD": {"class": "currency", "value": 10000},
        }
        
        total = sum(p["value"] for p in portfolio.values())
        
        # Calculate class allocations
        class_alloc = {}
        for symbol, data in portfolio.items():
            asset_class = data["class"]
            if asset_class not in class_alloc:
                class_alloc[asset_class] = 0
            class_alloc[asset_class] += data["value"] / total
        
        assert class_alloc["equity"] == 0.5
        assert class_alloc["crypto"] == 0.25

    def test_risk_contribution(self):
        """Test risk contribution by asset."""
        weights = np.array([0.4, 0.3, 0.3])
        volatilities = np.array([0.20, 0.30, 0.15])
        
        # Simplified risk contribution
        weighted_risk = weights * volatilities
        total_risk = np.sum(weighted_risk)
        risk_contrib = weighted_risk / total_risk
        
        assert sum(risk_contrib) == pytest.approx(1.0)


class TestAssetFiltering:
    """Test asset filtering and selection."""

    def test_filter_by_class(self):
        """Test filtering assets by class."""
        assets = [
            {"symbol": "AAPL", "class": AssetClass.EQUITY},
            {"symbol": "BTC", "class": AssetClass.CRYPTO},
            {"symbol": "ETH", "class": AssetClass.CRYPTO},
            {"symbol": "GC", "class": AssetClass.COMMODITY},
        ]
        
        crypto_assets = [a for a in assets if a["class"] == AssetClass.CRYPTO]
        
        assert len(crypto_assets) == 2

    def test_filter_by_liquidity(self):
        """Test filtering assets by liquidity."""
        assets = [
            {"symbol": "AAPL", "liquidity": 0.95},
            {"symbol": "SMALL_CAP", "liquidity": 0.30},
            {"symbol": "BTC", "liquidity": 0.90},
            {"symbol": "MICRO_CAP", "liquidity": 0.15},
        ]
        
        min_liquidity = 0.50
        liquid_assets = [a for a in assets if a["liquidity"] >= min_liquidity]
        
        assert len(liquid_assets) == 2

    def test_filter_by_volatility(self):
        """Test filtering assets by volatility."""
        assets = [
            {"symbol": "AAPL", "volatility": 0.20},
            {"symbol": "BTC", "volatility": 0.60},
            {"symbol": "GC", "volatility": 0.15},
            {"symbol": "MEME_COIN", "volatility": 1.50},
        ]
        
        max_volatility = 0.50
        low_vol_assets = [a for a in assets if a["volatility"] <= max_volatility]
        
        assert len(low_vol_assets) == 2
        assert "BTC" not in [a["symbol"] for a in low_vol_assets]

    def test_filter_by_region(self):
        """Test filtering assets by region."""
        assets = [
            {"symbol": "AAPL", "region": "US"},
            {"symbol": "TSM", "region": "ASIA"},
            {"symbol": "ASML", "region": "EU"},
            {"symbol": "GOOGL", "region": "US"},
        ]
        
        us_assets = [a for a in assets if a["region"] == "US"]
        
        assert len(us_assets) == 2
