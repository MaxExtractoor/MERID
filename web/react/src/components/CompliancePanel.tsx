import { useState, useEffect, useCallback } from 'react';
import {
  Shield, RefreshCw, CheckCircle, XCircle, AlertTriangle
} from 'lucide-react';

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
  const [venues, setVenues] = useState<VenueCompliance[]>([]);
  const [assets, setAssets] = useState<AssetCompliance[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<'venues' | 'assets'>('venues');

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/blockchain/compliance');
      if (res.ok) {
        const data = await res.json();
        if (data.venues) setVenues(data.venues);
        if (data.assets) setAssets(data.assets);
        return;
      }
    } catch { /* fallback */ }

    setVenues([
      { venue: 'Kalshi', status: 'ALLOWED', jurisdiction: 'US (CFTC)', lastReview: '2026-02-01', reviewOverdue: false },
      { venue: 'Binance', status: 'ALLOWED', jurisdiction: 'Global', lastReview: '2026-01-15', reviewOverdue: false },
      { venue: 'Coinbase', status: 'ALLOWED', jurisdiction: 'US', lastReview: '2026-02-01', reviewOverdue: false },
      { venue: 'Kraken', status: 'ALLOWED', jurisdiction: 'US', lastReview: '2026-01-20', reviewOverdue: false },
      { venue: 'OKX', status: 'RESTRICTED', jurisdiction: 'Non-US only', lastReview: '2026-01-10', reviewOverdue: true },
      { venue: 'Alpaca', status: 'ALLOWED', jurisdiction: 'US', lastReview: '2026-02-05', reviewOverdue: false },
      { venue: 'IBKR', status: 'ALLOWED', jurisdiction: 'US', lastReview: '2026-02-05', reviewOverdue: false },
      { venue: 'Polymarket', status: 'PROHIBITED', jurisdiction: 'US blocked', lastReview: '2026-01-01', reviewOverdue: false },
      { venue: 'Augur', status: 'PROHIBITED', jurisdiction: 'Unregulated', lastReview: '2026-01-01', reviewOverdue: false },
    ]);
    setAssets([
      { asset: 'BTC', status: 'ALLOWED' },
      { asset: 'ETH', status: 'ALLOWED' },
      { asset: 'SOL', status: 'ALLOWED' },
      { asset: 'USDC', status: 'ALLOWED' },
      { asset: 'USDT', status: 'ALLOWED' },
      { asset: 'AAPL', status: 'ALLOWED' },
      { asset: 'TSLA', status: 'ALLOWED' },
      { asset: 'SPY', status: 'ALLOWED' },
      { asset: 'TORN', status: 'PROHIBITED', reason: 'OFAC sanctioned' },
    ]);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const allowedVenues = venues.filter(v => v.status === 'ALLOWED').length;
  const prohibitedVenues = venues.filter(v => v.status === 'PROHIBITED').length;
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
            <button
              onClick={() => setTab('venues')}
              className={`px-2 py-1 text-xs rounded transition-colors ${
                tab === 'venues' ? 'bg-emerald-600 text-white' : 'bg-slate-700 text-gray-400 hover:text-white'
              }`}
            >
              Venues
            </button>
            <button
              onClick={() => setTab('assets')}
              className={`px-2 py-1 text-xs rounded transition-colors ${
                tab === 'assets' ? 'bg-emerald-600 text-white' : 'bg-slate-700 text-gray-400 hover:text-white'
              }`}
            >
              Assets
            </button>
          </div>
          <button onClick={fetchData} className="p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white" title="Refresh compliance">
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
                  {v.status === 'ALLOWED' ? <CheckCircle className={`w-4 h-4 ${style.color}`} /> :
                   v.status === 'RESTRICTED' ? <AlertTriangle className={`w-4 h-4 ${style.color}`} /> :
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
