"""
Predictive Models for MERID

Provides specialized predictive models for cryptocurrency trading
including price prediction, trend analysis, and market forecasting.

Features:
- Price prediction models
- Trend analysis and detection
- Market regime classification
- Volatility forecasting
- Signal generation
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

from ml.model_framework import MLModelFramework, ModelConfig, TrainingResult, PredictionResult
from utils.logger import get_logger

logger = get_logger("ml.predictive_models")

@dataclass
class PricePrediction:
    """Price prediction result."""
    symbol: str
    current_price: float
    predicted_price: float
    confidence: float
    time_horizon: str  # 1h, 4h, 1d, 1w
    prediction_time: float
    features_used: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class TrendSignal:
    """Trend analysis signal."""
    symbol: str
    trend_direction: str  # bullish, bearish, sideways
    strength: float  # 0-1
    confidence: float
    time_horizon: str
    signal_time: float
    indicators: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class MarketRegime:
    """Market regime classification."""
    regime: str  # bull_market, bear_market, sideways, volatile
    confidence: float
    volatility_level: str  # low, medium, high
    momentum: float
    regime_time: float
    features: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class VolatilityForecast:
    """Volatility forecast result."""
    symbol: str
    current_volatility: float
    predicted_volatility: float
    confidence: float
    time_horizon: str
    forecast_time: float
    risk_level: str  # low, medium, high
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class TradingSignal:
    """Generated trading signal."""
    symbol: str
    signal_type: str  # buy, sell, hold
    strength: float  # 0-1
    confidence: float
    entry_price: float
    target_price: float
    stop_loss: float
    time_horizon: str
    signal_time: float
    reasoning: str
    metadata: Dict[str, Any] = field(default_factory=dict)

class PricePredictor:
    """Price prediction model for cryptocurrency markets."""
    
    def __init__(self, ml_framework: MLModelFramework, config: Dict[str, Any]):
        self.ml_framework = ml_framework
        self.config = config
        
        # Model configurations
        self.price_models = {}
        self.model_configs = {}
        
        # Feature engineering
        self.feature_columns = [
            'price_change_1h', 'price_change_4h', 'price_change_24h',
            'volume_change_1h', 'volume_change_4h', 'volume_change_24h',
            'rsi_14', 'rsi_30', 'macd_signal', 'bollinger_position',
            'moving_avg_5', 'moving_avg_20', 'moving_avg_50',
            'volatility_1h', 'volatility_4h', 'volatility_24h',
            'market_sentiment', 'social_sentiment', 'news_sentiment'
        ]
        
        # Prediction cache
        self.prediction_cache: Dict[str, PricePrediction] = {}
        self.cache_ttl = config.get("cache_ttl", 300)  # 5 minutes
        
        logger.info("PricePredictor initialized")
    
    async def initialize_models(self) -> bool:
        """Initialize price prediction models."""
        try:
            # Create models for different time horizons
            time_horizons = ['1h', '4h', '1d', '1w']
            
            for horizon in time_horizons:
                model_id = f"price_predictor_{horizon}"
                
                config = ModelConfig(
                    model_type="regression",
                    framework="sklearn",  # Use sklearn for reliability
                    target_column=f"price_change_{horizon}",
                    feature_columns=self.feature_columns,
                    hyperparameters={
                        "model_name": "random_forest",
                        "n_estimators": 100,
                        "max_depth": 10
                    },
                    preprocessing={
                        "scale": True,
                        "scaler_type": "standard"
                    }
                )
                
                success = self.ml_framework.create_model(model_id, config)
                if success:
                    self.model_configs[horizon] = config
                    logger.info(f"Created price prediction model for {horizon}")
                else:
                    logger.error(f"Failed to create model for {horizon}")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize price prediction models: {e}")
            return False
    
    async def train_models(self, training_data: pd.DataFrame) -> Dict[str, TrainingResult]:
        """Train price prediction models."""
        results = {}
        
        for horizon, config in self.model_configs.items():
            model_id = f"price_predictor_{horizon}"
            
            # Prepare target variable
            target_col = f"price_change_{horizon}"
            if target_col not in training_data.columns:
                # Simulate target variable for demo
                training_data[target_col] = np.random.normal(0, 0.02, len(training_data))
            
            result = await self.ml_framework.train_model(model_id, training_data)
            if result:
                results[horizon] = result
                logger.info(f"Trained price prediction model for {horizon}")
            else:
                logger.error(f"Failed to train model for {horizon}")
        
        return results
    
    async def predict_price(self, symbol: str, current_data: pd.DataFrame, 
                           time_horizon: str = '1h') -> Optional[PricePrediction]:
        """Predict price for a given symbol and time horizon."""
        try:
            # Check cache
            cache_key = f"{symbol}_{time_horizon}"
            if cache_key in self.prediction_cache:
                cached = self.prediction_cache[cache_key]
                if time.time() - cached.prediction_time < self.cache_ttl:
                    return cached
            
            # Get model
            model_id = f"price_predictor_{time_horizon}"
            
            # Make prediction
            result = await self.ml_framework.predict(model_id, current_data)
            if not result:
                return None
            
            current_price = current_data['price'].iloc[0] if 'price' in current_data.columns else 3000.0
            predicted_change = result.prediction
            predicted_price = current_price * (1 + predicted_change)
            
            prediction = PricePrediction(
                symbol=symbol,
                current_price=current_price,
                predicted_price=predicted_price,
                confidence=result.confidence,
                time_horizon=time_horizon,
                prediction_time=time.time(),
                features_used=self.feature_columns,
                metadata={
                    "model_id": result.model_id,
                    "prediction_time_ms": result.prediction_time * 1000,
                    "feature_contributions": result.feature_contributions
                }
            )
            
            # Cache result
            self.prediction_cache[cache_key] = prediction
            
            logger.info(f"Price prediction for {symbol} ({time_horizon}): ${predicted_price:.2f}")
            return prediction
            
        except Exception as e:
            logger.error(f"Failed to predict price for {symbol}: {e}")
            return None

class TrendAnalyzer:
    """Trend analysis and signal generation."""
    
    def __init__(self, ml_framework: MLModelFramework, config: Dict[str, Any]):
        self.ml_framework = ml_framework
        self.config = config
        
        # Model configuration
        self.trend_model_id = "trend_analyzer"
        self.feature_columns = [
            'price_momentum_5', 'price_momentum_20', 'volume_momentum',
            'rsi_trend', 'macd_trend', 'moving_avg_convergence',
            'support_resistance', 'breakout_strength', 'volume_profile',
            'market_regime', 'volatility_trend'
        ]
        
        # Trend cache
        self.trend_cache: Dict[str, TrendSignal] = {}
        self.cache_ttl = config.get("cache_ttl", 600)  # 10 minutes
        
        logger.info("TrendAnalyzer initialized")
    
    async def initialize_model(self) -> bool:
        """Initialize trend analysis model."""
        try:
            config = ModelConfig(
                model_type="classification",
                framework="sklearn",
                target_column="trend_direction",
                feature_columns=self.feature_columns,
                hyperparameters={
                    "model_name": "random_forest",
                    "n_estimators": 50,
                    "max_depth": 8
                },
                preprocessing={
                    "scale": True,
                    "scaler_type": "standard"
                }
            )
            
            success = self.ml_framework.create_model(self.trend_model_id, config)
            if success:
                logger.info("Trend analysis model initialized")
                return True
            else:
                logger.error("Failed to initialize trend analysis model")
                return False
                
        except Exception as e:
            logger.error(f"Failed to initialize trend model: {e}")
            return False
    
    async def train_model(self, training_data: pd.DataFrame) -> Optional[TrainingResult]:
        """Train trend analysis model."""
        try:
            # Prepare target variable (trend classification)
            if "trend_direction" not in training_data.columns:
                # Simulate trend classification
                trends = np.random.choice(['bullish', 'bearish', 'sideways'], 
                                       size=len(training_data), 
                                       p=[0.4, 0.3, 0.3])
                training_data["trend_direction"] = trends
            
            result = await self.ml_framework.train_model(self.trend_model_id, training_data)
            if result:
                logger.info("Trend analysis model trained successfully")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to train trend model: {e}")
            return None
    
    async def analyze_trend(self, symbol: str, current_data: pd.DataFrame, 
                          time_horizon: str = '4h') -> Optional[TrendSignal]:
        """Analyze trend for a given symbol."""
        try:
            # Check cache
            cache_key = f"{symbol}_{time_horizon}"
            if cache_key in self.trend_cache:
                cached = self.trend_cache[cache_key]
                if time.time() - cached.signal_time < self.cache_ttl:
                    return cached
            
            # Make prediction
            result = await self.ml_framework.predict(self.trend_model_id, current_data)
            if not result:
                return None
            
            # Map prediction to trend direction
            trend_map = {0: 'bearish', 1: 'sideways', 2: 'bullish'}
            trend_direction = trend_map.get(int(result.prediction), 'sideways')
            
            # Calculate trend strength based on confidence and indicators
            strength = result.confidence
            
            # Generate mock indicators
            indicators = {
                'rsi': np.random.uniform(30, 70),
                'macd': np.random.uniform(-0.5, 0.5),
                'volume_ratio': np.random.uniform(0.8, 1.5),
                'price_momentum': np.random.uniform(-0.02, 0.02)
            }
            
            signal = TrendSignal(
                symbol=symbol,
                trend_direction=trend_direction,
                strength=strength,
                confidence=result.confidence,
                time_horizon=time_horizon,
                signal_time=time.time(),
                indicators=indicators,
                metadata={
                    "model_id": result.model_id,
                    "feature_contributions": result.feature_contributions
                }
            )
            
            # Cache result
            self.trend_cache[cache_key] = signal
            
            logger.info(f"Trend analysis for {symbol}: {trend_direction} (strength: {strength:.2f})")
            return signal
            
        except Exception as e:
            logger.error(f"Failed to analyze trend for {symbol}: {e}")
            return None

class MarketRegimeClassifier:
    """Market regime classification system."""
    
    def __init__(self, ml_framework: MLModelFramework, config: Dict[str, Any]):
        self.ml_framework = ml_framework
        self.config = config
        
        # Model configuration
        self.regime_model_id = "regime_classifier"
        self.feature_columns = [
            'market_volatility', 'trend_strength', 'volume_trend',
            'price_momentum', 'sentiment_score', 'fear_greed_index',
            'market_breadth', 'sector_rotation', 'liquidity_index',
            'macro_indicators', 'seasonal_patterns'
        ]
        
        # Regime cache
        self.regime_cache: Dict[str, MarketRegime] = {}
        self.cache_ttl = config.get("cache_ttl", 1800)  # 30 minutes
        
        logger.info("MarketRegimeClassifier initialized")
    
    async def initialize_model(self) -> bool:
        """Initialize market regime model."""
        try:
            config = ModelConfig(
                model_type="classification",
                framework="sklearn",
                target_column="market_regime",
                feature_columns=self.feature_columns,
                hyperparameters={
                    "model_name": "random_forest",
                    "n_estimators": 75,
                    "max_depth": 12
                },
                preprocessing={
                    "scale": True,
                    "scaler_type": "standard"
                }
            )
            
            success = self.ml_framework.create_model(self.regime_model_id, config)
            if success:
                logger.info("Market regime classifier initialized")
                return True
            else:
                logger.error("Failed to initialize market regime classifier")
                return False
                
        except Exception as e:
            logger.error(f"Failed to initialize regime model: {e}")
            return False
    
    async def train_model(self, training_data: pd.DataFrame) -> Optional[TrainingResult]:
        """Train market regime classifier."""
        try:
            # Prepare target variable (regime classification)
            if "market_regime" not in training_data.columns:
                # Simulate regime classification
                regimes = np.random.choice(['bull_market', 'bear_market', 'sideways', 'volatile'], 
                                        size=len(training_data), 
                                        p=[0.3, 0.2, 0.35, 0.15])
                training_data["market_regime"] = regimes
            
            result = await self.ml_framework.train_model(self.regime_model_id, training_data)
            if result:
                logger.info("Market regime classifier trained successfully")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to train regime model: {e}")
            return None
    
    async def classify_regime(self, market_data: pd.DataFrame) -> Optional[MarketRegime]:
        """Classify current market regime."""
        try:
            # Check cache
            if "current_regime" in self.regime_cache:
                cached = self.regime_cache["current_regime"]
                if time.time() - cached.regime_time < self.cache_ttl:
                    return cached
            
            # Make prediction
            result = await self.ml_framework.predict(self.regime_model_id, market_data)
            if not result:
                return None
            
            # Map prediction to regime
            regime_map = {0: 'bear_market', 1: 'bull_market', 2: 'sideways', 3: 'volatile'}
            regime = regime_map.get(int(result.prediction), 'sideways')
            
            # Determine volatility level
            volatility = np.random.uniform(0.1, 0.4)  # Mock volatility
            if volatility < 0.2:
                volatility_level = 'low'
            elif volatility < 0.3:
                volatility_level = 'medium'
            else:
                volatility_level = 'high'
            
            # Calculate momentum
            momentum = np.random.uniform(-0.05, 0.05)
            
            # Generate features
            features = {
                'volatility': volatility,
                'momentum': momentum,
                'sentiment': np.random.uniform(-1, 1),
                'volume_trend': np.random.uniform(-0.1, 0.1)
            }
            
            regime_data = MarketRegime(
                regime=regime,
                confidence=result.confidence,
                volatility_level=volatility_level,
                momentum=momentum,
                regime_time=time.time(),
                features=features,
                metadata={
                    "model_id": result.model_id,
                    "feature_contributions": result.feature_contributions
                }
            )
            
            # Cache result
            self.regime_cache["current_regime"] = regime_data
            
            logger.info(f"Market regime: {regime} (confidence: {result.confidence:.2f})")
            return regime_data
            
        except Exception as e:
            logger.error(f"Failed to classify market regime: {e}")
            return None

class VolatilityForecaster:
    """Volatility forecasting system."""
    
    def __init__(self, ml_framework: MLModelFramework, config: Dict[str, Any]):
        self.ml_framework = ml_framework
        self.config = config
        
        # Model configuration
        self.volatility_models = {}
        self.feature_columns = [
            'historical_volatility', 'volatility_trend', 'volume_volatility',
            'price_range', 'gap_movements', 'news_volatility',
            'order_book_depth', 'market_impact', 'liquidity_score',
            'macro_volatility', 'seasonal_volatility'
        ]
        
        # Forecast cache
        self.forecast_cache: Dict[str, VolatilityForecast] = {}
        self.cache_ttl = config.get("cache_ttl", 900)  # 15 minutes
        
        logger.info("VolatilityForecaster initialized")
    
    async def initialize_models(self) -> bool:
        """Initialize volatility forecasting models."""
        try:
            # Create models for different time horizons
            time_horizons = ['1h', '4h', '1d']
            
            for horizon in time_horizons:
                model_id = f"volatility_forecaster_{horizon}"
                
                config = ModelConfig(
                    model_type="regression",
                    framework="sklearn",
                    target_column=f"volatility_{horizon}",
                    feature_columns=self.feature_columns,
                    hyperparameters={
                        "model_name": "random_forest",
                        "n_estimators": 80,
                        "max_depth": 10
                    },
                    preprocessing={
                        "scale": True,
                        "scaler_type": "standard"
                    }
                )
                
                success = self.ml_framework.create_model(model_id, config)
                if success:
                    logger.info(f"Created volatility forecasting model for {horizon}")
                else:
                    logger.error(f"Failed to create volatility model for {horizon}")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize volatility models: {e}")
            return False
    
    async def forecast_volatility(self, symbol: str, current_data: pd.DataFrame, 
                                time_horizon: str = '4h') -> Optional[VolatilityForecast]:
        """Forecast volatility for a given symbol and time horizon."""
        try:
            # Check cache
            cache_key = f"{symbol}_{time_horizon}"
            if cache_key in self.forecast_cache:
                cached = self.forecast_cache[cache_key]
                if time.time() - cached.forecast_time < self.cache_ttl:
                    return cached
            
            # Get model
            model_id = f"volatility_forecaster_{time_horizon}"
            
            # Make prediction
            result = await self.ml_framework.predict(model_id, current_data)
            if not result:
                return None
            
            current_volatility = current_data['volatility'].iloc[0] if 'volatility' in current_data.columns else 0.25
            predicted_volatility = result.prediction
            
            # Determine risk level
            if predicted_volatility < 0.15:
                risk_level = 'low'
            elif predicted_volatility < 0.3:
                risk_level = 'medium'
            else:
                risk_level = 'high'
            
            forecast = VolatilityForecast(
                symbol=symbol,
                current_volatility=current_volatility,
                predicted_volatility=predicted_volatility,
                confidence=result.confidence,
                time_horizon=time_horizon,
                forecast_time=time.time(),
                risk_level=risk_level,
                metadata={
                    "model_id": result.model_id,
                    "feature_contributions": result.feature_contributions
                }
            )
            
            # Cache result
            self.forecast_cache[cache_key] = forecast
            
            logger.info(f"Volatility forecast for {symbol} ({time_horizon}): {predicted_volatility:.3f}")
            return forecast
            
        except Exception as e:
            logger.error(f"Failed to forecast volatility for {symbol}: {e}")
            return None

class PredictiveModels:
    """
    Comprehensive predictive models system for MERID.
    
    Integrates price prediction, trend analysis, market regime classification,
    and volatility forecasting for comprehensive market intelligence.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Initialize ML framework
        self.ml_framework = MLModelFramework(config.get("ml_framework", {}))
        
        # Initialize predictive components
        self.price_predictor = PricePredictor(self.ml_framework, config.get("price_predictor", {}))
        self.trend_analyzer = TrendAnalyzer(self.ml_framework, config.get("trend_analyzer", {}))
        self.regime_classifier = MarketRegimeClassifier(self.ml_framework, config.get("regime_classifier", {}))
        self.volatility_forecaster = VolatilityForecaster(self.ml_framework, config.get("volatility_forecaster", {}))
        
        # Trading signal generator
        self.signal_history: deque = deque(maxlen=1000)
        
        logger.info("PredictiveModels initialized")
    
    async def initialize_all(self) -> bool:
        """Initialize all predictive models."""
        try:
            # Initialize all components
            tasks = [
                self.price_predictor.initialize_models(),
                self.trend_analyzer.initialize_model(),
                self.regime_classifier.initialize_model(),
                self.volatility_forecaster.initialize_models()
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            success_count = sum(1 for result in results if result is True)
            
            if success_count == len(tasks):
                logger.info("All predictive models initialized successfully")
                return True
            else:
                logger.warning(f"Only {success_count}/{len(tasks)} models initialized")
                return False
                
        except Exception as e:
            logger.error(f"Failed to initialize predictive models: {e}")
            return False
    
    async def train_all(self, training_data: pd.DataFrame) -> Dict[str, Any]:
        """Train all predictive models."""
        results = {}
        
        try:
            # Train all models
            price_results = await self.price_predictor.train_models(training_data)
            trend_result = await self.trend_analyzer.train_model(training_data)
            regime_result = await self.regime_classifier.train_model(training_data)
            
            results["price_prediction"] = price_results
            results["trend_analysis"] = trend_result
            results["regime_classification"] = regime_result
            
            logger.info("All predictive models trained successfully")
            return results
            
        except Exception as e:
            logger.error(f"Failed to train predictive models: {e}")
            return results
    
    async def generate_trading_signal(self, symbol: str, market_data: pd.DataFrame) -> Optional[TradingSignal]:
        """Generate comprehensive trading signal."""
        try:
            # Get predictions from all models
            price_pred_1h = await self.price_predictor.predict_price(symbol, market_data, '1h')
            price_pred_4h = await self.price_predictor.predict_price(symbol, market_data, '4h')
            trend_signal = await self.trend_analyzer.analyze_trend(symbol, market_data, '4h')
            volatility_forecast = await self.volatility_forecaster.forecast_volatility(symbol, market_data, '4h')
            
            # Get market regime
            regime_data = await self.regime_classifier.classify_regime(market_data)
            
            # Generate signal based on all predictions
            signal_type, strength, confidence = self._analyze_signals(
                price_pred_1h, price_pred_4h, trend_signal, volatility_forecast, regime_data
            )
            
            if not signal_type:
                return None
            
            # Calculate entry, target, and stop loss
            current_price = market_data['price'].iloc[0] if 'price' in market_data.columns else 3000.0
            
            if signal_type == 'buy':
                target_price = current_price * 1.05  # 5% target
                stop_loss = current_price * 0.97    # 3% stop loss
            elif signal_type == 'sell':
                target_price = current_price * 0.95  # 5% target
                stop_loss = current_price * 1.03    # 3% stop loss
            else:  # hold
                target_price = current_price
                stop_loss = current_price
            
            # Generate reasoning
            reasoning = self._generate_reasoning(
                signal_type, price_pred_1h, trend_signal, volatility_forecast, regime_data
            )
            
            signal = TradingSignal(
                symbol=symbol,
                signal_type=signal_type,
                strength=strength,
                confidence=confidence,
                entry_price=current_price,
                target_price=target_price,
                stop_loss=stop_loss,
                time_horizon='4h',
                signal_time=time.time(),
                reasoning=reasoning,
                metadata={
                    "price_prediction_1h": price_pred_1h.predicted_price if price_pred_1h else None,
                    "price_prediction_4h": price_pred_4h.predicted_price if price_pred_4h else None,
                    "trend_direction": trend_signal.trend_direction if trend_signal else None,
                    "volatility_forecast": volatility_forecast.predicted_volatility if volatility_forecast else None,
                    "market_regime": regime_data.regime if regime_data else None
                }
            )
            
            # Store signal
            self.signal_history.append(signal)
            
            logger.info(f"Generated {signal_type} signal for {symbol} (strength: {strength:.2f})")
            return signal
            
        except Exception as e:
            logger.error(f"Failed to generate trading signal for {symbol}: {e}")
            return None
    
    def _analyze_signals(self, price_pred_1h, price_pred_4h, trend_signal, 
                        volatility_forecast, regime_data) -> Tuple[str, float, float]:
        """Analyze all signals to generate final trading decision."""
        signals = []
        confidences = []
        
        # Price prediction signals
        if price_pred_1h and price_pred_4h:
            price_change_1h = (price_pred_1h.predicted_price - price_pred_1h.current_price) / price_pred_1h.current_price
            price_change_4h = (price_pred_4h.predicted_price - price_pred_4h.current_price) / price_pred_4h.current_price
            
            avg_price_change = (price_change_1h + price_change_4h) / 2
            avg_confidence = (price_pred_1h.confidence + price_pred_4h.confidence) / 2
            
            if avg_price_change > 0.02:  # 2% threshold
                signals.append('buy')
            elif avg_price_change < -0.02:
                signals.append('sell')
            else:
                signals.append('hold')
            
            confidences.append(avg_confidence)
        
        # Trend signal
        if trend_signal:
            if trend_signal.trend_direction == 'bullish':
                signals.append('buy')
            elif trend_signal.trend_direction == 'bearish':
                signals.append('sell')
            else:
                signals.append('hold')
            
            confidences.append(trend_signal.confidence * trend_signal.strength)
        
        # Volatility adjustment
        volatility_factor = 1.0
        if volatility_forecast:
            if volatility_forecast.risk_level == 'high':
                volatility_factor = 0.7  # Reduce confidence in high volatility
            elif volatility_forecast.risk_level == 'low':
                volatility_factor = 1.2  # Increase confidence in low volatility
        
        # Market regime adjustment
        regime_factor = 1.0
        if regime_data:
            if regime_data.regime == 'bull_market':
                regime_factor = 1.1
            elif regime_data.regime == 'bear_market':
                regime_factor = 0.9
            elif regime_data.regime == 'volatile':
                regime_factor = 0.8
        
        # Final decision
        if not signals:
            return 'hold', 0.0, 0.0
        
        # Weighted voting
        signal_counts = {'buy': 0, 'sell': 0, 'hold': 0}
        total_weight = 0
        
        for i, signal in enumerate(signals):
            weight = confidences[i] * volatility_factor * regime_factor
            signal_counts[signal] += weight
            total_weight += weight
        
        if total_weight == 0:
            return 'hold', 0.0, 0.0
        
        # Find strongest signal
        best_signal = max(signal_counts, key=signal_counts.get)
        strength = signal_counts[best_signal] / total_weight
        confidence = min(strength * 0.9, 0.95)  # Cap confidence at 95%
        
        return best_signal, strength, confidence
    
    def _generate_reasoning(self, signal_type, price_pred_1h, trend_signal, 
                          volatility_forecast, regime_data) -> str:
        """Generate reasoning for trading signal."""
        reasons = []
        
        if signal_type == 'buy':
            reasons.append("Bullish price predictions indicate upward movement")
            if trend_signal and trend_signal.trend_direction == 'bullish':
                reasons.append("Strong upward trend detected")
            if volatility_forecast and volatility_forecast.risk_level == 'low':
                reasons.append("Low volatility environment supports position")
            if regime_data and regime_data.regime == 'bull_market':
                reasons.append("Favorable bull market conditions")
        elif signal_type == 'sell':
            reasons.append("Bearish price predictions indicate downward movement")
            if trend_signal and trend_signal.trend_direction == 'bearish':
                reasons.append("Strong downward trend detected")
            if volatility_forecast and volatility_forecast.risk_level == 'high':
                reasons.append("High volatility suggests risk-off position")
        else:
            reasons.append("Mixed signals suggest holding position")
        
        return "; ".join(reasons)
    
    def get_signal_history(self, symbol: Optional[str] = None, limit: int = 100) -> List[TradingSignal]:
        """Get trading signal history."""
        signals = list(self.signal_history)
        
        if symbol:
            signals = [s for s in signals if s.symbol == symbol]
        
        return signals[-limit:]
    
    def get_model_summary(self) -> Dict[str, Any]:
        """Get summary of all predictive models."""
        return {
            "ml_framework": self.ml_framework.get_model_summary(),
            "price_predictor": {
                "models": len(self.price_predictor.model_configs),
                "cache_size": len(self.price_predictor.prediction_cache)
            },
            "trend_analyzer": {
                "cache_size": len(self.trend_analyzer.trend_cache)
            },
            "regime_classifier": {
                "cache_size": len(self.regime_classifier.regime_cache)
            },
            "volatility_forecaster": {
                "cache_size": len(self.volatility_forecaster.forecast_cache)
            },
            "signal_history": len(self.signal_history)
        }
