/**
 * Resilient HTTP client with exponential backoff, health check gating, and error normalization.
 * Prevents spamming failing endpoints when backend is down.
 */

import { API_BASE_URL } from '../config/constants';
import { logUiError } from '../utils/logger';

export interface ApiError {
  status: number;
  message: string;
  code: string;
  retryable: boolean;
}

export interface FetchOptions extends RequestInit {
  skipHealthCheck?: boolean;
  maxRetries?: number;
  retryDelayMs?: number;
  timeoutMs?: number;
}

// Backend health state (module-level)
let backendHealthy = true;
let lastHealthCheck = 0;
let consecutiveFailures = 0;
const HEALTH_CHECK_INTERVAL_MS = 5000;
const MAX_CONSECUTIVE_FAILURES = 3;

/**
 * Check if backend is healthy via /api/v1/system/health endpoint.
 * Cached for HEALTH_CHECK_INTERVAL_MS to avoid spamming.
 */
export async function checkBackendHealth(): Promise<boolean> {
  const now = Date.now();
  if (now - lastHealthCheck < HEALTH_CHECK_INTERVAL_MS) {
    return backendHealthy;
  }
  
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 3000);
    
    const response = await fetch(`${API_BASE_URL}/api/v1/system/health`, {
      method: 'GET',
      credentials: 'include',
      signal: controller.signal,
    });
    
    clearTimeout(timeoutId);
    
    backendHealthy = response.ok;
    lastHealthCheck = now;
    
    if (response.ok) {
      consecutiveFailures = 0;
    }
    
    return backendHealthy;
  } catch (error) {
    backendHealthy = false;
    lastHealthCheck = now;
    return false;
  }
}

/**
 * Returns current backend health status without triggering a check.
 */
export function isBackendHealthy(): boolean {
  return backendHealthy;
}

/**
 * Reset health state (useful after recovery).
 */
export function resetHealthState(): void {
  backendHealthy = true;
  consecutiveFailures = 0;
  lastHealthCheck = 0;
}

/**
 * Normalize fetch errors into structured ApiError.
 */
function normalizeError(response: Response | null, nativeError: unknown): ApiError {
  if (response) {
    const status = response.status;
    const retryable = status >= 500 || status === 429 || status === 0;
    return {
      status,
      message: `HTTP ${status}: ${response.statusText}`,
      code: `HTTP_${status}`,
      retryable,
    };
  }
  
  // Network or other errors
  const message = nativeError instanceof Error ? nativeError.message : 'Unknown error';
  const isNetworkError = message.includes('fetch') || 
                         message.includes('network') || 
                         message.includes('Failed to fetch') ||
                         message.includes('ERR_CONNECTION_REFUSED');
  
  return {
    status: 0,
    message: isNetworkError ? 'Backend unavailable' : message,
    code: isNetworkError ? 'NETWORK_ERROR' : 'UNKNOWN_ERROR',
    retryable: true,
  };
}

/**
 * Resilient fetch with exponential backoff, timeout, and health check gating.
 */
export async function resilientFetch(
  url: string,
  options: FetchOptions = {}
): Promise<Response> {
  const {
    skipHealthCheck = false,
    maxRetries = 3,
    retryDelayMs = 1000,
    timeoutMs = 30000,
    ...fetchOptions
  } = options;
  
  // Check backend health first (unless skipped)
  if (!skipHealthCheck && !backendHealthy) {
    const healthy = await checkBackendHealth();
    if (!healthy) {
      throw normalizeError(null, new Error('Backend offline - request gated'));
    }
  }
  
  let lastError: ApiError | null = null;
  
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
      
      const response = await fetch(url, {
        ...fetchOptions,
        credentials: 'include',
        signal: controller.signal,
      });
      
      clearTimeout(timeoutId);
      
      if (response.ok) {
        consecutiveFailures = 0;
        backendHealthy = true;
        return response;
      }
      
      // Non-OK response - may retry if 5xx or 429
      lastError = normalizeError(response, null);
      
      if (!lastError.retryable || attempt === maxRetries - 1) {
        throw lastError;
      }
      
      // Exponential backoff
      const delay = retryDelayMs * Math.pow(2, attempt);
      await new Promise(r => setTimeout(r, delay));
      
    } catch (error) {
      // Preserve already-normalized ApiErrors (e.g. from the non-retryable throw above)
      if (error && typeof error === 'object' && 'retryable' in error && 'code' in error) {
        lastError = error as ApiError;
      } else {
        lastError = normalizeError(null, error);
      }
      
      if (!lastError.retryable || attempt === maxRetries - 1) {
        consecutiveFailures++;
        
        // Mark backend unhealthy after consecutive failures
        if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
          backendHealthy = false;
        }
        
        logUiError('resilientFetch', lastError.message, { url, attempt });
        throw lastError;
      }
      
      // Exponential backoff for network errors
      const delay = retryDelayMs * Math.pow(2, attempt) + (Math.random() * 1000);
      await new Promise(r => setTimeout(r, delay));
    }
  }
  
  throw lastError ?? normalizeError(null, new Error('Max retries exceeded'));
}

/**
 * JSON API helper with typed responses.
 */
export async function apiGet<T>(path: string, options?: FetchOptions): Promise<T> {
  const response = await resilientFetch(`${API_BASE_URL}${path}`, {
    method: 'GET',
    headers: { 'Accept': 'application/json' },
    ...options,
  });
  
  return response.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: unknown, options?: FetchOptions): Promise<T> {
  const response = await resilientFetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    },
    body: JSON.stringify(body),
    ...options,
  });
  
  return response.json() as Promise<T>;
}

/**
 * Creates a typed API client for a specific endpoint pattern.
 */
export function createApiClient<T>(basePath: string) {
  return {
    get: (path?: string, options?: FetchOptions) => 
      apiGet<T>(`${basePath}${path ?? ''}`, options),
    post: (path: string, body: unknown, options?: FetchOptions) => 
      apiPost<T>(`${basePath}${path}`, body, options),
    getAll: () => apiGet<T>(basePath),
  };
}
