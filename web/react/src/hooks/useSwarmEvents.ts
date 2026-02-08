/**
 * useSwarmEvents - Hook for subscribing to MERID swarm events
 * 
 * Subscribes to swarm-specific WebSocket events:
 * - strategy_opinion: Agent opinions
 * - consensus_decision: Consensus formation
 * - trade_intent: Execution intents
 * - order_event: Order execution results
 * - agent_heartbeat: Agent health
 * - watchdog_alert: Monitoring alerts
 * - swarm_telemetry: Aggregate metrics
 * 
 * Usage:
 *   const { opinions, consensus, telemetry } = useSwarmEvents();
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useMeridSocket } from './useMeridSocket';

// ============================================
// TYPES
// ============================================

export interface StrategyOpinion {
  opinion_id: string;
  agent_id: string;
  agent_role: string;
  symbol: string;
  venue: string;
  direction: 'LONG' | 'SHORT' | 'FLAT' | 'REDUCE' | 'CLOSE';
  confidence: number;
  rationale_summary: string;
  signal_strength: number;
  state_version: string;
  price_at_opinion: number;
  timestamp: number;
}

export interface ConsensusDecision {
  consensus_round_id: string;
  symbol: string;
  venue: string;
  decision: 'LONG' | 'SHORT' | 'FLAT' | 'REDUCE' | 'CLOSE';
  size_usd: number;
  confidence: number;
  participating_agents: string[];
  supporting_agents: string[];
  opposing_agents: string[];
  abstaining_agents: string[];
  dissenters: string[];
  dissent_ratio: number;
  consensus_score: number;
  opinion_ids: string[];
  opinion_window_ms: number;
  avg_confidence: number;
  aggregation_method: string;
  timestamp: number;
}

export interface TradeIntent {
  intent_id: string;
  symbol: string;
  side: 'buy' | 'sell' | 'reduce' | 'close';
  quantity: number;
  price: number;
  mode: 'simulation' | 'paper' | 'live';
  consensus_id: string;
  risk_checked: boolean;
  opinion_refs: string[];
  state_version: string;
  confidence: number;
  timestamp: number;
}

export interface OrderEvent {
  order_id: string;
  intent_id: string;
  symbol: string;
  side: 'buy' | 'sell';
  quantity: number;
  filled_quantity: number;
  price: number;
  filled_price: number;
  status: 'pending' | 'filled' | 'partial' | 'rejected' | 'cancelled';
  mode: 'simulation' | 'paper' | 'live';
  simulated: boolean;
  consensus_id: string;
  opinion_ids: string[];
  venue: string;
  timestamp: number;
}

export interface AgentHeartbeat {
  agent_id: string;
  agent_type: string;
  status: 'healthy' | 'degraded' | 'error' | 'offline';
  messages_processed_count: number;
  error_count: number;
  processing_latency_p50_ms: number;
  processing_latency_p99_ms: number;
  current_mode: 'simulation' | 'paper' | 'live';
  timestamp: number;
}

export interface WatchdogAlert {
  alert_id: string;
  watchdog_type: 'liveness' | 'consensus' | 'mode' | 'staleness';
  severity: 'info' | 'warning' | 'critical';
  agent_id?: string;
  symbol?: string;
  message: string;
  details: Record<string, any>;
  timestamp: number;
}

export interface SwarmTelemetry {
  swarm: {
    active_agents: number;
    total_agents: number;
    participation_rate: number;
    opinions_per_minute: number;
    consensus_per_minute: number;
    consensus_success_rate: number;
    avg_disagreement_rate: number;
    high_disagreement_count: number;
    pipeline_latency_ms: number;
  };
  agents: Array<{
    agent_id: string;
    agent_type: string;
    status: string;
    last_heartbeat: number;
    messages_processed: number;
    error_count: number;
    input_lag_ms: number;
    p99_latency_ms: number;
  }>;
  health_issues: Record<string, string>;
}

export interface UseSwarmEventsResult {
  // Event streams
  opinions: StrategyOpinion[];
  consensus: ConsensusDecision[];
  tradeIntents: TradeIntent[];
  orders: OrderEvent[];
  heartbeats: Map<string, AgentHeartbeat>;
  alerts: WatchdogAlert[];
  telemetry: SwarmTelemetry | null;
  
  // Connection state
  connected: boolean;
  error: Error | null;
  
  // Methods
  clear: () => void;
  clearAlerts: () => void;
}

// ============================================
// HOOK IMPLEMENTATION
// ============================================

export function useSwarmEvents(): UseSwarmEventsResult {
  const { socket, connected } = useMeridSocket();
  const [error] = useState<Error | null>(null);
  
  // Event state
  const [opinions, setOpinions] = useState<StrategyOpinion[]>([]);
  const [consensus, setConsensus] = useState<ConsensusDecision[]>([]);
  const [tradeIntents, setTradeIntents] = useState<TradeIntent[]>([]);
  const [orders, setOrders] = useState<OrderEvent[]>([]);
  const [heartbeats, setHeartbeats] = useState<Map<string, AgentHeartbeat>>(new Map());
  const [alerts, setAlerts] = useState<WatchdogAlert[]>([]);
  const [telemetry, setTelemetry] = useState<SwarmTelemetry | null>(null);
  
  // Track registered handlers to avoid duplicates
  const handlersRegistered = useRef(false);
  
  // Subscribe to swarm events via useMeridSocket
  useEffect(() => {
    if (!socket || handlersRegistered.current) return;
    handlersRegistered.current = true;
    
    const handleOpinion = (data: any) => {
      const opinion = data.data || data;
      setOpinions(prev => [opinion, ...prev].slice(0, 100));
    };
    
    const handleConsensus = (data: any) => {
      const decision = data.data || data;
      setConsensus(prev => [decision, ...prev].slice(0, 50));
    };
    
    const handleTradeIntent = (data: any) => {
      const intent = data.data || data;
      setTradeIntents(prev => [intent, ...prev].slice(0, 50));
    };
    
    const handleOrder = (data: any) => {
      const order = data.data || data;
      setOrders(prev => [order, ...prev].slice(0, 50));
    };
    
    const handleHeartbeat = (data: any) => {
      const heartbeat = data.data || data;
      setHeartbeats(prev => {
        const updated = new Map(prev);
        updated.set(heartbeat.agent_id, heartbeat);
        return updated;
      });
    };
    
    const handleAlert = (data: any) => {
      const alert = data.data || data;
      setAlerts(prev => [alert, ...prev].slice(0, 20));
    };
    
    const handleTelemetry = (data: any) => {
      const stats = data.data || data;
      setTelemetry(stats);
    };
    
    socket.on('strategy_opinion', handleOpinion);
    socket.on('consensus_decision', handleConsensus);
    socket.on('trade_intent', handleTradeIntent);
    socket.on('order_event', handleOrder);
    socket.on('agent_heartbeat', handleHeartbeat);
    socket.on('watchdog_alert', handleAlert);
    socket.on('swarm_telemetry', handleTelemetry);
    
    return () => {
      socket.off('strategy_opinion', handleOpinion);
      socket.off('consensus_decision', handleConsensus);
      socket.off('trade_intent', handleTradeIntent);
      socket.off('order_event', handleOrder);
      socket.off('agent_heartbeat', handleHeartbeat);
      socket.off('watchdog_alert', handleAlert);
      socket.off('swarm_telemetry', handleTelemetry);
      handlersRegistered.current = false;
    };
  }, [socket]);
  
  // Clear methods
  const clear = useCallback(() => {
    setOpinions([]);
    setConsensus([]);
    setTradeIntents([]);
    setOrders([]);
    setHeartbeats(new Map());
    setAlerts([]);
    setTelemetry(null);
  }, []);
  
  const clearAlerts = useCallback(() => {
    setAlerts([]);
  }, []);
  
  return {
    opinions,
    consensus,
    tradeIntents,
    orders,
    heartbeats,
    alerts,
    telemetry,
    connected,
    error,
    clear,
    clearAlerts,
  };
}
