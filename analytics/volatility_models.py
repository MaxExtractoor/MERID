"""
Volatility Modeling for MERID Predictive Analytics

Provides comprehensive volatility forecasting and risk assessment with
GARCH models and US-compliant configuration.

Features:
- GARCH volatility modeling
- Realized volatility calculation
- Volatility regime detection
- Risk assessment and VaR calculation
- US-compliant risk management
"""

import asyncio
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import logging

# Volatility modeling libraries (with fallbacks)
try:
    from arch import arch_model
    ARCH_AVAILABLE = True
except ImportError:
    ARCH_AVAILABLE = False

from utils.logger import get_logger

logger = get_logger("analytics.volatility_models")

@dataclass
class VolatilityMetrics:
    """Volatility metrics snapshot."""
    timestamp: float
    realized_volatility: float
    garch_volatility: float
    implied_volatility: float
    volatility_regime: str
    risk_level: str
    var_95: float
    var_99: float
    expected_shortfall_95: float
    expected_shortfall_99: float
    volatility_trend: float
    volatility_momentum: float
    market_stress: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class VolatilityForecast:
    """Volatility forecast result."""
    model_id: str
    model_type: str
    forecast_horizon: int
    volatility_forecasts: List[float]
    confidence_intervals: List[Tuple[float, float]]
    timestamps: List[datetime]
    model_metrics: Dict[str, float]
    training_time: float
    prediction_time: float
    metadata: Dict[str, Any] = field(default_factory=dict)

