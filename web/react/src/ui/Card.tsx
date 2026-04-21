/**
 * Optimized Card Component - Zero-lag renders with memoization
 */

import React from 'react';

interface CardProps {
  children: React.ReactNode;
  className?: string;
  variant?: 'default' | 'gradient' | 'bordered' | 'ghost';
  padding?: 'none' | 'sm' | 'md' | 'lg';
  onClick?: () => void;
}

const variantStyles = {
  default: 'bg-slate-900/70 border-slate-800',
  gradient: 'bg-gradient-to-br from-slate-900 via-slate-900 to-slate-800 border-slate-700/50',
  bordered: 'bg-slate-900 border-slate-700',
  ghost: 'bg-transparent border-transparent',
};

const paddingStyles = {
  none: '',
  sm: 'p-3',
  md: 'p-4',
  lg: 'p-6',
};

export const Card = React.memo(function Card({ 
  children, 
  className = '', 
  variant = 'default',
  padding = 'md',
  onClick 
}: CardProps) {
  return (
    <div 
      className={`
        rounded-xl border backdrop-blur-sm
        ${variantStyles[variant]}
        ${paddingStyles[padding]}
        ${onClick ? 'cursor-pointer hover:border-slate-600 transition-colors' : ''}
        ${className}
      `}
      onClick={onClick}
    >
      {children}
    </div>
  );
});

interface CardHeaderProps {
  children: React.ReactNode;
  className?: string;
  action?: React.ReactNode;
}

export const CardHeader = React.memo(function CardHeader({ 
  children, 
  className = '',
  action 
}: CardHeaderProps) {
  return (
    <div className={`flex items-center justify-between mb-3 ${className}`}>
      <div className="flex items-center gap-2">{children}</div>
      {action && <div>{action}</div>}
    </div>
  );
});

interface CardTitleProps {
  children: React.ReactNode;
  className?: string;
  size?: 'sm' | 'md' | 'lg';
}

const titleSizes = {
  sm: 'text-sm',
  md: 'text-base',
  lg: 'text-lg',
};

export const CardTitle = React.memo(function CardTitle({ 
  children, 
  className = '',
  size = 'md'
}: CardTitleProps) {
  return (
    <h3 className={`font-semibold text-slate-200 ${titleSizes[size]} ${className}`}>
      {children}
    </h3>
  );
});

interface CardContentProps {
  children: React.ReactNode;
  className?: string;
}

export const CardContent = React.memo(function CardContent({ 
  children, 
  className = '' 
}: CardContentProps) {
  return <div className={className}>{children}</div>;
});

interface CardFooterProps {
  children: React.ReactNode;
  className?: string;
}

export const CardFooter = React.memo(function CardFooter({ 
  children, 
  className = '' 
}: CardFooterProps) {
  return (
    <div className={`mt-4 pt-3 border-t border-slate-800 ${className}`}>
      {children}
    </div>
  );
});
