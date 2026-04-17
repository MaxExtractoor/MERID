/**
 * Global type augmentations to eliminate `as any` casts across the codebase.
 * Pass 20B debt — typed replacements for untyped globals.
 */

// ── Navigator Network Information API ─────────────────────────────────
// Non-standard API supported by Chrome/Edge. No official TS types.
interface NetworkInformation extends EventTarget {
  readonly type?: string;
  readonly effectiveType?: string;
  readonly downlink?: number;
  readonly rtt?: number;
  readonly saveData?: boolean;
  onchange?: EventListener;
}

interface Navigator {
  readonly connection?: NetworkInformation;
}

// ── Window augmentations for optional global services ─────────────────
interface Window {
  errorReportingService?: {
    report(data: Record<string, unknown>): Promise<void>;
  };
  logUxEvent?: (event: string, source: string, data: Record<string, unknown>) => void;
}

// ── Typed API Error with status/code ──────────────────────────────────
// Used by KalshiCancelAllButton, KalshiCredentialsCard, errorClassification
interface ApiError extends Error {
  status?: number;
  code?: string;
}
