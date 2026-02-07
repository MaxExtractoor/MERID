"""
Dynamic Position Sizing for MERID Advanced Risk Management

Provides comprehensive position sizing algorithms with volatility-based
risk management and US-compliant configuration.

Features:
- Volatility-based position sizing
- Kelly criterion implementation
- Fixed fractional position sizing
- Risk parity position sizing
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

from utils.logger import get_logger

logger = get_logger("risk.position_sizing")

@dataclass
class Position:
    """Position definition for sizing."""
    symbol: str
    current_price: float
    volatility: float
    beta: float = 1.0
    max_position_size: float = 1.0
    min_position_size: float = 0.01
    asset_class: str = "equity"
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class RiskParameters:
    """Risk management parameters."""
    max_portfolio_risk: float = 0.02  # 2% max portfolio risk
    max_position_risk: float = 0.01   # 1% max position risk
    max_correlation_exposure: float = 0.5
    stop_loss_atr_multiplier: float = 2.0
    take_profit_atr_multiplier: float = 3.0
    max_leverage: float = 2.0
    risk_free_rate: float = 0.02
    confidence_level: float = 0.95

@dataclass
class PositionSizingResult:
    """Position sizing result."""
    sizing_id: str
    symbol: str
    sizing_method: str
    position_size: float
    position_value: float
    risk_amount: float
    stop_loss_price: float
    take_profit_price: float
    shares: int
    risk_reward_ratio: float
    confidence_score: float
    sizing_time: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class PortfolioRisk:
    """Portfolio risk metrics."""
    total_risk: float
    position_risks: Dict[str, float]
    correlation_risk: float
    leverage: float
    var_95: float
    expected_shortfall: float
    risk_budget_used: float
    risk_capacity: float
    metadata: Dict[str, Any] = field(default_factory=dict)

class PositionSizer:
    """
    Advanced position sizing system for MERID.
    
    Provides multiple position sizing algorithms with risk management
    and US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Position universe
        self.positions: Dict[str, Position] = {}
        
        # Risk parameters
        self.risk_params = RiskParameters(**config.get("risk_parameters", {}))
        
        # Portfolio state
        self.current_positions: Dict[str, float] = {}  # symbol -> position_size
        self.portfolio_value: float = config.get("portfolio_value", 1000000.0)
        
        # Sizing history
        self.sizing_history: deque = deque(maxlen=1000)
        
        # Sizing methods
        self.sizing_methods = config.get("sizing_methods", [
            "volatility_based", "kelly_criterion", "fixed_fractional", "risk_parity"
        ])
        
        # Correlation matrix
        self.correlation_matrix: Optional[np.ndarray] = None
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "position_limits": True,
            "risk_limits": True,
            "leverage_limits": True,
            "audit_sizing": True
        })
        
        logger.info("PositionSizer initialized")
    
    def add_position(self, position: Position) -> bool:
        """Add position to sizing universe."""
        try:
            self.positions[position.symbol] = position
            logger.info(f"Added position {position.symbol} to sizing universe")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add position {position.symbol}: {e}")
            return False
    
    def update_correlation_matrix(self, correlation_matrix: np.ndarray) -> bool:
        """Update correlation matrix for risk calculations."""
        try:
            position_symbols = list(self.positions.keys())
            
            if correlation_matrix.shape != (len(position_symbols), len(position_symbols)):
                logger.error("Correlation matrix dimensions don't match position count")
                return False
            
            self.correlation_matrix = correlation_matrix
            logger.info(f"Updated correlation matrix for {len(position_symbols)} positions")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update correlation matrix: {e}")
            return False
    
    async def calculate_position_size(self, symbol: str, method: str = "volatility_based",
                                    signal_strength: float = 1.0,
                                    portfolio_context: Optional[Dict[str, Any]] = None) -> Optional[PositionSizingResult]:
        """Calculate optimal position size using specified method."""
        try:
            start_time = time.time()
            
            if symbol not in self.positions:
                logger.error(f"Position {symbol} not found")
                return None
            
            position = self.positions[symbol]
            
            # Select sizing method
            if method == "volatility_based":
                result = await self._volatility_based_sizing(position, signal_strength, portfolio_context)
            elif method == "kelly_criterion":
                result = await self._kelly_criterion_sizing(position, signal_strength, portfolio_context)
            elif method == "fixed_fractional":
                result = await self._fixed_fractional_sizing(position, signal_strength, portfolio_context)
            elif method == "risk_parity":
                result = await self._risk_parity_sizing(position, signal_strength, portfolio_context)
            else:
                logger.error(f"Unknown sizing method: {method}")
                return None
            
            if result:
                result.sizing_time = time.time() - start_time
                
                # Store result
                self.sizing_history.append(result)
                
                # Record for compliance
                if self.us_compliance.get("audit_sizing", True):
                    await self._record_compliance(result)
                
                logger.info(f"Position sizing completed: {symbol}, size: {result.position_size:.4f}")
                return result
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to calculate position size: {e}")
            return None
    
    async def _volatility_based_sizing(self, position: Position, signal_strength: float,
                                     portfolio_context: Optional[Dict[str, Any]]) -> PositionSizingResult:
        """Volatility-based position sizing."""
        try:
            # Calculate ATR (simplified as 2 * daily volatility)
            atr = 2 * position.volatility * position.current_price
            
            # Risk per share
            risk_per_share = atr * self.risk_params.stop_loss_atr_multiplier
            
            # Position size based on risk
            max_risk_amount = self.portfolio_value * self.risk_params.max_position_risk
            shares = int(max_risk_amount / risk_per_share)
            
            # Apply signal strength
            shares = int(shares * signal_strength)
            
            # Calculate position value
            position_value = shares * position.current_price
            position_size = position_value / self.portfolio_value
            
            # Apply position limits
            position_size = np.clip(position_size, position.min_position_size, position.max_position_size)
            
            # Recalculate shares
            shares = int((position_size * self.portfolio_value) / position.current_price)
            position_value = shares * position.current_price
            
            # Stop loss and take profit
            stop_loss_price = position.current_price - (atr * self.risk_params.stop_loss_atr_multiplier)
            take_profit_price = position.current_price + (atr * self.risk_params.take_profit_atr_multiplier)
            
            # Risk amount
            risk_amount = shares * (position.current_price - stop_loss_price)
            
            # Risk-reward ratio
            profit_potential = take_profit_price - position.current_price
            risk_amount_per_share = position.current_price - stop_loss_price
            risk_reward_ratio = profit_potential / risk_amount_per_share if risk_amount_per_share > 0 else 0
            
            # Confidence score
            confidence_score = min(1.0, signal_strength * (1.0 / position.volatility))
            
            return PositionSizingResult(
                sizing_id=f"vol_{int(time.time())}",
                symbol=position.symbol,
                sizing_method="volatility_based",
                position_size=position_size,
                position_value=position_value,
                risk_amount=risk_amount,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                shares=shares,
                risk_reward_ratio=risk_reward_ratio,
                confidence_score=confidence_score,
                sizing_time=0.0,
                metadata={
                    "atr": atr,
                    "signal_strength": signal_strength,
                    "volatility": position.volatility
                }
            )
            
        except Exception as e:
            logger.error(f"Volatility-based sizing failed: {e}")
            raise
    
    async def _kelly_criterion_sizing(self, position: Position, signal_strength: float,
                                   portfolio_context: Optional[Dict[str, Any]]) -> PositionSizingResult:
        """Kelly criterion position sizing."""
        try:
            # Expected return (simplified - based on signal strength)
            win_rate = 0.5 + (signal_strength * 0.3)  # 50% to 80% win rate
            avg_win = position.volatility * position.current_price * 3  # 3x volatility
            avg_loss = position.volatility * position.current_price * 1  # 1x volatility
            
            # Kelly fraction
            if avg_loss > 0:
                kelly_fraction = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_loss
            else:
                kelly_fraction = 0.0
            
            # Apply Kelly fraction with safety factor (half-Kelly)
            kelly_fraction = max(0, min(kelly_fraction * 0.5, 0.25))  # Cap at 25%
            
            # Position size
            position_size = kelly_fraction * signal_strength
            position_size = np.clip(position_size, position.min_position_size, position.max_position_size)
            
            # Calculate shares and value
            position_value = position_size * self.portfolio_value
            shares = int(position_value / position.current_price)
            position_value = shares * position.current_price
            
            # Stop loss and take profit
            atr = 2 * position.volatility * position.current_price
            stop_loss_price = position.current_price - (atr * self.risk_params.stop_loss_atr_multiplier)
            take_profit_price = position.current_price + (atr * self.risk_params.take_profit_atr_multiplier)
            
            # Risk amount
            risk_amount = shares * (position.current_price - stop_loss_price)
            
            # Risk-reward ratio
            profit_potential = take_profit_price - position.current_price
            risk_amount_per_share = position.current_price - stop_loss_price
            risk_reward_ratio = profit_potential / risk_amount_per_share if risk_amount_per_share > 0 else 0
            
            # Confidence score
            confidence_score = min(1.0, signal_strength * win_rate)
            
            return PositionSizingResult(
                sizing_id=f"kelly_{int(time.time())}",
                symbol=position.symbol,
                sizing_method="kelly_criterion",
                position_size=position_size,
                position_value=position_value,
                risk_amount=risk_amount,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                shares=shares,
                risk_reward_ratio=risk_reward_ratio,
                confidence_score=confidence_score,
                sizing_time=0.0,
                metadata={
                    "kelly_fraction": kelly_fraction,
                    "win_rate": win_rate,
                    "signal_strength": signal_strength
                }
            )
            
        except Exception as e:
            logger.error(f"Kelly criterion sizing failed: {e}")
            raise
    
    async def _fixed_fractional_sizing(self, position: Position, signal_strength: float,
                                     portfolio_context: Optional[Dict[str, Any]]) -> PositionSizingResult:
        """Fixed fractional position sizing."""
        try:
            # Fixed fraction (e.g., 2% of portfolio per position)
            fixed_fraction = 0.02  # 2% default
            
            # Adjust for volatility (lower volatility = larger position)
            volatility_adjustment = 0.2 / max(position.volatility, 0.1)  # Normalize around 20% vol
            volatility_adjustment = min(volatility_adjustment, 2.0)  # Cap at 2x
            
            # Calculate position size
            position_size = fixed_fraction * volatility_adjustment * signal_strength
            position_size = np.clip(position_size, position.min_position_size, position.max_position_size)
            
            # Calculate shares and value
            position_value = position_size * self.portfolio_value
            shares = int(position_value / position.current_price)
            position_value = shares * position.current_price
            
            # Stop loss and take profit
            atr = 2 * position.volatility * position.current_price
            stop_loss_price = position.current_price - (atr * self.risk_params.stop_loss_atr_multiplier)
            take_profit_price = position.current_price + (atr * self.risk_params.take_profit_atr_multiplier)
            
            # Risk amount
            risk_amount = shares * (position.current_price - stop_loss_price)
            
            # Risk-reward ratio
            profit_potential = take_profit_price - position.current_price
            risk_amount_per_share = position.current_price - stop_loss_price
            risk_reward_ratio = profit_potential / risk_amount_per_share if risk_amount_per_share > 0 else 0
            
            # Confidence score
            confidence_score = min(1.0, signal_strength * volatility_adjustment)
            
            return PositionSizingResult(
                sizing_id=f"fixed_{int(time.time())}",
                symbol=position.symbol,
                sizing_method="fixed_fractional",
                position_size=position_size,
                position_value=position_value,
                risk_amount=risk_amount,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                shares=shares,
                risk_reward_ratio=risk_reward_ratio,
                confidence_score=confidence_score,
                sizing_time=0.0,
                metadata={
                    "fixed_fraction": fixed_fraction,
                    "volatility_adjustment": volatility_adjustment,
                    "signal_strength": signal_strength
                }
            )
            
        except Exception as e:
            logger.error(f"Fixed fractional sizing failed: {e}")
            raise
    
    async def _risk_parity_sizing(self, position: Position, signal_strength: float,
                                portfolio_context: Optional[Dict[str, Any]]) -> PositionSizingResult:
        """Risk parity position sizing."""
        try:
            # Calculate risk contribution target
            n_positions = len(self.positions)
            risk_per_position = self.risk_params.max_portfolio_risk / n_positions
            
            # Position size based on volatility
            # Size = Risk_Target / (Volatility * Price)
            position_size = risk_per_position / (position.volatility * signal_strength)
            position_size = np.clip(position_size, position.min_position_size, position.max_position_size)
            
            # Calculate shares and value
            position_value = position_size * self.portfolio_value
            shares = int(position_value / position.current_price)
            position_value = shares * position.current_price
            
            # Stop loss and take profit
            atr = 2 * position.volatility * position.current_price
            stop_loss_price = position.current_price - (atr * self.risk_params.stop_loss_atr_multiplier)
            take_profit_price = position.current_price + (atr * self.risk_params.take_profit_atr_multiplier)
            
            # Risk amount
            risk_amount = shares * (position.current_price - stop_loss_price)
            
            # Risk-reward ratio
            profit_potential = take_profit_price - position.current_price
            risk_amount_per_share = position.current_price - stop_loss_price
            risk_reward_ratio = profit_potential / risk_amount_per_share if risk_amount_per_share > 0 else 0
            
            # Confidence score
            confidence_score = min(1.0, signal_strength * (1.0 / position.volatility))
            
            return PositionSizingResult(
                sizing_id=f"parity_{int(time.time())}",
                symbol=position.symbol,
                sizing_method="risk_parity",
                position_size=position_size,
                position_value=position_value,
                risk_amount=risk_amount,
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price,
                shares=shares,
                risk_reward_ratio=risk_reward_ratio,
                confidence_score=confidence_score,
                sizing_time=0.0,
                metadata={
                    "risk_per_position": risk_per_position,
                    "n_positions": n_positions,
                    "signal_strength": signal_strength
                }
            )
            
        except Exception as e:
            logger.error(f"Risk parity sizing failed: {e}")
            raise
    
    async def calculate_portfolio_risk(self, current_positions: Dict[str, float]) -> PortfolioRisk:
        """Calculate current portfolio risk metrics."""
        try:
            if not current_positions:
                return PortfolioRisk(
                    total_risk=0.0,
                    position_risks={},
                    correlation_risk=0.0,
                    leverage=0.0,
                    var_95=0.0,
                    expected_shortfall=0.0,
                    risk_budget_used=0.0,
                    risk_capacity=self.risk_params.max_portfolio_risk
                )
            
            # Calculate position risks
            position_risks = {}
            total_position_value = 0.0
            
            for symbol, size in current_positions.items():
                if symbol in self.positions:
                    position = self.positions[symbol]
                    position_value = size * self.portfolio_value
                    position_risk = position_value * position.volatility
                    position_risks[symbol] = position_risk
                    total_position_value += position_value
            
            # Calculate correlation risk (simplified)
            correlation_risk = 0.0
            if self.correlation_matrix is not None and len(current_positions) > 1:
                symbols = list(current_positions.keys())
                n = len(symbols)
                
                for i in range(n):
                    for j in range(i + 1, n):
                        if symbols[i] in position_risks and symbols[j] in position_risks:
                            # Find correlation coefficient
                            corr = 0.0  # Default to 0 if not found
                            try:
                                idx_i = list(self.positions.keys()).index(symbols[i])
                                idx_j = list(self.positions.keys()).index(symbols[j])
                                corr = self.correlation_matrix[idx_i, idx_j]
                            except (ValueError, IndexError):
                                pass
                            
                            correlation_risk += position_risks[symbols[i]] * position_risks[symbols[j]] * corr
            
            # Total portfolio risk
            total_risk = sum(position_risks.values()) + correlation_risk
            
            # Leverage
            leverage = total_position_value / self.portfolio_value if self.portfolio_value > 0 else 0
            
            # VaR and Expected Shortfall (simplified)
            portfolio_volatility = total_risk / total_position_value if total_position_value > 0 else 0
            var_95 = self.portfolio_value * portfolio_volatility * 1.645
            expected_shortfall = self.portfolio_value * portfolio_volatility * 2.06
            
            # Risk budget usage
            risk_budget_used = total_risk / self.portfolio_value
            
            return PortfolioRisk(
                total_risk=total_risk,
                position_risks=position_risks,
                correlation_risk=correlation_risk,
                leverage=leverage,
                var_95=var_95,
                expected_shortfall=expected_shortfall,
                risk_budget_used=risk_budget_used,
                risk_capacity=self.risk_params.max_portfolio_risk,
                metadata={
                    "total_position_value": total_position_value,
                    "portfolio_volatility": portfolio_volatility
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to calculate portfolio risk: {e}")
            return PortfolioRisk(
                total_risk=0.0, position_risks={}, correlation_risk=0.0, leverage=0.0,
                var_95=0.0, expected_shortfall=0.0, risk_budget_used=0.0,
                risk_capacity=self.risk_params.max_portfolio_risk
            )
    
    async def compare_sizing_methods(self, symbol: str, signal_strength: float = 1.0) -> Dict[str, PositionSizingResult]:
        """Compare multiple sizing methods for a position."""
        try:
            results = {}
            
            for method in self.sizing_methods:
                result = await self.calculate_position_size(symbol, method, signal_strength)
                if result:
                    results[method] = result
            
            # Find best result by confidence score
            best_method = None
            best_confidence = 0.0
            
            for method, result in results.items():
                if result.confidence_score > best_confidence:
                    best_confidence = result.confidence_score
                    best_method = method
            
            results["best_method"] = best_method
            results["best_confidence"] = best_confidence
            
            logger.info(f"Sizing comparison completed: best method = {best_method}")
            return results
            
        except Exception as e:
            logger.error(f"Failed to compare sizing methods: {e}")
            return {}
    
    async def _record_compliance(self, result: PositionSizingResult):
        """Record compliance audit entry."""
        if not self.us_compliance.get("audit_sizing", True):
            return
        
        audit_entry = {
            "sizing_id": result.sizing_id,
            "symbol": result.symbol,
            "method": result.sizing_method,
            "timestamp": time.time(),
            "position_size": result.position_size,
            "position_value": result.position_value,
            "risk_amount": result.risk_amount,
            "confidence_score": result.confidence_score,
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Position sizing audit entry: {audit_entry}")
    
    def get_sizing_history(self, symbol: Optional[str] = None, limit: int = 100) -> List[PositionSizingResult]:
        """Get sizing history."""
        if symbol:
            return [s for s in self.sizing_history if s.symbol == symbol][-limit:]
        return list(self.sizing_history)[-limit:]
    
    def get_position_universe(self) -> Dict[str, Position]:
        """Get current position universe."""
        return self.positions.copy()
    
    def update_risk_parameters(self, new_params: Dict[str, Any]):
        """Update risk parameters."""
        for key, value in new_params.items():
            if hasattr(self.risk_params, key):
                setattr(self.risk_params, key, value)
        
        logger.info("Risk parameters updated")
    
    def update_portfolio_value(self, new_value: float):
        """Update portfolio value."""
        self.portfolio_value = new_value
        logger.info(f"Portfolio value updated: ${new_value:,.2f}")
    
    def get_sizing_summary(self) -> Dict[str, Any]:
        """Get comprehensive sizing summary."""
        if not self.sizing_history:
            return {"status": "no_data"}
        
        # Recent sizing
        recent_sizing = list(self.sizing_history)[-100:]
        
        # Method distribution
        method_counts = {}
        for sizing in recent_sizing:
            method = sizing.sizing_method
            method_counts[method] = method_counts.get(method, 0) + 1
        
        # Position sizes
        position_sizes = [s.position_size for s in recent_sizing]
        risk_amounts = [s.risk_amount for s in recent_sizing]
        
        return {
            "total_sizing_calculations": len(self.sizing_history),
            "recent_sizing": len(recent_sizing),
            "method_distribution": method_counts,
            "sizing_metrics": {
                "avg_position_size": np.mean(position_sizes) if position_sizes else 0,
                "max_position_size": max(position_sizes) if position_sizes else 0,
                "avg_risk_amount": np.mean(risk_amounts) if risk_amounts else 0,
                "total_risk_amount": sum(risk_amounts) if risk_amounts else 0
            },
            "position_count": len(self.positions),
            "portfolio_value": self.portfolio_value,
            "available_methods": self.sizing_methods,
            "us_compliance": self.us_compliance
        }
