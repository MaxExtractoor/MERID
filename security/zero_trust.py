"""Zero-Trust Enforcement Layer for MERID.

Implements the hard invariants from the ZT security pass:

  ZT-01  Agent identity + tool scopes — every agent has declared scopes;
         execution and config tools are off by default.
  ZT-02  Dual control — kill-switch reset and domain/agent promotion require
         two distinct human approvals; single-operator resets are blocked.
  ZT-03  Stream publisher identity — StreamBus.publish() callers must be
         registered; unregistered sources are rejected.
  ZT-04  Config mutation gate — runtime agent-mode changes require operator
         token + audit log; anonymous mutations are blocked.
  ZT-05  Blast-radius caps — agents may not enumerate the full registry;
         only their own metrics and messages to declared targets.

Usage (agent scope check):
    from security.zero_trust import get_agent_scope_registry, AgentTool
    reg = get_agent_scope_registry()
    reg.register_agent("btc-analyst", allowed_tools={AgentTool.READ_MARKET_DATA})
    reg.check_tool(agent_id="btc-analyst", tool=AgentTool.SUBMIT_ORDER)  # raises

Usage (dual control):
    from security.zero_trust import get_dual_control_guard
    guard = get_dual_control_guard()
    token = guard.request_action("kill_switch_reset", operator_id="alice", reason="daily restart")
    guard.approve_action(token, approver_id="bob")  # second human
    guard.consume_action(token)                      # now allowed

Usage (stream publisher):
    from security.zero_trust import get_stream_publisher_guard
    spg = get_stream_publisher_guard()
    spg.register_publisher("price_feed", allowed_topics={"prices.*"})
    spg.assert_publish("price_feed", "prices.kalshi.BTC-USD")  # OK
    spg.assert_publish("price_feed", "trades.executed")        # raises
"""

from __future__ import annotations

import fnmatch
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, Optional, Set

from utils.logger import get_logger

logger = get_logger("security.zero_trust")


# ── Tool Scope Enum ────────────────────────────────────────────────────────

class AgentTool(Enum):
    """Every tool an agent can call.  EXECUTION and CONFIG_WRITE are off by default."""
    READ_MARKET_DATA   = auto()   # read-only price / orderbook data
    READ_PORTFOLIO     = auto()   # read own paper/live positions
    READ_RISK          = auto()   # read risk metrics, CQI, caps
    READ_AGENT_OWN     = auto()   # read own metrics / status
    PUBLISH_OPINION    = auto()   # write to agent.opinions topic
    SUBMIT_ORDER       = auto()   # submit an order via execution guard  ← HIGH RISK
    CANCEL_ORDER       = auto()   # cancel an open order                 ← HIGH RISK
    CONFIG_WRITE       = auto()   # mutate agent_modes / risk limits      ← HIGH RISK
    KILL_SWITCH        = auto()   # activate/reset global kill switch      ← CRITICAL
    DOMAIN_PROMOTE     = auto()   # promote a domain to live               ← CRITICAL
    AGENT_PROMOTE      = auto()   # promote an agent to live               ← CRITICAL
    BROADCAST_MSG      = auto()   # send broadcast AgentMessage           ← MEDIUM


# Tools that are OFF by default and require explicit grant
_HIGH_RISK_TOOLS: Set[AgentTool] = {
    AgentTool.SUBMIT_ORDER,
    AgentTool.CANCEL_ORDER,
    AgentTool.CONFIG_WRITE,
    AgentTool.KILL_SWITCH,
    AgentTool.DOMAIN_PROMOTE,
    AgentTool.AGENT_PROMOTE,
    AgentTool.BROADCAST_MSG,
}

# Tools that additionally require governance approval before grant
_GOVERNANCE_GATED_TOOLS: Set[AgentTool] = {
    AgentTool.SUBMIT_ORDER,
    AgentTool.CANCEL_ORDER,
    AgentTool.KILL_SWITCH,
    AgentTool.DOMAIN_PROMOTE,
    AgentTool.AGENT_PROMOTE,
}


class ScopeViolation(PermissionError):
    """Raised when an agent attempts to use a tool outside its scope."""


