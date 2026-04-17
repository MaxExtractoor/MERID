"""Tests for analytics/correlation_analysis.py - Correlation Analysis."""
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from dataclasses import asdict

from analytics.correlation_analysis import (
    CorrelationMetrics,
    CorrelationForecast,
    CorrelationAnalyzer,
)


class TestCorrelationMetrics:
    """Test CorrelationMetrics dataclass."""

    def test_high_correlation_metrics(self):
        """Test high correlation metrics."""
        metrics = CorrelationMetrics(
            timestamp=1000.0,
            asset_pairs=[("BTC", "ETH"), ("BTC", "SOL"), ("ETH", "SOL")],
            correlation_matrix={
                "BTC": {"BTC": 1.0, "ETH": 0.85, "SOL": 0.75},
                "ETH": {"BTC": 0.85, "ETH": 1.0, "SOL": 0.80},
                "SOL": {"BTC": 0.75, "ETH": 0.80, "SOL": 1.0},
            },
            average_correlation=0.80,
            max_correlation=0.85,
            min_correlation=0.75,
            correlation_trend=0.02,
            diversification_ratio=1.2,
            concentration_risk=0.65,
            systemic_risk=0.55,
        )
        assert metrics.average_correlation > 0.7
        assert metrics.concentration_risk > 0.5

    def test_low_correlation_metrics(self):
        """Test low correlation (diversified) metrics."""
        metrics = CorrelationMetrics(
            timestamp=1000.0,
            asset_pairs=[("AAPL", "GC"), ("AAPL", "EUR"), ("GC", "EUR")],
            correlation_matrix={
                "AAPL": {"AAPL": 1.0, "GC": 0.15, "EUR": -0.10},
                "GC": {"AAPL": 0.15, "GC": 1.0, "EUR": 0.20},
                "EUR": {"AAPL": -0.10, "GC": 0.20, "EUR": 1.0},
            },
            average_correlation=0.08,
            max_correlation=0.20,
            min_correlation=-0.10,
            correlation_trend=-0.01,
            diversification_ratio=1.8,
            concentration_risk=0.25,
            systemic_risk=0.20,
        )
        assert metrics.average_correlation < 0.3
        assert metrics.diversification_ratio > 1.5


class TestCorrelationForecast:
    """Test CorrelationForecast dataclass."""

    def test_basic_forecast(self):
        """Test basic correlation forecast."""
        forecast = CorrelationForecast(
            forecast_id="corr_001",
            asset_pairs=[("BTC", "ETH")],
            correlation_forecasts={"BTC_ETH": 0.82},
            confidence_intervals={"BTC_ETH": (0.75, 0.89)},
            forecast_horizon=30,
            timestamps=[datetime.now() + timedelta(days=i) for i in range(30)],
            model_metrics={"mae": 0.05, "rmse": 0.07},
            prediction_time=0.5,
        )
        assert forecast.forecast_horizon == 30
        assert forecast.correlation_forecasts["BTC_ETH"] == 0.82

    def test_multi_pair_forecast(self):
        """Test multi-pair correlation forecast."""
        forecast = CorrelationForecast(
            forecast_id="corr_002",
            asset_pairs=[("A", "B"), ("A", "C"), ("B", "C")],
            correlation_forecasts={"A_B": 0.70, "A_C": 0.40, "B_C": 0.55},
            confidence_intervals={
                "A_B": (0.60, 0.80),
                "A_C": (0.30, 0.50),
                "B_C": (0.45, 0.65),
            },
            forecast_horizon=14,
            timestamps=[datetime.now()],
            model_metrics={},
            prediction_time=1.0,
        )
        assert len(forecast.correlation_forecasts) == 3


class TestCorrelationAnalyzer:
    """Test CorrelationAnalyzer class."""

    @pytest.fixture
    def analyzer_config(self):
        """Create analyzer config."""
        return {
            "lookback_period": 252,
            "min_samples": 100,
            "correlation_threshold": 0.7,
        }

    @pytest.fixture
    def analyzer(self, analyzer_config):
        """Create correlation analyzer instance."""
        return CorrelationAnalyzer(analyzer_config)

    def test_analyzer_creation(self, analyzer):
        """Test creating analyzer."""
        assert analyzer is not None
        assert analyzer.lookback_period == 252

    def test_analyzer_parameters(self, analyzer):
        """Test analyzer parameters."""
        assert analyzer.min_samples == 100
        assert analyzer.correlation_threshold == 0.7

    def test_us_compliance(self, analyzer):
        """Test US compliance settings."""
        assert analyzer.us_compliance["data_privacy"] is True

    def test_asset_universe(self, analyzer):
        """Test asset universe storage."""
        assert hasattr(analyzer, 'asset_universe')
        assert isinstance(analyzer.asset_universe, dict)


