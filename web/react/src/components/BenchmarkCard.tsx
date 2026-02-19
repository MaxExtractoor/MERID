import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS } from '../config/constants';
import ErrorBar from './ErrorBar';
import { Activity, CheckCircle2, AlertTriangle, XCircle, HelpCircle } from 'lucide-react';

interface BenchmarkItem {
  name: string;
  category: string;
  status: 'pass' | 'warn' | 'fail' | 'no_data';
  value: any;
  target: string;
  detail: string;
}

interface BenchmarkReport {
  overall: string;
  timestamp: number;
  go_live_ready: boolean;
  summary: {
    pass: number;
    warn: number;
    fail: number;
    no_data: number;
    total: number;
  };
  benchmarks: BenchmarkItem[];
}

const STATUS_CONFIG = {
  pass: { icon: CheckCircle2, color: 'text-emerald-400', bg: 'bg-emerald-900/20', border: 'border-emerald-700/30', label: 'PASS' },
  warn: { icon: AlertTriangle, color: 'text-yellow-400', bg: 'bg-yellow-900/20', border: 'border-yellow-700/30', label: 'WARN' },
  fail: { icon: XCircle, color: 'text-red-400', bg: 'bg-red-900/20', border: 'border-red-700/30', label: 'FAIL' },
  no_data: { icon: HelpCircle, color: 'text-slate-500', bg: 'bg-slate-800/40', border: 'border-slate-700/30', label: 'N/A' },
};

const CATEGORY_LABELS: Record<string, string> = {
  latency: 'Latency & Throughput',
  data_quality: 'Data Quality',
  risk: 'Risk & Exposure',
  alerts: 'Alert Hygiene',
  swarm: 'Swarm / Consensus',
};

function StatusBadge({ status }: { status: keyof typeof STATUS_CONFIG }) {
  const cfg = STATUS_CONFIG[status];
  const Icon = cfg.icon;
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold ${cfg.bg} ${cfg.color} border ${cfg.border}`}>
      <Icon className="w-3 h-3" />
      {cfg.label}
    </span>
  );
}

export default function BenchmarkCard() {
  const { data, error } = useApiData<BenchmarkReport>(API_ENDPOINTS.BENCHMARKS_REPORT, { pollingInterval: 15000 });

  const benchmarks = data?.benchmarks ?? [];
  const categories = [...new Set(benchmarks.map(b => b.category))];

  return (
    <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-blue-400" />
          <h3 className="text-sm font-semibold text-slate-200">Go-Live Benchmarks</h3>
        </div>
        {data && (
          <div className="flex items-center gap-2">
            {data.go_live_ready ? (
              <span className="text-[10px] font-bold bg-emerald-900/40 text-emerald-400 px-2 py-0.5 rounded-full border border-emerald-700/40">
                READY
              </span>
            ) : (
              <span className="text-[10px] font-bold bg-red-900/40 text-red-400 px-2 py-0.5 rounded-full border border-red-700/40">
                NOT READY
              </span>
            )}
            <span className="text-[10px] text-slate-500">
              {data.summary.pass}P {data.summary.warn}W {data.summary.fail}F
            </span>
          </div>
        )}
      </div>

      <ErrorBar label="Benchmarks" error={error} />

      {categories.length === 0 && !error && (
        <p className="text-xs text-slate-500 italic">No benchmark data yet</p>
      )}

      <div className="space-y-3">
        {categories.map(cat => (
          <div key={cat}>
            <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-1.5">
              {CATEGORY_LABELS[cat] ?? cat}
            </div>
            <div className="space-y-1.5">
              {benchmarks.filter(b => b.category === cat).map(b => (
                <div key={b.name} className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <StatusBadge status={b.status} />
                    <span className="text-xs text-slate-300 truncate">
                      {b.name.replace(/_/g, ' ')}
                    </span>
                  </div>
                  <span className="text-[10px] text-slate-500 flex-shrink-0 text-right max-w-[180px] truncate" title={b.detail}>
                    {b.detail || b.target}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
