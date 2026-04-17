/**
 * KalshiRiskContextView — Unified Risk Context Dashboard
 *
 * Composes the three risk lanes into a single contextual view:
 *   1. Fear/Greed sentiment regime (context)
 *   2. Volatility regime & SizingMultiplier (sizing truth)
 *   3. Cross-links to full sentiment and vol-targeting dashboards
 *
 * This is the "at-a-glance" risk view operators check before sizing positions.
 */

import React, { useMemo } from 'react';
import {
  Activity, TrendingUp, TrendingDown, Gauge,
  AlertTriangle, ArrowRight, Snowflake, Flame,
  Shield, Target, BarChart3, Zap,
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS, CHART_COLORS } from '../config/constants';
import KalshiModeBadge from '../components/KalshiModeBadge';
import ExecutionGateStrip from '../components/ExecutionGateStrip';

// ── Interfaces ──────────────────────────────────────────────────────────────

interface SentimentData {
  value: number;
  regime: string;
  confidence: number;
  source: string;
  timestamp: string;
}

interface VolatilityData {
  value: number;  // annualized as fraction
  regime: string;
  uncertainty: number;
  confidence: number;
}

interface SizingMultiplierData {
  value: number;
  regime_label: 'NORMAL' | 'CAUTION' | 'HALTED';
  sentiment_contribution: number;
  volatility_contribution: number;
  reasoning: string;
  is_fallback: boolean;
}

interface AssetState {
  asset: string;
  sentiment: SentimentData | null;
  volatility: VolatilityData | null;
  sizing_multiplier: SizingMultiplierData;
  effective_size_factor: number;
  regime_label: string;
  is_stale: boolean;
}

interface SentimentVolSummary {
  timestamp: string;
  system_assessment: 'NORMAL' | 'CAUTION' | 'CRITICAL';
  summary: {
    total_assets_tracked: number;
    sentiment_distribution: {
      extreme_fear: number;
      fear: number;
      neutral: number;
      greed: number;
      extreme_greed: number;
    };
    volatility_distribution: {
      extreme: number;
      high: number;
      normal: number;
      low_dead: number;
    };
  };
  thresholds: {
    extreme_fear: number;
    fear: number;
    greed: number;
    extreme_greed: number;
    high_vol: number;
    extreme_vol: number;
  };
}

interface SentimentVolAlert {
  asset: string;
  type: string;
  severity: 'HIGH' | 'MEDIUM' | 'LOW';
  message: string;
  value?: number;
  multiplier_impact?: number;
}

/** Stable fallback so `useMemo` deps are not a fresh `{}` each render when data is absent. */
const EMPTY_ASSET_MAP: Record<string, AssetState> = {};

// ── Helpers ─────────────────────────────────────────────────────────────────

const REGIME_CONFIG: Record<string, { label: string; color: string; bg: string; icon: React.ReactNode; desc: string }> = {
  EXTREME_FEAR:  {
    label: 'Extreme Fear',
    color: 'text-red-400',
    bg: 'bg-red-500/20',
    icon: <Snowflake className="w-4 h-4" />,
    desc: 'Capitulation — consider contrarian longs'
  },
  FEAR: {
    label: 'Fear',
    color: 'text-orange-400',
    bg: 'bg-orange-500/20',
    icon: <TrendingDown className="w-4 h-4" />,
    desc: 'Anxiety — reduce size if following crowd'
  },
  NEUTRAL: {
    label: 'Neutral',
    color: 'text-slate-300',
    bg: 'bg-slate-500/20',
    icon: <Activity className="w-4 h-4" />,
    desc: 'Balanced — standard sizing applies'
  },
  GREED: {
    label: 'Greed',
    color: 'text-green-400',
    bg: 'bg-green-500/20',
    icon: <TrendingUp className="w-4 h-4" />,
    desc: 'Optimism — reduce size if following crowd'
  },
  EXTREME_GREED: {
    label: 'Extreme Greed',
    color: 'text-emerald-400',
    bg: 'bg-emerald-500/20',
    icon: <Flame className="w-4 h-4" />,
    desc: 'Mania — consider contrarian shorts'
  },
};

