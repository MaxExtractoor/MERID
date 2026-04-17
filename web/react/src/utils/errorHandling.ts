/**
 * Standardized Error Handling Utilities for Kalshi UI Components.
 * 
 * Provides consistent error categorization, recovery strategies,
 * and user-friendly messaging across all components.
 */

// Error type definitions
export type ErrorType = 'network' | 'api' | 'timeout' | 'validation' | 'permission' | 'unknown';
export type ErrorSeverity = 'low' | 'medium' | 'high' | 'critical';
export type RecoveryAction = 'retry' | 'refresh' | 'reconnect' | 'contact_support' | 'none';

export interface ErrorInfo {
  type: ErrorType;
  severity: ErrorSeverity;
  message: string;
  userMessage: string;
  retryable: boolean;
  recoveryAction: RecoveryAction;
  timestamp: number;
  context?: string;
  originalError?: Error;
}

export interface RetryConfig {
  maxRetries: number;
  baseDelay: number;
  maxDelay: number;
  backoffFactor: number;
  retryableErrors: ErrorType[];
}

// Default retry configuration
export const DEFAULT_RETRY_CONFIG: RetryConfig = {
  maxRetries: 3,
  baseDelay: 1000,
  maxDelay: 30000,
  backoffFactor: 2,
  retryableErrors: ['network', 'timeout', 'api'],
};

// Error categorization utility
export const categorizeError = (error: any, context?: string): ErrorInfo => {
  const timestamp = Date.now();
  
  if (!error) {
    return {
      type: 'unknown' as ErrorType,
      severity: 'medium' as ErrorSeverity,
      message: 'Unknown error occurred',
      userMessage: 'An unexpected error occurred. Please try again.',
      retryable: true,
      recoveryAction: 'retry' as RecoveryAction,
      timestamp,
      context,
    };
  }

  // Network errors
  if (error.name === 'TypeError' && error.message?.includes('fetch')) {
    return {
      type: 'network' as ErrorType,
      severity: 'medium' as ErrorSeverity,
      message: 'Network connection failed',
      userMessage: 'Network connection failed. Please check your internet connection and try again.',
      retryable: true,
      recoveryAction: 'retry' as RecoveryAction,
      timestamp,
      context,
      originalError: error,
    };
  }

  // Timeout errors
  if (error.name === 'AbortError' || error.message?.includes('timeout')) {
    return {
      type: 'timeout' as ErrorType,
      severity: 'medium' as ErrorSeverity,
      message: 'Request timed out',
      userMessage: 'The request took too long to complete. Please try again.',
      retryable: true,
      recoveryAction: 'retry' as RecoveryAction,
      timestamp,
      context,
      originalError: error,
    };
  }

  // API errors with HTTP status codes
  if (error.status) {
    if (error.status >= 500) {
      return {
        type: 'api' as ErrorType,
        severity: 'high' as ErrorSeverity,
        message: `Server error (${error.status})`,
        userMessage: 'The server is experiencing issues. Please try again in a moment.',
        retryable: true,
        recoveryAction: 'retry' as RecoveryAction,
        timestamp,
        context,
        originalError: error,
      };
    } else if (error.status === 429) {
      return {
        type: 'api' as ErrorType,
        severity: 'medium' as ErrorSeverity,
        message: 'Rate limit exceeded',
        userMessage: 'Too many requests. Please wait a moment and try again.',
        retryable: true,
        recoveryAction: 'retry' as RecoveryAction,
        timestamp,
        context,
        originalError: error,
      };
    } else if (error.status === 401 || error.status === 403) {
      return {
        type: 'permission' as ErrorType,
        severity: 'high' as ErrorSeverity,
        message: 'Authentication failed',
        userMessage: 'You need to log in again to continue.',
        retryable: false,
        recoveryAction: 'refresh' as RecoveryAction,
        timestamp,
        context,
        originalError: error,
      };
    } else if (error.status >= 400) {
      return {
        type: 'validation' as ErrorType,
        severity: 'medium' as ErrorSeverity,
        message: `Invalid request (${error.status})`,
        userMessage: 'The request was invalid. Please check your input and try again.',
        retryable: false,
        recoveryAction: 'none' as RecoveryAction,
        timestamp,
        context,
        originalError: error,
      };
    }
  }

  // WebSocket errors
  if (error.type === 'websocket' || error.message?.includes('WebSocket')) {
    return {
      type: 'network' as ErrorType,
      severity: 'medium' as ErrorSeverity,
      message: 'WebSocket connection failed',
      userMessage: 'Real-time connection failed. Attempting to reconnect...',
      retryable: true,
      recoveryAction: 'reconnect' as RecoveryAction,
      timestamp,
      context,
      originalError: error,
    };
  }

  // Default unknown error
  return {
    type: 'unknown' as ErrorType,
    severity: 'medium' as ErrorSeverity,
    message: error.message || 'An unexpected error occurred',
    userMessage: 'An unexpected error occurred. Please try again or contact support if the issue persists.',
    retryable: true,
    recoveryAction: 'retry' as RecoveryAction,
    timestamp,
    context,
    originalError: error,
  };
};

// Error severity assessment
export const getErrorSeverity = (errorInfo: ErrorInfo): ErrorSeverity => {
  return errorInfo.severity;
};

// Check if error is retryable
export const isRetryable = (errorInfo: ErrorInfo, config: RetryConfig = DEFAULT_RETRY_CONFIG): boolean => {
  return errorInfo.retryable && config.retryableErrors.includes(errorInfo.type);
};

