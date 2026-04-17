import React from 'react';
import './SkeletonLoader.css';

export interface SkeletonProps {
  variant?: 'text' | 'circular' | 'rectangular' | 'rounded';
  width?: string | number;
  height?: string | number;
  className?: string;
}

export function Skeleton({
  variant = 'text',
  width,
  height,
  className = '',
}: SkeletonProps) {
  const style: React.CSSProperties = {
    width: typeof width === 'number' ? `${width}px` : width,
    height: typeof height === 'number' ? `${height}px` : height,
  };

  return (
    <div
      className={`skeleton skeleton--${variant} ${className}`}
      style={style}
      aria-hidden="true"
    />
  );
}

export function SkeletonCard({ className = '' }: { className?: string }) {
  return (
    <div className={`skeleton-card ${className}`} aria-hidden="true">
      <Skeleton variant="rounded" height={120} className="skeleton-card__image" />
      <div className="skeleton-card__content">
        <Skeleton variant="text" width="60%" height={20} />
        <Skeleton variant="text" width="40%" height={16} />
        <Skeleton variant="text" width="80%" height={16} />
      </div>
    </div>
  );
}

export function SkeletonTable({ rows = 5, columns = 4 }: { rows?: number; columns?: number }) {
  return (
    <div className="skeleton-table" aria-hidden="true">
      <div className="skeleton-table__row skeleton-table__header">
        {Array.from({ length: columns }).map((_, i) => (
          <Skeleton key={`h-${i}`} variant="text" width="80%" height={16} />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, rowIdx) => (
        <div key={`r-${rowIdx}`} className="skeleton-table__row">
          {Array.from({ length: columns }).map((_, colIdx) => (
            <Skeleton
              key={`c-${rowIdx}-${colIdx}`}
              variant="text"
              width={`${60 + Math.random() * 30}%`}
              height={14}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

export function SkeletonMetricCard() {
  return (
    <div className="skeleton-metric-card" aria-hidden="true">
      <Skeleton variant="text" width="40%" height={12} />
      <Skeleton variant="text" width="60%" height={28} />
      <Skeleton variant="text" width="50%" height={14} />
    </div>
  );
}

export function SkeletonMetricRow({ count = 4 }: { count?: number }) {
  return (
    <div className="skeleton-metric-row" aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonMetricCard key={i} />
      ))}
    </div>
  );
}

const SkeletonLoader: React.FC<{ lines?: number }> = ({ lines = 3 }) => (
  <div className="skeleton-loader" aria-hidden="true">
    {Array.from({ length: lines }).map((_, i) => (
      <div key={i} className="animate-pulse bg-slate-700 h-4 rounded mb-2" />
    ))}
  </div>
);

export default SkeletonLoader;
