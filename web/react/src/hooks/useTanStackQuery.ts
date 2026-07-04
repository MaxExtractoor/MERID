/**
 * useTanStackQuery - Adapter hook for TanStack Query API calls
 * Provides a migration path from useApiData to TanStack Query
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { API_BASE_URL, AUTH_TOKEN_KEY } from '../config/constants';

interface UseQueryOptions {
  enabled?: boolean;
  refetchInterval?: number;
  staleTime?: number;
}

interface UseMutationOptions {
  onSuccess?: (data: unknown) => void;
  onError?: (error: Error) => void;
}

// Helper to get auth headers
const getAuthHeaders = () => {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
    headers['X-Session-ID'] = token;
  }
  return headers;
};

// Query hook for GET requests
export function useApiQuery<T>(
  endpoint: string,
  options: UseQueryOptions = {}
) {
  const { enabled = true, refetchInterval, staleTime = 30_000 } = options;

  return useQuery({
    queryKey: [endpoint],
    queryFn: async () => {
      const url = endpoint.startsWith('http') ? endpoint : `${API_BASE_URL}${endpoint}`;
      const response = await fetch(url, {
        headers: getAuthHeaders(),
      });
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      return response.json() as Promise<T>;
    },
    enabled,
    refetchInterval,
    staleTime,
  });
}

// Mutation hook for POST/PUT/DELETE requests
export function useApiMutation<T>(
  endpoint: string,
  method: 'POST' | 'PUT' | 'DELETE' | 'PATCH' = 'POST',
  options: UseMutationOptions = {}
) {
  const queryClient = useQueryClient();
  const { onSuccess, onError } = options;

  return useMutation({
    mutationFn: async (data?: unknown) => {
      const url = endpoint.startsWith('http') ? endpoint : `${API_BASE_URL}${endpoint}`;
      const response = await fetch(url, {
        method,
        headers: getAuthHeaders(),
        body: data ? JSON.stringify(data) : undefined,
      });
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      return response.json() as Promise<T>;
    },
    onSuccess: (data) => {
      // Invalidate related queries
      queryClient.invalidateQueries({ queryKey: [endpoint] });
      onSuccess?.(data);
    },
    onError,
  });
}

export default { useApiQuery, useApiMutation };
