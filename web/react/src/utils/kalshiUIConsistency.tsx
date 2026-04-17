/**
 * Global UI/UX Consistency Utilities for Kalshi Components.
 * 
 * Provides standardized patterns, themes, and consistency helpers
 * across all Kalshi UI components for a unified user experience.
 */

import React, { createContext, useContext, useState, useCallback } from 'react';

// Theme configuration
export interface KalshiTheme {
  colors: {
    primary: string;
    secondary: string;
    success: string;
    warning: string;
    error: string;
    info: string;
    background: string;
    surface: string;
    text: {
      primary: string;
      secondary: string;
      tertiary: string;
      inverse: string;
    };
    border: {
      primary: string;
      secondary: string;
      focus: string;
    };
  };
  spacing: {
    xs: string;
    sm: string;
    md: string;
    lg: string;
    xl: string;
  };
  typography: {
    fontFamily: string;
    fontSize: {
      xs: string;
      sm: string;
      md: string;
      lg: string;
      xl: string;
    };
    fontWeight: {
      normal: string;
      medium: string;
      semibold: string;
      bold: string;
    };
  };
  borderRadius: {
    sm: string;
    md: string;
    lg: string;
    xl: string;
  };
  shadows: {
    sm: string;
    md: string;
    lg: string;
    xl: string;
  };
  transitions: {
    fast: string;
    normal: string;
    slow: string;
  };
}

// Default Kalshi theme
export const DEFAULT_KALSHI_THEME: KalshiTheme = {
  colors: {
    primary: '#3b82f6',
    secondary: '#8b5cf6',
    success: '#10b981',
    warning: '#f59e0b',
    error: '#ef4444',
    info: '#06b6d4',
    background: '#0f172a',
    surface: '#1e293b',
    text: {
      primary: '#f8fafc',
      secondary: '#cbd5e1',
      tertiary: '#64748b',
      inverse: '#0f172a',
    },
    border: {
      primary: '#334155',
      secondary: '#475569',
      focus: '#3b82f6',
    },
  },
  spacing: {
    xs: '0.25rem',
    sm: '0.5rem',
    md: '1rem',
    lg: '1.5rem',
    xl: '2rem',
  },
  typography: {
    fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    fontSize: {
      xs: '0.75rem',
      sm: '0.875rem',
      md: '1rem',
      lg: '1.125rem',
      xl: '1.25rem',
    },
    fontWeight: {
      normal: '400',
      medium: '500',
      semibold: '600',
      bold: '700',
    },
  },
  borderRadius: {
    sm: '0.25rem',
    md: '0.375rem',
    lg: '0.5rem',
    xl: '0.75rem',
  },
  shadows: {
    sm: '0 1px 2px 0 rgba(0, 0, 0, 0.05)',
    md: '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
    lg: '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)',
    xl: '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)',
  },
  transitions: {
    fast: '150ms ease-in-out',
    normal: '250ms ease-in-out',
    slow: '350ms ease-in-out',
  },
};

// Component style variants
export interface ComponentVariants {
  buttons: {
    primary: string;
    secondary: string;
    outline: string;
    ghost: string;
    danger: string;
  };
  inputs: {
    default: string;
    error: string;
    success: string;
    disabled: string;
  };
  cards: {
    default: string;
    elevated: string;
    bordered: string;
    interactive: string;
  };
  badges: {
    default: string;
    success: string;
    warning: string;
    error: string;
    info: string;
  };
  loading: {
    skeleton: string;
    spinner: string;
    overlay: string;
  };
}

