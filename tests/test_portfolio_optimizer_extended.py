"""Extended tests for risk/portfolio_optimizer.py - Portfolio Optimizer Coverage."""
import pytest
import asyncio
import time
import numpy as np
from unittest.mock import patch, MagicMock, AsyncMock
from dataclasses import asdict

from risk.portfolio_optimizer import (
    Asset,
    PortfolioMetrics,
    OptimizationResult,
    PortfolioOptimizer,
    SCIPY_AVAILABLE,
    CVXPY_AVAILABLE,
)


class TestAssetDataclass:
    """Test Asset dataclass."""

    def test_asset_creation_minimal(self):
        """Test creating asset with minimal fields."""
        asset = Asset(
            symbol="BTC",
            expected_return=0.15,
            volatility=0.30
        )
        assert asset.symbol == "BTC"
        assert asset.expected_return == 0.15
        assert asset.volatility == 0.30
        assert asset.weight == 0.0
        assert asset.min_weight == 0.0
        assert asset.max_weight == 1.0

    def test_asset_creation_full(self):
        """Test creating asset with all fields."""
        asset = Asset(
            symbol="ETH",
            expected_return=0.20,
            volatility=0.40,
            weight=0.25,
            min_weight=0.05,
            max_weight=0.50,
            asset_class="crypto",
            metadata={"sector": "defi"}
        )
        assert asset.symbol == "ETH"
        assert asset.weight == 0.25
        assert asset.asset_class == "crypto"
        assert asset.metadata["sector"] == "defi"


class TestPortfolioMetrics:
    """Test PortfolioMetrics dataclass."""

    def test_metrics_creation(self):
        """Test creating portfolio metrics."""
        metrics = PortfolioMetrics(
            expected_return=0.12,
            volatility=0.18,
            sharpe_ratio=0.55,
            sortino_ratio=0.70,
            max_drawdown=0.15,
            var_95=-0.10,
            var_99=-0.15,
            expected_shortfall_95=-0.12,
            diversification_ratio=1.2,
            concentration_risk=0.25
        )
        assert metrics.expected_return == 0.12
        assert metrics.sharpe_ratio == 0.55
        assert metrics.turnover == 0.0

    def test_metrics_with_turnover(self):
        """Test metrics with turnover."""
        metrics = PortfolioMetrics(
            expected_return=0.10,
            volatility=0.15,
            sharpe_ratio=0.5,
            sortino_ratio=0.6,
            max_drawdown=0.10,
            var_95=-0.08,
            var_99=-0.12,
            expected_shortfall_95=-0.10,
            diversification_ratio=1.1,
            concentration_risk=0.20,
            turnover=0.15
        )
        assert metrics.turnover == 0.15


class TestOptimizationResult:
    """Test OptimizationResult dataclass."""

    def test_result_creation(self):
        """Test creating optimization result."""
        assets = [
            Asset("BTC", 0.15, 0.30),
            Asset("ETH", 0.20, 0.40)
        ]
        metrics = PortfolioMetrics(
            expected_return=0.17,
            volatility=0.32,
            sharpe_ratio=0.47,
            sortino_ratio=0.55,
            max_drawdown=0.12,
            var_95=-0.08,
            var_99=-0.12,
            expected_shortfall_95=-0.10,
            diversification_ratio=1.1,
            concentration_risk=0.5
        )
        result = OptimizationResult(
            optimization_id="opt_001",
            optimization_method="mean_variance",
            assets=assets,
            weights={"BTC": 0.6, "ETH": 0.4},
            portfolio_metrics=metrics,
            optimization_time=0.5,
            convergence=True,
            objective_value=0.47,
            constraints=["weight_sum", "min_weight"]
        )
        assert result.optimization_id == "opt_001"
        assert result.convergence is True
        assert result.weights["BTC"] == 0.6


class TestPortfolioOptimizerInit:
    """Test PortfolioOptimizer initialization."""

    def test_initialization_default(self):
        """Test optimizer initialization with defaults."""
        optimizer = PortfolioOptimizer(config={})
        
        assert optimizer.risk_free_rate == 0.02
        assert "mean_variance" in optimizer.optimization_methods
        assert optimizer.default_constraints["weight_sum"] == 1.0

    def test_initialization_custom_config(self):
        """Test optimizer with custom config."""
        config = {
            "risk_free_rate": 0.05,
            "optimization_methods": ["mean_variance", "min_variance"],
            "us_compliance": {
                "position_limits": False,
                "audit_optimization": False
            }
        }
        optimizer = PortfolioOptimizer(config=config)
        
        assert optimizer.risk_free_rate == 0.05
        assert len(optimizer.optimization_methods) == 2
        assert optimizer.us_compliance["position_limits"] is False


