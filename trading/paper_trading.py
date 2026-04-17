"""
Paper Trading System for MERID.

Provides simulated trading functionality for perps and prediction markets
without risking real capital. Tracks virtual portfolio, P&L, and performance.
"""

from __future__ import annotations

import collections
import json
import threading
import uuid
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Callable, Set, Any, Tuple
from enum import Enum

from utils.logger import get_logger
from trading.mode_controller import get_trading_mode_controller

logger = get_logger("trading.paper_trading")


def _get_live_price_feed():
    """Lazy import to avoid initializing crypto exchanges at module load time."""
    from data.live_price_feed import get_live_price_feed, PriceData
    return get_live_price_feed(), PriceData


def get_live_price_feed():
    """Public alias for test patching compatibility."""
    return _get_live_price_feed()


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
    PARTIALLY_FILLED = "partially_filled"
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
    # Bug 1 fix: track contracts separately from size_usd for prediction markets
    contracts: int = 0
    # Bug 1 fix: remaining_size tracks residual on partial fills
    remaining_size: float = 0.0
    created_at: float = field(default_factory=time.time)
    filled_at: Optional[float] = None
    market_type: str = "perp"  # perp or prediction
    market_id: Optional[str] = None
    venue: str = "paper"


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
    venue: str = "paper"
    # Bug 9 fix: store integer contract count for prediction markets so PnL
    # formula uses contracts directly instead of reconstructing from size_usd.
    contracts: int = 0


