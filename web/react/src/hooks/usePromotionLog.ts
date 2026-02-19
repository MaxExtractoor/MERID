import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL, API_ENDPOINTS } from '../config/constants';

export interface PromotionEvent {
  timestamp: number;
  entity_type: 'domain' | 'agent';
  entity_id: string;
  previous_status: string;
  new_status: string;
  reason: string;
  report_timestamp: number;
  runbook_version: string;
  source: 'automation' | 'operator' | 'system';
}

export interface PromotionLogResponse {
  total_events: number;
  returned: number;
  events: PromotionEvent[];
}

interface UsePromotionLogResult {
  data: PromotionLogResponse | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
}

export function usePromotionLog(
  entityType?: string,
  entityId?: string,
  limit = 50,
  pollingMs = 60000,
): UsePromotionLogResult {
  const [data, setData] = useState<PromotionLogResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const authHeaders = useCallback((headers?: HeadersInit): HeadersInit => {
    const token = localStorage.getItem('merid-access');
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(headers ?? {}),
    };
  }, []);

  const fetchLog = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (entityType) params.set('entity_type', entityType);
      if (entityId) params.set('entity_id', entityId);
      params.set('limit', String(limit));

      const res = await fetch(
        `${API_BASE_URL}${API_ENDPOINTS.PROMOTION_LOG}?${params.toString()}`,
        { headers: authHeaders() },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: PromotionLogResponse = await res.json();
      setData(json);
      setError(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to fetch promotion log');
    } finally {
      setLoading(false);
    }
  }, [authHeaders, entityType, entityId, limit]);

  const refetch = useCallback(async () => {
    setLoading(true);
    await fetchLog();
  }, [fetchLog]);

  useEffect(() => {
    fetchLog();
    const id = setInterval(fetchLog, pollingMs);
    return () => clearInterval(id);
  }, [fetchLog, pollingMs]);

  return { data, loading, error, refetch };
}
