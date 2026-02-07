import { useEffect, useMemo, useState } from 'react';
import { useApiData } from './useApiData';
import { useMeridSocket } from './useMeridSocket';
import { 
  AgentRow, 
  AgentsResponse, 
  AgentHeartbeatPayload,
  AgentStatusChangedPayload,
  AgentConnectedPayload,
  AgentDisconnectedPayload
} from '../types/agents';

type AgentMap = Record<string, AgentRow>;

/**
 * Merge partial agent update into existing agent
 */
function mergePartialAgent(prev: AgentRow, patch: Partial<AgentRow>): AgentRow {
  return { ...prev, ...patch };
}

/**
 * Validate agent payload has required fields
 */
function isValidAgentPayload(payload: unknown): payload is { id: string } {
  return typeof payload === 'object' && payload !== null && 'id' in payload;
}

/**
 * Hook for agent health data with REST + WebSocket integration
 * 
 * Fetches initial agent list via REST, then keeps it updated via WebSocket events
 */
export function useAgentsHealth() {
  // Fetch initial data via REST
  const { data, loading, error } = useApiData<AgentsResponse>('/api/v1/agents/health', {
    pollingInterval: 30000, // 30s fallback polling
  });
  
  // Local agent state (merged from REST + WS updates)
  const [agents, setAgents] = useState<AgentMap>({});
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Seed from REST response
  useEffect(() => {
    if (!data?.agents) return;
    
    setAgents(
      data.agents.reduce<AgentMap>((acc, agent) => {
        acc[agent.id] = agent;
        return acc;
      }, {})
    );
    setLastUpdated(new Date());
  }, [data?.agents]);

  // WebSocket connection for live updates
  const { socket } = useMeridSocket();

  // Handle WebSocket events
  useEffect(() => {
    if (!socket) return;

    // Heartbeat: partial update of existing agent
    const handleHeartbeat = (payload: AgentHeartbeatPayload) => {
      if (!isValidAgentPayload(payload)) {
        console.warn('[useAgentsHealth] Invalid heartbeat payload:', payload);
        return;
      }
      setAgents((prev) => {
        const existing = prev[payload.id];
        if (!existing) {
          console.warn('[useAgentsHealth] Heartbeat for unknown agent:', payload.id);
          return prev;
        }
        setLastUpdated(new Date());
        return {
          ...prev,
          [payload.id]: mergePartialAgent(existing, payload),
        };
      });
    };

    // Status change: full or partial update
    const handleStatusChanged = (payload: AgentStatusChangedPayload) => {
      if (!isValidAgentPayload(payload)) {
        console.warn('[useAgentsHealth] Invalid status_changed payload:', payload);
        return;
      }
      setAgents((prev) => {
        const existing = prev[payload.id];
        if (!existing) {
          // Agent not in our list yet, create minimal entry
          console.info('[useAgentsHealth] Status change for new agent:', payload.id);
          return {
            ...prev,
            [payload.id]: {
              id: payload.id,
              name: payload.id,
              role: 'SCALPER',
              strategy: 'UNKNOWN',
              cluster: 'unknown',
              status: payload.status,
              cpuPercent: payload.cpuPercent ?? 0,
              memoryMb: payload.memoryMb ?? 0,
              taskCount: payload.taskCount ?? 0,
              latencyMs: payload.latencyMs ?? null,
              lastSeen: payload.lastSeen ?? new Date().toISOString(),
            },
          };
        }
        setLastUpdated(new Date());
        return {
          ...prev,
          [payload.id]: mergePartialAgent(existing, payload),
        };
      });
    };

    // New agent connected: add to map
    const handleConnected = (payload: AgentConnectedPayload) => {
      if (!isValidAgentPayload(payload)) {
        console.warn('[useAgentsHealth] Invalid connected payload:', payload);
        return;
      }
      console.info('[useAgentsHealth] Agent connected:', payload.id);
      setAgents((prev) => ({
        ...prev,
        [payload.id]: payload,
      }));
      setLastUpdated(new Date());
    };

    // Agent disconnected: mark as offline
    const handleDisconnected = (payload: AgentDisconnectedPayload) => {
      if (!isValidAgentPayload(payload)) {
        console.warn('[useAgentsHealth] Invalid disconnected payload:', payload);
        return;
      }
      console.info('[useAgentsHealth] Agent disconnected:', payload.id);
      setAgents((prev) => {
        const existing = prev[payload.id];
        if (!existing) {
          console.warn('[useAgentsHealth] Disconnect for unknown agent:', payload.id);
          return prev;
        }
        setLastUpdated(new Date());
        return {
          ...prev,
          [payload.id]: { ...existing, status: 'OFFLINE' as const },
        };
      });
    };

    const handleError = (error: Error) => {
      console.error('[useAgentsHealth] WebSocket error:', error);
    };

    socket.on('agent:heartbeat', handleHeartbeat);
    socket.on('agent:status_changed', handleStatusChanged);
    socket.on('agent:connected', handleConnected);
    socket.on('agent:disconnected', handleDisconnected);
    socket.on('error', handleError);

    return () => {
      socket.off('agent:heartbeat', handleHeartbeat);
      socket.off('agent:status_changed', handleStatusChanged);
      socket.off('agent:connected', handleConnected);
      socket.off('agent:disconnected', handleDisconnected);
      socket.off('error', handleError);
    };
  }, [socket]);

  // Convert map to sorted array
  const rows: AgentRow[] = useMemo(() => {
    return Object.values(agents).sort((a, b) => {
      // Sort by status priority, then by name
      const statusOrder = { ONLINE: 0, DEGRADED: 1, OFFLINE: 2, UNKNOWN: 3 };
      const aOrder = statusOrder[a.status] ?? 3;
      const bOrder = statusOrder[b.status] ?? 3;
      if (aOrder !== bOrder) return aOrder - bOrder;
      return a.name.localeCompare(b.name);
    });
  }, [agents]);

  // Compute meta from current state (fallback to REST meta if no local updates)
  const meta = useMemo(() => {
    if (data?.meta && Object.keys(agents).length === 0) {
      return data.meta;
    }
    return {
      total: rows.length,
      online: rows.filter((a) => a.status === 'ONLINE').length,
      degraded: rows.filter((a) => a.status === 'DEGRADED').length,
      offline: rows.filter((a) => a.status === 'OFFLINE').length,
    };
  }, [rows, data?.meta, agents]);

  return { rows, meta, loading, error, lastUpdated };
}
