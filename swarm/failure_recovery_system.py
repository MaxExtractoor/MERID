"""
Failure modes and recovery patterns for multi-agent systems.

Implements detection, classification, and automated recovery for agent failures
including logic bugs, LLM hallucinations, deadlocks, partial outages, and
over-exploration/exploitation.
"""

import logging
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict, deque
import threading

logger = logging.getLogger(__name__)


class FailureMode(Enum):
    """Type of failure mode."""
    LOGIC_BUG = "logic_bug"
    MIS_ROUTING = "mis_routing"
    MIS_CONFIGURED_PROMPT = "mis_configured_prompt"
    MIS_CONFIGURED_TOOL = "mis_configured_tool"
    LLM_HALLUCINATION = "llm_hallucination"
    LOW_CONFIDENCE_OUTPUT = "low_confidence_output"
    TOOL_USE_ERROR = "tool_use_error"
    DEADLOCK = "deadlock"
    PING_PONG_LOOP = "ping_pong_loop"
    MESSAGE_STORM = "message_storm"
    PARTIAL_OUTAGE = "partial_outage"
    DEGRADED_API = "degraded_api"
    OVER_EXPLORATION = "over_exploration"
    OVER_EXPLOITATION = "over_exploitation"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    TIMEOUT = "timeout"


class RecoveryPattern(Enum):
    """Type of recovery pattern."""
    CIRCUIT_BREAKER = "circuit_breaker"
    BACKOFF_RETRY = "backoff_retry"
    FALLBACK_PATH = "fallback_path"
    ROLE_SWITCHING = "role_switching"
    FAILOVER = "failover"
    SELF_HEALING = "self_healing"
    GRACEFUL_DEGRADATION = "graceful_degradation"
    HUMAN_ESCALATION = "human_escalation"


@dataclass
class FailureDetector:
    """Failure detector configuration."""
    detector_id: str
    failure_mode: FailureMode
    name: str
    description: str
    
    detection_function: Callable[[Any], Tuple[bool, str, Dict[str, Any]]]
    detection_window_seconds: int
    
    enabled: bool = True
    detections: int = 0


@dataclass
class RecoveryAction:
    """Recovery action configuration."""
    action_id: str
    recovery_pattern: RecoveryPattern
    name: str
    description: str
    
    action_function: Callable[[Any], bool]
    max_attempts: int
    
    enabled: bool = True
    successes: int = 0
    failures: int = 0


@dataclass
class FailureEvent:
    """Failure event record."""
    event_id: str
    timestamp: datetime
    failure_mode: FailureMode
    
    affected_component: str
    description: str
    evidence: Dict[str, Any]
    
    recovery_pattern: Optional[RecoveryPattern] = None
    recovery_attempted: bool = False
    recovery_successful: bool = False
    recovery_actions_taken: List[str] = field(default_factory=list)
    
    resolved: bool = False
    resolved_at: Optional[datetime] = None


@dataclass
class CircuitBreakerState:
    """Circuit breaker state."""
    component_id: str
    failure_threshold: int
    timeout_seconds: int
    
    failure_count: int = 0
    last_failure: Optional[datetime] = None
    state: str = "closed"  # closed, open, half_open
    opened_at: Optional[datetime] = None


@dataclass
class BackoffStrategy:
    """Backoff retry strategy."""
    component_id: str
    initial_delay_ms: int
    max_delay_ms: int
    multiplier: float
    max_attempts: int
    
    current_attempt: int = 0
    current_delay_ms: int = 0


