import { useState, useEffect, useCallback } from 'react';
import { API_ENDPOINTS } from '../config/constants';

export interface LLMTracesSummary {
  total_traces: number;
  traces_window: number;
  tokens_window: number;
  avg_latency_ms: number;
  error_rate: number;
  by_role: Record<string, number>;
  by_status: Record<string, number>;
  window_s: number;
}

export interface LLMToolsSummary {
  total_calls: number;
  calls_window: number;
  avg_latency_ms: number;
  error_rate: number;
  by_tool: Record<string, number>;
  window_s: number;
}

export interface LLMGuardrailsSummary {
  total_events: number;
  events_window: number;
  by_type: Record<string, number>;
  window_s: number;
}

export interface LLMGuardrailEvent {
  id: string;
  trace_id: string;
  role: string;
  event_type: string;
  reason: string;
  created_at: number;
}

export interface LLMPromptVersion {
  id: string;
  role: string;
  name: string;
  version: number;
  content: string;
  created_at: number;
  created_by: string;
}

export interface LLMObservabilityData {
  tracesSummary: LLMTracesSummary;
  toolsSummary: LLMToolsSummary;
  guardrailsSummary: LLMGuardrailsSummary;
  guardrailEvents: LLMGuardrailEvent[];
  prompts: LLMPromptVersion[];
  promptCount: number;
}

const EMPTY_TRACES: LLMTracesSummary = {
  total_traces: 0,
  traces_window: 0,
  tokens_window: 0,
  avg_latency_ms: 0,
  error_rate: 0,
  by_role: {},
  by_status: {},
  window_s: 86400,
};

const EMPTY_TOOLS: LLMToolsSummary = {
  total_calls: 0,
  calls_window: 0,
  avg_latency_ms: 0,
  error_rate: 0,
  by_tool: {},
  window_s: 86400,
};

const EMPTY_GUARDRAILS: LLMGuardrailsSummary = {
  total_events: 0,
  events_window: 0,
  by_type: {},
  window_s: 86400,
};

export function useLLMObservability(pollMs = 30000) {
  const [data, setData] = useState<LLMObservabilityData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [traceRes, toolRes, guardRes, promptRes] = await Promise.all([
        fetch(API_ENDPOINTS.LLM_TRACES_SUMMARY),
        fetch(API_ENDPOINTS.LLM_TOOLS_SUMMARY),
        fetch(API_ENDPOINTS.LLM_GUARDRAILS),
        fetch(API_ENDPOINTS.LLM_PROMPTS),
      ]);

      const tracesSummary = traceRes.ok ? await traceRes.json() : null;
      const toolsSummary = toolRes.ok ? await toolRes.json() : null;
      const guardrailsRaw = guardRes.ok ? await guardRes.json() : null;
      const promptsRaw = promptRes.ok ? await promptRes.json() : null;

      if (!tracesSummary && !toolsSummary && !guardrailsRaw) {
        throw new Error('LLM observability endpoints unavailable');
      }

      setData({
        tracesSummary: tracesSummary ?? EMPTY_TRACES,
        toolsSummary: toolsSummary ?? EMPTY_TOOLS,
        guardrailsSummary: guardrailsRaw?.summary ?? EMPTY_GUARDRAILS,
        guardrailEvents: guardrailsRaw?.events ?? [],
        prompts: promptsRaw?.prompts ?? [],
        promptCount: promptsRaw?.count ?? (promptsRaw?.prompts?.length ?? 0),
      });
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, pollMs);
    return () => clearInterval(interval);
  }, [refresh, pollMs]);

  return { data, loading, error, refresh };
}
