/**
 * SpotBasisPanel — Live spot/Kalshi implied-spot basis monitor.
 *
 * Shows the spread between Coinbase spot price and the Kalshi-implied spot
 * (risk-neutral median from YES-probability interpolation across strikes) for
 * BTC, ETH, SOL, XRP, and DOGE.
 *
 * Color coding:
 *   aligned    → green   — basis within configured thresholds
 *   offside    → red     — sustained breach of abs or pct threshold
 *   stale_feed → yellow  — one or both feeds are MISSING
 *
 * Feed status dots (per asset row):
 *   ● green  = ok (<5s stale)
 *   ● yellow = stale (5–30s stale)
 *   ● red    = missing (>30s stale)
 */
import type { JSX } from 'react';
import { useApiQuery } from '../hooks/useTanStackQuery';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

// ── Types ──────────────────────────────────────────────────────────────────────

type FeedStatus = 'ok' | 'stale' | 'missing';
type AlignmentState = 'aligned' | 'offside' | 'stale_feed';

interface AssetBasisData {
  asset: string;
  spot_price: number | null;
  spot_status: FeedStatus;
  kalshi_book_status: FeedStatus;
  implied_spot_mid: number | null;
  implied_spot_bid: number | null;
  implied_spot_ask: number | null;
  basis_mid: number | null;
  basis_bid: number | null;
  basis_ask: number | null;
  alignment: AlignmentState;
  breach_count: number;
  markets_used: number;
  nearest_expiry_secs: number | null;
  computed_at: number;
}

interface SpotBasisResponse {
  timestamp: number;
  assets: Record<string, AssetBasisData>;
  error?: string;
}

// ── Constants ──────────────────────────────────────────────────────────────────

const ASSET_COLORS: Record<string, string> = {
  BTC:  'text-orange-400',
  ETH:  'text-blue-400',
  SOL:  'text-purple-400',
  XRP:  'text-green-400',
  DOGE: 'text-yellow-400',
};

