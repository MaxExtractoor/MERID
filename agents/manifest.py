"""
MERID Agent Manifest System - Section 4: LLM Agent Design

Defines agent capabilities, constraints, and allowed tools.
Each agent has a narrow role with explicit permissions.

Agent Roles:
- BullAnalyst: Searches for long opportunities
- BearAnalyst: Focuses on downside/shorts  
- RiskManager: Enforces limits, can veto
- SentimentAnalyst: Social/news sentiment
- TechnicalAnalyst: Chart patterns, indicators
- ExecutionAgent: Executes approved plans
- GovernanceAgent: Final authority, kill switch
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("agents.manifest")


class AgentRole(str, Enum):
    """Specialized agent roles."""
    BULL_ANALYST = "bull_analyst"
    BEAR_ANALYST = "bear_analyst"
    RISK_MANAGER = "risk_manager"
    SENTIMENT_ANALYST = "sentiment_analyst"
    TECHNICAL_ANALYST = "technical_analyst"
    FUNDAMENTAL_ANALYST = "fundamental_analyst"
    ARBITRAGE_ANALYST = "arbitrage_analyst"
    EXECUTION_AGENT = "execution_agent"
    GOVERNANCE_AGENT = "governance_agent"
    COORDINATOR = "coordinator"


class AgentPermission(str, Enum):
    """Agent permission tiers."""
    READ_ONLY = "read_only"           # Can only read data
    PROPOSE = "propose"               # Can propose trades
    EXECUTE_SMALL = "execute_small"   # Execute up to $1000
    EXECUTE_FULL = "execute_full"     # Execute any approved size
    VETO = "veto"                     # Can veto consensus
    KILL_SWITCH = "kill_switch"       # Can trigger kill switch


class AgentStatus(str, Enum):
    """Agent operational status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    SAFE_MODE = "safe_mode"


@dataclass
class ToolDefinition:
    """Definition of a tool an agent can use."""
    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    rate_limit: int = 60         # Calls per minute
    timeout_seconds: float = 30.0
    requires_permission: AgentPermission = AgentPermission.READ_ONLY
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "rate_limit": self.rate_limit,
            "timeout_seconds": self.timeout_seconds,
            "requires_permission": self.requires_permission.value,
        }


@dataclass
class AgentConstraints:
    """Constraints and safeguards for an agent."""
    # Output constraints
    max_output_tokens: int = 2000
    required_output_schema: str = ""      # Schema name for validation
    
    # Behavioral constraints
    max_opinions_per_minute: int = 10
    max_tool_calls_per_minute: int = 30
    
    # Scope constraints
    allowed_symbols: List[str] = field(default_factory=list)  # Empty = all
    allowed_venues: List[str] = field(default_factory=list)   # Empty = all
    max_position_size_usd: float = 10000.0
    
    # Safety constraints
    cannot_self_modify: bool = True
    cannot_spawn_agents: bool = True
    cannot_expand_scope: bool = True
    cannot_access_secrets_directly: bool = True
    
    # Escalation rules
    escalate_on_low_confidence: float = 0.3   # Escalate if confidence < this
    escalate_on_disagreement: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_output_tokens": self.max_output_tokens,
            "required_output_schema": self.required_output_schema,
            "max_opinions_per_minute": self.max_opinions_per_minute,
            "max_tool_calls_per_minute": self.max_tool_calls_per_minute,
            "allowed_symbols": self.allowed_symbols,
            "allowed_venues": self.allowed_venues,
            "max_position_size_usd": self.max_position_size_usd,
            "cannot_self_modify": self.cannot_self_modify,
            "cannot_spawn_agents": self.cannot_spawn_agents,
            "cannot_expand_scope": self.cannot_expand_scope,
            "cannot_access_secrets_directly": self.cannot_access_secrets_directly,
            "escalate_on_low_confidence": self.escalate_on_low_confidence,
            "escalate_on_disagreement": self.escalate_on_disagreement,
        }