const VOL_REGIME_CONFIG: Record<string, { label: string; color: string; bg: string; sizingImpact: string }> = {
  DEAD:    { label: 'Dead',    color: 'text-blue-400',   bg: 'bg-blue-500/20',    sizingImpact: 'Reduced (0.5×) — low signal' },
  LOW:     { label: 'Low',     color: 'text-cyan-400',   bg: 'bg-cyan-500/20',    sizingImpact: 'Boosted (1.1×) — favorable' },
  TARGET:  { label: 'Target',  color: 'text-green-400',  bg: 'bg-green-500/20',   sizingImpact: 'Normal (1.0×) — baseline' },
  HIGH:    { label: 'High',    color: 'text-amber-400',  bg: 'bg-amber-500/20',   sizingImpact: 'Reduced (0.7×) — caution' },
  EXTREME: { label: 'Extreme', color: 'text-red-400',    bg: 'bg-red-500/20',     sizingImpact: 'Severely reduced (0.3×)' },
};

const SIZING_REGIME_CONFIG: Record<string, { label: string; color: string; bg: string; icon: React.ReactNode }> = {
  NORMAL:  { label: 'Normal',  color: 'text-green-400',  bg: 'bg-green-500/20',  icon: <Shield className="w-4 h-4" /> },
  CAUTION: { label: 'Caution', color: 'text-amber-400',  bg: 'bg-amber-500/20',  icon: <AlertTriangle className="w-4 h-4" /> },
  HALTED:  { label: 'Halted',  color: 'text-red-400',    bg: 'bg-red-500/20',    icon: <Zap className="w-4 h-4" /> },
};

function gaugeColor(score: number): string {
  if (score <= 20) return CHART_COLORS.RED;
  if (score <= 40) return CHART_COLORS.ORANGE;
  if (score <= 60) return CHART_COLORS.GREEN;
  if (score <= 80) return CHART_COLORS.EMERALD;
  return CHART_COLORS.RED; // extreme greed also red
}

function arcPath(score: number, r: number, cx: number, cy: number): string {
  const startAngle = -180;
  const endAngle = startAngle + (score / 100) * 180;
  const startRad = (startAngle * Math.PI) / 180;
  const endRad = (endAngle * Math.PI) / 180;
  const x1 = cx + r * Math.cos(startRad);
  const y1 = cy + r * Math.sin(startRad);
  const x2 = cx + r * Math.cos(endRad);
  const y2 = cy + r * Math.sin(endRad);
  const largeArc = score > 50 ? 1 : 0;
  return `M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2}`;
}

// ── Sub-components ──────────────────────────────────────────────────────────

function FgiGauge({ score, regime, size = 'lg' }: { score: number; regime: string; size?: 'lg' | 'sm' }) {
  const cfg = REGIME_CONFIG[regime] ?? REGIME_CONFIG.NEUTRAL;
  const r = size === 'lg' ? 70 : 40;
  const cx = size === 'lg' ? 90 : 48;
  const cy = size === 'lg' ? 80 : 44;
  const sw = size === 'lg' ? 10 : 6;
  const w = cx * 2;
  const h = size === 'lg' ? 100 : 56;
  const fontSize = size === 'lg' ? 'text-2xl' : 'text-lg';

  return (
    <div className="flex flex-col items-center">
      <svg width={w} height={h} className="overflow-visible">
        <path d={arcPath(100, r, cx, cy)} fill="none" stroke={CHART_COLORS.GRID_STROKE} strokeWidth={sw} strokeLinecap="round" />
        <path d={arcPath(Math.max(score, 1), r, cx, cy)} fill="none" stroke={gaugeColor(score)} strokeWidth={sw} strokeLinecap="round" />
        <text x={cx} y={cy - (size === 'lg' ? 4 : 2)} textAnchor="middle" className={`${fontSize} font-bold fill-white`}>
          {Math.round(score)}
        </text>
      </svg>
      <div className="flex items-center gap-1.5 mt-1">
        <span className={cfg.color}>{cfg.icon}</span>
        <span className={`text-xs font-semibold ${cfg.color}`}>{cfg.label}</span>
      </div>
      <p className="text-[10px] text-slate-500 mt-0.5 text-center max-w-[120px]">{cfg.desc}</p>
    </div>
  );
}

