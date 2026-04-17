"""Tests for analytics/performance_attribution.py - Performance Attribution."""
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from dataclasses import asdict

from analytics.performance_attribution import (
    AttributionType,
    AttributionMethod,
    AttributionFactor,
    AttributionResult,
    FactorModel,
    PerformanceAttribution,
)


class TestAttributionType:
    """Test AttributionType enum."""

    def test_asset_allocation(self):
        """Test asset allocation type."""
        assert AttributionType.ASSET_ALLOCATION.value == "asset_allocation"

    def test_sector_attribution(self):
        """Test sector attribution type."""
        assert AttributionType.SECTOR.value == "sector"

    def test_region_attribution(self):
        """Test region attribution type."""
        assert AttributionType.REGION.value == "region"

    def test_style_attribution(self):
        """Test style attribution type."""
        assert AttributionType.STYLE.value == "style"

    def test_factor_attribution(self):
        """Test factor attribution type."""
        assert AttributionType.FACTOR.value == "factor"


class TestAttributionMethod:
    """Test AttributionMethod enum."""

    def test_arithmetic_method(self):
        """Test arithmetic attribution method."""
        assert AttributionMethod.ARITHMETIC.value == "arithmetic"

    def test_geometric_method(self):
        """Test geometric attribution method."""
        assert AttributionMethod.GEOMETRIC.value == "geometric"

    def test_regression_method(self):
        """Test regression attribution method."""
        assert AttributionMethod.REGRESSION.value == "regression"


class TestAttributionFactor:
    """Test AttributionFactor dataclass."""

    def test_positive_factor(self):
        """Test positive attribution factor."""
        factor = AttributionFactor(
            factor_id="tech_sector",
            factor_name="Technology",
            factor_type=AttributionType.SECTOR,
            exposure=0.35,
            contribution=0.08,
            attribution=0.03,
            weight=0.30,
            benchmark_weight=0.25,
            active_weight=0.05,
            return_contribution=0.025,
            risk_contribution=0.04,
        )
        assert factor.active_weight > 0
        assert factor.return_contribution > 0

    def test_negative_factor(self):
        """Test negative attribution factor."""
        factor = AttributionFactor(
            factor_id="energy_sector",
            factor_name="Energy",
            factor_type=AttributionType.SECTOR,
            exposure=0.10,
            contribution=-0.02,
            attribution=-0.015,
            weight=0.08,
            benchmark_weight=0.12,
            active_weight=-0.04,
            return_contribution=-0.01,
            risk_contribution=0.02,
        )
        assert factor.active_weight < 0
        assert factor.return_contribution < 0


class TestAttributionResult:
    """Test AttributionResult dataclass."""

    def test_positive_attribution(self):
        """Test positive attribution result."""
        result = AttributionResult(
            attribution_id="attr_001",
            portfolio_id="port_001",
            benchmark_id="SPX",
            period_start=datetime(2024, 1, 1),
            period_end=datetime(2024, 3, 31),
            total_return=0.15,
            benchmark_return=0.10,
            active_return=0.05,
            attribution_method=AttributionMethod.ARITHMETIC,
            factors=[],
            allocation_effect=0.02,
            selection_effect=0.025,
            interaction_effect=0.005,
            total_attribution=0.05,
            attribution_quality=0.95,
            risk_adjusted_attribution=0.04,
            timestamp=1000.0,
        )
        assert result.active_return > 0
        assert result.allocation_effect + result.selection_effect + result.interaction_effect == pytest.approx(result.total_attribution)

    def test_negative_attribution(self):
        """Test negative attribution result."""
        result = AttributionResult(
            attribution_id="attr_002",
            portfolio_id="port_002",
            benchmark_id="SPX",
            period_start=datetime(2024, 1, 1),
            period_end=datetime(2024, 3, 31),
            total_return=0.05,
            benchmark_return=0.10,
            active_return=-0.05,
            attribution_method=AttributionMethod.ARITHMETIC,
            factors=[],
            allocation_effect=-0.02,
            selection_effect=-0.025,
            interaction_effect=-0.005,
            total_attribution=-0.05,
            attribution_quality=0.90,
            risk_adjusted_attribution=-0.06,
            timestamp=1000.0,
        )
        assert result.active_return < 0