// Default component variants
export const DEFAULT_COMPONENT_VARIANTS: ComponentVariants = {
  buttons: {
    primary: 'bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 px-4 rounded-lg transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-slate-900',
    secondary: 'bg-slate-700 hover:bg-slate-600 text-white font-medium py-2 px-4 rounded-lg transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-slate-500 focus:ring-offset-2 focus:ring-offset-slate-900',
    outline: 'border border-slate-600 hover:bg-slate-800 text-slate-300 font-medium py-2 px-4 rounded-lg transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-slate-500 focus:ring-offset-2 focus:ring-offset-slate-900',
    ghost: 'hover:bg-slate-800 text-slate-300 font-medium py-2 px-4 rounded-lg transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-slate-500 focus:ring-offset-2 focus:ring-offset-slate-900',
    danger: 'bg-red-600 hover:bg-red-700 text-white font-medium py-2 px-4 rounded-lg transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 focus:ring-offset-slate-900',
  },
  inputs: {
    default: 'bg-slate-800 border border-slate-600 text-slate-300 placeholder-slate-500 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors duration-200',
    error: 'bg-slate-800 border border-red-500 text-slate-300 placeholder-slate-500 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-transparent transition-colors duration-200',
    success: 'bg-slate-800 border border-green-500 text-slate-300 placeholder-slate-500 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent transition-colors duration-200',
    disabled: 'bg-slate-900 border border-slate-700 text-slate-500 placeholder-slate-600 rounded-lg px-3 py-2 cursor-not-allowed opacity-50',
  },
  cards: {
    default: 'bg-slate-800 rounded-xl border border-slate-700',
    elevated: 'bg-slate-800 rounded-xl border border-slate-700 shadow-lg',
    bordered: 'bg-slate-800 rounded-xl border-2 border-slate-600',
    interactive: 'bg-slate-800 rounded-xl border border-slate-700 hover:border-slate-600 transition-colors duration-200 cursor-pointer',
  },
  badges: {
    default: 'inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-slate-700 text-slate-300',
    success: 'inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-green-500/20 text-green-400 border border-green-500/30',
    warning: 'inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-amber-500/20 text-amber-400 border border-amber-500/30',
    error: 'inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-red-500/20 text-red-400 border border-red-500/30',
    info: 'inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-blue-500/20 text-blue-400 border border-blue-500/30',
  },
  loading: {
    skeleton: 'animate-pulse bg-slate-700 rounded',
    spinner: 'animate-spin rounded-full border-2 border-slate-600 border-t-blue-500',
    overlay: 'fixed inset-0 bg-black/50 flex items-center justify-center z-50',
  },
};

// Theme context
interface ThemeContextValue {
  theme: KalshiTheme;
  variants: ComponentVariants;
  updateTheme: (theme: Partial<KalshiTheme>) => void;
  resetTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

// Theme provider
export const KalshiThemeProvider: React.FC<{
  children: React.ReactNode;
  theme?: Partial<KalshiTheme>;
  variants?: Partial<ComponentVariants>;
}> = ({ children, theme: customTheme, variants: customVariants }) => {
  const [theme, setTheme] = useState<KalshiTheme>({
    ...DEFAULT_KALSHI_THEME,
    ...customTheme,
  });

  const [variants, setVariants] = useState<ComponentVariants>({
    ...DEFAULT_COMPONENT_VARIANTS,
    ...customVariants,
  });

  const updateTheme = useCallback((newTheme: Partial<KalshiTheme>) => {
    setTheme(prev => ({
      ...prev,
      ...newTheme,
      colors: {
        ...prev.colors,
        ...newTheme.colors,
        text: {
          ...prev.colors.text,
          ...newTheme.colors?.text,
        },
        border: {
          ...prev.colors.border,
          ...newTheme.colors?.border,
        },
      },
      spacing: {
        ...prev.spacing,
        ...newTheme.spacing,
      },
      typography: {
        ...prev.typography,
        ...newTheme.typography,
        fontSize: {
          ...prev.typography.fontSize,
          ...newTheme.typography?.fontSize,
        },
        fontWeight: {
          ...prev.typography.fontWeight,
          ...newTheme.typography?.fontWeight,
        },
      },
      borderRadius: {
        ...prev.borderRadius,
        ...newTheme.borderRadius,
      },
      shadows: {
        ...prev.shadows,
        ...newTheme.shadows,
      },
      transitions: {
        ...prev.transitions,
        ...newTheme.transitions,
      },
    }));
  }, []);

  const resetTheme = useCallback(() => {
    setTheme(DEFAULT_KALSHI_THEME);
    setVariants(DEFAULT_COMPONENT_VARIANTS);
  }, []);

  const value: ThemeContextValue = {
    theme,
    variants,
    updateTheme,
    resetTheme,
  };

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  );
};

// Hook for using theme
export const useKalshiTheme = (): ThemeContextValue => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useKalshiTheme must be used within a KalshiThemeProvider');
  }
  return context;
};

// Utility functions for consistent styling
export const getConsistentClassNames = (
  baseClasses: string,
  variantClasses?: string,
  additionalClasses?: string
): string => {
  return [baseClasses, variantClasses, additionalClasses]
    .filter(Boolean)
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim();
};

// Color utility functions
export const getColorForStatus = (status: 'success' | 'warning' | 'error' | 'info', theme: KalshiTheme): string => {
  switch (status) {
    case 'success': return theme.colors.success;
    case 'warning': return theme.colors.warning;
    case 'error': return theme.colors.error;
    case 'info': return theme.colors.info;
    default: return theme.colors.primary;
  }
};

export const getTextColorForBackground = (backgroundColor: string, theme: KalshiTheme): string => {
  // Simple contrast calculation - in production, use a proper contrast ratio calculation
  const isLight = backgroundColor.toLowerCase().includes('white') || 
                  backgroundColor.toLowerCase().includes('f8') ||
                  backgroundColor.toLowerCase().includes('fafc');
  
  return isLight ? theme.colors.text.inverse : theme.colors.text.primary;
};

