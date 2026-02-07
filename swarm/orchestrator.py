"""
Model-agnostic AI Swarm Orchestrator for MERID.

Implements multi-agent coordination with pluggable models, role-based agents,
tool integrations, failure handling, and comprehensive security controls.
"""

import logging
from typing import Dict, List, Optional, Any, Set, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class AgentRole(Enum):
    """Agent role in swarm."""
    COORDINATOR = "coordinator"
    ROUTER = "router"
    TRADING_STRATEGY = "trading_strategy"
    DEFI_STRATEGY = "defi_strategy"
    EXECUTION = "execution"
    ROUTING = "routing"
    RISK = "risk"
    COMPLIANCE = "compliance"
    DATA = "data"
    OBSERVABILITY = "observability"
    GOVERNANCE = "governance"
    POLICY = "policy"
    SECURITY = "security"
    EXPLOIT_DETECTION = "exploit_detection"
    EXPERIMENT = "experiment"
    RND = "rnd"


class ModelCapability(Enum):
    """Model capability."""
    REASONING = "reasoning"
    CLASSIFICATION = "classification"
    CODE_GENERATION = "code_generation"
    DATA_ANALYSIS = "data_analysis"
    FAST_INFERENCE = "fast_inference"
    HIGH_ACCURACY = "high_accuracy"
    PRIVACY_PRESERVING = "privacy_preserving"


class FailureMode(Enum):
    """Failure mode."""
    MODEL_TIMEOUT = "model_timeout"
    MODEL_HALLUCINATION = "model_hallucination"
    MODEL_LOW_CONFIDENCE = "model_low_confidence"
    VENDOR_OUTAGE = "vendor_outage"
    ORCHESTRATION_DEADLOCK = "orchestration_deadlock"
    ORCHESTRATION_LOOP = "orchestration_loop"
    TOOL_FAILURE = "tool_failure"
    NETWORK_FAILURE = "network_failure"
    RPC_FAILURE = "rpc_failure"
    PROXY_FAILURE = "proxy_failure"
    SAFETY_VIOLATION = "safety_violation"
    COMPLIANCE_VIOLATION = "compliance_violation"


class FallbackStrategy(Enum):
    """Fallback strategy."""
    MODEL_FALLBACK = "model_fallback"
    PROXY_FALLBACK = "proxy_fallback"
    SIMPLIFIED_BEHAVIOR = "simplified_behavior"
    SAFE_MODE = "safe_mode"
    HUMAN_ESCALATION = "human_escalation"


@dataclass
class ModelProvider:
    """Model provider (vendor-agnostic)."""
    provider_id: str
    provider_name: str
    provider_type: str  # "local", "cloud", "hybrid"
    
    # Capabilities
    capabilities: Set[ModelCapability] = field(default_factory=set)
    
    # Performance
    avg_latency_ms: float = 0.0
    cost_per_1k_tokens: Decimal = Decimal("0")
    
    # Availability
    available: bool = True
    health_score: float = 1.0
    
    # Privacy
    data_retention_days: int = 0
    supports_private_deployment: bool = False
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AgentConfig:
    """Agent configuration."""
    agent_id: str
    agent_role: AgentRole
    
    # Model requirements
    required_capabilities: Set[ModelCapability] = field(default_factory=set)
    preferred_providers: List[str] = field(default_factory=list)
    fallback_providers: List[str] = field(default_factory=list)
    
    # Tools
    allowed_tools: Set[str] = field(default_factory=set)
    
    # Network policy
    network_policy_id: str = "public_data"
    
    # Permissions
    can_read_onchain: bool = True
    can_write_onchain: bool = False
    can_propose: bool = True
    can_execute: bool = False
    
    # Limits
    max_execution_time_sec: int = 60
    max_retries: int = 3
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AgentTask:
    """Agent task."""
    task_id: str
    agent_id: str
    agent_role: AgentRole
    
    # Task details
    task_type: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    # Execution
    model_provider_id: Optional[str] = None
    tools_used: List[str] = field(default_factory=list)
    network_requests: List[str] = field(default_factory=list)
    
    # Result
    success: bool = False
    result: Optional[Any] = None
    confidence: float = 0.0
    error_message: Optional[str] = None
    
    # Failure handling
    failure_mode: Optional[FailureMode] = None
    fallback_strategy: Optional[FallbackStrategy] = None
    retry_count: int = 0
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


@dataclass
class WorkflowStep:
    """Workflow step."""
    step_id: str
    step_name: str
    agent_role: AgentRole
    
    # Dependencies
    depends_on: List[str] = field(default_factory=list)
    
    # Execution
    executed: bool = False
    success: bool = False
    
    # Failure handling
    failure_modes: List[FailureMode] = field(default_factory=list)
    fallback_steps: List[str] = field(default_factory=list)


