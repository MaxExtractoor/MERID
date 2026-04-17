"""
LLM Governance — Sprint 14: LLM Instrumentation, RAG & Guardrails

Defines:
  - LLM roles and tool contracts
  - Prompt registry with versioning
  - Trace / observability models
  - Policy gate for tool-call authorization
  - Guardrails engine (injection defense, output constraints, autonomy levels)
  - Quality eval models
  - LLMGovernanceStore (in-memory singleton)
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── Enums ─────────────────────────────────────────────────────────

class LLMRole(str, Enum):
    RESEARCH = "research"
    DEV_SWARM_ASSISTANT = "dev_swarm_assistant"
    TRADING_INTELLIGENCE = "trading_intelligence"
    OPS_ASSISTANT = "ops_assistant"
    COGNITIVE_ASSISTANT = "cognitive_assistant"
    SPORTS_ANALYST = "sports_analyst"


class ToolPermission(str, Enum):
    READ = "read"
    WRITE_PROPOSAL = "write_proposal"
    WRITE_COMMENT = "write_comment"
    WRITE_LABEL = "write_label"
    EXECUTE_SIMULATION = "execute_simulation"


class AutonomyLevel(str, Enum):
    ASSISTIVE = "assistive"
    BOUNDED = "bounded"
    CONDITIONAL = "conditional"
    FULL = "full"


class GuardrailVerdict(str, Enum):
    ALLOW = "allow"
    WARN = "warn"
    BLOCK = "block"


class EvalDimension(str, Enum):
    FACTUALITY = "factuality"
    RELEVANCE = "relevance"
    SAFETY = "safety"
    POLICY_FIT = "policy_fit"


class TraceStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class InjectionRiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SuggestionStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class FeedbackRating(str, Enum):
    HELPFUL = "helpful"
    WRONG = "wrong"
    RISKY = "risky"


# ── Tool Contract ─────────────────────────────────────────────────

@dataclass
class ToolContract:
    tool_id: str = ""
    name: str = ""
    description: str = ""
    allowed_roles: List[LLMRole] = field(default_factory=list)
    permissions: List[ToolPermission] = field(default_factory=list)
    max_calls_per_minute: int = 60
    max_payload_bytes: int = 65536
    idempotent: bool = True
    read_sources: List[str] = field(default_factory=list)
    write_targets: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "name": self.name,
            "description": self.description,
            "allowed_roles": [r.value for r in self.allowed_roles],
            "permissions": [p.value for p in self.permissions],
            "max_calls_per_minute": self.max_calls_per_minute,
            "max_payload_bytes": self.max_payload_bytes,
            "idempotent": self.idempotent,
            "read_sources": self.read_sources,
            "write_targets": self.write_targets,
        }


# ── Role Definition ───────────────────────────────────────────────

@dataclass
class RoleDefinition:
    role: LLMRole = LLMRole.RESEARCH
    display_name: str = ""
    description: str = ""
    system_prompt: str = ""
    allowed_tools: List[str] = field(default_factory=list)
    autonomy_level: AutonomyLevel = AutonomyLevel.ASSISTIVE
    max_tokens_per_request: int = 4096
    max_requests_per_minute: int = 30

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role.value,
            "display_name": self.display_name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "allowed_tools": self.allowed_tools,
            "autonomy_level": self.autonomy_level.value,
            "max_tokens_per_request": self.max_tokens_per_request,
            "max_requests_per_minute": self.max_requests_per_minute,
        }


# ── Prompt Registry ───────────────────────────────────────────────

@dataclass
class PromptVersion:
    id: str = ""
    name: str = ""
    version: int = 1
    content: str = ""
    role: LLMRole = LLMRole.RESEARCH
    tags: List[str] = field(default_factory=list)
    created_at: float = 0.0
    created_by: str = ""
    is_active: bool = True
    eval_score: Optional[float] = None

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
        if self.created_at == 0.0:
            self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "content": self.content,
            "role": self.role.value,
            "tags": self.tags,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "is_active": self.is_active,
            "eval_score": self.eval_score,
        }


# ── Trace / Observability ────────────────────────────────────────

@dataclass
class ToolCallRecord:
    tool_id: str = ""
    tool_name: str = ""
    input_payload: Dict[str, Any] = field(default_factory=dict)
    output_payload: Dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    success: bool = True
    blocked: bool = False
    block_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "tool_name": self.tool_name,
            "input_payload": self.input_payload,
            "output_payload": self.output_payload,
            "latency_ms": self.latency_ms,
            "success": self.success,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
        }


@dataclass
class LLMTrace:
    trace_id: str = ""
    role: LLMRole = LLMRole.RESEARCH
    prompt_version_id: str = ""
    model: str = ""
    status: TraceStatus = TraceStatus.PENDING
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    tool_calls: List[ToolCallRecord] = field(default_factory=list)
    guardrail_verdicts: List[Dict[str, Any]] = field(default_factory=list)
    eval_scores: Dict[str, float] = field(default_factory=dict)
    created_at: float = 0.0
    completed_at: float = 0.0
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.trace_id:
            self.trace_id = str(uuid.uuid4())
        if self.created_at == 0.0:
            self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "role": self.role.value,
            "prompt_version_id": self.prompt_version_id,
            "model": self.model,
            "status": self.status.value,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "guardrail_verdicts": self.guardrail_verdicts,
            "eval_scores": self.eval_scores,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "metadata": self.metadata,
        }


# ── Quality Eval ──────────────────────────────────────────────────

@dataclass
class QualityEval:
    id: str = ""
    trace_id: str = ""
    dimension: EvalDimension = EvalDimension.FACTUALITY
    score: float = 0.0
    explanation: str = ""
    evaluated_at: float = 0.0
    evaluator: str = "auto"

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
        if self.evaluated_at == 0.0:
            self.evaluated_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "dimension": self.dimension.value,
            "score": self.score,
            "explanation": self.explanation,
            "evaluated_at": self.evaluated_at,
            "evaluator": self.evaluator,
        }


# ── Guardrail Models ─────────────────────────────────────────────

@dataclass
class GuardrailRule:
    id: str = ""
    name: str = ""
    description: str = ""
    applies_to_roles: List[LLMRole] = field(default_factory=list)
    condition: str = ""
    verdict: GuardrailVerdict = GuardrailVerdict.BLOCK
    enabled: bool = True

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "applies_to_roles": [r.value for r in self.applies_to_roles],
            "condition": self.condition,
            "verdict": self.verdict.value,
            "enabled": self.enabled,
        }


@dataclass
class GuardrailCheckResult:
    rule_id: str = ""
    rule_name: str = ""
    verdict: GuardrailVerdict = GuardrailVerdict.ALLOW
    reason: str = ""
    checked_at: float = 0.0

    def __post_init__(self):
        if self.checked_at == 0.0:
            self.checked_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "verdict": self.verdict.value,
            "reason": self.reason,
            "checked_at": self.checked_at,
        }


# ── LLM Suggestion (AI Suggestion Lane) ──────────────────────────

@dataclass
class LLMSuggestion:
    id: str = ""
    trace_id: str = ""
    role: LLMRole = LLMRole.RESEARCH
    title: str = ""
    description: str = ""
    evidence: List[str] = field(default_factory=list)
    reasoning: str = ""
    proposed_action: Dict[str, Any] = field(default_factory=dict)
    risk_level: str = "LOW"
    status: SuggestionStatus = SuggestionStatus.PENDING
    feedback: Optional[FeedbackRating] = None
    feedback_note: str = ""
    created_at: float = 0.0

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
        if self.created_at == 0.0:
            self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "role": self.role.value,
            "title": self.title,
            "description": self.description,
            "evidence": self.evidence,
            "reasoning": self.reasoning,
            "proposed_action": self.proposed_action,
            "risk_level": self.risk_level,
            "status": self.status.value,
            "feedback": self.feedback.value if self.feedback else None,
            "feedback_note": self.feedback_note,
            "created_at": self.created_at,
        }


# ── Aggregate Metrics ─────────────────────────────────────────────

@dataclass
class LLMGovernanceMetrics:
    total_traces: int = 0
    total_tool_calls: int = 0
    total_blocked: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_latency_ms: float = 0.0
    error_rate: float = 0.0
    block_rate: float = 0.0
    traces_by_role: Dict[str, int] = field(default_factory=dict)
    traces_by_status: Dict[str, int] = field(default_factory=dict)
    tool_calls_by_tool: Dict[str, int] = field(default_factory=dict)
    avg_eval_scores: Dict[str, float] = field(default_factory=dict)
    suggestions_pending: int = 0
    suggestions_accepted: int = 0
    suggestions_rejected: int = 0
    prompt_versions_active: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_traces": self.total_traces,
            "total_tool_calls": self.total_tool_calls,
            "total_blocked": self.total_blocked,
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost_usd,
            "avg_latency_ms": self.avg_latency_ms,
            "error_rate": self.error_rate,
            "block_rate": self.block_rate,
            "traces_by_role": self.traces_by_role,
            "traces_by_status": self.traces_by_status,
            "tool_calls_by_tool": self.tool_calls_by_tool,
            "avg_eval_scores": self.avg_eval_scores,
            "suggestions_pending": self.suggestions_pending,
            "suggestions_accepted": self.suggestions_accepted,
            "suggestions_rejected": self.suggestions_rejected,
            "prompt_versions_active": self.prompt_versions_active,
        }


# ── Default Role Definitions ─────────────────────────────────────

DEFAULT_ROLES: Dict[LLMRole, RoleDefinition] = {
    LLMRole.RESEARCH: RoleDefinition(
        role=LLMRole.RESEARCH,
        display_name="Research / Enrichment",
        description="External data, news, docs; read-only.",
        system_prompt=(
            "You are a MERID Research assistant. You may: "
            "(1) query external data sources, (2) summarize docs and news, "
            "(3) never modify internal state or place trades."
        ),
        allowed_tools=["get_brier_history", "get_slo_status", "get_pnl",
                        "get_odds_movement", "rag_dev", "rag_cognitive", "rag_sports"],
        autonomy_level=AutonomyLevel.ASSISTIVE,
    ),
    LLMRole.DEV_SWARM_ASSISTANT: RoleDefinition(
        role=LLMRole.DEV_SWARM_ASSISTANT,
        display_name="Dev Swarm Assistant",
        description="Code explainers, diff summarizers, proposal drafting; no direct deploy.",
        system_prompt=(
            "You are a MERID Dev Swarm assistant. You may: "
            "(1) inspect diffs and metrics, (2) propose DevProposals, "
            "(3) never push code, (4) never touch live markets directly."
        ),
        allowed_tools=["create_dev_proposal", "annotate_proposal",
                        "fetch_recent_regressions", "list_pending_approvals",
                        "rag_dev"],
        autonomy_level=AutonomyLevel.BOUNDED,
    ),
    LLMRole.TRADING_INTELLIGENCE: RoleDefinition(
        role=LLMRole.TRADING_INTELLIGENCE,
        display_name="Trading Intelligence",
        description="Narrative on markets, hypothesis generation; write to suggestion queues only.",
        system_prompt=(
            "You are a MERID Trading Intelligence agent. You may: "
            "(1) analyze market data and odds, (2) generate hypotheses, "
            "(3) write only to internal suggestion queues, never execute trades."
        ),
        allowed_tools=["get_opticodds_edges", "get_sports_events",
                        "get_market_calibration", "get_hypotheses",
                        "get_reality_debug_snapshot"],
        autonomy_level=AutonomyLevel.ASSISTIVE,
    ),
    LLMRole.OPS_ASSISTANT: RoleDefinition(
        role=LLMRole.OPS_ASSISTANT,
        display_name="Ops Assistant",
        description="Playbook lookup, runbook suggestion; propose actions only, never execute.",
        system_prompt=(
            "You are a MERID Ops assistant. You may: "
            "(1) look up playbooks and runbooks, (2) suggest operational actions, "
            "(3) never execute infrastructure changes directly."
        ),
        allowed_tools=["get_slo_status", "rag_dev", "rag_cognitive",
                        "list_pending_approvals"],
        autonomy_level=AutonomyLevel.ASSISTIVE,
    ),
    LLMRole.COGNITIVE_ASSISTANT: RoleDefinition(
        role=LLMRole.COGNITIVE_ASSISTANT,
        display_name="Cognitive Assistant",
        description="Hypothesis summarization, reality debug, cognitive health analysis.",
        system_prompt=(
            "You are a MERID Cognitive assistant. You may: "
            "(1) retrieve hypotheses and reality debug snapshots, "
            "(2) summarize cognitive health, (3) suggest hypothesis updates, "
            "(4) never modify hypotheses directly."
        ),
        allowed_tools=["get_hypotheses", "get_reality_debug_snapshot",
                        "get_team_diversity", "rag_cognitive"],
        autonomy_level=AutonomyLevel.ASSISTIVE,
    ),
    LLMRole.SPORTS_ANALYST: RoleDefinition(
        role=LLMRole.SPORTS_ANALYST,
        display_name="Sports Analyst",
        description="Edge explanations, odds movement narratives; no direct strategy changes.",
        system_prompt=(
            "You are a MERID Sports Betting analysis agent. "
            "Objectives: explain current edges using internal metrics and OpticOdds feeds. "
            "Never place bets or change limits; only propose insights and DevProposals."
        ),
        allowed_tools=["get_opticodds_edges", "get_sports_events",
                        "get_market_calibration", "rag_sports"],
        autonomy_level=AutonomyLevel.ASSISTIVE,
    ),
}


# ── Default Tool Contracts ────────────────────────────────────────

DEFAULT_TOOLS: Dict[str, ToolContract] = {
    "get_brier_history": ToolContract(
        tool_id="get_brier_history", name="Get Brier History",
        description="Retrieve Brier score history for an agent.",
        allowed_roles=[LLMRole.RESEARCH, LLMRole.COGNITIVE_ASSISTANT],
        permissions=[ToolPermission.READ],
        read_sources=["cognitive_store", "agent_metrics"],
    ),
    "get_slo_status": ToolContract(
        tool_id="get_slo_status", name="Get SLO Status",
        description="Retrieve SLO status for a subsystem.",
        allowed_roles=[LLMRole.RESEARCH, LLMRole.OPS_ASSISTANT],
        permissions=[ToolPermission.READ],
        read_sources=["observability", "slo_metrics"],
    ),
    "get_pnl": ToolContract(
        tool_id="get_pnl", name="Get PnL",
        description="Retrieve PnL series for a given horizon.",
        allowed_roles=[LLMRole.RESEARCH, LLMRole.TRADING_INTELLIGENCE],
        permissions=[ToolPermission.READ],
        read_sources=["portfolio", "positions"],
    ),
    "get_odds_movement": ToolContract(
        tool_id="get_odds_movement", name="Get Odds Movement",
        description="Retrieve odds movement history for an event.",
        allowed_roles=[LLMRole.RESEARCH, LLMRole.TRADING_INTELLIGENCE, LLMRole.SPORTS_ANALYST],
        permissions=[ToolPermission.READ],
        read_sources=["betting_consensus", "opticodds"],
    ),
    "create_dev_proposal": ToolContract(
        tool_id="create_dev_proposal", name="Create Dev Proposal",
        description="Create a new DevProposal in governance.",
        allowed_roles=[LLMRole.DEV_SWARM_ASSISTANT],
        permissions=[ToolPermission.WRITE_PROPOSAL],
        write_targets=["dev_swarm_governance"],
        idempotent=False,
    ),
    "annotate_proposal": ToolContract(
        tool_id="annotate_proposal", name="Annotate Proposal",
        description="Add a comment or label to an existing DevProposal.",
        allowed_roles=[LLMRole.DEV_SWARM_ASSISTANT],
        permissions=[ToolPermission.WRITE_COMMENT, ToolPermission.WRITE_LABEL],
        write_targets=["dev_swarm_governance"],
    ),
    "fetch_recent_regressions": ToolContract(
        tool_id="fetch_recent_regressions", name="Fetch Recent Regressions",
        description="List recent regression events.",
        allowed_roles=[LLMRole.DEV_SWARM_ASSISTANT, LLMRole.OPS_ASSISTANT],
        permissions=[ToolPermission.READ],
        read_sources=["dev_swarm_governance", "audit_log"],
    ),
    "list_pending_approvals": ToolContract(
        tool_id="list_pending_approvals", name="List Pending Approvals",
        description="List pending HITL approvals.",
        allowed_roles=[LLMRole.DEV_SWARM_ASSISTANT, LLMRole.OPS_ASSISTANT],
        permissions=[ToolPermission.READ],
        read_sources=["dev_swarm_governance"],
    ),
    "get_hypotheses": ToolContract(
        tool_id="get_hypotheses", name="Get Hypotheses",
        description="Retrieve hypotheses with optional filters.",
        allowed_roles=[LLMRole.TRADING_INTELLIGENCE, LLMRole.COGNITIVE_ASSISTANT],
        permissions=[ToolPermission.READ],
        read_sources=["cognitive_store"],
    ),
    "get_reality_debug_snapshot": ToolContract(
        tool_id="get_reality_debug_snapshot", name="Get Reality Debug Snapshot",
        description="Retrieve the latest reality debug report.",
        allowed_roles=[LLMRole.TRADING_INTELLIGENCE, LLMRole.COGNITIVE_ASSISTANT],
        permissions=[ToolPermission.READ],
        read_sources=["reality_debugger"],
    ),
    "get_team_diversity": ToolContract(
        tool_id="get_team_diversity", name="Get Team Diversity",
        description="Retrieve diversity metrics for a debate team.",
        allowed_roles=[LLMRole.COGNITIVE_ASSISTANT],
        permissions=[ToolPermission.READ],
        read_sources=["debate_teams"],
    ),
    "get_opticodds_edges": ToolContract(
        tool_id="get_opticodds_edges", name="Get OpticOdds Edges",
        description="Retrieve current edges from OpticOdds feed.",
        allowed_roles=[LLMRole.TRADING_INTELLIGENCE, LLMRole.SPORTS_ANALYST],
        permissions=[ToolPermission.READ],
        read_sources=["opticodds"],
    ),
    "get_sports_events": ToolContract(
        tool_id="get_sports_events", name="Get Sports Events",
        description="Retrieve sports events with filters.",
        allowed_roles=[LLMRole.TRADING_INTELLIGENCE, LLMRole.SPORTS_ANALYST],
        permissions=[ToolPermission.READ],
        read_sources=["betting_consensus"],
    ),
    "get_market_calibration": ToolContract(
        tool_id="get_market_calibration", name="Get Market Calibration",
        description="Retrieve calibration data for a market.",
        allowed_roles=[LLMRole.TRADING_INTELLIGENCE, LLMRole.SPORTS_ANALYST],
        permissions=[ToolPermission.READ],
        read_sources=["calibration_store"],
    ),
    "rag_dev": ToolContract(
        tool_id="rag_dev", name="RAG Dev",
        description="Retrieve relevant dev docs, runbooks, and proposals via RAG.",
        allowed_roles=[LLMRole.RESEARCH, LLMRole.DEV_SWARM_ASSISTANT, LLMRole.OPS_ASSISTANT],
        permissions=[ToolPermission.READ],
        read_sources=["rag_vector_store"],
    ),
    "rag_cognitive": ToolContract(
        tool_id="rag_cognitive", name="RAG Cognitive",
        description="Retrieve cognitive layer docs and regime notes via RAG.",
        allowed_roles=[LLMRole.RESEARCH, LLMRole.COGNITIVE_ASSISTANT, LLMRole.OPS_ASSISTANT],
        permissions=[ToolPermission.READ],
        read_sources=["rag_vector_store"],
    ),
    "rag_sports": ToolContract(
        tool_id="rag_sports", name="RAG Sports",
        description="Retrieve sports playbooks and historical notes via RAG.",
        allowed_roles=[LLMRole.RESEARCH, LLMRole.SPORTS_ANALYST],
        permissions=[ToolPermission.READ],
        read_sources=["rag_vector_store"],
    ),
}


# ── Default Guardrail Rules ──────────────────────────────────────

INJECTION_PATTERNS = [
    "ignore previous instructions",
    "ignore earlier instructions",
    "act as",
    "you are now",
    "disregard all",
    "override system",
    "forget your instructions",
    "new persona",
    "jailbreak",
    "DAN mode",
]

DEFAULT_GUARDRAIL_RULES: List[GuardrailRule] = [
    GuardrailRule(
        id="gr-tool-role-check",
        name="Tool-Role Authorization",
        description="Block tool calls not allowed for the requesting role.",
        applies_to_roles=list(LLMRole),
        condition="tool_not_in_role_allowlist",
        verdict=GuardrailVerdict.BLOCK,
    ),
    GuardrailRule(
        id="gr-rate-limit",
        name="Rate Limit",
        description="Block requests exceeding per-role rate limits.",
        applies_to_roles=list(LLMRole),
        condition="rate_limit_exceeded",
        verdict=GuardrailVerdict.BLOCK,
    ),
    GuardrailRule(
        id="gr-payload-size",
        name="Payload Size Limit",
        description="Block payloads exceeding tool max size.",
        applies_to_roles=list(LLMRole),
        condition="payload_too_large",
        verdict=GuardrailVerdict.BLOCK,
    ),
    GuardrailRule(
        id="gr-injection-defense",
        name="Prompt Injection Defense",
        description="Block or warn on suspected prompt injection patterns.",
        applies_to_roles=list(LLMRole),
        condition="injection_pattern_detected",
        verdict=GuardrailVerdict.BLOCK,
    ),
    GuardrailRule(
        id="gr-critical-action-hitl",
        name="Critical Action HITL",
        description="Require HITL approval for actions touching money, limits, or infra.",
        applies_to_roles=[LLMRole.DEV_SWARM_ASSISTANT, LLMRole.OPS_ASSISTANT],
        condition="critical_action_detected",
        verdict=GuardrailVerdict.WARN,
    ),
    GuardrailRule(
        id="gr-autonomy-cap",
        name="Autonomy Level Cap",
        description="Block actions that exceed the role's autonomy level.",
        applies_to_roles=list(LLMRole),
        condition="autonomy_exceeded",
        verdict=GuardrailVerdict.BLOCK,
    ),
]


# ── Policy Gate ───────────────────────────────────────────────────

class PolicyGate:
    """Evaluates tool-call requests against role permissions and guardrails."""

    def __init__(
        self,
        roles: Optional[Dict[LLMRole, RoleDefinition]] = None,
        tools: Optional[Dict[str, ToolContract]] = None,
        rules: Optional[List[GuardrailRule]] = None,
    ):
        self.roles = roles or dict(DEFAULT_ROLES)
        self.tools = tools or dict(DEFAULT_TOOLS)
        self.rules = rules or list(DEFAULT_GUARDRAIL_RULES)
        self._call_counts: Dict[str, List[float]] = {}

    def check_tool_call(
        self,
        role: LLMRole,
        tool_id: str,
        payload_bytes: int = 0,
        content: str = "",
    ) -> List[GuardrailCheckResult]:
        results: List[GuardrailCheckResult] = []

        # Tool-role authorization
        tool = self.tools.get(tool_id)
        if tool and role not in tool.allowed_roles:
            results.append(GuardrailCheckResult(
                rule_id="gr-tool-role-check",
                rule_name="Tool-Role Authorization",
                verdict=GuardrailVerdict.BLOCK,
                reason=f"Role '{role.value}' not allowed to call tool '{tool_id}'.",
            ))

        # Rate limit check
        role_def = self.roles.get(role)
        if role_def:
            now = time.time()
            key = f"{role.value}"
            calls = self._call_counts.get(key, [])
            calls = [t for t in calls if now - t < 60]
            if len(calls) >= role_def.max_requests_per_minute:
                results.append(GuardrailCheckResult(
                    rule_id="gr-rate-limit",
                    rule_name="Rate Limit",
                    verdict=GuardrailVerdict.BLOCK,
                    reason=f"Role '{role.value}' exceeded {role_def.max_requests_per_minute} req/min.",
                ))
            calls.append(now)
            self._call_counts[key] = calls

        # Payload size
        if tool and payload_bytes > tool.max_payload_bytes:
            results.append(GuardrailCheckResult(
                rule_id="gr-payload-size",
                rule_name="Payload Size Limit",
                verdict=GuardrailVerdict.BLOCK,
                reason=f"Payload {payload_bytes}B exceeds limit {tool.max_payload_bytes}B.",
            ))

        # Injection defense
        if content:
            injection_risk = self.detect_injection(content)
            if injection_risk in (InjectionRiskLevel.MEDIUM, InjectionRiskLevel.HIGH):
                results.append(GuardrailCheckResult(
                    rule_id="gr-injection-defense",
                    rule_name="Prompt Injection Defense",
                    verdict=GuardrailVerdict.BLOCK,
                    reason=f"Suspected prompt injection (risk={injection_risk.value}).",
                ))
            elif injection_risk == InjectionRiskLevel.LOW:
                results.append(GuardrailCheckResult(
                    rule_id="gr-injection-defense",
                    rule_name="Prompt Injection Defense",
                    verdict=GuardrailVerdict.WARN,
                    reason="Low-confidence injection pattern detected.",
                ))

        if not results:
            results.append(GuardrailCheckResult(
                rule_id="",
                rule_name="all-clear",
                verdict=GuardrailVerdict.ALLOW,
                reason="All checks passed.",
            ))

        return results

    @staticmethod
    def detect_injection(content: str) -> InjectionRiskLevel:
        lower = content.lower()
        matches = sum(1 for p in INJECTION_PATTERNS if p in lower)
        if matches >= 3:
            return InjectionRiskLevel.HIGH
        if matches == 2:
            return InjectionRiskLevel.MEDIUM
        if matches == 1:
            return InjectionRiskLevel.LOW
        return InjectionRiskLevel.NONE

    def is_blocked(self, results: List[GuardrailCheckResult]) -> bool:
        return any(r.verdict == GuardrailVerdict.BLOCK for r in results)


# ── LLM Governance Store (singleton) ─────────────────────────────

class LLMGovernanceStore:
    """In-memory store for LLM governance state."""

    def __init__(self):
        self.roles: Dict[LLMRole, RoleDefinition] = dict(DEFAULT_ROLES)
        self.tools: Dict[str, ToolContract] = dict(DEFAULT_TOOLS)
        self.prompts: Dict[str, PromptVersion] = {}
        self.traces: Dict[str, LLMTrace] = {}
        self.evals: Dict[str, QualityEval] = {}
        self.suggestions: Dict[str, LLMSuggestion] = {}
        self.guardrail_rules: List[GuardrailRule] = list(DEFAULT_GUARDRAIL_RULES)
        self.policy_gate = PolicyGate(self.roles, self.tools, self.guardrail_rules)

    # ── Roles ──
    def get_roles(self) -> List[RoleDefinition]:
        return list(self.roles.values())

    def get_role(self, role: LLMRole) -> Optional[RoleDefinition]:
        return self.roles.get(role)

    # ── Tools ──
    def get_tools(self) -> List[ToolContract]:
        return list(self.tools.values())

    def get_tool(self, tool_id: str) -> Optional[ToolContract]:
        return self.tools.get(tool_id)

    def get_tools_for_role(self, role: LLMRole) -> List[ToolContract]:
        return [t for t in self.tools.values() if role in t.allowed_roles]

    # ── Prompts ──
    def register_prompt(self, prompt: PromptVersion) -> PromptVersion:
        self.prompts[prompt.id] = prompt
        return prompt

    def get_prompts(self, role: Optional[LLMRole] = None, name: Optional[str] = None) -> List[PromptVersion]:
        results = list(self.prompts.values())
        if role:
            results = [p for p in results if p.role == role]
        if name:
            results = [p for p in results if p.name == name]
        return sorted(results, key=lambda p: (p.name, -p.version))

    def get_prompt(self, prompt_id: str) -> Optional[PromptVersion]:
        return self.prompts.get(prompt_id)

    def get_active_prompt(self, name: str) -> Optional[PromptVersion]:
        candidates = [p for p in self.prompts.values() if p.name == name and p.is_active]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.version)

    # ── Traces ──
    def record_trace(self, trace: LLMTrace) -> LLMTrace:
        self.traces[trace.trace_id] = trace
        return trace

    def get_trace(self, trace_id: str) -> Optional[LLMTrace]:
        return self.traces.get(trace_id)

    def get_traces(
        self,
        role: Optional[LLMRole] = None,
        status: Optional[TraceStatus] = None,
        limit: int = 100,
    ) -> List[LLMTrace]:
        results = list(self.traces.values())
        if role:
            results = [t for t in results if t.role == role]
        if status:
            results = [t for t in results if t.status == status]
        results.sort(key=lambda t: t.created_at, reverse=True)
        return results[:limit]

    def complete_trace(
        self,
        trace_id: str,
        status: TraceStatus = TraceStatus.COMPLETED,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        latency_ms: float = 0.0,
        error: str = "",
    ) -> Optional[LLMTrace]:
        trace = self.traces.get(trace_id)
        if not trace:
            return None
        trace.status = status
        trace.output_tokens = output_tokens
        trace.total_tokens = trace.input_tokens + output_tokens
        trace.cost_usd = cost_usd
        trace.latency_ms = latency_ms
        trace.completed_at = time.time()
        trace.error = error
        return trace

    # ── Evals ──
    def record_eval(self, eval_obj: QualityEval) -> QualityEval:
        self.evals[eval_obj.id] = eval_obj
        # Also attach to trace
        trace = self.traces.get(eval_obj.trace_id)
        if trace:
            trace.eval_scores[eval_obj.dimension.value] = eval_obj.score
        return eval_obj

    def get_evals(self, trace_id: Optional[str] = None) -> List[QualityEval]:
        results = list(self.evals.values())
        if trace_id:
            results = [e for e in results if e.trace_id == trace_id]
        return sorted(results, key=lambda e: e.evaluated_at, reverse=True)

    # ── Suggestions ──
    def add_suggestion(self, suggestion: LLMSuggestion) -> LLMSuggestion:
        self.suggestions[suggestion.id] = suggestion
        return suggestion

    def get_suggestions(
        self,
        status: Optional[SuggestionStatus] = None,
        role: Optional[LLMRole] = None,
        limit: int = 50,
    ) -> List[LLMSuggestion]:
        results = list(self.suggestions.values())
        if status:
            results = [s for s in results if s.status == status]
        if role:
            results = [s for s in results if s.role == role]
        results.sort(key=lambda s: s.created_at, reverse=True)
        return results[:limit]

    def update_suggestion(
        self,
        suggestion_id: str,
        status: Optional[SuggestionStatus] = None,
        feedback: Optional[FeedbackRating] = None,
        feedback_note: str = "",
    ) -> Optional[LLMSuggestion]:
        s = self.suggestions.get(suggestion_id)
        if not s:
            return None
        if status:
            s.status = status
        if feedback:
            s.feedback = feedback
            s.feedback_note = feedback_note
        return s

    # ── Guardrails ──
    def check_tool_call(
        self,
        role: LLMRole,
        tool_id: str,
        payload_bytes: int = 0,
        content: str = "",
    ) -> List[GuardrailCheckResult]:
        return self.policy_gate.check_tool_call(role, tool_id, payload_bytes, content)

    def get_guardrail_rules(self) -> List[GuardrailRule]:
        return self.guardrail_rules

    # ── Metrics ──
    def compute_metrics(self) -> LLMGovernanceMetrics:
        traces = list(self.traces.values())
        total = len(traces)
        if total == 0:
            return LLMGovernanceMetrics(
                prompt_versions_active=sum(1 for p in self.prompts.values() if p.is_active),
            )

        total_tokens = sum(t.total_tokens for t in traces)
        total_cost = sum(t.cost_usd for t in traces)
        total_tool_calls = sum(len(t.tool_calls) for t in traces)
        total_blocked = sum(
            1 for t in traces
            if any(v.get("verdict") == "block" for v in t.guardrail_verdicts)
        )
        latencies = [t.latency_ms for t in traces if t.latency_ms > 0]
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        errors = sum(1 for t in traces if t.status == TraceStatus.FAILED)

        by_role: Dict[str, int] = {}
        for t in traces:
            by_role[t.role.value] = by_role.get(t.role.value, 0) + 1

        by_status: Dict[str, int] = {}
        for t in traces:
            by_status[t.status.value] = by_status.get(t.status.value, 0) + 1

        by_tool: Dict[str, int] = {}
        for t in traces:
            for tc in t.tool_calls:
                by_tool[tc.tool_name] = by_tool.get(tc.tool_name, 0) + 1

        # Average eval scores across all traces
        dim_totals: Dict[str, List[float]] = {}
        for t in traces:
            for dim, score in t.eval_scores.items():
                dim_totals.setdefault(dim, []).append(score)
        avg_evals = {d: sum(v) / len(v) for d, v in dim_totals.items() if v}

        suggestions = list(self.suggestions.values())
        return LLMGovernanceMetrics(
            total_traces=total,
            total_tool_calls=total_tool_calls,
            total_blocked=total_blocked,
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            avg_latency_ms=avg_latency,
            error_rate=errors / total if total else 0.0,
            block_rate=total_blocked / total if total else 0.0,
            traces_by_role=by_role,
            traces_by_status=by_status,
            tool_calls_by_tool=by_tool,
            avg_eval_scores=avg_evals,
            suggestions_pending=sum(1 for s in suggestions if s.status == SuggestionStatus.PENDING),
            suggestions_accepted=sum(1 for s in suggestions if s.status == SuggestionStatus.ACCEPTED),
            suggestions_rejected=sum(1 for s in suggestions if s.status == SuggestionStatus.REJECTED),
            prompt_versions_active=sum(1 for p in self.prompts.values() if p.is_active),
        )


# ── Singleton ─────────────────────────────────────────────────────

_store_instance: Optional[LLMGovernanceStore] = None
_store_instance_lock = threading.Lock()


def get_llm_governance_store() -> LLMGovernanceStore:
    global _store_instance
    if _store_instance is None:
        with _store_instance_lock:
            if _store_instance is None:
                _store_instance = LLMGovernanceStore()
    return _store_instance
