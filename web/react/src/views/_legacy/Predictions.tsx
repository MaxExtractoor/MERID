import { useState, useMemo, useEffect } from 'react';
import BrierMetricsPanel from '../components/BrierMetricsPanel';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS } from '../config/constants';
import type { PMRiskSummary, PMAlert, AgentTrade } from '../types/api';
import {
  Target, ArrowUpRight, ArrowDownRight, TrendingUp,
  BarChart3, LineChart, Wallet, Zap,
  RefreshCw, Search, ChevronRight, X,
  Bot, Flame, Radio,
} from 'lucide-react';

/* ═══════════════════════════════════════════════════════
   Types
   ═══════════════════════════════════════════════════════ */
interface Market {
  id: string;
  symbol: string;
  question: string;
  yesPrice: number;
  noPrice: number;
  volume: number;
  status: string;
  endTime: string;
  ourPosition: string;
  ourSize: number;
  ourPnl: number;
  modelConfidence: number;
  category?: string;
}

interface PredictionDriftSignal {
  signal_id: string;
  market_id: string;
  question: string;
  old_probability: number;
  new_probability: number;
  drift_pct: number;
  direction: string;
  volume_in_window: number;
  detected_at: string | null;
}

interface VenueGate {
  mode: string;
  kill_switch_active: boolean;
  allowed_venues: string[];
}

interface PMSummary {
  venue_gate: VenueGate;
  risk: PMRiskSummary;
  alerts: PMAlert[];
}

type TabId = 'browse' | 'positions' | 'arb' | 'drift' | 'agents' | 'analytics';

/* ═══════════════════════════════════════════════════════
   Hooks
   ═══════════════════════════════════════════════════════ */
function useMarkets() {
  const { data, loading, refetch } = useApiData<{ markets: Market[]; meta: { total: number; open: number; totalVolume: number; totalPnl: number } }>(
    API_ENDPOINTS.PREDICTION_MARKETS,
    { pollingInterval: 15_000 },
  );
  const markets = data?.markets ?? [];
  const meta = data?.meta ?? { total: 0, open: 0, totalVolume: 0, totalPnl: 0 };
  return { markets, meta, loading, refresh: refetch };
}

function usePMSummary() {
  const { data } = useApiData<PMSummary>(
    API_ENDPOINTS.PREDICTION_MARKETS_SUMMARY,
    { pollingInterval: 15_000 },
  );
  return data;
}

function useDriftSignals() {
  const { data, loading } = useApiData<{ signals: PredictionDriftSignal[] }>(
    `${API_ENDPOINTS.PREDICTION_DRIFT_SIGNALS}?limit=30`,
    { pollingInterval: 30_000 },
  );
  return { signals: data?.signals ?? [], loading };
}

/* ═══════════════════════════════════════════════════════
   Helpers
   ═══════════════════════════════════════════════════════ */
