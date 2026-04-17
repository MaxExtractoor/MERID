"""
Cross-Asset Strategy Engine for MERID Multi-Asset Expansion

Provides comprehensive cross-asset strategy development and execution
with US-compliant configuration.

Features:
- Cross-asset signal generation
- Multi-timeframe analysis
- Asset class rotation strategies
- Statistical arbitrage
- US-compliant strategy management
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

logger = get_logger("multi_asset.cross_asset_strategy")

class StrategyType(Enum):
    """Strategy type enumeration."""
    ASSET_ROTATION = "asset_rotation"
    STATISTICAL_ARBITRAGE = "statistical_arbitrage"
    PAIRS_TRADING = "pairs_trading"
    MOMENTUM_ROTATION = "momentum_rotation"
    MEAN_REVERSION = "mean_reversion"
    RISK_PARITY = "risk_parity"
    DIVERSIFICATION = "diversification"

class SignalStrength(Enum):
    """Signal strength enumeration."""
    VERY_STRONG = 5
    STRONG = 4
    MODERATE = 3
    WEAK = 2
    VERY_WEAK = 1

@dataclass
class CrossAssetSignal:
    """Cross-asset trading signal."""
    signal_id: str
    strategy_type: StrategyType
    symbols: List[str]
    signal_type: str  # long, short, neutral
    strength: SignalStrength
    confidence: float
    expected_return: float
    risk_score: float
    holding_period: int  # days
    entry_price: Dict[str, float]
    stop_loss: Dict[str, float]
    take_profit: Dict[str, float]
    position_sizes: Dict[str, float]
    correlation_risk: float
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class AssetRotationSignal:
    """Asset rotation strategy signal."""
    signal_id: str
    asset_classes: List[str]
    recommended_allocation: Dict[str, float]
    current_allocation: Dict[str, float]
    rotation_reason: str
    momentum_score: float
    risk_adjusted_score: float
    expected_return: float
    risk_score: float
    rebalance_urgency: str
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class PairsTradingSignal:
    """Pairs trading strategy signal."""
    signal_id: str
    pair: Tuple[str, str]
    spread: float
    z_score: float
    signal_type: str  # long_short, short_long, neutral
    entry_ratio: float
    stop_loss_ratio: float
    take_profit_ratio: float
    half_life: float
    correlation: float
    confidence: float
    expected_return: float
    holding_period: int
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)

class CrossAssetStrategyEngine:
    """
    Comprehensive cross-asset strategy engine for MERID.
    
    Provides multi-asset strategy development, signal generation,
    and execution with US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Strategy registry
        self.strategies: Dict[str, Dict[str, Any]] = {}
        
        # Signal history
        self.signal_history: deque = deque(maxlen=1000)
        self.active_signals: Dict[str, CrossAssetSignal] = {}
        
        # Asset class data
        self.asset_class_data: Dict[str, pd.DataFrame] = {}
        self.asset_class_metrics: Dict[str, Dict[str, float]] = {}
        
        # Strategy parameters
        self.strategy_params = config.get("strategy_parameters", {
            "min_signal_confidence": 0.6,
            "max_position_size": 0.2,
            "risk_limit": 0.02,
            "correlation_threshold": 0.7,
            "momentum_lookback": 20,
            "mean_reversion_lookback": 50
        })
        
        # Performance tracking
        self.strategy_performance: Dict[str, Dict[str, float]] = {}
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "strategy_validation": True,
            "risk_limits": True,
            "position_limits": True,
            "audit_strategies": True
        })
        
        logger.info("CrossAssetStrategyEngine initialized")
    
    async def register_strategy(self, strategy_id: str, strategy_config: Dict[str, Any]) -> bool:
        """Register a new cross-asset strategy."""
        try:
            # Validate strategy configuration
            if not self._validate_strategy_config(strategy_config):
                logger.error(f"Invalid strategy configuration: {strategy_id}")
                return False
            
            # Check for existing strategy
            if strategy_id in self.strategies:
                logger.warning(f"Strategy {strategy_id} already registered, updating")
            
            # Register strategy
            self.strategies[strategy_id] = {
                "config": strategy_config,
                "active": True,
                "created_at": time.time(),
                "last_updated": time.time(),
                "performance": {}
            }
            
            # Initialize performance tracking
            self.strategy_performance[strategy_id] = {
                "total_signals": 0,
                "successful_signals": 0,
                "avg_return": 0.0,
                "win_rate": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown": 0.0
            }
            
            # Record for compliance
            if self.us_compliance.get("audit_strategies", True):
                await self._record_strategy_registration(strategy_id, strategy_config)
            
            logger.info(f"Strategy registered: {strategy_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to register strategy {strategy_id}: {e}")
            return False
    
    def _validate_strategy_config(self, config: Dict[str, Any]) -> bool:
        """Validate strategy configuration."""
        try:
            # Basic validation
            if not config.get("name") or not config.get("type"):
                return False
            
            strategy_type = config.get("type")
            if not isinstance(strategy_type, str) or strategy_type not in [s.value for s in StrategyType]:
                return False
            
            # Validate strategy-specific parameters
            if strategy_type == StrategyType.ASSET_ROTATION.value:
                required_params = ["asset_classes", "rebalance_frequency", "momentum_period"]
                for param in required_params:
                    if param not in config:
                        return False
            
            elif strategy_type == StrategyType.PAIRS_TRADING.value:
                required_params = ["pairs", "lookback_period", "z_score_threshold"]
                for param in required_params:
                    if param not in config:
                        return False
            
            # US compliance checks
            if self.us_compliance.get("strategy_validation", True):
                if not self._validate_strategy_compliance(config):
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Strategy validation error: {e}")
            return False
    
    def _validate_strategy_compliance(self, config: Dict[str, Any]) -> bool:
        """Validate strategy for US compliance."""
        try:
            # In production, implement actual compliance validation
            # For now, basic checks
            
            # Check for restricted strategies
            restricted_strategies = []
            if config.get("type") in restricted_strategies:
                return False
            
            # Check for excessive leverage
            max_leverage = config.get("max_leverage", 1.0)
            if max_leverage > 3.0:  # US compliance limit
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Strategy compliance validation error: {e}")
            return False
    
    async def generate_asset_rotation_signal(self, strategy_id: str, 
                                            asset_class_data: Dict[str, pd.DataFrame]) -> Optional[AssetRotationSignal]:
        """Generate asset rotation strategy signal."""
        try:
            if strategy_id not in self.strategies:
                logger.error(f"Strategy {strategy_id} not found")
                return None
            
            strategy_config = self.strategies[strategy_id]["config"]
            asset_classes = strategy_config.get("asset_classes", [])
            momentum_period = strategy_config.get("momentum_period", 20)
            
            # Calculate momentum scores for each asset class
            momentum_scores = {}
            risk_adjusted_scores = {}
            
            for asset_class in asset_classes:
                if asset_class not in asset_class_data:
                    continue
                
                data = asset_class_data[asset_class]
                if len(data) < momentum_period:
                    continue
                
                # Calculate momentum (price change over period)
                current_price = data.iloc[-1]["price"]
                past_price = data.iloc[-momentum_period]["price"]
                momentum = (current_price - past_price) / past_price
                
                # Calculate volatility
                returns = data["price"].pct_change().dropna()
                volatility = returns.std() * np.sqrt(252)
                
                # Risk-adjusted momentum (Sharpe-like)
                risk_free_rate = 0.02
                risk_adjusted_score = (momentum - risk_free_rate) / volatility if volatility > 0 else 0
                
                momentum_scores[asset_class] = momentum
                risk_adjusted_scores[asset_class] = risk_adjusted_score
            
            if not momentum_scores:
                return None
            
            # Rank asset classes by risk-adjusted momentum
            ranked_classes = sorted(risk_adjusted_scores.items(), key=lambda x: x[1], reverse=True)
            
            # Calculate recommended allocation
            total_score = sum(abs(score) for score in risk_adjusted_scores.values())
            recommended_allocation = {}
            
            if total_score > 0:
                for asset_class, score in risk_adjusted_scores.items():
                    allocation = abs(score) / total_score
                    recommended_allocation[asset_class] = allocation
            
            # Get current allocation (mock)
            current_allocation = {ac: 1.0/len(asset_classes) for ac in asset_classes}
            
            # Determine rotation reason
            top_class = ranked_classes[0][0] if ranked_classes else asset_classes[0]
            rotation_reason = f"Rotating to {top_class} due to strong momentum"
            
            # Calculate overall metrics
            expected_return = sum(momentum_scores.get(ac, 0) * recommended_allocation.get(ac, 0) 
                                for ac in asset_classes)
            risk_score = np.std(list(momentum_scores.values())) if len(momentum_scores) > 1 else 0
            
            # Determine rebalance urgency
            allocation_diff = sum(abs(recommended_allocation.get(ac, 0) - current_allocation.get(ac, 0)) 
                                 for ac in asset_classes)
            
            if allocation_diff > 0.3:
                rebalance_urgency = "high"
            elif allocation_diff > 0.15:
                rebalance_urgency = "medium"
            else:
                rebalance_urgency = "low"
            
            # Create signal
            signal = AssetRotationSignal(
                signal_id=f"rotation_{int(time.time())}",
                asset_classes=asset_classes,
                recommended_allocation=recommended_allocation,
                current_allocation=current_allocation,
                rotation_reason=rotation_reason,
                momentum_score=risk_adjusted_scores.get(top_class, 0),
                risk_adjusted_score=expected_return,
                expected_return=expected_return,
                risk_score=risk_score,
                rebalance_urgency=rebalance_urgency,
                timestamp=time.time(),
                metadata={
                    "strategy_id": strategy_id,
                    "momentum_scores": momentum_scores,
                    "risk_adjusted_scores": risk_adjusted_scores
                }
            )
            
            # Store signal
            self.signal_history.append(signal)
            
            logger.info(f"Asset rotation signal generated: {top_class}")
            return signal
            
        except Exception as e:
            logger.error(f"Failed to generate asset rotation signal: {e}")
            return None
    
    async def generate_pairs_trading_signal(self, strategy_id: str, 
                                          pair_data: Dict[str, pd.DataFrame]) -> Optional[PairsTradingSignal]:
        """Generate pairs trading strategy signal."""
        try:
            if strategy_id not in self.strategies:
                logger.error(f"Strategy {strategy_id} not found")
                return None
            
            strategy_config = self.strategies[strategy_id]["config"]
            pairs = strategy_config.get("pairs", [])
            lookback_period = strategy_config.get("lookback_period", 50)
            z_score_threshold = strategy_config.get("z_score_threshold", 2.0)
            
            # Find best pair for trading
            best_signal = None
            best_z_score = 0
            
            for pair in pairs:
                if len(pair) != 2:
                    continue
                
                symbol1, symbol2 = pair
                
                if symbol1 not in pair_data or symbol2 not in pair_data:
                    continue
                
                # Get price data
                prices1 = pair_data[symbol1]["price"].tail(lookback_period)
                prices2 = pair_data[symbol2]["price"].tail(lookback_period)
                
                if len(prices1) < lookback_period or len(prices2) < lookback_period:
                    continue
                
                # Calculate spread
                # Use hedge ratio from linear regression
                X = prices2.values
                y = prices1.values
                
                # Simple linear regression for hedge ratio
                X_mean = np.mean(X)
                y_mean = np.mean(y)
                
                numerator = np.sum((X - X_mean) * (y - y_mean))
                denominator = np.sum((X - X_mean) ** 2)
                
                if denominator == 0:
                    continue
                
                hedge_ratio = numerator / denominator
                spread = y - hedge_ratio * X
                
                # Calculate z-score
                spread_mean = np.mean(spread)
                spread_std = np.std(spread)
                
                if spread_std == 0:
                    continue
                
                current_spread = spread[-1]
                z_score = (current_spread - spread_mean) / spread_std
                
                # Check if signal meets threshold
                if abs(z_score) < z_score_threshold:
                    continue
                
                # Determine signal type
                if z_score > 0:
                    signal_type = "short_long"  # Short symbol1, Long symbol2
                else:
                    signal_type = "long_short"  # Long symbol1, Short symbol2
                
                # Calculate correlation
                correlation = np.corrcoef(prices1, prices2)[0, 1]
                
                # Calculate half-life of mean reversion
                # Using Ornstein-Uhlenbeck process approximation
                spread_lag = spread.shift(1).dropna()
                spread_current = spread[1:].dropna()
                
                if len(spread_lag) > 1:
                    # Linear regression for mean reversion
                    X_lag = spread_lag.values
                    y_current = spread_current.values
                    
                    X_lag_mean = np.mean(X_lag)
                    y_current_mean = np.mean(y_current)
                    
                    numerator_lr = np.sum((X_lag - X_lag_mean) * (y_current - y_current_mean))
                    denominator_lr = np.sum((X_lag - X_lag_mean) ** 2)
                    
                    if denominator_lr > 0:
                        beta = numerator_lr / denominator_lr
                        half_life = -np.log(2) / np.log(beta) if beta > 0 and beta != 1 else 20
                    else:
                        half_life = 20
                else:
                    half_life = 20
                
                # Calculate expected return and confidence
                expected_return = abs(z_score) * spread_std / prices1.iloc[-1] * 100  # Percentage
                confidence = min(1.0, abs(z_score) / (z_score_threshold * 2))
                
                # Create signal
                signal = PairsTradingSignal(
                    signal_id=f"pairs_{int(time.time())}",
                    pair=(symbol1, symbol2),
                    spread=current_spread,
                    z_score=z_score,
                    signal_type=signal_type,
                    entry_ratio=hedge_ratio,
                    stop_loss_ratio=hedge_ratio * 1.1,  # 10% wider stop
                    take_profit_ratio=hedge_ratio * 0.9,  # 10% tighter take profit
                    half_life=half_life,
                    correlation=correlation,
                    confidence=confidence,
                    expected_return=expected_return,
                    holding_period=int(half_life * 2),  # 2x half-life
                    timestamp=time.time(),
                    metadata={
                        "strategy_id": strategy_id,
                        "spread_mean": spread_mean,
                        "spread_std": spread_std
                    }
                )
                
                # Keep best signal (highest absolute z-score)
                if abs(z_score) > best_z_score:
                    best_z_score = abs(z_score)
                    best_signal = signal
            
            if best_signal:
                # Store signal
                self.signal_history.append(best_signal)
                
                logger.info(f"Pairs trading signal generated: {best_signal.pair}")
                return best_signal
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to generate pairs trading signal: {e}")
            return None
    
    async def generate_momentum_rotation_signal(self, strategy_id: str, 
                                             asset_data: Dict[str, pd.DataFrame]) -> Optional[CrossAssetSignal]:
        """Generate momentum rotation strategy signal."""
        try:
            if strategy_id not in self.strategies:
                logger.error(f"Strategy {strategy_id} not found")
                return None
            
            strategy_config = self.strategies[strategy_id]["config"]
            lookback_period = strategy_config.get("momentum_lookback", 20)
            top_n = strategy_config.get("top_assets", 5)
            
            # Calculate momentum scores for all assets
            momentum_scores = {}
            
            for symbol, data in asset_data.items():
                if len(data) < lookback_period:
                    continue
                
                # Calculate momentum
                current_price = data.iloc[-1]["price"]
                past_price = data.iloc[-lookback_period]["price"]
                momentum = (current_price - past_price) / past_price
                
                # Calculate volatility for risk adjustment
                returns = data["price"].pct_change().dropna()
                volatility = returns.std() * np.sqrt(252)
                
                # Risk-adjusted momentum
                risk_adjusted_momentum = momentum / volatility if volatility > 0 else 0
                
                momentum_scores[symbol] = risk_adjusted_momentum
            
            if not momentum_scores:
                return None
            
            # Select top momentum assets
            ranked_assets = sorted(momentum_scores.items(), key=lambda x: x[1], reverse=True)
            top_assets = ranked_assets[:top_n]
            
            if len(top_assets) < 2:
                return None
            
            # Generate long signals for top assets
            symbols = [asset[0] for asset in top_assets]
            
            # Calculate position sizes (equal weight for simplicity)
            position_size = 1.0 / len(top_assets)
            position_sizes = {symbol: position_size for symbol in symbols}
            
            # Calculate entry prices, stop losses, and take profits
            entry_prices = {}
            stop_losses = {}
            take_profits = {}
            
            for symbol in symbols:
                current_data = asset_data[symbol].iloc[-1]
                entry_prices[symbol] = current_data["price"]
                
                # Use ATR-based stops (simplified)
                volatility = current_data.get("volatility", 0.02)
                stop_losses[symbol] = entry_prices[symbol] * (1 - 2 * volatility)
                take_profits[symbol] = entry_prices[symbol] * (1 + 3 * volatility)
            
            # Calculate overall metrics
            avg_momentum = np.mean([score for _, score in top_assets])
            expected_return = avg_momentum
            risk_score = np.std([score for _, score in top_assets])
            
            # Determine signal strength
            if avg_momentum > 0.1:
                strength = SignalStrength.VERY_STRONG
            elif avg_momentum > 0.05:
                strength = SignalStrength.STRONG
            elif avg_momentum > 0.02:
                strength = SignalStrength.MODERATE
            elif avg_momentum > 0:
                strength = SignalStrength.WEAK
            else:
                strength = SignalStrength.VERY_WEAK
            
            confidence = min(1.0, abs(avg_momentum) / 0.1)
            
            # Calculate correlation risk (simplified)
            correlation_risk = 0.5  # Default
            
            # Create signal
            signal = CrossAssetSignal(
                signal_id=f"momentum_{int(time.time())}",
                strategy_type=StrategyType.MOMENTUM_ROTATION,
                symbols=symbols,
                signal_type="long",
                strength=strength,
                confidence=confidence,
                expected_return=expected_return,
                risk_score=risk_score,
                holding_period=lookback_period,
                entry_price=entry_prices,
                stop_loss=stop_losses,
                take_profit=take_profits,
                position_sizes=position_sizes,
                correlation_risk=correlation_risk,
                timestamp=time.time(),
                metadata={
                    "strategy_id": strategy_id,
                    "momentum_scores": momentum_scores,
                    "ranked_assets": ranked_assets
                }
            )
            
            # Store signal
            self.signal_history.append(signal)
            self.active_signals[signal.signal_id] = signal
            
            logger.info(f"Momentum rotation signal generated: {len(symbols)} assets")
            return signal
            
        except Exception as e:
            logger.error(f"Failed to generate momentum rotation signal: {e}")
            return None
    
    async def generate_mean_reversion_signal(self, strategy_id: str, 
                                          asset_data: Dict[str, pd.DataFrame]) -> Optional[CrossAssetSignal]:
        """Generate mean reversion strategy signal."""
        try:
            if strategy_id not in self.strategies:
                logger.error(f"Strategy {strategy_id} not found")
                return None
            
            strategy_config = self.strategies[strategy_id]["config"]
            lookback_period = strategy_config.get("mean_reversion_lookback", 50)
            deviation_threshold = strategy_config.get("deviation_threshold", 2.0)
            
            # Find assets with significant mean reversion opportunities
            reversion_opportunities = []
            
            for symbol, data in asset_data.items():
                if len(data) < lookback_period:
                    continue
                
                prices = data["price"].tail(lookback_period)
                
                # Calculate mean and standard deviation
                mean_price = np.mean(prices)
                std_price = np.std(prices)
                
                if std_price == 0:
                    continue
                
                current_price = prices.iloc[-1]
                z_score = (current_price - mean_price) / std_price
                
                # Check if deviation is significant
                if abs(z_score) < deviation_threshold:
                    continue
                
                # Calculate expected reversion return
                if z_score > 0:  # Price is high, expect to go down
                    expected_return = -abs(z_score) * std_price / mean_price
                    signal_type = "short"
                else:  # Price is low, expect to go up
                    expected_return = abs(z_score) * std_price / mean_price
                    signal_type = "long"
                
                # Calculate confidence based on deviation
                confidence = min(1.0, abs(z_score) / (deviation_threshold * 2))
                
                reversion_opportunities.append({
                    "symbol": symbol,
                    "z_score": z_score,
                    "expected_return": expected_return,
                    "signal_type": signal_type,
                    "confidence": confidence,
                    "current_price": current_price,
                    "mean_price": mean_price,
                    "std_price": std_price
                })
            
            if not reversion_opportunities:
                return None
            
            # Select best opportunity (highest expected return)
            best_opportunity = max(reversion_opportunities, key=lambda x: abs(x["expected_return"]))
            
            symbol = best_opportunity["symbol"]
            signal_type = best_opportunity["signal_type"]
            
            # Calculate position size based on confidence
            position_size = best_opportunity["confidence"] * 0.1  # Max 10% position
            
            # Calculate entry, stop loss, and take profit
            entry_price = best_opportunity["current_price"]
            std_price = best_opportunity["std_price"]
            
            if signal_type == "long":
                stop_loss = entry_price - 2 * std_price
                take_profit = best_opportunity["mean_price"]
            else:
                stop_loss = entry_price + 2 * std_price
                take_profit = best_opportunity["mean_price"]
            
            # Determine signal strength
            abs_z_score = abs(best_opportunity["z_score"])
            if abs_z_score > 3:
                strength = SignalStrength.VERY_STRONG
            elif abs_z_score > 2.5:
                strength = SignalStrength.STRONG
            elif abs_z_score > 2:
                strength = SignalStrength.MODERATE
            else:
                strength = SignalStrength.WEAK
            
            # Create signal
            signal = CrossAssetSignal(
                signal_id=f"mean_rev_{int(time.time())}",
                strategy_type=StrategyType.MEAN_REVERSION,
                symbols=[symbol],
                signal_type=signal_type,
                strength=strength,
                confidence=best_opportunity["confidence"],
                expected_return=best_opportunity["expected_return"],
                risk_score=abs_z_score / 4.0,  # Normalize risk score
                holding_period=lookback_period // 2,  # Half the lookback period
                entry_price={symbol: entry_price},
                stop_loss={symbol: stop_loss},
                take_profit={symbol: take_profit},
                position_sizes={symbol: position_size},
                correlation_risk=0.0,  # Single asset
                timestamp=time.time(),
                metadata={
                    "strategy_id": strategy_id,
                    "z_score": best_opportunity["z_score"],
                    "mean_price": best_opportunity["mean_price"],
                    "std_price": std_price
                }
            )
            
            # Store signal
            self.signal_history.append(signal)
            self.active_signals[signal.signal_id] = signal
            
            logger.info(f"Mean reversion signal generated: {symbol} ({signal_type})")
            return signal
            
        except Exception as e:
            logger.error(f"Failed to generate mean reversion signal: {e}")
            return None
    
    async def execute_strategy(self, strategy_id: str, market_data: Dict[str, Any]) -> List[CrossAssetSignal]:
        """Execute a specific strategy."""
        try:
            if strategy_id not in self.strategies:
                logger.error(f"Strategy {strategy_id} not found")
                return []
            
            strategy_config = self.strategies[strategy_id]["config"]
            strategy_type = strategy_config.get("type")
            
            signals = []
            
            if strategy_type == StrategyType.ASSET_ROTATION.value:
                # Generate asset rotation signal
                asset_class_data = market_data.get("asset_class_data", {})
                signal = await self.generate_asset_rotation_signal(strategy_id, asset_class_data)
                if signal:
                    signals.append(signal)
            
            elif strategy_type == StrategyType.PAIRS_TRADING.value:
                # Generate pairs trading signal
                pair_data = market_data.get("pair_data", {})
                signal = await self.generate_pairs_trading_signal(strategy_id, pair_data)
                if signal:
                    signals.append(signal)
            
            elif strategy_type == StrategyType.MOMENTUM_ROTATION.value:
                # Generate momentum rotation signal
                asset_data = market_data.get("asset_data", {})
                signal = await self.generate_momentum_rotation_signal(strategy_id, asset_data)
                if signal:
                    signals.append(signal)
            
            elif strategy_type == StrategyType.MEAN_REVERSION.value:
                # Generate mean reversion signal
                asset_data = market_data.get("asset_data", {})
                signal = await self.generate_mean_reversion_signal(strategy_id, asset_data)
                if signal:
                    signals.append(signal)
            
            # Update strategy performance
            if signals:
                await self._update_strategy_performance(strategy_id, signals)
            
            return signals
            
        except Exception as e:
            logger.error(f"Failed to execute strategy {strategy_id}: {e}")
            return []
    
    async def execute_all_strategies(self, market_data: Dict[str, Any]) -> Dict[str, List[CrossAssetSignal]]:
        """Execute all active strategies."""
        try:
            all_signals = {}
            
            for strategy_id in self.strategies:
                if self.strategies[strategy_id]["active"]:
                    signals = await self.execute_strategy(strategy_id, market_data)
                    if signals:
                        all_signals[strategy_id] = signals
            
            logger.info(f"Executed {len(all_signals)} strategies")
            return all_signals
            
        except Exception as e:
            logger.error(f"Failed to execute all strategies: {e}")
            return {}
    
    async def _update_strategy_performance(self, strategy_id: str, signals: List[CrossAssetSignal]):
        """Update strategy performance metrics."""
        try:
            if strategy_id not in self.strategy_performance:
                return
            
            performance = self.strategy_performance[strategy_id]
            
            # Update signal count
            performance["total_signals"] += len(signals)
            
            # Calculate average expected return
            if signals:
                avg_return = np.mean([s.expected_return for s in signals])
                performance["avg_return"] = (performance["avg_return"] * (performance["total_signals"] - len(signals)) + 
                                           avg_return * len(signals)) / performance["total_signals"]
            
            # In production, track actual returns and update other metrics
            
        except Exception as e:
            logger.error(f"Failed to update strategy performance: {e}")
    
    async def _record_strategy_registration(self, strategy_id: str, config: Dict[str, Any]):
        """Record strategy registration for compliance."""
        if not self.us_compliance.get("audit_strategies", True):
            return
        
        audit_entry = {
            "action": "strategy_registration",
            "strategy_id": strategy_id,
            "strategy_type": config.get("type"),
            "strategy_name": config.get("name"),
            "timestamp": time.time(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Strategy registration audit entry: {audit_entry}")
    
    def get_active_signals(self) -> Dict[str, CrossAssetSignal]:
        """Get all active signals."""
        return self.active_signals.copy()
    
    def get_signal_history(self, limit: int = 100) -> List[CrossAssetSignal]:
        """Get signal history."""
        return list(self.signal_history)[-limit:]
    
    def get_strategy_performance(self, strategy_id: Optional[str] = None) -> Dict[str, Any]:
        """Get strategy performance metrics."""
        if strategy_id:
            return self.strategy_performance.get(strategy_id, {})
        return self.strategy_performance.copy()
    
    def get_strategies(self) -> Dict[str, Dict[str, Any]]:
        """Get all registered strategies."""
        return self.strategies.copy()
    
    def activate_strategy(self, strategy_id: str) -> bool:
        """Activate a strategy."""
        try:
            if strategy_id in self.strategies:
                self.strategies[strategy_id]["active"] = True
                logger.info(f"Strategy {strategy_id} activated")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to activate strategy {strategy_id}: {e}")
            return False
    
    def deactivate_strategy(self, strategy_id: str) -> bool:
        """Deactivate a strategy."""
        try:
            if strategy_id in self.strategies:
                self.strategies[strategy_id]["active"] = False
                logger.info(f"Strategy {strategy_id} deactivated")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to deactivate strategy {strategy_id}: {e}")
            return False
    
    def remove_strategy(self, strategy_id: str) -> bool:
        """Remove a strategy."""
        try:
            if strategy_id in self.strategies:
                del self.strategies[strategy_id]
                if strategy_id in self.strategy_performance:
                    del self.strategy_performance[strategy_id]
                logger.info(f"Strategy {strategy_id} removed")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to remove strategy {strategy_id}: {e}")
            return False
    
    def update_strategy_config(self, strategy_id: str, new_config: Dict[str, Any]) -> bool:
        """Update strategy configuration."""
        try:
            if strategy_id not in self.strategies:
                return False
            
            # Validate new configuration
            if not self._validate_strategy_config(new_config):
                return False
            
            # Update configuration
            self.strategies[strategy_id]["config"] = new_config
            self.strategies[strategy_id]["last_updated"] = time.time()
            
            logger.info(f"Strategy {strategy_id} configuration updated")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update strategy configuration: {e}")
            return False
    
    def get_strategy_summary(self) -> Dict[str, Any]:
        """Get comprehensive strategy summary."""
        try:
            total_strategies = len(self.strategies)
            active_strategies = sum(1 for s in self.strategies.values() if s["active"])
            
            # Strategy type distribution
            type_counts = {}
            for strategy in self.strategies.values():
                strategy_type = strategy["config"].get("type", "unknown")
                type_counts[strategy_type] = type_counts.get(strategy_type, 0) + 1
            
            # Signal statistics
            total_signals = len(self.signal_history)
            active_signals = len(self.active_signals)
            
            # Performance summary
            total_performance = {
                "total_signals": sum(p.get("total_signals", 0) for p in self.strategy_performance.values()),
                "avg_return": np.mean([p.get("avg_return", 0) for p in self.strategy_performance.values()]) if self.strategy_performance else 0,
                "win_rate": np.mean([p.get("win_rate", 0) for p in self.strategy_performance.values()]) if self.strategy_performance else 0
            }
            
            return {
                "total_strategies": total_strategies,
                "active_strategies": active_strategies,
                "strategy_types": type_counts,
                "signal_statistics": {
                    "total_signals": total_signals,
                    "active_signals": active_signals
                },
                "performance_summary": total_performance,
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get strategy summary: {e}")
            return {"status": "error", "error": str(e)}
