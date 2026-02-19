"""
Dev Swarm Governance — Proposal lifecycle, risk tiers, HITL approvals, audit log.

Sprint 13: Dev Swarm Governance & Guardrails
"""

from __future__ import annotations

import time
import uuid
import threading
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional, Any


# ── Enums ────────────────────────────────────────────────────────────

class ProposalKind(Enum):
    """Category of change a proposal targets."""
    SIGNAL_CHANGE = "signal_change"
    MODEL_CHANGE = "model_change"
    REWARD_CHANGE = "reward_change"
    CALIBRATION_CHANGE = "calibration_change"
    BETTING_CHANGE = "betting_change"
    SLO_CHANGE = "slo_change"
    INFRA_CHANGE = "infra_change"
    UI_CHANGE = "ui_change"
    DOCS_CHANGE = "docs_change"
    CONFIG_CHANGE = "config_change"
    STRATEGY_CHANGE = "strategy_change"
    OPTICODDS_CHANGE = "opticodds_change"


class ProposalStatus(Enum):
    """Lifecycle status of a DevProposal."""
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SCHEDULED = "scheduled"
    EXECUTING = "executing"
    EXECUTED = "executed"
    ROLLED_BACK = "rolled_back"


class RiskTier(Enum):
    """Risk classification for proposals."""
    LOW = "low"          # UI tweaks, docs — 1 human approval
    MEDIUM = "medium"    # Model/reward tweaks, strategy — 2 approvals + backtest
    HIGH = "high"        # Infra, prod limits, SLO thresholds — 3 approvals + all green
    CRITICAL = "critical"  # OpticOdds strategy, global limits — 3 approvals + explicit sign-off


class ApprovalAction(Enum):
    """Actions a reviewer can take."""
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"
    ABSTAIN = "abstain"


class ReviewerRole(Enum):
    """Role of the reviewer in the approval process."""
    HUMAN_OWNER = "human_owner"
    HUMAN_REVIEWER = "human_reviewer"
    AGENT_REVIEWER = "agent_reviewer"
    RISK_REVIEWER = "risk_reviewer"


class AuditEventType(Enum):
    """Types of audit log events."""
    PROPOSAL_CREATED = "proposal_created"
    PROPOSAL_UPDATED = "proposal_updated"
    STATUS_CHANGED = "status_changed"
    APPROVAL_SUBMITTED = "approval_submitted"
    DEBATE_STARTED = "debate_started"
    DEBATE_ROUND = "debate_round"
    DEBATE_CONCLUDED = "debate_concluded"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"
    ROLLBACK_INITIATED = "rollback_initiated"
    GUARDRAIL_BLOCKED = "guardrail_blocked"
    EVIDENCE_ATTACHED = "evidence_attached"


# ── Risk tier policy ─────────────────────────────────────────────────

RISK_TIER_POLICY: Dict[RiskTier, Dict[str, Any]] = {
    RiskTier.LOW: {
        "min_approvals": 1,
        "require_human": True,
        "require_backtest": False,
        "require_slo_green": False,
        "max_debate_rounds": 1,
        "auto_schedule": True,
    },
    RiskTier.MEDIUM: {
        "min_approvals": 2,
        "require_human": True,
        "require_backtest": True,
        "require_slo_green": False,
        "max_debate_rounds": 2,
        "auto_schedule": False,
    },
    RiskTier.HIGH: {
        "min_approvals": 3,
        "require_human": True,
        "require_backtest": True,
        "require_slo_green": True,
        "max_debate_rounds": 3,
        "auto_schedule": False,
    },
    RiskTier.CRITICAL: {
        "min_approvals": 3,
        "require_human": True,
        "require_backtest": True,
        "require_slo_green": True,
        "max_debate_rounds": 4,
        "auto_schedule": False,
    },
}

