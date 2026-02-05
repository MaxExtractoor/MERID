"""
Paper Trading System for MERID.

Provides simulated trading functionality for perps and prediction markets
without risking real capital. Tracks virtual portfolio, P&L, and performance.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Set, Any
from enum import Enum

from utils.logger import get_logger
from data.live_price_feed import get_live_price_feed, PriceData
from trading.mode_controller import get_trading_mode_controller

logger = get_logger("trading.paper_trading")


def _get_risk_controller():
    """Lazy import risk controller to avoid circular imports."""
    try:
        from merid.risk import risk_controller
        return risk_controller
    except ImportError:
        return None


# Global singleton reference so FastAPI hot reloads don't lose state
_paper_engine: Optional["PaperTradingEngine"] = None


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

        self.price_feed = get_live_price_feed()
        self.current_prices: Dict[str, float] = {}
        self._subscribe_to_prices()

        self._listeners: Dict[str, Set[Callable[[Dict[str, Any]], None]]] = {
            "summary": set(),
            "trade": set(),
            "position": set(),
        }
        self._summary_dirty = False
        self._positions_dirty = False
        self._last_summary_emit = 0.0
        self._last_positions_emit = 0.0
        self.summary_snapshot: Optional[Dict[str, Any]] = None

    def _subscribe(self, event_type: str, callback: Callable[[Dict[str, Any]], None]) -> Callable[[], None]:
        if event_type not in self._listeners:
            raise ValueError(f"Unsupported telemetry event: {event_type}")
        self._listeners[event_type].add(callback)

        def _unsubscribe() -> None:
            self._listeners[event_type].discard(callback)

        return _unsubscribe

    def _notify_listeners(self, event_type: str, payload: Dict[str, Any]) -> None:
        listeners = list(self._listeners.get(event_type, []))
        if not listeners:
            return
        payload.setdefault("ts", time.time())
        for callback in listeners:
            try:
                callback(payload)
            except Exception as exc:
                logger.debug("Telemetry listener error (%s): %s", event_type, exc)

    def _mark_summary_dirty(self) -> None:
        self._summary_dirty = True
        self._emit_summary_if_needed()

    def _mark_positions_dirty(self) -> None:
        self._positions_dirty = True
        self._emit_positions_if_needed()

    def _emit_summary_if_needed(self, force: bool = False) -> None:
        now = time.time()
        if not force and (not self._summary_dirty or now - self._last_summary_emit < 1.0):
            return
        self._last_summary_emit = now
        self._summary_dirty = False
        stats = self.get_global_stats()
        self.summary_snapshot = stats
        self._notify_listeners(
            "summary",
            {
                "type": "summary",
                "stats": stats,
                "paper_enabled": True,
                "ts": now,
            },
        )

    def _emit_positions_if_needed(self, force: bool = False) -> None:
        now = time.time()
        if not force and (not self._positions_dirty or now - self._last_positions_emit < 1.0):
            return
        self._last_positions_emit = now
        self._positions_dirty = False
        positions = self.get_global_stats().get("positions", [])
        self._notify_listeners(
            "position",
            {
                "type": "positions_refresh",
                "positions": positions,
                "ts": now,
            },
        )

    # ------------------------------------------------------------------
    # Live price feed integration
    # ------------------------------------------------------------------

    def _subscribe_to_prices(self) -> None:
        try:
            self.price_feed.subscribe(self._on_price_update)
            logger.info("PaperTradingEngine subscribed to live price feed")
        except Exception as exc:
            logger.error(f"Failed to subscribe to price feed: {exc}")

    def _on_price_update(self, price_data: PriceData) -> None:
        symbol = price_data.symbol
        base = symbol.split('/')[0]
        self.current_prices[symbol] = price_data.price
        self.current_prices[base] = price_data.price

        price_changed = False
        for portfolio in self.portfolios.values():
            for position in portfolio.positions.values():
                if self._symbols_match(position.asset, symbol):
                    position.current_price = price_data.price
                    self._calculate_position_pnl(position)
                    price_changed = True

        if price_changed:
            self._mark_summary_dirty()
            self._mark_positions_dirty()

    @staticmethod
    def _symbols_match(position_asset: str, feed_symbol: str) -> bool:
        if position_asset == feed_symbol:
            return True
        if '/' not in position_asset:
            base = position_asset.split('-')[0]
            return feed_symbol.startswith(base)
        return position_asset.split('/')[0] == feed_symbol.split('/')[0]

    def _get_live_price(self, asset: str) -> float:
        symbol = asset if '/' in asset else f"{asset.upper()}/USDT"
        cached = self.current_prices.get(symbol)
        if cached:
            return cached
        price_data = self.price_feed.get_current_price(symbol)
        if price_data:
            self.current_prices[symbol] = price_data.price
            self.current_prices[symbol.split('/')[0]] = price_data.price
            return price_data.price
        return self.current_prices.get(asset.split('/')[0], 0.0)

    def get_portfolio(self, user_id: str) -> PaperPortfolio:
        """Get or create user portfolio."""
        if user_id not in self.portfolios:
            self.portfolios[user_id] = PaperPortfolio(
                user_id=user_id,
                starting_balance=self.starting_balance,
                current_balance=self.starting_balance
            )
        return self.portfolios[user_id]

    def get_recent_trades(self, limit: int = 25) -> List[Dict[str, Any]]:
        trades: List[Dict[str, Any]] = []
        for portfolio in self.portfolios.values():
            for order in portfolio.trade_history:
                trades.append((order, portfolio.user_id))

        trades.sort(key=lambda entry: entry[0].filled_at or entry[0].created_at, reverse=True)
        return [self._order_to_dict(order, user_id) for order, user_id in trades[:limit]]

    def get_global_stats(self) -> Dict[str, Any]:
        cash = 0.0
        total_unrealized = 0.0
        positions_snapshot: List[Dict[str, Any]] = []
        volume_24h = 0.0
        trades_24h = 0
        now = time.time()
        window_start = now - 86400

        for portfolio in self.portfolios.values():
            cash += portfolio.current_balance
            for position in portfolio.positions.values():
                pnl = self._calculate_position_pnl(position)
                total_unrealized += pnl
                positions_snapshot.append(self._position_to_dict(position, portfolio.user_id))

            for order in portfolio.trade_history:
                timestamp = order.filled_at or order.created_at
                if timestamp and timestamp >= window_start:
                    volume_24h += order.size_usd
                    trades_24h += 1

        positions_snapshot.sort(key=lambda entry: abs(entry.get("unrealized_pnl", entry.get("pnl", 0.0))), reverse=True)
        total_pnl = sum(p.total_pnl for p in self.portfolios.values()) + total_unrealized

        return {
            "accounts": len(self.portfolios),
            "cash": cash,
            "equity": cash + total_unrealized,
            "total_pnl": total_pnl,
            "active_positions": len(positions_snapshot),
            "volume_24h": volume_24h,
            "trades_24h": trades_24h,
            "positions": positions_snapshot,
        }

    def subscribe_to_summary(self, callback: Callable[[Dict[str, Any]], None]) -> Callable[[], None]:
        unsubscribe = self._subscribe("summary", callback)
        callback({
            "type": "summary",
            "stats": self.get_global_stats(),
            "paper_enabled": True,
            "ts": time.time(),
        })
        return unsubscribe

    def subscribe_to_trades(self, callback: Callable[[Dict[str, Any]], None], limit: int = 50) -> Callable[[], None]:
        unsubscribe = self._subscribe("trade", callback)
        callback({
            "type": "trades_snapshot",
            "trades": self.get_recent_trades(limit),
            "ts": time.time(),
        })
        return unsubscribe

    def subscribe_to_positions(self, callback: Callable[[Dict[str, Any]], None], limit: int = 50) -> Callable[[], None]:
        unsubscribe = self._subscribe("position", callback)
        positions = self.get_global_stats().get("positions", [])
        callback({
            "type": "positions_refresh",
            "positions": positions[:limit],
            "ts": time.time(),
        })
        return unsubscribe

    def _order_to_dict(self, order: PaperOrder, user_id: str) -> Dict[str, Any]:
        return {
            "order_id": order.order_id,
            "user_id": user_id,
            "asset": order.asset,
            "side": order.side,
            "size_usd": order.size_usd,
            "fill_price": order.fill_price,
            "market_type": order.market_type,
            "leverage": order.leverage,
            "status": order.status.value,
            "timestamp": order.filled_at or order.created_at,
        }

    def _position_to_dict(self, position: PaperPosition, user_id: str) -> Dict[str, Any]:
        pnl = self._calculate_position_pnl(position)
        return {
            "position_id": position.position_id,
            "user_id": user_id,
            "asset": position.asset,
            "side": position.side,
            "size_usd": position.size_usd,
            "entry_price": position.entry_price,
            "current_price": position.current_price,
            "leverage": position.leverage,
            "unrealized_pnl": pnl,
            "market_type": position.market_type,
            "timestamp": position.opened_at,
        }

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
        # Check risk controller before placing order
        risk_ctrl = _get_risk_controller()
        if risk_ctrl and not risk_ctrl.can_trade():
            logger.warning(f"Order rejected - risk kill switch triggered for {user_id}")
            order = PaperOrder(
                order_id=f"rejected_{int(time.time())}",
                user_id=user_id,
                asset=asset,
                side=side,
                order_type=PaperOrderType[order_type.upper()],
                size_usd=size_usd,
                status=PaperOrderStatus.REJECTED,
            )
            return order
        
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
            # For prediction markets, get real price from simulation aggregator
            try:
                from monitoring.simulation_prediction_markets import get_simulation_aggregator
                aggregator = get_simulation_aggregator()
                markets = aggregator.get_all_markets()
                
                # Find matching market
                market = next((m for m in markets if m.market_id == order.market_id), None)
                
                if market:
                    # Use real probability as price
                    current_price = market.yes_price if order.side == "yes" else market.no_price
                    logger.info(f"Using real prediction market price: {current_price} for {order.market_id}")
                else:
                    # Fallback to order price or 0.5
                    current_price = order.price or 0.5
                    logger.warning(f"Market {order.market_id} not found, using fallback price: {current_price}")
            except Exception as e:
                logger.error(f"Failed to get prediction market price: {e}")
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

        # Notify telemetry + spectator mode
        self._notify_listeners(
            "trade",
            {
                "type": "trade",
                "trade": self._order_to_dict(order, order.user_id),
                "ts": time.time(),
            },
        )
        self._mark_summary_dirty()
        self._mark_positions_dirty()

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
        
        # Record P&L with risk controller (may trigger daily loss kill)
        risk_ctrl = _get_risk_controller()
        if risk_ctrl:
            risk_ctrl.record_pnl(pnl)
        
        # Mark position as closed
        position.closed_at = time.time()
        position.realized_pnl = pnl
        
        # Remove from active positions
        del portfolio.positions[position_key]
        
        logger.info(f"Position closed: {position_key} - P&L: ${pnl:.2f}")

        self._notify_listeners(
            "position",
            {
                "type": "position_closed",
                "position_id": position.position_id,
                "user_id": user_id,
                "realized_pnl": pnl,
                "ts": time.time(),
            },
        )
        self._mark_summary_dirty()
        self._mark_positions_dirty()

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
    
    def _check_pending_orders(self):
        """Check if any pending orders should be triggered based on current prices."""
        for portfolio in self.portfolios.values():
            triggered_orders = []
            
            for order_id, order in list(portfolio.orders.items()):
                if order.status != PaperOrderStatus.PENDING:
                    continue
                
                current_price = self.current_prices.get(order.asset, 0)
                if current_price == 0:
                    continue
                
                should_trigger = False
                
                # Check limit orders
                if order.order_type == PaperOrderType.LIMIT:
                    if order.side in ["long", "yes"] and current_price <= (order.price or 0):
                        should_trigger = True
                    elif order.side in ["short", "no"] and current_price >= (order.price or 0):
                        should_trigger = True
                
                # Check stop-loss orders
                elif order.order_type == PaperOrderType.STOP_LOSS:
                    if order.side in ["long", "yes"] and current_price <= (order.stop_price or 0):
                        should_trigger = True
                    elif order.side in ["short", "no"] and current_price >= (order.stop_price or 0):
                        should_trigger = True
                
                if should_trigger:
                    triggered_orders.append((order_id, order))
            
            # Execute triggered orders
            for order_id, order in triggered_orders:
                logger.info(f"Triggering pending order: {order_id} at price {self.current_prices.get(order.asset)}")
                self._execute_order(order, portfolio)
                if order_id in portfolio.orders:
                    del portfolio.orders[order_id]
    
    def update_prices(self, prices: Dict[str, float]):
        """Update current market prices and check pending orders."""
        self.current_prices.update(prices)
        
        # Check if any pending orders should be triggered
        self._check_pending_orders()
        
        # Update all open positions
        price_changed = False
        for portfolio in self.portfolios.values():
            for position in portfolio.positions.values():
                if position.market_type == "perp":
                    self._calculate_position_pnl(position)
                    price_changed = True

        if price_changed:
            self._mark_summary_dirty()
            self._mark_positions_dirty()
    
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

def get_paper_engine() -> PaperTradingEngine:
    """Get or create paper trading engine singleton."""
    global _paper_engine
    if _paper_engine is None:
        _paper_engine = PaperTradingEngine(starting_balance=10000.0)
    return _paper_engine

def paper_trading_handler(action_type: str, parameters: Dict) -> Dict:
    """
    Handler for simulation pipeline paper trading execution.
    
    Integrates with SimulationPipeline to execute paper trades
    from LLM proposals.
    """
    engine = get_paper_engine()
    
    if action_type == "propose_order":
        order = engine.place_order(
            user_id=parameters.get("agent_id", "llm_agent"),
            asset=parameters.get("asset", "BTC"),
            side=parameters.get("side", "long"),
            size_usd=parameters.get("size", 100.0),
            order_type=parameters.get("order_type", "market"),
            price=parameters.get("price"),
            leverage=parameters.get("leverage", 1),
            market_type=parameters.get("market_type", "perp"),
        )
        
        return {
            "paper_executed": True,
            "paper_order_id": order.order_id,
            "status": order.status.value,
            "fill_price": order.fill_price,
            "pnl": 0.0,
        }
    
    elif action_type == "close_position":
        position_key = parameters.get("position_key")
        user_id = parameters.get("agent_id", "llm_agent")
        
        pnl = engine.close_position(user_id, position_key)
        
        return {
            "paper_executed": True,
            "closed": pnl is not None,
            "pnl": pnl or 0.0,
        }
    
    elif action_type == "get_portfolio":
        user_id = parameters.get("agent_id", "llm_agent")
        stats = engine.get_portfolio_stats(user_id)
        
        return {
            "paper_executed": True,
            "portfolio": stats,
        }
    
    else:
        return {
            "paper_executed": False,
            "error": f"Unknown action type: {action_type}",
        }


def get_paper_trading_engine() -> PaperTradingEngine:
    """Get or create the global paper trading engine instance."""
    global _paper_engine
    if _paper_engine is None:
        _paper_engine = PaperTradingEngine()
    return _paper_engine


def register_with_pipeline() -> None:
    """Register paper trading handler with simulation pipeline."""
    try:
        from core.simulation_pipeline import get_simulation_pipeline
        pipeline = get_simulation_pipeline()
        pipeline.register_paper_handler(paper_trading_handler)
        logger.info("Paper trading handler registered with simulation pipeline")
    except ImportError:
        logger.warning("Could not register with simulation pipeline")