class TestPortfolioOptimizerAssets:
    """Test asset management methods."""

    @pytest.fixture
    def optimizer(self):
        return PortfolioOptimizer(config={})

    def test_add_asset(self, optimizer):
        """Test adding asset."""
        asset = Asset("BTC", 0.15, 0.30)
        result = optimizer.add_asset(asset)
        
        assert result is True
        assert "BTC" in optimizer.assets

    def test_add_multiple_assets(self, optimizer):
        """Test adding multiple assets."""
        optimizer.add_asset(Asset("BTC", 0.15, 0.30))
        optimizer.add_asset(Asset("ETH", 0.20, 0.40))
        optimizer.add_asset(Asset("SOL", 0.25, 0.50))
        
        assert len(optimizer.assets) == 3

    def test_get_asset_universe(self, optimizer):
        """Test getting asset universe."""
        optimizer.add_asset(Asset("BTC", 0.15, 0.30))
        universe = optimizer.get_asset_universe()
        
        assert "BTC" in universe
        assert universe is not optimizer.assets  # Should be a copy


class TestCorrelationMatrix:
    """Test correlation matrix methods."""

    @pytest.fixture
    def optimizer_with_assets(self):
        optimizer = PortfolioOptimizer(config={})
        optimizer.add_asset(Asset("BTC", 0.15, 0.30))
        optimizer.add_asset(Asset("ETH", 0.20, 0.40))
        return optimizer

    def test_update_correlation_matrix(self, optimizer_with_assets):
        """Test updating correlation matrix."""
        corr_matrix = np.array([
            [1.0, 0.7],
            [0.7, 1.0]
        ])
        result = optimizer_with_assets.update_correlation_matrix(corr_matrix)
        
        assert result is True
        assert optimizer_with_assets.covariance_matrix is not None

    def test_update_correlation_matrix_wrong_size(self, optimizer_with_assets):
        """Test updating with wrong size matrix."""
        corr_matrix = np.array([
            [1.0, 0.5, 0.3],
            [0.5, 1.0, 0.4],
            [0.3, 0.4, 1.0]
        ])
        result = optimizer_with_assets.update_correlation_matrix(corr_matrix)
        
        assert result is False


