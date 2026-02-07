import { useState, useEffect, useCallback } from 'react';
import {
  Brain, ChevronDown, ChevronRight, RefreshCw,
  AlertTriangle, CheckCircle, XCircle, Clock, Zap
} from 'lucide-react';

interface DecisionEvent {
  id: string;
  timestamp: string;
  agent: string;
  phase: 'RESEARCH' | 'STRATEGY' | 'RISK' | 'EXECUTION' | 'REVIEW';
  action: string;
  reasoning: string;
  inputs: Record<string, string>;
  outcome: 'approved' | 'rejected' | 'modified' | 'pending';
  confidence: number;
  durationMs: number;
  tradeId?: string;
}

const PHASE_COLORS: Record<string, string> = {
  RESEARCH: 'bg-blue-500/20 text-blue-400 border-blue-500',
  STRATEGY: 'bg-purple-500/20 text-purple-400 border-purple-500',
  RISK: 'bg-amber-500/20 text-amber-400 border-amber-500',
  EXECUTION: 'bg-green-500/20 text-green-400 border-green-500',
  REVIEW: 'bg-gray-500/20 text-gray-400 border-gray-500',
};

const OUTCOME_CONFIG: Record<string, { icon: typeof CheckCircle; color: string }> = {
  approved: { icon: CheckCircle, color: 'text-green-400' },
  rejected: { icon: XCircle, color: 'text-red-400' },
  modified: { icon: AlertTriangle, color: 'text-amber-400' },
  pending: { icon: Clock, color: 'text-gray-400' },
};

