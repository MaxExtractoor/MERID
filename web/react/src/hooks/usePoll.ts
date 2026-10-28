/**
 * usePoll — the single view-level data hook.
 *
 * Replaces the old useApiData / useApiQuery split: pass an endpoint path
 * (fetched via getJson -> apiUrl + auth) or any fetcher returning a promise.
 * Polls on an interval, keeps the last good data on failure (never zeroes
 * out), exposes per-source freshness so views can show honest staleness.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getJson } from '../agents/api';

export interface PollSource<T> {
  path?: string;
  fetcher?: () => Promise<T>;
}

export interface UsePollOptions<T> {
  /** Poll interval ms. Default 15000. 0 = fetch once, no interval. */
  ms?: number;
  /** Optional transform applied to the raw response. */
  map?: (raw: unknown) => T;
  /** Disable polling entirely (e.g. feature flag off). */
  enabled?: boolean;
}

export interface UsePollResult<T> {
  data: T | undefined;
  error: string | undefined;
  /** True until the first fetch resolves (success or failure). */
  loading: boolean;
  /** Epoch ms of the last successful fetch. */
  lastOk: number | undefined;
  /** Force an immediate refetch. */
  refresh: () => void;
}

export function usePoll<T = unknown>(
  source: string | PollSource<T> | (() => Promise<T>),
  options?: UsePollOptions<T>,
): UsePollResult<T> {
  const ms = options?.ms ?? 15_000;
  const enabled = options?.enabled !== false;
  const map = options?.map;

  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<string | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [lastOk, setLastOk] = useState<number | undefined>(undefined);
  const inFlight = useRef(false);
  const mounted = useRef(true);

  // Stable ref to the source so callers can pass inline lambdas without
  // retriggering the interval every render.
  const sourceRef = useRef(source);
  sourceRef.current = source;
  const mapRef = useRef(map);
  mapRef.current = map;

  const poll = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const src = sourceRef.current;
      const raw: unknown =
        typeof src === 'string'
          ? await getJson(src)
          : typeof src === 'function'
            ? await src()
            : src.fetcher
              ? await src.fetcher()
              : src.path
                ? await getJson(src.path)
                : undefined;
      if (!mounted.current) return;
      const out = mapRef.current ? mapRef.current(raw) : (raw as T);
      setData(out);
      setError(undefined);
      setLastOk(Date.now());
      setLoading(false);
    } catch (e) {
      if (!mounted.current) return;
      setError(e instanceof Error ? e.message : String(e));
      setLoading(false);
      // Keep last-good data — a failed poll must not blank the view.
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    if (!enabled) {
      setLoading(false);
      return () => { mounted.current = false; };
    }
    void poll();
    let id: number | undefined;
    if (ms > 0) id = window.setInterval(() => void poll(), ms);
    return () => {
      mounted.current = false;
      if (id != null) window.clearInterval(id);
    };
  }, [poll, ms, enabled]);

  const refresh = useCallback(() => void poll(), [poll]);
  return { data, error, loading, lastOk, refresh };
}

export default usePoll;
