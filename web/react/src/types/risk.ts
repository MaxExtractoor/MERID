export type CircuitBreakerState = 'CLOSED' | 'OPEN' | 'HALF_OPEN';

export interface OperatorRiskState {
  /** False when any monitored PM crypto asset lacks healthy spot — CRYPTO_15M_MM blocks quoting for affected assets. */
  all_pm_assets_have_spot?: boolean;
  kill_switch: {
    active: boolean;
    reason: string | null;
    can_trade: boolean;
  };
  pnl: {
    daily_pnl: number;
    daily_loss_limit: number;
    limit_remaining: number;
    utilization_pct: number;
  };
  position: {
    total_value: number;
    max_allowed: number;
    utilization_pct: number;
  };
  errors: {
    count_1h: number;
    threshold: number;
    near_limit: boolean;
    /** startup_grace: ERROR_THRESHOLD hard-kill suppressed until warm-up or grace expiry */
    phase?: 'startup_grace' | 'steady';
    execution_warm?: boolean;
    startup_grace_seconds?: number;
    grace_seconds_remaining?: number;
  };
  /** LivePriceFeed + PM get_spot_price + crypto_pm_vol_bridge cache (operator diagnostics) */
  crypto_pm_feed?: {
    summary?: {
      all_pm_assets_have_spot?: boolean;
      kalshi_only_mode?: boolean;
      /** False when LivePriceFeed.running is false (process-level feed off). */
      live_price_feed_running?: boolean;
      /** True shortly after stream start — tick gaps are not yet treated as unhealthy. */
      live_feed_warming?: boolean;
      last_global_stream_tick_age_seconds?: number | null;
      note?: string;
      error?: string;
    };
    assets?: Record<
      string,
      {
        /** Same as pm_spot_effective_ok — usable for PM / MM gate (get_spot_price path). */
        pm_spot_ok?: boolean;
        /** True only when LivePriceFeed quote exists and is within MERID_PM_MAX_SPOT_AGE_SECONDS. */
        pm_spot_effective_ok?: boolean;
        /** When not ok: no_quote_or_feed_ttl_expired | pm_max_age_exceeded | live_price_feed_unhealthy | … */
        pm_spot_unusable_reason?: string;
        pm_spot_usd?: number | null;
        pm_max_spot_age_seconds?: number;
        /** Stream liveness (distinct from PM max-age gate). */
        live_price_feed_healthy?: boolean;
        last_stream_tick_age_seconds?: number | null;
        live_price_feed?: Record<string, unknown>;
        vol_bridge?: Record<string, unknown>;
      }
    >;
  };
}
