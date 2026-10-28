/**
 * agents/hooks.ts — tiny shared hooks for the agent-monitoring surface.
 */

import { useEffect, useRef, useState } from 'react';

/** Current epoch-ms, re-rendered every `intervalMs`. `null` disables ticking. */
export function useNow(intervalMs: number | null = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (intervalMs == null) return;
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

/**
 * Live countdown derived from a prop value: keeps decrementing every second
 * between prop refreshes, resynchronizing whenever `secs` changes.
 * Returns undefined when no value has ever been supplied (truthful 'n/a').
 */
export function useLiveCountdown(secs: number | undefined): number | undefined {
  const anchorRef = useRef<{ secs: number; at: number } | null>(null);
  const lastSecsRef = useRef<number | undefined>(undefined);
  const now = useNow(1000);
  // Adjust-during-render: re-anchor only when the incoming value changes.
  if (secs !== lastSecsRef.current) {
    lastSecsRef.current = secs;
    if (secs != null) anchorRef.current = { secs, at: now };
  }
  const a = anchorRef.current;
  if (!a) return undefined;
  return Math.max(0, a.secs - (now - a.at) / 1000);
}

/** True when the user prefers reduced motion (live-listens for changes). */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState<boolean>(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  });
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const onChange = (e: MediaQueryListEvent) => setReduced(e.matches);
    if (typeof mq.addEventListener === 'function') {
      mq.addEventListener('change', onChange);
      return () => mq.removeEventListener('change', onChange);
    }
    // Safari <14 fallback
    mq.addListener(onChange);
    return () => mq.removeListener(onChange);
  }, []);
  return reduced;
}

/**
 * Flash direction when a numeric value changes: 'up' | 'down' | null.
 * Clears itself after `durationMs`. Honours reduced-motion by returning null.
 */
export function useFlashOnChange(value: number | undefined, durationMs = 320): 'up' | 'down' | null {
  const [flash, setFlash] = useState<'up' | 'down' | null>(null);
  const prevRef = useRef<number | undefined>(undefined);
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    const prev = prevRef.current;
    prevRef.current = value;
    if (reduced || value == null || prev == null || prev === value) return;
    setFlash(value > prev ? 'up' : 'down');
    const id = window.setTimeout(() => setFlash(null), durationMs);
    return () => window.clearTimeout(id);
  }, [value, durationMs, reduced]);

  return flash;
}
