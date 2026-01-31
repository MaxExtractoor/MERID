"""
Execution Simulator - Self-hosted paper trading without third-party dependencies

Provides a complete broker-like interface for MERID strategies:
- Market data ingestion (live or replay)
- Order matching and execution simulation
- Risk checks and position management
- PnL tracking and portfolio accounting
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import json
from decimal import Decimal

from utils.logger import get_logger

logger = get_logger("execution.simulator")


class OrderType(Enum):
    """Order types supported by the simulator."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderSide(Enum):
    """Order sides."""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    """Order status lifecycle."""
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class MarketData:
    """Market data tick or quote."""
    symbol: str
    timestamp: float
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None
    last_price: Optional[float] = None
    last_size: Optional[float] = None


@dataclass
class Order:
    """Order representation."""
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: str = "GTC"  # Good Till Cancelled
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    fills: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Position:
    """Position tracking."""
    symbol: str
    quantity: float = 0.0
    avg_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    last_updated: float = field(default_factory=time.time)


@dataclass
class Account:
    """Account state."""
    account_id: str
    cash: float = 100000.0  # Starting cash
    positions: Dict[str, Position] = field(default_factory=dict)
    orders: Dict[str, Order] = field(default_factory=dict)
    margin_used: float = 0.0
    buying_power: float = 100000.0
    last_updated: float = field(default_factory=time.time)


class OrderBook:
    """Simple limit order book implementation."""
    
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bids: Dict[float, List[Order]] = {}  # price -> orders
        self.asks: Dict[float, List[Order]] = {}  # price -> orders
        self.last_update = time.time()
    
    def add_order(self, order: Order) -> None:
        """Add order to the book."""
        book = self.bids if order.side == OrderSide.BUY else self.asks
        if order.price not in book:
            book[order.price] = []
        book[order.price].append(order)
        self.last_update = time.time()
    
    def remove_order(self, order: Order) -> None:
        """Remove order from the book."""
        book = self.bids if order.side == OrderSide.BUY else self.asks
        if order.price in book and order in book[order.price]:
            book[order.price].remove(order)
            if not book[order.price]:
                del book[order.price]
        self.last_update = time.time()
    
    def get_best_bid(self) -> Optional[float]:
        """Get best bid price."""
        return max(self.bids.keys()) if self.bids else None
    
    def get_best_ask(self) -> Optional[float]:
        """Get best ask price."""
        return min(self.asks.keys()) if self.asks else None
    
    def get_spread(self) -> Optional[float]:
        """Get bid-ask spread."""
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        if best_bid and best_ask:
            return best_ask - best_bid
        return None


class RiskManager:
    """Risk management for the simulator."""
    
    def __init__(self):
        self.max_notional_per_order = 50000.0
        self.max_position_per_symbol = 1000.0
        self.max_daily_loss = 10000.0
        self.margin_requirement = 0.5  # 50% margin requirement
    
    def check_order_risk(self, account: Account, order: Order, market_data: Optional[MarketData] = None) -> tuple[bool, str]:
        """Check if order passes risk rules."""
        # Check notional
        notional = order.quantity * (order.price or market_data.last_price or 0)
        if notional > self.max_notional_per_order:
            return False, f"Order notional ${notional:,.2f} exceeds maximum ${self.max_notional_per_order:,.2f}"
        
        # Check position limits
        current_pos = account.positions.get(order.symbol, Position(order.symbol))
        new_quantity = current_pos.quantity
        if order.side == OrderSide.BUY:
            new_quantity += order.quantity
        else:
            new_quantity -= order.quantity
        
        if abs(new_quantity) > self.max_position_per_symbol:
            return False, f"Position {abs(new_quantity)} exceeds maximum {self.max_position_per_symbol}"
        
        # Check buying power
        if order.side == OrderSide.BUY:
            required_cash = notional * self.margin_requirement
            if account.cash < required_cash:
                return False, f"Insufficient cash: need ${required_cash:,.2f}, have ${account.cash:,.2f}"
        
        return True, "Order passes risk checks"


