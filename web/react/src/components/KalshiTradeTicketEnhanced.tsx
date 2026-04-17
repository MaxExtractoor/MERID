/**
 * Enhanced KalshiTradeTicket with improved error handling and loading states
 * 
 * Fixes:
 * - Loading spinners during order submission
 * - Better error categorization and recovery
 * - Network timeout handling
 * - Input validation feedback
 * - Graceful degradation on API failures
 */

import { useState, useMemo, useCallback, useEffect, useRef, memo } from 'react';
import {
  AlertTriangle, CheckCircle, Info,
  ArrowRight, Loader2, RefreshCw, WifiOff, Clock,
} from '../ui/icons';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS, AUTH_TOKEN_KEY } from '../config/constants';
import { logUxEvent } from '../utils/uxTelemetry';
import { SentimentBundleCard } from './SentimentBundleCard';

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
  orderGroupId?: string;
  availableGroups?: Array<{
    order_group_id: string;
    name: string;
    status: 'active' | 'triggered' | 'canceled' | 'pending';
    utilization_pct: number;
  }>;
  lastUpdated?: string | number;
  balance?: { available: number; total: number };
}

type ErrorType = 'validation' | 'network' | 'api' | 'insufficient_balance' | 'market_closed';
type LoadingState = 'idle' | 'validating' | 'submitting' | 'fetching_balance' | 'checking_limits';

interface TradeError {
  type: ErrorType;
  message: string;
  recoverable: boolean;
  retryAction?: () => void;
}

