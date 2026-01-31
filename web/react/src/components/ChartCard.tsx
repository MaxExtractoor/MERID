interface ChartCardProps {
  title: string;
  children: React.ReactNode;
  className?: string;
}

export default function ChartCard({ title, children, className = '' }: ChartCardProps) {
  return (
    <div className={`rounded-xl border border-slate-800 bg-slate-900/70 p-4 shadow-sm dark:bg-slate-950 ${className}`}>
      <h2 className="mb-3 text-sm font-semibold text-slate-300">
        {title}
      </h2>
      <div className="h-64 w-full rounded-lg bg-slate-900/80 dark:bg-slate-900">
        {children}
      </div>
    </div>
  );
}

// Light theme variant
export function ChartCardLight({ title, children, className = '' }: ChartCardProps) {
  return (
    <div className={`rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-950 ${className}`}>
      <h2 className="mb-3 text-sm font-semibold text-slate-700 dark:text-slate-300">
        {title}
      </h2>
      <div className="h-64 w-full rounded-lg bg-slate-50 dark:bg-slate-900">
        {children}
      </div>
    </div>
  );
}
