"""
Cross-Hedge Engine.

Manages hedging between prediction markets and spot/derivatives markets.
Allows capturing prediction market edge while hedging underlying exposure.

Version: 1.0.0
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

from utils.logger import get_logger

logger = get_logger("prediction.cross_hedge")


class HedgeType(Enum):
    """Types of hedges."""
    SPOT = "spot"           # Hedge with spot position
    PERP = "perp"           # Hedge with perpetual futures
    OPTIONS = "options"     # Hedge with options
    PREDICTION = "prediction"  # Hedge with another prediction market


class HedgeStatus(Enum):
    """Status of a hedge."""
    PROPOSED = "proposed"
    ACTIVE = "active"
    PARTIALLY_CLOSED = "partially_closed"
    CLOSED = "closed"
    LIQUIDATED = "liquidated"


@dataclass
class HedgeLeg:
    """A single leg of a hedge."""
    leg_id: str
    leg_type: HedgeType
    
    # Position
    venue: str
    symbol: str
    side: str  # "long" or "short"
    quantity: float
    entry_price: float
    
    # Current state
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    
    # Hedge ratio
    delta: float = 1.0  # How much this leg hedges
    
    def update_pnl(self, current_price: float) -> float:
        """Update unrealized P&L."""
        self.current_price = current_price
        if self.side == "long":
            self.unrealized_pnl = (current_price - self.entry_price) * self.quantity
        else:
            self.unrealized_pnl = (self.entry_price - current_price) * self.quantity
        return self.unrealized_pnl
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "leg_id": self.leg_id,
            "leg_type": self.leg_type.value,
            "venue": self.venue,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "unrealized_pnl": self.unrealized_pnl,
            "delta": self.delta,
        }


@dataclass
class CrossHedgePosition:
    """A complete cross-hedge position."""
    position_id: str
    status: HedgeStatus = HedgeStatus.PROPOSED
    
    # Prediction market leg
    prediction_platform: str = ""
    prediction_market_id: str = ""
    prediction_side: str = ""  # "yes" or "no"
    prediction_quantity: float = 0.0
    prediction_entry_price: float = 0.0
    prediction_current_price: float = 0.0
    
    # Hedge legs
    hedge_legs: List[HedgeLeg] = field(default_factory=list)
    
    # P&L
    prediction_pnl: float = 0.0
    hedge_pnl: float = 0.0
    total_pnl: float = 0.0
    
    # Risk metrics
    net_delta: float = 0.0  # Net exposure
    max_loss: float = 0.0
    
    # Timing
    opened_at: float = field(default_factory=time.time)
    closed_at: Optional[float] = None
    
    # Metadata
    strategy: str = ""
    notes: str = ""
    
    def calculate_pnl(self) -> float:
        """Calculate total P&L."""
        # Prediction P&L
        if self.prediction_side == "yes":
            self.prediction_pnl = (self.prediction_current_price - self.prediction_entry_price) * self.prediction_quantity
        else:
            self.prediction_pnl = (self.prediction_entry_price - self.prediction_current_price) * self.prediction_quantity
        
        # Hedge P&L
        self.hedge_pnl = sum(leg.unrealized_pnl for leg in self.hedge_legs)
        
        # Total
        self.total_pnl = self.prediction_pnl + self.hedge_pnl
        return self.total_pnl
    
    def calculate_net_delta(self) -> float:
        """Calculate net delta exposure."""
        # Prediction delta
        pred_delta = self.prediction_quantity if self.prediction_side == "yes" else -self.prediction_quantity
        
        # Hedge deltas
        hedge_delta = sum(
            leg.delta * leg.quantity * (1 if leg.side == "long" else -1)
            for leg in self.hedge_legs
        )
        
        self.net_delta = pred_delta + hedge_delta
        return self.net_delta
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "position_id": self.position_id,
            "status": self.status.value,
            "prediction_platform": self.prediction_platform,
            "prediction_market_id": self.prediction_market_id,
            "prediction_side": self.prediction_side,
            "prediction_quantity": self.prediction_quantity,
            "prediction_entry_price": self.prediction_entry_price,
            "prediction_current_price": self.prediction_current_price,
            "hedge_legs": [leg.to_dict() for leg in self.hedge_legs],
            "prediction_pnl": self.prediction_pnl,
            "hedge_pnl": self.hedge_pnl,
            "total_pnl": self.total_pnl,
            "net_delta": self.net_delta,
            "max_loss": self.max_loss,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
            "strategy": self.strategy,
            "notes": self.notes,
        }


@dataclass
class HedgeStrategy:
    """A predefined hedging strategy."""
    strategy_id: str
    name: str
    description: str
    
    # When to apply
    applicable_categories: List[str] = field(default_factory=list)
    min_edge_pct: float = 2.0
    
    # How to hedge
    hedge_type: HedgeType = HedgeType.SPOT
    hedge_ratio: float = 1.0  # 1.0 = fully hedged
    
    # Risk parameters
    max_position_usd: float = 10000.0
    stop_loss_pct: float = 5.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "description": self.description,
            "applicable_categories": self.applicable_categories,
            "min_edge_pct": self.min_edge_pct,
            "hedge_type": self.hedge_type.value,
            "hedge_ratio": self.hedge_ratio,
            "max_position_usd": self.max_position_usd,
            "stop_loss_pct": self.stop_loss_pct,
        }


class CrossHedgeEngine:
    """
    Engine for managing cross-hedges between prediction and spot markets.
    
    Strategies:
    1. Price prediction hedge: Bet on price prediction, hedge with spot/perp
    2. Event hedge: Bet on event outcome, hedge correlated assets
    3. Arbitrage hedge: Exploit cross-platform price differences
    """
    
    def __init__(self):
        self.logger = get_logger("prediction.cross_hedge")
        
        # Active positions
        self._positions: Dict[str, CrossHedgePosition] = {}
        
        # Historical positions
        self._history: List[CrossHedgePosition] = []
        self._max_history: int = 1000
        
        # Strategies
        self._strategies: Dict[str, HedgeStrategy] = {}
        self._init_default_strategies()
        
        # Configuration
        self._enabled: bool = False  # Disabled by default
        self._max_positions: int = 10
        self._max_total_exposure_usd: float = 100000.0
    
    def _init_default_strategies(self) -> None:
        """Initialize default hedging strategies."""
        self._strategies["btc_price_hedge"] = HedgeStrategy(
            strategy_id="btc_price_hedge",
            name="BTC Price Prediction Hedge",
            description="Hedge BTC price predictions with BTC spot/perp",
            applicable_categories=["crypto", "bitcoin", "btc"],
            hedge_type=HedgeType.PERP,
            hedge_ratio=0.8,  # 80% hedged
            max_position_usd=50000.0,
        )
        
        self._strategies["eth_price_hedge"] = HedgeStrategy(
            strategy_id="eth_price_hedge",
            name="ETH Price Prediction Hedge",
            description="Hedge ETH price predictions with ETH spot/perp",
            applicable_categories=["crypto", "ethereum", "eth"],
            hedge_type=HedgeType.PERP,
            hedge_ratio=0.8,
            max_position_usd=30000.0,
        )
        
        self._strategies["election_hedge"] = HedgeStrategy(
            strategy_id="election_hedge",
            name="Election Outcome Hedge",
            description="Hedge election predictions with correlated assets",
            applicable_categories=["politics", "election"],
            hedge_type=HedgeType.OPTIONS,
            hedge_ratio=0.5,  # Partial hedge
            max_position_usd=10000.0,
        )
    
    def propose_hedge(
        self,
        prediction_platform: str,
        prediction_market_id: str,
        prediction_side: str,
        prediction_quantity: float,
        prediction_price: float,
        category: str = "",
    ) -> Optional[CrossHedgePosition]:
        """Propose a cross-hedge for a prediction position."""
        if not self._enabled:
            self.logger.warning("Cross-hedge engine is disabled")
            return None
        
        # Find applicable strategy
        strategy = self._find_strategy(category)
        if not strategy:
            self.logger.info(f"No hedge strategy for category: {category}")
            return None
        
        # Create position
        import uuid
        position_id = f"hedge_{uuid.uuid4().hex[:12]}"
        
        position = CrossHedgePosition(
            position_id=position_id,
            status=HedgeStatus.PROPOSED,
            prediction_platform=prediction_platform,
            prediction_market_id=prediction_market_id,
            prediction_side=prediction_side,
            prediction_quantity=prediction_quantity,
            prediction_entry_price=prediction_price,
            prediction_current_price=prediction_price,
            strategy=strategy.strategy_id,
        )
        
        # Calculate hedge legs
        hedge_legs = self._calculate_hedge_legs(position, strategy)
        position.hedge_legs = hedge_legs
        
        # Calculate max loss
        position.max_loss = self._calculate_max_loss(position, strategy)
        
        # Calculate net delta
        position.calculate_net_delta()
        
        return position
    
    def _find_strategy(self, category: str) -> Optional[HedgeStrategy]:
        """Find applicable strategy for category."""
        category_lower = category.lower()
        
        for strategy in self._strategies.values():
            for applicable in strategy.applicable_categories:
                if applicable.lower() in category_lower or category_lower in applicable.lower():
                    return strategy
        
        return None
    
    def _calculate_hedge_legs(
        self,
        position: CrossHedgePosition,
        strategy: HedgeStrategy
    ) -> List[HedgeLeg]:
        """Calculate hedge legs for a position."""
        legs = []
        
        import uuid
        
        # Determine hedge direction (opposite of prediction)
        hedge_side = "short" if position.prediction_side == "yes" else "long"
        
        # Calculate hedge quantity
        hedge_quantity = position.prediction_quantity * strategy.hedge_ratio
        
        # Create hedge leg based on strategy type
        if strategy.hedge_type == HedgeType.PERP:
            # Hedge with perpetual futures
            symbol = self._get_hedge_symbol(position.prediction_market_id)
            
            legs.append(HedgeLeg(
                leg_id=f"leg_{uuid.uuid4().hex[:8]}",
                leg_type=HedgeType.PERP,
                venue="binance",  # Default venue
                symbol=symbol,
                side=hedge_side,
                quantity=hedge_quantity,
                entry_price=position.prediction_entry_price,  # Simplified
                delta=strategy.hedge_ratio,
            ))
        
        elif strategy.hedge_type == HedgeType.SPOT:
            # Hedge with spot
            symbol = self._get_hedge_symbol(position.prediction_market_id)
            
            legs.append(HedgeLeg(
                leg_id=f"leg_{uuid.uuid4().hex[:8]}",
                leg_type=HedgeType.SPOT,
                venue="coinbase",
                symbol=symbol,
                side=hedge_side,
                quantity=hedge_quantity,
                entry_price=position.prediction_entry_price,
                delta=strategy.hedge_ratio,
            ))
        
        return legs
    
    def _get_hedge_symbol(self, market_id: str) -> str:
        """Get hedge symbol from market ID."""
        market_lower = market_id.lower()
        
        if "btc" in market_lower or "bitcoin" in market_lower:
            return "BTC/USDT"
        elif "eth" in market_lower or "ethereum" in market_lower:
            return "ETH/USDT"
        elif "sol" in market_lower or "solana" in market_lower:
            return "SOL/USDT"
        
        return "BTC/USDT"  # Default
    
    def _calculate_max_loss(
        self,
        position: CrossHedgePosition,
        strategy: HedgeStrategy
    ) -> float:
        """Calculate maximum loss for position."""
        # Prediction max loss (can lose entire position)
        pred_max_loss = position.prediction_quantity * position.prediction_entry_price
        
        # Hedge max loss (based on stop loss)
        hedge_max_loss = sum(
            leg.quantity * leg.entry_price * (strategy.stop_loss_pct / 100)
            for leg in position.hedge_legs
        )
        
        return pred_max_loss + hedge_max_loss
    
    def activate_position(self, position_id: str) -> bool:
        """Activate a proposed position."""
        position = self._positions.get(position_id)
        if not position:
            return False
        
        if position.status != HedgeStatus.PROPOSED:
            return False
        
        # Check limits
        if len([p for p in self._positions.values() if p.status == HedgeStatus.ACTIVE]) >= self._max_positions:
            self.logger.warning("Max positions reached")
            return False
        
        position.status = HedgeStatus.ACTIVE
        self.logger.info(f"Activated cross-hedge position: {position_id}")
        return True
    
    def close_position(self, position_id: str) -> bool:
        """Close a position."""
        position = self._positions.get(position_id)
        if not position:
            return False
        
        position.status = HedgeStatus.CLOSED
        position.closed_at = time.time()
        position.calculate_pnl()
        
        # Move to history
        self._history.append(position)
        del self._positions[position_id]
        
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        
        self.logger.info(f"Closed cross-hedge position: {position_id} | P&L: ${position.total_pnl:.2f}")
        return True
    
    def update_prices(self, position_id: str, prediction_price: float, hedge_prices: Dict[str, float]) -> None:
        """Update prices for a position."""
        position = self._positions.get(position_id)
        if not position:
            return
        
        position.prediction_current_price = prediction_price
        
        for leg in position.hedge_legs:
            if leg.symbol in hedge_prices:
                leg.update_pnl(hedge_prices[leg.symbol])
        
        position.calculate_pnl()
        position.calculate_net_delta()
    
    def enable(self) -> None:
        """Enable the cross-hedge engine."""
        self._enabled = True
        self.logger.info("Cross-hedge engine enabled")
    
    def disable(self) -> None:
        """Disable the cross-hedge engine."""
        self._enabled = False
        self.logger.info("Cross-hedge engine disabled")
    
    def add_strategy(self, strategy: HedgeStrategy) -> None:
        """Add a custom strategy."""
        self._strategies[strategy.strategy_id] = strategy
        self.logger.info(f"Added strategy: {strategy.name}")
    
    def get_position(self, position_id: str) -> Optional[CrossHedgePosition]:
        """Get a position."""
        return self._positions.get(position_id)
    
    def get_active_positions(self) -> List[CrossHedgePosition]:
        """Get all active positions."""
        return [p for p in self._positions.values() if p.status == HedgeStatus.ACTIVE]
    
    def get_total_exposure(self) -> float:
        """Get total exposure across all positions."""
        return sum(
            p.prediction_quantity * p.prediction_entry_price
            for p in self.get_active_positions()
        )
    
    def get_status(self) -> Dict[str, Any]:
        """Get engine status."""
        active = self.get_active_positions()
        
        return {
            "enabled": self._enabled,
            "active_positions": len(active),
            "total_exposure_usd": self.get_total_exposure(),
            "total_pnl": sum(p.total_pnl for p in active),
            "strategies": {k: v.to_dict() for k, v in self._strategies.items()},
            "positions": [p.to_dict() for p in active],
            "config": {
                "max_positions": self._max_positions,
                "max_total_exposure_usd": self._max_total_exposure_usd,
            },
        }


# Singleton
_cross_hedge_engine: Optional[CrossHedgeEngine] = None


def get_cross_hedge_engine() -> CrossHedgeEngine:
    """Get or create the Cross-Hedge Engine singleton."""
    global _cross_hedge_engine
    if _cross_hedge_engine is None:
        _cross_hedge_engine = CrossHedgeEngine()
    return _cross_hedge_engine
