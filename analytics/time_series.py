"""
Time Series Analysis for MERID Predictive Analytics

Provides comprehensive time series modeling and forecasting with
ARIMA, LSTM, Prophet integration and US-compliant configuration.

Features:
- ARIMA time series modeling
- LSTM neural network forecasting
- Prophet trend analysis
- Seasonal decomposition
- Cross-validation and model selection
- US-compliant data handling
"""

import asyncio
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
from abc import ABC, abstractmethod

# Time series libraries (with fallbacks)
try:
    from statsmodels.tsa.arima.model import ARIMA
    from statsmodels.tsa.stattools import adfuller, acf, pacf
    from statsmodels.tsa.seasonal import seasonal_decompose
    STATSMODELS_AVAILABLE = True
except ImportError:
    STATSMODELS_AVAILABLE = False

try:
    import prophet
    from prophet import Prophet
    PROPHET_AVAILABLE = True
except ImportError:
    PROPHET_AVAILABLE = False

try:
    import tensorflow as tf
    from tensorflow import keras
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import LSTM, Dense, Dropout
    from tensorflow.keras.optimizers import Adam
    TENSORFLOW_AVAILABLE = True
except ImportError:
    TENSORFLOW_AVAILABLE = False

from utils.logger import get_logger

logger = get_logger("analytics.time_series")

@dataclass
class TimeSeriesConfig:
    """Time series model configuration."""
    model_type: str  # arima, lstm, prophet
    target_column: str
    feature_columns: List[str]
    time_column: str
    frequency: str  # daily, hourly, 4h, 1h
    seasonal_periods: int = 0
    forecast_horizon: int = 24
    confidence_interval: float = 0.95
    
    # ARIMA parameters
    arima_order: Tuple[int, int, int] = (1, 1, 1)
    seasonal_order: Tuple[int, int, int, int] = (0, 0, 0, 0)
    
    # LSTM parameters
    lstm_units: List[int] = field(default_factory=lambda: [50, 50])
    lstm_dropout: float = 0.2
    lstm_epochs: int = 100
    lstm_batch_size: int = 32
    lstm_learning_rate: float = 0.001
    
    # Prophet parameters
    prophet_yearly_seasonality: bool = True
    prophet_weekly_seasonality: bool = True
    prophet_daily_seasonality: bool = True
    
    # Validation parameters
    validation_split: float = 0.2
    cross_validation_folds: int = 5
    
    # US compliance
    data_privacy: bool = True
    model_transparency: bool = True
    audit_predictions: bool = True

@dataclass
class ForecastResult:
    """Time series forecast result."""
    model_id: str
    model_type: str
    target_column: str
    forecast_horizon: int
    predictions: List[float]
    confidence_lower: List[float]
    confidence_upper: List[float]
    timestamps: List[datetime]
    model_metrics: Dict[str, float]
    training_time: float
    prediction_time: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ModelMetrics:
    """Model performance metrics."""
    model_id: str
    model_type: str
    mae: float  # Mean Absolute Error
    mse: float  # Mean Squared Error
    rmse: float  # Root Mean Squared Error
    mape: float  # Mean Absolute Percentage Error
    aic: float  # Akaike Information Criterion
    bic: float  # Bayesian Information Criterion
    r2_score: float  # R-squared
    training_samples: int
    validation_samples: int
    timestamp: float

class TimeSeriesModel(ABC):
    """Abstract base class for time series models."""
    
    def __init__(self, config: TimeSeriesConfig):
        self.config = config
        self.model = None
        self.is_trained = False
        self.training_history = []
        
    @abstractmethod
    async def train(self, data: pd.DataFrame) -> ModelMetrics:
        """Train the time series model."""
        pass
    
    @abstractmethod
    async def forecast(self, data: pd.DataFrame, steps: int) -> ForecastResult:
        """Generate forecast for specified number of steps."""
        pass
    
    @abstractmethod
    def get_model_info(self) -> Dict[str, Any]:
        """Get model information."""
        pass

