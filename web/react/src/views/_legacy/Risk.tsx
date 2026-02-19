import React from "react";
import { RefreshCw, Shield } from 'lucide-react';
import { useApiData } from "../hooks/useApiData";
import { useMeridSocket } from "../hooks/useMeridSocket";
import { API_ENDPOINTS, STATUS_TYPES, DEFAULTS } from "../config/constants";
import { formatCurrency, formatPercent, formatDateTime } from "../utils/formatters";
import MetricCard from "../components/MetricCard";
import StatusIndicator from "../components/StatusIndicator";
import DataTableEnhanced from "../components/DataTableEnhanced";
import ErrorAlert from "../components/ErrorAlert";
import EmptyState from "../components/EmptyState";
import { StubBadge } from "../components/DataGuard";
import { DataAgeBadge } from "../components/DataAgeBadge";
import { RiskStatus } from "../types/risk";
import { useFeatureFlags } from "../config/featureFlags";

interface RiskMetrics {
  marginUsed: number;
  marginAvailable: number;
  marginCallLevel: number;
  portfolioValue: number;
  totalExposure: number;
  var95: number;
  var99: number;
  maxDrawdown: number;
  sharpeRatio: number;
  leverage: number;
}

interface RiskAlert {
  id: string;
  level: "low" | "medium" | "high" | "critical";
  type: string;
  message: string;
  timestamp: string;
  resolved: boolean;
}

interface SystemHealth {
  component: string;
  status: "online" | "offline" | "degraded";
  lastCheck: string;
  latency: number;
  errorRate: number;
  uptime: number;
}

interface PositionLimit {
  symbol: string;
  currentSize: number;
  maxLimit: number;
  utilizationPercent: number;
  status: "normal" | "warning" | "critical";
}

