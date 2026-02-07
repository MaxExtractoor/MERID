"""MERID Swarm-Integrated Market Maker Agent.

Market making agent that integrates with MERID swarm for risk-managed
liquidity provision across prediction markets and crypto DEXs.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
from enum import Enum
import asyncio
import structlog

logger = structlog.get_logger(__name__)


class MMRiskLevel(str, Enum):
    """Risk levels for market making."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class MMPosition:
    """Market maker position tracking."""
    market_id: str
    market_type: str  # prediction or crypto
    side: str
    size: Decimal
    entry_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    inventory_skew: Decimal
    timestamp: datetime


class SwarmMarketMakerAgent:
    """Swarm agent for market making operations."""
    
    def __init__(
        self,
        kalshi_mm=None,
        polymarket_mm=None,
        uniswap_mm=None,
        cronos_mm=None,
        swarm_orchestrator=None
    ):
        self.kalshi = kalshi_mm
        self.polymarket = polymarket_mm
        self.uniswap = uniswap_mm
        self.cronos = cronos_mm
        self.swarm = swarm_orchestrator
        
        self.logger = logger.bind(agent="SwarmMarketMaker")
        self.positions: List[MMPosition] = []
        self.running = False
        
        # Risk parameters
        self.max_position = Decimal("1000")
        self.max_var = Decimal("500")
        self.target_spread = Decimal("0.02")
        self.inventory_limit = Decimal("5000")
    
    async def evaluate_mm_opportunity(
        self,
        market_id: str,
        market_type: str,
        expected_edge: Decimal,
        liquidity_score: Decimal
    ) -> Dict[str, Any]:
        """Evaluate market making opportunity with swarm."""
        
        # Check current inventory
        current_inventory = self._get_inventory(market_id)
        
        # Calculate risk metrics
        var = expected_edge * current_inventory * Decimal("0.1")
        
        if self.swarm:
            # Get swarm risk assessment
            try:
                risk_check = await self.swarm.run_risk_check({
                    "symbol": market_id,
                    "exposure": current_inventory,
                    "var": var,
                    "strategy": "market_making"
                })
                
                if not risk_check.get("approved"):
                    return {
                        "approved": False,
                        "reason": "swarm_risk_rejection",
                        "risk_level": MMRiskLevel.HIGH
                    }
                
            except Exception as e:
                self.logger.error("swarm_risk_error", error=str(e))
        
        # Calculate opportunity score
        opportunity_score = (
            float(expected_edge) * 
            float(liquidity_score) * 
            (1 - min(float(current_inventory) / float(self.inventory_limit), 1.0))
        )
        
        risk_level = self._calculate_risk_level(var, current_inventory)
        
        return {
            "approved": True,
            "opportunity_score": opportunity_score,
            "risk_level": risk_level,
            "max_position": self.max_position,
            "recommended_spread": self._calculate_spread(risk_level)
        }
    
    def _get_inventory(self, market_id: str) -> Decimal:
        """Get current inventory for market."""
        for pos in self.positions:
            if pos.market_id == market_id:
                return pos.size
        return Decimal("0")
    
    def _calculate_risk_level(
        self,
        var: Decimal,
        inventory: Decimal
    ) -> MMRiskLevel:
        """Calculate risk level for position."""
        if var > self.max_var or inventory > self.inventory_limit:
            return MMRiskLevel.CRITICAL
        elif var > self.max_var * Decimal("0.7"):
            return MMRiskLevel.HIGH
        elif var > self.max_var * Decimal("0.4"):
            return MMRiskLevel.MEDIUM
        else:
            return MMRiskLevel.LOW
    
    def _calculate_spread(self, risk_level: MMRiskLevel) -> Decimal:
        """Calculate spread based on risk level."""
        multipliers = {
            MMRiskLevel.LOW: Decimal("1.0"),
            MMRiskLevel.MEDIUM: Decimal("1.5"),
            MMRiskLevel.HIGH: Decimal("2.0"),
            MMRiskLevel.CRITICAL: Decimal("3.0")
        }
        
        return self.target_spread * multipliers.get(risk_level, Decimal("1.0"))
    
    async def execute_mm_strategy(
        self,
        market_type: str,
        market_id: str,
        strategy: str = "pure_mm"
    ) -> Dict[str, Any]:
        """Execute market making strategy."""
        
        self.logger.info(
            "executing_mm_strategy",
            market_type=market_type,
            market_id=market_id,
            strategy=strategy
        )
        
        if market_type == "kalshi" and self.kalshi:
            return await self._run_kalshi_mm(market_id, strategy)
        elif market_type == "uniswap" and self.uniswap:
            return await self._run_uniswap_mm(market_id, strategy)
        elif market_type == "cronos" and self.cronos:
            return await self._run_cronos_mm(market_id, strategy)
        else:
            return {"status": "error", "reason": "market_type_not_supported"}
    
    async def _run_kalshi_mm(
        self,
        market_id: str,
        strategy: str
    ) -> Dict[str, Any]:
        """Run Kalshi market making."""
        from core.market_maker_prediction import ContractSide
        
        try:
            # Get market
            markets = await self.kalshi.get_markets()
            market = next((m for m in markets if m.id == market_id), None)
            
            if not market:
                return {"status": "error", "reason": "market_not_found"}
            
            # Evaluate opportunity
            evaluation = await self.evaluate_mm_opportunity(
                market_id,
                "kalshi",
                Decimal("0.02"),
                Decimal("0.8")
            )
            
            if not evaluation["approved"]:
                return {"status": "rejected", "reason": evaluation["reason"]}
            
            # Generate quotes
            quotes = self.kalshi.generate_quotes(
                market,
                min_spread=evaluation["recommended_spread"],
                max_position=evaluation["max_position"]
            )
            
            # Place quotes
            placed = []
            for quote in quotes:
                result = await self.kalshi.place_order(
                    market_id,
                    quote.side,
                    quote.size,
                    quote.price
                )
                placed.append(result)
            
            return {
                "status": "success",
                "quotes_placed": len(placed),
                "spread": str(evaluation["recommended_spread"]),
                "risk_level": evaluation["risk_level"]
            }
            
        except Exception as e:
            self.logger.error("kalshi_mm_error", error=str(e))
            return {"status": "error", "message": str(e)}
    
    async def _run_uniswap_mm(
        self,
        pair: str,
        strategy: str
    ) -> Dict[str, Any]:
        """Run Uniswap market making."""
        try:
            # Evaluate LP opportunity
            evaluation = await self.evaluate_mm_opportunity(
                pair,
                "uniswap",
                Decimal("0.25"),  # Expected APR
                Decimal("0.9")    # Liquidity score
            )
            
            if not evaluation["approved"]:
                return {"status": "rejected", "reason": evaluation["reason"]}
            
            # Add liquidity
            result = await self.uniswap.add_liquidity(
                pair=pair,
                token0_amount=Decimal("1000"),
                token1_amount=Decimal("1000")
            )
            
            return {
                "status": result.get("status"),
                "lp_tokens": str(result.get("lp_tokens", 0)),
                "risk_level": evaluation["risk_level"]
            }
            
        except Exception as e:
            self.logger.error("uniswap_mm_error", error=str(e))
            return {"status": "error", "message": str(e)}
    
    async def _run_cronos_mm(
        self,
        pair: str,
        strategy: str
    ) -> Dict[str, Any]:
        """Run Cronos market making."""
        try:
            # Generate Hummingbot config
            from core.market_maker_crypto import HummingbotStrategyAdapter
            adapter = HummingbotStrategyAdapter()
            
            config = adapter.configure_pure_mm(
                pair=pair,
                bid_spread=Decimal("0.005"),
                ask_spread=Decimal("0.005"),
                order_amount=Decimal("1.0")
            )
            
            yml_config = adapter.generate_hummingbot_config_yml(pair)
            
            return {
                "status": "configured",
                "config": config,
                "yml": yml_config
            }
            
        except Exception as e:
            self.logger.error("cronos_mm_error", error=str(e))
            return {"status": "error", "message": str(e)}
    
    async def hedge_inventory(self) -> List[Dict[str, Any]]:
        """Hedge excess inventory across all markets."""
        hedges = []
        
        for pos in self.positions:
            if abs(pos.size) > self.max_position:
                self.logger.info(
                    "hedging_position",
                    market=pos.market_id,
                    size=str(pos.size)
                )
                
                if pos.market_type == "kalshi" and self.kalshi:
                    # Find market and hedge
                    markets = await self.kalshi.get_markets()
                    market = next((m for m in markets if m.id == pos.market_id), None)
                    
                    if market:
                        hedge_result = await self.kalshi.hedge_inventory(market)
                        if hedge_result:
                            hedges.append(hedge_result)
        
        return hedges
    
    async def start_mm_loop(
        self,
        markets: List[Dict[str, str]],
        interval: int = 60
    ):
        """Start continuous market making loop."""
        self.running = True
        self.logger.info("mm_loop_started", markets=len(markets))
        
        while self.running:
            try:
                for market in markets:
                    await self.execute_mm_strategy(
                        market["type"],
                        market["id"],
                        market.get("strategy", "pure_mm")
                    )
                
                # Periodic hedging
                await self.hedge_inventory()
                
                await asyncio.sleep(interval)
                
            except Exception as e:
                self.logger.error("mm_loop_error", error=str(e))
                await asyncio.sleep(interval)
    
    def stop_mm_loop(self):
        """Stop market making loop."""
        self.running = False
        self.logger.info("mm_loop_stopped")
    
    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get market maker portfolio summary."""
        total_exposure = sum(abs(p.size) for p in self.positions)
        total_pnl = sum(p.unrealized_pnl for p in self.positions)
        
        by_type = {}
        for pos in self.positions:
            if pos.market_type not in by_type:
                by_type[pos.market_type] = {"count": 0, "exposure": Decimal("0")}
            by_type[pos.market_type]["count"] += 1
            by_type[pos.market_type]["exposure"] += abs(pos.size)
        
        return {
            "total_positions": len(self.positions),
            "total_exposure": str(total_exposure),
            "total_pnl": str(total_pnl),
            "by_type": by_type,
            "risk_utilization": float(total_exposure / self.inventory_limit)
        }


class MarketMakingOrchestrator:
    """Orchestrate multiple market maker agents."""
    
    def __init__(self):
        self.agents: List[SwarmMarketMakerAgent] = []
        self.logger = logger.bind(component="MMOrchestrator")
    
    def add_agent(self, agent: SwarmMarketMakerAgent):
        """Add market maker agent."""
        self.agents.append(agent)
        self.logger.info("agent_added", total=len(self.agents))
    
    async def start_all(self, markets: List[Dict[str, str]]):
        """Start all market maker agents."""
        tasks = [
            agent.start_mm_loop(markets) 
            for agent in self.agents
        ]
        await asyncio.gather(*tasks)
    
    def stop_all(self):
        """Stop all market maker agents."""
        for agent in self.agents:
            agent.stop_mm_loop()
    
    def get_aggregate_summary(self) -> Dict[str, Any]:
        """Get aggregate summary across all agents."""
        summaries = [agent.get_portfolio_summary() for agent in self.agents]
        
        return {
            "agents": len(self.agents),
            "total_positions": sum(s["total_positions"] for s in summaries),
            "total_exposure": sum(float(s["total_exposure"]) for s in summaries),
            "agent_details": summaries
        }


# Singleton
swarm_mm_agent = SwarmMarketMakerAgent()
mm_orchestrator = MarketMakingOrchestrator()
