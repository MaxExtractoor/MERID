/**
 * Feature flags for MERID UI.
 *
 * KALSHI_ONLY mode hides legacy/research panels and focuses the UI
 * on the Kalshi trading critical path.
 *
 * Flags are read from:
 *   1. Vite env vars  (VITE_KALSHI_ONLY=true in .env or CLI)
 *   2. localStorage   (merid-kalshi-only)
 *   3. URL param       (?kalshi_only=true)
 *
 * Any truthy source wins.
 */

function isTruthy(val: string | null | undefined): boolean {
  if (!val) return false;
  return ['true', '1', 'yes'].includes(val.trim().toLowerCase());
}

function resolveKalshiOnly(): boolean {
  // 1. Vite env
  try {
    if (isTruthy(import.meta.env.VITE_KALSHI_ONLY)) return true;
  } catch { /* not in Vite context */ }

  // 2. localStorage
  try {
    if (isTruthy(localStorage.getItem('merid-kalshi-only'))) return true;
  } catch { /* SSR or restricted */ }

  // 3. URL param
  try {
    const params = new URLSearchParams(window.location.search);
    if (isTruthy(params.get('kalshi_only'))) return true;
  } catch { /* SSR */ }

  return false;
}

export interface FeatureFlags {
  kalshiOnly: boolean;
}

const flags: FeatureFlags = {
  kalshiOnly: resolveKalshiOnly(),
};

export function useFeatureFlags(): FeatureFlags {
  return flags;
}

export function setKalshiOnly(enabled: boolean): void {
  try {
    localStorage.setItem('merid-kalshi-only', String(enabled));
  } catch { /* ignore */ }
  // Reload to apply
  window.location.reload();
}
