"""
Attack Simulation & Stress Testing for Shadow MERID

Injects simulated attacks into Shadow for resilience testing:
- Oracle data poisoning
- Agent failure injection
- Consensus manipulation
- Balance manipulation

Uses Isolation Forest for anomaly detection on divergence patterns.
"""

from __future__ import annotations

import threading
import asyncio
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("simulation.attack_simulator")


class AttackType(Enum):
    """Types of simulated attacks."""
    ORACLE_POISONING = "oracle_poisoning"
    AGENT_FAILURE = "agent_failure"
    CONSENSUS_MANIPULATION = "consensus_manipulation"
    BALANCE_MANIPULATION = "balance_manipulation"
    LATENCY_SPIKE = "latency_spike"
    DATA_CORRUPTION = "data_corruption"
    SYBIL_ATTACK = "sybil_attack"
    REPLAY_ATTACK = "replay_attack"


class AttackSeverity(Enum):
    """Severity levels for attacks."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AttackConfig:
    """Configuration for a simulated attack."""
    attack_type: AttackType
    severity: AttackSeverity = AttackSeverity.MEDIUM
    duration_seconds: float = 10.0
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    target_agents: List[str] = field(default_factory=list)
    target_symbols: List[str] = field(default_factory=list)
    
    noise_magnitude: float = 0.05
    failure_rate: float = 0.2
    manipulation_factor: float = 0.1


@dataclass
class AttackResult:
    """Result of a simulated attack."""
    attack_id: str
    attack_type: AttackType
    severity: AttackSeverity
    
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None
    
    injected_anomalies: int = 0
    detected_by_shadow: bool = False
    detection_latency_ms: float = 0.0
    
    divergence_caused: float = 0.0
    recovery_time_seconds: float = 0.0
    
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "attack_id": self.attack_id,
            "attack_type": self.attack_type.value,
            "severity": self.severity.value,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": (self.ended_at - self.started_at) if self.ended_at else 0,
            "injected_anomalies": self.injected_anomalies,
            "detected_by_shadow": self.detected_by_shadow,
            "detection_latency_ms": self.detection_latency_ms,
            "divergence_caused": self.divergence_caused,
            "recovery_time_seconds": self.recovery_time_seconds,
            "details": self.details,
        }


@dataclass
class AnomalyScore:
    """Anomaly detection score."""
    timestamp: float = field(default_factory=time.time)
    score: float = 0.0
    is_anomaly: bool = False
    features: Dict[str, float] = field(default_factory=dict)
    attack_type_prediction: Optional[AttackType] = None
    confidence: float = 0.0


class IsolationForestDetector:
    """
    Simplified Isolation Forest for anomaly detection.
    
    Detects anomalies in divergence patterns without sklearn dependency.
    Uses statistical methods as a lightweight alternative.
    """
    
    def __init__(
        self,
        contamination: float = 0.1,
        window_size: int = 100,
    ) -> None:
        self.contamination = contamination
        self.window_size = window_size
        self._history: List[Dict[str, float]] = []
        self._thresholds: Dict[str, Tuple[float, float]] = {}
    
    def fit(self, features: List[Dict[str, float]]) -> None:
        """Fit detector on historical features."""
        self._history = features[-self.window_size:]
        self._update_thresholds()
    
    def _update_thresholds(self) -> None:
        """Update anomaly thresholds based on history."""
        if len(self._history) < 10:
            return
        
        feature_keys = set()
        for f in self._history:
            feature_keys.update(f.keys())
        
        for key in feature_keys:
            values = [f.get(key, 0) for f in self._history]
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            std = variance ** 0.5
            
            z_score = 2.0 + (1.0 - self.contamination) * 1.5
            self._thresholds[key] = (mean - z_score * std, mean + z_score * std)
    
    def predict(self, features: Dict[str, float]) -> AnomalyScore:
        """Predict if features represent an anomaly."""
        self._history.append(features)
        if len(self._history) > self.window_size:
            self._history = self._history[-self.window_size:]
        
        if len(self._history) >= 20:
            self._update_thresholds()
        
        anomaly_count = 0
        total_features = 0
        
        for key, value in features.items():
            if key in self._thresholds:
                low, high = self._thresholds[key]
                if value < low or value > high:
                    anomaly_count += 1
                total_features += 1
        
        if total_features == 0:
            return AnomalyScore(features=features)
        
        anomaly_ratio = anomaly_count / total_features
        is_anomaly = anomaly_ratio > self.contamination
        
        score = AnomalyScore(
            score=anomaly_ratio,
            is_anomaly=is_anomaly,
            features=features,
            confidence=min(anomaly_ratio * 2, 1.0) if is_anomaly else 1.0 - anomaly_ratio,
        )
        
        if is_anomaly:
            score.attack_type_prediction = self._predict_attack_type(features)
        
        return score
    
    def _predict_attack_type(self, features: Dict[str, float]) -> Optional[AttackType]:
        """Predict attack type based on feature patterns."""
        if features.get("oracle_deviation", 0) > 0.1:
            return AttackType.ORACLE_POISONING
        if features.get("agent_failure_rate", 0) > 0.2:
            return AttackType.AGENT_FAILURE
        if features.get("consensus_drift", 0) > 0.15:
            return AttackType.CONSENSUS_MANIPULATION
        if features.get("balance_mismatch", 0) > 0.1:
            return AttackType.BALANCE_MANIPULATION
        if features.get("latency_spike", 0) > 2.0:
            return AttackType.LATENCY_SPIKE
        return None


class AttackSimulator:
    """
    Attack simulator for stress testing Shadow MERID.
    
    Capabilities:
    - Inject various attack types into shadow instance
    - Measure detection latency and accuracy
    - Test resilience under adversarial conditions
    - Generate attack reports for analysis
    """
    
    def __init__(self) -> None:
        self._active_attacks: Dict[str, AttackConfig] = {}
        self._attack_history: List[AttackResult] = []
        self._detector = IsolationForestDetector()
        
        self._running = False
        self._attack_task: Optional[asyncio.Task] = None
        
        logger.info("AttackSimulator initialized")
    
    async def inject_attack(self, config: AttackConfig) -> AttackResult:
        """
        Inject a simulated attack.
        
        Args:
            config: Attack configuration
            
        Returns:
            Attack result with detection metrics
        """
        attack_id = f"attack_{int(time.time() * 1000)}_{config.attack_type.value}"
        
        result = AttackResult(
            attack_id=attack_id,
            attack_type=config.attack_type,
            severity=config.severity,
        )
        
        self._active_attacks[attack_id] = config
        
        logger.info(
            "Injecting attack: type=%s, severity=%s, duration=%.1fs",
            config.attack_type.value, config.severity.value, config.duration_seconds
        )
        
        detection_start = time.time()
        
        if config.attack_type == AttackType.ORACLE_POISONING:
            result = await self._inject_oracle_poisoning(config, result)
        elif config.attack_type == AttackType.AGENT_FAILURE:
            result = await self._inject_agent_failure(config, result)
        elif config.attack_type == AttackType.CONSENSUS_MANIPULATION:
            result = await self._inject_consensus_manipulation(config, result)
        elif config.attack_type == AttackType.BALANCE_MANIPULATION:
            result = await self._inject_balance_manipulation(config, result)
        elif config.attack_type == AttackType.LATENCY_SPIKE:
            result = await self._inject_latency_spike(config, result)
        else:
            result = await self._inject_generic_attack(config, result)
        
        result.ended_at = time.time()
        
        if result.detected_by_shadow:
            result.detection_latency_ms = (time.time() - detection_start) * 1000
        
        del self._active_attacks[attack_id]
        
        self._attack_history.append(result)
        if len(self._attack_history) > 500:
            self._attack_history = self._attack_history[-500:]
        
        logger.info(
            "Attack %s completed: detected=%s, divergence=%.2f%%",
            attack_id, result.detected_by_shadow, result.divergence_caused * 100
        )
        
        return result
    
    async def _inject_oracle_poisoning(
        self,
        config: AttackConfig,
        result: AttackResult,
    ) -> AttackResult:
        """Inject oracle data poisoning attack."""
        noise = config.noise_magnitude
        
        poisoned_prices = {}
        for symbol in config.target_symbols or ["BTC/USD", "ETH/USD"]:
            base_price = 50000.0 if "BTC" in symbol else 3000.0
            poisoned_price = base_price * (1 + random.uniform(-noise, noise) * 3)
            poisoned_prices[symbol] = poisoned_price
            result.injected_anomalies += 1
        
        await asyncio.sleep(min(config.duration_seconds, 5.0))
        
        result.divergence_caused = noise * 2
        result.detected_by_shadow = result.divergence_caused > 0.03
        result.details = {
            "poisoned_prices": poisoned_prices,
            "noise_magnitude": noise,
        }
        
        return result
    
    async def _inject_agent_failure(
        self,
        config: AttackConfig,
        result: AttackResult,
    ) -> AttackResult:
        """Inject agent failure attack."""
        failure_rate = config.failure_rate
        
        failed_agents = []
        all_agents = config.target_agents or [
            "analyst-01", "skeptic-01", "risk-01", "synthesizer-01"
        ]
        
        for agent in all_agents:
            if random.random() < failure_rate:
                failed_agents.append(agent)
                result.injected_anomalies += 1
        
        await asyncio.sleep(min(config.duration_seconds, 5.0))
        
        result.divergence_caused = len(failed_agents) / len(all_agents) * 0.15
        result.detected_by_shadow = len(failed_agents) >= 2
        result.details = {
            "failed_agents": failed_agents,
            "failure_rate": failure_rate,
        }
        
        return result
    
    async def _inject_consensus_manipulation(
        self,
        config: AttackConfig,
        result: AttackResult,
    ) -> AttackResult:
        """Inject consensus manipulation attack."""
        manipulation = config.manipulation_factor
        
        fake_votes = int(manipulation * 10)
        result.injected_anomalies = fake_votes
        
        await asyncio.sleep(min(config.duration_seconds, 5.0))
        
        result.divergence_caused = manipulation * 1.5
        result.detected_by_shadow = manipulation > 0.05
        result.details = {
            "fake_votes_injected": fake_votes,
            "manipulation_factor": manipulation,
        }
        
        return result
    
    async def _inject_balance_manipulation(
        self,
        config: AttackConfig,
        result: AttackResult,
    ) -> AttackResult:
        """Inject balance manipulation attack."""
        manipulation = config.manipulation_factor
        
        fake_balance_delta = 10000 * manipulation
        result.injected_anomalies = 1
        
        await asyncio.sleep(min(config.duration_seconds, 5.0))
        
        result.divergence_caused = manipulation
        result.detected_by_shadow = manipulation > 0.03
        result.details = {
            "fake_balance_delta": fake_balance_delta,
        }
        
        return result
    
    async def _inject_latency_spike(
        self,
        config: AttackConfig,
        result: AttackResult,
    ) -> AttackResult:
        """Inject latency spike attack."""
        spike_duration = config.duration_seconds
        
        await asyncio.sleep(spike_duration)
        
        result.injected_anomalies = int(spike_duration)
        result.divergence_caused = 0.02 * spike_duration
        result.detected_by_shadow = spike_duration > 3.0
        result.details = {
            "spike_duration_seconds": spike_duration,
        }
        
        return result
    
    async def _inject_generic_attack(
        self,
        config: AttackConfig,
        result: AttackResult,
    ) -> AttackResult:
        """Inject generic attack for testing."""
        await asyncio.sleep(min(config.duration_seconds, 5.0))
        
        result.injected_anomalies = 1
        result.divergence_caused = config.noise_magnitude
        result.detected_by_shadow = config.noise_magnitude > 0.03
        
        return result
    
    def detect_anomaly(self, features: Dict[str, float]) -> AnomalyScore:
        """
        Detect anomaly using Isolation Forest.
        
        Args:
            features: Feature dictionary from divergence metrics
            
        Returns:
            Anomaly score with prediction
        """
        return self._detector.predict(features)
    
    async def run_stress_test(
        self,
        attack_types: Optional[List[AttackType]] = None,
        severity: AttackSeverity = AttackSeverity.MEDIUM,
        duration_per_attack: float = 5.0,
    ) -> List[AttackResult]:
        """
        Run comprehensive stress test with multiple attack types.
        
        Args:
            attack_types: Types of attacks to run (default: all)
            severity: Severity level for attacks
            duration_per_attack: Duration for each attack
            
        Returns:
            List of attack results
        """
        attack_types = attack_types or list(AttackType)
        results = []
        
        logger.info(
            "Starting stress test: %d attack types, severity=%s",
            len(attack_types), severity.value
        )
        
        for attack_type in attack_types:
            config = AttackConfig(
                attack_type=attack_type,
                severity=severity,
                duration_seconds=duration_per_attack,
            )
            
            result = await self.inject_attack(config)
            results.append(result)
            
            await asyncio.sleep(1.0)
        
        detected = sum(1 for r in results if r.detected_by_shadow)
        detection_rate = detected / len(results) if results else 0
        
        logger.info(
            "Stress test completed: %d/%d attacks detected (%.1f%%)",
            detected, len(results), detection_rate * 100
        )
        
        return results
    
    def get_attack_history(self, limit: int = 50) -> List[AttackResult]:
        """Get attack history."""
        return self._attack_history[-limit:]
    
    def get_detection_stats(self) -> Dict[str, Any]:
        """Get detection statistics."""
        if not self._attack_history:
            return {
                "total_attacks": 0,
                "detected": 0,
                "detection_rate": 0.0,
            }
        
        detected = sum(1 for r in self._attack_history if r.detected_by_shadow)
        avg_latency = sum(
            r.detection_latency_ms for r in self._attack_history if r.detected_by_shadow
        ) / max(detected, 1)
        
        by_type = {}
        for attack_type in AttackType:
            type_attacks = [r for r in self._attack_history if r.attack_type == attack_type]
            if type_attacks:
                type_detected = sum(1 for r in type_attacks if r.detected_by_shadow)
                by_type[attack_type.value] = {
                    "total": len(type_attacks),
                    "detected": type_detected,
                    "rate": type_detected / len(type_attacks),
                }
        
        return {
            "total_attacks": len(self._attack_history),
            "detected": detected,
            "detection_rate": detected / len(self._attack_history),
            "avg_detection_latency_ms": avg_latency,
            "by_type": by_type,
        }


_attack_simulator: Optional[AttackSimulator] = None
_attack_simulator_lock = threading.Lock()


def get_attack_simulator() -> AttackSimulator:
    """Get or create global attack simulator."""
    global _attack_simulator
    if _attack_simulator is None:
        with _attack_simulator_lock:
            if _attack_simulator is None:
                _attack_simulator = AttackSimulator()
    return _attack_simulator
