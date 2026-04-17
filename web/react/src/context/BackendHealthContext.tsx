/**
 * BackendHealthContext — Centralized backend reachability probe.
 *
 * A single lightweight HEAD/GET probe runs on an exponential-backoff schedule.
 * When the backend is unreachable (ERR_CONNECTION_REFUSED, DNS failure, etc.),
 * all polling hooks and WebSocket reconnect loops can read `backendOffline`
 * from this context and skip their own retries, eliminating the console/network
 * flood observed when the backend is down.
 *
 * When the probe succeeds, `backendOffline` flips to false and normal polling
 * resumes immediately.
 */

import React, { createContext, useContext, useState, useEffect, useRef, useCallback } from 'react';
import { API_BASE_URL, API_ENDPOINTS } from '../config/constants';

export interface BackendHealthState {
  /** True when the backend has been unreachable for >=2 consecutive probe failures. */
  backendOffline: boolean;
  /** Epoch-ms of the last successful backend response (from any source). */
  lastSuccessAt: number | null;
  /** Epoch-ms of when the next probe attempt is scheduled. */
  nextRetryAt: number | null;
  /** Number of consecutive probe failures. */
  consecutiveFailures: number;
  /** Manually trigger an immediate probe (e.g. user clicks "retry now"). */
  probeNow: () => void;
  /** Called by useApiData / WS hooks on any successful backend response to
   *  reset the offline state without waiting for the next probe. */
  reportSuccess: () => void;
  /** Called by useApiData / WS hooks on network-level failures to contribute
   *  to the offline detection (avoids needing the probe to be the only signal). */
  reportFailure: () => void;
}

const BackendHealthContext = createContext<BackendHealthState>({
  backendOffline: false,
  lastSuccessAt: null,
  nextRetryAt: null,
  consecutiveFailures: 0,
  probeNow: () => {},
  reportSuccess: () => {},
  reportFailure: () => {},
});

// ── Shared singleton state so hooks outside the React tree can read it ──
// (WebSocket hooks may fire before the context provider renders.)
let _globalOffline = false;
let _globalReportSuccess: (() => void) | null = null;
let _globalReportFailure: (() => void) | null = null;

/** Non-React accessor: is the backend currently considered offline? */
export function isBackendOffline(): boolean {
  return _globalOffline;
}

/** Non-React accessor: report a successful backend response. */
export function reportBackendSuccess(): void {
  _globalReportSuccess?.();
}

/** Non-React accessor: report a network-level failure. */
export function reportBackendFailure(): void {
  _globalReportFailure?.();
}

// ── Helpers ──

/** Returns true when a fetch error looks like a network-level connection failure. */
export function isConnectionRefused(err: unknown): boolean {
  if (err instanceof TypeError) {
    const msg = err.message.toLowerCase();
    return (
      msg.includes('failed to fetch') ||
      msg.includes('network request failed') ||
      msg.includes('networkerror') ||
      msg.includes('load failed') ||
      msg.includes('err_connection_refused')
    );
  }
  return false;
}

// Minimum/maximum probe intervals (ms)
const PROBE_BASE_MS = 2_000;
const PROBE_MAX_MS = 30_000;
// How many consecutive failures before we declare "offline"
const OFFLINE_THRESHOLD = 2;

