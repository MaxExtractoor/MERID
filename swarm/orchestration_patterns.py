"""
Canonical orchestration pattern library for MERID swarm deployments.

Provides reusable templates describing agent topologies, comms flows, and safety
checkpoints. Designed so Phase 9 deployments can snap to vetted blueprints
instead of bespoke orchestration each time.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from utils.logger import get_logger


logger = get_logger(__name__)


@dataclass
class OrchestrationPattern:
    pattern_id: str
    name: str
    description: str
    topology: Dict[str, List[str]]
    communication_channels: List[str]
    safety_gates: List[str]
    recommended_use_cases: List[str] = field(default_factory=list)


class OrchestrationPatternLibrary:
    def __init__(self) -> None:
        self._patterns: Dict[str, OrchestrationPattern] = {}
        self._seed_defaults()

    def _seed_defaults(self) -> None:
        self.register_pattern(
            OrchestrationPattern(
                pattern_id="guardian_handoff",
                name="Guardian Assisted Handoff",
                description="Governor agent validates intents before execution agents act",
                topology={"governor": ["strategy"], "strategy": ["execution"], "execution": []},
                communication_channels=["intent_bus", "execution_queue"],
                safety_gates=["multi_agent_risk_controls", "capability_gating"],
                recommended_use_cases=["high_notional", "regulated_assets"],
            )
        )

    def register_pattern(self, pattern: OrchestrationPattern) -> None:
        self._patterns[pattern.pattern_id] = pattern
        logger.info("Registered orchestration pattern %s", pattern.pattern_id)

    def get_pattern(self, pattern_id: str) -> Optional[OrchestrationPattern]:
        return self._patterns.get(pattern_id)

    def list_patterns(self) -> List[OrchestrationPattern]:
        return list(self._patterns.values())


_orchestration_patterns: Optional[OrchestrationPatternLibrary] = None
_orchestration_patterns_lock = threading.Lock()


def get_orchestration_pattern_library() -> OrchestrationPatternLibrary:
    global _orchestration_patterns
    if _orchestration_patterns is None:
        with _orchestration_patterns_lock:
            if _orchestration_patterns is None:
                _orchestration_patterns = OrchestrationPatternLibrary()
    return _orchestration_patterns
