import React from 'react';

interface ChartWrapperProps {
  title: string;
  children: React.ReactNode;
}

function ChartWrapper({ title, children }: ChartWrapperProps) {
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

const MemoizedChartWrapper = React.memo(ChartWrapper);
MemoizedChartWrapper.displayName = 'ChartWrapper';
export default MemoizedChartWrapper;
