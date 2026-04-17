"""
MERID Swarm Watchdog - MVP
Provides basic monitoring, loop detection, and invariant checking for swarm operations.
"""

import time
import threading
from typing import Dict, List, Optional, Set, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque
import hashlib

from swarm.tracing.tracer import tracer, SpanType, SpanStatus
from utils.logger import get_logger

logger = get_logger("swarm.watchdog")


class WatchdogViolation(Enum):
    """Types of watchdog violations"""
    TURN_LIMIT_EXCEEDED = "turn_limit_exceeded"
    LOOP_DETECTED = "loop_detected"
    FORBIDDEN_PATH_ACCESS = "forbidden_path_access"
    MERGE_WITHOUT_TESTS = "merge_without_tests"
    AGENT_TIMEOUT = "agent_timeout"
    CASCADE_DETECTED = "cascade_detected"
    RESOURCE_EXHAUSTION = "resource_exhaustion"


@dataclass
class ViolationEvent:
    """Watchdog violation event"""
    violation_type: WatchdogViolation
    agent_id: str
    task_id: str
    timestamp: float
    details: Dict[str, Any]
    severity: str = "medium"  # "low", "medium", "high", "critical"


@dataclass
class TaskContext:
    """Context for tracking task execution"""
    task_id: str
    start_time: float
    agent_turns: Dict[str, int] = field(default_factory=dict)
    agent_states: Dict[str, str] = field(default_factory=dict)
    message_history: List[Dict[str, Any]] = field(default_factory=list)
    active_agents: Set[str] = field(default_factory=set)
    completed_agents: Set[str] = field(default_factory=set)


class WatchdogConfig:
    """Watchdog configuration"""
    
    def __init__(self):
        # Turn limits
        self.max_turns_per_agent = 50
        self.max_total_turns = 200
        
        # Loop detection
        self.loop_detection_window = 10
        self.max_state_repetitions = 3
        
        # Timeouts
        self.agent_timeout_seconds = 300  # 5 minutes
        self.task_timeout_seconds = 1800  # 30 minutes
        
        # Invariants
        self.forbidden_paths = [
            "/etc/", "/sys/", "/proc/", "/dev/",
            "C:\\Windows\\System32", "C:\\Program Files"
        ]
        self.protected_files = [
            "*.key", "*.pem", "*.p12", "passwords.txt",
            "secrets.yaml", ".env"
        ]
        
        # Cascade detection
        self.cascade_threshold_agents = 5
        self.cascade_time_window = 60  # seconds


class LoopDetector:
    """Detects loops in agent interactions"""
    
    def __init__(self, window_size: int = 10):
        self.window_size = window_size
    
    def detect_state_loop(self, agent_id: str, state_history: List[str]) -> bool:
        """Detect if agent is repeating the same state"""
        if len(state_history) < self.window_size:
            return False
        
        recent_states = state_history[-self.window_size:]
        unique_states = set(recent_states)
        
        # If we see the same state repeated too many times
        for state in unique_states:
            if recent_states.count(state) >= 3:
                return True
        
        return False
    
    def detect_message_loop(self, message_history: List[Dict[str, Any]]) -> bool:
        """Detect if agents are stuck in a messaging loop"""
        if len(message_history) < 6:
            return False
        
        # Look for repeating patterns in recent messages
        recent_messages = message_history[-6:]
        
        # Check if same pair of agents keep exchanging similar messages
        agent_pairs = [(msg.get("from"), msg.get("to")) for msg in recent_messages]
        pair_counts = defaultdict(int)
        
        for pair in agent_pairs:
            pair_counts[pair] += 1
        
        # If same pair appears 4+ times in recent history
        for pair, count in pair_counts.items():
            if count >= 4 and pair[0] != pair[1]:  # Different agents
                return True
        
        return False


class InvariantChecker:
    """Checks system invariants and security constraints"""
    
    def __init__(self, config: WatchdogConfig):
        self.config = config
    
    def check_forbidden_paths(self, file_path: str) -> bool:
        """Check if file path is forbidden"""
        path_normalized = file_path.lower().replace("\\", "/")
        
        for forbidden in self.config.forbidden_paths:
            if forbidden.lower().replace("\\", "/") in path_normalized:
                return True
        
        return False
    
    def check_protected_files(self, file_path: str) -> bool:
        """Check if file is protected"""
        import fnmatch
        
        file_name = file_path.split("/")[-1].split("\\")[-1]
        
        for pattern in self.config.protected_files:
            if fnmatch.fnmatch(file_name.lower(), pattern.lower()):
                return True
        
        return False
    
    def check_merge_without_tests(self, file_path: str, has_tests: bool) -> bool:
        """Check if merge is happening without tests"""
        if file_path.endswith((".py", ".js", ".ts")) and not has_tests:
            return True
        return False


