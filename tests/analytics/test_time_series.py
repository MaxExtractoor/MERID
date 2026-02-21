"""Tests for analytics/time_series.py - Time Series Analysis."""
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from dataclasses import asdict

from analytics.time_series import (
    TimeSeriesConfig,
    ForecastResult,
    ModelMetrics,
    STATSMODELS_AVAILABLE,
)


class TestTimeSeriesConfig:
    """Test TimeSeriesConfig dataclass."""

    def test_default_config(self):
        """Test default time series config."""
        config = TimeSeriesConfig(
            model_type="arima",
            target_column="price",
            feature_columns=["volume", "volatility"],
            time_column="timestamp",
            frequency="daily",
        )
        assert config.model_type == "arima"
        assert config.forecast_horizon == 24
        assert config.confidence_interval == 0.95

    def test_arima_config(self):
        """Test ARIMA configuration."""
        config = TimeSeriesConfig(
            model_type="arima",
            target_column="close",
            feature_columns=[],
            time_column="date",
            frequency="daily",
            arima_order=(2, 1, 2),
            seasonal_order=(1, 1, 1, 7),
        )
        assert config.arima_order == (2, 1, 2)
        assert config.seasonal_order == (1, 1, 1, 7)

    def test_lstm_config(self):
        """Test LSTM configuration."""
        config = TimeSeriesConfig(
            model_type="lstm",
            target_column="price",
            feature_columns=["volume", "ma_20", "rsi"],
            time_column="timestamp",
            frequency="1h",
            lstm_units=[64, 32],
            lstm_dropout=0.3,
            lstm_epochs=50,
            lstm_batch_size=64,
            lstm_learning_rate=0.0001,
        )
        assert config.lstm_units == [64, 32]
        assert config.lstm_dropout == 0.3
        assert config.lstm_epochs == 50

    def test_prophet_config(self):
        """Test Prophet configuration."""
        config = TimeSeriesConfig(
            model_type="prophet",
            target_column="y",
            feature_columns=[],
            time_column="ds",
            frequency="daily",
            prophet_yearly_seasonality=True,
            prophet_weekly_seasonality=True,
            prophet_daily_seasonality=False,
        )
        assert config.prophet_yearly_seasonality is True
        assert config.prophet_daily_seasonality is False

    def test_validation_config(self):
        """Test validation configuration."""
        config = TimeSeriesConfig(
            model_type="arima",
            target_column="price",
            feature_columns=[],
            time_column="ts",
            frequency="hourly",
            validation_split=0.3,
            cross_validation_folds=10,
        )
        assert config.validation_split == 0.3
        assert config.cross_validation_folds == 10

    def test_us_compliance_config(self):
        """Test US compliance settings."""
        config = TimeSeriesConfig(
            model_type="arima",
            target_column="price",
            feature_columns=[],
            time_column="ts",
            frequency="daily",
            data_privacy=True,
            model_transparency=True,
            audit_predictions=True,
        )
        assert config.data_privacy is True
        assert config.model_transparency is True
        assert config.audit_predictions is True


class TestForecastResult:
    """Test ForecastResult dataclass."""

    def test_basic_forecast(self):
        """Test basic forecast result."""
        result = ForecastResult(
            model_id="arima_001",
            model_type="arima",
            target_column="price",
            forecast_horizon=24,
            predictions=[100.0, 101.0, 102.0],
            confidence_lower=[98.0, 99.0, 100.0],
            confidence_upper=[102.0, 103.0, 104.0],
            timestamps=[datetime.now() + timedelta(hours=i) for i in range(3)],
            model_metrics={"mae": 1.5, "rmse": 2.0},
            training_time=10.5,
            prediction_time=0.1,
        )
        assert result.model_id == "arima_001"
        assert len(result.predictions) == 3
        assert result.training_time == 10.5

    def test_forecast_confidence_intervals(self):
        """Test forecast confidence intervals."""
        predictions = [100.0, 105.0, 110.0]
        lower = [95.0, 100.0, 105.0]
        upper = [105.0, 110.0, 115.0]
        
        result = ForecastResult(
            model_id="lstm_001",
            model_type="lstm",
            target_column="price",
            forecast_horizon=3,
            predictions=predictions,
            confidence_lower=lower,
            confidence_upper=upper,
            timestamps=[datetime.now()],
            model_metrics={},
            training_time=60.0,
            prediction_time=0.5,
        )
        
        # Verify confidence intervals contain predictions
        for i in range(len(predictions)):
            assert lower[i] <= predictions[i] <= upper[i]

    def test_forecast_with_metadata(self):
        """Test forecast with metadata."""
        result = ForecastResult(
            model_id="prophet_001",
            model_type="prophet",
            target_column="y",
            forecast_horizon=7,
            predictions=[1.0] * 7,
            confidence_lower=[0.9] * 7,
            confidence_upper=[1.1] * 7,
            timestamps=[datetime.now()],
            model_metrics={"mape": 5.0},
            training_time=30.0,
            prediction_time=1.0,
            metadata={"seasonality": "weekly", "trend": "linear"},
        )
        assert result.metadata["seasonality"] == "weekly"


