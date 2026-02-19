import { useApiData } from '../hooks/useApiData';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';
import { Bot, ArrowRight } from 'lucide-react';

interface SignalEntry {
  ts: string;
  market_id: string;
  question: string;
  side: string;
  confidence: number;
  ev_cents: number;
  agent: string;
}

interface OrderEntry {
  ts: string;
  market_id: string;
  side: string;
  size: number;
  price_cents: number;
  status: string;
  source: string;
  agent: string;
}

interface GridAgent {
  name: string;
  signals?: SignalEntry[];
  orders?: OrderEntry[];
}

interface KalshiActivityLogProps {
  ticker: string | null;
  maxItems?: number;
}

export default function KalshiActivityLog({ ticker, maxItems = 12 }: KalshiActivityLogProps) {
  const { data: gridData } = useApiData<{ agents: GridAgent[] }>(
    API_ENDPOINTS.KALSHI_GRID_AGENTS,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.STANDARD },
  );

  if (!gridData) return null;

  // Collect signals and orders mentioning this ticker from all agents
  type LogItem = { ts: string; type: 'signal' | 'order'; agent: string; side: string; detail: string };
  const items: LogItem[] = [];

  for (const agent of gridData.agents ?? []) {
    for (const s of agent.signals ?? []) {
      if (!ticker || s.market_id === ticker) {
        items.push({
          ts: s.ts,
          type: 'signal',
          agent: agent.name,
          side: s.side,
          detail: `EV ${s.ev_cents > 0 ? '+' : ''}${s.ev_cents}¢ · ${(s.confidence * 100).toFixed(0)}% conf`,
        });
      }
    }
    for (const o of agent.orders ?? []) {
      if (!ticker || o.market_id === ticker) {
        items.push({
          ts: o.ts,
          type: 'order',
          agent: agent.name,
          side: o.side,
          detail: `${o.size}×${o.price_cents}¢ ${o.status}`,
        });
      }
    }
  }

  items.sort((a, b) => b.ts.localeCompare(a.ts));
  const visible = items.slice(0, maxItems);

  if (visible.length === 0) {
    return (
      <div className="bg-slate-800 rounded-xl p-3">
        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Agent Activity</h4>
        <p className="text-[10px] text-gray-600 text-center py-3">No agent activity for this market</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-800 rounded-xl p-3">
      <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Agent Activity</h4>
      <div className="space-y-1 max-h-48 overflow-y-auto">
        {visible.map((item, i) => (
          <div key={i} className="flex items-center gap-2 text-[10px] py-1 px-1 rounded hover:bg-slate-700/50">
            {item.type === 'signal' ? (
              <Bot className="w-3 h-3 text-cyan-400 shrink-0" />
            ) : (
              <ArrowRight className="w-3 h-3 text-orange-400 shrink-0" />
            )}
            <span className="text-gray-500 font-mono shrink-0">
              {new Date(item.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
            <span className="text-gray-400 truncate">{item.agent}</span>
            <span className={`font-medium ${item.side === 'yes' ? 'text-green-400' : 'text-red-400'}`}>
              {item.side.toUpperCase()}
            </span>
            <span className="text-gray-500 truncate">{item.detail}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
