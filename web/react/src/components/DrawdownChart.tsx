import { TrendingDown, AlertTriangle, Activity } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, CHART_COLORS} from "../config/constants";
import type { EquityHistoryPoint, DrawdownHistoryPoint } from '../types/api';

interface DrawdownChartProps {
  agentId?: string;
  timestamps?: number[];
  equity?: number[];
  drawdownSeries?: number[];
  maxDrawdown?: number;
  warningThreshold?: number;  // e.g., 0.1 for -10%
  dangerThreshold?: number;   // e.g., 0.2 for -20%
  height?: number;
  showEquity?: boolean;
}

export default function DrawdownChart({
  agentId,
  timestamps: propTimestamps,
  equity: propEquity,
  drawdownSeries: propDrawdown,
  maxDrawdown: propMaxDrawdown,
  warningThreshold = 0.1,
  dangerThreshold = 0.2,
  height = 200,
  showEquity = true,
}: DrawdownChartProps) {
  // Fetch via useApiData when agentId is provided and no prop data exists
  const shouldFetch = !!agentId && !propTimestamps;
  const { data: equityData, loading: eqLoading } = useApiData<{ history: EquityHistoryPoint[] }>(
    agentId ? API_ENDPOINTS.RISK_AGENT_EQUITY_HISTORY(agentId) : '',
    { pollingInterval: 15000, enabled: shouldFetch },
  );
  const { data: drawdownData } = useApiData<{ history: DrawdownHistoryPoint[] }>(
    agentId ? API_ENDPOINTS.RISK_AGENT_DRAWDOWN_HISTORY(agentId) : '',
    { pollingInterval: 15000, enabled: shouldFetch },
  );
  const { data: metricsData } = useApiData<{ max_drawdown?: number }>(
    agentId ? API_ENDPOINTS.RISK_AGENT_METRICS(agentId) : '',
    { pollingInterval: 15000, enabled: shouldFetch },
  );

  // Merge props with fetched data (props take priority)
  const timestamps = propTimestamps ?? (equityData?.history?.map((h) => h.timestamp) ?? []);
  const equity = propEquity ?? (equityData?.history?.map((h) => h.equity) ?? []);
  const drawdown = propDrawdown ?? (drawdownData?.history?.map((h) => h.drawdown) ?? []);
  const maxDrawdown = propMaxDrawdown ?? (metricsData?.max_drawdown ?? 0);
  const loading = shouldFetch && eqLoading && !equityData;

  const formatPercent = (value: number) => {
    return `${(value * 100).toFixed(1)}%`;
  };

  const formatTime = (ts: number) => {
    return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const getDrawdownColor = (dd: number) => {
    if (dd >= dangerThreshold) return CHART_COLORS.LIGHT_RED; // red
    if (dd >= warningThreshold) return CHART_COLORS.YELLOW; // yellow
    return CHART_COLORS.LIGHT_GREEN; // green
  };

  // SVG rendering
  const width = 400;
  const chartHeight = height - 40;
  const padding = { top: 10, right: 10, bottom: 30, left: 50 };
  const chartWidth = width - padding.left - padding.right;
  const innerHeight = chartHeight - padding.top - padding.bottom;

  const renderChart = () => {
    if (timestamps.length < 2) {
      return (
        <div className="flex items-center justify-center h-full text-gray-500">
          <div className="text-center">
            <Activity className="w-8 h-8 mx-auto mb-2 opacity-50" />
            <p className="text-sm">Waiting for data...</p>
          </div>
        </div>
      );
    }

    // Calculate scales
    const equityMin = Math.min(...equity) * 0.95;
    const equityMax = Math.max(...equity) * 1.05;
    const equityRange = equityMax - equityMin || 1;

    const ddMax = Math.max(...drawdown, dangerThreshold) * 1.1;

    // Generate paths
    const equityPoints = equity.map((e, i) => {
      const x = padding.left + (i / (equity.length - 1)) * chartWidth;
      const y = padding.top + (1 - (e - equityMin) / equityRange) * innerHeight;
      return `${x},${y}`;
    });

    const drawdownPoints = drawdown.map((d, i) => {
      const x = padding.left + (i / (drawdown.length - 1)) * chartWidth;
      const y = padding.top + (d / ddMax) * innerHeight;
      return `${x},${y}`;
    });

    // Drawdown fill area
    const drawdownArea = [
      `${padding.left},${padding.top}`,
      ...drawdownPoints,
      `${padding.left + chartWidth},${padding.top}`,
    ].join(' ');

    // Threshold lines
    const warningY = padding.top + (warningThreshold / ddMax) * innerHeight;
    const dangerY = padding.top + (dangerThreshold / ddMax) * innerHeight;

    return (
      <svg width="100%" height={chartHeight} viewBox={`0 0 ${width} ${chartHeight}`} preserveAspectRatio="xMidYMid meet">
        {/* Grid lines */}
        <g className="text-slate-700">
          {[0.25, 0.5, 0.75, 1].map((pct) => (
            <line
              key={pct}
              x1={padding.left}
              y1={padding.top + pct * innerHeight}
              x2={padding.left + chartWidth}
              y2={padding.top + pct * innerHeight}
              stroke="currentColor"
              strokeDasharray="2,2"
              opacity="0.3"
            />
          ))}
        </g>

        {/* Threshold lines */}
        <line
          x1={padding.left}
          y1={warningY}
          x2={padding.left + chartWidth}
          y2={warningY}
          stroke={CHART_COLORS.YELLOW}
          strokeDasharray="4,4"
          opacity="0.5"
        />
        <line
          x1={padding.left}
          y1={dangerY}
          x2={padding.left + chartWidth}
          y2={dangerY}
          stroke={CHART_COLORS.LIGHT_RED}
          strokeDasharray="4,4"
          opacity="0.5"
        />

        {/* Drawdown area */}
        <polygon
          points={drawdownArea}
          fill="url(#drawdownGradient)"
          opacity="0.3"
        />

        {/* Drawdown line */}
        <path
          d={`M ${drawdownPoints.join(' L ')}`}
          fill="none"
          stroke={getDrawdownColor(maxDrawdown)}
          strokeWidth="2"
        />

        {/* Equity line (if enabled) */}
        {showEquity && (
          <path
            d={`M ${equityPoints.join(' L ')}`}
            fill="none"
            stroke={CHART_COLORS.LIGHT_BLUE}
            strokeWidth="2"
          />
        )}

        {/* Gradient definitions */}
        <defs>
          <linearGradient id="drawdownGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={getDrawdownColor(maxDrawdown)} stopOpacity="0.4" />
            <stop offset="100%" stopColor={getDrawdownColor(maxDrawdown)} stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Y-axis labels */}
        <text x={padding.left - 5} y={padding.top + 4} textAnchor="end" className="fill-gray-500 text-[10px]">0%</text>
        <text x={padding.left - 5} y={warningY + 4} textAnchor="end" className="fill-yellow-400 text-[10px]">-{formatPercent(warningThreshold)}</text>
        <text x={padding.left - 5} y={dangerY + 4} textAnchor="end" className="fill-red-400 text-[10px]">-{formatPercent(dangerThreshold)}</text>

        {/* X-axis labels */}
        {timestamps.length > 0 && (
          <>
            <text x={padding.left} y={chartHeight - 5} textAnchor="start" className="fill-gray-500 text-[10px]">
              {formatTime(timestamps[0])}
            </text>
            <text x={padding.left + chartWidth} y={chartHeight - 5} textAnchor="end" className="fill-gray-500 text-[10px]">
              {formatTime(timestamps[timestamps.length - 1])}
            </text>
          </>
        )}
      </svg>
    );
  };

  if (loading) {
    return (
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4" style={{ height }}>
        <div className="animate-pulse h-full">
          <div className="h-4 bg-slate-700 rounded w-32 mb-4"></div>
          <div className="h-full bg-slate-700/50 rounded"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <TrendingDown className="w-5 h-5 text-red-400" />
          <span className="font-medium text-white">Drawdown Analysis</span>
        </div>
        
        <div className="flex items-center gap-3">
          {maxDrawdown >= dangerThreshold && (
            <div className="flex items-center gap-1 px-2 py-0.5 bg-red-500/20 rounded text-xs text-red-400">
              <AlertTriangle className="w-3 h-3" />
              High Risk
            </div>
          )}
          <div className={`text-sm font-medium ${maxDrawdown >= dangerThreshold ? 'text-red-400' : maxDrawdown >= warningThreshold ? 'text-yellow-400' : 'text-green-400'}`}>
            Max: -{formatPercent(maxDrawdown)}
          </div>
        </div>
      </div>

      {/* Chart */}
      <div style={{ height: chartHeight }}>
        {renderChart()}
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 mt-2 text-xs text-gray-400">
        <div className="flex items-center gap-1">
          <div className="w-3 h-0.5 bg-red-400/50"></div>
          <span>Drawdown</span>
        </div>
        {showEquity && (
          <div className="flex items-center gap-1">
            <div className="w-3 h-0.5 bg-blue-400"></div>
            <span>Equity</span>
          </div>
        )}
        <div className="flex items-center gap-1">
          <div className="w-3 h-0.5 bg-yellow-400" style={{ borderStyle: 'dashed' }}></div>
          <span>Warning (-{formatPercent(warningThreshold)})</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-0.5 bg-red-400" style={{ borderStyle: 'dashed' }}></div>
          <span>Danger (-{formatPercent(dangerThreshold)})</span>
        </div>
      </div>
    </div>
  );
}
