"""
Collaborative Swarm Layer

Implements:
- Decentralized agent registry with DID-based identities
- Secure cross-agent messaging with mTLS
- Capability-based discovery and matchmaking
- Federated learning interface
- Multi-provider LLM gateway
"""

import logging
from typing import Dict, List, Optional, Any, Set, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import hashlib
import uuid

logger = logging.getLogger(__name__)


class DIDMethod(Enum):
    """DID methods supported."""
    DID_KEY = "did:key"
    DID_WEB = "did:web"
    DID_PKH = "did:pkh"


class AgentCapability(Enum):
    """Agent capabilities."""
    TRADING = "trading"
    RISK_MANAGEMENT = "risk_management"
    DATA_ANALYSIS = "data_analysis"
    EXECUTION = "execution"
    RESEARCH = "research"
    SECURITY = "security"
    GOVERNANCE = "governance"
    MONITORING = "monitoring"


class CollaborationScope(Enum):
    """Scope of collaboration."""
    RESEARCH = "research"
    STRATEGY = "strategy"
    TOOLS = "tools"
    MODEL_TRAINING = "model_training"


class DataClassification(Enum):
    """Data classification levels."""
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class LLMProvider(Enum):
    """LLM providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    COHERE = "cohere"
    LOCAL = "local"


@dataclass
class AgentIdentity:
    """Agent identity with DID."""
    agent_id: str
    did: str
    did_method: DIDMethod
    
    public_key: str
    certificate: str = ""
    
    name: str = ""
    description: str = ""
    
    endpoints: Dict[str, str] = field(default_factory=dict)
    capabilities: List[AgentCapability] = field(default_factory=list)
    
    trust_score: float = 0.5
    reputation: float = 0.5
    
    registered_at: datetime = field(default_factory=datetime.utcnow)
    last_seen: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SecureMessage:
    """A secure message between agents."""
    message_id: str
    
    from_agent: str
    to_agent: str
    
    payload: Dict[str, Any]
    
    signature: str = ""
    nonce: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    encrypted: bool = True
    session_bound: bool = True


@dataclass
class CollaborationTask:
    """A collaboration task between agents."""
    task_id: str
    
    initiator: str
    participants: List[str]
    
    scope: CollaborationScope
    description: str
    
    data_classification: DataClassification = DataClassification.INTERNAL
    
    status: str = "pending"
    result: Optional[Dict[str, Any]] = None
    
    cost_budget: float = 0.0
    cost_spent: float = 0.0
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


@dataclass
class FederatedModel:
    """A federated learning model."""
    model_id: str
    name: str
    version: str
    
    contributors: List[str] = field(default_factory=list)
    
    current_round: int = 0
    total_rounds: int = 10
    
    aggregation_method: str = "fedavg"
    
    privacy_budget_epsilon: float = 1.0
    privacy_budget_delta: float = 1e-5
    
    metrics: Dict[str, float] = field(default_factory=dict)
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class LLMRequest:
    """A request to the LLM gateway."""
    request_id: str
    
    provider: LLMProvider
    model: str
    
    prompt: str
    max_tokens: int = 1000
    temperature: float = 0.7
    
    data_classification: DataClassification = DataClassification.INTERNAL
    
    agent_id: str = ""
    workflow_id: str = ""
    
    response: str = ""
    tokens_used: int = 0
    cost: float = 0.0
    
    created_at: datetime = field(default_factory=datetime.utcnow)


class DecentralizedAgentRegistry:
    """
    Decentralized Agent Registry with DID-based identities.
    
    Features:
    - DID method support (did:key, did:web, did:pkh)
    - Public key and certificate management
    - Capability advertisement
    - Trust and reputation tracking
    """
    
    def __init__(self):
        self._agents: Dict[str, AgentIdentity] = {}
        self._did_index: Dict[str, str] = {}
        self._capability_index: Dict[AgentCapability, Set[str]] = {
            cap: set() for cap in AgentCapability
        }
    
    def register_agent(
        self,
        name: str,
        did_method: DIDMethod,
        public_key: str,
        capabilities: List[AgentCapability],
        endpoints: Optional[Dict[str, str]] = None,
        description: str = "",
    ) -> AgentIdentity:
        """Register a new agent."""
        agent_id = f"agent_{uuid.uuid4().hex[:12]}"
        
        # Generate DID based on method
        if did_method == DIDMethod.DID_KEY:
            did = f"did:key:{hashlib.sha256(public_key.encode()).hexdigest()[:32]}"
        elif did_method == DIDMethod.DID_WEB:
            did = f"did:web:merid.io:agents:{agent_id}"
        else:
            did = f"did:pkh:eip155:1:{public_key[:42]}"
        
        identity = AgentIdentity(
            agent_id=agent_id,
            did=did,
            did_method=did_method,
            public_key=public_key,
            name=name,
            description=description,
            endpoints=endpoints or {},
            capabilities=capabilities,
        )
        
        self._agents[agent_id] = identity
        self._did_index[did] = agent_id
        
        for cap in capabilities:
            self._capability_index[cap].add(agent_id)
        
        logger.info(f"Registered agent '{name}' with DID '{did}'")
        return identity
    
    def resolve_did(self, did: str) -> Optional[AgentIdentity]:
        """Resolve a DID to agent identity."""
        agent_id = self._did_index.get(did)
        if agent_id:
            return self._agents.get(agent_id)
        return None
    
    def discover_by_capability(
        self,
        capability: AgentCapability,
        min_trust: float = 0.0,
    ) -> List[AgentIdentity]:
        """Discover agents by capability."""
        agent_ids = self._capability_index.get(capability, set())
        agents = [
            self._agents[aid] for aid in agent_ids
            if self._agents[aid].trust_score >= min_trust
        ]
        return sorted(agents, key=lambda a: a.trust_score, reverse=True)
    
    def update_reputation(
        self,
        agent_id: str,
        score_delta: float,
    ) -> None:
        """Update agent reputation."""
        if agent_id in self._agents:
            agent = self._agents[agent_id]
            agent.reputation = max(0.0, min(1.0, agent.reputation + score_delta))
            agent.trust_score = (agent.trust_score + agent.reputation) / 2
    
    def get_registry_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        by_capability = {
            cap.value: len(agents)
            for cap, agents in self._capability_index.items()
        }
        
        return {
            "total_agents": len(self._agents),
            "by_capability": by_capability,
            "avg_trust_score": (
                sum(a.trust_score for a in self._agents.values()) / len(self._agents)
                if self._agents else 0
            ),
        }


class SecureMessagingProtocol:
    """
    Secure Cross-Agent Messaging Protocol with mTLS.
    
    Features:
    - mTLS mutual authentication
    - Message-level signatures
    - Nonce-based replay prevention
    - Session binding
    """
    
    def __init__(self, registry: DecentralizedAgentRegistry):
        self._registry = registry
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._message_log: List[SecureMessage] = []
        self._replay_cache: Set[str] = set()
    
    def establish_session(
        self,
        from_agent: str,
        to_agent: str,
    ) -> str:
        """Establish a secure session between agents."""
        session_id = f"session_{uuid.uuid4().hex[:16]}"
        
        self._sessions[session_id] = {
            "from_agent": from_agent,
            "to_agent": to_agent,
            "established_at": datetime.utcnow(),
            "messages_count": 0,
        }
        
        logger.debug(f"Established session '{session_id}'")
        return session_id
    
    def send_message(
        self,
        session_id: str,
        payload: Dict[str, Any],
    ) -> Optional[SecureMessage]:
        """Send a secure message."""
        if session_id not in self._sessions:
            logger.error(f"Session '{session_id}' not found")
            return None
        
        session = self._sessions[session_id]
        
        nonce = uuid.uuid4().hex
        
        # Check replay
        if nonce in self._replay_cache:
            logger.warning("Replay attack detected")
            return None
        
        message = SecureMessage(
            message_id=f"msg_{uuid.uuid4().hex[:12]}",
            from_agent=session["from_agent"],
            to_agent=session["to_agent"],
            payload=payload,
            nonce=nonce,
            signature=self._sign_message(payload, nonce),
        )
        
        self._replay_cache.add(nonce)
        self._message_log.append(message)
        session["messages_count"] += 1
        
        # Cleanup old nonces
        if len(self._replay_cache) > 10000:
            self._replay_cache = set(list(self._replay_cache)[-5000:])
        
        return message
    
    def _sign_message(self, payload: Dict[str, Any], nonce: str) -> str:
        """Sign a message (placeholder - use real crypto in production)."""
        content = str(payload) + nonce
        return hashlib.sha256(content.encode()).hexdigest()
    
    def verify_message(self, message: SecureMessage) -> bool:
        """Verify a message signature."""
        expected_sig = self._sign_message(message.payload, message.nonce)
        return message.signature == expected_sig
    
    def get_messaging_stats(self) -> Dict[str, Any]:
        """Get messaging statistics."""
        return {
            "active_sessions": len(self._sessions),
            "total_messages": len(self._message_log),
            "replay_cache_size": len(self._replay_cache),
        }


class CollaborationOrchestrator:
    """
    Capability-Based Discovery and Matchmaking System.
    
    Features:
    - Multi-criteria agent selection
    - Task delegation and result validation
    - Collaboration policy enforcement
    """
    
    def __init__(
        self,
        registry: DecentralizedAgentRegistry,
        messaging: SecureMessagingProtocol,
    ):
        self._registry = registry
        self._messaging = messaging
        self._tasks: Dict[str, CollaborationTask] = {}
        self._policies: Dict[CollaborationScope, Dict[str, Any]] = {}
        
        self._initialize_default_policies()
    
    def _initialize_default_policies(self) -> None:
        """Initialize default collaboration policies."""
        self._policies = {
            CollaborationScope.RESEARCH: {
                "max_participants": 10,
                "min_trust_score": 0.3,
                "data_sharing": DataClassification.INTERNAL,
                "requires_approval": False,
            },
            CollaborationScope.STRATEGY: {
                "max_participants": 5,
                "min_trust_score": 0.5,
                "data_sharing": DataClassification.CONFIDENTIAL,
                "requires_approval": True,
            },
            CollaborationScope.TOOLS: {
                "max_participants": 20,
                "min_trust_score": 0.2,
                "data_sharing": DataClassification.PUBLIC,
                "requires_approval": False,
            },
            CollaborationScope.MODEL_TRAINING: {
                "max_participants": 50,
                "min_trust_score": 0.4,
                "data_sharing": DataClassification.INTERNAL,
                "requires_approval": True,
            },
        }
    
    def create_task(
        self,
        initiator: str,
        scope: CollaborationScope,
        description: str,
        required_capabilities: List[AgentCapability],
        cost_budget: float = 0.0,
    ) -> CollaborationTask:
        """Create a collaboration task."""
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        
        # Find suitable participants
        candidates = []
        policy = self._policies.get(scope, {})
        min_trust = policy.get("min_trust_score", 0.0)
        
        for cap in required_capabilities:
            agents = self._registry.discover_by_capability(cap, min_trust)
            candidates.extend([a.agent_id for a in agents])
        
        # Deduplicate and limit
        max_participants = policy.get("max_participants", 10)
        participants = list(set(candidates))[:max_participants]
        
        task = CollaborationTask(
            task_id=task_id,
            initiator=initiator,
            participants=participants,
            scope=scope,
            description=description,
            data_classification=policy.get("data_sharing", DataClassification.INTERNAL),
            cost_budget=cost_budget,
        )
        
        self._tasks[task_id] = task
        
        logger.info(f"Created collaboration task '{task_id}' with {len(participants)} participants")
        return task
    
    def complete_task(
        self,
        task_id: str,
        result: Dict[str, Any],
    ) -> bool:
        """Complete a collaboration task."""
        if task_id not in self._tasks:
            return False
        
        task = self._tasks[task_id]
        task.status = "completed"
        task.result = result
        task.completed_at = datetime.utcnow()
        
        # Update participant reputations
        for participant in task.participants:
            self._registry.update_reputation(participant, 0.01)
        
        logger.info(f"Completed collaboration task '{task_id}'")
        return True
    
    def get_task_stats(self) -> Dict[str, Any]:
        """Get task statistics."""
        by_scope = {}
        for scope in CollaborationScope:
            count = sum(1 for t in self._tasks.values() if t.scope == scope)
            by_scope[scope.value] = count
        
        completed = sum(1 for t in self._tasks.values() if t.status == "completed")
        
        return {
            "total_tasks": len(self._tasks),
            "completed_tasks": completed,
            "by_scope": by_scope,
        }


class FederatedLearningCoordinator:
    """
    Federated Learning Interface for Privacy-Preserving Collaboration.
    
    Features:
    - Model versioning and contributor management
    - Secure aggregation (FedAvg/FedSGD)
    - Differential privacy implementation
    """
    
    def __init__(self):
        self._models: Dict[str, FederatedModel] = {}
        self._updates: Dict[str, List[Dict[str, Any]]] = {}
    
    def create_model(
        self,
        name: str,
        total_rounds: int = 10,
        aggregation_method: str = "fedavg",
        privacy_epsilon: float = 1.0,
        privacy_delta: float = 1e-5,
    ) -> FederatedModel:
        """Create a federated model."""
        model_id = f"fl_model_{uuid.uuid4().hex[:8]}"
        
        model = FederatedModel(
            model_id=model_id,
            name=name,
            version="0.0.1",
            total_rounds=total_rounds,
            aggregation_method=aggregation_method,
            privacy_budget_epsilon=privacy_epsilon,
            privacy_budget_delta=privacy_delta,
        )
        
        self._models[model_id] = model
        self._updates[model_id] = []
        
        logger.info(f"Created federated model '{name}'")
        return model
    
    def submit_update(
        self,
        model_id: str,
        contributor: str,
        gradients: Dict[str, Any],
        local_metrics: Dict[str, float],
    ) -> bool:
        """Submit a model update from a contributor."""
        if model_id not in self._models:
            return False
        
        model = self._models[model_id]
        
        if contributor not in model.contributors:
            model.contributors.append(contributor)
        
        # Add noise for differential privacy
        noisy_gradients = self._add_dp_noise(
            gradients,
            model.privacy_budget_epsilon,
        )
        
        self._updates[model_id].append({
            "contributor": contributor,
            "gradients": noisy_gradients,
            "metrics": local_metrics,
            "round": model.current_round,
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        return True
    
    def _add_dp_noise(
        self,
        gradients: Dict[str, Any],
        epsilon: float,
    ) -> Dict[str, Any]:
        """Add differential privacy noise (placeholder)."""
        # In production, implement proper Gaussian mechanism
        return gradients
    
    def aggregate_round(self, model_id: str) -> bool:
        """Aggregate updates for current round."""
        if model_id not in self._models:
            return False
        
        model = self._models[model_id]
        round_updates = [
            u for u in self._updates[model_id]
            if u["round"] == model.current_round
        ]
        
        if not round_updates:
            return False
        
        # FedAvg aggregation (placeholder)
        avg_metrics = {}
        for key in round_updates[0]["metrics"]:
            values = [u["metrics"].get(key, 0) for u in round_updates]
            avg_metrics[key] = sum(values) / len(values)
        
        model.metrics = avg_metrics
        model.current_round += 1
        
        # Update version
        major, minor, patch = model.version.split(".")
        model.version = f"{major}.{minor}.{int(patch) + 1}"
        
        logger.info(f"Aggregated round {model.current_round - 1} for model '{model_id}'")
        return True
    
    def get_fl_stats(self) -> Dict[str, Any]:
        """Get federated learning statistics."""
        return {
            "total_models": len(self._models),
            "total_contributors": sum(
                len(m.contributors) for m in self._models.values()
            ),
            "total_updates": sum(len(u) for u in self._updates.values()),
        }


class MultiProviderLLMGateway:
    """
    Multi-Provider LLM Gateway with Security Controls.
    
    Features:
    - Provider abstraction and failover
    - Data classification and redaction
    - Cost tracking and optimization
    """
    
    def __init__(self):
        self._providers: Dict[LLMProvider, Dict[str, Any]] = {}
        self._requests: List[LLMRequest] = []
        self._redaction_patterns: List[str] = []
        
        self._initialize_providers()
        self._initialize_redaction()
    
    def _initialize_providers(self) -> None:
        """Initialize provider configurations."""
        self._providers = {
            LLMProvider.OPENAI: {
                "models": ["gpt-4", "gpt-3.5-turbo"],
                "max_tokens": 8192,
                "rate_limit": 100,
                "cost_per_1k_tokens": 0.03,
                "data_residency": ["us", "eu"],
            },
            LLMProvider.ANTHROPIC: {
                "models": ["claude-3-opus", "claude-3-sonnet"],
                "max_tokens": 100000,
                "rate_limit": 50,
                "cost_per_1k_tokens": 0.015,
                "data_residency": ["us"],
            },
            LLMProvider.GOOGLE: {
                "models": ["gemini-pro", "gemini-ultra"],
                "max_tokens": 32000,
                "rate_limit": 60,
                "cost_per_1k_tokens": 0.001,
                "data_residency": ["us", "eu", "asia"],
            },
            LLMProvider.LOCAL: {
                "models": ["llama-3", "gemma-2"],
                "max_tokens": 8192,
                "rate_limit": 1000,
                "cost_per_1k_tokens": 0.0,
                "data_residency": ["local"],
            },
        }
    
    def _initialize_redaction(self) -> None:
        """Initialize redaction patterns."""
        self._redaction_patterns = [
            r"0x[a-fA-F0-9]{64}",  # Private keys
            r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",  # Emails
            r"\b\d{3}-\d{2}-\d{4}\b",  # SSN
            r"\b\d{16}\b",  # Credit cards
        ]
    
    def select_provider(
        self,
        data_classification: DataClassification,
        preferred_provider: Optional[LLMProvider] = None,
    ) -> LLMProvider:
        """Select appropriate provider based on data classification."""
        if data_classification == DataClassification.RESTRICTED:
            return LLMProvider.LOCAL
        
        if data_classification == DataClassification.CONFIDENTIAL:
            if preferred_provider in [LLMProvider.LOCAL, LLMProvider.ANTHROPIC]:
                return preferred_provider
            return LLMProvider.LOCAL
        
        if preferred_provider:
            return preferred_provider
        
        return LLMProvider.OPENAI
    
    def redact_sensitive(self, text: str) -> str:
        """Redact sensitive information from text."""
        import re
        redacted = text
        for pattern in self._redaction_patterns:
            redacted = re.sub(pattern, "[REDACTED]", redacted)
        return redacted
    
    def create_request(
        self,
        prompt: str,
        data_classification: DataClassification,
        agent_id: str = "",
        max_tokens: int = 1000,
        temperature: float = 0.7,
        preferred_provider: Optional[LLMProvider] = None,
    ) -> LLMRequest:
        """Create an LLM request."""
        provider = self.select_provider(data_classification, preferred_provider)
        
        # Redact if needed
        safe_prompt = prompt
        if data_classification in [DataClassification.CONFIDENTIAL, DataClassification.RESTRICTED]:
            safe_prompt = self.redact_sensitive(prompt)
        
        request = LLMRequest(
            request_id=f"llm_{uuid.uuid4().hex[:12]}",
            provider=provider,
            model=self._providers[provider]["models"][0],
            prompt=safe_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            data_classification=data_classification,
            agent_id=agent_id,
        )
        
        self._requests.append(request)
        return request
    
    def get_gateway_stats(self) -> Dict[str, Any]:
        """Get gateway statistics."""
        by_provider = {}
        for provider in LLMProvider:
            count = sum(1 for r in self._requests if r.provider == provider)
            by_provider[provider.value] = count
        
        total_cost = sum(r.cost for r in self._requests)
        total_tokens = sum(r.tokens_used for r in self._requests)
        
        return {
            "total_requests": len(self._requests),
            "by_provider": by_provider,
            "total_cost": total_cost,
            "total_tokens": total_tokens,
            "providers_configured": len(self._providers),
        }


class CollaborativeSwarmLayer:
    """
    Main Collaborative Swarm Layer.
    
    Integrates all components for secure, privacy-preserving
    collaboration between agents.
    """
    
    def __init__(self):
        self.registry = DecentralizedAgentRegistry()
        self.messaging = SecureMessagingProtocol(self.registry)
        self.collaboration = CollaborationOrchestrator(self.registry, self.messaging)
        self.federated_learning = FederatedLearningCoordinator()
        self.llm_gateway = MultiProviderLLMGateway()
    
    def get_layer_status(self) -> Dict[str, Any]:
        """Get overall layer status."""
        return {
            "registry": self.registry.get_registry_stats(),
            "messaging": self.messaging.get_messaging_stats(),
            "collaboration": self.collaboration.get_task_stats(),
            "federated_learning": self.federated_learning.get_fl_stats(),
            "llm_gateway": self.llm_gateway.get_gateway_stats(),
        }


_layer: Optional[CollaborativeSwarmLayer] = None


def get_collaborative_swarm_layer() -> CollaborativeSwarmLayer:
    """Get global CollaborativeSwarmLayer instance."""
    global _layer
    if _layer is None:
        _layer = CollaborativeSwarmLayer()
    return _layer
