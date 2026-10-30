/**
 * agents/session.ts — operator session lifecycle for the gated API surface.
 *
 * Backend contract (verified web/api/auth.py + auth/user_manager.py):
 *   - Every `/api/v1/kalshi/*` route is wrapped in Depends(get_current_session).
 *   - Sessions are minted by POST /api/v1/auth/register (username-only is
 *     accepted; username has no uniqueness constraint) and validated via
 *     `X-Session-ID` or `Authorization: Bearer`.
 *   - Users and sessions are IN-MEMORY: a backend restart invalidates every
 *     token, so a stored token may 401 at any time. Callers must clear and
 *     re-mint — ensureSession(true) — rather than trust the stored value.
 *
 * No login screen exists because there is nothing to type: the deployment is
 * a single-operator local console and register is the session-issuance
 * endpoint the backend actually exposes.
 */

import { apiUrl } from '../config/apiBase';

export const SESSION_TOKEN_KEY = 'merid-access';

const REGISTER_PATH = '/api/v1/auth/register';
const OPERATOR_USERNAME = 'operator';

/** The only router gated by get_current_session is /api/v1/kalshi. */
export const isSessionScopedPath = (path: string): boolean =>
  path.startsWith('/api/v1/kalshi');

export function getSessionId(): string | null {
  try {
    return localStorage.getItem(SESSION_TOKEN_KEY);
  } catch {
    return null;
  }
}

export function clearSession(): void {
  try {
    localStorage.removeItem(SESSION_TOKEN_KEY);
  } catch { /* noop */ }
}

/** Clear only if the stored token is still the one that failed — prevents a
 *  concurrent re-mint from being wiped by a stale 401 handler. */
export function clearSessionIf(expected: string | null): void {
  if (expected != null && getSessionId() === expected) clearSession();
}

let mintPromise: Promise<string> | null = null;

async function mintSession(): Promise<string> {
  const res = await fetch(apiUrl(REGISTER_PATH), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: OPERATOR_USERNAME }),
  });
  if (!res.ok) throw new Error(`session mint failed (${res.status})`);
  const data = (await res.json()) as { session_id?: string };
  if (!data.session_id) throw new Error('session mint returned no session_id');
  try {
    localStorage.setItem(SESSION_TOKEN_KEY, data.session_id);
  } catch { /* noop */ }
  return data.session_id;
}

/**
 * Resolve a session token. With `force`, mints a fresh one even if a token is
 * stored (the stored one may be a dead post-restart token). Concurrent calls
 * share one in-flight mint so a 401 storm produces a single register.
 */
export function ensureSession(force = false): Promise<string> {
  if (!force) {
    const existing = getSessionId();
    if (existing) return Promise.resolve(existing);
  }
  if (!mintPromise) {
    mintPromise = mintSession().finally(() => {
      mintPromise = null;
    });
  }
  return mintPromise;
}
