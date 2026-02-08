/**
 * ConsensusPill — renders a colored pill showing the swarm's consensus
 * stance for a given symbol.
 *
 * Props:
 *   symbol  — the currently-selected trading symbol (e.g. "BTC-USD")
 *   summary — the full UseConsensusSummaryResult from the hook
 *
 * When the symbol has no data or the response is a stub, a muted gray
 * pill reading "Consensus: No data (simulation)" is shown.
 */

import React from "react";
import { isStub } from "../utils/stub";
import type {
  UseConsensusSummaryResult,
  Stance,
} from "../hooks/useConsensusSummary";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";

interface ConsensusPillProps {
  symbol: string;
  summary: UseConsensusSummaryResult;
}

const STANCE_CONFIG: Record<
  Stance,
  { label: string; classes: string; Icon: React.ElementType }
> = {
  strong_long: {
    label: "Consensus: Strong Long",
    classes: "bg-emerald-500/20 text-emerald-400 border-emerald-500/40",
    Icon: TrendingUp,
  },
  weak_long: {
    label: "Consensus: Weak Long",
    classes:
      "bg-transparent text-emerald-400 border-emerald-500/50",
    Icon: TrendingUp,
  },
  neutral: {
    label: "Consensus: Neutral",
    classes: "bg-slate-500/20 text-slate-400 border-slate-500/40",
    Icon: Minus,
  },
  weak_short: {
    label: "Consensus: Weak Short",
    classes:
      "bg-transparent text-red-400 border-red-500/50",
    Icon: TrendingDown,
  },
  strong_short: {
    label: "Consensus: Strong Short",
    classes: "bg-red-500/20 text-red-400 border-red-500/40",
    Icon: TrendingDown,
  },
};

export default function ConsensusPill({ symbol, summary }: ConsensusPillProps) {
  const entry = summary.bySymbol[symbol];
  const stubbed = isStub(summary.rawResponse) || !entry;

  if (stubbed) {
    return (
      <span
        className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium border border-slate-600/40 bg-slate-700/30 text-slate-500"
        data-testid="consensus-pill"
        data-stance="none"
      >
        <Minus className="w-3 h-3" />
        Consensus: No data (simulation)
      </span>
    );
  }

  const cfg = STANCE_CONFIG[entry.stance] ?? STANCE_CONFIG.neutral;
  const { Icon } = cfg;

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium border ${cfg.classes}`}
      data-testid="consensus-pill"
      data-stance={entry.stance}
      title={`Confidence: ${(entry.confidence * 100).toFixed(0)}% · ${entry.supporting_agents} supporting · ${entry.opposing_agents} opposing`}
    >
      <Icon className="w-3 h-3" />
      {cfg.label}
    </span>
  );
}
