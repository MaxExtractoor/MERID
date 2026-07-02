"""
15M Strategy Performance Tracking - PnL Attribution and Trade Book

Simple trade book for tracking PnL attribution per trade and per asset.
Subscribes to order_fill events and maintains open/closed trade records.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from config.kalshi_crypto_config import kalshi_ticker_to_asset
from config.kalshi_universe import KALSHI_CRYPTO_ASSETS
import logging
import pandas as pd
from datetime import datetime, timezone

from merid.kalshi.maker_bot_advanced import kalshi_event_bus, KalshiEvent

logger = logging.getLogger(__name__)

@dataclass
class OpenPosition:
    """Open position tracking."""
    asset: str
    ticker: str
    side: str  # "long_up" or "long_down"
    qty: int
    avg_price: float
    ts_open: float
    total_cost: float

@dataclass
class ClosedTrade:
    """Closed trade with PnL attribution."""
    asset: str
    ticker: str
    side: str
    qty: int
    entry_price: float
    exit_price: float
    pnl: float
    fees: float
    ts_open: float
    ts_close: float
    holding_time: float
    pnl_percent: float
    reason: str  # "signal_exit", "stop_loss", "take_profit", "manual"

class TradeBook:
    """Trade book for PnL attribution and performance tracking."""
    
    def __init__(self):
        self.open_positions: Dict[str, OpenPosition] = {}
        self.closed_trades: List[ClosedTrade] = []
        self.trade_counter = 0
        
        # Performance metrics
        self.total_pnl = 0.0
        self.total_fees = 0.0
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        
        # Subscribe to order fill events
        kalshi_event_bus.subscribe(self._handle_event)
        
        logger.info("TradeBook initialized")
    
    def _handle_event(self, event: KalshiEvent):
        """Handle events from the event bus."""
        try:
            if event.type == "order_fill":
                self.on_fill(event.payload)
            elif event.type == "position_update":
                self.on_position_update(event.payload)
                
        except Exception as e:
            logger.error(f"Error handling event in TradeBook: {e}")
    
    def on_fill(self, event_payload: Dict):
        """
        Process order fill events.
        
        Args:
            event_payload: Order fill payload with ticker, count, price, side, etc.
        """
        ticker = event_payload.get("ticker")
        asset = self._ticker_to_asset(ticker)
        qty = event_payload.get("count", 0)
        price = event_payload.get("price", 0.0)
        side = event_payload.get("side")  # "buy" or "sell"
        ts = event_payload.get("ts", time.time())
        
        if not ticker or qty == 0 or price == 0:
            logger.warning(f"Invalid fill data: {event_payload}")
            return
        
        # Determine trade side (long_up/long_down) from ticker
        trade_side = self._ticker_to_side(ticker)
        if not trade_side:
            logger.warning(f"Could not determine trade side for ticker: {ticker}")
            return
        
        key = ticker  # One position per ticker for v1
        
        if side == "buy":
            # Opening or adding to position
            self._handle_buy(ticker, asset, trade_side, qty, price, ts)
        else:  # sell
            # Closing or reducing position
            self._handle_sell(ticker, asset, trade_side, qty, price, ts)
    
    def _handle_buy(self, ticker: str, asset: str, side: str, qty: int, price: float, ts: float):
        """Handle buy order (opening position)."""
        pos = self.open_positions.get(ticker)
        
        if pos:
            # Add to existing position
            new_qty = pos.qty + qty
            new_cost = pos.total_cost + (qty * price)
            new_avg = new_cost / new_qty
            
            pos.qty = new_qty
            pos.avg_price = new_avg
            pos.total_cost = new_cost
            
            logger.info(f"Added to position {ticker}: +{qty} @ {price}, new avg: {new_avg:.2f}")
        else:
            # Open new position
            total_cost = qty * price
            self.open_positions[ticker] = OpenPosition(
                asset=asset,
                ticker=ticker,
                side=side,
                qty=qty,
                avg_price=price,
                ts_open=ts,
                total_cost=total_cost
            )
            
            logger.info(f"Opened position {ticker}: {qty} @ {price}")
    
    def _handle_sell(self, ticker: str, asset: str, side: str, qty: int, price: float, ts: float):
        """Handle sell order (closing position)."""
        pos = self.open_positions.get(ticker)
        
        if not pos:
            logger.warning(f"No open position found for {ticker}")
            return
        
        if qty > pos.qty:
            logger.warning(f"Selling more than position size: {qty} > {pos.qty}")
            qty = pos.qty
        
        # Calculate PnL
        pnl_per_contract = price - pos.avg_price
        pnl = pnl_per_contract * qty
        
        # Calculate fees (0.1% per trade)
        entry_fees = pos.avg_price * qty * 0.001
        exit_fees = price * qty * 0.001
        total_fees = entry_fees + exit_fees
        
        # Net PnL
        net_pnl = pnl - total_fees
        
        # Calculate holding time and PnL percentage
        holding_time = ts - pos.ts_open
        pnl_percent = (net_pnl / (pos.avg_price * qty)) * 100 if pos.avg_price * qty > 0 else 0
        
        # Create closed trade record
        trade = ClosedTrade(
            asset=asset,
            ticker=ticker,
            side=side,
            qty=qty,
            entry_price=pos.avg_price,
            exit_price=price,
            pnl=net_pnl,
            fees=total_fees,
            ts_open=pos.ts_open,
            ts_close=ts,
            holding_time=holding_time,
            pnl_percent=pnl_percent,
            reason="signal_exit"  # Default reason
        )
        
        self.closed_trades.append(trade)
        self._update_performance_metrics(trade)
        
        # Update or remove open position
        pos.qty -= qty
        pos.total_cost -= (qty * pos.avg_price)
        
        if pos.qty == 0:
            del self.open_positions[ticker]
            logger.info(f"Closed position {ticker}: PnL ${net_pnl:.2f} ({pnl_percent:.1f}%)")
        else:
            logger.info(f"Reduced position {ticker}: -{qty} @ {price}, remaining: {pos.qty}")
    
    def on_position_update(self, event_payload: Dict):
        """Handle position update events (external updates)."""
        # This can handle position updates from external sources
        if "positions" in event_payload:
            for pos_data in event_payload["positions"]:
                ticker = pos_data.get("ticker")
                count = pos_data.get("count", 0)
                if ticker and count == 0 and ticker in self.open_positions:
                    # Position was externally closed
                    pos = self.open_positions[ticker]
                    self._handle_sell(ticker, pos.asset, pos.side, pos.qty, pos.avg_price, time.time())
    
    def _ticker_to_asset(self, ticker: str) -> Optional[str]:
        """Convert ticker to asset name."""
        try:
            from config.kalshi_crypto_config import kalshi_ticker_to_asset

            return kalshi_ticker_to_asset(ticker)
        except Exception:
            return None
    
    def _ticker_to_side(self, ticker: str) -> Optional[str]:
        """Convert ticker to trade side."""
        if "UP" in ticker:
            return "long_up"
        elif "DOWN" in ticker:
            return "long_down"
        return None
    
    def _update_performance_metrics(self, trade: ClosedTrade):
        """Update performance metrics after trade close."""
        self.total_trades += 1
        self.total_pnl += trade.pnl
        self.total_fees += trade.fees
        
        if trade.pnl > 0:
            self.winning_trades += 1
        else:
            self.losing_trades += 1
    
    def get_performance_summary(self) -> Dict[str, any]:
        """Get comprehensive performance summary."""
        win_rate = self.winning_trades / self.total_trades if self.total_trades > 0 else 0
        net_pnl = self.total_pnl - self.total_fees
        
        # Calculate additional metrics
        avg_trade_pnl = net_pnl / self.total_trades if self.total_trades > 0 else 0
        avg_holding_time = sum(t.holding_time for t in self.closed_trades) / len(self.closed_trades) if self.closed_trades else 0
        
        # Best and worst trades
        best_trade = max(self.closed_trades, key=lambda t: t.pnl) if self.closed_trades else None
        worst_trade = min(self.closed_trades, key=lambda t: t.pnl) if self.closed_trades else None
        
        # Asset-specific performance
        asset_performance = self._get_asset_performance()
        
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": win_rate,
            "total_pnl": self.total_pnl,
            "total_fees": self.total_fees,
            "net_pnl": net_pnl,
            "avg_trade_pnl": avg_trade_pnl,
            "avg_holding_time": avg_holding_time,
            "open_positions": len(self.open_positions),
            "best_trade": {
                "pnl": best_trade.pnl,
                "ticker": best_trade.ticker,
                "pnl_percent": best_trade.pnl_percent
            } if best_trade else None,
            "worst_trade": {
                "pnl": worst_trade.pnl,
                "ticker": worst_trade.ticker,
                "pnl_percent": worst_trade.pnl_percent
            } if worst_trade else None,
            "asset_performance": asset_performance
        }
    
    def _get_asset_performance(self) -> Dict[str, any]:
        """Get performance breakdown by asset."""
        asset_stats = {}
        
        for asset in KALSHI_CRYPTO_ASSETS:
            asset_trades = [t for t in self.closed_trades if t.asset == asset]
            
            if asset_trades:
                asset_pnl = sum(t.pnl for t in asset_trades)
                asset_fees = sum(t.fees for t in asset_trades)
                asset_trades_count = len(asset_trades)
                asset_wins = len([t for t in asset_trades if t.pnl > 0])
                asset_win_rate = asset_wins / asset_trades_count
                
                asset_stats[asset] = {
                    "trades": asset_trades_count,
                    "pnl": asset_pnl,
                    "fees": asset_fees,
                    "net_pnl": asset_pnl - asset_fees,
                    "win_rate": asset_win_rate,
                    "avg_pnl": asset_pnl / asset_trades_count
                }
        
        return asset_stats
    
    def get_recent_trades(self, limit: int = 10) -> List[Dict]:
        """Get recent closed trades."""
        recent_trades = sorted(self.closed_trades, key=lambda t: t.ts_close, reverse=True)[:limit]
        
        return [
            {
                "ticker": trade.ticker,
                "asset": trade.asset,
                "side": trade.side,
                "qty": trade.qty,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "pnl": trade.pnl,
                "pnl_percent": trade.pnl_percent,
                "fees": trade.fees,
                "holding_time": trade.holding_time,
                "ts_close": trade.ts_close,
                "reason": trade.reason
            }
            for trade in recent_trades
        ]
    
    def get_open_positions(self) -> List[Dict]:
        """Get current open positions."""
        return [
            {
                "ticker": pos.ticker,
                "asset": pos.asset,
                "side": pos.side,
                "qty": pos.qty,
                "avg_price": pos.avg_price,
                "total_cost": pos.total_cost,
                "ts_open": pos.ts_open,
                "holding_time": time.time() - pos.ts_open,
                "unrealized_pnl": self._calculate_unrealized_pnl(pos)
            }
            for pos in self.open_positions.values()
        ]
    
    def _calculate_unrealized_pnl(self, pos: OpenPosition) -> float:
        """Calculate unrealized PnL for open position (mock implementation)."""
        # In production, this would use current market prices
        # For now, return 0 (no unrealized PnL calculation)
        return 0.0
    
    def export_trades_to_csv(self, filename: str = None) -> str:
        """Export closed trades to CSV."""
        if filename is None:
            filename = f"trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        if not self.closed_trades:
            logger.warning("No trades to export")
            return filename
        
        # Create DataFrame
        trades_data = []
        for trade in self.closed_trades:
            trades_data.append({
                "ticker": trade.ticker,
                "asset": trade.asset,
                "side": trade.side,
                "qty": trade.qty,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "pnl": trade.pnl,
                "fees": trade.fees,
                "net_pnl": trade.pnl - trade.fees,
                "pnl_percent": trade.pnl_percent,
                "ts_open": datetime.fromtimestamp(trade.ts_open, tz=timezone.utc),
                "ts_close": datetime.fromtimestamp(trade.ts_close, tz=timezone.utc),
                "holding_time": trade.holding_time,
                "reason": trade.reason
            })
        
        df = pd.DataFrame(trades_data)
        df.to_csv(filename, index=False)
        
        logger.info(f"Exported {len(self.closed_trades)} trades to {filename}")
        return filename

# Trade book singleton
trade_book = TradeBook()

# Example usage:
"""
# Trade book automatically subscribes to events
# Get performance summary
summary = trade_book.get_performance_summary()
print(f"Performance: {summary}")

# Get recent trades
recent = trade_book.get_recent_trades(5)
print(f"Recent trades: {recent}")

# Get open positions
positions = trade_book.get_open_positions()
print(f"Open positions: {positions}")

# Export trades
filename = trade_book.export_trades_to_csv()
print(f"Exported trades to {filename}")
"""
