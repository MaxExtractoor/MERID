"""Tests for Monte Carlo simulation module."""

import pytest
import numpy as np
from merid.risk.monte_carlo import (
    run_monte_carlo_simulation,
    stress_test_allocation,
    generate_stress_scenarios,
    calculate_portfolio_risk_metrics,
    SimulationResult
)


class TestMonteCarloSimulation:
    """Test Monte Carlo simulation functionality."""
    
    def test_simulation_empty_assets(self):
        """Test simulation with no assets."""
        result = run_monte_carlo_simulation(
            initial_portfolio_value=1.0,
            expected_returns={},
            volatilities={},
            correlation_matrix={},
            weights={},
            num_simulations=100
        )
        
        assert result.mean_return == 0.0
        assert result.std_return == 0.0
    
    def test_simulation_single_asset(self):
        """Test simulation with single asset."""
        result = run_monte_carlo_simulation(
            initial_portfolio_value=1.0,
            expected_returns={"BTC": 0.001},
            volatilities={"BTC": 0.02},
            correlation_matrix={"BTC": {"BTC": 1.0}},
            weights={"BTC": 1.0},
            num_simulations=1000
        )
        
        assert result.mean_return is not None
        assert result.std_return > 0
        assert result.var_95 is not None
        assert result.var_99 is not None
        assert result.sharpe_ratio is not None
        assert 0 <= result.win_rate <= 1
    
    def test_simulation_multiple_assets(self):
        """Test simulation with multiple assets."""
        result = run_monte_carlo_simulation(
            initial_portfolio_value=1.0,
            expected_returns={
                "BTC": 0.001,
                "ETH": 0.0015,
                "DOGE": 0.002
            },
            volatilities={
                "BTC": 0.02,
                "ETH": 0.025,
                "DOGE": 0.03
            },
            correlation_matrix={
                "BTC": {"BTC": 1.0, "ETH": 0.8, "DOGE": 0.5},
                "ETH": {"BTC": 0.8, "ETH": 1.0, "DOGE": 0.6},
                "DOGE": {"BTC": 0.5, "ETH": 0.6, "DOGE": 1.0}
            },
            weights={
                "BTC": 0.5,
                "ETH": 0.3,
                "DOGE": 0.2
            },
            num_simulations=1000
        )
        
        assert result.mean_return is not None
        assert result.std_return > 0
        assert result.var_95 < 0  # VaR should be negative (loss)
        assert result.expected_shortfall_95 is not None
    
    def test_simulation_weight_normalization(self):
        """Test that weights are normalized if they don't sum to 1."""
        result = run_monte_carlo_simulation(
            initial_portfolio_value=1.0,
            expected_returns={"BTC": 0.001},
            volatilities={"BTC": 0.02},
            correlation_matrix={"BTC": {"BTC": 1.0}},
            weights={"BTC": 0.5},  # Doesn't sum to 1
            num_simulations=100
        )
        
        # Should still work despite non-normalized weights
        assert result is not None
    
    def test_simulation_different_horizons(self):
        """Test simulation with different time horizons."""
        result_1day = run_monte_carlo_simulation(
            initial_portfolio_value=1.0,
            expected_returns={"BTC": 0.001},
            volatilities={"BTC": 0.02},
            correlation_matrix={"BTC": {"BTC": 1.0}},
            weights={"BTC": 1.0},
            num_simulations=100,
            time_horizon_days=1
        )
        
        result_7day = run_monte_carlo_simulation(
            initial_portfolio_value=1.0,
            expected_returns={"BTC": 0.001},
            volatilities={"BTC": 0.02},
            correlation_matrix={"BTC": {"BTC": 1.0}},
            weights={"BTC": 1.0},
            num_simulations=100,
            time_horizon_days=7
        )
        
        # Longer horizon should have higher volatility
        assert result_7day.std_return >= result_1day.std_return