class TestPortfolioOptimization:
    """Test portfolio optimization methods."""

    @pytest.fixture
    def configured_optimizer(self):
        optimizer = PortfolioOptimizer(config={})
        optimizer.add_asset(Asset("BTC", 0.15, 0.30))
        optimizer.add_asset(Asset("ETH", 0.20, 0.40))
        optimizer.add_asset(Asset("SOL", 0.25, 0.50))
        
        corr_matrix = np.array([
            [1.0, 0.6, 0.5],
            [0.6, 1.0, 0.7],
            [0.5, 0.7, 1.0]
        ])
        optimizer.update_correlation_matrix(corr_matrix)
        return optimizer

    @pytest.mark.asyncio
    async def test_optimize_mean_variance(self, configured_optimizer):
        """Test mean-variance optimization."""
        result = await configured_optimizer.optimize_portfolio("mean_variance")
        
        assert result is not None
        assert result.optimization_method in ["mean_variance", "mean_variance_simplified"]
        assert sum(result.weights.values()) == pytest.approx(1.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_optimize_risk_parity(self, configured_optimizer):
        """Test risk parity optimization."""
        result = await configured_optimizer.optimize_portfolio("risk_parity")
        
        assert result is not None
        assert sum(result.weights.values()) == pytest.approx(1.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_optimize_max_diversification(self, configured_optimizer):
        """Test max diversification optimization."""
        result = await configured_optimizer.optimize_portfolio("max_diversification")
        
        assert result is not None
        assert sum(result.weights.values()) == pytest.approx(1.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_optimize_min_variance(self, configured_optimizer):
        """Test minimum variance optimization."""
        result = await configured_optimizer.optimize_portfolio("min_variance")
        
        assert result is not None
        assert sum(result.weights.values()) == pytest.approx(1.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_optimize_unknown_method(self, configured_optimizer):
        """Test optimization with unknown method."""
        result = await configured_optimizer.optimize_portfolio("unknown_method")
        
        assert result is None

    @pytest.mark.asyncio
    async def test_optimize_insufficient_assets(self):
        """Test optimization with insufficient assets."""
        optimizer = PortfolioOptimizer(config={})
        optimizer.add_asset(Asset("BTC", 0.15, 0.30))  # Only one asset
        
        result = await optimizer.optimize_portfolio("mean_variance")
        
        assert result is None

    @pytest.mark.asyncio
    async def test_optimize_no_covariance(self):
        """Test optimization without covariance matrix."""
        optimizer = PortfolioOptimizer(config={})
        optimizer.add_asset(Asset("BTC", 0.15, 0.30))
        optimizer.add_asset(Asset("ETH", 0.20, 0.40))
        # No covariance matrix set
        
        result = await optimizer.optimize_portfolio("mean_variance")
        
        assert result is None

    @pytest.mark.asyncio
    async def test_optimize_with_constraints(self, configured_optimizer):
        """Test optimization with custom constraints."""
        constraints = {
            "min_weight": 0.1,
            "max_weight": 0.5
        }
        result = await configured_optimizer.optimize_portfolio("mean_variance", constraints)
        
        assert result is not None
        for weight in result.weights.values():
            assert weight >= 0.1 - 0.01  # Allow small tolerance
            assert weight <= 0.5 + 0.01


class TestSimplifiedOptimization:
    """Test simplified optimization fallbacks."""

    @pytest.fixture
    def optimizer(self):
        optimizer = PortfolioOptimizer(config={})
        optimizer.add_asset(Asset("BTC", 0.15, 0.30))
        optimizer.add_asset(Asset("ETH", 0.20, 0.40))
        
        corr_matrix = np.array([
            [1.0, 0.6],
            [0.6, 1.0]
        ])
        optimizer.update_correlation_matrix(corr_matrix)
        return optimizer

    @pytest.mark.asyncio
    async def test_simplified_mean_variance(self, optimizer):
        """Test simplified mean-variance."""
        expected_returns = np.array([0.15, 0.20])
        constraints = {"min_weight": 0.0, "max_weight": 1.0}
        
        result = await optimizer._simplified_mean_variance(
            expected_returns, 
            optimizer.covariance_matrix, 
            constraints
        )
        
        assert result is not None
        assert "simplified" in result.metadata

    @pytest.mark.asyncio
    async def test_simplified_risk_parity(self, optimizer):
        """Test simplified risk parity."""
        constraints = {"min_weight": 0.0, "max_weight": 1.0}
        
        result = await optimizer._simplified_risk_parity(
            optimizer.covariance_matrix, 
            constraints
        )
        
        assert result is not None
        assert result.metadata.get("simplified") is True

    @pytest.mark.asyncio
    async def test_simplified_max_diversification(self, optimizer):
        """Test simplified max diversification."""
        expected_returns = np.array([0.15, 0.20])
        volatilities = np.array([0.30, 0.40])
        constraints = {"min_weight": 0.0, "max_weight": 1.0}
        
        result = await optimizer._simplified_max_diversification(
            expected_returns,
            volatilities,
            optimizer.covariance_matrix, 
            constraints
        )
        
        assert result is not None

    @pytest.mark.asyncio
    async def test_simplified_min_variance(self, optimizer):
        """Test simplified min variance."""
        constraints = {"min_weight": 0.0, "max_weight": 1.0}
        
        result = await optimizer._simplified_min_variance(
            optimizer.covariance_matrix, 
            constraints
        )
        
        assert result is not None


class TestPortfolioMetricsCalculation:
    """Test portfolio metrics calculation."""

    @pytest.fixture
    def optimizer(self):
        optimizer = PortfolioOptimizer(config={})
        optimizer.add_asset(Asset("BTC", 0.15, 0.30))
        optimizer.add_asset(Asset("ETH", 0.20, 0.40))
        
        corr_matrix = np.array([
            [1.0, 0.6],
            [0.6, 1.0]
        ])
        optimizer.update_correlation_matrix(corr_matrix)
        return optimizer

    def test_calculate_portfolio_metrics(self, optimizer):
        """Test calculating portfolio metrics."""
        weights = {"BTC": 0.6, "ETH": 0.4}
        
        metrics = optimizer._calculate_portfolio_metrics(weights)
        
        assert metrics.expected_return > 0
        assert metrics.volatility > 0
        assert metrics.sharpe_ratio != 0
        assert 0 <= metrics.concentration_risk <= 1

    def test_calculate_metrics_equal_weights(self, optimizer):
        """Test metrics with equal weights."""
        weights = {"BTC": 0.5, "ETH": 0.5}
        
        metrics = optimizer._calculate_portfolio_metrics(weights)
        
        # Equal weights -> concentration risk = 2 * 0.5^2 = 0.5
        assert metrics.concentration_risk == pytest.approx(0.5)


class TestOptimizationComparison:
    """Test optimization comparison."""

    @pytest.fixture
    def configured_optimizer(self):
        optimizer = PortfolioOptimizer(config={
            "optimization_methods": ["mean_variance", "risk_parity", "min_variance"]
        })
        optimizer.add_asset(Asset("BTC", 0.15, 0.30))
        optimizer.add_asset(Asset("ETH", 0.20, 0.40))
        optimizer.add_asset(Asset("SOL", 0.25, 0.50))
        
        corr_matrix = np.array([
            [1.0, 0.6, 0.5],
            [0.6, 1.0, 0.7],
            [0.5, 0.7, 1.0]
        ])
        optimizer.update_correlation_matrix(corr_matrix)
        return optimizer

    @pytest.mark.asyncio
    async def test_compare_optimizations(self, configured_optimizer):
        """Test comparing multiple optimization methods."""
        results = await configured_optimizer.compare_optimizations()
        
        assert len(results) > 0
        assert "best_method" in results
        assert "best_sharpe" in results

    @pytest.mark.asyncio
    async def test_compare_with_constraints(self, configured_optimizer):
        """Test comparison with constraints."""
        constraints = {"min_weight": 0.1}
        results = await configured_optimizer.compare_optimizations(constraints)
        
        assert len(results) > 0


class TestOptimizationHistory:
    """Test optimization history tracking."""

    @pytest.fixture
    def configured_optimizer(self):
        optimizer = PortfolioOptimizer(config={})
        optimizer.add_asset(Asset("BTC", 0.15, 0.30))
        optimizer.add_asset(Asset("ETH", 0.20, 0.40))
        
        corr_matrix = np.array([
            [1.0, 0.6],
            [0.6, 1.0]
        ])
        optimizer.update_correlation_matrix(corr_matrix)
        return optimizer

    @pytest.mark.asyncio
    async def test_optimization_history(self, configured_optimizer):
        """Test optimization history is recorded."""
        await configured_optimizer.optimize_portfolio("mean_variance")
        await configured_optimizer.optimize_portfolio("min_variance")
        
        history = configured_optimizer.get_optimization_history()
        
        assert len(history) >= 2

    @pytest.mark.asyncio
    async def test_history_limit(self, configured_optimizer):
        """Test history respects limit."""
        await configured_optimizer.optimize_portfolio("mean_variance")
        await configured_optimizer.optimize_portfolio("min_variance")
        
        history = configured_optimizer.get_optimization_history(limit=1)
        
        assert len(history) == 1


class TestConfigUpdate:
    """Test configuration updates."""

    def test_update_config(self):
        """Test updating optimizer config."""
        optimizer = PortfolioOptimizer(config={"risk_free_rate": 0.02})
        
        optimizer.update_config({"risk_free_rate": 0.05})
        
        assert optimizer.risk_free_rate == 0.05

    def test_update_optimization_methods(self):
        """Test updating optimization methods."""
        optimizer = PortfolioOptimizer(config={})
        
        optimizer.update_config({
            "optimization_methods": ["mean_variance"]
        })
        
        assert optimizer.optimization_methods == ["mean_variance"]


class TestOptimizationSummary:
    """Test optimization summary."""

    @pytest.fixture
    def configured_optimizer(self):
        optimizer = PortfolioOptimizer(config={})
        optimizer.add_asset(Asset("BTC", 0.15, 0.30))
        optimizer.add_asset(Asset("ETH", 0.20, 0.40))
        
        corr_matrix = np.array([
            [1.0, 0.6],
            [0.6, 1.0]
        ])
        optimizer.update_correlation_matrix(corr_matrix)
        return optimizer

    def test_summary_no_data(self):
        """Test summary with no optimization history."""
        optimizer = PortfolioOptimizer(config={})
        
        summary = optimizer.get_optimization_summary()
        
        assert summary["status"] == "no_data"

    @pytest.mark.asyncio
    async def test_summary_with_data(self, configured_optimizer):
        """Test summary with optimization data."""
        await configured_optimizer.optimize_portfolio("mean_variance")
        
        summary = configured_optimizer.get_optimization_summary()
        
        assert "total_optimizations" in summary
        assert "method_distribution" in summary
        assert "performance_metrics" in summary
        assert summary["total_optimizations"] >= 1


class TestComplianceRecording:
    """Test compliance audit recording."""

    @pytest.fixture
    def optimizer(self):
        return PortfolioOptimizer(config={
            "us_compliance": {"audit_optimization": True}
        })

    @pytest.mark.asyncio
    async def test_compliance_recording(self, optimizer):
        """Test compliance is recorded."""
        optimizer.add_asset(Asset("BTC", 0.15, 0.30))
        optimizer.add_asset(Asset("ETH", 0.20, 0.40))
        
        corr_matrix = np.array([
            [1.0, 0.6],
            [0.6, 1.0]
        ])
        optimizer.update_correlation_matrix(corr_matrix)
        
        # Should complete without error
        result = await optimizer.optimize_portfolio("mean_variance")
        
        assert result is not None

    @pytest.mark.asyncio
    async def test_compliance_disabled(self):
        """Test when compliance recording is disabled."""
        optimizer = PortfolioOptimizer(config={
            "us_compliance": {"audit_optimization": False}
        })
        optimizer.add_asset(Asset("BTC", 0.15, 0.30))
        optimizer.add_asset(Asset("ETH", 0.20, 0.40))
        
        corr_matrix = np.array([
            [1.0, 0.6],
            [0.6, 1.0]
        ])
        optimizer.update_correlation_matrix(corr_matrix)
        
        result = await optimizer.optimize_portfolio("mean_variance")
        
        assert result is not None


class TestEdgeCases:
    """Test edge cases."""

    def test_zero_volatility_asset(self):
        """Test handling asset with zero volatility."""
        optimizer = PortfolioOptimizer(config={})
        asset = Asset("STABLE", 0.02, 0.001)  # Very low volatility
        
        result = optimizer.add_asset(asset)
        
        assert result is True

    @pytest.mark.asyncio
    async def test_highly_correlated_assets(self):
        """Test with highly correlated assets."""
        optimizer = PortfolioOptimizer(config={})
        optimizer.add_asset(Asset("A", 0.10, 0.20))
        optimizer.add_asset(Asset("B", 0.12, 0.22))
        
        # Near perfect correlation
        corr_matrix = np.array([
            [1.0, 0.99],
            [0.99, 1.0]
        ])
        optimizer.update_correlation_matrix(corr_matrix)
        
        result = await optimizer.optimize_portfolio("mean_variance")
        
        # Should still produce a result
        assert result is not None

    @pytest.mark.asyncio
    async def test_negative_correlation(self):
        """Test with negatively correlated assets."""
        optimizer = PortfolioOptimizer(config={})
        optimizer.add_asset(Asset("STOCK", 0.10, 0.20))
        optimizer.add_asset(Asset("BOND", 0.05, 0.10))
        
        # Negative correlation
        corr_matrix = np.array([
            [1.0, -0.3],
            [-0.3, 1.0]
        ])
        optimizer.update_correlation_matrix(corr_matrix)
        
        result = await optimizer.optimize_portfolio("mean_variance")
        
        assert result is not None
        # Negative correlation should improve diversification
        assert result.portfolio_metrics.diversification_ratio >= 1.0

    def test_metrics_with_no_downside(self):
        """Test metrics when all assets have positive returns."""
        optimizer = PortfolioOptimizer(config={"risk_free_rate": 0.0})
        optimizer.add_asset(Asset("A", 0.15, 0.20))
        optimizer.add_asset(Asset("B", 0.20, 0.25))
        
        corr_matrix = np.array([
            [1.0, 0.5],
            [0.5, 1.0]
        ])
        optimizer.update_correlation_matrix(corr_matrix)
        
        weights = {"A": 0.5, "B": 0.5}
        metrics = optimizer._calculate_portfolio_metrics(weights)
        
        # All returns above risk-free rate, so sortino uses default
        assert metrics.sortino_ratio != 0


class TestAvailabilityFlags:
    """Test library availability flags."""

    def test_scipy_flag(self):
        """Test SCIPY_AVAILABLE flag exists."""
        from risk.portfolio_optimizer import SCIPY_AVAILABLE
        assert isinstance(SCIPY_AVAILABLE, bool)

    def test_cvxpy_flag(self):
        """Test CVXPY_AVAILABLE flag exists."""
        from risk.portfolio_optimizer import CVXPY_AVAILABLE
        assert isinstance(CVXPY_AVAILABLE, bool)
