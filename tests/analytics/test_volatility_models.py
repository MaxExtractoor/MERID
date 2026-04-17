"""Tests for analytics/volatility_models.py - Volatility Modeling."""
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from dataclasses import asdict

from analytics.volatility_models import (
    VolatilityMetrics,
    VolatilityForecast,
    ARCH_AVAILABLE,
)


class TestVolatilityMetrics:
    """Test VolatilityMetrics dataclass."""

    def test_low_volatility_metrics(self):
        """Test low volatility metrics."""
        metrics = VolatilityMetrics(
            timestamp=1000.0,
            realized_volatility=0.15,
            garch_volatility=0.14,
            implied_volatility=0.16,
            volatility_regime="low",
            risk_level="low",
            var_95=0.02,
            var_99=0.03,
            expected_shortfall_95=0.025,
            expected_shortfall_99=0.04,
            volatility_trend=-0.01,
            volatility_momentum=-0.005,
            market_stress=0.2,
        )
        assert metrics.volatility_regime == "low"
        assert metrics.risk_level == "low"
        assert metrics.realized_volatility < 0.2

    def test_high_volatility_metrics(self):
        """Test high volatility metrics."""
        metrics = VolatilityMetrics(
            timestamp=1000.0,
            realized_volatility=0.45,
            garch_volatility=0.50,
            implied_volatility=0.55,
            volatility_regime="high",
            risk_level="high",
            var_95=0.08,
            var_99=0.12,
            expected_shortfall_95=0.10,
            expected_shortfall_99=0.15,
            volatility_trend=0.05,
            volatility_momentum=0.03,
            market_stress=0.8,
        )
        assert metrics.volatility_regime == "high"
        assert metrics.var_99 > metrics.var_95
        assert metrics.expected_shortfall_99 > metrics.expected_shortfall_95

    def test_extreme_volatility_metrics(self):
        """Test extreme volatility metrics."""
        metrics = VolatilityMetrics(
            timestamp=1000.0,
            realized_volatility=0.80,
            garch_volatility=0.85,
            implied_volatility=1.0,
            volatility_regime="extreme",
            risk_level="critical",
            var_95=0.15,
            var_99=0.25,
            expected_shortfall_95=0.20,
            expected_shortfall_99=0.35,
            volatility_trend=0.10,
            volatility_momentum=0.08,
            market_stress=0.95,
        )
        assert metrics.market_stress > 0.9
        assert metrics.implied_volatility >= metrics.realized_volatility

    def test_volatility_metrics_with_metadata(self):
        """Test volatility metrics with metadata."""
        metrics = VolatilityMetrics(
            timestamp=1000.0,
            realized_volatility=0.25,
            garch_volatility=0.27,
            implied_volatility=0.30,
            volatility_regime="medium",
            risk_level="medium",
            var_95=0.04,
            var_99=0.06,
            expected_shortfall_95=0.05,
            expected_shortfall_99=0.08,
            volatility_trend=0.01,
            volatility_momentum=0.005,
            market_stress=0.4,
            metadata={"symbol": "BTC/USD", "window": "1d"},
        )
        assert metrics.metadata["symbol"] == "BTC/USD"


class TestVolatilityForecast:
    """Test VolatilityForecast dataclass."""

    def test_basic_forecast(self):
        """Test basic volatility forecast."""
        forecast = VolatilityForecast(
            model_id="garch_001",
            model_type="GARCH(1,1)",
            forecast_horizon=10,
            volatility_forecasts=[0.20, 0.21, 0.22, 0.23, 0.24, 0.25, 0.26, 0.27, 0.28, 0.29],
            confidence_intervals=[(0.15, 0.25), (0.16, 0.26)] * 5,
            timestamps=[datetime.now() + timedelta(hours=i) for i in range(10)],
            model_metrics={"aic": 100.0, "bic": 105.0, "log_likelihood": -50.0},
            training_time=5.0,
            prediction_time=0.1,
        )
        assert forecast.forecast_horizon == 10
        assert len(forecast.volatility_forecasts) == 10

    def test_forecast_confidence_intervals(self):
        """Test forecast confidence intervals."""
        vol_forecasts = [0.25, 0.26, 0.27]
        ci = [(0.20, 0.30), (0.21, 0.31), (0.22, 0.32)]
        
        forecast = VolatilityForecast(
            model_id="garch_002",
            model_type="GARCH(1,1)",
            forecast_horizon=3,
            volatility_forecasts=vol_forecasts,
            confidence_intervals=ci,
            timestamps=[datetime.now()],
            model_metrics={},
            training_time=3.0,
            prediction_time=0.05,
        )
        
        # Verify forecasts within confidence intervals
        for i, vol in enumerate(vol_forecasts):
            assert ci[i][0] <= vol <= ci[i][1]

    def test_forecast_with_metrics(self):
        """Test forecast with model metrics."""
        forecast = VolatilityForecast(
            model_id="egarch_001",
            model_type="EGARCH(1,1)",
            forecast_horizon=5,
            volatility_forecasts=[0.30] * 5,
            confidence_intervals=[(0.25, 0.35)] * 5,
            timestamps=[datetime.now()],
            model_metrics={
                "aic": 95.5,
                "bic": 100.2,
                "log_likelihood": -45.0,
                "persistence": 0.95,
            },
            training_time=8.0,
            prediction_time=0.2,
        )
        assert forecast.model_metrics["persistence"] == 0.95


