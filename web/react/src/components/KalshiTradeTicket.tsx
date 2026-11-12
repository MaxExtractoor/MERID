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
 *   - Enhanced: Network status, timeout handling, retry logic
 */

import React, { useState, useMemo, useCallback, useEffect, useRef, memo } from 'react';
import {
  DollarSign, AlertTriangle, CheckCircle, Info,
  ArrowRight, Loader2, RefreshCw, WifiOff, Clock,
} from '../ui/icons';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { getJson, postJson } from '../agents/api';
import { reasonLabel } from '../agents/format';
import { useKalshiStore } from '../store';
import { logUxEvent } from '../utils/uxTelemetry';
import { ConfirmModal } from './ConfirmModal';

interface Outcome {
  id: string;
  name: string;
  /** Own-side last price in dollars (0-1). null = venue did not quote — the
   *  ticket refuses to guess a price for order submission. */
  price: number | null;
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
  lastUpdated?: string | number;
  enhanced?: boolean;
  balance?: { available: number; total: number };
  /** Live entry-TTE cutoff (s) on this market's agent, when known. */
  entryCutoffSecs?: number;
  /** Live seconds-to-close on this market's agent, when known. */
  secsToClose?: number;
  /** ms since the live orderbook last updated (authoritative freshness). */
  bookAgeMs?: number;
  /** Backend book_fresh flag for this market, when known. */
  bookFresh?: boolean;
  /** Backend executable flag — book healthy enough to trade against. */
  marketExecutable?: boolean;
  /** Current veto/gate reason on this market's agent (e.g. SKIP_MARKET_NOT_READY). */
  marketVetoReason?: string;
  /** Gate-level sub-reason (e.g. STALE:age=75s>t60s, NOT-LIVE-SEQUENCE-CONFIRMED). */
  marketVetoDetail?: string;
}

type Side = 'yes' | 'no';
type SizeMode = 'contracts' | 'dollars';

// Official Kalshi taker-fee schedule (verified 2026-11): fees are charged on
// expected earnings — fees = round_up(0.07 x C x P x (1-P)), rounded UP to the
// centicent ($0.0001). P is the own-side contract price in dollars. The same
// parabolic form applies to YES and NO sides because P is always the price
// actually paid. Backend enforces the identical kalshi_fee_cents_exact.
const KALSHI_TAKER_FEE_RATE = 0.07;

const ProgressBar = memo(function ProgressBar({ pct, color }: { pct: number; color: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ref.current) {
      ref.current.style.setProperty('--bar-width', `${pct}%`);
    }
  }, [pct]);
  return <div ref={ref} className={`h-full rounded-full transition-all progress-bar-var ${color}`} />;
});

/** Estimated taker fee in USD — ceil to the centicent ($0.0001), per the
 *  published schedule. A limit order that rests may pay the maker rate
 *  (~50% lower) instead, so this is the conservative estimate. */
function kalshiFee(priceCents: number, contracts: number): number {
  const p = priceCents / 100;
  const raw = KALSHI_TAKER_FEE_RATE * contracts * p * (1 - p);
  return Math.ceil(raw * 10000) / 10000;
}

/** Contract count display — trims to the 0.01 grid without float noise. */
const fmtCount = (n: number): string =>
  (Math.round(n * 100) / 100).toLocaleString('en-US', { maximumFractionDigits: 2 });

type TradeErrorType = 'validation' | 'network' | 'api' | 'insufficient_balance' | 'market_closed';
interface TradeError {
  type: TradeErrorType;
  message: string;
  recoverable: boolean;
}

