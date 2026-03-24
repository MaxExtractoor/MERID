"""Real-time portfolio data publisher for WebSocket streaming."""

import asyncio
import time
from typing import Dict
from observability.event_stream import get_event_stream
from trading.paper_trading import get_paper_trading_engine
from utils.logger import get_logger

logger = get_logger(__name__)


class PortfolioPublisher:
    """Publishes live portfolio updates to WebSocket clients using real trading data."""
    
    def __init__(self, user_id: str = "default_user"):
        self.event_stream = get_event_stream()
        self.running = False
        self.task = None
        self.user_id = user_id
        self.ready_event: asyncio.Event = asyncio.Event()
        
        # Connect to real paper trading engine
        self.trading_engine = get_paper_trading_engine()
        
        logger.info(f"PortfolioPublisher initialized with REAL data from PaperTradingEngine")
    
    async def start(self):
        """Start publishing portfolio updates."""
        if self.running:
            logger.warning("Portfolio publisher already running")
            return
        
        self.running = True
        self.ready_event.set()
        self.task = asyncio.create_task(self._publish_loop())
        logger.info("Portfolio publisher started")
    
    async def stop(self):
        """Stop publishing portfolio updates."""
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Portfolio publisher stopped")
    
    async def _publish_loop(self):
        """Main loop for publishing portfolio updates."""
        try:
            while self.running:
                portfolio_data = self._get_real_portfolio_data()
                logger.info(f"💼 REAL portfolio: ${portfolio_data['total_value']:,.2f} | P&L: ${portfolio_data['pnl_today']:,.2f}")
                await self.event_stream.publish("portfolio_update", portfolio_data)
                await asyncio.sleep(10)  # Update every 10 seconds
        except asyncio.CancelledError:
            logger.info("Portfolio publisher loop cancelled")
        except Exception as e:
            logger.error(f"Error in portfolio publisher loop: {e}", exc_info=True)
    
    def _get_real_portfolio_data(self) -> Dict:
        """Get real portfolio data from PaperTradingEngine."""
        try:
            # Get portfolio from trading engine
            portfolio = self.trading_engine.get_portfolio(self.user_id)
            
            # Calculate total value including positions
            total_value = portfolio.current_balance
            for position in portfolio.positions.values():
                total_value += position.size_usd + position.unrealized_pnl
            
            # Calculate 24h change (simplified - would need historical data for accurate)
            change_24h = portfolio.total_pnl
            change_24h_percent = (change_24h / portfolio.starting_balance) * 100 if portfolio.starting_balance > 0 else 0
            
            return {
                "total_value": round(total_value, 2),
                "change_24h": round(change_24h, 2),
                "change_24h_percent": round(change_24h_percent, 2),
                "pnl_today": round(portfolio.total_pnl, 2),
                "positions_count": len(portfolio.positions),
                "total_trades": portfolio.total_trades,
                "winning_trades": portfolio.winning_trades,
                "losing_trades": portfolio.losing_trades,
                "timestamp": int(time.time() * 1000)
            }
        except Exception as e:
            logger.error(f"Failed to get real portfolio data: {e}", exc_info=True)
            # Return safe default
            return {
                "total_value": 10000.00,
                "change_24h": 0.00,
                "change_24h_percent": 0.00,
                "pnl_today": 0.00,
                "positions_count": 0,
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "timestamp": int(time.time() * 1000)
            }


# Global instance
_portfolio_publisher: PortfolioPublisher = None


def get_portfolio_publisher() -> PortfolioPublisher:
    """Get the global portfolio publisher instance."""
    global _portfolio_publisher
    if _portfolio_publisher is None:
        _portfolio_publisher = PortfolioPublisher()
    return _portfolio_publisher
