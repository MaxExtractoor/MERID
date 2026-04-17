// @ts-nocheck - Install zod package for full type checking
/**
 * API contract validation schemas using Zod
 * Ensures runtime type safety for API requests and responses
 */

import { z } from 'zod';

// ── Common Schemas ─────────────────────────────────────────────────────────

export const TimestampSchema = z.union([
  z.string().datetime(),
  z.number(),
]);

export const UUIDSchema = z.string().uuid();

export const MoneySchema = z.number().int().min(0);

export const PercentageSchema = z.number().min(0).max(100);

// ── Kalshi API Schemas ─────────────────────────────────────────────────────

export const KalshiMarketSchema = z.object({
  ticker: z.string(),
  title: z.string(),
  status: z.enum(['active', 'closed', 'settled']),
  yes_bid: z.number().min(1).max(99),
  yes_ask: z.number().min(1).max(99),
  no_bid: z.number().min(1).max(99),
  no_ask: z.number().min(1).max(99),
  volume: z.number().int().min(0),
  open_interest: z.number().int().min(0),
  settlement_value: z.number().optional(),
  event_ticker: z.string(),
  close_time: TimestampSchema.optional(),
});

export const KalshiPositionSchema = z.object({
  ticker: z.string(),
  side: z.enum(['yes', 'no']),
  count: z.number().int(),
  avg_price_cents: z.number().int().min(1).max(99),
  market_title: z.string().optional(),
  unrealized_pnl: z.number().optional(),
});

export const KalshiOrderSchema = z.object({
  order_id: z.string(),
  ticker: z.string(),
  side: z.enum(['yes', 'no']),
  action: z.enum(['buy', 'sell']),
  status: z.enum(['pending', 'open', 'filled', 'cancelled', 'rejected']),
  count: z.number().int().positive(),
  filled_count: z.number().int().min(0),
  remaining_count: z.number().int().min(0),
  price_cents: z.number().int().min(1).max(99),
  order_type: z.enum(['market', 'limit']),
  created_at: TimestampSchema,
  updated_at: TimestampSchema.optional(),
  fill_ids: z.array(z.string()).optional(),
});

export const KalshiFillSchema = z.object({
  fill_id: z.string(),
  order_id: z.string(),
  ticker: z.string(),
  side: z.enum(['yes', 'no']),
  count: z.number().int().positive(),
  price_cents: z.number().int().min(1).max(99),
  filled_at: TimestampSchema,
  fee_cents: z.number().int().min(0),
});

export const KalshiBalanceSchema = z.object({
  available: z.number().min(0),
  total: z.number().min(0),
  pending_deposits: z.number().min(0).optional(),
  pending_withdrawals: z.number().min(0).optional(),
});

// ── System Health Schemas ─────────────────────────────────────────────────

export const ServiceHealthSchema = z.object({
  status: z.enum(['healthy', 'degraded', 'unhealthy']),
  last_check: z.number(),
  latency_ms: z.number().optional(),
  error_count: z.number().int().min(0).optional(),
});

export const SystemHealthSchema = z.object({
  status: z.enum(['healthy', 'degraded', 'unhealthy']),
  timestamp: z.number(),
  environment: z.string(),
  incident_flag: z.boolean(),
  services: z.record(ServiceHealthSchema),
  version: z.string().optional(),
});

// ── Risk & Circuit Breaker Schemas ─────────────────────────────────────────

export const CircuitBreakerSchema = z.object({
  state: z.enum(['CLOSED', 'OPEN', 'HALF_OPEN']),
  state_color: z.string(),
  error_count: z.number().int().min(0),
  window_seconds: z.number().int().positive(),
  threshold: z.number().int().positive(),
  last_error_at: z.string().nullable(),
  opened_at: z.string().nullable(),
  cooldown_seconds: z.number().int().positive(),
  half_open_successes: z.number().int().min(0),
});

export const LockdownSchema = z.object({
  trading_suite_enabled: z.boolean(),
  global_mode: z.enum(['paper', 'live', 'shadow']),
  spectator_mode: z.boolean(),
  lockdown_reason: z.string().nullable(),
});

export const RiskLimitsSchema = z.object({
  max_daily_loss_usd: z.number().positive(),
  current_daily_pnl: z.number(),
  daily_loss_utilization_pct: PercentageSchema,
  max_per_symbol_exposure_usd: z.number().positive(),
  max_open_orders: z.number().int().positive(),
  current_open_orders: z.number().int().min(0),
});

export const RiskEventSchema = z.object({
  timestamp: z.string(),
  type: z.string(),
  details: z.record(z.unknown()),
});

export const RiskProtectionsSchema = z.object({
  timestamp: z.string(),
  circuit_breaker: CircuitBreakerSchema,
  lockdown: LockdownSchema,
  risk_limits: RiskLimitsSchema,
  recent_events: z.array(RiskEventSchema),
});