export const BackendHealthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [backendOffline, setBackendOffline] = useState(false);
  const [lastSuccessAt, setLastSuccessAt] = useState<number | null>(null);
  const [nextRetryAt, setNextRetryAt] = useState<number | null>(null);
  const [consecutiveFailures, setConsecutiveFailures] = useState(0);

  const failuresRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  // Track the probe's internal abort-timeout so we can clean it up on unmount.
  const probeAbortTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Schedule helper (ref-stable, no useCallback needed) ──
  // Uses a ref so runProbe can call it without a circular dependency.
  const scheduleProbeRef = useRef<() => void>(() => {});

  // ── Probe function ──
  // Stable via ref indirection for scheduleProbe; no deps required.
  const runProbe = useCallback(async () => {
    try {
      const controller = new AbortController();
      probeAbortTimerRef.current = setTimeout(() => controller.abort(), 5_000);
      const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.SYSTEM_HEALTH}`, {
        signal: controller.signal,
        headers: { Accept: 'application/json' },
      });
      // Clear the abort timeout now that fetch completed.
      if (probeAbortTimerRef.current) { clearTimeout(probeAbortTimerRef.current); probeAbortTimerRef.current = null; }

      if (!mountedRef.current) return;

      if (res.ok || res.status === 401 || res.status === 403 || res.status === 429) {
        // Backend is reachable (even if auth fails, the server is up).
        failuresRef.current = 0;
        setConsecutiveFailures(0);
        setBackendOffline(false);
        _globalOffline = false;
        setLastSuccessAt(Date.now());
      } else {
        // Server responded but with a 5xx — count as reachable but unhealthy;
        // don't mark offline for server errors, only connection-level failures.
        failuresRef.current = 0;
        setConsecutiveFailures(0);
        setBackendOffline(false);
        _globalOffline = false;
      }
    } catch {
      // Clear the abort timeout on error path too.
      if (probeAbortTimerRef.current) { clearTimeout(probeAbortTimerRef.current); probeAbortTimerRef.current = null; }
      if (!mountedRef.current) return;
      // Network-level failure (ERR_CONNECTION_REFUSED, DNS, timeout).
      failuresRef.current += 1;
      setConsecutiveFailures(failuresRef.current);
      if (failuresRef.current >= OFFLINE_THRESHOLD) {
        setBackendOffline(true);
        _globalOffline = true;
      }
    }
    // Schedule next probe with backoff — only if still mounted.
    if (mountedRef.current) {
      scheduleProbeRef.current();
    }
  }, []);

  // Keep scheduleProbeRef wired to the latest closure.
  scheduleProbeRef.current = () => {
    if (!mountedRef.current) return;
    if (timerRef.current) clearTimeout(timerRef.current);
    const failures = failuresRef.current;
    const baseDelay = failures === 0
      ? PROBE_MAX_MS // Backend is healthy — probe infrequently.
      : Math.min(PROBE_BASE_MS * Math.pow(2, failures - 1), PROBE_MAX_MS);
    // Add ±20% jitter to prevent synchronized retries across browser tabs / clients.
    const jitter = baseDelay * 0.2 * (Math.random() * 2 - 1); // range: -20% to +20%
    const delay = Math.max(PROBE_BASE_MS, Math.round(baseDelay + jitter));
    const nextAt = Date.now() + delay;
    setNextRetryAt(nextAt);
    timerRef.current = setTimeout(runProbe, delay);
  };

  // ── Public methods for hooks to call ──
  const reportSuccess = useCallback(() => {
    if (!mountedRef.current) return;
    if (failuresRef.current === 0 && !_globalOffline) return; // already healthy
    failuresRef.current = 0;
    setConsecutiveFailures(0);
    setBackendOffline(false);
    _globalOffline = false;
    setLastSuccessAt(Date.now());
    // Reset the probe timer to a slow cadence.
    scheduleProbeRef.current();
  }, []);

  const reportFailure = useCallback(() => {
    if (!mountedRef.current) return;
    failuresRef.current += 1;
    setConsecutiveFailures(failuresRef.current);
    if (failuresRef.current >= OFFLINE_THRESHOLD) {
      setBackendOffline(true);
      _globalOffline = true;
      // Speed up the probe schedule when we transition to offline.
      scheduleProbeRef.current();
    }
  }, []);

  const probeNow = useCallback(() => {
    if (!mountedRef.current) return;
    if (timerRef.current) clearTimeout(timerRef.current);
    runProbe();
  }, [runProbe]);

  // Wire up global accessors.
  useEffect(() => {
    _globalReportSuccess = reportSuccess;
    _globalReportFailure = reportFailure;
    return () => {
      _globalReportSuccess = null;
      _globalReportFailure = null;
    };
  }, [reportSuccess, reportFailure]);

  // Start probing on mount; full cleanup on unmount.
  useEffect(() => {
    mountedRef.current = true;
    runProbe();
    return () => {
      mountedRef.current = false;
      if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
      if (probeAbortTimerRef.current) { clearTimeout(probeAbortTimerRef.current); probeAbortTimerRef.current = null; }
      // Reset global state so a re-mount (e.g. HMR) starts fresh.
      _globalOffline = false;
    };
  }, [runProbe]);

  const value: BackendHealthState = {
    backendOffline,
    lastSuccessAt,
    nextRetryAt,
    consecutiveFailures,
    probeNow,
    reportSuccess,
    reportFailure,
  };

  return (
    <BackendHealthContext.Provider value={value}>
      {children}
    </BackendHealthContext.Provider>
  );
};

/** React hook to read backend health state. */
export function useBackendHealth(): BackendHealthState {
  return useContext(BackendHealthContext);
}
