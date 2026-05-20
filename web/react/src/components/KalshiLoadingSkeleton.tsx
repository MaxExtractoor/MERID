
/**
 * KalshiLoadingSkeleton - Kalshi-branded loading skeleton for lazy-loaded views
 * Used with React.Suspense for code splitting (Tier 1 optimization)
 */
export default function KalshiLoadingSkeleton() {
  return (
    <div className="flex flex-col items-center justify-center h-full p-8">
      <div className="w-full max-w-2xl space-y-6">
        {/* Header skeleton */}
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-lg bg-slate-800/50 animate-pulse" />
          <div className="flex-1 space-y-2">
            <div className="h-6 bg-slate-800/50 rounded animate-pulse w-1/3" />
            <div className="h-4 bg-slate-800/30 rounded animate-pulse w-1/4" />
          </div>
        </div>

        {/* Metric cards skeleton */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="bg-slate-900/70 rounded-xl border border-slate-800 p-4 space-y-3">
              <div className="h-3 bg-slate-800/50 rounded animate-pulse w-1/2" />
              <div className="h-8 bg-slate-800/30 rounded animate-pulse w-3/4" />
            </div>
          ))}
        </div>

        {/* Main content skeleton */}
        <div className="bg-slate-900/70 rounded-xl border border-slate-800 p-6 space-y-4">
          <div className="h-5 bg-slate-800/50 rounded animate-pulse w-1/4" />
          <div className="space-y-3">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="flex items-center gap-4">
                <div className="w-16 h-16 bg-slate-800/30 rounded-lg animate-pulse" />
                <div className="flex-1 space-y-2">
                  <div className="h-4 bg-slate-800/50 rounded animate-pulse w-2/3" />
                  <div className="h-3 bg-slate-800/30 rounded animate-pulse w-1/2" />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Loading indicator */}
        <div className="flex items-center justify-center gap-3 text-slate-400">
          <div className="w-5 h-5 border-2 border-blue-500/30 border-t-blue-500 rounded-full animate-spin" />
          <span className="text-sm">Loading Kalshi dashboard...</span>
        </div>
      </div>
    </div>
  );
}