# Map proposal kinds to default risk tiers
KIND_DEFAULT_RISK: Dict[ProposalKind, RiskTier] = {
    ProposalKind.DOCS_CHANGE: RiskTier.LOW,
    ProposalKind.UI_CHANGE: RiskTier.LOW,
    ProposalKind.CONFIG_CHANGE: RiskTier.MEDIUM,
    ProposalKind.SIGNAL_CHANGE: RiskTier.MEDIUM,
    ProposalKind.MODEL_CHANGE: RiskTier.MEDIUM,
    ProposalKind.REWARD_CHANGE: RiskTier.MEDIUM,
    ProposalKind.CALIBRATION_CHANGE: RiskTier.MEDIUM,
    ProposalKind.STRATEGY_CHANGE: RiskTier.MEDIUM,
    ProposalKind.BETTING_CHANGE: RiskTier.HIGH,
    ProposalKind.SLO_CHANGE: RiskTier.HIGH,
    ProposalKind.INFRA_CHANGE: RiskTier.HIGH,
    ProposalKind.OPTICODDS_CHANGE: RiskTier.CRITICAL,
}


# ── Data classes ─────────────────────────────────────────────────────

@dataclass
class ApprovalRecord:
    """A single approval/rejection from a reviewer."""
    id: str = ""
    proposal_id: str = ""
    reviewer_id: str = ""
    reviewer_role: str = "human_reviewer"
    action: str = "approve"
    justification: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:8]
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DebateRound:
    """A single round in a proposal debate."""
    round_number: int = 0
    proposer_argument: str = ""
    challenger_argument: str = ""
    evidence_refs: List[str] = field(default_factory=list)
    metrics_snapshot: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProposalMetrics:
    """Before/after metrics for a proposal."""
    metric_name: str = ""
    baseline_value: float = 0.0
    expected_value: float = 0.0
    actual_value: Optional[float] = None
    unit: str = ""
    improved: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DevProposal:
    """A governed change proposal in the dev swarm."""
    id: str = ""
    kind: str = "config_change"
    title: str = ""
    description: str = ""
    target: str = ""
    diff_summary: str = ""
    risk_tier: str = "medium"
    risk_score: float = 0.5
    affected_subsystems: List[str] = field(default_factory=list)
    status: str = "draft"
    proposer_id: str = ""
    owner_id: str = ""
    branch_ref: str = ""
    pr_link: str = ""
    consensus_score: float = 0.0
    forecast_question: str = ""
    forecast_probability: float = 0.5
    rollout_strategy: str = "full"  # canary, shadow, full
    approvals: List[ApprovalRecord] = field(default_factory=list)
    debate_rounds: List[DebateRound] = field(default_factory=list)
    metrics: List[ProposalMetrics] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0
    scheduled_at: Optional[float] = None
    executed_at: Optional[float] = None
    rolled_back_at: Optional[float] = None

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:8]
        now = time.time()
        if self.created_at == 0.0:
            self.created_at = now
        if self.updated_at == 0.0:
            self.updated_at = now

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["approvals"] = [a.to_dict() if isinstance(a, ApprovalRecord) else a for a in self.approvals]
        d["debate_rounds"] = [r.to_dict() if isinstance(r, DebateRound) else r for r in self.debate_rounds]
        d["metrics"] = [m.to_dict() if isinstance(m, ProposalMetrics) else m for m in self.metrics]
        return d

    @property
    def approval_count(self) -> int:
        return sum(1 for a in self.approvals if a.action == ApprovalAction.APPROVE.value)

    @property
    def rejection_count(self) -> int:
        return sum(1 for a in self.approvals if a.action == ApprovalAction.REJECT.value)

    @property
    def human_approval_count(self) -> int:
        return sum(
            1 for a in self.approvals
            if a.action == ApprovalAction.APPROVE.value
            and a.reviewer_role in (ReviewerRole.HUMAN_OWNER.value, ReviewerRole.HUMAN_REVIEWER.value)
        )

    @property
    def policy(self) -> Dict[str, Any]:
        try:
            tier = RiskTier(self.risk_tier)
        except ValueError:
            tier = RiskTier.MEDIUM
        return RISK_TIER_POLICY[tier]

    @property
    def meets_approval_threshold(self) -> bool:
        policy = self.policy
        if self.approval_count < policy["min_approvals"]:
            return False
        if policy["require_human"] and self.human_approval_count < 1:
            return False
        return True


