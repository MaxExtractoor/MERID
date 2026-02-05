import React, { useState } from "react";
import { useApiData } from "../hooks/useApiData";
import { useMeridSocket } from "../hooks/useMeridSocket";
import { API_ENDPOINTS, STATUS_TYPES } from "../config/constants";
import { formatCurrency, formatPercent, formatDateTime } from "../utils/formatters";
import MetricCard from "../components/MetricCard";
import StatusIndicator from "../components/StatusIndicator";
import DataTableEnhanced from "../components/DataTableEnhanced";
import SwarmPanel from "../components/SwarmPanel";
import ExplainabilityPanel from "../components/ExplainabilityPanel";
import { RiskStatus } from "../types/risk";
import { LiveAgentHealthPanel } from "./LiveAgentHealthPanel";
import { Activity, HeartPulse, Brain } from "lucide-react";

interface Agent {
  id: string;
  name: string;
  role: string;
  status: "online" | "offline" | "degraded";
  confidence: number;
  pnl: number;
  winRate: number;
  totalTrades: number;
  lastDecision?: string;
  lastDecisionTime?: string;
  charter?: string;
}

interface AgentDetail {
  id: string;
  name: string;
  role: string;
  status: "online" | "offline" | "degraded";
  confidence: number;
  pnl: number;
  winRate: number;
  totalTrades: number;
  lastDecision: string;
  lastDecisionTime: string;
  charter: string;
  metrics: {
    avgTradeSize: number;
    avgHoldTime: number;
    sharpeRatio: number;
    maxDrawdown: number;
    dailyPnl: number;
    weeklyPnl: number;
    monthlyPnl: number;
  };
  recentDecisions: Array<{
    timestamp: string;
    decision: string;
    confidence: number;
    outcome?: string;
    pnl?: number;
  }>;
}