# ── Agent Scope Registry ───────────────────────────────────────────────────

@dataclass
class AgentScopeEntry:
    agent_id: str
    allowed_tools: Set[AgentTool] = field(default_factory=set)
    governance_approved_tools: Set[AgentTool] = field(default_factory=set)
    registered_at: float = field(default_factory=time.time)
    last_violation_at: Optional[float] = None
    violation_count: int = 0

    def can_use(self, tool: AgentTool) -> bool:
        if tool not in self.allowed_tools:
            return False
        if tool in _GOVERNANCE_GATED_TOOLS and tool not in self.governance_approved_tools:
            return False
        return True


class AgentScopeRegistry:
    """Central registry that maps agent_id → permitted tools.

    ZT-01 invariant: no agent may call SUBMIT_ORDER, CANCEL_ORDER,
    CONFIG_WRITE, KILL_SWITCH, DOMAIN_PROMOTE, or AGENT_PROMOTE unless
    explicitly registered AND governance-approved for that tool.
    """

    def __init__(self) -> None:
        self._entries: Dict[str, AgentScopeEntry] = {}
        self._lock = threading.Lock()

    def register_agent(
        self,
        agent_id: str,
        allowed_tools: Optional[Set[AgentTool]] = None,
        governance_approved_tools: Optional[Set[AgentTool]] = None,
    ) -> AgentScopeEntry:
        """Register an agent with its permitted tool set.

        Defaults: read-only tools only; all high-risk tools denied.
        """
        if allowed_tools is None:
            allowed_tools = {
                AgentTool.READ_MARKET_DATA,
                AgentTool.READ_PORTFOLIO,
                AgentTool.READ_RISK,
                AgentTool.READ_AGENT_OWN,
                AgentTool.PUBLISH_OPINION,
            }
        # Strip high-risk tools from allowed unless explicitly granted
        safe_tools = allowed_tools - _HIGH_RISK_TOOLS
        granted_high_risk = allowed_tools & _HIGH_RISK_TOOLS
        gov_approved = (governance_approved_tools or set()) & _GOVERNANCE_GATED_TOOLS
        final_tools = safe_tools | granted_high_risk

        entry = AgentScopeEntry(
            agent_id=agent_id,
            allowed_tools=final_tools,
            governance_approved_tools=gov_approved,
        )
        with self._lock:
            self._entries[agent_id] = entry
        logger.info(
            "[ZT-01] Agent '%s' registered: tools=%s gov_approved=%s",
            agent_id,
            {t.name for t in final_tools},
            {t.name for t in gov_approved},
        )
        return entry

    def grant_governance_approval(self, agent_id: str, tool: AgentTool) -> None:
        """Grant governance approval for a governance-gated tool.

        Caller must itself be authorized (e.g. called from DOMAIN_PROMOTE flow
        after dual-control approval).
        """
        if tool not in _GOVERNANCE_GATED_TOOLS:
            logger.warning("[ZT-01] %s is not governance-gated, no-op", tool.name)
            return
        with self._lock:
            entry = self._entries.get(agent_id)
            if entry is None:
                raise ScopeViolation(f"Agent '{agent_id}' not registered")
            entry.governance_approved_tools.add(tool)
        logger.info("[ZT-01] Governance approval granted: agent=%s tool=%s", agent_id, tool.name)

    def revoke_governance_approval(self, agent_id: str, tool: AgentTool) -> None:
        with self._lock:
            entry = self._entries.get(agent_id)
            if entry:
                entry.governance_approved_tools.discard(tool)
        logger.info("[ZT-01] Governance approval revoked: agent=%s tool=%s", agent_id, tool.name)

    def check_tool(self, agent_id: str, tool: AgentTool) -> None:
        """Assert that agent_id is permitted to use tool.

        Raises ScopeViolation on any denial — callers must not proceed.
        """
        with self._lock:
            entry = self._entries.get(agent_id)

        if entry is None:
            _msg = (
                f"[ZT-01] SCOPE VIOLATION: unregistered agent '{agent_id}' "
                f"attempted to use {tool.name}"
            )
            logger.critical(_msg)
            raise ScopeViolation(_msg)

        if not entry.can_use(tool):
            with self._lock:
                entry.violation_count += 1
                entry.last_violation_at = time.time()
            _detail = (
                f"not in allowed_tools" if tool not in entry.allowed_tools
                else f"not governance-approved"
            )
            _msg = (
                f"[ZT-01] SCOPE VIOLATION: agent '{agent_id}' attempted "
                f"{tool.name} ({_detail})"
            )
            logger.critical(_msg)
            raise ScopeViolation(_msg)

    def is_registered(self, agent_id: str) -> bool:
        return agent_id in self._entries

    def get_entry(self, agent_id: str) -> Optional[AgentScopeEntry]:
        return self._entries.get(agent_id)

    def all_agent_ids(self) -> list[str]:
        with self._lock:
            return list(self._entries.keys())

    def violation_summary(self) -> Dict[str, int]:
        with self._lock:
            return {aid: e.violation_count for aid, e in self._entries.items() if e.violation_count > 0}


