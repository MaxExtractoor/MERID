"""
Live Correlation Bot Deployment Skeleton

Production-ready skeleton for deploying the Kalshi correlation/arbitrage bot
with rate limiting, risk checks, and logging.

Usage:
    bot = LiveCorrelationBot(
        event_tickers=["KXBTC-DAILY", "KXBTC-HOURLY"],
        max_qps=1.0,
    )
    bot.run()  # Starts the main loop
"""

import asyncio
import time
import logging
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading

from merid.risk.crypto_swarm_risk_btc15m import (
    CryptoSwarmRiskBTC15m,
    TradeProposal as RiskProposal,
    TradeMode,
    RiskPhase,
)

logger = logging.getLogger(__name__)


@dataclass
class BotConfig:
    """Configuration for live correlation bot."""
    event_tickers: List[str]
    max_qps: float = 1.0                    # Max queries per second
    scan_interval: float = 5.0             # Seconds between full scans
    min_edge: float = 0.02                   # Minimum edge for trading
    fee_bp: float = 10.0                     # Fees in basis points
    max_position_size: float = 100.0        # Max dollars per trade
    enable_trading: bool = False            # Set True to enable live orders
    log_opportunities: bool = True          # Log all detected opportunities


@dataclass
class BotStats:
    """Runtime statistics for the bot."""
    scans_completed: int = 0
    opportunities_found: int = 0
    trades_attempted: int = 0
    trades_executed: int = 0
    errors: int = 0
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def runtime_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.start_time).total_seconds()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "scans_completed": self.scans_completed,
            "opportunities_found": self.opportunities_found,
            "trades_attempted": self.trades_attempted,
            "trades_executed": self.trades_executed,
            "errors": self.errors,
            "runtime_seconds": self.runtime_seconds,
        }