class TestVolatilityCalculations:
    """Test volatility calculation methods."""

    def test_realized_volatility(self):
        """Test realized volatility calculation."""
        # Daily returns
        returns = np.array([0.01, -0.02, 0.015, -0.01, 0.025, -0.005, 0.02])
        
        # Annualized realized volatility (assuming 252 trading days)
        daily_vol = np.std(returns)
        annualized_vol = daily_vol * np.sqrt(252)
        
        assert daily_vol > 0
        assert annualized_vol > daily_vol

    def test_ewma_volatility(self):
        """Test EWMA volatility calculation."""
        returns = np.array([0.01, -0.02, 0.015, -0.01, 0.025])
        lambda_decay = 0.94
        
        # EWMA variance
        ewma_var = np.var(returns)  # Start with simple variance
        for ret in returns[-3:]:
            ewma_var = lambda_decay * ewma_var + (1 - lambda_decay) * ret**2
        
        ewma_vol = np.sqrt(ewma_var)
        assert ewma_vol > 0

    def test_parkinson_volatility(self):
        """Test Parkinson volatility estimator."""
        # High-low data
        highs = np.array([105, 107, 106, 108, 110])
        lows = np.array([100, 102, 101, 103, 105])
        
        # Parkinson estimator
        log_hl = np.log(highs / lows)
        parkinson_var = np.mean(log_hl**2) / (4 * np.log(2))
        parkinson_vol = np.sqrt(parkinson_var)
        
        assert parkinson_vol > 0

    def test_garman_klass_volatility(self):
        """Test Garman-Klass volatility estimator."""
        opens = np.array([100, 103, 102, 105, 107])
        highs = np.array([105, 107, 106, 108, 110])
        lows = np.array([99, 101, 100, 103, 105])
        closes = np.array([103, 102, 105, 107, 108])
        
        # Garman-Klass estimator components
        log_hl = np.log(highs / lows)
        log_co = np.log(closes / opens)
        
        gk_var = 0.5 * np.mean(log_hl**2) - (2 * np.log(2) - 1) * np.mean(log_co**2)
        gk_vol = np.sqrt(max(gk_var, 0))
        
        assert gk_vol >= 0


class TestVaRCalculations:
    """Test Value at Risk calculations."""

    def test_historical_var(self):
        """Test historical VaR calculation."""
        returns = np.random.randn(1000) * 0.02  # Random returns with 2% vol
        
        var_95 = np.percentile(returns, 5)  # 5th percentile for 95% VaR
        var_99 = np.percentile(returns, 1)  # 1st percentile for 99% VaR
        
        assert var_99 < var_95 < 0  # Both should be negative (losses)

    def test_parametric_var(self):
        """Test parametric VaR calculation."""
        portfolio_value = 100000
        volatility = 0.02  # Daily volatility
        
        # Z-scores for confidence levels
        z_95 = 1.645
        z_99 = 2.326
        
        var_95 = portfolio_value * volatility * z_95
        var_99 = portfolio_value * volatility * z_99
        
        assert var_99 > var_95
        assert var_95 == pytest.approx(3290, rel=0.01)

    def test_expected_shortfall(self):
        """Test Expected Shortfall (CVaR) calculation."""
        np.random.seed(42)
        returns = np.random.randn(10000) * 0.02
        
        var_95 = np.percentile(returns, 5)
        
        # ES is average of returns below VaR
        es_95 = returns[returns <= var_95].mean()
        
        assert es_95 < var_95  # ES should be more extreme than VaR

    def test_cornish_fisher_var(self):
        """Test Cornish-Fisher VaR adjustment."""
        mean_return = 0.001
        std_return = 0.02
        skewness = -0.5  # Negative skew (fat left tail)
        kurtosis = 4.0   # Excess kurtosis
        
        z = 1.645  # 95% confidence
        
        # Cornish-Fisher adjustment
        cf_z = (z + (z**2 - 1) * skewness / 6 + 
                (z**3 - 3*z) * (kurtosis - 3) / 24 - 
                (2*z**3 - 5*z) * skewness**2 / 36)
        
        cf_var = mean_return - cf_z * std_return
        normal_var = mean_return - z * std_return
        
        # CF adjustment changes VaR based on distribution shape
        # Verify both are negative (representing losses)
        assert cf_var < 0
        assert normal_var < 0


