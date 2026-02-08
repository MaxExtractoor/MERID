/**
 * useConsensusStream — Single shared connection to the consensus WebSocket.
 *
 * Every component that needs consensus data (ConsensusBoard, DebateTimeline,
 * TradeFloor, AgentOpinionChart) should use this hook instead of opening its
 * own WebSocket.  Internally delegates to useKafkaStream so reconnect logic,
 * deduplication, and backoff are handled in one place.
 *
 * Usage:
 *   const { opinions, plans, lastEvent, connected, status } = useConsensusStream();
 */

import { useMemo } from 'react';
import { useKafkaStream, StreamEvent, UseKafkaStreamOptions } from './useKafkaStream';

// ============================================
// TYPES
// ============================================

export interface ConsensusOpinion {
  opinion_id?: string;
  id?: string;
  agent_id?: string;
  agent?: string;
  role?: string;
  symbol?: string;
  stance?: string;
  position?: string;
  score?: number;
  confidence?: number;
  rationale?: string;
  reasoning?: string;
  horizon?: string;
  timestamp?: number | string;
}

export interface ConsensusTradePlan {
  plan_id?: string;
  id?: string;
  symbol?: string;
  title?: string;
  direction?: string;
  target_size_usd?: number;
  confidence?: number;
  consensus_score?: number;
  supporting_agents?: string[];
  opposing_agents?: string[];
  status: string;
  timestamp?: number;
}

export interface UseConsensusStreamResult {
  /** All parsed consensus events (newest first) */
  events: StreamEvent[];
  /** Opinions extracted from events */
  opinions: ConsensusOpinion[];
  /** Trade plans extracted from events */
  plans: ConsensusTradePlan[];
  /** Latest event of any type */
  lastEvent: StreamEvent | null;
  /** True when WebSocket is open */
  connected: boolean;
  /** Detailed connection status */
  status: 'connecting' | 'connected' | 'disconnected' | 'unavailable' | 'max_retries_exceeded';
  /** Connection error, if any */
  error: Error | null;
  /** Send a message to the server */
  send: (message: any) => void;
  /** Clear all buffered events */
  clear: () => void;
}

// ============================================
// PARSER (shared with useKafkaStream specialisations)
// ============================================

function parseConsensusMessage(data: any): StreamEvent | null {
  let message = data;

  if (typeof data === 'string') {
    try {
      message = JSON.parse(data);
    } catch {
      return null;
    }
  }

  if (!message) return null;

  // Already in StreamEvent shape
  if (message.event_type) {
    return message as StreamEvent;
  }

  // Consensus coordinator format: { type, data, ts? }
  if (message.type && message.data) {
    const payload = message.data;
    const timestamp = message.ts ?? payload.timestamp ?? Date.now() / 1000;

    return {
      event_id:
        payload.opinion_id ||
        payload.plan_id ||
        payload.round_id ||
        `${message.type}_${timestamp}`,
      event_type: message.type,
      timestamp,
      source: 'consensus',
      payload,
    } as StreamEvent;
  }

  return null;
}

// ============================================
// HOOK
// ============================================

const CONSENSUS_OPTIONS: UseKafkaStreamOptions = {
  maxEvents: 200,
  parseMessage: parseConsensusMessage,
};

/**
 * Shared consensus stream hook.
 * Opens exactly one WebSocket to `/api/v1/consensus/ws/stream`.
 */
export function useConsensusStream(): UseConsensusStreamResult {
  const {
    events,
    connected,
    status,
    error,
    send,
    clear,
  } = useKafkaStream('/api/v1/consensus/ws/stream', CONSENSUS_OPTIONS);

  const opinions = useMemo<ConsensusOpinion[]>(
    () =>
      events
        .filter((e) => e.event_type === 'opinion')
        .map((e) => e.payload as unknown as ConsensusOpinion),
    [events],
  );

  const plans = useMemo<ConsensusTradePlan[]>(
    () =>
      events
        .filter((e) => e.event_type === 'trade_plan')
        .map((e) => e.payload as unknown as ConsensusTradePlan),
    [events],
  );

  const lastEvent = events.length > 0 ? events[0] : null;

  return {
    events,
    opinions,
    plans,
    lastEvent,
    connected,
    status,
    error,
    send,
    clear,
  };
}

export default useConsensusStream;