class ExecutionSimulator:
    """
    Main execution simulator service.
    
    Provides broker-like API for MERID strategies with no external dependencies.
    """
    
    def __init__(self):
        self.accounts: Dict[str, Account] = {}
        self.order_books: Dict[str, OrderBook] = {}
        self.market_data: Dict[str, MarketData] = {}
        self.risk_manager = RiskManager()
        self.fees = {
            "commission_rate": 0.001,  # 0.1% commission
            "slippage_rate": 0.0005,   # 0.05% slippage
        }
        self._running = False
        self._market_data_callbacks: List[Callable[[MarketData], None]] = []
        
        logger.info("ExecutionSimulator initialized")
    
    async def start(self) -> None:
        """Start the simulator service."""
        if self._running:
            return
        
        self._running = True
        logger.info("ExecutionSimulator started")
    
    async def stop(self) -> None:
        """Stop the simulator service."""
        self._running = False
        logger.info("ExecutionSimulator stopped")
    
    def create_account(self, account_id: str, initial_cash: float = 100000.0) -> Account:
        """Create a new trading account."""
        if account_id in self.accounts:
            raise ValueError(f"Account {account_id} already exists")
        
        account = Account(account_id=account_id, cash=initial_cash, buying_power=initial_cash)
        self.accounts[account_id] = account
        logger.info(f"Created account {account_id} with ${initial_cash:,.2f}")
        return account
    
    def get_account(self, account_id: str) -> Optional[Account]:
        """Get account by ID."""
        return self.accounts.get(account_id)
    
    def submit_order(self, account_id: str, symbol: str, side: str, order_type: str,
                    quantity: float, price: Optional[float] = None, 
                    stop_price: Optional[float] = None) -> Dict[str, Any]:
        """Submit a new order."""
        if account_id not in self.accounts:
            raise ValueError(f"Account {account_id} not found")
        
        order = Order(
            order_id=str(uuid.uuid4()),
            symbol=symbol,
            side=OrderSide(side.lower()),
            order_type=OrderType(order_type.lower()),
            quantity=quantity,
            price=price,
            stop_price=stop_price
        )
        
        account = self.accounts[account_id]
        
        # Risk check
        market_data = self.market_data.get(symbol)
        passed, reason = self.risk_manager.check_order_risk(account, order, market_data)
        if not passed:
            order.status = OrderStatus.REJECTED
            return {
                "order_id": order.order_id,
                "status": "rejected",
                "reason": reason
            }
        
        # Add to account
        account.orders[order.order_id] = order
        
        # Handle different order types
        if order.order_type == OrderType.MARKET:
            self._execute_market_order(account, order)
        elif order.order_type == OrderType.LIMIT:
            self._add_limit_order_to_book(order)
        elif order.order_type == OrderType.STOP:
            # For stop orders, we'll trigger when market data crosses the stop price
            pass  # Handled in market data updates
        
        return {
            "order_id": order.order_id,
            "status": order.status.value,
            "symbol": order.symbol,
            "side": order.side.value,
            "type": order.order_type.value,
            "quantity": order.quantity,
            "price": order.price
        }
    
    def cancel_order(self, account_id: str, order_id: str) -> Dict[str, Any]:
        """Cancel an existing order."""
        account = self.accounts.get(account_id)
        if not account:
            raise ValueError(f"Account {account_id} not found")
        
        order = account.orders.get(order_id)
        if not order:
            raise ValueError(f"Order {order_id} not found")
        
        if order.status in [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED]:
            raise ValueError(f"Cannot cancel order in {order.status.value} status")
        
        # Remove from order book if it's a limit order
        if order.order_type == OrderType.LIMIT:
            book = self.order_books.get(order.symbol)
            if book:
                book.remove_order(order)
        
        order.status = OrderStatus.CANCELLED
        order.updated_at = time.time()
        
        return {
            "order_id": order.order_id,
            "status": "cancelled"
        }
    
    def get_positions(self, account_id: str) -> List[Dict[str, Any]]:
        """Get all positions for an account."""
        account = self.accounts.get(account_id)
        if not account:
            raise ValueError(f"Account {account_id} not found")
        
        positions = []
        for symbol, pos in account.positions.items():
            positions.append({
                "symbol": symbol,
                "quantity": pos.quantity,
                "avg_price": pos.avg_price,
                "unrealized_pnl": pos.unrealized_pnl,
                "realized_pnl": pos.realized_pnl
            })
        
        return positions
    
    def get_orders(self, account_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get orders for an account, optionally filtered by status."""
        account = self.accounts.get(account_id)
        if not account:
            raise ValueError(f"Account {account_id} not found")
        
        orders = []
        for order in account.orders.values():
            if status and order.status.value != status:
                continue
            orders.append({
                "order_id": order.order_id,
                "symbol": order.symbol,
                "side": order.side.value,
                "type": order.order_type.value,
                "quantity": order.quantity,
                "filled_quantity": order.filled_quantity,
                "avg_fill_price": order.avg_fill_price,
                "status": order.status.value,
                "created_at": order.created_at
            })
        
        return orders
    
    def update_market_data(self, market_data: MarketData) -> None:
        """Update market data and trigger order matching."""
        self.market_data[market_data.symbol] = market_data
        
        # Update unrealized PnL for all positions
        self._update_unrealized_pnl(market_data)
        
        # Trigger stop orders
        self._check_stop_orders(market_data)
        
        # Match limit orders
        self._match_limit_orders(market_data)
        
        # Notify callbacks
        for callback in self._market_data_callbacks:
            callback(market_data)
    
    def _execute_market_order(self, account: Account, order: Order) -> None:
        """Execute a market order immediately."""
        market_data = self.market_data.get(order.symbol)
        if not market_data:
            order.status = OrderStatus.REJECTED
            return
        
        # Determine fill price
        if order.side == OrderSide.BUY:
            fill_price = market_data.ask_price or market_data.last_price
        else:
            fill_price = market_data.bid_price or market_data.last_price
        
        if not fill_price:
            order.status = OrderStatus.REJECTED
            return
        
        # Apply slippage
        slippage = fill_price * self.fees["slippage_rate"]
        if order.side == OrderSide.BUY:
            fill_price += slippage
        else:
            fill_price -= slippage
        
        # Execute fill
        self._fill_order(account, order, fill_price, order.quantity)
    
    def _add_limit_order_to_book(self, order: Order) -> None:
        """Add a limit order to the order book."""
        if order.symbol not in self.order_books:
            self.order_books[order.symbol] = OrderBook(order.symbol)
        
        book = self.order_books[order.symbol]
        book.add_order(order)
    
    def _match_limit_orders(self, market_data: MarketData) -> None:
        """Match limit orders against current market data."""
        book = self.order_books.get(market_data.symbol)
        if not book:
            return
        
        # Match marketable limit orders
        if market_data.last_price:
            # Buy orders that can be filled at current price
            if market_data.last_price <= book.get_best_ask() or book.get_best_ask() is None:
                marketable_buys = []
                for price, orders in book.bids.items():
                    if price >= market_data.last_price:
                        marketable_buys.extend(orders)
                
                for order in marketable_buys:
                    account = self._find_account_for_order(order)
                    if account:
                        self._fill_order(account, order, market_data.last_price, order.quantity)
                        book.remove_order(order)
            
            # Sell orders that can be filled at current price
            if market_data.last_price >= book.get_best_bid() or book.get_best_bid() is None:
                marketable_sells = []
                for price, orders in book.asks.items():
                    if price <= market_data.last_price:
                        marketable_sells.extend(orders)
                
                for order in marketable_sells:
                    account = self._find_account_for_order(order)
                    if account:
                        self._fill_order(account, order, market_data.last_price, order.quantity)
                        book.remove_order(order)
    
    def _check_stop_orders(self, market_data: MarketData) -> None:
        """Check and trigger stop orders."""
        if not market_data.last_price:
            return
        
        for account in self.accounts.values():
            for order in account.orders.values():
                if order.order_type == OrderType.STOP and order.status == OrderStatus.NEW:
                    trigger_price = order.stop_price
                    
                    # Buy stop orders trigger when price goes above stop
                    if order.side == OrderSide.BUY and market_data.last_price >= trigger_price:
                        # Convert to market order
                        self._execute_market_order(account, order)
                    
                    # Sell stop orders trigger when price goes below stop
                    elif order.side == OrderSide.SELL and market_data.last_price <= trigger_price:
                        # Convert to market order
                        self._execute_market_order(account, order)
    
    def _fill_order(self, account: Account, order: Order, fill_price: float, fill_quantity: float) -> None:
        """Fill an order and update positions/cash."""
        # Calculate commission
        commission = fill_price * fill_quantity * self.fees["commission_rate"]
        
        # Update order
        order.filled_quantity += fill_quantity
        order.avg_fill_price = ((order.avg_fill_price * (order.filled_quantity - fill_quantity)) + 
                                (fill_price * fill_quantity)) / order.filled_quantity
        order.updated_at = time.time()
        
        if order.filled_quantity >= order.quantity:
            order.status = OrderStatus.FILLED
        else:
            order.status = OrderStatus.PARTIALLY_FILLED
        
        # Record fill
        fill = {
            "fill_id": str(uuid.uuid4()),
            "order_id": order.order_id,
            "symbol": order.symbol,
            "side": order.side.value,
            "quantity": fill_quantity,
            "price": fill_price,
            "commission": commission,
            "timestamp": time.time()
        }
        order.fills.append(fill)
        
        # Update position
        if order.symbol not in account.positions:
            account.positions[order.symbol] = Position(order.symbol)
        
        position = account.positions[order.symbol]
        old_quantity = position.quantity
        old_avg_price = position.avg_price
        
        if order.side == OrderSide.BUY:
            # Buying increases position
            if old_quantity >= 0:
                # Adding to long position
                total_cost = (old_quantity * old_avg_price) + (fill_quantity * fill_price)
                position.quantity = old_quantity + fill_quantity
                position.avg_price = total_cost / position.quantity if position.quantity != 0 else 0
            else:
                # Covering short position
                cover_quantity = min(fill_quantity, abs(old_quantity))
                realized_pnl = cover_quantity * (old_avg_price - fill_price) - commission
                position.realized_pnl += realized_pnl
                position.quantity = old_quantity + fill_quantity
                
                if position.quantity > 0:
                    position.avg_price = fill_price
        else:
            # Selling reduces position
            if old_quantity > 0:
                # Selling long position
                sell_quantity = min(fill_quantity, old_quantity)
                realized_pnl = sell_quantity * (fill_price - old_avg_price) - commission
                position.realized_pnl += realized_pnl
                position.quantity = old_quantity - fill_quantity
            else:
                # Adding to short position
                total_cost = (abs(old_quantity) * old_avg_price) + (fill_quantity * fill_price)
                position.quantity = old_quantity - fill_quantity
                position.avg_price = total_cost / abs(position.quantity) if position.quantity != 0 else 0
        
        position.last_updated = time.time()
        
        # Update cash
        if order.side == OrderSide.SELL:
            account.cash += (fill_price * fill_quantity) - commission
        else:
            account.cash -= (fill_price * fill_quantity) + commission
        
        account.buying_power = account.cash / self.risk_manager.margin_requirement
        account.last_updated = time.time()
        
        logger.info(f"Filled order {order.order_id}: {fill_quantity} @ {fill_price}, commission: ${commission:.2f}")
    
    def _update_unrealized_pnl(self, market_data: MarketData) -> None:
        """Update unrealized PnL for all positions in the symbol."""
        if not market_data.last_price:
            return
        
        for account in self.accounts.values():
            position = account.positions.get(market_data.symbol)
            if position and position.quantity != 0:
                if position.quantity > 0:
                    # Long position
                    position.unrealized_pnl = position.quantity * (market_data.last_price - position.avg_price)
                else:
                    # Short position
                    position.unrealized_pnl = abs(position.quantity) * (position.avg_price - market_data.last_price)
    
    def _find_account_for_order(self, order: Order) -> Optional[Account]:
        """Find the account that owns this order."""
        for account in self.accounts.values():
            if order.order_id in account.orders:
                return account
        return None
    
    def subscribe_market_data(self, callback: Callable[[MarketData], None]) -> None:
        """Subscribe to market data updates."""
        self._market_data_callbacks.append(callback)
    
    def get_account_summary(self, account_id: str) -> Dict[str, Any]:
        """Get account summary including PnL."""
        account = self.accounts.get(account_id)
        if not account:
            raise ValueError(f"Account {account_id} not found")
        
        total_unrealized = sum(pos.unrealized_pnl for pos in account.positions.values())
        total_realized = sum(pos.realized_pnl for pos in account.positions.values())
        total_pnl = total_unrealized + total_realized
        
        return {
            "account_id": account.account_id,
            "cash": account.cash,
            "buying_power": account.buying_power,
            "margin_used": account.margin_used,
            "total_unrealized_pnl": total_unrealized,
            "total_realized_pnl": total_realized,
            "total_pnl": total_pnl,
            "position_count": len([p for p in account.positions.values() if p.quantity != 0]),
            "order_count": len([o for o in account.orders.values() if o.status in [OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED]])
        }


# Global simulator instance
_simulator: Optional[ExecutionSimulator] = None


def get_execution_simulator() -> ExecutionSimulator:
    """Get the global execution simulator instance."""
    global _simulator
    if _simulator is None:
        _simulator = ExecutionSimulator()
    return _simulator
