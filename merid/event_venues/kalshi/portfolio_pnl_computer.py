"""Real-Time PnL Computation for Kalshi Portfolio.

This module provides:
- RealTimePnLComputer: Subscribes to price updates and recomputes PnL
- PnL updates on every price tick from KalshiMarketStateStore
- Integration with portfolio engine for snapshot generation
- Event publishing for downstream consumers

Design principles:
- Unrealized PnL computed from positions + current marks (not stored)
- Updates on every price tick (real-time, not end-of-day)
- Uses integer arithmetic in cents to avoid float drift
- Subscribes to KalshiMarketStateStore for price updates
"""

from __future__ import annotations

import asyncio
import threading
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Optional, Callable, Set

from utils.logger import get_logger
from merid.event_venues.kalshi.portfolio_models import Position, PortfolioSnapshot
from merid.event_venues.kalshi.portfolio_engine import get_portfolio_engine

logger = get_logger("merid.event_venues.kalshi.portfolio_pnl_computer")


# ═══════════════════════════════════════════════════════════════════════════
# PnL Computation Result
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class PnLUpdate:
    """Real-time PnL update for a position or portfolio."""
    ticker: str
    unrealized_pnl_cents: int
    unrealized_pnl_usd: float
    mark_price_cents: int
    quantity: int
    avg_entry_price_cents: int
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            object.__setattr__(self, 'timestamp', datetime.now(timezone.utc))
    
    @property
    def pnl_per_contract_cents(self) -> int:
        """PnL per contract."""
        if self.quantity == 0:
            return 0
        return self.unrealized_pnl_cents // self.quantity


