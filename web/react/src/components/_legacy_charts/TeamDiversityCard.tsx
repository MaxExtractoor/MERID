/**
 * TeamDiversityCard — Visual gauge showing strategy diversity score
 * for a team, plus the strategy breakdown.
 */

interface TeamDiversityCardProps {
  teamId: string;
  teamName?: string;
  diversityScore: number;
  strategies: string[];
  memberCount?: number;
}

const STRATEGY_COLORS: Record<string, string> = {
  mean_reversion: "bg-blue-500",
  momentum: "bg-emerald-500",
  contrarian: "bg-red-500",
  challenger: "bg-amber-500",
  arbiter: "bg-purple-500",
  arbiter_bayesian: "bg-indigo-500",
  arbiter_extremizing: "bg-pink-500",
  arbiter_median: "bg-teal-500",
};

export default function TeamDiversityCard({
  teamId,
  teamName,
  diversityScore,
  strategies,
  memberCount,
}: TeamDiversityCardProps) {
  const pct = Math.round(diversityScore * 100);
  const color =
    pct >= 75
      ? "text-emerald-400"
      : pct >= 50
      ? "text-blue-400"
      : pct >= 25
      ? "text-amber-400"
      : "text-red-400";

  const ringColor =
    pct >= 75
      ? "stroke-emerald-500"
      : pct >= 50
      ? "stroke-blue-500"
      : pct >= 25
      ? "stroke-amber-500"
      : "stroke-red-500";

  const circumference = 2 * Math.PI * 36;
  const offset = circumference - (pct / 100) * circumference;

  return (
    <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
      <div className="flex items-center gap-4">
        {/* Circular gauge */}
        <div className="relative w-20 h-20 shrink-0">
          <svg className="w-20 h-20 -rotate-90" viewBox="0 0 80 80">
            <circle
              cx="40"
              cy="40"
              r="36"
              fill="none"
              stroke="#334155"
              strokeWidth="6"
            />
            <circle
              cx="40"
              cy="40"
              r="36"
              fill="none"
              className={ringColor}
              strokeWidth="6"
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={offset}
              style={{ transition: "stroke-dashoffset 0.6s ease" }}
            />
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className={`text-lg font-bold ${color}`}>{pct}%</span>
          </div>
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-white truncate">
            {teamName ?? teamId}
          </div>
          <div className="text-[11px] text-slate-500 mt-0.5">
            Diversity Score
            {memberCount !== undefined && ` · ${memberCount} members`}
          </div>

          {/* Strategy pills */}
          <div className="flex flex-wrap gap-1 mt-2">
            {strategies.map((s) => (
              <span
                key={s}
                className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-300"
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    STRATEGY_COLORS[s] ?? "bg-slate-500"
                  }`}
                />
                {s.replace(/_/g, " ")}
              </span>
            ))}
            {strategies.length === 0 && (
              <span className="text-[10px] text-slate-500">No strategies</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