@dataclass
class AgentManifest:
    """
    Complete manifest defining an agent's capabilities and constraints.
    
    This is the "constitution" for the agent - it defines what the agent
    can and cannot do, what tools it has access to, and how it should behave.
    """
    
    # Identity
    agent_id: str = field(default_factory=lambda: f"agent_{uuid.uuid4().hex[:8]}")
    name: str = ""
    role: AgentRole = AgentRole.BULL_ANALYST
    version: str = "1.0.0"
    
    # Permissions
    permissions: List[AgentPermission] = field(default_factory=lambda: [AgentPermission.READ_ONLY])
    
    # Tools
    allowed_tools: List[str] = field(default_factory=list)
    
    # Input/Output
    input_topics: List[str] = field(default_factory=list)   # Kafka topics to consume
    output_topics: List[str] = field(default_factory=list)  # Kafka topics to produce
    output_schemas: List[str] = field(default_factory=list) # Required output schemas
    
    # Constraints
    constraints: AgentConstraints = field(default_factory=AgentConstraints)
    
    # Behavioral rules
    fallback_behavior: str = "safe_mode"  # What to do on failure
    escalation_target: str = "governance_agent"
    
    # System prompt components
    constitution: str = ""      # Core rules and identity
    capabilities: str = ""      # What it can do
    limitations: str = ""       # What it cannot do
    
    # Metadata
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "role": self.role.value,
            "version": self.version,
            "permissions": [p.value for p in self.permissions],
            "allowed_tools": self.allowed_tools,
            "input_topics": self.input_topics,
            "output_topics": self.output_topics,
            "output_schemas": self.output_schemas,
            "constraints": self.constraints.to_dict(),
            "fallback_behavior": self.fallback_behavior,
            "escalation_target": self.escalation_target,
            "constitution": self.constitution,
            "capabilities": self.capabilities,
            "limitations": self.limitations,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    
    def has_permission(self, permission: AgentPermission) -> bool:
        """Check if agent has a specific permission."""
        return permission in self.permissions
    
    def can_use_tool(self, tool_name: str) -> bool:
        """Check if agent can use a specific tool."""
        return tool_name in self.allowed_tools
    
    def generate_system_prompt(self) -> str:
        """Generate the system prompt from manifest."""
        prompt_parts = [
            f"# Agent: {self.name}",
            f"Role: {self.role.value}",
            f"Version: {self.version}",
            "",
            "## Constitution",
            self.constitution or self._default_constitution(),
            "",
            "## Capabilities", 
            self.capabilities or self._default_capabilities(),
            "",
            "## Limitations",
            self.limitations or self._default_limitations(),
            "",
            "## Output Requirements",
            f"- All outputs MUST conform to schemas: {', '.join(self.output_schemas)}",
            "- Output MUST be valid JSON matching the schema",
            "- Non-conforming output will be rejected",
            "",
            "## Safety Rules",
            "- You CANNOT modify your own code or parameters",
            "- You CANNOT spawn new agents",
            "- You CANNOT expand your scope beyond defined limits",
            "- You CANNOT access secrets or credentials directly",
            f"- Maximum position size: ${self.constraints.max_position_size_usd}",
            f"- Escalate to {self.escalation_target} when confidence < {self.constraints.escalate_on_low_confidence}",
        ]
        
        return "\n".join(prompt_parts)
    
    def _default_constitution(self) -> str:
        role_constitutions = {
            AgentRole.BULL_ANALYST: (
                "You are a Bull Analyst agent. Your role is to identify and analyze "
                "potential long opportunities. You look for bullish signals, positive "
                "momentum, and favorable risk/reward setups. You provide reasoned opinions "
                "but do not have final decision authority."
            ),
            AgentRole.BEAR_ANALYST: (
                "You are a Bear Analyst agent. Your role is to identify downside risks, "
                "potential short opportunities, and warn about overbought conditions. "
                "You provide critical analysis and skeptical viewpoints to balance the team."
            ),
            AgentRole.RISK_MANAGER: (
                "You are a Risk Manager agent. Your role is to enforce risk limits, "
                "evaluate position sizing, and VETO trades that exceed risk parameters. "
                "You have authority to block trades but not to initiate them."
            ),
            AgentRole.EXECUTION_AGENT: (
                "You are an Execution Agent. Your role is to execute APPROVED trade plans "
                "with minimal slippage. You do NOT make trading decisions - you only execute "
                "what has been approved by consensus and cleared by risk management."
            ),
            AgentRole.GOVERNANCE_AGENT: (
                "You are a Governance Agent. You have final authority over system operations "
                "including the kill switch. You resolve disputes, handle escalations, and "
                "ensure all agents operate within their defined constraints."
            ),
        }
        return role_constitutions.get(self.role, "You are a MERID trading agent.")
    
    def _default_capabilities(self) -> str:
        tool_list = ", ".join(self.allowed_tools) if self.allowed_tools else "none"
        return f"Allowed tools: {tool_list}"
    
    def _default_limitations(self) -> str:
        return (
            "- Cannot execute trades directly (must go through ExecutionAgent)\n"
            "- Cannot access external APIs except through approved tools\n"
            "- Cannot store state between sessions\n"
            "- Cannot communicate outside the MERID system"
        )