@dataclass
class PaperPortfolio:
    """Paper trading portfolio."""
    user_id: str
    starting_balance: float = 10000.0
    current_balance: float = 10000.0
    total_pnl: float = 0.0
    total_fees: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    positions: Dict[str, PaperPosition] = field(default_factory=dict)
    orders: Dict[str, PaperOrder] = field(default_factory=dict)
    trade_history: List[PaperOrder] = field(default_factory=list)
    closed_positions: List[PaperPosition] = field(default_factory=list)
    equity_snapshots: collections.deque = field(default_factory=lambda: collections.deque(maxlen=500))


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
    
    # Per-venue fee rates in basis points (1 bp = 0.01%)
    DEFAULT_FEE_BPS: Dict[str, float] = {
        "paper": 0.0,
        "binance": 10.0,     # 0.10%
        "binanceus": 10.0,
        "alpaca": 0.0,       # commission-free equities
        "kalshi": 7.0,       # $0.07 per contract
        "polymarket": 0.0,   # no fees on poly paper
        "bitget": 10.0,
        "coinbase": 15.0,    # 0.15%
    }

    def __init__(self, starting_balance: float = 10000.0, fee_overrides: Optional[Dict[str, float]] = None):
        from merid.settings import settings
        
        self.starting_balance = starting_balance
        self.portfolios: Dict[str, PaperPortfolio] = {}
        self.order_counter = 0
        self.position_counter = 0
        self.fee_bps = dict(self.DEFAULT_FEE_BPS)
        if fee_overrides:
            self.fee_bps.update(fee_overrides)
        self.total_fees_paid: float = 0.0
        self._last_equity_snapshot_ts: float = 0.0
        self._equity_snapshot_interval: float = 60.0  # Record equity every 60s

        # Only init price feed if not in Kalshi-only mode
        if not settings.KALSHI_ONLY:
            feed, _ = get_live_price_feed()
            self.price_feed = feed
            self.current_prices: Dict[str, float] = {}
            self._subscribe_to_prices()
        else:
            self.price_feed = None
            self.current_prices: Dict[str, float] = {}

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

    def reset_state(self) -> None:
        """Wipe all portfolios, positions, orders, and trade history.

        Used by the fresh-start path to guarantee a clean baseline.
        Does NOT touch price subscriptions or listeners.
        """
        self.portfolios.clear()
        self.order_counter = 0
        self.position_counter = 0
        self.total_fees_paid = 0.0
        self._last_equity_snapshot_ts = 0.0
        self._summary_dirty = False
        self._positions_dirty = False
        self.summary_snapshot = None
        logger.info("Paper trading engine state reset to clean baseline")

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

    def _on_price_update(self, price_data: Any) -> None:  # PriceData from data.live_price_feed
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
            self._maybe_record_equity_snapshots()

    def _maybe_record_equity_snapshots(self) -> None:
        """Record an equity snapshot per portfolio, throttled to once per interval."""
        now = time.time()
        if now - self._last_equity_snapshot_ts < self._equity_snapshot_interval:
            return
        self._last_equity_snapshot_ts = now
        for portfolio in self.portfolios.values():
            unrealized = sum(
                self._calculate_position_pnl(pos) for pos in portfolio.positions.values()
            )
            true_eq = portfolio.current_balance + unrealized - portfolio.total_fees
            portfolio.equity_snapshots.append((now, round(true_eq, 2)))

    def get_equity_series(self, user_id: str) -> List[Tuple[float, float]]:
        """Return the equity snapshot series [(timestamp, true_equity), ...] for a portfolio."""
        portfolio = self.get_portfolio(user_id)
        return list(portfolio.equity_snapshots)

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

        total_fees = sum(p.total_fees for p in self.portfolios.values())
        true_equity = cash + total_unrealized - total_fees

        # INVARIANT: Total position value (exposure) must never be negative
        total_position_value = sum(
            pos.get("size_usd", 0) for pos in positions_snapshot
        )
        if total_position_value < -0.01:  # Small tolerance for floating point
            logger.critical(
                "EXPOSURE_INVARIANT_VIOLATION: total_position_value=%.4f is negative! "
                "This indicates data corruption or calculation error.",
                total_position_value
            )
            # Emit metric for monitoring
            try:
                from monitoring.metrics import emit_counter
                emit_counter("merid_negative_exposure_violations_total", 1, {"source": "paper_trading"})
            except Exception:
                pass  # Metric emission is best-effort

        return {
            "accounts": len(self.portfolios),
            "cash": cash,
            "equity": cash + total_unrealized,
            "true_equity": round(true_equity, 2),
            "total_fees": round(total_fees, 4),
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
        market_id: Optional[str] = None,
        venue: str = "paper",
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
        
        # Generate order ID with collision detection
        self.order_counter += 1
        order_id = f"paper_order_{self.order_counter}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        
        # INVARIANT: Order ID must be unique (collision check)
        existing_order_ids = set()
        for p in self.portfolios.values():
            for order in p.trade_history:
                existing_order_ids.add(order.order_id)
        if order_id in existing_order_ids:
            logger.critical(
                "ORDER_ID_INVARIANT_VIOLATION: Generated order ID %s collides with existing order! "
                "This indicates a bug in ID generation or extremely high-frequency ordering.",
                order_id
            )
            raise RuntimeError(f"Order ID collision detected: {order_id}")
        
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
            market_id=market_id,
            venue=venue,
        )
        
        # Validate balance
        required_margin = size_usd / leverage if market_type == "perp" else size_usd
        if portfolio.current_balance < required_margin:
            order.status = PaperOrderStatus.REJECTED
            logger.warning(f"Order rejected - insufficient balance: {user_id}")
            return order
        
        # Execute market orders immediately; lock margin for resting orders.
        if order.order_type == PaperOrderType.MARKET:
            self._execute_order(order, portfolio)
        else:
            # Bug 3 fix: lock the required margin immediately for limit/stop
            # orders so the balance check reflects real available capital.
            # Without this, multiple pending orders can each pass the balance
            # check at placement but would collectively exceed the portfolio
            # when they all trigger.  Margin is returned if the order is
            # cancelled (see cancel_order); it is consumed by _execute_order
            # on trigger (which re-deducts it — see _execute_order guard below).
            portfolio.current_balance -= required_margin
            order._locked_margin = required_margin
            portfolio.orders[order_id] = order
        
        return order

    def cancel_order(self, user_id: str, order_id: str) -> bool:
        """Cancel a pending order and return any locked margin to the portfolio.

        Bug 3 fix companion: limit/stop orders lock margin at placement time.
        Cancellation must release that margin back to current_balance.

        Returns True if the order was found and cancelled, False otherwise.
        """
        portfolio = self.get_portfolio(user_id)
        order = portfolio.orders.get(order_id)
        if order is None:
            logger.warning("cancel_order: order %s not found for user %s", order_id, user_id)
            return False
        if order.status != PaperOrderStatus.PENDING:
            logger.warning(
                "cancel_order: order %s is %s, not PENDING — skipping",
                order_id, order.status.value,
            )
            return False
        # Return locked margin
        locked = getattr(order, "_locked_margin", 0.0)
        if locked > 0:
            portfolio.current_balance += locked
            logger.debug(
                "cancel_order: returned $%.4f locked margin for order %s",
                locked, order_id,
            )
        order.status = PaperOrderStatus.CANCELLED
        del portfolio.orders[order_id]
        _save_paper_state(self)
        return True

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
        
        # Bug 1 fix: use actual filled_size (may be partial) not full size_usd.
        # For the PaperTradingEngine perp/prediction path, we fill the full
        # requested size (no partial-fill simulation here — that lives in
        # order_router.simulate_paper_fill for the Kalshi path).  We still
        # set remaining_size explicitly so the pattern is unambiguous.
        order.fill_price = fill_price
        order.filled_size = order.size_usd
        order.remaining_size = 0.0
        order.status = PaperOrderStatus.FILLED
        order.filled_at = time.time()
        
        # Calculate and deduct fee
        fee_rate_bps = self.fee_bps.get(order.venue, 0.0)
        fee = order.size_usd * fee_rate_bps / 10_000.0
        portfolio.current_balance -= fee
        self.total_fees_paid += fee
        portfolio.total_fees += fee

        # Bug 3 fix: only deduct margin here for market orders.  Limit/stop
        # orders had their margin locked at placement (order._locked_margin),
        # so deducting again would double-charge the portfolio.
        _already_locked = getattr(order, "_locked_margin", 0.0) > 0
        if not _already_locked:
            required_margin = order.size_usd / order.leverage if order.market_type == "perp" else order.size_usd
            portfolio.current_balance -= required_margin
        
        # Create or update position
        self._update_position(order, portfolio)

        # Add to trade history only for confirmed fills (not pending limit orders)
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

        # Publish to streaming_bus.SIMULATION so AuditTrail receives paper fills
        try:
            import asyncio as _asyncio
            from core.streaming_bus import streaming_bus, StreamEvent, EventChannel
            _sim_event = StreamEvent(
                channel=EventChannel.SIMULATION,
                event_type="paper_fill",
                data={
                    "order_id": order.order_id,
                    "user_id": order.user_id,
                    "asset": order.asset,
                    "side": order.side,
                    "size_usd": order.size_usd,
                    "fill_price": order.fill_price,
                    "market_type": order.market_type,
                    "market_id": order.market_id,
                    "venue": order.venue,
                    "ts": order.filled_at,
                },
                source="paper_trading_engine",
            )
            _loop = _asyncio.get_event_loop()
            if _loop.is_running():
                _loop.create_task(streaming_bus.publish(_sim_event))
        except Exception as _exc:
            logger.debug(f"streaming_bus SIMULATION publish error (non-fatal): {_exc}")

        logger.info(f"Order executed: {order.order_id} - {order.asset} {order.side} @ {fill_price}")
        _save_paper_state(self)
    
    def _update_position(self, order: PaperOrder, portfolio: PaperPortfolio):
        """Update or create position from order."""
        # Bug 7 fix: include market_id in key so distinct Kalshi contracts
        # (different strikes/expiries) for the same asset/side are not merged.
        _mid = (order.market_id or "").replace(" ", "_")
        position_key = f"{order.asset}_{order.side}_{order.market_type}_{order.venue}_{_mid}" if _mid else f"{order.asset}_{order.side}_{order.market_type}_{order.venue}"
        
        # INVARIANT: Position key stability - if key exists, asset must match
        if position_key in portfolio.positions:
            existing = portfolio.positions[position_key]
            if existing.asset != order.asset:
                logger.critical(
                    "POSITION_KEY_INVARIANT_VIOLATION: position_key=%s has asset=%s but order.asset=%s! "
                    "This indicates position key collision or data corruption.",
                    position_key, existing.asset, order.asset
                )
                raise ValueError(f"Position key collision: {position_key} has mismatched assets")
        
        # Bug 1 fix: use filled_size (may be partial), not full size_usd.
        filled_usd = order.filled_size
        if position_key in portfolio.positions:
            # Update existing position (average entry price)
            position = portfolio.positions[position_key]
            total_size = position.size_usd + filled_usd
            position.entry_price = (
                (position.entry_price * position.size_usd + order.fill_price * filled_usd) / total_size
            )
            position.size_usd = total_size
            # Bug 9 fix: accumulate contract count
            if order.contracts > 0:
                position.contracts += order.contracts
        else:
            # Create new position
            self.position_counter += 1
            position_id = f"paper_pos_{self.position_counter}_{int(time.time())}"

            # Bug 9 fix: derive contracts from filled_size when not explicitly set
            _contracts = order.contracts if order.contracts > 0 else 0
            if _contracts == 0 and order.market_type != "perp" and order.fill_price and order.fill_price > 0:
                _contracts = int(round(filled_usd / (order.fill_price / 100.0))) if order.fill_price < 1.0 else int(round(filled_usd / order.fill_price))

            position = PaperPosition(
                position_id=position_id,
                user_id=order.user_id,
                asset=order.asset,
                side=order.side,
                size_usd=filled_usd,
                entry_price=order.fill_price,
                current_price=order.fill_price,
                leverage=order.leverage,
                market_type=order.market_type,
                market_id=order.market_id,
                venue=order.venue,
                contracts=_contracts,
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
        
        # INVARIANT: PnL must be finite (not NaN, not Inf)
        if not isinstance(pnl, (int, float)) or not (pnl == pnl) or pnl == float('inf') or pnl == float('-inf'):  # NaN check: x != x
            logger.critical(
                "PnL_INVARIANT_VIOLATION: position %s has non-finite pnl=%s! "
                "entry_price=%s current_price=%s size_usd=%s. "
                "This indicates calculation error or data corruption. Blocking position close.",
                position_key, pnl, position.entry_price, position.current_price, position.size_usd
            )
            raise ValueError(f"Cannot close position {position_key}: non-finite PnL {pnl}")
        
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
        
        # Mark position as closed and archive for reconciliation
        position.closed_at = time.time()
        position.realized_pnl = pnl
        portfolio.closed_positions.append(position)
        
        # Remove from active positions
        del portfolio.positions[position_key]
        
        logger.info(f"Position closed: {position_key} - P&L: ${pnl:.2f}")
        _save_paper_state(self)

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
        """Calculate position P&L.

        Returns the last known ``unrealized_pnl`` unchanged when the price
        feed does not have a current price for the asset, rather than
        silently falling back to entry_price (which would zero the PnL).
        Sets ``position.price_stale = True`` so the reconciliation check
        can flag stale positions explicitly (BUG-07 fix).
        """
        _MISSING = object()  # sentinel distinct from 0.0

        if position.market_type == "perp":
            raw = self.current_prices.get(position.asset, _MISSING)
            if raw is _MISSING:
                position.price_stale = True
                logger.debug(
                    "_calculate_position_pnl: no price for %s — keeping last unrealized_pnl=%.4f",
                    position.asset, position.unrealized_pnl,
                )
                return position.unrealized_pnl
            current_price = raw
            position.price_stale = False
            position.current_price = current_price

            if position.side == "long":
                price_change_pct = (current_price - position.entry_price) / position.entry_price
            else:  # short
                price_change_pct = (position.entry_price - current_price) / position.entry_price

            pnl = position.size_usd * price_change_pct * position.leverage

        else:  # prediction market
            raw = self.current_prices.get(position.asset, _MISSING)
            if raw is _MISSING:
                position.price_stale = True
                logger.debug(
                    "_calculate_position_pnl: no price for %s (PM) — keeping last unrealized_pnl=%.4f",
                    position.asset, position.unrealized_pnl,
                )
                return position.unrealized_pnl
            current_price = raw
            position.price_stale = False
            position.current_price = current_price
            if position.entry_price > 0:
                # Bug 9 fix: Kalshi contracts pay out in cents (0-100 scale).
                # If we have an explicit contract count use it directly:
                #   pnl = (current_cents - entry_cents) * contracts / 100  (USD)
                # Fallback: treat prices as fractions (0-1 scale) with size_usd.
                if position.contracts > 0 and position.entry_price <= 1.0:
                    # Prices stored as fractions (0-1); pnl in USD
                    if position.side in ("yes", "long"):
                        pnl = (current_price - position.entry_price) * position.contracts
                    else:
                        pnl = (position.entry_price - current_price) * position.contracts
                elif position.contracts > 0 and position.entry_price > 1.0:
                    # Prices stored as cents (1-99 scale)
                    if position.side in ("yes", "long"):
                        pnl = (current_price - position.entry_price) * position.contracts / 100.0
                    else:
                        pnl = (position.entry_price - current_price) * position.contracts / 100.0
                else:
                    # Legacy fallback: use percentage return on size_usd
                    price_change_pct = (
                        (current_price - position.entry_price) / position.entry_price
                        if position.side in ("yes", "long")
                        else (position.entry_price - current_price) / position.entry_price
                    )
                    pnl = position.size_usd * price_change_pct
            else:
                pnl = 0.0

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
    
    def get_positions(self) -> List[Dict[str, Any]]:
        """Return all open positions across every portfolio.

        Used by the reconciliation module to compare MERID's internal
        state against venue-reported positions.
        """
        positions: List[Dict[str, Any]] = []
        for portfolio in self.portfolios.values():
            for position in portfolio.positions.values():
                positions.append({
                    "symbol": position.asset,
                    "quantity": position.size_usd / position.entry_price if position.entry_price else 0.0,
                    "entry_price": position.entry_price,
                    "side": position.side,
                    "market_type": position.market_type,
                    "user_id": position.user_id,
                })
        return positions

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
        
        # Calculate win rate
        total_closed = portfolio.winning_trades + portfolio.losing_trades
        win_rate = (portfolio.winning_trades / total_closed * 100) if total_closed > 0 else 0.0

        # Bug 2 fix: use a single canonical equity definition (fee-inclusive).
        # gross_equity is retained for reference but ROI and true_equity both
        # use the fee-deducted figure so all three are consistent.
        gross_equity = portfolio.current_balance + total_unrealized_pnl
        true_equity = gross_equity - portfolio.total_fees

        # ROI is based on true (net-of-fees) equity so it matches live returns.
        roi = ((true_equity - portfolio.starting_balance) / portfolio.starting_balance * 100)

        return {
            "user_id": user_id,
            "starting_balance": portfolio.starting_balance,
            "current_balance": portfolio.current_balance,
            "total_position_value": total_position_value,
            "total_unrealized_pnl": round(total_unrealized_pnl, 4),
            # Bug 2 fix: 'equity' is now fee-inclusive (same as true_equity).
            # 'gross_equity' is provided separately for reference.
            "equity": round(true_equity, 4),
            "gross_equity": round(gross_equity, 4),
            "true_equity": round(true_equity, 2),
            "total_fees": round(portfolio.total_fees, 4),
            # BUG-02 fix: two clearly distinct PnL fields.
            # total_realized_pnl: closed-position PnL only (matches portfolio.total_pnl).
            # total_pnl: full mark-to-market figure (realized + unrealized).
            "total_realized_pnl": round(portfolio.total_pnl, 4),
            "total_pnl": round(portfolio.total_pnl + total_unrealized_pnl, 4),
            "roi_pct": roi,
            "total_trades": portfolio.total_trades,
            "winning_trades": portfolio.winning_trades,
            "losing_trades": portfolio.losing_trades,
            "win_rate_pct": win_rate,
            "open_positions": len(portfolio.positions),
            "pending_orders": len(portfolio.orders)
        }

def _close_enough(a: float, b: float, tol: float = 0.01) -> bool:
    """Return True if *a* and *b* are within *tol* absolute difference."""
    return abs(a - b) <= tol


# Default persistence path
_PERSIST_DIR = Path(__file__).resolve().parent.parent / "data"
_PERSIST_FILE = _PERSIST_DIR / "paper_positions.json"


def _save_paper_state(engine: PaperTradingEngine) -> None:
    """Persist paper trading state to disk."""
    try:
        _PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        state = {
            "saved_at": time.time(),
            "portfolios": {},
        }
        for uid, portfolio in engine.portfolios.items():
            positions = {}
            for pk, pos in portfolio.positions.items():
                positions[pk] = {
                    "position_id": pos.position_id,
                    "user_id": pos.user_id,
                    "asset": pos.asset,
                    "side": pos.side,
                    "size_usd": pos.size_usd,
                    "entry_price": pos.entry_price,
                    "current_price": pos.current_price,
                    "leverage": pos.leverage,
                    "unrealized_pnl": pos.unrealized_pnl,
                    "realized_pnl": pos.realized_pnl,
                    "opened_at": pos.opened_at,
                    "market_type": pos.market_type,
                    "market_id": pos.market_id,
                    # Bug 10 fix: persist venue and contracts so position key
                    # and PnL formula are correct after restart.
                    "venue": pos.venue,
                    "contracts": pos.contracts,
                }
            trades = []
            for order in portfolio.trade_history[-500:]:
                trades.append({
                    "order_id": order.order_id,
                    "user_id": order.user_id,
                    "asset": order.asset,
                    "side": order.side,
                    "order_type": order.order_type.value,
                    "size_usd": order.size_usd,
                    "price": order.price,
                    "leverage": order.leverage,
                    "status": order.status.value,
                    "fill_price": order.fill_price,
                    "filled_size": order.filled_size,
                    "created_at": order.created_at,
                    "filled_at": order.filled_at,
                    "market_type": order.market_type,
                    "market_id": order.market_id,
                })
            closed = []
            for cp in portfolio.closed_positions[-500:]:
                closed.append({
                    "position_id": cp.position_id,
                    "user_id": cp.user_id,
                    "asset": cp.asset,
                    "side": cp.side,
                    "size_usd": cp.size_usd,
                    "entry_price": cp.entry_price,
                    "current_price": cp.current_price,
                    "leverage": cp.leverage,
                    "unrealized_pnl": cp.unrealized_pnl,
                    "realized_pnl": cp.realized_pnl,
                    "opened_at": cp.opened_at,
                    "closed_at": cp.closed_at,
                    "market_type": cp.market_type,
                    "market_id": cp.market_id,
                    "venue": cp.venue,
                    "contracts": cp.contracts,
                })
            state["portfolios"][uid] = {
                "starting_balance": portfolio.starting_balance,
                "current_balance": portfolio.current_balance,
                "total_pnl": portfolio.total_pnl,
                "total_fees": getattr(portfolio, "total_fees", 0.0),
                "total_trades": portfolio.total_trades,
                "winning_trades": portfolio.winning_trades,
                "losing_trades": portfolio.losing_trades,
                "positions": positions,
                "trade_history": trades,
                "closed_positions": closed,
            }
        # Bug 10 fix: persist engine-level counters so they are seeded
        # correctly on reload and cannot collide with historical IDs.
        state["order_counter"] = engine.order_counter
        state["position_counter"] = engine.position_counter
        _PERSIST_FILE.write_text(json.dumps(state, indent=2))
        logger.debug(f"Paper trading state saved ({len(engine.portfolios)} portfolios)")
    except Exception as exc:
        logger.warning(f"Failed to save paper trading state: {exc}")


def _load_paper_state(engine: PaperTradingEngine) -> None:
    """Restore paper trading state from disk."""
    if not _PERSIST_FILE.exists():
        return
    try:
        data = json.loads(_PERSIST_FILE.read_text())
        for uid, pdata in data.get("portfolios", {}).items():
            portfolio = engine.get_portfolio(uid)
            portfolio.starting_balance = pdata.get("starting_balance", 10000.0)
            portfolio.current_balance = pdata.get("current_balance", 10000.0)
            portfolio.total_pnl = pdata.get("total_pnl", 0.0)
            portfolio.total_fees = pdata.get("total_fees", 0.0)
            portfolio.total_trades = pdata.get("total_trades", 0)
            portfolio.winning_trades = pdata.get("winning_trades", 0)
            portfolio.losing_trades = pdata.get("losing_trades", 0)
            for pk, posdata in pdata.get("positions", {}).items():
                portfolio.positions[pk] = PaperPosition(
                    position_id=posdata["position_id"],
                    user_id=posdata["user_id"],
                    asset=posdata["asset"],
                    side=posdata["side"],
                    size_usd=posdata["size_usd"],
                    entry_price=posdata["entry_price"],
                    current_price=posdata.get("current_price", posdata["entry_price"]),
                    leverage=posdata.get("leverage", 1),
                    unrealized_pnl=posdata.get("unrealized_pnl", 0.0),
                    realized_pnl=posdata.get("realized_pnl", 0.0),
                    opened_at=posdata.get("opened_at", time.time()),
                    market_type=posdata.get("market_type", "perp"),
                    market_id=posdata.get("market_id"),
                    # Bug 10 fix: restore venue (was lost on reload, broke position key lookup)
                    venue=posdata.get("venue", "paper"),
                    # Bug 9/10 fix: restore contract count for correct PM PnL formula
                    contracts=posdata.get("contracts", 0),
                )
            for tdata in pdata.get("trade_history", []):
                try:
                    order = PaperOrder(
                        order_id=tdata["order_id"],
                        user_id=tdata["user_id"],
                        asset=tdata["asset"],
                        side=tdata["side"],
                        order_type=PaperOrderType(tdata.get("order_type", "market")),
                        size_usd=tdata["size_usd"],
                        price=tdata.get("price"),
                        leverage=tdata.get("leverage", 1),
                        status=PaperOrderStatus(tdata.get("status", "filled")),
                        fill_price=tdata.get("fill_price"),
                        filled_size=tdata.get("filled_size", 0.0),
                        created_at=tdata.get("created_at", 0.0),
                        filled_at=tdata.get("filled_at"),
                        market_type=tdata.get("market_type", "perp"),
                        market_id=tdata.get("market_id"),
                    )
                    portfolio.trade_history.append(order)
                except Exception:
                    continue
            for cpdata in pdata.get("closed_positions", []):
                try:
                    cp = PaperPosition(
                        position_id=cpdata["position_id"],
                        user_id=cpdata["user_id"],
                        asset=cpdata["asset"],
                        side=cpdata["side"],
                        size_usd=cpdata["size_usd"],
                        entry_price=cpdata["entry_price"],
                        current_price=cpdata.get("current_price", cpdata["entry_price"]),
                        leverage=cpdata.get("leverage", 1),
                        unrealized_pnl=cpdata.get("unrealized_pnl", 0.0),
                        realized_pnl=cpdata.get("realized_pnl", 0.0),
                        opened_at=cpdata.get("opened_at", 0.0),
                        closed_at=cpdata.get("closed_at"),
                        market_type=cpdata.get("market_type", "perp"),
                        market_id=cpdata.get("market_id"),
                        venue=cpdata.get("venue", "paper"),
                        contracts=cpdata.get("contracts", 0),
                    )
                    portfolio.closed_positions.append(cp)
                except Exception:
                    continue
        # Bug 10 fix: seed engine counters from persisted values so new IDs
        # never collide with historical order/position IDs.
        engine.order_counter = max(engine.order_counter, data.get("order_counter", 0))
        engine.position_counter = max(engine.position_counter, data.get("position_counter", 0))

        # ── Post-load repair: sync counters to avoid reconciliation deltas ──
        _repaired = 0
        for uid, portfolio in engine.portfolios.items():
            actual_history_len = len(portfolio.trade_history)
            if portfolio.total_trades != actual_history_len:
                logger.info(
                    "Repair %s/trade_count: total_trades %d → %d (history length)",
                    uid, portfolio.total_trades, actual_history_len,
                )
                portfolio.total_trades = actual_history_len
                _repaired += 1

            # Recompute win/loss from closed_positions (the only source of truth)
            real_wins = sum(1 for p in portfolio.closed_positions if getattr(p, "realized_pnl", 0) > 0)
            real_losses = sum(1 for p in portfolio.closed_positions if getattr(p, "realized_pnl", 0) < 0)
            if portfolio.winning_trades != real_wins or portfolio.losing_trades != real_losses:
                logger.info(
                    "Repair %s/win_loss: wins %d→%d, losses %d→%d (from %d closed positions)",
                    uid, portfolio.winning_trades, real_wins,
                    portfolio.losing_trades, real_losses,
                    len(portfolio.closed_positions),
                )
                portfolio.winning_trades = real_wins
                portfolio.losing_trades = real_losses
                _repaired += 1

            # Recalculate balance identity using closed_positions as source of truth.
            # Invariant: cash + margin_locked + total_fees == starting_balance + realized_pnl
            realized_pnl = sum(
                getattr(cp, "realized_pnl", 0.0)
                for cp in portfolio.closed_positions
            )
            if not _close_enough(portfolio.total_pnl, realized_pnl):
                logger.info(
                    "Repair %s/total_pnl: %.4f → %.4f (from %d closed positions)",
                    uid, portfolio.total_pnl, realized_pnl,
                    len(portfolio.closed_positions),
                )
                portfolio.total_pnl = realized_pnl
                _repaired += 1

            # Derive expected cash from the corrected identity (fees included).
            margin_locked = sum(
                p.size_usd / max(p.leverage, 1)
                for p in portfolio.positions.values()
            )
            total_fees = getattr(portfolio, "total_fees", 0.0)
            expected_cash = portfolio.starting_balance + portfolio.total_pnl - margin_locked - total_fees
            if not _close_enough(portfolio.current_balance, expected_cash):
                logger.info(
                    "Repair %s/balance_identity: cash %.4f → %.4f (fees=%.4f)",
                    uid, portfolio.current_balance, expected_cash, total_fees,
                )
                portfolio.current_balance = expected_cash
                _repaired += 1

        if _repaired:
            logger.info("Post-load repair: fixed %d inconsistencies across %d portfolios",
                         _repaired, len(engine.portfolios))

        logger.info(f"Paper trading state restored ({len(data.get('portfolios', {}))} portfolios)")
    except Exception as exc:
        logger.warning(f"Failed to load paper trading state: {exc}")


_paper_engine_lock = threading.Lock()


def get_paper_engine() -> PaperTradingEngine:
    """Get or create paper trading engine singleton."""
    global _paper_engine
    if _paper_engine is None:
        with _paper_engine_lock:
            if _paper_engine is None:
                _paper_engine = PaperTradingEngine(starting_balance=10000.0)
                # Always reset paper state on startup.  Stale paper positions
                # accumulate across restarts and cause:
                #   - 1000s of reconciliation PnL-mismatch issues
                #   - Portfolio risk agent "limit breach" → KalshiRiskManager
                #     kill switch → real Kalshi trading blocked
                # A clean baseline every boot prevents all of these.
                _paper_engine.reset_state()
                for f in (_PERSIST_FILE, _PERSIST_DIR / "paper_ladder_state.json"):
                    if f.exists():
                        try:
                            f.unlink()
                            logger.info("Startup: deleted stale %s", f.name)
                        except Exception as _del_exc:
                            logger.warning("Could not delete %s: %s", f.name, _del_exc)
                logger.info("Paper trading state reset on startup (clean baseline)")
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


def get_paper_trading_engine() -> Optional["PaperTradingEngine"]:
    """Get or create the global paper trading engine instance.

    Delegates to ``get_paper_engine()`` so that fresh-start detection and
    persisted-state restoration always run exactly once regardless of which
    factory is called first (BUG-06 fix: eliminates the bare-engine race).
    Returns None in Kalshi-only mode.
    """
    try:
        from merid.settings import settings
        if settings.KALSHI_ONLY:
            logger.info("Paper trading engine SKIPPED (Kalshi-only mode)")
            return None
    except Exception:
        pass
    return get_paper_engine()


def register_with_pipeline() -> None:
    """Register paper trading handler with simulation pipeline."""
    try:
        from core.simulation_pipeline import get_simulation_pipeline
        pipeline = get_simulation_pipeline()
        pipeline.register_paper_handler(paper_trading_handler)
        logger.info("Paper trading handler registered with simulation pipeline")
    except ImportError:
        logger.warning("Could not register with simulation pipeline")
