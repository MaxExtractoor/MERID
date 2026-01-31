"""
Agent pattern playbook for exponential growth layer.

Provides curated archetypes and reusable templates that can be referenced by
curriculum learning, self-evolution loop, and swarm orchestrators when spinning
up new roles. Patterns capture historical performance, telemetry signatures,
and governance notes so that growth decisions are grounded in evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import logging
import uuid


logger = logging.getLogger(__name__)


@dataclass
class AgentPattern:
    """Reusable agent blueprint backed by empirical results."""

    pattern_id: str
    name: str
    archetype: str
    description: str
    strengths: List[str]
    weaknesses: List[str]
    telemetry_signatures: Dict[str, float]
    success_metrics: Dict[str, float]
    governance_notes: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_used: Optional[datetime] = None
    tags: List[str] = field(default_factory=list)

    def record_use(self, metrics_delta: Dict[str, float], notes: Optional[str] = None) -> None:
        self.last_used = datetime.utcnow()
        for key, delta in metrics_delta.items():
            self.success_metrics[key] = self.success_metrics.get(key, 0.0) + delta
        if notes:
            self.governance_notes.append(notes)


class AgentPatternLibrary:
    """Central registry of vetted agent archetypes."""

    def __init__(self) -> None:
        self._patterns: Dict[str, AgentPattern] = {}

    def register_pattern(
        self,
        name: str,
        archetype: str,
        description: str,
        strengths: List[str],
        weaknesses: List[str],
        telemetry_signatures: Optional[Dict[str, float]] = None,
        success_metrics: Optional[Dict[str, float]] = None,
        tags: Optional[List[str]] = None,
    ) -> AgentPattern:
        pattern_id = uuid.uuid4().hex[:12]
        pattern = AgentPattern(
            pattern_id=pattern_id,
            name=name,
            archetype=archetype,
            description=description,
            strengths=strengths,
            weaknesses=weaknesses,
            telemetry_signatures=telemetry_signatures or {},
            success_metrics=success_metrics or {},
            tags=tags or [],
        )
        self._patterns[pattern_id] = pattern
        logger.info("Registered agent pattern %s (%s)", pattern_id, name)
        return pattern

    def get_pattern(self, pattern_id: str) -> Optional[AgentPattern]:
        return self._patterns.get(pattern_id)

    def list_patterns(self, tag: Optional[str] = None, archetype: Optional[str] = None) -> List[AgentPattern]:
        patterns = list(self._patterns.values())
        if tag:
            patterns = [p for p in patterns if tag in p.tags]
        if archetype:
            patterns = [p for p in patterns if p.archetype == archetype]
        return sorted(patterns, key=lambda p: p.created_at, reverse=True)

    def suggest_patterns(
        self,
        capability: str,
        min_sharpe: float = 1.0,
        telemetry_window: Optional[Tuple[str, float]] = None,
    ) -> List[AgentPattern]:
        """
        Recommend patterns for a capability.

        Args:
            capability: Tag describing requested behavior (e.g., "latency", "governance").
            min_sharpe: Minimum historical sharpe/score requirement.
            telemetry_window: Optional tuple of (metric, minimum_value) to ensure telemetry match.
        """
        candidates = [
            p for p in self._patterns.values()
            if capability in p.tags and p.success_metrics.get("sharpe_ratio", 0) >= min_sharpe
        ]
        if telemetry_window:
            metric, threshold = telemetry_window
            candidates = [
                p for p in candidates
                if p.telemetry_signatures.get(metric, 0) >= threshold
            ]
        return sorted(candidates, key=lambda p: p.success_metrics.get("sharpe_ratio", 0), reverse=True)

    def get_playbook(self) -> Dict[str, List[Dict[str, object]]]:
        """Structured view of archetypes for dashboards."""
        playbook: Dict[str, List[Dict[str, object]]] = {}
        for pattern in self._patterns.values():
            playbook.setdefault(pattern.archetype, []).append(
                {
                    "pattern_id": pattern.pattern_id,
                    "name": pattern.name,
                    "strengths": pattern.strengths,
                    "weaknesses": pattern.weaknesses,
                    "tags": pattern.tags,
                    "sharpe_ratio": pattern.success_metrics.get("sharpe_ratio"),
                    "last_used": pattern.last_used.isoformat() if pattern.last_used else None,
                }
            )
        return playbook

    def record_outcome(
        self,
        pattern_id: str,
        metrics_delta: Dict[str, float],
        notes: Optional[str] = None,
    ) -> None:
        pattern = self._patterns.get(pattern_id)
        if not pattern:
            raise KeyError(f"Pattern '{pattern_id}' not found")
        pattern.record_use(metrics_delta, notes)
        logger.debug("Recorded outcome for pattern %s delta=%s", pattern_id, metrics_delta)


_agent_pattern_library: Optional[AgentPatternLibrary] = None


def get_agent_pattern_library() -> AgentPatternLibrary:
    global _agent_pattern_library
    if _agent_pattern_library is None:
        _agent_pattern_library = AgentPatternLibrary()
    return _agent_pattern_library
