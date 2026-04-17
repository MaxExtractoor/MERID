import React from 'react';
import { Inbox, Search, Filter, Bell, TrendingUp, BarChart3, AlertTriangle } from 'lucide-react';

export type EmptyStateVariant = 'default' | 'search' | 'filter' | 'notifications' | 'chart' | 'data' | 'error';

export interface EmptyStateProps {
  title?: string;
  message?: string;
  icon?: React.ReactNode;
  variant?: EmptyStateVariant;
  action?: React.ReactNode;
}

const variantConfig: Record<EmptyStateVariant, { icon: React.ElementType; defaultTitle: string; defaultMessage: string }> = {
  default: { icon: Inbox, defaultTitle: 'No data available', defaultMessage: 'Data will appear here once available.' },
  search: { icon: Search, defaultTitle: 'No results found', defaultMessage: 'Try adjusting your search terms or filters.' },
  filter: { icon: Filter, defaultTitle: 'No matches', defaultMessage: 'No items match your current filter criteria.' },
  notifications: { icon: Bell, defaultTitle: 'No notifications', defaultMessage: 'You\'re all caught up! New notifications will appear here.' },
  chart: { icon: BarChart3, defaultTitle: 'No chart data', defaultMessage: 'Chart will populate once trading data is available.' },
  data: { icon: TrendingUp, defaultTitle: 'No data yet', defaultMessage: 'Data will appear here as activity occurs.' },
  error: { icon: AlertTriangle, defaultTitle: 'Unable to load data', defaultMessage: 'There was an error loading this content. Please try again.' },
};

export function EmptyState({
  title,
  message,
  icon,
  variant = 'default',
  action,
}: EmptyStateProps) {
  const config = variantConfig[variant];
  const IconComponent = config.icon;

  return (
    <div className="flex flex-col items-center justify-center py-12 text-center" role="status" aria-live="polite">
      {icon || <IconComponent className="w-10 h-10 text-slate-600 mb-3" aria-hidden="true" />}
      <h3 className="text-sm font-medium text-slate-400 mb-1">{title || config.defaultTitle}</h3>
      <p className="text-xs text-slate-500 max-w-xs mb-3">{message || config.defaultMessage}</p>
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

const MemoizedEmptyState = React.memo(EmptyState);
MemoizedEmptyState.displayName = 'EmptyState';
export default MemoizedEmptyState;