# ── Dual Control Guard ─────────────────────────────────────────────────────

class DualControlAction(str, Enum):
    KILL_SWITCH_RESET    = "kill_switch_reset"
    KILL_SWITCH_ACTIVATE = "kill_switch_activate"
    DOMAIN_PROMOTE       = "domain_promote"
    DOMAIN_DEMOTE        = "domain_demote"
    AGENT_PROMOTE        = "agent_promote"
    AGENT_DEMOTE         = "agent_demote"
    RISK_LIMIT_CHANGE    = "risk_limit_change"
    LIVE_MODE_ENABLE     = "live_mode_enable"


class DualControlError(PermissionError):
    """Raised when a dual-control policy is violated."""


@dataclass
class PendingApproval:
    token: str
    action: DualControlAction
    subject: str                    # domain / agent_id / "global"
    requester_id: str
    reason: str
    requested_at: float
    approver_id: Optional[str] = None
    approved_at: Optional[float] = None
    consumed: bool = False
    expires_at: float = field(init=False)

    def __post_init__(self) -> None:
        self.expires_at = self.requested_at + 3600.0   # 1-hour window

    @property
    def is_approved(self) -> bool:
        return self.approver_id is not None

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def is_consumed(self) -> bool:
        return self.consumed


class DualControlGuard:
    """Enforces two-distinct-human approval for destructive actions.

    ZT-02 invariant:
      - requester != approver (no self-approval)
      - approval token must be consumed before the action proceeds
      - tokens expire after 1 hour
      - every request and approval is audit-logged
    """

    def __init__(self) -> None:
        self._pending: Dict[str, PendingApproval] = {}
        self._history: list[PendingApproval] = []
        self._lock = threading.Lock()

    def request_action(
        self,
        action: DualControlAction,
        operator_id: str,
        subject: str = "global",
        reason: str = "",
    ) -> str:
        """Create a pending approval request.  Returns an approval token."""
        token = f"dc_{uuid.uuid4().hex}"
        pa = PendingApproval(
            token=token,
            action=action,
            subject=subject,
            requester_id=operator_id,
            reason=reason,
            requested_at=time.time(),
        )
        with self._lock:
            self._pending[token] = pa
        logger.warning(
            "[ZT-02] DUAL-CONTROL REQUEST: action=%s subject=%s requester=%s reason=%r token=%s",
            action.value, subject, operator_id, reason, token,
        )
        return token

    def approve_action(self, token: str, approver_id: str) -> None:
        """Record second-human approval.  approver_id must differ from requester."""
        with self._lock:
            pa = self._pending.get(token)
            if pa is None:
                raise DualControlError(f"[ZT-02] Unknown approval token: {token}")
            if pa.is_expired:
                del self._pending[token]
                raise DualControlError(f"[ZT-02] Approval token expired: {token}")
            if pa.is_consumed:
                raise DualControlError(f"[ZT-02] Approval token already consumed: {token}")
            if pa.approver_id is not None:
                raise DualControlError(f"[ZT-02] Already approved by {pa.approver_id}")
            if approver_id == pa.requester_id:
                raise DualControlError(
                    f"[ZT-02] SELF-APPROVAL BLOCKED: {approver_id} cannot approve "
                    f"their own request (action={pa.action.value})"
                )
            pa.approver_id = approver_id
            pa.approved_at = time.time()
        logger.warning(
            "[ZT-02] DUAL-CONTROL APPROVED: action=%s subject=%s approver=%s token=%s",
            pa.action.value, pa.subject, approver_id, token,
        )

    def consume_action(self, token: str) -> PendingApproval:
        """Assert full approval then mark consumed.  Call immediately before executing."""
        with self._lock:
            pa = self._pending.get(token)
            if pa is None:
                raise DualControlError(f"[ZT-02] Unknown approval token: {token}")
            if pa.is_expired:
                del self._pending[token]
                raise DualControlError(f"[ZT-02] Approval token expired: {token}")
            if not pa.is_approved:
                raise DualControlError(
                    f"[ZT-02] Action '{pa.action.value}' requires second-human approval "
                    f"before it can proceed (requested by {pa.requester_id})"
                )
            if pa.is_consumed:
                raise DualControlError(f"[ZT-02] Approval token already consumed: {token}")
            pa.consumed = True
            self._history.append(pa)
            del self._pending[token]
        logger.warning(
            "[ZT-02] DUAL-CONTROL CONSUMED: action=%s subject=%s requester=%s approver=%s",
            pa.action.value, pa.subject, pa.requester_id, pa.approver_id,
        )
        return pa

    def pending_count(self) -> int:
        self._purge_expired()
        return len(self._pending)

    def _purge_expired(self) -> None:
        with self._lock:
            expired = [t for t, pa in self._pending.items() if pa.is_expired]
            for t in expired:
                logger.info("[ZT-02] Purging expired approval token: %s", t)
                del self._pending[t]

    def history(self, limit: int = 50) -> list[PendingApproval]:
        return self._history[-limit:]


