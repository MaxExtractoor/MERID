from __future__ import annotations

# Stage 3 Swarm Evolution: performance-weighted spawning and pruning.

import itertools
import random
from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from core.time_authority import current_time
from utils.logger import get_logger

from swarm.performance import SwarmPerformanceLedger


@dataclass
class LineageRecord:
    agent_id: str
    parent_id: str | None
    generation: int
    created_at: str
    notes: str = ""


class SwarmSpawner:
    """Controls which agents are active using ledger performance data."""

    def __init__(
        self,
        ledger: SwarmPerformanceLedger,
        *,
        max_population: int = 8,
        stale_score: float = 0.35,
        spawn_threshold: float = 0.6,
        min_votes_to_spawn: int = 4,
    ) -> None:
        self.ledger = ledger
        self.max_population = max_population
        self.stale_score = stale_score
        self.spawn_threshold = spawn_threshold
        self.min_votes_to_spawn = min_votes_to_spawn
        self._active_agents: List = []
        self._lineage: Dict[str, LineageRecord] = {}
        self.logger = get_logger("swarm.spawner")
        self._id_counter = itertools.count(1)

    def bootstrap(self, agents: Sequence) -> List:
        self._active_agents = list(agents)
        now = current_time()["utc_iso"]
        for agent in self._active_agents:
            self._lineage[agent.agent_id] = LineageRecord(
                agent_id=agent.agent_id,
                parent_id=None,
                generation=0,
                created_at=now,
                notes="bootstrap",
            )
        self.logger.info("Spawner bootstrapped with %d base agents.", len(self._active_agents))
        return list(self._active_agents)

    def refresh_population(self) -> List:
        leaderboard = {row["agent_id"]: row for row in self.ledger.leaderboard(limit=20)}

        # Retire underperformers (exclude original bootstrap generation to preserve diversity)
        survivors: List = []
        for agent in self._active_agents:
            stats = leaderboard.get(agent.agent_id)
            lineage = self._lineage.get(agent.agent_id)
            if stats and stats["votes"] >= self.min_votes_to_spawn and stats["score"] < self.stale_score:
                if lineage and lineage.generation > 0:
                    self.logger.info("Retiring agent %s (score %.2f).", agent.agent_id, stats["score"])
                    continue
            survivors.append(agent)

        self._active_agents = survivors

        if len(self._active_agents) < self.max_population:
            parent_stats = self.ledger.best_parent(min_score=self.spawn_threshold, min_votes=self.min_votes_to_spawn)
            if parent_stats:
                parent = self._find_agent(parent_stats["agent_id"])
                if parent:
                    child = self._spawn_child(parent)
                    self._active_agents.append(child)
                    self.logger.info("Spawned child agent %s from parent %s.", child.agent_id, parent.agent_id)

        # Ensure diversity by random shuffling (prevents ordering bias in orchestrator)
        random.shuffle(self._active_agents)
        return list(self._active_agents)

    def lineage(self) -> List[LineageRecord]:
        return list(self._lineage.values())

    def _spawn_child(self, parent) -> object:
        suffix = next(self._id_counter)
        base_id = parent.agent_id.split("#")[0]
        child_id = f"{base_id}#{suffix:04d}"
        agent_cls = parent.__class__

        try:
            child = agent_cls(agent_id=child_id, model_name=getattr(parent, "model_name", None))
        except TypeError:
            child = agent_cls()  # Fall back to constructor defaults
            setattr(child, "agent_id", child_id)

        # Inherit trust baseline and subtle mutation via tool budget adjustments (if present)
        child.trust = getattr(parent, "trust", 1.0)
        if hasattr(child, "tool_budget"):
            delta = random.choice([-1, 0, 1])
            child.tool_budget = max(0, child.tool_budget + delta)

        now = current_time()["utc_iso"]
        parent_record = self._lineage.get(parent.agent_id)
        generation = (parent_record.generation + 1) if parent_record else 1
        self._lineage[child_id] = LineageRecord(
            agent_id=child_id,
            parent_id=parent.agent_id,
            generation=generation,
            created_at=now,
            notes="spawned",
        )
        return child

    def _find_agent(self, agent_id: str):
        for agent in self._active_agents:
            if agent.agent_id == agent_id:
                return agent
        return None