function VolGauge({ value, regime }: { value: number; regime: string }) {
  const cfg = VOL_REGIME_CONFIG[regime] ?? VOL_REGIME_CONFIG.TARGET;
  const pct = Math.min(100, (value / 2) * 100); // 200% vol = 100% gauge

  return (
    <div className="flex flex-col items-center">
      <div className="w-24 h-24 relative">
        <svg viewBox="0 0 100 60" className="w-full h-full">
          {/* Background arc */}
          <path d={arcPath(100, 45, 50, 55)} fill="none" stroke={CHART_COLORS.GRID_STROKE} strokeWidth={8} strokeLinecap="round" />
          {/* Value arc */}
          <path d={arcPath(Math.max(pct, 5), 45, 50, 55)} fill="none" stroke={gaugeColor(value * 50)} strokeWidth={8} strokeLinecap="round" />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center pt-4">
          <span className="text-xl font-bold text-white">{(value * 100).toFixed(0)}%</span>
        </div>
      </div>
      <div className={`px-2 py-0.5 rounded text-[10px] font-bold ${cfg.color} ${cfg.bg}`}>
        {cfg.label}
      </div>
      <p className="text-[10px] text-slate-500 mt-0.5 text-center">{cfg.sizingImpact}</p>
    </div>
  );
}

