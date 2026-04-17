/**
 * KalshiTradeTicket — Unified order entry for Kalshi binary contracts.
 *
 * Features:
 *   - YES/NO toggle with implied probability visualization
 *   - Size input in contracts or USD
 *   - Live fee and post-fee edge display
 *   - Limit price input with bid/ask reference
 *   - Payout and max loss visualization
 *   - Validation and error surfacing
 */

import React, { useState, useMemo, useCallback, useEffect, useRef, memo } from 'react';
import {
  DollarSign, AlertTriangle, CheckCircle, Info,
  ArrowRight, Loader2,
} from 'lucide-react';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS, AUTH_TOKEN_KEY } from '../config/constants';
import { useApiData } from '../hooks/useApiData';
import { logUxEvent } from '../utils/uxTelemetry';
import { SentimentBundleCard } from './SentimentBundleCard';
import { useFillToast } from '../hooks/useFillToast';

interface Outcome {
  id: string;
  name: string;
  price: number;
  bid: number | null;
  ask: number | null;
}

interface TradeTicketProps {
  ticker: string;
  question: string;
  outcomes: Outcome[];
  onOrderPlaced?: () => void;
  suggestedSize?: number;
  suggestedSide?: 'yes' | 'no';
  mode?: 'paper' | 'live';
  kellyFraction?: number;
  positionLimitPct?: number;
  orderGroupId?: string; // Optional: assign order to a specific group
  availableGroups?: Array<{
    order_group_id: string;
    name: string;
    status: 'active' | 'triggered' | 'canceled' | 'pending';
    utilization_pct: number;
  }>; // Available order groups for selection
  lastUpdated?: string | number; // T-035: ISO timestamp or epoch of last price update
}

type Side = 'yes' | 'no';
type SizeMode = 'contracts' | 'dollars';

const KALSHI_FEE_RATE = 0.07; // 7% of profit (Kalshi standard)

const ProgressBar = memo(function ProgressBar({ pct, color }: { pct: number; color: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ref.current) {
      ref.current.style.setProperty('--bar-width', `${pct}%`);
    }
  }, [pct]);
  return <div ref={ref} className={`h-full rounded-full transition-all progress-bar-var ${color}`} />;
});

function kalshiFee(priceCents: number, contracts: number, side: Side): number {
  const profit = side === 'yes'
    ? (100 - priceCents) * contracts / 100
    : priceCents * contracts / 100;
  return Math.max(0, profit * KALSHI_FEE_RATE);
}

