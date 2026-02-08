import { useState, useEffect } from 'react';
import { useDevSwarm } from '../hooks/useDevSwarm';
import DevSwarmTaskList from '../components/DevSwarmTaskList';
import DevSwarmStats from '../components/DevSwarmStats';
import DevSwarmCreateTask from '../components/DevSwarmCreateTask';
import DevSwarmReadiness from '../components/DevSwarmReadiness';
import CodebaseHealth from '../components/CodebaseHealth';

export default function DevSwarm() {
  const { tasks, stats, agents, loading, error, refreshTasks, refreshStats, createTask } = useDevSwarm();
  const [showCreateForm, setShowCreateForm] = useState(false);

  useEffect(() => {
    refreshTasks();
    refreshStats();
    
    // Refresh every 5 seconds
    const interval = setInterval(() => {
      refreshTasks();
      refreshStats();
    }, 5000);
    
    return () => clearInterval(interval);
  }, []);

  const handleCreateTask = async (taskData: any) => {
    try {
      await createTask(taskData);
      setShowCreateForm(false);
      refreshTasks();
      refreshStats();
    } catch (err) {
      console.error('Failed to create task:', err);
    }
  };

  if (loading && !stats) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-900/20 border border-red-500 rounded-lg p-4">
          <h3 className="text-red-400 font-semibold mb-2">Error Loading Dev Swarm</h3>
          <p className="text-red-300">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white">Dev Swarm</h1>
          <p className="text-slate-400 mt-1">
            Autonomous development agents for code generation, testing, and fixes
          </p>
        </div>
        <button
          onClick={() => setShowCreateForm(!showCreateForm)}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-medium transition-colors"
        >
          {showCreateForm ? 'Cancel' : '+ New Task'}
        </button>
      </div>

      {/* Stats Dashboard */}
      {stats && <DevSwarmStats stats={stats} agents={agents || []} />}

      {/* Readiness Audit */}
      <DevSwarmReadiness />

      {/* Global Codebase Health */}
      <CodebaseHealth />

      {/* Create Task Form */}
      {showCreateForm && (
        <DevSwarmCreateTask
          onSubmit={handleCreateTask}
          onCancel={() => setShowCreateForm(false)}
        />
      )}

      {/* Task List */}
      <DevSwarmTaskList tasks={tasks || []} onRefresh={refreshTasks} />
    </div>
  );
}