function SizingMultiplierCard({ multiplier, onDrillDown }: { multiplier: SizingMultiplierData; onDrillDown: () => void }) {
  const cfg = SIZING_REGIME_CONFIG[multiplier.regime_label] ?? SIZING_REGIME_CONFIG.NORMAL;
  const isReduced = multiplier.value < 1.0;

  return (
    <div className={`rounded-xl border p-4 ${cfg.bg} border-opacity-40 transition-all`}
         style={{ borderColor: multiplier.regime_label === 'HALTED' ? '#ef4444' : multiplier.regime_label === 'CAUTION' ? '#f59e0b' : '#22c55e' }}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Target className={`w-5 h-5 ${cfg.color}`} />
          <h3 className="text-sm font-medium text-gray-300">Sizing Multiplier</h3>
        </div>
        <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-bold ${cfg.color} ${cfg.bg}`}>
          {cfg.icon}
          {cfg.label}
        </div>
      </div>

      <div className="flex items-center gap-4 mb-3">
        <div className="text-3xl font-bold text-white">
          {(multiplier.value ?? 0).toFixed(2)}×
        </div>
        <div className="flex-1">
          <div className="flex justify-between text-[10px] text-slate-400 mb-1">
            <span>Sentiment: {((multiplier.sentiment_contribution ?? 0) * 100).toFixed(0)}%</span>
            <span>Vol: {((multiplier.volatility_contribution ?? 0) * 100).toFixed(0)}%</span>
          </div>
          <div className="h-2 bg-slate-800 rounded-full overflow-hidden flex">
            <div
              className={`h-full ${isReduced ? 'bg-amber-500' : 'bg-green-500'}`}
              style={{ width: `${Math.min(100, multiplier.sentiment_contribution * 100)}%` }}
            />
            <div
              className={`h-full ${multiplier.volatility_contribution < 1.0 ? 'bg-red-500' : 'bg-green-500'}`}
              style={{ width: `${Math.min(100, multiplier.volatility_contribution * 100)}%` }}
            />
          </div>
        </div>
      </div>

      <p className="text-xs text-slate-400 mb-3">
        {multiplier.reasoning}
      </p>

      {multiplier.is_fallback && (
        <div className="flex items-center gap-1.5 text-[10px] text-amber-400 mb-3">
          <AlertTriangle className="w-3 h-3" />
          Using fallback values — data may be stale
        </div>
      )}

      <button
        onClick={onDrillDown}
        className="flex items-center gap-2 text-xs text-blue-400 hover:text-blue-300 transition-colors"
      >
        Open Vol Dashboard <ArrowRight className="w-3 h-3" />
      </button>
    </div>
  );
}

function AssetRow({ asset, state, onSelect }: { asset: string; state: AssetState; onSelect: (asset: string) => void }) {
  const sentCfg = state.sentiment ? REGIME_CONFIG[state.sentiment.regime] ?? REGIME_CONFIG.NEUTRAL : null;
  const volCfg = state.volatility ? VOL_REGIME_CONFIG[state.volatility.regime] ?? VOL_REGIME_CONFIG.TARGET : null;
  const sizingCfg = SIZING_REGIME_CONFIG[state.sizing_multiplier.regime_label];

  return (
    <button
      type="button"
      onClick={() => onSelect(asset)}
      className="flex items-center gap-4 p-3 bg-slate-900/50 rounded-lg border border-slate-800 hover:border-slate-700 cursor-pointer transition-all w-full text-left"
    >
      <div className="w-12 font-bold text-white">{asset}</div>

      {/* Sentiment */}
      <div className="flex-1 flex items-center gap-2">
        {sentCfg ? (
          <>
            <span className={sentCfg.color}>{sentCfg.icon}</span>
            <span className={`text-xs ${sentCfg.color}`}>{(state.sentiment?.value ?? 0).toFixed(0)}</span>
          </>
        ) : (
          <span className="text-xs text-slate-500">—</span>
        )}
      </div>

      {/* Volatility */}
      <div className="flex-1 flex items-center gap-2">
        {volCfg ? (
          <>
            <span className={volCfg.color}>{volCfg.label}</span>
            <span className="text-xs text-slate-400">({((state.volatility?.value ?? 0) * 100).toFixed(0)}%)</span>
          </>
        ) : (
          <span className="text-xs text-slate-500">—</span>
        )}
      </div>

      {/* Sizing */}
      <div className="flex items-center gap-2">
        <span className={`text-sm font-bold ${sizingCfg.color}`}>{(state.effective_size_factor ?? 0).toFixed(2)}×</span>
        <span className={`text-[10px] px-1.5 py-0.5 rounded ${sizingCfg.bg} ${sizingCfg.color}`}>
          {state.regime_label}
        </span>
      </div>
    </button>
  );
}

// ── Main Component ───────────────────────────────────────────────────────────

interface KalshiRiskContextViewProps {
  onNavigate?: (view: string) => void;
}

const KalshiRiskContextView: React.FC<KalshiRiskContextViewProps> = ({ onNavigate }) => {
  const std = { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD };
  const slow = { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW };

  // Fetch summary and alerts
  const summaryRes = useApiData<SentimentVolSummary>(API_ENDPOINTS.SENTIMENT_VOL_SUMMARY, std);
  const alertsRes = useApiData<{ alerts: SentimentVolAlert[] }>(API_ENDPOINTS.SENTIMENT_VOL_ALERTS, slow);
  const assetsRes = useApiData<{ assets: Record<string, AssetState> }>(API_ENDPOINTS.SENTIMENT_VOL_ASSETS, std);

  const summary = summaryRes.data;
  const alerts = alertsRes.data?.alerts ?? [];
  const assets = assetsRes.data?.assets ?? EMPTY_ASSET_MAP;

  // Get primary asset (BTC) for detailed display
  const primaryAsset = useMemo(() => {
    return assets['BTC'] ?? Object.values(assets)[0] ?? null;
  }, [assets]);

  const handleDrillDownSentiment = () => {
    onNavigate?.('kalshi-sentiment');
  };

  const handleDrillDownVol = () => {
    onNavigate?.('kalshi-vol-dashboard');
  };

  return (
    <div className="space-y-4">
      <ExecutionGateStrip />

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <Gauge className="w-7 h-7 text-purple-400" />
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-2">
              Risk Context <KalshiModeBadge />
            </h1>
            <p className="text-sm text-gray-400">
              Fear/Greed, Volatility & Sizing at a glance
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {summary && (
            <div className={`px-3 py-1.5 rounded-lg text-sm font-bold ${
              summary.system_assessment === 'CRITICAL' ? 'bg-red-500/20 text-red-400' :
              summary.system_assessment === 'CAUTION' ? 'bg-amber-500/20 text-amber-400' :
              'bg-green-500/20 text-green-400'
            }`}>
              System: {summary.system_assessment}
            </div>
          )}

          <button
            onClick={() => { summaryRes.refetch(); alertsRes.refetch(); assetsRes.refetch(); }}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-gray-300 text-sm"
          >
            <Activity className="w-4 h-4" />
            Refresh
          </button>
        </div>
      </div>

      {/* ═══ TOP ROW: Primary Asset Context ═══ */}
      {primaryAsset && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* 1. Fear/Greed Context */}
          <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Activity className="w-4 h-4 text-blue-400" />
                <h3 className="text-sm font-medium text-gray-300">Sentiment Context</h3>
              </div>
              <span className="text-xs text-slate-500">{primaryAsset.asset}</span>
            </div>

            {primaryAsset.sentiment ? (
              <div className="flex flex-col items-center">
                <FgiGauge score={primaryAsset.sentiment.value} regime={primaryAsset.sentiment.regime} />
                <div className="mt-3 text-center">
                  <p className="text-xs text-slate-400">
                    Confidence: {(primaryAsset.sentiment.confidence * 100).toFixed(0)}%
                  </p>
                  <button
                    onClick={handleDrillDownSentiment}
                    className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 mt-2 mx-auto"
                  >
                    Full sentiment <ArrowRight className="w-3 h-3" />
                  </button>
                </div>
              </div>
            ) : (
              <p className="text-xs text-slate-500 text-center py-8">No sentiment data</p>
            )}
          </div>

          {/* 2. Volatility Context */}
          <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-purple-400" />
                <h3 className="text-sm font-medium text-gray-300">Volatility Context</h3>
              </div>
              <span className="text-xs text-slate-500">{primaryAsset.asset}</span>
            </div>

            {primaryAsset.volatility ? (
              <div className="flex flex-col items-center">
                <VolGauge value={primaryAsset.volatility.value} regime={primaryAsset.volatility.regime} />
                <div className="mt-3 text-center">
                  <p className="text-xs text-slate-400">
                    Uncertainty: {(primaryAsset.volatility.uncertainty * 100).toFixed(0)}%
                  </p>
                  <button
                    onClick={handleDrillDownVol}
                    className="flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 mt-2 mx-auto"
                  >
                    Vol targeting <ArrowRight className="w-3 h-3" />
                  </button>
                </div>
              </div>
            ) : (
              <p className="text-xs text-slate-500 text-center py-8">No volatility data</p>
            )}
          </div>

          {/* 3. Sizing Truth */}
          <SizingMultiplierCard
            multiplier={primaryAsset.sizing_multiplier}
            onDrillDown={handleDrillDownVol}
          />
        </div>
      )}

      {/* ═══ MIDDLE ROW: Alerts & Distribution ═══ */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Active Alerts */}
        <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
          <div className="flex items-center gap-2 mb-4">
            <AlertTriangle className="w-4 h-4 text-amber-400" />
            <h3 className="text-sm font-medium text-gray-300">Active Alerts</h3>
            <span className="ml-auto text-xs text-slate-500">{alerts.length} alerts</span>
          </div>

          {alerts.length === 0 ? (
            <p className="text-xs text-slate-500 text-center py-4">No active alerts</p>
          ) : (
            <div className="space-y-2 max-h-48 overflow-y-auto">
              {alerts.slice(0, 10).map((alert, i) => (
                <div
                  key={i}
                  className={`flex items-center gap-2 p-2 rounded text-xs ${
                    alert.severity === 'HIGH' ? 'bg-red-500/10 border border-red-500/30' :
                    alert.severity === 'MEDIUM' ? 'bg-amber-500/10 border border-amber-500/30' :
                    'bg-slate-800'
                  }`}
                >
                  <span className={`font-bold ${
                    alert.severity === 'HIGH' ? 'text-red-400' :
                    alert.severity === 'MEDIUM' ? 'text-amber-400' :
                    'text-slate-400'
                  }`}>
                    {alert.asset}
                  </span>
                  <span className="text-slate-300">{alert.message}</span>
                  {alert.multiplier_impact !== undefined && (
                    <span className="ml-auto text-slate-400">
                      {alert.multiplier_impact.toFixed(2)}×
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Distribution Summary */}
        {summary && (
          <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
            <div className="flex items-center gap-2 mb-4">
              <Activity className="w-4 h-4 text-cyan-400" />
              <h3 className="text-sm font-medium text-gray-300">Distribution</h3>
              <span className="ml-auto text-xs text-slate-500">
                {summary.summary.total_assets_tracked} assets
              </span>
            </div>

            <div className="grid grid-cols-2 gap-4 text-xs">
              <div>
                <p className="text-slate-500 mb-2">Sentiment</p>
                <div className="space-y-1">
                  {Object.entries(summary.summary.sentiment_distribution).map(([key, count]) => (
                    count > 0 && (
                      <div key={key} className="flex justify-between">
                        <span className="text-slate-400 capitalize">{key.replace('_', ' ')}</span>
                        <span className="text-white">{count}</span>
                      </div>
                    )
                  ))}
                </div>
              </div>
              <div>
                <p className="text-slate-500 mb-2">Volatility</p>
                <div className="space-y-1">
                  {Object.entries(summary.summary.volatility_distribution).map(([key, count]) => (
                    count > 0 && (
                      <div key={key} className="flex justify-between">
                        <span className="text-slate-400 capitalize">{key.replace('_', '/')}</span>
                        <span className="text-white">{count}</span>
                      </div>
                    )
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ═══ BOTTOM ROW: Asset Table ═══ */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-800">
          <Target className="w-4 h-4 text-green-400" />
          <h3 className="text-sm font-medium text-gray-300">All Assets</h3>
          <span className="ml-auto text-xs text-slate-500">
            {Object.keys(assets).length} tracked
          </span>
        </div>

        <div className="divide-y divide-slate-800">
          {Object.entries(assets).map(([asset, state]) => (
            <AssetRow
              key={asset}
              asset={asset}
              state={state}
              onSelect={(a) => {
                // Could navigate to asset-specific view or expand details
                console.log('Selected asset:', a);
              }}
            />
          ))}
        </div>
      </div>

      {/* ═══ FOOTER: Thresholds Reference ═══ */}
      {summary?.thresholds && (
        <div className="bg-slate-900/50 rounded-lg p-3 border border-slate-800 text-[10px] text-slate-500">
          <div className="flex flex-wrap gap-x-6 gap-y-1">
            <span>FGI: {summary.thresholds.extreme_fear}/{summary.thresholds.fear}/{summary.thresholds.greed}/{summary.thresholds.extreme_greed}</span>
            <span>Vol: {(summary.thresholds.high_vol * 100).toFixed(0)}%/{(summary.thresholds.extreme_vol * 100).toFixed(0)}%</span>
          </div>
        </div>
      )}
    </div>
  );
};

export default KalshiRiskContextView;
