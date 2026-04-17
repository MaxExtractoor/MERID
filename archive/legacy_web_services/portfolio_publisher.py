"""Real-time portfolio data publisher for WebSocket streaming."""

import asyncio
import threading
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
        
        # Connect to real paper trading engine
        self.trading_engine = get_paper_trading_engine()
        
        logger.info(f"PortfolioPublisher initialized with REAL data from PaperTradingEngine")
    
    async def start(self):
        """Start publishing portfolio updates."""
        if self.running:
            logger.warning("Portfolio publisher already running")
            return
        
        self.running = True
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
                portfolio_data = await self._get_portfolio_data()
                source = portfolio_data.get("source", "?")
                logger.info(
                    "💼 portfolio (%s): $%,.2f | P&L: $%,.2f",
                    source, portfolio_data["total_value"], portfolio_data["pnl_today"],
                )
                await self.event_stream.publish("portfolio_update", portfolio_data)
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            logger.info("Portfolio publisher loop cancelled")
        except Exception as e:
            logger.error(f"Error in portfolio publisher loop: {e}", exc_info=True)

    async def _get_portfolio_data(self) -> Dict:
        """Get portfolio data — Kalshi live first, paper engine fallback."""
        # ── Primary: real Kalshi balance ──
        try:
            from merid.execution.executors.kalshi import KalshiExecutor
            if not hasattr(self, '_kalshi_exec'):
                self._kalshi_exec = KalshiExecutor()
            bal = await self._kalshi_exec.get_balance()
            positions = await self._kalshi_exec.get_positions()
            usd = bal.get("usd_dollars", 0.0) if isinstance(bal, dict) else 0.0
            pos_count = len(positions) if isinstance(positions, list) else 0

            daily_pnl = 0.0
            try:
                from merid.risk.kill_switches import risk_controller
                daily_pnl = float(risk_controller.get_status().get("daily_pnl", 0.0))
            except Exception:
                pass

            if usd > 0:
                return {
                    "total_value": round(usd, 2),
                    "change_24h": round(daily_pnl, 2),
                    "change_24h_percent": round((daily_pnl / usd) * 100, 2) if usd > 0 else 0.0,
                    "pnl_today": round(daily_pnl, 2),
                    "positions_count": pos_count,
                    "total_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "timestamp": int(time.time() * 1000),
                    "source": "kalshi_live",
                }
        except Exception as exc:
            logger.debug("Kalshi portfolio fetch failed: %s", exc)

        # ── Fallback: PaperTradingEngine ──
        try:
            portfolio = self.trading_engine.get_portfolio(self.user_id)
            total_value = portfolio.current_balance
            for position in portfolio.positions.values():
                total_value += position.size_usd + position.unrealized_pnl
            change_24h = portfolio.total_pnl
            return {
                "total_value": round(total_value, 2),
                "change_24h": round(change_24h, 2),
                "change_24h_percent": round((change_24h / portfolio.starting_balance) * 100, 2) if portfolio.starting_balance > 0 else 0.0,
                "pnl_today": round(portfolio.total_pnl, 2),
                "positions_count": len(portfolio.positions),
                "total_trades": portfolio.total_trades,
                "winning_trades": portfolio.winning_trades,
                "losing_trades": portfolio.losing_trades,
                "timestamp": int(time.time() * 1000),
                "source": "paper_engine",
            }
        except Exception as e:
            logger.error(f"Failed to get portfolio data: {e}")

        return {
            "total_value": 0.0, "change_24h": 0.0, "change_24h_percent": 0.0,
            "pnl_today": 0.0, "positions_count": 0, "total_trades": 0,
            "winning_trades": 0, "losing_trades": 0,
            "timestamp": int(time.time() * 1000), "source": "unavailable",
        }


# Global instance
_portfolio_publisher: PortfolioPublisher = None
_portfolio_publisher_lock = threading.Lock()


def get_portfolio_publisher() -> PortfolioPublisher:
    """Get the global portfolio publisher instance."""
    global _portfolio_publisher
    if _portfolio_publisher is None:
        with _portfolio_publisher_lock:
            if _portfolio_publisher is None:
                _portfolio_publisher = PortfolioPublisher()
    return _portfolio_publisher
