/**
 * ProtectView — Unified Risk Management & Safety (Stage 8)
 * 
 * Consolidates: KalshiRiskScreen + KalshiRiskContextView + KillSwitchView
 * 
 * Tabs:
 *   - "Overview": Risk summary, exposure, kill switch status
 *   - "Alerts": Live risk alerts and breach history
 *   - "Kill Switch": Emergency controls and safety gates
 *   - "Context": Risk context and market regime analysis
 * 
 * Features:
 *   - Unified risk dashboard
 *   - Kill switch with confirmation flows
 *   - Risk alert feed
 *   - Position downsize controls
 */

import React, { useState, useCallback } from 'react';
import {
  Shield, ShieldAlert, Bell, Activity,
  AlertTriangle, CheckCircle, XCircle, RefreshCw,
  ArrowDownRight, Gauge
} from '../ui/icons';
import { DRAWDOWN_TIER_CONFIG, getDrawdownTierConfig } from '../shared/config/riskConfig';
import { useApiData } from '../hooks/useApiData';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { authHeaders } from '../api/auth';

// Sub-components
import ExecutionGateStrip from '../components/ExecutionGateStrip';
import KalshiModeBadge from '../components/KalshiModeBadge';
import { Card, CardHeader, CardTitle, CardContent } from '../ui/Card';
import { Badge, BadgeVariant } from '../ui/Badge';
import { Button } from '../ui/Button';
import { ConfirmModal } from '../components/ConfirmModal';

// ── Types ────────────────────────────────────────────────────────────────────

interface RiskSummary {
  daily_pnl_usd: number;
  total_unrealized_pnl_usd: number;
  drawdown_pct: number;
  total_notional_usd: number;
  open_market_count: number;
  daily_trades: number;
  kill_switch_active: boolean;
  kill_switch_reason?: string;
  limits: {
    max_daily_loss_usd: number;
    max_notional_usd: number;
    drawdown_halt_pct: number;
  };
  category_notional: Record<string, number>;
  recent_breaches?: Array<{
    ts: string;
    check: string;
    reason: string;
  }>;
}

interface KillSwitchState {
  active: boolean;
  global_kill: boolean;
  kill_reason?: string;
  can_trade: boolean;
  triggered_at?: string;
}

interface RiskAlert {
  id: string;
  level: 'warning' | 'critical' | 'info';
  category: string;
  message: string;
  timestamp: string;
  acknowledged?: boolean;
}

interface SizingMetrics {
  drawdown_tier: 'normal' | 'warning' | 'downsize' | 'halt';
  drawdown_pct: number;
  drawdown_thresholds: {
    warning: number;
    downsize: number;
    halt: number;
  };
  kelly_fraction: number;
  kelly_utilization_pct: number;
  vol_scale: number;
  effective_fraction: number;
  target_vol: number;
  realized_vol: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  calmar_ratio: number;
  win_rate_pct: number;
  profit_factor: number;
  atr_value: number;
  trades_today: number;
}

type ProtectTab = 'overview' | 'alerts' | 'kill-switch' | 'context';

// ── Helpers ─────────────────────────────────────────────────────────────────

function getAlertBadgeVariant(level: RiskAlert['level']): BadgeVariant {
  switch (level) {
    case 'critical': return 'danger';
    case 'warning': return 'warning';
    case 'info': return 'info';
    default: return 'default';
  }
}

// ── Sub-Components ─────────────────────────────────────────────────────────

interface RiskGaugeProps {
  label: string;
  value: number;
  max: number;
  unit?: string;
  color?: string;
}

const RiskGauge: React.FC<RiskGaugeProps> = ({ label, value, max, unit = '', color = 'bg-blue-500' }) => {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  const isWarning = pct > 75;
  const isDanger = pct > 90;
  
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-slate-400">{label}</span>
        <span className={`font-mono ${isDanger ? 'text-red-400' : isWarning ? 'text-yellow-400' : 'text-white'}`}>
          {value.toFixed(1)}{unit}
        </span>
      </div>
      <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
        <div 
          className={`h-full rounded-full transition-all ${
            isDanger ? 'bg-red-500' : isWarning ? 'bg-yellow-500' : color
          }`} 
          style={{ width: `${pct}%` }} 
        />
      </div>
    </div>
  );
};

// ── Main Component ───────────────────────────────────────────────────────────