class TestModelMetrics:
    """Test ModelMetrics dataclass."""

    def test_basic_metrics(self):
        """Test basic model metrics."""
        metrics = ModelMetrics(
            model_id="arima_001",
            model_type="arima",
            mae=1.5,
            mse=3.0,
            rmse=1.73,
            mape=2.5,
            aic=100.0,
            bic=105.0,
            r2_score=0.95,
            training_samples=1000,
            validation_samples=200,
            timestamp=1000.0,
        )
        assert metrics.mae == 1.5
        assert metrics.r2_score == 0.95

    def test_metrics_validation(self):
        """Test metrics values are valid."""
        metrics = ModelMetrics(
            model_id="test",
            model_type="arima",
            mae=1.5,
            mse=2.25,
            rmse=1.5,
            mape=3.0,
            aic=50.0,
            bic=55.0,
            r2_score=0.85,
            training_samples=500,
            validation_samples=100,
            timestamp=1000.0,
        )
        # RMSE should be sqrt(MSE)
        assert metrics.rmse == pytest.approx(np.sqrt(metrics.mse), rel=0.1)
        # R2 should be between 0 and 1 for good models
        assert 0 <= metrics.r2_score <= 1

    def test_poor_model_metrics(self):
        """Test metrics for poor model."""
        metrics = ModelMetrics(
            model_id="bad_model",
            model_type="lstm",
            mae=50.0,
            mse=3000.0,
            rmse=54.77,
            mape=25.0,
            aic=500.0,
            bic=520.0,
            r2_score=0.2,  # Poor R2
            training_samples=100,
            validation_samples=20,
            timestamp=1000.0,
        )
        assert metrics.r2_score < 0.5  # Poor fit
        assert metrics.mape > 10  # High error


class TestTimeSeriesDataPreparation:
    """Test time series data preparation utilities."""

    def test_create_sequences(self):
        """Test creating sequences for LSTM."""
        data = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        window_size = 3
        
        X, y = [], []
        for i in range(len(data) - window_size):
            X.append(data[i:i+window_size])
            y.append(data[i+window_size])
        
        X = np.array(X)
        y = np.array(y)
        
        assert X.shape == (7, 3)
        assert len(y) == 7
        assert y[0] == 4  # First target

    def test_train_test_split(self):
        """Test train/test splitting for time series."""
        data = pd.DataFrame({
            'date': pd.date_range('2024-01-01', periods=100),
            'price': np.random.randn(100).cumsum() + 100,
        })
        
        split_idx = int(len(data) * 0.8)
        train = data[:split_idx]
        test = data[split_idx:]
        
        assert len(train) == 80
        assert len(test) == 20
        # Ensure no overlap
        assert train['date'].max() < test['date'].min()

    def test_feature_scaling(self):
        """Test feature scaling for time series."""
        data = np.array([100, 150, 200, 250, 300])
        
        # Min-max scaling
        min_val = data.min()
        max_val = data.max()
        scaled = (data - min_val) / (max_val - min_val)
        
        assert scaled.min() == 0.0
        assert scaled.max() == 1.0

    def test_differencing(self):
        """Test differencing for stationarity."""
        data = np.array([100, 102, 105, 103, 108, 112])
        diff = np.diff(data)
        
        assert len(diff) == len(data) - 1
        assert diff[0] == 2  # 102 - 100
        assert diff[1] == 3  # 105 - 102