function fmtVol(v: number): string {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(0)}K`;
  return `$${v.toFixed(0)}`;
}

function fmtPct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

function fmtCents(v: number): string {
  return `${Math.round(v * 100)}¢`;
}

function timeUntil(endTime: string): string {
  const ms = new Date(endTime).getTime() - Date.now();
  if (ms <= 0) return 'Ended';
  const h = Math.floor(ms / 3_600_000);
  if (h >= 24) return `${Math.floor(h / 24)}d ${h % 24}h`;
  const m = Math.floor((ms % 3_600_000) / 60_000);
  return `${h}h ${m}m`;
}

function guessCategory(q: string): string {
  const lq = q.toLowerCase();
  if (lq.includes('bitcoin') || lq.includes('btc') || lq.includes('ethereum') || lq.includes('eth') || lq.includes('crypto') || lq.includes('solana')) return 'Crypto';
  if (lq.includes('president') || lq.includes('election') || lq.includes('trump') || lq.includes('biden') || lq.includes('congress') || lq.includes('fed') || lq.includes('rate')) return 'Politics';
  if (lq.includes('nba') || lq.includes('nfl') || lq.includes('mlb') || lq.includes('basketball') || lq.includes('football') || lq.includes('golf') || lq.includes('tennis') || lq.includes('masters')) return 'Sports';
  if (lq.includes('climate') || lq.includes('temperature') || lq.includes('weather')) return 'Climate';
  if (lq.includes('tech') || lq.includes('layoff') || lq.includes('company') || lq.includes('stock') || lq.includes('s&p') || lq.includes('nasdaq')) return 'Economics';
  return 'Other';
}

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`bg-slate-700/50 rounded animate-pulse ${className}`} />;
}

/* ═══════════════════════════════════════════════════════
   Sub-Components
   ═══════════════════════════════════════════════════════ */

/* ── Probability Pill ───────────────────────────────── */
function ProbPill({ value, variant }: { value: number; variant: 'yes' | 'no' }) {
  const pct = Math.round(value * 100);
  const bg = variant === 'yes'
    ? pct >= 60 ? 'bg-emerald-500' : 'bg-emerald-500/70'
    : pct >= 60 ? 'bg-red-500' : 'bg-red-500/70';
  return (
    <span className={`inline-flex items-center justify-center min-w-[48px] px-2 py-1 rounded-md text-sm font-bold text-white ${bg}`}>
      {pct}%
    </span>
  );
}

/* ── Market Card (Kalshi style) ─────────────────────── */
function MarketCard({ market, onClick }: { market: Market; onClick: () => void }) {
  const isLive = market.status === 'OPEN';
  const cat = market.category || guessCategory(market.question);
  const hasPos = market.ourPosition !== 'NONE';

  return (
    <button type="button"
      onClick={onClick}
      className="w-full text-left bg-slate-900/70 hover:bg-slate-800/80 border border-slate-700/50 hover:border-slate-600 rounded-xl p-5 transition-all group relative"
     title="Click">
      {/* Position indicator */}
      {hasPos && (
        <div className="absolute top-3 right-3">
          <div className={`w-2 h-2 rounded-full ${market.ourPnl >= 0 ? 'bg-emerald-400' : 'bg-red-400'} animate-pulse`} />
        </div>
      )}

      {/* Header row */}
      <div className="flex items-center gap-2 mb-3">
        {isLive && (
          <span className="flex items-center gap-1 text-[10px] font-bold text-emerald-400 bg-emerald-500/15 px-1.5 py-0.5 rounded">
            <Radio className="w-2.5 h-2.5" />LIVE
          </span>
        )}
        <span className="text-[10px] text-slate-500 uppercase font-medium">{cat}</span>
        <span className="ml-auto text-[10px] text-slate-500">{timeUntil(market.endTime)}</span>
      </div>

      {/* Question */}
      <h3 className="text-sm font-semibold text-slate-200 mb-4 line-clamp-2 leading-snug group-hover:text-white transition-colors">
        {market.question}
      </h3>

      {/* Outcomes */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-sm text-slate-300">Yes</span>
          <div className="flex items-center gap-2">
            {market.ourPosition === 'YES' && <span className="text-[10px] text-emerald-400 font-medium">{market.ourSize} contracts</span>}
            <ProbPill value={market.yesPrice} variant="yes" />
          </div>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-sm text-slate-300">No</span>
          <div className="flex items-center gap-2">
            {market.ourPosition === 'NO' && <span className="text-[10px] text-red-400 font-medium">{market.ourSize} contracts</span>}
            <ProbPill value={market.noPrice} variant="no" />
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between mt-4 pt-3 border-t border-slate-700/50">
        <span className="text-xs text-slate-500">{fmtVol(market.volume)} vol</span>
        {hasPos && (
          <span className={`text-xs font-semibold ${market.ourPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {market.ourPnl >= 0 ? '+' : ''}{market.ourPnl.toFixed(2)}
          </span>
        )}
        <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-slate-400 transition-colors" />
      </div>
    </button>
  );
}

