/**
 * Optimized Skeleton Loading Components
 */

import React from 'react';

interface SkeletonProps {
  className?: string;
  width?: string | number;
  height?: string | number;
}

export const Skeleton = React.memo(function Skeleton({ 
  className = '',
  width,
  height
}: SkeletonProps) {
  const style: React.CSSProperties = {};
  if (width) style.width = typeof width === 'number' ? `${width}px` : width;
  if (height) style.height = typeof height === 'number' ? `${height}px` : height;
  
  return (
    <div 
      className={`bg-slate-700/50 rounded animate-pulse ${className}`}
      style={style}
    />
  );
});

interface SkeletonTextProps {
  lines?: number;
  className?: string;
}

export const SkeletonText = React.memo(function SkeletonText({ 
  lines = 3,
  className = ''
}: SkeletonTextProps) {
  return (
    <div className={`space-y-2 ${className}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton 
          key={i} 
          className="h-4" 
          width={i === lines - 1 ? '75%' : '100%'} 
        />
      ))}
    </div>
  );
});

interface SkeletonCardProps {
  rows?: number;
  className?: string;
}

export const SkeletonCard = React.memo(function SkeletonCard({ 
  rows = 4,
  className = ''
}: SkeletonCardProps) {
  return (
    <div className={`bg-slate-900/70 rounded-xl border border-slate-800 p-4 ${className}`}>
      <div className="flex items-center gap-3 mb-4">
        <Skeleton className="w-10 h-10 rounded-lg" />
        <div className="flex-1">
          <Skeleton className="h-4 w-32 mb-2" />
          <Skeleton className="h-3 w-20" />
        </div>
      </div>
      <div className="space-y-3">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="flex items-center gap-3">
            <Skeleton className="w-8 h-8 rounded" />
            <div className="flex-1">
              <Skeleton className="h-3 w-full" />
            </div>
            <Skeleton className="h-3 w-16" />
          </div>
        ))}
      </div>
    </div>
  );
});
