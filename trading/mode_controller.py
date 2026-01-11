"""
MERID Trading Mode Controller

Global trading mode management with Paper/Live/Hybrid/Autonomous modes.
Includes spectator feature for watching agent paper trades.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Callable
from collections import deque

from utils.logger import get_logger

logger = get_logger("trading.mode_controller")


class TradingMode(Enum):
    """Trading execution modes."""
    PAPER = "paper"           # All trades are simulated
    LIVE = "live"             # Real execution on exchanges
    HYBRID = "hybrid"         # Paper trades with live data, manual approval for live
    AUTONOMOUS = "autonomous" # Full autonomous live trading


class TradeAction(Enum):
    """Trade action types."""
    BUY = "buy"
    SELL = "sell"
    LONG = "long"
    SHORT = "short"
    CLOSE = "close"


@dataclass
class SpectatorTrade:
    """A trade visible in spectator mode."""
    trade_id: str
    agent_id: str
    symbol: str
    action: str
    quantity: float
    price: float
    timestamp: float
    mode: str
    pnl: float = 0.0
    status: str = "open"
    entry_price: float = 0.0
    exit_price: float = 0.0
    exit_timestamp: Optional[float] = None
    strategy: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ModeChangeEvent:
    """Event when trading mode changes."""
    event_id: str
    old_mode: str
    new_mode: str
    changed_by: str
    timestamp: float
    reason: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TradingModeController:
    """
    Global trading mode controller.
    
    Manages:
    - Current trading mode (Paper/Live/Hybrid/Autonomous)
    - Spectator trade log for watching agent activity
    - Mode change history
    - Trade execution gating based on mode
    """
    
    def __init__(self):
        self._mode = TradingMode.PAPER
        self._spectator_trades: deque = deque(maxlen=1000)
        self._mode_history: deque = deque(maxlen=100)
        self._subscribers: List[Callable] = []
        self._live_approval_required = True
        self._autonomous_limits = {
            "max_position_usd": 1000.0,
            "max_daily_trades": 50,
            "max_daily_volume_usd": 10000.0,
            "allowed_symbols": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        }
        self._daily_stats = {
            "trades": 0,
            "volume_usd": 0.0,
            "last_reset": time.time(),
        }
        self._running = False
        logger.info("TradingModeController initialized in PAPER mode")
    
    @property
    def mode(self) -> TradingMode:
        return self._mode
    
    @property
    def mode_name(self) -> str:
        return self._mode.value
    
    @property
    def is_paper(self) -> bool:
        return self._mode == TradingMode.PAPER
    
    @property
    def is_live(self) -> bool:
        return self._mode in (TradingMode.LIVE, TradingMode.AUTONOMOUS)
    
    @property
    def is_hybrid(self) -> bool:
        return self._mode == TradingMode.HYBRID
    
    @property
    def is_autonomous(self) -> bool:
        return self._mode == TradingMode.AUTONOMOUS
    
    def set_mode(self, mode: str, changed_by: str = "system", reason: str = "") -> bool:
        """Change trading mode."""
        try:
            new_mode = TradingMode(mode.lower())
        except ValueError:
            logger.error(f"Invalid trading mode: {mode}")
            return False
        
        old_mode = self._mode
        self._mode = new_mode
        
        # Log mode change
        event = ModeChangeEvent(
            event_id=str(uuid.uuid4()),
            old_mode=old_mode.value,
            new_mode=new_mode.value,
            changed_by=changed_by,
            timestamp=time.time(),
            reason=reason,
        )
        self._mode_history.append(event)
        
        logger.info(f"Trading mode changed: {old_mode.value} -> {new_mode.value} by {changed_by}")
        
        # Notify subscribers
        for callback in self._subscribers:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Mode change callback error: {e}")
        
        return True
    
    def can_execute_live(self, symbol: str, amount_usd: float) -> tuple[bool, str]:
        """Check if a live trade can be executed based on current mode and limits."""
        # Paper mode - never execute live
        if self._mode == TradingMode.PAPER:
            return False, "Paper mode - live execution disabled"
        
        # Hybrid mode - requires manual approval
        if self._mode == TradingMode.HYBRID:
            if self._live_approval_required:
                return False, "Hybrid mode - manual approval required"
        
        # Autonomous mode - check limits
        if self._mode == TradingMode.AUTONOMOUS:
            # Reset daily stats if needed
            if time.time() - self._daily_stats["last_reset"] > 86400:
                self._daily_stats = {
                    "trades": 0,
                    "volume_usd": 0.0,
                    "last_reset": time.time(),
                }
            
            # Check symbol allowlist
            if symbol not in self._autonomous_limits["allowed_symbols"]:
                return False, f"Symbol {symbol} not in autonomous allowlist"
            
            # Check position size
            if amount_usd > self._autonomous_limits["max_position_usd"]:
                return False, f"Position ${amount_usd} exceeds max ${self._autonomous_limits['max_position_usd']}"
            
            # Check daily trade count
            if self._daily_stats["trades"] >= self._autonomous_limits["max_daily_trades"]:
                return False, "Daily trade limit reached"
            
            # Check daily volume
            if self._daily_stats["volume_usd"] + amount_usd > self._autonomous_limits["max_daily_volume_usd"]:
                return False, "Daily volume limit would be exceeded"
        
        return True, "Execution allowed"
    
    def record_trade(
        self,
        agent_id: str,
        symbol: str,
        action: str,
        quantity: float,
        price: float,
        strategy: str = "",
        confidence: float = 0.0,
        reasoning: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SpectatorTrade:
        """Record a trade for spectator viewing."""
        trade = SpectatorTrade(
            trade_id=str(uuid.uuid4()),
            agent_id=agent_id,
            symbol=symbol,
            action=action,
            quantity=quantity,
            price=price,
            timestamp=time.time(),
            mode=self._mode.value,
            entry_price=price,
            strategy=strategy,
            confidence=confidence,
            reasoning=reasoning,
            metadata=metadata or {},
        )
        
        self._spectator_trades.append(trade)
        
        # Update daily stats
        self._daily_stats["trades"] += 1
        self._daily_stats["volume_usd"] += quantity * price
        
        logger.debug(f"Spectator trade recorded: {agent_id} {action} {quantity} {symbol} @ {price}")
        
        return trade
    
    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        pnl: float,
    ) -> Optional[SpectatorTrade]:
        """Close a trade and calculate P&L."""
        for trade in self._spectator_trades:
            if trade.trade_id == trade_id:
                trade.status = "closed"
                trade.exit_price = exit_price
                trade.exit_timestamp = time.time()
                trade.pnl = pnl
                return trade
        return None
    
    def get_spectator_trades(
        self,
        limit: int = 50,
        agent_id: Optional[str] = None,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[SpectatorTrade]:
        """Get trades for spectator view with optional filters."""
        trades = list(self._spectator_trades)
        
        if agent_id:
            trades = [t for t in trades if t.agent_id == agent_id]
        if symbol:
            trades = [t for t in trades if t.symbol == symbol]
        if status:
            trades = [t for t in trades if t.status == status]
        
        # Return most recent first
        trades.reverse()
        return trades[:limit]
    
    def get_mode_history(self, limit: int = 20) -> List[ModeChangeEvent]:
        """Get mode change history."""
        history = list(self._mode_history)
        history.reverse()
        return history[:limit]
    
    def get_status(self) -> Dict[str, Any]:
        """Get current controller status."""
        return {
            "mode": self._mode.value,
            "is_paper": self.is_paper,
            "is_live": self.is_live,
            "is_hybrid": self.is_hybrid,
            "is_autonomous": self.is_autonomous,
            "live_approval_required": self._live_approval_required,
            "autonomous_limits": self._autonomous_limits,
            "daily_stats": self._daily_stats,
            "spectator_trades_count": len(self._spectator_trades),
            "mode_changes_count": len(self._mode_history),
        }
    
    def set_autonomous_limits(self, limits: Dict[str, Any]) -> None:
        """Update autonomous mode limits."""
        self._autonomous_limits.update(limits)
        logger.info(f"Autonomous limits updated: {limits}")
    
    def subscribe(self, callback: Callable) -> None:
        """Subscribe to mode change events."""
        self._subscribers.append(callback)
    
    def unsubscribe(self, callback: Callable) -> None:
        """Unsubscribe from mode change events."""
        if callback in self._subscribers:
            self._subscribers.remove(callback)


# Singleton instance
_controller: Optional[TradingModeController] = None


def get_trading_mode_controller() -> TradingModeController:
    """Get the global trading mode controller."""
    global _controller
    if _controller is None:
        _controller = TradingModeController()
    return _controller
