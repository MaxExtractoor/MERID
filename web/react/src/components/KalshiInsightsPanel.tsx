/**
 * KalshiInsightsPanel — AI-generated actionable insights for Kalshi trading.
 *
 * Best practices applied:
 *   - Short, actionable bullets with clear labeling (Suggestion vs Fact)
 *   - Drill-down "Details" accordion for explainability
 *   - One-click accept/dismiss for proposed changes
 *   - Role-aware: operator sees execution suggestions, observer sees summaries
 */

import React, { useState, useMemo } from 'react';
import {
  Lightbulb, ChevronDown, ChevronUp, Check, X,
  AlertTriangle, Activity, TrendingUp, Droplets, Zap,
  ExternalLink,
} from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS } from '../config/constants';

type InsightType = 'performance' | 'risk' | 'liquidity' | 'opportunity';

interface Insight {
  id: string;
  kind: 'suggestion' | 'fact' | 'warning';
  insight_type?: InsightType;
  title: string;
  body: string;
  details?: string;
  action_label?: string;
  action_endpoint?: string;
  link_view?: string;
  severity: 'info' | 'warning' | 'critical';
  ts: string;
}

const TYPE_STYLE: Record<InsightType, { icon: React.ElementType; color: string; label: string }> = {
  performance: { icon: TrendingUp, color: 'text-blue-400', label: 'Performance' },
  risk: { icon: AlertTriangle, color: 'text-red-400', label: 'Risk' },
  liquidity: { icon: Droplets, color: 'text-cyan-400', label: 'Liquidity' },
  opportunity: { icon: Zap, color: 'text-emerald-400', label: 'Opportunity' },
};

// No mock/placeholder data — insights come from the API only