# ============================================
# PREDEFINED AGENT MANIFESTS
# ============================================

def create_bull_analyst_manifest(agent_id: str = None) -> AgentManifest:
    """Create manifest for Bull Analyst agent."""
    return AgentManifest(
        agent_id=agent_id or f"bull_{uuid.uuid4().hex[:8]}",
        name="Bull Analyst",
        role=AgentRole.BULL_ANALYST,
        permissions=[AgentPermission.READ_ONLY, AgentPermission.PROPOSE],
        allowed_tools=[
            "get_price",
            "get_orderbook",
            "get_technical_indicators",
            "get_sentiment",
            "get_news",
            "submit_opinion",
        ],
        input_topics=[
            "prices.spot.*",
            "prices.perps.*",
            "social.sentiment.*",
            "news.headlines.*",
        ],
        output_topics=["agent.opinions.*"],
        output_schemas=["AgentOpinion"],
        constraints=AgentConstraints(
            required_output_schema="AgentOpinion",
            max_position_size_usd=5000.0,
        ),
        constitution=(
            "You are a Bull Analyst. Your mission is to find profitable long opportunities. "
            "Analyze price action, sentiment, and fundamentals to identify assets with "
            "upside potential. Be optimistic but data-driven. Your opinions contribute to "
            "team consensus but are not final decisions."
        ),
    )


def create_bear_analyst_manifest(agent_id: str = None) -> AgentManifest:
    """Create manifest for Bear Analyst agent."""
    return AgentManifest(
        agent_id=agent_id or f"bear_{uuid.uuid4().hex[:8]}",
        name="Bear Analyst",
        role=AgentRole.BEAR_ANALYST,
        permissions=[AgentPermission.READ_ONLY, AgentPermission.PROPOSE],
        allowed_tools=[
            "get_price",
            "get_orderbook",
            "get_technical_indicators",
            "get_sentiment",
            "get_news",
            "get_risk_metrics",
            "submit_opinion",
        ],
        input_topics=[
            "prices.spot.*",
            "prices.perps.*",
            "social.sentiment.*",
            "news.headlines.*",
            "risk.metrics",
        ],
        output_topics=["agent.opinions.*"],
        output_schemas=["AgentOpinion"],
        constraints=AgentConstraints(
            required_output_schema="AgentOpinion",
            max_position_size_usd=5000.0,
        ),
        constitution=(
            "You are a Bear Analyst. Your mission is to identify risks and potential "
            "short opportunities. Look for overbought conditions, negative catalysts, "
            "and weak fundamentals. Be skeptical and provide critical analysis to "
            "balance overly bullish sentiment."
        ),
    )