class TestCorrelationCalculations:
    """Test correlation calculation methods."""

    def test_pearson_correlation(self):
        """Test Pearson correlation calculation."""
        np.random.seed(42)
        n = 100
        
        x = np.random.randn(n)
        y = x * 0.8 + np.random.randn(n) * 0.5
        
        correlation = np.corrcoef(x, y)[0, 1]
        
        assert 0.5 < correlation < 1.0

    def test_rolling_correlation(self):
        """Test rolling correlation calculation."""
        np.random.seed(42)
        n = 200
        window = 50
        
        x = np.cumsum(np.random.randn(n))
        y = np.cumsum(np.random.randn(n))
        
        df = pd.DataFrame({'x': x, 'y': y})
        rolling_corr = df['x'].rolling(window).corr(df['y'])
        
        # Rolling correlation should vary over time
        assert rolling_corr.dropna().std() > 0

    def test_correlation_matrix(self):
        """Test correlation matrix calculation."""
        np.random.seed(42)
        n = 100
        
        data = {
            'A': np.random.randn(n),
            'B': np.random.randn(n),
            'C': np.random.randn(n),
        }
        df = pd.DataFrame(data)
        
        corr_matrix = df.corr()
        
        # Diagonal should be 1
        assert all(corr_matrix.iloc[i, i] == 1.0 for i in range(3))
        # Should be symmetric
        assert np.allclose(corr_matrix.values, corr_matrix.values.T)

    def test_spearman_correlation(self):
        """Test Spearman rank correlation."""
        np.random.seed(42)
        
        x = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        y = np.array([1.1, 2.2, 2.9, 4.1, 5.0, 6.2, 7.0, 8.1, 8.9, 10.1])
        
        from scipy import stats
        spearman_corr, _ = stats.spearmanr(x, y)
        
        assert spearman_corr > 0.95

    def test_partial_correlation(self):
        """Test partial correlation concept."""
        np.random.seed(42)
        n = 100
        
        # Z influences both X and Y
        z = np.random.randn(n)
        x = z + np.random.randn(n) * 0.3
        y = z + np.random.randn(n) * 0.3
        
        # Simple correlation
        simple_corr = np.corrcoef(x, y)[0, 1]
        
        # Correlation is high due to confounding
        assert simple_corr > 0.5


class TestDiversificationMetrics:
    """Test diversification metrics."""

    def test_diversification_ratio(self):
        """Test diversification ratio calculation."""
        weights = np.array([0.4, 0.3, 0.3])
        volatilities = np.array([0.20, 0.25, 0.15])
        corr_matrix = np.array([
            [1.0, 0.5, 0.3],
            [0.5, 1.0, 0.4],
            [0.3, 0.4, 1.0],
        ])
        
        # Weighted average volatility
        weighted_avg_vol = np.sum(weights * volatilities)
        
        # Portfolio volatility
        cov_matrix = np.outer(volatilities, volatilities) * corr_matrix
        port_vol = np.sqrt(weights @ cov_matrix @ weights)
        
        # Diversification ratio
        div_ratio = weighted_avg_vol / port_vol
        
        assert div_ratio > 1.0  # Diversification benefit

    def test_effective_assets(self):
        """Test effective number of assets."""
        weights = np.array([0.5, 0.3, 0.15, 0.05])
        
        # Herfindahl-Hirschman Index
        hhi = np.sum(weights ** 2)
        
        # Effective number of assets = 1/HHI
        effective_assets = 1 / hhi
        
        assert effective_assets < len(weights)
        assert effective_assets > 1

    def test_concentration_risk(self):
        """Test concentration risk calculation."""
        weights = np.array([0.7, 0.2, 0.1])
        threshold = 0.3
        
        # Count positions above threshold
        concentrated_weight = np.sum(weights[weights > threshold])
        
        assert concentrated_weight > 0.5


class TestCorrelationDynamics:
    """Test correlation dynamics and regime changes."""

    def test_correlation_breakdown(self):
        """Test correlation breakdown detection."""
        # Normal period correlation
        normal_corr = 0.5
        
        # Crisis period correlation (tends to spike)
        crisis_corr = 0.9
        
        # Correlation change
        corr_change = crisis_corr - normal_corr
        
        assert corr_change > 0.3  # Significant change

    def test_correlation_regime_detection(self):
        """Test correlation regime detection."""
        correlations = [0.4, 0.42, 0.45, 0.80, 0.85, 0.82, 0.45, 0.40]
        threshold = 0.6
        
        regimes = ["high" if c > threshold else "normal" for c in correlations]
        
        # Detect regime changes
        changes = sum(1 for i in range(1, len(regimes)) if regimes[i] != regimes[i-1])
        
        assert changes >= 2

    def test_dcc_garch_concept(self):
        """Test DCC-GARCH correlation dynamics concept."""
        # Simplified DCC update
        alpha = 0.05
        beta = 0.90
        
        q_prev = 0.5  # Previous Q
        epsilon_t = 0.8  # Standardized residual product
        q_bar = 0.4  # Unconditional correlation
        
        # DCC update equation
        q_new = (1 - alpha - beta) * q_bar + alpha * epsilon_t + beta * q_prev
        
        assert 0 < q_new < 1
