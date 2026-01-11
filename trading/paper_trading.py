"""
Paper Trading System for MERID.

Provides simulated trading functionality for perps and prediction markets
without risking real capital. Tracks virtual portfolio, P&L, and performance.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum

from utils.logger import get_logger

logger = get_logger("trading.paper_trading")


class PaperOrderStatus(Enum):
    """Paper order status."""
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class PaperOrderType(Enum):
    """Paper order type."""
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"


@dataclass
class PaperOrder:
    """Paper trading order."""
    order_id: str
    user_id: str
    asset: str
    side: str  # long/short or yes/no
    order_type: PaperOrderType
    size_usd: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    leverage: int = 1
    status: PaperOrderStatus = PaperOrderStatus.PENDING
    fill_price: Optional[float] = None
    filled_size: float = 0.0
    created_at: float = field(default_factory=time.time)
    filled_at: Optional[float] = None
    market_type: str = "perp"  # perp or prediction
    market_id: Optional[str] = None


@dataclass
class PaperPosition:
    """Paper trading position."""
    position_id: str
    user_id: str
    asset: str
    side: str
    size_usd: float
    entry_price: float
    current_price: float
    leverage: int = 1
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    opened_at: float = field(default_factory=time.time)
    closed_at: Optional[float] = None
    market_type: str = "perp"
    market_id: Optional[str] = None


@dataclass
class PaperPortfolio:
    """Paper trading portfolio."""
    user_id: str
    starting_balance: float = 10000.0
    current_balance: float = 10000.0
    total_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    positions: Dict[str, PaperPosition] = field(default_factory=dict)
    orders: Dict[str, PaperOrder] = field(default_factory=dict)
    trade_history: List[PaperOrder] = field(default_factory=list)


class PaperTradingEngine:
    """
    Paper trading engine for simulated trading.
    
    Features:
    - Virtual portfolio management
    - Simulated order execution
    - Position tracking
    - P&L calculation
    - Performance metrics
    """
    
    def __init__(self, starting_balance: float = 10000.0):
        self.starting_balance = starting_balance
        self.portfolios: Dict[str, PaperPortfolio] = {}
        self.order_counter = 0
        self.position_counter = 0
        
        # Mock price data (in production, connect to real price feeds)
        self.current_prices = {
            "BTC": 43250.50,
            "ETH": 2280.75,
            "SOL": 98.30,
            "AVAX": 35.20,
            "MATIC": 0.85
        }
    
    def get_portfolio(self, user_id: str) -> PaperPortfolio:
        """Get or create user portfolio."""
        if user_id not in self.portfolios:
            self.portfolios[user_id] = PaperPortfolio(
                user_id=user_id,
                starting_balance=self.starting_balance,
                current_balance=self.starting_balance
            )
        return self.portfolios[user_id]
    
    def place_order(
        self,
        user_id: str,
        asset: str,
        side: str,
        size_usd: float,
        order_type: str = "market",
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        leverage: int = 1,
        market_type: str = "perp",
        market_id: Optional[str] = None
    ) -> PaperOrder:
        """Place paper trading order."""
        portfolio = self.get_portfolio(user_id)
        
        # Generate order ID
        self.order_counter += 1
        order_id = f"paper_order_{self.order_counter}_{int(time.time())}"
        
        # Create order
        order = PaperOrder(
            order_id=order_id,
            user_id=user_id,
            asset=asset,
            side=side,
            order_type=PaperOrderType[order_type.upper()],
            size_usd=size_usd,
            price=price,
            stop_price=stop_price,
            leverage=leverage,
            market_type=market_type,
            market_id=market_id
        )
        
        # Validate balance
        required_margin = size_usd / leverage if market_type == "perp" else size_usd
        if portfolio.current_balance < required_margin:
            order.status = PaperOrderStatus.REJECTED
            logger.warning(f"Order rejected - insufficient balance: {user_id}")
            return order
        
        # Execute market orders immediately
        if order.order_type == PaperOrderType.MARKET:
            self._execute_order(order, portfolio)
        else:
            # Add to pending orders
            portfolio.orders[order_id] = order
        
        return order
    
    def _execute_order(self, order: PaperOrder, portfolio: PaperPortfolio):
        """Execute paper order."""
        # Get current price
        if order.market_type == "perp":
            current_price = self.current_prices.get(order.asset, 0.0)
        else:
            # For prediction markets, use probability as price
            current_price = order.price or 0.5
        
        if current_price == 0.0:
            order.status = PaperOrderStatus.REJECTED
            logger.error(f"Order rejected - invalid price for {order.asset}")
            return
        
        # Simulate slippage (0.1% for market orders)
        slippage = 0.001
        if order.side in ["long", "yes"]:
            fill_price = current_price * (1 + slippage)
        else:
            fill_price = current_price * (1 - slippage)
        
        # Fill order
        order.fill_price = fill_price
        order.filled_size = order.size_usd
        order.status = PaperOrderStatus.FILLED
        order.filled_at = time.time()
        
        # Deduct from balance
        required_margin = order.size_usd / order.leverage if order.market_type == "perp" else order.size_usd
        portfolio.current_balance -= required_margin
        
        # Create or update position
        self._update_position(order, portfolio)
        
        # Add to trade history
        portfolio.trade_history.append(order)
        portfolio.total_trades += 1
        
        logger.info(f"Order executed: {order.order_id} - {order.asset} {order.side} @ {fill_price}")
    
    def _update_position(self, order: PaperOrder, portfolio: PaperPortfolio):
        """Update or create position from order."""
        position_key = f"{order.asset}_{order.side}_{order.market_type}"
        
        if position_key in portfolio.positions:
            # Update existing position (average entry price)
            position = portfolio.positions[position_key]
            total_size = position.size_usd + order.size_usd
            position.entry_price = (
                (position.entry_price * position.size_usd + order.fill_price * order.size_usd) / total_size
            )
            position.size_usd = total_size
        else:
            # Create new position
            self.position_counter += 1
            position_id = f"paper_pos_{self.position_counter}_{int(time.time())}"
            
            position = PaperPosition(
                position_id=position_id,
                user_id=order.user_id,
                asset=order.asset,
                side=order.side,
                size_usd=order.size_usd,
                entry_price=order.fill_price,
                current_price=order.fill_price,
                leverage=order.leverage,
                market_type=order.market_type,
                market_id=order.market_id
            )
            
            portfolio.positions[position_key] = position
    
    def close_position(self, user_id: str, position_key: str) -> Optional[float]:
        """Close paper position and realize P&L."""
        portfolio = self.get_portfolio(user_id)
        
        if position_key not in portfolio.positions:
            logger.warning(f"Position not found: {position_key}")
            return None
        
        position = portfolio.positions[position_key]
        
        # Calculate P&L
        pnl = self._calculate_position_pnl(position)
        
        # Return margin + P&L to balance
        returned_amount = (position.size_usd / position.leverage) + pnl
        portfolio.current_balance += returned_amount
        portfolio.total_pnl += pnl
        
        # Update win/loss stats
        if pnl > 0:
            portfolio.winning_trades += 1
        elif pnl < 0:
            portfolio.losing_trades += 1
        
        # Mark position as closed
        position.closed_at = time.time()
        position.realized_pnl = pnl
        
        # Remove from active positions
        del portfolio.positions[position_key]
        
        logger.info(f"Position closed: {position_key} - P&L: ${pnl:.2f}")
        
        return pnl
    
    def _calculate_position_pnl(self, position: PaperPosition) -> float:
        """Calculate position P&L."""
        if position.market_type == "perp":
            # Get current price
            current_price = self.current_prices.get(position.asset, position.entry_price)
            position.current_price = current_price
            
            # Calculate P&L based on side
            if position.side == "long":
                price_change_pct = (current_price - position.entry_price) / position.entry_price
            else:  # short
                price_change_pct = (position.entry_price - current_price) / position.entry_price
            
            # Apply leverage
            pnl = position.size_usd * price_change_pct * position.leverage
        
        else:  # prediction market
            # For prediction markets, P&L depends on outcome
            # Simplified: assume 50% chance of winning
            if position.side == "yes":
                pnl = position.size_usd * 0.5  # Mock 50% return
            else:
                pnl = -position.size_usd * 0.5
        
        position.unrealized_pnl = pnl
        return pnl
    
    def update_prices(self, prices: Dict[str, float]):
        """Update current market prices."""
        self.current_prices.update(prices)
        
        # Update all open positions
        for portfolio in self.portfolios.values():
            for position in portfolio.positions.values():
                if position.market_type == "perp":
                    self._calculate_position_pnl(position)
    
    def get_portfolio_stats(self, user_id: str) -> Dict:
        """Get portfolio statistics."""
        portfolio = self.get_portfolio(user_id)
        
        # Calculate total position value
        total_position_value = sum(
            pos.size_usd for pos in portfolio.positions.values()
        )
        
        # Calculate total unrealized P&L
        total_unrealized_pnl = sum(
            self._calculate_position_pnl(pos) for pos in portfolio.positions.values()
        )
        
        # Calculate equity
        equity = portfolio.current_balance + total_unrealized_pnl
        
        # Calculate win rate
        total_closed = portfolio.winning_trades + portfolio.losing_trades
        win_rate = (portfolio.winning_trades / total_closed * 100) if total_closed > 0 else 0.0
        
        # Calculate ROI
        roi = ((equity - portfolio.starting_balance) / portfolio.starting_balance * 100)
        
        return {
            "user_id": user_id,
            "starting_balance": portfolio.starting_balance,
            "current_balance": portfolio.current_balance,
            "total_position_value": total_position_value,
            "total_unrealized_pnl": total_unrealized_pnl,
            "equity": equity,
            "total_pnl": portfolio.total_pnl + total_unrealized_pnl,
            "roi_pct": roi,
            "total_trades": portfolio.total_trades,
            "winning_trades": portfolio.winning_trades,
            "losing_trades": portfolio.losing_trades,
            "win_rate_pct": win_rate,
            "open_positions": len(portfolio.positions),
            "pending_orders": len(portfolio.orders)
        }
    
    def reset_portfolio(self, user_id: str):
        """Reset portfolio to starting balance."""
        if user_id in self.portfolios:
            del self.portfolios[user_id]
        logger.info(f"Portfolio reset for user: {user_id}")


# Global paper trading engine instance
_paper_engine: Optional[PaperTradingEngine] = None


def get_paper_engine() -> PaperTradingEngine:
    """Get or create paper trading engine singleton."""
    global _paper_engine
    if _paper_engine is None:
        _paper_engine = PaperTradingEngine(starting_balance=10000.0)
    return _paper_engine