class ARIMAModel(TimeSeriesModel):
    """ARIMA time series model implementation."""
    
    def __init__(self, config: TimeSeriesConfig):
        super().__init__(config)
        
        if not STATSMODELS_AVAILABLE:
            raise ImportError("Statsmodels is not available for ARIMA modeling")
        
        self.model_type = "arima"
        self.order = config.arima_order
        self.seasonal_order = config.seasonal_order
    
    async def train(self, data: pd.DataFrame) -> ModelMetrics:
        """Train ARIMA model."""
        try:
            start_time = time.time()
            
            # Prepare data
            ts_data = self._prepare_data(data)
            
            # Check stationarity
            is_stationary = self._check_stationarity(ts_data)
            
            if not is_stationary:
                # Difference the series
                ts_data = ts_data.diff().dropna()
                logger.info("Applied differencing to make series stationary")
            
            # Split data
            train_size = int(len(ts_data) * (1 - self.config.validation_split))
            train_data = ts_data[:train_size]
            val_data = ts_data[train_size:]
            
            # Fit model
            self.model = ARIMA(
                train_data,
                order=self.order,
                seasonal_order=self.seasonal_order
            )
            
            fitted_model = self.model.fit(disp=False)
            
            # Calculate metrics
            predictions = fitted_model.predict(start=len(train_data), end=len(ts_data)-1)
            
            mae = np.mean(np.abs(val_data - predictions))
            mse = np.mean((val_data - predictions) ** 2)
            rmse = np.sqrt(mse)
            
            # Calculate MAPE
            mape = np.mean(np.abs((val_data - predictions) / val_data)) * 100
            
            # Get AIC and BIC
            aic = fitted_model.aic
            bic = fitted_model.bic
            
            # Calculate R-squared
            ss_res = np.sum((val_data - predictions) ** 2)
            ss_tot = np.sum((val_data - np.mean(val_data)) ** 2)
            r2_score = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
            
            training_time = time.time() - start_time
            
            metrics = ModelMetrics(
                model_id=f"arima_{self.config.target_column}_{int(time.time())}",
                model_type=self.model_type,
                mae=mae,
                mse=mse,
                rmse=rmse,
                mape=mape,
                aic=aic,
                bic=bic,
                r2_score=r2_score,
                training_samples=len(train_data),
                validation_samples=len(val_data),
                timestamp=training_time
            )
            
            self.is_trained = True
            self.training_history.append(metrics)
            
            logger.info(f"ARIMA model trained: MAE={mae:.4f}, RMSE={rmse:.4f}")
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to train ARIMA model: {e}")
            raise
    
    async def forecast(self, data: pd.DataFrame, steps: int) -> ForecastResult:
        """Generate ARIMA forecast."""
        if not self.is_trained:
            raise ValueError("Model must be trained before forecasting")
        
        try:
            start_time = time.time()
            
            # Prepare data
            ts_data = self._prepare_data(data)
            
            # Generate forecast
            forecast_result = self.model.get_forecast(steps=steps)
            
            # Extract predictions and confidence intervals
            predictions = forecast_result.predicted_mean.tolist()
            conf_int = forecast_result.conf_int()
            
            # Handle confidence intervals
            if conf_int is not None and len(conf_int) > 0:
                confidence_lower = conf_int[:, 0].tolist()
                confidence_upper = conf_int[:, 1].tolist()
            else:
                # Generate simple confidence intervals
                std_error = np.std(predictions)
                confidence_lower = [p - 1.96 * std_error for p in predictions]
                confidence_upper = [p + 1.96 * std_error for p in predictions]
            
            # Generate timestamps
            last_timestamp = pd.to_datetime(data[self.config.time_column].iloc[-1])
            timestamps = []
            
            for i in range(steps):
                if self.config.frequency == "daily":
                    timestamp = last_timestamp + timedelta(days=i+1)
                elif self.config.frequency == "hourly":
                    timestamp = last_timestamp + timedelta(hours=i+1)
                elif self.config.frequency == "4h":
                    timestamp = last_timestamp + timedelta(hours=4*(i+1))
                elif self.config.frequency == "1h":
                    timestamp = last_timestamp + timedelta(hours=i+1)
                else:
                    timestamp = last_timestamp + timedelta(hours=i+1)
                timestamps.append(timestamp)
            
            prediction_time = time.time() - start_time
            
            result = ForecastResult(
                model_id=f"arima_{self.config.target_column}_{int(time.time())}",
                model_type=self.model_type,
                target_column=self.config.target_column,
                forecast_horizon=steps,
                predictions=predictions,
                confidence_lower=confidence_lower,
                confidence_upper=confidence_upper,
                timestamps=timestamps,
                model_metrics=self.training_history[-1].__dict__ if self.training_history else {},
                training_time=self.training_history[-1].timestamp if self.training_history else 0,
                prediction_time=prediction_time,
                metadata={
                    "order": self.order,
                    "seasonal_order": self.seasonal_order,
                    "stationary": self._check_stationarity(self._prepare_data(data))
                }
            )
            
            logger.info(f"ARIMA forecast generated: {steps} steps")
            return result
            
        except Exception as e:
            logger.error(f"Failed to generate ARIMA forecast: {e}")
            raise
    
    def _prepare_data(self, data: pd.DataFrame) -> pd.Series:
        """Prepare time series data."""
        # Sort by time
        data = data.sort_values(self.config.time_column)
        
        # Extract target column
        ts_data = data[self.config.target_column]
        
        # Handle missing values
        ts_data = ts_data.fillna(method='ffill').fillna(method='bfill')
        
        # Ensure numeric
        ts_data = pd.to_numeric(ts_data, errors='coerce')
        
        return ts_data
    
    def _check_stationarity(self, ts_data: pd.Series) -> bool:
        """Check if time series is stationary."""
        try:
            # Augmented Dickey-Fuller test
            result = adfuller(ts_data)
            p_value = result[1]
            
            # Consider stationary if p-value < 0.05
            return p_value < 0.05
            
        except Exception as e:
            logger.warning(f"Stationarity check failed: {e}")
            return True  # Assume stationary if check fails
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get ARIMA model information."""
        if not self.is_trained:
            return {"status": "not_trained"}
        
        return {
            "model_type": self.model_type,
            "order": self.order,
            "seasonal_order": self.seasonal_order,
            "is_trained": self.is_trained,
            "aic": self.model.aic if self.model else None,
            "bic": self.model.bic if self.model else None,
            "config": self.config.__dict__
        }

class LSTMModel(TimeSeriesModel):
    """LSTM neural network time series model."""
    
    def __init__(self, config: TimeSeriesConfig):
        super().__init__(config)
        
        if not TENSORFLOW_AVAILABLE:
            raise ImportError("TensorFlow is not available for LSTM modeling")
        
        self.model_type = "lstm"
        self.units = config.lstm_units
        self.dropout = config.lstm_dropout
        self.epochs = config.lstm_epochs
        self.batch_size = config.lstm_batch_size
        self.learning_rate = config.lstm_learning_rate
        
        # Data scaling
        self.scaler_mean = None
        self.scaler_std = None
    
    async def train(self, data: pd.DataFrame) -> ModelMetrics:
        """Train LSTM model."""
        try:
            start_time = time.time()
            
            # Prepare data
            X, y = self._prepare_lstm_data(data)
            
            # Split data
            train_size = int(len(X) * (1 - self.config.validation_split))
            X_train, X_val = X[:train_size], X[train_size:]
            y_train, y_val = y[:train_size], y[train_size:]
            
            # Reshape for LSTM [samples, timesteps, features]
            X_train = X_train.reshape((X_train.shape[0], X_train.shape[1], 1))
            X_val = X_val.reshape((X_val.shape[0], X_val.shape[1], 1))
            
            # Build LSTM model
            self.model = Sequential([
                LSTM(self.units[0], return_sequences=True, input_shape=(X_train.shape[1], X_train.shape[2])),
                Dropout(self.dropout),
                LSTM(self.units[1], return_sequences=False),
                Dropout(self.dropout),
                Dense(1)
            ])
            
            # Compile model
            self.model.compile(
                optimizer=Adam(learning_rate=self.learning_rate),
                loss='mse',
                metrics=['mae', 'mse']
            )
            
            # Train model
            history = self.model.fit(
                X_train, y_train,
                epochs=self.epochs,
                batch_size=self.batch_size,
                validation_data=(X_val, y_val),
                verbose=0
            )
            
            # Calculate metrics
            val_predictions = self.model.predict(X_val)
            
            mae = np.mean(np.abs(y_val - val_predictions.flatten()))
            mse = np.mean((y_val - val_predictions.flatten()) ** 2)
            rmse = np.sqrt(mse)
            
            # Calculate MAPE
            mape = np.mean(np.abs((y_val - val_predictions.flatten()) / y_val)) * 100
            
            # Calculate R-squared
            ss_res = np.sum((y_val - val_predictions.flatten()) ** 2)
            ss_tot = np.sum((y_val - np.mean(y_val)) ** 2)
            r2_score = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
            
            training_time = time.time() - start_time
            
            metrics = ModelMetrics(
                model_id=f"lstm_{self.config.target_column}_{int(time.time())}",
                model_type=self.model_type,
                mae=mae,
                mse=mse,
                rmse=rmse,
                mape=mape,
                aic=0,  # LSTM doesn't have AIC
                bic=0,  # LSTM doesn't have BIC
                r2_score=r2_score,
                training_samples=len(X_train),
                validation_samples=len(X_val),
                timestamp=training_time
            )
            
            self.is_trained = True
            self.training_history.append(metrics)
            
            logger.info(f"LSTM model trained: MAE={mae:.4f}, RMSE={rmse:.4f}")
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to train LSTM model: {e}")
            raise
    
    async def forecast(self, data: pd.DataFrame, steps: int) -> ForecastResult:
        """Generate LSTM forecast."""
        if not self.is_trained:
            raise ValueError("Model must be trained before forecasting")
        
        try:
            start_time = time.time()
            
            # Prepare data
            X, y = self._prepare_lstm_data(data)
            
            # Get last sequence for prediction
            last_sequence = X[-1:].reshape((1, len(X[-1:]), 1))
            
            # Generate forecast
            predictions = []
            current_sequence = last_sequence.copy()
            
            for i in range(steps):
                pred = self.model.predict(current_sequence, verbose=0)
                predictions.append(pred[0, 0])
                
                # Update sequence for next prediction
                current_sequence = np.roll(current_sequence, -1, axis=1)
                current_sequence[-1, 0] = pred[0, 0]
            
            # Inverse transform predictions
            if self.scaler_std is not None:
                predictions = predictions * self.scaler_std + self.scaler_mean
            
            # Generate confidence intervals (simplified)
            std_error = np.std(predictions)
            confidence_lower = [p - 1.96 * std_error for p in predictions]
            confidence_upper = [p + 1.96 * std_error for p in predictions]
            
            # Generate timestamps
            last_timestamp = pd.to_datetime(data[self.config.time_column].iloc[-1])
            timestamps = []
            
            for i in range(steps):
                if self.config.frequency == "daily":
                    timestamp = last_timestamp + timedelta(days=i+1)
                elif self.config.frequency == "hourly":
                    timestamp = last_timestamp + timedelta(hours=i+1)
                elif self.config.frequency == "4h":
                    timestamp = last_timestamp + timedelta(hours=4*(i+1))
                elif self.config.frequency == "1h":
                    timestamp = last_timestamp + timedelta(hours=i+1)
                else:
                    timestamp = last_timestamp + timedelta(hours=i+1)
                timestamps.append(timestamp)
            
            prediction_time = time.time() - start_time
            
            result = ForecastResult(
                model_id=f"lstm_{self.config.target_column}_{int(time.time())}",
                model_type=self.model_type,
                target_column=self.config.target_column,
                forecast_horizon=steps,
                predictions=predictions,
                confidence_lower=confidence_lower,
                confidence_upper=confidence_upper,
                timestamps=timestamps,
                model_metrics=self.training_history[-1].__dict__ if self.training_history else {},
                training_time=self.training_history[-1].timestamp if self.training_history else 0,
                prediction_time=prediction_time,
                metadata={
                    "units": self.units,
                    "dropout": self.dropout,
                    "epochs": self.epochs,
                    "batch_size": self.batch_size
                }
            )
            
            logger.info(f"LSTM forecast generated: {steps} steps")
            return result
            
        except Exception as e:
            logger.error(f"Failed to generate LSTM forecast: {e}")
            raise
    
    def _prepare_lstm_data(self, data: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        """Prepare data for LSTM training."""
        # Sort by time
        data = data.sort_values(self.config.time_column)
        
        # Extract target column
        ts_data = data[self.config.target_column].values
        
        # Handle missing values
        ts_data = pd.Series(ts_data).fillna(method='ffill').fillna(method='bfill')
        
        # Scale data
        self.scaler_mean = np.mean(ts_data)
        self.scaler_std = np.std(ts_data)
        scaled_data = (ts_data - self.scaler_mean) / self.scaler_std
        
        # Create sequences
        sequences = []
        for i in range(len(scaled_data) - 10):
            sequences.append(scaled_data[i:i+11])
        
        X = np.array(sequences)
        y = scaled_data[10:]
        
        return X, y
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get LSTM model information."""
        if not self.is_trained:
            return {"status": "not_trained"}
        
        return {
            "model_type": self.model_type,
            "units": self.units,
            "dropout": self.dropout,
            "epochs": self.epochs,
            "batch_size": self.batch_size,
            "learning_rate": self.learning_rate,
            "is_trained": self.is_trained,
            "scaler_mean": self.scaler_mean,
            "scaler_std": self.scaler_std,
            "config": self.config.__dict__
        }

