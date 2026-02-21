/**
 * AgentCalibrationProfile — Per-agent detail card showing:
 *   - Calibration scatter plot
 *   - Badge tier pills
 *   - Brier score + total points
 *   - Prediction count
 *
 * Designed to be shown in a modal or expandable panel.
 */

import { Award, Target, Trophy, Shield } from "lucide-react";
import CalibrationChart from "./CalibrationChart";
import type {
  AgentCalibrationData,
  AgentBadge,
} from "../../hooks/useDebateCalibration";

interface AgentCalibrationProfileProps {
  agentId: string;
  calibration: AgentCalibrationData | null;
  badges: AgentBadge[];
  rewardsTotal: number;
  loading: boolean;
  onClose?: () => void;
}

const TIER_COLORS: Record<string, string> = {
  gold: "bg-yellow-500/20 text-yellow-400 border-yellow-500/40",
  silver: "bg-slate-400/20 text-slate-300 border-slate-400/40",
  bronze: "bg-amber-700/20 text-amber-500 border-amber-700/40",
};

const TIER_ICONS: Record<string, typeof Trophy> = {
  gold: Trophy,
  silver: Award,
  bronze: Shield,
};

export default function AgentCalibrationProfile({
  agentId,
  calibration,
  badges,
  rewardsTotal,
  loading,
  onClose,
}: AgentCalibrationProfileProps) {
  if (loading) {
    return (
      <div className="bg-slate-800/80 border border-slate-700/50 rounded-xl p-6 animate-pulse">
        <div className="h-4 bg-slate-700 rounded w-48 mb-4" />
        <div className="h-40 bg-slate-700/50 rounded" />
      </div>
    );
  }

  const calScore = calibration?.calibration_score;
  const calColor =
    calScore !== null && calScore !== undefined
      ? calScore >= 0.8
        ? "text-emerald-400"
        : calScore >= 0.6
        ? "text-blue-400"
        : calScore >= 0.4
        ? "text-amber-400"
        : "text-red-400"
      : "text-slate-500";

  return (
    <div className="bg-slate-800/80 border border-slate-700/50 rounded-xl p-5 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-white flex items-center gap-2">
            <Target className="w-4 h-4 text-blue-400" />
            {agentId}
          </h3>
          <div className="text-[11px] text-slate-500 mt-0.5">
            {calibration?.total_predictions ?? 0} predictions ·{" "}
            {rewardsTotal.toFixed(1)} reward pts
          </div>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-slate-300 text-sm px-2"
          >
            ✕
          </button>
        )}
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-slate-700/30 rounded-lg p-3 text-center">
          <div className="text-[10px] text-slate-500 uppercase">
            Calibration
          </div>
          <div className={`text-xl font-bold ${calColor}`}>
            {calScore !== null && calScore !== undefined
              ? calScore.toFixed(3)
              : "—"}
          </div>
        </div>
        <div className="bg-slate-700/30 rounded-lg p-3 text-center">
          <div className="text-[10px] text-slate-500 uppercase">
            Predictions
          </div>
          <div className="text-xl font-bold text-white">
            {calibration?.total_predictions ?? 0}
          </div>
        </div>
        <div className="bg-slate-700/30 rounded-lg p-3 text-center">
          <div className="text-[10px] text-slate-500 uppercase">
            Reward Pts
          </div>
          <div className="text-xl font-bold text-yellow-400">
            {rewardsTotal.toFixed(1)}
          </div>
        </div>
      </div>

      {/* Badges */}
      {badges.length > 0 && (
        <div>
          <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-1.5">
            Badges
          </div>
          <div className="flex flex-wrap gap-1.5">
            {badges.map((b, i) => {
              const tierClass =
                TIER_COLORS[b.tier] ?? "bg-slate-700/50 text-slate-400 border-slate-600";
              const Icon = TIER_ICONS[b.tier] ?? Award;
              return (
                <span
                  key={i}
                  className={`flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border ${tierClass}`}
                >
                  <Icon className="w-3 h-3" />
                  {b.name}
                </span>
              );
            })}
          </div>
        </div>
      )}

      {/* Calibration chart */}
      {calibration && calibration.bins.length > 0 && (
        <div>
          <div className="text-[10px] text-slate-500 uppercase tracking-wide mb-1.5">
            Calibration Plot
          </div>
          <CalibrationChart bins={calibration.bins} height={200} />
        </div>
      )}
    </div>
  );
}