// ── Grid & Agent Schemas ───────────────────────────────────────────────────

export const GridCellSchema = z.object({
  row: z.number().int(),
  col: z.number().int(),
  status: z.enum(['idle', 'running', 'paused', 'error']),
  ticker: z.string().optional(),
  signal_count: z.number().int().min(0).optional(),
  last_signal: TimestampSchema.optional(),
});

export const GridStatusSchema = z.object({
  running: z.boolean(),
  mode: z.enum(['paper', 'live']),
  mode_enabled: z.boolean(),
  cells: z.array(GridCellSchema),
  last_tick: TimestampSchema.optional(),
});

export const AgentSchema = z.object({
  id: z.string(),
  name: z.string(),
  status: z.enum(['running', 'paused', 'stopped', 'error']),
  strategy: z.string(),
  state: z.string(),
  heartbeat_age_ms: z.number().min(0),
  positions_count: z.number().int().min(0),
  today_pnl: z.number(),
  tasks_completed: z.number().int().min(0),
  uptime: z.number().min(0),
});

export const AgentSummarySchema = z.object({
  total_agents: z.number().int().min(0),
  active_agents: z.number().int().min(0),
  idle_agents: z.number().int().min(0),
  tasks_completed: z.number().int().min(0),
  tasks_pending: z.number().int().min(0),
  average_response_time: z.number().min(0),
  success_rate: z.number().min(0).max(100),
  agents: z.array(AgentSchema),
  summary: z.object({
    total: z.number().int().min(0),
    healthy: z.number().int().min(0),
    paused: z.number().int().min(0),
    unhealthy: z.number().int().min(0),
  }),
});

// ── P&L Schemas ──────────────────────────────────────────────────────────

export const PnLSummarySchema = z.object({
  today_pnl: z.number(),
  today_pnl_pct: z.number(),
  mtm_pnl: z.number(),
  max_drawdown: z.number(),
  max_drawdown_pct: z.number(),
  limit_daily_loss: z.number().positive(),
  limit_utilization_pct: PercentageSchema,
});

// ── Execution Gate Schemas ────────────────────────────────────────────────

export const ExecutionGateReasonSchema = z.object({
  severity: z.enum(['critical', 'warning', 'info']),
  message: z.string(),
  hint: z.string().optional(),
  category: z.string().optional(),
});

export const ExecutionGateSchema = z.object({
  blocked: z.boolean(),
  safe_to_trade: z.boolean(),
  gate_state: z.enum(['blocked', 'limited', 'clear']),
  reasons: z.array(ExecutionGateReasonSchema),
  last_updated: TimestampSchema,
});

// ── Validator Functions ──────────────────────────────────────────────────

export function validateApiResponse<T>(
  schema: z.ZodSchema<T>,
  data: unknown
): { success: true; data: T } | { success: false; errors: z.ZodError } {
  const result = schema.safeParse(data);
  
  if (result.success) {
    return { success: true, data: result.data };
  }
  
  return { success: false, errors: result.error };
}

/**
 * Log validation errors for debugging
 */
export function logValidationErrors(
  endpoint: string,
  error: z.ZodError,
  rawData: unknown
): void {
  console.error(`API validation failed for ${endpoint}:`, {
    errors: error.errors.map((e) => ({
      path: e.path.join('.'),
      message: e.message,
      value: e.path.reduce((obj: unknown, key: string | number) => {
        if (obj && typeof obj === 'object') {
          return (obj as Record<string | number, unknown>)[key];
        }
        return undefined;
      }, rawData),
    })),
    rawDataPreview: JSON.stringify(rawData).slice(0, 200),
  });
}

// ── Type Exports ─────────────────────────────────────────────────────────

export type KalshiMarket = z.infer<typeof KalshiMarketSchema>;
export type KalshiPosition = z.infer<typeof KalshiPositionSchema>;
export type KalshiOrder = z.infer<typeof KalshiOrderSchema>;
export type KalshiFill = z.infer<typeof KalshiFillSchema>;
export type KalshiBalance = z.infer<typeof KalshiBalanceSchema>;
export type SystemHealth = z.infer<typeof SystemHealthSchema>;
export type CircuitBreaker = z.infer<typeof CircuitBreakerSchema>;
export type RiskProtections = z.infer<typeof RiskProtectionsSchema>;
export type GridStatus = z.infer<typeof GridStatusSchema>;
export type Agent = z.infer<typeof AgentSchema>;
export type AgentSummary = z.infer<typeof AgentSummarySchema>;
export type PnLSummary = z.infer<typeof PnLSummarySchema>;
export type ExecutionGate = z.infer<typeof ExecutionGateSchema>;