const ASSET_ORDER = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE'] as const;

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmtPrice(v: number | null, asset: string): string {
  if (v === null || v === undefined) return '—';
  if (asset === 'BTC') return `$${v.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
  if (asset === 'ETH') return `$${v.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
  return `$${v.toFixed(4)}`;
}

function fmtBasis(v: number | null, asset: string): string {
  if (v === null || v === undefined) return '—';
  const prefix = v >= 0 ? '+' : '';
  const abs = Math.abs(v);
  if (asset === 'BTC') return `${prefix}$${abs.toFixed(0)}`;
  if (asset === 'ETH') return `${prefix}$${abs.toFixed(1)}`;
  return `${prefix}$${abs.toFixed(4)}`;
}

function fmtExpiry(secs: number | null): string {
  if (secs === null || secs === undefined) return '—';
  if (secs < 60) return `${Math.round(secs)}s`;
  if (secs < 3600) return `${Math.round(secs / 60)}m`;
  return `${Math.round(secs / 3600)}h`;
}

function FeedDot({ status, label }: { status: FeedStatus; label: string }): JSX.Element {
  const colors: Record<FeedStatus, string> = {
    ok:      'bg-green-400',
    stale:   'bg-yellow-400',
    missing: 'bg-red-400',
  };
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${colors[status]}`}
      title={`${label}: ${status}`}
    />
  );
}

function AlignmentBadge({ alignment }: { alignment: AlignmentState }): JSX.Element {
  const styles: Record<AlignmentState, string> = {
    aligned:    'bg-green-900/40 text-green-300 border border-green-700/50',
    offside:    'bg-red-900/40 text-red-300 border border-red-700/50',
    stale_feed: 'bg-yellow-900/40 text-yellow-300 border border-yellow-700/50',
  };
  const labels: Record<AlignmentState, string> = {
    aligned:    'Aligned',
    offside:    'Offside',
    stale_feed: 'Stale Feed',
  };
  return (
    <span className={`px-1.5 py-0.5 rounded text-xs font-mono ${styles[alignment]}`}>
      {labels[alignment]}
    </span>
  );
}

// ── Component ──────────────────────────────────────────────────────────────────

export default function SpotBasisPanel(): JSX.Element {
  const { data, isLoading, error } = useApiQuery<SpotBasisResponse>(
    API_ENDPOINTS.SPOT_BASIS,
    { refetchInterval: DEFAULTS.POLLING_INTERVALS.SPOT_BASIS }
  );

  const offside = data
    ? ASSET_ORDER.filter(a => data.assets[a]?.alignment === 'offside')
    : [];

  // ── Error / isLoading states ─────────────────────────────────────────────────
  if (isLoading && !data) {
    return (
      <div className="bg-gray-900 rounded-lg p-4 border border-gray-700">
        <h3 className="text-sm font-semibold text-gray-300 mb-2">Spot / Kalshi Basis</h3>
        <div className="text-gray-500 text-xs animate-pulse">Loading basis data…</div>
      </div>
    );
  }

  if (error || (data && data.error)) {
    return (
      <div className="bg-gray-900 rounded-lg p-4 border border-gray-700">
        <h3 className="text-sm font-semibold text-gray-300 mb-2">Spot / Kalshi Basis</h3>
        <div className="text-red-400 text-xs">{error instanceof Error ? error.message : (error ?? data?.error)}</div>
      </div>
    );
  }

  // ── Main render ────────────────────────────────────────────────────────────
  return (
    <div className="bg-gray-900 rounded-lg border border-gray-700">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-700">
        <h3 className="text-sm font-semibold text-gray-200">
          Spot / Kalshi Basis
          <span className="ml-2 text-xs text-gray-500 font-normal">
            (Coinbase vs Kalshi implied spot)
          </span>
        </h3>
        <div className="text-xs font-mono">
          {offside.length > 0 ? (
            <span className="text-red-400 font-semibold">
              ⚠ {offside.join(', ')} offside
            </span>
          ) : (
            <span className="text-green-400">✓ All aligned</span>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-500 border-b border-gray-800">
              <th className="text-left px-3 py-1.5 font-medium">Asset</th>
              <th className="text-right px-3 py-1.5 font-medium">Spot</th>
              <th className="text-right px-3 py-1.5 font-medium">Implied</th>
              <th className="text-right px-3 py-1.5 font-medium">Basis mid</th>
              <th className="text-right px-2 py-1.5 font-medium text-gray-600">Bid / Ask</th>
              <th className="text-center px-2 py-1.5 font-medium" title="Spot feed · Book feed">Feeds</th>
              <th className="text-center px-3 py-1.5 font-medium">Status</th>
              <th className="text-right px-3 py-1.5 font-medium" title="Nearest expiry · Markets used">Expiry</th>
            </tr>
          </thead>
          <tbody>
            {ASSET_ORDER.map((asset) => {
              const ab = data?.assets[asset];

              // Show placeholder row when no data
              if (!ab) {
                return (
                  <tr key={asset} className="border-b border-gray-800/50">
                    <td className={`px-3 py-1.5 font-mono font-bold ${ASSET_COLORS[asset]}`}>{asset}</td>
                    <td colSpan={7} className="px-3 py-1.5 text-gray-600 text-center">—</td>
                  </tr>
                );
              }

              const basisColor =
                ab.alignment === 'offside'    ? 'text-red-400'    :
                ab.alignment === 'stale_feed' ? 'text-yellow-500' :
                ab.basis_mid === null         ? 'text-gray-600'   :
                Math.abs(ab.basis_mid) < 1    ? 'text-gray-300'   :
                'text-yellow-300';

              return (
                <tr key={asset} className="border-b border-gray-800/50 hover:bg-gray-800/20 transition-colors">
                  {/* Asset name */}
                  <td className={`px-3 py-1.5 font-mono font-bold ${ASSET_COLORS[asset]}`}>
                    {asset}
                  </td>

                  {/* Coinbase spot */}
                  <td className="px-3 py-1.5 text-right text-gray-300 font-mono tabular-nums">
                    {fmtPrice(ab.spot_price, asset)}
                  </td>

                  {/* Kalshi implied spot (mid) */}
                  <td className="px-3 py-1.5 text-right text-gray-400 font-mono tabular-nums">
                    {fmtPrice(ab.implied_spot_mid, asset)}
                  </td>

                  {/* Basis mid */}
                  <td className={`px-3 py-1.5 text-right font-mono tabular-nums font-semibold ${basisColor}`}>
                    {fmtBasis(ab.basis_mid, asset)}
                  </td>

                  {/* Bid / Ask basis */}
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-gray-600 text-xs">
                    {fmtBasis(ab.basis_bid, asset)} / {fmtBasis(ab.basis_ask, asset)}
                  </td>

                  {/* Feed status dots */}
                  <td className="px-2 py-1.5 text-center">
                    <span className="inline-flex gap-1 items-center">
                      <FeedDot status={ab.spot_status} label="Spot (Coinbase)" />
                      <FeedDot status={ab.kalshi_book_status} label="Book (Kalshi)" />
                    </span>
                  </td>

                  {/* Alignment badge */}
                  <td className="px-3 py-1.5 text-center">
                    <AlignmentBadge alignment={ab.alignment} />
                    {ab.breach_count > 0 && ab.alignment !== 'offside' && (
                      <span className="ml-1 text-gray-600 text-xs" title={`${ab.breach_count} consecutive breach ticks`}>
                        ({ab.breach_count})
                      </span>
                    )}
                  </td>

                  {/* Expiry + markets used */}
                  <td className="px-3 py-1.5 text-right font-mono tabular-nums text-gray-400">
                    {fmtExpiry(ab.nearest_expiry_secs)}
                    {ab.markets_used > 0 && (
                      <span className="ml-1 text-gray-600 text-xs">
                        ×{ab.markets_used}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Footer caption */}
      <div className="px-4 py-1.5 border-t border-gray-800 text-xs text-gray-600">
        Implied spot = strike where Kalshi YES prob ≈ 50% (risk-neutral median). Basis = implied − Coinbase.
      </div>
    </div>
  );
}