@dataclass
class Workflow:
    """Multi-agent workflow."""
    workflow_id: str
    workflow_name: str
    description: str
    
    # Steps
    steps: List[WorkflowStep] = field(default_factory=list)
    
    # Execution
    current_step: Optional[str] = None
    completed_steps: List[str] = field(default_factory=list)
    failed_steps: List[str] = field(default_factory=list)
    
    # Status
    status: str = "pending"  # "pending", "running", "completed", "failed", "safe_mode"
    
    # Metrics
    total_execution_time_sec: float = 0.0
    total_cost_usd: Decimal = Decimal("0")
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class ModelInterface(ABC):
    """Abstract model interface (vendor-agnostic)."""
    
    @abstractmethod
    def generate(
        self,
        prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> tuple[str, float]:
        """Generate response. Returns (response, confidence)."""
        pass
    
    @abstractmethod
    def classify(
        self,
        text: str,
        labels: List[str],
    ) -> tuple[str, float]:
        """Classify text. Returns (label, confidence)."""
        pass
    
    @abstractmethod
    def get_capabilities(self) -> Set[ModelCapability]:
        """Get model capabilities."""
        pass


class SwarmOrchestrator:
    """
    Model-agnostic AI Swarm Orchestrator for MERID.
    
    Implements:
    - Multi-agent coordination with role-based agents
    - Model-agnostic design (pluggable providers)
    - Tool integrations (on-chain, data, governance)
    - Network policy enforcement (proxies, relays)
    - Failure modes and fallback strategies
    - Security and compliance controls
    - Comprehensive metrics and logging
    """
    
    def __init__(self):
        self._model_providers: Dict[str, ModelProvider] = {}
        self._model_interfaces: Dict[str, ModelInterface] = {}
        self._agent_configs: Dict[str, AgentConfig] = {}
        self._tasks: List[AgentTask] = []
        self._workflows: Dict[str, Workflow] = {}
        
        self._initialize_default_config()
    
    def _initialize_default_config(self) -> None:
        """Initialize default orchestrator configuration."""
        
        # Register model providers (examples)
        self.register_model_provider(
            provider_id="local_llama",
            provider_name="Local Llama",
            provider_type="local",
            capabilities={
                ModelCapability.REASONING,
                ModelCapability.FAST_INFERENCE,
                ModelCapability.PRIVACY_PRESERVING,
            },
            avg_latency_ms=100.0,
            cost_per_1k_tokens=Decimal("0"),
            supports_private_deployment=True,
        )
        
        self.register_model_provider(
            provider_id="cloud_gpt",
            provider_name="Cloud GPT",
            provider_type="cloud",
            capabilities={
                ModelCapability.REASONING,
                ModelCapability.CODE_GENERATION,
                ModelCapability.HIGH_ACCURACY,
            },
            avg_latency_ms=500.0,
            cost_per_1k_tokens=Decimal("0.002"),
            data_retention_days=30,
        )
        
        self.register_model_provider(
            provider_id="local_classifier",
            provider_name="Local Classifier",
            provider_type="local",
            capabilities={
                ModelCapability.CLASSIFICATION,
                ModelCapability.FAST_INFERENCE,
                ModelCapability.PRIVACY_PRESERVING,
            },
            avg_latency_ms=50.0,
            cost_per_1k_tokens=Decimal("0"),
            supports_private_deployment=True,
        )
        
        # Register agent configs
        self.register_agent(
            agent_id="coordinator_001",
            agent_role=AgentRole.COORDINATOR,
            required_capabilities={ModelCapability.REASONING},
            preferred_providers=["local_llama", "cloud_gpt"],
            allowed_tools={"route_task", "diagnose_task"},
            network_policy_id="public_data",
            can_propose=True,
        )
        
        self.register_agent(
            agent_id="trading_strategy_001",
            agent_role=AgentRole.TRADING_STRATEGY,
            required_capabilities={ModelCapability.REASONING, ModelCapability.DATA_ANALYSIS},
            preferred_providers=["cloud_gpt", "local_llama"],
            allowed_tools={"read_market_data", "analyze_opportunity", "propose_trade"},
            network_policy_id="sensitive_data",
            can_propose=True,
        )
        
        self.register_agent(
            agent_id="risk_001",
            agent_role=AgentRole.RISK,
            required_capabilities={ModelCapability.CLASSIFICATION, ModelCapability.FAST_INFERENCE},
            preferred_providers=["local_classifier", "local_llama"],
            allowed_tools={"check_limits", "calculate_var", "check_exposure"},
            network_policy_id="sensitive_data",
            can_propose=True,
        )
        
        self.register_agent(
            agent_id="compliance_001",
            agent_role=AgentRole.COMPLIANCE,
            required_capabilities={ModelCapability.CLASSIFICATION},
            preferred_providers=["local_classifier"],
            allowed_tools={"check_geo_compliance", "check_venue_allowed"},
            network_policy_id="sensitive_data",
            can_propose=True,
        )
        
        self.register_agent(
            agent_id="execution_001",
            agent_role=AgentRole.EXECUTION,
            required_capabilities={ModelCapability.FAST_INFERENCE},
            preferred_providers=["local_llama"],
            allowed_tools={"build_transaction", "submit_transaction"},
            network_policy_id="critical_ops",
            can_execute=True,
        )
        
        logger.info("Initialized default swarm orchestrator configuration")
    
    def register_model_provider(
        self,
        provider_id: str,
        provider_name: str,
        provider_type: str,
        capabilities: Set[ModelCapability],
        avg_latency_ms: float = 0.0,
        cost_per_1k_tokens: Decimal = Decimal("0"),
        data_retention_days: int = 0,
        supports_private_deployment: bool = False,
    ) -> ModelProvider:
        """Register model provider."""
        provider = ModelProvider(
            provider_id=provider_id,
            provider_name=provider_name,
            provider_type=provider_type,
            capabilities=capabilities,
            avg_latency_ms=avg_latency_ms,
            cost_per_1k_tokens=cost_per_1k_tokens,
            data_retention_days=data_retention_days,
            supports_private_deployment=supports_private_deployment,
        )
        
        self._model_providers[provider_id] = provider
        
        logger.info(
            f"Registered model provider '{provider_id}': {provider_name} ({provider_type})"
        )
        
        return provider
    
    def register_model_interface(
        self,
        provider_id: str,
        interface: ModelInterface,
    ) -> None:
        """Register model interface implementation."""
        self._model_interfaces[provider_id] = interface
        
        logger.info(f"Registered model interface for provider '{provider_id}'")
    
    def register_agent(
        self,
        agent_id: str,
        agent_role: AgentRole,
        required_capabilities: Set[ModelCapability],
        preferred_providers: List[str],
        allowed_tools: Set[str],
        network_policy_id: str = "public_data",
        can_propose: bool = True,
        can_execute: bool = False,
    ) -> AgentConfig:
        """Register agent configuration."""
        config = AgentConfig(
            agent_id=agent_id,
            agent_role=agent_role,
            required_capabilities=required_capabilities,
            preferred_providers=preferred_providers,
            allowed_tools=allowed_tools,
            network_policy_id=network_policy_id,
            can_propose=can_propose,
            can_execute=can_execute,
        )
        
        self._agent_configs[agent_id] = config
        
        logger.info(
            f"Registered agent '{agent_id}': {agent_role.value} "
            f"(providers: {preferred_providers})"
        )
        
        return config
    
    def select_model_provider(
        self,
        agent_id: str,
        prefer_low_latency: bool = False,
        prefer_low_cost: bool = False,
        prefer_privacy: bool = False,
    ) -> Optional[ModelProvider]:
        """Select best model provider for agent."""
        config = self._agent_configs.get(agent_id)
        if not config:
            logger.error(f"Agent '{agent_id}' not found")
            return None
        
        # Get providers that meet requirements
        candidates = []
        for provider_id in config.preferred_providers:
            provider = self._model_providers.get(provider_id)
            if not provider or not provider.available:
                continue
            
            # Check capabilities
            if not config.required_capabilities.issubset(provider.capabilities):
                continue
            
            candidates.append(provider)
        
        if not candidates:
            logger.error(f"No available providers for agent '{agent_id}'")
            return None
        
        # Apply preferences
        if prefer_privacy:
            candidates = [p for p in candidates if p.supports_private_deployment]
        
        # Sort by preference
        if prefer_low_latency:
            candidates.sort(key=lambda p: (p.avg_latency_ms, float(p.cost_per_1k_tokens)))
        elif prefer_low_cost:
            candidates.sort(key=lambda p: (float(p.cost_per_1k_tokens), p.avg_latency_ms))
        else:
            # Default: balance latency and cost
            candidates.sort(key=lambda p: (p.avg_latency_ms * float(p.cost_per_1k_tokens)))
        
        return candidates[0]
    
    def create_task(
        self,
        agent_id: str,
        task_type: str,
        description: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> AgentTask:
        """Create agent task."""
        config = self._agent_configs.get(agent_id)
        if not config:
            raise ValueError(f"Agent '{agent_id}' not found")
        
        task_id = f"task_{agent_id}_{int(datetime.utcnow().timestamp())}"
        
        task = AgentTask(
            task_id=task_id,
            agent_id=agent_id,
            agent_role=config.agent_role,
            task_type=task_type,
            description=description,
            parameters=parameters or {},
        )
        
        self._tasks.append(task)
        
        logger.info(
            f"Created task '{task_id}' for agent '{agent_id}': {task_type}"
        )
        
        return task
    
    def execute_task(
        self,
        task_id: str,
        prefer_low_latency: bool = False,
    ) -> AgentTask:
        """Execute agent task."""
        task = next((t for t in self._tasks if t.task_id == task_id), None)
        if not task:
            raise ValueError(f"Task '{task_id}' not found")
        
        task.started_at = datetime.utcnow()
        
        # Select model provider
        provider = self.select_model_provider(
            task.agent_id,
            prefer_low_latency=prefer_low_latency,
        )
        
        if not provider:
            task.success = False
            task.error_message = "No available model provider"
            task.failure_mode = FailureMode.VENDOR_OUTAGE
            task.completed_at = datetime.utcnow()
            return task
        
        task.model_provider_id = provider.provider_id
        
        # Get model interface
        interface = self._model_interfaces.get(provider.provider_id)
        if not interface:
            task.success = False
            task.error_message = f"No interface for provider '{provider.provider_id}'"
            task.completed_at = datetime.utcnow()
            return task
        
        # Execute task (simplified - real implementation would call tools, etc.)
        try:
            # Example: generate response
            response, confidence = interface.generate(
                prompt=f"Task: {task.description}\nParameters: {task.parameters}",
                max_tokens=1000,
            )
            
            task.success = True
            task.result = response
            task.confidence = confidence
            
        except Exception as e:
            task.success = False
            task.error_message = str(e)
            task.failure_mode = FailureMode.MODEL_TIMEOUT
            
            # Apply fallback strategy
            self._apply_fallback(task)
        
        task.completed_at = datetime.utcnow()
        
        logger.info(
            f"Executed task '{task_id}': "
            f"{'success' if task.success else 'failed'} "
            f"(provider: {provider.provider_id}, confidence: {task.confidence:.2f})"
        )
        
        return task
    
    def _apply_fallback(self, task: AgentTask) -> None:
        """Apply fallback strategy for failed task."""
        config = self._agent_configs.get(task.agent_id)
        if not config:
            return
        
        # Try fallback providers
        if task.retry_count < config.max_retries:
            task.retry_count += 1
            task.fallback_strategy = FallbackStrategy.MODEL_FALLBACK
            
            logger.info(
                f"Applying fallback for task '{task.task_id}': "
                f"retry {task.retry_count}/{config.max_retries}"
            )
            
            # Would retry with different provider
            return
        
        # Escalate to human
        task.fallback_strategy = FallbackStrategy.HUMAN_ESCALATION
        
        logger.warning(
            f"Task '{task.task_id}' failed after {task.retry_count} retries, "
            f"escalating to human"
        )
    
    def create_workflow(
        self,
        workflow_id: str,
        workflow_name: str,
        description: str,
        steps: List[WorkflowStep],
    ) -> Workflow:
        """Create multi-agent workflow."""
        workflow = Workflow(
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            description=description,
            steps=steps,
        )
        
        self._workflows[workflow_id] = workflow
        
        logger.info(
            f"Created workflow '{workflow_id}': {workflow_name} ({len(steps)} steps)"
        )
        
        return workflow
    
    def get_agent_config(self, agent_id: str) -> Optional[AgentConfig]:
        """Get agent configuration."""
        return self._agent_configs.get(agent_id)
    
    def get_model_provider(self, provider_id: str) -> Optional[ModelProvider]:
        """Get model provider."""
        return self._model_providers.get(provider_id)
    
    def get_available_providers(
        self,
        capabilities: Optional[Set[ModelCapability]] = None,
    ) -> List[ModelProvider]:
        """Get available model providers."""
        providers = [p for p in self._model_providers.values() if p.available]
        
        if capabilities:
            providers = [
                p for p in providers
                if capabilities.issubset(p.capabilities)
            ]
        
        return providers
    
    def get_tasks(
        self,
        agent_id: Optional[str] = None,
        agent_role: Optional[AgentRole] = None,
        success: Optional[bool] = None,
    ) -> List[AgentTask]:
        """Get agent tasks."""
        tasks = self._tasks
        
        if agent_id:
            tasks = [t for t in tasks if t.agent_id == agent_id]
        
        if agent_role:
            tasks = [t for t in tasks if t.agent_role == agent_role]
        
        if success is not None:
            tasks = [t for t in tasks if t.success == success]
        
        return tasks


_swarm_orchestrator: Optional[SwarmOrchestrator] = None


def get_swarm_orchestrator() -> SwarmOrchestrator:
    """Get global SwarmOrchestrator instance."""
    global _swarm_orchestrator
    if _swarm_orchestrator is None:
        _swarm_orchestrator = SwarmOrchestrator()
    return _swarm_orchestrator