export const EnhancedKalshiTradeTicket = memo<TradeTicketProps>(({
  ticker,
  question: _question,
  outcomes,
  onOrderPlaced,
  suggestedSize,
  suggestedSide,
  mode = 'paper',
  kellyFraction: _kellyFraction,
  positionLimitPct: _positionLimitPct,
  orderGroupId,
  availableGroups = [],
  lastUpdated,
  balance,
}) => {
  // Enhanced state management
  const [side, setSide] = useState<'yes' | 'no'>(suggestedSide || 'yes');
  const [contracts, setContracts] = useState<string>(suggestedSize?.toString() || '1');
  const [useLimit, setUseLimit] = useState(false);
  const [limitPrice, setLimitPrice] = useState<string>('');
  const [selectedGroupId, setSelectedGroupId] = useState(orderGroupId || '');
  const [loadingState, setLoadingState] = useState<LoadingState>('idle');
  const [tradeError, setTradeError] = useState<TradeError | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [networkStatus, setNetworkStatus] = useState<'online' | 'offline' | 'slow'>('online');

  // Refs for timeout management
  const submitTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const retryCountRef = useRef(0);

  // Network status monitoring
  useEffect(() => {
    const checkNetworkStatus = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/health`, { 
          method: 'HEAD',
          signal: AbortSignal.timeout(3000)
        });
        setNetworkStatus(response.ok ? 'online' : 'slow');
      } catch {
        setNetworkStatus('offline');
      }
    };

    checkNetworkStatus();
    const interval = setInterval(checkNetworkStatus, 30000);
    return () => clearInterval(interval);
  }, []);

  // Enhanced validation with detailed feedback
  const validate = useCallback((): TradeError | null => {
    setLoadingState('validating');
    
    try {
      const contractsNum = parseInt(contracts);
      if (!contracts || contractsNum < 1) {
        return {
          type: 'validation',
          message: 'Contracts must be at least 1',
          recoverable: true
        };
      }
      if (contractsNum > 10000) {
        return {
          type: 'validation', 
          message: 'Contracts exceed maximum (10,000)',
          recoverable: true
        };
      }

      if (useLimit) {
        const priceNum = parseInt(limitPrice);
        if (!limitPrice || priceNum < 1 || priceNum > 99) {
          return {
            type: 'validation',
            message: 'Limit price must be 1-99 cents',
            recoverable: true
          };
        }
      }

      // Balance check
      if (balance && balance.available < contractsNum * 0.01) {
        return {
          type: 'insufficient_balance',
          message: `Insufficient balance. Available: $${balance.available.toFixed(2)}`,
          recoverable: false
        };
      }

      // Market freshness check
      if (lastUpdated) {
        const lastUpdate = typeof lastUpdated === 'string' 
          ? new Date(lastUpdated).getTime() 
          : lastUpdated * 1000;
        const staleThreshold = 5 * 60 * 1000; // 5 minutes
        if (Date.now() - lastUpdate > staleThreshold) {
          return {
            type: 'market_closed',
            message: 'Market data is stale. Please refresh.',
            recoverable: true,
            retryAction: () => window.location.reload()
          };
        }
      }

      return null;
    } finally {
      setLoadingState('idle');
    }
  }, [contracts, useLimit, limitPrice, balance, lastUpdated]);

  // Enhanced order submission with timeout and retry
  const submitOrder = useCallback(async () => {
    const validationError = validate();
    if (validationError) {
      setTradeError(validationError);
      return;
    }

    setLoadingState('submitting');
    setTradeError(null);
    
    const contractsNum = parseInt(contracts);
    const priceCents = useLimit ? parseInt(limitPrice) : (side === 'yes' ? outcomes[0].ask : outcomes[1].bid) || 50;
    const effectiveContracts = contractsNum * (useLimit ? 1 : 2); // Market orders double

    const token = localStorage.getItem(AUTH_TOKEN_KEY);
    
    // Clear any existing timeout
    if (submitTimeoutRef.current) {
      clearTimeout(submitTimeoutRef.current);
    }

    // Set submission timeout
    submitTimeoutRef.current = setTimeout(() => {
      setTradeError({
        type: 'network',
        message: 'Order submission timed out. Please check your connection.',
        recoverable: true,
        retryAction: submitOrder
      });
      setLoadingState('idle');
    }, 15000); // 15 second timeout

    try {
      const params = new URLSearchParams({
        ticker,
        action: 'buy',
        side,
        count: String(contractsNum),
        price_cents: String(priceCents),
        order_type: useLimit ? 'limit' : 'market',
        mode,
        ...(selectedGroupId ? { order_group_id: selectedGroupId } : {}),
      });
      const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_ORDERS}?${params}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
        },
        signal: AbortSignal.timeout(12000), // 12 second fetch timeout
      });

      if (submitTimeoutRef.current) {
        clearTimeout(submitTimeoutRef.current);
        submitTimeoutRef.current = null;
      }

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        
        throw new Error(data.detail || `Order failed (${response.status})`);
      }

      const msg = `Order placed: ${effectiveContracts} ${(side ?? '').toUpperCase()} @ ${priceCents}¢`;
      setSuccess(msg);
      logUxEvent('trade_ticket_order', mode, {
        ticker,
        side,
        contracts: effectiveContracts,
        price_cents: priceCents,
        order_group_id: selectedGroupId,
      });
      onOrderPlaced?.();
      retryCountRef.current = 0; // Reset retry count on success
      
    } catch (error) {
      if (submitTimeoutRef.current) {
        clearTimeout(submitTimeoutRef.current);
        submitTimeoutRef.current = null;
      }

      const errorMessage = error instanceof Error ? error.message : 'Order submission failed';
      
      setTradeError({
        type: errorMessage.includes('network') || errorMessage.includes('timeout') ? 'network' : 'api',
        message: errorMessage,
        recoverable: retryCountRef.current < 2, // Allow up to 2 retries
        retryAction: retryCountRef.current < 2 ? submitOrder : undefined
      });
      
      retryCountRef.current += 1;
    } finally {
      setLoadingState('idle');
    }
  }, [validate, ticker, side, contracts, useLimit, limitPrice, outcomes, mode, onOrderPlaced, selectedGroupId, balance]);

  // Balance refresh
  const refreshBalance = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const response = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_BALANCE}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: AbortSignal.timeout(5000),
      });
      
      if (response.ok) {
        await response.json();
        logUxEvent('balance_refresh', mode);
      }
    } catch (error) {
      console.warn('Failed to refresh balance:', error);
    } finally {
      setIsRefreshing(false);
    }
  }, [mode]);

  // Calculations (same as original)
  const { cost, fee, maxPayout, netProfit, edgePct } = useMemo(() => {
    const contractsNum = parseInt(contracts) || 0;
    const priceCents = useLimit ? parseInt(limitPrice) : (side === 'yes' ? outcomes[0].ask : outcomes[1].bid) || 50;
    const baseCost = contractsNum * 0.01;
    const profit = side === 'yes' ? (100 - priceCents) * contractsNum * 0.01 : priceCents * contractsNum * 0.01;
    const calcFee = profit > 0 ? profit * 0.07 : 0;
    const payout = profit > 0 ? profit + baseCost : baseCost;
    
    return {
      cost: baseCost,
      fee: calcFee,
      maxPayout: payout,
      netProfit: profit - calcFee,
      edgePct: side === 'yes' ? ((100 - priceCents) - 50) : (priceCents - 50),
    };
  }, [contracts, useLimit, limitPrice, side, outcomes]);

  // Clear success message
  useEffect(() => {
    if (!success) return;
    const t = setTimeout(() => setSuccess(null), DEFAULTS.TIMEOUTS.TOAST);
    return () => clearTimeout(t);
  }, [success]);

  // Network status indicator
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
        <NetworkStatusIndicator />
      </div>

      {/* Sentiment Indicator */}
      {['BTC', 'ETH', 'SOL', 'XRP', 'DOGE'].some(a => ticker?.toUpperCase?.().includes(a)) && (
        <div className="mb-4">
          <SentimentBundleCard asset={['BTC','ETH','SOL','XRP','DOGE'].find(a => ticker?.toUpperCase?.().includes(a)) ?? 'BTC'} compact />
        </div>
      )}

      {/* Balance Display with Refresh */}
      {balance && (
        <div className="flex justify-between items-center p-2 bg-slate-700/50 rounded-lg">
          <div className="text-xs">
            <span className="text-gray-400">Available: </span>
            <span className="text-white font-mono">${balance.available.toFixed(2)}</span>
          </div>
          <button
            onClick={refreshBalance}
            disabled={isRefreshing}
            className="p-1 text-gray-400 hover:text-white transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3 h-3 ${isRefreshing ? 'animate-spin' : ''}`} />
          </button>
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
              : 'bg-slate-700 text-gray-400 hover:bg-slate-600'
          }`}
        >
          YES
        </button>
        <button
          type="button"
          onClick={() => setSide('no')}
          className={`flex-1 py-2.5 text-sm font-bold transition-all ${
            side === 'no'
              ? 'bg-red-600 text-white'
              : 'bg-slate-700 text-gray-400 hover:bg-slate-600'
          }`}
        >
          NO
        </button>
      </div>

      {/* Size Input */}
      <div>
        <label className="block text-xs text-gray-400 mb-1">Size (contracts)</label>
        <input
          type="number"
          min="1"
          max="10000"
          value={contracts}
          onChange={(e) => setContracts(e.target.value)}
          className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
          disabled={loadingState !== 'idle'}
        />
      </div>

      {/* Limit Price Toggle */}
      <div className="flex items-center justify-between">
        <label className="flex items-center gap-2 text-sm text-gray-300">
          <input
            type="checkbox"
            checked={useLimit}
            onChange={(e) => setUseLimit(e.target.checked)}
            className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
            disabled={loadingState !== 'idle'}
          />
          Use limit price
        </label>
        {useLimit && (
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <span>Current:</span>
            <span className="font-mono">
              {side === 'yes' ? outcomes[0].ask || '--' : outcomes[1].bid || '--'}¢
            </span>
          </div>
        )}
      </div>

      {/* Limit Price Input */}
      {useLimit && (
        <div>
          <label className="block text-xs text-gray-400 mb-1">Limit price (cents)</label>
          <input
            type="number"
            min="1"
            max="99"
            value={limitPrice}
            onChange={(e) => setLimitPrice(e.target.value)}
            className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            disabled={loadingState !== 'idle'}
          />
        </div>
      )}

      {/* Order Group Selection */}
      {availableGroups.length > 0 && (
        <div>
          <label className="block text-xs text-gray-400 mb-1">Order Group (optional)</label>
          <select
            value={selectedGroupId}
            onChange={(e) => setSelectedGroupId(e.target.value)}
            className="w-full px-3 py-2 bg-slate-700 border border-slate-600 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            disabled={loadingState !== 'idle'}
          >
            <option value="">No group</option>
            {availableGroups.map(group => (
              <option key={group.order_group_id} value={group.order_group_id}>
                {group.name} ({group.utilization_pct.toFixed(1)}% used)
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Cost Summary */}
      <div className="space-y-2 p-3 bg-slate-700/30 rounded-lg">
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

      {/* Enhanced Error Display */}
      {tradeError && (
        <div className={`flex items-start gap-2 px-3 py-2 rounded-lg border text-xs ${
          tradeError.type === 'insufficient_balance' || tradeError.type === 'market_closed'
            ? 'bg-red-500/10 border-red-500/30 text-red-400'
            : tradeError.type === 'network'
            ? 'bg-yellow-500/10 border-yellow-500/30 text-yellow-400'
            : 'bg-blue-500/10 border-blue-500/30 text-blue-400'
        }`}>
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <div className="flex-1">
            <span>{tradeError.message}</span>
            {tradeError.recoverable && tradeError.retryAction && (
              <button
                onClick={tradeError.retryAction}
                className="ml-2 underline hover:no-underline"
              >
                Retry
              </button>
            )}
          </div>
        </div>
      )}

      {/* Success Display */}
      {success && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-green-500/10 border border-green-500/30 text-green-400 text-xs">
          <CheckCircle className="w-3.5 h-3.5 shrink-0" />
          <span>{success}</span>
        </div>
      )}

      {/* Submit Button with Loading State */}
      <button
        onClick={submitOrder}
        disabled={loadingState !== 'idle' || networkStatus === 'offline'}
        className="w-full py-3 px-4 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-700 disabled:opacity-50 text-white font-medium rounded-lg transition-colors flex items-center justify-center gap-2"
      >
        {loadingState === 'submitting' ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            <span>Submitting...</span>
          </>
        ) : loadingState === 'validating' ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            <span>Validating...</span>
          </>
        ) : networkStatus === 'offline' ? (
          <>
            <WifiOff className="w-4 h-4" />
            <span>Offline</span>
          </>
        ) : (
          <>
            <ArrowRight className="w-4 h-4" />
            <span>Place Order</span>
          </>
        )}
      </button>
    </div>
  );
});

EnhancedKalshiTradeTicket.displayName = 'EnhancedKalshiTradeTicket';
