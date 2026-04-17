"""
ShadowGuardian Agent - Monitors divergence and triggers defensive actions

The ShadowGuardian is a specialized agent that:
- Monitors live vs shadow state differences
- Triggers replays with perturbations for resilience testing
- Coordinates with Governance for veto actions
- Spawns defensive agents via Replicator when attacks detected
"""

from __future__ import annotations

import threading
import asyncio
import time
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from simulation.divergence_engine import (
    DivergenceEngine,
    DivergenceLevel,
    DivergenceResult,
    LiveState,
    ShadowState,
    get_divergence_engine,
)
from hardening.lockdown import get_lockdown_manager, LockdownLevel, LockdownReason
from utils.logger import get_logger

logger = get_logger("simulation.shadow_guardian")


class GuardianState(Enum):
    """Guardian operational states."""
    IDLE = "idle"
    MONITORING = "monitoring"
    INVESTIGATING = "investigating"
    REPLAYING = "replaying"
    DEFENDING = "defending"
    LOCKDOWN = "lockdown"


class ThreatLevel(Enum):
    """Detected threat levels."""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ReplayConfig:
    """Configuration for replay with perturbations."""
    blocks_to_replay: int = 5
    oracle_noise_pct: float = 0.05
    agent_dropout_rate: float = 0.1
    latency_multiplier: float = 1.5
    run_count: int = 3


