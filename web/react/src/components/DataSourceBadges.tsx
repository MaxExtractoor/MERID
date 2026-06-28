/**
 * DataSourceBadge — Visual indicator for synthetic/manual/external data sources
 * 
 * This component ensures operators never confuse simulated/manual data with live capital.
 */


interface DataSourceBadgeProps {
  /** Whether the data is synthetic (not from actual venue) */
  synthetic?: boolean;
  /** Whether the order/position bypassed normal pipeline (manual/external) */
  manualOrExternal?: boolean;
  /** Source identifier: executor, rest_client, synthetic_agent_signal, etc. */
  source?: string;
  /** Show only the most critical indicator (compact mode) */
  compact?: boolean;
  /** Additional tooltip text */
  tooltip?: string;
}

export function DataSourceBadge({
  synthetic,
  manualOrExternal,
  source,
  compact = false,
  tooltip,
}: DataSourceBadgeProps) {
  // Determine badge style based on data source
  if (synthetic) {
    return (
      <span
        className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-purple-500/20 text-purple-400 border border-purple-500/30"
        title={tooltip || `Synthetic data (${source || 'unknown source'}) — not actual venue data`}
      >
        {compact ? 'SIM' : 'SIMULATED'}
      </span>
    );
  }

  if (manualOrExternal) {
    return (
      <span
        className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-orange-500/20 text-orange-400 border border-orange-500/30"
        title={tooltip || `Manual/External (${source || 'unknown source'}) — bypassed normal pipeline`}
      >
        {compact ? 'EXT' : 'EXTERNAL'}
      </span>
    );
  }

  // Real venue data — subtle indicator
  return compact ? null : (
    <span
      className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-green-500/10 text-green-400 border border-green-500/20"
      title={tooltip || `Live venue data (${source || 'executor'})`}
    >
      LIVE
    </span>
  );
}

/**
 * DataSourceBanner — Full-width banner for when synthetic data is displayed
 */
interface DataSourceBannerProps {
  /** Profile mode: prod, paper */
  profile?: string;
  /** Whether any synthetic data is currently displayed */
  showingSynthetic?: boolean;
  /** Call to action or additional context */
  context?: string;
}

export function DataSourceBanner({
  profile = 'prod',
  showingSynthetic,
  context,
}: DataSourceBannerProps) {
  // Only show banner in non-prod modes or when explicitly showing synthetic
  if (profile === 'prod' && !showingSynthetic) {
    return null;
  }

  const isPaper = profile === 'paper';

  return (
    <div
      className={`flex items-center justify-between px-3 py-2 text-xs border-b ${
        isPaper
          ? 'bg-blue-950/30 border-blue-500/30 text-blue-400'
          : showingSynthetic
          ? 'bg-orange-950/30 border-orange-500/30 text-orange-400'
          : 'hidden'
      }`}
    >
      <div className="flex items-center gap-2">
        <span className="w-2 h-2 rounded-full animate-pulse bg-current" />
        <span className="font-semibold uppercase tracking-wider">
          {isPaper ? 'Paper Trading' : 'Mixed Data Sources'}
        </span>
        <span className="opacity-75">
          {isPaper
            ? '— Orders are simulated, no real capital at risk'
            : '— Some data shown is synthetic or manual'}
        </span>
      </div>
      {context && <span className="opacity-75">{context}</span>}
    </div>
  );
}

/**
 * OrderLineageBadge — Compact indicator for order lineage completeness
 */
interface OrderLineageBadgeProps {
  /** Whether the order has complete lineage (signal → agent → risk → router) */
  chainComplete?: boolean;
  /** Coverage ratio like "4/4" */
  chainCoverage?: string;
  /** Whether the order was flagged as manual/external */
  manualOrExternal?: boolean;
  /** Number of warnings in lineage */
  warningCount?: number;
}

export function OrderLineageBadge({
  chainComplete,
  chainCoverage,
  manualOrExternal,
  warningCount = 0,
}: OrderLineageBadgeProps) {
  if (manualOrExternal) {
    return (
      <span
        className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-orange-500/20 text-orange-400 border border-orange-500/30 cursor-help"
        title="This order bypassed the normal pipeline (manual or external). No lineage trace available."
      >
        EXTERNAL
      </span>
    );
  }

  if (!chainComplete) {
    return (
      <span
        className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 cursor-help"
        title={`Incomplete lineage (${chainCoverage || 'unknown'}). Possible shadow path or missing trace data. ${warningCount} warnings.`}
      >
        PARTIAL {chainCoverage && `(${chainCoverage})`}
      </span>
    );
  }

  return (
    <span
      className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-green-500/10 text-green-400 border border-green-500/20 cursor-help"
      title={`Complete lineage trace (${chainCoverage || '4/4'}). Order flowed through canonical pipeline.`}
    >
      TRACED
    </span>
  );
}
