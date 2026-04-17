export interface DebateAgentQuota {
  agent_id: string;
  tier: 'gold' | 'silver' | 'bronze' | 'restricted';
  quota_pct: number;
  utilized_pct: number;
  available_pct: number;
  total_risk_usd: number;
  allocated_risk_usd: number;
  debate_contribution_pct: number;
  last_updated: string;
}

export interface DebateQuotaSummary {
  total_agents: number;
  total_teams: number;
  tier_distribution: Record<string, number>;
  agent_utilization: {
    utilization: number;
    total_quota: number;
    utilized: number;
  };
  team_utilization: {
    utilization: number;
    total_quota: number;
    utilized: number;
  };
  agent_profiles: Record<string, DebateAgentQuota>;
  team_profiles: Record<string, any>;
}

export interface DebatePnLAttribution {
  tracked_trades: number;
  debate_contribution_pct: number;
  debate_sizing_win_rate: number;
  debate_exit_win_rate: number;
  total_debate_contribution: number;
  database_stats: {
    trade_records: number;
    attribution_records: number;
    database_size_mb: number;
  };
}

export interface HistoricalContributionPoint {
  timestamp: string;
  debate_contribution_pct: number;
  win_rate: number;
  utilization_pct: number;
}

export interface HistoricalContributionResponse {
  points: HistoricalContributionPoint[];
}
