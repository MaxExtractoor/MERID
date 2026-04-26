"""
Per-Agent and Per-Team Risk Quotas
Implements risk tiering and quota management for agents and teams based on debate performance.
"""

import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
import logging
import asyncio

from merid.prediction.debate import get_debate_store
from core.slo_monitor import SLOMonitor

logger = logging.getLogger("merid.prediction.agent_risk_quotas")


class RiskTier(Enum):
    """Risk tiers for agents and teams."""
    GOLD = "gold"      # Highest performing, highest risk quota
    SILVER = "silver"  # Good performance, moderate risk quota
    BRONZE = "bronze"  # Lower performance, limited risk quota
    RESTRICTED = "restricted"  # Poor performance, minimal risk quota


@dataclass
class AgentRiskProfile:
    """Risk profile for an individual agent."""
    agent_id: str
    team_id: str
    tier: RiskTier
    debate_count: int
    avg_debate_lift: float
    success_rate: float
    calibration_score: float
    reward_total: float
    badges_earned: List[str]
    risk_quota_pct: float  # % of portfolio equity this agent can control
    current_risk_pct: float = 0.0
    last_updated: float = field(default_factory=time.time)


@dataclass
class TeamRiskProfile:
    """Risk profile for a team."""
    team_id: str
    tier: RiskTier
    agent_count: int
    avg_debate_lift: float
    success_rate: float
    total_reward: float
    risk_quota_pct: float  # % of portfolio equity this team can control
    current_risk_pct: float = 0.0
    last_updated: float = field(default_factory=time.time)


@dataclass
class RiskQuotaCheck:
    """Result of a risk quota check."""
    passed: bool
    agent_quota_pct: float
    team_quota_pct: float
    current_agent_risk: float
    current_team_risk: float
    violation_type: Optional[str] = None
    recommended_multiplier: Optional[float] = None