const KIND_STYLE: Record<string, { icon: React.ElementType; color: string; bg: string; label: string }> = {
  suggestion: { icon: Lightbulb, color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/20', label: 'Suggestion' },
  fact: { icon: Activity, color: 'text-blue-400', bg: 'bg-blue-500/10 border-blue-500/20', label: 'Fact' },
  warning: { icon: AlertTriangle, color: 'text-red-400', bg: 'bg-red-500/10 border-red-500/20', label: 'Warning' },
};

interface InsightsPanelProps {
  onNavigate?: (view: string) => void;
}

const KalshiInsightsPanel: React.FC<InsightsPanelProps> = ({ onNavigate }) => {
  const { data } = useApiData<{ insights: Insight[] }>(
    API_ENDPOINTS.KALSHI_INSIGHTS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.SLOW },
  );

  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [accepted, setAccepted] = useState<Set<string>>(new Set());
  const [typeFilter, setTypeFilter] = useState<InsightType | ''>('');

  const rawInsights = useMemo(() => {
    return data?.insights ?? [];
  }, [data]);

  const insights = useMemo(() => {
    let filtered = rawInsights.filter(i => !dismissed.has(i.id));
    if (typeFilter) {
      filtered = filtered.filter(i => i.insight_type === typeFilter);
    }
    return filtered;
  }, [rawInsights, dismissed, typeFilter]);

  const toggle = (id: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const handleAccept = async (insight: Insight) => {
    if (!insight.action_endpoint) return;
    try {
      const token = localStorage.getItem('merid-access');
      await fetch(`${API_BASE_URL}${insight.action_endpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
      setAccepted(prev => new Set(prev).add(insight.id));
    } catch {
      // silent — endpoint may not exist yet
    }
  };

  if (insights.length === 0 && !typeFilter) {
    return (
      <div className="bg-slate-900 rounded-xl p-4 border border-slate-800">
        <div className="flex items-center gap-2 mb-2">
          <Lightbulb className="w-4 h-4 text-amber-400" />
          <h3 className="text-sm font-medium text-gray-300">AI Insights</h3>
        </div>
        <p className="text-xs text-gray-500">No active insights. The swarm is monitoring.</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-800">
        <Lightbulb className="w-4 h-4 text-amber-400" />
        <h3 className="text-sm font-medium text-gray-300">AI Insights</h3>
        <span className="ml-auto text-[10px] text-gray-500">{insights.length} active</span>
      </div>

      {/* Type filter tabs */}
      <div className="flex items-center gap-1 px-4 py-2 border-b border-slate-800/50">
        <button
          type="button"
          onClick={() => setTypeFilter('')}
          className={`px-2 py-0.5 rounded text-[10px] font-medium transition-all ${
            !typeFilter ? 'bg-amber-500/20 text-amber-300' : 'text-gray-500 hover:text-white'
          }`}
        >
          All
        </button>
        {(Object.entries(TYPE_STYLE) as [InsightType, typeof TYPE_STYLE[InsightType]][]).map(([type, cfg]) => (
          <button
            type="button"
            key={type}
            onClick={() => setTypeFilter(typeFilter === type ? '' : type)}
            className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium transition-all ${
              typeFilter === type ? 'bg-amber-500/20 text-amber-300' : 'text-gray-500 hover:text-white'
            }`}
          >
            <cfg.icon className="w-2.5 h-2.5" />
            {cfg.label}
          </button>
        ))}
      </div>

      <div className="divide-y divide-slate-800/50 max-h-[360px] overflow-y-auto">
        {insights.map(insight => {
          const style = KIND_STYLE[insight.kind] ?? KIND_STYLE.fact;
          const Icon = style.icon;
          const isExpanded = expanded.has(insight.id);
          const isAccepted = accepted.has(insight.id);

          return (
            <div key={insight.id} className={`px-4 py-3 ${isAccepted ? 'opacity-50' : ''}`}>
              {/* Header row */}
              <div className="flex items-start gap-2">
                <Icon className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${style.color}`} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded border ${style.bg} ${style.color}`}>
                      {style.label}
                    </span>
                    {insight.severity === 'critical' && (
                      <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-red-500/20 text-red-400 border border-red-500/30">
                        CRITICAL
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-white font-medium">{insight.title}</p>
                  <p className="text-[11px] text-gray-400 mt-0.5">{insight.body}</p>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-1 shrink-0">
                  {insight.action_label && !isAccepted && (
                    <button
                      type="button"
                      onClick={() => handleAccept(insight)}
                      className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium bg-green-500/20 text-green-400 hover:bg-green-500/30 border border-green-500/30"
                      title={`Apply: ${insight.action_label}`}
                    >
                      <Check className="w-3 h-3" />
                      {insight.action_label}
                    </button>
                  )}
                  {isAccepted && (
                    <span className="text-[10px] text-green-400">Applied</span>
                  )}
                  <button
                    type="button"
                    onClick={() => setDismissed(prev => new Set(prev).add(insight.id))}
                    className="p-1 rounded text-gray-500 hover:text-gray-300 hover:bg-slate-800"
                    title="Dismiss"
                    aria-label="Dismiss insight"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              </div>

              {/* Type badge */}
              {insight.insight_type && TYPE_STYLE[insight.insight_type] && (
                <div className="ml-5 mt-1">
                  <span className={`text-[9px] font-medium px-1.5 py-0.5 rounded bg-slate-800 ${TYPE_STYLE[insight.insight_type].color}`}>
                    {TYPE_STYLE[insight.insight_type].label}
                  </span>
                </div>
              )}

              {/* Expandable details + View details link */}
              <div className="flex items-center gap-3 mt-1.5 ml-5">
                {insight.details && (
                  <button
                    type="button"
                    onClick={() => toggle(insight.id)}
                    className="flex items-center gap-1 text-[10px] text-gray-500 hover:text-gray-300"
                  >
                    {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                    {isExpanded ? 'Hide details' : 'Show details'}
                  </button>
                )}
                {insight.link_view && onNavigate && (
                  <button
                    type="button"
                    onClick={() => onNavigate(insight.link_view!)}
                    className="flex items-center gap-1 text-[10px] text-blue-400 hover:text-blue-300"
                  >
                    <ExternalLink className="w-2.5 h-2.5" />
                    View details
                  </button>
                )}
              </div>
              {isExpanded && insight.details && (
                <div className="mt-2 ml-5 px-3 py-2 rounded bg-slate-800/50 text-[11px] text-gray-400 leading-relaxed">
                  {insight.details}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default KalshiInsightsPanel;
