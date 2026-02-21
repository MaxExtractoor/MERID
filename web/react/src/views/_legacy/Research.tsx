import { useState } from "react";
import { RefreshCw } from 'lucide-react';
import { useApiData } from "../hooks/useApiData";
import { API_ENDPOINTS, STATUS_TYPES, DEFAULTS, AUTH_TOKEN_KEY } from "../config/constants";
import { formatCurrency, formatPercent, formatDateTime } from "../utils/formatters";
import MetricCard from "../components/MetricCard";
import DataTableEnhanced from "../components/DataTableEnhanced";
import AnalyticsCharts from "../components/AnalyticsCharts";
import StubGate from "../components/StubGate";
import ErrorAlert from "../components/ErrorAlert";
import { RiskStatus } from "../types/risk";

interface BacktestConfig {
  strategy: string;
  symbols: string[];
  startDate: string;
  endDate: string;
  initialCapital: number;
  commission: number;
  slippage: number;
}

interface BacktestResult {
  id: string;
  strategy: string;
  config: BacktestConfig;
  status: "running" | "completed" | "failed";
  startTime?: string;
  endTime?: string;
  duration?: string;
  equityCurve: Array<{
    date: string;
    equity: number;
    returns: number;
    drawdown: number;
  }>;
  metrics: {
    totalReturn: number;
    annualizedReturn: number;
    sharpeRatio: number;
    maxDrawdown: number;
    winRate: number;
    profitFactor: number;
    totalTrades: number;
    avgTradeDuration: string;
    avgWin: number;
    avgLoss: number;
  };
  trades: Trade[];
}

interface Trade {
  id: string;
  symbol: string;
  side: string;
  entryTime: string;
  exitTime: string;
  entryPrice: number;
  exitPrice: number;
  quantity: number;
  pnl: number;
  pnlPercent: number;
  duration: string;
}

