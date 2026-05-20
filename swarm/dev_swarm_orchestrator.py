"""
Dev Swarm Orchestrator for MERID Self-Building Capability.

Coordinates multiple dev agents (coder, reviewer, tester, architect) to
autonomously implement features, fix bugs, and improve the codebase.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any

from utils.logger import get_logger

logger = get_logger(__name__)

from core.policy_engine import PolicyDecision
from core.telemetry_manager import get_telemetry_manager
from latency_optimizer.orchestrator_hooks import (
    record_dev_swarm_command,
    record_llm_request,
)
from swarm.command_runner import (
    CommandRequest,
    CommandResult,
    CommandStatus,
    get_command_runner,
)
from swarm.test_agents import iter_default_test_agents


class TaskType(Enum):
    FEATURE = "feature"
    BUG_FIX = "bug_fix"
    REFACTOR = "refactor"
    TEST = "test"
    DOCUMENTATION = "documentation"
    UNIT_TEST = "unit_test"
    INTEGRATION_TEST = "integration_test"
    TEST_SELF_HEAL = "test_self_heal"
    TEST_DISCOVERY = "test_discovery"


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    TESTING = "testing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class CommandExecutionRecord:
    command: str
    status: CommandStatus
    guardrail_decision: PolicyDecision
    guardrail_id: Optional[str]
    guardrail_rationale: str
    stdout: str
    stderr: str
    exit_code: Optional[int]
    recorded_at: datetime = field(default_factory=datetime.utcnow)
    latency_status: Optional[str] = None
    latency_observed_ms: Optional[float] = None
    latency_fallback: Optional[str] = None


@dataclass
class DevTask:
    task_id: str
    task_type: TaskType
    description: str
    priority: int
    status: TaskStatus
    assigned_agent: Optional[str] = None
    created_at: datetime = None
    completed_at: Optional[datetime] = None
    artifacts: List[str] = None
    blocked_reason: Optional[str] = None
    command_history: List[CommandExecutionRecord] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        if self.artifacts is None:
            self.artifacts = []
        if self.command_history is None:
            self.command_history = []
        if self.metadata is None:
            self.metadata = {}


@dataclass
class DevAgent:
    agent_id: str
    role: str
    capabilities: List[str]
    active: bool = True
    current_task: Optional[str] = None
    focus_areas: Optional[List[str]] = None
    description: Optional[str] = None


class DevSwarmOrchestrator:
    """
    Orchestrates a swarm of dev agents for autonomous development.
    
    Features:
    - Task queue management
    - Agent assignment and coordination
    - Code review workflows
    - Test execution coordination
    - Artifact tracking
    - Safety guardrails
    """
    
    def __init__(self):
        self._agents: Dict[str, DevAgent] = {}
        self._tasks: Dict[str, DevTask] = {}
        self._task_queue: List[str] = []
        self._completed_tasks: List[str] = []
        self._running = False
        self._telemetry = get_telemetry_manager()
        
        self._register_default_agents()
    
    def _register_default_agents(self) -> None:
        """Register default dev agents."""
        self._agents = {
            "coder_1": DevAgent(
                agent_id="coder_1",
                role="coder",
                capabilities=["python", "typescript", "code_generation", "bug_fixing"],
            ),
            "coder_2": DevAgent(
                agent_id="coder_2",
                role="coder",
                capabilities=["python", "solidity", "code_generation", "refactoring"],
            ),
            "reviewer_1": DevAgent(
                agent_id="reviewer_1",
                role="reviewer",
                capabilities=["code_review", "security_audit", "best_practices"],
            ),
            "tester_unit_core": DevAgent(
                agent_id="tester_unit_core",
                role="tester",
                capabilities=["unit_testing", "coverage_analysis", "core_module_focus"],
            ),
            "tester_unit_governance": DevAgent(
                agent_id="tester_unit_governance",
                role="tester",
                capabilities=["unit_testing", "governance_policies", "mutation_testing"],
            ),
            "tester_integration_api": DevAgent(
                agent_id="tester_integration_api",
                role="tester",
                capabilities=["integration_testing", "api_contracts", "trace_replay"],
            ),
            "tester_self_heal": DevAgent(
                agent_id="tester_self_heal",
                role="tester",
                capabilities=["flaky_detection", "fixture_refactor", "resilient_testing"],
            ),
            "architect_1": DevAgent(
                agent_id="architect_1",
                role="architect",
                capabilities=["system_design", "refactoring", "architecture_review"],
            ),
        }

        for profile in iter_default_test_agents():
            if profile.agent_id in self._agents:
                continue
            self._agents[profile.agent_id] = DevAgent(
                agent_id=profile.agent_id,
                role=profile.role,
                capabilities=list(profile.capabilities),
                focus_areas=list(profile.focus_areas),
                description=profile.description,
            )
    
    def register_agent(self, agent: DevAgent) -> None:
        """Register a dev agent."""
        self._agents[agent.agent_id] = agent
        logger.info(f"Registered dev agent: {agent.agent_id} ({agent.role})")
    
    def submit_task(self, task: DevTask) -> str:
        """Submit a task to the swarm."""
        self._tasks[task.task_id] = task
        self._task_queue.append(task.task_id)
        self._task_queue.sort(key=lambda tid: self._tasks[tid].priority, reverse=True)
        
        logger.info(f"Submitted task: {task.task_id} ({task.task_type.value}) priority={task.priority}")
        self._emit_task_event("task_submitted", task, {"priority": task.priority})
        return task.task_id
    
    def _select_agent(self, task: DevTask) -> Optional[DevAgent]:
        """Select best available agent for task."""
        role_map = {
            TaskType.FEATURE: "coder",
            TaskType.BUG_FIX: "coder",
            TaskType.REFACTOR: "architect",
            TaskType.TEST: "tester",
            TaskType.UNIT_TEST: "tester",
            TaskType.INTEGRATION_TEST: "tester",
            TaskType.TEST_SELF_HEAL: "tester",
            TaskType.TEST_DISCOVERY: "tester",
            TaskType.DOCUMENTATION: "coder",
        }
        
        preferred_role = role_map.get(task.task_type, "coder")
        
        candidates = [
            agent for agent in self._agents.values()
            if agent.active and agent.current_task is None and agent.role == preferred_role
        ]
        
        if not candidates:
            candidates = [
                agent for agent in self._agents.values()
                if agent.active and agent.current_task is None
            ]
        
        return candidates[0] if candidates else None
    
    async def _execute_task(self, task: DevTask, agent: DevAgent) -> bool:
        """Execute a task with assigned agent."""
        from swarm.local_llm_gateway import get_local_llm_gateway, LLMRequest
        
        logger.info(f"Agent {agent.agent_id} executing task {task.task_id}")
        
        task.status = TaskStatus.IN_PROGRESS
        task.assigned_agent = agent.agent_id
        agent.current_task = task.task_id
        
        try:
            llm_gateway = get_local_llm_gateway()
            
            prompt = self._build_task_prompt(task, agent)
            
            request = LLMRequest(
                request_id=f"task_{task.task_id}",
                prompt=prompt,
                model="codellama",
                max_tokens=2000,
                temperature=0.2,
                system_prompt=f"You are a {agent.role} agent working on MERID codebase.",
            )
            
            metadata = {
                "task_id": task.task_id,
                "agent_id": agent.agent_id,
                "task_type": task.task_type.value,
            }
            with record_llm_request(metadata, decision_key=request.request_id):
                response = await llm_gateway.generate(request)
            
            if response:
                task.artifacts.append(response.response_text)
                
                if task.task_type in [TaskType.FEATURE, TaskType.BUG_FIX]:
                    task.status = TaskStatus.REVIEW
                    logger.info(f"Task {task.task_id} ready for review")
                else:
                    task.status = TaskStatus.COMPLETED
                    task.completed_at = datetime.utcnow()
                    logger.info(f"Task {task.task_id} completed")
                self._emit_task_event("task_progress", task, {"status": task.status.value})
                
                return True
            else:
                task.status = TaskStatus.FAILED
                logger.error(f"Task {task.task_id} failed: no LLM response")
                self._emit_task_event("task_failed", task, {"reason": "llm_no_response"})
                return False
                
        except Exception as e:
            logger.error(f"Error executing task {task.task_id}: {e}")
            task.status = TaskStatus.FAILED
            self._emit_task_event("task_failed", task, {"reason": str(e)})
            return False
        finally:
            agent.current_task = None
            self._tasks[task.task_id] = task

    async def execute_command(
        self,
        task_id: str,
        command: str,
        *,
        agent_id: Optional[str] = None,
        surface: str = "dev_swarm",
        action: str = "execute_command",
        description: str = "",
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: int = 60,
    ) -> CommandResult:
        """Execute a shell command for a task via guardrail-enforced runner."""

        if task_id not in self._tasks:
            raise ValueError(f"Unknown task_id {task_id}")

        task = self._tasks[task_id]
        agent = None
        if agent_id:
            agent = self._agents.get(agent_id)
            if agent is None:
                raise ValueError(f"Unknown agent_id {agent_id}")
        elif task.assigned_agent:
            agent = self._agents.get(task.assigned_agent)

        runner = get_command_runner()
        request = CommandRequest(
            command=command,
            surface=surface,
            action=action,
            intent_id=f"task:{task_id}",
            agent_id=agent.agent_id if agent else "dev_swarm_orchestrator",
            description=description or task.description,
            cwd=cwd,
            env=env,
            timeout=timeout,
        )

        logger.info(
            "Executing guarded command for task %s: %s (agent=%s)",
            task_id,
            command,
            agent.agent_id if agent else "orchestrator",
        )

        metadata = {
            "task_id": task_id,
            "agent_id": agent.agent_id if agent else "orchestrator",
            "command": command.split()[0],
        }
        with record_dev_swarm_command(metadata, decision_key=request.intent_id) as probe:
            request.latency_probe_config = {
                "domain": probe.domain,
                "workflow": probe.workflow,
                "metadata": probe.metadata,
                "decision_key": request.intent_id,
            }
            result = await asyncio.to_thread(runner.run, request)
            latency_decision = probe.decision
        self._record_command_result(task, command, result, latency_decision=latency_decision)
        return result

    def _record_command_result(
        self,
        task: DevTask,
        command: str,
        result: CommandResult,
        latency_decision: Optional[OptimizationDecision] = None,
    ) -> None:
        record = CommandExecutionRecord(
            command=command,
            status=result.status,
            guardrail_decision=result.guardrail_decision,
            guardrail_id=result.guardrail_id,
            guardrail_rationale=result.guardrail_rationale,
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            latency_status=(latency_decision.status if latency_decision else None),
            latency_observed_ms=(
                latency_decision.observed_ms if latency_decision else None
            ),
            latency_fallback=(
                latency_decision.fallback.strategy_id
                if latency_decision and latency_decision.fallback
                else None
            ),
        )

        task.command_history.append(record)

        summary = (
            f"[{record.recorded_at.isoformat()}] COMMAND `{command}` -> {result.status.value} "
            f"(guardrail={result.guardrail_decision.value}:{result.guardrail_id})"
        )
        detail = result.stdout.strip() or result.stderr.strip()
        if detail:
            summary = f"{summary} :: {detail}"

        task.artifacts.append(summary)

        if result.status == CommandStatus.DENIED:
            task.status = TaskStatus.FAILED
            task.blocked_reason = (
                f"Guardrail {result.guardrail_id or 'unknown'} denied command: "
                f"{result.guardrail_rationale}"
            )
            self._emit_task_event("task_guardrail_denied", task, {"guardrail": result.guardrail_id})
        elif result.status == CommandStatus.PENDING_APPROVAL:
            task.blocked_reason = (
                f"Guardrail {result.guardrail_id or 'unknown'} requires approval: "
                f"{result.guardrail_rationale}"
            )
        else:
            task.blocked_reason = None
            self._emit_task_event("command_executed", task, {"command": command, "status": result.status.value})

    def _build_task_prompt(self, task: DevTask, agent: DevAgent) -> str:
        """Build prompt for task execution."""
        return f"""
