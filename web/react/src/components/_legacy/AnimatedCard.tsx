/**
 * AnimatedCard — A card wrapper with entrance animation and hover effects.
 *
 * Usage:
 *   <AnimatedCard delay={100}>
 *     <p>Content</p>
 *   </AnimatedCard>
 */

import React, { type ReactNode } from 'react';

interface AnimatedCardProps {
  children: ReactNode;
  delay?: number;
  className?: string;
  glow?: 'none' | 'blue' | 'green' | 'amber' | 'rose' | 'purple';
}

const GLOW_CLASSES: Record<string, string> = {
  none: '',
  blue: 'hover:shadow-blue-500/10 hover:border-blue-500/30',
  green: 'hover:shadow-emerald-500/10 hover:border-emerald-500/30',
  amber: 'hover:shadow-amber-500/10 hover:border-amber-500/30',
  rose: 'hover:shadow-rose-500/10 hover:border-rose-500/30',
  purple: 'hover:shadow-purple-500/10 hover:border-purple-500/30',
};

function AnimatedCard({
  children,
  delay = 0,
  className = '',
  glow = 'blue',
}: AnimatedCardProps) {
  return (
    <div
      className={`
        bg-slate-800/60 border border-slate-700/50 rounded-xl
        transition-all duration-300 ease-out
        hover:shadow-lg ${GLOW_CLASSES[glow]}
        animate-in fade-in slide-in-from-bottom-2
        ${className}
      `}
      style={{ animationDelay: `${delay}ms`, animationFillMode: 'both' }}
    >
      {children}
    </div>
  );
}

const MemoizedAnimatedCard = React.memo(AnimatedCard);
MemoizedAnimatedCard.displayName = 'AnimatedCard';
export default MemoizedAnimatedCard;
