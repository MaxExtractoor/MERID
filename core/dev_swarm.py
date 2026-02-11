"""DevSwarm Autonomous Development System for MERID.

Multi-agent system that automates code generation, testing, and CI fixes
using LLMs (DeepSeek, Claude, etc.) and agent frameworks.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from enum import Enum
import asyncio
import subprocess
import json
import os
import time
import uuid
import structlog

logger = structlog.get_logger(__name__)


class DevAgentRole(Enum):
    """Roles in the DevSwarm."""
    PLANNER = "planner"
    CODER = "coder"
    TESTER = "tester"
    REVIEWER = "reviewer"
    AUDITOR = "auditor"


@dataclass
class DevAgent:
    """A development agent in the swarm."""
    name: str
    role: DevAgentRole
    llm_model: str
    system_prompt: str
    tools: List[Callable]
    max_iterations: int = 5
    timeout_seconds: Optional[int] = None


@dataclass
class DevTask:
    """A development task for the swarm."""
    description: str
    target_files: List[str]
    success_criteria: str
    priority: int = 1
    estimated_effort: str = "medium"  # small, medium, large
    timeout_seconds: Optional[int] = None
    task_id: str = field(default_factory=lambda: f"task-{uuid.uuid4().hex[:8]}")
    status: str = "pending"
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    cost_usd: float = 0.0


@dataclass
class SwarmConfig:
    """Configuration for a DevSwarm instance."""
    max_concurrent_tasks: int = 5
    max_concurrent_agents: int = 10
    default_task_timeout: int = 300
    default_agent_timeout: int = 60
    max_daily_cost_usd: float = 50.0
    enable_timeouts: bool = True
    enable_cost_tracking: bool = True
    enable_metrics: bool = True


# Persistence availability flag
try:
    from core.dev_swarm_persistence import DevSwarmPersistence
    PERSISTENCE_AVAILABLE = True
except ImportError:
    PERSISTENCE_AVAILABLE = False


class DevSwarm:
    """MERID Autonomous Development Swarm."""

    # Cost estimates per effort level (credits)
    EFFORT_COST = {"small": 5.0, "medium": 15.0, "large": 40.0}

    def __init__(
        self,
        agents: List[DevAgent] = None,
        config: Optional[SwarmConfig] = None,
        enable_persistence: bool = False,
        enable_timeouts: bool = None,
        max_concurrent_tasks: int = None,
        max_concurrent_agents: int = None,
    ):
        self.config = config or SwarmConfig()
        self.agents = agents or []
        self.task_history: List[Any] = []  # List of DevTask objects
        self.active_tasks: Dict[str, DevTask] = {}
        self.logger = logger.bind(component="DevSwarm")

        # Allow direct overrides for convenience
        if enable_timeouts is not None:
            self.config.enable_timeouts = enable_timeouts
        if max_concurrent_tasks is not None:
            self.config.max_concurrent_tasks = max_concurrent_tasks
        if max_concurrent_agents is not None:
            self.config.max_concurrent_agents = max_concurrent_agents

        # Cost tracking
        self.daily_cost_usd: float = 0.0
        self.cost_reset_time: float = time.time()

        # State
        self._shutdown: bool = False
        self.is_paused: bool = False

        # Persistence
        self.persistence = None
        if enable_persistence and PERSISTENCE_AVAILABLE:
            try:
                from core.dev_swarm_persistence import DevSwarmPersistence as _Persist
                self.persistence = _Persist()
            except Exception:
                self.persistence = None

        self._load_state()

    def _load_state(self) -> None:
        """Load persisted state if persistence is available."""
        if self.persistence is None:
            return
        try:
            tasks = self.persistence.load_tasks()
            for t in tasks:
                self.task_history.append(t)
            metadata = self.persistence.load_metadata()
            if metadata:
                self.daily_cost_usd = metadata.get("daily_cost_usd", 0.0)
        except Exception as exc:
            self.logger.debug("load_state_failed", error=str(exc))

    def register_agent(self, agent: DevAgent) -> None:
        """Register an agent to the swarm."""
        self.agents.append(agent)
        self.logger.info("agent_registered", name=agent.name, role=agent.role.value)

    def pause(self) -> bool:
        """Pause the swarm — no new tasks will be accepted.

        Returns True if the swarm was running and is now paused,
        False if it was already paused.
        """
        if self.is_paused:
            return False
        self.is_paused = True
        self.logger.info("swarm_paused")
        return True

    def resume(self) -> bool:
        """Resume the swarm.

        Returns True if the swarm was paused and is now running,
        False if it was already running.
        """
        if not self.is_paused:
            return False
        self.is_paused = False
        self.logger.info("swarm_resumed")
        return True

    async def shutdown(self, timeout: float = 10.0) -> None:
        """Gracefully shut down the swarm."""
        self._shutdown = True
        if self.active_tasks:
            try:
                await asyncio.wait_for(self._wait_for_active_tasks(), timeout=timeout)
            except asyncio.TimeoutError:
                self.logger.warning("shutdown_timeout", remaining=len(self.active_tasks))
        self.logger.info("swarm_shutdown")

    async def _wait_for_active_tasks(self) -> None:
        """Wait for active tasks to complete."""
        while self.active_tasks:
            await asyncio.sleep(0.1)

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel an active task."""
        task = self.active_tasks.pop(task_id, None)
        if task:
            task.status = "cancelled"
            task.completed_at = time.time()
            self.task_history.append(task)
            return True
        return False

    def get_stats(self) -> Dict[str, Any]:
        """Get swarm statistics."""
        completed = sum(
            1 for t in self.task_history
            if (getattr(t, 'status', None) if hasattr(t, 'status') else t.get('status')) == 'completed'
        )
        failed = sum(
            1 for t in self.task_history
            if (getattr(t, 'status', None) if hasattr(t, 'status') else t.get('status')) in ('failed', 'timeout')
        )
        total = len(self.task_history)
        success_rate = completed / total if total > 0 else 0

        # Average duration for completed tasks
        durations = []
        for t in self.task_history:
            sa = getattr(t, 'started_at', None) if hasattr(t, 'started_at') else None
            ca = getattr(t, 'completed_at', None) if hasattr(t, 'completed_at') else None
            if sa and ca:
                durations.append(ca - sa)
        avg_duration = sum(durations) / len(durations) if durations else 0

        return {
            "total_tasks": total,
            "active_tasks": len(self.active_tasks),
            "agents": len(self.agents),
            "daily_cost_usd": self.daily_cost_usd,
            "is_paused": self.is_paused,
            "is_shutdown": self._shutdown,
            "completed": completed,
            "failed": failed,
            "success_rate": success_rate,
            "avg_duration_seconds": avg_duration,
        }

    def compact_storage(self, keep_recent: int = 1000) -> bool:
        """Compact persistence storage."""
        if self.persistence is None:
            return False
        try:
            self.persistence.compact(keep_recent=keep_recent)
            return True
        except Exception:
            return False

    def get_storage_stats(self) -> Dict[str, Any]:
        """Get persistence storage statistics."""
        if self.persistence is None:
            return {"persistence_enabled": False}
        try:
            stats = self.persistence.get_stats()
            stats["persistence_enabled"] = True
            return stats
        except Exception:
            return {"persistence_enabled": True, "error": "stats unavailable"}

    async def _execute_task_pipeline(self, task: DevTask) -> Dict[str, Any]:
        """Execute the full agent pipeline for a task."""
        results = {"phases": [], "task_id": task.task_id}

        planner = self._find_agent(DevAgentRole.PLANNER)
        coder = self._find_agent(DevAgentRole.CODER)
        tester = self._find_agent(DevAgentRole.TESTER)
        reviewer = self._find_agent(DevAgentRole.REVIEWER)

        if planner:
            plan = await self._run_agent_phase(planner, task, {})
            results["phases"].append({"agent": planner.name, "phase": "planning", "result": plan})

        if coder:
            code_result = await self._run_agent_phase(coder, task, results)
            results["phases"].append({"agent": coder.name, "phase": "coding", "result": code_result})

        if tester:
            test_result = await self._run_agent_phase(tester, task, results)
            results["phases"].append({"agent": tester.name, "phase": "testing", "result": test_result})

            if not test_result.get("passed", True) and coder and coder.max_iterations > 0:
                self.logger.warning("tests_failed", retrying=True)
                coder.max_iterations -= 1
                code_result = await self._run_agent_phase(coder, task, results)
                results["phases"].append({"agent": coder.name, "phase": "coding_retry", "result": code_result})

        if reviewer:
            review_result = await self._run_agent_phase(reviewer, task, results)
            results["phases"].append({"agent": reviewer.name, "phase": "review", "result": review_result})

        task.status = "completed"
        task.completed_at = time.time()
        task.result = results
        results["status"] = "completed"
        return results

    async def execute_task(self, task: DevTask) -> DevTask:
        """Execute a development task through the agent pipeline."""
        if self._shutdown:
            task.status = "rejected"
            task.error = "Swarm is shut down"
            self.task_history.append(task)
            return task
        if self.is_paused:
            task.status = "failed"
            task.error = "Swarm is paused"
            self.task_history.append(task)
            return task
        if len(self.active_tasks) >= self.config.max_concurrent_tasks:
            task.status = "failed"
            task.error = "Max concurrent tasks limit"
            self.task_history.append(task)
            return task

        # Daily cost reset (24h window)
        if time.time() - self.cost_reset_time > 86400:
            self.daily_cost_usd = 0.0
            self.cost_reset_time = time.time()

        # Budget gate — check daily cost limit
        estimated_cost = self.EFFORT_COST.get(task.estimated_effort, 15.0)
        if self.config.enable_cost_tracking and self.daily_cost_usd >= self.config.max_daily_cost_usd:
            task.status = "failed"
            task.error = "Daily cost budget exceeded"
            self.task_history.append(task)
            return task

        # Register as active and mark started
        task.status = "running"
        task.started_at = time.time()
        self.active_tasks[task.task_id] = task

        self.logger.info("task_started", description=task.description[:50])
        if self.config.enable_cost_tracking:
            try:
                from core.agent_credit_ledger import get_credit_ledger
                ledger = get_credit_ledger()
                for agent in self.agents:
                    if not ledger.check_budget(agent.name, estimated_cost):
                        self.logger.warning(
                            "agent_low_budget",
                            agent=agent.name,
                            cost=estimated_cost,
                        )
            except Exception:
                pass  # ledger module not available or check failed — allow execution

        # Execute pipeline
        effective_timeout = task.timeout_seconds or self.config.default_task_timeout
        try:
            if self.config.enable_timeouts:
                try:
                    results = await asyncio.wait_for(
                        self._execute_task_pipeline(task),
                        timeout=effective_timeout,
                    )
                except asyncio.TimeoutError:
                    task.status = "timeout"
                    task.error = f"Task exceeded timeout of {effective_timeout}s"
                    task.completed_at = time.time()
                    return task
            else:
                results = await self._execute_task_pipeline(task)

            # Deduct credits
            try:
                from core.agent_credit_ledger import get_credit_ledger
                ledger = get_credit_ledger()
                for phase in results.get("phases", []):
                    agent_name = phase.get("agent", "")
                    if agent_name:
                        per_agent_cost = estimated_cost / max(len(results["phases"]), 1)
                        ledger.deduct(agent_name, per_agent_cost, reason=task.description[:60])
            except Exception as exc:
                self.logger.debug("credit_deduction_skipped", error=str(exc))

        except asyncio.CancelledError:
            task.status = "cancelled"
            task.error = "Task was cancelled"
            task.completed_at = time.time()
            return task
        except Exception as exc:
            task.status = "failed"
            task.error = str(exc)
            task.completed_at = time.time()
            self.logger.error("execute_task_failed", error=str(exc))
            return task
        finally:
            self.active_tasks.pop(task.task_id, None)
            # Avoid duplicates — _execute_task_pipeline.finally also appends
            if task not in self.task_history:
                self.task_history.append(task)

        # Track cost
        task.cost_usd = estimated_cost
        if self.config.enable_cost_tracking:
            self.daily_cost_usd += estimated_cost

        # Persist task and metadata
        if self.persistence:
            try:
                self.persistence.save_task(task)
                self.persistence.save_metadata({
                    "daily_cost_usd": self.daily_cost_usd,
                    "cost_reset_time": self.cost_reset_time,
                })
            except Exception as exc:
                self.logger.debug("persist_after_execute_failed", error=str(exc))

        return task

    def _find_agent(self, role: DevAgentRole) -> Optional[DevAgent]:
        """Find an agent by role."""
        return next((a for a in self.agents if a.role == role), None)

    async def _run_agent_phase(
        self,
        agent: DevAgent,
        task: DevTask,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a single agent phase."""
        self.logger.info(
            "agent_phase_start",
            agent=agent.name,
            role=agent.role.value,
            task=task.description[:30]
        )

        prompt = self._build_agent_prompt(agent, task, context)

        try:
            if self.config.enable_timeouts:
                try:
                    result = await asyncio.wait_for(
                        self._execute_agent_with_tools(agent, task, context),
                        timeout=self.config.default_agent_timeout,
                    )
                except asyncio.TimeoutError:
                    return {"agent": agent.name, "status": "timeout", "error": f"Agent {agent.name} timed out"}
            else:
                result = await self._execute_agent_with_tools(agent, task, context)
        except Exception as exc:
            return {"agent": agent.name, "status": "error", "error": str(exc)}

        return {
            "agent": agent.name,
            "role": agent.role.value,
            "prompt": prompt,
            "result": result
        }

    def _build_agent_prompt(self, agent: DevAgent, task: DevTask, context: Dict) -> str:
        """Build prompt for an agent."""
        return f"""{agent.system_prompt}

Task: {task.description}
Target Files: {', '.join(task.target_files)}
Success Criteria: {task.success_criteria}

Context: {json.dumps(context, indent=2)}

Execute your role and return structured output.
"""

    async def _execute_agent_with_tools(
        self, agent: DevAgent, task: DevTask, context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute tools available to the agent."""
        results = {}
        for tool in agent.tools:
            try:
                if callable(tool):
                    result = tool(task)
                    results[tool.__name__] = result
            except Exception as e:
                results[tool.__name__] = {"error": str(e)}
        return results

    # Alias for backward compatibility
    _execute_agent_tools = _execute_agent_with_tools


# Tool functions for agents
def analyze_coverage(task: DevTask) -> Dict[str, Any]:
    """Analyze test coverage for target files."""
    try:
        result = subprocess.run(
            ["coverage", "report", "--include=*.py"],
            capture_output=True,
            text=True,
            cwd=os.getcwd()
        )
        return {
            "command": "coverage report",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except Exception as e:
        return {"error": str(e)}


def run_pytest(task: DevTask) -> Dict[str, Any]:
    """Run pytest on target files."""
    try:
        test_files = [f"tests/**/test_{os.path.basename(f)}" for f in task.target_files]
        result = subprocess.run(
            ["pytest", "-v", "--tb=short"] + test_files,
            capture_output=True,
            text=True,
            cwd=os.getcwd()
        )
        return {
            "command": "pytest",
            "stdout": result.stdout[-5000:],  # Last 5000 chars
            "stderr": result.stderr[-2000:],
            "returncode": result.returncode,
            "passed": result.returncode == 0
        }
    except Exception as e:
        return {"error": str(e)}


def run_linters(task: DevTask) -> Dict[str, Any]:
    """Run linters on target files."""
    results = {}
    
    # Ruff
    try:
        ruff_result = subprocess.run(
            ["ruff", "check"] + task.target_files,
            capture_output=True,
            text=True
        )
        results["ruff"] = {
            "passed": ruff_result.returncode == 0,
            "output": ruff_result.stdout
        }
    except Exception as e:
        results["ruff"] = {"error": str(e)}
    
    # MyPy
    try:
        mypy_result = subprocess.run(
            ["mypy"] + task.target_files,
            capture_output=True,
            text=True
        )
        results["mypy"] = {
            "passed": mypy_result.returncode == 0,
            "output": mypy_result.stdout
        }
    except Exception as e:
        results["mypy"] = {"error": str(e)}
    
    return results


def get_git_status(task: DevTask) -> Dict[str, Any]:
    """Get git repository status."""
    try:
        status = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True,
            text=True
        )
        diff = subprocess.run(
            ["git", "diff", "--stat"],
            capture_output=True,
            text=True
        )
        return {
            "modified_files": status.stdout.strip().split("\n") if status.stdout else [],
            "diff_stats": diff.stdout
        }
    except Exception as e:
        return {"error": str(e)}


# Pre-configured MERID DevSwarm Agents
MERID_DEV_AGENTS = [
    DevAgent(
        name="CoveragePlanner",
        role=DevAgentRole.PLANNER,
        llm_model="deepseek-chat",
        system_prompt="""You are a test coverage planning expert.
        Analyze coverage gaps and create a plan to achieve target coverage.
        Focus on MERID Tier 2 modules (core/, trading/router, trading/spectator).
        Output: List of uncovered lines and test implementation strategy.""",
        tools=[analyze_coverage],
        max_iterations=3
    ),
    DevAgent(
        name="PyTestCoder",
        role=DevAgentRole.CODER,
        llm_model="deepseek-chat",
        system_prompt="""You are a pytest expert for MERID trading systems.
        Write comprehensive tests including edge cases, async tests, and mocks.
        Use pytest-asyncio, pytest-mock, and follow MERID test patterns.
        Output: Complete test file content.""",
        tools=[run_pytest],
        max_iterations=5
    ),
    DevAgent(
        name="TestValidator",
        role=DevAgentRole.TESTER,
        llm_model="deepseek-chat",
        system_prompt="""You are a test validation expert.
        Run tests and verify they pass, achieve coverage targets, and handle edge cases.
        Report specific failures and coverage metrics.
        Output: Test results and coverage report.""",
        tools=[run_pytest, analyze_coverage],
        max_iterations=3
    ),
    DevAgent(
        name="CodeReviewer",
        role=DevAgentRole.REVIEWER,
        llm_model="deepseek-chat",
        system_prompt="""You are a code review expert for Python trading systems.
        Check for: code quality, type safety, security issues, and test completeness.
        Use ruff, mypy, and bandit for automated checks.
        Output: Review report with approval/rejection and specific issues.""",
        tools=[run_linters, get_git_status],
        max_iterations=2
    ),
]


def create_merid_dev_swarm() -> DevSwarm:
    """Factory function to create the default MERID DevSwarm."""
    swarm = DevSwarm()
    for agent in MERID_DEV_AGENTS:
        swarm.register_agent(agent)
    return swarm


# Task templates for common workflows
class DevTaskTemplates:
    """Templates for common development tasks."""
    
    @staticmethod
    def fix_coverage_gap(module_path: str, current_coverage: float, target_coverage: float = 85.0) -> DevTask:
        """Create a task to fix coverage gap in a module."""
        return DevTask(
            description=f"Fix test coverage for {module_path}. Current: {current_coverage}%, Target: {target_coverage}%",
            target_files=[module_path],
            success_criteria=f"Achieve {target_coverage}% coverage with all tests passing",
            priority=1,
            estimated_effort="medium"
        )
    
    @staticmethod
    def add_tests_for_module(module_path: str, test_type: str = "unit") -> DevTask:
        """Create a task to add tests for a module."""
        test_file = f"tests/{module_path.replace('.py', '')}/test_{os.path.basename(module_path)}"
        return DevTask(
            description=f"Add {test_type} tests for {module_path}",
            target_files=[module_path, test_file],
            success_criteria="Tests cover happy path, edge cases, and error handling",
            priority=2,
            estimated_effort="medium"
        )
    
    @staticmethod
    def refactor_for_quality(file_path: str, issues: List[str]) -> DevTask:
        """Create a task to refactor code for quality improvements."""
        return DevTask(
            description=f"Refactor {file_path} to address: {', '.join(issues)}",
            target_files=[file_path],
            success_criteria="All linters pass, tests pass, no regressions",
            priority=3,
            estimated_effort="large" if len(issues) > 3 else "medium"
        )

    # ------------------------------------------------------------------
    # Baseline remediation templates (RG-01 .. RG-11 + structural)
    # ------------------------------------------------------------------

    @staticmethod
    def rotate_secrets_and_purge_history() -> DevTask:
        return DevTask(
            description="[RG-01] Rotate all leaked secrets and purge from git history",
            target_files=["kalshi_private_key.pem", ".env", "config/credentials.yaml", "tests/test_secrets_guard.py"],
            success_criteria="No secrets in git log; all API keys rotated and tested",
            priority=0, estimated_effort="large",
        )

    @staticmethod
    def expand_gitignore() -> DevTask:
        return DevTask(
            description="[RG-03] Expand .gitignore to cover all sensitive and generated files",
            target_files=[".gitignore", "tests/test_gitignore.py"],
            success_criteria=".gitignore covers *.pem, .env*, *.db, __pycache__, node_modules",
            priority=1, estimated_effort="small",
        )

    @staticmethod
    def improve_trading_execution_coverage() -> DevTask:
        return DevTask(
            description="[RG-04] Improve test coverage for trading execution module",
            target_files=["trading/execution.py", "tests/test_trading_execution.py"],
            success_criteria="Coverage >= 80% for trading/execution.py with edge-case tests",
            priority=1, estimated_effort="large",
        )

    @staticmethod
    def improve_compliance_audit_coverage() -> DevTask:
        return DevTask(
            description="[RG-05] Improve test coverage for compliance audit logger",
            target_files=["compliance/audit_logger.py", "tests/test_compliance_audit.py"],
            success_criteria="Coverage >= 80% for compliance/audit_logger.py",
            priority=1, estimated_effort="medium",
        )

    @staticmethod
    def add_security_domain_tests() -> DevTask:
        return DevTask(
            description="[RG-07] Add security domain tests for breach detection",
            target_files=["security/breach_detection.py", "tests/test_security_domain.py"],
            success_criteria="Breach detection module has unit + integration tests",
            priority=1, estimated_effort="medium",
        )

    @staticmethod
    def add_governance_domain_tests() -> DevTask:
        return DevTask(
            description="[RG-08] Add governance domain tests for LLM governance store",
            target_files=["merid/governance/llm_governance_store.py", "tests/test_governance_domain.py"],
            success_criteria="Governance store has unit tests covering CRUD + role-based access",
            priority=1, estimated_effort="medium",
        )

    @staticmethod
    def add_web_api_smoke_tests() -> DevTask:
        return DevTask(
            description="[RG-10] Add smoke tests for all web API endpoints",
            target_files=["web/api/", "tests/test_api_smoke.py"],
            success_criteria="Every registered route returns 2xx or expected 4xx",
            priority=2, estimated_effort="medium",
        )

    @staticmethod
    def clean_empty_test_files() -> DevTask:
        return DevTask(
            description="[RG-11] Clean up empty or placeholder test files",
            target_files=["tests/", "tests/test_cleanup.py"],
            success_criteria="No test files with 0 test functions; all files have >=1 assertion",
            priority=2, estimated_effort="small",
        )

    @staticmethod
    def refactor_core_into_subpackages() -> DevTask:
        return DevTask(
            description="Refactor core/ into logical subpackages (state, risk, consensus, notifications)",
            target_files=["core/", "tests/test_core_structure.py"],
            success_criteria="core/ split into subpackages; all imports updated; tests pass",
            priority=2, estimated_effort="large",
        )

    @staticmethod
    def break_god_classes() -> DevTask:
        return DevTask(
            description="Break god classes (>500 LOC) into focused modules",
            target_files=["core/", "web/api/", "tests/test_god_classes.py"],
            success_criteria="No class exceeds 500 LOC; single-responsibility principle applied",
            priority=2, estimated_effort="large",
        )

    @staticmethod
    def add_data_feed_tests() -> DevTask:
        return DevTask(
            description="Add tests for data feed modules (live_price_feed, staleness)",
            target_files=["data/live_price_feed.py", "tests/test_data_feeds.py"],
            success_criteria="Data feed module has unit tests covering cache, staleness, reconnect",
            priority=2, estimated_effort="medium",
        )

    @staticmethod
    def add_frontend_tests() -> DevTask:
        return DevTask(
            description="Add frontend component tests for React dashboard",
            target_files=["web/react/src/", "web/react/src/__tests__/"],
            success_criteria="Key dashboard components have snapshot + interaction tests",
            priority=2, estimated_effort="large",
        )

    @staticmethod
    def archive_stale_docs() -> DevTask:
        return DevTask(
            description="Archive stale documentation and update README",
            target_files=["docs/", "README.md", "tests/test_docs.py"],
            success_criteria="Stale docs moved to docs/archive/; README reflects current state",
            priority=3, estimated_effort="small",
        )

    @staticmethod
    def consolidate_utf8_utils() -> DevTask:
        return DevTask(
            description="Consolidate duplicate UTF-8 utility functions into a single module",
            target_files=["utils/encoding.py", "tests/test_encoding.py"],
            success_criteria="Single source of truth for UTF-8 helpers; no duplicate implementations",
            priority=3, estimated_effort="small",
        )

    @staticmethod
    def codebase_drift_audit() -> DevTask:
        return DevTask(
            description="Codebase Drift Auditor — detect structural drift from baseline",
            target_files=["CODEBASE_BASELINE.json", "core/codebase_drift_auditor.py", "tests/test_codebase_drift.py"],
            success_criteria="Baseline snapshot exists; drift report generated on CI",
            priority=1, estimated_effort="medium",
        )

    # ------------------------------------------------------------------
    # Season 2 Tier 1 Risk Gap (RRG) templates
    # ------------------------------------------------------------------

    @staticmethod
    def build_state_manager() -> DevTask:
        return DevTask(
            description="[RRG-01/RRG-02] Build CriticalStateManager with reconciliation — "
                        "persistent state store for pipeline modes, halt flags, and agent registry "
                        "with automatic reconciliation on restart",
            target_files=[
                "core/critical_state_manager.py",
                "core/state_reconciliation.py",
                "tests/test_critical_state_manager.py",
            ],
            success_criteria="CriticalStateManager persists and reconciles all pipeline state; "
                             "100% test coverage for state transitions; RRG-01 and RRG-02 resolved",
            priority=0, estimated_effort="large",
        )

    @staticmethod
    def implement_black_swan_drill_harness() -> DevTask:
        return DevTask(
            description="[RRG-03] Implement BlackSwanDrillHarness — automated chaos drills "
                        "including FlashCrash, ExchangeOutage, and LiquidityCrisis scenarios",
            target_files=[
                "core/black_swan_drills.py",
                "tests/test_black_swan_drills.py",
            ],
            success_criteria="BlackSwanDrillHarness runs FlashCrash, ExchangeOutage, LiquidityCrisis "
                             "drills with pass/fail verdicts; integrated into CI; RRG-03 resolved",
            priority=0, estimated_effort="large",
        )

    @staticmethod
    def add_observability_kill_switch() -> DevTask:
        return DevTask(
            description="[RRG-04] Add ObservabilityGuard kill switch — runtime toggle to "
                        "disable non-essential observability when system is under stress",
            target_files=[
                "core/observability_guard.py",
                "tests/test_observability_guard.py",
            ],
            success_criteria="ObservabilityGuard can disable/enable observability subsystems; "
                             "stress-triggered auto-disable tested; RRG-04 resolved",
            priority=0, estimated_effort="medium",
        )

    @staticmethod
    def enforce_agent_registry() -> DevTask:
        return DevTask(
            description="[RRG-05] Enforce AuthorityEnforcer for agent registry — "
                        "mandatory registration and permission checks for all agent actions",
            target_files=[
                "swarm/agent_registry.py",
                "swarm/authority_enforcer.py",
                "tests/test_authority_enforcer.py",
            ],
            success_criteria="AuthorityEnforcer blocks unregistered agents; permission matrix "
                             "enforced for all agent actions; RRG-05 resolved",
            priority=1, estimated_effort="large",
        )

    @staticmethod
    def build_emergency_control_panel() -> DevTask:
        return DevTask(
            description="[RRG-06] Build EmergencyControlPanel — one-click halt, "
                        "position flatten, and system lockdown UI with backend routes",
            target_files=[
                "web/react/src/components/EmergencyControlPanel.tsx",
                "web/api/emergency_routes.py",
                "tests/test_emergency_control_panel.py",
            ],
            success_criteria="EmergencyControlPanel renders with halt/flatten/lockdown buttons; "
                             "backend routes execute actions; RRG-06 resolved",
            priority=1, estimated_effort="large",
        )

    @staticmethod
    def add_model_drift_detection() -> DevTask:
        return DevTask(
            description="[RRG-08] Add ModelDriftDetector — monitor LLM output distributions "
                        "for drift and alert when confidence calibration degrades",
            target_files=[
                "core/model_drift_detector.py",
                "tests/test_model_drift_detector.py",
            ],
            success_criteria="ModelDriftDetector computes KL-divergence on rolling windows; "
                             "alerts fire when drift exceeds threshold; RRG-08 resolved",
            priority=2, estimated_effort="medium",
        )

    @staticmethod
    def add_override_intent_logging() -> DevTask:
        return DevTask(
            description="[RRG-09] Add OverrideManager — structured logging for all "
                        "operator overrides with intent capture and audit trail",
            target_files=[
                "core/override_manager.py",
                "tests/test_override_manager.py",
            ],
            success_criteria="OverrideManager logs every override with intent, timestamp, "
                             "and rollback plan; audit trail queryable; RRG-09 resolved",
            priority=2, estimated_effort="medium",
        )
