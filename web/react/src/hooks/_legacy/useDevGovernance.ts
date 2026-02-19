import { useState, useCallback, useEffect } from 'react';
import axios from 'axios';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

// ── Types ────────────────────────────────────────────────────────────

export interface ApprovalRecord {
  id: string;
  proposal_id: string;
  reviewer_id: string;
  reviewer_role: string;
  action: string;
  justification: string;
  timestamp: number;
}

export interface DebateRound {
  round_number: number;
  proposer_argument: string;
  challenger_argument: string;
  evidence_refs: string[];
  metrics_snapshot: Record<string, unknown>;
  timestamp: number;
}

export interface ProposalMetric {
  metric_name: string;
  baseline_value: number;
  expected_value: number;
  actual_value: number | null;
  unit: string;
  improved: boolean | null;
}

export interface DevProposal {
  id: string;
  kind: string;
  title: string;
  description: string;
  target: string;
  diff_summary: string;
  risk_tier: string;
  risk_score: number;
  affected_subsystems: string[];
  status: string;
  proposer_id: string;
  owner_id: string;
  branch_ref: string;
  pr_link: string;
  consensus_score: number;
  forecast_question: string;
  forecast_probability: number;
  rollout_strategy: string;
  meets_approval_threshold?: boolean;
  approvals: ApprovalRecord[];
  debate_rounds: DebateRound[];
  metrics: ProposalMetric[];
  tags: string[];
  created_at: number;
  updated_at: number;
  scheduled_at: number | null;
  executed_at: number | null;
  rolled_back_at: number | null;
}

export interface GovernanceMetrics {
  total_proposals: number;
  proposals_by_status: Record<string, number>;
  proposals_by_risk: Record<string, number>;
  proposals_by_kind: Record<string, number>;
  approval_rate: number;
  regression_rate: number;
  avg_time_to_decision_s: number;
  avg_time_to_revert_s: number;
  agent_initiated_ratio: number;
  human_initiated_ratio: number;
  proposals_this_week: number;
  guardrail_blocks: number;
}

export interface AgentGovernanceStats {
  agent_id: string;
  proposals_created: number;
  proposals_approved: number;
  proposals_rejected: number;
  proposals_executed: number;
  proposals_rolled_back: number;
  reviews_given: number;
  avg_risk_score: number;
}

export interface AuditEvent {
  id: string;
  event_type: string;
  proposal_id: string;
  actor_id: string;
  actor_type: string;
  details: Record<string, unknown>;
  timestamp: number;
}

export interface RiskPolicy {
  risk_tiers: Record<string, {
    min_approvals: number;
    require_human: boolean;
    require_backtest: boolean;
    require_slo_green: boolean;
    max_debate_rounds: number;
    auto_schedule: boolean;
  }>;
  kind_defaults: Record<string, string>;
}

export interface CreateProposalRequest {
  kind: string;
  title: string;
  description?: string;
  target?: string;
  diff_summary?: string;
  risk_tier?: string;
  risk_score?: number;
  affected_subsystems?: string[];
  proposer_id?: string;
  owner_id?: string;
  branch_ref?: string;
  pr_link?: string;
  forecast_question?: string;
  rollout_strategy?: string;
  tags?: string[];
}

export interface SubmitApprovalRequest {
  reviewer_id: string;
  reviewer_role?: string;
  action: string;
  justification?: string;
}

const getErrorMessage = (err: unknown, fallback: string) => {
  if (axios.isAxiosError(err)) {
    return err.response?.data?.detail || err.message || fallback;
  }
  if (err instanceof Error) {
    return err.message;
  }
  return fallback;
};

// ── useDevProposals ──────────────────────────────────────────────────

export function useDevProposals(pollMs = 10000) {
  const [proposals, setProposals] = useState<DevProposal[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchProposals = useCallback(async (filters?: {
    status?: string;
    kind?: string;
    risk_tier?: string;
  }) => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string> = {};
      if (filters?.status) params.status = filters.status;
      if (filters?.kind) params.kind = filters.kind;
      if (filters?.risk_tier) params.risk_tier = filters.risk_tier;
      const res = await axios.get(API_ENDPOINTS.DEV_GOVERNANCE_PROPOSALS, { params });
      setProposals(res.data.proposals ?? []);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load proposals'));
    } finally {
      setLoading(false);
    }
  }, []);

  const getProposal = useCallback(async (id: string): Promise<DevProposal | null> => {
    try {
      const res = await axios.get(API_ENDPOINTS.DEV_GOVERNANCE_PROPOSAL(id));
      return res.data;
    } catch {
      return null;
    }
  }, []);

  const createProposal = useCallback(async (req: CreateProposalRequest): Promise<DevProposal | null> => {
    try {
      const res = await axios.post(API_ENDPOINTS.DEV_GOVERNANCE_PROPOSALS, req);
      await fetchProposals();
      return res.data;
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to create proposal'));
      return null;
    }
  }, [fetchProposals]);

  const updateStatus = useCallback(async (id: string, status: string, actorId = 'human'): Promise<DevProposal | null> => {
    try {
      const res = await axios.patch(API_ENDPOINTS.DEV_GOVERNANCE_PROPOSAL_STATUS(id), {
        status,
        actor_id: actorId,
      });
      await fetchProposals();
      return res.data;
    } catch {
      return null;
    }
  }, [fetchProposals]);

  useEffect(() => {
    fetchProposals();
    const interval = setInterval(() => fetchProposals(), pollMs);
    return () => clearInterval(interval);
  }, [fetchProposals, pollMs]);

  return { proposals, loading, error, fetchProposals, getProposal, createProposal, updateStatus };
}

