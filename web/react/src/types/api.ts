/**
 * Shared API DTO types for backend response mapping.
 */

// ── Live Notifications (raw notification from API) ───────────────────

export interface RawNotification {
  id?: string;
  type?: string;
  severity?: string;
  title?: string;
  message?: string;
  timestamp?: string;
  read?: boolean;
}

// ── Continuous Trader (CT) diagnostics ───────────────────────────────

/** Per-ticker result from the most recent CT cycle. */
export interface CTTickerDiagnostic {
  ticker: string;
  asset: string;
  timeframe: string;
  /** Kalshi implied YES probability at cycle time (0–1). */
  implied_yes_prob: number;
  /** Model win probability from strategy/estimate (0–1). */
  model_win_prob: number;
  /** Edge in basis points (model_win_prob - implied_yes_prob) × 10 000. */
  edge_bps: number;
  side: 'YES' | 'NO' | 'none';
  kelly_raw: number;
  kelly_frac: number;
  /** null means approved (no veto). */
  veto_reason:
    | 'no_estimate'
    | 'edge_too_low'
    | 'negative_kelly'
    | 'bankroll_says_0'
    | 'group_notional_cap'
    | 'low_confidence'
    | 'risk_check_failed'
    | 'max_yes_price_cap'
    | null;
}

/** Veto reason → count breakdown for a cycle. */
export type CTVetoBreakdown = Partial<
  Record<
    | 'no_estimate'
    | 'edge_too_low'
    | 'negative_kelly'
    | 'bankroll_says_0'
    | 'group_notional_cap'
    | 'low_confidence'
    | 'risk_check_failed'
    | 'max_yes_price_cap',
    number
  >
>;

/** Per-cycle summary from the most recent trade_cycle() call. */
export interface CTCycleStats {
  candidates_seen: number;
  markets_with_any_edge: number;
  markets_after_risk_veto: number;
  vetoed_total: number;
  vetoed_by_reason: CTVetoBreakdown;
  ticker_diagnostics: CTTickerDiagnostic[];
  /** Unix timestamp of the cycle. */
  cycle_ts: number;
}

/** Full CT status response from GET /api/v1/ct/status. */
export interface CTStatus {
  running: boolean;
  candidate_count: number;
  config: {
    max_group_notional: number;
    min_confidence: number;
    bankroll_fraction: number;
    max_yes_price: number;
    kelly_fraction: number;
    min_edge: number | Record<string, number>;
    edge_profile: string;
    /** Dead zone threshold (¢ around 50¢); 0 = disabled. */
    filter_dead_zone_pct: number;
    /** Spot-band percentage; 0 = disabled. */
    filter_spot_band_pct: number;
  };
  risk: {
    group_notional: Record<string, number>;
    daily_loss: number;
    trade_count: number;
    execution_rejections: number;
  };
  filter: Record<string, number | string | null>;
  last_cycle: Partial<CTCycleStats>;
}

export interface CTStatusResponse {
  status: 'ok' | 'unavailable';
  data: CTStatus;
}