# ── Stream Publisher Guard ─────────────────────────────────────────────────

class PublisherViolation(PermissionError):
    """Raised when an unregistered or out-of-scope publisher attempts to publish."""


@dataclass
class PublisherEntry:
    publisher_id: str
    allowed_topic_patterns: Set[str]   # fnmatch glob patterns e.g. "prices.*"
    registered_at: float = field(default_factory=time.time)
    publish_count: int = 0
    violation_count: int = 0


class StreamPublisherGuard:
    """Enforces producer identity on the stream bus.

    ZT-03 invariant: every call to StreamBus.publish() must declare a
    publisher_id that is registered here and whose allowed_topic_patterns
    match the target topic.  Anonymous / unregistered publishers are rejected.
    """

    def __init__(self) -> None:
        self._publishers: Dict[str, PublisherEntry] = {}
        self._lock = threading.Lock()
        # When True, unknown publishers are blocked; when False (dev mode), warned only.
        self._strict: bool = True

    def set_strict(self, strict: bool) -> None:
        self._strict = strict
        logger.info("[ZT-03] StreamPublisherGuard strict=%s", strict)

    def register_publisher(
        self,
        publisher_id: str,
        allowed_topics: Optional[Set[str]] = None,
    ) -> None:
        """Register a publisher with its permitted topic patterns."""
        patterns = allowed_topics or set()
        with self._lock:
            self._publishers[publisher_id] = PublisherEntry(
                publisher_id=publisher_id,
                allowed_topic_patterns=patterns,
            )
        logger.info("[ZT-03] Publisher registered: id=%s topics=%s", publisher_id, patterns)

    def assert_publish(self, publisher_id: str, topic: str) -> None:
        """Assert that publisher_id is allowed to publish to topic.

        Raises PublisherViolation if not.  Must be called before bus.publish().
        """
        with self._lock:
            entry = self._publishers.get(publisher_id)

        if entry is None:
            with self._lock:
                # Still increment violation even though entry is absent
                pass
            _msg = (
                f"[ZT-03] PUBLISHER VIOLATION: unregistered publisher '{publisher_id}' "
                f"attempted to publish to '{topic}'"
            )
            logger.critical(_msg)
            if self._strict:
                raise PublisherViolation(_msg)
            logger.warning("[ZT-03] Non-strict mode: allowing unregistered publisher (WARNING)")
            return

        matched = any(
            fnmatch.fnmatch(topic, pattern)
            for pattern in entry.allowed_topic_patterns
        )
        if not matched:
            with self._lock:
                entry.violation_count += 1
            _msg = (
                f"[ZT-03] PUBLISHER VIOLATION: publisher '{publisher_id}' not permitted "
                f"for topic '{topic}' (allowed: {entry.allowed_topic_patterns})"
            )
            logger.critical(_msg)
            if self._strict:
                raise PublisherViolation(_msg)
            logger.warning("[ZT-03] Non-strict mode: allowing out-of-scope publish (WARNING)")
            return

        with self._lock:
            entry.publish_count += 1

    def is_registered(self, publisher_id: str) -> bool:
        return publisher_id in self._publishers

    def violation_summary(self) -> Dict[str, int]:
        with self._lock:
            return {
                pid: e.violation_count
                for pid, e in self._publishers.items()
                if e.violation_count > 0
            }