def create_risk_manager_manifest(agent_id: str = None) -> AgentManifest:
    """Create manifest for Risk Manager agent."""
    return AgentManifest(
        agent_id=agent_id or f"risk_{uuid.uuid4().hex[:8]}",
        name="Risk Manager",
        role=AgentRole.RISK_MANAGER,
        permissions=[
            AgentPermission.READ_ONLY,
            AgentPermission.PROPOSE,
            AgentPermission.VETO,
        ],
        allowed_tools=[
            "get_positions",
            "get_exposure",
            "get_risk_metrics",
            "get_pnl",
            "submit_opinion",
            "veto_plan",
            "adjust_position_size",
        ],
        input_topics=[
            "agent.opinions.*",
            "consensus.*",
            "risk.metrics",
            "trades.executed.*",
        ],
        output_topics=["agent.opinions.*", "risk.alerts.*"],
        output_schemas=["AgentOpinion", "RiskDecision"],
        constraints=AgentConstraints(
            required_output_schema="RiskDecision",
            max_position_size_usd=10000.0,
        ),
        constitution=(
            "You are a Risk Manager. Your PRIMARY duty is to protect capital. "
            "You review all trade plans for risk compliance. You CAN and SHOULD "
            "veto trades that exceed risk limits. You cannot initiate trades, "
            "only approve, reduce, or veto them. Safety is your top priority."
        ),
    )


def create_execution_agent_manifest(agent_id: str = None) -> AgentManifest:
    """Create manifest for Execution Agent."""
    return AgentManifest(
        agent_id=agent_id or f"exec_{uuid.uuid4().hex[:8]}",
        name="Execution Agent",
        role=AgentRole.EXECUTION_AGENT,
        permissions=[
            AgentPermission.READ_ONLY,
            AgentPermission.EXECUTE_FULL,
        ],
        allowed_tools=[
            "get_price",
            "get_orderbook",
            "place_order",
            "cancel_order",
            "get_order_status",
            "get_positions",
        ],
        input_topics=[
            "consensus.*",
            "prices.spot.*",
            "orderbook.l2.*",
        ],
        output_topics=["trades.executed.*", "orders.placed.*"],
        output_schemas=["TradeExecution"],
        constraints=AgentConstraints(
            required_output_schema="TradeExecution",
            max_position_size_usd=50000.0,  # Higher limit for execution
        ),
        constitution=(
            "You are an Execution Agent. You execute APPROVED trade plans ONLY. "
            "You do NOT make trading decisions. You optimize execution quality "
            "(minimize slippage, choose best venue). You MUST have an approved "
            "plan_id before executing any trade. Unauthorized execution is forbidden."
        ),
    )


def create_governance_agent_manifest(agent_id: str = None) -> AgentManifest:
    """Create manifest for Governance Agent."""
    return AgentManifest(
        agent_id=agent_id or f"gov_{uuid.uuid4().hex[:8]}",
        name="Governance Agent",
        role=AgentRole.GOVERNANCE_AGENT,
        permissions=[
            AgentPermission.READ_ONLY,
            AgentPermission.VETO,
            AgentPermission.KILL_SWITCH,
        ],
        allowed_tools=[
            "get_system_status",
            "get_agent_status",
            "override_decision",
            "trigger_kill_switch",
            "resume_trading",
            "adjust_global_limits",
        ],
        input_topics=[
            "agent.opinions.*",
            "consensus.*",
            "risk.alerts.*",
            "trades.executed.*",
        ],
        output_topics=["governance.*", "alerts.*"],
        output_schemas=["GovernanceDecision"],
        constraints=AgentConstraints(
            required_output_schema="GovernanceDecision",
            escalate_on_low_confidence=0.0,  # Never escalate, final authority
        ),
        constitution=(
            "You are the Governance Agent. You have FINAL AUTHORITY over system "
            "operations. You handle escalations, resolve disputes, and can trigger "
            "the kill switch in emergencies. Use your authority sparingly and only "
            "when necessary. Your decisions are logged and audited."
        ),
    )


