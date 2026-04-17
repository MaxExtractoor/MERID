"""
MERID Swarm Integration - Tracing and Watchdog Setup
Integrates tracing and watchdog infrastructure with existing swarm components.
"""

import time
import uuid
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from swarm.tracing.tracer import tracer, SpanType, SpanContext, trace_span
from swarm.watchdog.monitor import watchdog, WatchdogViolation
from utils.logger import get_logger

logger = get_logger("swarm.integration")


@dataclass
class TaskMetrics:
    """Metrics collected during task execution"""
    task_id: str
    start_time: float
    end_time: Optional[float] = None
    success: bool = False
    rollback_count: int = 0
    human_intervention_count: int = 0
    total_turns: int = 0
    total_tokens: int = 0
    cascade_size: int = 0
    cascade_depth: int = 0
    branching_factor: float = 0.0
    retry_index: float = 0.0
    misalignment_scores: Dict[str, float] = None
    
    def __post_init__(self):
        if self.misalignment_scores is None:
            self.misalignment_scores = {}


class SwarmTaskRunner:
    """Enhanced task runner with tracing and watchdog integration"""
    
    def __init__(self, enable_enforcement: bool = False):
        self.enable_enforcement = enable_enforcement
        self.active_tasks: Dict[str, TaskMetrics] = {}
        
        logger.info(f"SwarmTaskRunner initialized - enforcement: {enable_enforcement}")
    
    def execute_task(self, task_config: Dict[str, Any]) -> TaskMetrics:
        """Execute a task with full tracing and monitoring"""
        task_id = str(uuid.uuid4())
        
        # Start task-level tracing
        with SpanContext(SpanType.TASK_ROOT, f"task_{task_config.get('type', 'unknown')}") as task_span:
            task_span.set_tag("task_id", task_id)
            task_span.set_tag("task_type", task_config.get("type"))
            task_span.set_tag("task_complexity", task_config.get("complexity", "medium"))
            
            # Initialize metrics
            metrics = TaskMetrics(
                task_id=task_id,
                start_time=time.time()
            )
            self.active_tasks[task_id] = metrics
            
            # Start watchdog monitoring
            agent_ids = task_config.get("agents", [])
            watchdog.start_task(task_id, agent_ids)
            
            try:
                # Execute the actual task
                result = self._execute_task_with_monitoring(task_config, task_id, task_span)
                
                # Record success
                metrics.success = True
                metrics.end_time = time.time()
                
                task_span.set_tag("success", True)
                task_span.set_tag("duration_seconds", metrics.end_time - metrics.start_time)
                
                logger.info(f"Task {task_id} completed successfully")
                
            except Exception as e:
                # Record failure
                metrics.success = False
                metrics.end_time = time.time()
                
                task_span.set_tag("success", False)
                task_span.set_tag("error", str(e))
                task_span.add_event("task_failed", {"error": str(e)})
                
                # Record failure for cascade detection
                watchdog.record_agent_failure("task_runner", str(e))
                
                logger.error(f"Task {task_id} failed: {e}")
                raise
            
            finally:
                # End watchdog monitoring
                watchdog.end_task(task_id)
                
                # Collect final metrics
                self._collect_final_metrics(task_id, task_span)
        
        return metrics
    
    def _execute_task_with_monitoring(self, task_config: Dict[str, Any], 
                                   task_id: str, parent_span) -> Dict[str, Any]:
        """Execute task with agent-level monitoring"""
        agents = task_config.get("agents", [])
        
        for i, agent_config in enumerate(agents):
            agent_id = agent_config.get("id", f"agent_{i}")
            
            # Trace agent execution
            with SpanContext(SpanType.AGENT_EXECUTION, f"agent_{agent_id}", 
                           parent_span.span_id, agent_id, parent_span.trace_id) as agent_span:
                
                agent_span.set_tag("agent_id", agent_id)
                agent_span.set_tag("agent_role", agent_config.get("role"))
                agent_span.set_tag("turn_number", i + 1)
                
                # Record agent turn with watchdog
                watchdog.record_agent_turn(task_id, agent_id, f"turn_{i+1}")
                
                # Simulate agent work (replace with actual agent execution)
                result = self._simulate_agent_work(agent_config, agent_span)
                
                # Update metrics
                metrics = self.active_tasks[task_id]
                metrics.total_turns += 1
                if result.get("tokens_used"):
                    metrics.total_tokens += result["tokens_used"]
                
                # Record agent state for misalignment calculation
                agent_state = result.get("state_vector", [])
                if agent_state:
                    self._update_agent_states(task_id, agent_id, agent_state)
        
        return {"status": "completed", "task_id": task_id}
    
    def _simulate_agent_work(self, agent_config: Dict[str, Any], 
                           agent_span) -> Dict[str, Any]:
        """Simulate agent work with tool calls and state operations"""
        agent_id = agent_config.get("id")
        role = agent_config.get("role", "unknown")
        
        result = {"state_vector": [], "tokens_used": 0}
        
        # Simulate tool calls
        tools = agent_config.get("tools", [])
        for tool in tools:
            with SpanContext(SpanType.TOOL_CALL, f"tool_{tool}", 
                           agent_span.span_id, agent_id, agent_span.trace_id) as tool_span:
                
                tool_span.set_tag("tool_name", tool)
                tool_span.set_tag("agent_id", agent_id)
                
                # Record file access for invariant checking
                if tool in ["file_read", "file_write"]:
                    file_path = f"/tmp/swarm/{agent_id}_{tool}.py"
                    has_tests = tool == "file_write" and "test" in file_path
                    watchdog.record_file_access(
                        self._get_current_task_id(), 
                        agent_id, 
                        file_path, 
                        tool, 
                        has_tests
                    )
                
                # Simulate tool execution with potential failures
                if hasattr(self, '_fault_injection_enabled') and self._fault_injection_enabled:
                    if tool == "repo_search" and hasattr(self, '_flaky_tool_rate'):
                        import random
                        if random.random() < self._flaky_tool_rate:
                            tool_span.set_tag("failed", True)
                            tool_span.add_event("tool_failed", {"error": "Flaky tool failure"})
                            raise Exception(f"Tool {tool} failed (fault injection)")
                
                result["tokens_used"] += 50  # Simulate token usage
        
        # Simulate state operations
        state_ops = agent_config.get("state_operations", [])
        for op in state_ops:
            with SpanContext(SpanType.STATE_READ if op == "read" else SpanType.STATE_WRITE,
                           f"state_{op}", agent_span.span_id, agent_id, agent_span.trace_id) as state_span:
                
                state_span.set_tag("operation", op)
                state_span.set_tag("agent_id", agent_id)
        
        # Generate synthetic state vector for misalignment calculation
        import numpy as np
        state_vector = np.random.randn(128)  # 128-dimensional state
        if role == "planner":
            state_vector[:10] = 1.0  # Planning-focused features
        elif role == "reviewer":
            state_vector[10:20] = 1.0  # Review-focused features
        elif role == "tester":
            state_vector[20:30] = 1.0  # Testing-focused features
        
        result["state_vector"] = state_vector.tolist()
        
        return result
    
    def _record_agent_message(self, task_id: str, from_agent: str, to_agent: str, 
                           message: str):
        """Record agent message for loop detection"""
        watchdog.record_message(task_id, from_agent, to_agent, message)
        
        # Also trace the message
        with SpanContext(SpanType.AGENT_MESSAGE, f"message_{from_agent}_to_{to_agent}",
                       agent_id=from_agent) as msg_span:
            msg_span.set_tag("from_agent", from_agent)
            msg_span.set_tag("to_agent", to_agent)
            msg_span.set_tag("message_length", len(message))
    
    def _update_agent_states(self, task_id: str, agent_id: str, state_vector: List[float]):
        """Update agent states for misalignment calculation"""
        metrics = self.active_tasks.get(task_id)
        if not metrics:
            return
        
        # Store state vector (in real implementation, this would be persistent)
        if not hasattr(metrics, '_agent_states'):
            metrics._agent_states = {}
        metrics._agent_states[agent_id] = state_vector
        
        # Calculate misalignment with other agents
        self._calculate_misalignment_scores(task_id)
    
    def _calculate_misalignment_scores(self, task_id: str):
        """Calculate pairwise misalignment scores"""
        metrics = self.active_tasks.get(task_id)
        if not metrics or not hasattr(metrics, '_agent_states'):
            return
        
        states = metrics._agent_states
        agent_ids = list(states.keys())
        
        import numpy as np
        
        # Simple covariance estimation (in real implementation, use historical data)
        all_states = np.array(list(states.values()))
        covariance_matrix = np.cov(all_states.T) if len(all_states) > 1 else np.eye(len(all_states[0]))
        
        # Calculate pairwise misalignment
        for i, agent_a in enumerate(agent_ids):
            for j, agent_b in enumerate(agent_ids):
                if i >= j:  # Avoid duplicates
                    continue
                
                state_a = np.array(states[agent_a])
                state_b = np.array(states[agent_b])
                
                # Use the misalignment calculation from metrics spec
                try:
                    # Simplified version for demo
                    cosine_sim = np.dot(state_a, state_b) / (
                        np.linalg.norm(state_a) * np.linalg.norm(state_b)
                    )
                    misalignment = 1.0 - cosine_sim
                    misalignment = max(0.0, min(1.0, misalignment))
                    
                    pair_key = f"{agent_a}_vs_{agent_b}"
                    metrics.misalignment_scores[pair_key] = misalignment
                    
                except Exception as e:
                    logger.warning(f"Failed to calculate misalignment for {agent_a}-{agent_b}: {e}")
    
    def _collect_final_metrics(self, task_id: str, task_span):
        """Collect final metrics from watchdog and tracing"""
        metrics = self.active_tasks.get(task_id)
        if not metrics:
            return
        
        # Get watchdog violations for this task
        all_violations = watchdog.get_violations()
        violations = [v for v in all_violations if v.task_id == task_id]
        
        # Count rollbacks and human interventions
        for violation in violations:
            if violation.violation_type == WatchdogViolation.CASCADE_DETECTED:
                metrics.cascade_size = violation.details.get("cascade_size", 0)
            elif violation.violation_type == WatchdogViolation.TURN_LIMIT_EXCEEDED:
                metrics.human_intervention_count += 1
        
        # Get task summary from watchdog
        task_summary = watchdog.get_task_summary(task_id)
        if task_summary:
            metrics.total_turns = task_summary.get("total_turns", 0)
            metrics.branching_factor = self._calculate_branching_factor(task_id)
            metrics.retry_index = self._calculate_retry_index(task_id)
        
        # Add metrics to span
        task_span.set_tag("total_turns", metrics.total_turns)
        task_span.set_tag("cascade_size", metrics.cascade_size)
        task_span.set_tag("misalignment_count", len(metrics.misalignment_scores))
        task_span.set_tag("violation_count", len(violations))
    
    def _calculate_branching_factor(self, task_id: str) -> float:
        """Calculate branching factor from task execution"""
        # Simplified calculation - in real implementation, analyze trace data
        violations = watchdog.get_violations(task_id=task_id)
        cascade_violations = [v for v in violations if v.violation_type == WatchdogViolation.CASCADE_DETECTED]
        
        if not cascade_violations:
            return 0.0
        
        # Average cascade size as proxy for branching factor
        total_affected = sum(v.details.get("cascade_size", 0) for v in cascade_violations)
        return total_affected / len(cascade_violations) if cascade_violations else 0.0
    
    def _calculate_retry_index(self, task_id: str) -> float:
        """Calculate retry index from task execution"""
        # Simplified calculation - in real implementation, count actual retries
        violations = watchdog.get_violations(task_id=task_id)
        timeout_violations = [v for v in violations if v.violation_type == WatchdogViolation.AGENT_TIMEOUT]
        
        return len(timeout_violations)  # Simplified proxy
    
    def _get_current_task_id(self) -> str:
        """Get current task ID (simplified for demo)"""
        # In real implementation, this would come from context
        return list(self.active_tasks.keys())[-1] if self.active_tasks else "unknown"
    
    def enable_fault_injection(self, flaky_tool_rate: float = 0.1):
        """Enable fault injection for testing"""
        self._fault_injection_enabled = True
        self._flaky_tool_rate = flaky_tool_rate
        logger.info(f"Fault injection enabled - flaky tool rate: {flaky_tool_rate}")
    
    def disable_fault_injection(self):
        """Disable fault injection"""
        self._fault_injection_enabled = False
        logger.info("Fault injection disabled")
    
    def get_task_metrics(self, task_id: str) -> Optional[TaskMetrics]:
        """Get metrics for a specific task"""
        return self.active_tasks.get(task_id)
    
    def get_all_metrics(self) -> List[TaskMetrics]:
        """Get metrics for all completed tasks"""
        return list(self.active_tasks.values())


# Global task runner instance
task_runner = SwarmTaskRunner(enable_enforcement=False)  # Silent recording mode
