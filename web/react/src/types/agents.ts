// Agent types for MERID dashboard

export type AgentStatus = 'ONLINE' | 'DEGRADED' | 'OFFLINE' | 'UNKNOWN';

export type AgentRole =
  | 'SCALPER'
  | 'ARBITRAGE'
  | 'SNIPER'
  | 'MARKET_MAKER'
  | 'LIQUIDITY_PROVIDER';

export interface AgentRow {
  id: string;
  name: string;
  role: AgentRole;
  strategy: string;
  cluster: string;
  status: AgentStatus;
  cpuPercent: number;
  memoryMb: number;
  taskCount: number;
  latencyMs: number | null;
  lastSeen: string; // ISO 8601
}

export interface AgentsResponse {
  agents: AgentRow[];
  meta: {
    total: number;
    online: number;
    degraded: number;
    offline: number;
  };
}

// WebSocket payload types
export interface AgentHeartbeatPayload {
  id: string;
  cpuPercent?: number;
  memoryMb?: number;
  taskCount?: number;
  latencyMs?: number | null;
  lastSeen?: string;
}

export interface AgentStatusChangedPayload {
  id: string;
  status: AgentStatus;
  cpuPercent?: number;
  memoryMb?: number;
  taskCount?: number;
  latencyMs?: number | null;
  lastSeen?: string;
}

export interface AgentConnectedPayload extends AgentRow {}

export interface AgentDisconnectedPayload {
  id: string;
  status: 'OFFLINE';
}

export type AgentWsPayload =
  | { type: 'agent:heartbeat'; data: AgentHeartbeatPayload }
  | { type: 'agent:status_changed'; data: AgentStatusChangedPayload }
  | { type: 'agent:connected'; data: AgentConnectedPayload }
  | { type: 'agent:disconnected'; data: AgentDisconnectedPayload };