class AgentRiskQuotaManager:
    """Manages risk quotas for agents and teams based on debate performance."""
    
    def __init__(self):
        self.slo_monitor = SLOMonitor.get_instance()
        self.debate_store = get_debate_store()
        self.agent_profiles: Dict[str, AgentRiskProfile] = {}
        self.team_profiles: Dict[str, TeamRiskProfile] = {}
        self.position_allocations: Dict[str, Dict[str, float]] = {}  # symbol -> {agent_id: risk_amount}
        # CRITICAL: No default - must fetch from actual settings/Kalshi balance
        self._portfolio_equity_usd: Optional[float] = None  # Lazy-loaded from settings
        
        # Risk tier configurations
        self.tier_configs = {
            RiskTier.GOLD: {
                "quota_pct": 0.015,      # 1.5% of portfolio equity per agent (15% of 10% max risk)
                "team_quota_pct": 0.025,  # 2.5% of portfolio equity per team
                "min_debate_count": 10,
                "min_avg_lift": 0.02,
                "min_success_rate": 0.7,
                "min_calibration": 0.6,
                "min_reward": 10.0  # $10 minimum (was $100)
            },
            RiskTier.SILVER: {
                "quota_pct": 0.008,      # 0.8% of portfolio equity per agent
                "team_quota_pct": 0.015,  # 1.5% of portfolio equity per team
                "min_debate_count": 5,
                "min_avg_lift": 0.01,
                "min_success_rate": 0.5,
                "min_calibration": 0.4,
                "min_reward": 5.0  # $5 minimum
            },
            RiskTier.BRONZE: {
                "quota_pct": 0.003,      # 0.3% of portfolio equity per agent
                "team_quota_pct": 0.008,  # 0.8% of portfolio equity per team
                "min_debate_count": 3,
                "min_avg_lift": 0.005,
                "min_success_rate": 0.3,
                "min_calibration": 0.2,
                "min_reward": 2.5  # $2.50 minimum
            },
            RiskTier.RESTRICTED: {
                "quota_pct": 0.001,      # 0.1% of portfolio equity per agent
                "team_quota_pct": 0.003,  # 0.3% of portfolio equity per team
                "min_debate_count": 0,
                "min_avg_lift": 0.0,
                "min_success_rate": 0.0,
                "min_calibration": 0.0,
                "min_reward": 0.0
            }
        }
        
        # Badge bonuses
        self.badge_bonuses = {
            "top_performer": 0.02,    # +2% quota
            "consistent": 0.01,        # +1% quota
            "high_accuracy": 0.015,    # +1.5% quota
            "collaborative": 0.005     # +0.5% quota
        }
        
        self.last_profile_update = 0.0
        self.profile_update_interval = 3600  # Update profiles every hour
    
    @property
    def portfolio_equity_usd(self) -> float:
        """
        Get portfolio equity from settings (actual Kalshi bankroll).
        
        Falls back to settings.MERID_TOTAL_CAPITAL_USD which is either:
        1. Explicitly configured, or
        2. Auto-fetched from Kalshi API balance
        """
        if self._portfolio_equity_usd is None:
            try:
                from merid.settings import settings
                self._portfolio_equity_usd = settings.MERID_TOTAL_CAPITAL_USD
                logger.info(
                    "[AGENT_RISK_QUOTAS] Loaded portfolio equity from settings: $%.2f",
                    self._portfolio_equity_usd
                )
            except Exception as exc:
                logger.error(
                    "[AGENT_RISK_QUOTAS] Failed to load portfolio equity from settings: %s. "
                    "Risk quotas will fail closed.",
                    exc
                )
                # Fail-closed: return 0 to trigger rejection
                self._portfolio_equity_usd = 0.0
        return self._portfolio_equity_usd
    
    async def check_position_risk_quota(
        self,
        symbol: str,
        agent_id: str,
        position_risk: float,
        portfolio_equity: float
    ) -> RiskQuotaCheck:
        """
        Check if a position complies with agent and team risk quotas.
        
        Args:
            symbol: Kalshi symbol
            agent_id: Agent requesting the position
            position_risk: Risk amount of the position
            portfolio_equity: Total portfolio equity
            
        Returns:
            RiskQuotaCheck with compliance status and recommendations
        """
        try:
            # Ensure profiles are up to date
            await self._update_profiles_if_needed()
            
            # Get agent and team profiles
            agent_profile = self.agent_profiles.get(agent_id)
            if not agent_profile:
                # Unknown agent - assign restricted tier
                agent_profile = await self._create_default_agent_profile(agent_id)
            
            team_profile = self.team_profiles.get(agent_profile.team_id)
            if not team_profile:
                # Unknown team - assign restricted tier
                team_profile = await self._create_default_team_profile(agent_profile.team_id)
            
            # Calculate current risk allocations
            current_agent_risk = self._get_agent_current_risk(agent_id)
            current_team_risk = self._get_team_current_risk(agent_profile.team_id)
            
            # Calculate risk percentages
            current_agent_risk_pct = current_agent_risk / portfolio_equity if portfolio_equity > 0 else 0
            current_team_risk_pct = current_team_risk / portfolio_equity if portfolio_equity > 0 else 0
            
            # Check quota compliance
            agent_quota_pct = agent_profile.risk_quota_pct
            team_quota_pct = team_profile.risk_quota_pct
            
            new_agent_risk_pct = current_agent_risk_pct + (position_risk / portfolio_equity if portfolio_equity > 0 else 0)
            new_team_risk_pct = current_team_risk_pct + (position_risk / portfolio_equity if portfolio_equity > 0 else 0)
            self.last_portfolio_equity = portfolio_equity if portfolio_equity > 0 else self.last_portfolio_equity
            
            passed = (new_agent_risk_pct <= agent_quota_pct and 
                     new_team_risk_pct <= team_quota_pct)
            
            violation_type = None
            recommended_multiplier = None
            
            if not passed:
                agent_mult = team_mult = None
                if new_agent_risk_pct > agent_quota_pct:
                    max_allowed_risk = agent_quota_pct * portfolio_equity
                    agent_mult = max_allowed_risk / position_risk if position_risk > 0 else 1.0
                if new_team_risk_pct > team_quota_pct:
                    max_allowed_risk = team_quota_pct * portfolio_equity
                    team_mult = max_allowed_risk / position_risk if position_risk > 0 else 1.0

                available_mults = [x for x in (agent_mult, team_mult) if x is not None]
                if available_mults:
                    recommended_multiplier = min(available_mults)
                    violation_type = (
                        "both_quotas_exceeded"
                        if agent_mult is not None and team_mult is not None
                        else "agent_quota_exceeded" if agent_mult is not None
                        else "team_quota_exceeded"
                    )
            
            # Track SLO metrics
            self.slo_monitor.track_slo(
                metric_name="agent.risk.quota_check",
                success=passed,
                total=1,
                metadata={
                    "symbol": symbol,
                    "agent_id": agent_id,
                    "team_id": agent_profile.team_id,
                    "agent_tier": agent_profile.tier.value,
                    "team_tier": team_profile.tier.value,
                    "position_risk": position_risk,
                    "current_agent_risk_pct": current_agent_risk_pct,
                    "current_team_risk_pct": current_team_risk_pct,
                    "agent_quota_pct": agent_quota_pct,
                    "team_quota_pct": team_quota_pct,
                    "violation_type": violation_type,
                    "recommended_multiplier": recommended_multiplier
                }
            )
            
            logger.info(
                f"Risk quota check for {agent_id} ({agent_profile.tier.value}): "
                f"{'PASSED' if passed else 'FAILED'} - "
                f"agent: {current_agent_risk_pct:.2%}/{agent_quota_pct:.2%}, "
                f"team: {current_team_risk_pct:.2%}/{team_quota_pct:.2%}"
            )
            
            return RiskQuotaCheck(
                passed=passed,
                agent_quota_pct=agent_quota_pct,
                team_quota_pct=team_quota_pct,
                current_agent_risk=current_agent_risk_pct,
                current_team_risk=current_team_risk_pct,
                violation_type=violation_type,
                recommended_multiplier=recommended_multiplier
            )
            
        except Exception as e:
            logger.error(f"Error checking risk quota for agent {agent_id}: {e}")
            # Fail-safe: restrict to minimal quota
            return RiskQuotaCheck(
                passed=False,
                agent_quota_pct=0.01,
                team_quota_pct=0.03,
                current_agent_risk=0.0,
                current_team_risk=0.0,
                violation_type="error",
                recommended_multiplier=0.5
            )
    
    async def allocate_position_risk(self, symbol: str, agent_id: str, risk_amount: float):
        """Allocate position risk to an agent."""
        if symbol not in self.position_allocations:
            self.position_allocations[symbol] = {}
        
        self.position_allocations[symbol][agent_id] = risk_amount
        
        # Update current risk in profiles using most recent equity
        equity = max(self.last_portfolio_equity, 1.0)
        if agent_id in self.agent_profiles:
            agent_profile = self.agent_profiles[agent_id]
            agent_profile.current_risk_pct = self._get_agent_current_risk(agent_id) / equity

            team_id = agent_profile.team_id
            if team_id in self.team_profiles:
                team_profile = self.team_profiles[team_id]
                team_profile.current_risk_pct = self._get_team_current_risk(team_id) / equity
    
    def deallocate_position_risk(self, symbol: str, agent_id: str):
        """Deallocate position risk from an agent."""
        if symbol in self.position_allocations and agent_id in self.position_allocations[symbol]:
            del self.position_allocations[symbol][agent_id]
            
            # Clean up empty symbol allocations
            if not self.position_allocations[symbol]:
                del self.position_allocations[symbol]
            
            # Update current risk in profiles
            equity = max(self.last_portfolio_equity, 1.0)
            if agent_id in self.agent_profiles:
                agent_profile = self.agent_profiles[agent_id]
                agent_profile.current_risk_pct = self._get_agent_current_risk(agent_id) / equity
                team_id = agent_profile.team_id
                if team_id in self.team_profiles:
                    team_profile = self.team_profiles[team_id]
                    team_profile.current_risk_pct = self._get_team_current_risk(team_id) / equity
    
    async def _update_profiles_if_needed(self):
        """Update agent and team profiles if they're stale."""
        current_time = time.time()
        if current_time - self.last_profile_update > self.profile_update_interval:
            await self._update_all_profiles()
            self.last_profile_update = current_time
    
    async def _update_all_profiles(self):
        """Update all agent and team risk profiles based on recent performance."""
        try:
            # Get agent performance data from debate store
            debate_store = get_debate_store()
            
            # Get agent performance summary
            try:
                agent_performance = await debate_store.get_agent_performance_summary()
                logger.info(f"Retrieved performance data for {len(agent_performance)} agents")
            except Exception as e:
                logger.warning(f"Could not fetch agent performance from debate store: {e}")
                agent_performance = {}
            
            # Get team performance summary  
            try:
                team_performance = await debate_store.get_team_performance_summary()
                logger.info(f"Retrieved performance data for {len(team_performance)} teams")
            except Exception as e:
                logger.warning(f"Could not fetch team performance from debate store: {e}")
                team_performance = {}
            
            # Update agent profiles
            for agent_id, perf_data in agent_performance.items():
                await self._update_agent_profile_from_performance(agent_id, perf_data)
            
            # Update team profiles
            for team_id, perf_data in team_performance.items():
                await self._update_team_profile_from_performance(team_id, perf_data)
            
            logger.info(f"Updated {len(agent_performance)} agent and {len(team_performance)} team risk profiles")
            
        except Exception as e:
            logger.error(f"Error updating risk profiles: {e}")
    
    async def _update_agent_profile_from_performance(self, agent_id: str, perf_data: Dict[str, Any]):
        """Update agent profile based on performance data."""
        # Extract performance metrics
        debate_count = perf_data.get("debate_count", 0)
        avg_debate_lift = perf_data.get("avg_debate_lift", 0.0)
        success_rate = perf_data.get("success_rate", 0.0)
        calibration_score = perf_data.get("calibration_score", 0.0)
        reward_total = perf_data.get("reward_total", 0.0)
        badges_earned = perf_data.get("badges_earned", [])
        team_id = perf_data.get("team_id", f"unknown_team_{agent_id}")
        
        # Determine risk tier based on performance
        new_tier = self._calculate_agent_tier(debate_count, avg_debate_lift, success_rate, calibration_score)
        
        # Get or create profile
        if agent_id not in self.agent_profiles:
            await self._create_default_agent_profile(agent_id)
        
        profile = self.agent_profiles[agent_id]
        
        # Update profile
        profile.team_id = team_id
        profile.tier = new_tier
        profile.debate_count = debate_count
        profile.avg_debate_lift = avg_debate_lift
        profile.success_rate = success_rate
        profile.calibration_score = calibration_score
        profile.reward_total = reward_total
        profile.badges_earned = badges_earned
        profile.risk_quota_pct = self.tier_configs[new_tier]["quota_pct"]
        profile.last_updated = time.time()
        
        # Ensure team profile exists
        if team_id not in self.team_profiles:
            await self._create_default_team_profile(team_id)
    
    async def _update_team_profile_from_performance(self, team_id: str, perf_data: Dict[str, Any]):
        """Update team profile based on performance data."""
        # Extract performance metrics
        agent_count = perf_data.get("agent_count", 0)
        avg_debate_lift = perf_data.get("avg_debate_lift", 0.0)
        success_rate = perf_data.get("success_rate", 0.0)
        total_reward = perf_data.get("total_reward", 0.0)
        
        # Determine risk tier based on team performance
        new_tier = self._calculate_team_tier(agent_count, avg_debate_lift, success_rate)
        
        # Get or create profile
        if team_id not in self.team_profiles:
            await self._create_default_team_profile(team_id)
        
        profile = self.team_profiles[team_id]
        
        # Update profile
        profile.tier = new_tier
        profile.agent_count = agent_count
        profile.avg_debate_lift = avg_debate_lift
        profile.success_rate = success_rate
        profile.total_reward = total_reward
        # BUG-O fix: team profiles use "team_quota_pct", not "quota_pct".
        profile.risk_quota_pct = self.tier_configs[new_tier]["team_quota_pct"]
        profile.last_updated = time.time()

    def _calculate_agent_tier(self, debate_count: int, avg_lift: float, success_rate: float, calibration: float) -> RiskTier:
        """Calculate agent risk tier based on performance metrics."""
        performance_data = {
            "debate_count": debate_count,
            "avg_debate_lift": avg_lift,
            "success_rate": success_rate,
            "calibration_score": calibration,
            "reward_total": 0.0,
        }
        return self._determine_agent_tier(performance_data)
    
    def _calculate_team_tier(self, agent_count: int, avg_lift: float, success_rate: float) -> RiskTier:
        """Calculate team risk tier based on performance metrics."""
        # Minimum agents required for tier consideration
        if agent_count < 2:
            return RiskTier.RESTRICTED
        
        # Gold tier: Excellent team performance
        if (avg_lift >= 0.03 and success_rate >= 0.65 and agent_count >= 5):
            return RiskTier.GOLD
        
        # Silver tier: Good team performance
        if (avg_lift >= 0.01 and success_rate >= 0.55 and agent_count >= 3):
            return RiskTier.SILVER
        
        # Bronze tier: Moderate team performance
        if (avg_lift >= 0.0 and success_rate >= 0.45 and agent_count >= 2):
            return RiskTier.BRONZE
        
        # Restricted tier: Poor team performance
        return RiskTier.RESTRICTED
    
    async def _create_default_agent_profile(self, agent_id: str) -> AgentRiskProfile:
        """Create a default agent profile with restricted tier."""
        team_id = f"unknown_team_{agent_id}"
        
        profile = AgentRiskProfile(
            agent_id=agent_id,
            team_id=team_id,
            tier=RiskTier.RESTRICTED,
            debate_count=0,
            avg_debate_lift=0.0,
            success_rate=0.0,
            calibration_score=0.0,
            reward_total=0.0,
            badges_earned=[],
            risk_quota_pct=self.tier_configs[RiskTier.RESTRICTED]["quota_pct"]
        )
        
        self.agent_profiles[agent_id] = profile
        
        # Ensure team profile exists
        if team_id not in self.team_profiles:
            await self._create_default_team_profile(team_id)
        
        return profile
    
    async def _create_default_team_profile(self, team_id: str) -> TeamRiskProfile:
        """Create a default team profile with restricted tier."""
        profile = TeamRiskProfile(
            team_id=team_id,
            tier=RiskTier.RESTRICTED,
            agent_count=0,
            avg_debate_lift=0.0,
            success_rate=0.0,
            total_reward=0.0,
            risk_quota_pct=self.tier_configs[RiskTier.RESTRICTED]["team_quota_pct"]
        )
        
        self.team_profiles[team_id] = profile
        return profile
    
    def _determine_agent_tier(self, performance_data: Dict[str, Any]) -> RiskTier:
        """Determine agent risk tier based on performance metrics."""
        # Check against tier requirements in order (highest to lowest)
        for tier in [RiskTier.GOLD, RiskTier.SILVER, RiskTier.BRONZE]:
            config = self.tier_configs[tier]
            
            if (performance_data.get("debate_count", 0) >= config["min_debate_count"] and
                performance_data.get("avg_debate_lift", 0) >= config["min_avg_lift"] and
                performance_data.get("success_rate", 0) >= config["min_success_rate"] and
                performance_data.get("calibration_score", 0) >= config["min_calibration"] and
                performance_data.get("reward_total", 0) >= config["min_reward"]):
                return tier
        
        return RiskTier.RESTRICTED
    
    def _calculate_quota_with_bonuses(self, base_quota: float, badges: List[str]) -> float:
        """Calculate risk quota with badge bonuses."""
        quota = base_quota
        for badge in badges:
            if badge in self.badge_bonuses:
                quota += self.badge_bonuses[badge]
        return quota
    
    def _get_agent_current_risk(self, agent_id: str) -> float:
        """Get current total risk allocated to an agent."""
        total_risk = 0.0
        for symbol_allocations in self.position_allocations.values():
            total_risk += symbol_allocations.get(agent_id, 0.0)
        return total_risk
    
    def _get_team_current_risk(self, team_id: str) -> float:
        """Get current total risk allocated to a team."""
        total_risk = 0.0
        for agent_id, profile in self.agent_profiles.items():
            if profile.team_id == team_id:
                total_risk += self._get_agent_current_risk(agent_id)
        return total_risk
    
    def get_risk_quota_summary(self) -> Dict[str, Any]:
        """Get summary of risk quotas and current utilization."""
        agent_summary = {}
        for agent_id, profile in self.agent_profiles.items():
            agent_summary[agent_id] = {
                "team_id": profile.team_id,
                "tier": profile.tier.value,
                "quota_pct": profile.risk_quota_pct,
                "current_risk_pct": profile.current_risk_pct,
                "utilization_pct": profile.current_risk_pct / profile.risk_quota_pct if profile.risk_quota_pct > 0 else 0,
                "debate_count": profile.debate_count,
                "avg_debate_lift": profile.avg_debate_lift,
                "success_rate": profile.success_rate
            }
        
        team_summary = {}
        for team_id, profile in self.team_profiles.items():
            team_summary[team_id] = {
                "tier": profile.tier.value,
                "quota_pct": profile.risk_quota_pct,
                "current_risk_pct": profile.current_risk_pct,
                "utilization_pct": profile.current_risk_pct / profile.risk_quota_pct if profile.risk_quota_pct > 0 else 0,
                "agent_count": profile.agent_count,
                "avg_debate_lift": profile.avg_debate_lift,
                "success_rate": profile.success_rate
            }
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_profiles": agent_summary,
            "team_profiles": team_summary,
            "tier_distribution": {
                "gold": len([p for p in self.agent_profiles.values() if p.tier == RiskTier.GOLD]),
                "silver": len([p for p in self.agent_profiles.values() if p.tier == RiskTier.SILVER]),
                "bronze": len([p for p in self.agent_profiles.values() if p.tier == RiskTier.BRONZE]),
                "restricted": len([p for p in self.agent_profiles.values() if p.tier == RiskTier.RESTRICTED])
            },
            "total_positions": len(self.position_allocations),
            "quota_utilization": {
                "agents": {
                    "total_quota_pct": sum(p.risk_quota_pct for p in self.agent_profiles.values()),
                    "total_current_pct": sum(p.current_risk_pct for p in self.agent_profiles.values()),
                    "utilization": sum(p.current_risk_pct for p in self.agent_profiles.values()) / sum(p.risk_quota_pct for p in self.agent_profiles.values()) if self.agent_profiles else 0
                },
                "teams": {
                    "total_quota_pct": sum(p.risk_quota_pct for p in self.team_profiles.values()),
                    "total_current_pct": sum(p.current_risk_pct for p in self.team_profiles.values()),
                    "utilization": sum(p.current_risk_pct for p in self.team_profiles.values()) / sum(p.risk_quota_pct for p in self.team_profiles.values()) if self.team_profiles else 0
                }
            }
        }
    
    def update_agent_tier(self, agent_id: str, new_tier: RiskTier):
        """Manually update an agent's risk tier."""
        if agent_id in self.agent_profiles:
            old_tier = self.agent_profiles[agent_id].tier
            self.agent_profiles[agent_id].tier = new_tier
            
            # Update quota based on new tier
            base_quota = self.tier_configs[new_tier]["quota_pct"]
            badges = self.agent_profiles[agent_id].badges_earned
            self.agent_profiles[agent_id].risk_quota_pct = self._calculate_quota_with_bonuses(base_quota, badges)
            
            logger.info(f"Updated agent {agent_id} tier: {old_tier.value} → {new_tier.value}")
        else:
            logger.warning(f"Agent {agent_id} not found for tier update")
    
    def clear_position_allocations(self):
        """Clear all position allocations (useful for end-of-day reset)."""
        self.position_allocations.clear()
        
        # Reset current risk in profiles
        for profile in self.agent_profiles.values():
            profile.current_risk_pct = 0.0
        
        for profile in self.team_profiles.values():
            profile.current_risk_pct = 0.0
        
        logger.info("Cleared all position allocations")


# Global instance
_quota_manager_instance: Optional[AgentRiskQuotaManager] = None


def get_agent_risk_quota_manager() -> AgentRiskQuotaManager:
    """Get the global agent risk quota manager instance."""
    global _quota_manager_instance
    if _quota_manager_instance is None:
        _quota_manager_instance = AgentRiskQuotaManager()
    return _quota_manager_instance


async def check_agent_risk_quota(
    symbol: str,
    agent_id: str,
    position_risk: float,
    portfolio_equity: float
) -> RiskQuotaCheck:
    """
    Check if a position complies with agent risk quotas.
    
    Args:
        symbol: Kalshi symbol
        agent_id: Agent requesting the position
        position_risk: Risk amount of the position
        portfolio_equity: Total portfolio equity
        
    Returns:
        RiskQuotaCheck with compliance status
    """
    quota_manager = get_agent_risk_quota_manager()
    return await quota_manager.check_position_risk_quota(symbol, agent_id, position_risk, portfolio_equity)