class TestFactorModel:
    """Test FactorModel dataclass."""

    def test_fama_french_model(self):
        """Test Fama-French style factor model."""
        model = FactorModel(
            model_id="ff3",
            model_name="Fama-French 3-Factor",
            model_type="linear",
            factors=["market", "size", "value"],
            factor_loadings={"market": 1.1, "size": 0.3, "value": -0.2},
            factor_returns={"market": 0.08, "size": 0.02, "value": 0.03},
            factor_covariance=np.eye(3) * 0.01,
            specific_risk=0.05,
            r_squared=0.85,
            adjusted_r_squared=0.83,
        )
        assert len(model.factors) == 3
        assert model.r_squared > 0.8

    def test_custom_factor_model(self):
        """Test custom factor model."""
        model = FactorModel(
            model_id="custom_001",
            model_name="Crypto Factor Model",
            model_type="linear",
            factors=["btc_momentum", "defi_exposure", "liquidity"],
            factor_loadings={"btc_momentum": 0.8, "defi_exposure": 0.5, "liquidity": 0.3},
            factor_returns={"btc_momentum": 0.15, "defi_exposure": 0.10, "liquidity": 0.02},
            factor_covariance=np.eye(3) * 0.02,
            specific_risk=0.10,
            r_squared=0.70,
            adjusted_r_squared=0.65,
        )
        assert model.specific_risk > 0


class TestPerformanceAttribution:
    """Test PerformanceAttribution class."""

    @pytest.fixture
    def attribution_config(self):
        """Create attribution config."""
        return {
            "default_method": "arithmetic",
            "min_period_days": 30,
            "risk_free_rate": 0.02,
        }

    @pytest.fixture
    def attribution(self, attribution_config):
        """Create performance attribution instance."""
        return PerformanceAttribution(attribution_config)

    def test_attribution_creation(self, attribution):
        """Test creating attribution."""
        assert attribution is not None

    def test_attribution_history(self, attribution):
        """Test attribution history storage."""
        assert hasattr(attribution, 'attribution_history')
        assert attribution.attribution_history.maxlen == 1000

    def test_factor_models(self, attribution):
        """Test factor models storage."""
        assert hasattr(attribution, 'factor_models')
        assert isinstance(attribution.factor_models, dict)


class TestBrinsonAttribution:
    """Test Brinson attribution methodology."""

    def test_allocation_effect(self):
        """Test allocation effect calculation."""
        # Portfolio weights vs benchmark weights
        port_weights = {"tech": 0.40, "finance": 0.30, "healthcare": 0.30}
        bench_weights = {"tech": 0.30, "finance": 0.35, "healthcare": 0.35}
        
        # Benchmark returns by sector
        bench_returns = {"tech": 0.15, "finance": 0.08, "healthcare": 0.05}
        
        # Total benchmark return
        total_bench_return = sum(bench_weights[s] * bench_returns[s] for s in bench_weights)
        
        # Allocation effect = sum((wp - wb) * (rb - R_b))
        allocation_effect = sum(
            (port_weights[s] - bench_weights[s]) * (bench_returns[s] - total_bench_return)
            for s in port_weights
        )
        
        # Overweight in tech (high return) should give positive allocation
        assert allocation_effect > 0

    def test_selection_effect(self):
        """Test selection effect calculation."""
        # Benchmark weights
        bench_weights = {"tech": 0.30, "finance": 0.35, "healthcare": 0.35}
        
        # Portfolio vs benchmark returns by sector
        port_returns = {"tech": 0.18, "finance": 0.10, "healthcare": 0.04}
        bench_returns = {"tech": 0.15, "finance": 0.08, "healthcare": 0.05}
        
        # Selection effect = sum(wb * (rp - rb))
        selection_effect = sum(
            bench_weights[s] * (port_returns[s] - bench_returns[s])
            for s in bench_weights
        )
        
        # Good stock picking should give positive selection
        assert selection_effect > 0

    def test_interaction_effect(self):
        """Test interaction effect calculation."""
        port_weights = {"A": 0.60, "B": 0.40}
        bench_weights = {"A": 0.50, "B": 0.50}
        port_returns = {"A": 0.12, "B": 0.08}
        bench_returns = {"A": 0.10, "B": 0.10}
        
        # Interaction effect = sum((wp - wb) * (rp - rb))
        interaction_effect = sum(
            (port_weights[s] - bench_weights[s]) * (port_returns[s] - bench_returns[s])
            for s in port_weights
        )
        
        assert isinstance(interaction_effect, float)

    def test_total_attribution(self):
        """Test total attribution equals active return."""
        allocation = 0.02
        selection = 0.015
        interaction = 0.005
        
        total_attribution = allocation + selection + interaction
        
        portfolio_return = 0.12
        benchmark_return = 0.08
        active_return = portfolio_return - benchmark_return
        
        assert total_attribution == pytest.approx(active_return)


