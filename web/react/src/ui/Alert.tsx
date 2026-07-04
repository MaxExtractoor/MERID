/**
 * Alert - Alert message component
 */

import React from 'react';
import { AlertTriangle, CheckCircle, XCircle, Info } from './icons';

interface AlertProps {
  variant?: 'info' | 'success' | 'warning' | 'error';
  title?: string;
  children: React.ReactNode;
  className?: string;
}

const variantConfig = {
  info: {
    icon: Info,
    containerClass: 'bg-blue-500/10 border-blue-500/30 text-blue-400',
    iconClass: 'text-blue-400',
  },
  success: {
    icon: CheckCircle,
    containerClass: 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400',
    iconClass: 'text-emerald-400',
  },
  warning: {
    icon: AlertTriangle,
    containerClass: 'bg-amber-500/10 border-amber-500/30 text-amber-400',
    iconClass: 'text-amber-400',
  },
  error: {
    icon: XCircle,
    containerClass: 'bg-red-500/10 border-red-500/30 text-red-400',
    iconClass: 'text-red-400',
  },
};

export const Alert: React.FC<AlertProps> = ({ 
  variant = 'info', 
  title, 
  children, 
  className = '' 
}) => {
  const config = variantConfig[variant];
  const Icon = config.icon;

  return (
    <div className={`rounded-lg border p-4 ${config.containerClass} ${className}`} role="alert">
      <div className="flex items-start gap-3">
        <Icon className={`w-5 h-5 flex-shrink-0 ${config.iconClass}`} />
        <div className="flex-1">
          {title && (
            <h5 className="font-semibold mb-1">{title}</h5>
          )}
          <div className="text-sm">{children}</div>
        </div>
      </div>
    </div>
  );
};

export default Alert;
