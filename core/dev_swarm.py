"""DevSwarm Autonomous Development System for MERID.

Multi-agent system that automates code generation, testing, and CI fixes
using LLMs (DeepSeek, Claude, etc.) and agent frameworks.
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Callable
from enum import Enum
import subprocess
import json
import os
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


@dataclass
class DevTask:
    """A development task for the swarm."""
    description: str
    target_files: List[str]
    success_criteria: str
    priority: int = 1
    estimated_effort: str = "medium"  # small, medium, large


class DevSwarm:
    """MERID Autonomous Development Swarm."""
    
    def __init__(self, agents: List[DevAgent] = None):
        self.agents = agents or []
        self.task_history: List[Dict[str, Any]] = []
        self.logger = logger.bind(component="DevSwarm")
    
    def register_agent(self, agent: DevAgent) -> None:
        """Register an agent to the swarm."""
        self.agents.append(agent)
        self.logger.info("agent_registered", name=agent.name, role=agent.role.value)
    
    # Cost estimates per effort level (credits)
    EFFORT_COST = {"small": 5.0, "medium": 15.0, "large": 40.0}

    async def execute_task(self, task: DevTask) -> Dict[str, Any]:
        """Execute a development task through the agent pipeline."""
        self.logger.info("task_started", description=task.description[:50])

        # Budget gate — reject if agents lack credits
        estimated_cost = self.EFFORT_COST.get(task.estimated_effort, 15.0)
        try:
            from core.agent_credit_ledger import get_credit_ledger, InsufficientCreditsError
            ledger = get_credit_ledger()
            for agent in self.agents:
                if not ledger.check_budget(agent.name, estimated_cost):
                    self.logger.warning(
                        "task_rejected_budget",
                        agent=agent.name,
                        cost=estimated_cost,
                        balance=ledger.balance(agent.name),
                    )
                    return {
                        "status": "rejected",
                        "reason": f"Agent {agent.name} has insufficient credits "
                                  f"(need {estimated_cost}, have {ledger.balance(agent.name):.1f})",
                    }
        except ImportError:
            pass  # ledger module not available — allow execution

        # Find appropriate agents
        planner = self._find_agent(DevAgentRole.PLANNER)
        coder = self._find_agent(DevAgentRole.CODER)
        tester = self._find_agent(DevAgentRole.TESTER)
        reviewer = self._find_agent(DevAgentRole.REVIEWER)
        
        results = {"phases": []}
        
        # Phase 1: Planning
        if planner:
            plan = await self._run_agent_phase(planner, task, {})
            results["phases"].append({"agent": planner.name, "phase": "planning", "result": plan})
        
        # Phase 2: Coding
        if coder:
            code_result = await self._run_agent_phase(coder, task, results)
            results["phases"].append({"agent": coder.name, "phase": "coding", "result": code_result})
        
        # Phase 3: Testing
        if tester:
            test_result = await self._run_agent_phase(tester, task, results)
            results["phases"].append({"agent": tester.name, "phase": "testing", "result": test_result})
            
            # If tests fail, loop back to coding
            if not test_result.get("passed", True):
                self.logger.warning("tests_failed", retrying=True)
                # Retry coding with test feedback
                if coder and coder.max_iterations > 0:
                    coder.max_iterations -= 1
                    code_result = await self._run_agent_phase(coder, task, results)
                    results["phases"].append({"agent": coder.name, "phase": "coding_retry", "result": code_result})
        
        # Phase 4: Review
        if reviewer:
            review_result = await self._run_agent_phase(reviewer, task, results)
            results["phases"].append({"agent": reviewer.name, "phase": "review", "result": review_result})
        
        results["status"] = "completed"
        self.logger.info("task_completed", task=task.description[:50])

        # Deduct credits from participating agents
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

        return results
    
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
        
        # Build prompt for the agent
        prompt = self._build_agent_prompt(agent, task, context)
        
        # In real implementation, this would call the LLM
        # For now, simulate with tool execution
        result = await self._execute_agent_tools(agent, task)
        
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
    
    async def _execute_agent_tools(self, agent: DevAgent, task: DevTask) -> Dict[str, Any]:
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
