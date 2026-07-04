/**
 * Separator - Visual divider component
 */

import React from 'react';

interface SeparatorProps {
  orientation?: 'horizontal' | 'vertical';
  className?: string;
}

export const Separator: React.FC<SeparatorProps> = ({ 
  orientation = 'horizontal', 
  className = '' 
}) => {
  const baseClasses = 'bg-slate-700';
  const orientationClasses = orientation === 'horizontal' 
    ? 'w-full h-px' 
    : 'h-full w-px';
  
  return (
    <div 
      className={`${baseClasses} ${orientationClasses} ${className}`}
      role="separator"
      aria-orientation={orientation}
    />
  );
};

export default Separator;
