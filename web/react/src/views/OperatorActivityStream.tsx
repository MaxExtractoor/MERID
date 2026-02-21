import { useState, useEffect, useCallback } from 'react';
import { Activity, FileText, Brain, RefreshCw } from 'lucide-react';
import { API_BASE_URL, API_ENDPOINTS, DEFAULTS} from '../config/constants';
import { logUiError } from '../utils/logger';
import { formatDateTime } from '../utils/formatters';

type Tab = 'orders' | 'decisions' | 'audit';

interface ActivityOrder {
  id: string;
  symbol: string;
  side: string;
  size: number;
  price: number;
  status: string;
  timestamp: string;
}

interface Decision {
  agent: string;
  type: string;
  confidence: number;
  reasoning: string;
  timestamp: string;
}

interface AuditEntry {
  seq: number;
  timestamp: string;
  event_type: string;
  source: string;
  hash: string;
}

export function OperatorActivityStream() {
  const [tab, setTab] = useState<Tab>('orders');
  const [orders, setOrders] = useState<ActivityOrder[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [auditEntries, setAuditEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchTab = useCallback(async (t: Tab) => {
    setLoading(true);
    try {
      const token = localStorage.getItem('merid-access');
      const headers: HeadersInit = {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      };

      const fetchOperator = (endpoint: string) => fetch(`${API_BASE_URL}${endpoint}`, { headers });

      if (t === 'orders') {
        const res = await fetchOperator(`${API_ENDPOINTS.OPERATOR_ORDERS}?limit=20`);
        if (res.ok) {
          const data = await res.json();
          setOrders(data.orders || data || []);
        }
      } else if (t === 'decisions') {
        const res = await fetchOperator(`${API_ENDPOINTS.SYSTEM_DECISIONS}?limit=10`);
        if (res.ok) {
          const data = await res.json();
          setDecisions(data.decisions || []);
        }
      } else if (t === 'audit') {
        const res = await fetchOperator(`${API_ENDPOINTS.OPERATOR_AUDIT_TRAIL}?limit=20`);
        if (res.ok) {
          const data = await res.json();
          setAuditEntries(data.entries || []);
        }
      }
    } catch (err) {
      logUiError('OperatorActivityStream', 'Fetch failed', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTab(tab);
    const id = setInterval(() => fetchTab(tab), DEFAULTS.POLLING_INTERVALS.MEDIUM);
    return () => clearInterval(id);
  }, [tab, fetchTab]);

  const tabs: { key: Tab; label: string; icon: typeof Activity }[] = [
    { key: 'orders', label: 'Orders', icon: Activity },
    { key: 'decisions', label: 'Decisions', icon: Brain },
    { key: 'audit', label: 'Audit Trail', icon: FileText },
  ];

  return (
    <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-4 space-y-3">
      {/* Tab Bar */}
      <div className="flex items-center justify-between">
        <div className="flex gap-1">
          {tabs.map(({ key, label, icon: Icon }) => (
            <button type="button"
              key={key}
              onClick={() => setTab(key)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                tab === key
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {label}
            </button>
          ))}
        </div>
        <button type="button"
          onClick={() => fetchTab(tab)}
          className="p-1.5 bg-slate-800 hover:bg-slate-700 rounded-lg transition-colors"
          title="Refresh"
        >
          <RefreshCw className={`w-3.5 h-3.5 text-slate-400 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Content */}
      <div className="max-h-80 overflow-y-auto space-y-1">
        {loading && !orders.length && !decisions.length && !auditEntries.length ? (
          <div className="text-center text-slate-500 text-sm py-6">Loading...</div>
        ) : tab === 'orders' ? (
          orders.length === 0 ? (
            <div className="text-center text-slate-500 text-sm py-6">No recent orders</div>
          ) : (
            orders.map((o, i) => (
              <div key={o.id || i} className="flex items-center justify-between px-3 py-2 bg-slate-800/50 rounded-lg text-xs">
                <div className="flex items-center gap-3">
                  <span className={`font-semibold ${o.side === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {o.side}
                  </span>
                  <span className="text-slate-200 font-medium">{o.symbol}</span>
                  <span className="text-slate-500">{o.size}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                    o.status === 'filled' ? 'bg-emerald-500/20 text-emerald-400' :
                    o.status === 'cancelled' ? 'bg-slate-500/20 text-slate-400' :
                    'bg-blue-500/20 text-blue-400'
                  }`}>
                    {o.status}
                  </span>
                  {o.timestamp && <span className="text-slate-600">{formatDateTime(o.timestamp)}</span>}
                </div>
              </div>
            ))
          )
        ) : tab === 'decisions' ? (
          decisions.length === 0 ? (
            <div className="text-center text-slate-500 text-sm py-6">No recent decisions</div>
          ) : (
            decisions.map((d, i) => (
              <div key={i} className="px-3 py-2 bg-slate-800/50 rounded-lg text-xs space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-blue-400 font-medium">{d.agent}</span>
                  <span className="text-slate-500">{d.timestamp && formatDateTime(d.timestamp)}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-slate-300">{d.type}</span>
                  <span className="text-slate-500">conf: {((d.confidence ?? 0) * 100).toFixed(0)}%</span>
                </div>
                {d.reasoning && (
                  <p className="text-slate-500 truncate">{d.reasoning}</p>
                )}
              </div>
            ))
          )
        ) : (
          auditEntries.length === 0 ? (
            <div className="text-center text-slate-500 text-sm py-6">No audit entries</div>
          ) : (
            auditEntries.map((e, i) => (
              <div key={e.seq || i} className="flex items-center justify-between px-3 py-2 bg-slate-800/50 rounded-lg text-xs">
                <div className="flex items-center gap-3">
                  <span className="text-slate-600 font-mono">#{e.seq}</span>
                  <span className="text-slate-300">{e.event_type}</span>
                  <span className="text-slate-500">{e.source}</span>
                </div>
                <span className="text-slate-600 font-mono text-[10px]">{e.hash?.slice(0, 12)}</span>
              </div>
            ))
          )
        )}
      </div>
    </div>
  );
}
