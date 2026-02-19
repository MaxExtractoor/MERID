import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { 
  Activity, 
  TrendingUp, 
  Zap,
  RefreshCw,
  Users, 
  Bot, 
  User,
  AlertTriangle,
  Clock,
  DollarSign,
  BarChart3,
  Wifi,
  WifiOff,
  Target
} from 'lucide-react';
import ConsensusBoard from '../components/ConsensusBoard';
import DebateTimeline from '../components/DebateTimeline';
import AgentStatusPanel from '../components/AgentStatusPanel';
import SharpeRatioTile from '../components/SharpeRatioTile';
import DrawdownChart from '../components/DrawdownChart';
import AgentPerformanceTable from '../components/AgentPerformanceTable';
import AgentOpinionChart from '../components/charts/AgentOpinionChart';
import { useAgentOpinions } from '../hooks/useKafkaStream';
import { API_ENDPOINTS } from '../config/constants';
import { logUiError } from '../utils/logger';
import type { RawOrderPayload, OpinionEventPayload } from '../types/api';

// Trade event types matching backend schema
interface TradeEvent {
  event_type: string;
  type?: string;
  trader_type: 'human' | 'agent' | 'system';
  trader_id: string;
  timestamp: number;
  venue?: string;
  symbol?: string;
  side?: string;
  qty?: number;
  price?: number;
  status?: string;
  order_id?: string;
  confidence?: number;
  reasoning?: string;
  signal?: string;
  realized_pnl?: number;
  unrealized_pnl?: number;
  mode?: string;
  is_simulated?: boolean;
}

interface RiskSummary {
  total_equity: number;
  total_pnl: number;
  unrealized_pnl: number;
  position_count: number;
  exposure: number;
}

interface AgentOpinionRecord {
  opinion_id: string;
  agent_id: string;
  agent_role: string;
  symbol: string;
  stance: 'strong_bull' | 'bull' | 'neutral' | 'bear' | 'strong_bear';
  score: number;
  confidence: number;
  timestamp: number;
  rationale?: string;
}

