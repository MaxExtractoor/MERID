"""Agent trust coupling with source reliability (Stage 6)."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from utils.logger import get_logger

logger = get_logger("core.agent_trust")


@dataclass
class AgentTrustProfile:
    """Trust profile for a single agent."""

    agent_id: str
    trust: float = 1.0  # Current trust [0.5, 2.0]
    last_active_at: float = field(default_factory=lambda: time.time())
    total_votes: int = 0
    correct_votes: int = 0
    avg_srw_used: float = 1.0  # Rolling average of source SRW used
    trust_max: float = 2.0  # Dynamic cap for source abuse protection

    def update_trust(
        self,
        vote_correct: bool,
        source_srw: float,
    ) -> None:
        """
        Update agent trust using Stage 6 formula:
        
        Δtrust = 
            +0.05 × srw           if correct
            −0.08 × (1.1 − srw)   if incorrect
        
        Interpretation:
        - Being right with weak data helps a little
        - Being wrong with strong data hurts more
        - Being wrong with bad data hurts less
        """
        self.total_votes += 1
        if vote_correct:
            self.correct_votes += 1

        # Compute trust delta
        if vote_correct:
            delta = 0.05 * source_srw
        else:
            delta = -0.08 * (1.1 - source_srw)

        self.trust += delta
        self.trust = min(max(self.trust, 0.5), self.trust_max)

        # Update rolling average SRW
        self._update_avg_srw(source_srw)

        # Check for source abuse
        self._check_source_abuse()

        self.last_active_at = time.time()

        logger.debug(
            "Agent %s trust updated: %.3f (delta=%.4f, correct=%s, srw=%.3f)",
            self.agent_id,
            self.trust,
            delta,
            vote_correct,
            source_srw,
        )

    def _update_avg_srw(self, new_srw: float) -> None:
        """Update rolling average of source SRW used (exponential moving average)."""
        alpha = 0.2  # Smoothing factor
        self.avg_srw_used = alpha * new_srw + (1 - alpha) * self.avg_srw_used

    def _check_source_abuse(self) -> None:
        """
        Apply soft trust cap if agent repeatedly relies on low-SRW sources.
        
        If avg_srw_used < 0.4 over recent votes, cap trust_max at 1.2
        """
        if self.total_votes >= 10 and self.avg_srw_used < 0.4:
            self.trust_max = 1.2
            if self.trust > self.trust_max:
                self.trust = self.trust_max
            logger.warning(
                "Agent %s trust capped at %.1f due to low-quality source usage (avg_srw=%.3f)",
                self.agent_id,
                self.trust_max,
                self.avg_srw_used,
            )

    def apply_decay(self) -> None:
        """
        Apply time-based trust decay for agent inactivity:
        
        days_idle = (now - last_active_at) / 86400
        decay_factor = exp(-0.03 × days_idle)
        trust *= decay_factor
        trust = clamp(trust, 0.5, 2.0)
        """
        now = time.time()
        days_idle = (now - self.last_active_at) / 86400.0
        if days_idle > 0:
            decay_factor = math.exp(-0.03 * days_idle)
            old_trust = self.trust
            self.trust *= decay_factor
            self.trust = min(max(self.trust, 0.5), 2.0)
            if abs(old_trust - self.trust) > 0.01:
                logger.debug(
                    "Agent %s trust decayed: %.3f → %.3f (idle %.1f days)",
                    self.agent_id,
                    old_trust,
                    self.trust,
                    days_idle,
                )

    def to_dict(self) -> dict:
        """Serialize for API exposure."""
        return {
            "agent_id": self.agent_id,
            "trust": round(self.trust, 4),
            "last_active_at": self.last_active_at,
            "total_votes": self.total_votes,
            "correct_votes": self.correct_votes,
            "accuracy": round(self.correct_votes / self.total_votes, 4) if self.total_votes > 0 else 0.0,
            "avg_srw_used": round(self.avg_srw_used, 4),
            "trust_max": self.trust_max,
        }


class AgentTrustRegistry:
    """Global registry tracking trust for all agents."""

    def __init__(self) -> None:
        self._agents: Dict[str, AgentTrustProfile] = {}

    def get_trust(self, agent_id: str) -> float:
        """Get current trust for an agent (defaults to 1.0 if unknown)."""
        if agent_id not in self._agents:
            self._agents[agent_id] = AgentTrustProfile(agent_id=agent_id)
        return self._agents[agent_id].trust

    def update_trust(
        self,
        agent_id: str,
        vote_correct: bool,
        source_srw: float,
    ) -> None:
        """Update agent trust based on vote outcome and source quality."""
        if agent_id not in self._agents:
            self._agents[agent_id] = AgentTrustProfile(agent_id=agent_id)
        self._agents[agent_id].update_trust(vote_correct, source_srw)

    def apply_decay_all(self) -> None:
        """Apply time-based decay to all agents."""
        for profile in self._agents.values():
            profile.apply_decay()

    def get_profile(self, agent_id: str) -> Optional[AgentTrustProfile]:
        """Get full trust profile for an agent."""
        return self._agents.get(agent_id)

    def all_profiles(self) -> Dict[str, AgentTrustProfile]:
        """Return all tracked agent profiles."""
        return self._agents.copy()

    def snapshot(self) -> Dict[str, dict]:
        """Serialize all agent trust profiles for API exposure."""
        return {agent_id: profile.to_dict() for agent_id, profile in self._agents.items()}


# Global singleton
_trust_registry = AgentTrustRegistry()


def get_trust_registry() -> AgentTrustRegistry:
    """Access the global agent trust registry."""
    return _trust_registry
