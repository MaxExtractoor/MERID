"""
Reflection Layer for Agent Self-Learning and Consequence Tracking.

Agents reflect on outcomes of their decisions, store learnings in memory,
and adjust future behavior based on historical performance.
"""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.time_authority import current_time
from utils.logger import get_logger

logger = get_logger("agents.reflection")

REFLECTION_PATH = Path("logs/agent_reflections.json")
REFLECTION_PATH.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class Reflection:
    """Single reflection entry capturing agent decision and outcome."""
    agent_id: str
    energy_id: str
    decision: str  # vote: accept/reject/abstain
    confidence: float
    reasoning: str
    outcome: Optional[str]  # validated/invalidated/pending
    reality_gap: Optional[float]  # difference between prediction and reality
    timestamp: str
    learning: Optional[str]  # what the agent learned from this
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ReflectionLayer:
    """
    Perpetual self-learning system for agents.
    
    Tracks:
    - Decision history per agent
    - Outcome validation (correct/incorrect predictions)
    - Pattern recognition (what works, what doesn't)
    - Adaptive confidence calibration
    """
    
    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self._path = storage_path or REFLECTION_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._reflections: List[Reflection] = []
        self._agent_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "total_decisions": 0,
            "correct_predictions": 0,
            "incorrect_predictions": 0,
            "avg_confidence": 0.0,
            "avg_reality_gap": 0.0,
            "learnings": []
        })
        self._lock = threading.Lock()
        self._load()
    
    def record_decision(
        self,
        agent_id: str,
        energy_id: str,
        decision: str,
        confidence: float,
        reasoning: str
    ) -> None:
        """Record agent decision for future reflection."""
        reflection = Reflection(
            agent_id=agent_id,
            energy_id=energy_id,
            decision=decision,
            confidence=confidence,
            reasoning=reasoning[:500],  # Truncate for storage
            outcome=None,
            reality_gap=None,
            timestamp=current_time()["utc_iso"],
            learning=None
        )
        
        with self._lock:
            self._reflections.append(reflection)
            self._agent_stats[agent_id]["total_decisions"] += 1
            self._persist()
        
        logger.debug(
            "Recorded decision for %s on energy %s: %s (%.2f confidence)",
            agent_id, energy_id, decision, confidence
        )
    
    def record_outcome(
        self,
        energy_id: str,
        validated: bool,
        reality_gap: Optional[float] = None
    ) -> None:
        """Update reflections with actual outcome after validation."""
        outcome_str = "validated" if validated else "invalidated"
        
        with self._lock:
            for reflection in self._reflections:
                if reflection.energy_id == energy_id and reflection.outcome is None:
                    reflection.outcome = outcome_str
                    reflection.reality_gap = reality_gap
                    
                    # Generate learning based on outcome
                    learning = self._generate_learning(reflection, validated, reality_gap)
                    reflection.learning = learning
                    
                    # Update agent stats
                    agent_id = reflection.agent_id
                    if validated:
                        self._agent_stats[agent_id]["correct_predictions"] += 1
                    else:
                        self._agent_stats[agent_id]["incorrect_predictions"] += 1
                    
                    if reality_gap is not None:
                        # Update running average of reality gap
                        stats = self._agent_stats[agent_id]
                        current_avg = stats.get("avg_reality_gap", 0.0)
                        total = stats["total_decisions"]
                        stats["avg_reality_gap"] = (current_avg * (total - 1) + reality_gap) / total
                    
                    if learning:
                        self._agent_stats[agent_id]["learnings"].append({
                            "timestamp": reflection.timestamp,
                            "learning": learning
                        })
            
            self._persist()
        
        logger.info(
            "Recorded outcome for energy %s: %s (gap: %s)",
            energy_id, outcome_str, reality_gap
        )
    
    def _generate_learning(
        self,
        reflection: Reflection,
        validated: bool,
        reality_gap: Optional[float]
    ) -> str:
        """Generate learning insight from decision outcome."""
        if validated:
            if reflection.confidence > 0.8:
                return "High confidence validated - pattern recognition strong"
            elif reflection.confidence < 0.5:
                return "Low confidence but correct - increase confidence threshold"
            else:
                return "Moderate confidence validated - maintain calibration"
        else:
            if reflection.confidence > 0.8:
                return "High confidence invalidated - overconfidence detected, recalibrate"
            elif reality_gap and reality_gap > 0.1:
                return f"Large reality gap ({reality_gap:.2%}) - improve signal quality"
            else:
                return "Prediction invalidated - review reasoning patterns"
    
    def get_agent_context(self, agent_id: str, limit: int = 10) -> str:
        """
        Get reflection context for agent to include in prompts.
        
        Returns recent learnings and performance stats to inform future decisions.
        """
        with self._lock:
            stats = self._agent_stats.get(agent_id, {})
            if not stats or stats.get("total_decisions", 0) == 0:
                return ""
            
            total = stats["total_decisions"]
            correct = stats.get("correct_predictions", 0)
            accuracy = (correct / total * 100) if total > 0 else 0
            
            recent_learnings = stats.get("learnings", [])[-limit:]
            
            context_parts = [
                f"Your Performance: {accuracy:.1f}% accuracy ({correct}/{total} correct)",
                f"Avg Reality Gap: {stats.get('avg_reality_gap', 0):.2%}"
            ]
            
            if recent_learnings:
                context_parts.append("\nRecent Learnings:")
                for item in recent_learnings[-3:]:  # Last 3 learnings
                    context_parts.append(f"- {item['learning']}")
            
            return "\n".join(context_parts)
    
    def get_agent_stats(self, agent_id: str) -> Dict[str, Any]:
        """Get complete stats for an agent."""
        with self._lock:
            return dict(self._agent_stats.get(agent_id, {}))
    
    def get_all_reflections(self, agent_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get reflection history, optionally filtered by agent."""
        with self._lock:
            reflections = self._reflections
            if agent_id:
                reflections = [r for r in reflections if r.agent_id == agent_id]
            return [r.to_dict() for r in reflections[-limit:]]
    
    def _persist(self) -> None:
        """Save reflections to disk."""
        data = {
            "reflections": [r.to_dict() for r in self._reflections],
            "agent_stats": dict(self._agent_stats)
        }
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    
    def _load(self) -> None:
        """Load reflections from disk."""
        if not self._path.exists():
            return
        
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            
            # Load reflections
            for item in data.get("reflections", []):
                self._reflections.append(Reflection(**item))
            
            # Load agent stats
            for agent_id, stats in data.get("agent_stats", {}).items():
                self._agent_stats[agent_id] = stats
            
            logger.info(
                "Loaded %d reflections for %d agents",
                len(self._reflections),
                len(self._agent_stats)
            )
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Failed to load reflections: %s", exc)


# Global singleton
reflection_layer = ReflectionLayer()
