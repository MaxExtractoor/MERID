/**
 * Regression tests for agents/session.ts + the auth path in agents/api.ts.
 *
 * Backend contract (verified web/api/kalshi_api.py:186 +
 * kalshi_agent_grid_api.py:38): only the /api/v1/kalshi router is wrapped in
 * Depends(get_current_session); /api/v1/kalshi-grid is unauthenticated.
 */

import { isSessionScopedPath, getSessionId, clearSession, ensureSession } from '../session';
import { getJson } from '../api';

const REGISTER = '/api/v1/auth/register';
const jsonRes = (body: unknown, status = 200) =>
  ({
    ok: status >= 200 && status < 300,
    status,
    statusText: `status ${status}`,
    json: async () => body,
  }) as Response;

let fetchMock: jest.Mock;
let backingStore: Map<string, string>;

const storage = () => localStorage as unknown as {
  getItem: jest.Mock; setItem: jest.Mock; removeItem: jest.Mock; clear: jest.Mock;
};

beforeEach(() => {
  clearSession();
  backingStore = new Map();
  storage().getItem.mockImplementation((k: string) => backingStore.get(k) ?? null);
  storage().setItem.mockImplementation((k: string, v: string) => { backingStore.set(k, v); });
  storage().removeItem.mockImplementation((k: string) => { backingStore.delete(k); });
  storage().clear.mockImplementation(() => { backingStore.clear(); });
  fetchMock = jest.fn();
  global.fetch = fetchMock as unknown as typeof fetch;
});

describe('isSessionScopedPath', () => {
  it('scopes /api/v1/kalshi routes', () => {
    expect(isSessionScopedPath('/api/v1/kalshi/balance')).toBe(true);
    expect(isSessionScopedPath('/api/v1/kalshi')).toBe(true);
  });

  it('does not scope /api/v1/kalshi-grid (different, unauthenticated router)', () => {
    expect(isSessionScopedPath('/api/v1/kalshi-grid/agents')).toBe(false);
    expect(isSessionScopedPath('/api/v1/kalshi-grid/decision-feed?limit=60')).toBe(false);
  });

  it('scopes live-runtime-state routes (halt/release/recover require a session)', () => {
    expect(isSessionScopedPath('/api/v1/live-runtime-state/')).toBe(true);
    expect(isSessionScopedPath('/api/v1/live-runtime-state/halt')).toBe(true);
    expect(isSessionScopedPath('/api/v1/live-runtime-state/release')).toBe(true);
    expect(isSessionScopedPath('/api/v1/live-runtime-state/recover')).toBe(true);
    expect(isSessionScopedPath('/api/v1/live-runtime-stateX')).toBe(false);
  });

  it('does not scope look-alike prefixes or other routers', () => {
    expect(isSessionScopedPath('/api/v1/kalshix/y')).toBe(false);
    expect(isSessionScopedPath('/api/v1/agents')).toBe(false);
    expect(isSessionScopedPath('/api/v1/kalshi-grid/agents')).toBe(false);
  });
});

describe('authed fetch scoping', () => {
  it('mints a session and sends auth headers for /api/v1/kalshi/*', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonRes({ session_id: 'tok-1' }))   // register
      .mockResolvedValueOnce(jsonRes({ ok: true }));             // data call
    await getJson('/api/v1/kalshi/balance');
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][0]).toBe(REGISTER);
    const headers = fetchMock.mock.calls[1][1].headers as Record<string, string>;
    expect(headers['X-Session-ID']).toBe('tok-1');
    expect(headers.Authorization).toBe('Bearer tok-1');
  });

  it('never mints and sends no session headers for /api/v1/kalshi-grid/*', async () => {
    fetchMock.mockResolvedValueOnce(jsonRes({ agents: [] }));
    await getJson('/api/v1/kalshi-grid/agents');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/kalshi-grid/agents');
    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(headers['X-Session-ID']).toBeUndefined();
    expect(headers.Authorization).toBeUndefined();
  });
});

describe('401 re-mint', () => {
  it('on 401 clears the stale token, re-mints once, and retries with the new token', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonRes({ session_id: 'tok-old' }))
      .mockResolvedValueOnce(jsonRes({}, 401))
      .mockResolvedValueOnce(jsonRes({ session_id: 'tok-new' }))
      .mockResolvedValueOnce(jsonRes({ ok: true }));
    await getJson('/api/v1/kalshi/balance');
    expect(fetchMock).toHaveBeenCalledTimes(4);
    const retryHeaders = fetchMock.mock.calls[3][1].headers as Record<string, string>;
    expect(retryHeaders['X-Session-ID']).toBe('tok-new');
  });

  it('concurrent stale 401s share a single re-mint', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonRes({ session_id: 'tok-old' }))       // shared mint
      .mockResolvedValueOnce(jsonRes({}, 401))                          // req A
      .mockResolvedValueOnce(jsonRes({}, 401))                          // req B
      .mockResolvedValueOnce(jsonRes({ session_id: 'tok-new' }))       // single re-mint
      .mockResolvedValueOnce(jsonRes({ ok: 1 }))
      .mockResolvedValueOnce(jsonRes({ ok: 2 }));
    const [a, b] = await Promise.all([
      getJson('/api/v1/kalshi/balance'),
      getJson('/api/v1/kalshi/positions'),
    ]);
    expect(a).toEqual({ ok: 1 });
    expect(b).toEqual({ ok: 2 });
    const registers = fetchMock.mock.calls.filter((c) => c[0] === REGISTER);
    expect(registers).toHaveLength(2); // one initial mint + one shared re-mint
  });
});

describe('localStorage unavailable', () => {
  const denyStorage = () => {
    storage().getItem.mockImplementation(() => { throw new Error('denied'); });
    storage().setItem.mockImplementation(() => { throw new Error('denied'); });
    storage().removeItem.mockImplementation(() => { throw new Error('denied'); });
  };

  it('still uses the minted token via in-memory fallback', async () => {
    denyStorage();
    fetchMock
      .mockResolvedValueOnce(jsonRes({ session_id: 'tok-mem' }))
      .mockResolvedValueOnce(jsonRes({ ok: true }));
    await getJson('/api/v1/kalshi/balance');
    expect(getSessionId()).toBe('tok-mem');
    const headers = fetchMock.mock.calls[1][1].headers as Record<string, string>;
    expect(headers['X-Session-ID']).toBe('tok-mem');
  });

  it('clearSession wipes the in-memory token too', async () => {
    denyStorage();
    fetchMock.mockResolvedValueOnce(jsonRes({ session_id: 'tok-mem' }));
    await ensureSession();
    expect(getSessionId()).toBe('tok-mem');
    clearSession();
    expect(getSessionId()).toBeNull();
  });
});

describe('mint timeout / abort propagation', () => {
  it('passes the caller AbortSignal through to the register fetch', async () => {
    fetchMock.mockResolvedValueOnce(jsonRes({ session_id: 'tok-x' }))
      .mockResolvedValueOnce(jsonRes({ ok: true }));
    await getJson('/api/v1/kalshi/balance');
    const mintInit = fetchMock.mock.calls[0][1] as RequestInit;
    expect(mintInit.signal).toBeInstanceOf(AbortSignal);
  });

  it('a caller abort rejects the in-flight mint instead of hanging', async () => {
    fetchMock.mockImplementationOnce((_url: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
      }));
    const ctrl = new AbortController();
    const p = ensureSession(false, ctrl.signal);
    ctrl.abort();
    await expect(p).rejects.toThrow();
  });
});
