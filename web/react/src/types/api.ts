/**
 * Shared API DTO types for backend response mapping.
 *
 * These interfaces represent the "raw" shapes returned by various backend
 * endpoints before the frontend normalizes them into view-specific models.
 * Views should import from here instead of defining ad-hoc Record<string, unknown>.
 *
 * Aligned with backend contracts:
 * - REST: GET /api/v1/trading/portfolio-summary  (RawPosition)
 * - REST: GET /api/v1/trading/orders/open         (RawOrder)
 * - REST: GET /api/v1/trading/orders/open          (RawOrderPayload — TradeFloor REST fallback)
 * - WS:   /ws/trades                              (OpinionEventPayload)
 * - REST: GET /api/v1/spectator/live              (AgentTrade)
 * - REST: GET /api/v1/prediction-markets/summary  (PMRiskSummary, PMAlert)
 * - REST: GET /api/v1/consensus/metrics           (CalibrationBin)
 * - REST: GET /api/v1/signals/decay-configs       (DecayConfig)
 * - REST: GET /api/v1/signals/metrics             (SignalMetricsData)
 * - REST: GET /api/v1/signals/features/:symbol    (SignalFeaturesResponse)
 */

// ── Positions (portfolio summary) ────────────────────────────────────

export interface RawPosition {
  asset?: string;
  symbol?: string;
  size?: number;
  quantity?: number;
  avg_price?: number;
  avgPrice?: number;
  current_price?: number;
  currentPrice?: number;
  size_usd?: number;
  marketValue?: number;
  pnl?: number;
  unrealizedPnl?: number;
  pnl_pct?: number;
  unrealizedPnlPct?: number;
  side?: string;
  venue?: string;
}

// ── Orders (open orders) ─────────────────────────────────────────────

export interface RawOrder {
  id?: string;
  order_id?: string;
  symbol?: string;
  asset?: string;
  side?: string;
  type?: string;
  order_type?: string;
  size?: number;
  quantity?: number;
  price?: number;
  status?: string;
  createdAt?: string;
  timestamp?: string;
  venue?: string;
}

// ── TradeFloor (REST fallback order payload) ─────────────────────────

export interface RawOrderPayload {
  symbol?: string;
  side?: string;
  size?: number;
  quantity?: number;
  price?: number;
  status?: string;
  id?: string;
  venue?: string;
}

// ── TradeFloor (opinion event from Kafka stream) ─────────────────────

export interface OpinionEventPayload {
  opinion_id?: string;
  agent_id?: string;
  role?: string;
  agent_role?: string;
  symbol?: string;
  stance?: string;
  score?: number;
  confidence?: number;
  timestamp?: number;
  rationale?: string;
}

// ── Predictions (agent activity) ─────────────────────────────────────

export interface AgentTrade {
  action?: string;
  symbol?: string;
  agent_id?: string;
  quantity?: number;
  price?: number;
  strategy?: string;
  confidence?: number;
}

// ── Prediction Markets (summary sub-types) ───────────────────────────

export interface PMRiskSummary {
  total_exposure: number;
  daily_loss: number;
  kill_switch_active: boolean;
  breaches: number;
}

export interface PMAlert {
  alert_type: string;
  severity: string;
  message: string;
  timestamp: string;
}

// ── Prediction Consensus (calibration bins) ──────────────────────────

export interface CalibrationBin {
  bucket?: string;
  actual_rate?: number;
  expected_rate?: number;
  count?: number;
}

// ── Signal Layer ─────────────────────────────────────────────────────

export interface DecayConfig {
  tau_seconds: number;
  min_weight: number;
  max_age_seconds: number;
  refresh_boost: number;
}

export interface SignalStoreMetrics {
  feature_snapshots?: number;
  signal_snapshots?: number;
  arb_signals_total?: number;
  cqi_entries?: number;
}

export interface SignalArbMetrics {
  total_signals?: number;
  active_signals?: number;
  symbols_tracked?: number;
}

export interface SignalDriftMetrics {
  domains_tracked?: string[];
  total_outcomes?: number;
}

export interface SignalMetricsData {
  store?: SignalStoreMetrics;
  arb?: SignalArbMetrics;
  drift?: SignalDriftMetrics;
}

export interface FeatureData {
  value: number | string;
  decay_weight: number;
}

export interface FeatureSectionData {
  features?: Record<string, FeatureData>;
  avg_freshness: number;
  source?: string;
}

export interface SignalFeaturesResponse {
  news?: FeatureSectionData;
  social?: FeatureSectionData;
  onchain?: FeatureSectionData;
}

// ── Prediction Markets Panel (dual snake/camel shape) ────────────────

export interface RawPredictionMarket {
  id?: string;
  market_id?: string;
  question?: string;
  symbol?: string;
  category?: string;
  platform?: string;
  yesPrice?: number;
  yes_price?: number;
  noPrice?: number;
  no_price?: number;
  volume?: number;
  volume_24h?: number;
  endTime?: string;
  close_date?: string;
  ourPosition?: string;
  ourPnl?: number;
  modelConfidence?: number;
}

// ── Agent Status Panel (heartbeat response) ──────────────────────────

export interface RawAgentHeartbeat {
  agent_id?: string;
  role?: string;
  last_updated?: number;
  sharpe_ratio?: number;
  max_drawdown?: number;
  current_drawdown?: number;
  total_pnl?: number;
  total_trades?: number;
  win_rate?: number;
  consensus_weight?: number;
  prediction_accuracy?: number;
}

// ── Drawdown Chart (equity/drawdown history points) ──────────────────

export interface EquityHistoryPoint {
  timestamp: number;
  equity: number;
}

export interface DrawdownHistoryPoint {
  timestamp: number;
  drawdown: number;
}

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

// ── Resilience API types ──────────────────────────────────────────────

export interface CircuitBreakerInfo {
  name: string;
  state: 'closed' | 'open' | 'half_open';
  failure_count: number;
  failure_threshold: number;
  time_until_retry: number;
  recovery_timeout: number;
}

export interface BulkheadInfo {
  name: string;
  active: number;
  max_concurrent: number;
  queued: number;
  max_queued: number;
  total_accepted: number;
  total_rejected: number;
  avg_wait_ms: number;
}

export interface VenueHealthInfo {
  venue: string;
  domain: string;
  mode: string;
  enabled: boolean;
  has_credentials: boolean;
  breaker_state: string;
  breaker_failures: number;
  adapter_status: string;
  health: 'healthy' | 'degraded' | 'unhealthy' | 'disabled';
}

export interface ResilienceStatus {
  timestamp: string;
  overall_health: 'healthy' | 'degraded' | 'unhealthy';
  circuit_breakers: CircuitBreakerInfo[];
  bulkheads: BulkheadInfo[];
  venue_health: VenueHealthInfo[];
  summary: {
    breakers_total: number;
    breakers_open: number;
    venues_total: number;
    venues_healthy: number;
    venues_degraded: number;
    venues_unhealthy: number;
  };
}
