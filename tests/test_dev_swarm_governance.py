"""
Sprint 13 — Dev Swarm Governance & Guardrails tests.

Validates:
  1. Endpoint constants (DEV_GOVERNANCE_PROPOSALS, DEV_GOVERNANCE_METRICS, etc.)
  2. useDevProposals / useDevApprovals / useGovernanceDashboard hook types
  3. DevProposalBoard component structure
  4. DevProposalDetail component structure
  5. GovernanceDashboard component structure
  6. HITLApprovalQueue component structure
  7. DevAgentRoster component structure
  8. DevSwarmControlCenter view assembly
  9. Navigation wiring (App.tsx + Sidebar.tsx)
  10. Backend core model (enums, dataclasses, GovernanceStore)
  11. Backend API route availability
  12. GovernanceStore lifecycle (create, approve, reject, debate, metrics, audit)
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

# ── Paths ──────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
REACT_SRC = ROOT / "web" / "react" / "src"
CONSTANTS_FILE = REACT_SRC / "config" / "constants.ts"
HOOK_FILE = REACT_SRC / "hooks" / "useDevGovernance.ts"
PROPOSAL_BOARD_FILE = REACT_SRC / "components" / "DevProposalBoard.tsx"
PROPOSAL_DETAIL_FILE = REACT_SRC / "components" / "DevProposalDetail.tsx"
GOVERNANCE_DASHBOARD_FILE = REACT_SRC / "components" / "GovernanceDashboard.tsx"
HITL_QUEUE_FILE = REACT_SRC / "components" / "HITLApprovalQueue.tsx"
AGENT_ROSTER_FILE = REACT_SRC / "components" / "DevAgentRoster.tsx"
VIEW_FILE = REACT_SRC / "views" / "DevSwarmControlCenter.tsx"
APP_FILE = REACT_SRC / "App.tsx"
SIDEBAR_FILE = REACT_SRC / "components" / "Sidebar.tsx"
GOVERNANCE_ROUTES_FILE = ROOT / "web" / "api" / "dev_swarm_governance_routes.py"
GOVERNANCE_CORE_FILE = ROOT / "core" / "dev_swarm_governance.py"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


# ═══════════════════════════════════════════════════════════════════
# §1  Endpoint Constants
# ═══════════════════════════════════════════════════════════════════


class TestEndpointConstants:
    """Verify all dev swarm governance constants are defined."""

    src = _read(CONSTANTS_FILE)

    def test_proposals_constant(self):
        assert "DEV_GOVERNANCE_PROPOSALS" in self.src
        assert "/api/dev-swarm/governance/proposals" in self.src

    def test_proposal_by_id_constant(self):
        assert "DEV_GOVERNANCE_PROPOSAL:" in self.src or "DEV_GOVERNANCE_PROPOSAL" in self.src
        # Function form: (id: string) => `/api/dev-swarm/governance/proposals/${id}`
        assert "DEV_GOVERNANCE_PROPOSAL" in self.src

    def test_proposal_status_constant(self):
        assert "DEV_GOVERNANCE_PROPOSAL_STATUS" in self.src

    def test_proposal_approvals_constant(self):
        assert "DEV_GOVERNANCE_PROPOSAL_APPROVALS" in self.src

    def test_proposal_debates_constant(self):
        assert "DEV_GOVERNANCE_PROPOSAL_DEBATES" in self.src

    def test_proposal_metrics_constant(self):
        assert "DEV_GOVERNANCE_PROPOSAL_METRICS" in self.src

    def test_governance_metrics_constant(self):
        assert "DEV_GOVERNANCE_METRICS" in self.src
        assert "/api/dev-swarm/governance/metrics" in self.src

    def test_agent_stats_constant(self):
        assert "DEV_GOVERNANCE_AGENT_STATS" in self.src
        assert "/api/dev-swarm/governance/agent-stats" in self.src

    def test_risk_policy_constant(self):
        assert "DEV_GOVERNANCE_RISK_POLICY" in self.src
        assert "/api/dev-swarm/governance/risk-policy" in self.src

    def test_audit_log_constant(self):
        assert "DEV_GOVERNANCE_AUDIT_LOG" in self.src
        assert "/api/dev-swarm/governance/audit-log" in self.src

    def test_pending_approvals_constant(self):
        assert "DEV_GOVERNANCE_PENDING" in self.src
        assert "/api/dev-swarm/governance/pending-approvals" in self.src


# ═══════════════════════════════════════════════════════════════════
# §2  React Hook Types & Data Flow
# ═══════════════════════════════════════════════════════════════════


class TestHookTypes:
    """Verify useDevGovernance hook file exports correct types and hooks."""

    src = _read(HOOK_FILE)

    # ── Exported interfaces ──────────────────────────────────────

    def test_dev_proposal_interface(self):
        assert "export interface DevProposal" in self.src

    def test_approval_record_interface(self):
        assert "export interface ApprovalRecord" in self.src

    def test_debate_round_interface(self):
        assert "export interface DebateRound" in self.src

    def test_proposal_metric_interface(self):
        assert "export interface ProposalMetric" in self.src

    def test_governance_metrics_interface(self):
        assert "export interface GovernanceMetrics" in self.src

    def test_agent_governance_stats_interface(self):
        assert "export interface AgentGovernanceStats" in self.src

    def test_audit_event_interface(self):
        assert "export interface AuditEvent" in self.src

    def test_risk_policy_interface(self):
        assert "export interface RiskPolicy" in self.src

    def test_create_proposal_request_interface(self):
        assert "export interface CreateProposalRequest" in self.src

    def test_submit_approval_request_interface(self):
        assert "export interface SubmitApprovalRequest" in self.src

    # ── Exported hooks ───────────────────────────────────────────

    def test_use_dev_proposals_hook(self):
        assert "export function useDevProposals" in self.src

    def test_use_dev_approvals_hook(self):
        assert "export function useDevApprovals" in self.src

    def test_use_governance_dashboard_hook(self):
        assert "export function useGovernanceDashboard" in self.src

    # ── DevProposal fields ───────────────────────────────────────

    @pytest.mark.parametrize("field", [
        "id", "kind", "title", "description", "target", "diff_summary",
        "risk_tier", "risk_score", "affected_subsystems", "status",
        "proposer_id", "owner_id", "branch_ref", "pr_link",
        "consensus_score", "forecast_question", "forecast_probability",
        "rollout_strategy", "approvals", "debate_rounds", "metrics",
        "tags", "created_at", "updated_at",
    ])
    def test_dev_proposal_has_field(self, field: str):
        # Match field declaration in the interface
        assert re.search(rf"\b{field}\b\s*:", self.src), f"DevProposal missing field: {field}"

    # ── Hook return values ───────────────────────────────────────

    def test_use_dev_proposals_returns_proposals(self):
        assert "proposals" in self.src
        assert "fetchProposals" in self.src
        assert "createProposal" in self.src
        assert "updateStatus" in self.src

    def test_use_dev_approvals_returns_pending(self):
        assert "pending" in self.src
        assert "submitApproval" in self.src
        assert "addDebateRound" in self.src

    def test_use_governance_dashboard_returns_metrics(self):
        assert "agentStats" in self.src
        assert "riskPolicy" in self.src
        assert "auditLog" in self.src
        assert "refreshAll" in self.src

    # ── API endpoint usage ───────────────────────────────────────

    def test_hooks_use_governance_endpoints(self):
        assert "API_ENDPOINTS.DEV_GOVERNANCE_PROPOSALS" in self.src
        assert "API_ENDPOINTS.DEV_GOVERNANCE_METRICS" in self.src
        assert "API_ENDPOINTS.DEV_GOVERNANCE_PENDING" in self.src
        assert "API_ENDPOINTS.DEV_GOVERNANCE_AGENT_STATS" in self.src
        assert "API_ENDPOINTS.DEV_GOVERNANCE_AUDIT_LOG" in self.src


# ═══════════════════════════════════════════════════════════════════
# §3  DevProposalBoard Component
# ═══════════════════════════════════════════════════════════════════


class TestDevProposalBoard:
    """Verify DevProposalBoard component structure."""

    src = _read(PROPOSAL_BOARD_FILE)

    def test_file_exists(self):
        assert PROPOSAL_BOARD_FILE.exists()

    def test_exports_default(self):
        assert "export default function DevProposalBoard" in self.src

    def test_kanban_view_mode(self):
        assert "kanban" in self.src
        assert "list" in self.src

    def test_status_columns_defined(self):
        for status in ["draft", "in_review", "approved", "rejected", "scheduled", "executing", "executed", "rolled_back"]:
            assert status in self.src, f"Missing status column: {status}"

    def test_risk_colors_defined(self):
        for risk in ["low", "medium", "high", "critical"]:
            assert risk in self.src, f"Missing risk color: {risk}"

    def test_kind_labels_defined(self):
        for kind in ["signal_change", "model_change", "reward_change", "betting_change", "infra_change"]:
            assert kind in self.src, f"Missing kind label: {kind}"

    def test_filter_controls(self):
        assert "filterRisk" in self.src
        assert "filterKind" in self.src
        assert "sortBy" in self.src

    def test_proposal_card_component(self):
        assert "ProposalCard" in self.src

    def test_imports_dev_proposal_type(self):
        assert "DevProposal" in self.src
        assert "useDevGovernance" in self.src


# ═══════════════════════════════════════════════════════════════════
# §4  DevProposalDetail Component
# ═══════════════════════════════════════════════════════════════════


class TestDevProposalDetail:
    """Verify DevProposalDetail component structure."""

    src = _read(PROPOSAL_DETAIL_FILE)

    def test_file_exists(self):
        assert PROPOSAL_DETAIL_FILE.exists()

    def test_exports_default(self):
        assert "export default function DevProposalDetail" in self.src

    def test_tabs_defined(self):
        for tab in ["summary", "approvals", "debates", "metrics"]:
            assert tab in self.src, f"Missing tab: {tab}"

    def test_approval_actions(self):
        assert "approve" in self.src
        assert "reject" in self.src
        assert "request_changes" in self.src

    def test_status_change_actions(self):
        assert "in_review" in self.src
        assert "scheduled" in self.src
        assert "executing" in self.src
        assert "executed" in self.src
        assert "rolled_back" in self.src

    def test_modal_structure(self):
        assert "fixed inset-0" in self.src  # Modal overlay

    def test_props_interface(self):
        assert "onClose" in self.src
        assert "onApproval" in self.src
        assert "onStatusChange" in self.src
        assert "onDebateRound" in self.src

    def test_debate_round_form(self):
        assert "debateProposer" in self.src or "proposer_argument" in self.src
        assert "debateChallenger" in self.src or "challenger_argument" in self.src

    def test_metrics_table(self):
        assert "metric_name" in self.src
        assert "baseline_value" in self.src
        assert "expected_value" in self.src
        assert "actual_value" in self.src


# ═══════════════════════════════════════════════════════════════════
# §5  GovernanceDashboard Component
# ═══════════════════════════════════════════════════════════════════


class TestGovernanceDashboard:
    """Verify GovernanceDashboard component structure."""

    src = _read(GOVERNANCE_DASHBOARD_FILE)

    def test_file_exists(self):
        assert GOVERNANCE_DASHBOARD_FILE.exists()

    def test_exports_default(self):
        assert "export default function GovernanceDashboard" in self.src

    def test_metric_tiles(self):
        for label in ["Total Proposals", "This Week", "Approval Rate", "Regression Rate", "Guardrail Blocks"]:
            assert label in self.src, f"Missing metric tile: {label}"

    def test_distribution_charts(self):
        assert "By Status" in self.src
        assert "By Risk Tier" in self.src
        assert "By Kind" in self.src

    def test_distribution_bar_component(self):
        assert "DistributionBar" in self.src

    def test_imports_governance_metrics(self):
        assert "GovernanceMetrics" in self.src
        assert "useDevGovernance" in self.src

    def test_refresh_button(self):
        assert "onRefresh" in self.src
        assert "Refresh" in self.src


# ═══════════════════════════════════════════════════════════════════
# §6  HITLApprovalQueue Component
# ═══════════════════════════════════════════════════════════════════


class TestHITLApprovalQueue:
    """Verify HITLApprovalQueue component structure."""

    src = _read(HITL_QUEUE_FILE)

    def test_file_exists(self):
        assert HITL_QUEUE_FILE.exists()

    def test_exports_default(self):
        assert "export default function HITLApprovalQueue" in self.src

    def test_risk_badge_colors(self):
        for risk in ["low", "medium", "high", "critical"]:
            assert risk in self.src, f"Missing risk badge: {risk}"

    def test_quick_action_buttons(self):
        assert "Approve" in self.src
        assert "Reject" in self.src

    def test_expanded_detail_view(self):
        assert "expandedId" in self.src or "isExpanded" in self.src

    def test_justification_input(self):
        assert "justification" in self.src or "Justification" in self.src

    def test_pending_count_badge(self):
        assert "pending" in self.src

    def test_critical_alert(self):
        assert "critical" in self.src
        assert "animate-pulse" in self.src

    def test_all_clear_state(self):
        assert "All Clear" in self.src

    def test_props_interface(self):
        assert "onApproval" in self.src
        assert "onSelect" in self.src
        assert "onRefresh" in self.src


# ═══════════════════════════════════════════════════════════════════
# §7  DevAgentRoster Component
# ═══════════════════════════════════════════════════════════════════


class TestDevAgentRoster:
    """Verify DevAgentRoster component structure."""

    src = _read(AGENT_ROSTER_FILE)

    def test_file_exists(self):
        assert AGENT_ROSTER_FILE.exists()

    def test_exports_default(self):
        assert "export default function DevAgentRoster" in self.src

    def test_agent_stats_fields(self):
        for field in ["proposals_created", "proposals_approved", "proposals_rejected",
                       "proposals_executed", "proposals_rolled_back", "reviews_given"]:
            assert field in self.src, f"Missing agent stat field: {field}"

    def test_human_vs_agent_detection(self):
        assert "isHuman" in self.src or "agent_" in self.src

    def test_execution_rate_bar(self):
        assert "Execution Rate" in self.src or "successRate" in self.src

    def test_risk_avg_display(self):
        assert "avg_risk_score" in self.src or "Risk Avg" in self.src

    def test_imports_agent_stats_type(self):
        assert "AgentGovernanceStats" in self.src
        assert "useDevGovernance" in self.src


# ═══════════════════════════════════════════════════════════════════
# §8  DevSwarmControlCenter View Assembly
# ═══════════════════════════════════════════════════════════════════


class TestDevSwarmControlCenter:
    """Verify DevSwarmControlCenter view integrates all governance components."""

    src = _read(VIEW_FILE)

    def test_file_exists(self):
        assert VIEW_FILE.exists()

    def test_exports_default(self):
        assert "export default function DevSwarmControlCenter" in self.src

    def test_imports_all_hooks(self):
        assert "useDevProposals" in self.src
        assert "useDevApprovals" in self.src
        assert "useGovernanceDashboard" in self.src

    def test_imports_all_components(self):
        assert "DevProposalBoard" in self.src
        assert "DevProposalDetail" in self.src
        assert "DevAgentRoster" in self.src
        assert "GovernanceDashboard" in self.src
        assert "HITLApprovalQueue" in self.src

    def test_tab_navigation(self):
        for tab in ["overview", "proposals", "approvals", "agents", "audit"]:
            assert tab in self.src, f"Missing tab: {tab}"

    def test_selected_proposal_state(self):
        assert "selectedProposal" in self.src
        assert "setSelectedProposal" in self.src

    def test_refresh_all_button(self):
        assert "Refresh All" in self.src

    def test_pending_approval_badge(self):
        assert "pending" in self.src
        assert "animate-pulse" in self.src

    def test_audit_log_tab(self):
        assert "Audit Log" in self.src
        assert "auditLog" in self.src

    def test_proposal_detail_modal_wired(self):
        assert "DevProposalDetail" in self.src
        assert "onClose" in self.src
        assert "onApproval" in self.src
        assert "onStatusChange" in self.src
        assert "onDebateRound" in self.src


# ═══════════════════════════════════════════════════════════════════
# §9  Navigation Wiring
# ═══════════════════════════════════════════════════════════════════


class TestNavigationWiring:
    """Verify devswarm-governance is wired into App.tsx and Sidebar.tsx."""

    app_src = _read(APP_FILE)
    sidebar_src = _read(SIDEBAR_FILE)

    def test_app_imports_control_center(self):
        assert "DevSwarmControlCenter" in self.app_src

    def test_app_view_type_includes_governance(self):
        assert "devswarm-governance" in self.app_src

    def test_app_renders_control_center(self):
        assert "devswarm-governance" in self.app_src
        assert "DevSwarmControlCenter" in self.app_src

    def test_sidebar_view_type_includes_governance(self):
        assert "devswarm-governance" in self.sidebar_src

    def test_sidebar_has_governance_nav_item(self):
        assert "Swarm Governance" in self.sidebar_src
        assert "devswarm-governance" in self.sidebar_src

    def test_sidebar_governance_icon(self):
        assert "Shield" in self.sidebar_src


# ═══════════════════════════════════════════════════════════════════
# §10  Backend Core Model
# ═══════════════════════════════════════════════════════════════════


class TestCoreModel:
    """Verify core/dev_swarm_governance.py data model integrity."""

    src = _read(GOVERNANCE_CORE_FILE)

    # ── Enums ────────────────────────────────────────────────────

    def test_proposal_kind_enum(self):
        assert "class ProposalKind(Enum)" in self.src
        for kind in ["SIGNAL_CHANGE", "MODEL_CHANGE", "REWARD_CHANGE", "BETTING_CHANGE",
                      "SLO_CHANGE", "INFRA_CHANGE", "UI_CHANGE", "DOCS_CHANGE",
                      "CONFIG_CHANGE", "STRATEGY_CHANGE", "OPTICODDS_CHANGE"]:
            assert kind in self.src, f"Missing ProposalKind: {kind}"

    def test_proposal_status_enum(self):
        assert "class ProposalStatus(Enum)" in self.src
        for status in ["DRAFT", "IN_REVIEW", "APPROVED", "REJECTED", "SCHEDULED",
                        "EXECUTING", "EXECUTED", "ROLLED_BACK"]:
            assert status in self.src, f"Missing ProposalStatus: {status}"

    def test_risk_tier_enum(self):
        assert "class RiskTier(Enum)" in self.src
        for tier in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]:
            assert tier in self.src, f"Missing RiskTier: {tier}"

    def test_approval_action_enum(self):
        assert "class ApprovalAction(Enum)" in self.src
        for action in ["APPROVE", "REJECT", "REQUEST_CHANGES", "ABSTAIN"]:
            assert action in self.src, f"Missing ApprovalAction: {action}"

    def test_reviewer_role_enum(self):
        assert "class ReviewerRole(Enum)" in self.src
        for role in ["HUMAN_OWNER", "HUMAN_REVIEWER", "AGENT_REVIEWER", "RISK_REVIEWER"]:
            assert role in self.src, f"Missing ReviewerRole: {role}"

    def test_audit_event_type_enum(self):
        assert "class AuditEventType(Enum)" in self.src
        for evt in ["PROPOSAL_CREATED", "STATUS_CHANGED", "APPROVAL_SUBMITTED",
                     "DEBATE_ROUND", "EXECUTION_COMPLETED", "ROLLBACK_INITIATED",
                     "GUARDRAIL_BLOCKED", "EVIDENCE_ATTACHED"]:
            assert evt in self.src, f"Missing AuditEventType: {evt}"

    # ── Risk policy ──────────────────────────────────────────────

    def test_risk_tier_policy_defined(self):
        assert "RISK_TIER_POLICY" in self.src

    def test_kind_default_risk_defined(self):
        assert "KIND_DEFAULT_RISK" in self.src

    # ── Dataclasses ──────────────────────────────────────────────

    def test_approval_record_dataclass(self):
        assert "class ApprovalRecord" in self.src

    def test_debate_round_dataclass(self):
        assert "class DebateRound" in self.src

    def test_proposal_metrics_dataclass(self):
        assert "class ProposalMetrics" in self.src

    def test_dev_proposal_dataclass(self):
        assert "class DevProposal" in self.src

    def test_audit_event_dataclass(self):
        assert "class AuditEvent" in self.src

    def test_governance_metrics_dataclass(self):
        assert "class GovernanceMetrics" in self.src

    # ── GovernanceStore ──────────────────────────────────────────

    def test_governance_store_class(self):
        assert "class GovernanceStore" in self.src

    def test_governance_store_singleton(self):
        assert "get_governance_store" in self.src


# ═══════════════════════════════════════════════════════════════════
# §11  Backend API Route Availability
# ═══════════════════════════════════════════════════════════════════


class TestAPIRoutes:
    """Verify dev_swarm_governance_routes.py defines all expected endpoints."""

    src = _read(GOVERNANCE_ROUTES_FILE)

    def test_file_exists(self):
        assert GOVERNANCE_ROUTES_FILE.exists()

    def test_router_prefix(self):
        assert '/api/dev-swarm/governance' in self.src

    def test_create_proposal_endpoint(self):
        assert '@router.post("/proposals"' in self.src

    def test_list_proposals_endpoint(self):
        assert '@router.get("/proposals")' in self.src

    def test_get_proposal_endpoint(self):
        assert '@router.get("/proposals/{proposal_id}")' in self.src

    def test_update_status_endpoint(self):
        assert '@router.patch("/proposals/{proposal_id}/status")' in self.src

    def test_submit_approval_endpoint(self):
        assert '@router.post("/proposals/{proposal_id}/approvals")' in self.src

    def test_list_approvals_endpoint(self):
        assert '@router.get("/proposals/{proposal_id}/approvals")' in self.src

    def test_add_debate_endpoint(self):
        assert '@router.post("/proposals/{proposal_id}/debates")' in self.src

    def test_list_debates_endpoint(self):
        assert '@router.get("/proposals/{proposal_id}/debates")' in self.src

    def test_attach_metrics_endpoint(self):
        assert '@router.post("/proposals/{proposal_id}/metrics")' in self.src

    def test_governance_metrics_endpoint(self):
        assert '@router.get("/metrics")' in self.src

    def test_agent_stats_endpoint(self):
        assert '@router.get("/agent-stats")' in self.src

    def test_risk_policy_endpoint(self):
        assert '@router.get("/risk-policy")' in self.src

    def test_audit_log_endpoint(self):
        assert '@router.get("/audit-log")' in self.src

    def test_pending_approvals_endpoint(self):
        assert '@router.get("/pending-approvals")' in self.src

    # ── Request models ───────────────────────────────────────────

    def test_create_proposal_request_model(self):
        assert "class CreateProposalRequest" in self.src

    def test_submit_approval_request_model(self):
        assert "class SubmitApprovalRequest" in self.src

    def test_add_debate_round_request_model(self):
        assert "class AddDebateRoundRequest" in self.src

    def test_attach_metrics_request_model(self):
        assert "class AttachMetricsRequest" in self.src

    def test_update_status_request_model(self):
        assert "class UpdateStatusRequest" in self.src


# ═══════════════════════════════════════════════════════════════════
# §12  GovernanceStore Lifecycle (Integration Tests)
# ═══════════════════════════════════════════════════════════════════


class TestGovernanceStoreLifecycle:
    """Integration tests for GovernanceStore CRUD and lifecycle transitions."""

    @pytest.fixture(autouse=True)
    def fresh_store(self):
        from core.dev_swarm_governance import GovernanceStore
        self.store = GovernanceStore()

    def _make_proposal(self, **overrides) -> Any:
        from core.dev_swarm_governance import DevProposal
        defaults = dict(
            kind="config_change",
            title="Test proposal for config change",
            description="Unit test proposal",
            risk_tier="medium",
            risk_score=0.5,
            status="draft",
            proposer_id="human",
            owner_id="human",
        )
        defaults.update(overrides)
        return DevProposal(**defaults)

    # ── Create ───────────────────────────────────────────────────

    def test_create_proposal(self):
        p = self._make_proposal()
        created = self.store.create_proposal(p, actor_id="human")
        assert created.id == p.id
        assert created.status == "draft"
        assert created.kind == "config_change"

    def test_create_proposal_generates_id(self):
        p = self._make_proposal()
        assert len(p.id) > 0

    def test_create_proposal_emits_audit(self):
        p = self._make_proposal()
        self.store.create_proposal(p, actor_id="human")
        events = self.store.get_audit_log(proposal_id=p.id)
        assert len(events) == 1
        assert events[0].event_type == "proposal_created"

    # ── Read ─────────────────────────────────────────────────────

    def test_get_proposal(self):
        p = self._make_proposal()
        self.store.create_proposal(p)
        fetched = self.store.get_proposal(p.id)
        assert fetched is not None
        assert fetched.title == p.title

    def test_get_nonexistent_proposal(self):
        assert self.store.get_proposal("nonexistent") is None

    def test_list_proposals_empty(self):
        assert self.store.list_proposals() == []

    def test_list_proposals_returns_all(self):
        for i in range(5):
            self.store.create_proposal(self._make_proposal(title=f"Proposal {i}"))
        assert len(self.store.list_proposals()) == 5

    def test_list_proposals_filter_by_status(self):
        self.store.create_proposal(self._make_proposal(status="draft"))
        self.store.create_proposal(self._make_proposal(status="in_review"))
        assert len(self.store.list_proposals(status="draft")) == 1
        assert len(self.store.list_proposals(status="in_review")) == 1

    def test_list_proposals_filter_by_kind(self):
        self.store.create_proposal(self._make_proposal(kind="config_change"))
        self.store.create_proposal(self._make_proposal(kind="infra_change"))
        assert len(self.store.list_proposals(kind="config_change")) == 1

    def test_list_proposals_filter_by_risk_tier(self):
        self.store.create_proposal(self._make_proposal(risk_tier="low"))
        self.store.create_proposal(self._make_proposal(risk_tier="critical"))
        assert len(self.store.list_proposals(risk_tier="critical")) == 1

    def test_list_proposals_pagination(self):
        for i in range(10):
            self.store.create_proposal(self._make_proposal(title=f"P{i}"))
        page = self.store.list_proposals(limit=3, offset=0)
        assert len(page) == 3
        page2 = self.store.list_proposals(limit=3, offset=3)
        assert len(page2) == 3
        assert page[0].id != page2[0].id

    # ── Status transitions ───────────────────────────────────────

    def test_update_status(self):
        p = self._make_proposal()
        self.store.create_proposal(p)
        updated = self.store.update_status(p.id, "in_review")
        assert updated is not None
        assert updated.status == "in_review"

    def test_update_status_nonexistent(self):
        assert self.store.update_status("nope", "in_review") is None

    def test_update_status_emits_audit(self):
        p = self._make_proposal()
        self.store.create_proposal(p)
        self.store.update_status(p.id, "in_review")
        events = self.store.get_audit_log(proposal_id=p.id, event_type="status_changed")
        assert len(events) == 1

    def test_executed_sets_timestamp(self):
        p = self._make_proposal()
        self.store.create_proposal(p)
        self.store.update_status(p.id, "executed")
        fetched = self.store.get_proposal(p.id)
        assert fetched.executed_at is not None

    def test_scheduled_sets_timestamp(self):
        p = self._make_proposal()
        self.store.create_proposal(p)
        self.store.update_status(p.id, "scheduled")
        fetched = self.store.get_proposal(p.id)
        assert fetched.scheduled_at is not None

    def test_rolled_back_sets_timestamp(self):
        p = self._make_proposal()
        self.store.create_proposal(p)
        self.store.update_status(p.id, "rolled_back")
        fetched = self.store.get_proposal(p.id)
        assert fetched.rolled_back_at is not None

    # ── Approvals ────────────────────────────────────────────────

    def test_submit_approval(self):
        p = self._make_proposal(status="in_review")
        self.store.create_proposal(p)
        record = self.store.submit_approval(
            p.id, reviewer_id="alice", reviewer_role="human_reviewer",
            action="approve", justification="Looks good",
        )
        assert record is not None
        assert record.action == "approve"
        assert record.reviewer_id == "alice"

    def test_submit_approval_nonexistent(self):
        assert self.store.submit_approval("nope", "alice", "human_reviewer", "approve") is None

    def test_approval_emits_audit(self):
        p = self._make_proposal(status="in_review")
        self.store.create_proposal(p)
        self.store.submit_approval(p.id, "alice", "human_reviewer", "approve")
        events = self.store.get_audit_log(proposal_id=p.id, event_type="approval_submitted")
        assert len(events) == 1

    def test_approval_count(self):
        p = self._make_proposal(status="in_review")
        self.store.create_proposal(p)
        self.store.submit_approval(p.id, "alice", "human_reviewer", "approve")
        self.store.submit_approval(p.id, "bob", "human_reviewer", "approve")
        self.store.submit_approval(p.id, "carol", "human_reviewer", "reject")
        fetched = self.store.get_proposal(p.id)
        assert fetched.approval_count == 2
        assert fetched.rejection_count == 1

    def test_human_approval_count(self):
        p = self._make_proposal(status="in_review")
        self.store.create_proposal(p)
        self.store.submit_approval(p.id, "alice", "human_reviewer", "approve")
        self.store.submit_approval(p.id, "agent_1", "agent_reviewer", "approve")
        fetched = self.store.get_proposal(p.id)
        assert fetched.human_approval_count == 1

    def test_auto_approve_low_risk(self):
        """Low risk: 1 human approval → auto-schedule (auto_schedule=True)."""
        p = self._make_proposal(status="in_review", risk_tier="low")
        self.store.create_proposal(p)
        self.store.submit_approval(p.id, "alice", "human_reviewer", "approve")
        fetched = self.store.get_proposal(p.id)
        assert fetched.status == "scheduled"

    def test_auto_approve_medium_risk(self):
        """Medium risk: 2 approvals needed, at least 1 human → approved (not auto-scheduled)."""
        p = self._make_proposal(status="in_review", risk_tier="medium")
        self.store.create_proposal(p)
        self.store.submit_approval(p.id, "alice", "human_reviewer", "approve")
        # Not yet met threshold
        fetched = self.store.get_proposal(p.id)
        assert fetched.status == "in_review"
        self.store.submit_approval(p.id, "bob", "human_reviewer", "approve")
        fetched = self.store.get_proposal(p.id)
        assert fetched.status == "approved"

    def test_auto_reject_majority(self):
        """If majority reject after min_approvals reviews, auto-reject."""
        p = self._make_proposal(status="in_review", risk_tier="medium")
        self.store.create_proposal(p)
        self.store.submit_approval(p.id, "alice", "human_reviewer", "reject")
        self.store.submit_approval(p.id, "bob", "human_reviewer", "reject")
        fetched = self.store.get_proposal(p.id)
        assert fetched.status == "rejected"

    def test_meets_approval_threshold_false(self):
        p = self._make_proposal(status="in_review", risk_tier="high")
        self.store.create_proposal(p)
        self.store.submit_approval(p.id, "alice", "human_reviewer", "approve")
        fetched = self.store.get_proposal(p.id)
        assert fetched.meets_approval_threshold is False

    def test_meets_approval_threshold_true(self):
        p = self._make_proposal(status="in_review", risk_tier="low")
        self.store.create_proposal(p)
        self.store.submit_approval(p.id, "alice", "human_reviewer", "approve")
        fetched = self.store.get_proposal(p.id)
        assert fetched.meets_approval_threshold is True

    # ── Debates ──────────────────────────────────────────────────

    def test_add_debate_round(self):
        p = self._make_proposal()
        self.store.create_proposal(p)
        dr = self.store.add_debate_round(
            p.id, proposer_argument="Pro argument", challenger_argument="Con argument",
        )
        assert dr is not None
        assert dr.round_number == 1
        assert dr.proposer_argument == "Pro argument"

    def test_add_multiple_debate_rounds(self):
        p = self._make_proposal()
        self.store.create_proposal(p)
        self.store.add_debate_round(p.id, "Pro 1", "Con 1")
        dr2 = self.store.add_debate_round(p.id, "Pro 2", "Con 2")
        assert dr2.round_number == 2
        fetched = self.store.get_proposal(p.id)
        assert len(fetched.debate_rounds) == 2

    def test_debate_round_nonexistent(self):
        assert self.store.add_debate_round("nope", "a", "b") is None

    def test_debate_emits_audit(self):
        p = self._make_proposal()
        self.store.create_proposal(p)
        self.store.add_debate_round(p.id, "Pro", "Con")
        events = self.store.get_audit_log(proposal_id=p.id, event_type="debate_round")
        assert len(events) == 1

    def test_debate_with_evidence(self):
        p = self._make_proposal()
        self.store.create_proposal(p)
        dr = self.store.add_debate_round(
            p.id, "Pro", "Con",
            evidence_refs=["backtest_v2.json", "slo_report.pdf"],
            metrics_snapshot={"sharpe": 1.5},
        )
        assert dr.evidence_refs == ["backtest_v2.json", "slo_report.pdf"]
        assert dr.metrics_snapshot == {"sharpe": 1.5}

    # ── Metrics ──────────────────────────────────────────────────

    def test_attach_metrics(self):
        from core.dev_swarm_governance import ProposalMetrics
        p = self._make_proposal()
        self.store.create_proposal(p)
        ok = self.store.attach_metrics(p.id, [
            ProposalMetrics(metric_name="sharpe", baseline_value=1.0, expected_value=1.2),
            ProposalMetrics(metric_name="drawdown", baseline_value=0.15, expected_value=0.10),
        ])
        assert ok is True
        fetched = self.store.get_proposal(p.id)
        assert len(fetched.metrics) == 2

    def test_attach_metrics_nonexistent(self):
        assert self.store.attach_metrics("nope", []) is False

    def test_attach_metrics_emits_audit(self):
        from core.dev_swarm_governance import ProposalMetrics
        p = self._make_proposal()
        self.store.create_proposal(p)
        self.store.attach_metrics(p.id, [
            ProposalMetrics(metric_name="pnl", baseline_value=100, expected_value=120),
        ])
        events = self.store.get_audit_log(proposal_id=p.id, event_type="evidence_attached")
        assert len(events) == 1

    # ── Governance metrics ───────────────────────────────────────

    def test_compute_governance_metrics_empty(self):
        m = self.store.compute_governance_metrics()
        assert m.total_proposals == 0
        assert m.approval_rate == 0.0

    def test_compute_governance_metrics_populated(self):
        self.store.create_proposal(self._make_proposal(status="executed", proposer_id="human"))
        self.store.create_proposal(self._make_proposal(status="rejected", proposer_id="agent_coder"))
        self.store.create_proposal(self._make_proposal(status="draft", proposer_id="human"))
        m = self.store.compute_governance_metrics()
        assert m.total_proposals == 3
        assert m.proposals_by_status["executed"] == 1
        assert m.proposals_by_status["rejected"] == 1
        assert m.proposals_by_status["draft"] == 1
        assert m.human_initiated_ratio > 0
        assert m.agent_initiated_ratio > 0

    def test_governance_metrics_proposals_this_week(self):
        p = self._make_proposal()
        self.store.create_proposal(p)
        m = self.store.compute_governance_metrics()
        assert m.proposals_this_week >= 1

    # ── Audit log ────────────────────────────────────────────────

    def test_audit_log_empty(self):
        assert self.store.get_audit_log() == []

    def test_audit_log_filters_by_proposal(self):
        p1 = self._make_proposal()
        p2 = self._make_proposal()
        self.store.create_proposal(p1)
        self.store.create_proposal(p2)
        events = self.store.get_audit_log(proposal_id=p1.id)
        assert all(e.proposal_id == p1.id for e in events)

    def test_audit_log_filters_by_event_type(self):
        p = self._make_proposal(status="in_review")
        self.store.create_proposal(p)
        self.store.submit_approval(p.id, "alice", "human_reviewer", "approve")
        events = self.store.get_audit_log(event_type="approval_submitted")
        assert len(events) >= 1

    def test_audit_log_pagination(self):
        for i in range(10):
            self.store.create_proposal(self._make_proposal(title=f"P{i}"))
        page = self.store.get_audit_log(limit=3, offset=0)
        assert len(page) == 3

    # ── Agent stats ──────────────────────────────────────────────

    def test_agent_stats_empty(self):
        assert self.store.get_agent_governance_stats() == []

    def test_agent_stats_populated(self):
        p = self._make_proposal(proposer_id="agent_coder_1", status="executed")
        self.store.create_proposal(p)
        self.store.submit_approval(p.id, "human", "human_reviewer", "approve")
        stats = self.store.get_agent_governance_stats()
        assert len(stats) >= 1
        agent_stat = next((s for s in stats if s["agent_id"] == "agent_coder_1"), None)
        assert agent_stat is not None
        assert agent_stat["proposals_created"] == 1

    # ── Serialization ────────────────────────────────────────────

    def test_proposal_to_dict(self):
        p = self._make_proposal()
        d = p.to_dict()
        assert isinstance(d, dict)
        assert "id" in d
        assert "kind" in d
        assert "approvals" in d
        assert "debate_rounds" in d
        assert "metrics" in d

    def test_approval_record_to_dict(self):
        from core.dev_swarm_governance import ApprovalRecord
        a = ApprovalRecord(proposal_id="test", reviewer_id="alice", action="approve")
        d = a.to_dict()
        assert d["reviewer_id"] == "alice"
        assert d["action"] == "approve"

    def test_debate_round_to_dict(self):
        from core.dev_swarm_governance import DebateRound
        dr = DebateRound(round_number=1, proposer_argument="Pro", challenger_argument="Con")
        d = dr.to_dict()
        assert d["round_number"] == 1

    def test_governance_metrics_to_dict(self):
        from core.dev_swarm_governance import GovernanceMetrics
        m = GovernanceMetrics(total_proposals=5, approval_rate=0.8)
        d = m.to_dict()
        assert d["total_proposals"] == 5
        assert d["approval_rate"] == 0.8

    def test_audit_event_to_dict(self):
        from core.dev_swarm_governance import AuditEvent
        e = AuditEvent(event_type="proposal_created", proposal_id="abc", actor_id="human")
        d = e.to_dict()
        assert d["event_type"] == "proposal_created"


# ═══════════════════════════════════════════════════════════════════
# §13  Risk Policy Validation
# ═══════════════════════════════════════════════════════════════════


class TestRiskPolicy:
    """Validate risk tier policies and kind→tier mappings."""

    def test_all_tiers_have_policy(self):
        from core.dev_swarm_governance import RiskTier, RISK_TIER_POLICY
        for tier in RiskTier:
            assert tier in RISK_TIER_POLICY, f"Missing policy for {tier}"

    def test_policy_fields(self):
        from core.dev_swarm_governance import RiskTier, RISK_TIER_POLICY
        required_fields = {"min_approvals", "require_human", "require_backtest",
                           "require_slo_green", "max_debate_rounds", "auto_schedule"}
        for tier, policy in RISK_TIER_POLICY.items():
            for field in required_fields:
                assert field in policy, f"Missing {field} in {tier} policy"

    def test_low_tier_auto_schedule(self):
        from core.dev_swarm_governance import RiskTier, RISK_TIER_POLICY
        assert RISK_TIER_POLICY[RiskTier.LOW]["auto_schedule"] is True

    def test_high_tier_requires_backtest(self):
        from core.dev_swarm_governance import RiskTier, RISK_TIER_POLICY
        assert RISK_TIER_POLICY[RiskTier.HIGH]["require_backtest"] is True

    def test_critical_tier_min_approvals(self):
        from core.dev_swarm_governance import RiskTier, RISK_TIER_POLICY
        assert RISK_TIER_POLICY[RiskTier.CRITICAL]["min_approvals"] >= 3

    def test_all_kinds_have_default_risk(self):
        from core.dev_swarm_governance import ProposalKind, KIND_DEFAULT_RISK
        for kind in ProposalKind:
            assert kind in KIND_DEFAULT_RISK, f"Missing default risk for {kind}"

    def test_opticodds_is_critical(self):
        from core.dev_swarm_governance import ProposalKind, RiskTier, KIND_DEFAULT_RISK
        assert KIND_DEFAULT_RISK[ProposalKind.OPTICODDS_CHANGE] == RiskTier.CRITICAL

    def test_docs_is_low(self):
        from core.dev_swarm_governance import ProposalKind, RiskTier, KIND_DEFAULT_RISK
        assert KIND_DEFAULT_RISK[ProposalKind.DOCS_CHANGE] == RiskTier.LOW

    def test_approval_escalation(self):
        """Verify min_approvals increases with risk tier severity."""
        from core.dev_swarm_governance import RiskTier, RISK_TIER_POLICY
        low = RISK_TIER_POLICY[RiskTier.LOW]["min_approvals"]
        med = RISK_TIER_POLICY[RiskTier.MEDIUM]["min_approvals"]
        high = RISK_TIER_POLICY[RiskTier.HIGH]["min_approvals"]
        assert low <= med <= high
