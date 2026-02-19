/**
 * ConsensusTable — cross-market consensus overview for Risk / Operator views.
 *
 * Columns: Symbol · Asset Class · Stance · Confidence · Plans · Support vs Oppose
 * Sortable by stance strength, confidence, or plan count.
 * Gated by isStub() — shows a "simulation" banner when data is stubbed.
 */

import { useMemo, useState } from "react";
import { isStub, stubMessage } from "../utils/stub";
import type {
  UseConsensusSummaryResult,
  ConsensusSymbolSummary,
  Stance,
} from "../hooks/useConsensusSummary";
import { AlertTriangle, ArrowUpDown } from "lucide-react";
import { ExecutionGateChip } from './ExecutionGateChip';
import { useExecutionGate } from '../hooks/useExecutionGate';

interface ConsensusTableProps {
  summary: UseConsensusSummaryResult;
  onSymbolClick?: (symbol: string) => void;
}

type SortKey = "stance" | "confidence" | "plans";

const STANCE_ORDER: Record<Stance, number> = {
  strong_long: 5,
  weak_long: 4,
  neutral: 3,
  weak_short: 2,
  strong_short: 1,
};

const STANCE_LABEL: Record<Stance, string> = {
  strong_long: "Strong Long",
  weak_long: "Weak Long",
  neutral: "Neutral",
  weak_short: "Weak Short",
  strong_short: "Strong Short",
};

const STANCE_COLOR: Record<Stance, string> = {
  strong_long: "text-emerald-400",
  weak_long: "text-emerald-300",
  neutral: "text-slate-400",
  weak_short: "text-red-300",
  strong_short: "text-red-400",
};

function totalPlans(s: ConsensusSymbolSummary): number {
  return s.active_plans.proposed + s.active_plans.approved + s.active_plans.executing;
}

function SupportOpposeBar({ supporting, opposing }: { supporting: number; opposing: number }) {
  const total = supporting + opposing;
  if (total === 0) {
    return <div className="h-2 rounded bg-slate-700 w-full" />;
  }
  const supPct = (supporting / total) * 100;
  const oppPct = 100 - supPct;

  const barColor =
    supPct > 60 ? "bg-emerald-500" : oppPct > 60 ? "bg-red-500" : "bg-slate-400";
  const oppColor =
    oppPct > 60 ? "bg-red-500" : supPct > 60 ? "bg-emerald-500/30" : "bg-slate-500";

  return (
    <div className="flex h-2 rounded overflow-hidden w-full" title={`${supporting} for / ${opposing} against`}>
      <div className={`${barColor}`} style={{ width: `${supPct}%` }} />
      <div className={`${oppColor}`} style={{ width: `${oppPct}%` }} />
    </div>
  );
}

export default function ConsensusTable({ summary, onSymbolClick }: ConsensusTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("confidence");
  const [sortDesc, setSortDesc] = useState(true);
  const stubbed = isStub(summary.rawResponse);
  const { blocked } = useExecutionGate();

  const sorted = useMemo(() => {
    const items = [...summary.symbols];
    items.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "stance":
          cmp = STANCE_ORDER[a.stance] - STANCE_ORDER[b.stance];
          break;
        case "confidence":
          cmp = a.confidence - b.confidence;
          break;
        case "plans":
          cmp = totalPlans(a) - totalPlans(b);
          break;
      }
      return sortDesc ? -cmp : cmp;
    });
    return items;
  }, [summary.symbols, sortKey, sortDesc]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDesc(!sortDesc);
    } else {
      setSortKey(key);
      setSortDesc(true);
    }
  };

  if (stubbed) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-6" data-testid="consensus-table-stub">
        <div className="flex items-center gap-2 text-amber-400 text-sm mb-2">
          <AlertTriangle className="w-4 h-4" />
          <span className="font-medium">Consensus metrics not available (simulation)</span>
        </div>
        <p className="text-slate-500 text-xs">{stubMessage(summary.rawResponse)}</p>
      </div>
    );
  }

  if (sorted.length === 0) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-6 text-center text-slate-500 text-sm" data-testid="consensus-table-empty">
        No consensus data across any markets yet.
      </div>
    );
  }

  const SortHeader = ({ label, field }: { label: string; field: SortKey }) => (
    <th
      className="px-3 py-2 text-left text-xs font-medium text-slate-400 cursor-pointer select-none hover:text-slate-200 whitespace-nowrap"
      onClick={() => toggleSort(field)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        <ArrowUpDown className="w-3 h-3 opacity-50" />
      </span>
    </th>
  );

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800/50 overflow-hidden" data-testid="consensus-table">
      {blocked && (
        <div className="flex items-center gap-2 px-3 py-2 bg-red-950/40 border-b border-red-500/20 text-[11px] text-red-300">
          <ExecutionGateChip variant="inline" />
          <span className="text-slate-500">Plans are generated but cannot execute while gate is blocked.</span>
        </div>
      )}
      <table className="w-full text-sm">
        <thead className="bg-slate-800">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-400">Symbol</th>
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-400">Class</th>
            <SortHeader label="Stance" field="stance" />
            <SortHeader label="Confidence" field="confidence" />
            <SortHeader label="Plans" field="plans" />
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-32">Support vs Oppose</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/50">
          {sorted.map((s) => (
            <tr
              key={s.symbol}
              className="hover:bg-slate-700/30 transition-colors cursor-pointer"
              onClick={() => onSymbolClick?.(s.symbol)}
              data-testid={`consensus-row-${s.symbol}`}
            >
              <td className="px-3 py-2 font-mono text-slate-200">{s.symbol}</td>
              <td className="px-3 py-2 text-slate-400 capitalize">{s.asset_class}</td>
              <td className={`px-3 py-2 font-medium ${STANCE_COLOR[s.stance]}`}>
                {STANCE_LABEL[s.stance]}
              </td>
              <td className="px-3 py-2 text-slate-300">{(s.confidence * 100).toFixed(0)}%</td>
              <td className="px-3 py-2 text-slate-400">
                <span title="proposed / approved / executing">
                  {s.active_plans.proposed}/{s.active_plans.approved}/{s.active_plans.executing}
                </span>
              </td>
              <td className="px-3 py-2">
                <SupportOpposeBar supporting={s.supporting_agents} opposing={s.opposing_agents} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