export default function Risk() {
  const { kalshiOnly } = useFeatureFlags();

  // Fetch risk metrics (skip in Kalshi mode)
  const { data: riskMetrics, loading: riskLoading, error: riskError, refetch: refetchRisk, lastUpdated: riskUpdated, rawResponse: riskRaw, isStub: riskIsStub } = useApiData<RiskMetrics>(
    kalshiOnly ? '' : API_ENDPOINTS.RISK_METRICS,
    { pollingInterval: kalshiOnly ? 0 : DEFAULTS.POLLING_INTERVALS.RISK }
  );

  // Fetch risk alerts
  const { data: alerts } = useApiData<RiskAlert[]>(
    kalshiOnly ? '' : API_ENDPOINTS.RISK_ALERTS,
    { pollingInterval: kalshiOnly ? 0 : DEFAULTS.POLLING_INTERVALS.RISK_ALERTS }
  );

  // Fetch system health
  const { data: systemHealth } = useApiData<SystemHealth[]>(
    kalshiOnly ? '' : API_ENDPOINTS.SYSTEM_HEALTH,
    { pollingInterval: kalshiOnly ? 0 : DEFAULTS.POLLING_INTERVALS.SYSTEM_HEALTH }
  );

  // Fetch position limits
  const { data: positionLimits } = useApiData<PositionLimit[]>(
    kalshiOnly ? '' : API_ENDPOINTS.RISK_POSITION_LIMITS,
    { pollingInterval: kalshiOnly ? 0 : DEFAULTS.POLLING_INTERVALS.RISK_POSITION_LIMITS }
  );

  const isLoading = riskLoading && !riskMetrics && !alerts && !systemHealth;

  // WebSocket for real-time updates
  const { socket, connected } = useMeridSocket();

  React.useEffect(() => {
    if (socket && connected) {
      const handleRiskUpdate = () => {
        // This would trigger a refetch of risk data
      };

      socket.on("risk_update", handleRiskUpdate);

      return () => {
        socket.off("risk_update", handleRiskUpdate);
      };
    }
  }, [socket, connected]);

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

  const getMarginStatus = (marginUsed: number, marginCallLevel: number): RiskStatus => {
    if (marginUsed >= marginCallLevel) return "BAD";
    if (marginUsed >= marginCallLevel * 0.8) return "WARNING";
    return "GOOD";
  };

  const getVaRStatus = (var95: number, portfolioValue: number): RiskStatus => {
    const varPercent = Math.abs(var95) / portfolioValue;
    if (varPercent >= 0.05) return "BAD";
    if (varPercent >= 0.03) return "WARNING";
    return "GOOD";
  };

  // Crypto-only view - show message in Kalshi mode (after all hooks)
  if (kalshiOnly) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <Shield className="w-12 h-12 text-slate-600 mx-auto mb-4" />
          <h2 className="text-xl font-semibold text-slate-400 mb-2">Crypto-Only View</h2>
          <p className="text-slate-500">This view is not available in Kalshi mode.</p>
        </div>
      </div>
    );
  }

  const getLeverageStatus = (leverage: number): RiskStatus => {
    if (leverage >= 5) return "BAD";
    if (leverage >= 3) return "WARNING";
    return "GOOD";
  };

  const getAlertColor = (level: string) => {
    switch (level) {
      case "critical": return "text-red-500";
      case "high": return "text-orange-500";
      case "medium": return "text-amber-500";
      case "low": return "text-blue-500";
      default: return "text-slate-500";
    }
  };

  const getHealthStatus = (status: string): keyof typeof STATUS_TYPES => {
    switch (status.toLowerCase()) {
      case "online":
        return "ONLINE";
      case "degraded":
        return "DEGRADED";
      case "offline":
        return "OFFLINE";
      default:
        return "WARNING";
    }
  };

  const alertColumns = [
    {
      key: "timestamp" as keyof RiskAlert,
      label: "Time",
      sortable: true,
      render: (value: unknown) => formatDateTime(String(value)),
    },
    {
      key: "level" as keyof RiskAlert,
      label: "Level",
      render: (value: unknown) => (
        <span className={`px-2 py-1 rounded text-xs font-medium ${getAlertColor(String(value))}`}>
          {String(value).toUpperCase()}
        </span>
      ),
    },
    {
      key: "type" as keyof RiskAlert,
      label: "Type",
      render: (value: unknown) => (
        <span className="text-slate-300">{String(value)}</span>
      ),
    },
    {
      key: "message" as keyof RiskAlert,
      label: "Message",
      render: (value: unknown) => (
        <span className="text-slate-300 text-sm">{String(value)}</span>
      ),
    },
    {
      key: "resolved" as keyof RiskAlert,
      label: "Status",
      render: (value: unknown) => (
        <span className={`px-2 py-1 rounded text-xs font-medium ${
          value ? "bg-green-500/20 text-green-500" : "bg-red-500/20 text-red-500"
        }`}>
          {value ? "Resolved" : "Active"}
        </span>
      ),
    },
  ];

  const healthColumns = [
    {
      key: "component" as keyof SystemHealth,
      label: "Component",
      sortable: true,
    },
    {
      key: "status" as keyof SystemHealth,
      label: "Status",
      render: (value: unknown) => (
        <StatusIndicator status={getHealthStatus(String(value))} showText />
      ),
    },
    {
      key: "lastCheck" as keyof SystemHealth,
      label: "Last Check",
      sortable: true,
      render: (value: unknown) => formatDateTime(String(value)),
    },
    {
      key: "latency" as keyof SystemHealth,
      label: "Latency",
      sortable: true,
      render: (value: unknown) => {
        const v = Number(value);
        return (
          <span className={v >= 1000 ? "text-red-500" : v >= 500 ? "text-amber-500" : "text-green-500"}>
            {v}ms
          </span>
        );
      },
    },
    {
      key: "errorRate" as keyof SystemHealth,
      label: "Error Rate",
      sortable: true,
      render: (value: unknown) => {
        const v = Number(value);
        return (
          <span className={v >= 5 ? "text-red-500" : v >= 1 ? "text-amber-500" : "text-green-500"}>
            {v}%
          </span>
        );
      },
    },
    {
      key: "uptime" as keyof SystemHealth,
      label: "Uptime",
      sortable: true,
      render: (value: unknown) => {
        const v = Number(value);
        return (
          <span className={v >= 99.9 ? "text-green-500" : v >= 99 ? "text-amber-500" : "text-red-500"}>
            {formatPercent(v)}
          </span>
        );
      },
    },
  ];

  const limitColumns = [
    {
      key: "symbol" as keyof PositionLimit,
      label: "Symbol",
      sortable: true,
    },
    {
      key: "currentSize" as keyof PositionLimit,
      label: "Current Size",
      sortable: true,
    },
    {
      key: "maxLimit" as keyof PositionLimit,
      label: "Max Limit",
      sortable: true,
    },
    {
      key: "utilizationPercent" as keyof PositionLimit,
      label: "Utilization",
      sortable: true,
      render: (value: unknown) => {
        const v = Number(value);
        return (
          <div className="flex items-center gap-2">
            <div className="w-16 bg-slate-700 rounded-full h-2">
              <div
                className={`h-2 rounded-full ${
                  v >= 90 ? "bg-red-500" : v >= 75 ? "bg-amber-500" : "bg-green-500"
                }`}
                style={{ width: `${v}%` }}
              />
            </div>
            <span className={`text-sm ${
              v >= 90 ? "text-red-500" : v >= 75 ? "text-amber-500" : "text-green-500"
            }`}>
              {formatPercent(v)}
            </span>
          </div>
        );
      },
    },
    {
      key: "status" as keyof PositionLimit,
      label: "Status",
      render: (value: unknown) => (
        <StatusIndicator status={convertRiskStatus(getLeverageStatus(parseFloat(String(value))))} showText />
      ),
    },
  ];

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="w-6 h-6 text-blue-400 animate-spin" />
        <span className="ml-3 text-slate-400">Loading risk dashboard…</span>
      </div>
    );
  }

  if (riskError && !riskMetrics) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-white">Risk & Health</h1>
        <ErrorAlert message="Failed to load risk metrics" onRetry={refetchRisk} />
      </div>
    );
  }

  if (!riskMetrics && !alerts && !systemHealth) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-white">Risk & Health</h1>
        <EmptyState title="No risk data" message="Risk metrics will appear here once the system is active." />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold text-white">Risk & Health</h1>
          {riskIsStub && <StubBadge data={riskRaw} />}
        </div>
        <div className="flex items-center gap-3">
          <DataAgeBadge lastUpdated={riskUpdated} />
          <StatusIndicator status={connected ? "ONLINE" : "OFFLINE"} showText />
          <span className="text-sm text-slate-400">Live Monitoring</span>
        </div>
      </div>

      {/* Risk Metrics Cards */}
      {riskMetrics && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <MetricCard
            label="Margin Used"
            value={formatPercent(riskMetrics.marginUsed)}
            status={convertRiskStatus(getMarginStatus(riskMetrics.marginUsed, riskMetrics.marginCallLevel))}
          />
          <MetricCard
            label="Available Margin"
            value={formatCurrency(riskMetrics.marginAvailable)}
            status={riskMetrics.marginAvailable > 10000 ? "GOOD" : "WARNING"}
          />
          <MetricCard
            label="95% VaR"
            value={formatCurrency(Math.abs(riskMetrics.var95))}
            status={convertRiskStatus(getVaRStatus(riskMetrics.var95, riskMetrics.portfolioValue))}
          />
          <MetricCard
            label="Leverage"
            value={`${riskMetrics.leverage}x`}
            status={convertRiskStatus(getLeverageStatus(riskMetrics.leverage))}
          />
        </div>
      )}

      {/* Additional Risk Metrics */}
      {riskMetrics && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <MetricCard
            label="Portfolio Value"
            value={formatCurrency(riskMetrics.portfolioValue)}
            status="GOOD"
          />
          <MetricCard
            label="Total Exposure"
            value={formatCurrency(riskMetrics.totalExposure)}
            status="WARNING"
          />
          <MetricCard
            label="Max Drawdown"
            value={formatPercent(riskMetrics.maxDrawdown)}
            status={riskMetrics.maxDrawdown <= 10 ? "GOOD" : "BAD"}
          />
          <MetricCard
            label="Sharpe Ratio"
            value={riskMetrics.sharpeRatio}
            status={riskMetrics.sharpeRatio >= 1.5 ? "GOOD" : riskMetrics.sharpeRatio >= 1 ? "WARNING" : "BAD"}
          />
        </div>
      )}

      {/* Risk Alerts */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">
          Risk Alerts ({alerts?.filter(a => !a.resolved).length || 0} active)
        </h2>
        <DataTableEnhanced
          data={alerts || []}
          columns={alertColumns}
          pageSize={10}
          showPagination
          showFilter
        />
      </div>

      {/* System Health */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">System Health</h2>
        <DataTableEnhanced
          data={systemHealth || []}
          columns={healthColumns}
          pageSize={10}
          showPagination
          showFilter
        />
      </div>

      {/* Position Limits */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Position Limits</h2>
        <DataTableEnhanced
          data={positionLimits || []}
          columns={limitColumns}
          pageSize={15}
          showPagination
          showFilter
        />
      </div>
    </div>
  );
}