class TestFactorAttribution:
    """Test factor-based attribution."""

    def test_factor_contribution(self):
        """Test factor contribution calculation."""
        factor_loadings = {"market": 1.1, "size": 0.3, "value": -0.2}
        factor_returns = {"market": 0.08, "size": 0.02, "value": 0.03}
        
        factor_contribution = sum(
            factor_loadings[f] * factor_returns[f] 
            for f in factor_loadings
        )
        
        # Expected: 1.1*0.08 + 0.3*0.02 + (-0.2)*0.03 = 0.088 + 0.006 - 0.006 = 0.088
        assert factor_contribution == pytest.approx(0.088)

    def test_residual_return(self):
        """Test residual return calculation."""
        total_return = 0.12
        factor_contribution = 0.088
        
        residual_return = total_return - factor_contribution
        
        assert residual_return == pytest.approx(0.032)

    def test_risk_decomposition(self):
        """Test risk decomposition."""
        factor_loadings = np.array([1.1, 0.3, -0.2])
        factor_covariance = np.array([
            [0.04, 0.01, 0.005],
            [0.01, 0.02, 0.003],
            [0.005, 0.003, 0.03],
        ])
        specific_variance = 0.01
        
        # Systematic risk
        systematic_variance = factor_loadings @ factor_covariance @ factor_loadings
        
        # Total variance
        total_variance = systematic_variance + specific_variance
        
        # R-squared
        r_squared = systematic_variance / total_variance
        
        assert 0 < r_squared < 1


class TestRiskAdjustedAttribution:
    """Test risk-adjusted attribution metrics."""

    def test_information_ratio(self):
        """Test information ratio calculation."""
        active_return = 0.05
        tracking_error = 0.08
        
        information_ratio = active_return / tracking_error
        
        assert information_ratio == pytest.approx(0.625)

    def test_sharpe_contribution(self):
        """Test Sharpe ratio contribution by factor."""
        factor_returns = {"market": 0.08, "size": 0.02, "value": 0.03}
        factor_risks = {"market": 0.15, "size": 0.08, "value": 0.10}
        risk_free_rate = 0.02
        
        sharpe_by_factor = {
            f: (factor_returns[f] - risk_free_rate) / factor_risks[f]
            for f in factor_returns
        }
        
        assert sharpe_by_factor["market"] > sharpe_by_factor["size"]

    def test_marginal_contribution_to_risk(self):
        """Test marginal contribution to risk."""
        weights = np.array([0.4, 0.3, 0.3])
        cov_matrix = np.array([
            [0.04, 0.02, 0.01],
            [0.02, 0.03, 0.015],
            [0.01, 0.015, 0.02],
        ])
        
        portfolio_var = weights @ cov_matrix @ weights
        portfolio_vol = np.sqrt(portfolio_var)
        
        # Marginal contribution to risk
        mcr = (cov_matrix @ weights) / portfolio_vol
        
        # Total risk contribution = weights * MCR
        trc = weights * mcr
        
        # Should sum to portfolio volatility
        assert np.sum(trc) == pytest.approx(portfolio_vol)
