/**
 * Structured UI logger.
 *
 * Provides `logUiError`, `logUiWarn`, and `logUiInfo` — thin wrappers
 * around `console.*` that emit a consistent JSON-shaped object so logs
 * are grep-able and piped to the backend `/api/v1/telemetry` endpoint
 * for aggregation and SLI tracking.
 *
 * Usage:
 *   import { logUiError, logUiWarn } from '../utils/logger';
 *   logUiError('TopBar', 'PnL fetch failed', err, { endpoint: '/portfolio' });
 */

import { API_ENDPOINTS } from '../config/constants';

export type LogLevel = 'error' | 'warn' | 'info';

export interface UiLogEntry {
  level: LogLevel;
  component: string;
  message: string;
  error?: string;
  stack?: string;
  context?: Record<string, unknown>;
  timestamp: string;
  correlation_id?: string;
}

/**
 * Enable/disable backend telemetry piping.
 * Set to false to silence beacon calls during tests or local dev.
 */
let _telemetryEnabled = true;

export function setTelemetryEnabled(enabled: boolean): void {
  _telemetryEnabled = enabled;
}

/** Internal: build the structured entry and emit it. */
function emit(
  level: LogLevel,
  component: string,
  message: string,
  error?: unknown,
  context?: Record<string, unknown>,
): UiLogEntry {
  const entry: UiLogEntry = {
    level,
    component,
    message,
    timestamp: new Date().toISOString(),
  };

  if (error instanceof Error) {
    entry.error = error.message;
    entry.stack = error.stack;
  } else if (error !== undefined && error !== null) {
    entry.error = String(error);
  }

  if (context && Object.keys(context).length > 0) {
    entry.context = context;
  }

  // Emit to console with the structured object as a second arg so
  // browser DevTools can expand it while the first arg stays readable.
  const tag = `[${component}]`;
  switch (level) {
    case 'error':
      console.error(`${tag} ${message}`, entry);
      break;
    case 'warn':
      console.warn(`${tag} ${message}`, entry);
      break;
    default:
      console.info(`${tag} ${message}`, entry);
  }

  // ── Backend telemetry ──────────────────────────────────────────
  // Pipe errors and warnings to /api/v1/telemetry via sendBeacon
  // (fire-and-forget, works even during page unload).
  if (_telemetryEnabled && (level === 'error' || level === 'warn')) {
    try {
      const blob = new Blob([JSON.stringify(entry)], { type: 'application/json' });
      navigator.sendBeacon?.(API_ENDPOINTS.TELEMETRY, blob);
    } catch {
      // sendBeacon unavailable or blocked — console output is still there
    }
  }

  return entry;
}

/**
 * Log a UI error with structured context.
 *
 * @param component  Component or hook name, e.g. `'TopBar'`
 * @param message    Human-readable description
 * @param error      The caught error (Error object or unknown)
 * @param context    Optional key-value bag (endpoint, agentId, etc.)
 */
export function logUiError(
  component: string,
  message: string,
  error?: unknown,
  context?: Record<string, unknown>,
): UiLogEntry {
  return emit('error', component, message, error, context);
}

/**
 * Log a UI warning (e.g. stub fallback data in use).
 */
export function logUiWarn(
  component: string,
  message: string,
  context?: Record<string, unknown>,
): UiLogEntry {
  return emit('warn', component, message, undefined, context);
}

/**
 * Log a UI info event (e.g. successful reconnect, mode switch).
 */
export function logUiInfo(
  component: string,
  message: string,
  context?: Record<string, unknown>,
): UiLogEntry {
  return emit('info', component, message, undefined, context);
}