class TestTimeSeriesForecasting:
    """Test time series forecasting logic."""

    def test_naive_forecast(self):
        """Test naive forecasting method."""
        history = [100, 101, 102, 103, 104]
        
        # Naive: last value
        naive_forecast = history[-1]
        assert naive_forecast == 104

    def test_moving_average_forecast(self):
        """Test moving average forecasting."""
        history = [100, 102, 104, 106, 108]
        window = 3
        
        ma = sum(history[-window:]) / window
        assert ma == pytest.approx(106.0)

    def test_exponential_smoothing(self):
        """Test exponential smoothing."""
        history = [100, 102, 104, 103, 105]
        alpha = 0.3
        
        # Simple exponential smoothing
        forecast = history[0]
        for value in history[1:]:
            forecast = alpha * value + (1 - alpha) * forecast
        
        assert forecast > 100  # Should be between first and last

    def test_trend_extrapolation(self):
        """Test linear trend extrapolation."""
        # Linear trend: y = 100 + 2*x
        x = np.array([0, 1, 2, 3, 4])
        y = 100 + 2 * x
        
        # Extrapolate to x=5
        slope = (y[-1] - y[0]) / (x[-1] - x[0])
        intercept = y[0]
        
        forecast = intercept + slope * 5
        assert forecast == pytest.approx(110.0)


class TestModelSelection:
    """Test model selection and validation."""

    def test_aic_comparison(self):
        """Test AIC-based model comparison."""
        models = [
            {"name": "ARIMA(1,1,1)", "aic": 100.5},
            {"name": "ARIMA(2,1,1)", "aic": 98.2},
            {"name": "ARIMA(1,1,2)", "aic": 101.0},
        ]
        
        best_model = min(models, key=lambda x: x["aic"])
        assert best_model["name"] == "ARIMA(2,1,1)"

    def test_cross_validation_folds(self):
        """Test time series cross-validation folds."""
        n_samples = 100
        n_folds = 5
        min_train_size = 50
        
        folds = []
        fold_size = (n_samples - min_train_size) // n_folds
        
        for i in range(n_folds):
            train_end = min_train_size + i * fold_size
            test_start = train_end
            test_end = train_end + fold_size
            folds.append((train_end, test_start, test_end))
        
        assert len(folds) == n_folds
        # Each fold has increasing training data
        for i in range(1, len(folds)):
            assert folds[i][0] > folds[i-1][0]

    def test_rmse_calculation(self):
        """Test RMSE calculation."""
        actual = np.array([100, 102, 105, 103, 108])
        predicted = np.array([101, 103, 104, 104, 107])
        
        mse = np.mean((actual - predicted) ** 2)
        rmse = np.sqrt(mse)
        
        # MSE = (1 + 1 + 1 + 1 + 1) / 5 = 1, RMSE = 1.0
        assert rmse == pytest.approx(1.0, rel=0.01)

    def test_mape_calculation(self):
        """Test MAPE calculation."""
        actual = np.array([100.0, 200.0, 300.0, 400.0])
        predicted = np.array([110.0, 190.0, 320.0, 380.0])
        
        # Errors: 10%, 5%, 6.67%, 5% = avg 6.67%
        mape = np.mean(np.abs((actual - predicted) / actual)) * 100
        
        assert mape == pytest.approx(6.67, rel=0.1)


@pytest.mark.skipif(not STATSMODELS_AVAILABLE, reason="Statsmodels not available")
class TestARIMAModel:
    """Test ARIMA model functionality."""

    @pytest.fixture
    def sample_data(self):
        """Create sample time series data."""
        np.random.seed(42)
        n = 200
        trend = np.linspace(0, 10, n)
        seasonality = 5 * np.sin(np.linspace(0, 8 * np.pi, n))
        noise = np.random.randn(n) * 0.5
        
        data = pd.DataFrame({
            'date': pd.date_range('2024-01-01', periods=n),
            'value': 100 + trend + seasonality + noise,
        })
        return data

    def test_arima_config_creation(self):
        """Test ARIMA config creation."""
        config = TimeSeriesConfig(
            model_type="arima",
            target_column="value",
            feature_columns=[],
            time_column="date",
            frequency="daily",
            arima_order=(1, 1, 1),
        )
        assert config.arima_order == (1, 1, 1)

    def test_stationarity_test(self, sample_data):
        """Test stationarity testing."""
        from statsmodels.tsa.stattools import adfuller
        
        result = adfuller(sample_data['value'].values)
        adf_statistic = result[0]
        p_value = result[1]
        
        # Original series may not be stationary
        # After differencing it should be
        diff_data = np.diff(sample_data['value'].values)
        diff_result = adfuller(diff_data)
        
        # Differenced series should have lower p-value
        assert diff_result[1] < p_value or diff_result[1] < 0.05