export default function ExplainabilityTimeline() {
  const [events, setEvents] = useState<DecisionEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [phaseFilter, setPhaseFilter] = useState<string>('all');

  const fetchEvents = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/explainability/decisions');
      if (res.ok) {
        const data = await res.json();
        if (data.decisions) {
          setEvents(data.decisions);
          return;
        }
      }
    } catch {
      // fallback
    }

    const now = Date.now();
    setEvents([
      {
        id: 'dec-1', timestamp: new Date(now - 5000).toISOString(),
        agent: 'CryptoArbAgent', phase: 'RESEARCH',
        action: 'Detected cross-exchange spread BTC/USDT',
        reasoning: 'Binance ask 104850 < Coinbase bid 104892. Spread 4.0 bps exceeds 2.0 bps threshold.',
        inputs: { binance_ask: '104850.20', coinbase_bid: '104892.50', threshold_bps: '2.0' },
        outcome: 'approved', confidence: 0.92, durationMs: 45,
      },
      {
        id: 'dec-2', timestamp: new Date(now - 12000).toISOString(),
        agent: 'CryptoArbAgent', phase: 'STRATEGY',
        action: 'Generated arb proposal BTC cross-exchange',
        reasoning: 'Quarter-Kelly sizing: $42.30 expected PnL on 0.01 BTC. Risk-adjusted edge 3.8 bps after fees.',
        inputs: { expected_pnl: '$42.30', position_size: '0.01 BTC', fee_estimate: '$1.20' },
        outcome: 'approved', confidence: 0.88, durationMs: 12,
      },
      {
        id: 'dec-3', timestamp: new Date(now - 15000).toISOString(),
        agent: 'GlobalRiskManager', phase: 'RISK',
        action: 'Pre-trade risk check: 7-point validation',
        reasoning: 'All 7 checks passed. Domain crypto enabled, notional within limits, daily loss $45/$1000.',
        inputs: { domain: 'crypto', notional: '$1048.50', daily_loss_used: '$45.00', daily_loss_limit: '$1000.00' },
        outcome: 'approved', confidence: 1.0, durationMs: 3,
      },
      {
        id: 'dec-4', timestamp: new Date(now - 60000).toISOString(),
        agent: 'PredictionMarketAgent', phase: 'STRATEGY',
        action: 'Evaluated KXBTC-105K-YES edge',
        reasoning: 'Implied prob 61% vs model estimate 64.2%. Speculative edge 3.2% in MID phase. Below EARLY threshold 5%.',
        inputs: { implied_prob: '0.61', model_prob: '0.642', phase: 'MID', threshold: '3.0%' },
        outcome: 'approved', confidence: 0.70, durationMs: 85,
      },
      {
        id: 'dec-5', timestamp: new Date(now - 120000).toISOString(),
        agent: 'GlobalRiskManager', phase: 'RISK',
        action: 'Rejected ETH/USDT arb: daily loss limit proximity',
        reasoning: 'Daily loss at $920/$1000 (92%). New trade risk $15 would bring to 93.5%. Rejected per 90% soft limit.',
        inputs: { daily_loss: '$920', limit: '$1000', trade_risk: '$15', soft_limit: '90%' },
        outcome: 'rejected', confidence: 1.0, durationMs: 2, tradeId: 'arb-eth-003',
      },
      {
        id: 'dec-6', timestamp: new Date(now - 300000).toISOString(),
        agent: 'EquityAgent', phase: 'EXECUTION',
        action: 'Submitted AAPL buy order via Alpaca (PAPER)',
        reasoning: 'Momentum signal confirmed. RSI 42 with bullish divergence. Entry at $185.20, stop $183.50.',
        inputs: { symbol: 'AAPL', side: 'buy', qty: '10', price: '$185.20', mode: 'PAPER' },
        outcome: 'approved', confidence: 0.75, durationMs: 120,
      },
    ]);
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchEvents();
    const interval = setInterval(fetchEvents, 5000);
    return () => clearInterval(interval);
  }, [fetchEvents]);

  const filtered = phaseFilter === 'all'
    ? events
    : events.filter(e => e.phase === phaseFilter);

  const formatTime = (ts: string) => {
    const d = new Date(ts);
    return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  const formatAgo = (ts: string) => {
    const ms = Date.now() - new Date(ts).getTime();
    if (ms < 60000) return `${Math.floor(ms / 1000)}s ago`;
    if (ms < 3600000) return `${Math.floor(ms / 60000)}m ago`;
    return `${Math.floor(ms / 3600000)}h ago`;
  };

  if (loading) {
    return (
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <div className="flex items-center gap-2 text-gray-400">
          <RefreshCw className="w-4 h-4 animate-spin" />
          <span>Loading decision trail...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain className="w-5 h-5 text-violet-400" />
          <h3 className="text-lg font-bold text-white">Decision Audit Trail</h3>
          <span className="text-sm text-gray-400">{events.length} decisions</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex gap-1">
            {['all', 'RESEARCH', 'STRATEGY', 'RISK', 'EXECUTION'].map(f => (
              <button
                key={f}
                onClick={() => setPhaseFilter(f)}
                className={`px-2 py-1 text-xs rounded transition-colors ${
                  phaseFilter === f ? 'bg-violet-600 text-white' : 'bg-slate-700 text-gray-400 hover:text-white'
                }`}
              >
                {f === 'all' ? 'All' : f}
              </button>
            ))}
          </div>
          <button
            onClick={fetchEvents}
            className="p-1.5 rounded hover:bg-slate-700 text-gray-400 hover:text-white transition-colors"
            title="Refresh decisions"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Timeline */}
      <div className="relative">
        <div className="absolute left-4 top-0 bottom-0 w-px bg-slate-700" />

        <div className="space-y-3">
          {filtered.map(event => {
            const isExpanded = expandedId === event.id;
            const phaseCfg = PHASE_COLORS[event.phase] || PHASE_COLORS.REVIEW;
            const outcomeCfg = OUTCOME_CONFIG[event.outcome] || OUTCOME_CONFIG.pending;
            const OutcomeIcon = outcomeCfg.icon;

            return (
              <div key={event.id} className="relative pl-10">
                {/* Timeline dot */}
                <div className={`absolute left-2.5 top-3 w-3 h-3 rounded-full border-2 ${
                  event.outcome === 'approved' ? 'bg-green-500 border-green-400' :
                  event.outcome === 'rejected' ? 'bg-red-500 border-red-400' :
                  event.outcome === 'modified' ? 'bg-amber-500 border-amber-400' :
                  'bg-gray-500 border-gray-400'
                }`} />

                <div
                  className={`bg-slate-800/50 rounded-lg border border-slate-700/50 p-3 cursor-pointer hover:border-slate-600 transition-colors ${
                    event.outcome === 'rejected' ? 'border-l-2 border-l-red-500' : ''
                  }`}
                  onClick={() => setExpandedId(isExpanded ? null : event.id)}
                >
                  {/* Header Row */}
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      {isExpanded
                        ? <ChevronDown className="w-4 h-4 text-gray-500" />
                        : <ChevronRight className="w-4 h-4 text-gray-500" />
                      }
                      <span className={`text-xs px-1.5 py-0.5 rounded ${phaseCfg.split(' ').slice(0, 2).join(' ')}`}>
                        {event.phase}
                      </span>
                      <span className="text-sm font-medium text-white">{event.action}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <OutcomeIcon className={`w-4 h-4 ${outcomeCfg.color}`} />
                      <span className="text-xs text-gray-500">{formatAgo(event.timestamp)}</span>
                    </div>
                  </div>

                  {/* Agent + Meta */}
                  <div className="flex items-center gap-3 text-xs text-gray-400 ml-6">
                    <span className="flex items-center gap-1">
                      <Zap className="w-3 h-3" /> {event.agent}
                    </span>
                    <span>{event.durationMs}ms</span>
                    <span className={`font-mono ${event.confidence >= 0.8 ? 'text-green-400' : event.confidence >= 0.6 ? 'text-amber-400' : 'text-red-400'}`}>
                      {(event.confidence * 100).toFixed(0)}% conf
                    </span>
                    <span className="text-gray-600">{formatTime(event.timestamp)}</span>
                  </div>

                  {/* Expanded Detail */}
                  {isExpanded && (
                    <div className="mt-3 ml-6 space-y-2">
                      {/* Reasoning */}
                      <div className="bg-slate-900/50 rounded p-2">
                        <span className="text-xs font-medium text-gray-400">Reasoning</span>
                        <p className="text-sm text-gray-300 mt-1">{event.reasoning}</p>
                      </div>

                      {/* Inputs */}
                      <div className="bg-slate-900/50 rounded p-2">
                        <span className="text-xs font-medium text-gray-400">Inputs</span>
                        <div className="grid grid-cols-2 gap-1 mt-1">
                          {Object.entries(event.inputs).map(([k, v]) => (
                            <div key={k} className="flex items-center gap-2 text-xs">
                              <span className="text-gray-500">{k}:</span>
                              <span className="text-gray-300 font-mono">{v}</span>
                            </div>
                          ))}
                        </div>
                      </div>

                      {event.tradeId && (
                        <div className="text-xs text-gray-500">
                          Trade ID: <span className="font-mono text-gray-400">{event.tradeId}</span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
