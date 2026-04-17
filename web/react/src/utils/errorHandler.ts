/**
 * Unified error handling middleware for API calls
 * Provides consistent error processing, logging, and user-friendly messages
 */

import { logUiError } from '../utils/logger';

export interface ApiError {
  type: 'network' | 'auth' | 'validation' | 'server' | 'timeout' | 'unknown';
  message: string;
  originalError: Error;
  statusCode?: number;
  endpoint?: string;
  timestamp: number;
  retryable: boolean;
}

export interface ErrorHandlerOptions {
  endpoint?: string;
  context?: string;
  silent?: boolean;
  onError?: (error: ApiError) => void;
  onRetry?: () => void;
}

/**
 * Classify and process API errors into standardized format
 */
export function processApiError(error: unknown, options: ErrorHandlerOptions = {}): ApiError {
  const { endpoint, context } = options;
  const timestamp = Date.now();

  // Convert to Error instance
  const originalError = error instanceof Error ? error : new Error(String(error));

  // Default error
  let apiError: ApiError = {
    type: 'unknown',
    message: originalError.message || 'An unexpected error occurred',
    originalError,
    endpoint,
    timestamp,
    retryable: false,
  };

  // Classify based on error type and message
  if (originalError.name === 'AbortError' || originalError.message.includes('timeout')) {
    apiError = {
      ...apiError,
      type: 'timeout',
      message: 'Request timed out. Please try again.',
      retryable: true,
    };
  } else if (originalError.message.includes('fetch') || originalError.message.includes('network')) {
    apiError = {
      ...apiError,
      type: 'network',
      message: 'Network connection failed. Check your internet connection.',
      retryable: true,
    };
  } else if (originalError.message.includes('401') || originalError.message.includes('Unauthorized')) {
    apiError = {
      ...apiError,
      type: 'auth',
      message: 'Authentication failed. Please log in again.',
      statusCode: 401,
      retryable: false,
    };
  } else if (originalError.message.includes('403')) {
    apiError = {
      ...apiError,
      type: 'auth',
      message: 'Access denied. Insufficient permissions.',
      statusCode: 403,
      retryable: false,
    };
  } else if (originalError.message.includes('404')) {
    apiError = {
      ...apiError,
      type: 'validation',
      message: 'Resource not found.',
      statusCode: 404,
      retryable: false,
    };
  } else if (originalError.message.includes('422') || originalError.message.includes('Validation')) {
    apiError = {
      ...apiError,
      type: 'validation',
      message: 'Invalid data provided. Please check your inputs.',
      statusCode: 422,
      retryable: false,
    };
  } else if (originalError.message.includes('429') || originalError.message.includes('Rate limit')) {
    apiError = {
      ...apiError,
      type: 'server',
      message: 'Too many requests. Please wait a moment.',
      statusCode: 429,
      retryable: true,
    };
  } else if (originalError.message.includes('5') && /^5\d{2}$/.test(originalError.message.slice(0, 3))) {
    const statusCode = parseInt(originalError.message.slice(0, 3), 10);
    apiError = {
      ...apiError,
      type: 'server',
      message: 'Server error. Our team has been notified.',
      statusCode,
      retryable: statusCode !== 501, // 501 Not Implemented is not retryable
    };
  }

  // Log error if not silent
  if (!options.silent) {
    logUiError(
      context || 'ApiErrorHandler',
      `API Error [${apiError.type}]: ${apiError.message}`,
      originalError,
      { endpoint, statusCode: apiError.statusCode, retryable: apiError.retryable }
    );
  }

  // Call error callback if provided
  options.onError?.(apiError);

  return apiError;
}

/**
 * Wrapper for fetch that includes unified error handling
 */
export async function fetchWithErrorHandling(
  url: string,
  init?: RequestInit,
  options: ErrorHandlerOptions = {}
): Promise<Response> {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000);

    const response = await fetch(url, {
      ...init,
      signal: controller.signal,
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    return response;
  } catch (error) {
    throw processApiError(error, { ...options, endpoint: url });
  }
}

/**
 * Retry wrapper with exponential backoff
 */
export async function retryWithBackoff<T>(
  operation: () => Promise<T>,
  options: {
    maxRetries?: number;
    baseDelay?: number;
    maxDelay?: number;
    shouldRetry?: (error: ApiError) => boolean;
    onRetry?: (attempt: number, error: ApiError) => void;
  } = {}
): Promise<T> {
  const {
    maxRetries = 3,
    baseDelay = 1000,
    maxDelay = 30000,
    shouldRetry = (error) => error.retryable,
    onRetry,
  } = options;

  let lastError: ApiError | undefined;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await operation();
    } catch (error) {
      const processedError = processApiError(error);
      lastError = processedError;

      if (attempt === maxRetries || !shouldRetry(processedError)) {
        throw processedError;
      }

      // Exponential backoff with jitter
      const delay = Math.min(
        baseDelay * Math.pow(2, attempt) + Math.random() * 1000,
        maxDelay
      );

      onRetry?.(attempt + 1, processedError);

      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }

  throw lastError || new Error('Operation failed after retries');
}

/**
 * Hook-compatible error handler for React components
 */
export function createErrorHandler(context: string) {
  return {
    handle: (error: unknown, options: Omit<ErrorHandlerOptions, 'context'> = {}) => {
      return processApiError(error, { context, ...options });
    },
    wrap: <T extends (...args: unknown[]) => Promise<unknown>>(
      fn: T,
      options: Omit<ErrorHandlerOptions, 'context'> = {}
    ) => {
      return async (...args: Parameters<T>): Promise<ReturnType<T>> => {
        try {
          return await fn(...args) as ReturnType<T>;
        } catch (error) {
          throw processApiError(error, { context, ...options });
        }
      };
    },
  };
}
