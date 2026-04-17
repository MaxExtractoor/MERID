// Centralized authentication utilities for API calls
import { AUTH_TOKEN_KEY } from '../config/constants';

/**
 * Get authentication headers for API requests.
 * Returns headers with Authorization Bearer token and X-Session-ID if token exists.
 */
export function getAuthHeaders(additionalHeaders?: HeadersInit): HeadersInit {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
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
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  
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
  return !!localStorage.getItem(AUTH_TOKEN_KEY);
}

/**
 * Get the raw auth token
 */
export function getAuthToken(): string | null {
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

/**
 * Clear authentication (logout)
 */
export function clearAuth(): void {
  localStorage.removeItem(AUTH_TOKEN_KEY);
}