class LiveCorrelationBot:
    """
    Live deployment skeleton for Kalshi correlation/arbitrage bot.
    
    Features:
    - Strict QPS rate limiting (respects Kalshi API tiers)
    - Risk layer integration (caps, FG regime, sentiment)
    - Opportunity logging for analysis
    - Graceful shutdown handling
    
    Usage:
        config = BotConfig(
            event_tickers=["KXBTC-DAILY", "KXBTC-HOURLY"],
            max_qps=1.0,
            enable_trading=False,  # Start in monitoring mode
        )
        
        bot = LiveCorrelationBot(config)
        
        # Run in background thread
        bot.start()
        
        # Or run blocking
        # bot.run()
        
        # Later...
        bot.stop()
    """
    
    def __init__(
        self,
        config: BotConfig,
        kalshi_session=None,
        risk_engine: Optional[CryptoSwarmRiskBTC15m] = None,
        equity: float = 0.0,
    ):
        self.config = config
        self.ksession = kalshi_session
        # Use provided engine or create a default one
        if risk_engine is not None:
            self.risk_engine: CryptoSwarmRiskBTC15m = risk_engine
        else:
            _init_phase = RiskPhase.PHASE_0
            try:
                from merid.risk.promotion_engine import get_promotion_engine
                _phase_name = get_promotion_engine().current_phase.name
                _init_phase = RiskPhase[_phase_name] if _phase_name in RiskPhase.__members__ else RiskPhase.PHASE_0
            except Exception as _e:
                logger.debug("phase_lookup_promotion_engine: %s", _e)
            self.risk_engine = CryptoSwarmRiskBTC15m(current_equity=equity, phase=_init_phase)
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stats = BotStats()
        self._last_request_time = 0.0
        self._min_interval = 1.0 / config.max_qps if config.max_qps > 0 else 1.0
        
        # Opportunity log
        self._opportunities: List[Dict[str, Any]] = []
        self._max_opps_log = 1000
    
    def _rate_limit(self):
        """Enforce QPS rate limiting."""
        now = time.time()
        elapsed = now - self._last_request_time
        
        if elapsed < self._min_interval:
            sleep_time = self._min_interval - elapsed
            time.sleep(sleep_time)
        
        self._last_request_time = time.time()
    
    def _fetch_markets_for_event(self, event_ticker: str) -> List[Dict[str, Any]]:
        """Fetch markets with rate limiting."""
        self._rate_limit()
        
        if self.ksession is None:
            logger.warning("No Kalshi session, returning empty list")
            return []
        
        try:
            # Placeholder for actual Kalshi API call
            # resp = self.ksession.request("GET", "/markets", ...)
            # return resp.json().get("markets", [])
            
            # For now, return synthetic data for testing
            return self._synthetic_markets(event_ticker)
            
        except Exception as exc:
            logger.error(f"Failed to fetch markets for {event_ticker}: {exc}")
            self._stats.errors += 1
            return []
    
    def _synthetic_markets(self, event_ticker: str) -> List[Dict[str, Any]]:
        """Generate synthetic market data for testing."""
        import random
        
        # Generate 3-5 markets per event
        num_markets = random.randint(3, 5)
        markets = []
        
        for i in range(num_markets):
            # Random YES/NO prices that sum close to 1
            yes_price = random.randint(30, 70)
            no_price = 100 - yes_price + random.randint(-2, 2)
            
            markets.append({
                "ticker": f"{event_ticker}-M{i+1}",
                "title": f"Market {i+1} for {event_ticker}",
                "yes_price": yes_price,
                "no_price": no_price,
            })
        
        return markets
    
    def _find_arbitrage_opportunities(
        self,
        markets: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Find YES/NO sum arbitrage opportunities."""
        opps = []
        fee_decimal = self.config.fee_bp / 10000.0
        
        for m in markets:
            ticker = m.get("ticker", "unknown")
            yes_price = m.get("yes_price", 50) / 100.0
            no_price = m.get("no_price", 50) / 100.0
            
            total = yes_price + no_price
            edge = abs(1.0 - total)
            
            # Require edge > fees + min profit
            threshold = fee_decimal + self.config.min_edge
            
            if edge > threshold:
                opp = {
                    "market": ticker,
                    "edge": edge - fee_decimal,
                    "yes_price": yes_price,
                    "no_price": no_price,
                    "total": total,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                opps.append(opp)
        
        return opps
    
    def _risk_check(self, opp: Dict[str, Any]) -> bool:
        """
        Check if opportunity passes risk filters via CryptoSwarmRiskBTC15m.

        Returns True if allowed to trade.
        """
        if opp["edge"] < self.config.min_edge:
            return False

        proposal = RiskProposal(
            asset="BTC",
            timeframe="arb",
            side="yes",
            price_cents=int(opp.get("yes_price", 0.5) * 100),
            intent_risk=min(self.config.max_position_size, 50.0),
            tags=["arb", "correlation_bot"],
        )
        decision = self.risk_engine.evaluate_arb_proposal(proposal)

        if decision.mode == TradeMode.BLOCKED:
            logger.info("Risk blocked arb opp %s: %s", opp.get("market"), decision.reason)
            return False

        return True
    
    def _compute_position_size(self, opp: Dict[str, Any]) -> float:
        """Compute safe position size via risk engine."""
        base_size = 50.0
        edge_mult = min(2.0, 1.0 + opp["edge"] * 10)
        size = base_size * edge_mult

        # Apply config cap first
        size = min(size, self.config.max_position_size)

        # Run through dedicated arb risk path for final approved size
        proposal = RiskProposal(
            asset="BTC",
            timeframe="arb",
            side="yes",
            price_cents=int(opp.get("yes_price", 0.5) * 100),
            intent_risk=size,
            tags=["arb", "correlation_bot"],
        )
        decision = self.risk_engine.evaluate_arb_proposal(proposal)
        return decision.final_size
    
    def _execute_trade(self, opp: Dict[str, Any], size: float) -> bool:
        """
        Execute arbitrage trade.
        
        Returns True if successful.
        """
        self._stats.trades_attempted += 1
        
        if not self.config.enable_trading:
            logger.info(
                f"[PAPER] Would trade {opp['market']} size=${size:.2f} "
                f"edge={opp['edge']:.2%}"
            )
            return True
        
        # Live trading — route through KalshiExecutor
        try:
            from merid.execution.executors.kalshi import KalshiExecutor
            executor = KalshiExecutor()

            # Run the async execute_trade in a new event loop if none is running
            async def _submit():
                return await executor.execute_trade(
                    symbol=opp["market"],
                    side="buy",
                    amount=size,
                    order_type="market",
                    metadata={"outcome": "yes", "source": "correlation_bot"},
                )

            try:
                import concurrent.futures
                loop = asyncio.get_running_loop()
                future = asyncio.run_coroutine_threadsafe(_submit(), loop)
                result = future.result(timeout=10)
            except RuntimeError:
                result = asyncio.run(_submit())

            if result.success:
                logger.info(
                    "[LIVE] Executed %s size=%.2f order_id=%s",
                    opp["market"], size, result.tx_id,
                )
                self._stats.trades_executed += 1
                return True
            else:
                logger.error("[LIVE] Order failed for %s: %s", opp["market"], result.error)
                self._stats.errors += 1
                return False

        except Exception as exc:
            logger.error("Trade execution failed: %s", exc)
            self._stats.errors += 1
            return False
    
    def _scan_cycle(self):
        """Perform one full scan cycle."""
        all_opportunities = []
        
        for event in self.config.event_tickers:
            # Fetch markets
            markets = self._fetch_markets_for_event(event)
            
            if not markets:
                continue
            
            # Find arbs
            opps = self._find_arbitrage_opportunities(markets)
            all_opportunities.extend(opps)
        
        # Process opportunities
        for opp in all_opportunities:
            self._stats.opportunities_found += 1
            
            # Log opportunity
            if self.config.log_opportunities:
                self._log_opportunity(opp)
            
            # Risk check
            if not self._risk_check(opp):
                continue
            
            # Compute size
            size = self._compute_position_size(opp)
            
            if size <= 0:
                continue
            
            # Execute
            self._execute_trade(opp, size)
        
        self._stats.scans_completed += 1
        
        # Log progress
        if self._stats.scans_completed % 10 == 0:
            logger.info(f"Bot stats: {self._stats.to_dict()}")
    
    def _log_opportunity(self, opp: Dict[str, Any]):
        """Log opportunity for later analysis."""
        self._opportunities.append(opp)
        
        # Trim log
        if len(self._opportunities) > self._max_opps_log:
            self._opportunities = self._opportunities[-self._max_opps_log:]
    
    def run(self):
        """Run the bot main loop (blocking)."""
        logger.info(f"Starting correlation bot with config: {self.config}")
        self._running = True
        
        try:
            while self._running:
                self._scan_cycle()
                
                # Sleep between scans
                time.sleep(self.config.scan_interval)
                
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        except Exception as exc:
            logger.error(f"Bot error: {exc}")
            self._stats.errors += 1
        finally:
            self._running = False
            logger.info(f"Bot stopped. Final stats: {self._stats.to_dict()}")
    
    def start(self):
        """Start the bot in a background thread."""
        if self._running:
            logger.warning("Bot already running")
            return
        
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()
        logger.info("Bot started in background thread")
    
    def stop(self):
        """Stop the bot gracefully."""
        logger.info("Stopping bot...")
        self._running = False
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        
        logger.info("Bot stopped")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current bot statistics."""
        return {
            "running": self._running,
            **self._stats.to_dict(),
        }
    
    def get_opportunities(self, n: int = 100) -> List[Dict[str, Any]]:
        """Get recent opportunities."""
        return self._opportunities[-n:]


# ── Convenience functions ──────────────────────────────────────────

def run_correlation_bot(
    event_tickers: List[str],
    max_qps: float = 1.0,
    enable_trading: bool = False,
) -> LiveCorrelationBot:
    """
    Quick one-liner to start a correlation bot.
    
    Args:
        event_tickers: List of event tickers to scan
        max_qps: Max API queries per second
        enable_trading: Set True for live trading (default: paper)
    
    Returns:
        Running LiveCorrelationBot instance
    """
    config = BotConfig(
        event_tickers=event_tickers,
        max_qps=max_qps,
        enable_trading=enable_trading,
    )
    
    bot = LiveCorrelationBot(config)
    bot.start()
    
    return bot


def quick_scan(
    event_ticker: str,
    kalshi_session=None,
) -> List[Dict[str, Any]]:
    """
    Quick one-off scan for arbitrage opportunities.
    
    Returns:
        List of opportunities
    """
    config = BotConfig(
        event_tickers=[event_ticker],
        max_qps=2.0,  # Higher QPS for one-off
        scan_interval=0.0,  # Single scan
    )
    
    bot = LiveCorrelationBot(config, kalshi_session=kalshi_session)
    
    # Just do one cycle
    bot._scan_cycle()
    
    return bot.get_opportunities()
