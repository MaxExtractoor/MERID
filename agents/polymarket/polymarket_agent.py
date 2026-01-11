"""
Polymarket Agent - Production-ready arbitrage scanner.

Scans Polymarket CLOB API for BTC binary options mispricing opportunities.
Implements Account88888-style up/down arbitrage strategy.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Optional
from dataclasses import dataclass

import httpx
from agents.base_agent import BaseAgent
from core.energy import create_energy
from core.orchestrator import get_core
from utils.logger import get_logger

logger = get_logger("agents.polymarket")

POLYMARKET_CLOB_API = "https://clob.polymarket.com"
POLYMARKET_GAMMA_API = "https://gamma-api.polymarket.com"


@dataclass
class PolymarketOpportunity:
    """Arbitrage opportunity structure."""
    market_id: str
    condition_id: str
    question: str
    yes_price: float
    no_price: float
    arb_profit: float
    volume_24h: float
    liquidity: float


class PolymarketAgent(BaseAgent):
    """
    Production Polymarket arbitrage scanner.
    
    Monitors binary options markets for mispricing where yes_price + no_price < 1.0,
    indicating risk-free arbitrage opportunity.
    """
    
    def __init__(self):
        role = "Scan Polymarket for BTC binary options mispricing arbitrage opportunities. Identify markets where yes + no prices < 1.0 for risk-free profit."
        super().__init__("polymarket-01", "merid-strategist:latest", role)
        
        self.client = httpx.AsyncClient(timeout=30.0)
        self.min_arb_profit = 0.01  # Minimum 1% profit threshold
        self.min_liquidity = 1000.0  # Minimum $1000 liquidity
        
    async def scan(self) -> List[PolymarketOpportunity]:
        """
        Scan Polymarket for arbitrage opportunities.
        
        Returns:
            List of arbitrage opportunities found
        """
        opportunities = []
        
        try:
            # Fetch active markets from Gamma API
            markets = await self._fetch_active_markets()
            
            for market in markets:
                # Only scan binary markets (2 outcomes)
                if len(market.get('outcomes', [])) != 2:
                    continue
                
                # Check for BTC-related markets
                question = market.get('question', '').lower()
                if 'btc' not in question and 'bitcoin' not in question:
                    continue
                
                # Get current prices from CLOB
                opportunity = await self._check_arbitrage(market)
                
                if opportunity and opportunity.arb_profit >= self.min_arb_profit:
                    opportunities.append(opportunity)
                    logger.info(
                        f"Arbitrage found: {opportunity.question} - "
                        f"Profit: {opportunity.arb_profit:.2%}"
                    )
                    
                    # Create energy for consensus
                    await self._submit_opportunity(opportunity)
            
            return opportunities
            
        except Exception as exc:
            logger.error(f"Polymarket scan error: {exc}")
            return []
    
    async def _fetch_active_markets(self) -> List[Dict]:
        """Fetch active markets from Polymarket Gamma API."""
        try:
            response = await self.client.get(
                f"{POLYMARKET_GAMMA_API}/markets",
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": 100
                }
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            logger.error(f"Failed to fetch markets: {exc}")
            return []
    
    async def _check_arbitrage(self, market: Dict) -> Optional[PolymarketOpportunity]:
        """
        Check if market has arbitrage opportunity.
        
        Args:
            market: Market data from Gamma API
            
        Returns:
            PolymarketOpportunity if arbitrage exists, None otherwise
        """
        try:
            condition_id = market.get('condition_id')
            if not condition_id:
                return None
            
            # Get order book from CLOB
            response = await self.client.get(
                f"{POLYMARKET_CLOB_API}/book",
                params={"condition_id": condition_id}
            )
            response.raise_for_status()
            book_data = response.json()
            
            # Extract best bid/ask for yes and no outcomes
            yes_book = book_data.get('yes', {})
            no_book = book_data.get('no', {})
            
            yes_ask = float(yes_book.get('asks', [[0, 0]])[0][0]) if yes_book.get('asks') else 1.0
            no_ask = float(no_book.get('asks', [[0, 0]])[0][0]) if no_book.get('asks') else 1.0
            
            # Calculate arbitrage profit
            total_cost = yes_ask + no_ask
            arb_profit = 1.0 - total_cost
            
            # Check liquidity
            yes_liquidity = sum(float(ask[1]) for ask in yes_book.get('asks', [])[:5])
            no_liquidity = sum(float(ask[1]) for ask in no_book.get('asks', [])[:5])
            total_liquidity = yes_liquidity + no_liquidity
            
            if arb_profit > 0 and total_liquidity >= self.min_liquidity:
                return PolymarketOpportunity(
                    market_id=market.get('id', ''),
                    condition_id=condition_id,
                    question=market.get('question', ''),
                    yes_price=yes_ask,
                    no_price=no_ask,
                    arb_profit=arb_profit,
                    volume_24h=float(market.get('volume_24h', 0)),
                    liquidity=total_liquidity
                )
            
            return None
            
        except Exception as exc:
            logger.warning(f"Failed to check arbitrage for market: {exc}")
            return None
    
    async def _submit_opportunity(self, opportunity: PolymarketOpportunity):
        """Submit arbitrage opportunity to consensus."""
        try:
            energy_payload = (
                f"Polymarket Arbitrage Opportunity\n\n"
                f"Market: {opportunity.question}\n"
                f"Strategy: Buy YES at {opportunity.yes_price:.4f} + NO at {opportunity.no_price:.4f}\n"
                f"Total Cost: {opportunity.yes_price + opportunity.no_price:.4f}\n"
                f"Guaranteed Payout: 1.0000\n"
                f"Risk-Free Profit: {opportunity.arb_profit:.4f} ({opportunity.arb_profit:.2%})\n"
                f"Liquidity: ${opportunity.liquidity:.2f}\n"
                f"24h Volume: ${opportunity.volume_24h:.2f}\n\n"
                f"Execution: Buy both outcomes simultaneously for guaranteed profit."
            )
            
            energy = create_energy("polymarket_arbitrage", energy_payload)
            merid = get_core()
            await merid.run_cycle(energy)
            
        except Exception as exc:
            logger.error(f"Failed to submit opportunity: {exc}")
    
    async def close(self):
        """Clean up resources."""
        await self.client.aclose()


async def run_scanner():
    """Run continuous Polymarket arbitrage scanner."""
    agent = PolymarketAgent()
    
    try:
        while True:
            logger.info("Starting Polymarket scan...")
            opportunities = await agent.scan()
            
            if opportunities:
                logger.info(f"Found {len(opportunities)} arbitrage opportunities")
            else:
                logger.debug("No arbitrage opportunities found")
            
            # Scan every 5 minutes
            await asyncio.sleep(300)
            
    except KeyboardInterrupt:
        logger.info("Scanner stopped by user")
    finally:
        await agent.close()


if __name__ == "__main__":
    asyncio.run(run_scanner())