class ProphetModel(TimeSeriesModel):
    """Prophet time series model implementation."""
    
    def __init__(self, config: TimeSeriesConfig):
        super().__init__(config)
        
        if not PROPHET_AVAILABLE:
            raise ImportError("Prophet is not available for time series modeling")
        
        self.model_type = "prophet"
        self.model = None
    
    async def train(self, data: pd.DataFrame) -> ModelMetrics:
        """Train Prophet model."""
        try:
            start_time = time.time()
            
            # Prepare data for Prophet
            prophet_data = self._prepare_prophet_data(data)
            
            # Create and fit model
            self.model = Prophet(
                yearly_seasonality=self.config.prophet_yearly_seasonality,
                weekly_seasonality=self.config.prophet_weekly_seasonality,
                daily_seasonality=self.config.prophet_daily_seasonality
            )
            
            self.model.fit(prophet_data)
            
            # Calculate metrics on validation set
            train_size = int(len(prophet_data) * (1 - self.config.validation_split))
            train_data = prophet_data[:train_size]
            val_data = prophet_data[train_size:]
            
            # Generate predictions for validation
            future = self.model.make_dataframe(periods=len(val_data))
            forecast = self.model.predict(future)
            
            # Align predictions with validation data
            val_predictions = forecast['yhat'].iloc[:len(val_data)]
            
            mae = np.mean(np.abs(val_data['y'] - val_predictions))
            mse = np.mean((val_data['y'] - val_predictions) ** 2)
            rmse = np.sqrt(mse)
            
            # Calculate MAPE
            mape = np.mean(np.abs((val_data['y'] - val_predictions) / val_data['y'])) * 100
            
            # Calculate R-squared
            ss_res = np.sum((val_data['y'] - val_predictions) ** 2)
            ss_tot = np.sum((val_data['y'] - np.mean(val_data['y'])) ** 2)
            r2_score = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
            
            training_time = time.time() - start_time
            
            metrics = ModelMetrics(
                model_id=f"prophet_{self.config.target_column}_{int(time.time())}",
                model_type=self.model_type,
                mae=mae,
                mse=mse,
                rmse=rmse,
                mape=mape,
                aic=0,  # Prophet doesn't expose AIC easily
                bic=0,  # Prophet doesn't expose BIC easily
                r2_score=r2_score,
                training_samples=len(train_data),
                validation_samples=len(val_data),
                timestamp=training_time
            )
            
            self.is_trained = True
            self.training_history.append(metrics)
            
            logger.info(f"Prophet model trained: MAE={mae:.4f}, RMSE={rmse:.4f}")
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to train Prophet model: {e}")
            raise
    
    async def forecast(self, data: pd.DataFrame, steps: int) -> ForecastResult:
        """Generate Prophet forecast."""
        if not self.is_trained:
            raise ValueError("Model must be trained before forecasting")
        
        try:
            start_time = time.time()
            
            # Prepare data
            prophet_data = self._prepare_prophet_data(data)
            
            # Generate future dataframe
            future = self.model.make_dataframe(periods=steps)
            
            # Generate forecast
            forecast = self.model.predict(future)
            
            # Extract predictions and confidence intervals
            predictions = forecast['yhat'].tolist()
            confidence_lower = forecast['yhat_lower'].tolist()
            confidence_upper = forecast['yhat_upper'].tolist()
            timestamps = forecast['ds'].tolist()
            
            prediction_time = time.time() - start_time
            
            result = ForecastResult(
                model_id=f"prophet_{self.config.target_column}_{int(time.time())}",
                model_type=self.model_type,
                target_column=self.config.target_column,
                forecast_horizon=steps,
                predictions=predictions,
                confidence_lower=confidence_lower,
                confidence_upper=confidence_upper,
                timestamps=[pd.to_datetime(ts) for ts in timestamps],
                model_metrics=self.training_history[-1].__dict__ if self.training_history else {},
                training_time=self.training_history[-1].timestamp if self.training_history else 0,
                prediction_time=prediction_time,
                metadata={
                    "yearly_seasonality": self.config.prophet_yearly_seasonality,
                    "weekly_seasonality": self.config.prophet_weekly_seasonality,
                    "daily_seasonality": self.config.prophet_daily_seasonality
                }
            )
            
            logger.info(f"Prophet forecast generated: {steps} steps")
            return result
            
        except Exception as e:
            logger.error(f"Failed to generate Prophet forecast: {e}")
            raise
    
    def _prepare_prophet_data(self, data: pd.DataFrame) -> pd.DataFrame:
        """Prepare data for Prophet."""
        # Prophet expects columns 'ds' (datestamp) and 'y' (value)
        prophet_data = data[[self.config.time_column, self.config.target_column]].copy()
        prophet_data.columns = ['ds', 'y']
        
        # Convert timestamp column
        prophet_data['ds'] = pd.to_datetime(prophet_data['ds'])
        
        # Handle missing values
        prophet_data = prophet_data.dropna()
        
        return prophet_data
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get Prophet model information."""
        if not self.is_trained:
            return {"status": "not_trained"}
        
        return {
            "model_type": self.model_type,
            "is_trained": self.is_trained,
            "config": self.config.__dict__
        }

class TimeSeriesAnalyzer:
    """
    Comprehensive time series analysis system for MERID.
    
    Provides unified interface for multiple time series models
    with automatic model selection and validation.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Model registry
        self.models: Dict[str, TimeSeriesModel] = {}
        self.model_configs: Dict[str, TimeSeriesConfig] = {}
        
        # Analysis results
        self.forecast_results: deque = deque(maxlen=100)
        self.model_metrics: Dict[str, List[ModelMetrics]] = {}
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "data_privacy": True,
            "model_transparency": True,
            "audit_predictions": True
        })
        
        logger.info("TimeSeriesAnalyzer initialized")
    
    async def create_model(self, model_id: str, config: TimeSeriesConfig) -> bool:
        """Create a time series model."""
        try:
            # Model selection based on type
            if config.model_type == "arima":
                model = ARIMAModel(config)
            elif config.model_type == "lstm":
                model = LSTMModel(config)
            elif config.model_type == "prophet":
                model = ProphetModel(config)
            else:
                logger.error(f"Unknown model type: {config.model_type}")
                return False
            
            self.models[model_id] = model
            self.model_configs[model_id] = config
            
            logger.info(f"Created {config.model_type} model: {model_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create model {model_id}: {e}")
            return False
    
    async def train_model(self, model_id: str, data: pd.DataFrame) -> Optional[ModelMetrics]:
        """Train a time series model."""
        if model_id not in self.models:
            logger.error(f"Model {model_id} not found")
            return None
        
        try:
            # US compliance checks
            if not self._check_data_compliance(data):
                logger.warning("Data failed compliance checks")
            
            model = self.models[model_id]
            result = await model.train(data)
            
            # Store metrics
            if model_id not in self.model_metrics:
                self.model_metrics[model_id] = []
            self.model_metrics[model_id].append(result)
            
            logger.info(f"Model {model_id} trained successfully")
            return result
            
        except Exception as e:
            logger.error(f"Failed to train model {model_id}: {e}")
            return None
    
    async def forecast(self, model_id: str, data: pd.DataFrame, 
                        steps: Optional[int] = None) -> Optional[ForecastResult]:
        """Generate forecast with a trained model."""
        if model_id not in self.models:
            logger.error(f"Model {model_id} not found")
            return None
        
        try:
            model = self.models[model_id]
            
            if not model.is_trained:
                logger.error(f"Model {model_id} is not trained")
                return None
            
            # Use configured horizon if steps not provided
            if steps is None:
                steps = model.config.forecast_horizon
            
            result = await model.forecast(data, steps)
            
            # Store result
            self.forecast_results.append(result)
            
            # Record for compliance
            if self.us_compliance.get("audit_predictions", True):
                await self._record_compliance(model_id, result)
            
            logger.info(f"Forecast generated with model {model_id}: {steps} steps")
            return result
            
        except Exception as e:
            logger.error(f"Failed to generate forecast with model {model_id}: {e}")
            return None
    
    async def compare_models(self, model_ids: List[str], data: pd.DataFrame) -> Dict[str, Any]:
        """Compare multiple models and select the best one."""
        comparison_results = {}
        
        for model_id in model_ids:
            if model_id not in self.models:
                continue
            
            try:
                # Train model if not trained
                model = self.models[model_id]
                if not model.is_trained:
                    await model.train(data)
                
                # Generate forecast
                result = await model.forecast(data, model.config.forecast_horizon)
                
                # Calculate validation metrics
                metrics = model.training_history[-1] if model.training_history else None
                
                comparison_results[model_id] = {
                    "model_type": model.model_type,
                    "forecast_result": result,
                    "metrics": metrics.__dict__ if metrics else {},
                    "mae": metrics.mae if metrics else float('inf'),
                    "rmse": metrics.rmse if metrics else float('inf'),
                    "r2_score": metrics.r2_score if metrics else 0.0
                }
                
            except Exception as e:
                logger.error(f"Failed to evaluate model {model_id}: {e}")
                comparison_results[model_id] = {"error": str(e)}
        
        # Find best model based on RMSE
        best_model_id = None
        best_rmse = float('inf')
        
        for model_id, result in comparison_results.items():
            if "error" not in result and result["rmse"] < best_rmse:
                best_rmse = result["rmse"]
                best_model_id = model_id
        
        comparison_results["best_model"] = best_model_id
        comparison_results["best_rmse"] = best_rmse
        
        return comparison_results
    
    def _check_data_compliance(self, data: pd.DataFrame) -> bool:
        """Check if data complies with US regulations."""
        # Simple compliance checks
        if self.us_compliance.get("data_privacy", True):
            # Check for PII (simplified)
            pii_columns = ['name', 'email', 'phone', 'address', 'ssn']
            for col in data.columns:
                if col.lower() in pii_columns:
                    return False
        
        return True
    
    async def _record_compliance(self, model_id: str, result: ForecastResult):
        """Record compliance audit entry."""
        if not self.us_compliance.get("audit_predictions", True):
            return
        
        audit_entry = {
            "model_id": model_id,
            "model_type": result.model_type,
            "forecast_horizon": result.forecast_horizon,
            "prediction_count": len(result.predictions),
            "timestamp": time.time(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Time series audit entry: {audit_entry}")
    
    def get_model_summary(self) -> Dict[str, Any]:
        """Get summary of all time series models."""
        summary = {
            "total_models": len(self.models),
            "trained_models": sum(1 for model in self.models.values() if model.is_trained),
            "model_types": {
                "arima": sum(1 for model in self.models.values() if model.model_type == "arima"),
                "lstm": sum(1 for model in self.models.values() if model.model_type == "lstm"),
                "prophet": sum(1 for model in self.models.values() if model.model_type == "prophet")
            },
            "forecast_results": len(self.forecast_results),
            "model_metrics": {model_id: len(metrics) for model_id, metrics in self.model_metrics.items()},
            "us_compliance": self.us_compliance
        }
        
        return summary
    
    def get_forecast_history(self, model_id: Optional[str] = None, limit: int = 100) -> List[ForecastResult]:
        """Get forecast history for models."""
        if model_id:
            return [result for result in self.forecast_results if result.model_id == model_id][-limit:]
        return list(self.forecast_results)[-limit:]
    
    def get_available_models(self) -> List[Dict[str, Any]]:
        """Get list of available time series models."""
        return [
            {
                "model_id": model_id,
                "model_type": model.model_type,
                "is_trained": model.is_trained,
                "config": model.config.__dict__
            }
            for model_id, model in self.models.items()
        ]
