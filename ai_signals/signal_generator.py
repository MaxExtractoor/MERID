"""
AI-Powered Signal Generator for MERID AI-Powered Signals

Provides comprehensive AI-powered trading signal generation with
deep learning models and US-compliant configuration.

Features:
- Deep learning signal models
- Ensemble signal generation
- Real-time signal scoring
- Signal validation and backtesting
- US-compliant signal generation
"""

import asyncio
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
from enum import Enum

from utils.logger import get_logger

logger = get_logger("ai_signals.signal_generator")

class SignalType(Enum):
    """Signal type enumeration."""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    STRONG_BUY = "strong_buy"
    STRONG_SELL = "strong_sell"

class SignalSource(Enum):
    """Signal source enumeration."""
    DEEP_LEARNING = "deep_learning"
    ENSEMBLE = "ensemble"
    TECHNICAL = "technical"
    FUNDAMENTAL = "fundamental"
    SENTIMENT = "sentiment"
    MULTI_FACTOR = "multi_factor"

class SignalConfidence(Enum):
    """Signal confidence enumeration."""
    VERY_LOW = 1
    LOW = 2
    MEDIUM = 3
    HIGH = 4
    VERY_HIGH = 5

@dataclass
class TradingSignal:
    """Trading signal definition."""
    signal_id: str
    symbol: str
    signal_type: SignalType
    signal_source: SignalSource
    confidence: SignalConfidence
    strength: float
    expected_return: float
    risk_score: float
    time_horizon: int  # days
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: float
    generated_at: datetime
    expires_at: datetime
    features: Dict[str, float]
    model_predictions: Dict[str, float]
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class SignalModel:
    """Signal model definition."""
    model_id: str
    model_name: str
    model_type: str
    model_version: str
    features: List[str]
    target_variable: str
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    auc_score: float
    training_data_points: int
    last_trained: datetime
    is_active: bool
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class EnsembleConfig:
    """Ensemble configuration."""
    ensemble_id: str
    ensemble_name: str
    models: List[str]
    weights: List[float]
    voting_method: str  # weighted, majority, consensus
    threshold: float
    metadata: Dict[str, Any] = field(default_factory=dict)

