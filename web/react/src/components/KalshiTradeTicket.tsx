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

import React, { useState, useMemo, useCallback } from 'react';
import {
  DollarSign, AlertTriangle, CheckCircle, Info,
  ArrowRight, Loader2,
} from 'lucide-react';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { useApiData } from '../hooks/useApiData';

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
}

type Side = 'yes' | 'no';
type SizeMode = 'contracts' | 'dollars';

const KALSHI_FEE_RATE = 0.07; // 7% of profit (Kalshi standard)

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
}) => {
  // Execution gate — prevent order submission when trading is halted
  const { data: gateData } = useApiData<{ blocked: boolean; safe_to_trade: boolean }>(
    '/api/v1/system/execution-gate',
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST_REFRESH },
  );
  const executionBlocked = gateData?.blocked ?? false;

  const [side, setSide] = useState<Side>(suggestedSide ?? 'yes');
  const [sizeMode, setSizeMode] = useState<SizeMode>('contracts');
  const [contracts, setContracts] = useState(suggestedSize ?? 1);
  const [dollarAmount, setDollarAmount] = useState(1);
  const [useLimit, setUseLimit] = useState(false);
  const [limitPrice, setLimitPrice] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const yesOutcome = outcomes.find(o => o.name.toLowerCase() === 'yes') ?? outcomes[0];
  const noOutcome = outcomes.find(o => o.name.toLowerCase() === 'no') ?? outcomes[1];

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

    // Require explicit confirmation for live orders
    if (mode === 'live') {
      const confirmed = window.confirm(
        `⚠️ LIVE ORDER — real money at risk\n\n` +
        `Buy ${effectiveContracts} ${side.toUpperCase()} on ${ticker}\n` +
        `Price: ${priceCents}¢  ·  Cost: $${cost.toFixed(2)}\n` +
        `Max loss: $${cost.toFixed(2)}  ·  Net profit if win: $${netProfit.toFixed(2)}\n\n` +
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
      });
      const token = localStorage.getItem('merid-access');
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_ORDERS}?${params}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Order failed (${res.status})`);
      }
      setSuccess(`Order placed: ${effectiveContracts} ${side.toUpperCase()} @ ${priceCents}¢`);
      onOrderPlaced?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Order submission failed');
    } finally {
      setSubmitting(false);
    }
  }, [validate, ticker, side, effectiveContracts, priceCents, cost, netProfit, useLimit, mode, onOrderPlaced]);

  return (
    <div className="bg-slate-800 rounded-xl p-4 space-y-4">
      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">Trade Ticket</h3>

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
          YES {yesOutcome && <span className="ml-1 font-mono">{(yesOutcome.price * 100).toFixed(0)}¢</span>}
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
          NO {noOutcome && <span className="ml-1 font-mono">{(noOutcome.price * 100).toFixed(0)}¢</span>}
        </button>
      </div>

      {/* Implied Probability Bar */}
      <div className="space-y-1">
        <div className="flex justify-between text-xs text-gray-400">
          <span>Implied Probability</span>
          <span className="font-mono">{impliedProb}%</span>
        </div>
        <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${side === 'yes' ? 'bg-green-500' : 'bg-red-500'}`}
            style={{ width: `${Math.max(2, Math.min(98, impliedProb))}%` }}
          />
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
              const v = parseInt(e.target.value) || 0;
              if (sizeMode === 'contracts') setContracts(Math.max(0, v));
              else setDollarAmount(Math.max(0, v));
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
                  <> ({(activeOutcome.bid * 100).toFixed(0)}–{(activeOutcome.ask * 100).toFixed(0)})</>
                )}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Cost / Payout Summary */}
      <div className="bg-slate-900 rounded-lg p-3 space-y-2">
        <div className="flex justify-between text-xs">
          <span className="text-gray-400">Cost</span>
          <span className="text-white font-mono">${cost.toFixed(2)}</span>
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-gray-400">Max Payout</span>
          <span className="text-green-400 font-mono">${maxPayout.toFixed(2)}</span>
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-gray-400">
            Fee
            <span className="ml-1 text-[10px] text-gray-600" title="Kalshi charges 7% of profit on winning trades">
              (7% of profit)
            </span>
          </span>
          <span className="text-yellow-400 font-mono">-${fee.toFixed(2)}</span>
        </div>
        <div className="border-t border-slate-700 pt-2 flex justify-between text-xs font-medium">
          <span className="text-gray-300">Net Profit if Win</span>
          <span className={`font-mono ${netProfit >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {netProfit >= 0 ? '+' : ''}${netProfit.toFixed(2)}
          </span>
        </div>
        <div className="flex justify-between text-xs">
          <span className="text-gray-400">Max Loss</span>
          <span className="text-red-400 font-mono">-${cost.toFixed(2)}</span>
        </div>
      </div>

      {/* Edge display */}
      {edgePct !== 0 && (
        <div className="flex items-center gap-2 text-xs">
          <Info className="w-3.5 h-3.5 text-gray-500" />
          <span className="text-gray-400">Edge:</span>
          <span className={`font-mono ${edgePct > 0 ? 'text-green-400' : 'text-red-400'}`}>
            {edgePct > 0 ? '+' : ''}{edgePct.toFixed(1)}%
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

      {/* Execution gate warning */}
      {executionBlocked && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          <span>Trading halted — execution gate is blocked</span>
        </div>
      )}

      {/* Submit */}
      <button
        type="button"
        onClick={handleSubmit}
        disabled={submitting || effectiveContracts <= 0 || executionBlocked}
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
            Buy {effectiveContracts} {side.toUpperCase()}
            <ArrowRight className="w-4 h-4" />
            <span className="font-mono">${cost.toFixed(2)}</span>
          </>
        )}
      </button>

      {/* Kelly / limit info */}
      {kellyFraction != null && (
        <div className="flex items-center gap-2 text-xs">
          <Info className="w-3.5 h-3.5 text-gray-500" />
          <span className="text-gray-400">Kelly:</span>
          <span className={`font-mono ${kellyFraction > 0.25 ? 'text-amber-400' : 'text-green-400'}`}>
            {(kellyFraction * 100).toFixed(1)}%
          </span>
          {kellyFraction > 0.25 && <span title="High Kelly fraction"><AlertTriangle className="w-3 h-3 text-amber-400" /></span>}
        </div>
      )}
      {positionLimitPct != null && positionLimitPct > 75 && (
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          <span>Position limit: {positionLimitPct.toFixed(0)}% utilized</span>
        </div>
      )}

      <p className={`text-[10px] text-center ${mode === 'live' ? 'text-green-500 font-semibold' : 'text-gray-600'}`}>
        {mode === 'live' ? 'LIVE — real money at risk' : 'Paper trading mode. Orders are simulated.'}
      </p>
    </div>
  );
};

export default KalshiTradeTicket;