# ============================================
# AGENT REGISTRY
# ============================================

class AgentRegistry:
    """Registry of all agent manifests."""
    
    _instance: Optional["AgentRegistry"] = None
    
    def __init__(self):
        self._manifests: Dict[str, AgentManifest] = {}
        self._tools: Dict[str, ToolDefinition] = {}
        self._status: Dict[str, AgentStatus] = {}
        self._heartbeats: Dict[str, float] = {}
    
    @classmethod
    def get_instance(cls) -> "AgentRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def register_agent(self, manifest: AgentManifest) -> None:
        """Register an agent manifest."""
        self._manifests[manifest.agent_id] = manifest
        self._status[manifest.agent_id] = AgentStatus.OFFLINE
        logger.info(f"Registered agent: {manifest.agent_id} ({manifest.role.value})")
    
    def register_tool(self, tool: ToolDefinition) -> None:
        """Register a tool definition."""
        self._tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")
    
    def get_manifest(self, agent_id: str) -> Optional[AgentManifest]:
        """Get agent manifest by ID."""
        return self._manifests.get(agent_id)
    
    def get_tool(self, tool_name: str) -> Optional[ToolDefinition]:
        """Get tool definition by name."""
        return self._tools.get(tool_name)
    
    def update_status(self, agent_id: str, status: AgentStatus) -> None:
        """Update agent status."""
        self._status[agent_id] = status
        self._heartbeats[agent_id] = time.time()
    
    def record_heartbeat(self, agent_id: str) -> None:
        """Record agent heartbeat."""
        self._heartbeats[agent_id] = time.time()
        if self._status.get(agent_id) == AgentStatus.OFFLINE:
            self._status[agent_id] = AgentStatus.HEALTHY
    
    def get_status(self, agent_id: str) -> AgentStatus:
        """Get agent status."""
        return self._status.get(agent_id, AgentStatus.OFFLINE)
    
    def check_heartbeats(self, timeout_seconds: float = 60.0) -> List[str]:
        """Check for agents with stale heartbeats."""
        stale_agents = []
        cutoff = time.time() - timeout_seconds
        
        for agent_id, last_heartbeat in self._heartbeats.items():
            if last_heartbeat < cutoff:
                self._status[agent_id] = AgentStatus.OFFLINE
                stale_agents.append(agent_id)
        
        return stale_agents
    
    def list_agents(self) -> List[Dict[str, Any]]:
        """List all registered agents."""
        return [
            {
                "agent_id": m.agent_id,
                "name": m.name,
                "role": m.role.value,
                "status": self._status.get(m.agent_id, AgentStatus.OFFLINE).value,
                "last_heartbeat": self._heartbeats.get(m.agent_id, 0),
            }
            for m in self._manifests.values()
        ]
    
    def get_agents_by_role(self, role: AgentRole) -> List[AgentManifest]:
        """Get all agents with a specific role."""
        return [m for m in self._manifests.values() if m.role == role]


def get_agent_registry() -> AgentRegistry:
    """Get the global agent registry."""
    return AgentRegistry.get_instance()


def initialize_default_agents() -> None:
    """Initialize the default agent roster."""
    registry = get_agent_registry()
    
    # Register default agents
    registry.register_agent(create_bull_analyst_manifest("bull_primary"))
    registry.register_agent(create_bear_analyst_manifest("bear_primary"))
    registry.register_agent(create_risk_manager_manifest("risk_primary"))
    registry.register_agent(create_execution_agent_manifest("exec_primary"))
    registry.register_agent(create_governance_agent_manifest("gov_primary"))
    
    logger.info("Default agent roster initialized")
