"""
Reflection Layer for Agent Self-Learning and Consequence Tracking.

Agents reflect on outcomes of their decisions, store learnings in memory,
and adjust future behavior based on historical performance.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# PROFILE-GUARD: Skip reflection loading for kalshi_crypto_15m_v2 (sealed 15m stack doesn't need LLM reflection)
_is_15m_crypto = os.getenv("MERID_PROFILE", "") == "kalshi_crypto_15m_v2"

if not _is_15m_crypto:
    from core.time_authority import current_time
    from core.persistence_manager import get_persistence_manager
    from utils.logger import get_logger

    logger = get_logger("agents.reflection")

    REFLECTION_PATH = Path("logs/agent_reflections.json")
    REFLECTION_PATH.parent.mkdir(parents=True, exist_ok=True)
else:
    # Create stub logger for kalshi_crypto_15m_v2 to prevent import errors
    class StubLogger:
        def info(self, *args, **kwargs):
            pass
        def warning(self, *args, **kwargs):
            pass
        def error(self, *args, **kwargs):
            pass
        def debug(self, *args, **kwargs):
            pass
    
    logger = StubLogger()
    REFLECTION_PATH = None


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
    """V1 reflection layer — loads reflections from disk, records decisions."""
    
    def __init__(self, path: Optional[Path] = None) -> None:
        # PROFILE-GUARD: Skip reflection loading for kalshi_crypto_15m_v2 (sealed 15m stack doesn't need LLM reflection)
        if _is_15m_crypto:
            self._path = None
            self._reflections: List[Reflection] = []
            self._agent_stats: Dict[str, Dict[str, int]] = defaultdict(
                lambda: {"total_decisions": 0, "correct_predictions": 0, "incorrect_predictions": 0}
            )
            self._lock = threading.Lock()
            self._loaded = True  # Mark as loaded to prevent background thread
            self._reflection_tick_stats: Dict[str, Dict[str, int]] = defaultdict(
                lambda: {"reads": 0, "writes": 0}
            )
            self._tick_window_start = time.time()
            self._tick_window_seconds = 60
            logger.info("[PROFILE-GUARD] Reflection layer disabled for kalshi_crypto_15m_v2")
            return
        
        self._path = path or Path(REFLECTION_PATH)
        self._reflections: List[Reflection] = []
        self._agent_stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"total_decisions": 0, "correct_predictions": 0, "incorrect_predictions": 0}
        )
        self._lock = threading.Lock()
        self._loaded = False
        
        # INSTRUMENTATION: Tick counter for read/write tracking
        self._reflection_tick_stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"reads": 0, "writes": 0}
        )
        self._tick_window_start = time.time()
        self._tick_window_seconds = 60  # Log every 60 seconds
        
        # Load reflections in a background thread — works whether or not
        # the asyncio event loop is already running at construction time.
        threading.Thread(target=self._bg_load, daemon=True).start()
    
    def _get_new_system(self):
        """Lazy-import the v2 ReflectionSystem to avoid circular imports."""
        try:
            from agents.reflection.integration import get_reflection_system
            return get_reflection_system()
        except Exception:
            return None

    def record_decision(
        self,
        agent_id: str,
        energy_id: str,
        decision: str,
        confidence: float,
        reasoning: str
    ) -> None:
        """Record agent decision for future reflection."""
        # INSTRUMENTATION: Track write tick
        self._reflection_tick_stats[agent_id]["writes"] += 1
        self._log_tick_stats_if_needed()
        
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
        
        # Forward to new ReflectionSystem so v2 storage stays in sync
        new_sys = self._get_new_system()
        if new_sys:
            try:
                new_sys.record_decision(
                    agent_id=agent_id,
                    energy_id=energy_id,
                    decision=decision,
                    confidence=confidence,
                    reasoning=reasoning[:500],
                )
            except Exception as exc:
                logger.debug("v2 bridge record_decision failed: %s", exc)
        
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
        
        # Forward outcome to new ReflectionSystem
        new_sys = self._get_new_system()
        if new_sys:
            try:
                price_change = (reality_gap or 0.0) * (1 if validated else -1)
                # Find matching reflection IDs in v2 and validate them
                v2_refs = new_sys.core.get_energy_reflections(energy_id)
                for ref in v2_refs:
                    if ref.outcome is None:
                        new_sys.validate_market_outcome(
                            reflection_id=ref.reflection_id,
                            actual_price_change=price_change,
                        )
            except Exception as exc:
                logger.debug("v2 bridge record_outcome failed: %s", exc)
        
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
        # INSTRUMENTATION: Track read tick
        self._reflection_tick_stats[agent_id]["reads"] += 1
        self._log_tick_stats_if_needed()
        
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
        # INSTRUMENTATION: Track read tick
        self._reflection_tick_stats[agent_id]["reads"] += 1
        self._log_tick_stats_if_needed()
        
        with self._lock:
            return dict(self._agent_stats.get(agent_id, {}))
    
    def get_all_reflections(self, agent_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get reflection history, optionally filtered by agent."""
        with self._lock:
            reflections = self._reflections
            if agent_id:
                reflections = [r for r in reflections if r.agent_id == agent_id]
            return [r.to_dict() for r in reflections[-limit:]]
    
    def _log_tick_stats_if_needed(self) -> None:
        """Log tick stats if window has elapsed.
        
        Logs read/write counts per agent type for the time window.
        This helps identify which agents are using reflection heavily.
        """
        import os
        profile = os.environ.get('MERID_PROFILE', '')
        
        # Only log for 15m crypto profiles
        if profile not in ('kalshi_crypto_15m', 'kalshi_crypto_15m_v2'):
            return
        
        now = time.time()
        window_elapsed = now - self._tick_window_start
        
        if window_elapsed >= self._tick_window_seconds:
            # Log stats for each agent type
            for agent_id, stats in self._reflection_tick_stats.items():
                reads = stats.get("reads", 0)
                writes = stats.get("writes", 0)
                
                if reads > 0 or writes > 0:
                    logger.info(
                        "[REFLECTION-TICK] agent_type=%s classification=research_only "
                        "reads=%d writes=%d in last_window=%.0f sec profile=%s",
                        agent_id, reads, writes, window_elapsed, profile
                    )
            
            # Reset window
            self._tick_window_start = now
            self._reflection_tick_stats.clear()
    
    def flush(self) -> None:
        """Force immediate persistence of all reflections."""
        with self._lock:
            data = {
                "reflections": [r.to_dict() for r in self._reflections],
                "agent_stats": dict(self._agent_stats)
            }
            persist = get_persistence_manager()
            persist.write_json(self._path, data, immediate=True)
            logger.info("Flushed %d reflections to disk", len(self._reflections))
    
    def _persist(self) -> None:
        """Save reflections to disk using batched persistence."""
        data = {
            "reflections": [r.to_dict() for r in self._reflections],
            "agent_stats": dict(self._agent_stats)
        }
        # Use persistence manager for batched writes
        persist = get_persistence_manager()
        persist.write_json(self._path, data, immediate=False)
    
    async def _load_async(self) -> None:
        """Async wrapper to run _load in thread pool - prevents blocking event loop."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._load_sync)
        self._loaded = True
    
    def _bg_load(self) -> None:
        """Background-thread entry point: load from disk then mark ready."""
        try:
            self._load_sync()
        except Exception as exc:
            logger.warning("ReflectionLayer background load failed: %s", exc)
        finally:
            self._loaded = True

    def _load_sync(self) -> None:
        """Load reflections from disk — runs in thread pool to avoid blocking event loop."""
        # INSTRUMENTATION: Track load timing
        import time
        load_start_ts = time.time()
        
        v2_path = self._path.parent / "agent_reflections_v2.json"
        load_path = v2_path if v2_path.exists() else self._path
        
        if not load_path.exists():
            logger.info("No reflection storage found, starting fresh")
            return
        
        try:
            data = json.loads(load_path.read_text(encoding="utf-8"))
            
            # v2 format nests under 'reflections' with different schema
            raw_refs = data.get("reflections", [])
            
            # Process in batches to avoid blocking for too long even in thread
            batch_size = 100
            for i in range(0, len(raw_refs), batch_size):
                batch = raw_refs[i:i + batch_size]
                for item in batch:
                    try:
                        with self._lock:
                            self._reflections.append(Reflection(
                                agent_id=item.get("agent_id", "unknown"),
                                energy_id=item.get("energy_id", ""),
                                decision=item.get("decision", "abstain"),
                                confidence=float(item.get("confidence", 0.0)),
                                reasoning=item.get("reasoning", "")[:500],
                                outcome=item.get("outcome"),
                                reality_gap=item.get("reality_gap"),
                                timestamp=item.get("timestamp", ""),
                                learning=item.get("learning_insight") or item.get("learning"),
                            ))
                    except Exception:
                        continue
            
            # Load agent stats (v1 format) or rebuild from reflections
            v1_stats = data.get("agent_stats", {})
            if v1_stats:
                with self._lock:
                    for agent_id, stats in v1_stats.items():
                        self._agent_stats[agent_id] = stats
            else:
                # Rebuild stats from loaded reflections
                with self._lock:
                    for ref in self._reflections:
                        self._agent_stats[ref.agent_id]["total_decisions"] += 1
                        if ref.outcome == "validated":
                            self._agent_stats[ref.agent_id]["correct_predictions"] += 1
                        elif ref.outcome == "invalidated":
                            self._agent_stats[ref.agent_id]["incorrect_predictions"] += 1
            
            source = "v2" if load_path == v2_path else "v1"
            logger.info(
                "Loaded %d reflections for %d agents (source: %s, deferred load)",
                len(self._reflections),
                len(self._agent_stats),
                source,
            )
            
            # INSTRUMENTATION: Log timing and sample of loaded agents
            duration_ms = (time.time() - load_start_ts) * 1000
            logger.info(
                "[REFLECTION-TRACE] load_complete profile=%s source=%s "
                "reflection_count=%d agent_count=%d duration_ms=%.2f",
                os.environ.get('MERID_PROFILE', 'unknown'),
                source,
                len(self._reflections),
                len(self._agent_stats),
                duration_ms
            )
            
            # Sample first 10 agent IDs for visibility
            sampled_agents = list(self._agent_stats.keys())[:10]
            logger.info(
                "[REFLECTION-TRACE] sampled_agents=%s total_sampled=%d of %d",
                sampled_agents,
                len(sampled_agents),
                len(self._agent_stats)
            )
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Failed to load reflections: %s", exc)

    def _load(self) -> None:
        """Deprecated: synchronous load - kept for backwards compatibility."""
        pass


# Global singleton
reflection_layer = ReflectionLayer()