export default function Agents() {
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [showDetail, setShowDetail] = useState(false);
  const [activeTab, setActiveTab] = useState<"fleet" | "health" | "explainability">("fleet");

  // Fetch agents data
  const { data: agents } = useApiData<Agent[]>(
    API_ENDPOINTS.AGENTS,
    { pollingInterval: 10000 }
  );

  // WebSocket for real-time updates
  const { socket, connected } = useMeridSocket();

  React.useEffect(() => {
    if (socket && connected) {
      const handleAgentUpdate = (data: any) => {
        // This would trigger a refetch of agents
        console.log("Agent update:", data);
      };

      socket.on("agent_update", handleAgentUpdate);

      return () => {
        socket.off("agent_update", handleAgentUpdate);
      };
    }
  }, [socket, connected]);

  // Fetch agent detail when selected
  const { data: agentDetail } = useApiData<AgentDetail>(
    selectedAgent ? API_ENDPOINTS.AGENT_DETAIL(selectedAgent.id) : "",
    { enabled: !!selectedAgent }
  );

  // Early return if no agents data
  if (!agents || agents.length === 0) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold text-white">Bots & Agents</h1>
          <div className="flex items-center gap-4">
            <StatusIndicator status={connected ? "ONLINE" : "OFFLINE"} showText />
            <span className="text-sm text-slate-400">Live Updates</span>
          </div>
        </div>
        <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
          <div className="text-center py-8">
            <div className="text-slate-400">No agents available</div>
          </div>
        </div>
      </div>
    );
  }

  // From here, agents is guaranteed non-null and non-empty
  const safeAgents = agents;

  const handleAgentClick = (agent: Agent) => {
    setSelectedAgent(agent);
  };

  const convertRiskStatus = (status: RiskStatus): keyof typeof STATUS_TYPES => {
    switch (status) {
      case "GOOD":
        return "GOOD";
      case "WARNING":
        return "WARNING";
      case "BAD":
        return "BAD";
      case "UNKNOWN":
      default:
        return "WARNING";
    }
  };

  const getAgentStatus = (agent: Agent | AgentDetail): RiskStatus => {
    const status = agent.status;
    switch (status) {
      case "online":
        return "GOOD";
      case "offline":
        return "BAD";
      case "degraded":
        return "WARNING";
      default:
        return "UNKNOWN";
    }
  };

  const getPnLStatus = (pnl: number): RiskStatus => {
    return pnl >= 0 ? "GOOD" : "BAD";
  };

  const getWinRateStatus = (winRate: number): RiskStatus => {
    if (winRate >= 0.6) return "GOOD";
    if (winRate >= 0.4) return "WARNING";
    return "BAD";
  };

  const getConfidenceStatus = (confidence: number): RiskStatus => {
    if (confidence >= 0.8) return "GOOD";
    if (confidence >= 0.5) return "WARNING";
    return "BAD";
  };

  const getSharpeStatus = (sharpe: number): RiskStatus => {
    if (sharpe >= 1.5) return "GOOD";
    if (sharpe >= 1.0) return "WARNING";
    return "BAD";
  };

  const getDrawdownStatus = (drawdown: number): RiskStatus => {
    if (drawdown <= 10) return "GOOD";
    if (drawdown <= 20) return "WARNING";
    return "BAD";
  };

  const getRoleColor = (role: string) => {
    const colors = {
      "trader": "text-blue-500",
      "analyst": "text-purple-500",
      "risk_manager": "text-amber-500",
      "market_maker": "text-green-500",
      "arbitrage": "text-cyan-500",
      "researcher": "text-pink-500",
    };
    return colors[role as keyof typeof colors] || "text-slate-500";
  };

  const columns = [
    {
      key: "name" as keyof Agent,
      label: "Agent Name",
      sortable: true,
      render: (value: string, row: Agent) => (
        <button
          onClick={() => handleAgentClick(row)}
          className="text-blue-400 hover:text-blue-300 font-medium text-left"
        >
          {value}
        </button>
      ),
    },
    {
      key: "role" as keyof Agent,
      label: "Role",
      sortable: true,
      render: (value: string) => (
        <span className={`px-2 py-1 rounded text-xs font-medium ${getRoleColor(value)}`}>
          {value.replace("_", " ").toUpperCase()}
        </span>
      ),
    },
    {
      key: "status" as keyof Agent,
      label: "Status",
      render: (_value: string, row: Agent) => (
        <StatusIndicator status={convertRiskStatus(getAgentStatus(row))} showText />
      ),
    },
    {
      key: "confidence" as keyof Agent,
      label: "Confidence",
      sortable: true,
      render: (value: number, _row: Agent) => (
        <div className="flex items-center gap-2">
          <div className="w-16 bg-slate-700 rounded-full h-2">
            <div
              className={`h-2 rounded-full ${
                value >= 80 ? "bg-green-500" : value >= 60 ? "bg-amber-500" : "bg-red-500"
              }`}
              style={{ width: `${value}%` }}
            />
          </div>
          <span className="text-sm">{value}%</span>
        </div>
      ),
    },
    {
      key: "pnl" as keyof Agent,
      label: "P&L",
      sortable: true,
      render: (value: number) => (
        <span className={value >= 0 ? "text-green-500" : "text-red-500"}>
          {formatCurrency(value)}
        </span>
      ),
    },
    {
      key: "winRate" as keyof Agent,
      label: "Win Rate",
      sortable: true,
      render: (value: number) => (
        <span className={value >= 0.6 ? "text-green-500" : value >= 0.4 ? "text-amber-500" : "text-red-500"}>
          {formatPercent(value)}
        </span>
      ),
    },
    {
      key: "totalTrades" as keyof Agent,
      label: "Total Trades",
      sortable: true,
      render: (value: number) => value.toLocaleString(),
    },
    {
      key: "lastDecisionTime" as keyof Agent,
      label: "Last Decision",
      sortable: true,
      render: (value: string) => value ? formatDateTime(value) : "Never",
    },
  ];

  const detailColumns = [
    {
      key: "timestamp" as keyof AgentDetail["recentDecisions"][0],
      label: "Time",
      sortable: true,
      render: (value: string) => formatDateTime(value),
    },
    {
      key: "decision" as keyof AgentDetail["recentDecisions"][0],
      label: "Decision",
      sortable: true,
    },
    {
      key: "confidence" as keyof AgentDetail["recentDecisions"][0],
      label: "Confidence",
      sortable: true,
      render: (value: number) => (
        <span className={value >= 0.8 ? "text-green-500" : value >= 0.5 ? "text-amber-500" : "text-red-500"}>
          {formatPercent(value)}
        </span>
      ),
    },
    {
      key: "outcome" as keyof AgentDetail["recentDecisions"][0],
      label: "Outcome",
      sortable: true,
      render: (value: string) => (
        <span className={`px-2 py-1 rounded text-xs font-medium ${
          value === "profit" ? "bg-green-500/20 text-green-500" : 
          value === "loss" ? "bg-red-500/20 text-red-500" : 
          "bg-slate-500/20 text-slate-500"
        }`}>
          {value?.toUpperCase() || "PENDING"}
        </span>
      ),
    },
    {
      key: "pnl" as keyof AgentDetail["recentDecisions"][0],
      label: "P&L",
      render: (value?: number) => value !== undefined ? (
        <span className={value >= 0 ? "text-green-500" : "text-red-500"}>
          {formatCurrency(value)}
        </span>
      ) : "-",
    },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Bots & Agents</h1>
        <div className="flex items-center gap-4">
          <StatusIndicator status={connected ? "ONLINE" : "OFFLINE"} showText />
          <span className="text-sm text-slate-400">Live Updates</span>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-slate-800">
        <div className="flex gap-4">
          <button
            onClick={() => setActiveTab("fleet")}
            className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === "fleet"
                ? "border-blue-500 text-blue-400"
                : "border-transparent text-slate-400 hover:text-slate-300"
            }`}
          >
            <Activity className="w-4 h-4" />
            Fleet
          </button>
          <button
            onClick={() => setActiveTab("health")}
            className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === "health"
                ? "border-blue-500 text-blue-400"
                : "border-transparent text-slate-400 hover:text-slate-300"
            }`}
          >
            <HeartPulse className="w-4 h-4" />
            Health
          </button>
          <button
            onClick={() => setActiveTab("explainability")}
            className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === "explainability"
                ? "border-blue-500 text-blue-400"
                : "border-transparent text-slate-400 hover:text-slate-300"
            }`}
          >
            <Brain className="w-4 h-4" />
            Explainability
          </button>
        </div>
      </div>

      {/* Tab Content */}
      {activeTab === "health" ? (
        <LiveAgentHealthPanel />
      ) : activeTab === "explainability" ? (
        <ExplainabilityPanel />
      ) : (
        <>
          {/* Swarm Intelligence Panel */}
          <SwarmPanel />

          {/* Summary Cards */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <MetricCard
              label="Total Agents"
              value={safeAgents.length}
              status="GOOD"
            />
            <MetricCard
              label="Active Agents"
              value={safeAgents.filter(a => a.status === "online").length}
              delta={safeAgents.filter(a => a.status === "online").length - safeAgents.filter(a => a.status === "offline").length}
              status="GOOD"
            />
            <MetricCard
              label="Total P&L"
              value={safeAgents.reduce((sum, a) => sum + a.pnl, 0)}
              status={convertRiskStatus(getPnLStatus(safeAgents.reduce((sum, a) => sum + a.pnl, 0)))}
            />
            <MetricCard
              label="Avg Confidence"
              value={safeAgents.reduce((sum, a) => sum + a.confidence, 0) / safeAgents.length}
              deltaPercent={5.2}
              status={convertRiskStatus(getConfidenceStatus(safeAgents.reduce((sum, a) => sum + a.confidence, 0) / safeAgents.length))}
            />
          </div>

          {/* Agents Table */}
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
            <h2 className="text-lg font-semibold text-white mb-4">Agent Fleet</h2>
            <DataTableEnhanced
              data={safeAgents}
              columns={columns}
              pageSize={15}
              showPagination
              showFilter
            />
          </div>
        </>
      )}

      {/* Agent Detail Modal */}
      {showDetail && selectedAgent && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-slate-800 rounded-xl border border-slate-700 p-6 max-w-4xl max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold text-white">{selectedAgent.name}</h2>
              <button
                onClick={() => setShowDetail(false)}
                className="text-slate-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            {!agentDetail ? (
              <div className="text-center py-8">
                <div className="text-slate-400">Loading agent details...</div>
              </div>
            ) : (
              <div className="space-y-6">
                {/* Overview */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <MetricCard
                    label="Status"
                    value={agentDetail.status}
                    status={convertRiskStatus(getAgentStatus(agentDetail))}
                  />
                  <MetricCard
                    label="Confidence"
                    value={`${agentDetail.confidence ?? 0}%`}
                    status={convertRiskStatus(getConfidenceStatus(agentDetail.confidence ?? 0))}
                  />
                  <MetricCard
                    label="P&L"
                    value={agentDetail.pnl ?? 0}
                    status={convertRiskStatus(getPnLStatus(agentDetail.pnl ?? 0))}
                  />
                  <MetricCard
                    label="Win Rate"
                    value={agentDetail.winRate ?? 0}
                    status={convertRiskStatus(getWinRateStatus(agentDetail.winRate ?? 0))}
                  />
                </div>

                {/* Performance Metrics */}
                <div>
                  <h3 className="text-lg font-semibold text-white mb-4">Performance Metrics</h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <MetricCard
                      label="Avg Trade Size"
                      value={formatCurrency(agentDetail.metrics?.avgTradeSize ?? 0)}
                      status="GOOD"
                    />
                    <MetricCard
                      label="Avg Hold Time"
                      value={`${agentDetail.metrics?.avgHoldTime ?? 0}m`}
                      status="GOOD"
                    />
                    <MetricCard
                      label="Sharpe Ratio"
                      value={agentDetail.metrics?.sharpeRatio ?? 0}
                      status={convertRiskStatus(getSharpeStatus(agentDetail.metrics?.sharpeRatio ?? 0))}
                    />
                    <MetricCard
                      label="Max Drawdown"
                      value={formatPercent(agentDetail.metrics?.maxDrawdown ?? 0)}
                      status={convertRiskStatus(getDrawdownStatus(agentDetail.metrics?.maxDrawdown ?? 0))}
                    />
                  </div>
                </div>

                {/* P&L Breakdown */}
                <div>
                  <h3 className="text-lg font-semibold text-white mb-4">P&L Breakdown</h3>
                  <div className="grid grid-cols-3 gap-4">
                    <MetricCard
                      label="Daily P&L"
                      value={agentDetail.metrics?.dailyPnl ?? 0}
                      status={convertRiskStatus(getPnLStatus(agentDetail.metrics?.dailyPnl ?? 0))}
                    />
                    <MetricCard
                      label="Weekly P&L"
                      value={agentDetail.metrics?.weeklyPnl ?? 0}
                      status={convertRiskStatus(getPnLStatus(agentDetail.metrics?.weeklyPnl ?? 0))}
                    />
                    <MetricCard
                      label="Monthly P&L"
                      value={agentDetail.metrics?.monthlyPnl ?? 0}
                      status={convertRiskStatus(getPnLStatus(agentDetail.metrics?.monthlyPnl ?? 0))}
                    />
                  </div>
                </div>

                {/* Recent Decisions */}
                <div>
                  <h3 className="text-lg font-semibold text-white mb-4">Recent Decisions</h3>
                  <DataTableEnhanced
                    data={agentDetail.recentDecisions ?? []}
                    columns={detailColumns}
                    pageSize={10}
                    showPagination
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
