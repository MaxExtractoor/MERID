/**
 * Error Classification Utilities
 * 
 * Maps HTTP errors, API responses, and network failures to classified errors
 * with appropriate action hints for operators.
 */

import type { ErrorClass, ClassifiedError } from '../components/ErrorBar';

export function classifyError(error: Error | { message?: string; status?: number; code?: string } | null): ClassifiedError {
  if (!error) {
    return {
      message: 'Unknown error occurred',
      class: 'unknown',
      retryable: true,
    };
  }

  const message = error.message || 'Unknown error';
  const status = (error as any).status;
  const code = (error as any).code;

  // Network/connectivity errors
  if (message.toLowerCase().includes('network') || 
      message.toLowerCase().includes('fetch') ||
      message.toLowerCase().includes('connection') ||
      message.toLowerCase().includes('timeout') ||
      code === 'NETWORK_ERROR' ||
      code === 'TIMEOUT') {
    return {
      message,
      class: 'network',
      action: 'Check network connection and retry',
      retryable: true,
    };
  }

  // HTTP status code mapping
  if (status) {
    switch (status) {
      case 401:
        return {
          message,
          class: 'auth',
          action: 'Check credentials in Settings → Operator',
          retryable: false,
        };
      case 403:
        return {
          message,
          class: 'permission',
          action: 'Insufficient permissions. Check API key scope.',
          retryable: false,
        };
      case 429:
        return {
          message,
          class: 'rate_limit',
          action: 'Rate limit exceeded. Wait and retry.',
          retryable: true,
        };
      case 400:
      case 422:
        return {
          message,
          class: 'validation',
          action: 'Check request parameters and try again.',
          retryable: false,
        };
      case 500:
      case 502:
      case 503:
      case 504:
        return {
          message,
          class: 'system',
          action: 'System error. Try again in a few minutes.',
          retryable: true,
        };
      default:
        if (status >= 400 && status < 500) {
          return {
            message,
            class: 'validation',
            action: 'Request error. Check parameters.',
            retryable: false,
          };
        } else {
          return {
            message,
            class: 'system',
            action: 'Server error. Retry later.',
            retryable: true,
          };
        }
    }
  }

  // Error code mapping
  if (code) {
    switch (code) {
      case 'INVALID_CREDENTIALS':
      case 'UNAUTHORIZED':
        return {
          message,
          class: 'auth',
          action: 'Update Kalshi credentials in Settings',
          retryable: false,
        };
      case 'INSUFFICIENT_BALANCE':
        return {
          message,
          class: 'validation',
          action: 'Insufficient balance. Add funds or reduce size.',
          retryable: false,
        };
      case 'MARKET_CLOSED':
        return {
          message,
          class: 'validation',
          action: 'Market is closed. Try when market is open.',
          retryable: false,
        };
      case 'RATE_LIMIT_EXCEEDED':
        return {
          message,
          class: 'rate_limit',
          action: 'Rate limit exceeded. Slow down requests.',
          retryable: true,
        };
      default:
        return {
          message,
          class: 'unknown',
          retryable: true,
        };
    }
  }

  // Message-based classification
  const lowerMessage = message.toLowerCase();
  if (lowerMessage.includes('unauthorized') || lowerMessage.includes('authentication')) {
    return {
      message,
      class: 'auth',
      action: 'Check API credentials in Settings',
      retryable: false,
    };
  }

  if (lowerMessage.includes('forbidden') || lowerMessage.includes('permission')) {
    return {
      message,
      class: 'permission',
      action: 'Check API key permissions',
      retryable: false,
    };
  }

  // P0-002: Asset-ticker mismatch (cross-asset mispairing detection)
  if (lowerMessage.includes('asset_ticker_mismatch') ||
      lowerMessage.includes('asset-ticker mismatch') ||
      lowerMessage.includes('cross-asset')) {
    return {
      message,
      class: 'asset_mismatch',  // P0-002: New error class for strike selector rejections
      action: 'Check spot-market wiring. Spot asset does not match market ticker.',
      retryable: false,
      metric: 'merid_pm_strike_asset_mismatch_total',  // Related P0 metric
    };
  }

  // P0-001: Spot staleness violations
  if (lowerMessage.includes('stale spot') ||
      lowerMessage.includes('spot price.*stale') ||
      lowerMessage.includes('max_spot_age')) {
    return {
      message,
      class: 'staleness',  // P0-001: Spot price staleness
      action: 'Check price feed health or increase MERID_PM_MAX_SPOT_AGE_SECONDS',
      retryable: true,
      metric: 'merid_pm_spot_staleness_violations_total',  // Related P0 metric
    };
  }

  if (lowerMessage.includes('rate limit') || lowerMessage.includes('too many requests')) {
    return {
      message,
      class: 'rate_limit',
      action: 'Rate limit exceeded. Wait before retrying.',
      retryable: true,
    };
  }

  if (lowerMessage.includes('validation') || lowerMessage.includes('invalid')) {
    return {
      message,
      class: 'validation',
      action: 'Check input parameters',
      retryable: false,
    };
  }

  if (lowerMessage.includes('network') || lowerMessage.includes('connection')) {
    return {
      message,
      class: 'network',
      action: 'Check network connectivity',
      retryable: true,
    };
  }

  // Default to system error for unknown cases
  return {
    message,
    class: 'system',
    action: 'Unexpected error. Try again or contact support.',
    retryable: true,
  };
}

/**
 * Test error classification function for development/testing
 */
export function createTestError(type: ErrorClass, message?: string): ClassifiedError {
  const testMessages: Record<ErrorClass, string> = {
    network: 'Network connection failed',
    auth: 'Authentication failed: Invalid credentials',
    permission: 'Access denied: Insufficient permissions',
    rate_limit: 'Rate limit exceeded: Too many requests',
    validation: 'Invalid request parameters',
    system: 'Internal server error',
    unknown: 'Unknown error occurred',
    asset_mismatch: 'Asset-ticker mismatch detected',
    staleness: 'Spot price feed is stale',
  };

  return {
    message: message || testMessages[type],
    class: type,
    action: getActionForClass(type),
    retryable: getRetryableForClass(type),
  };
}

function getActionForClass(errorClass: ErrorClass): string {
  switch (errorClass) {
    case 'network': return 'Check network connection';
    case 'auth': return 'Check credentials in Settings';
    case 'permission': return 'Check API key permissions';
    case 'rate_limit': return 'Wait and retry';
    case 'validation': return 'Check request parameters';
    case 'system': return 'Try again later';
    default: return 'Contact support';
  }
}

function getRetryableForClass(errorClass: ErrorClass): boolean {
  switch (errorClass) {
    case 'network':
    case 'rate_limit':
    case 'system':
    case 'unknown':
      return true;
    case 'auth':
    case 'permission':
    case 'validation':
      return false;
    default:
      return true;
  }
}
