import { useState } from 'react';
import {
  Shield, RefreshCw, CheckCircle, XCircle, AlertTriangle
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import ErrorBar from './ErrorBar';
import { API_ENDPOINTS, DEFAULTS, COMPLIANCE_STATUS} from '../config/constants';

interface VenueCompliance {
  venue: string;
  status: 'ALLOWED' | 'RESTRICTED' | 'PROHIBITED';
  jurisdiction: string;
  lastReview: string;
  reviewOverdue: boolean;
}

interface AssetCompliance {
  asset: string;
  status: 'ALLOWED' | 'PROHIBITED';
  reason?: string;
}

const STATUS_STYLES: Record<string, { color: string; bg: string }> = {
  ALLOWED: { color: 'text-green-400', bg: 'bg-green-500/10' },
  RESTRICTED: { color: 'text-amber-400', bg: 'bg-amber-500/10' },
  PROHIBITED: { color: 'text-red-400', bg: 'bg-red-500/10' },
};

export default function CompliancePanel() {
  const [tab, setTab] = useState<'venues' | 'assets'>('venues');

  const { data: rawData, loading, error: fetchError, refetch } = useApiData<{ venues: VenueCompliance[]; assets: AssetCompliance[] }>(
    API_ENDPOINTS.BLOCKCHAIN_COMPLIANCE,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.INFREQUENT },
  );

  if (fetchError && !rawData) {
    return <ErrorBar label="Compliance" error={fetchError} onRetry={refetch} />;
  }
  const venues = rawData?.venues ?? [];
  const assets = rawData?.assets ?? [];

  const allowedVenues = venues.filter(v => v.status === COMPLIANCE_STATUS.ALLOWED).length;
  const prohibitedVenues = venues.filter(v => v.status === COMPLIANCE_STATUS.PROHIBITED).length;
  const overdueCount = venues.filter(v => v.reviewOverdue).length;

  if (loading) {
    return (
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center gap-2 text-gray-400">
          <RefreshCw className="w-4 h-4 animate-spin" />
          <span>Loading compliance data...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield className="w-5 h-5 text-emerald-400" />
          <h3 className="text-lg font-bold text-white">Compliance</h3>
          <span className="text-xs px-2 py-0.5 rounded bg-green-500/20 text-green-400">{allowedVenues} allowed</span>
          {prohibitedVenues > 0 && (
            <span className="text-xs px-2 py-0.5 rounded bg-red-500/20 text-red-400">{prohibitedVenues} blocked</span>
          )}
          {overdueCount > 0 && (
            <span className="text-xs px-2 py-0.5 rounded bg-amber-500/20 text-amber-400">{overdueCount} overdue</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="flex gap-1">
            <button type="button"
              onClick={() => setTab('venues')}
              className={`px-2 py-1 text-xs rounded transition-colors ${
                tab === 'venues' ? 'bg-emerald-600 text-white' : 'bg-slate-700 text-gray-400 hover:text-white'
              }`}
            >
              Venues
            </button>
            <button type="button"
              onClick={() => setTab('assets')}
              className={`px-2 py-1 text-xs rounded transition-colors ${
                tab === 'assets' ? 'bg-emerald-600 text-white' : 'bg-slate-700 text-gray-400 hover:text-white'
              }`}
            >
              Assets
            </button>
          </div>
          <button type="button" onClick={() => refetch()} className="p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white" title="Refresh compliance" aria-label="Refresh">
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {tab === 'venues' ? (
        <div className="space-y-2">
          {venues.map(v => {
            const style = STATUS_STYLES[v.status] || STATUS_STYLES.ALLOWED;
            return (
              <div key={v.venue} className={`${style.bg} rounded-lg border border-slate-700/50 p-3 flex items-center justify-between`}>
                <div className="flex items-center gap-3">
                  {v.status === COMPLIANCE_STATUS.ALLOWED ? <CheckCircle className={`w-4 h-4 ${style.color}`} /> :
                   v.status === COMPLIANCE_STATUS.RESTRICTED ? <AlertTriangle className={`w-4 h-4 ${style.color}`} /> :
                   <XCircle className={`w-4 h-4 ${style.color}`} />}
                  <div>
                    <span className="text-sm font-medium text-white">{v.venue}</span>
                    <span className="text-xs text-gray-500 ml-2">{v.jurisdiction}</span>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  {v.reviewOverdue && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400">review overdue</span>
                  )}
                  <span className={`text-xs font-medium ${style.color}`}>{v.status}</span>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-2">
          {assets.map(a => {
            const style = STATUS_STYLES[a.status] || STATUS_STYLES.ALLOWED;
            return (
              <div key={a.asset} className={`${style.bg} rounded-lg border border-slate-700/50 p-2 text-center`}>
                <span className="text-sm font-mono font-medium text-white">{a.asset}</span>
                <div className={`text-[10px] ${style.color}`}>
                  {a.status}{a.reason ? ` · ${a.reason}` : ''}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
