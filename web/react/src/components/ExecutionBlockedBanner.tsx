import { ShieldOff, AlertOctagon, Wifi, DollarSign, FileWarning } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { HelpPopover } from './HelpPopover';

interface BlockReason {
  source: string;
  severity: string;
  message: string;
  details: string | null;
}

interface ExecutionGateData {
  blocked: boolean;
  safe_to_trade: boolean;
  reasons: BlockReason[];
  timestamp: number;
}

const SOURCE_ICONS: Record<string, typeof ShieldOff> = {
  kill_switch: AlertOctagon,
  reconciliation: FileWarning,
  price_feed: Wifi,
  pnl_consistency: DollarSign,
};

/**
 * Prominent banner shown when execution is blocked.
 * Polls the unified execution gate endpoint and displays
 * all active block reasons with severity-appropriate styling.
 */
export function ExecutionBlockedBanner() {
  const { data } = useApiData<ExecutionGateData>(
    '/api/v1/system/execution-gate',
    { pollingInterval: 5000 },
  );

  if (!data || !data.blocked) return null;

  const criticalReasons = data.reasons.filter(r => r.severity === 'critical');
  const warningReasons = data.reasons.filter(r => r.severity === 'warning');

  return (
    <div className="bg-red-950/95 border-b-2 border-red-600/70 px-4 py-3 space-y-2">
      {/* Main banner line */}
      <div className="flex items-center justify-center gap-2 text-red-200 font-semibold text-sm">
        <ShieldOff className="w-5 h-5 text-red-400 animate-pulse" />
        <span>EXECUTION BLOCKED — Trading is halted</span>
        <HelpPopover title="Execution Blocked">
          <p>Trading is halted because one or more safety checks failed. No orders will be submitted until all critical issues are resolved.</p>
          <p className="mt-1 font-medium text-slate-200">Actions you can take:</p>
          <ul className="list-disc list-inside mt-1 space-y-0.5 text-slate-400">
            <li><b>Kill switch</b> — Reset via Mode &amp; Safety panel after investigating the cause.</li>
            <li><b>Reconciliation</b> — Wait for the next reconciliation cycle, or trigger a manual run.</li>
            <li><b>Stale feeds</b> — Check venue connectivity and data source health.</li>
            <li><b>PnL divergence</b> — Inspect PnL sources in the Consistency widget.</li>
          </ul>
        </HelpPopover>
      </div>

      {/* Critical reasons */}
      {criticalReasons.length > 0 && (
        <div className="flex flex-wrap items-center justify-center gap-3">
          {criticalReasons.map((r, i) => {
            const Icon = SOURCE_ICONS[r.source] ?? AlertOctagon;
            return (
              <div key={i} className="flex items-center gap-1.5 bg-red-900/50 border border-red-700/40 rounded px-2.5 py-1 text-xs text-red-300">
                <Icon className="w-3.5 h-3.5 text-red-400 flex-shrink-0" />
                <span className="font-medium">{r.message}</span>
                {r.details && <span className="text-red-400/70">— {r.details}</span>}
              </div>
            );
          })}
        </div>
      )}

      {/* Warning reasons */}
      {warningReasons.length > 0 && (
        <div className="flex flex-wrap items-center justify-center gap-3">
          {warningReasons.map((r, i) => {
            const Icon = SOURCE_ICONS[r.source] ?? AlertOctagon;
            return (
              <div key={i} className="flex items-center gap-1.5 bg-amber-900/30 border border-amber-700/30 rounded px-2.5 py-1 text-xs text-amber-300">
                <Icon className="w-3.5 h-3.5 text-amber-400 flex-shrink-0" />
                <span>{r.message}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