// Spacing utility functions
export const getSpacing = (size: 'xs' | 'sm' | 'md' | 'lg' | 'xl', theme: KalshiTheme): string => {
  return theme.spacing[size];
};

// Typography utility functions
export const getTypography = (
  size: 'xs' | 'sm' | 'md' | 'lg' | 'xl',
  weight: 'normal' | 'medium' | 'semibold' | 'bold' = 'normal',
  theme: KalshiTheme
): string => {
  return `${theme.typography.fontSize[size]} ${theme.typography.fontWeight[weight]} ${theme.typography.fontFamily}`;
};

// Border radius utility functions
export const getBorderRadius = (size: 'sm' | 'md' | 'lg' | 'xl', theme: KalshiTheme): string => {
  return theme.borderRadius[size];
};

// Shadow utility functions
export const getShadow = (size: 'sm' | 'md' | 'lg' | 'xl', theme: KalshiTheme): string => {
  return theme.shadows[size];
};

// Transition utility functions
export const getTransition = (speed: 'fast' | 'normal' | 'slow', theme: KalshiTheme): string => {
  return theme.transitions[speed];
};

// Component style generators
export const generateButtonStyles = (
  variant: keyof ComponentVariants['buttons'],
  variants: ComponentVariants,
  additionalClasses?: string
): string => {
  return getConsistentClassNames(variants.buttons[variant], additionalClasses);
};

export const generateInputStyles = (
  variant: keyof ComponentVariants['inputs'],
  variants: ComponentVariants,
  additionalClasses?: string
): string => {
  return getConsistentClassNames(variants.inputs[variant], additionalClasses);
};

export const generateCardStyles = (
  variant: keyof ComponentVariants['cards'],
  variants: ComponentVariants,
  additionalClasses?: string
): string => {
  return getConsistentClassNames(variants.cards[variant], additionalClasses);
};

export const generateBadgeStyles = (
  variant: keyof ComponentVariants['badges'],
  variants: ComponentVariants,
  additionalClasses?: string
): string => {
  return getConsistentClassNames(variants.badges[variant], additionalClasses);
};

// Responsive design utilities
export const getResponsiveClasses = (
  baseClasses: string,
  smClasses?: string,
  mdClasses?: string,
  lgClasses?: string,
  xlClasses?: string
): string => {
  const classes = [baseClasses];
  
  if (smClasses) classes.push(`sm:${smClasses}`);
  if (mdClasses) classes.push(`md:${mdClasses}`);
  if (lgClasses) classes.push(`lg:${lgClasses}`);
  if (xlClasses) classes.push(`xl:${xlClasses}`);
  
  return classes.join(' ');
};

// Animation utilities
export const getAnimationClasses = (
  animation: 'fade-in' | 'slide-up' | 'slide-down' | 'scale-in' | 'pulse'
): string => {
  const animations = {
    'fade-in': 'animate-fade-in',
    'slide-up': 'animate-slide-up',
    'slide-down': 'animate-slide-down',
    'scale-in': 'animate-scale-in',
    'pulse': 'animate-pulse',
  };
  
  return animations[animation] || '';
};

// Layout utilities
export const getFlexClasses = (
  direction: 'row' | 'col' = 'row',
  justify: 'start' | 'center' | 'end' | 'between' | 'around' | 'evenly' = 'start',
  align: 'start' | 'center' | 'end' | 'stretch' = 'start',
  wrap: boolean = false
): string => {
  const classes = ['flex'];
  
  if (direction === 'col') classes.push('flex-col');
  
  const justifyClasses = {
    start: 'justify-start',
    center: 'justify-center',
    end: 'justify-end',
    between: 'justify-between',
    around: 'justify-around',
    evenly: 'justify-evenly',
  };
  
  const alignClasses = {
    start: 'items-start',
    center: 'items-center',
    end: 'items-end',
    stretch: 'items-stretch',
  };
  
  classes.push(justifyClasses[justify]);
  classes.push(alignClasses[align]);
  
  if (wrap) classes.push('flex-wrap');
  
  return classes.join(' ');
};

// Export all utilities
export const KalshiUIUtils = {
  getConsistentClassNames,
  getColorForStatus,
  getTextColorForBackground,
  getSpacing,
  getTypography,
  getBorderRadius,
  getShadow,
  getTransition,
  generateButtonStyles,
  generateInputStyles,
  generateCardStyles,
  generateBadgeStyles,
  getResponsiveClasses,
  getAnimationClasses,
  getFlexClasses,
  DEFAULT_KALSHI_THEME,
  DEFAULT_COMPONENT_VARIANTS,
};

export default KalshiUIUtils;
