import React from 'react';

interface ChartWrapperProps {
  title: string;
  children: React.ReactNode;
}

export default function ChartWrapper({ title, children }: ChartWrapperProps) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-4 dark:border-slate-700 dark:bg-slate-950">
      <h2 className="mb-3 text-sm font-semibold text-slate-300 dark:text-slate-100">
        {title}
      </h2>
      <div className="h-64 w-full">
        {children}
      </div>
    </div>
  );
}