// Calculate retry delay with exponential backoff
export const calculateRetryDelay = (
  retryCount: number, 
  config: RetryConfig = DEFAULT_RETRY_CONFIG
): number => {
  const delay = config.baseDelay * Math.pow(config.backoffFactor, retryCount - 1);
  return Math.min(delay, config.maxDelay);
};

// Generate user-friendly error messages
export const getUserMessage = (errorInfo: ErrorInfo): string => {
  return errorInfo.userMessage;
};

// Get recovery action for error
export const getRecoveryAction = (errorInfo: ErrorInfo): RecoveryAction => {
  return errorInfo.recoveryAction;
};

// Error logging utility
export const logError = (errorInfo: ErrorInfo, additionalContext?: Record<string, any>) => {
  const logData = {
    ...errorInfo,
    additionalContext,
    userAgent: typeof window !== 'undefined' ? window.navigator.userAgent : 'unknown',
    url: typeof window !== 'undefined' ? window.location.href : 'unknown',
    timestamp: new Date(errorInfo.timestamp).toISOString(),
  };

  // Log to console with appropriate level
  const logMethod = errorInfo.severity === 'critical' ? 'error' : 
                   errorInfo.severity === 'high' ? 'error' : 
                   errorInfo.severity === 'medium' ? 'warn' : 'info';

  console[logMethod]('🚨 UI Error:', logData);

  // Send to error reporting service if available
  if (typeof window !== 'undefined' && (window as any).errorReportingService) {
    (window as any).errorReportingService.report(logData).catch((reportError: unknown) => {
      console.warn('Failed to report error to service:', reportError);
    });
  }
};

// Error recovery strategies
export const getRecoveryStrategy = (errorInfo: ErrorInfo): {
  action: RecoveryAction;
  label: string;
  description: string;
  icon: string;
  color: string;
} => {
  switch (errorInfo.recoveryAction) {
    case 'retry':
      return {
        action: 'retry',
        label: 'Retry',
        description: 'Try the operation again',
        icon: '🔄',
        color: 'blue',
      };
    case 'refresh':
      return {
        action: 'refresh',
        label: 'Refresh',
        description: 'Refresh the page',
        icon: '🔄',
        color: 'green',
      };
    case 'reconnect':
      return {
        action: 'reconnect',
        label: 'Reconnect',
        description: 'Reconnect to the service',
        icon: '🔌',
        color: 'orange',
      };
    case 'contact_support':
      return {
        action: 'contact_support',
        label: 'Contact Support',
        description: 'Get help from support team',
        icon: '📞',
        color: 'red',
      };
    default:
      return {
        action: 'none',
        label: 'Dismiss',
        description: 'Close this message',
        icon: '✅',
        color: 'gray',
      };
  }
};

// Error aggregation for batch operations
export const aggregateErrors = (errors: ErrorInfo[]): {
  total: number;
  byType: Record<ErrorType, number>;
  bySeverity: Record<ErrorSeverity, number>;
  mostCommon: ErrorType;
  mostSevere: ErrorSeverity;
} => {
  const byType = errors.reduce((acc, error) => {
    acc[error.type] = (acc[error.type] || 0) + 1;
    return acc;
  }, {} as Record<ErrorType, number>);

  const bySeverity = errors.reduce((acc, error) => {
    acc[error.severity] = (acc[error.severity] || 0) + 1;
    return acc;
  }, {} as Record<ErrorSeverity, number>);

  const typeEntries = Object.entries(byType);
  const severityEntries = Object.entries(bySeverity);
  const mostCommon = typeEntries.length > 0
    ? typeEntries.reduce((a, b) => a[1] > b[1] ? a : b)[0] as ErrorType
    : 'unknown' as ErrorType;
  const mostSevere = severityEntries.length > 0
    ? severityEntries.reduce((a, b) => {
        const severityOrder = { critical: 4, high: 3, medium: 2, low: 1 };
        return severityOrder[a[0] as ErrorSeverity] > severityOrder[b[0] as ErrorSeverity] ? a : b;
      })[0] as ErrorSeverity
    : 'low' as ErrorSeverity;

  return {
    total: errors.length,
    byType,
    bySeverity,
    mostCommon,
    mostSevere,
  };
};

// Error pattern matching for specific scenarios
export const matchErrorPattern = (error: Error): ErrorInfo | null => {
  const message = error.message.toLowerCase();
  
  // Network connectivity issues
  if (message.includes('network') || message.includes('fetch') || message.includes('connection')) {
    return categorizeError(error, 'network_connectivity');
  }
  
  // Authentication issues
  if (message.includes('unauthorized') || message.includes('authentication') || message.includes('login')) {
    return categorizeError(error, 'authentication');
  }
  
  // Permission issues
  if (message.includes('forbidden') || message.includes('permission') || message.includes('access')) {
    return categorizeError(error, 'permission');
  }
  
  // Validation issues
  if (message.includes('invalid') || message.includes('required') || message.includes('missing')) {
    return categorizeError(error, 'validation');
  }
  
  // Rate limiting
  if (message.includes('rate limit') || message.includes('too many requests')) {
    return categorizeError(error, 'rate_limit');
  }
  
  return null;
};

// Export all utilities
export const ErrorHandlingUtils = {
  categorizeError,
  getErrorSeverity,
  isRetryable,
  calculateRetryDelay,
  getUserMessage,
  getRecoveryAction,
  logError,
  getRecoveryStrategy,
  aggregateErrors,
  matchErrorPattern,
  DEFAULT_RETRY_CONFIG,
};

export default ErrorHandlingUtils;
