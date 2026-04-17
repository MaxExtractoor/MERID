/**
 * Global Error Boundary for React component crash prevention.
 * 
 * Provides centralized error catching, logging, and recovery
 * mechanisms across the entire Kalshi application.
 */

import React, { Component, ReactNode, ErrorInfo, useCallback } from 'react';
import { authHeaders } from '../api/auth';

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
  retryCount: number;
  componentStack: string;
  timestamp: number;
}

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: ErrorInfo, componentStack: string) => void;
  maxRetries?: number;
  resetOnError?: boolean;
  logToConsole?: boolean;
  enableRetry?: boolean;
}

interface ErrorReport {
  error: {
    message: string;
    name: string;
    stack?: string;
  };
  componentStack: string;
  timestamp: number;
  retryCount: number;
  userAgent: string;
  url: string;
  component?: string;
}

// Error categorization utility
const categorizeError = (error: Error): 'network' | 'render' | 'state' | 'unknown' => {
  if (error.message.includes('Network') || error.message.includes('fetch')) {
    return 'network';
  }
  
  if (error.message.includes('Cannot read property') || error.message.includes('undefined')) {
    return 'render';
  }
  
  if (error.message.includes('setState') || error.message.includes('hook')) {
    return 'state';
  }
  
  return 'unknown';
};

// Error severity assessment
const getErrorSeverity = (error: Error): 'low' | 'medium' | 'high' | 'critical' => {
  const category = categorizeError(error);
  
  if (category === 'network') return 'medium';
  if (category === 'render') return 'high';
  if (category === 'state') return 'critical';
  
  return 'low';
};

// Generate user-friendly error message
const getUserFriendlyMessage = (_error: Error, category: string): string => {
  switch (category) {
    case 'network':
      return 'A network connection issue occurred. Please check your internet connection and try again.';
    case 'render':
      return 'A display issue occurred. The component has been reset to prevent further issues.';
    case 'state':
      return 'An internal state issue occurred. The component has been reset to restore functionality.';
    default:
      return 'An unexpected error occurred. The component has been reset to prevent further issues.';
  }
};

// Default error fallback component
const DefaultErrorFallback: React.FC<{
  error: Error;
  errorInfo: ErrorInfo;
  onRetry: () => void;
  onReload: () => void;
  retryCount: number;
  maxRetries: number;
  enableRetry: boolean;
}> = ({ error, errorInfo: _errorInfo, onRetry, onReload, retryCount, maxRetries, enableRetry }) => {
  const category = categorizeError(error);
  const severity = getErrorSeverity(error);
  const userMessage = getUserFriendlyMessage(error, category);
  
  const getSeverityColor = () => {
    switch (severity) {
      case 'critical': return 'text-red-400 border-red-500/30 bg-red-500/10';
      case 'high': return 'text-orange-400 border-orange-500/30 bg-orange-500/10';
      case 'medium': return 'text-amber-400 border-amber-500/30 bg-amber-500/10';
      default: return 'text-gray-400 border-gray-500/30 bg-gray-500/10';
    }
  };

  const getSeverityIcon = () => {
    switch (severity) {
      case 'critical': return '🔴';
      case 'high': return '🟠';
      case 'medium': return '🟡';
      default: return '⚪';
    }
  };

  return (
    <div className={`rounded-xl p-6 border ${getSeverityColor()} m-4`}>
      <div className="flex items-center gap-3 mb-4">
        <span className="text-2xl">{getSeverityIcon()}</span>
        <h3 className="text-lg font-semibold">Component Error</h3>
      </div>
      
      <div className="mb-4">
        <p className="text-sm text-gray-300 mb-2">{userMessage}</p>
        
        <details className="text-xs text-gray-400">
          <summary className="cursor-pointer hover:text-gray-300 mb-2">
            Technical Details
          </summary>
          <div className="mt-2 space-y-2">
            <div>
              <strong>Error Type:</strong> {category}
            </div>
            <div>
              <strong>Severity:</strong> {severity}
            </div>
            <div>
              <strong>Message:</strong> {error.message}
            </div>
            {error.stack && (
              <div className="mt-2">
                <strong>Stack Trace:</strong>
                <pre className="mt-1 p-2 bg-slate-800 rounded overflow-auto text-xs max-h-32">
                  {error.stack}
                </pre>
              </div>
            )}
          </div>
        </details>
      </div>
      
      <div className="flex items-center gap-3">
        {enableRetry && retryCount < maxRetries && (
          <button
            onClick={onRetry}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded transition-colors"
          >
            🔄 Retry ({retryCount}/{maxRetries})
          </button>
        )}
        
        <button
          onClick={onReload}
          className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm rounded transition-colors"
        >
          🔄 Reload Page
        </button>
        
        {retryCount >= maxRetries && (
          <span className="text-xs text-gray-500">
            Max retries reached. Please reload the page.
          </span>
        )}
      </div>
    </div>
  );
};