const ProtectView: React.FC = () => {
  const [activeTab, setActiveTab] = useState<ProtectTab>('overview');
  const [confirmModal, setConfirmModal] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    onConfirm: () => void;
    variant?: 'primary' | 'warning' | 'danger';
  }>({ isOpen: false, title: '', message: '', onConfirm: () => {} });
  const [downsizing, setDownsizing] = useState(false);
  const [downsizeResult, setDownsizeResult] = useState<string | null>(null);

  // Data fetching
  const riskRes = useApiData<RiskSummary>(
    API_ENDPOINTS.KALSHI_RISK,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );

  const ksRes = useApiData<KillSwitchState>(
    API_ENDPOINTS.KALSHI_KILL_SWITCH,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.FAST }
  );

  const sizingRes = useApiData<SizingMetrics>(
    API_ENDPOINTS.KALSHI_SIZING_METRICS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );

  const alertsRes = useApiData<{ alerts: RiskAlert[] }>(
    API_ENDPOINTS.KALSHI_RISK_EVENTS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD }
  );

  const risk = riskRes.data;
  const ks = ksRes.data;
  const sizing = sizingRes.data;
  const alerts = alertsRes.data?.alerts || [];

  const isKillActive = ks?.active || ks?.global_kill || risk?.kill_switch_active;
  const canTrade = ks?.can_trade ?? !isKillActive;

  // Kill switch handlers
  const executeKillSwitch = useCallback(async (activate: boolean) => {
    try {
      const endpoint = activate 
        ? API_ENDPOINTS.OPERATOR_EMERGENCY_STOP 
        : API_ENDPOINTS.OPERATOR_RESET_KILL_SWITCH;
      const body = activate
        ? JSON.stringify({ reason: 'Manual operator activation from Protect view' })
        : JSON.stringify({ confirm: true });
      
      const res = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body,
      });
      
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      
      await Promise.all([riskRes.refetch(), ksRes.refetch()]);
    } catch (err) {
      console.error('Kill switch action failed:', err);
    }
  }, [riskRes, ksRes]);

  const handleKillSwitch = useCallback((activate: boolean) => {
    if (activate) {
      setConfirmModal({
        isOpen: true,
        title: '⚠️ ACTIVATE KILL SWITCH',
        message: 'This will IMMEDIATELY halt ALL trading activity.\n\nAre you sure you want to proceed?',
        variant: 'danger',
        onConfirm: () => {
          setConfirmModal(prev => ({ ...prev, isOpen: false }));
          executeKillSwitch(true);
        },
      });
    } else {
      setConfirmModal({
        isOpen: true,
        title: 'Reset Kill Switch',
        message: 'This will re-enable trading.\n\nEnsure all issues are resolved before proceeding.',
        variant: 'warning',
        onConfirm: () => {
          setConfirmModal(prev => ({ ...prev, isOpen: false }));
          executeKillSwitch(false);
        },
      });
    }
  }, [executeKillSwitch]);

  // Downsize handler
  const handleDownsize = useCallback(async () => {
    setConfirmModal({
      isOpen: true,
      title: 'Confirm Position Downsize',
      message: 'This will reduce position sizes according to current risk parameters.\n\nContinue?',
      variant: 'warning',
      onConfirm: async () => {
        setConfirmModal(prev => ({ ...prev, isOpen: false }));
        setDownsizing(true);
        setDownsizeResult(null);
        try {
          const res = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_RISK_DOWNSIZE}`, {
            method: 'POST',
            headers: authHeaders(),
          });
          const json = await res.json().catch(() => ({}));
          setDownsizeResult(json.message || 'Downsize triggered successfully');
          riskRes.refetch();
        } catch (err) {
          setDownsizeResult(`Failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
        } finally {
          setDownsizing(false);
        }
      },
    });
  }, [riskRes]);

  const tabs = [
    { id: 'overview' as const, label: 'Overview', icon: Shield },
    { id: 'alerts' as const, label: `Alerts (${alerts.filter(a => !a.acknowledged).length})`, icon: Bell },
    { id: 'kill-switch' as const, label: 'Kill Switch', icon: ShieldAlert },
    { id: 'context' as const, label: 'Context', icon: Activity },
  ];

  const tier = sizing ? DRAWDOWN_TIER_CONFIG[sizing.drawdown_tier] : DRAWDOWN_TIER_CONFIG.normal;

  return (
    <div className="space-y-4">
      <ExecutionGateStrip />
      
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-3">
          <Shield className={`w-6 h-6 ${isKillActive ? 'text-red-400' : 'text-red-300'}`} />
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-2">
              Protect <KalshiModeBadge />
            </h1>
            <p className="text-sm text-slate-400">
              Risk management and safety controls
            </p>
          </div>
        </div>
        
        {/* Kill Switch Quick Status */}
        <div className={`flex items-center gap-3 px-4 py-2 rounded-lg border ${
          isKillActive 
            ? 'bg-red-500/10 border-red-500/30' 
            : 'bg-green-500/10 border-green-500/30'
        }`}>
          {isKillActive ? (
            <>
              <XCircle className="w-5 h-5 text-red-400" />
              <div>
                <div className="text-sm font-bold text-red-400">KILL SWITCH ACTIVE</div>
                <div className="text-xs text-red-300">{ks?.kill_reason || risk?.kill_switch_reason || 'Manual activation'}</div>
              </div>
            </>
          ) : (
            <>
              <CheckCircle className="w-5 h-5 text-green-400" />
              <div>
                <div className="text-sm font-bold text-green-400">TRADING ENABLED</div>
                <div className="text-xs text-green-300">All systems operational</div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 bg-slate-800 rounded-lg p-1 w-fit">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? 'bg-slate-700 text-white'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            <tab.icon className="w-4 h-4" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="min-h-[500px]">
        {/* Overview Tab */}
        {activeTab === 'overview' && (
          <div className="space-y-4">
            {/* Risk Summary Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Card>
                <CardContent className="p-4">
                  <div className="text-xs text-slate-500 mb-1">Daily PnL</div>
                  <div className={`text-2xl font-bold ${(risk?.daily_pnl_usd || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    ${(risk?.daily_pnl_usd || 0).toFixed(2)}
                  </div>
                  <div className="text-xs text-slate-500">
                    Max: -${(risk?.limits?.max_daily_loss_usd || 0).toFixed(0)}
                  </div>
                </CardContent>
              </Card>
              
              <Card>
                <CardContent className="p-4">
                  <div className="text-xs text-slate-500 mb-1">Drawdown</div>
                  <div className={`text-2xl font-bold ${
                    (risk?.drawdown_pct || 0) < 5 ? 'text-green-400' : 
                    (risk?.drawdown_pct || 0) < 10 ? 'text-yellow-400' : 'text-red-400'
                  }`}>
                    {(risk?.drawdown_pct || 0).toFixed(1)}%
                  </div>
                  <div className="text-xs text-slate-500">
                    Halt: {((risk?.limits?.drawdown_halt_pct || 0.15) * 100).toFixed(0)}%
                  </div>
                </CardContent>
              </Card>
              
              <Card>
                <CardContent className="p-4">
                  <div className="text-xs text-slate-500 mb-1">Notional</div>
                  <div className="text-2xl font-bold text-white">
                    ${(risk?.total_notional_usd || 0).toFixed(0)}
                  </div>
                  <div className="text-xs text-slate-500">
                    Max: ${(risk?.limits?.max_notional_usd || 0).toFixed(0)}
                  </div>
                </CardContent>
              </Card>
              
              <Card className={isKillActive ? 'border-red-500/30' : ''}>
                <CardContent className="p-4">
                  <div className="text-xs text-slate-500 mb-1">Status</div>
                  <div className={`text-2xl font-bold ${isKillActive ? 'text-red-400' : 'text-green-400'}`}>
                    {isKillActive ? 'HALTED' : 'ACTIVE'}
                  </div>
                  <div className="text-xs text-slate-500">
                    {risk?.open_market_count || 0} open markets
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Drawdown Tier & Gauges */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Drawdown Tier Card */}
              {sizing && (
                <Card>
                  <CardHeader>
                    <CardTitle>Drawdown Tier</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className={`flex items-center gap-3 p-3 rounded-lg ${tier.bg}`}>
                      <div className={tier.color}>{React.createElement(tier.icon, { className: 'w-5 h-5' })}</div>
                      <div>
                        <div className={`font-bold ${tier.color}`}>{tier.label}</div>
                        <div className="text-xs text-slate-400">
                          {(sizing.drawdown_pct || 0).toFixed(1)}% / 
                          W:{(sizing.drawdown_thresholds?.warning || 0)}% 
                          D:{(sizing.drawdown_thresholds?.downsize || 0)}% 
                          H:{(sizing.drawdown_thresholds?.halt || 0)}%
                        </div>
                      </div>
                    </div>
                    
                    {(sizing.drawdown_tier === 'downsize' || sizing.drawdown_tier === 'halt') && (
                      <Button
                        variant="warning"
                        onClick={handleDownsize}
                        loading={downsizing}
                        className="w-full"
                      >
                        <ArrowDownRight className="w-4 h-4 mr-2" />
                        Force Position Downsize
                      </Button>
                    )}
                    
                    {downsizeResult && (
                      <div className="text-xs text-orange-300 bg-orange-900/20 p-2 rounded">
                        {downsizeResult}
                      </div>
                    )}
                  </CardContent>
                </Card>
              )}

              {/* Risk Gauges */}
              <Card>
                <CardHeader>
                  <CardTitle>Risk Utilization</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <RiskGauge 
                    label="Daily Loss" 
                    value={Math.abs(risk?.daily_pnl_usd || 0)} 
                    max={risk?.limits?.max_daily_loss_usd || 500}
                    unit="$"
                    color="bg-red-500"
                  />
                  <RiskGauge 
                    label="Drawdown" 
                    value={risk?.drawdown_pct || 0} 
                    max={(risk?.limits?.drawdown_halt_pct || 0.15) * 100}
                    unit="%"
                    color="bg-orange-500"
                  />
                  <RiskGauge 
                    label="Notional" 
                    value={risk?.total_notional_usd || 0} 
                    max={risk?.limits?.max_notional_usd || 10000}
                    unit="$"
                    color="bg-blue-500"
                  />
                </CardContent>
              </Card>
            </div>

            {/* Category Exposure */}
            {risk?.category_notional && Object.keys(risk.category_notional).length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>Category Exposure</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    {Object.entries(risk.category_notional).map(([cat, notional]) => (
                      <div key={cat} className="flex items-center gap-4">
                        <span className="text-sm text-slate-400 w-20 capitalize">{cat}</span>
                        <div className="flex-1">
                          <RiskGauge 
                            label="" 
                            value={notional as number} 
                            max={(risk?.limits?.max_notional_usd || 10000) / 2}
                            unit="$"
                          />
                        </div>
                        <span className="text-sm text-white font-mono">
                          ${(notional as number).toFixed(0)}
                        </span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        )}

        {/* Alerts Tab */}
        {activeTab === 'alerts' && (
          <Card>
            <CardHeader
              action={
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => alertsRes.refetch()}
                  icon={<RefreshCw className="w-4 h-4" />}
                >
                  Refresh
                </Button>
              }
            >
              <CardTitle>Risk Alerts</CardTitle>
            </CardHeader>
            <CardContent>
              {alerts.length === 0 ? (
                <div className="text-center py-8 text-slate-500">
                  <CheckCircle className="w-12 h-12 mx-auto mb-3 opacity-50" />
                  <p>No active risk alerts</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {alerts.map(alert => (
                    <div 
                      key={alert.id}
                      className={`flex items-start gap-3 p-3 rounded-lg border ${
                        alert.level === 'critical' ? 'bg-red-500/10 border-red-500/30' :
                        alert.level === 'warning' ? 'bg-yellow-500/10 border-yellow-500/30' :
                        'bg-slate-800 border-slate-700'
                      }`}
                    >
                      <Badge variant={getAlertBadgeVariant(alert.level)}>
                        {alert.level.toUpperCase()}
                      </Badge>
                      <div className="flex-1">
                        <div className="text-sm text-white">{alert.message}</div>
                        <div className="text-xs text-slate-500 mt-1">
                          {alert.category} · {new Date(alert.timestamp).toLocaleTimeString()}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {/* Kill Switch Tab */}
        {activeTab === 'kill-switch' && (
          <div className="space-y-4">
            {/* Kill Switch Control */}
            <Card className={isKillActive ? 'border-red-500/30' : ''}>
              <CardHeader>
                <CardTitle className={isKillActive ? 'text-red-400' : ''}>
                  Emergency Kill Switch
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className={`p-4 rounded-lg ${isKillActive ? 'bg-red-500/10' : 'bg-green-500/10'}`}>
                  <div className="flex items-center gap-3">
                    {isKillActive ? (
                      <XCircle className="w-8 h-8 text-red-400" />
                    ) : (
                      <CheckCircle className="w-8 h-8 text-green-400" />
                    )}
                    <div>
                      <div className={`font-bold ${isKillActive ? 'text-red-400' : 'text-green-400'}`}>
                        {isKillActive ? 'KILL SWITCH IS ACTIVE' : 'Trading is enabled'}
                      </div>
                      {ks?.triggered_at && (
                        <div className="text-sm text-slate-400">
                          Triggered: {new Date(ks.triggered_at).toLocaleString()}
                        </div>
                      )}
                    </div>
                  </div>
                </div>

                <div className="flex gap-3">
                  {!isKillActive ? (
                    <Button
                      variant="danger"
                      size="lg"
                      onClick={() => handleKillSwitch(true)}
                      className="flex-1"
                    >
                      <ShieldAlert className="w-5 h-5 mr-2" />
                      ACTIVATE KILL SWITCH
                    </Button>
                  ) : (
                    <Button
                      variant="warning"
                      size="lg"
                      onClick={() => handleKillSwitch(false)}
                      className="flex-1"
                    >
                      <CheckCircle className="w-5 h-5 mr-2" />
                      Reset Kill Switch
                    </Button>
                  )}
                </div>

                <div className="text-xs text-slate-500 bg-slate-800 p-3 rounded-lg">
                  <strong>Warning:</strong> Activating the kill switch will immediately halt all trading 
                  activity and cancel all resting orders. This action cannot be undone automatically.
                </div>
              </CardContent>
            </Card>

            {/* Recent Breaches */}
            {(risk?.recent_breaches?.length || 0) > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>Recent Breaches</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    {risk?.recent_breaches?.map((breach, i) => (
                      <div key={i} className="flex items-start gap-3 text-sm">
                        <AlertTriangle className="w-4 h-4 text-yellow-400 mt-0.5" />
                        <div>
                          <div className="text-white">{breach.check}</div>
                          <div className="text-xs text-slate-400">{breach.reason}</div>
                          <div className="text-xs text-slate-500">
                            {new Date(breach.ts).toLocaleTimeString()}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        )}

        {/* Context Tab */}
        {activeTab === 'context' && (
          <div className="space-y-4">
            {sizing ? (
              <>
                <Card>
                  <CardHeader>
                    <CardTitle>Sizing Metrics</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      <div className="bg-slate-800 rounded-lg p-3">
                        <div className="text-xs text-slate-500 mb-1">Kelly Fraction</div>
                        <div className="text-lg font-bold text-white">{(sizing.kelly_fraction || 0).toFixed(3)}</div>
                      </div>
                      <div className="bg-slate-800 rounded-lg p-3">
                        <div className="text-xs text-slate-500 mb-1">Kelly Utilization</div>
                        <div className="text-lg font-bold text-white">{(sizing.kelly_utilization_pct || 0).toFixed(0)}%</div>
                      </div>
                      <div className="bg-slate-800 rounded-lg p-3">
                        <div className="text-xs text-slate-500 mb-1">Vol Scale</div>
                        <div className="text-lg font-bold text-white">{(sizing.vol_scale || 0).toFixed(2)}x</div>
                      </div>
                      <div className="bg-slate-800 rounded-lg p-3">
                        <div className="text-xs text-slate-500 mb-1">Effective Fraction</div>
                        <div className="text-lg font-bold text-white">{((sizing.effective_fraction || 0) * 100).toFixed(2)}%</div>
                      </div>
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>Performance Metrics</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      <div className="bg-slate-800 rounded-lg p-3">
                        <div className="text-xs text-slate-500 mb-1">Sharpe</div>
                        <div className="text-lg font-bold text-blue-400">{(sizing.sharpe_ratio || 0).toFixed(2)}</div>
                      </div>
                      <div className="bg-slate-800 rounded-lg p-3">
                        <div className="text-xs text-slate-500 mb-1">Sortino</div>
                        <div className="text-lg font-bold text-purple-400">{(sizing.sortino_ratio || 0).toFixed(2)}</div>
                      </div>
                      <div className="bg-slate-800 rounded-lg p-3">
                        <div className="text-xs text-slate-500 mb-1">Calmar</div>
                        <div className="text-lg font-bold text-teal-400">{(sizing.calmar_ratio || 0).toFixed(2)}</div>
                      </div>
                      <div className="bg-slate-800 rounded-lg p-3">
                        <div className="text-xs text-slate-500 mb-1">Win Rate</div>
                        <div className="text-lg font-bold text-white">{(sizing.win_rate_pct || 0).toFixed(0)}%</div>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              </>
            ) : (
              <Card>
                <CardContent className="p-8 text-center">
                  <Gauge className="w-12 h-12 text-slate-600 mx-auto mb-3" />
                  <p className="text-slate-400">Sizing metrics unavailable</p>
                </CardContent>
              </Card>
            )}
          </div>
        )}
      </div>

      {/* Confirm Modal */}
      <ConfirmModal
        isOpen={confirmModal.isOpen}
        title={confirmModal.title}
        message={confirmModal.message}
        confirmVariant={confirmModal.variant}
        onConfirm={confirmModal.onConfirm}
        onCancel={() => setConfirmModal(prev => ({ ...prev, isOpen: false }))}
      />
    </div>
  );
};

export default ProtectView;
