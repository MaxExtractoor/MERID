from __future__ import annotations

# Stage 3 Swarm Evolution: performance-weighted spawning and pruning.

import itertools
import random
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

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


@dataclass
class QuarantineRecord:
    """Tracks a spawned child waiting for gauntlet clearance."""
    agent_id: str
    parent_id: str
    quarantined_at: str
    gauntlet_passed: bool = False
    gauntlet_verdict_id: Optional[str] = None


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
        self._quarantine: Dict[str, QuarantineRecord] = {}
        self._quarantine_agents: Dict[str, object] = {}
        self.logger = get_logger("swarm.spawner")
        self._id_counter = itertools.count(1)
        self._bootstrapped = False

        # Tracking for mining metrics
        self._replication_count = 0
        self._termination_count = 0
        self._evolution_count = 0

    def get_active_agents(self) -> List:
        """Get list of currently active agents."""
        return list(self._active_agents)
    
    def get_replication_count(self) -> int:
        """Get total number of agent replications."""
        return self._replication_count
    
    def get_termination_count(self) -> int:
        """Get total number of agent terminations."""
        return self._termination_count
    
    def get_evolution_count(self) -> int:
        """Get total number of charter evolutions."""
        return self._evolution_count
    
    def bootstrap(self, agents: Sequence) -> List:
        if self._bootstrapped:
            self.logger.warning(
                "Spawner.bootstrap() called more than once — ignoring duplicate call "
                "to prevent generation-0 proliferation."
            )
            return list(self._active_agents)
        self._bootstrapped = True
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

        # Promote quarantined children that have since passed the gauntlet
        newly_released = self._release_quarantined()
        for child in newly_released:
            self._active_agents.append(child)
            self.logger.info(
                "Released quarantined agent %s into active pool (gauntlet passed).",
                child.agent_id,
            )

        # Only spawn a new child if there is still room after releasing quarantined agents
        if len(self._active_agents) < self.max_population:
            parent_stats = self.ledger.best_parent(min_score=self.spawn_threshold, min_votes=self.min_votes_to_spawn)
            if parent_stats:
                parent = self._find_agent(parent_stats["agent_id"])
                if parent:
                    child = self._spawn_child(parent)
                    # Do NOT add to _active_agents — child is quarantined until gauntlet passes
                    self._store_quarantined_agent(child.agent_id, child)
                    self._quarantine_child(child, parent.agent_id)
                    self.logger.info(
                        "Spawned child agent %s from parent %s — placed in quarantine pending gauntlet.",
                        child.agent_id,
                        parent.agent_id,
                    )

        # Ensure diversity by random shuffling (prevents ordering bias in orchestrator)
        random.shuffle(self._active_agents)
        return list(self._active_agents)

    def lineage(self) -> List[LineageRecord]:
        return list(self._lineage.values())

    def quarantine_status(self) -> List[dict]:
        """Return current quarantine queue for monitoring."""
        return [
            {
                "agent_id": r.agent_id,
                "parent_id": r.parent_id,
                "quarantined_at": r.quarantined_at,
                "gauntlet_passed": r.gauntlet_passed,
            }
            for r in self._quarantine.values()
        ]

    def clear_gauntlet_pass(self, agent_id: str, verdict_id: str) -> bool:
        """Mark a quarantined agent as gauntlet-passed so it is released on the
        next refresh_population() call.

        Called externally by the gauntlet runner after a PASS verdict.
        """
        rec = self._quarantine.get(agent_id)
        if rec is None:
            return False
        rec.gauntlet_passed = True
        rec.gauntlet_verdict_id = verdict_id
        self.logger.info(
            "Gauntlet cleared for quarantined agent %s (verdict=%s).",
            agent_id,
            verdict_id,
        )
        return True

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

        # Reset trust to 0 — child must earn trust via gauntlet, not inherit parent's.
        # Tool budget mutation is still allowed as a diversity mechanism.
        child.trust = 0.0
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
        self._replication_count += 1
        return child

    def _quarantine_child(self, child, parent_id: str) -> None:
        """Place a newly spawned child in the quarantine queue.

        The child will not be added to _active_agents until clear_gauntlet_pass()
        is called by the gauntlet runner with a PASS verdict.
        """
        now = current_time()["utc_iso"]
        self._quarantine[child.agent_id] = QuarantineRecord(
            agent_id=child.agent_id,
            parent_id=parent_id,
            quarantined_at=now,
        )

    def _release_quarantined(self) -> List:
        """Return agents from quarantine whose gauntlet has passed.

        Released agents are removed from the quarantine dict.
        """
        released = []
        to_remove = []
        for agent_id, rec in self._quarantine.items():
            if rec.gauntlet_passed:
                # Find the actual agent object — it was created in _spawn_child
                # but never added to _active_agents, so we reconstruct it from lineage
                agent = self._find_quarantined_agent(agent_id)
                if agent is not None:
                    to_remove.append(agent_id)
                    released.append(agent)
        for agent_id in to_remove:
            del self._quarantine[agent_id]
        return released

    def _find_quarantined_agent(self, agent_id: str):
        """Attempt to locate a quarantined agent object.

        Spawned children are stored in _quarantine_agents keyed by agent_id
        so they can be released without re-instantiation.
        """
        return self._quarantine_agents.get(agent_id)

    def _find_agent(self, agent_id: str):
        for agent in self._active_agents:
            if agent.agent_id == agent_id:
                return agent
        return None

    def _store_quarantined_agent(self, agent_id: str, agent_obj) -> None:
        """Store agent object for later retrieval when released from quarantine."""
        self._quarantine_agents[agent_id] = agent_obj


_spawner: SwarmSpawner | None = None
_spawner_lock = threading.Lock()


def get_spawner() -> SwarmSpawner:
    """Get or create global swarm spawner."""
    global _spawner
    if _spawner is None:
        with _spawner_lock:
            if _spawner is None:
                from swarm.performance import SwarmPerformanceLedger
                ledger = SwarmPerformanceLedger()
                _spawner = SwarmSpawner(ledger)
    return _spawner
