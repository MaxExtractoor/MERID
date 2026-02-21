import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS } from '../config/constants';
import ErrorBar from './ErrorBar';
import { Shield } from 'lucide-react';

interface VenueCap {
  venue: string;
  max_exposure_usd: number;
  current_exposure_usd: number;
  remaining_usd: number;
  utilization_pct: number;
}

interface GuardStatus {
  venue_caps?: Record<string, VenueCap>;
  domain_caps?: Record<string, unknown>;
  global_kill_switch?: boolean;
}

function barColor(pct: number): string {
  if (pct >= 90) return 'bg-red-500';
  if (pct >= 70) return 'bg-yellow-500';
  return 'bg-emerald-500';
}

function textColor(pct: number): string {
  if (pct >= 90) return 'text-red-400';
  if (pct >= 70) return 'text-yellow-400';
  return 'text-emerald-400';
}

function fmtUsd(n: number): string {
  if (n >= 1000) return `$${(n / 1000).toFixed(1)}k`;
  return `$${n.toFixed(0)}`;
}

export default function VenueExposureCard() {
  const { data, error } = useApiData<GuardStatus>(API_ENDPOINTS.GUARD_STATUS, { pollingInterval: 10000 });

  const caps = data?.venue_caps
    ? Object.values(data.venue_caps)
        .filter(cap => cap.venue.toLowerCase() === 'kalshi' || cap.venue.toLowerCase() === 'prediction')
        .sort((a, b) => b.utilization_pct - a.utilization_pct)
    : [];

  return (
    <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-4">
        <Shield className="w-4 h-4 text-blue-400" />
        <h3 className="text-sm font-semibold text-slate-200">Venue Exposure Caps</h3>
        {data?.global_kill_switch && (
          <span className="ml-auto text-[10px] font-bold bg-red-900/40 text-red-400 px-2 py-0.5 rounded-full border border-red-700/40">
            KILL SWITCH
          </span>
        )}
      </div>

      <ErrorBar label="Venue Exposure" error={error} />

      {caps.length === 0 && !error && (
        <p className="text-xs text-slate-500 italic">No venue caps configured</p>
      )}

      <div className="space-y-3">
        {caps.map(cap => (
          <div key={cap.venue}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium text-slate-300 uppercase tracking-wide">
                {cap.venue}
              </span>
              <span className={`text-xs font-mono ${textColor(cap.utilization_pct)}`}>
                {fmtUsd(cap.current_exposure_usd)} / {fmtUsd(cap.max_exposure_usd)}
              </span>
            </div>
            <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${barColor(cap.utilization_pct)}`}
                style={{ width: `${Math.min(cap.utilization_pct, 100)}%` }}
              />
            </div>
            <div className="flex justify-between mt-0.5">
              <span className="text-[10px] text-slate-500">
                {cap.utilization_pct.toFixed(1)}% used
              </span>
              <span className="text-[10px] text-slate-500">
                {fmtUsd(cap.remaining_usd)} remaining
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