// ── useDevApprovals ──────────────────────────────────────────────────

export function useDevApprovals() {
  const [pending, setPending] = useState<DevProposal[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchPending = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axios.get(API_ENDPOINTS.DEV_GOVERNANCE_PENDING);
      setPending(res.data.pending ?? []);
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to load pending approvals'));
    } finally {
      setLoading(false);
    }
  }, []);

  const submitApproval = useCallback(async (
    proposalId: string,
    req: SubmitApprovalRequest,
  ): Promise<{ approval: ApprovalRecord; proposal: DevProposal } | null> => {
    try {
      const res = await axios.post(
        API_ENDPOINTS.DEV_GOVERNANCE_PROPOSAL_APPROVALS(proposalId),
        req,
      );
      await fetchPending();
      return res.data;
    } catch (err: unknown) {
      setError(getErrorMessage(err, 'Failed to submit approval'));
      return null;
    }
  }, [fetchPending]);

  const addDebateRound = useCallback(async (
    proposalId: string,
    proposerArg: string,
    challengerArg: string,
    evidenceRefs: string[] = [],
    metricsSnapshot: Record<string, unknown> = {},
  ) => {
    try {
      const res = await axios.post(
        API_ENDPOINTS.DEV_GOVERNANCE_PROPOSAL_DEBATES(proposalId),
        {
          proposer_argument: proposerArg,
          challenger_argument: challengerArg,
          evidence_refs: evidenceRefs,
          metrics_snapshot: metricsSnapshot,
        },
      );
      return res.data;
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    fetchPending();
    const interval = setInterval(fetchPending, DEFAULTS.POLLING_INTERVALS.RISK_ALERTS);
    return () => clearInterval(interval);
  }, [fetchPending]);

  return { pending, loading, error, fetchPending, submitApproval, addDebateRound };
}

// ── useGovernanceDashboard ───────────────────────────────────────────

export function useGovernanceDashboard(pollMs = 15000) {
  const [metrics, setMetrics] = useState<GovernanceMetrics | null>(null);
  const [agentStats, setAgentStats] = useState<AgentGovernanceStats[]>([]);
  const [riskPolicy, setRiskPolicy] = useState<RiskPolicy | null>(null);
  const [auditLog, setAuditLog] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchMetrics = useCallback(async () => {
    try {
      const res = await axios.get(API_ENDPOINTS.DEV_GOVERNANCE_METRICS);
      setMetrics(res.data);
    } catch {
      // silent
    }
  }, []);

  const fetchAgentStats = useCallback(async () => {
    try {
      const res = await axios.get(API_ENDPOINTS.DEV_GOVERNANCE_AGENT_STATS);
      setAgentStats(res.data);
    } catch {
      // silent
    }
  }, []);

  const fetchRiskPolicy = useCallback(async () => {
    try {
      const res = await axios.get(API_ENDPOINTS.DEV_GOVERNANCE_RISK_POLICY);
      setRiskPolicy(res.data);
    } catch {
      // silent
    }
  }, []);

  const fetchAuditLog = useCallback(async (filters?: {
    proposal_id?: string;
    event_type?: string;
    limit?: number;
  }) => {
    try {
      const res = await axios.get(API_ENDPOINTS.DEV_GOVERNANCE_AUDIT_LOG, { params: filters });
      setAuditLog(res.data.events ?? []);
    } catch {
      // silent
    }
  }, []);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    await Promise.all([fetchMetrics(), fetchAgentStats(), fetchRiskPolicy(), fetchAuditLog()]);
    setLoading(false);
  }, [fetchMetrics, fetchAgentStats, fetchRiskPolicy, fetchAuditLog]);

  useEffect(() => {
    refreshAll();
    const interval = setInterval(refreshAll, pollMs);
    return () => clearInterval(interval);
  }, [refreshAll, pollMs]);

  return {
    metrics,
    agentStats,
    riskPolicy,
    auditLog,
    loading,
    fetchMetrics,
    fetchAgentStats,
    fetchRiskPolicy,
    fetchAuditLog,
    refreshAll,
  };
}