class TestVolatilityRegimes:
    """Test volatility regime detection."""

    def test_regime_classification(self):
        """Test volatility regime classification."""
        def classify_vol_regime(vol):
            if vol < 0.15:
                return "low"
            elif vol < 0.30:
                return "medium"
            elif vol < 0.50:
                return "high"
            else:
                return "extreme"
        
        assert classify_vol_regime(0.10) == "low"
        assert classify_vol_regime(0.25) == "medium"
        assert classify_vol_regime(0.40) == "high"
        assert classify_vol_regime(0.70) == "extreme"

    def test_regime_transition_detection(self):
        """Test regime transition detection."""
        volatilities = [0.10, 0.12, 0.15, 0.20, 0.35, 0.45, 0.40, 0.30]
        threshold = 0.25
        
        transitions = []
        prev_regime = volatilities[0] < threshold
        
        for i, vol in enumerate(volatilities[1:], 1):
            curr_regime = vol < threshold
            if curr_regime != prev_regime:
                transitions.append((i, "low_to_high" if not curr_regime else "high_to_low"))
            prev_regime = curr_regime
        
        assert len(transitions) >= 1

    def test_volatility_clustering(self):
        """Test volatility clustering detection."""
        # Generate clustered volatility
        np.random.seed(42)
        n = 100
        vols = []
        current_vol = 0.20
        
        for i in range(n):
            # GARCH-like dynamics
            innovation = np.random.randn() * 0.05
            current_vol = 0.1 + 0.85 * current_vol + 0.10 * abs(innovation)
            vols.append(current_vol)
        
        vols = np.array(vols)
        
        # Test autocorrelation (volatility clustering)
        autocorr = np.corrcoef(vols[:-1], vols[1:])[0, 1]
        assert autocorr > 0.5  # Should be positively correlated


class TestRiskManagement:
    """Test risk management based on volatility."""

    def test_position_sizing_by_volatility(self):
        """Test position sizing based on volatility."""
        base_position = 10000
        target_risk = 0.02  # 2% risk per trade
        
        scenarios = [
            {"vol": 0.10, "expected_size": base_position * (target_risk / 0.10)},
            {"vol": 0.20, "expected_size": base_position * (target_risk / 0.20)},
            {"vol": 0.40, "expected_size": base_position * (target_risk / 0.40)},
        ]
        
        for s in scenarios:
            position = base_position * (target_risk / s["vol"])
            assert position == pytest.approx(s["expected_size"], rel=0.01)

    def test_stop_loss_by_volatility(self):
        """Test stop loss adjustment by volatility."""
        def calculate_stop(price, volatility, multiplier=2):
            return price * (1 - multiplier * volatility)
        
        price = 100
        
        low_vol_stop = calculate_stop(price, 0.10)
        high_vol_stop = calculate_stop(price, 0.30)
        
        # Higher volatility = wider stop
        assert high_vol_stop < low_vol_stop

    def test_kelly_criterion(self):
        """Test Kelly criterion for position sizing."""
        win_rate = 0.55
        win_loss_ratio = 1.5
        
        # Kelly formula
        kelly_fraction = win_rate - (1 - win_rate) / win_loss_ratio
        
        assert kelly_fraction > 0
        assert kelly_fraction < 1

    def test_max_drawdown_estimation(self):
        """Test max drawdown estimation from volatility."""
        annual_vol = 0.30
        time_horizon_years = 1
        
        # Approximate max drawdown (rough heuristic)
        expected_max_dd = annual_vol * np.sqrt(time_horizon_years) * 2.5
        
        assert expected_max_dd > 0
        assert expected_max_dd < 1  # Should be less than 100%


class TestVolatilityForecasting:
    """Test volatility forecasting methods."""

    def test_simple_moving_average_vol(self):
        """Test SMA volatility forecast."""
        returns = np.array([0.01, -0.02, 0.015, -0.01, 0.025, -0.005, 0.02, -0.015])
        window = 5
        
        # Rolling volatility
        rolling_vols = [np.std(returns[max(0, i-window+1):i+1]) for i in range(len(returns))]
        
        # Forecast is last rolling volatility
        forecast_vol = rolling_vols[-1]
        
        assert forecast_vol > 0

    def test_exponential_weighted_vol(self):
        """Test exponentially weighted volatility forecast."""
        returns = np.array([0.01, -0.02, 0.015, -0.01, 0.025])
        lambda_decay = 0.94
        
        weights = np.array([lambda_decay ** i for i in range(len(returns)-1, -1, -1)])
        weights /= weights.sum()
        
        ewm_vol = np.sqrt(np.sum(weights * returns**2))
        
        assert ewm_vol > 0

    def test_volatility_mean_reversion(self):
        """Test volatility mean reversion forecast."""
        current_vol = 0.40
        long_term_vol = 0.25
        reversion_speed = 0.1
        
        # Mean reversion forecast
        forecast_vol = current_vol + reversion_speed * (long_term_vol - current_vol)
        
        # Forecast should be between current and long-term
        assert long_term_vol < forecast_vol < current_vol
