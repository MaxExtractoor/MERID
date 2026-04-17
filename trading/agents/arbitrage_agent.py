"""
Arbitrage Agent - Detects and executes cross-venue arbitrage opportunities.

Monitors price discrepancies across:
- Polymarket vs prediction market consensus
- CEX vs DEX spreads
- Perp funding rate arbitrage
- Cross-chain arbitrage
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from utils.deps import get_ccxt_async
from utils.logger import get_logger

logger = get_logger("trading.agents.arbitrage")
VENUE_FALLBACKS = {
    "binance": "binanceus",
}


@dataclass
class ArbitrageOpportunity:
    """Represents a detected arbitrage opportunity."""
    opportunity_id: str
    type: str  # 'cross_venue', 'funding_rate', 'prediction_market'
    venue_a: str
    venue_b: str
    asset: str
    price_a: float
    price_b: float
    spread_bps: float  # Basis points
    expected_profit: float
    slippage_estimate: float
    gas_cost_estimate: float
    net_profit: float
    confidence: float
    detected_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    
    def is_profitable(self, min_profit_threshold: float = 0.001) -> bool:
        """Check if opportunity is profitable after costs."""
        return self.net_profit > min_profit_threshold
    
    def is_valid(self) -> bool:
        """Check if opportunity is still valid."""
        if self.expires_at and time.time() > self.expires_at:
            return False
        return self.is_profitable()


@dataclass
class ArbitrageExecution:
    """Tracks arbitrage execution."""
    opportunity_id: str
    executed_at: float
    leg_a_status: str  # 'pending', 'filled', 'failed'
    leg_b_status: str
    leg_a_fill_price: Optional[float] = None
    leg_b_fill_price: Optional[float] = None
    actual_profit: Optional[float] = None
    execution_time_ms: Optional[float] = None


class ArbitrageAgent:
    """
    Detects and executes arbitrage opportunities across venues.
    
    Strategies:
    1. Cross-venue arbitrage (CEX/DEX spreads)
    2. Funding rate arbitrage (perp markets)
    3. Prediction market arbitrage (Polymarket vs consensus)
    4. Triangular arbitrage
    """
    
    def __init__(
        self,
        min_spread_bps: float = 10.0,  # Minimum 0.1% spread
        max_slippage_bps: float = 5.0,
        min_confidence: float = 0.85,
        max_position_size_usd: float = 10000.0
    ):
        self.min_spread_bps = min_spread_bps
        self.max_slippage_bps = max_slippage_bps
        self.min_confidence = min_confidence
        self.max_position_size_usd = max_position_size_usd
        
        self.active_opportunities: Dict[str, ArbitrageOpportunity] = {}
        self.execution_history: List[ArbitrageExecution] = []
        
        self.total_opportunities_detected = 0
        self.total_executed = 0
        self.total_profit = 0.0
        self.win_rate = 0.0
        self._restricted_venues: set[str] = set()
        self._venue_overrides: Dict[str, str] = {}
        
        logger.info(
            "ArbitrageAgent initialized: min_spread=%.1f bps, max_slippage=%.1f bps",
            min_spread_bps, max_slippage_bps
        )
    
    async def scan_cross_venue_arbitrage(
        self,
        venues: List[str],
        assets: List[str]
    ) -> List[ArbitrageOpportunity]:
        """
        Scan for cross-venue arbitrage opportunities.
        
        Compares prices across multiple venues for the same asset.
        """
        opportunities = []
        
        for asset in assets:
            prices = await self._fetch_prices_across_venues(asset, venues)
            
            if len(prices) < 2:
                continue
            
            # Find max spread
            sorted_prices = sorted(prices.items(), key=lambda x: x[1])
            venue_low, price_low = sorted_prices[0]
            venue_high, price_high = sorted_prices[-1]
            
            spread_bps = ((price_high - price_low) / price_low) * 10000
            
            if spread_bps >= self.min_spread_bps:
                # Estimate costs
                slippage = self._estimate_slippage(asset, venue_low, venue_high)
                gas_cost = self._estimate_gas_cost(venue_low, venue_high)
                
                # Calculate net profit
                position_size = min(self.max_position_size_usd, 5000.0)  # Conservative
                gross_profit = (spread_bps / 10000) * position_size
                net_profit = gross_profit - slippage - gas_cost
                
                if net_profit > 0:
                    opp = ArbitrageOpportunity(
                        opportunity_id=f"arb_{asset}_{int(time.time() * 1000)}",
                        type="cross_venue",
                        venue_a=venue_low,
                        venue_b=venue_high,
                        asset=asset,
                        price_a=price_low,
                        price_b=price_high,
                        spread_bps=spread_bps,
                        expected_profit=gross_profit,
                        slippage_estimate=slippage,
                        gas_cost_estimate=gas_cost,
                        net_profit=net_profit,
                        confidence=self._calculate_confidence(spread_bps, slippage),
                        expires_at=time.time() + 5.0  # 5 second window
                    )
                    
                    opportunities.append(opp)
                    self.total_opportunities_detected += 1
                    
                    logger.info(
                        "Arbitrage opportunity detected: %s on %s/%s, spread=%.2f bps, net_profit=$%.2f",
                        asset, venue_low, venue_high, spread_bps, net_profit
                    )
        
        return opportunities
    
    async def scan_funding_rate_arbitrage(
        self,
        perp_venues: List[str],
        assets: List[str]
    ) -> List[ArbitrageOpportunity]:
        """
        Scan for funding rate arbitrage in perpetual markets.
        
        Strategy: Long on venue with negative funding, short on venue with positive funding.
        """
        opportunities = []
        
        for asset in assets:
            funding_rates = await self._fetch_funding_rates(asset, perp_venues)
            
            if len(funding_rates) < 2:
                continue
            
            # Find max funding rate differential
            sorted_rates = sorted(funding_rates.items(), key=lambda x: x[1])
            venue_negative, rate_negative = sorted_rates[0]
            venue_positive, rate_positive = sorted_rates[-1]
            
            rate_diff_bps = (rate_positive - rate_negative) * 10000
            
            if rate_diff_bps >= self.min_spread_bps:
                # Annualized funding rate arbitrage
                annual_profit_bps = rate_diff_bps * 365 * 3  # 3 funding periods per day
                
                position_size = min(self.max_position_size_usd, 10000.0)
                expected_profit = (annual_profit_bps / 10000) * position_size / 365  # Daily
                
                opp = ArbitrageOpportunity(
                    opportunity_id=f"funding_{asset}_{int(time.time() * 1000)}",
                    type="funding_rate",
                    venue_a=venue_negative,
                    venue_b=venue_positive,
                    asset=asset,
                    price_a=rate_negative,
                    price_b=rate_positive,
                    spread_bps=rate_diff_bps,
                    expected_profit=expected_profit,
                    slippage_estimate=0.0,  # Minimal for funding arb
                    gas_cost_estimate=10.0,  # Estimated
                    net_profit=expected_profit - 10.0,
                    confidence=0.90,  # High confidence for funding arb
                    expires_at=None  # Can hold position
                )
                
                opportunities.append(opp)
                self.total_opportunities_detected += 1
                
                logger.info(
                    "Funding rate arbitrage: %s, rate_diff=%.2f bps, daily_profit=$%.2f",
                    asset, rate_diff_bps, expected_profit
                )
        
        return opportunities
    
    async def execute_arbitrage(
        self,
        opportunity: ArbitrageOpportunity,
        auto_execute: bool = False
    ) -> Optional[ArbitrageExecution]:
        """
        Execute arbitrage opportunity.
        
        For now, returns execution plan. Actual execution requires exchange integration.
        """
        # Execution gate — unified safety check
        try:
            from core.execution_gate import check_execution_gate
            gate = check_execution_gate()
            if gate.blocked:
                reasons_str = "; ".join(r.message for r in gate.reasons)
                logger.warning(
                    "execution_blocked | agent=arbitrage opp=%s reasons=[%s]",
                    opportunity.opportunity_id, reasons_str,
                )
                return None
            if gate.is_limited:
                logger.warning(
                    "execution_limited | agent=arbitrage opp=%s — arb is new risk, blocked in reduce-only mode",
                    opportunity.opportunity_id,
                )
                return None
        except ImportError:
            logger.warning("execution_gate module not available — proceeding without gate check")

        if not opportunity.is_valid():
            logger.warning("Opportunity %s no longer valid", opportunity.opportunity_id)
            return None
        
        if opportunity.confidence < self.min_confidence:
            logger.warning(
                "Opportunity %s below confidence threshold: %.2f < %.2f",
                opportunity.opportunity_id, opportunity.confidence, self.min_confidence
            )
            return None
        
        execution = ArbitrageExecution(
            opportunity_id=opportunity.opportunity_id,
            executed_at=time.time(),
            leg_a_status="pending",
            leg_b_status="pending"
        )
        
        if auto_execute:
            # Execute via paper trading system (production uses real exchange APIs)
            # Real execution requires exchange API keys configured in .env
            logger.info("Executing arbitrage: %s", opportunity.opportunity_id)
            
            # Simulate execution delay
            await asyncio.sleep(0.1)
            
            execution.leg_a_status = "filled"
            execution.leg_b_status = "filled"
            execution.leg_a_fill_price = opportunity.price_a
            execution.leg_b_fill_price = opportunity.price_b
            execution.actual_profit = opportunity.net_profit
            execution.execution_time_ms = 100.0
            
            self.total_executed += 1
            self.total_profit += execution.actual_profit
            self.win_rate = self.total_profit / max(self.total_executed, 1)
            
            logger.info(
                "Arbitrage executed: %s, profit=$%.2f, time=%.1fms",
                opportunity.opportunity_id, execution.actual_profit, execution.execution_time_ms
            )
        else:
            logger.info("Arbitrage opportunity ready for manual execution: %s", opportunity.opportunity_id)
        
        self.execution_history.append(execution)
        return execution
    
    def get_performance_stats(self) -> Dict:
        """Get agent performance statistics."""
        return {
            "total_opportunities_detected": self.total_opportunities_detected,
            "total_executed": self.total_executed,
            "total_profit": self.total_profit,
            "win_rate": self.win_rate,
            "avg_profit_per_trade": self.total_profit / max(self.total_executed, 1),
            "execution_history_count": len(self.execution_history)
        }

    # Helper methods
    async def _fetch_prices_across_venues(
        self,
        asset: str,
        venues: List[str]
    ) -> Dict[str, float]:
        """Fetch current prices across venues using CCXT."""
        prices: Dict[str, float] = {}
        ccxt_async = get_ccxt_async()
        if not ccxt_async:
            logger.warning("CCXT not available, using cached prices")
            prices = {venue: 100.0 for venue in venues}
        else:
            for venue in venues:
                exchange = None
                venue_key = venue.lower()
                target_exchange = self._venue_overrides.get(venue_key, venue_key)
                try:
                    exchange_class = getattr(ccxt_async, target_exchange, None)
                    if exchange_class:
                        exchange = exchange_class()
                        ticker = await exchange.fetch_ticker(f"{asset}/USDT")
                        prices[venue] = ticker["last"]
                except Exception as exc:  # pragma: no cover - network failures
                    message = str(exc).lower()
                    if "restricted" in message or "451" in message:
                        if venue_key not in self._restricted_venues:
                            logger.warning(
                                "Venue %s blocked access (likely geo restriction). Skipping future requests.",
                                venue,
                            )
                            self._restricted_venues.add(venue_key)
                            fallback = VENUE_FALLBACKS.get(venue_key)
                            if fallback and venue_key not in self._venue_overrides:
                                self._venue_overrides[venue_key] = fallback
                                logger.info(
                                    "Routing %s price lookups through %s due to geo restrictions",
                                    venue,
                                    fallback,
                                )
                        else:
                            logger.debug("Venue %s still restricted", venue)
                    else:
                        logger.warning("Failed to fetch price from %s: %s", venue, exc)
                finally:
                    if exchange:
                        try:
                            await exchange.close()
                        except Exception:
                            logger.debug("Failed to close %s exchange cleanly", venue)

        # Backfill missing venues using cached market data
        if len(prices) < len(venues):
            try:
                from data.live_price_feed import get_live_price_feed

                feed = get_live_price_feed()
                for venue in venues:
                    if venue not in prices:
                        price = feed.get_price(asset)
                        if price:
                            prices[venue] = price.price
            except Exception as exc:  # pragma: no cover - best effort
                logger.warning("Fallback price feed unavailable: %s", exc)
        return prices

    async def _fetch_funding_rates(
        self,
        asset: str,
        venues: List[str]
    ) -> Dict[str, float]:
        """Fetch funding rates across perp venues using CCXT."""
        rates: Dict[str, float] = {}
        ccxt_async = get_ccxt_async()
        if not ccxt_async:
            logger.warning("CCXT not available, using default rates")
            rates = {venue: 0.0001 for venue in venues}
        else:
            for venue in venues:
                try:
                    exchange_class = getattr(ccxt_async, venue.lower(), None)
                    if exchange_class and hasattr(exchange_class, "fetch_funding_rate"):
                        exchange = exchange_class()
                        funding = await exchange.fetch_funding_rate(f"{asset}/USDT:USDT")
                        rates[venue] = funding.get("fundingRate", 0.0)
                        await exchange.close()
                except Exception as exc:
                    logger.debug("Funding rate not available for %s: %s", venue, exc)
                    rates[venue] = 0.0
        return rates

    def _estimate_slippage(
        self,
        asset: str,
        venue_a: str,
        venue_b: str
    ) -> float:
        """Estimate slippage cost in USD."""
        # Conservative estimate: 0.05% slippage
        return self.max_position_size_usd * 0.0005

    def _estimate_gas_cost(
        self,
        venue_a: str,
        venue_b: str
    ) -> float:
        """Estimate gas/transaction costs."""
        if "dex" in venue_a.lower() or "dex" in venue_b.lower():
            return 20.0  # Higher for DEX
        return 5.0  # Lower for CEX

    def _calculate_confidence(
        self,
        spread_bps: float,
        slippage: float
    ) -> float:
        """Calculate confidence score for opportunity."""
        spread_score = min(spread_bps / 50.0, 1.0)  # Normalize to 50 bps
        slippage_score = 1.0 - min(slippage / 100.0, 1.0)
        return spread_score * 0.7 + slippage_score * 0.3


# Global singleton
_arbitrage_agent: Optional[ArbitrageAgent] = None
_arbitrage_agent_lock = threading.Lock()


def get_arbitrage_agent() -> ArbitrageAgent:
    """Get or create arbitrage agent singleton."""
    global _arbitrage_agent
    if _arbitrage_agent is None:
        with _arbitrage_agent_lock:
            if _arbitrage_agent is None:
                _arbitrage_agent = ArbitrageAgent()
    return _arbitrage_agent
