"""
Portfolio Management for MERID.

Provides portfolio tracking, rebalancing, and position sizing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum

from utils.logger import get_logger

logger = get_logger("portfolio.manager")


class AllocationStrategy(Enum):
    """Portfolio allocation strategies."""
    EQUAL_WEIGHT = "equal_weight"
    MARKET_CAP = "market_cap"
    RISK_PARITY = "risk_parity"
    MOMENTUM = "momentum"
    CUSTOM = "custom"


class PositionSizingMethod(Enum):
    """Position sizing methods."""
    FIXED_AMOUNT = "fixed_amount"
    FIXED_PERCENT = "fixed_percent"
    KELLY_CRITERION = "kelly_criterion"
    VOLATILITY_ADJUSTED = "volatility_adjusted"
    ATR_BASED = "atr_based"


@dataclass
class PortfolioAsset:
    """An asset in the portfolio."""
    symbol: str
    quantity: float
    avg_cost: float
    current_price: float
    target_weight: float = 0.0
    current_weight: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    last_updated: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "avg_cost": self.avg_cost,
            "current_price": self.current_price,
            "market_value": self.quantity * self.current_price,
            "target_weight": self.target_weight,
            "current_weight": self.current_weight,
            "pnl": self.pnl,
            "pnl_pct": self.pnl_pct,
        }


@dataclass
class RebalanceOrder:
    """An order to rebalance the portfolio."""
    symbol: str
    action: str  # 'buy' or 'sell'
    quantity: float
    current_weight: float
    target_weight: float
    weight_diff: float
    estimated_value: float


@dataclass
class PortfolioSnapshot:
    """A snapshot of portfolio state."""
    timestamp: float
    total_value: float
    cash: float
    invested: float
    pnl: float
    pnl_pct: float
    assets: Dict[str, float]  # symbol -> value


class PortfolioManager:
    """
    Manages portfolio allocation and rebalancing.
    """
    
    def __init__(self, initial_capital: float = 100000.0):
        self._cash = initial_capital
        self._initial_capital = initial_capital
        self._assets: Dict[str, PortfolioAsset] = {}
        self._target_weights: Dict[str, float] = {}
        self._allocation_strategy = AllocationStrategy.EQUAL_WEIGHT
        self._sizing_method = PositionSizingMethod.FIXED_PERCENT
        self._snapshots: List[PortfolioSnapshot] = []
        self._rebalance_threshold = 0.05  # 5% drift triggers rebalance
        
        logger.info(f"Portfolio manager initialized with ${initial_capital:,.2f}")
    
    @property
    def total_value(self) -> float:
        """Get total portfolio value."""
        invested = sum(a.quantity * a.current_price for a in self._assets.values())
        return self._cash + invested
    
    @property
    def invested_value(self) -> float:
        """Get total invested value."""
        return sum(a.quantity * a.current_price for a in self._assets.values())
    
    @property
    def pnl(self) -> float:
        """Get total P&L."""
        return self.total_value - self._initial_capital
    
    @property
    def pnl_pct(self) -> float:
        """Get total P&L percentage."""
        return (self.pnl / self._initial_capital) * 100 if self._initial_capital > 0 else 0
    
    def set_allocation_strategy(self, strategy: AllocationStrategy) -> None:
        """Set the allocation strategy."""
        self._allocation_strategy = strategy
        logger.info(f"Allocation strategy set to {strategy.value}")
    
    def set_target_weights(self, weights: Dict[str, float]) -> None:
        """Set target weights for assets."""
        total = sum(weights.values())
        if abs(total - 1.0) > 0.01:
            logger.warning(f"Target weights sum to {total}, normalizing...")
            weights = {k: v / total for k, v in weights.items()}
        
        self._target_weights = weights
        logger.info(f"Target weights set for {len(weights)} assets")
    
    def update_price(self, symbol: str, price: float) -> None:
        """Update price for an asset."""
        if symbol in self._assets:
            asset = self._assets[symbol]
            asset.current_price = price
            asset.pnl = (price - asset.avg_cost) * asset.quantity
            asset.pnl_pct = ((price - asset.avg_cost) / asset.avg_cost) * 100 if asset.avg_cost > 0 else 0
            asset.last_updated = time.time()
            self._update_weights()
    
    def add_position(self, symbol: str, quantity: float, price: float) -> None:
        """Add or update a position."""
        if symbol in self._assets:
            asset = self._assets[symbol]
            total_cost = (asset.avg_cost * asset.quantity) + (price * quantity)
            total_quantity = asset.quantity + quantity
            asset.avg_cost = total_cost / total_quantity if total_quantity > 0 else 0
            asset.quantity = total_quantity
            asset.current_price = price
        else:
            self._assets[symbol] = PortfolioAsset(
                symbol=symbol,
                quantity=quantity,
                avg_cost=price,
                current_price=price,
            )
        
        self._cash -= quantity * price
        self._update_weights()
        logger.info(f"Added position: {quantity} {symbol} @ ${price:.2f}")
    
    def remove_position(self, symbol: str, quantity: float, price: float) -> float:
        """Remove from a position. Returns realized P&L."""
        if symbol not in self._assets:
            return 0.0
        
        asset = self._assets[symbol]
        sell_quantity = min(quantity, asset.quantity)
        
        realized_pnl = (price - asset.avg_cost) * sell_quantity
        asset.quantity -= sell_quantity
        
        if asset.quantity <= 0:
            del self._assets[symbol]
        
        self._cash += sell_quantity * price
        self._update_weights()
        
        logger.info(f"Removed position: {sell_quantity} {symbol} @ ${price:.2f}, P&L: ${realized_pnl:.2f}")
        return realized_pnl
    
    def _update_weights(self) -> None:
        """Update current weights for all assets."""
        total = self.total_value
        if total <= 0:
            return
        
        for asset in self._assets.values():
            asset.current_weight = (asset.quantity * asset.current_price) / total
            asset.target_weight = self._target_weights.get(asset.symbol, 0)
    
    def calculate_rebalance_orders(self) -> List[RebalanceOrder]:
        """Calculate orders needed to rebalance portfolio."""
        orders = []
        total = self.total_value
        
        # Check each target weight
        for symbol, target_weight in self._target_weights.items():
            current_weight = 0.0
            current_price = 0.0
            
            if symbol in self._assets:
                asset = self._assets[symbol]
                current_weight = asset.current_weight
                current_price = asset.current_price
            else:
                # Need to fetch price for new asset
                current_price = self._get_current_price(symbol)
            
            if current_price <= 0:
                continue
            
            weight_diff = target_weight - current_weight
            
            if abs(weight_diff) < self._rebalance_threshold:
                continue
            
            target_value = total * target_weight
            current_value = total * current_weight
            value_diff = target_value - current_value
            quantity = abs(value_diff) / current_price
            
            orders.append(RebalanceOrder(
                symbol=symbol,
                action="buy" if weight_diff > 0 else "sell",
                quantity=quantity,
                current_weight=current_weight,
                target_weight=target_weight,
                weight_diff=weight_diff,
                estimated_value=abs(value_diff),
            ))
        
        return orders
    
    def _get_current_price(self, symbol: str) -> float:
        """Get current price for a symbol."""
        try:
            from data.live_price_feed import get_live_price_feed
            feed = get_live_price_feed()
            price_data = feed.get_current_price(symbol)
            return price_data.price if price_data else 0.0
        except:
            return 0.0
    
    def calculate_position_size(
        self,
        symbol: str,
        entry_price: float,
        stop_loss: float,
        risk_per_trade: float = 0.02,
    ) -> float:
        """
        Calculate position size based on risk management.
        
        Args:
            symbol: Trading symbol
            entry_price: Entry price
            stop_loss: Stop loss price
            risk_per_trade: Max risk per trade as fraction of portfolio
            
        Returns:
            Position size in units
        """
        if self._sizing_method == PositionSizingMethod.FIXED_AMOUNT:
            return 1000 / entry_price  # $1000 per trade
        
        elif self._sizing_method == PositionSizingMethod.FIXED_PERCENT:
            trade_value = self.total_value * 0.1  # 10% of portfolio
            return trade_value / entry_price
        
        elif self._sizing_method == PositionSizingMethod.VOLATILITY_ADJUSTED:
            # Risk-based position sizing
            risk_amount = self.total_value * risk_per_trade
            risk_per_unit = abs(entry_price - stop_loss)
            if risk_per_unit <= 0:
                return 0
            return risk_amount / risk_per_unit
        
        elif self._sizing_method == PositionSizingMethod.KELLY_CRITERION:
            # Simplified Kelly: f = (bp - q) / b
            # Assuming 55% win rate, 1.5:1 reward/risk
            win_rate = 0.55
            reward_risk = 1.5
            kelly_fraction = (win_rate * reward_risk - (1 - win_rate)) / reward_risk
            kelly_fraction = max(0, min(kelly_fraction, 0.25))  # Cap at 25%
            trade_value = self.total_value * kelly_fraction
            return trade_value / entry_price
        
        else:
            return (self.total_value * 0.05) / entry_price  # Default 5%
    
    def take_snapshot(self) -> PortfolioSnapshot:
        """Take a snapshot of current portfolio state."""
        snapshot = PortfolioSnapshot(
            timestamp=time.time(),
            total_value=self.total_value,
            cash=self._cash,
            invested=self.invested_value,
            pnl=self.pnl,
            pnl_pct=self.pnl_pct,
            assets={s: a.quantity * a.current_price for s, a in self._assets.items()},
        )
        self._snapshots.append(snapshot)
        return snapshot
    
    def get_holdings(self) -> List[Dict[str, Any]]:
        """Get current holdings."""
        return [a.to_dict() for a in self._assets.values()]
    
    def get_summary(self) -> Dict[str, Any]:
        """Get portfolio summary."""
        return {
            "total_value": self.total_value,
            "cash": self._cash,
            "invested": self.invested_value,
            "pnl": self.pnl,
            "pnl_pct": self.pnl_pct,
            "num_positions": len(self._assets),
            "allocation_strategy": self._allocation_strategy.value,
            "sizing_method": self._sizing_method.value,
            "rebalance_threshold": self._rebalance_threshold,
        }
    
    def get_allocation(self) -> Dict[str, Any]:
        """Get current vs target allocation."""
        allocation = {}
        for symbol, asset in self._assets.items():
            allocation[symbol] = {
                "current_weight": asset.current_weight,
                "target_weight": asset.target_weight,
                "drift": asset.current_weight - asset.target_weight,
            }
        
        # Add targets not in portfolio
        for symbol, target in self._target_weights.items():
            if symbol not in allocation:
                allocation[symbol] = {
                    "current_weight": 0,
                    "target_weight": target,
                    "drift": -target,
                }
        
        return allocation
    
    def get_value_history(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Get portfolio value history for charting."""
        # Take a snapshot if we don't have recent data
        if not self._snapshots or (time.time() - self._snapshots[-1].timestamp > 60):
            self.take_snapshot()
        
        # Return recent snapshots
        recent = self._snapshots[-limit:] if len(self._snapshots) > limit else self._snapshots
        
        return [
            {
                "timestamp": s.timestamp,
                "total_value": s.total_value,
                "equity": s.total_value,
                "cash": s.cash,
                "invested": s.invested,
                "pnl": s.pnl,
                "pnl_pct": s.pnl_pct,
            }
            for s in recent
        ]


# Singleton instance
_portfolio_manager: Optional[PortfolioManager] = None


def get_portfolio_manager() -> PortfolioManager:
    """Get or create portfolio manager singleton."""
    global _portfolio_manager
    if _portfolio_manager is None:
        _portfolio_manager = PortfolioManager()
    return _portfolio_manager