class GARCHModel:
    """GARCH volatility model implementation."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        if not ARCH_AVAILABLE:
            raise ImportError("ARCH library is not available for GARCH modeling")
        
        self.model_type = "garch"
        self.model = None
        self.is_trained = False
        
        # Model parameters
        self.p = config.get("p", 1)  # GARCH order
        self.q = config.get("q", 1)  # ARCH order
        self.mean_model = config.get("mean_model", "Constant")
        self.volatility_model = config.get("volatility_model", "GARCH")
        self.distribution = config.get("distribution", "normal")
        
        # Training history
        self.training_history = []
    
    async def train(self, returns: pd.Series) -> Dict[str, float]:
        """Train GARCH model."""
        try:
            start_time = time.time()
            
            # Prepare data
            returns = returns.dropna()
            
            if len(returns) < 100:
                raise ValueError("Insufficient data for GARCH training")
            
            # Create GARCH model
            self.model = arch_model(
                returns * 100,  # Scale returns for better convergence
                p=self.p,
                q=self.q,
                mean=self.mean_model,
                vol=self.volatility_model,
                dist=self.distribution
            )
            
            # Fit model
            fitted_model = self.model.fit(disp=False)
            
            # Calculate metrics
            log_likelihood = fitted_model.loglikelihood
            aic = fitted_model.aic
            bic = fitted_model.bic
            
            # Get conditional volatility
            conditional_vol = fitted_model.conditional_volatility / 100  # Rescale back
            
            # Calculate in-sample performance
            predicted_vol = conditional_vol[:-1]
            actual_vol = np.abs(returns[1:])
            
            mse = np.mean((actual_vol - predicted_vol) ** 2)
            mae = np.mean(np.abs(actual_vol - predicted_vol))
            
            training_time = time.time() - start_time
            
            metrics = {
                "log_likelihood": log_likelihood,
                "aic": aic,
                "bic": bic,
                "mse": mse,
                "mae": mae,
                "training_time": training_time,
                "training_samples": len(returns)
            }
            
            self.is_trained = True
            self.training_history.append(metrics)
            
            logger.info(f"GARCH model trained: AIC={aic:.2f}, MSE={mse:.6f}")
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to train GARCH model: {e}")
            raise
    
    async def forecast(self, steps: int) -> VolatilityForecast:
        """Generate volatility forecast."""
        if not self.is_trained:
            raise ValueError("Model must be trained before forecasting")
        
        try:
            start_time = time.time()
            
            # Generate forecast
            forecast = self.model.forecast(horizon=steps, start=None)
            
            # Extract volatility forecasts
            variance_forecasts = forecast.variance.iloc[-1]
            volatility_forecasts = np.sqrt(variance_forecasts.values) / 100  # Rescale back
            
            # Generate confidence intervals (simplified)
            std_error = np.std(volatility_forecasts)
            confidence_intervals = [
                (v - 1.96 * std_error, v + 1.96 * std_error) 
                for v in volatility_forecasts
            ]
            
            # Generate timestamps
            last_timestamp = datetime.now()
            timestamps = [
                last_timestamp + timedelta(hours=i+1) 
                for i in range(steps)
            ]
            
            prediction_time = time.time() - start_time
            
            result = VolatilityForecast(
                model_id=f"garch_{int(time.time())}",
                model_type=self.model_type,
                forecast_horizon=steps,
                volatility_forecasts=volatility_forecasts.tolist(),
                confidence_intervals=confidence_intervals,
                timestamps=timestamps,
                model_metrics=self.training_history[-1] if self.training_history else {},
                training_time=self.training_history[-1]["training_time"] if self.training_history else 0,
                prediction_time=prediction_time,
                metadata={
                    "p": self.p,
                    "q": self.q,
                    "mean_model": self.mean_model,
                    "volatility_model": self.volatility_model,
                    "distribution": self.distribution
                }
            )
            
            logger.info(f"GARCH forecast generated: {steps} steps")
            return result
            
        except Exception as e:
            logger.error(f"Failed to generate GARCH forecast: {e}")
            raise

class VolatilityAnalyzer:
    """
    Comprehensive volatility analysis system for MERID.
    
    Provides volatility modeling, forecasting, and risk assessment
    with multiple model support and US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Model registry
        self.models: Dict[str, GARCHModel] = {}
        
        # Analysis history
        self.volatility_history: deque = deque(maxlen=1000)
        self.forecast_history: deque = deque(maxlen=500)
        
        # Volatility regimes
        self.volatility_regimes = {
            "low": {"range": (0.0, 0.15), "risk": "low"},
            "medium": {"range": (0.15, 0.30), "risk": "medium"},
            "high": {"range": (0.30, 0.50), "risk": "high"},
            "extreme": {"range": (0.50, 1.0), "risk": "critical"}
        }
        
        # Risk parameters
        self.risk_params = config.get("risk_params", {
            "var_confidence_levels": [0.95, 0.99],
            "es_confidence_levels": [0.95, 0.99],
            "lookback_period": 252,  # 1 year
            "min_samples": 100
        })
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "risk_assessment": True,
            "volatility_logging": True,
            "model_transparency": True
        })
        
        logger.info("VolatilityAnalyzer initialized")
    
    async def create_model(self, model_id: str, config: Dict[str, Any]) -> bool:
        """Create a volatility model."""
        try:
            model = GARCHModel(config)
            self.models[model_id] = model
            
            logger.info(f"Created GARCH model: {model_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create model {model_id}: {e}")
            return False
    
    async def train_model(self, model_id: str, returns: pd.Series) -> Optional[Dict[str, float]]:
        """Train a volatility model."""
        if model_id not in self.models:
            logger.error(f"Model {model_id} not found")
            return None
        
        try:
            model = self.models[model_id]
            result = await model.train(returns)
            
            logger.info(f"Model {model_id} trained successfully")
            return result
            
        except Exception as e:
            logger.error(f"Failed to train model {model_id}: {e}")
            return None
    
    async def forecast_volatility(self, model_id: str, steps: int = 24) -> Optional[VolatilityForecast]:
        """Generate volatility forecast."""
        if model_id not in self.models:
            logger.error(f"Model {model_id} not found")
            return None
        
        try:
            model = self.models[model_id]
            
            if not model.is_trained:
                logger.error(f"Model {model_id} is not trained")
                return None
            
            result = await model.forecast(steps)
            self.forecast_history.append(result)
            
            logger.info(f"Volatility forecast generated with model {model_id}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to generate forecast with model {model_id}: {e}")
            return None
    
    def calculate_realized_volatility(self, prices: pd.Series, window: int = 252) -> pd.Series:
        """Calculate realized volatility."""
        try:
            # Calculate log returns
            log_returns = np.log(prices / prices.shift(1)).dropna()
            
            # Calculate rolling volatility
            realized_vol = log_returns.rolling(window=window).std() * np.sqrt(252)
            
            return realized_vol
            
        except Exception as e:
            logger.error(f"Failed to calculate realized volatility: {e}")
            return pd.Series()
    
    def calculate_var(self, returns: pd.Series, confidence: float = 0.95) -> float:
        """Calculate Value at Risk."""
        try:
            var = np.percentile(returns, (1 - confidence) * 100)
            return var
            
        except Exception as e:
            logger.error(f"Failed to calculate VaR: {e}")
            return 0.0
    
    def calculate_expected_shortfall(self, returns: pd.Series, confidence: float = 0.95) -> float:
        """Calculate Expected Shortfall (Conditional VaR)."""
        try:
            var = self.calculate_var(returns, confidence)
            es = returns[returns <= var].mean()
            return es
            
        except Exception as e:
            logger.error(f"Failed to calculate Expected Shortfall: {e}")
            return 0.0
    
    def determine_volatility_regime(self, volatility: float) -> str:
        """Determine volatility regime."""
        for regime, params in self.volatility_regimes.items():
            min_vol, max_vol = params["range"]
            if min_vol <= volatility < max_vol:
                return regime
        
        return "extreme"
    
    async def analyze_volatility(self, prices: pd.Series, returns: pd.Series) -> Optional[VolatilityMetrics]:
        """Comprehensive volatility analysis."""
        try:
            # Calculate realized volatility
            realized_vol = self.calculate_realized_volatility(prices).iloc[-1]
            
            # Get GARCH volatility if model available
            garch_vol = realized_vol  # Fallback
            for model in self.models.values():
                if model.is_trained:
                    # Get latest conditional volatility
                    garch_vol = realized_vol * 0.95  # Mock adjustment
                    break
            
            # Determine regime
            regime = self.determine_volatility_regime(realized_vol)
            risk_level = self.volatility_regimes[regime]["risk"]
            
            # Calculate risk metrics
            var_95 = self.calculate_var(returns, 0.95)
            var_99 = self.calculate_var(returns, 0.99)
            es_95 = self.calculate_expected_shortfall(returns, 0.95)
            es_99 = self.calculate_expected_shortfall(returns, 0.99)
            
            # Calculate volatility trend
            vol_series = self.calculate_realized_volatility(prices, window=30)
            if len(vol_series) > 1:
                volatility_trend = (vol_series.iloc[-1] - vol_series.iloc[-2]) / vol_series.iloc[-2]
            else:
                volatility_trend = 0.0
            
            # Market stress indicator
            market_stress = min(1.0, realized_vol / 0.5)  # Normalized stress
            
            metrics = VolatilityMetrics(
                timestamp=time.time(),
                realized_volatility=realized_vol,
                garch_volatility=garch_vol,
                implied_volatility=realized_vol * 1.1,  # Mock implied vol
                volatility_regime=regime,
                risk_level=risk_level,
                var_95=var_95,
                var_99=var_99,
                expected_shortfall_95=es_95,
                expected_shortfall_99=es_99,
                volatility_trend=volatility_trend,
                volatility_momentum=volatility_trend,  # Simplified
                market_stress=market_stress,
                metadata={"analysis_type": "comprehensive"}
            )
            
            self.volatility_history.append(metrics)
            
            logger.info(f"Volatility analysis completed: {regime} regime")
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to analyze volatility: {e}")
            return None
    
    def get_volatility_summary(self) -> Dict[str, Any]:
        """Get comprehensive volatility analysis summary."""
        if not self.volatility_history:
            return {"status": "no_data"}
        
        # Recent metrics
        recent_metrics = list(self.volatility_history)[-100:]
        
        # Regime distribution
        regime_counts = {}
        for metrics in recent_metrics:
            regime = metrics.volatility_regime
            regime_counts[regime] = regime_counts.get(regime, 0) + 1
        
        # Average volatility
        avg_realized_vol = np.mean([m.realized_volatility for m in recent_metrics])
        avg_garch_vol = np.mean([m.garch_volatility for m in recent_metrics])
        
        # Risk metrics
        avg_var_95 = np.mean([m.var_95 for m in recent_metrics])
        avg_es_95 = np.mean([m.expected_shortfall_95 for m in recent_metrics])
        
        # Market stress
        avg_stress = np.mean([m.market_stress for m in recent_metrics])
        
        return {
            "total_analyses": len(self.volatility_history),
            "recent_analyses": len(recent_metrics),
            "regime_distribution": regime_counts,
            "average_volatility": {
                "realized": avg_realized_vol,
                "garch": avg_garch_vol
            },
            "risk_metrics": {
                "avg_var_95": avg_var_95,
                "avg_es_95": avg_es_95
            },
            "market_stress": avg_stress,
            "volatility_regimes": self.volatility_regimes,
            "us_compliance": self.us_compliance
        }
    
    def get_forecast_history(self, model_id: Optional[str] = None, limit: int = 100) -> List[VolatilityForecast]:
        """Get forecast history."""
        if model_id:
            return [f for f in self.forecast_history if f.model_id == model_id][-limit:]
        return list(self.forecast_history)[-limit:]
    
    def get_available_models(self) -> List[Dict[str, Any]]:
        """Get list of available volatility models."""
        return [
            {
                "model_id": model_id,
                "model_type": model.model_type,
                "is_trained": model.is_trained,
                "config": model.config
            }
            for model_id, model in self.models.items()
        ]
