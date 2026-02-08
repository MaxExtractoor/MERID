/**
 * PredictionEdgePill — colored pill showing swarm stance on a prediction market.
 *
 * Displays: "Swarm: Strong YES", "Swarm: Weak NO", etc.
 * Optionally shows edge bar comparing market_prob vs swarm_prob.
 */

import React from "react";
import type { PredictionStance } from "../hooks/usePredictionConsensus";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";

interface PredictionEdgePillProps {
  stance: PredictionStance;
  edge: number;
  swarmProb: number;
  marketProb: number;
  confidence: number;
  showBar?: boolean;
}

const STANCE_CONFIG: Record<
  PredictionStance,
  { label: string; classes: string; Icon: React.ElementType }
> = {
  strong_yes: {
    label: "Swarm: Strong YES",
    classes: "bg-emerald-500/20 text-emerald-400 border-emerald-500/40",
    Icon: TrendingUp,
  },
  weak_yes: {
    label: "Swarm: Weak YES",
    classes: "bg-transparent text-emerald-400 border-emerald-500/50",
    Icon: TrendingUp,
  },
  neutral: {
    label: "Swarm: Neutral",
    classes: "bg-slate-500/20 text-slate-400 border-slate-500/40",
    Icon: Minus,
  },
  weak_no: {
    label: "Swarm: Weak NO",
    classes: "bg-transparent text-red-400 border-red-500/50",
    Icon: TrendingDown,
  },
  strong_no: {
    label: "Swarm: Strong NO",
    classes: "bg-red-500/20 text-red-400 border-red-500/40",
    Icon: TrendingDown,
  },
};

export default function PredictionEdgePill({
  stance,
  edge,
  swarmProb,
  marketProb,
  confidence,
  showBar = false,
}: PredictionEdgePillProps) {
  const cfg = STANCE_CONFIG[stance] ?? STANCE_CONFIG.neutral;
  const { Icon } = cfg;

  return (
    <div className="inline-flex flex-col gap-1" data-testid="prediction-edge-pill">
      <span
        className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium border ${cfg.classes}`}
        data-stance={stance}
        title={`Edge: ${(edge * 100).toFixed(1)}% · Confidence: ${(confidence * 100).toFixed(0)}%`}
      >
        <Icon className="w-3 h-3" />
        {cfg.label}
        <span className="ml-1 opacity-70">({(edge * 100).toFixed(1)}%)</span>
      </span>

      {showBar && (
        <div className="flex items-center gap-2 text-[10px] text-slate-500 px-1">
          <span>Mkt {(marketProb * 100).toFixed(0)}%</span>
          <div className="relative flex-1 h-1.5 bg-slate-700 rounded-full overflow-hidden">
            {/* Market prob bar */}
            <div
              className="absolute inset-y-0 left-0 bg-slate-500/60 rounded-full"
              style={{ width: `${marketProb * 100}%` }}
            />
            {/* Swarm prob bar overlay */}
            <div
              className={`absolute inset-y-0 left-0 rounded-full ${
                edge >= 0 ? "bg-emerald-500/70" : "bg-red-500/70"
              }`}
              style={{ width: `${swarmProb * 100}%` }}
            />
          </div>
          <span>Swarm {(swarmProb * 100).toFixed(0)}%</span>
        </div>
      )}
    </div>
  );
}