class CascadeDetector:
    """Detects cascading failures"""
    
    def __init__(self, config: WatchdogConfig):
        self.config = config
        self.failure_history: deque = deque(maxlen=100)
    
    def add_failure(self, agent_id: str, timestamp: float):
        """Add a failure event"""
        self.failure_history.append({
            "agent_id": agent_id,
            "timestamp": timestamp
        })
    
    def detect_cascade(self) -> List[str]:
        """Detect if cascade is occurring"""
        current_time = time.time()
        cutoff_time = current_time - self.config.cascade_time_window
        
        recent_failures = [
            f for f in self.failure_history 
            if f["timestamp"] > cutoff_time
        ]
        
        # Count unique agents failing in time window
        unique_agents = set(f["agent_id"] for f in recent_failures)
        
        if len(unique_agents) >= self.config.cascade_threshold_agents:
            return list(unique_agents)
        
        return []


class SwarmWatchdog:
    """Main watchdog class for swarm monitoring"""
    
    def __init__(self, config: Optional[WatchdogConfig] = None):
        self.config = config or WatchdogConfig()
        self.active_tasks: Dict[str, TaskContext] = {}
        self.violations: List[ViolationEvent] = []
        self.loop_detector = LoopDetector(self.config.loop_detection_window)
        self.invariant_checker = InvariantChecker(self.config)
        self.cascade_detector = CascadeDetector(self.config)
        self._lock = threading.RLock()
        
        # Start background monitoring
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        
        logger.info("Swarm watchdog initialized")
    
    def start_task(self, task_id: str, agent_ids: List[str]) -> TaskContext:
        """Start monitoring a new task"""
        with self._lock:
            # Extract agent IDs from agent configs if needed
            if agent_ids and isinstance(agent_ids[0], dict):
                agent_id_strings = [agent.get('id', str(agent)) for agent in agent_ids]
            else:
                agent_id_strings = agent_ids
                
            context = TaskContext(
                task_id=task_id,
                start_time=time.time(),
                active_agents=set(agent_id_strings)
            )
            self.active_tasks[task_id] = context
            
            logger.info(f"Started monitoring task {task_id} with agents {agent_ids}")
            return context
    
    def end_task(self, task_id: str):
        """End monitoring for a task"""
        with self._lock:
            if task_id in self.active_tasks:
                del self.active_tasks[task_id]
                logger.info(f"Ended monitoring task {task_id}")
    
    def record_agent_turn(self, task_id: str, agent_id: str, state: str = None):
        """Record an agent taking a turn"""
        with self._lock:
            context = self.active_tasks.get(task_id)
            if not context:
                return
            
            # Increment turn count
            context.agent_turns[agent_id] = context.agent_turns.get(agent_id, 0) + 1
            
            # Update state
            if state:
                context.agent_states[agent_id] = state
            
            # Check turn limits
            if context.agent_turns[agent_id] > self.config.max_turns_per_agent:
                self._record_violation(
                    WatchdogViolation.TURN_LIMIT_EXCEEDED,
                    agent_id,
                    task_id,
                    {
                        "turn_count": context.agent_turns[agent_id],
                        "limit": self.config.max_turns_per_agent
                    },
                    "high"
                )
            
            total_turns = sum(context.agent_turns.values())
            if total_turns > self.config.max_total_turns:
                self._record_violation(
                    WatchdogViolation.TURN_LIMIT_EXCEEDED,
                    agent_id,
                    task_id,
                    {
                        "total_turns": total_turns,
                        "limit": self.config.max_total_turns
                    },
                    "critical"
                )
    
    def record_message(self, task_id: str, from_agent: str, to_agent: str, 
                      message_content: str = ""):
        """Record a message between agents"""
        with self._lock:
            context = self.active_tasks.get(task_id)
            if not context:
                return
            
            message = {
                "from": from_agent,
                "to": to_agent,
                "content": message_content,
                "timestamp": time.time()
            }
            context.message_history.append(message)
            
            # Check for loops
            if self.loop_detector.detect_message_loop(context.message_history):
                self._record_violation(
                    WatchdogViolation.LOOP_DETECTED,
                    from_agent,
                    task_id,
                    {
                        "message_pattern": "repeated_agent_pair",
                        "recent_messages": context.message_history[-6:]
                    },
                    "medium"
                )
    
    def record_file_access(self, task_id: str, agent_id: str, file_path: str, 
                          operation: str = "read", has_tests: bool = False):
        """Record file access for invariant checking"""
        with self._lock:
            # Check forbidden paths
            if self.invariant_checker.check_forbidden_paths(file_path):
                self._record_violation(
                    WatchdogViolation.FORBIDDEN_PATH_ACCESS,
                    agent_id,
                    task_id,
                    {
                        "file_path": file_path,
                        "operation": operation
                    },
                    "critical"
                )
            
            # Check protected files
            if self.invariant_checker.check_protected_files(file_path):
                self._record_violation(
                    WatchdogViolation.FORBIDDEN_PATH_ACCESS,
                    agent_id,
                    task_id,
                    {
                        "file_path": file_path,
                        "operation": operation,
                        "protected_file": True
                    },
                    "critical"
                )
            
            # Check merge without tests
            if operation == "write" and self.invariant_checker.check_merge_without_tests(file_path, has_tests):
                self._record_violation(
                    WatchdogViolation.MERGE_WITHOUT_TESTS,
                    agent_id,
                    task_id,
                    {
                        "file_path": file_path,
                        "has_tests": has_tests
                    },
                    "medium"
                )
    
    def record_agent_failure(self, agent_id: str, error: str = ""):
        """Record an agent failure for cascade detection"""
        self.cascade_detector.add_failure(agent_id, time.time())
        
        # Check for cascade
        cascading_agents = self.cascade_detector.detect_cascade()
        if cascading_agents:
            # Find which task this might be affecting
            affected_task = None
            with self._lock:
                for task_id, context in self.active_tasks.items():
                    if agent_id in context.active_agents:
                        affected_task = task_id
                        break
            
            self._record_violation(
                WatchdogViolation.CASCADE_DETECTED,
                agent_id,
                affected_task or "unknown",
                {
                    "cascading_agents": cascading_agents,
                    "cascade_size": len(cascading_agents),
                    "error": error
                },
                "critical"
            )
    
    def _record_violation(self, violation_type: WatchdogViolation, agent_id: str,
                         task_id: str, details: Dict[str, Any], severity: str):
        """Record a violation event"""
        violation = ViolationEvent(
            violation_type=violation_type,
            agent_id=agent_id,
            task_id=task_id,
            timestamp=time.time(),
            details=details,
            severity=severity
        )
        
        self.violations.append(violation)
        logger.warning(f"Watchdog violation: {violation_type.value} by {agent_id} in task {task_id}")
    
    def _monitor_loop(self):
        """Background monitoring loop"""
        while True:
            try:
                self._check_timeouts()
                self._check_state_loops()
                time.sleep(10)  # Check every 10 seconds
            except Exception as e:
                logger.error(f"Watchdog monitor loop error: {e}")
                time.sleep(10)
    
    def _check_timeouts(self):
        """Check for agent and task timeouts"""
        current_time = time.time()
        
        with self._lock:
            for task_id, context in list(self.active_tasks.items()):
                # Check task timeout
                task_age = current_time - context.start_time
                if task_age > self.config.task_timeout_seconds:
                    self._record_violation(
                        WatchdogViolation.AGENT_TIMEOUT,
                        "task",
                        task_id,
                        {
                            "task_age_seconds": task_age,
                            "timeout_seconds": self.config.task_timeout_seconds
                        },
                        "high"
                    )
    
    def _check_state_loops(self):
        """Check for state loops in active agents"""
        with self._lock:
            for task_id, context in self.active_tasks.items():
                for agent_id, state in context.agent_states.items():
                    # Build state history from spans
                    state_history = []
                    spans = tracer.get_trace(context.task_id)
                    for span in spans:
                        if (span.agent_id == agent_id and 
                            span.span_type == SpanType.AGENT_EXECUTION):
                            state_hash = hashlib.md5(
                                str(span.tags).encode()
                            ).hexdigest()
                            state_history.append(state_hash)
                    
                    if self.loop_detector.detect_state_loop(agent_id, state_history):
                        self._record_violation(
                            WatchdogViolation.LOOP_DETECTED,
                            agent_id,
                            task_id,
                            {
                                "loop_type": "state_repetition",
                                "state_history_length": len(state_history)
                            },
                            "medium"
                        )
    
    def get_violations(self, severity: Optional[str] = None,
                      violation_type: Optional[WatchdogViolation] = None) -> List[ViolationEvent]:
        """Get violations with optional filtering"""
        violations = self.violations
        
        if severity:
            violations = [v for v in violations if v.severity == severity]
        
        if violation_type:
            violations = [v for v in violations if v.violation_type == violation_type]
        
        return violations
    
    def get_task_summary(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get summary of task execution"""
        with self._lock:
            context = self.active_tasks.get(task_id)
            if not context:
                return None
            
            violations = [v for v in self.violations if v.task_id == task_id]
            
            return {
                "task_id": task_id,
                "start_time": context.start_time,
                "duration_seconds": time.time() - context.start_time,
                "agent_turns": dict(context.agent_turns),
                "total_turns": sum(context.agent_turns.values()),
                "active_agents": list(context.active_agents),
                "completed_agents": list(context.completed_agents),
                "message_count": len(context.message_history),
                "violation_count": len(violations),
                "violations_by_severity": {
                    sev: len([v for v in violations if v.severity == sev])
                    for sev in ["low", "medium", "high", "critical"]
                }
            }


# Global watchdog instance
watchdog = SwarmWatchdog()
