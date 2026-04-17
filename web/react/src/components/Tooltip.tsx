import React, { useState, useCallback } from 'react';
import { HelpCircle } from '../ui/icons';
import './Tooltip.css';

interface TooltipProps {
  children: React.ReactNode;
  content?: string;
  position?: 'top' | 'bottom' | 'left' | 'right';
  delay?: number;
  maxWidth?: number;
}

const Tooltip: React.FC<TooltipProps> = ({ 
  children, 
  content,
  position = 'top',
  delay = 200,
  maxWidth = 250,
}) => {
  const [isVisible, setIsVisible] = useState(false);
  const [timeoutId, setTimeoutId] = useState<NodeJS.Timeout | null>(null);

  const show = useCallback(() => {
    const id = setTimeout(() => setIsVisible(true), delay);
    setTimeoutId(id);
  }, [delay]);

  const hide = useCallback(() => {
    if (timeoutId) clearTimeout(timeoutId);
    setIsVisible(false);
  }, [timeoutId]);

  if (!content) {
    return <>{children}</>;
  }

  return (
    <div 
      className="tooltip-wrapper relative inline-block"
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      title={isVisible ? undefined : content}
    >
      {children}
      {isVisible && (
        <div 
          className={`tooltip tooltip--${position}`}
          style={{ maxWidth }}
          role="tooltip"
        >
          {content}
        </div>
      )}
    </div>
  );
};

export function InfoTooltip({ 
  content, 
  size = 14,
  className = ''
}: { 
  content: string; 
  size?: number;
  className?: string;
}) {
  return (
    <Tooltip content={content}>
      <HelpCircle 
        size={size} 
        className={`text-slate-500 hover:text-slate-300 cursor-help transition-colors ${className}`}
        aria-label="More information"
      />
    </Tooltip>
  );
}

const MemoizedTooltip = React.memo(Tooltip);
MemoizedTooltip.displayName = 'Tooltip';
export default MemoizedTooltip;
