/**
 * apiBase — single source of truth for API and WebSocket base URLs.
 *
 * Precedence:
 *   1. VITE_API_BASE / VITE_WS_BASE env (explicit override, dev or prod)
 *   2. Same-origin relative URL (works through the Vite dev proxy at /api
 *      and when the backend serves the built bundle directly)
 *
 * Every fetch in the app should go through apiUrl(); every WebSocket through
 * wsUrl(). Never hardcode http://localhost:8011 or ws://localhost:8011.
 */

const env = (key: string): string | undefined => {
  try {
    const meta = (globalThis as { import?: { meta?: { env?: Record<string, string> } } }).import;
    return meta?.meta?.env?.[key];
  } catch {
    return undefined;
  }
};

const stripTrailingSlash = (s: string) => s.replace(/\/+$/, '');

/** HTTP API base. Empty string means same-origin (recommended). */
export const API_BASE: string = stripTrailingSlash(env('VITE_API_BASE') ?? '');

/** Build a fetch URL. Absolute http(s) URLs pass through untouched. */
export function apiUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
}

/** Build a WebSocket URL. Absolute ws(s) URLs pass through untouched. */
export function wsUrl(path: string): string {
  if (/^wss?:\/\//.test(path)) return path;
  const override = env('VITE_WS_BASE');
  if (override) return `${stripTrailingSlash(override)}${path.startsWith('/') ? path : `/${path}`}`;
  if (API_BASE) return `${API_BASE.replace(/^http/, 'ws')}${path.startsWith('/') ? path : `/${path}`}`;
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}${path.startsWith('/') ? path : `/${path}`}`;
}
