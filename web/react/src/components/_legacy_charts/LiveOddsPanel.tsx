/**
 * LiveOddsPanel — Odds movement table with sparklines and line-move alerts.
 *
 * Shows a compact grid of events with:
 *   - Sport badge + title
 *   - Current book/swarm probs
 *   - Edge magnitude
 *   - OddsSparkline for line movement
 *   - Line-move alert indicator
 */

import { AlertTriangle, Zap } from "lucide-react";
import OddsSparkline from "./OddsSparkline";
import type { EventOddsSnapshot } from "../../hooks/useLiveOdds";

interface LiveOddsPanelProps {
  events: EventOddsSnapshot[];
  maxEvents?: number;
}

const SPORT_COLORS: Record<string, string> = {
  nfl: "bg-green-500/20 text-green-400",
  nba: "bg-orange-500/20 text-orange-400",
  mlb: "bg-red-500/20 text-red-400",
  nhl: "bg-blue-500/20 text-blue-400",
  soccer: "bg-emerald-500/20 text-emerald-400",
  mma: "bg-rose-500/20 text-rose-400",
  politics: "bg-purple-500/20 text-purple-400",
  crypto: "bg-amber-500/20 text-amber-400",
};

export default function LiveOddsPanel({
  events,
  maxEvents = 10,
}: LiveOddsPanelProps) {
  if (events.length === 0) {
    return (
      <div className="text-center py-8 text-slate-500 text-sm">
        No live odds data available
      </div>
    );
  }

  // Sort: live first, then by absolute edge descending
  const sorted = [...events]
    .sort((a, b) => {
      if (a.state === "live" && b.state !== "live") return -1;
      if (b.state === "live" && a.state !== "live") return 1;
      return Math.abs(b.current_edge) - Math.abs(a.current_edge);
    })
    .slice(0, maxEvents);

  return (
    <div className="space-y-1.5">
      {sorted.map((ev) => {
        const sportClass =
          SPORT_COLORS[ev.sport] ?? "bg-slate-500/20 text-slate-400";
        const edgeColor =
          Math.abs(ev.current_edge) >= 0.05
            ? "text-emerald-400"
            : Math.abs(ev.current_edge) >= 0.02
            ? "text-blue-400"
            : "text-slate-400";

        return (
          <div
            key={ev.event_id}
            className="flex items-center gap-3 bg-slate-800/40 border border-slate-700/30 rounded-lg px-3 py-2 hover:border-slate-600/50 transition-colors"
          >
            {/* Sport badge */}
            <span
              className={`px-1.5 py-0.5 text-[9px] font-bold uppercase rounded ${sportClass} shrink-0`}
            >
              {ev.sport}
            </span>

            {/* Live indicator */}
            {ev.state === "live" && (
              <Zap className="w-3 h-3 text-red-400 animate-pulse shrink-0" />
            )}

            {/* Title */}
            <span className="text-xs text-white truncate flex-1 min-w-0">
              {ev.title}
            </span>

            {/* Probs */}
            <div className="flex items-center gap-2 text-[10px] shrink-0">
              <span className="text-blue-400">
                {(ev.current_book_prob * 100).toFixed(0)}%
              </span>
              <span className="text-slate-600">→</span>
              <span className="text-emerald-400">
                {(ev.current_swarm_prob * 100).toFixed(0)}%
              </span>
            </div>

            {/* Edge */}
            <span className={`text-[10px] font-semibold w-10 text-right shrink-0 ${edgeColor}`}>
              {ev.current_edge >= 0 ? "+" : ""}
              {(ev.current_edge * 100).toFixed(1)}%
            </span>

            {/* Sparkline */}
            <OddsSparkline
              data={ev.sparkline}
              width={80}
              height={24}
              showAlert={ev.line_move_alert}
            />

            {/* Line move alert */}
            {ev.line_move_alert && (
              <AlertTriangle className="w-3 h-3 text-amber-400 shrink-0" />
            )}
          </div>
        );
      })}
    </div>
  );
}
