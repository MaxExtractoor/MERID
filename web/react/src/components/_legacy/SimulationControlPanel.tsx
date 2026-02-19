import { useState } from 'react';
import { Play, Pause, RotateCcw, FastForward, Settings, Save, Upload, Clock, Zap } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import ErrorBar from './ErrorBar';
import { API_ENDPOINTS, DEFAULTS} from '../config/constants';

interface SimulationState {
  running: boolean;
  speed: number;
  current_time: string;
  elapsed_seconds: number;
  events_processed: number;
}

interface SimulationControlPanelProps {
  className?: string;
}

export default function SimulationControlPanel({ className = '' }: SimulationControlPanelProps) {
  const [loading, setLoading] = useState(false);

  const { data: state, error: fetchError, refetch } = useApiData<SimulationState>(
    API_ENDPOINTS.SIMULATION_STATUS,
    {
      pollingInterval: DEFAULTS.POLLING_INTERVALS.SIMULATION,
      initialData: {
        running: false,
        speed: 1,
        current_time: new Date().toISOString(),
        elapsed_seconds: 0,
        events_processed: 0,
      },
    },
  );

  if (fetchError && !state) {
    return <ErrorBar label="Simulation" error={fetchError} onRetry={refetch} />;
  }

  const speedOptions = [
    { value: 1, label: '1x', color: 'text-gray-400' },
    { value: 10, label: '10x', color: 'text-blue-400' },
    { value: 100, label: '100x', color: 'text-purple-400' },
    { value: 1000, label: '1000x', color: 'text-red-400' }
  ];

  const handlePlayPause = async () => {
    setLoading(true);
    try {
      const endpoint = state?.running ? '/api/v1/simulation/pause' : '/api/v1/simulation/start';
      const response = await fetch(endpoint, { method: 'POST' });
      if (response.ok) {
        refetch();
      }
    } catch {
      // Operation failed — UI state unchanged
    } finally {
      setLoading(false);
    }
  };

  const handleReset = async () => {
    if (!confirm('Reset simulation? This will clear all paper trading data.')) return;
    
    setLoading(true);
    try {
      const response = await fetch(API_ENDPOINTS.SIMULATION_RESET, { method: 'POST' });
      if (response.ok) {
        refetch();
      }
    } catch {
      // Operation failed — UI state unchanged
    } finally {
      setLoading(false);
    }
  };

  const handleSpeedChange = async (speed: number) => {
    setLoading(true);
    try {
      const response = await fetch(API_ENDPOINTS.SIMULATION_SPEED(speed), { method: 'POST' });
      if (response.ok) {
        refetch();
      }
    } catch {
      // Operation failed — UI state unchanged
    } finally {
      setLoading(false);
    }
  };

  const handleSaveState = async () => {
    try {
      const response = await fetch(API_ENDPOINTS.SIMULATION_SAVE, { method: 'POST' });
      if (response.ok) {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `simulation_state_${Date.now()}.json`;
        a.click();
      }
    } catch {
      // Operation failed — UI state unchanged
    }
  };

  const formatTime = (seconds: number) => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className={`bg-slate-800/50 rounded-lg border border-slate-700/50 ${className}`}>
      {/* Header */}
      <div className="px-6 py-4 border-b border-slate-700/50">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Zap className="w-6 h-6 text-yellow-400" />
            <h2 className="text-lg font-bold text-white">Simulation Control</h2>
          </div>
          <div className={`px-3 py-1 rounded-full text-xs font-medium ${
            state.running 
              ? 'bg-green-500/20 text-green-400 animate-pulse' 
              : 'bg-gray-500/20 text-gray-400'
          }`}>
            {state.running ? 'RUNNING' : 'PAUSED'}
          </div>
        </div>
      </div>

      <div className="p-6 space-y-6">
        {/* Playback Controls */}
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-gray-400">Playback Controls</h3>
          <div className="flex items-center gap-3">
            <button type="button"
              onClick={handlePlayPause}
              disabled={loading}
              className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg font-medium transition-colors ${
                state.running
                  ? 'bg-yellow-600 hover:bg-yellow-700 text-white'
                  : 'bg-green-600 hover:bg-green-700 text-white'
              } disabled:opacity-50`}
              title={state.running ? 'Pause simulation' : 'Start simulation'}
            >
              {state.running ? (
                <>
                  <Pause className="w-5 h-5" />
                  Pause
                </>
              ) : (
                <>
                  <Play className="w-5 h-5" />
                  Start
                </>
              )}
            </button>

            <button type="button"
              onClick={handleReset}
              disabled={loading}
              className="px-4 py-3 bg-red-600 hover:bg-red-700 text-white rounded-lg font-medium transition-colors disabled:opacity-50 flex items-center gap-2"
              title="Reset simulation"
            >
              <RotateCcw className="w-5 h-5" />
              Reset
            </button>
          </div>
        </div>

        {/* Speed Controls */}
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-gray-400">Simulation Speed</h3>
          <div className="grid grid-cols-4 gap-2">
            {speedOptions.map(option => (
              <button type="button"
                key={option.value}
                onClick={() => handleSpeedChange(option.value)}
                disabled={loading}
                className={`px-4 py-2 rounded-lg font-medium transition-all ${
                  state.speed === option.value
                    ? 'bg-blue-600 text-white ring-2 ring-blue-400'
                    : 'bg-slate-700 text-gray-400 hover:bg-slate-600'
                } disabled:opacity-50`}
              >
                {option.label}
              </button>
            ))}
          </div>
          <p className="text-xs text-gray-500">
            Current speed: <span className={speedOptions.find(o => o.value === state.speed)?.color}>
              {state.speed}x real-time
            </span>
          </p>
        </div>

        {/* Time Display */}
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-gray-400">Simulation Time</h3>
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-slate-700/30 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <Clock className="w-4 h-4 text-blue-400" />
                <p className="text-xs text-gray-400">Current Time</p>
              </div>
              <p className="text-lg font-mono text-white">
                {new Date(state.current_time).toLocaleString()}
              </p>
            </div>

            <div className="bg-slate-700/30 rounded-lg p-4">
              <div className="flex items-center gap-2 mb-2">
                <FastForward className="w-4 h-4 text-purple-400" />
                <p className="text-xs text-gray-400">Elapsed</p>
              </div>
              <p className="text-lg font-mono text-white">
                {formatTime(state.elapsed_seconds)}
              </p>
            </div>
          </div>
        </div>

        {/* Statistics */}
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-gray-400">Statistics</h3>
          <div className="bg-slate-700/30 rounded-lg p-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-400">Events Processed</span>
              <span className="text-lg font-bold text-white">{state.events_processed.toLocaleString()}</span>
            </div>
          </div>
        </div>

        {/* State Management */}
        <div className="space-y-3">
          <h3 className="text-sm font-medium text-gray-400">State Management</h3>
          <div className="grid grid-cols-2 gap-3">
            <button type="button"
              onClick={handleSaveState}
              className="flex items-center justify-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg transition-colors"
              title="Save simulation state"
            >
              <Save className="w-4 h-4" />
              Save State
            </button>

            <button type="button"
              className="flex items-center justify-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg transition-colors"
              title="Load simulation state"
            >
              <Upload className="w-4 h-4" />
              Load State
            </button>
          </div>
        </div>

        {/* Advanced Settings */}
        <div className="pt-4 border-t border-slate-700/50">
          <button type="button"
            className="w-full flex items-center justify-center gap-2 px-4 py-2 text-gray-400 hover:text-white transition-colors"
            title="Advanced settings"
          >
            <Settings className="w-4 h-4" />
            <span className="text-sm">Advanced Settings</span>
          </button>
        </div>
      </div>

      {/* Footer Info */}
      <div className="px-6 py-3 border-t border-slate-700/50 bg-slate-900/50">
        <p className="text-xs text-gray-500 text-center">
          Simulation uses historical and synthetic data • Paper trading only
        </p>
      </div>
    </div>
  );
}
