"""
MERID Treasury Yield Strategy Engine - Phase 22

Yield strategy agent competition with multiple vault candidates.
This is where long-term compounding lives.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from utils.logger import get_logger

logger = get_logger("treasury.yield_strategies")


class YieldProtocol(Enum):
    """Supported yield protocols."""
    AAVE_V3 = "aave_v3"
    COMPOUND_V3 = "compound_v3"
    LIDO = "lido"
    ROCKET_POOL = "rocket_pool"
    EIGENLAYER = "eigenlayer"
    PENDLE = "pendle"
    CONVEX = "convex"
    YEARN_V3 = "yearn_v3"
    MORPHO = "morpho"
    SPARK = "spark"
    MAKER_DSR = "maker_dsr"
    ETHENA = "ethena"
    FRAX = "frax"
    TREASURY_BONDS = "treasury_bonds"  # TradFi
    MONEY_MARKET = "money_market"  # TradFi


class RiskTier(Enum):
    """Risk tier classification."""
    TIER_1_SAFE = "tier_1_safe"  # Stablecoins, T-bills
    TIER_2_LOW = "tier_2_low"  # Blue-chip staking
    TIER_3_MEDIUM = "tier_3_medium"  # LP positions
    TIER_4_HIGH = "tier_4_high"  # Leveraged strategies
    TIER_5_DEGEN = "tier_5_degen"  # High-risk DeFi


class StrategyStatus(Enum):
    """Strategy execution status."""
    PROPOSED = "proposed"
    SIMULATING = "simulating"
    APPROVED = "approved"
    ACTIVE = "active"
    PAUSED = "paused"
    UNWINDING = "unwinding"
    COMPLETED = "completed"
    REJECTED = "rejected"
    EMERGENCY_EXIT = "emergency_exit"


@dataclass
class YieldSource:
    """Individual yield source configuration."""
    source_id: str
    protocol: YieldProtocol
    chain: str
    asset: str
    current_apy: float
    historical_apy_7d: float
    historical_apy_30d: float
    tvl_usd: float
    risk_tier: RiskTier
    smart_contract_risk: float  # 0-1
    liquidity_risk: float  # 0-1
    protocol_risk: float  # 0-1
    min_deposit_usd: float = 0.0
    max_deposit_usd: float = float('inf')
    lock_period_days: float = 0.0
    withdrawal_delay_hours: float = 0.0
    last_updated: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "protocol": self.protocol.value,
            "chain": self.chain,
            "asset": self.asset,
            "current_apy": self.current_apy,
            "historical_apy_7d": self.historical_apy_7d,
            "historical_apy_30d": self.historical_apy_30d,
            "tvl_usd": self.tvl_usd,
            "risk_tier": self.risk_tier.value,
            "smart_contract_risk": self.smart_contract_risk,
            "liquidity_risk": self.liquidity_risk,
            "protocol_risk": self.protocol_risk,
            "min_deposit_usd": self.min_deposit_usd,
            "max_deposit_usd": self.max_deposit_usd,
            "lock_period_days": self.lock_period_days,
            "withdrawal_delay_hours": self.withdrawal_delay_hours,
            "last_updated": self.last_updated,
        }
    
    def risk_adjusted_apy(self) -> float:
        """Calculate risk-adjusted APY."""
        total_risk = (self.smart_contract_risk + self.liquidity_risk + self.protocol_risk) / 3
        return self.current_apy * (1 - total_risk)


@dataclass
class YieldStrategy:
    """Complete yield strategy with allocations."""
    strategy_id: str
    name: str
    description: str
    status: StrategyStatus
    risk_tier: RiskTier
    target_apy: float
    allocations: List[Dict[str, Any]]  # source_id -> allocation_pct
    total_allocated_usd: float = 0.0
    current_value_usd: float = 0.0
    realized_yield_usd: float = 0.0
    unrealized_yield_usd: float = 0.0
    created_at: float = field(default_factory=time.time)
    last_rebalance: Optional[float] = None
    next_rebalance: Optional[float] = None
    simulation_results: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "risk_tier": self.risk_tier.value,
            "target_apy": self.target_apy,
            "allocations": self.allocations,
            "total_allocated_usd": self.total_allocated_usd,
            "current_value_usd": self.current_value_usd,
            "realized_yield_usd": self.realized_yield_usd,
            "unrealized_yield_usd": self.unrealized_yield_usd,
            "created_at": self.created_at,
            "last_rebalance": self.last_rebalance,
            "next_rebalance": self.next_rebalance,
            "simulation_results": self.simulation_results,
        }


@dataclass
class StrategyProposal:
    """Strategy proposal from a yield agent."""
    proposal_id: str
    agent_id: str
    strategy: YieldStrategy
    rationale: str
    confidence: float
    expected_sharpe: float
    max_drawdown_pct: float
    simulation_score: float = 0.0
    votes: Dict[str, float] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "agent_id": self.agent_id,
            "strategy": self.strategy.to_dict(),
            "rationale": self.rationale,
            "confidence": self.confidence,
            "expected_sharpe": self.expected_sharpe,
            "max_drawdown_pct": self.max_drawdown_pct,
            "simulation_score": self.simulation_score,
            "votes": self.votes,
            "created_at": self.created_at,
        }


class YieldSourceRegistry:
    """
    Registry of all available yield sources.
    
    Tracks APYs, risks, and liquidity across protocols.
    """
    
    def __init__(self):
        self._sources: Dict[str, YieldSource] = {}
        self._apy_history: Dict[str, List[Tuple[float, float]]] = {}
        self._init_default_sources()
    
    def _init_default_sources(self) -> None:
        """Initialize default yield sources."""
        defaults = [
            YieldSource(
                source_id="aave_v3_eth_usdc",
                protocol=YieldProtocol.AAVE_V3,
                chain="ethereum",
                asset="USDC",
                current_apy=4.5,
                historical_apy_7d=4.3,
                historical_apy_30d=4.1,
                tvl_usd=2_000_000_000,
                risk_tier=RiskTier.TIER_1_SAFE,
                smart_contract_risk=0.05,
                liquidity_risk=0.02,
                protocol_risk=0.03,
            ),
            YieldSource(
                source_id="lido_eth",
                protocol=YieldProtocol.LIDO,
                chain="ethereum",
                asset="ETH",
                current_apy=3.8,
                historical_apy_7d=3.7,
                historical_apy_30d=3.9,
                tvl_usd=30_000_000_000,
                risk_tier=RiskTier.TIER_2_LOW,
                smart_contract_risk=0.08,
                liquidity_risk=0.05,
                protocol_risk=0.06,
                withdrawal_delay_hours=24,
            ),
            YieldSource(
                source_id="maker_dsr",
                protocol=YieldProtocol.MAKER_DSR,
                chain="ethereum",
                asset="DAI",
                current_apy=5.0,
                historical_apy_7d=5.0,
                historical_apy_30d=5.0,
                tvl_usd=1_500_000_000,
                risk_tier=RiskTier.TIER_1_SAFE,
                smart_contract_risk=0.04,
                liquidity_risk=0.01,
                protocol_risk=0.03,
            ),
            YieldSource(
                source_id="eigenlayer_restaking",
                protocol=YieldProtocol.EIGENLAYER,
                chain="ethereum",
                asset="stETH",
                current_apy=6.5,
                historical_apy_7d=6.2,
                historical_apy_30d=5.8,
                tvl_usd=15_000_000_000,
                risk_tier=RiskTier.TIER_3_MEDIUM,
                smart_contract_risk=0.15,
                liquidity_risk=0.12,
                protocol_risk=0.10,
                withdrawal_delay_hours=168,  # 7 days
            ),
            YieldSource(
                source_id="pendle_pt_usde",
                protocol=YieldProtocol.PENDLE,
                chain="ethereum",
                asset="USDe",
                current_apy=15.0,
                historical_apy_7d=14.5,
                historical_apy_30d=12.0,
                tvl_usd=500_000_000,
                risk_tier=RiskTier.TIER_4_HIGH,
                smart_contract_risk=0.20,
                liquidity_risk=0.18,
                protocol_risk=0.15,
                lock_period_days=90,
            ),
            YieldSource(
                source_id="ethena_susde",
                protocol=YieldProtocol.ETHENA,
                chain="ethereum",
                asset="sUSDe",
                current_apy=25.0,
                historical_apy_7d=22.0,
                historical_apy_30d=18.0,
                tvl_usd=3_000_000_000,
                risk_tier=RiskTier.TIER_4_HIGH,
                smart_contract_risk=0.25,
                liquidity_risk=0.15,
                protocol_risk=0.20,
                withdrawal_delay_hours=168,
            ),
        ]
        
        for source in defaults:
            self._sources[source.source_id] = source
    
    def register_source(self, source: YieldSource) -> None:
        """Register a yield source."""
        self._sources[source.source_id] = source
        logger.info("Registered yield source: %s", source.source_id)
    
    def update_apy(self, source_id: str, new_apy: float) -> None:
        """Update APY for a source."""
        if source_id in self._sources:
            old_apy = self._sources[source_id].current_apy
            self._sources[source_id].current_apy = new_apy
            self._sources[source_id].last_updated = time.time()
            
            # Track history
            if source_id not in self._apy_history:
                self._apy_history[source_id] = []
            self._apy_history[source_id].append((time.time(), new_apy))
            
            # Keep last 1000 data points
            if len(self._apy_history[source_id]) > 1000:
                self._apy_history[source_id] = self._apy_history[source_id][-1000:]
    
    def get_source(self, source_id: str) -> Optional[YieldSource]:
        """Get a yield source by ID."""
        return self._sources.get(source_id)
    
    def get_sources_by_risk(self, risk_tier: RiskTier) -> List[YieldSource]:
        """Get sources by risk tier."""
        return [s for s in self._sources.values() if s.risk_tier == risk_tier]
    
    def get_sources_by_asset(self, asset: str) -> List[YieldSource]:
        """Get sources by asset."""
        return [s for s in self._sources.values() if s.asset.upper() == asset.upper()]
    
    def get_top_sources(self, limit: int = 10, risk_adjusted: bool = True) -> List[YieldSource]:
        """Get top yield sources."""
        sources = list(self._sources.values())
        if risk_adjusted:
            sources.sort(key=lambda s: s.risk_adjusted_apy(), reverse=True)
        else:
            sources.sort(key=lambda s: s.current_apy, reverse=True)
        return sources[:limit]
    
    def get_all_sources(self) -> List[YieldSource]:
        """Get all yield sources."""
        return list(self._sources.values())


class YieldStrategyAgent:
    """
    Individual yield strategy agent.
    
    Competes with other agents to propose optimal strategies.
    """
    
    def __init__(
        self,
        agent_id: str,
        name: str,
        risk_preference: RiskTier,
        specialization: Optional[YieldProtocol] = None,
    ):
        self.agent_id = agent_id
        self.name = name
        self.risk_preference = risk_preference
        self.specialization = specialization
        self.trust_score = 0.5
        self.proposals_submitted = 0
        self.proposals_accepted = 0
        self.total_yield_generated = 0.0
    
    def propose_strategy(
        self,
        registry: YieldSourceRegistry,
        target_allocation_usd: float,
        max_risk_tier: RiskTier = RiskTier.TIER_3_MEDIUM,
    ) -> StrategyProposal:
        """Propose a yield strategy."""
        # Get eligible sources
        eligible_sources = [
            s for s in registry.get_all_sources()
            if s.risk_tier.value <= max_risk_tier.value
        ]
        
        if self.specialization:
            # Prefer specialized protocol
            specialized = [s for s in eligible_sources if s.protocol == self.specialization]
            if specialized:
                eligible_sources = specialized + [s for s in eligible_sources if s not in specialized]
        
        # Build allocation based on risk-adjusted APY
        allocations = []
        remaining_pct = 100.0
        
        sorted_sources = sorted(eligible_sources, key=lambda s: s.risk_adjusted_apy(), reverse=True)
        
        for source in sorted_sources[:5]:  # Max 5 sources
            if remaining_pct <= 0:
                break
            
            # Allocation based on risk tier
            if source.risk_tier == RiskTier.TIER_1_SAFE:
                alloc_pct = min(40.0, remaining_pct)
            elif source.risk_tier == RiskTier.TIER_2_LOW:
                alloc_pct = min(30.0, remaining_pct)
            elif source.risk_tier == RiskTier.TIER_3_MEDIUM:
                alloc_pct = min(20.0, remaining_pct)
            else:
                alloc_pct = min(10.0, remaining_pct)
            
            allocations.append({
                "source_id": source.source_id,
                "allocation_pct": alloc_pct,
                "expected_apy": source.current_apy,
                "risk_adjusted_apy": source.risk_adjusted_apy(),
            })
            remaining_pct -= alloc_pct
        
        # Calculate weighted APY
        weighted_apy = sum(
            a["allocation_pct"] / 100 * a["expected_apy"]
            for a in allocations
        )
        
        strategy = YieldStrategy(
            strategy_id=f"strat_{uuid.uuid4().hex[:12]}",
            name=f"{self.name} Strategy",
            description=f"Yield strategy proposed by {self.name}",
            status=StrategyStatus.PROPOSED,
            risk_tier=max_risk_tier,
            target_apy=weighted_apy,
            allocations=allocations,
            total_allocated_usd=target_allocation_usd,
        )
        
        proposal = StrategyProposal(
            proposal_id=f"prop_{uuid.uuid4().hex[:12]}",
            agent_id=self.agent_id,
            strategy=strategy,
            rationale=f"Diversified allocation across {len(allocations)} sources with {weighted_apy:.2f}% target APY",
            confidence=0.7 + (self.trust_score * 0.2),
            expected_sharpe=weighted_apy / 10,  # Simplified
            max_drawdown_pct=5.0 + (max_risk_tier.value.count("_") * 2),
        )
        
        self.proposals_submitted += 1
        return proposal
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "risk_preference": self.risk_preference.value,
            "specialization": self.specialization.value if self.specialization else None,
            "trust_score": self.trust_score,
            "proposals_submitted": self.proposals_submitted,
            "proposals_accepted": self.proposals_accepted,
            "total_yield_generated": self.total_yield_generated,
            "acceptance_rate": self.proposals_accepted / max(1, self.proposals_submitted),
        }


class StrategyCompetition:
    """
    Manages competition between yield strategy agents.
    
    Agents compete to propose the best strategies.
    """
    
    def __init__(self):
        self._agents: Dict[str, YieldStrategyAgent] = {}
        self._active_proposals: Dict[str, StrategyProposal] = {}
        self._competition_history: List[Dict[str, Any]] = []
        self._init_default_agents()
    
    def _init_default_agents(self) -> None:
        """Initialize default yield agents."""
        agents = [
            YieldStrategyAgent(
                agent_id="yield_conservative",
                name="Conservative Yield",
                risk_preference=RiskTier.TIER_1_SAFE,
            ),
            YieldStrategyAgent(
                agent_id="yield_balanced",
                name="Balanced Yield",
                risk_preference=RiskTier.TIER_2_LOW,
            ),
            YieldStrategyAgent(
                agent_id="yield_growth",
                name="Growth Yield",
                risk_preference=RiskTier.TIER_3_MEDIUM,
            ),
            YieldStrategyAgent(
                agent_id="yield_aave_specialist",
                name="Aave Specialist",
                risk_preference=RiskTier.TIER_2_LOW,
                specialization=YieldProtocol.AAVE_V3,
            ),
            YieldStrategyAgent(
                agent_id="yield_staking_specialist",
                name="Staking Specialist",
                risk_preference=RiskTier.TIER_2_LOW,
                specialization=YieldProtocol.LIDO,
            ),
        ]
        
        for agent in agents:
            self._agents[agent.agent_id] = agent
    
    def run_competition(
        self,
        registry: YieldSourceRegistry,
        target_allocation_usd: float,
        max_risk_tier: RiskTier = RiskTier.TIER_3_MEDIUM,
    ) -> List[StrategyProposal]:
        """Run a competition round."""
        proposals = []
        
        for agent in self._agents.values():
            if agent.risk_preference.value <= max_risk_tier.value:
                proposal = agent.propose_strategy(
                    registry=registry,
                    target_allocation_usd=target_allocation_usd,
                    max_risk_tier=max_risk_tier,
                )
                proposals.append(proposal)
                self._active_proposals[proposal.proposal_id] = proposal
        
        # Sort by expected Sharpe ratio
        proposals.sort(key=lambda p: p.expected_sharpe, reverse=True)
        
        self._competition_history.append({
            "timestamp": time.time(),
            "proposals": len(proposals),
            "target_allocation_usd": target_allocation_usd,
            "max_risk_tier": max_risk_tier.value,
        })
        
        return proposals
    
    def vote_on_proposal(
        self,
        proposal_id: str,
        voter_id: str,
        vote: float,  # -1 to 1
    ) -> bool:
        """Vote on a proposal."""
        if proposal_id not in self._active_proposals:
            return False
        
        self._active_proposals[proposal_id].votes[voter_id] = vote
        return True
    
    def get_winning_proposal(self) -> Optional[StrategyProposal]:
        """Get the proposal with highest votes."""
        if not self._active_proposals:
            return None
        
        best = None
        best_score = float('-inf')
        
        for proposal in self._active_proposals.values():
            if proposal.votes:
                score = sum(proposal.votes.values()) / len(proposal.votes)
            else:
                score = proposal.expected_sharpe
            
            if score > best_score:
                best_score = score
                best = proposal
        
        return best
    
    def accept_proposal(self, proposal_id: str) -> bool:
        """Accept a proposal."""
        if proposal_id not in self._active_proposals:
            return False
        
        proposal = self._active_proposals[proposal_id]
        proposal.strategy.status = StrategyStatus.APPROVED
        
        # Update agent stats
        if proposal.agent_id in self._agents:
            self._agents[proposal.agent_id].proposals_accepted += 1
            self._agents[proposal.agent_id].trust_score = min(
                1.0,
                self._agents[proposal.agent_id].trust_score + 0.05
            )
        
        return True
    
    def get_agents(self) -> List[YieldStrategyAgent]:
        """Get all agents."""
        return list(self._agents.values())
    
    def get_proposals(self) -> List[StrategyProposal]:
        """Get active proposals."""
        return list(self._active_proposals.values())


class TreasurySimulationSandbox:
    """
    Treasury-only simulation sandbox.
    
    Simulates yield strategies before deployment.
    """
    
    def __init__(self):
        self._simulations: Dict[str, Dict[str, Any]] = {}
        self._simulation_results: Dict[str, Dict[str, Any]] = {}
    
    def simulate_strategy(
        self,
        strategy: YieldStrategy,
        duration_days: int = 365,
        monte_carlo_runs: int = 1000,
    ) -> Dict[str, Any]:
        """Simulate a yield strategy."""
        simulation_id = f"sim_{uuid.uuid4().hex[:12]}"
        
        # Track simulation
        self._simulations[simulation_id] = {
            "strategy_id": strategy.strategy_id,
            "started_at": time.time(),
            "duration_days": duration_days,
            "monte_carlo_runs": monte_carlo_runs,
        }
        
        # Run Monte Carlo simulation
        import random
        
        results = []
        for _ in range(monte_carlo_runs):
            # Simulate each allocation
            total_return = 0.0
            for alloc in strategy.allocations:
                base_apy = alloc["expected_apy"]
                # Add volatility
                volatility = base_apy * 0.2  # 20% volatility
                simulated_apy = random.gauss(base_apy, volatility)
                simulated_apy = max(0, simulated_apy)  # No negative yields
                
                allocation_return = (alloc["allocation_pct"] / 100) * simulated_apy
                total_return += allocation_return
            
            results.append(total_return)
        
        # Calculate statistics
        results.sort()
        mean_return = sum(results) / len(results)
        std_dev = (sum((r - mean_return) ** 2 for r in results) / len(results)) ** 0.5
        
        simulation_result = {
            "simulation_id": simulation_id,
            "strategy_id": strategy.strategy_id,
            "duration_days": duration_days,
            "monte_carlo_runs": monte_carlo_runs,
            "mean_apy": mean_return,
            "std_dev": std_dev,
            "sharpe_ratio": mean_return / std_dev if std_dev > 0 else 0,
            "percentiles": {
                "p5": results[int(len(results) * 0.05)],
                "p25": results[int(len(results) * 0.25)],
                "p50": results[int(len(results) * 0.50)],
                "p75": results[int(len(results) * 0.75)],
                "p95": results[int(len(results) * 0.95)],
            },
            "var_95": results[int(len(results) * 0.05)],  # 5th percentile
            "max_drawdown_estimate": abs(min(results) - mean_return),
            "completed_at": time.time(),
        }
        
        self._simulation_results[simulation_id] = simulation_result
        
        # Update strategy with simulation results
        strategy.simulation_results = simulation_result
        
        return simulation_result
    
    def get_simulation(self, simulation_id: str) -> Optional[Dict[str, Any]]:
        """Get simulation results."""
        return self._simulation_results.get(simulation_id)
    
    def compare_strategies(
        self,
        strategies: List[YieldStrategy],
    ) -> Dict[str, Any]:
        """Compare multiple strategies."""
        comparisons = []
        
        for strategy in strategies:
            if strategy.simulation_results:
                comparisons.append({
                    "strategy_id": strategy.strategy_id,
                    "name": strategy.name,
                    "mean_apy": strategy.simulation_results["mean_apy"],
                    "sharpe_ratio": strategy.simulation_results["sharpe_ratio"],
                    "var_95": strategy.simulation_results["var_95"],
                })
        
        # Rank by Sharpe ratio
        comparisons.sort(key=lambda c: c["sharpe_ratio"], reverse=True)
        
        return {
            "comparisons": comparisons,
            "best_sharpe": comparisons[0] if comparisons else None,
            "best_return": max(comparisons, key=lambda c: c["mean_apy"]) if comparisons else None,
            "lowest_risk": min(comparisons, key=lambda c: abs(c["var_95"])) if comparisons else None,
        }


# Singleton instances
_yield_registry: Optional[YieldSourceRegistry] = None
_strategy_competition: Optional[StrategyCompetition] = None
_simulation_sandbox: Optional[TreasurySimulationSandbox] = None


def get_yield_registry() -> YieldSourceRegistry:
    global _yield_registry
    if _yield_registry is None:
        _yield_registry = YieldSourceRegistry()
    return _yield_registry


def get_strategy_competition() -> StrategyCompetition:
    global _strategy_competition
    if _strategy_competition is None:
        _strategy_competition = StrategyCompetition()
    return _strategy_competition


def get_simulation_sandbox() -> TreasurySimulationSandbox:
    global _simulation_sandbox
    if _simulation_sandbox is None:
        _simulation_sandbox = TreasurySimulationSandbox()
    return _simulation_sandbox