// Enhanced Error Boundary Component
class EnhancedErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  private errorReportingEndpoint = '/api/v1/errors/report';
  
  constructor(props: ErrorBoundaryProps) {
    super(props);
    
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
      retryCount: 0,
      componentStack: '',
      timestamp: Date.now(),
    };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return {
      hasError: true,
      error,
      timestamp: Date.now(),
    };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    const componentStack = errorInfo.componentStack || '';
    const category = categorizeError(error);
    const severity = getErrorSeverity(error);
    
    // Update state with error info
    this.setState({
      errorInfo,
      componentStack,
      timestamp: Date.now(),
    });

    // Log to console if enabled
    if (this.props.logToConsole !== false) {
      console.group(`🚨 Error Boundary Caught: ${category} (${severity})`);
      console.error('Error:', error);
      console.error('Error Info:', errorInfo);
      console.error('Component Stack:', componentStack);
      console.groupEnd();
    }

    // Call custom error handler
    if (this.props.onError) {
      try {
        this.props.onError(error, errorInfo, componentStack);
      } catch (handlerError) {
        console.error('Error in custom error handler:', handlerError);
      }
    }

    // Report error to server
    this.reportError(error, errorInfo, componentStack, category, severity);

    // Log UX event
    if (typeof window !== 'undefined' && (window as any).logUxEvent) {
      (window as any).logUxEvent('component_crash', 'ErrorBoundary', {
        error: error.message,
        category,
        severity,
        componentStack: componentStack.substring(0, 500), // Limit length
        retryCount: this.state.retryCount,
        timestamp: Date.now(),
      });
    }
  }

  private reportError = (
    error: Error, 
    _errorInfo: ErrorInfo, 
    componentStack: string, 
    category: string, 
    severity: string
  ) => {
    const errorReport: ErrorReport = {
      error: {
        message: error.message,
        name: error.name,
        stack: error.stack,
      },
      componentStack,
      timestamp: Date.now(),
      retryCount: this.state.retryCount,
      userAgent: navigator.userAgent,
      url: window.location.href,
      component: this.getComponentName(),
    };

    // Send error report (fire and forget)
    fetch(this.errorReportingEndpoint, {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...errorReport,
        category,
        severity,
      }),
    }).catch(reportError => {
      console.warn('Failed to report error to server:', reportError);
    });
  };

  private getComponentName = (): string => {
    try {
      const displayName = (this.props.children as any)?.type?.displayName;
      const name = (this.props.children as any)?.type?.name;
      return displayName || name || 'Unknown';
    } catch {
      return 'Unknown';
    }
  };

  private handleRetry = () => {
    const { maxRetries = 3, resetOnError = true } = this.props;
    
    if (this.state.retryCount >= maxRetries) {
      return;
    }

    this.setState(prevState => ({
      hasError: false,
      error: null,
      errorInfo: null,
      componentStack: '',
      retryCount: prevState.retryCount + 1,
      timestamp: Date.now(),
    }));

    // Reset error after a delay if enabled
    if (resetOnError) {
      setTimeout(() => {
        this.setState({
          hasError: false,
          error: null,
          errorInfo: null,
          componentStack: '',
        });
      }, 100);
    }
  };

  private handleReload = () => {
    window.location.reload();
  };

  render() {
    const { hasError, error, errorInfo, retryCount } = this.state;
    const { 
      children, 
      fallback, 
      maxRetries = 3, 
      enableRetry = true,
      logToConsole: _logToConsole = true 
    } = this.props;

    if (hasError && error && errorInfo) {
      // Use custom fallback if provided
      if (fallback) {
        return fallback;
      }

      // Use default error fallback
      return (
        <DefaultErrorFallback
          error={error}
          errorInfo={errorInfo}
          onRetry={this.handleRetry}
          onReload={this.handleReload}
          retryCount={retryCount}
          maxRetries={maxRetries}
          enableRetry={enableRetry}
        />
      );
    }

    return children;
  }
}

// HOC for wrapping components with error boundary
export const withErrorBoundary = <P extends object>(
  Component: React.ComponentType<P>,
  errorBoundaryProps?: Partial<ErrorBoundaryProps>
): React.FC<P> => {
  const WrappedComponent = (props: P) => (
    <EnhancedErrorBoundary {...errorBoundaryProps}>
      <Component {...props} />
    </EnhancedErrorBoundary>
  );

  WrappedComponent.displayName = `withErrorBoundary(${Component.displayName || Component.name})`;
  
  return WrappedComponent;
};

// Hook for manual error reporting
export const useErrorReporting = () => {
  const reportError = useCallback((error: Error, context?: string) => {
    const errorReport = {
      error: {
        message: error.message,
        name: error.name,
        stack: error.stack,
      },
      componentStack: context || 'Manual report',
      timestamp: Date.now(),
      retryCount: 0,
      userAgent: navigator.userAgent,
      url: window.location.href,
      component: context || 'Manual',
    };

    // Send error report
    fetch('/api/v1/errors/report', {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      body: JSON.stringify(errorReport),
    }).catch(reportError => {
      console.warn('Failed to report manual error:', reportError);
    });

    // Log to console
    console.error('Manual error report:', error, context);
  }, []);

  return { reportError };
};

export default EnhancedErrorBoundary;
