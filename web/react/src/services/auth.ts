// Centralized authentication utilities for API calls
import { AUTH_TOKEN_KEY } from '../config/constants';

/**
 * Safely get item from localStorage (handles private mode, disabled storage).
 */
function safeLocalStorageGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    // Private mode, storage disabled, or quota exceeded
    return null;
  }
}

/**
 * Safely remove item from localStorage.
 */
function safeLocalStorageRemove(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // Ignore
  }
}

/**
 * Get authentication headers for API requests.
 * Returns headers with Authorization Bearer token and X-Session-ID if token exists.
 */
export function getAuthHeaders(additionalHeaders?: HeadersInit): HeadersInit {
  const token = safeLocalStorageGet(AUTH_TOKEN_KEY);
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
    headers['X-Session-ID'] = token;
  }

  if (additionalHeaders) {
    Object.assign(headers, additionalHeaders);
  }

  return headers;
}

/**
 * Hook-compatible version of getAuthHeaders for use in React components.
 * Memoized to prevent unnecessary re-renders.
 */
export function useAuthHeaders(additionalHeaders?: HeadersInit): () => HeadersInit {
  const token = safeLocalStorageGet(AUTH_TOKEN_KEY);

  return () => {
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
    };

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
      headers['X-Session-ID'] = token;
    }

    if (additionalHeaders) {
      Object.assign(headers, additionalHeaders);
    }

    return headers;
  };
}

/**
 * Check if user is authenticated (has valid token)
 */
export function isAuthenticated(): boolean {
  return !!safeLocalStorageGet(AUTH_TOKEN_KEY);
}

/**
 * Get the raw auth token
 */
export function getAuthToken(): string | null {
  return safeLocalStorageGet(AUTH_TOKEN_KEY);
}

/**
 * Clear authentication (logout)
 */
export function clearAuth(): void {
  safeLocalStorageRemove(AUTH_TOKEN_KEY);
}
