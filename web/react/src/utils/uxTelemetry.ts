/**
 * UX Telemetry — lightweight event logger for UI interactions.
 *
 * Logs tab changes, favorites toggles, ticket opens, risk feed interactions,
 * and other UI events to help understand how the surface is used during live runs.
 *
 * Events are buffered in memory and flushed to localStorage periodically.
 * Can be exported as JSON for analysis.
 */

interface UxEvent {
  ts: number;
  action: string;
  target?: string;
  meta?: Record<string, unknown>;
}

const STORAGE_KEY = 'merid:ux_telemetry';
const MAX_EVENTS = 500;
const FLUSH_INTERVAL_MS = 10_000;

let _buffer: UxEvent[] = [];
let _flushTimer: ReturnType<typeof setInterval> | null = null;

function _load(): UxEvent[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function _flush() {
  if (_buffer.length === 0) return;
  try {
    const existing = _load();
    const merged = [...existing, ..._buffer].slice(-MAX_EVENTS);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(merged));
    _buffer = [];
  } catch {
    // localStorage full or unavailable — drop oldest
    _buffer = _buffer.slice(-100);
  }
}

function _ensureTimer() {
  if (_flushTimer) return;
  _flushTimer = setInterval(_flush, FLUSH_INTERVAL_MS);
}

/**
 * Log a UI event. Lightweight — call freely from event handlers.
 *
 * @param action  Short action name, e.g. 'tab_change', 'favorite_toggle', 'ticket_open'
 * @param target  Optional target identifier, e.g. ticker, tab id
 * @param meta    Optional key-value metadata
 */
export function logUxEvent(action: string, target?: string, meta?: Record<string, unknown>) {
  _ensureTimer();
  _buffer.push({
    ts: Date.now(),
    action,
    target,
    meta,
  });
}

/**
 * Get all logged events (from localStorage + current buffer).
 */
export function getUxEvents(): UxEvent[] {
  return [..._load(), ..._buffer];
}

/**
 * Export events as downloadable JSON blob URL.
 */
export function exportUxEvents(): string {
  const events = getUxEvents();
  const blob = new Blob([JSON.stringify(events, null, 2)], { type: 'application/json' });
  return URL.createObjectURL(blob);
}

/**
 * Clear all logged events.
 */
export function clearUxEvents() {
  _buffer = [];
  try { localStorage.removeItem(STORAGE_KEY); } catch { /* ignore */ }
}

/**
 * Get summary stats of logged events.
 */
export function getUxStats(): { total: number; byAction: Record<string, number>; lastEvent: number | null } {
  const events = getUxEvents();
  const byAction: Record<string, number> = {};
  for (const e of events) {
    byAction[e.action] = (byAction[e.action] ?? 0) + 1;
  }
  return {
    total: events.length,
    byAction,
    lastEvent: events.length > 0 ? events[events.length - 1].ts : null,
  };
}
