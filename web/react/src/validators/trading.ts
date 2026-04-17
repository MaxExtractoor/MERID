// @ts-nocheck - Install zod package for full type checking
import { z } from 'zod';

/**
 * Input validation schemas for trading operations
 * Used to validate user inputs before sending to API
 */

// Order validation
export const OrderSchema = z.object({
  ticker: z.string().min(1, 'Ticker is required').max(50, 'Ticker too long'),
  side: z.enum(['yes', 'no'], {
    errorMap: () => ({ message: 'Side must be "yes" or "no"' }),
  }),
  action: z.enum(['buy', 'sell'], {
    errorMap: () => ({ message: 'Action must be "buy" or "sell"' }),
  }),
  count: z.number().int().positive().max(10000, 'Order size exceeds maximum'),
  price_cents: z.number().int().min(1).max(99, 'Price must be 1-99 cents'),
  order_type: z.enum(['market', 'limit'], {
    errorMap: () => ({ message: 'Order type must be "market" or "limit"' }),
  }),
  mode: z.enum(['paper', 'live'], {
    errorMap: () => ({ message: 'Mode must be "paper" or "live"' }),
  }),
});

// Position limit validation
export const PositionLimitSchema = z.object({
  ticker: z.string().min(1),
  max_position_size: z.number().positive().max(1000000, 'Position limit too high'),
  current_position: z.number(),
  order_size: z.number().positive(),
}).refine((data) => {
  return Math.abs(data.current_position + data.order_size) <= data.max_position_size;
}, {
  message: 'Order would exceed position limit',
  path: ['order_size'],
});

// Balance validation
export const BalanceCheckSchema = z.object({
  available_balance: z.number().min(0),
  order_cost: z.number().positive(),
}).refine((data) => data.available_balance >= data.order_cost, {
  message: 'Insufficient balance for order',
  path: ['order_cost'],
});

// Grid mode validation
export const GridModeSchema = z.object({
  mode: z.enum(['paper', 'live']),
  force: z.boolean().optional(),
});

// Price validation
export const PriceSchema = z.object({
  ticker: z.string().min(1),
  price: z.number().positive(),
  timestamp: z.number().optional(),
}).refine((data) => {
  if (data.timestamp) {
    // Price must be newer than 30 seconds
    return Date.now() - data.timestamp < 30000;
  }
  return true;
}, {
  message: 'Price data is stale (>30s)',
  path: ['timestamp'],
});

// Emergency stop validation
export const EmergencyStopSchema = z.object({
  reason: z.string().min(5, 'Reason must be at least 5 characters').max(500),
  confirm: z.boolean().refine((val) => val === true, {
    message: 'Must confirm emergency stop',
  }),
});

// Kill switch validation
export const KillSwitchResetSchema = z.object({
  confirm: z.boolean().refine((val) => val === true, {
    message: 'Must confirm kill switch reset',
  }),
  resolved_issues: z.string().min(10, 'Please describe resolved issues'),
});

// Batch order validation
export const BatchOrderSchema = z.array(OrderSchema).max(100, 'Maximum 100 orders per batch');

// Order amendment validation
export const OrderAmendSchema = z.object({
  order_id: z.string().min(1, 'Order ID is required'),
  new_price_cents: z.number().int().min(1).max(99),
  reason: z.string().min(5).optional(),
});

// Cancel order validation
export const CancelOrderSchema = z.object({
  order_id: z.string().min(1, 'Order ID is required'),
  reason: z.string().optional(),
});

// Risk limits validation
export const RiskLimitsSchema = z.object({
  max_daily_loss_usd: z.number().positive().max(10000000),
  max_per_symbol_exposure_usd: z.number().positive().max(10000000),
  max_open_orders: z.number().int().positive().max(1000),
});

// Type exports
export type OrderInput = z.infer<typeof OrderSchema>;
export type PositionLimitInput = z.infer<typeof PositionLimitSchema>;
export type BalanceCheckInput = z.infer<typeof BalanceCheckSchema>;
export type GridModeInput = z.infer<typeof GridModeSchema>;
export type PriceInput = z.infer<typeof PriceSchema>;
export type EmergencyStopInput = z.infer<typeof EmergencyStopSchema>;
export type KillSwitchResetInput = z.infer<typeof KillSwitchResetSchema>;
export type BatchOrderInput = z.infer<typeof BatchOrderSchema>;
export type OrderAmendInput = z.infer<typeof OrderAmendSchema>;
export type CancelOrderInput = z.infer<typeof CancelOrderSchema>;
export type RiskLimitsInput = z.infer<typeof RiskLimitsSchema>;

/**
 * Validate input and return either the validated data or error messages
 */
export function validateInput<T>(
  schema: z.ZodSchema<T>,
  data: unknown
): { success: true; data: T } | { success: false; errors: string[] } {
  const result = schema.safeParse(data);
  
  if (result.success) {
    return { success: true, data: result.data };
  }
  
  const errors = result.error.errors.map((e) => e.message);
  return { success: false, errors };
}

/**
 * Quick validation helpers for common trading operations
 */
export const validators = {
  order: (data: unknown) => validateInput(OrderSchema, data),
  positionLimit: (data: unknown) => validateInput(PositionLimitSchema, data),
  balanceCheck: (data: unknown) => validateInput(BalanceCheckSchema, data),
  gridMode: (data: unknown) => validateInput(GridModeSchema, data),
  price: (data: unknown) => validateInput(PriceSchema, data),
  emergencyStop: (data: unknown) => validateInput(EmergencyStopSchema, data),
  killSwitchReset: (data: unknown) => validateInput(KillSwitchResetSchema, data),
  batchOrder: (data: unknown) => validateInput(BatchOrderSchema, data),
  orderAmend: (data: unknown) => validateInput(OrderAmendSchema, data),
  cancelOrder: (data: unknown) => validateInput(CancelOrderSchema, data),
  riskLimits: (data: unknown) => validateInput(RiskLimitsSchema, data),
};