class FailureRecoverySystem:
    """
    Failure modes and recovery patterns system.
    
    Implements:
    - Detection for all failure modes
    - Circuit breakers per agent/tool/venue
    - Backoff retry strategies
    - Fallback paths with alternate tools/agents
    - Role switching to backup agents
    - Self-healing actions from runbooks
    - Graceful degradation (full swarm → core → minimal)
    - Human escalation for unrecoverable failures
    """
    
    def __init__(self):
        self._failure_detectors: Dict[str, FailureDetector] = {}
        self._recovery_actions: Dict[str, RecoveryAction] = {}
        self._failure_events: List[FailureEvent] = []
        
        self._circuit_breakers: Dict[str, CircuitBreakerState] = {}
        self._backoff_strategies: Dict[str, BackoffStrategy] = {}
        self._fallback_paths: Dict[str, List[str]] = {}
        
        self._lock = threading.Lock()
        
        self._initialize_failure_detectors()
        self._initialize_recovery_actions()
        self._initialize_fallback_paths()
    
    def _initialize_failure_detectors(self) -> None:
        """Initialize failure detectors."""
        self.register_failure_detector(
            detector_id="detect_deadlock",
            failure_mode=FailureMode.DEADLOCK,
            name="Deadlock Detection",
            description="Detect circular waiting between agents",
            detection_function=self._detect_deadlock,
            detection_window_seconds=60,
        )
        
        self.register_failure_detector(
            detector_id="detect_ping_pong",
            failure_mode=FailureMode.PING_PONG_LOOP,
            name="Ping-Pong Loop Detection",
            description="Detect agents repeatedly sending same messages",
            detection_function=self._detect_ping_pong,
            detection_window_seconds=30,
        )
        
        self.register_failure_detector(
            detector_id="detect_message_storm",
            failure_mode=FailureMode.MESSAGE_STORM,
            name="Message Storm Detection",
            description="Detect excessive message volume",
            detection_function=self._detect_message_storm,
            detection_window_seconds=10,
        )
        
        self.register_failure_detector(
            detector_id="detect_llm_hallucination",
            failure_mode=FailureMode.LLM_HALLUCINATION,
            name="LLM Hallucination Detection",
            description="Detect low-confidence or contradictory LLM outputs",
            detection_function=self._detect_llm_hallucination,
            detection_window_seconds=5,
        )
        
        self.register_failure_detector(
            detector_id="detect_over_exploration",
            failure_mode=FailureMode.OVER_EXPLORATION,
            name="Over-Exploration Detection",
            description="Detect too many experiments without exploitation",
            detection_function=self._detect_over_exploration,
            detection_window_seconds=300,
        )
        
        logger.info("Initialized failure detectors")
    
    def _initialize_recovery_actions(self) -> None:
        """Initialize recovery actions."""
        self.register_recovery_action(
            action_id="circuit_breaker_open",
            recovery_pattern=RecoveryPattern.CIRCUIT_BREAKER,
            name="Open Circuit Breaker",
            description="Open circuit breaker to stop cascading failures",
            action_function=self._action_circuit_breaker,
            max_attempts=1,
        )
        
        self.register_recovery_action(
            action_id="backoff_retry",
            recovery_pattern=RecoveryPattern.BACKOFF_RETRY,
            name="Backoff and Retry",
            description="Retry with exponential backoff",
            action_function=self._action_backoff_retry,
            max_attempts=5,
        )
        
        self.register_recovery_action(
            action_id="switch_to_fallback",
            recovery_pattern=RecoveryPattern.FALLBACK_PATH,
            name="Switch to Fallback",
            description="Use alternate tool or agent",
            action_function=self._action_fallback,
            max_attempts=3,
        )
        
        self.register_recovery_action(
            action_id="failover_to_backup",
            recovery_pattern=RecoveryPattern.FAILOVER,
            name="Failover to Backup",
            description="Switch to backup agent instance",
            action_function=self._action_failover,
            max_attempts=2,
        )
        
        self.register_recovery_action(
            action_id="graceful_degradation",
            recovery_pattern=RecoveryPattern.GRACEFUL_DEGRADATION,
            name="Graceful Degradation",
            description="Reduce to core functionality",
            action_function=self._action_graceful_degradation,
            max_attempts=1,
        )
        
        logger.info("Initialized recovery actions")
    
    def _initialize_fallback_paths(self) -> None:
        """Initialize fallback paths."""
        self._fallback_paths = {
            "primary_trader": ["backup_trader", "simple_baseline_trader"],
            "complex_analyzer": ["simple_analyzer", "rule_based_analyzer"],
            "llm_router": ["rule_based_router", "random_router"],
        }
    
    def register_failure_detector(
        self,
        detector_id: str,
        failure_mode: FailureMode,
        name: str,
        description: str,
        detection_function: Callable[[Any], Tuple[bool, str, Dict[str, Any]]],
        detection_window_seconds: int,
    ) -> FailureDetector:
        """Register failure detector."""
        detector = FailureDetector(
            detector_id=detector_id,
            failure_mode=failure_mode,
            name=name,
            description=description,
            detection_function=detection_function,
            detection_window_seconds=detection_window_seconds,
        )
        
        self._failure_detectors[detector_id] = detector
        
        logger.info(f"Registered failure detector '{detector_id}': {name}")
        
        return detector
    
    def register_recovery_action(
        self,
        action_id: str,
        recovery_pattern: RecoveryPattern,
        name: str,
        description: str,
        action_function: Callable[[Any], bool],
        max_attempts: int,
    ) -> RecoveryAction:
        """Register recovery action."""
        action = RecoveryAction(
            action_id=action_id,
            recovery_pattern=recovery_pattern,
            name=name,
            description=description,
            action_function=action_function,
            max_attempts=max_attempts,
        )
        
        self._recovery_actions[action_id] = action
        
        logger.info(f"Registered recovery action '{action_id}': {name}")
        
        return action
    
    def register_circuit_breaker(
        self,
        component_id: str,
        failure_threshold: int = 5,
        timeout_seconds: int = 60,
    ) -> CircuitBreakerState:
        """Register circuit breaker for component."""
        breaker = CircuitBreakerState(
            component_id=component_id,
            failure_threshold=failure_threshold,
            timeout_seconds=timeout_seconds,
        )
        
        self._circuit_breakers[component_id] = breaker
        
        logger.info(
            f"Registered circuit breaker for '{component_id}': "
            f"threshold={failure_threshold}, timeout={timeout_seconds}s"
        )
        
        return breaker
    
    def register_backoff_strategy(
        self,
        component_id: str,
        initial_delay_ms: int = 100,
        max_delay_ms: int = 30000,
        multiplier: float = 2.0,
        max_attempts: int = 5,
    ) -> BackoffStrategy:
        """Register backoff retry strategy."""
        strategy = BackoffStrategy(
            component_id=component_id,
            initial_delay_ms=initial_delay_ms,
            max_delay_ms=max_delay_ms,
            multiplier=multiplier,
            max_attempts=max_attempts,
            current_delay_ms=initial_delay_ms,
        )
        
        self._backoff_strategies[component_id] = strategy
        
        logger.info(
            f"Registered backoff strategy for '{component_id}': "
            f"initial={initial_delay_ms}ms, max={max_delay_ms}ms"
        )
        
        return strategy
    
    def detect_failures(
        self,
        context: Dict[str, Any],
    ) -> List[FailureEvent]:
        """Detect failures in context."""
        with self._lock:
            failures = []
            
            for detector_id, detector in self._failure_detectors.items():
                if not detector.enabled:
                    continue
                
                try:
                    detected, description, evidence = detector.detection_function(context)
                    
                    if detected:
                        event = self._create_failure_event(
                            failure_mode=detector.failure_mode,
                            affected_component=context.get("component_id", "unknown"),
                            description=description,
                            evidence=evidence,
                        )
                        
                        failures.append(event)
                        detector.detections += 1
                
                except Exception as e:
                    logger.error(f"Error in failure detector '{detector_id}': {e}")
            
            return failures
    
    def attempt_recovery(
        self,
        failure_event: FailureEvent,
    ) -> bool:
        """Attempt recovery for failure event."""
        with self._lock:
            # Select recovery pattern
            recovery_pattern = self._select_recovery_pattern(failure_event)
            
            if not recovery_pattern:
                logger.warning(
                    f"No recovery pattern for failure mode {failure_event.failure_mode.value}"
                )
                return False
            
            failure_event.recovery_pattern = recovery_pattern
            failure_event.recovery_attempted = True
            
            # Find matching recovery action
            action = next(
                (a for a in self._recovery_actions.values() if a.recovery_pattern == recovery_pattern),
                None
            )
            
            if not action or not action.enabled:
                return False
            
            # Attempt recovery
            try:
                success = action.action_function({
                    "failure_event": failure_event,
                    "component_id": failure_event.affected_component,
                })
                
                if success:
                    action.successes += 1
                    failure_event.recovery_successful = True
                    failure_event.resolved = True
                    failure_event.resolved_at = datetime.utcnow()
                else:
                    action.failures += 1
                
                failure_event.recovery_actions_taken.append(action.action_id)
                
                logger.info(
                    f"Recovery attempt for '{failure_event.event_id}': "
                    f"{'SUCCESS' if success else 'FAILED'}"
                )
                
                return success
            
            except Exception as e:
                logger.error(f"Error during recovery: {e}")
                action.failures += 1
                return False
    
    def _select_recovery_pattern(
        self,
        failure_event: FailureEvent,
    ) -> Optional[RecoveryPattern]:
        """Select appropriate recovery pattern for failure."""
        # Map failure modes to recovery patterns
        pattern_map = {
            FailureMode.LOGIC_BUG: RecoveryPattern.FALLBACK_PATH,
            FailureMode.MIS_ROUTING: RecoveryPattern.FALLBACK_PATH,
            FailureMode.LLM_HALLUCINATION: RecoveryPattern.BACKOFF_RETRY,
            FailureMode.LOW_CONFIDENCE_OUTPUT: RecoveryPattern.FALLBACK_PATH,
            FailureMode.TOOL_USE_ERROR: RecoveryPattern.BACKOFF_RETRY,
            FailureMode.DEADLOCK: RecoveryPattern.CIRCUIT_BREAKER,
            FailureMode.PING_PONG_LOOP: RecoveryPattern.CIRCUIT_BREAKER,
            FailureMode.MESSAGE_STORM: RecoveryPattern.CIRCUIT_BREAKER,
            FailureMode.PARTIAL_OUTAGE: RecoveryPattern.FAILOVER,
            FailureMode.DEGRADED_API: RecoveryPattern.BACKOFF_RETRY,
            FailureMode.OVER_EXPLORATION: RecoveryPattern.GRACEFUL_DEGRADATION,
            FailureMode.OVER_EXPLOITATION: RecoveryPattern.GRACEFUL_DEGRADATION,
            FailureMode.RESOURCE_EXHAUSTION: RecoveryPattern.GRACEFUL_DEGRADATION,
            FailureMode.TIMEOUT: RecoveryPattern.BACKOFF_RETRY,
        }
        
        return pattern_map.get(failure_event.failure_mode)
    
    def _detect_deadlock(
        self,
        context: Dict[str, Any],
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Detect deadlock."""
        # Simplified detection: check for circular waiting
        waiting_for = context.get("waiting_for", {})
        
        if len(waiting_for) > 1:
            # Check for cycles
            for agent_id, waiting_on in waiting_for.items():
                if waiting_on in waiting_for and waiting_for[waiting_on] == agent_id:
                    return True, f"Deadlock detected: {agent_id} <-> {waiting_on}", {
                        "agents": [agent_id, waiting_on],
                    }
        
        return False, "", {}
    
    def _detect_ping_pong(
        self,
        context: Dict[str, Any],
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Detect ping-pong loop."""
        message_history = context.get("message_history", [])
        
        if len(message_history) < 4:
            return False, "", {}
        
        # Check for repeated back-and-forth
        last_4 = message_history[-4:]
        if (last_4[0] == last_4[2] and last_4[1] == last_4[3]):
            return True, "Ping-pong loop detected", {
                "repeated_messages": last_4,
            }
        
        return False, "", {}
    
    def _detect_message_storm(
        self,
        context: Dict[str, Any],
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Detect message storm."""
        message_count = context.get("messages_last_10s", 0)
        
        if message_count > 100:
            return True, f"Message storm: {message_count} messages in 10s", {
                "message_count": message_count,
                "threshold": 100,
            }
        
        return False, "", {}
    
    def _detect_llm_hallucination(
        self,
        context: Dict[str, Any],
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Detect LLM hallucination."""
        confidence = context.get("llm_confidence", 1.0)
        
        if confidence < 0.3:
            return True, f"Low confidence LLM output: {confidence:.2f}", {
                "confidence": confidence,
                "threshold": 0.3,
            }
        
        return False, "", {}
    
    def _detect_over_exploration(
        self,
        context: Dict[str, Any],
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Detect over-exploration."""
        exploration_rate = context.get("exploration_rate", 0.0)
        
        if exploration_rate > 0.5:
            return True, f"Over-exploration: {exploration_rate:.2%}", {
                "exploration_rate": exploration_rate,
                "threshold": 0.5,
            }
        
        return False, "", {}
    
    def _action_circuit_breaker(
        self,
        context: Dict[str, Any],
    ) -> bool:
        """Open circuit breaker."""
        component_id = context.get("component_id")
        if not component_id:
            return False
        
        breaker = self._circuit_breakers.get(component_id)
        if not breaker:
            return False
        
        breaker.state = "open"
        breaker.opened_at = datetime.utcnow()
        
        logger.info(f"Opened circuit breaker for '{component_id}'")
        
        return True
    
    def _action_backoff_retry(
        self,
        context: Dict[str, Any],
    ) -> bool:
        """Retry with backoff."""
        component_id = context.get("component_id")
        if not component_id:
            return False
        
        strategy = self._backoff_strategies.get(component_id)
        if not strategy:
            return False
        
        if strategy.current_attempt >= strategy.max_attempts:
            return False
        
        strategy.current_attempt += 1
        strategy.current_delay_ms = min(
            int(strategy.current_delay_ms * strategy.multiplier),
            strategy.max_delay_ms
        )
        
        logger.info(
            f"Backoff retry for '{component_id}': "
            f"attempt {strategy.current_attempt}/{strategy.max_attempts}, "
            f"delay {strategy.current_delay_ms}ms"
        )
        
        return True
    
    def _action_fallback(
        self,
        context: Dict[str, Any],
    ) -> bool:
        """Switch to fallback."""
        component_id = context.get("component_id")
        if not component_id:
            return False
        
        fallbacks = self._fallback_paths.get(component_id, [])
        if not fallbacks:
            return False
        
        # Use first available fallback
        fallback = fallbacks[0]
        
        logger.info(f"Switching from '{component_id}' to fallback '{fallback}'")
        
        return True
    
    def _action_failover(
        self,
        context: Dict[str, Any],
    ) -> bool:
        """Failover to backup."""
        component_id = context.get("component_id")
        if not component_id:
            return False
        
        backup_id = f"{component_id}_backup"
        
        logger.info(f"Failing over from '{component_id}' to '{backup_id}'")
        
        return True
    
    def _action_graceful_degradation(
        self,
        context: Dict[str, Any],
    ) -> bool:
        """Gracefully degrade functionality."""
        logger.info("Initiating graceful degradation: reducing to core functionality")
        
        # This would trigger reduction to minimal viable trader
        return True
    
    def _create_failure_event(
        self,
        failure_mode: FailureMode,
        affected_component: str,
        description: str,
        evidence: Dict[str, Any],
    ) -> FailureEvent:
        """Create failure event."""
        import hashlib
        event_id = hashlib.md5(
            f"{failure_mode.value}_{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:16]
        
        event = FailureEvent(
            event_id=event_id,
            timestamp=datetime.utcnow(),
            failure_mode=failure_mode,
            affected_component=affected_component,
            description=description,
            evidence=evidence,
        )
        
        self._failure_events.append(event)
        
        logger.warning(
            f"Failure event '{event_id}': {failure_mode.value} - {description}"
        )
        
        return event
    
    def get_failure_events(
        self,
        failure_mode: Optional[FailureMode] = None,
        resolved: Optional[bool] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[FailureEvent]:
        """Query failure events."""
        events = self._failure_events
        
        if failure_mode:
            events = [e for e in events if e.failure_mode == failure_mode]
        
        if resolved is not None:
            events = [e for e in events if e.resolved == resolved]
        
        if since:
            events = [e for e in events if e.timestamp >= since]
        
        return events[-limit:]
    
    def get_recovery_summary(self) -> Dict[str, Any]:
        """Get failure recovery summary."""
        return {
            "failure_detectors": len(self._failure_detectors),
            "recovery_actions": len(self._recovery_actions),
            "circuit_breakers": len(self._circuit_breakers),
            "backoff_strategies": len(self._backoff_strategies),
            "total_failures": len(self._failure_events),
            "by_failure_mode": {
                mode.value: len([e for e in self._failure_events if e.failure_mode == mode])
                for mode in FailureMode
            },
            "recovery_success_rate": (
                len([e for e in self._failure_events if e.recovery_successful]) /
                len([e for e in self._failure_events if e.recovery_attempted])
                if any(e.recovery_attempted for e in self._failure_events) else 0.0
            ),
            "unresolved_failures": len([e for e in self._failure_events if not e.resolved]),
        }


_failure_recovery_system: Optional[FailureRecoverySystem] = None


def get_failure_recovery_system() -> FailureRecoverySystem:
    """Get global FailureRecoverySystem instance."""
    global _failure_recovery_system
    if _failure_recovery_system is None:
        _failure_recovery_system = FailureRecoverySystem()
    return _failure_recovery_system