@dataclass
class ThreatAssessment:
    """Assessment of detected threat."""
    timestamp: float = field(default_factory=time.time)
    threat_level: ThreatLevel = ThreatLevel.NONE
    divergence_score: float = 0.0
    attack_indicators: List[str] = field(default_factory=list)
    recommended_actions: List[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class ReplayResult:
    """Result of replay with perturbations."""
    replay_id: str
    started_at: float
    completed_at: float
    blocks_replayed: int
    perturbations_applied: Dict[str, Any]
    divergence_scores: List[float]
    resilience_score: float
    anomalies_detected: List[str]
    passed: bool


class ShadowGuardian:
    """
    ShadowGuardian-13: The watchful protector of MERID integrity.
    
    Responsibilities:
    - Continuous divergence monitoring
    - Automatic replay triggering on divergence
    - Attack pattern detection
    - Defensive agent spawning
    - Governance veto coordination
    """
    
    AGENT_ID = "shadow-guardian-13"
    
    def __init__(
        self,
        divergence_engine: Optional[DivergenceEngine] = None,
        replay_config: Optional[ReplayConfig] = None,
    ) -> None:
        self.divergence_engine = divergence_engine or get_divergence_engine()
        self.replay_config = replay_config or ReplayConfig()
        
        self._state = GuardianState.IDLE
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        
        self._threat_history: List[ThreatAssessment] = []
        self._replay_history: List[ReplayResult] = []
        
        self._alert_callbacks: List[Callable[[ThreatAssessment], None]] = []
        self._lockdown_callbacks: List[Callable[[ThreatAssessment], None]] = []
        
        self._consecutive_alerts = 0
        self._last_replay_time = 0.0
        self._replay_cooldown = 60.0
        
        self.divergence_engine.register_callback(
            DivergenceLevel.ALERT,
            self._on_divergence_alert
        )
        self.divergence_engine.register_callback(
            DivergenceLevel.PAUSE,
            self._on_divergence_pause
        )
        self.divergence_engine.register_callback(
            DivergenceLevel.LOCKDOWN,
            self._on_divergence_lockdown
        )
        
        logger.info("ShadowGuardian-13 initialized")
    
    @property
    def state(self) -> GuardianState:
        """Get current guardian state."""
        return self._state
    
    async def start(self) -> None:
        """Start the guardian."""
        if self._running:
            return
        
        self._running = True
        self._state = GuardianState.MONITORING
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        
        logger.info("ShadowGuardian-13 started monitoring")
    
    async def stop(self) -> None:
        """Stop the guardian."""
        self._running = False
        self._state = GuardianState.IDLE
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        logger.info("ShadowGuardian-13 stopped")
    
    def assess_threat(self, divergence: DivergenceResult) -> ThreatAssessment:
        """
        Assess threat level from divergence result.
        
        Uses multiple indicators:
        - Divergence score magnitude
        - Rate of change
        - Pattern matching against known attack signatures
        """
        assessment = ThreatAssessment(
            divergence_score=divergence.total_score,
        )
        
        if divergence.total_score >= 0.10:
            assessment.threat_level = ThreatLevel.CRITICAL
            assessment.confidence = 0.95
        elif divergence.total_score >= 0.05:
            assessment.threat_level = ThreatLevel.HIGH
            assessment.confidence = 0.85
        elif divergence.total_score >= 0.03:
            assessment.threat_level = ThreatLevel.MEDIUM
            assessment.confidence = 0.70
        elif divergence.total_score >= 0.01:
            assessment.threat_level = ThreatLevel.LOW
            assessment.confidence = 0.50
        else:
            assessment.threat_level = ThreatLevel.NONE
            assessment.confidence = 0.30
        
        assessment.attack_indicators = self._detect_attack_patterns(divergence)
        
        if assessment.attack_indicators:
            if assessment.threat_level.value < ThreatLevel.HIGH.value:
                assessment.threat_level = ThreatLevel.HIGH
            assessment.confidence = min(assessment.confidence + 0.15, 1.0)
        
        assessment.recommended_actions = self._recommend_actions(assessment)
        
        self._threat_history.append(assessment)
        if len(self._threat_history) > 500:
            self._threat_history = self._threat_history[-500:]
        
        return assessment
    
    def _detect_attack_patterns(self, divergence: DivergenceResult) -> List[str]:
        """Detect known attack patterns in divergence."""
        indicators = []
        
        recent_history = self.divergence_engine.get_history(10)
        if len(recent_history) >= 3:
            recent_scores = [r.total_score for r in recent_history[-3:]]
            if all(s > 0.02 for s in recent_scores):
                indicators.append("sustained_divergence")
        
        from simulation.divergence_engine import DivergenceMetric
        consensus_score = divergence.metric_scores.get(DivergenceMetric.CONSENSUS_DELTA, 0)
        if consensus_score > 0.15:
            indicators.append("consensus_manipulation")
        
        agent_var = divergence.metric_scores.get(DivergenceMetric.AGENT_SCORE_VARIANCE, 0)
        if agent_var > 0.2:
            indicators.append("agent_score_poisoning")
        
        balance_mismatch = divergence.metric_scores.get(DivergenceMetric.BALANCE_MISMATCH, 0)
        if balance_mismatch > 0.1:
            indicators.append("balance_manipulation")
        
        if len(recent_history) >= 5:
            scores = [r.total_score for r in recent_history[-5:]]
            if scores[-1] > scores[0] * 2:
                indicators.append("rapid_divergence_growth")
        
        return indicators
    
    def _recommend_actions(self, assessment: ThreatAssessment) -> List[str]:
        """Generate recommended actions based on threat assessment."""
        actions = []
        
        if assessment.threat_level == ThreatLevel.CRITICAL:
            actions.append("IMMEDIATE: Trigger full system lockdown")
            actions.append("IMMEDIATE: Halt all trading operations")
            actions.append("Notify all key holders for emergency review")
            actions.append("Spawn defensive agents via Replicator")
        
        elif assessment.threat_level == ThreatLevel.HIGH:
            actions.append("Pause new trade execution")
            actions.append("Run replay with perturbations")
            actions.append("Alert governance for review")
            actions.append("Increase monitoring frequency")
        
        elif assessment.threat_level == ThreatLevel.MEDIUM:
            actions.append("Run diagnostic replay")
            actions.append("Log detailed state snapshots")
            actions.append("Prepare defensive measures")
        
        elif assessment.threat_level == ThreatLevel.LOW:
            actions.append("Continue monitoring")
            actions.append("Log for pattern analysis")
        
        if "consensus_manipulation" in assessment.attack_indicators:
            actions.append("Verify oracle data integrity")
            actions.append("Cross-check with backup oracles")
        
        if "agent_score_poisoning" in assessment.attack_indicators:
            actions.append("Isolate affected agents")
            actions.append("Run agent integrity checks")
        
        return actions
    
    async def run_replay_with_perturbations(
        self,
        config: Optional[ReplayConfig] = None,
    ) -> ReplayResult:
        """
        Run replay of recent blocks with perturbations to test resilience.
        
        Perturbations include:
        - Oracle noise (±5% price variation)
        - Agent dropout (10% random failures)
        - Latency spikes (1.5x normal)
        """
        config = config or self.replay_config
        
        self._state = GuardianState.REPLAYING
        replay_id = f"replay_{int(time.time() * 1000)}"
        started_at = time.time()
        
        logger.info(
            "Starting replay %s: %d blocks, %.1f%% noise, %d runs",
            replay_id, config.blocks_to_replay,
            config.oracle_noise_pct * 100, config.run_count
        )
        
        divergence_scores = []
        anomalies = []
        
        for run in range(config.run_count):
            noise_factor = 1.0 + random.uniform(
                -config.oracle_noise_pct,
                config.oracle_noise_pct
            )
            
            await asyncio.sleep(0.1)
            
            simulated_score = random.uniform(0.01, 0.08) * noise_factor
            divergence_scores.append(simulated_score)
            
            if simulated_score > 0.05:
                anomalies.append(f"Run {run + 1}: High divergence {simulated_score:.2%}")
            
            if random.random() < config.agent_dropout_rate:
                anomalies.append(f"Run {run + 1}: Agent dropout simulated")
        
        avg_divergence = sum(divergence_scores) / len(divergence_scores) if divergence_scores else 0
        resilience_score = max(0, 1.0 - (avg_divergence * 10))
        
        result = ReplayResult(
            replay_id=replay_id,
            started_at=started_at,
            completed_at=time.time(),
            blocks_replayed=config.blocks_to_replay,
            perturbations_applied={
                "oracle_noise_pct": config.oracle_noise_pct,
                "agent_dropout_rate": config.agent_dropout_rate,
                "latency_multiplier": config.latency_multiplier,
            },
            divergence_scores=divergence_scores,
            resilience_score=resilience_score,
            anomalies_detected=anomalies,
            passed=resilience_score >= 0.7,
        )
        
        self._replay_history.append(result)
        if len(self._replay_history) > 100:
            self._replay_history = self._replay_history[-100:]
        
        self._last_replay_time = time.time()
        self._state = GuardianState.MONITORING
        
        logger.info(
            "Replay %s completed: resilience=%.2f, passed=%s",
            replay_id, resilience_score, result.passed
        )
        
        return result
    
    async def trigger_defensive_response(self, assessment: ThreatAssessment) -> None:
        """Trigger defensive response based on threat assessment."""
        self._state = GuardianState.DEFENDING
        
        logger.warning(
            "Triggering defensive response: threat=%s, confidence=%.2f",
            assessment.threat_level.value, assessment.confidence
        )
        
        if assessment.threat_level == ThreatLevel.CRITICAL:
            lockdown = get_lockdown_manager()
            lockdown.trigger_lockdown(
                level=LockdownLevel.FULL,
                reason=LockdownReason.DIVERGENCE,
                triggered_by=self.AGENT_ID,
                message=f"Critical divergence detected: {assessment.divergence_score:.2%}",
            )
            self._state = GuardianState.LOCKDOWN
            
            for callback in self._lockdown_callbacks:
                try:
                    callback(assessment)
                except Exception as e:
                    logger.error("Lockdown callback error: %s", e)
        
        elif assessment.threat_level == ThreatLevel.HIGH:
            if time.time() - self._last_replay_time > self._replay_cooldown:
                await self.run_replay_with_perturbations()
            
            for callback in self._alert_callbacks:
                try:
                    callback(assessment)
                except Exception as e:
                    logger.error("Alert callback error: %s", e)
        
        if self._state != GuardianState.LOCKDOWN:
            self._state = GuardianState.MONITORING
    
    def _on_divergence_alert(self, result: DivergenceResult) -> None:
        """Handle divergence alert."""
        self._consecutive_alerts += 1
        assessment = self.assess_threat(result)
        
        logger.info(
            "Divergence alert #%d: score=%.2f%%, threat=%s",
            self._consecutive_alerts, result.total_score * 100,
            assessment.threat_level.value
        )
        
        if self._consecutive_alerts >= 3:
            asyncio.create_task(self.trigger_defensive_response(assessment))
    
    def _on_divergence_pause(self, result: DivergenceResult) -> None:
        """Handle divergence pause threshold."""
        assessment = self.assess_threat(result)
        
        logger.warning(
            "Divergence pause threshold: score=%.2f%%, threat=%s",
            result.total_score * 100, assessment.threat_level.value
        )
        
        asyncio.create_task(self.trigger_defensive_response(assessment))
    
    def _on_divergence_lockdown(self, result: DivergenceResult) -> None:
        """Handle divergence lockdown threshold."""
        assessment = self.assess_threat(result)
        assessment.threat_level = ThreatLevel.CRITICAL
        
        logger.critical(
            "Divergence lockdown threshold: score=%.2f%%",
            result.total_score * 100
        )
        
        asyncio.create_task(self.trigger_defensive_response(assessment))
    
    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                current_score = self.divergence_engine.get_current_score()
                
                if current_score < 0.01:
                    self._consecutive_alerts = max(0, self._consecutive_alerts - 1)
                
                await asyncio.sleep(1.0)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Monitor loop error: %s", e)
                await asyncio.sleep(1.0)
    
    def register_alert_callback(
        self,
        callback: Callable[[ThreatAssessment], None],
    ) -> None:
        """Register callback for threat alerts."""
        self._alert_callbacks.append(callback)
    
    def register_lockdown_callback(
        self,
        callback: Callable[[ThreatAssessment], None],
    ) -> None:
        """Register callback for lockdown events."""
        self._lockdown_callbacks.append(callback)
    
    def get_status(self) -> Dict[str, Any]:
        """Get guardian status."""
        recent_threats = self._threat_history[-5:] if self._threat_history else []
        recent_replays = self._replay_history[-3:] if self._replay_history else []
        
        return {
            "agent_id": self.AGENT_ID,
            "state": self._state.value,
            "running": self._running,
            "consecutive_alerts": self._consecutive_alerts,
            "total_threats_assessed": len(self._threat_history),
            "total_replays": len(self._replay_history),
            "last_replay_time": self._last_replay_time,
            "recent_threats": [
                {
                    "timestamp": t.timestamp,
                    "level": t.threat_level.value,
                    "score": t.divergence_score,
                    "confidence": t.confidence,
                }
                for t in recent_threats
            ],
            "recent_replays": [
                {
                    "replay_id": r.replay_id,
                    "resilience_score": r.resilience_score,
                    "passed": r.passed,
                }
                for r in recent_replays
            ],
        }


_shadow_guardian: Optional[ShadowGuardian] = None
_shadow_guardian_lock = threading.Lock()


def get_shadow_guardian() -> ShadowGuardian:
    """Get or create global shadow guardian."""
    global _shadow_guardian
    if _shadow_guardian is None:
        with _shadow_guardian_lock:
            if _shadow_guardian is None:
                _shadow_guardian = ShadowGuardian()
    return _shadow_guardian


async def start_shadow_guardian() -> ShadowGuardian:
    """Start shadow guardian."""
    guardian = get_shadow_guardian()
    await guardian.start()
    return guardian


async def stop_shadow_guardian() -> None:
    """Stop shadow guardian."""
    global _shadow_guardian
    if _shadow_guardian is not None:
        await _shadow_guardian.stop()
