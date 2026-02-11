import React, { useState } from "react";
import { RefreshCw } from 'lucide-react';
import { useApiData } from "../hooks/useApiData";
import { API_ENDPOINTS, STATUS_TYPES, DEFAULTS } from "../config/constants";
import { formatDateTime, formatPercent } from "../utils/formatters";
import MetricCard from "../components/MetricCard";
import StatusIndicator from "../components/StatusIndicator";
import DataTableEnhanced from "../components/DataTableEnhanced";
import ErrorAlert from "../components/ErrorAlert";
import EmptyState from "../components/EmptyState";
import { RiskStatus } from "../types/risk";

interface ApiStatus {
  id: string;
  name: string;
  category: "market_data" | "trading" | "infrastructure" | "comms" | "onchain_intel" | "prediction_markets";
  status: "online" | "offline" | "degraded";
  lastCheck: string;
  latency: number;
  errorRate: number;
  uptime: number;
  configCompleteness: number;
  endpoint: string;
  method: string;
  version: string;
  dependencies?: string[];
}

interface ApiMetrics {
  totalApis: number;
  onlineApis: number;
  offlineApis: number;
  degradedApis: number;
  avgLatency: number;
  errorRate: number;
  overallHealth: number;
}

export default function ApiDashboard() {
  const [selectedCategory, setSelectedCategory] = useState<string>("all");
  const [selectedApi, setSelectedApi] = useState<ApiStatus | null>(null);
  const [showDetails, setShowDetails] = useState(false);

  // Fetch API status data
  const { data: apiStatus, loading: statusLoading, error: statusError, refetch: refetchStatus } = useApiData<ApiStatus[]>(
    API_ENDPOINTS.API_STATUS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.API_STATUS }
  );

  // Fetch API metrics
  const { data: metrics, loading: metricsLoading } = useApiData<ApiMetrics>(
    API_ENDPOINTS.API_METRICS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SYSTEM_HEALTH }
  );

  const isLoading = statusLoading && metricsLoading && !apiStatus && !metrics;

  const filteredApis = React.useMemo(() => {
    if (!apiStatus) return [];
    
    return apiStatus.filter(api => {
      const categoryMatch = selectedCategory === "all" || api.category === selectedCategory;
      return categoryMatch;
    });
  }, [apiStatus, selectedCategory]);

  const categories = React.useMemo(() => {
    if (!apiStatus) return [];
    return [...new Set(apiStatus.map(api => api.category))];
  }, [apiStatus]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="w-6 h-6 text-blue-400 animate-spin" />
        <span className="ml-3 text-slate-400">Loading API dashboard…</span>
      </div>
    );
  }

  if (statusError && !apiStatus) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-white">API Dashboard</h1>
        <ErrorAlert message="Failed to load API status" onRetry={refetchStatus} />
      </div>
    );
  }

  if (apiStatus && apiStatus.length === 0) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-white">API Dashboard</h1>
        <EmptyState title="No APIs configured" message="API integrations will appear here once configured." />
      </div>
    );
  }

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

  const getApiStatus = (status: string): RiskStatus => {
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

  const getLatencyStatus = (latency: number): RiskStatus => {
    if (latency <= 200) return "GOOD";
    if (latency <= 500) return "WARNING";
    return "BAD";
  };

  const getCategoryColor = (category: string) => {
    const colors = {
      "market_data": "text-green-500",
      "trading": "text-blue-500",
      "infrastructure": "text-purple-500",
      "comms": "text-cyan-500",
      "onchain_intel": "text-orange-500",
      "prediction_markets": "text-pink-500",
    };
    return colors[category as keyof typeof colors] || "text-slate-500";
  };

  const getCategoryIcon = (category: string) => {
    const icons = {
      "market_data": "📊",
      "trading": "💹",
      "infrastructure": "🏗️",
      "comms": "📡",
      "onchain_intel": "⛓️",
      "prediction_markets": "🎯",
    };
    return icons[category as keyof typeof icons] || "🔧";
  };

  const getLatencyColor = (latency: number) => {
    if (latency >= 1000) return "text-red-500";
    if (latency >= 500) return "text-amber-500";
    return "text-green-500";
  };

  const getErrorRateColor = (errorRate: number) => {
    if (errorRate >= 5) return "text-red-500";
    if (errorRate >= 2) return "text-amber-500";
    return "text-green-500";
  };

  const getUptimeColor = (uptime: number) => {
    if (uptime >= 99.9) return "text-green-500";
    if (uptime >= 99) return "text-amber-500";
    return "text-red-500";
  };

  const getConfigColor = (completeness: number) => {
    if (completeness >= 90) return "text-green-500";
    if (completeness >= 75) return "text-amber-500";
    return "text-red-500";
  };

  const columns = [
    {
      key: "name" as keyof ApiStatus,
      label: "API Name",
      sortable: true,
      render: (value: string, row: ApiStatus) => (
        <button type="button"
          onClick={() => {
            setSelectedApi(row);
            setShowDetails(true);
          }}
          className="text-left text-blue-400 hover:text-blue-300"
        >
          {value}
        </button>
      ),
    },
    {
      key: "category" as keyof ApiStatus,
      label: "Category",
      sortable: true,
      render: (value: string) => (
        <div className="flex items-center gap-2">
          <span>{getCategoryIcon(value)}</span>
          <span className={`px-2 py-1 rounded text-xs font-medium ${getCategoryColor(value)}`}>
            {value.replace("_", " ").toUpperCase()}
          </span>
        </div>
      ),
    },
    {
      key: "status" as keyof ApiStatus,
      label: "Status",
      render: (_value: string, api: ApiStatus) => (
        <StatusIndicator status={convertRiskStatus(getApiStatus(api.status))} showText />
      ),
    },
    {
      key: "endpoint" as keyof ApiStatus,
      label: "Endpoint",
      render: (value: string) => (
        <code className="text-xs bg-slate-800 px-2 py-1 rounded text-slate-300">
          {value}
        </code>
      ),
    },
    {
      key: "method" as keyof ApiStatus,
      label: "Method",
      sortable: true,
      render: (value: string) => (
        <span className={`px-2 py-1 rounded text-xs font-medium ${
          value === "GET" ? "bg-green-500/20 text-green-500" : "bg-blue-500/20 text-blue-500"
        }`}>
          {value}
        </span>
      ),
    },
    {
      key: "latency" as keyof ApiStatus,
      label: "Latency",
      sortable: true,
      render: (value: number) => (
        <span className={getLatencyColor(value)}>
          {value}ms
        </span>
      ),
    },
    {
      key: "lastCheck" as keyof ApiStatus,
      label: "Last Check",
      sortable: true,
      render: (value: string) => formatDateTime(value),
    },
    {
      key: "uptime" as keyof ApiStatus,
      label: "Uptime",
      sortable: true,
      render: (value: number) => (
        <span className={getUptimeColor(value)}>
          {formatPercent(value)}
        </span>
      ),
    },
    {
      key: "errorRate" as keyof ApiStatus,
      label: "Error Rate",
      sortable: true,
      render: (value: number) => (
        <span className={getErrorRateColor(value)}>
          {formatPercent(value)}
        </span>
      ),
    },
    {
      key: "version" as keyof ApiStatus,
      label: "Version",
      sortable: true,
      render: (value: string) => (
        <span className="text-xs bg-slate-800 px-2 py-1 rounded text-slate-400">
          {value}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">API Dashboard</h1>
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-400">
            {filteredApis.length} APIs
          </span>
        </div>
      </div>

      {/* Overall Metrics */}
      {metrics && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <MetricCard
            label="Total APIs"
            value={metrics.totalApis}
            status={convertRiskStatus("GOOD")}
          />
          <MetricCard
            label="Online APIs"
            value={metrics.onlineApis}
            delta={metrics.onlineApis - metrics.offlineApis}
            status={convertRiskStatus(metrics.onlineApis === metrics.totalApis ? "GOOD" : "WARNING")}
          />
          <MetricCard
            label="Avg Latency"
            value={`${metrics.avgLatency}ms`}
            status={convertRiskStatus(getLatencyStatus(metrics.avgLatency))}
          />
          <MetricCard
            label="Overall Health"
            value={formatPercent(metrics.overallHealth)}
            status={convertRiskStatus(metrics.overallHealth >= 95 ? "GOOD" : metrics.overallHealth >= 80 ? "WARNING" : "BAD")}
          />
        </div>
      )}

      {/* Category Filter */}
      <div className="flex items-center gap-4">
        <label className="text-sm font-medium text-slate-400">Filter by Category:</label>
        <select aria-label="Filter by Category:"
          id="api-category-filter"
          name="categoryFilter"
          value={selectedCategory}
          onChange={(e) => setSelectedCategory(e.target.value)}
          title="Filter by API category"
          className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white"
        >
          <option value="all">All Categories</option>
          {categories.map(category => (
            <option key={category} value={category}>
              {category.replace("_", " ").toUpperCase()}
            </option>
          ))}
        </select>
      </div>

      {/* API Status Table */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">API Status</h2>
        <DataTableEnhanced
          data={filteredApis}
          columns={columns}
          pageSize={15}
          showPagination
          showFilter
        />
      </div>

      {/* API Details Modal */}
      {showDetails && selectedApi && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-slate-800 rounded-xl border border-slate-700 p-6 max-w-2xl max-h-[80vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-semibold text-white">API Details</h3>
              <button type="button"
                onClick={() => setShowDetails(false)}
                className="text-slate-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <h4 className="text-sm font-medium text-slate-400">Name</h4>
                <p className="text-white">{selectedApi.name}</p>
              </div>

              <div>
                <h4 className="text-sm font-medium text-slate-400">Category</h4>
                <p className="text-white">{selectedApi.category.replace("_", " ").toUpperCase()}</p>
              </div>

              <div>
                <h4 className="text-sm font-medium text-slate-400">Status</h4>
                <StatusIndicator status={convertRiskStatus(getApiStatus(selectedApi.status))} showText />
              </div>

              <div>
                <h4 className="text-sm font-medium text-slate-400">Endpoint</h4>
                <code className="text-xs bg-slate-700 px-2 py-1 rounded text-slate-300">
                  {selectedApi.endpoint}
                </code>
              </div>

              <div>
                <h4 className="text-sm font-medium text-slate-400">Method</h4>
                <span className={`px-2 py-1 rounded text-xs font-medium ${
                  selectedApi.method === "GET" ? "bg-green-500/20 text-green-500" : "bg-blue-500/20 text-blue-500"
                }`}>
                  {selectedApi.method}
                </span>
              </div>

              <div>
                <h4 className="text-sm font-medium text-slate-400">Version</h4>
                <span className="text-xs bg-slate-700 px-2 py-1 rounded text-slate-400">
                  {selectedApi.version}
                </span>
              </div>

              <div>
                <h4 className="text-sm font-medium text-slate-400">Performance</h4>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <span className="text-slate-400">Latency:</span>
                    <span className={getLatencyColor(selectedApi.latency)}>
                      {selectedApi.latency}ms
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400">Error Rate:</span>
                    <span className={getErrorRateColor(selectedApi.errorRate)}>
                      {formatPercent(selectedApi.errorRate)}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400">Uptime:</span>
                    <span className={getUptimeColor(selectedApi.uptime)}>
                      {formatPercent(selectedApi.uptime)}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-400">Config Completeness:</span>
                    <span className={getConfigColor(selectedApi.configCompleteness)}>
                      {selectedApi.configCompleteness}%
                    </span>
                  </div>
                </div>
              </div>

              <div>
                <h4 className="text-sm font-medium text-slate-400">Last Check</h4>
                <p className="text-white">{formatDateTime(selectedApi.lastCheck)}</p>
              </div>

              {selectedApi.dependencies && selectedApi.dependencies.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-slate-400">Dependencies</h4>
                  <div className="space-y-2">
                    {selectedApi.dependencies.map((dep, index) => (
                      <div key={index} className="text-xs bg-slate-700 px-2 py-1 rounded text-slate-300">
                        {dep}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