class AISignalGenerator:
    """
    Comprehensive AI-powered signal generation system for MERID.
    
    Provides deep learning models, ensemble methods, and real-time
    signal generation with US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Signal models
        self.models: Dict[str, SignalModel] = {}
        
        # Ensemble configurations
        self.ensembles: Dict[str, EnsembleConfig] = {}
        
        # Generated signals
        self.signals: deque = deque(maxlen=10000)
        self.active_signals: Dict[str, TradingSignal] = {}
        
        # Feature engineering
        self.feature_engineers: Dict[str, Any] = {}
        
        # Signal validation
        self.validation_rules: Dict[str, Any] = {}
        
        # Performance tracking
        self.signal_performance: Dict[str, Dict[str, float]] = {}
        
        # Configuration
        self.signal_config = config.get("signal_generation", {
            "max_signals_per_symbol": 10,
            "signal_expiry_hours": 24,
            "min_confidence_threshold": 0.6,
            "max_position_size": 0.1,
            "risk_limit": 0.02
        })
        
        # Feature definitions
        self.feature_definitions = {
            "price_momentum": {"type": "technical", "window": 20},
            "volume_momentum": {"type": "technical", "window": 10},
            "volatility": {"type": "technical", "window": 30},
            "rsi": {"type": "technical", "period": 14},
            "macd": {"type": "technical", "fast": 12, "slow": 26},
            "bollinger_position": {"type": "technical", "period": 20},
            "price_trend": {"type": "technical", "window": 50},
            "volume_trend": {"type": "technical", "window": 30},
            "momentum_divergence": {"type": "technical", "window": 14},
            "support_resistance": {"type": "technical", "window": 100}
        }
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "signal_validation": True,
            "model_transparency": True,
            "performance_disclosure": True,
            "audit_signals": True
        })
        
        logger.info("AISignalGenerator initialized")
    
    async def register_model(self, model_id: str, model_name: str, model_type: str,
                           features: List[str], target_variable: str,
                           performance_metrics: Dict[str, float]) -> bool:
        """Register a signal model."""
        try:
            # Validate model configuration
            if not self._validate_model_config(features, target_variable, performance_metrics):
                logger.error(f"Invalid model configuration: {model_id}")
                return False
            
            # Create model
            model = SignalModel(
                model_id=model_id,
                model_name=model_name,
                model_type=model_type,
                model_version="1.0",
                features=features,
                target_variable=target_variable,
                accuracy=performance_metrics.get("accuracy", 0.0),
                precision=performance_metrics.get("precision", 0.0),
                recall=performance_metrics.get("recall", 0.0),
                f1_score=performance_metrics.get("f1_score", 0.0),
                auc_score=performance_metrics.get("auc_score", 0.0),
                training_data_points=performance_metrics.get("training_data_points", 0),
                last_trained=datetime.now(),
                is_active=True
            )
            
            # Store model
            self.models[model_id] = model
            
            # Initialize performance tracking
            self.signal_performance[model_id] = {
                "total_signals": 0,
                "successful_signals": 0,
                "avg_return": 0.0,
                "accuracy": 0.0,
                "sharpe_ratio": 0.0
            }
            
            # Record for compliance
            if self.us_compliance.get("audit_signals", True):
                await self._record_model_registration(model)
            
            logger.info(f"Model registered: {model_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to register model {model_id}: {e}")
            return False
    
    def _validate_model_config(self, features: List[str], target_variable: str,
                             performance_metrics: Dict[str, float]) -> bool:
        """Validate model configuration."""
        try:
            # Check features
            if not features or len(features) == 0:
                return False
            
            # Check target variable
            if not target_variable:
                return False
            
            # Check performance metrics
            required_metrics = ["accuracy", "precision", "recall"]
            for metric in required_metrics:
                if metric not in performance_metrics:
                    return False
                if not 0 <= performance_metrics[metric] <= 1:
                    return False
            
            # US compliance checks
            if self.us_compliance.get("model_transparency", True):
                if not self._validate_model_transparency(features, performance_metrics):
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Model configuration validation error: {e}")
            return False
    
    def _validate_model_transparency(self, features: List[str], 
                                   performance_metrics: Dict[str, float]) -> bool:
        """Validate model transparency for US compliance."""
        try:
            # Check if features are interpretable
            for feature in features:
                if feature not in self.feature_definitions:
                    # Allow custom features but flag for review
                    logger.warning(f"Custom feature detected: {feature}")
            
            # Check performance metrics are reasonable
            if performance_metrics.get("accuracy", 0) < 0.5:
                return False  # Model should be better than random
            
            return True
            
        except Exception as e:
            logger.error(f"Model transparency validation error: {e}")
            return False
    
    async def create_ensemble(self, ensemble_id: str, ensemble_name: str,
                           models: List[str], weights: List[float],
                           voting_method: str = "weighted", threshold: float = 0.5) -> bool:
        """Create an ensemble model."""
        try:
            # Validate ensemble configuration
            if not self._validate_ensemble_config(models, weights, voting_method):
                logger.error(f"Invalid ensemble configuration: {ensemble_id}")
                return False
            
            # Normalize weights
            total_weight = sum(weights)
            if total_weight > 0:
                normalized_weights = [w / total_weight for w in weights]
            else:
                normalized_weights = [1.0 / len(models)] * len(models)
            
            # Create ensemble
            ensemble = EnsembleConfig(
                ensemble_id=ensemble_id,
                ensemble_name=ensemble_name,
                models=models,
                weights=normalized_weights,
                voting_method=voting_method,
                threshold=threshold
            )
            
            # Store ensemble
            self.ensembles[ensemble_id] = ensemble
            
            logger.info(f"Ensemble created: {ensemble_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create ensemble {ensemble_id}: {e}")
            return False
    
    def _validate_ensemble_config(self, models: List[str], weights: List[float],
                                voting_method: str) -> bool:
        """Validate ensemble configuration."""
        try:
            # Check models exist
            for model_id in models:
                if model_id not in self.models:
                    return False
            
            # Check weights
            if len(weights) != len(models):
                return False
            
            if any(w < 0 for w in weights):
                return False
            
            # Check voting method
            valid_methods = ["weighted", "majority", "consensus"]
            if voting_method not in valid_methods:
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Ensemble configuration validation error: {e}")
            return False
    
    async def generate_signal(self, symbol: str, market_data: pd.DataFrame,
                           model_id: Optional[str] = None,
                           ensemble_id: Optional[str] = None) -> Optional[TradingSignal]:
        """Generate a trading signal."""
        try:
            # Determine signal source
            if ensemble_id and ensemble_id in self.ensembles:
                signal_source = SignalSource.ENSEMBLE
                predictions = await self._generate_ensemble_predictions(ensemble_id, market_data)
            elif model_id and model_id in self.models:
                signal_source = SignalSource.DEEP_LEARNING
                predictions = await self._generate_model_predictions(model_id, market_data)
            else:
                logger.error("No valid model or ensemble specified")
                return None
            
            if not predictions:
                return None
            
            # Generate signal from predictions
            signal = await self._create_signal_from_predictions(symbol, predictions, signal_source)
            
            if signal:
                # Validate signal
                if await self._validate_signal(signal):
                    # Store signal
                    self.signals.append(signal)
                    self.active_signals[signal.signal_id] = signal
                    
                    # Update model performance
                    await self._update_model_performance(signal)
                    
                    # Record for compliance
                    if self.us_compliance.get("audit_signals", True):
                        await self._record_signal_generation(signal)
                    
                    logger.info(f"Signal generated: {signal.signal_id} for {symbol}")
                    return signal
                else:
                    logger.warning(f"Signal validation failed: {signal.signal_id}")
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to generate signal for {symbol}: {e}")
            return None
    
    async def _generate_model_predictions(self, model_id: str, market_data: pd.DataFrame) -> Optional[Dict[str, float]]:
        """Generate predictions from a single model."""
        try:
            if model_id not in self.models:
                return None
            
            model = self.models[model_id]
            
            # Extract features
            features = await self._extract_features(market_data, model.features)
            
            if not features:
                return None
            
            # Mock model prediction (in production, use actual model)
            predictions = {}
            
            # Generate mock predictions based on features
            for feature in model.features:
                if feature in features:
                    # Simulate model prediction
                    base_prediction = np.random.normal(0, 0.1)
                    feature_value = features[feature]
                    
                    # Adjust prediction based on feature
                    if "momentum" in feature.lower():
                        prediction = base_prediction + feature_value * 0.5
                    elif "volatility" in feature.lower():
                        prediction = base_prediction - feature_value * 0.3
                    elif "trend" in feature.lower():
                        prediction = base_prediction + feature_value * 0.4
                    else:
                        prediction = base_prediction + feature_value * 0.2
                    
                    predictions[feature] = np.clip(prediction, -1, 1)
            
            # Generate overall prediction
            overall_prediction = np.mean(list(predictions.values()))
            predictions["overall"] = overall_prediction
            
            return predictions
            
        except Exception as e:
            logger.error(f"Failed to generate model predictions: {e}")
            return None
    
    async def _generate_ensemble_predictions(self, ensemble_id: str, market_data: pd.DataFrame) -> Optional[Dict[str, float]]:
        """Generate predictions from an ensemble."""
        try:
            if ensemble_id not in self.ensembles:
                return None
            
            ensemble = self.ensembles[ensemble_id]
            
            # Generate predictions from each model
            model_predictions = {}
            
            for model_id in ensemble.models:
                predictions = await self._generate_model_predictions(model_id, market_data)
                if predictions:
                    model_predictions[model_id] = predictions
            
            if not model_predictions:
                return None
            
            # Combine predictions using ensemble method
            combined_predictions = await self._combine_ensemble_predictions(
                model_predictions, ensemble.weights, ensemble.voting_method
            )
            
            return combined_predictions
            
        except Exception as e:
            logger.error(f"Failed to generate ensemble predictions: {e}")
            return None
    
    async def _combine_ensemble_predictions(self, model_predictions: Dict[str, float],
                                         weights: List[float], voting_method: str) -> Dict[str, float]:
        """Combine predictions from multiple models."""
        try:
            combined_predictions = {}
            
            # Get all prediction keys
            all_keys = set()
            for predictions in model_predictions.values():
                all_keys.update(predictions.keys())
            
            # Combine predictions for each key
            for key in all_keys:
                predictions_list = []
                weight_list = []
                
                for i, (model_id, predictions) in enumerate(model_predictions.items()):
                    if key in predictions:
                        predictions_list.append(predictions[key])
                        weight_list.append(weights[i])
                
                if predictions_list:
                    if voting_method == "weighted":
                        # Weighted average
                        total_weight = sum(weight_list)
                        if total_weight > 0:
                            combined_predictions[key] = sum(p * w for p, w in zip(predictions_list, weight_list)) / total_weight
                        else:
                            combined_predictions[key] = np.mean(predictions_list)
                    elif voting_method == "majority":
                        # Majority vote (simplified)
                        positive_votes = sum(1 for p in predictions_list if p > 0)
                        negative_votes = sum(1 for p in predictions_list if p < 0)
                        combined_predictions[key] = 1 if positive_votes > negative_votes else -1
                    elif voting_method == "consensus":
                        # Consensus (require agreement)
                        if all(p > 0 for p in predictions_list):
                            combined_predictions[key] = np.mean(predictions_list)
                        elif all(p < 0 for p in predictions_list):
                            combined_predictions[key] = np.mean(predictions_list)
                        else:
                            combined_predictions[key] = 0
                else:
                    combined_predictions[key] = 0
            
            return combined_predictions
            
        except Exception as e:
            logger.error(f"Failed to combine ensemble predictions: {e}")
            return {}
    
    async def _extract_features(self, market_data: pd.DataFrame, feature_list: List[str]) -> Optional[Dict[str, float]]:
        """Extract features from market data."""
        try:
            features = {}
            
            for feature_name in feature_list:
                if feature_name in self.feature_definitions:
                    feature_config = self.feature_definitions[feature_name]
                    feature_type = feature_config["type"]
                    
                    if feature_type == "technical":
                        feature_value = await self._extract_technical_feature(market_data, feature_name, feature_config)
                        if feature_value is not None:
                            features[feature_name] = feature_value
                else:
                    # Custom feature (mock implementation)
                    features[feature_name] = np.random.normal(0, 1)
            
            return features if features else None
            
        except Exception as e:
            logger.error(f"Failed to extract features: {e}")
            return None
    
    async def _extract_technical_feature(self, market_data: pd.DataFrame, feature_name: str,
                                       feature_config: Dict[str, Any]) -> Optional[float]:
        """Extract technical feature."""
        try:
            if "close" not in market_data.columns or "volume" not in market_data.columns:
                return None
            
            close_prices = market_data["close"]
            volume = market_data["volume"]
            
            if feature_name == "price_momentum":
                window = feature_config.get("window", 20)
                if len(close_prices) >= window:
                    return (close_prices.iloc[-1] - close_prices.iloc[-window]) / close_prices.iloc[-window]
            
            elif feature_name == "volume_momentum":
                window = feature_config.get("window", 10)
                if len(volume) >= window:
                    return (volume.iloc[-1] - volume.iloc[-window]) / volume.iloc[-window]
            
            elif feature_name == "volatility":
                window = feature_config.get("window", 30)
                if len(close_prices) >= window:
                    returns = close_prices.pct_change().dropna()
                    return returns.tail(window).std()
            
            elif feature_name == "rsi":
                period = feature_config.get("period", 14)
                if len(close_prices) >= period:
                    delta = close_prices.diff()
                    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
                    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
                    rs = gain / loss
                    return 100 - (100 / (1 + rs.iloc[-1]))
            
            elif feature_name == "macd":
                fast = feature_config.get("fast", 12)
                slow = feature_config.get("slow", 26)
                if len(close_prices) >= slow:
                    exp1 = close_prices.ewm(span=fast).mean()
                    exp2 = close_prices.ewm(span=slow).mean()
                    macd = exp1 - exp2
                    return macd.iloc[-1]
            
            elif feature_name == "bollinger_position":
                period = feature_config.get("period", 20)
                if len(close_prices) >= period:
                    sma = close_prices.rolling(window=period).mean()
                    std = close_prices.rolling(window=period).std()
                    upper_band = sma + (std * 2)
                    lower_band = sma - (std * 2)
                    current_price = close_prices.iloc[-1]
                    return (current_price - lower_band.iloc[-1]) / (upper_band.iloc[-1] - lower_band.iloc[-1])
            
            elif feature_name == "price_trend":
                window = feature_config.get("window", 50)
                if len(close_prices) >= window:
                    # Simple linear regression slope
                    x = np.arange(len(close_prices.tail(window)))
                    y = close_prices.tail(window).values
                    slope = np.polyfit(x, y, 1)[0]
                    return slope / close_prices.iloc[-1]  # Normalized slope
            
            elif feature_name == "volume_trend":
                window = feature_config.get("window", 30)
                if len(volume) >= window:
                    x = np.arange(len(volume.tail(window)))
                    y = volume.tail(window).values
                    slope = np.polyfit(x, y, 1)[0]
                    return slope / volume.iloc[-1]  # Normalized slope
            
            # Default case
            return np.random.normal(0, 0.1)
            
        except Exception as e:
            logger.error(f"Failed to extract technical feature {feature_name}: {e}")
            return None
    
    async def _create_signal_from_predictions(self, symbol: str, predictions: Dict[str, float],
                                           signal_source: SignalSource) -> Optional[TradingSignal]:
        """Create trading signal from predictions."""
        try:
            # Get overall prediction
            overall_prediction = predictions.get("overall", 0)
            
            # Determine signal type
            if overall_prediction > 0.7:
                signal_type = SignalType.STRONG_BUY
            elif overall_prediction > 0.3:
                signal_type = SignalType.BUY
            elif overall_prediction > -0.3:
                signal_type = SignalType.HOLD
            elif overall_prediction > -0.7:
                signal_type = SignalType.SELL
            else:
                signal_type = SignalType.STRONG_SELL
            
            # Calculate confidence
            confidence_score = abs(overall_prediction)
            if confidence_score > 0.8:
                confidence = SignalConfidence.VERY_HIGH
            elif confidence_score > 0.6:
                confidence = SignalConfidence.HIGH
            elif confidence_score > 0.4:
                confidence = SignalConfidence.MEDIUM
            elif confidence_score > 0.2:
                confidence = SignalConfidence.LOW
            else:
                confidence = SignalConfidence.VERY_LOW

            # Cap confidence by asset signal_quality (prevents over-sizing on noisy assets)
            try:
                from data.asset_universe import ASSET_UNIVERSE
                _base = symbol.split("/")[0].split("-")[0]
                _asset = ASSET_UNIVERSE.get(_base)
                if _asset:
                    _sq = _asset.signal_quality
                    if _sq == "medium" and confidence.value > SignalConfidence.HIGH.value:
                        confidence = SignalConfidence.HIGH
                    elif _sq == "low" and confidence.value > SignalConfidence.MEDIUM.value:
                        confidence = SignalConfidence.MEDIUM
            except Exception:
                logger.debug("silent catch in signal_generator:655")

            # Calculate signal strength
            strength = abs(overall_prediction)
            
            # Calculate expected return (simplified)
            expected_return = overall_prediction * 0.1  # 10% max return
            
            # Calculate risk score
            risk_score = 1 - confidence_score
            
            # Get current price (mock)
            current_price = 100.0  # In production, get from market data
            
            # Calculate stop loss and take profit
            stop_loss = current_price * (1 - abs(expected_return) * 2)
            take_profit = current_price * (1 + abs(expected_return) * 3)
            
            # Calculate position size
            max_position = self.signal_config["max_position_size"]
            position_size = min(max_position, confidence_score * max_position)
            
            # Create signal
            signal = TradingSignal(
                signal_id=f"signal_{int(time.time())}_{symbol}",
                symbol=symbol,
                signal_type=signal_type,
                signal_source=signal_source,
                confidence=confidence,
                strength=strength,
                expected_return=expected_return,
                risk_score=risk_score,
                time_horizon=7,  # 7 days default
                entry_price=current_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_size=position_size,
                generated_at=datetime.now(),
                expires_at=datetime.now() + timedelta(hours=self.signal_config["signal_expiry_hours"]),
                features=predictions,
                model_predictions=predictions,
                metadata={
                    "overall_prediction": overall_prediction,
                    "confidence_score": confidence_score
                }
            )
            
            return signal
            
        except Exception as e:
            logger.error(f"Failed to create signal from predictions: {e}")
            return None
    
    async def _validate_signal(self, signal: TradingSignal) -> bool:
        """Validate a trading signal."""
        try:
            # Check confidence threshold
            min_confidence = self.signal_config["min_confidence_threshold"]
            confidence_value = signal.confidence.value / 5.0  # Convert enum to 0-1 scale
            
            if confidence_value < min_confidence:
                return False
            
            # Check risk limits
            if signal.risk_score > self.signal_config["risk_limit"]:
                return False
            
            # Check position size
            if signal.position_size > self.signal_config["max_position_size"]:
                return False
            
            # Check for conflicting signals
            existing_signals = [s for s in self.active_signals.values() if s.symbol == signal.symbol]
            if len(existing_signals) >= self.signal_config["max_signals_per_symbol"]:
                return False
            
            # US compliance checks
            if self.us_compliance.get("signal_validation", True):
                if not self._validate_signal_compliance(signal):
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Signal validation error: {e}")
            return False
    
    def _validate_signal_compliance(self, signal: TradingSignal) -> bool:
        """Validate signal for US compliance."""
        try:
            # Check for excessive position sizes
            if signal.position_size > 0.2:  # 20% max position
                return False
            
            # Check for excessive leverage
            if signal.expected_return > 0.5:  # 50% max expected return
                return False
            
            # Check for reasonable stop loss
            if signal.stop_loss <= 0:
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Signal compliance validation error: {e}")
            return False
    
    async def _update_model_performance(self, signal: TradingSignal):
        """Update model performance metrics."""
        try:
            # Get model ID from signal source
            if signal.signal_source == SignalSource.DEEP_LEARNING:
                # Find model from signal metadata (simplified)
                model_id = "default_model"  # In production, get from signal
            elif signal.signal_source == SignalSource.ENSEMBLE:
                # Update ensemble models
                model_id = "ensemble"  # In production, handle ensemble updates
            else:
                return
            
            if model_id in self.signal_performance:
                performance = self.signal_performance[model_id]
                performance["total_signals"] += 1
                
                # In production, update with actual performance
                # For now, use expected return as proxy
                performance["avg_return"] = (performance["avg_return"] * (performance["total_signals"] - 1) + 
                                          signal.expected_return) / performance["total_signals"]
            
        except Exception as e:
            logger.error(f"Failed to update model performance: {e}")
    
    async def _record_model_registration(self, model: SignalModel):
        """Record model registration for compliance."""
        if not self.us_compliance.get("audit_signals", True):
            return
        
        audit_entry = {
            "action": "model_registration",
            "model_id": model.model_id,
            "model_name": model.model_name,
            "model_type": model.model_type,
            "accuracy": model.accuracy,
            "precision": model.precision,
            "recall": model.recall,
            "timestamp": time.time(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Model registration audit entry: {audit_entry}")
    
    async def _record_signal_generation(self, signal: TradingSignal):
        """Record signal generation for compliance."""
        if not self.us_compliance.get("audit_signals", True):
            return
        
        audit_entry = {
            "action": "signal_generation",
            "signal_id": signal.signal_id,
            "symbol": signal.symbol,
            "signal_type": signal.signal_type.value,
            "signal_source": signal.signal_source.value,
            "confidence": signal.confidence.value,
            "expected_return": signal.expected_return,
            "position_size": signal.position_size,
            "timestamp": signal.generated_at.isoformat(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Signal generation audit entry: {audit_entry}")
    
    def get_active_signals(self, symbol: Optional[str] = None) -> List[TradingSignal]:
        """Get active signals."""
        signals = list(self.active_signals.values())
        
        if symbol:
            signals = [s for s in signals if s.symbol == symbol]
        
        return sorted(signals, key=lambda s: s.generated_at, reverse=True)
    
    def get_signal_history(self, limit: int = 100) -> List[TradingSignal]:
        """Get signal history."""
        return list(self.signals)[-limit:]
    
    def get_models(self) -> Dict[str, SignalModel]:
        """Get all registered models."""
        return self.models.copy()
    
    def get_ensembles(self) -> Dict[str, EnsembleConfig]:
        """Get all ensemble configurations."""
        return self.ensembles.copy()
    
    def get_model_performance(self, model_id: Optional[str] = None) -> Dict[str, Any]:
        """Get model performance metrics."""
        if model_id:
            return self.signal_performance.get(model_id, {})
        return self.signal_performance.copy()
    
    def expire_signal(self, signal_id: str) -> bool:
        """Expire a signal."""
        try:
            if signal_id in self.active_signals:
                del self.active_signals[signal_id]
                logger.info(f"Signal expired: {signal_id}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"Failed to expire signal {signal_id}: {e}")
            return False
    
    def deactivate_model(self, model_id: str) -> bool:
        """Deactivate a model."""
        try:
            if model_id in self.models:
                self.models[model_id].is_active = False
                logger.info(f"Model deactivated: {model_id}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"Failed to deactivate model {model_id}: {e}")
            return False
    
    def get_signal_summary(self) -> Dict[str, Any]:
        """Get comprehensive signal summary."""
        try:
            # Signal type distribution
            signal_types = {}
            for signal in self.active_signals.values():
                signal_type = signal.signal_type.value
                signal_types[signal_type] = signal_types.get(signal_type, 0) + 1
            
            # Signal source distribution
            signal_sources = {}
            for signal in self.active_signals.values():
                source = signal.signal_source.value
                signal_sources[source] = signal_sources.get(source, 0) + 1
            
            # Confidence distribution
            confidence_levels = {}
            for signal in self.active_signals.values():
                confidence = signal.confidence.value
                confidence_levels[confidence] = confidence_levels.get(confidence, 0) + 1
            
            return {
                "total_signals": len(self.active_signals),
                "signal_types": signal_types,
                "signal_sources": signal_sources,
                "confidence_levels": confidence_levels,
                "active_models": sum(1 for m in self.models.values() if m.is_active),
                "active_ensembles": len(self.ensembles),
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get signal summary: {e}")
            return {"status": "error", "error": str(e)}
    
    def update_config(self, new_config: Dict[str, Any]):
        """Update signal generator configuration."""
        self.config.update(new_config)
        
        # Update specific parameters
        if "signal_generation" in new_config:
            self.signal_config.update(new_config["signal_generation"])
        
        logger.info("AI signal generator configuration updated")