class TestStressTesting:
    """Test stress testing functionality."""
    
    def test_generate_stress_scenarios(self):
        """Test generation of standard stress scenarios."""
        scenarios = generate_stress_scenarios()
        
        assert len(scenarios) > 0
        assert "baseline" in [s.get("name") for s in scenarios]
        assert "bull_market" in [s.get("name") for s in scenarios]
        assert "bear_market" in [s.get("name") for s in scenarios]
        
        # Check that scenarios have asset returns
        for scenario in scenarios:
            assert "BTC" in scenario or "name" in scenario
    
    def test_stress_test_allocation(self):
        """Test stress testing of allocation."""
        allocation = {"BTC": 0.5, "ETH": 0.3, "DOGE": 0.2}
        # Filter scenarios to only include assets in allocation
        scenarios = [
            {
                "name": "baseline",
                "BTC": 0.001,
                "ETH": 0.001,
                "DOGE": 0.002
            },
            {
                "name": "bull_market",
                "BTC": 0.05,
                "ETH": 0.06,
                "DOGE": 0.10
            },
            {
                "name": "bear_market",
                "BTC": -0.05,
                "ETH": -0.06,
                "DOGE": -0.10
            }
        ]
        
        correlation_matrix = {
            "BTC": {"BTC": 1.0, "ETH": 0.8, "DOGE": 0.5},
            "ETH": {"BTC": 0.8, "ETH": 1.0, "DOGE": 0.6},
            "DOGE": {"BTC": 0.5, "ETH": 0.6, "DOGE": 1.0}
        }
        
        volatilities = {
            "BTC": 0.02,
            "ETH": 0.025,
            "DOGE": 0.03
        }
        
        results = stress_test_allocation(
            current_allocation=allocation,
            stress_scenarios=scenarios,
            correlation_matrix=correlation_matrix,
            volatilities=volatilities
        )
        
        # Should have results for each scenario
        assert len(results) == len(scenarios)
        
        # Each result should be a SimulationResult
        for scenario_name, result in results.items():
            assert isinstance(result, SimulationResult)
            assert result.mean_return is not None
    
    def test_stress_test_bear_vs_bull(self):
        """Test that bear market shows worse results than bull market."""
        allocation = {"BTC": 1.0}
        scenarios = [
            {"name": "bull", "BTC": 0.05},
            {"name": "bear", "BTC": -0.05}
        ]
        
        correlation_matrix = {"BTC": {"BTC": 1.0}}
        volatilities = {"BTC": 0.02}
        
        results = stress_test_allocation(
            current_allocation=allocation,
            stress_scenarios=scenarios,
            correlation_matrix=correlation_matrix,
            volatilities=volatilities
        )
        
        # Bull market should have higher mean return than bear
        assert results["bull"].mean_return > results["bear"].mean_return


class TestPortfolioRiskMetrics:
    """Test analytical portfolio risk metrics."""
    
    def test_calculate_risk_metrics_empty(self):
        """Test risk metrics with empty allocation."""
        metrics = calculate_portfolio_risk_metrics(
            allocation={},
            correlation_matrix={},
            volatilities={}
        )
        
        assert metrics["portfolio_volatility"] == 0.0
        assert metrics["diversification_ratio"] == 0.0
    
    def test_calculate_risk_metrics_single_asset(self):
        """Test risk metrics with single asset."""
        metrics = calculate_portfolio_risk_metrics(
            allocation={"BTC": 1.0},
            correlation_matrix={"BTC": {"BTC": 1.0}},
            volatilities={"BTC": 0.02}
        )
        
        assert metrics["portfolio_volatility"] == 0.02
        assert metrics["diversification_ratio"] == 1.0  # No diversification with single asset
    
    def test_calculate_risk_metrics_multiple_assets(self):
        """Test risk metrics with multiple assets."""
        metrics = calculate_portfolio_risk_metrics(
            allocation={
                "BTC": 0.5,
                "ETH": 0.3,
                "DOGE": 0.2
            },
            correlation_matrix={
                "BTC": {"BTC": 1.0, "ETH": 0.8, "DOGE": 0.5},
                "ETH": {"BTC": 0.8, "ETH": 1.0, "DOGE": 0.6},
                "DOGE": {"BTC": 0.5, "ETH": 0.6, "DOGE": 1.0}
            },
            volatilities={
                "BTC": 0.02,
                "ETH": 0.025,
                "DOGE": 0.03
            }
        )
        
        assert metrics["portfolio_volatility"] > 0
        assert metrics["diversification_ratio"] >= 1.0  # Should benefit from diversification
        assert metrics["weighted_avg_volatility"] > 0
    
    def test_diversification_benefit(self):
        """Test that diversification reduces portfolio volatility."""
        # Perfectly correlated assets
        metrics_correlated = calculate_portfolio_risk_metrics(
            allocation={"BTC": 0.5, "ETH": 0.5},
            correlation_matrix={
                "BTC": {"BTC": 1.0, "ETH": 1.0},
                "ETH": {"BTC": 1.0, "ETH": 1.0}
            },
            volatilities={"BTC": 0.02, "ETH": 0.02}
        )
        
        # Uncorrelated assets
        metrics_uncorrelated = calculate_portfolio_risk_metrics(
            allocation={"BTC": 0.5, "ETH": 0.5},
            correlation_matrix={
                "BTC": {"BTC": 1.0, "ETH": 0.0},
                "ETH": {"BTC": 0.0, "ETH": 1.0}
            },
            volatilities={"BTC": 0.02, "ETH": 0.02}
        )
        
        # Uncorrelated should have lower portfolio volatility
        assert metrics_uncorrelated["portfolio_volatility"] < metrics_correlated["portfolio_volatility"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x", "-s"])
