// web/react/src/hooks/useKalshiExecutionTelemetry.ts
import { useEffect, useState, useCallback } from "react";
import { authHeaders } from "../api/auth";
import { API_BASE_URL, API_ENDPOINTS } from "../config/constants";

type ProductMetrics = {
  [key: string]: {
    value: number;
    status: "good" | "warning" | "info";
    threshold?: number;
  };
};

type ExecutionTelemetryData = {
  metrics: {
    [product: string]: {
      [metric: string]: number;
    };
  };
  status: {
    [product: string]: ProductMetrics;
  };
  error?: string;
};

export const useKalshiExecutionTelemetry = () => {
  const [data, setData] = useState<ExecutionTelemetryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_EXECUTION_TELEMETRY}`, { headers: authHeaders() });
      if (!resp.ok) throw new Error(await resp.text());
      const json = await resp.json();
      setData(json);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 10000);
    return () => clearInterval(id);
  }, [fetchData]);

  return { data, loading, error, refetch: fetchData };
};
