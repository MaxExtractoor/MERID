/**
 * Risk Limit Utilization Bars
 *
 * Horizontal bar chart showing current value vs limit for each risk control.
 * Polls /api/operator/risk-utilization.
 */

import { useState, useEffect, useCallback } from 'react';
import { Shield, AlertTriangle, AlertOctagon } from 'lucide-react';
import { API_BASE_URL } from '../../config/constants';

interface RiskLimit {
  name: string;
  current: number;
  max: number;
  utilization_pct: number;
  status: 'good' | 'warning' | 'critical';
}

interface RiskLimitBarsProps {
  className?: string;
}

const STATUS_COLORS = {
  good: { bar: 'bg-emerald-500', text: 'text-emerald-400', bg: 'bg-emerald-500/10' },
  warning: { bar: 'bg-amber-500', text: 'text-amber-400', bg: 'bg-amber-500/10' },
  critical: { bar: 'bg-red-500', text: 'text-red-400', bg: 'bg-red-500/10' },
};

function StatusIcon({ status }: { status: string }) {
  if (status === 'critical') return <AlertOctagon className="w-3.5 h-3.5 text-red-400" />;
  if (status === 'warning') return <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />;
  return <Shield className="w-3.5 h-3.5 text-emerald-400" />;
}

export function RiskLimitBars({ className = '' }: RiskLimitBarsProps) {
  const [limits, setLimits] = useState<RiskLimit[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/operator/risk-utilization`);
      if (res.ok) {
        const json = await res.json();
        setLimits(json.limits || []);
      }
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 10000);
    return () => clearInterval(id);
  }, [fetchData]);

  return (
    <div className={`bg-slate-900/70 rounded-xl border border-slate-800 p-4 ${className}`}>
      <div className="flex items-center gap-2 mb-4">
        <Shield className="w-4 h-4 text-blue-400" />
        <h3 className="text-sm font-semibold text-slate-300">Risk Limit Utilization</h3>
      </div>

      {loading && limits.length === 0 ? (
        <div className="space-y-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-10 bg-slate-800 rounded animate-pulse" />
          ))}
        </div>
      ) : limits.length === 0 ? (
        <div className="text-sm text-slate-600 text-center py-4">No risk limits data</div>
      ) : (
        <div className="space-y-3">
          {limits.map((limit) => {
            const colors = STATUS_COLORS[limit.status] || STATUS_COLORS.good;
            const pct = Math.min(limit.utilization_pct, 100);
            return (
              <div key={limit.name} className="group">
                {/* Label row */}
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-1.5">
                    <StatusIcon status={limit.status} />
                    <span className="text-xs font-medium text-slate-400">{limit.name}</span>
                  </div>
                  <span className={`text-xs font-semibold ${colors.text}`}>
                    {limit.utilization_pct.toFixed(1)}%
                  </span>
                </div>

                {/* Bar */}
                <div className="relative h-3 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className={`absolute inset-y-0 left-0 rounded-full transition-all duration-500 ${colors.bar}`}
                    style={{ width: `${pct}%` }}
                  />
                  {/* 70% warning line */}
                  <div
                    className="absolute inset-y-0 w-px bg-amber-500/40"
                    style={{ left: '70%' }}
                  />
                  {/* 90% critical line */}
                  <div
                    className="absolute inset-y-0 w-px bg-red-500/40"
                    style={{ left: '90%' }}
                  />
                </div>

                {/* Tooltip on hover */}
                <div className="flex items-center justify-between mt-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                  <span className="text-[10px] text-slate-600">
                    {typeof limit.current === 'number' && limit.current % 1 !== 0
                      ? `$${limit.current.toLocaleString()}`
                      : limit.current}
                  </span>
                  <span className="text-[10px] text-slate-600">
                    max: {typeof limit.max === 'number' && limit.max % 1 !== 0
                      ? `$${limit.max.toLocaleString()}`
                      : limit.max}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
