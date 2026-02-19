interface SkeletonProps {
  className?: string;
  style?: React.CSSProperties;
}

function Bone({ className = '', style }: SkeletonProps) {
  return (
    <div className={`animate-pulse bg-slate-700/50 rounded ${className}`} style={style} />
  );
}

export function SkeletonCard() {
  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <Bone className="h-4 w-24" />
        <Bone className="h-4 w-12" />
      </div>
      <Bone className="h-8 w-32" />
      <Bone className="h-3 w-full" />
    </div>
  );
}

export function SkeletonTable({ rows = 5 }: { rows?: number }) {
  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl overflow-hidden">
      <div className="flex gap-4 px-4 py-3 border-b border-slate-700/50">
        <Bone className="h-3 w-20" />
        <Bone className="h-3 w-32" />
        <Bone className="h-3 w-16" />
        <Bone className="h-3 w-24" />
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-4 px-4 py-3 border-b border-slate-700/30 last:border-0">
          <Bone className="h-3 w-20" />
          <Bone className="h-3 w-32" />
          <Bone className="h-3 w-16" />
          <Bone className="h-3 w-24" />
        </div>
      ))}
    </div>
  );
}

export function SkeletonChart() {
  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4 space-y-3">
      <Bone className="h-4 w-32" />
      <div className="flex items-end gap-1 h-32">
        {Array.from({ length: 12 }).map((_, i) => (
          <Bone key={i} className="flex-1" style={{ height: `${20 + Math.random() * 80}%` }} />
        ))}
      </div>
    </div>
  );
}

export function SkeletonMetricRow({ count = 4 }: { count?: number }) {
  return (
    <div className="grid gap-4" style={{ gridTemplateColumns: `repeat(${count}, minmax(0, 1fr))` }}>
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  );
}

function SkeletonLoader({ variant = 'dashboard' }: { variant?: 'dashboard' | 'table' | 'cards' }) {
  if (variant === 'table') {
    return (
      <div className="space-y-4">
        <SkeletonMetricRow count={3} />
        <SkeletonTable rows={8} />
      </div>
    );
  }

  if (variant === 'cards') {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <SkeletonMetricRow count={4} />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <SkeletonChart />
        <SkeletonChart />
      </div>
      <SkeletonTable rows={5} />
    </div>
  );
}

const MemoizedSkeletonLoader = React.memo(SkeletonLoader);
MemoizedSkeletonLoader.displayName = 'SkeletonLoader';
export default MemoizedSkeletonLoader;
