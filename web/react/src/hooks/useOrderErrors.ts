import { useState, useEffect, useCallback, useRef } from 'react';
import { API_BASE_URL, API_ENDPOINTS, AUTH_TOKEN_KEY } from '../config/constants';
import { logUiError } from '../utils/logger';

export interface ErrorBreakdownItem {
  code: string;
  count: number;
  percentage: number;
  severity: 'critical' | 'warning' | 'info';
  category: 'risk' | 'validation' | 'market' | 'system' | 'funds' | 'other';
  description: string;
}

export interface ErrorCategory {
  count: number;
  codes: string[];
}

export interface ErrorSeverity {
  critical: number;
  warning: number;
  info: number;
}

export interface OrderErrorsData {
  window_hours: number;
  total_rejections: number;
  breakdown: ErrorBreakdownItem[];
  by_category: Record<string, ErrorCategory>;
  by_severity: ErrorSeverity;
  top_errors: ErrorBreakdownItem[];
  last_updated: string;
}

export interface UseOrderErrorsReturn {
  data: OrderErrorsData | null;
  loading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
  setWindowHours: (hours: number) => void;
  windowHours: number;
}

const POLL_INTERVAL = 10000; // 10 seconds

export function useOrderErrors(pollingInterval = POLL_INTERVAL): UseOrderErrorsReturn {
  const [data, setData] = useState<OrderErrorsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [windowHours, setWindowHours] = useState(24);
  const consecutiveFailures = useRef(0);

  const authHeaders = useCallback((headers?: HeadersInit): HeadersInit => {
    const token = localStorage.getItem(AUTH_TOKEN_KEY);
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}`, 'X-Session-ID': token } : {}),
      'merid-access': 'O2jbnfBmraDuTGDBTC0lyRBpllrWOFnxjp9qfeUFxm8',
      ...(headers ?? {}),
    };
  }, []);

  const fetchOrderErrors = useCallback(async () => {
    try {
      const url = new URL(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_ORDER_ERRORS}`);
      url.searchParams.set('window_hours', windowHours.toString());
      
      const response = await fetch(url.toString(), {
        headers: authHeaders(),
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      const json = await response.json();
      setData(json);
      setError(null);
      consecutiveFailures.current = 0;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch order errors';
      setError(message);
      if (consecutiveFailures.current === 0) {
        logUiError('useOrderErrors', 'Order errors fetch error', err);
      }
      consecutiveFailures.current += 1;
    } finally {
      setLoading(false);
    }
  }, [authHeaders, windowHours]);

  const refetch = useCallback(async () => {
    setLoading(true);
    await fetchOrderErrors();
  }, [fetchOrderErrors]);

  useEffect(() => {
    fetchOrderErrors();
    
    const interval = setInterval(() => {
      if (consecutiveFailures.current > 1) return; // back off: skip ticks while backend is down
      fetchOrderErrors();
    }, pollingInterval);
    return () => clearInterval(interval);
  }, [fetchOrderErrors, pollingInterval]);

  return {
    data,
    loading,
    error,
    refetch,
    setWindowHours,
    windowHours,
  };
}

// Helper to get color for severity
export function getSeverityColor(severity: string): string {
  switch (severity) {
    case 'critical':
      return 'text-red-400 bg-red-400/10 border-red-400/20';
    case 'warning':
      return 'text-amber-400 bg-amber-400/10 border-amber-400/20';
    case 'info':
      return 'text-blue-400 bg-blue-400/10 border-blue-400/20';
    default:
      return 'text-slate-400 bg-slate-400/10 border-slate-400/20';
  }
}

// Helper to get color for category
export function getCategoryColor(category: string): string {
  switch (category) {
    case 'risk':
      return 'text-red-400';
    case 'validation':
      return 'text-yellow-400';
    case 'market':
      return 'text-blue-400';
    case 'system':
      return 'text-purple-400';
    case 'funds':
      return 'text-orange-400';
    default:
      return 'text-slate-400';
  }
}

// Format error code for display
export function formatErrorCode(code: string): string {
  return code.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase());
}
