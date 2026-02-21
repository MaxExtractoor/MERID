import { useState, useCallback } from 'react';
import axios from 'axios';
import { logUiError } from '../utils/logger';

const API_BASE = '/api/dev-swarm';

export interface DevTask {
  task_id: string;
  description: string;
  target_files: string[];
  success_criteria: string;
  priority: number;
  estimated_effort: string;
  timeout_seconds: number;
  max_cost_usd: number;
  status: string;
  created_at: number;
  started_at: number | null;
  completed_at: number | null;
  error: string | null;
  cost_usd: number;
  duration_seconds: number | null;
  result: unknown | null;
}

export interface DevAgent {
  name: string;
  role: string;
  llm_model: string;
  max_iterations: number;
  timeout_seconds: number;
}

export interface DevSwarmStats {
  active_tasks: number;
  total_tasks: number;
  completed: number;
  failed: number;
  timeout: number;
  cancelled: number;
  success_rate: number;
  avg_duration_seconds: number;
  daily_cost_usd: number;
  cost_budget_remaining: number;
}

export interface CreateTaskRequest {
  description: string;
  target_files: string[];
  success_criteria: string;
  priority?: number;
  estimated_effort?: string;
  timeout_seconds?: number;
  max_cost_usd?: number;
}

export function useDevSwarm() {
  const [tasks, setTasks] = useState<DevTask[]>([]);
  const [stats, setStats] = useState<DevSwarmStats | null>(null);
  const [agents, setAgents] = useState<DevAgent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refreshTasks = useCallback(async (status?: string) => {
    setLoading(true);
    setError(null);
    try {
      const params = status ? { status } : {};
      const response = await axios.get(`${API_BASE}/tasks`, { params });
      setTasks(response.data.tasks);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load tasks';
      setError(msg);
      logUiError('useDevSwarm', 'Failed to load tasks', err);
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshStats = useCallback(async () => {
    try {
      const response = await axios.get(`${API_BASE}/stats`);
      setStats(response.data);
    } catch (err) {
      logUiError('useDevSwarm', 'Failed to load stats', err);
    }
  }, []);

  const loadAgents = useCallback(async () => {
    try {
      const response = await axios.get(`${API_BASE}/agents`);
      setAgents(response.data);
    } catch (err) {
      logUiError('useDevSwarm', 'Failed to load agents', err);
    }
  }, []);

  const getTask = useCallback(async (taskId: string): Promise<DevTask | null> => {
    try {
      const response = await axios.get(`${API_BASE}/tasks/${taskId}`);
      return response.data;
    } catch (err) {
      logUiError('useDevSwarm', 'Failed to load task', err);
      return null;
    }
  }, []);

  const createTask = useCallback(async (request: CreateTaskRequest): Promise<DevTask | null> => {
    setLoading(true);
    setError(null);
    try {
      const response = await axios.post(`${API_BASE}/tasks`, request);
      await refreshTasks();
      await refreshStats();
      return response.data;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to create task';
      setError(msg);
      logUiError('useDevSwarm', 'Failed to create task', err);
      return null;
    } finally {
      setLoading(false);
    }
  }, [refreshTasks, refreshStats]);

  const cancelTask = useCallback(async (taskId: string): Promise<boolean> => {
    try {
      await axios.delete(`${API_BASE}/tasks/${taskId}`);
      await refreshTasks();
      await refreshStats();
      return true;
    } catch (err) {
      logUiError('useDevSwarm', 'Failed to cancel task', err);
      return false;
    }
  }, [refreshTasks, refreshStats]);

  return {
    tasks,
    stats,
    agents,
    loading,
    error,
    refreshTasks,
    refreshStats,
    loadAgents,
    getTask,
    createTask,
    cancelTask,
  };
}
