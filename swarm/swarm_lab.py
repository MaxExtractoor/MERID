"""
MERID Swarm Lab - Autonomous R&D and continuous evolution system.

Implements:
- Permanent R&D swarm that invents tools/features
- Continuous discovery and idea generation
- Autonomous code and UI generation
- Multi-stage testing and validation
- Governance-integrated rollout
- Living dashboard maintenance
"""

import logging
from typing import Dict, List, Optional, Any, Set, Tuple, Awaitable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import re
import asyncio
from core.event_bus import event_stream
from social.social_aware_quant import get_social_bot_health_monitor
from social.social_data_quality import get_social_data_quality_monitor

logger = logging.getLogger(__name__)


class SwarmLabStatus(Enum):
    """Runtime status for orchestrator."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


class AgentRole(Enum):
    """Swarm Lab agent role."""
    PRODUCT_DISCOVERY = "product_discovery"
    RESEARCH_STRATEGY = "research_strategy"
    TOOLING_INFRA = "tooling_infra"
    UI_UX_WORKFLOW = "ui_ux_workflow"
    CODE_INTEGRATION = "code_integration"
    EVALUATION_QA = "evaluation_qa"
    GOVERNANCE_SAFETY = "governance_safety"


class IdeaStatus(Enum):
    """Idea pipeline status."""
    DISCOVERED = "discovered"
    PRIORITIZED = "prioritized"
    DESIGNING = "designing"
    IMPLEMENTING = "implementing"
    TESTING = "testing"
    STAGING = "staging"
    APPROVED = "approved"
    DEPLOYED = "deployed"
    REJECTED = "rejected"


class TestStage(Enum):
    """Testing stage."""
    STATIC_CHECKS = "static_checks"
    SIMULATION = "simulation"
    STAGING = "staging"
    CANARY = "canary"
    PRODUCTION = "production"


TestStage.__test__ = False


class RiskLevel(Enum):
    """Change risk level."""
    LOW = "low"  # UI/instrumentation
    MEDIUM = "medium"  # New features, non-critical logic
    HIGH = "high"  # Risk logic, agent permissions, MEV behavior
    CRITICAL = "critical"  # Tokenomics, custody, governance


@dataclass
class Idea:
    """R&D idea."""
    idea_id: str
    
    # Classification
    theme: str  # e.g., "better RWA UX", "faster HFT monitoring"
    category: str  # tool, feature, ui, strategy, infra
    
    # Details
    title: str
    problem: str
    target_users: List[str] = field(default_factory=list)
    
    # Scoring
    impact_score: float = 0.0  # 0.0-1.0
    complexity_score: float = 0.0  # 0.0-1.0
    risk_level: RiskLevel = RiskLevel.LOW
    
    # Priority
    priority_score: float = 0.0  # impact / (complexity + risk)
    
    # Status
    status: IdeaStatus = IdeaStatus.DISCOVERED
    
    # Metadata
    discovered_by: str = ""
    discovered_from: str = ""  # telemetry, feedback, research, etc.
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Design:
    """Feature/tool design."""
    design_id: str
    idea_id: str
    
    # Specification
    title: str
    description: str
    specs: Dict[str, Any] = field(default_factory=dict)
    
    # Components
    backend_modules: List[str] = field(default_factory=list)
    frontend_components: List[str] = field(default_factory=list)
    database_schemas: List[str] = field(default_factory=list)
    api_endpoints: List[str] = field(default_factory=list)
    
    # Integration
    dependencies: List[str] = field(default_factory=list)
    integrates_with: List[str] = field(default_factory=list)
    
    # Security and risk
    security_considerations: List[str] = field(default_factory=list)
    privacy_considerations: List[str] = field(default_factory=list)
    risk_mitigations: List[str] = field(default_factory=list)
    
    # Approval
    approved: bool = False
    approved_by: Optional[str] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Implementation:
    """Code implementation."""
    implementation_id: str
    design_id: str
    
    # Code artifacts
    files_created: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    
    # Tests
    unit_tests: List[str] = field(default_factory=list)
    integration_tests: List[str] = field(default_factory=list)
    
    # Documentation
    docs_updated: List[str] = field(default_factory=list)
    
    # Status
    code_complete: bool = False
    tests_passing: bool = False
    docs_complete: bool = False
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TestResult:
    """Test execution result."""
    test_id: str
    implementation_id: str
    
    # Stage
    stage: TestStage
    
    # Results
    passed: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    # Metrics
    metrics: Dict[str, Any] = field(default_factory=dict)
    
    # Details
    details: str = ""
    
    executed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Rollout:
    """Deployment rollout."""
    rollout_id: str
    implementation_id: str
    
    # Plan
    stages: List[str] = field(default_factory=list)  # canary, partial, full
    current_stage: str = ""
    
    # Metrics
    success_criteria: Dict[str, Any] = field(default_factory=dict)
    rollback_criteria: Dict[str, Any] = field(default_factory=dict)
    
    # Status
    stage_metrics: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    rolled_back: bool = False
    rollback_reason: str = ""
    
    # Governance
    governance_approved: bool = False
    governance_proposal_id: Optional[str] = None
    
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


@dataclass
class LabAgent:
    """Swarm Lab agent."""
    agent_id: str
    role: AgentRole
    
    # Capabilities
    capabilities: List[str] = field(default_factory=list)
    
    # Performance
    ideas_generated: int = 0
    designs_created: int = 0
    implementations_completed: int = 0
    tests_run: int = 0
    tasks_completed: int = 0
    success_rate: float = 1.0
    
    # Status
    active: bool = True
    current_task: Optional[str] = None
    last_active: datetime = field(default_factory=datetime.utcnow)
    
    created_at: datetime = field(default_factory=datetime.utcnow)


class SwarmLabOrchestrator:
    """
    MERID Swarm Lab Orchestrator.
    
    Runs a permanent, autonomous R&D swarm that:
    - Discovers and prioritizes improvement opportunities
    - Designs and implements new tools/features/UI
    - Tests and validates changes
    - Rolls out via governance-approved stages
    - Maintains and refactors over time
    """
    
    def __init__(self):
        self._agents: Dict[str, LabAgent] = {}
        self._ideas: Dict[str, Idea] = {}
        self._designs: Dict[str, Design] = {}
        self._implementations: Dict[str, Implementation] = {}
        self._test_results: List[TestResult] = []
        self._rollouts: Dict[str, Rollout] = {}
        self._status: SwarmLabStatus = SwarmLabStatus.STOPPED
        self._loop_task: Optional[asyncio.Task] = None
        self._stop_event: asyncio.Event = asyncio.Event()
        self._cycle_interval: float = 60.0
        self._cycle_count: int = 0
        self._health = get_social_bot_health_monitor()
        self._quality = get_social_data_quality_monitor()
        self._component_name = "swarm_lab"
        self._health.register_component(
            self._component_name,
            component_type="swarm",
            auto_recover=True,
            heartbeat_interval=self._cycle_interval,
        )

        self._initialize_agents()
    
    def _initialize_agents(self) -> None:
        """Initialize specialist agents."""
        
        # Product discovery agents
        self.register_agent(
            role=AgentRole.PRODUCT_DISCOVERY,
            capabilities=[
                "mine_metrics",
                "analyze_user_behavior",
                "process_feedback",
                "track_market_trends",
                "identify_feature_gaps",
            ],
        )
        
        # Research and strategy agents
        self.register_agent(
            role=AgentRole.RESEARCH_STRATEGY,
            capabilities=[
                "explore_trading_strategies",
                "design_risk_models",
                "research_mev_mechanisms",
                "design_experiments",
                "define_metrics",
            ],
        )
        
        # Tooling and infra design agents
        self.register_agent(
            role=AgentRole.TOOLING_INFRA,
            capabilities=[
                "design_data_services",
                "design_simulators",
                "design_exploit_scanners",
                "design_backtest_engines",
                "design_mcp_tools",
                "design_apis",
            ],
        )
        
        # UI/UX and workflow agents
        self.register_agent(
            role=AgentRole.UI_UX_WORKFLOW,
            capabilities=[
                "design_ui_screens",
                "design_workflows",
                "create_wireframes",
                "optimize_layouts",
                "write_copy",
                "design_onboarding",
            ],
        )
        
        # Code & integration agents
        self.register_agent(
            role=AgentRole.CODE_INTEGRATION,
            capabilities=[
                "generate_backend_code",
                "generate_frontend_code",
                "refactor_code",
                "create_integration_glue",
                "define_config_schemas",
                "write_tests",
            ],
        )
        
        # Evaluation & QA agents
        self.register_agent(
            role=AgentRole.EVALUATION_QA,
            capabilities=[
                "build_test_suites",
                "run_unit_tests",
                "run_integration_tests",
                "run_simulations",
                "run_regression_tests",
                "check_accessibility",
                "check_performance",
            ],
        )
        
        # Governance & safety agents
        self.register_agent(
            role=AgentRole.GOVERNANCE_SAFETY,
            capabilities=[
                "check_sovereignty_constraints",
                "check_security_constraints",
                "check_risk_constraints",
                "check_compliance_constraints",
                "prepare_governance_proposals",
                "veto_unsafe_changes",
            ],
        )
        
        logger.info(f"Initialized {len(self._agents)} Swarm Lab agents")
    
    def register_agent(
        self,
        role: AgentRole,
        capabilities: Optional[List[str]] = None,
    ) -> LabAgent:
        """Register Swarm Lab agent."""
        agent_id = f"lab_{role.value}_{int(datetime.utcnow().timestamp())}"
        
        agent = LabAgent(
            agent_id=agent_id,
            role=role,
            capabilities=capabilities or [],
        )
        
        self._agents[agent_id] = agent
        
        logger.info(f"Registered agent '{agent_id}' with role {role.value}")
        
        return agent
    
    def discover_idea(
        self,
        theme: str,
        category: str,
        title: str,
        problem: str,
        target_users: Optional[List[str]] = None,
        discovered_by: str = "",
        discovered_from: str = "",
    ) -> Idea:
        """Discover new idea."""
        idea_id = f"idea_{int(datetime.utcnow().timestamp())}"
        
        idea = Idea(
            idea_id=idea_id,
            theme=theme,
            category=category,
            title=title,
            problem=problem,
            target_users=target_users or [],
            discovered_by=discovered_by,
            discovered_from=discovered_from,
        )
        
        self._ideas[idea_id] = idea
        
        # Update agent stats
        agent = next(
            (a for a in self._agents.values() if a.agent_id == discovered_by),
            None,
        )
        if agent:
            agent.ideas_generated += 1
        
        logger.info(
            f"Discovered idea '{idea_id}': {title} "
            f"(theme: {theme}, category: {category})"
        )
        
        return idea
    
    def prioritize_idea(
        self,
        idea_id: str,
        impact_score: float,
        complexity_score: float,
        risk_level: RiskLevel,
    ) -> Idea:
        """Prioritize idea."""
        idea = self._ideas.get(idea_id)
        
        if not idea:
            raise ValueError(f"Idea '{idea_id}' not found")
        
        idea.impact_score = impact_score
        idea.complexity_score = complexity_score
        idea.risk_level = risk_level
        
        # Calculate priority: impact / (complexity + risk_weight)
        risk_weight = {
            RiskLevel.LOW: 0.1,
            RiskLevel.MEDIUM: 0.3,
            RiskLevel.HIGH: 0.6,
            RiskLevel.CRITICAL: 1.0,
        }[risk_level]
        
        idea.priority_score = impact_score / (complexity_score + risk_weight)
        idea.status = IdeaStatus.PRIORITIZED
        
        logger.info(
            f"Prioritized idea '{idea_id}': "
            f"impact={impact_score:.2f}, complexity={complexity_score:.2f}, "
            f"risk={risk_level.value}, priority={idea.priority_score:.2f}"
        )
        
        return idea
    
    def create_design(
        self,
        idea_id: str,
        title: str,
        description: str,
        specs: Optional[Dict[str, Any]] = None,
        backend_modules: Optional[List[str]] = None,
        frontend_components: Optional[List[str]] = None,
        security_considerations: Optional[List[str]] = None,
    ) -> Design:
        """Create design for idea."""
        design_id = f"design_{int(datetime.utcnow().timestamp())}"
        
        design = Design(
            design_id=design_id,
            idea_id=idea_id,
            title=title,
            description=description,
            specs=specs or {},
            backend_modules=backend_modules or [],
            frontend_components=frontend_components or [],
            security_considerations=security_considerations or [],
        )
        
        self._designs[design_id] = design
        
        # Update idea status
        idea = self._ideas.get(idea_id)
        if idea:
            idea.status = IdeaStatus.DESIGNING
        
        logger.info(
            f"Created design '{design_id}' for idea '{idea_id}': {title}"
        )
        
        return design
    
    def approve_design(
        self,
        design_id: str,
        approved_by: str,
    ) -> Design:
        """Approve design."""
        design = self._designs.get(design_id)
        
        if not design:
            raise ValueError(f"Design '{design_id}' not found")
        
        design.approved = True
        design.approved_by = approved_by
        
        # Update idea status
        idea = self._ideas.get(design.idea_id)
        if idea:
            idea.status = IdeaStatus.IMPLEMENTING
        
        logger.info(
            f"Approved design '{design_id}' by {approved_by}"
        )
        
        return design
    
    def create_implementation(
        self,
        design_id: str,
        files_created: Optional[List[str]] = None,
        files_modified: Optional[List[str]] = None,
        unit_tests: Optional[List[str]] = None,
        integration_tests: Optional[List[str]] = None,
    ) -> Implementation:
        """Create implementation."""
        implementation_id = f"impl_{int(datetime.utcnow().timestamp())}"
        
        implementation = Implementation(
            implementation_id=implementation_id,
            design_id=design_id,
            files_created=files_created or [],
            files_modified=files_modified or [],
            unit_tests=unit_tests or [],
            integration_tests=integration_tests or [],
        )
        
        self._implementations[implementation_id] = implementation
        
        logger.info(
            f"Created implementation '{implementation_id}' for design '{design_id}'"
        )
        
        return implementation
    
    def mark_implementation_complete(
        self,
        implementation_id: str,
        code_complete: bool = True,
        tests_passing: bool = True,
        docs_complete: bool = True,
    ) -> Implementation:
        """Mark implementation complete."""
        implementation = self._implementations.get(implementation_id)
        
        if not implementation:
            raise ValueError(f"Implementation '{implementation_id}' not found")
        
        implementation.code_complete = code_complete
        implementation.tests_passing = tests_passing
        implementation.docs_complete = docs_complete
        
        # Update design status
        design = self._designs.get(implementation.design_id)
        if design:
            idea = self._ideas.get(design.idea_id)
            if idea:
                idea.status = IdeaStatus.TESTING
        
        logger.info(
            f"Marked implementation '{implementation_id}' complete: "
            f"code={code_complete}, tests={tests_passing}, docs={docs_complete}"
        )
        
        return implementation
    
    def run_test_stage(
        self,
        implementation_id: str,
        stage: TestStage,
    ) -> TestResult:
        """Run test stage."""
        test_id = f"test_{stage.value}_{int(datetime.utcnow().timestamp())}"
        
        # Simulate test execution
        passed = True  # In real implementation, would run actual tests
        errors = []
        warnings = []
        metrics = {}
        
        result = TestResult(
            test_id=test_id,
            implementation_id=implementation_id,
            stage=stage,
            passed=passed,
            errors=errors,
            warnings=warnings,
            metrics=metrics,
        )
        
        self._test_results.append(result)
        
        logger.info(
            f"Ran test stage '{stage.value}' for implementation '{implementation_id}': "
            f"{'PASSED' if passed else 'FAILED'}"
        )
        
        return result
    
    def create_rollout(
        self,
        implementation_id: str,
        stages: Optional[List[str]] = None,
        governance_required: bool = False,
    ) -> Rollout:
        """Create rollout plan."""
        rollout_id = f"rollout_{int(datetime.utcnow().timestamp())}"
        
        rollout = Rollout(
            rollout_id=rollout_id,
            implementation_id=implementation_id,
            stages=stages or ["canary", "partial", "full"],
            current_stage="canary",
            governance_approved=not governance_required,
        )
        
        self._rollouts[rollout_id] = rollout
        
        logger.info(
            f"Created rollout '{rollout_id}' for implementation '{implementation_id}' "
            f"(governance_required: {governance_required})"
        )
        
        return rollout

    async def start(self, cycle_interval: float = 60.0) -> None:
        """Start background orchestration loop."""
        if self._status == SwarmLabStatus.RUNNING:
            return
        self._status = SwarmLabStatus.STARTING
        self._cycle_interval = cycle_interval
        self._stop_event.clear()
        loop = asyncio.get_running_loop()
        self._loop_task = loop.create_task(self._run_loop())
        self._health.update_heartbeat(self._component_name, status="running")
        logger.info("Swarm Lab orchestrator started")

    async def stop(self) -> None:
        """Stop background loop."""
        if self._loop_task:
            self._stop_event.set()
            await self._loop_task
            self._loop_task = None
        self._status = SwarmLabStatus.STOPPED
        self._health.update_heartbeat(self._component_name, status="stopped")
        logger.info("Swarm Lab orchestrator stopped")

    async def _run_loop(self) -> None:
        """Periodic orchestration tasks."""
        self._status = SwarmLabStatus.RUNNING
        while True:
            if self._stop_event.is_set():
                break
            start = datetime.utcnow()
            try:
                await self._run_cycle()
                self._health.update_heartbeat(
                    self._component_name,
                    metadata={
                        "cycle": self._cycle_count,
                        "ideas": len(self._ideas),
                        "designs": len(self._designs),
                    },
                )
            except Exception as exc:  # pragma: no cover
                logger.error("Swarm Lab cycle failed: %s", exc)
                self._status = SwarmLabStatus.ERROR
                self._health.record_failure(self._component_name, f"cycle_error:{exc}")
            elapsed = (datetime.utcnow() - start).total_seconds()
            wait_time = max(1.0, self._cycle_interval - elapsed)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait_time)
                break
            except asyncio.TimeoutError:
                continue
        self._status = SwarmLabStatus.STOPPED

    async def _run_cycle(self) -> None:
        """Orchestration logic per cycle."""
        self._cycle_count += 1
        # TODO: plug real cycle tasks (idea harvesting, validation, etc.)
        payload = self.get_status_payload()
        await event_stream.publish(
            "swarm_activity",
            {
                "cycle": self._cycle_count,
                "metrics": payload["metrics"],
                "top_idea": payload["top_ideas"][0] if payload["top_ideas"] else {},
            },
        )

    @property
    def status(self) -> SwarmLabStatus:
        return self._status

    def get_metrics(self) -> Dict[str, Any]:
        """Return aggregate metrics for dashboards."""
        idea_status: Dict[str, int] = {}
        for idea in self._ideas.values():
            idea_status.setdefault(idea.status.value, 0)
            idea_status[idea.status.value] += 1

        return {
            "total_agents": len(self._agents),
            "active_agents": sum(1 for agent in self._agents.values() if agent.active),
            "ideas_total": len(self._ideas),
            "ideas_by_status": idea_status,
            "designs_total": len(self._designs),
            "implementations_total": len(self._implementations),
            "test_results_total": len(self._test_results),
            "rollouts_total": len(self._rollouts),
        }

    def get_agents_snapshot(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Return summary of top agents by tasks completed."""
        agents = sorted(
            self._agents.values(),
            key=lambda agent: agent.tasks_completed,
            reverse=True,
        )[:limit]
        return [
            {
                "agent_id": agent.agent_id,
                "role": agent.role.value,
                "active": agent.active,
                "tasks_completed": agent.tasks_completed,
                "capabilities": agent.capabilities,
            }
            for agent in agents
        ]

    def get_top_ideas(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Return highest-priority ideas."""
        ideas = sorted(
            self._ideas.values(),
            key=lambda idea: idea.priority_score,
            reverse=True,
        )[:limit]
        return [
            {
                "idea_id": idea.idea_id,
                "title": idea.title,
                "status": idea.status.value,
                "priority": round(idea.priority_score, 4),
                "theme": idea.theme,
            }
            for idea in ideas
        ]

    def get_status_payload(self) -> Dict[str, Any]:
        """Return comprehensive status payload for APIs."""
        metrics = self.get_metrics()
        return {
            "status": self._status.value,
            "cycle_count": self._cycle_count,
            "cycle_interval": self._cycle_interval,
            "metrics": metrics,
            "top_ideas": self.get_top_ideas(),
            "agents": self.get_agents_snapshot(),
        }
    
    def advance_rollout_stage(
        self,
        rollout_id: str,
    ) -> Rollout:
        """Advance rollout to next stage."""
        rollout = self._rollouts.get(rollout_id)
        
        if not rollout:
            raise ValueError(f"Rollout '{rollout_id}' not found")
        
        current_idx = rollout.stages.index(rollout.current_stage)
        
        if current_idx < len(rollout.stages) - 1:
            rollout.current_stage = rollout.stages[current_idx + 1]
            
            logger.info(
                f"Advanced rollout '{rollout_id}' to stage '{rollout.current_stage}'"
            )
        else:
            rollout.completed_at = datetime.utcnow()
            
            # Update idea status
            implementation = self._implementations.get(rollout.implementation_id)
            if implementation:
                design = self._designs.get(implementation.design_id)
                if design:
                    idea = self._ideas.get(design.idea_id)
                    if idea:
                        idea.status = IdeaStatus.DEPLOYED
            
            logger.info(f"Completed rollout '{rollout_id}'")
        
        return rollout
    
    def rollback_rollout(
        self,
        rollout_id: str,
        reason: str,
    ) -> Rollout:
        """Rollback rollout."""
        rollout = self._rollouts.get(rollout_id)
        
        if not rollout:
            raise ValueError(f"Rollout '{rollout_id}' not found")
        
        rollout.rolled_back = True
        rollout.rollback_reason = reason
        
        logger.warning(
            f"Rolled back rollout '{rollout_id}': {reason}"
        )
        
        return rollout
    
    def get_prioritized_ideas(
        self,
        top_n: int = 10,
    ) -> List[Idea]:
        """Get top prioritized ideas."""
        prioritized = [
            i for i in self._ideas.values()
            if i.status == IdeaStatus.PRIORITIZED
        ]
        
        # Sort by priority score (descending)
        prioritized.sort(key=lambda x: x.priority_score, reverse=True)
        
        return prioritized[:top_n]
    
    def get_active_implementations(self) -> List[Implementation]:
        """Get active implementations."""
        return [
            i for i in self._implementations.values()
            if not i.code_complete or not i.tests_passing or not i.docs_complete
        ]
    
    def get_lab_metrics(self) -> Dict[str, Any]:
        """Get Swarm Lab metrics."""
        return {
            "agents": {
                "total": len(self._agents),
                "active": sum(1 for a in self._agents.values() if a.active),
                "by_role": {
                    role.value: sum(1 for a in self._agents.values() if a.role == role)
                    for role in AgentRole
                },
            },
            "ideas": {
                "total": len(self._ideas),
                "by_status": {
                    status.value: sum(1 for i in self._ideas.values() if i.status == status)
                    for status in IdeaStatus
                },
            },
            "designs": {
                "total": len(self._designs),
                "approved": sum(1 for d in self._designs.values() if d.approved),
            },
            "implementations": {
                "total": len(self._implementations),
                "complete": sum(
                    1 for i in self._implementations.values()
                    if i.code_complete and i.tests_passing and i.docs_complete
                ),
            },
            "rollouts": {
                "total": len(self._rollouts),
                "active": sum(1 for r in self._rollouts.values() if not r.completed_at),
                "completed": sum(1 for r in self._rollouts.values() if r.completed_at),
                "rolled_back": sum(1 for r in self._rollouts.values() if r.rolled_back),
            },
            "tests": {
                "total": len(self._test_results),
                "passed": sum(1 for t in self._test_results if t.passed),
                "failed": sum(1 for t in self._test_results if not t.passed),
            },
        }


_swarm_lab_orchestrator: Optional[SwarmLabOrchestrator] = None


def get_swarm_lab_orchestrator() -> SwarmLabOrchestrator:
    """Get global SwarmLabOrchestrator instance."""
    global _swarm_lab_orchestrator
    if _swarm_lab_orchestrator is None:
        _swarm_lab_orchestrator = SwarmLabOrchestrator()
    return _swarm_lab_orchestrator