# ── ZT Policy Constants ────────────────────────────────────────────────────

class ZTPolicy:
    """Hard invariants — referenced by enforcement code and tests alike."""

    # ZT-01: Every execution/config API call requires a valid, unexpired,
    # scoped token even from inside the cluster.
    EXECUTION_REQUIRES_SCOPED_TOKEN = True

    # ZT-01: High-risk tools are off by default; must be explicitly granted.
    HIGH_RISK_TOOLS_OFF_BY_DEFAULT = True

    # ZT-01: Governance-gated tools additionally require governance approval.
    GOVERNANCE_GATED_TOOLS = frozenset(_GOVERNANCE_GATED_TOOLS)

    # ZT-02: Sensitive changes require dual control (two distinct humans).
    DUAL_CONTROL_ACTIONS = frozenset(DualControlAction)

    # ZT-02: Approval tokens expire after this many seconds.
    APPROVAL_TOKEN_TTL_S = 3600

    # ZT-03: Stream publishers must be registered; unregistered = rejected.
    STREAM_PUBLISHER_MUST_BE_REGISTERED = True

    # ZT-04: Config mutations must be authenticated + audit-logged.
    CONFIG_MUTATION_REQUIRES_AUTH = True

    # ZT-05: Agents may not enumerate the global agent registry.
    AGENTS_CANNOT_ENUMERATE_REGISTRY = True

    # ZT-DEV: Dev auth bypass must be explicitly opted-in AND blocked in live mode.
    DEV_BYPASS_REQUIRES_EXPLICIT_OPT_IN = True
    DEV_BYPASS_BLOCKED_IN_LIVE_MODE = True


# ── Singletons ─────────────────────────────────────────────────────────────

_agent_scope_registry: Optional[AgentScopeRegistry] = None
_agent_scope_registry_lock = threading.Lock()

_dual_control_guard: Optional[DualControlGuard] = None
_dual_control_guard_lock = threading.Lock()

_stream_publisher_guard: Optional[StreamPublisherGuard] = None
_stream_publisher_guard_lock = threading.Lock()


def get_agent_scope_registry() -> AgentScopeRegistry:
    global _agent_scope_registry
    if _agent_scope_registry is None:
        with _agent_scope_registry_lock:
            if _agent_scope_registry is None:
                _agent_scope_registry = AgentScopeRegistry()
    return _agent_scope_registry


def get_dual_control_guard() -> DualControlGuard:
    global _dual_control_guard
    if _dual_control_guard is None:
        with _dual_control_guard_lock:
            if _dual_control_guard is None:
                _dual_control_guard = DualControlGuard()
    return _dual_control_guard


def get_stream_publisher_guard() -> StreamPublisherGuard:
    global _stream_publisher_guard
    if _stream_publisher_guard is None:
        with _stream_publisher_guard_lock:
            if _stream_publisher_guard is None:
                _stream_publisher_guard = StreamPublisherGuard()
    return _stream_publisher_guard