export default function Research() {
  const [showBacktestForm, setShowBacktestForm] = useState(false);
  const [backtestStatus, setBacktestStatus] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [backtestConfig, setBacktestConfig] = useState<BacktestConfig>({
    strategy: "momentum",
    symbols: ["BTC-USD", "ETH-USD"],
    startDate: new Date(Date.now() - 365 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
    endDate: new Date().toISOString().split('T')[0],
    initialCapital: 100000,
    commission: 0.001,
    slippage: 0.0005,
  });

  // Fetch backtest results
  const { data: backtests, loading: backtestsLoading, error: backtestsError, refetch, rawResponse: backtestsRaw } = useApiData<BacktestResult[]>(
    API_ENDPOINTS.BACKTEST_RESULTS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.BACKTESTS }
  );

  if (backtestsLoading && !backtests) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="w-6 h-6 text-blue-400 animate-spin" />
        <span className="ml-3 text-slate-400">Loading research data…</span>
      </div>
    );
  }

  if (backtestsError && !backtests) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-white">Research & Backtesting</h1>
        <ErrorAlert message="Failed to load backtest results" onRetry={refetch} />
      </div>
    );
  }

  const handleRunBacktest = async () => {
    setBacktestStatus(null);
    try {
      const response = await fetch(API_ENDPOINTS.BACKTEST, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localStorage.getItem(AUTH_TOKEN_KEY)}`,
        },
        body: JSON.stringify(backtestConfig),
      });

      if (!response.ok) {
        throw new Error("Failed to start backtest");
      }

      // Reset form and close
      setShowBacktestForm(false);
      setBacktestConfig({
        strategy: "momentum",
        symbols: ["BTC-USD", "ETH-USD"],
        startDate: new Date(Date.now() - 365 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
        endDate: new Date().toISOString().split('T')[0],
        initialCapital: 100000,
        commission: 0.001,
        slippage: 0.0005,
      });

      setBacktestStatus({ type: 'success', message: 'Backtest started successfully' });
      setTimeout(() => setBacktestStatus(null), DEFAULTS.POLLING_INTERVALS.STANDARD);

      // Refetch results
      refetch();
    } catch (error) {
      setBacktestStatus({ type: 'error', message: 'Failed to start backtest. Please try again.' });
    }
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

  const getReturnStatus = (value: number): RiskStatus => {
    return value >= 0 ? "GOOD" : "BAD";
  };

  const getSharpeStatus = (value: number): RiskStatus => {
    if (value >= 1.5) return "GOOD";
    if (value >= 1) return "WARNING";
    return "BAD";
  };

  const getDrawdownStatus = (value: number): RiskStatus => {
    if (value <= 10) return "GOOD";
    if (value <= 20) return "WARNING";
    return "BAD";
  };

  const getWinRateStatus = (value: number): RiskStatus => {
    if (value >= 50) return "GOOD";
    if (value >= 40) return "WARNING";
    return "BAD";
  };

  const getReturnColor = (value: number) => {
    if (value >= 0) return "text-green-500";
    return "text-red-500";
  };

  const getSharpeColor = (value: number) => {
    if (value >= 2) return "text-green-500";
    if (value >= 1) return "text-amber-500";
    return "text-red-500";
  };

  const getDrawdownColor = (value: number) => {
    if (value <= 5) return "text-green-500";
    if (value <= 10) return "text-amber-500";
    return "text-red-500";
  };

  const columns: Array<{
    key: keyof BacktestResult;
    label: string;
    sortable?: boolean;
    render?: (value: unknown, row: BacktestResult) => React.ReactNode;
  }> = [
    {
      key: "strategy" as keyof BacktestResult,
      label: "Strategy",
      sortable: true,
    },
    {
      key: "status" as keyof BacktestResult,
      label: "Status",
      render: (value: unknown) => {
        const status = typeof value === "string" ? value : "";
        return (
        <span className={`px-2 py-1 rounded text-xs font-medium ${
          status === "completed" ? "bg-green-500/20 text-green-500" :
          status === "running" ? "bg-blue-500/20 text-blue-500" :
          "bg-red-500/20 text-red-500"
        }`}>
          {status ? status.toUpperCase() : "UNKNOWN"}
        </span>
        );
      },
    },
    {
      key: "duration" as keyof BacktestResult,
      label: "Duration",
      sortable: true,
      render: (value: unknown) => (typeof value === "string" && value ? value : "-"),
    },
    {
      key: "metrics.totalReturn" as keyof BacktestResult,
      label: "Total Return",
      sortable: true,
      render: (value: unknown) => {
        const numeric = typeof value === "number" ? value : Number(value) || 0;
        return (
        <span className={getReturnColor(numeric)}>
          {formatPercent(numeric)}
        </span>
        );
      },
    },
    {
      key: "metrics.sharpeRatio" as keyof BacktestResult,
      label: "Sharpe Ratio",
      sortable: true,
      render: (value: unknown) => {
        const numeric = typeof value === "number" ? value : Number(value) || 0;
        return (
        <span className={getSharpeColor(numeric)}>
          {numeric.toFixed(2)}
        </span>
        );
      },
    },
    {
      key: "metrics.maxDrawdown" as keyof BacktestResult,
      label: "Max Drawdown",
      sortable: true,
      render: (value: unknown) => {
        const numeric = typeof value === "number" ? value : Number(value) || 0;
        return (
        <span className={getDrawdownColor(numeric)}>
          {formatPercent(numeric)}
        </span>
        );
      },
    },
    {
      key: "startTime" as keyof BacktestResult,
      label: "Start Time",
      sortable: true,
      render: (value: unknown) => {
        const timestamp = typeof value === "string" ? value : "";
        return timestamp ? formatDateTime(timestamp) : "-";
      },
    },
    {
      key: "endTime" as keyof BacktestResult,
      label: "End Time",
      sortable: true,
      render: (value: unknown) => {
        const timestamp = typeof value === "string" ? value : "";
        return timestamp ? formatDateTime(timestamp) : "-";
      },
    },
    {
      key: "metrics.totalTrades" as keyof BacktestResult,
      label: "Total Trades",
      sortable: true,
    },
    {
      key: "metrics.winRate" as keyof BacktestResult,
      label: "Win Rate",
      sortable: true,
      render: (value: unknown) => {
        const numeric = typeof value === "number" ? value : Number(value) || 0;
        return (
        <span className={numeric >= 50 ? "text-green-500" : numeric >= 40 ? "text-amber-500" : "text-red-500"}>
          {formatPercent(numeric)}
        </span>
        );
      },
    },
  ];

  const tradeColumns: Array<{
    key: keyof Trade;
    label: string;
    sortable?: boolean;
    render?: (value: unknown, row: Trade) => React.ReactNode;
  }> = [
    {
      key: "symbol" as keyof Trade,
      label: "Symbol",
      sortable: true,
    },
    {
      key: "side" as keyof Trade,
      label: "Side",
      render: (value: unknown) => {
        const side = typeof value === "string" ? value : "";
        return (
        <span className={`px-2 py-1 rounded text-xs font-medium ${
          side === "BUY" ? "bg-green-500/20 text-green-500" : "bg-red-500/20 text-red-500"
        }`}>
          {side || "-"}
        </span>
        );
      },
    },
    {
      key: "entryTime" as keyof Trade,
      label: "Entry Time",
      sortable: true,
      render: (value: unknown) => {
        const timestamp = typeof value === "string" ? value : "";
        return timestamp ? formatDateTime(timestamp) : "-";
      },
    },
    {
      key: "exitTime" as keyof Trade,
      label: "Exit Time",
      sortable: true,
      render: (value: unknown) => {
        const timestamp = typeof value === "string" ? value : "";
        return timestamp ? formatDateTime(timestamp) : "-";
      },
    },
    {
      key: "entryPrice" as keyof Trade,
      label: "Entry Price",
      sortable: true,
      render: (value: unknown) => {
        const numeric = typeof value === "number" ? value : Number(value) || 0;
        return formatCurrency(numeric);
      },
    },
    {
      key: "exitPrice" as keyof Trade,
      label: "Exit Price",
      sortable: true,
      render: (value: unknown) => {
        const numeric = typeof value === "number" ? value : Number(value) || 0;
        return formatCurrency(numeric);
      },
    },
    {
      key: "quantity" as keyof Trade,
      label: "Quantity",
      sortable: true,
    },
    {
      key: "pnl" as keyof Trade,
      label: "P&L",
      sortable: true,
      render: (value: unknown) => {
        const numeric = typeof value === "number" ? value : Number(value) || 0;
        return (
        <span className={numeric >= 0 ? "text-green-500" : "text-red-500"}>
          {formatCurrency(numeric)}
        </span>
        );
      },
    },
    {
      key: "pnlPercent" as keyof Trade,
      label: "P&L %",
      sortable: true,
      render: (value: unknown) => {
        const numeric = typeof value === "number" ? value : Number(value) || 0;
        return (
        <span className={numeric >= 0 ? "text-green-500" : "text-red-500"}>
          {formatPercent(numeric)}
        </span>
        );
      },
    },
    {
      key: "duration" as keyof Trade,
      label: "Duration",
      sortable: true,
    },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Research</h1>
        <button type="button"
          onClick={() => setShowBacktestForm(true)}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium transition-colors"
        >
          Run Backtest
        </button>
      </div>

      {/* Mutation Feedback */}
      {backtestStatus && (
        <div className={`rounded-lg px-4 py-3 text-sm ${
          backtestStatus.type === 'success'
            ? 'bg-emerald-900/20 border border-emerald-500/30 text-emerald-300'
            : 'bg-red-900/20 border border-red-500/30 text-red-300'
        }`}>
          {backtestStatus.message}
        </div>
      )}

      {/* Analytics Charts */}
      <AnalyticsCharts />

      {/* Backtest Form Modal */}
      {showBacktestForm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 max-w-2xl w-full mx-4">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold text-white">Run Backtest</h2>
              <button type="button"
                onClick={() => setShowBacktestForm(false)}
                className="text-slate-400 hover:text-white"
              >
                ✕
              </button>
            </div>

            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label htmlFor="backtest-strategy" className="block text-sm font-medium text-slate-400 mb-1">Strategy</label>
                  <select aria-label="Strategy"
                    id="backtest-strategy"
                    name="strategy"
                    value={backtestConfig.strategy}
                    onChange={(e) => setBacktestConfig({ ...backtestConfig, strategy: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                  >
                    <option value="momentum">Momentum</option>
                    <option value="mean_reversion">Mean Reversion</option>
                    <option value="arbitrage">Arbitrage</option>
                    <option value="trend_following">Trend Following</option>
                  </select>
                </div>

                <div>
                  <label htmlFor="initial-capital" className="block text-sm font-medium text-slate-400 mb-1">Initial Capital</label>
                  <input aria-label="Initial Capital"
                    id="initial-capital"
                    name="initialCapital"
                    type="number"
                    value={backtestConfig.initialCapital}
                    onChange={(e) => setBacktestConfig({ ...backtestConfig, initialCapital: Number(e.target.value) })}
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                  />
                </div>

                <div>
                  <label htmlFor="start-date" className="block text-sm font-medium text-slate-400 mb-1">Start Date</label>
                  <input aria-label="Start Date"
                    id="start-date"
                    name="startDate"
                    type="date"
                    value={backtestConfig.startDate}
                    onChange={(e) => setBacktestConfig({ ...backtestConfig, startDate: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                  />
                </div>

                <div>
                  <label htmlFor="end-date" className="block text-sm font-medium text-slate-400 mb-1">End Date</label>
                  <input aria-label="End Date"
                    id="end-date"
                    name="endDate"
                    type="date"
                    value={backtestConfig.endDate}
                    onChange={(e) => setBacktestConfig({ ...backtestConfig, endDate: e.target.value })}
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label htmlFor="commission" className="block text-sm font-medium text-slate-400 mb-1">Commission (%)</label>
                  <input aria-label="Commission (%)"
                    id="commission"
                    name="commission"
                    type="number"
                    value={backtestConfig.commission}
                    onChange={(e) => setBacktestConfig({ ...backtestConfig, commission: Number(e.target.value) })}
                    step="0.001"
                    min="0"
                    max="1"
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                  />
                </div>

                <div>
                  <label htmlFor="slippage" className="block text-sm font-medium text-slate-400 mb-1">Slippage (%)</label>
                  <input aria-label="Slippage (%)"
                    id="slippage"
                    name="slippage"
                    type="number"
                    value={backtestConfig.slippage}
                    onChange={(e) => setBacktestConfig({ ...backtestConfig, slippage: Number(e.target.value) })}
                    step="0.0001"
                    min="0"
                    max="1"
                    className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                  />
                </div>

                <div>
                  <span className="block text-sm font-medium text-slate-400 mb-1">Symbols</span>
                  <div className="space-y-2">
                    {backtestConfig.symbols.map((symbol, index) => (
                      <div key={index} className="flex items-center gap-2">
                        <input aria-label="symbol"
                          id={`symbol-${index}`}
                          name={`symbol-${index}`}
                          type="text"
                          value={symbol}
                          onChange={(e) => {
                            const newSymbols = [...backtestConfig.symbols];
                            newSymbols[index] = e.target.value.toUpperCase();
                            setBacktestConfig({ ...backtestConfig, symbols: newSymbols });
                          }}
                          className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
                          placeholder="BTC-USD"
                        />
                        {index > 0 && (
                          <button type="button"
                            onClick={() => {
                              const newSymbols = backtestConfig.symbols.filter((_, i) => i !== index);
                              setBacktestConfig({ ...backtestConfig, symbols: newSymbols });
                            }}
                            className="text-red-500 hover:text-red-400"
                          >
                            Remove
                          </button>
                        )}
                      </div>
                    ))}
                    <button type="button"
                      onClick={() => {
                        setBacktestConfig({
                          ...backtestConfig,
                          symbols: [...backtestConfig.symbols, ""],
                        });
                      }}
                      className="text-blue-500 hover:text-blue-400 text-sm"
                    >
                      Add Symbol
                    </button>
                  </div>
                </div>
              </div>

              <div className="flex gap-2 mt-6">
                <StubGate data={backtestsRaw} label="Simulation only — backtest disabled">
                  <button type="button"
                    onClick={handleRunBacktest}
                    className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium transition-colors"
                   title="Run Backtest">
                    Run Backtest
                  </button>
                </StubGate>
                <button type="button"
                  onClick={() => setShowBacktestForm(false)}
                  className="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg font-medium transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Backtest Results */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Backtest Results</h2>
        {(!backtests || backtests.length === 0) ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-400">
            <svg className="w-12 h-12 mb-3 text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <p className="text-sm font-medium mb-1">No backtest results yet</p>
            <p className="text-xs text-slate-500">Click "Run Backtest" above to start a strategy simulation</p>
          </div>
        ) : (
        <DataTableEnhanced
          data={backtests || []}
          columns={columns}
          pageSize={10}
          showPagination
          showFilter
        />
        )}
      </div>

      {/* Selected Backtest Details */}
      {backtests && backtests.length > 0 && (
        <div className="space-y-6">
          {backtests.map((backtest) => (
            <div key={backtest.id} className="bg-slate-900 rounded-xl border border-slate-800 p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold text-white">{backtest.strategy} - {backtest.config.startDate} to {backtest.config.endDate}</h3>
                <span className={`px-2 py-1 rounded text-xs font-medium ${
                  backtest.status === "completed" ? "bg-green-500/20 text-green-500" :
                  backtest.status === "running" ? "bg-blue-500/20 text-blue-500" :
                  "bg-red-500/20 text-red-500"
                }`}>
                  {backtest.status.toUpperCase()}
                </span>
              </div>

              {/* Metrics Summary */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                <MetricCard
                  label="Total Return"
                  value={formatPercent(backtest.metrics.totalReturn)}
                  status={convertRiskStatus(getReturnStatus(backtest.metrics.totalReturn))}
                />
                <MetricCard
                  label="Sharpe Ratio"
                  value={backtest.metrics.sharpeRatio}
                  status={convertRiskStatus(getSharpeStatus(backtest.metrics.sharpeRatio))}
                />
                <MetricCard
                  label="Max Drawdown"
                  value={formatPercent(backtest.metrics.maxDrawdown)}
                  status={convertRiskStatus(getDrawdownStatus(backtest.metrics.maxDrawdown))}
                />
                <MetricCard
                  label="Win Rate"
                  value={formatPercent(backtest.metrics.winRate)}
                  status={convertRiskStatus(getWinRateStatus(backtest.metrics.winRate))}
                />
              </div>

              {/* Trades */}
              <div>
                <h4 className="text-md font-semibold text-white mb-4">Trades ({backtest.trades.length})</h4>
                <DataTableEnhanced
                  data={backtest.trades}
                  columns={tradeColumns}
                  pageSize={10}
                  showPagination
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