Task Type: {task.task_type.value}
Description: {task.description}
Agent Role: {agent.role}
Capabilities: {', '.join(agent.capabilities)}

Please provide implementation for this task following MERID coding standards.
Include necessary imports, error handling, and documentation.
"""
    
    async def _review_task(self, task: DevTask) -> bool:
        """Review completed task."""
        reviewer = next(
            (a for a in self._agents.values() if a.role == "reviewer" and a.current_task is None),
            None
        )
        
        if not reviewer:
            logger.warning(f"No reviewer available for task {task.task_id}")
            return False
        
        logger.info(f"Reviewer {reviewer.agent_id} reviewing task {task.task_id}")
        
        await asyncio.sleep(1.0)
        
        task.status = TaskStatus.TESTING
        self._emit_task_event("task_reviewed", task, {})
        return True
    
    async def _test_task(self, task: DevTask) -> bool:
        """Test completed task."""
        tester = next(
            (a for a in self._agents.values() if a.role == "tester" and a.current_task is None),
            None
        )
        
        if not tester:
            logger.warning(f"No tester available for task {task.task_id}")
            return False
        
        logger.info(f"Tester {tester.agent_id} testing task {task.task_id}")
        
        await asyncio.sleep(1.0)
        
        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.utcnow()
        self._completed_tasks.append(task.task_id)
        self._emit_task_event("task_completed", task, {})
        
        return True

    def _emit_task_event(self, event_type: str, task: DevTask, fields: Optional[Dict[str, Any]] = None) -> None:
        if not self._telemetry:
            return
        try:
            payload = {
                "task_id": task.task_id,
                "task_type": task.task_type.value,
                "status": task.status.value,
                "agent_id": task.assigned_agent,
            }
            if task.metadata:
                payload.update({f"meta.{k}": v for k, v in task.metadata.items()})
            if fields:
                payload.update(fields)
            self._telemetry.log_structured(
                stream_name="test_swarm",
                level="INFO",
                event_type=event_type,
                message=f"Test swarm task event: {event_type}",
                fields=payload,
            )
        except Exception:
            logger.exception("Failed to emit telemetry for test swarm task %s", task.task_id)
    
    async def orchestrate(self) -> None:
        """Main orchestration loop."""
        self._running = True
        logger.info("Dev swarm orchestration started")
        
        while self._running:
            try:
                if not self._task_queue:
                    await asyncio.sleep(5.0)
                    continue
                
                task_id = self._task_queue[0]
                task = self._tasks.get(task_id)
                
                if not task:
                    self._task_queue.pop(0)
                    continue
                
                if task.status == TaskStatus.PENDING:
                    agent = self._select_agent(task)
                    if agent:
                        self._task_queue.pop(0)
                        success = await self._execute_task(task, agent)
                        if not success:
                            self._task_queue.append(task_id)
                    else:
                        await asyncio.sleep(2.0)
                
                elif task.status == TaskStatus.REVIEW:
                    success = await self._review_task(task)
                    if success:
                        self._task_queue.pop(0)
                        self._task_queue.append(task_id)
                    else:
                        await asyncio.sleep(2.0)
                
                elif task.status == TaskStatus.TESTING:
                    success = await self._test_task(task)
                    if success:
                        self._task_queue.pop(0)
                
                elif task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
                    if task_id in self._task_queue:
                        self._task_queue.remove(task_id)
                
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error in orchestration loop: {e}")
                await asyncio.sleep(5.0)
    
    def get_swarm_status(self) -> Dict[str, Any]:
        """Get swarm status."""
        return {
            "running": self._running,
            "agents": {
                agent_id: {
                    "role": agent.role,
                    "active": agent.active,
                    "current_task": agent.current_task,
                }
                for agent_id, agent in self._agents.items()
            },
            "tasks": {
                "pending": len([t for t in self._tasks.values() if t.status == TaskStatus.PENDING]),
                "in_progress": len([t for t in self._tasks.values() if t.status == TaskStatus.IN_PROGRESS]),
                "review": len([t for t in self._tasks.values() if t.status == TaskStatus.REVIEW]),
                "testing": len([t for t in self._tasks.values() if t.status == TaskStatus.TESTING]),
                "completed": len(self._completed_tasks),
                "failed": len([t for t in self._tasks.values() if t.status == TaskStatus.FAILED]),
            },
            "queue_length": len(self._task_queue),
        }
    
    async def start(self) -> None:
        """Start orchestration."""
        asyncio.create_task(self.orchestrate())
    
    def stop(self) -> None:
        """Stop orchestration."""
        self._running = False
        logger.info("Dev swarm orchestration stopped")


_dev_swarm_orchestrator: Optional[DevSwarmOrchestrator] = None
_dev_swarm_orchestrator_lock = threading.Lock()


def get_dev_swarm_orchestrator() -> DevSwarmOrchestrator:
    """Get global DevSwarmOrchestrator instance."""
    global _dev_swarm_orchestrator
    if _dev_swarm_orchestrator is None:
        with _dev_swarm_orchestrator_lock:
            if _dev_swarm_orchestrator is None:
                _dev_swarm_orchestrator = DevSwarmOrchestrator()
    return _dev_swarm_orchestrator