/* ── Market Detail Slide-Over ──────────────────────── */
function MarketDetail({ market, onClose }: { market: Market; onClose: () => void }) {
  const [side, setSide] = useState<'buy' | 'sell'>('buy');
  const [outcome, setOutcome] = useState<'YES' | 'NO'>('YES');
  const [qty, setQty] = useState(10);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const price = outcome === 'YES' ? market.yesPrice : market.noPrice;
  const cost = qty * price;
  const payout = qty * 1.0; // $1 per contract
  const profit = payout - cost;

  const handleSubmit = async () => {
    setSubmitting(true);
    setResult(null);
    try {
      const res = await fetch(API_ENDPOINTS.SPECTATOR_RECORD, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_id: 'operator',
          symbol: market.symbol,
          action: side === 'buy' ? 'BUY' : 'SELL',
          quantity: qty,
          price: price,
          strategy: 'manual_prediction',
          confidence: market.modelConfidence,
          reasoning: `${side.toUpperCase()} ${outcome} on "${market.question}" @ ${fmtCents(price)}`,
          metadata: { market_id: market.id, outcome, side },
        }),
      });
      if (res.ok) {
        setResult(`✓ ${side === 'buy' ? 'Bought' : 'Sold'} ${qty} ${outcome} @ ${fmtCents(price)}`);
      } else {
        setResult('✗ Order failed');
      }
    } catch {
      setResult('✗ Network error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-label="Close market detail"
      />
      <div className="relative z-10 w-full max-w-lg bg-slate-900 border-l border-slate-700 overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-slate-900/95 backdrop-blur-md border-b border-slate-800 p-5 z-10">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-slate-500 uppercase">{guessCategory(market.question)}</span>
            <button type="button" title="Close market detail" onClick={onClose} className="p-1 hover:bg-slate-800 rounded-lg transition-colors" aria-label="Close">
              <X className="w-5 h-5 text-slate-400" />
            </button>
          </div>
          <h2 className="text-lg font-bold text-white leading-snug">{market.question}</h2>
          <div className="flex items-center gap-3 mt-2">
            {market.status === 'OPEN' && (
              <span className="flex items-center gap-1 text-xs font-bold text-emerald-400">
                <Radio className="w-3 h-3" />LIVE
              </span>
            )}
            <span className="text-xs text-slate-500">{fmtVol(market.volume)} vol</span>
            <span className="text-xs text-slate-500">Ends {timeUntil(market.endTime)}</span>
          </div>
        </div>

        {/* Probability Display */}
        <div className="p-5 space-y-4">
          {/* Visual probability bar */}
          <div className="relative h-10 rounded-lg overflow-hidden flex">
            <div className="bg-emerald-500/80 flex items-center justify-center transition-all" style={{ width: `${market.yesPrice * 100}%` }}>
              <span className="text-xs font-bold text-white">YES {Math.round(market.yesPrice * 100)}%</span>
            </div>
            <div className="bg-red-500/80 flex items-center justify-center transition-all" style={{ width: `${market.noPrice * 100}%` }}>
              <span className="text-xs font-bold text-white">NO {Math.round(market.noPrice * 100)}%</span>
            </div>
          </div>

          {/* Outcome rows */}
          <div className="space-y-2">
            <div className="flex items-center justify-between p-3 rounded-lg bg-slate-800/50 border border-slate-700/50">
              <span className="text-sm font-medium text-slate-200">Yes</span>
              <div className="flex items-center gap-2">
                <span className="text-lg font-bold text-emerald-400">{Math.round(market.yesPrice * 100)}%</span>
                <button type="button"
                  onClick={() => { setOutcome('YES'); setSide('buy'); }}
                  className="px-3 py-1 text-xs font-bold rounded bg-emerald-600 hover:bg-emerald-500 text-white transition-colors"
                >
                  Yes {fmtCents(market.yesPrice)}
                </button>
                <button type="button"
                  onClick={() => { setOutcome('YES'); setSide('sell'); }}
                  className="px-3 py-1 text-xs font-bold rounded bg-slate-700 hover:bg-slate-600 text-red-400 transition-colors"
                >
                  No {fmtCents(market.noPrice)}
                </button>
              </div>
            </div>
            <div className="flex items-center justify-between p-3 rounded-lg bg-slate-800/50 border border-slate-700/50">
              <span className="text-sm font-medium text-slate-200">No</span>
              <div className="flex items-center gap-2">
                <span className="text-lg font-bold text-red-400">{Math.round(market.noPrice * 100)}%</span>
                <button type="button"
                  onClick={() => { setOutcome('NO'); setSide('buy'); }}
                  className="px-3 py-1 text-xs font-bold rounded bg-emerald-600 hover:bg-emerald-500 text-white transition-colors"
                >
                  Yes {fmtCents(market.noPrice)}
                </button>
                <button type="button"
                  onClick={() => { setOutcome('NO'); setSide('sell'); }}
                  className="px-3 py-1 text-xs font-bold rounded bg-slate-700 hover:bg-slate-600 text-red-400 transition-colors"
                >
                  No {fmtCents(market.yesPrice)}
                </button>
              </div>
            </div>
          </div>

          {/* Model Confidence */}
          <div className="flex items-center justify-between p-3 rounded-lg bg-blue-500/10 border border-blue-500/20">
            <div className="flex items-center gap-2">
              <Bot className="w-4 h-4 text-blue-400" />
              <span className="text-sm text-blue-300">Model Confidence</span>
            </div>
            <span className="text-sm font-bold text-blue-400">{Math.round(market.modelConfidence * 100)}%</span>
          </div>

          {/* Current Position */}
          {market.ourPosition !== 'NONE' && (
            <div className={`p-3 rounded-lg border ${market.ourPnl >= 0 ? 'bg-emerald-500/10 border-emerald-500/20' : 'bg-red-500/10 border-red-500/20'}`}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Wallet className="w-4 h-4 text-slate-400" />
                  <span className="text-sm text-slate-300">Your Position</span>
                </div>
                <div className="text-right">
                  <div className="text-sm font-bold text-white">{market.ourPosition} × {market.ourSize}</div>
                  <div className={`text-xs font-semibold ${market.ourPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                    {market.ourPnl >= 0 ? '+' : ''}${market.ourPnl.toFixed(2)} P&L
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Order Panel */}
        <div className="border-t border-slate-800 p-5 space-y-4">
          <h3 className="text-sm font-semibold text-slate-300 uppercase">Place Order</h3>

          {/* Buy / Sell toggle */}
          <div className="flex rounded-lg overflow-hidden border border-slate-700">
            <button type="button"
              onClick={() => setSide('buy')}
              className={`flex-1 py-2 text-sm font-bold transition-colors ${side === 'buy' ? 'bg-emerald-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-white'}`}
            >
              Buy
            </button>
            <button type="button"
              onClick={() => setSide('sell')}
              className={`flex-1 py-2 text-sm font-bold transition-colors ${side === 'sell' ? 'bg-red-600 text-white' : 'bg-slate-800 text-slate-400 hover:text-white'}`}
            >
              Sell
            </button>
          </div>

          {/* Outcome toggle */}
          <div className="flex rounded-lg overflow-hidden border border-slate-700">
            <button type="button"
              onClick={() => setOutcome('YES')}
              className={`flex-1 py-2 text-sm font-bold transition-colors ${outcome === 'YES' ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500' : 'bg-slate-800 text-slate-400'}`}
            >
              Yes {fmtCents(market.yesPrice)}
            </button>
            <button type="button"
              onClick={() => setOutcome('NO')}
              className={`flex-1 py-2 text-sm font-bold transition-colors ${outcome === 'NO' ? 'bg-red-500/20 text-red-400 border-red-500' : 'bg-slate-800 text-slate-400'}`}
            >
              No {fmtCents(market.noPrice)}
            </button>
          </div>

          {/* Quantity */}
          <div>
            <span className="text-xs text-slate-500 mb-1 block">Contracts</span>
            <div className="flex items-center gap-2">
              {[1, 5, 10, 25, 50, 100].map(n => (
                <button type="button"
                  key={n}
                  onClick={() => setQty(n)}
                  className={`px-2 py-1 rounded text-xs font-medium transition-colors ${qty === n ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>

          {/* Cost summary */}
          <div className="bg-slate-800/50 rounded-lg p-3 space-y-1 text-sm">
            <div className="flex justify-between text-slate-400">
              <span>Price</span><span>{fmtCents(price)}</span>
            </div>
            <div className="flex justify-between text-slate-400">
              <span>Qty</span><span>{qty}</span>
            </div>
            <div className="flex justify-between text-slate-300 font-medium border-t border-slate-700 pt-1 mt-1">
              <span>Total Cost</span><span>${cost.toFixed(2)}</span>
            </div>
            <div className="flex justify-between text-emerald-400 font-medium">
              <span>Max Payout</span><span>${payout.toFixed(2)}</span>
            </div>
            <div className="flex justify-between text-emerald-300 font-bold">
              <span>Potential Profit</span><span>+${profit.toFixed(2)}</span>
            </div>
          </div>

          {/* Submit */}
          <button type="button"
            onClick={handleSubmit}
            disabled={submitting}
            className={`w-full py-3 rounded-lg font-bold text-white transition-colors disabled:opacity-50 ${
              side === 'buy' ? 'bg-emerald-600 hover:bg-emerald-500' : 'bg-red-600 hover:bg-red-500'
            }`}
           title="Submit">
            {submitting ? 'Submitting...' : `${side === 'buy' ? 'Buy' : 'Sell'} ${outcome}`}
          </button>

          {/* Result toast */}
          {result && (
            <div className={`text-center text-sm py-2 rounded-lg ${result.startsWith('✓') ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
              {result}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Positions Panel ──────────────────────────────── */
function PositionsPanel({ markets }: { markets: Market[] }) {
  const positions = useMemo(() => markets.filter(m => m.ourPosition !== 'NONE'), [markets]);
  const totalPnl = useMemo(() => positions.reduce((s, p) => s + p.ourPnl, 0), [positions]);

  if (positions.length === 0) {
    return (
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-8 text-center">
        <Wallet className="w-8 h-8 text-slate-600 mx-auto mb-3" />
        <p className="text-slate-400 text-sm">No open positions</p>
        <p className="text-slate-500 text-xs mt-1">Browse markets and place orders to get started</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-900/70 rounded-xl border border-slate-800 overflow-hidden">
      <div className="flex items-center justify-between p-4 border-b border-slate-800">
        <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
          <Wallet className="w-4 h-4 text-blue-400" />
          Open Positions ({positions.length})
        </h3>
        <span className={`text-sm font-bold ${totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
          Total: {totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}
        </span>
      </div>
      <div className="divide-y divide-slate-800">
        {positions.map(p => (
          <div key={p.id} className="p-4 hover:bg-slate-800/30 transition-colors">
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm font-medium text-slate-200 line-clamp-1 flex-1">{p.question}</span>
              <span className={`text-sm font-bold ml-3 ${p.ourPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                {p.ourPnl >= 0 ? '+' : ''}${p.ourPnl.toFixed(2)}
              </span>
            </div>
            <div className="flex items-center gap-3 text-xs text-slate-500">
              <span className={`font-bold ${p.ourPosition === 'YES' ? 'text-emerald-400' : 'text-red-400'}`}>
                {p.ourPosition} × {p.ourSize}
              </span>
              <span>Entry: {fmtCents(p.ourPosition === 'YES' ? p.yesPrice : p.noPrice)}</span>
              <span>Current: {fmtPct(p.ourPosition === 'YES' ? p.yesPrice : p.noPrice)}</span>
              <span className="ml-auto">{fmtVol(p.volume)} vol</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Arb Opportunities Panel ──────────────────────── */
function ArbPanel({ markets }: { markets: Market[] }) {
  const arbs = useMemo(() => {
    return markets
      .filter(m => {
        const spread = Math.abs((m.yesPrice + m.noPrice) - 1.0);
        return spread > 0.02 && m.status === 'OPEN';
      })
      .map(m => ({
        ...m,
        spread: Math.abs((m.yesPrice + m.noPrice) - 1.0),
        arbType: (m.yesPrice + m.noPrice) < 1.0 ? 'Under-priced' : 'Over-priced',
        potentialReturn: Math.abs((m.yesPrice + m.noPrice) - 1.0) * 100,
      }))
      .sort((a, b) => b.spread - a.spread)
      .slice(0, 10);
  }, [markets]);

  if (arbs.length === 0) {
    return (
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-8 text-center">
        <Zap className="w-8 h-8 text-slate-600 mx-auto mb-3" />
        <p className="text-slate-400 text-sm">No arbitrage opportunities detected</p>
        <p className="text-slate-500 text-xs mt-1">Markets are efficiently priced</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-900/70 rounded-xl border border-slate-800 overflow-hidden">
      <div className="flex items-center justify-between p-4 border-b border-slate-800">
        <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
          <Zap className="w-4 h-4 text-amber-400" />
          Arb Opportunities ({arbs.length})
        </h3>
      </div>
      <div className="divide-y divide-slate-800">
        {arbs.map(a => (
          <div key={a.id} className="p-4 hover:bg-slate-800/30 transition-colors">
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm font-medium text-slate-200 line-clamp-1 flex-1">{a.question}</span>
              <span className="text-sm font-bold text-amber-400 ml-3">+{a.potentialReturn.toFixed(1)}%</span>
            </div>
            <div className="flex items-center gap-3 text-xs text-slate-500">
              <span className={`font-medium ${a.arbType === 'Under-priced' ? 'text-emerald-400' : 'text-red-400'}`}>
                {a.arbType}
              </span>
              <span>Yes: {fmtCents(a.yesPrice)}</span>
              <span>No: {fmtCents(a.noPrice)}</span>
              <span>Spread: {(a.spread * 100).toFixed(1)}%</span>
              <span className="ml-auto">{fmtVol(a.volume)} vol</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Drift Signals Panel ──────────────────────────── */
function DriftPanel() {
  const { signals, loading } = useDriftSignals();

  if (loading) {
    return (
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-6">
        <Skeleton className="h-5 w-40 mb-4" />
        {[1, 2, 3].map(i => <Skeleton key={i} className="h-16 mb-2" />)}
      </div>
    );
  }

  if (signals.length === 0) {
    return (
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-8 text-center">
        <TrendingUp className="w-8 h-8 text-slate-600 mx-auto mb-3" />
        <p className="text-slate-400 text-sm">No drift signals detected</p>
        <p className="text-slate-500 text-xs mt-1">Monitoring for significant probability movements</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-900/70 rounded-xl border border-slate-800 overflow-hidden">
      <div className="flex items-center justify-between p-4 border-b border-slate-800">
        <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
          <Flame className="w-4 h-4 text-orange-400" />
          Drift Signals ({signals.length})
        </h3>
      </div>
      <div className="divide-y divide-slate-800">
        {signals.map((s, i) => {
          const up = s.direction === 'up' || s.new_probability > s.old_probability;
          return (
            <div key={s.signal_id || i} className="p-4 hover:bg-slate-800/30 transition-colors">
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm font-medium text-slate-200 line-clamp-1 flex-1">{s.question}</span>
                <div className={`flex items-center gap-1 ml-3 ${up ? 'text-emerald-400' : 'text-red-400'}`}>
                  {up ? <ArrowUpRight className="w-4 h-4" /> : <ArrowDownRight className="w-4 h-4" />}
                  <span className="text-sm font-bold">{Math.abs(s.drift_pct).toFixed(1)}%</span>
                </div>
              </div>
              <div className="flex items-center gap-3 text-xs text-slate-500">
                <span>{s.old_probability}% → {s.new_probability}%</span>
                {s.volume_in_window > 0 && <span>Vol: {fmtVol(s.volume_in_window)}</span>}
                <span className="ml-auto">{s.detected_at ? new Date(s.detected_at).toLocaleTimeString() : 'recent'}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── Agent Activity Panel ─────────────────────────── */
function AgentActivityPanel() {
  const [activity, setActivity] = useState<AgentTrade[]>([]);

  useEffect(() => {
    const f = async () => {
      try {
        const r = await fetch(`${API_ENDPOINTS.SPECTATOR_LIVE}?limit=15`);
        if (r.ok) {
          const d = await r.json();
          setActivity(d.trades || []);
        }
      } catch (err) { logUiError('Predictions', 'Activity fetch failed', err); }
    };
    f(); const i = setInterval(f, 10_000); return () => clearInterval(i);
  }, []);

  if (activity.length === 0) {
    return (
      <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-8 text-center">
        <Bot className="w-8 h-8 text-slate-600 mx-auto mb-3" />
        <p className="text-slate-400 text-sm">No agent activity yet</p>
        <p className="text-slate-500 text-xs mt-1">Agent trades will appear here as they execute</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-900/70 rounded-xl border border-slate-800 overflow-hidden">
      <div className="flex items-center justify-between p-4 border-b border-slate-800">
        <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
          <Bot className="w-4 h-4 text-purple-400" />
          Agent PM Activity ({activity.length})
        </h3>
      </div>
      <div className="divide-y divide-slate-800 max-h-[400px] overflow-y-auto">
        {activity.map((t: AgentTrade, i: number) => (
          <div key={i} className="p-3 hover:bg-slate-800/30 transition-colors">
            <div className="flex items-center gap-2 mb-1">
              <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${t.action === 'BUY' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}`}>
                {t.action}
              </span>
              <span className="text-xs font-medium text-slate-200">{t.symbol}</span>
              <span className="text-xs text-slate-500 ml-auto">{t.agent_id}</span>
            </div>
            <div className="flex items-center gap-2 text-[10px] text-slate-500">
              <span>{t.quantity} @ ${t.price?.toFixed(2)}</span>
              {t.strategy && <span className="text-blue-400">{t.strategy}</span>}
              {(t.confidence ?? 0) > 0 && <span>{Math.round((t.confidence ?? 0) * 100)}% conf</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════
   Main Component
   ═══════════════════════════════════════════════════════ */
const CATEGORIES = ['All', 'Crypto', 'Politics', 'Sports', 'Economics', 'Climate', 'Other'] as const;

const TABS: Array<{ id: TabId; label: string; icon: React.ComponentType }> = [
  { id: 'browse', label: 'Browse Markets', icon: BarChart3 },
  { id: 'positions', label: 'Positions', icon: Wallet },
  { id: 'arb', label: 'Arb Ops', icon: Zap },
  { id: 'drift', label: 'Drift', icon: Flame },
  { id: 'agents', label: 'Agents', icon: Bot },
  { id: 'analytics', label: 'Analytics', icon: LineChart },
];

export default function Predictions() {
  const { markets, meta, loading, refresh } = useMarkets();
  const pmSummary = usePMSummary();
  const [activeTab, setActiveTab] = useState<TabId>('browse');
  const [selectedMarket, setSelectedMarket] = useState<Market | null>(null);
  const [category, setCategory] = useState<string>('All');
  const [searchQ, setSearchQ] = useState('');

  // Enrich markets with categories
  const enriched = useMemo(() =>
    markets.map(m => ({ ...m, category: m.category || guessCategory(m.question) })),
    [markets]
  );

  // Filter markets
  const filtered = useMemo(() => {
    let list = enriched;
    if (category !== 'All') list = list.filter(m => m.category === category);
    if (searchQ.trim()) {
      const q = searchQ.toLowerCase();
      list = list.filter(m => m.question.toLowerCase().includes(q) || m.symbol.toLowerCase().includes(q));
    }
    return list.sort((a, b) => b.volume - a.volume);
  }, [enriched, category, searchQ]);

  const positionCount = useMemo(() => markets.filter(m => m.ourPosition !== 'NONE').length, [markets]);
  const mode = pmSummary?.venue_gate?.mode?.toUpperCase() || 'SIM';

  if (loading) {
    return (
      <div className="space-y-5 p-4 lg:p-6">
        <Skeleton className="h-10 w-64" />
        <div className="grid grid-cols-4 gap-4">{[1,2,3,4].map(i => <Skeleton key={i} className="h-20" />)}</div>
        <div className="grid grid-cols-3 gap-4">{[1,2,3,4,5,6].map(i => <Skeleton key={i} className="h-48" />)}</div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* ─── Header ─────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-purple-500/20 rounded-lg">
            <Target className="w-6 h-6 text-purple-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">Prediction Markets</h1>
            <p className="text-sm text-slate-400">Kalshi · Real-time odds · Agent-powered trading</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* Mode badge */}
          <span
            role="button"
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === 'Enter') refresh(); }}
            className={`px-3 py-1 rounded-full text-xs font-bold border cursor-pointer ${
            mode === 'LIVE' ? 'bg-red-500/20 text-red-400 border-red-500/30' :
            mode === 'PAPER' ? 'bg-amber-500/20 text-amber-400 border-amber-500/30' :
            'bg-slate-500/20 text-slate-400 border-slate-500/30'
          }`}>
            {mode}
          </span>
          <button type="button" onClick={refresh} className="p-2 rounded-lg hover:bg-slate-800 transition-colors" title="Refresh" aria-label="Refresh">
            <RefreshCw className="w-4 h-4 text-slate-400" />
          </button>
        </div>
      </div>

      {/* ─── Stats Strip ────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
          <div className="text-xs text-slate-500 mb-1">Total Markets</div>
          <div className="text-2xl font-bold text-white">{meta.total}</div>
        </div>
        <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
          <div className="text-xs text-slate-500 mb-1">Open</div>
          <div className="text-2xl font-bold text-emerald-400">{meta.open}</div>
        </div>
        <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
          <div className="text-xs text-slate-500 mb-1">Total Volume</div>
          <div className="text-2xl font-bold text-white">{fmtVol(meta.totalVolume)}</div>
        </div>
        <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4">
          <div className="text-xs text-slate-500 mb-1">P&L</div>
          <div className={`text-2xl font-bold ${meta.totalPnl >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
            {meta.totalPnl >= 0 ? '+' : ''}${meta.totalPnl.toFixed(2)}
          </div>
        </div>
      </div>

      {/* ─── Tab Navigation ─────────────────────── */}
      <nav className="flex items-center gap-1 bg-slate-900/60 rounded-xl p-1 border border-slate-800 overflow-x-auto">
        {TABS.map(tab => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          const badge = tab.id === 'positions' ? positionCount : undefined;
          return (
            <button type="button"
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium whitespace-nowrap transition-all ${
                isActive
                  ? 'bg-purple-600/20 text-purple-400 border border-purple-500/30'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 border border-transparent'
              }`}
            >
              <Icon className="w-4 h-4" />
              <span>{tab.label}</span>
              {badge !== undefined && badge > 0 && (
                <span className="bg-purple-500/30 text-purple-300 text-[10px] font-bold px-1.5 py-0.5 rounded-full">{badge}</span>
              )}
            </button>
          );
        })}
      </nav>

      {/* ─── Tab Content ────────────────────────── */}
      <div className="min-h-[500px]">

        {/* ═══ BROWSE MARKETS ═══ */}
        {activeTab === 'browse' && (
          <div className="space-y-4">
            {/* Search + Category Filters */}
            <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3">
              <div className="relative flex-1 max-w-md">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                <input aria-label="Search Q"
                  id="prediction-market-search"
                  name="marketSearch"
                  type="text"
                  value={searchQ}
                  onChange={e => setSearchQ(e.target.value)}
                  placeholder="Search markets..."
                  className="w-full pl-10 pr-4 py-2 bg-slate-800/50 border border-slate-700/50 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-purple-500"
                />
              </div>
              <div className="flex items-center gap-1 flex-wrap">
                {CATEGORIES.map(cat => (
                  <button type="button"
                    key={cat}
                    onClick={() => setCategory(cat)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                      category === cat
                        ? 'bg-purple-600/20 text-purple-400 border border-purple-500/30'
                        : 'bg-slate-800/50 text-slate-400 hover:text-slate-200 border border-transparent hover:border-slate-700'
                    }`}
                  >
                    {cat}
                  </button>
                ))}
              </div>
            </div>

            {/* Market Cards Grid */}
            {filtered.length === 0 ? (
              <div className="text-center py-12 text-slate-500">
                <Search className="w-8 h-8 mx-auto mb-3 opacity-50" />
                <p>No markets match your filters</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {filtered.map(m => (
                  <MarketCard key={m.id} market={m} onClick={() => setSelectedMarket(m)} />
                ))}
              </div>
            )}
          </div>
        )}

        {/* ═══ POSITIONS ═══ */}
        {activeTab === 'positions' && <PositionsPanel markets={enriched} />}

        {/* ═══ ARB OPS ═══ */}
        {activeTab === 'arb' && <ArbPanel markets={enriched} />}

        {/* ═══ DRIFT ═══ */}
        {activeTab === 'drift' && <DriftPanel />}

        {/* ═══ AGENTS ═══ */}
        {activeTab === 'agents' && <AgentActivityPanel />}

        {/* ═══ ANALYTICS ═══ */}
        {activeTab === 'analytics' && <BrierMetricsPanel />}
      </div>

      {/* ─── Market Detail Slide-Over ───────────── */}
      {selectedMarket && (
        <MarketDetail market={selectedMarket} onClose={() => setSelectedMarket(null)} />
      )}
    </div>
  );
}
