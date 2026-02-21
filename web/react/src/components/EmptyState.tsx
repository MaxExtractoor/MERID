import React from 'react';
import { Inbox } from 'lucide-react';

interface EmptyStateProps {
  title?: string;
  message?: string;
  icon?: React.ReactNode;
}

function EmptyState({ 
  title = 'No data available', 
  message = 'Data will appear here once available.',
  icon,
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      {icon || <Inbox className="w-10 h-10 text-slate-600 mb-3" />}
      <h3 className="text-sm font-medium text-slate-400 mb-1">{title}</h3>
      <p className="text-xs text-slate-500 max-w-xs">{message}</p>
    </div>
  );
}

const MemoizedEmptyState = React.memo(EmptyState);
MemoizedEmptyState.displayName = 'EmptyState';
export default MemoizedEmptyState;
