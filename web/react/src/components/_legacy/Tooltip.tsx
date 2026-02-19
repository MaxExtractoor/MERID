/**
 * Reusable Tooltip — hover-activated tooltip with configurable placement.
 *
 * Usage:
 *   <Tooltip text="Explanation here">
 *     <span>Hover me</span>
 *   </Tooltip>
 */

import React, { type ReactNode } from 'react';

type Placement = 'top' | 'bottom' | 'left' | 'right';

const PLACEMENT_CLASSES: Record<Placement, string> = {
  top: 'bottom-full left-1/2 -translate-x-1/2 mb-2',
  bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
  left: 'right-full top-1/2 -translate-y-1/2 mr-2',
  right: 'left-full top-1/2 -translate-y-1/2 ml-2',
};

interface TooltipProps {
  text: string;
  placement?: Placement;
  children: ReactNode;
  className?: string;
}

function Tooltip({ text, placement = 'top', children, className = '' }: TooltipProps) {
  return (
    <span className={`relative group cursor-help ${className}`}>
      {children}
      <span
        className={`absolute ${PLACEMENT_CLASSES[placement]} px-2.5 py-1.5 text-xs leading-tight bg-slate-800 text-slate-200 rounded-lg shadow-xl opacity-0 group-hover:opacity-100 transition-opacity duration-150 whitespace-nowrap pointer-events-none z-50 border border-slate-700 max-w-xs`}
      >
        {text}
      </span>
    </span>
  );
}

const MemoizedTooltip = React.memo(Tooltip);
MemoizedTooltip.displayName = 'Tooltip';
export default MemoizedTooltip;