const KalshiTradeTicket: React.FC<TradeTicketProps> = ({
  ticker,
  question: _question,
  outcomes,
  onOrderPlaced,
  suggestedSize,
  suggestedSide,
  mode = 'live',
  kellyFraction,
  positionLimitPct,
  orderGroupId: initialGroupId,
  availableGroups = [],
  lastUpdated,
}) => {
  // Execution gate — prevent order submission when trading is halted
  const { data: gateData } = useApiData<{ blocked: boolean; safe_to_trade: boolean }>(
    API_ENDPOINTS.SYSTEM_EXECUTION_GATE,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH },
  );
  // Safe default: block when gate data is unavailable (null = still loading or endpoint down)
  const executionBlocked = mode === 'live' && (gateData == null || gateData.blocked);

  // Fills integrity check — prevent order submission when data integrity is broken
  const { reconciliationStatus } = useFillToast();
  const fillsIntegrityBroken = reconciliationStatus === 'broken';
  const fillsIntegrityDegraded = reconciliationStatus === 'degraded';

  const [side, setSide] = useState<Side>(suggestedSide ?? 'yes');
  const [sizeMode, setSizeMode] = useState<SizeMode>('contracts');
  const [contracts, setContracts] = useState(suggestedSize ?? 1);
  const [dollarAmount, setDollarAmount] = useState(1);
  const [useLimit, setUseLimit] = useState(false);
  const [limitPrice, setLimitPrice] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [selectedGroupId, setSelectedGroupId] = useState<string>(initialGroupId || '');

  const yesOutcome = outcomes.find(o => (o.name ?? '').toLowerCase() === 'yes') ?? outcomes[0];
  const noOutcome = outcomes.find(o => (o.name ?? '').toLowerCase() === 'no') ?? outcomes[1];

  const activeOutcome = side === 'yes' ? yesOutcome : noOutcome;
  const priceCents = useMemo(() => {
    if (useLimit && limitPrice != null) return limitPrice;
    return Math.round((activeOutcome?.price ?? 0.5) * 100);
  }, [useLimit, limitPrice, activeOutcome]);

  const effectiveContracts = useMemo(() => {
    if (sizeMode === 'contracts') return contracts;
    if (priceCents <= 0) return 0;
    return Math.floor(dollarAmount / (priceCents / 100));
  }, [sizeMode, contracts, dollarAmount, priceCents]);

  const cost = (priceCents / 100) * effectiveContracts;
  const maxPayout = effectiveContracts; // $1 per contract
  const maxProfit = maxPayout - cost;
  const fee = kalshiFee(priceCents, effectiveContracts, side);
  const netProfit = maxProfit - fee;
  const impliedProb = priceCents;
  const edgePct = activeOutcome?.price
    ? ((side === 'yes' ? 1 - activeOutcome.price : activeOutcome.price) - (1 - priceCents / 100)) * 100
    : 0;

  const spread = useMemo(() => {
    if (!activeOutcome?.bid || !activeOutcome?.ask) return null;
    return Math.round((activeOutcome.ask - activeOutcome.bid) * 100);
  }, [activeOutcome]);

  const validate = useCallback((): string | null => {
    if (effectiveContracts <= 0) return 'Size must be at least 1 contract';
    if (priceCents <= 0 || priceCents >= 100) return 'Price must be between 1¢ and 99¢';
    if (useLimit && limitPrice == null) return 'Enter a limit price';
    return null;
  }, [effectiveContracts, priceCents, useLimit, limitPrice]);

  const handleSubmit = useCallback(async () => {
    const err = validate();
    if (err) { setError(err); return; }

    // T-035: Block trading on stale data (>30s since last price update)
    if (lastUpdated) {
      const dataAge = Date.now() - new Date(lastUpdated).getTime();
      if (dataAge > 30_000) {
        setError('Market data is stale (>30s). Refresh before trading.');
        return;
      }
    }

    // Require explicit confirmation for live orders
    if (mode === 'live') {
      const confirmed = window.confirm(
        `⚠️ LIVE ORDER — real money at risk\n\n` +
        `Buy ${effectiveContracts} ${side?.toUpperCase?.() ?? '?'} on ${ticker}\n` +
        `Price: ${priceCents}¢  ·  Cost: $${(cost ?? 0).toFixed(2)}\n` +
        `Max loss: $${(cost ?? 0).toFixed(2)}  ·  Net profit if win: $${(netProfit ?? 0).toFixed(2)}\n\n` +
        `Continue?`
      );
      if (!confirmed) return;
    }

    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const params = new URLSearchParams({
        ticker,
        side,
        action: 'buy',
        count: String(effectiveContracts),
        price_cents: String(priceCents),
        order_type: useLimit ? 'limit' : 'market',
        mode,
        ...(selectedGroupId ? { order_group_id: selectedGroupId } : {}),
      });
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_ORDERS}?${params}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
        },
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Order failed (${res.status})`);
      }
      const msg = `Order placed: ${effectiveContracts} ${side?.toUpperCase?.() ?? '?'} @ ${priceCents}¢`;
      setSuccess(msg);
      logUxEvent('trade_ticket_order', mode, {
        ticker,
        side,
        contracts: effectiveContracts,
        price_cents: priceCents,
        order_group_id: selectedGroupId,
      });
      onOrderPlaced?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Order submission failed');
    } finally {
      setSubmitting(false);
    }
  }, [validate, ticker, side, effectiveContracts, priceCents, cost, netProfit, useLimit, mode, onOrderPlaced, selectedGroupId, lastUpdated]);

  useEffect(() => {
    if (!success) return;
    const t = setTimeout(() => setSuccess(null), DEFAULTS.TIMEOUTS.TOAST);
    return () => clearTimeout(t);
  }, [success]);

  return (
    <div className="bg-slate-800 rounded-xl p-4 space-y-4">
      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">Trade Ticket</h3>

      {/* Sentiment Indicator */}
      {['BTC', 'ETH', 'SOL', 'XRP', 'DOGE'].some(a => ticker?.toUpperCase?.().includes(a)) && (
        <div className="mb-4">
          <SentimentBundleCard asset={['BTC','ETH','SOL','XRP','DOGE'].find(a => ticker?.toUpperCase?.().includes(a)) ?? 'BTC'} compact />
        </div>
      )}

      {/* YES/NO Toggle */}
      <div className="flex rounded-lg overflow-hidden border border-slate-700">
        <button
          type="button"
          onClick={() => setSide('yes')}
          className={`flex-1 py-2.5 text-sm font-bold transition-all ${
            side === 'yes'
              ? 'bg-green-600 text-white'
              : 'bg-slate-700 text-gray-400 hover:text-white'
          }`}
        >
          YES {yesOutcome && <span className="ml-1 font-mono">{((yesOutcome.price ?? 0) * 100).toFixed(0)}¢</span>}
        </button>
        <button
          type="button"
          onClick={() => setSide('no')}
          className={`flex-1 py-2.5 text-sm font-bold transition-all ${
            side === 'no'
              ? 'bg-red-600 text-white'
              : 'bg-slate-700 text-gray-400 hover:text-white'
          }`}
        >
          NO {noOutcome && <span className="ml-1 font-mono">{((noOutcome.price ?? 0) * 100).toFixed(0)}¢</span>}
        </button>
      </div>

      {/* Implied Probability Bar */}
      <div className="space-y-1">
        <div className="flex justify-between text-xs text-gray-400">
          <span>Implied Probability</span>
          <span className="font-mono">{impliedProb}%</span>
        </div>
        <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
          <ProgressBar pct={Math.max(2, Math.min(98, impliedProb))} color={side === 'yes' ? 'bg-green-500' : 'bg-red-500'} />
        </div>
      </div>

      {/* Size Input */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-400">Size</span>
          <div className="flex rounded-md overflow-hidden border border-slate-700">
            <button
              type="button"
              onClick={() => setSizeMode('contracts')}
              className={`px-2 py-0.5 text-[10px] ${sizeMode === 'contracts' ? 'bg-slate-600 text-white' : 'bg-slate-800 text-gray-500'}`}
            >
              Contracts
            </button>
            <button
              type="button"
              onClick={() => setSizeMode('dollars')}
              className={`px-2 py-0.5 text-[10px] ${sizeMode === 'dollars' ? 'bg-slate-600 text-white' : 'bg-slate-800 text-gray-500'}`}
            >
              USD
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {sizeMode === 'dollars' && <DollarSign className="w-4 h-4 text-gray-400" />}
          <input
            type="number"
            min={1}
            value={sizeMode === 'contracts' ? contracts : dollarAmount}
            onChange={(e) => {
              const raw = e.target.value;
              if (raw === '' || raw === '-') return;
              const v = parseInt(raw, 10);
              if (isNaN(v)) return;
              if (sizeMode === 'contracts') setContracts(Math.max(1, v));
              else setDollarAmount(Math.max(1, v));
            }}
            className="flex-1 bg-slate-700 rounded-lg px-3 py-2 text-sm text-white border border-slate-600 focus:border-orange-500 focus:outline-none font-mono"
            aria-label={sizeMode === 'contracts' ? 'Number of contracts' : 'Dollar amount'}
          />
          {sizeMode === 'dollars' && effectiveContracts > 0 && (
            <span className="text-xs text-gray-500">= {effectiveContracts} contracts</span>
          )}
        </div>
      </div>

      {/* Limit Price Toggle */}
      <div className="space-y-2">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            aria-label="Use limit price"
            checked={useLimit}
            onChange={(e) => {
              setUseLimit(e.target.checked);
              if (e.target.checked && limitPrice == null) {
                setLimitPrice(Math.round((activeOutcome?.price ?? 0.5) * 100));
              }
            }}
            className="rounded border-slate-600 bg-slate-700 text-orange-500 focus:ring-orange-500"
          />
          <span className="text-xs text-gray-400">Limit order</span>
        </label>
        {useLimit && (
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={1}
              max={99}
              value={limitPrice ?? ''}
              onChange={(e) => setLimitPrice(parseInt(e.target.value) || null)}
              className="w-20 bg-slate-700 rounded-lg px-3 py-1.5 text-sm text-white border border-slate-600 focus:border-orange-500 focus:outline-none font-mono"
              aria-label="Limit price in cents"
            />
            <span className="text-xs text-gray-500">¢</span>
            {spread != null && (
              <span className="text-[10px] text-gray-500 ml-auto">
                Spread: {spread}¢
                {activeOutcome?.bid && activeOutcome?.ask && (
                  <> ({((activeOutcome.bid ?? 0) * 100).toFixed(0)}–{((activeOutcome.ask ?? 0) * 100).toFixed(0)})</>
                )}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Order Group Selector */}
      {availableGroups.length > 0 && (
        <div className="space-y-2">
          <label htmlFor="order-group-select" className="text-xs text-gray-400">Order Group (optional)</label>
          <select
            aria-label="Order group"
            id="order-group-select"
            value={selectedGroupId}
            onChange={(e) => setSelectedGroupId(e.target.value)}
            className="w-full bg-slate-700 rounded-lg px-3 py-2 text-sm text-white border border-slate-600 focus:border-orange-500 focus:outline-none"
          >
            <option value="">— No Group —</option>
            {availableGroups.map((group) => (
              <option 
                key={group.order_group_id} 
                value={group.order_group_id}
                disabled={group.status !== 'active'}
              >
                {group.name || group.order_group_id} 
                {group.status === 'active' ? `(${group.utilization_pct}% used)` : `[${group.status}]`}
              </option>
            ))}
          </select>
          {selectedGroupId && (
            <p className="text-[10px] text-gray-500">
              Order will be assigned to group: {availableGroups.find(g => g.order_group_id === selectedGroupId)?.name || selectedGroupId}
            </p>
          )}
        </div>
      )}

      {/* Cost / Payout Summary */}
      <div className="bg-slate-900 rounded-lg p-3 space-y-2">
        <div className="flex justify-between text-xs">
          <span className="text-gray-400">Cost</span>
          <span className="text-white font-mono">${(cost ?? 0).toFixed(2)}</span>
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-gray-400">Max Payout</span>
          <span className="text-green-400 font-mono">${(maxPayout ?? 0).toFixed(2)}</span>
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-gray-400">
            Fee
            <span className="ml-1 text-[10px] text-gray-600" title="Kalshi charges 7% of profit on winning trades">
              (7% of profit)
            </span>
          </span>
          <span className="text-yellow-400 font-mono">-${(fee ?? 0).toFixed(2)}</span>
        </div>
        <div className="border-t border-slate-700 pt-2 flex justify-between text-xs font-medium">
          <span className="text-gray-300">Net Profit if Win</span>
          <span className={`font-mono ${netProfit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {netProfit >= 0 ? '+' : ''}${(netProfit ?? 0).toFixed(2)}
          </span>
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-gray-400">Max Loss</span>
          <span className="text-red-400 font-mono">-${(cost ?? 0).toFixed(2)}</span>
        </div>
      </div>

      {/* Edge display */}
      {edgePct !== 0 && (
        <div className="flex items-center gap-2 text-xs">
          <Info className="w-3.5 h-3.5 text-gray-500" />
          <span className="text-gray-400">Edge:</span>
          <span className={`font-mono ${edgePct > 0 ? 'text-green-400' : 'text-red-400'}`}>
            {edgePct > 0 ? '+' : ''}{(edgePct ?? 0).toFixed(1)}%
          </span>
        </div>
      )}

      {/* Error / Success */}
      {error && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}
      {success && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-green-500/10 border border-green-500/30 text-green-400 text-xs">
          <CheckCircle className="w-3.5 h-3.5 shrink-0" />
          <span>{success}</span>
        </div>
      )}

      {/* Execution gate + Fills integrity warnings */}
      {executionBlocked && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          <span>Live trading halted — execution gate is blocked</span>
        </div>
      )}
      {fillsIntegrityBroken && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          <span>Trading blocked — fills reconciliation BROKEN (position/fill mismatch)</span>
        </div>
      )}
      {fillsIntegrityDegraded && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          <span>Warning: fills reconciliation DEGRADED — some fills may be pending</span>
        </div>
      )}

      {/* Submit */}
      <button
        type="button"
        onClick={handleSubmit}
        disabled={submitting || effectiveContracts <= 0 || executionBlocked || fillsIntegrityBroken}
        title={fillsIntegrityBroken ? 'Trading disabled: fills reconciliation broken' : executionBlocked ? 'Trading halted: execution gate blocked' : undefined}
        className={`w-full flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-bold transition-all disabled:opacity-50 ${
          side === 'yes'
            ? 'bg-green-600 hover:bg-green-500 text-white'
            : 'bg-red-600 hover:bg-red-500 text-white'
        }`}
      >
        {submitting ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <>
            Buy {effectiveContracts} {side?.toUpperCase?.() ?? '?'}
            <ArrowRight className="w-4 h-4" />
            <span className="font-mono">${(cost ?? 0).toFixed(2)}</span>
          </>
        )}
      </button>

      {/* Kelly / limit info */}
      {kellyFraction != null && (
        <div className="flex items-center gap-2 text-xs">
          <Info className="w-3.5 h-3.5 text-gray-500" />
          <span className="text-gray-400">Kelly:</span>
          <span className={`font-mono ${kellyFraction > 0.25 ? 'text-amber-400' : 'text-green-400'}`}>
            {((kellyFraction ?? 0) * 100).toFixed(1)}%
          </span>
          {kellyFraction > 0.25 && <span title="High Kelly fraction"><AlertTriangle className="w-3 h-3 text-amber-400" /></span>}
        </div>
      )}
      {positionLimitPct != null && positionLimitPct > 75 && (
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          <span>Position limit: {(positionLimitPct ?? 0).toFixed(0)}% utilized</span>
        </div>
      )}

      <p className={`text-[10px] text-center ${mode === 'live' ? 'text-green-500 font-semibold' : 'text-gray-600'}`}>
        {mode === 'live' ? 'LIVE — real money at risk' : 'Paper trading mode. Orders are simulated.'}
      </p>
    </div>
  );
};

export default KalshiTradeTicket;