const KalshiTradeTicket: React.FC<TradeTicketProps> = ({
  ticker,
  question,
  outcomes,
  onOrderPlaced,
  suggestedSize,
  suggestedSide,
  mode = 'live',
  kellyFraction,
  positionLimitPct,
  lastUpdated,
  enhanced = false,
  balance,
  entryCutoffSecs,
  secsToClose,
  bookAgeMs,
  bookFresh,
  marketExecutable,
  marketVetoReason,
  marketVetoDetail,
}) => {
  // Execution gate — /api/v1/system/execution-gate does not exist on the
  // backend. Gate on the real live-runtime-state instead: any state other
  // than confirmed LIVE_ENTRIES_ENABLED blocks live order submission
  // (fail-closed — never allow live orders on unknown state).
  const liveRuntime = useKalshiStore(s => s.system.live);
  const executionBlocked = mode === 'live' && liveRuntime?.state !== 'LIVE_ENTRIES_ENABLED';

  // Fills integrity — meta.reconciliation_status captured by the store's
  // shared fills probe (a second useFillToast() here would double-poll the
  // endpoint AND double-fire every fill toast).
  const fillsRecon = useKalshiStore(s => s.portfolio.fills_reconciliation);
  const fillsIntegrityBroken = fillsRecon === 'broken';
  const fillsIntegrityDegraded = fillsRecon === 'degraded';

  // Connectivity from the shared store — no private health poller.
  const storeConnected = useKalshiStore(s => s.connected);
  const storeLastUpdate = useKalshiStore(s => s.lastUpdate);

  const [side, setSide] = useState<Side>(suggestedSide ?? 'yes');
  const [sizeMode, setSizeMode] = useState<SizeMode>('contracts');
  // Contracts are fractional — Kalshi V2 settles on the 0.01-contract grid,
  // matching the strategy's centi-contract sizing.
  const [contracts, setContracts] = useState<number>(suggestedSize ?? 1);
  const [dollarAmount, setDollarAmount] = useState(1);
  const [useLimit, setUseLimit] = useState(false);
  const [limitPrice, setLimitPrice] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // Synchronous in-flight guard — a ref, not state, so a double-click in the
  // same synchronous burst cannot sneak a second submission through before
  // React re-renders the button disabled.
  const submitGuardRef = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const [tradeError, setTradeError] = useState<TradeError | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const retryCountRef = useRef(0);
  // Live-order confirmation: one ConfirmModal ack per order INTENT. Params
  // changing invalidates the ack; retries of the same intent don't re-ask.
  const [confirmOpen, setConfirmOpen] = useState(false);
  const liveConfirmRef = useRef(false);
  // When a submit's outcome is uncertain (network drop/timeout) the guard
  // stays latched until reconciliation proves the order never landed — the
  // operator can override only by explicitly acknowledging manual checks.
  const [uncertainSubmit, setUncertainSubmit] = useState(false);

  const yesOutcome = outcomes.find(o => (o.name ?? '').toLowerCase() === 'yes') ?? outcomes[0];
  const noOutcome = outcomes.find(o => (o.name ?? '').toLowerCase() === 'no') ?? outcomes[1];

  const activeOutcome = side === 'yes' ? yesOutcome : noOutcome;
  // null = no usable price — never substitute a plausible-looking 50¢.
  const priceCents = useMemo<number | null>(() => {
    if (useLimit && limitPrice != null) return limitPrice;
    const p = activeOutcome?.price;
    return typeof p === 'number' && Number.isFinite(p) && p > 0 && p < 1
      ? Math.round(p * 100)
      : null;
  }, [useLimit, limitPrice, activeOutcome]);

  const effectiveContracts = useMemo(() => {
    if (sizeMode === 'contracts') return contracts;
    if (priceCents == null || priceCents <= 0) return 0;
    // Round DOWN to the 0.01-contract grid — never oversize a dollar budget.
    return Math.floor((dollarAmount / (priceCents / 100)) * 100) / 100;
  }, [sizeMode, contracts, dollarAmount, priceCents]);

  const cost = priceCents != null ? (priceCents / 100) * effectiveContracts : 0;
  const maxPayout = effectiveContracts; // $1 per contract
  const maxProfit = maxPayout - cost;
  const fee = priceCents != null ? kalshiFee(priceCents, effectiveContracts) : 0;
  const netProfit = maxProfit - fee;
  const impliedProb = priceCents ?? 0;
  // "vs market": how far the limit price sits from the live own-side quote.
  // Negative = cheaper than market (maker advantage), positive = paying
  // through. Only meaningful for limit orders — a market order IS the quote.
  const marketC = activeOutcome?.price != null && activeOutcome.price > 0 && activeOutcome.price < 1
    ? Math.round(activeOutcome.price * 100)
    : null;
  const vsMarketC = useLimit && marketC != null && priceCents != null ? priceCents - marketC : null;

  const spread = useMemo(() => {
    if (activeOutcome?.bid == null || activeOutcome?.ask == null) return null;
    return Math.round((activeOutcome.ask - activeOutcome.bid) * 100);
  }, [activeOutcome]);

  // A new order intent (different params) invalidates the live-order ack.
  useEffect(() => {
    liveConfirmRef.current = false;
  }, [ticker, side, effectiveContracts, priceCents, mode]);

  const validate = useCallback((): string | null => {
    if (effectiveContracts < 0.01) return 'Size must be at least 0.01 contracts';
    if (priceCents == null) return 'Price unavailable — the venue did not quote this outcome';
    if (priceCents <= 0 || priceCents >= 100) return 'Price must be between 1¢ and 99¢';
    if (useLimit && limitPrice == null) return 'Enter a limit price';
    // Spendable = available cash only — portfolio value cannot collateralize a
    // new order, and Kalshi reserves cost + fee per contract.
    if (enhanced && balance && balance.available < cost + fee) return 'Insufficient balance';
    return null;
  }, [effectiveContracts, priceCents, useLimit, limitPrice, enhanced, balance, cost, fee]);

  /** After an uncertain submit (network drop/timeout), reconcile against the
   *  authoritative order + fill ledgers before allowing any retry. Returns
   *  'landed' when a matching resting order or fill is found, 'absent' when
   *  the order provably never arrived (retry is safe), 'unknown' when the
   *  ledgers themselves can't be read (retry is unsafe — stay latched). */
  const reconcileSubmission = useCallback(async (): Promise<'landed' | 'absent' | 'unknown'> => {
    const freshMs = 150_000; // a match created within 150s is this submit
    const isFresh = (ts?: string | null) => {
      if (!ts) return false;
      const t = Date.parse(ts);
      return Number.isFinite(t) && Date.now() - t < freshMs;
    };
    try {
      const [ordersRes, fillsRes] = await Promise.all([
        getJson<{ orders?: Array<{ ticker?: string; side?: string; created_at?: string | null }> }>(
          API_ENDPOINTS.KALSHI_ORDERS,
        ),
        getJson<{ fills?: Array<{ ticker?: string; side?: string; timestamp?: string; filled_at?: string }> }>(
          `${API_ENDPOINTS.KALSHI_FILLS}?since_hours=1&limit=50`,
        ),
      ]);
      const match = (row: { ticker?: string; side?: string }) =>
        row.ticker === ticker && String(row.side ?? '').toLowerCase() === side;
      const landed =
        (ordersRes.orders ?? []).some((o) => match(o) && isFresh(o.created_at)) ||
        (fillsRes.fills ?? []).some((f) => match(f) && isFresh(f.timestamp ?? f.filled_at));
      return landed ? 'landed' : 'absent';
    } catch {
      return 'unknown';
    }
  }, [ticker, side]);

  /** The actual POST — call only after the live ack (or directly in paper). */
  const executeOrder = useCallback(async () => {
    setSubmitting(true);
    setError(null);
    setTradeError(null);
    setSuccess(null);
    setUncertainSubmit(false);

    try {
      const params = new URLSearchParams({
        ticker,
        side,
        action: 'buy',
        count: String(effectiveContracts),
        price_cents: String(priceCents ?? 0),
        order_type: useLimit ? 'limit' : 'market',
        mode,
      });
      await postJson<unknown>(`${API_ENDPOINTS.KALSHI_ORDERS}?${params}`);

      const msg = `Order placed: ${effectiveContracts} ${side.toUpperCase()} @ ${priceCents}¢`;
      setSuccess(msg);
      retryCountRef.current = 0;
      logUxEvent('trade_ticket_order', mode, {
        ticker,
        side,
        contracts: effectiveContracts,
        price_cents: priceCents,
      });
      onOrderPlaced?.();
      submitGuardRef.current = false;
    } catch (e) {
      const errorMessage = e instanceof Error ? e.message : 'Order submission failed';
      // The request may still have landed exchange-side — reconcile the
      // ledgers before deciding whether a retry is safe. Never release the
      // guard on a timeout alone (the old 15s timer did, enabling dups).
      const outcome = await reconcileSubmission();
      if (outcome === 'landed') {
        setSuccess(`Order confirmed via orders/fills: ${effectiveContracts} ${side.toUpperCase()} @ ${priceCents}¢ — submit response was lost`);
        retryCountRef.current = 0;
        onOrderPlaced?.();
        submitGuardRef.current = false;
      } else if (outcome === 'absent') {
        // No matching resting order or fill — the order never arrived; this
        // intent is safe to retry.
        submitGuardRef.current = false;
        if (enhanced) {
          setTradeError({
            type: errorMessage.includes('network') || errorMessage.includes('timeout') ? 'network' : 'api',
            message: errorMessage,
            recoverable: retryCountRef.current < 2,
          });
          retryCountRef.current += 1;
        } else {
          setError(errorMessage);
        }
      } else {
        // Ledgers unreadable — outcome genuinely unknown. Latch the guard;
        // the operator must verify Open Orders and explicitly re-arm.
        setUncertainSubmit(true);
        setTradeError({
          type: 'network',
          message: `Outcome unknown (${errorMessage}) — check Open Orders before retrying; a blind retry may duplicate a live order.`,
          recoverable: false,
        });
      }
    } finally {
      setSubmitting(false);
    }
  }, [ticker, side, effectiveContracts, priceCents, useLimit, mode, onOrderPlaced, enhanced, reconcileSubmission]);

  const handleSubmit = useCallback(async () => {
    if (submitGuardRef.current) return;

    const err = validate();
    if (err) {
      if (enhanced) {
        setTradeError({ type: 'validation', message: err, recoverable: true });
      } else {
        setError(err);
      }
      return;
    }

    // T-035: Block trading on stale data.  Prefer the live orderbook age
    // (authoritative — catalog rows can be minutes old while the endpoint
    // itself polls fine); fall back to the catalog timestamp only when no
    // book telemetry exists for this market.
    const dataAge = bookAgeMs != null
      ? bookAgeMs
      : lastUpdated
        ? Date.now() - new Date(lastUpdated).getTime()
        : null;
    if (dataAge != null && dataAge > 30_000) {
      const staleMsg = 'Market data is stale (>30s). Refresh before trading.';
      if (enhanced) {
        setTradeError({ type: 'market_closed', message: staleMsg, recoverable: true });
      } else {
        setError(staleMsg);
      }
      return;
    }

    // Live orders confirm via ConfirmModal (consistent with kill-switch /
    // cancel flows); the ack persists for this intent until params change.
    if (mode === 'live' && !liveConfirmRef.current) {
      setConfirmOpen(true);
      return;
    }

    submitGuardRef.current = true;
    void executeOrder();
  }, [validate, mode, lastUpdated, bookAgeMs, enhanced, executeOrder]);

  const handleLiveConfirm = useCallback(() => {
    setConfirmOpen(false);
    liveConfirmRef.current = true;
    if (!submitGuardRef.current) {
      submitGuardRef.current = true;
      void executeOrder();
    }
  }, [executeOrder]);

  /** Operator override after an uncertain submit — only reachable after the
   *  UI has told them to check Open Orders first. */
  const handleVerifyAndRearm = useCallback(() => {
    setUncertainSubmit(false);
    setTradeError(null);
    submitGuardRef.current = false;
  }, []);

  useEffect(() => {
    if (!success) return;
    const t = setTimeout(() => setSuccess(null), DEFAULTS.TIMEOUTS.TOAST);
    return () => clearTimeout(t);
  }, [success]);

  // Connectivity derived from the shared store — no private health poller.
  const networkStatus = !storeConnected
    ? 'offline'
    : (storeLastUpdate > 0 && Date.now() - storeLastUpdate > 45_000 ? 'slow' : 'online');

  const NetworkStatusIndicator = () => (
    <div className="flex items-center gap-1 text-xs">
      {networkStatus === 'offline' && <WifiOff className="w-3 h-3 text-red-400" />}
      {networkStatus === 'slow' && <Clock className="w-3 h-3 text-yellow-400" />}
      <span className={networkStatus === 'online' ? 'text-green-400' : networkStatus === 'slow' ? 'text-yellow-400' : 'text-red-400'}>
        {networkStatus === 'online' ? 'Online' : networkStatus === 'slow' ? 'Slow' : 'Offline'}
      </span>
    </div>
  );

  return (
    <div className="bg-slate-800 rounded-xl p-4 space-y-4">
      <div className="flex justify-between items-center">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">Trade Ticket</h3>
        {enhanced && <NetworkStatusIndicator />}
      </div>

      {/* LEGACY REMOVAL: SentimentBundleCard removed - social sentiment not used in 15m stack */}

      {question && (
        <p className="text-xs text-gray-400 truncate" title={question}>{question}</p>
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
          YES {yesOutcome && <span className="ml-1 font-mono">{yesOutcome.price != null ? `${(yesOutcome.price * 100).toFixed(0)}¢` : '—'}</span>}
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
          NO {noOutcome && <span className="ml-1 font-mono">{noOutcome.price != null ? `${(noOutcome.price * 100).toFixed(0)}¢` : '—'}</span>}
        </button>
      </div>

      {/* Implied Probability Bar */}
      <div className="space-y-1">
        <div className="flex justify-between text-xs text-gray-400">
          <span>Implied Probability</span>
          <span className="font-mono">{priceCents != null ? `${priceCents}%` : 'n/a'}</span>
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
            min={0.01}
            step={0.01}
            value={sizeMode === 'contracts' ? contracts : dollarAmount}
            onChange={(e) => {
              const raw = e.target.value;
              if (raw === '' || raw === '-' || raw === '.') return;
              const v = parseFloat(raw);
              if (!Number.isFinite(v)) return;
              if (sizeMode === 'contracts') setContracts(Math.max(0.01, Math.round(v * 100) / 100));
              else setDollarAmount(Math.max(0.01, v));
            }}
            className="flex-1 bg-slate-700 rounded-lg px-3 py-2 text-sm text-white border border-slate-600 focus:border-orange-500 focus:outline-none font-mono"
            aria-label={sizeMode === 'contracts' ? 'Number of contracts' : 'Dollar amount'}
          />
          {sizeMode === 'dollars' && effectiveContracts > 0 && (
            <span className="text-xs text-gray-500">= {fmtCount(effectiveContracts)} contracts</span>
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
                setLimitPrice(
                  activeOutcome?.price != null && activeOutcome.price > 0 && activeOutcome.price < 1
                    ? Math.round(activeOutcome.price * 100)
                    : null,
                );
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

      {/* Order-group assignment deliberately removed: POST /api/v1/kalshi/orders
          does not accept order_group_id, so the selector silently dropped the
          operator's choice. Re-add only with a backend param. */}

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
            <span className="ml-1 text-[10px] text-gray-600" title="Estimated fee assuming taker order. Actual fees depend on maker/taker status, fill price, and contract count. Kalshi uses a tiered parabolic formula (7%/5%/3% tiers).">
              (est. taker)
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

      {/* vs-market display — how far the limit price sits from the live
          quote, NOT an edge estimate (edge requires a model probability). */}
      {vsMarketC != null && (
        <div className="flex items-center gap-2 text-xs">
          <Info className="w-3.5 h-3.5 text-gray-500" />
          <span className="text-gray-400">vs market:</span>
          <span className={`font-mono ${vsMarketC <= 0 ? 'text-green-400' : 'text-amber-400'}`}>
            {vsMarketC > 0 ? '+' : ''}{vsMarketC}¢
          </span>
          <span className="text-gray-600 text-[10px]">
            {vsMarketC <= 0 ? 'below ask — likely maker' : 'paying through market'}
          </span>
        </div>
      )}

      {/* Error - base mode */}
      {!enhanced && error && (
        <div className="rounded-lg bg-red-500/10 border border-red-500/30 p-3 flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
          <div className="text-sm text-red-300">{error}</div>
        </div>
      )}

      {/* Error - enhanced mode */}
      {enhanced && tradeError && (
        <div className={`rounded-lg border p-3 flex items-start gap-2 ${
          tradeError.recoverable ? 'bg-amber-500/10 border-amber-500/30' : 'bg-red-500/10 border-red-500/30'
        }`}>
          <AlertTriangle className={`w-4 h-4 shrink-0 mt-0.5 ${tradeError.recoverable ? 'text-amber-400' : 'text-red-400'}`} />
          <div className="flex-1">
            <div className={`text-sm ${tradeError.recoverable ? 'text-amber-300' : 'text-red-300'}`}>{tradeError.message}</div>
            {tradeError.recoverable && (
              <button 
                onClick={handleSubmit}
                disabled={submitting}
                className="mt-2 flex items-center gap-1 px-2 py-1 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 text-white text-xs rounded"
              >
                <RefreshCw className={`w-3 h-3 ${submitting ? 'animate-spin' : ''}`} />
                {submitting ? 'Retrying...' : 'Retry'}
              </button>
            )}
          </div>
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

      {/* Pre-submit market context from the live wall agent (5s poll):
          - TTE cutoff: agent-side entry floor — warning only, the manual
            order routes through the router's readiness gate, not the agent's.
          - Readiness veto: the router applies the same is_market_entry_ready
            gate, so a manual order is likely to be rejected while it holds. */}
      {entryCutoffSecs != null && secsToClose != null && secsToClose < entryCutoffSecs && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs"
          title={`New agent entries vetoed below ${Math.round(entryCutoffSecs)}s to expiry`}>
          <Clock className="w-3.5 h-3.5 shrink-0" />
          <span>TTE cutoff passed ({Math.round(entryCutoffSecs)}s) — agent entries vetoed this window</span>
        </div>
      )}
      {marketVetoReason && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 text-xs"
          title={marketVetoDetail ?? marketVetoReason}>
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          <span className="min-w-0">
            Gate: <span className="font-semibold">{reasonLabel(marketVetoReason)}</span>
            {marketVetoDetail && <span className="block truncate text-[10px] text-cyan-400/70 font-mono">{marketVetoDetail}</span>}
          </span>
        </div>
      )}

      {/* Live-book freshness + executability (advisory — the order router
          re-checks readiness authoritatively; these warn before submit). */}
      {bookFresh === false && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs">
          <Clock className="w-3.5 h-3.5 shrink-0" />
          <span>Orderbook stale{bookAgeMs != null ? ` (${Math.round(bookAgeMs / 1000)}s)` : ''} — quotes may be outdated</span>
        </div>
      )}
      {marketExecutable === false && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          <span>Book not executable — entries will be rejected by the readiness gate</span>
        </div>
      )}

      {/* Submit */}
      <button
        type="button"
        onClick={handleSubmit}
        disabled={submitting || submitGuardRef.current || effectiveContracts < 0.01 || priceCents == null || executionBlocked || fillsIntegrityBroken}
        title={fillsIntegrityBroken ? 'Trading disabled: fills reconciliation broken' : executionBlocked ? 'Trading halted: execution gate blocked' : priceCents == null ? 'No venue price for this outcome' : undefined}
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
            Buy {fmtCount(effectiveContracts)} {side.toUpperCase()}
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

      {/* Uncertain-submit re-arm — only after the operator has checked Open
          Orders (a blind retry could duplicate a live order). */}
      {uncertainSubmit && (
        <button
          type="button"
          onClick={handleVerifyAndRearm}
          className="w-full py-1.5 rounded-lg text-xs font-medium bg-slate-700 hover:bg-slate-600 text-gray-300"
        >
          I verified Open Orders — re-enable submit
        </button>
      )}

      <ConfirmModal
        isOpen={confirmOpen}
        title="Confirm LIVE order"
        message={`Buy ${fmtCount(effectiveContracts)} ${side.toUpperCase()} on ${ticker} @ ${priceCents ?? '—'}¢ — cost $${cost.toFixed(2)}, max loss $${cost.toFixed(2)}, net profit if win $${netProfit.toFixed(2)}. Real money at risk.`}
        confirmText="Place live order"
        confirmVariant="danger"
        checklistItems={[{ id: 'ack', label: 'I understand this is a real-money live order' }]}
        onConfirm={handleLiveConfirm}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
};

export default KalshiTradeTicket;