@dataclass
class AuditEvent:
    """Immutable audit log entry."""
    id: str = ""
    event_type: str = "proposal_created"
    proposal_id: str = ""
    actor_id: str = ""
    actor_type: str = "human"  # human, agent, system
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:12]
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GovernanceMetrics:
    """Aggregate governance metrics for dashboards."""
    total_proposals: int = 0
    proposals_by_status: Dict[str, int] = field(default_factory=dict)
    proposals_by_risk: Dict[str, int] = field(default_factory=dict)
    proposals_by_kind: Dict[str, int] = field(default_factory=dict)
    approval_rate: float = 0.0
    regression_rate: float = 0.0
    avg_time_to_decision_s: float = 0.0
    avg_time_to_revert_s: float = 0.0
    agent_initiated_ratio: float = 0.0
    human_initiated_ratio: float = 0.0
    proposals_this_week: int = 0
    guardrail_blocks: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Governance Store ─────────────────────────────────────────────────

class GovernanceStore:
    """In-memory governance store for proposals, approvals, and audit log."""

    def __init__(self):
        self._proposals: Dict[str, DevProposal] = {}
        self._audit_log: List[AuditEvent] = []
        self._lock = threading.Lock()

    # ── Proposals ────────────────────────────────────────────────

    def create_proposal(self, proposal: DevProposal, actor_id: str = "system") -> DevProposal:
        with self._lock:
            self._proposals[proposal.id] = proposal
            self._emit_audit(
                AuditEventType.PROPOSAL_CREATED, proposal.id, actor_id,
                details={"kind": proposal.kind, "risk_tier": proposal.risk_tier, "title": proposal.title},
            )
            return proposal

    def get_proposal(self, proposal_id: str) -> Optional[DevProposal]:
        return self._proposals.get(proposal_id)

    def list_proposals(
        self,
        status: Optional[str] = None,
        kind: Optional[str] = None,
        risk_tier: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[DevProposal]:
        with self._lock:
            proposals = list(self._proposals.values())
            if status:
                proposals = [p for p in proposals if p.status == status]
            if kind:
                proposals = [p for p in proposals if p.kind == kind]
            if risk_tier:
                proposals = [p for p in proposals if p.risk_tier == risk_tier]
            proposals.sort(key=lambda p: p.updated_at, reverse=True)
            return proposals[offset:offset + limit]

    def update_status(
        self, proposal_id: str, new_status: str, actor_id: str = "system"
    ) -> Optional[DevProposal]:
        with self._lock:
            p = self._proposals.get(proposal_id)
            if not p:
                return None
            old_status = p.status
            p.status = new_status
            p.updated_at = time.time()
            if new_status == ProposalStatus.EXECUTED.value:
                p.executed_at = time.time()
            elif new_status == ProposalStatus.SCHEDULED.value:
                p.scheduled_at = time.time()
            elif new_status == ProposalStatus.ROLLED_BACK.value:
                p.rolled_back_at = time.time()
            self._emit_audit(
                AuditEventType.STATUS_CHANGED, proposal_id, actor_id,
                details={"old_status": old_status, "new_status": new_status},
            )
            return p

    # ── Approvals ────────────────────────────────────────────────

    def submit_approval(
        self,
        proposal_id: str,
        reviewer_id: str,
        reviewer_role: str,
        action: str,
        justification: str = "",
    ) -> Optional[ApprovalRecord]:
        with self._lock:
            p = self._proposals.get(proposal_id)
            if not p:
                return None
            record = ApprovalRecord(
                proposal_id=proposal_id,
                reviewer_id=reviewer_id,
                reviewer_role=reviewer_role,
                action=action,
                justification=justification,
            )
            p.approvals.append(record)
            p.updated_at = time.time()
            self._emit_audit(
                AuditEventType.APPROVAL_SUBMITTED, proposal_id, reviewer_id,
                details={"action": action, "reviewer_role": reviewer_role},
            )
            # Auto-transition if threshold met
            if p.status == ProposalStatus.IN_REVIEW.value and p.meets_approval_threshold:
                policy = p.policy
                if policy.get("auto_schedule"):
                    p.status = ProposalStatus.SCHEDULED.value
                    p.scheduled_at = time.time()
                else:
                    p.status = ProposalStatus.APPROVED.value
                p.updated_at = time.time()
                self._emit_audit(
                    AuditEventType.STATUS_CHANGED, proposal_id, "system",
                    details={"new_status": p.status, "reason": "approval_threshold_met"},
                )
            # Auto-reject if majority reject
            total_reviews = len(p.approvals)
            if total_reviews >= p.policy["min_approvals"] and p.rejection_count > p.approval_count:
                p.status = ProposalStatus.REJECTED.value
                p.updated_at = time.time()
                self._emit_audit(
                    AuditEventType.STATUS_CHANGED, proposal_id, "system",
                    details={"new_status": p.status, "reason": "majority_rejected"},
                )
            return record

    # ── Debates ──────────────────────────────────────────────────

    def add_debate_round(
        self,
        proposal_id: str,
        proposer_argument: str,
        challenger_argument: str,
        evidence_refs: Optional[List[str]] = None,
        metrics_snapshot: Optional[Dict[str, Any]] = None,
        actor_id: str = "system",
    ) -> Optional[DebateRound]:
        with self._lock:
            p = self._proposals.get(proposal_id)
            if not p:
                return None
            round_num = len(p.debate_rounds) + 1
            dr = DebateRound(
                round_number=round_num,
                proposer_argument=proposer_argument,
                challenger_argument=challenger_argument,
                evidence_refs=evidence_refs or [],
                metrics_snapshot=metrics_snapshot or {},
            )
            p.debate_rounds.append(dr)
            p.updated_at = time.time()
            self._emit_audit(
                AuditEventType.DEBATE_ROUND, proposal_id, actor_id,
                details={"round": round_num},
            )
            return dr

    # ── Metrics ──────────────────────────────────────────────────

    def attach_metrics(
        self, proposal_id: str, metrics: List[ProposalMetrics], actor_id: str = "system"
    ) -> bool:
        with self._lock:
            p = self._proposals.get(proposal_id)
            if not p:
                return False
            p.metrics.extend(metrics)
            p.updated_at = time.time()
            self._emit_audit(
                AuditEventType.EVIDENCE_ATTACHED, proposal_id, actor_id,
                details={"metric_count": len(metrics)},
            )
            return True

    # ── Governance metrics ───────────────────────────────────────

    def compute_governance_metrics(self) -> GovernanceMetrics:
        with self._lock:
            proposals = list(self._proposals.values())
            total = len(proposals)
            if total == 0:
                return GovernanceMetrics()

            by_status: Dict[str, int] = {}
            by_risk: Dict[str, int] = {}
            by_kind: Dict[str, int] = {}
            executed = []
            rolled_back = []
            decision_times: List[float] = []
            revert_times: List[float] = []
            agent_count = 0
            human_count = 0
            now = time.time()
            week_ago = now - 7 * 86400

            for p in proposals:
                by_status[p.status] = by_status.get(p.status, 0) + 1
                by_risk[p.risk_tier] = by_risk.get(p.risk_tier, 0) + 1
                by_kind[p.kind] = by_kind.get(p.kind, 0) + 1

                if p.status == ProposalStatus.EXECUTED.value:
                    executed.append(p)
                if p.status == ProposalStatus.ROLLED_BACK.value:
                    rolled_back.append(p)

                # Decision time = first approval - created
                if p.approvals:
                    first_approval_ts = min(a.timestamp for a in p.approvals)
                    decision_times.append(first_approval_ts - p.created_at)

                if p.rolled_back_at and p.executed_at:
                    revert_times.append(p.rolled_back_at - p.executed_at)

                if p.proposer_id.startswith("agent_") or p.proposer_id.startswith("coder_") or p.proposer_id.startswith("tester_"):
                    agent_count += 1
                else:
                    human_count += 1

            guardrail_blocks = sum(
                1 for e in self._audit_log if e.event_type == AuditEventType.GUARDRAIL_BLOCKED.value
            )

            proposals_this_week = sum(1 for p in proposals if p.created_at >= week_ago)

            return GovernanceMetrics(
                total_proposals=total,
                proposals_by_status=by_status,
                proposals_by_risk=by_risk,
                proposals_by_kind=by_kind,
                approval_rate=len(executed) / max(total, 1),
                regression_rate=len(rolled_back) / max(len(executed), 1) if executed else 0.0,
                avg_time_to_decision_s=sum(decision_times) / max(len(decision_times), 1) if decision_times else 0.0,
                avg_time_to_revert_s=sum(revert_times) / max(len(revert_times), 1) if revert_times else 0.0,
                agent_initiated_ratio=agent_count / max(total, 1),
                human_initiated_ratio=human_count / max(total, 1),
                proposals_this_week=proposals_this_week,
                guardrail_blocks=guardrail_blocks,
            )

    # ── Audit log ────────────────────────────────────────────────

    def get_audit_log(
        self,
        proposal_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 200,
        offset: int = 0,
    ) -> List[AuditEvent]:
        with self._lock:
            events = list(self._audit_log)
            if proposal_id:
                events = [e for e in events if e.proposal_id == proposal_id]
            if event_type:
                events = [e for e in events if e.event_type == event_type]
            events.sort(key=lambda e: e.timestamp, reverse=True)
            return events[offset:offset + limit]

    def _emit_audit(
        self, event_type: AuditEventType, proposal_id: str, actor_id: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        event = AuditEvent(
            event_type=event_type.value,
            proposal_id=proposal_id,
            actor_id=actor_id,
            details=details or {},
        )
        self._audit_log.append(event)

    # ── Agent roster with governance context ─────────────────────

    def get_agent_governance_stats(self) -> List[Dict[str, Any]]:
        """Per-agent governance stats: proposals created, approved, rejected, impact."""
        with self._lock:
            agent_stats: Dict[str, Dict[str, Any]] = {}
            for p in self._proposals.values():
                pid = p.proposer_id
                if pid not in agent_stats:
                    agent_stats[pid] = {
                        "agent_id": pid,
                        "proposals_created": 0,
                        "proposals_approved": 0,
                        "proposals_rejected": 0,
                        "proposals_executed": 0,
                        "proposals_rolled_back": 0,
                        "reviews_given": 0,
                        "avg_risk_score": 0.0,
                        "risk_scores": [],
                    }
                agent_stats[pid]["proposals_created"] += 1
                agent_stats[pid]["risk_scores"].append(p.risk_score)
                if p.status == ProposalStatus.APPROVED.value or p.status == ProposalStatus.EXECUTED.value:
                    agent_stats[pid]["proposals_approved"] += 1
                if p.status == ProposalStatus.REJECTED.value:
                    agent_stats[pid]["proposals_rejected"] += 1
                if p.status == ProposalStatus.EXECUTED.value:
                    agent_stats[pid]["proposals_executed"] += 1
                if p.status == ProposalStatus.ROLLED_BACK.value:
                    agent_stats[pid]["proposals_rolled_back"] += 1

                for a in p.approvals:
                    rid = a.reviewer_id
                    if rid not in agent_stats:
                        agent_stats[rid] = {
                            "agent_id": rid,
                            "proposals_created": 0,
                            "proposals_approved": 0,
                            "proposals_rejected": 0,
                            "proposals_executed": 0,
                            "proposals_rolled_back": 0,
                            "reviews_given": 0,
                            "avg_risk_score": 0.0,
                            "risk_scores": [],
                        }
                    agent_stats[rid]["reviews_given"] += 1

            result = []
            for stats in agent_stats.values():
                scores = stats.pop("risk_scores", [])
                stats["avg_risk_score"] = sum(scores) / max(len(scores), 1) if scores else 0.0
                result.append(stats)
            return result


# ── Singleton ────────────────────────────────────────────────────────

_governance_store: Optional[GovernanceStore] = None
_store_lock = threading.Lock()


def get_governance_store() -> GovernanceStore:
    global _governance_store
    if _governance_store is None:
        with _store_lock:
            if _governance_store is None:
                _governance_store = GovernanceStore()
    return _governance_store
