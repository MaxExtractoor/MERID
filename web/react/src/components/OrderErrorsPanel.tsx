import { useState } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  BarChart3,
  CheckCircle,
  Clock,
  Filter,
  Info,
  RefreshCw,
  XCircle,
} from '../ui/icons';
import { useOrderErrors, getSeverityColor, getCategoryColor, formatErrorCode } from '../hooks/useOrderErrors';
import { formatDateTime } from '../utils/formatters';
import type { ErrorBreakdownItem } from '../hooks/useOrderErrors';

interface ErrorBarProps {
  count: number;
  total: number;
  color: string;
}

function ErrorBar({ count, total, color }: ErrorBarProps) {
  const percentage = total > 0 ? (count / total) * 100 : 0;
  
  return (
    <div className="h-2 bg-slate-800 rounded-full overflow-hidden flex-1">
      <div
        className={`h-full ${color} transition-all duration-500`}
        style={{ width: `${percentage}%` }}
      />
    </div>
  );
}

interface ErrorRowProps {
  error: ErrorBreakdownItem;
  index: number;
  total: number;
}

function ErrorRow({ error, index, total }: ErrorRowProps) {
  const severityColor = getSeverityColor(error.severity);
  const categoryColor = getCategoryColor(error.category);
  
  const getSeverityIcon = () => {
    switch (error.severity) {
      case 'critical':
        return <XCircle className="w-4 h-4" />;
      case 'warning':
        return <AlertTriangle className="w-4 h-4" />;
      default:
        return <Info className="w-4 h-4" />;
    }
  };
  
  return (
    <div className={`flex items-center gap-4 p-3 rounded-lg border ${severityColor}`}>
      {/* Rank */}
      <div className="w-8 text-center text-sm font-medium text-slate-500">
        #{index + 1}
      </div>
      
      {/* Severity Icon */}
      <div className="w-8 flex justify-center">
        {getSeverityIcon()}
      </div>
      
      {/* Error Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-sm truncate">
            {formatErrorCode(error.code)}
          </span>
          <span className={`text-xs px-2 py-0.5 rounded-full bg-slate-800 ${categoryColor}`}>
            {error.category}
          </span>
        </div>
        <p className="text-xs text-slate-400 mt-0.5 truncate">
          {error.description}
        </p>
      </div>
      
      {/* Count & Bar */}
      <div className="flex items-center gap-4 w-48">
        <ErrorBar count={error.count} total={total} color={severityColor.split(' ')[0].replace('text-', 'bg-')} />
        <div className="text-right min-w-[60px]">
          <div className="font-semibold text-sm">{error.count.toLocaleString()}</div>
          <div className="text-xs text-slate-500">{error.percentage}%</div>
        </div>
      </div>
    </div>
  );
}

interface CategoryCardProps {
  category: string;
  data: { count: number; codes: string[] };
  total: number;
}

function CategoryCard({ category, data, total }: CategoryCardProps) {
  const color = getCategoryColor(category);
  const percentage = total > 0 ? (data.count / total) * 100 : 0;
  
  const categoryLabels: Record<string, string> = {
    risk: 'Risk Controls',
    validation: 'Validation Errors',
    market: 'Market Issues',
    system: 'System Errors',
    funds: 'Fund Issues',
    other: 'Other',
  };
  
  return (
    <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
      <div className="flex items-center justify-between mb-2">
        <span className={`font-medium ${color}`}>{categoryLabels[category] || category}</span>
        <span className="text-lg font-bold text-slate-100">{data.count.toLocaleString()}</span>
      </div>
      <div className="h-2 bg-slate-800 rounded-full overflow-hidden mb-2">
        <div className={`h-full ${color.replace('text-', 'bg-')} transition-all duration-500`} style={{ width: `${percentage}%` }} />
      </div>
      <div className="flex items-center justify-between text-xs text-slate-500">
        <span>{percentage.toFixed(1)}% of total</span>
        <span>{data.codes.length} error types</span>
      </div>
    </div>
  );
}

interface OrderErrorsPanelProps {
  compact?: boolean;
}