export default function TradeFloor() {
  const [events, setEvents] = useState<TradeEvent[]>([]);
  const [orders, setOrders] = useState<TradeEvent[]>([]);
  const [riskSummary, setRiskSummary] = useState<RiskSummary | null>(null);
  const [mode, setMode] = useState<string>('OFFLINE');
  const [isSimulated, setIsSimulated] = useState(true);
  const [wsConnected, setWsConnected] = useState(false);
  const [filter, setFilter] = useState<'all' | 'agents' | 'human'>('all');
  const [viewMode, setViewMode] = useState<'orders' | 'consensus' | 'risk'>('orders');
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [opinionSymbol, setOpinionSymbol] = useState<string>('BTC');
  const wsRef = useRef<WebSocket | null>(null);
  const riskWsRef = useRef<WebSocket | null>(null);
  const tradeRetryCount = useRef(0);
  const riskRetryCount = useRef(0);
  const tradeReconnectTimeout = useRef<NodeJS.Timeout | null>(null);
  const riskReconnectTimeout = useRef<NodeJS.Timeout | null>(null);
  const hasLoggedTradeError = useRef(false);
  const hasLoggedRiskError = useRef(false);
  const mountedRef = useRef(true);
  const [, setTradeWsStatus] = useState<'connecting' | 'connected' | 'disconnected' | 'unavailable'>('disconnected');
  const [, setRiskWsStatus] = useState<'connecting' | 'connected' | 'disconnected' | 'unavailable'>('disconnected');
  const ordersLengthRef = useRef(orders.length);
  const riskSummaryRef = useRef<RiskSummary | null>(riskSummary);

  const MAX_RETRIES = 5;
  const INITIAL_DELAY = 2000;
  const MAX_DELAY = 30000;

  const calculateBackoff = useCallback((attempt: number): number => {
    const baseDelay = Math.min(INITIAL_DELAY * Math.pow(2, attempt), MAX_DELAY);
    const jitter = baseDelay * 0.3 * Math.random();
    return Math.floor(baseDelay + jitter);
  }, []);

  const {
    events: opinionEvents,
    clear: clearOpinions,
  } = useAgentOpinions({ maxEvents: 200 });

  useEffect(() => {
    ordersLengthRef.current = orders.length;
  }, [orders.length]);

  useEffect(() => {
    riskSummaryRef.current = riskSummary;
  }, [riskSummary]);

  // Connect to unified trade events WebSocket with bounded backoff
  useEffect(() => {
    mountedRef.current = true;
    tradeRetryCount.current = 0;
    riskRetryCount.current = 0;

    const connectTradeWs = () => {
      if (!mountedRef.current) return;
      if (tradeRetryCount.current >= MAX_RETRIES) {
        setTradeWsStatus('unavailable');
        return;
      }

      setTradeWsStatus('connecting');
      let opened = false;
      const ws = new WebSocket(`ws://${window.location.host}/ws/trades`);
      
      ws.onopen = () => {
        opened = true;
        setWsConnected(true);
        setTradeWsStatus('connected');
        tradeRetryCount.current = 0;
        hasLoggedTradeError.current = false;
      };

      ws.onmessage = (event) => {
        try {
          const data: TradeEvent = JSON.parse(event.data);
          
          // Check for feature_unavailable
          if (data.event_type === 'feature_unavailable') {
            setTradeWsStatus('unavailable');
            ws.close(1000);
            return;
          }
          
          if (data.event_type === 'heartbeat' || data.type === 'heartbeat') return;
          
          if (data.event_type === 'mode_status' || data.event_type === 'mode_change') {
            setMode(data.mode || 'OFFLINE');
            setIsSimulated(data.is_simulated !== false);
            return;
          }

          // Add to timeline
          setEvents(prev => [data, ...prev].slice(0, 100));

          // Track orders separately
          if (data.event_type?.startsWith('order_')) {
            setOrders(prev => {
              const existing = prev.findIndex(o => o.order_id === data.order_id);
              if (existing >= 0) {
                const updated = [...prev];
                updated[existing] = data;
                return updated;
              }
              return [data, ...prev].slice(0, 50);
            });
          }
        } catch (err) {
          logUiError('TradeFloor', 'WS trade parse error', err);
        }
      };

      ws.onclose = () => {
        wsRef.current = null;
        setWsConnected(false);
        setTradeWsStatus('disconnected');
        
        if (!mountedRef.current) return;
        // If WS never opened, connection itself failed — give up faster
        if (!opened) {
          tradeRetryCount.current += 2;
        }
        if (tradeRetryCount.current < MAX_RETRIES) {
          tradeRetryCount.current++;
          const delay = calculateBackoff(tradeRetryCount.current);
          tradeReconnectTimeout.current = setTimeout(connectTradeWs, delay);
        } else {
          setTradeWsStatus('unavailable');
        }
      };

      ws.onerror = () => {
        hasLoggedTradeError.current = true;
      };

      wsRef.current = ws;
    };

    // Connect to risk WebSocket with bounded backoff
    const connectRiskWs = () => {
      if (!mountedRef.current) return;
      if (riskRetryCount.current >= MAX_RETRIES) {
        setRiskWsStatus('unavailable');
        return;
      }

      setRiskWsStatus('connecting');
      let riskOpened = false;
      const ws = new WebSocket(`ws://${window.location.host}/ws/risk`);
      
      ws.onopen = () => {
        riskOpened = true;
        setRiskWsStatus('connected');
        riskRetryCount.current = 0;
        hasLoggedRiskError.current = false;
      };
      
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          
          // Check for feature_unavailable
          if (data.type === 'feature_unavailable' || data.event_type === 'feature_unavailable') {
            setRiskWsStatus('unavailable');
            ws.close(1000);
            return;
          }
          
          if (data.event_type === 'risk_summary') {
            setRiskSummary({
              total_equity: data.total_equity,
              total_pnl: data.total_pnl,
              unrealized_pnl: data.unrealized_pnl,
              position_count: data.position_count,
              exposure: data.exposure,
            });
          }
        } catch (err) {
          logUiError('TradeFloor', 'WS risk parse error', err);
        }
      };

      ws.onclose = () => {
        riskWsRef.current = null;
        setRiskWsStatus('disconnected');
        
        if (!mountedRef.current) return;
        if (!riskOpened) {
          riskRetryCount.current += 2;
        }
        if (riskRetryCount.current < MAX_RETRIES) {
          riskRetryCount.current++;
          const delay = calculateBackoff(riskRetryCount.current);
          riskReconnectTimeout.current = setTimeout(connectRiskWs, delay);
        } else {
          setRiskWsStatus('unavailable');
        }
      };

      ws.onerror = () => {
        hasLoggedRiskError.current = true;
      };

      riskWsRef.current = ws;
    };

    // REST fallback: fetch initial risk summary + orders if WS unavailable
    const fetchRestFallback = async () => {
      try {
        const [riskRes, ordersRes] = await Promise.all([
          fetch(API_ENDPOINTS.RISK_METRICS),
          fetch(API_ENDPOINTS.ORDERS),
        ]);
        if (riskRes.ok) {
          const risk = await riskRes.json();
          if (!riskSummaryRef.current) {
            setRiskSummary({
              total_equity: risk.portfolioValue || risk.totalExposure || 0,
              total_pnl: risk.totalPnL || 0,
              unrealized_pnl: risk.totalPnL ? risk.totalPnL * 0.3 : 0,
              position_count: Object.keys(risk.exposure || {}).length,
              exposure: risk.totalExposure || 0,
            });
          }
        }
        if (ordersRes.ok) {
          const orderData = await ordersRes.json();
          const orderList = Array.isArray(orderData) ? orderData : (orderData.orders || []);
          if (ordersLengthRef.current === 0 && orderList.length > 0) {
            setOrders(orderList.map((o: RawOrderPayload) => ({
              event_type: 'order_new',
              trader_type: 'agent' as const,
              trader_id: 'system',
              timestamp: Date.now() / 1000,
              symbol: o.symbol,
              side: o.side,
              qty: o.size || o.quantity,
              price: o.price,
              status: o.status,
              order_id: o.id,
              venue: o.venue,
            })));
          }
        }
      } catch (err) { logUiError('TradeFloor', 'REST fallback failed', err); }
    };
    fetchRestFallback();

    connectTradeWs();
    connectRiskWs();

    return () => {
      mountedRef.current = false;
      if (tradeReconnectTimeout.current) clearTimeout(tradeReconnectTimeout.current);
      if (riskReconnectTimeout.current) clearTimeout(riskReconnectTimeout.current);
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.close();
      }
      wsRef.current = null;
      if (riskWsRef.current && riskWsRef.current.readyState === WebSocket.OPEN) {
        riskWsRef.current.close();
      }
      riskWsRef.current = null;
    };
  }, [calculateBackoff]);

  const formatTime = (ts: number) => {
    return new Date(ts * 1000).toLocaleTimeString();
  };

  const formatCurrency = (val: number) => {
    return val.toLocaleString('en-US', { style: 'currency', currency: 'USD' });
  };

  const getEventIcon = (event: TradeEvent) => {
    if (event.trader_type === 'agent') return <Bot className="w-4 h-4 text-purple-400" />;
    if (event.trader_type === 'human') return <User className="w-4 h-4 text-blue-400" />;
    return <Zap className="w-4 h-4 text-yellow-400" />;
  };

  const getEventColor = (event: TradeEvent) => {
    switch (event.event_type) {
      case 'order_filled': return 'text-green-400';
      case 'order_cancelled': 
      case 'order_rejected': return 'text-red-400';
      case 'agent_decision': return 'text-purple-400';
      case 'pnl_update': {
        const pnl = event.realized_pnl ?? 0;
        return pnl >= 0 ? 'text-green-400' : 'text-red-400';
      }
      default: return 'text-gray-400';
    }
  };

  const getSideColor = (side?: string) => {
    if (!side) return 'text-gray-400';
    return side.toLowerCase().includes('buy') || side.toLowerCase().includes('long') 
      ? 'text-green-400' 
      : 'text-red-400';
  };

  const getStatusBadge = (status?: string) => {
    switch (status?.toLowerCase()) {
      case 'filled':
        return <span className="px-2 py-0.5 bg-green-500/20 text-green-400 rounded text-xs">Filled</span>;
      case 'new':
      case 'pending':
        return <span className="px-2 py-0.5 bg-yellow-500/20 text-yellow-400 rounded text-xs">Pending</span>;
      case 'cancelled':
        return <span className="px-2 py-0.5 bg-red-500/20 text-red-400 rounded text-xs">Cancelled</span>;
      case 'partial':
        return <span className="px-2 py-0.5 bg-blue-500/20 text-blue-400 rounded text-xs">Partial</span>;
      default:
        return <span className="px-2 py-0.5 bg-gray-500/20 text-gray-400 rounded text-xs">{status || 'Unknown'}</span>;
    }
  };

  const filteredOrders = orders.filter(o => {
    if (filter === 'all') return true;
    if (filter === 'agents') return o.trader_type === 'agent';
    if (filter === 'human') return o.trader_type === 'human';
    return true;
  });

  const filteredEvents = events.filter(e => {
    if (filter === 'all') return true;
    if (filter === 'agents') return e.trader_type === 'agent';
    if (filter === 'human') return e.trader_type === 'human';
    return true;
  });

  const agentOpinions = useMemo<AgentOpinionRecord[]>(() => {
    return opinionEvents.map((event) => {
      const payload = ((event as { payload?: OpinionEventPayload }).payload || {}) as OpinionEventPayload;
      const stanceValue = typeof payload.stance === 'string' ? payload.stance : 'neutral';
      const normalizedStance = ['strong_bull', 'bull', 'neutral', 'bear', 'strong_bear'].includes(stanceValue)
        ? (stanceValue as AgentOpinionRecord['stance'])
        : 'neutral';

      return {
        opinion_id: payload.opinion_id || event.event_id,
        agent_id: payload.agent_id || 'unknown',
        agent_role: payload.role || payload.agent_role || 'analyst',
        symbol: payload.symbol || 'UNKNOWN',
        stance: normalizedStance,
        score: typeof payload.score === 'number' ? payload.score : 0,
        confidence: typeof payload.confidence === 'number' ? payload.confidence : 0,
        timestamp: payload.timestamp || event.timestamp || Date.now() / 1000,
        rationale: payload.rationale,
      };
    }).filter(opinion => opinion.symbol !== 'UNKNOWN');
  }, [opinionEvents]);

  const opinionSymbols = useMemo(() => {
    return Array.from(new Set(agentOpinions.map(opinion => opinion.symbol)));
  }, [agentOpinions]);

  useEffect(() => {
    if (opinionSymbols.length > 0 && !opinionSymbols.includes(opinionSymbol)) {
      setOpinionSymbol(opinionSymbols[0]);
    }
  }, [opinionSymbols, opinionSymbol]);

  const filteredOpinions = useMemo(() => {
    return agentOpinions.filter(opinion => opinion.symbol === opinionSymbol);
  }, [agentOpinions, opinionSymbol]);

  const opinionSelectDisabled = opinionSymbols.length === 0;

  const isInitialLoad = events.length === 0 && !wsConnected && !riskSummary;

  if (isInitialLoad) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="w-6 h-6 text-blue-400 animate-spin" />
        <span className="ml-3 text-slate-400">Connecting to trade floor…</span>
      </div>
    );
  }

  return (
    <div className="p-4 space-y-4 h-full overflow-hidden flex flex-col">
      {/* Header with Mode Badge */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-3">
          <Activity className="w-8 h-8 text-blue-500" />
          <div>
            <h1 className="text-2xl font-bold text-white">Trade Floor</h1>
            <p className="text-sm text-gray-400">Agents + Humans trading together</p>
          </div>
        </div>
        
        <div className="flex items-center gap-4">
          {/* Connection Status */}
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full ${wsConnected ? 'bg-green-500/20' : 'bg-red-500/20'}`}>
            {wsConnected ? <Wifi className="w-4 h-4 text-green-400" /> : <WifiOff className="w-4 h-4 text-red-400" />}
            <span className={wsConnected ? 'text-green-400' : 'text-red-400'}>
              {wsConnected ? 'Live' : 'Disconnected'}
            </span>
          </div>
          
          {/* Mode Badge */}
          <div className={`px-4 py-2 rounded-lg font-medium ${
            isSimulated 
              ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/50' 
              : 'bg-green-500/20 text-green-400 border border-green-500/50'
          }`}>
            {isSimulated ? '🔶 SIMULATED' : '🟢 LIVE'} - {mode}
          </div>
        </div>
      </div>

      {/* Live Risk Strip */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <div className="bg-slate-800/70 rounded-lg p-4 border border-slate-700/50">
          <div className="flex items-center gap-2 text-gray-400 text-sm mb-1">
            <DollarSign className="w-4 h-4" />
            Total Equity
          </div>
          <div className="text-2xl font-bold text-white">
            {riskSummary ? formatCurrency(riskSummary.total_equity) : '$0.00'}
          </div>
        </div>
        
        <div className="bg-slate-800/70 rounded-lg p-4 border border-slate-700/50">
          <div className="flex items-center gap-2 text-gray-400 text-sm mb-1">
            <TrendingUp className="w-4 h-4" />
            Total P&L
          </div>
          <div className={`text-2xl font-bold ${(riskSummary?.total_pnl || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {riskSummary ? formatCurrency(riskSummary.total_pnl) : '$0.00'}
          </div>
        </div>
        
        <div className="bg-slate-800/70 rounded-lg p-4 border border-slate-700/50">
          <div className="flex items-center gap-2 text-gray-400 text-sm mb-1">
            <BarChart3 className="w-4 h-4" />
            Unrealized P&L
          </div>
          <div className={`text-2xl font-bold ${(riskSummary?.unrealized_pnl || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {riskSummary ? formatCurrency(riskSummary.unrealized_pnl) : '$0.00'}
          </div>
        </div>
        
        <div className="bg-slate-800/70 rounded-lg p-4 border border-slate-700/50">
          <div className="flex items-center gap-2 text-gray-400 text-sm mb-1">
            <Users className="w-4 h-4" />
            Positions
          </div>
          <div className="text-2xl font-bold text-white">
            {riskSummary?.position_count || 0}
          </div>
        </div>
        
        <div className="bg-slate-800/70 rounded-lg p-4 border border-slate-700/50">
          <div className="flex items-center gap-2 text-gray-400 text-sm mb-1">
            <AlertTriangle className="w-4 h-4" />
            Exposure
          </div>
          <div className="text-2xl font-bold text-white">
            {riskSummary ? formatCurrency(riskSummary.exposure) : '$0.00'}
          </div>
        </div>
      </div>

      {/* View Mode Tabs */}
      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          <button type="button"
            onClick={() => setViewMode('orders')}
            className={`px-4 py-2 rounded-lg flex items-center gap-2 transition-colors ${
              viewMode === 'orders'
                ? 'bg-blue-500/20 text-blue-400 border border-blue-500/50'
                : 'bg-slate-800/50 text-gray-400 hover:bg-slate-700/50'
            }`}
          >
            <Activity className="w-4 h-4" />
            Orders & Events
          </button>
          <button type="button"
            onClick={() => setViewMode('consensus')}
            className={`px-4 py-2 rounded-lg flex items-center gap-2 transition-colors ${
              viewMode === 'consensus'
                ? 'bg-purple-500/20 text-purple-400 border border-purple-500/50'
                : 'bg-slate-800/50 text-gray-400 hover:bg-slate-700/50'
            }`}
          >
            <Target className="w-4 h-4" />
            Consensus & Debate
          </button>
          <button type="button"
            onClick={() => setViewMode('risk')}
            className={`px-4 py-2 rounded-lg flex items-center gap-2 transition-colors ${
              viewMode === 'risk'
                ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/50'
                : 'bg-slate-800/50 text-gray-400 hover:bg-slate-700/50'
            }`}
          >
            <BarChart3 className="w-4 h-4" />
            Risk & Performance
          </button>
        </div>

        {/* Filter Tabs (only show for orders view) */}
        {viewMode === 'orders' && (
          <div className="flex gap-2">
            {(['all', 'agents', 'human'] as const).map(f => (
              <button type="button"
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-1.5 rounded-lg flex items-center gap-2 text-sm transition-colors ${
                  filter === f 
                    ? 'bg-blue-500/20 text-blue-400 border border-blue-500/50' 
                    : 'bg-slate-800/50 text-gray-400 hover:bg-slate-700/50'
                }`}
              >
                {f === 'agents' && <Bot className="w-3 h-3" />}
                {f === 'human' && <User className="w-3 h-3" />}
                {f === 'all' && <Users className="w-3 h-3" />}
                {f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Main Content - Split View */}
      <div className="flex-1 grid grid-cols-1 xl:grid-cols-3 gap-4 min-h-0 overflow-hidden">
        {viewMode === 'consensus' ? (
          <>
            {/* Consensus Board (1/3 width) */}
            <div className="bg-slate-900/70 rounded-xl border border-slate-700/50 p-4 overflow-auto">
              <ConsensusBoard />
            </div>
            
            {/* Debate Timeline + Agent Opinions (2/3 width) */}
            <div className="xl:col-span-2 space-y-4 overflow-auto">
              <div className="bg-slate-900/70 rounded-xl border border-slate-700/50 p-4">
                <DebateTimeline />
              </div>
              <div className="flex items-center justify-between text-xs text-slate-400 px-1">
                <span>Opinion focus</span>
                <select
                  id="opinion-symbol"
                  name="opinionSymbol"
                  value={opinionSymbol}
                  onChange={(event) => setOpinionSymbol(event.target.value)}
                  disabled={opinionSelectDisabled}
                  aria-label="Select opinion symbol"
                  title="Select opinion symbol"
                  className="bg-slate-900/70 border border-slate-700/50 rounded px-2 py-1 text-xs text-slate-200 disabled:opacity-60"
                >
                  {(opinionSymbols.length > 0 ? opinionSymbols : [opinionSymbol]).map((symbol) => (
                    <option key={symbol} value={symbol}>
                      {symbol}
                    </option>
                  ))}
                </select>
              </div>
              <AgentOpinionChart
                symbol={opinionSymbol}
                opinions={filteredOpinions}
                showRationale
                onRefresh={() => clearOpinions()}
              />
            </div>
          </>
        ) : viewMode === 'risk' ? (
          <>
            {/* Agent Status Panel (1/3 width) */}
            <div className="overflow-auto">
              <AgentStatusPanel 
                onAgentSelect={(agentId) => setSelectedAgentId(agentId)}
                showMetrics={true}
              />
            </div>
            
            {/* Risk Metrics (2/3 width) */}
            <div className="xl:col-span-2 space-y-4 overflow-auto">
              {/* Top Row: Sharpe and Drawdown */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <SharpeRatioTile 
                  agentId={selectedAgentId || undefined}
                />
                <DrawdownChart 
                  agentId={selectedAgentId || undefined}
                  height={200}
                />
              </div>
              
              {/* Agent Performance Table */}
              <AgentPerformanceTable 
                onAgentSelect={(agentId) => setSelectedAgentId(agentId)}
              />
            </div>
          </>
        ) : (
          <>
            {/* Orders Table (2/3 width) */}
            <div className="xl:col-span-2 bg-slate-900/70 rounded-xl border border-slate-700/50 flex flex-col overflow-hidden">
              <div className="p-4 border-b border-slate-700/50 flex items-center justify-between">
                <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                  <Activity className="w-5 h-5 text-blue-400" />
                  Live Orders
                </h2>
                <span className="text-sm text-gray-400">{filteredOrders.length} orders</span>
              </div>
          
          <div className="flex-1 overflow-auto">
            <table className="w-full">
              <thead className="sticky top-0 bg-slate-800/90 backdrop-blur">
                <tr className="text-left text-sm text-gray-400">
                  <th className="p-3">Type</th>
                  <th className="p-3">Trader</th>
                  <th className="p-3">Venue</th>
                  <th className="p-3">Symbol</th>
                  <th className="p-3">Side</th>
                  <th className="p-3">Qty</th>
                  <th className="p-3">Price</th>
                  <th className="p-3">Status</th>
                  <th className="p-3">Time</th>
                </tr>
              </thead>
              <tbody>
                {filteredOrders.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="p-8 text-center text-gray-500">
                      <Clock className="w-8 h-8 mx-auto mb-2 opacity-50" />
                      <p>Waiting for orders...</p>
                      <p className="text-sm">Orders will appear here when agents or humans trade</p>
                    </td>
                  </tr>
                ) : (
                  filteredOrders.map((order, idx) => (
                    <tr key={order.order_id || idx} className="border-t border-slate-700/30 hover:bg-slate-800/50">
                      <td className="p-3">{getEventIcon(order)}</td>
                      <td className="p-3 font-mono text-sm">{order.trader_id}</td>
                      <td className="p-3 text-gray-400">{order.venue || '-'}</td>
                      <td className="p-3 font-medium text-white">{order.symbol || '-'}</td>
                      <td className={`p-3 font-medium ${getSideColor(order.side)}`}>
                        {order.side?.toUpperCase() || '-'}
                      </td>
                      <td className="p-3 text-gray-300">{order.qty?.toFixed(4) || '-'}</td>
                      <td className="p-3 text-gray-300">{order.price ? `$${order.price.toLocaleString()}` : '-'}</td>
                      <td className="p-3">{getStatusBadge(order.status)}</td>
                      <td className="p-3 text-gray-500 text-sm">{formatTime(order.timestamp)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Timeline (1/3 width) */}
        <div className="bg-slate-900/70 rounded-xl border border-slate-700/50 flex flex-col overflow-hidden">
          <div className="p-4 border-b border-slate-700/50">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <Zap className="w-5 h-5 text-yellow-400" />
              Event Timeline
            </h2>
          </div>
          
          <div className="flex-1 overflow-auto p-2">
            {filteredEvents.length === 0 ? (
              <div className="p-8 text-center text-gray-500">
                <Activity className="w-8 h-8 mx-auto mb-2 opacity-50 animate-pulse" />
                <p>Waiting for events...</p>
              </div>
            ) : (
              <div className="space-y-2">
                {filteredEvents.map((event, idx) => (
                  <div 
                    key={`${event.timestamp}-${idx}`}
                    className="p-3 bg-slate-800/50 rounded-lg border border-slate-700/30 hover:border-slate-600/50 transition-colors"
                  >
                    <div className="flex items-center gap-2 mb-1">
                      {getEventIcon(event)}
                      <span className="font-medium text-white text-sm">{event.trader_id}</span>
                      <span className="text-gray-500 text-xs ml-auto">{formatTime(event.timestamp)}</span>
                    </div>
                    
                    <div className={`text-sm ${getEventColor(event)}`}>
                      {event.event_type === 'agent_decision' && (
                        <>
                          <span className="font-medium">{event.signal?.toUpperCase()}</span>
                          {event.symbol && <span> on {event.symbol}</span>}
                          {event.confidence && <span className="text-gray-400"> ({(event.confidence * 100).toFixed(0)}%)</span>}
                        </>
                      )}
                      
                      {event.event_type?.startsWith('order_') && (
                        <>
                          <span className="font-medium">{event.event_type.replace('order_', '').toUpperCase()}</span>
                          {event.symbol && <span> {event.side} {event.symbol}</span>}
                          {event.qty && <span> x{event.qty}</span>}
                          {event.price && <span> @ ${event.price.toLocaleString()}</span>}
                        </>
                      )}
                      
                      {event.event_type === 'pnl_update' && (
                        <>
                          P&L: {formatCurrency(event.realized_pnl || 0)}
                          <span className="text-gray-400"> (Unrealized: {formatCurrency(event.unrealized_pnl || 0)})</span>
                        </>
                      )}
                      
                      {event.event_type === 'mode_change' && (
                        <>Mode changed to <span className="font-medium">{event.mode}</span></>
                      )}
                    </div>
                    
                    {event.reasoning && (
                      <p className="text-xs text-gray-500 mt-1 line-clamp-2">{event.reasoning}</p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
          </>
        )}
      </div>
    </div>
  );
}
