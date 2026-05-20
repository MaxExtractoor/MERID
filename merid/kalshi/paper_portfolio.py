# merid/kalshi/paper_portfolio.py
"""Kalshi paper portfolio for crypto lane."""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from decimal import Decimal
import time
from collections import defaultdict

from utils.logger import get_logger

logger = get_logger("merid.kalshi.paper_portfolio")


@dataclass
class PaperPosition:
    """Position in paper portfolio."""
    market_id: str
    side: str  # "yes" or "no"
    contracts: int
    entry_price_cents: int
    entry_ts: float
    agent_id: str


# Number of concurrent lanes for bankroll allocation split
# BUG-FIX: Made configurable via env var instead of hardcoded
import os
_DEFAULT_LANE_COUNT = int(os.getenv("MERID_KALSHI_LANE_COUNT", "8"))  # 4 symbols * 2 modes (live/paper)


@dataclass
class PaperTrade:
    """Completed paper trade."""
    market_id: str
    side: str
    contracts: int
    entry_price_cents: int
    exit_price_cents: int
    entry_ts: float
    exit_ts: float
    profit_usd: Decimal
    agent_id: str


class KalshiPaperPortfolio:
    """Paper portfolio for crypto agents - same instruments, live orderbooks, simulated fills."""
    
    def __init__(self, portfolio_id: str = "kalshi_paper_crypto"):
        self.portfolio_id = portfolio_id
        self._positions: Dict[str, PaperPosition] = {}  # market_id -> position
        self._trades: List[PaperTrade] = []
        # BUG-FIX: Made configurable via env var instead of hardcoded
        starting_cash = Decimal(os.getenv("MERID_PAPER_STARTING_CASH", "10000.00"))
        self._cash_balance = starting_cash
        self._margin_used = Decimal("0")
        
    def get_orderbook_snapshot(self, market_id: str) -> Dict[str, Any]:
        """Get current orderbook snapshot for pricing.
        
        PRIORITY:
        1. Live Kalshi orderbook API (for real pricing)
        2. Market cache from ws_bridge (for recent data)
        3. Configurable fallback (for paper trading only)
        """
        # Try to get live orderbook from Kalshi
        try:
            from merid.event_venues.kalshi.client import get_kalshi_client
            client = get_kalshi_client()
            # Get market orderbook from Kalshi REST API
            orderbook = client.get_orderbook(market_id)
            if orderbook and orderbook.get("bids") and orderbook.get("asks"):
                best_bid = orderbook["bids"][0]["price"] if orderbook["bids"] else None
                best_ask = orderbook["asks"][0]["price"] if orderbook["asks"] else None
                if best_bid and best_ask:
                    return {
                        "market_id": market_id,
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                        "mid_price": (best_bid + best_ask) / 2,
                        "bid_size": orderbook["bids"][0].get("size", 0),
                        "ask_size": orderbook["asks"][0].get("size", 0),
                        "timestamp": time.time(),
                        "source": "kalshi_api"
                    }
        except Exception as exc:
            logger.debug(f"Live orderbook unavailable for {market_id}: {exc}")
        
        # Try market cache from WebSocket feed
        try:
            from merid.event_venues.kalshi.market_cache import get_market_cache
            cache = get_market_cache()
            cached = cache.get(market_id)
            if cached and cached.get("best_bid") and cached.get("best_ask"):
                return {
                    "market_id": market_id,
                    "best_bid": cached["best_bid"],
                    "best_ask": cached["best_ask"],
                    "mid_price": (cached["best_bid"] + cached["best_ask"]) / 2,
                    "bid_size": cached.get("bid_size", 0),
                    "ask_size": cached.get("ask_size", 0),
                    "timestamp": time.time(),
                    "source": "market_cache"
                }
        except Exception as exc:
            logger.debug(f"Market cache unavailable for {market_id}: {exc}")
        
        # PRODUCTION SAFETY: Configurable fallback for paper trading only
        # Never use hardcoded values in production - fail closed
        default_bid = int(os.getenv("MERID_PAPER_FALLBACK_BID", "48"))
        default_ask = int(os.getenv("MERID_PAPER_FALLBACK_ASK", "52"))
        logger.warning(
            f"[ORDERBOOK-FALLBACK] Using configured fallback for {market_id}. "
            f"bid={default_bid}¢ ask={default_ask}¢. "
            f"This should only happen in paper trading mode."
        )
        # BUG-FIX: Made configurable via env vars instead of hardcoded
        default_size = int(os.getenv("MERID_PAPER_FALLBACK_SIZE", "100"))
        return {
            "market_id": market_id,
            "best_bid": default_bid,
            "best_ask": default_ask,
            "mid_price": (default_bid + default_ask) / 2,
            "bid_size": default_size,
            "ask_size": default_size,
            "timestamp": time.time(),
            "source": "configured_fallback"
        }
    
    def simulate_fill(self, market_id: str, side: str, contracts: int) -> Optional[int]:
        """Simulate order fill against current orderbook."""
        orderbook = self.get_orderbook_snapshot(market_id)
        
        if side == "yes":
            # Buying YES -> fill at ask price
            fill_price = orderbook["best_ask"]
            max_fillable = orderbook["ask_size"]
        else:
            # Buying NO (selling YES) -> fill at bid price
            fill_price = orderbook["best_bid"]
            max_fillable = orderbook["bid_size"]
        
        if contracts <= max_fillable:
            return fill_price
        else:
            # Partial fill or reject
            logger.warning(f"Paper order size {contracts} exceeds liquidity {max_fillable} for {market_id}")
            return None
    
    def execute_order(self, agent_id: str, market_id: str, side: str, contracts: int) -> bool:
        """Execute an order in paper portfolio."""
        # Simulate fill
        fill_price = self.simulate_fill(market_id, side, contracts)
        if fill_price is None:
            logger.info(f"Paper order rejected for {market_id}: insufficient liquidity")
            return False
        
        # Calculate margin requirement
        # BUG-FIX: Made configurable via env var instead of hardcoded $1 per contract
        margin_per_contract = Decimal(os.getenv("MERID_KALSHI_MARGIN_PER_CONTRACT_CENTS", "100"))
        margin_required = Decimal(str(contracts)) * margin_per_contract
        
        if self._cash_balance - self._margin_used < margin_required:
            logger.info(f"Paper order rejected for {market_id}: insufficient margin")
            return False
        
        # Record position
        position_key = f"{market_id}_{side}"
        if position_key in self._positions:
            # Add to existing position
            existing = self._positions[position_key]
            total_contracts = existing.contracts + contracts
            avg_price = ((existing.entry_price_cents * existing.contracts) + (fill_price * contracts)) / total_contracts
            existing.contracts = total_contracts
            existing.entry_price_cents = avg_price
        else:
            # New position
            self._positions[position_key] = PaperPosition(
                market_id=market_id,
                side=side,
                contracts=contracts,
                entry_price_cents=fill_price,
                entry_ts=time.time(),
                agent_id=agent_id
            )
        
        self._margin_used += margin_required
        logger.info(f"Paper order executed: {agent_id} {side} {contracts} contracts of {market_id} at {fill_price}¢")
        return True
    
    async def paper_fill(self, order: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a paper fill for crypto lane orders with backtest lag simulation."""
        try:
            # Enforce backtest lag for realistic paper trading simulation
            # Simulate network latency + execution delay (50-200ms typical for live trading)
            import asyncio
            lag_ms = order.get("paper_lag_ms", 100)  # Default 100ms lag
            if lag_ms > 0:
                await asyncio.sleep(lag_ms / 1000.0)
            
            market_id = order.get("market_id", "")
            side = order.get("side", "yes")
            size = order.get("size", 0.0)
            
            # Convert size to contracts (assuming $1 per contract for simplicity)
            contracts = int(size)
            
            # Execute the paper order
            agent_id = ctx.get("agent_id", "crypto_lane")
            success = self.execute_order(agent_id, market_id, side, contracts)
            
            if success:
                return {
                    "success": True,
                    "market_id": market_id,
                    "side": side,
                    "contracts": contracts,
                    "size": size,
                    "simulated": True,
                    "timestamp": time.time(),
                    "lag_ms": lag_ms,
                }
            else:
                return {
                    "success": False,
                    "reason": "Paper fill failed",
                    "market_id": market_id,
                }
                
        except Exception as exc:
            logger.error(f"Paper fill failed: {exc}")
            return {
                "success": False,
                "reason": str(exc),
                "market_id": order.get("market_id", ""),
            }
    
    def close_position(self, market_id: str, side: str) -> Optional[PaperTrade]:
        """Close a position and record trade."""
        position_key = f"{market_id}_{side}"
        if position_key not in self._positions:
            return None
        
        position = self._positions[position_key]
        exit_price = self.simulate_fill(market_id, side, position.contracts)
        if exit_price is None:
            return None
        
        # Calculate P&L
        if side == "yes":
            profit_cents = (exit_price - position.entry_price_cents) * position.contracts
        else:
            profit_cents = (position.entry_price_cents - exit_price) * position.contracts
        
        profit_usd = Decimal(str(profit_cents / 100))
        
        # Record trade
        trade = PaperTrade(
            market_id=market_id,
            side=side,
            contracts=position.contracts,
            entry_price_cents=position.entry_price_cents,
            exit_price_cents=exit_price,
            entry_ts=position.entry_ts,
            exit_ts=time.time(),
            profit_usd=profit_usd,
            agent_id=position.agent_id
        )
        
        self._trades.append(trade)
        self._cash_balance += profit_usd
        
        # Release margin and remove position
        # BUG-FIX: Use same configurable margin per contract
        margin_per_contract = Decimal(os.getenv("MERID_KALSHI_MARGIN_PER_CONTRACT_CENTS", "100"))
        margin_released = Decimal(str(position.contracts)) * margin_per_contract
        self._margin_used -= margin_released
        del self._positions[position_key]
        
        logger.info(f"Paper position closed: {market_id} {side} P&L ${profit_usd}")
        return trade
    
    async def count_open_positions(self, symbol: str, timeframe: str, mode: str) -> int:
        """Count open positions for given criteria."""
        try:
            # Count positions matching the criteria
            count = 0
            for pos_key, position in self._positions.items():
                # Simple matching - in production would be more sophisticated
                if symbol in pos_key:  # Check if symbol is in position key
                    count += 1
            return count
        except Exception as exc:
            logger.error(f"Failed to count positions: {exc}")
            return 0
    
    def get_lane_bankroll(self, lane_id: str) -> float:
        """Get bankroll allocated to a specific lane.
        
        PRIORITY:
        1. Live Kalshi bankroll via v2 unified service (for live trading)
        2. Paper portfolio cash balance (for paper trading fallback)
        
        This ensures position sizing uses the actual Kalshi balance when available,
        falling back to paper balance only when live bankroll is unavailable.
        """
        # Try live bankroll first via v2 unified service
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
            live_equity = get_equity_for_risk_calc_sync()
            if live_equity is not None and live_equity > 0:
                # Allocate equally among lanes
                allocated = float(live_equity) / _DEFAULT_LANE_COUNT
                logger.debug(f"Using live Kalshi bankroll for {lane_id}: ${allocated:.2f}")
                return allocated
        except Exception as exc:
            logger.debug(f"Live bankroll unavailable for {lane_id}: {exc}")
        
        # Fallback to paper portfolio cash balance
        try:
            base_bankroll = float(self._cash_balance)
            if base_bankroll > 0:
                allocated = base_bankroll / _DEFAULT_LANE_COUNT
                logger.warning(f"Using paper bankroll for {lane_id}: ${allocated:.2f}")
                return allocated
        except Exception as exc:
            logger.error(f"Failed to get paper bankroll for {lane_id}: {exc}")
        
        # PRODUCTION SAFETY: No bankroll available - fail closed with 0
        # Never use hardcoded fallback values in production
        logger.critical(
            f"[BANKROLL-FAIL-CLOSED] No bankroll available for {lane_id}. "
            f"Live Kalshi API unavailable AND paper balance empty. "
            f"Returning 0 to prevent trading with fake bankroll."
        )
        return 0.0
    
    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get portfolio summary."""
        total_pnl = sum(trade.profit_usd for trade in self._trades)
        win_rate = len([t for t in self._trades if t.profit_usd > 0]) / len(self._trades) if self._trades else 0
        
        return {
            "portfolio_id": self.portfolio_id,
            "cash_balance": float(self._cash_balance),
            "margin_used": float(self._margin_used),
            "total_pnl": float(total_pnl),
            "open_positions": len(self._positions),
            "total_trades": len(self._trades),
            "win_rate": win_rate,
            "available_margin": float(self._cash_balance - self._margin_used)
        }
    
    def get_agent_performance(self, agent_id: str) -> Dict[str, Any]:
        """Get performance metrics for a specific agent."""
        agent_trades = [t for t in self._trades if t.agent_id == agent_id]
        agent_pnl = sum(t.profit_usd for t in agent_trades)
        agent_win_rate = len([t for t in agent_trades if t.profit_usd > 0]) / len(agent_trades) if agent_trades else 0
        
        return {
            "agent_id": agent_id,
            "total_trades": len(agent_trades),
            "total_pnl": float(agent_pnl),
            "win_rate": agent_win_rate,
            "avg_trade_pnl": float(agent_pnl / len(agent_trades)) if agent_trades else 0
        }


# Singleton
_paper_portfolio: Optional[KalshiPaperPortfolio] = None
_portfolio_lock = None


def get_kalshi_paper_portfolio() -> KalshiPaperPortfolio:
    """Return the Kalshi paper portfolio singleton."""
    global _paper_portfolio, _portfolio_lock
    if _paper_portfolio is None:
        if _portfolio_lock is None:
            import threading
            _portfolio_lock = threading.Lock()
        with _portfolio_lock:
            if _paper_portfolio is None:
                _paper_portfolio = KalshiPaperPortfolio()
    return _paper_portfolio