@dataclass
class PortfolioPnLUpdate:
    """Portfolio-level PnL update."""
    account_id: str
    total_unrealized_pnl_cents: int
    total_unrealized_pnl_usd: float
    position_updates: Dict[str, PnLUpdate]  # ticker -> PnLUpdate
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            object.__setattr__(self, 'timestamp', datetime.now(timezone.utc))
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for API transmission."""
        return {
            "account_id": self.account_id,
            "total_unrealized_pnl_cents": self.total_unrealized_pnl_cents,
            "total_unrealized_pnl_usd": self.total_unrealized_pnl_usd,
            "timestamp": self.timestamp.isoformat(),
            "positions": {
                ticker: {
                    "ticker": update.ticker,
                    "unrealized_pnl_cents": update.unrealized_pnl_cents,
                    "unrealized_pnl_usd": update.unrealized_pnl_usd,
                    "mark_price_cents": update.mark_price_cents,
                    "quantity": update.quantity,
                    "avg_entry_price_cents": update.avg_entry_price_cents,
                    "pnl_per_contract_cents": update.pnl_per_contract_cents,
                    "timestamp": update.timestamp.isoformat(),
                }
                for ticker, update in self.position_updates.items()
            },
        }


# ═══════════════════════════════════════════════════════════════════════════
# Real-Time PnL Computer
# ═══════════════════════════════════════════════════════════════════════════

class RealTimePnLComputer:
    """Computes unrealized PnL in real-time from price updates.
    
    Subscribes to KalshiMarketStateStore for price updates and
    recomputes unrealized PnL for all open positions on every tick.
    """
    
    _instance: Optional["RealTimePnLComputer"] = None
    _lock: threading.Lock = threading.Lock()
    
    def __new__(cls) -> "RealTimePnLComputer":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._local_lock = threading.Lock()
        self._engine = get_portfolio_engine()
        
        # Subscribers for PnL updates
        self._subscribers: Set[Callable[[PortfolioPnLUpdate], None]] = set()
        
        # Cache of current marks
        self._current_marks: Dict[str, int] = {}  # ticker -> mark_price_cents
        
        # Processing state
        self._enabled = True
        self._last_update: datetime = datetime.now(timezone.utc)
        
        self._initialized = True
        logger.info("RealTimePnLComputer initialized")
    
    def compute_position_pnl(self, position: Position, mark_price_cents: int) -> PnLUpdate:
        """Compute unrealized PnL for a single position.
        
        Args:
            position: Position to compute PnL for
            mark_price_cents: Current market price in cents
            
        Returns:
            PnLUpdate with computed PnL
        """
        if not position.is_open:
            return PnLUpdate(
                ticker=position.ticker,
                unrealized_pnl_cents=0,
                unrealized_pnl_usd=0.0,
                mark_price_cents=mark_price_cents,
                quantity=position.quantity,
                avg_entry_price_cents=position.avg_entry_price_cents,
            )
        
        # Compute unrealized PnL
        # Long position: (mark - entry) * quantity
        # Short position: (entry - mark) * abs(quantity)
        if position.quantity > 0:
            unrealized_pnl_cents = (mark_price_cents - position.avg_entry_price_cents) * position.quantity
        else:
            unrealized_pnl_cents = (position.avg_entry_price_cents - mark_price_cents) * abs(position.quantity)
        
        return PnLUpdate(
            ticker=position.ticker,
            unrealized_pnl_cents=unrealized_pnl_cents,
            unrealized_pnl_usd=unrealized_pnl_cents / 100.0,
            mark_price_cents=mark_price_cents,
            quantity=position.quantity,
            avg_entry_price_cents=position.avg_entry_price_cents,
        )
    
    def compute_portfolio_pnl(
        self,
        account_id: str,
        positions: Dict[str, Position],
        current_marks: Optional[Dict[str, int]] = None,
    ) -> PortfolioPnLUpdate:
        """Compute unrealized PnL for all positions in a portfolio.
        
        Args:
            account_id: Account to compute PnL for
            positions: Dictionary of positions (position_id -> Position)
            current_marks: Optional current market prices (ticker -> cents)
                           If not provided, uses cached marks
            
        Returns:
            PortfolioPnLUpdate with computed PnL for all positions
        """
        marks = current_marks or self._current_marks
        
        position_updates: Dict[str, PnLUpdate] = {}
        total_unrealized_pnl_cents = 0
        
        for position in positions.values():
            if not position.is_open:
                continue
            
            mark_price = marks.get(position.ticker, position.avg_entry_price_cents)
            
            pnl_update = self.compute_position_pnl(position, mark_price)
            position_updates[position.ticker] = pnl_update
            total_unrealized_pnl_cents += pnl_update.unrealized_pnl_cents
        
        return PortfolioPnLUpdate(
            account_id=account_id,
            total_unrealized_pnl_cents=total_unrealized_pnl_cents,
            total_unrealized_pnl_usd=total_unrealized_pnl_cents / 100.0,
            position_updates=position_updates,
        )
    
    def on_price_update(self, ticker: str, mark_price_cents: int) -> None:
        """Handle a price update from KalshiMarketStateStore.
        
        Args:
            ticker: Market ticker
            mark_price_cents: Current mark price in cents
        """
        if not self._enabled:
            return
        
        with self._local_lock:
            # Update cached mark
            self._current_marks[ticker] = mark_price_cents
            self._last_update = datetime.now(timezone.utc)
            
            # Get current portfolio state
            # Single-account design: Kalshi venue uses one account per API key
            # Multi-account not needed for current Kalshi integration
            account_id = "default"
            snapshot = self._engine.get_snapshot(account_id, self._current_marks)
            
            # Compute PnL update
            pnl_update = self.compute_portfolio_pnl(
                account_id=account_id,
                positions=snapshot.positions,
                current_marks=self._current_marks,
            )
            
            # Notify subscribers
            for subscriber in self._subscribers:
                try:
                    subscriber(pnl_update)
                except Exception as e:
                    logger.error(
                        "PnLComputer: error notifying subscriber: %s",
                        e,
                        exc_info=True
                    )
            
            logger.debug(
                "PnLComputer: price update %s @ %dc total_pnl=%dc",
                ticker, mark_price_cents, pnl_update.total_unrealized_pnl_cents
            )
    
    def subscribe(self, callback: Callable[[PortfolioPnLUpdate], None]) -> None:
        """Subscribe to PnL updates.
        
        Args:
            callback: Function to call with PnL updates
        """
        with self._local_lock:
            self._subscribers.add(callback)
            logger.debug("PnLComputer: subscriber added, total=%d", len(self._subscribers))
    
    def unsubscribe(self, callback: Callable[[PortfolioPnLUpdate], None]) -> None:
        """Unsubscribe from PnL updates.
        
        Args:
            callback: Function to remove from subscribers
        """
        with self._local_lock:
            self._subscribers.discard(callback)
            logger.debug("PnLComputer: subscriber removed, total=%d", len(self._subscribers))
    
    def get_current_marks(self) -> Dict[str, int]:
        """Get cached current market marks.
        
        Returns:
            Dictionary of ticker -> mark_price_cents
        """
        with self._local_lock:
            return self._current_marks.copy()
    
    def enable(self) -> None:
        """Enable PnL computation."""
        with self._local_lock:
            self._enabled = True
            logger.info("PnLComputer enabled")
    
    def disable(self) -> None:
        """Disable PnL computation."""
        with self._local_lock:
            self._enabled = False
            logger.info("PnLComputer disabled")
    
    def get_snapshot_with_pnl(
        self,
        account_id: str = "default",
    ) -> PortfolioSnapshot:
        """Get portfolio snapshot with current PnL.
        
        Args:
            account_id: Account to snapshot
            
        Returns:
            PortfolioSnapshot with unrealized PnL computed from current marks
        """
        with self._local_lock:
            return self._engine.get_snapshot(account_id, self._current_marks)


# ═══════════════════════════════════════════════════════════════════════════
# Singleton Accessor
# ═══════════════════════════════════════════════════════════════════════════

def get_pnl_computer() -> RealTimePnLComputer:
    """Get the singleton RealTimePnLComputer instance."""
    return RealTimePnLComputer()


# ═══════════════════════════════════════════════════════════════════════════
# Integration with KalshiMarketStateStore
# ═══════════════════════════════════════════════════════════════════════════

async def start_pnl_computer_subscription() -> None:
    """Start subscribing to KalshiMarketStateStore for price updates.
    
    This function should be called during application startup to
    enable real-time PnL computation.
    """
    try:
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        
        pnl_computer = get_pnl_computer()
        market_state_store = get_kalshi_market_state_store()
        
        # Subscribe to market state updates for all tracked positions
        # The PnL computer will be notified whenever a market's state is updated
        # (via WS orderbook updates or REST market data)
        
        logger.info("PnLComputer: subscribing to KalshiMarketStateStore for price updates")
        
        # Subscribe to all current and future position tickers
        from merid.event_venues.kalshi.portfolio_engine import get_portfolio_engine
        engine = get_portfolio_engine()
        snapshot = engine.get_snapshot()
        
        if snapshot:
            for ticker, position in snapshot.positions.items():
                # Subscribe to updates for this ticker
                market_state_store.subscribe_to_updates(
                    ticker, 
                    lambda t, s, pnl=pnl_computer: pnl.on_price_update(t, s.mid_cents)
                )
                logger.info("PnLComputer: subscribed to ticker=%s for position qty=%d", ticker, position.quantity)
        
        logger.info("PnLComputer: subscription to KalshiMarketStateStore complete")
        
    except Exception as e:
        logger.error(
            "PnLComputer: failed to start subscription to KalshiMarketStateStore: %s",
            e,
            exc_info=True
        )
