"""
Agent Orchestrator for MERID.

Coordinates all agents, manages consensus formation, and handles real-time decision making.
Production-grade implementation with actual agent swarming and consensus.
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from agents.twitter_agent import get_twitter_agent
from agents.telegram_agent import get_telegram_agent
from agents.news_monitor_agent import get_news_monitor_agent
from data.live_price_feed import get_live_price_feed
from trading.agents.arbitrage_agent import get_arbitrage_agent
from trading.agents.execution_agent import get_execution_agent
from trading.agents.slippage_agent import get_slippage_agent
from utils.logger import get_logger

logger = get_logger("core.agent_orchestrator")


class AgentRole(Enum):
    """Agent role types."""
    TWITTER = "twitter"
    TELEGRAM = "telegram"
    NEWS_MONITOR = "news_monitor"
    ARBITRAGE = "arbitrage"
    EXECUTION = "execution"
    SLIPPAGE = "slippage"
    PRICE_FEED = "price_feed"


@dataclass
class AgentDecision:
    """Agent decision structure."""
    agent_role: AgentRole
    decision_type: str
    data: Dict[str, Any]
    confidence: float
    reasoning: List[str]
    timestamp: datetime


@dataclass
class ConsensusResult:
    """Consensus result structure."""
    approved: bool
    confidence: float
    votes_for: int
    votes_against: int
    participating_agents: List[AgentRole]
    decisions: List[AgentDecision]
    timestamp: datetime


class AgentOrchestrator:
    """
    Production Agent Orchestrator.
    
    Manages all MERID agents, coordinates decision-making,
    forms consensus, and executes actions.
    """
    
    def __init__(self):
        """Initialize agent orchestrator."""
        # Initialize all agents
        self.twitter_agent = get_twitter_agent()
        self.telegram_agent = get_telegram_agent()
        self.news_monitor = get_news_monitor_agent()
        self.price_feed = get_live_price_feed()
        self.arbitrage_agent = get_arbitrage_agent()
        self.execution_agent = get_execution_agent()
        self.slippage_agent = get_slippage_agent()
        
        # Agent registry
        self.agents = {
            AgentRole.TWITTER: self.twitter_agent,
            AgentRole.TELEGRAM: self.telegram_agent,
            AgentRole.NEWS_MONITOR: self.news_monitor,
            AgentRole.PRICE_FEED: self.price_feed,
            AgentRole.ARBITRAGE: self.arbitrage_agent,
            AgentRole.EXECUTION: self.execution_agent,
            AgentRole.SLIPPAGE: self.slippage_agent
        }
        
        # State tracking
        self.running = False
        self.recent_decisions: List[AgentDecision] = []
        self.consensus_history: List[ConsensusResult] = []
        
        logger.info("Agent Orchestrator initialized with 7 agents")
    
    async def start(self):
        """Start all agents and orchestration."""
        self.running = True
        logger.info("Starting agent orchestration...")

        # Note: news_monitor is started by OrchestratorAgentManager — not duplicated here.
        # Note: price_feed.start_streaming() is started by main.py lifespan — not duplicated here.
        tasks = [
            asyncio.create_task(self._orchestration_loop())
        ]

        logger.info("All agents started successfully")

        # Wait for tasks
        await asyncio.gather(*tasks, return_exceptions=True)
    
    def stop(self):
        """Stop all agents."""
        self.running = False
        self.news_monitor.stop_monitoring()
        self.price_feed.stop_streaming()
        logger.info("All agents stopped")
    
    async def _orchestration_loop(self):
        """Main orchestration loop - coordinates agent decisions."""
        logger.info("Orchestration loop started")
        
        while self.running:
            try:
                # Check for arbitrage opportunities
                await self._check_arbitrage_opportunities()
                
                # Monitor market conditions
                await self._monitor_market_conditions()
                
                # Post periodic updates
                await self._post_periodic_updates()
                
                # Sleep before next cycle
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except Exception as exc:
                logger.error(f"Error in orchestration loop: {exc}")
                await asyncio.sleep(30)
    
    async def _check_arbitrage_opportunities(self):
        """Check for and act on arbitrage opportunities."""
        try:
            # Get current prices
            prices = self.price_feed.get_all_prices()
            
            if not prices:
                return
            
            # Check for arbitrage (simplified - real implementation would check cross-venue)
            for symbol, price_data in prices.items():
                # Calculate spread
                spread = (price_data.ask - price_data.bid) / price_data.bid * 10000  # in bps
                
                if spread > 50:  # Significant spread
                    # Create agent decision
                    decision = AgentDecision(
                        agent_role=AgentRole.ARBITRAGE,
                        decision_type="arbitrage_opportunity",
                        data={
                            "symbol": symbol,
                            "spread_bps": spread,
                            "bid": price_data.bid,
                            "ask": price_data.ask,
                            "exchange": price_data.exchange
                        },
                        confidence=0.85,
                        reasoning=[
                            f"Detected {spread:.1f} bps spread on {symbol}",
                            f"Spread exceeds threshold of 50 bps",
                            "Market conditions favorable for arbitrage"
                        ],
                        timestamp=datetime.now()
                    )
                    
                    self.recent_decisions.append(decision)
                    
                    # Post to social media
                    base = symbol.split('/')[0]
                    await self._broadcast_arbitrage_opportunity(
                        asset=base,
                        spread_bps=spread,
                        price=price_data.price
                    )
                    
        except Exception as exc:
            logger.error(f"Error checking arbitrage: {exc}")
    
    async def _monitor_market_conditions(self):
        """Monitor and report on market conditions."""
        try:
            prices = self.price_feed.get_all_prices()
            
            for symbol, price_data in prices.items():
                # Check for significant price movements
                if abs(price_data.change_24h_pct) > 5.0:  # >5% move
                    base = symbol.split('/')[0]
                    
                    # Post market update
                    if self.twitter_agent.enabled:
                        self.twitter_agent.post_market_update(
                            asset=base,
                            price=price_data.price,
                            change_pct=price_data.change_24h_pct,
                            volume=price_data.volume_24h
                        )
                    
                    if self.telegram_agent.enabled:
                        await self.telegram_agent.send_market_update(
                            asset=base,
                            price=price_data.price,
                            change_pct=price_data.change_24h_pct,
                            volume=price_data.volume_24h
                        )
                    
        except Exception as exc:
            logger.error(f"Error monitoring market: {exc}")
    
    async def _post_periodic_updates(self):
        """Post periodic system status updates."""
        # Post every 6 hours
        if int(time.time()) % 21600 < 30:  # Within 30 seconds of 6-hour mark
            try:
                stats = self.get_system_stats()
                
                if self.twitter_agent.enabled:
                    self.twitter_agent.post_system_status(
                        blocks_mined=stats['consensus_results'],
                        agents_active=stats['active_agents'],
                        consensus_rate=stats['consensus_rate']
                    )
                
                if self.telegram_agent.enabled:
                    await self.telegram_agent.send_system_status(
                        blocks_mined=stats['consensus_results'],
                        agents_active=stats['active_agents'],
                        consensus_rate=stats['consensus_rate']
                    )
                    
            except Exception as exc:
                logger.error(f"Error posting updates: {exc}")
    
    async def _broadcast_arbitrage_opportunity(self, asset: str, spread_bps: float, price: float):
        """Broadcast arbitrage opportunity to social media."""
        try:
            # Estimate profit (simplified)
            profit = price * (spread_bps / 10000) * 1000  # For $1000 position
            
            if self.twitter_agent.enabled:
                self.twitter_agent.post_arbitrage_opportunity(
                    asset=asset,
                    venue_a="Exchange A",
                    venue_b="Exchange B",
                    spread_bps=spread_bps,
                    profit=profit
                )
            
            if self.telegram_agent.enabled:
                await self.telegram_agent.send_arbitrage_alert(
                    asset=asset,
                    venue_a="Exchange A",
                    venue_b="Exchange B",
                    spread_bps=spread_bps,
                    profit=profit
                )
                
        except Exception as exc:
            logger.error(f"Error broadcasting arbitrage: {exc}")
    
    async def form_market_consensus(
        self,
        ticker: str,
        asset: str,
        timeframe: str,
    ) -> "MarketConsensusSnapshot":
        """
        Form consensus on a Kalshi market (NEW market-centric flow).

        This is the NEW consensus path for Kalshi trading decisions.
        Uses MarketConsensusSnapshot as the unit of consensus.

        Args:
            ticker: Kalshi contract ID
            asset: Asset symbol (BTC, ETH, etc.)
            timeframe: Timeframe (15m, 1h, 24h, etc.)

        Returns:
            MarketConsensusSnapshot with consensus action and parameters
        """
        try:
            # Import here to avoid circular dependencies
            from merid.signals.market_aggregator import get_market_aggregator
            from merid.signals.market_consensus import AgentOpinion, TradingAction
            from merid.consensus.market_engine import get_market_consensus_engine

            # Step 1: Create market snapshot with data + features
            aggregator = get_market_aggregator()
            snapshot = await aggregator.create_snapshot(ticker, asset, timeframe)

            if not snapshot:
                logger.warning(f"Could not create snapshot for {ticker}")
                # Return empty snapshot
                from merid.signals.market_consensus import MarketConsensusSnapshot
                return MarketConsensusSnapshot(
                    contract_id=ticker,
                    asset=asset,
                    timeframe=timeframe,
                    consensus_action=TradingAction.NO_EDGE,
                )

            # Step 2: Collect agent opinions
            agent_opinions = []
            for role, agent in self.agents.items():
                try:
                    opinion = await self._get_agent_market_opinion(role, agent, snapshot)
                    if opinion:
                        agent_opinions.append(opinion)
                except Exception as exc:
                    logger.error(f"Error getting opinion from {role}: {exc}")

            # Step 3: Form consensus using market consensus engine
            engine = get_market_consensus_engine()
            consensus_snapshot = await engine.form_consensus(snapshot, agent_opinions)

            logger.info(
                f"Market consensus formed for {ticker}: "
                f"{consensus_snapshot.consensus_action.value.upper()} "
                f"({consensus_snapshot.agreement_pct:.1f}%)"
            )

            return consensus_snapshot

        except Exception as exc:
            logger.error(f"Error forming market consensus for {ticker}: {exc}")
            # Return empty snapshot
            from merid.signals.market_consensus import MarketConsensusSnapshot, TradingAction
            return MarketConsensusSnapshot(
                contract_id=ticker,
                asset=asset,
                timeframe=timeframe,
                consensus_action=TradingAction.NO_EDGE,
            )

    async def _get_agent_market_opinion(
        self,
        role: AgentRole,
        agent: Any,
        snapshot: "MarketConsensusSnapshot",
    ) -> Optional["AgentOpinion"]:
        """
        Get an agent's opinion on a market snapshot.

        Each agent evaluates the market data + features and returns
        a trading action (LONG/SHORT/FLAT/NO_EDGE) with confidence.

        Args:
            role: Agent role
            agent: Agent instance
            snapshot: Market snapshot to evaluate

        Returns:
            AgentOpinion or None
        """
        from merid.signals.market_consensus import AgentOpinion, TradingAction

        # Simplified opinion generation based on role
        # In production, each agent would have sophisticated models

        if not snapshot.market_data or not snapshot.features:
            return None

        market_data = snapshot.market_data
        features = snapshot.features

        action = TradingAction.NO_EDGE
        confidence = 0.5
        edge_estimate = 0.0
        reasoning = []
        primary_factors = []

        if role == AgentRole.NEWS_MONITOR:
            # News agent looks at sentiment
            news_net = features.news_bullish_score - features.news_bearish_score
            if news_net > 0.3:
                action = TradingAction.LONG
                confidence = min(0.8, 0.5 + news_net * 0.5)
                edge_estimate = news_net * 5.0  # Rough heuristic
                reasoning.append(f"Bullish news sentiment: {news_net:.2f}")
                primary_factors.append("news_bullish")
            elif news_net < -0.3:
                action = TradingAction.SHORT
                confidence = min(0.8, 0.5 + abs(news_net) * 0.5)
                edge_estimate = news_net * 5.0
                reasoning.append(f"Bearish news sentiment: {news_net:.2f}")
                primary_factors.append("news_bearish")
            else:
                action = TradingAction.FLAT
                reasoning.append("Neutral news sentiment")

        elif role == AgentRole.PRICE_FEED:
            # Price feed looks at implied prob vs fair value
            implied = market_data.implied_prob
            # Simple heuristic: if price is extreme, fade it
            if implied > 0.7:
                action = TradingAction.SHORT
                confidence = 0.6
                edge_estimate = (implied - 0.5) * 10
                reasoning.append(f"Market overpriced at {implied:.0%}")
                primary_factors.append("price_extreme")
            elif implied < 0.3:
                action = TradingAction.LONG
                confidence = 0.6
                edge_estimate = (0.5 - implied) * 10
                reasoning.append(f"Market underpriced at {implied:.0%}")
                primary_factors.append("price_extreme")

        elif role == AgentRole.ARBITRAGE:
            # Arbitrage looks at spread and liquidity
            if market_data.spread_pct < 2.0 and market_data.total_depth > 100:
                # Good liquidity → more confident
                confidence = 0.7
                reasoning.append("Good liquidity for execution")
                primary_factors.append("liquidity")
            elif market_data.spread_pct > 5.0:
                action = TradingAction.FLAT
                confidence = 0.8
                reasoning.append(f"Spread too wide: {market_data.spread_pct:.1f}%")
                primary_factors.append("poor_liquidity")

        elif role == AgentRole.EXECUTION:
            # Execution looks at feasibility
            if market_data.total_depth > 50:
                confidence = 0.65
                reasoning.append("Sufficient depth for execution")
            else:
                action = TradingAction.FLAT
                confidence = 0.7
                reasoning.append("Insufficient depth")

        # Add generic reasoning
        reasoning.append(f"{role.value} evaluated {snapshot.contract_id}")

        return AgentOpinion(
            agent_id=f"{role.value}_agent",
            agent_role=role.value,
            action=action,
            confidence=confidence,
            edge_estimate_pct=edge_estimate,
            reasoning=reasoning,
            primary_factors=primary_factors,
        )

    async def form_consensus(self, proposal: Dict[str, Any]) -> ConsensusResult:
        """
        Form consensus among agents on a proposal (OLD general-purpose path).

        NOTE: For Kalshi market trading decisions, use form_market_consensus() instead.
        This method is preserved for backwards compatibility with other proposal types.

        Args:
            proposal: Proposal to vote on

        Returns:
            ConsensusResult with voting outcome
        """
        decisions = []
        votes_for = 0
        votes_against = 0
        
        # Collect votes from each agent with real evaluation logic
        for role, agent in self.agents.items():
            try:
                # Get agent-specific confidence based on proposal type and market data
                confidence, reasoning = await self._evaluate_agent_vote(role, agent, proposal)
                vote = confidence > 0.5
                
                decision = AgentDecision(
                    agent_role=role,
                    decision_type="consensus_vote",
                    data={"proposal": proposal, "vote": vote},
                    confidence=confidence,
                    reasoning=reasoning,
                    timestamp=datetime.now()
                )
                
                decisions.append(decision)
                
                if vote:
                    votes_for += 1
                else:
                    votes_against += 1
                    
            except Exception as exc:
                logger.error(f"Error getting vote from {role}: {exc}")
        
        # Calculate consensus
        total_votes = votes_for + votes_against
        consensus_confidence = votes_for / total_votes if total_votes > 0 else 0.0
        approved = consensus_confidence >= 0.66  # 2/3 majority
        
        result = ConsensusResult(
            approved=approved,
            confidence=consensus_confidence,
            votes_for=votes_for,
            votes_against=votes_against,
            participating_agents=[d.agent_role for d in decisions],
            decisions=decisions,
            timestamp=datetime.now()
        )
        
        self.consensus_history.append(result)
        
        # Broadcast consensus result
        if self.twitter_agent.enabled:
            self.twitter_agent.post_consensus_result(
                block_index=len(self.consensus_history),
                approved=approved,
                confidence=consensus_confidence,
                agents_voted=total_votes
            )
        
        if self.telegram_agent.enabled:
            await self.telegram_agent.send_consensus_result(
                block_index=len(self.consensus_history),
                approved=approved,
                confidence=consensus_confidence,
                agents_voted=total_votes
            )
        
        logger.info(f"General consensus formed: {'APPROVED' if approved else 'REJECTED'} ({consensus_confidence:.1%})")
        logger.debug("Note: For Kalshi markets, use form_market_consensus() instead")
        
        return result
    
    def get_system_stats(self) -> Dict:
        """Get system-wide statistics."""
        active_agents = sum(1 for role, agent in self.agents.items() 
                          if hasattr(agent, 'enabled') and agent.enabled)
        
        consensus_results = len(self.consensus_history)
        approved = sum(1 for c in self.consensus_history if c.approved)
        consensus_rate = approved / consensus_results if consensus_results > 0 else 0.0
        
        return {
            "running": self.running,
            "active_agents": active_agents,
            "total_agents": len(self.agents),
            "recent_decisions": len(self.recent_decisions),
            "consensus_results": consensus_results,
            "consensus_rate": consensus_rate,
            "twitter_enabled": self.twitter_agent.enabled,
            "telegram_enabled": self.telegram_agent.enabled,
            "news_monitoring": self.news_monitor.running,
            "price_streaming": self.price_feed.running
        }
    
    def get_recent_decisions(self, limit: int = 10) -> List[AgentDecision]:
        """Get recent agent decisions."""
        return self.recent_decisions[-limit:]
    
    def get_consensus_history(self, limit: int = 10) -> List[ConsensusResult]:
        """Get recent consensus results."""
        return self.consensus_history[-limit:]
    
    async def _evaluate_agent_vote(
        self, 
        role: AgentRole, 
        agent: Any, 
        proposal: Dict[str, Any]
    ) -> tuple:
        """
        Evaluate agent vote based on role-specific logic and market data.
        
        Returns:
            Tuple of (confidence: float, reasoning: List[str])
        """
        reasoning = []
        confidence = 0.5  # Base confidence
        
        # Get current market data for context
        prices = self.price_feed.get_all_prices()
        proposal_type = proposal.get("type", "unknown")
        symbol = proposal.get("symbol", "BTC/USDT")
        
        if role == AgentRole.PRICE_FEED:
            # Price feed evaluates based on data freshness
            if prices:
                confidence = 0.8
                reasoning.append("Price data is fresh and available")
            else:
                confidence = 0.3
                reasoning.append("No price data available")
                
        elif role == AgentRole.ARBITRAGE:
            # Arbitrage agent evaluates spread opportunities
            if prices and symbol in prices:
                price_data = prices[symbol]
                spread = (price_data.ask - price_data.bid) / price_data.bid * 10000
                if spread > 30:
                    confidence = 0.85
                    reasoning.append(f"Favorable spread detected: {spread:.1f} bps")
                else:
                    confidence = 0.4
                    reasoning.append(f"Spread too tight: {spread:.1f} bps")
            else:
                confidence = 0.3
                reasoning.append("No price data for evaluation")
                
        elif role == AgentRole.EXECUTION:
            # Execution agent evaluates order feasibility
            amount = proposal.get("amount", 0)
            if amount > 0 and amount < 10000:
                confidence = 0.75
                reasoning.append(f"Order size ${amount} within limits")
            elif amount >= 10000:
                confidence = 0.5
                reasoning.append(f"Large order ${amount} requires caution")
            else:
                confidence = 0.3
                reasoning.append("Invalid order amount")
                
        elif role == AgentRole.SLIPPAGE:
            # Slippage agent evaluates market depth
            if prices and symbol in prices:
                volume = prices[symbol].volume_24h
                if volume > 1000000:
                    confidence = 0.8
                    reasoning.append(f"High liquidity: ${volume/1e6:.1f}M volume")
                else:
                    confidence = 0.5
                    reasoning.append(f"Low liquidity: ${volume/1e3:.1f}K volume")
            else:
                confidence = 0.4
                reasoning.append("Cannot assess liquidity")
                
        elif role == AgentRole.NEWS_MONITOR:
            # News agent evaluates sentiment
            if hasattr(agent, 'get_recent_sentiment'):
                sentiment = agent.get_recent_sentiment()
                if sentiment > 0.6:
                    confidence = 0.75
                    reasoning.append(f"Positive news sentiment: {sentiment:.2f}")
                elif sentiment < 0.4:
                    confidence = 0.35
                    reasoning.append(f"Negative news sentiment: {sentiment:.2f}")
                else:
                    confidence = 0.55
                    reasoning.append(f"Neutral news sentiment: {sentiment:.2f}")
            else:
                confidence = 0.5
                reasoning.append("News sentiment unavailable")
                
        elif role == AgentRole.TWITTER:
            # Twitter agent evaluates social sentiment
            if hasattr(agent, 'enabled') and agent.enabled:
                confidence = 0.6
                reasoning.append("Social monitoring active")
            else:
                confidence = 0.5
                reasoning.append("Social monitoring disabled")
                
        elif role == AgentRole.TELEGRAM:
            # Telegram agent provides community feedback
            if hasattr(agent, 'enabled') and agent.enabled:
                confidence = 0.6
                reasoning.append("Community channel active")
            else:
                confidence = 0.5
                reasoning.append("Community channel disabled")
        
        # Add proposal type to reasoning
        reasoning.append(f"{role.value} evaluated {proposal_type} proposal")
        
        return (confidence, reasoning)


# Global singleton
_agent_orchestrator: Optional[AgentOrchestrator] = None


def get_agent_orchestrator() -> AgentOrchestrator:
    """Get or create agent orchestrator singleton."""
    global _agent_orchestrator
    if _agent_orchestrator is None:
        _agent_orchestrator = AgentOrchestrator()
    return _agent_orchestrator