function OrderErrorsPanel({ compact = false }: OrderErrorsPanelProps) {
  const { data, loading, error, refetch, windowHours, setWindowHours } = useOrderErrors();
  const [filterSeverity, setFilterSeverity] = useState<string | null>(null);
  const [filterCategory, setFilterCategory] = useState<string | null>(null);

  const timeWindowOptions = [1, 6, 12, 24, 48, 72, 168];

  if (loading && !data) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 animate-pulse">
        <div className="h-6 bg-slate-800 rounded mb-4"></div>
        <div className="space-y-3">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-12 bg-slate-800 rounded"></div>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-slate-900 rounded-xl border border-red-800 p-6">
        <div className="flex items-center gap-2 text-red-400 mb-2">
          <AlertCircle className="w-5 h-5" />
          <span className="font-semibold">Order Errors Unavailable</span>
        </div>
        <p className="text-sm text-slate-400">{error}</p>
        <button onClick={refetch} className="mt-3 text-sm text-blue-400 hover:text-blue-300">
          Retry
        </button>
      </div>
    );
  }

  if (!data) return null;

  const { total_rejections, breakdown, by_category, by_severity } = data;

  // Filter errors
  const filteredErrors = breakdown.filter((err) => {
    if (filterSeverity && err.severity !== filterSeverity) return false;
    if (filterCategory && err.category !== filterCategory) return false;
    return true;
  });

  // Compact view
  if (compact) {
    const hasCritical = by_severity.critical > 0;
    const hasWarning = by_severity.warning > 0;
    
    return (
      <div
        className={`rounded-lg px-4 py-3 cursor-pointer transition-all ${
          hasCritical
            ? 'bg-red-500/20 border border-red-500/50 hover:bg-red-500/30'
            : hasWarning
            ? 'bg-amber-500/20 border border-amber-500/50 hover:bg-amber-500/30'
            : 'bg-slate-800 border border-slate-700 hover:bg-slate-700'
        }`}
        onClick={refetch}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-slate-400" />
            <span className="font-medium">
              {total_rejections.toLocaleString()} Order Rejections
            </span>
          </div>
          <div className="flex items-center gap-2">
            {by_severity.critical > 0 && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-red-500/20 text-red-400">
                {by_severity.critical} Critical
              </span>
            )}
            {by_severity.warning > 0 && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400">
                {by_severity.warning} Warning
              </span>
            )}
          </div>
        </div>
      </div>
    );
  }

  // Full panel view
  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-orange-500/10">
            <BarChart3 className="w-5 h-5 text-orange-400" />
          </div>
          <div>
            <h3 className="font-semibold text-slate-100">Order Error Breakdown</h3>
            <p className="text-sm text-slate-500">
              Rejection analysis by error code ({windowHours}h window)
            </p>
          </div>
        </div>
        <button
          onClick={() => refetch()}
          className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm transition-colors"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Time Window Selector */}
      <div className="flex items-center gap-2 mb-6 flex-wrap">
        <Clock className="w-4 h-4 text-slate-400" />
        <span className="text-sm text-slate-400">Time window:</span>
        {timeWindowOptions.map((hours) => (
          <button
            key={hours}
            onClick={() => setWindowHours(hours)}
            className={`px-2 py-1 text-xs rounded transition-colors ${
              windowHours === hours
                ? 'bg-blue-500/20 text-blue-400'
                : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
            }`}
          >
            {hours}h
          </button>
        ))}
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="bg-slate-800/50 rounded-lg p-3 text-center">
          <div className="text-2xl font-bold text-slate-100">{total_rejections.toLocaleString()}</div>
          <div className="text-xs text-slate-500">Total Rejections</div>
        </div>
        <div className="bg-red-500/10 rounded-lg p-3 text-center">
          <div className="text-2xl font-bold text-red-400">{by_severity.critical.toLocaleString()}</div>
          <div className="text-xs text-slate-500">Critical</div>
        </div>
        <div className="bg-amber-500/10 rounded-lg p-3 text-center">
          <div className="text-2xl font-bold text-amber-400">{by_severity.warning.toLocaleString()}</div>
          <div className="text-xs text-slate-500">Warning</div>
        </div>
        <div className="bg-blue-500/10 rounded-lg p-3 text-center">
          <div className="text-2xl font-bold text-blue-400">{by_severity.info.toLocaleString()}</div>
          <div className="text-xs text-slate-500">Info</div>
        </div>
      </div>

      {/* Category Breakdown */}
      {Object.keys(by_category).length > 0 && (
        <div className="mb-6">
          <h4 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-3">
            By Category
          </h4>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
            {Object.entries(by_category).map(([category, data]) => (
              <CategoryCard key={category} category={category} data={data} total={total_rejections} />
            ))}
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-4 mb-4">
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-slate-400" />
          <span className="text-sm text-slate-400">Filter:</span>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => setFilterSeverity(filterSeverity === 'critical' ? null : 'critical')}
            className={`px-3 py-1 text-xs rounded-full transition-colors ${
              filterSeverity === 'critical'
                ? 'bg-red-500/30 text-red-400 border border-red-500/50'
                : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
            }`}
          >
            Critical
          </button>
          <button
            onClick={() => setFilterSeverity(filterSeverity === 'warning' ? null : 'warning')}
            className={`px-3 py-1 text-xs rounded-full transition-colors ${
              filterSeverity === 'warning'
                ? 'bg-amber-500/30 text-amber-400 border border-amber-500/50'
                : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
            }`}
          >
            Warning
          </button>
          <button
            onClick={() => setFilterSeverity(filterSeverity === 'info' ? null : 'info')}
            className={`px-3 py-1 text-xs rounded-full transition-colors ${
              filterSeverity === 'info'
                ? 'bg-blue-500/30 text-blue-400 border border-blue-500/50'
                : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
            }`}
          >
            Info
          </button>
          {(filterSeverity || filterCategory) && (
            <button
              onClick={() => { setFilterSeverity(null); setFilterCategory(null); }}
              className="px-3 py-1 text-xs rounded-full bg-slate-700 text-slate-300 hover:bg-slate-600"
            >
              Clear filters
            </button>
          )}
        </div>
      </div>

      {/* Error List */}
      <div className="space-y-2">
        <h4 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-3">
          Error Details ({filteredErrors.length} of {breakdown.length})
        </h4>
        {filteredErrors.length === 0 ? (
          <div className="text-center py-8 text-slate-500">
            <CheckCircle className="w-12 h-12 mx-auto mb-3 opacity-50" />
            <p>No order rejections in this window</p>
          </div>
        ) : (
          filteredErrors.map((err, index) => (
            <ErrorRow key={err.code} error={err} index={index} total={total_rejections} />
          ))
        )}
      </div>

      {/* Footer */}
      <div className="mt-6 pt-4 border-t border-slate-800 text-xs text-slate-500 flex items-center justify-between">
        <div>
          Last updated: {formatDateTime(data.last_updated)}
        </div>
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1">
            <XCircle className="w-3 h-3 text-red-400" />
            Critical = Trading blocked
          </span>
          <span className="flex items-center gap-1">
            <AlertTriangle className="w-3 h-3 text-amber-400" />
            Warning = Review needed
          </span>
          <span className="flex items-center gap-1">
            <Info className="w-3 h-3 text-blue-400" />
            Info = Low priority
          </span>
        </div>
      </div>
    </div>
  );
}

export default OrderErrorsPanel;
