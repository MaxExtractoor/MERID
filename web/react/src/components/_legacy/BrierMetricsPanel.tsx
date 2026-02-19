import { useState } from 'react';
import { Target, TrendingUp, TrendingDown, Award, RefreshCw, AlertCircle } from 'lucide-react';
import { useApiData } from '../hooks/useApiData';
import { DEFAULTS } from "../config/constants";

interface BrierScore {
  agent_name: string;
  overall_score: number;
  total_predictions: number;
  calibration_score: number;
  resolution_score: number;
  trend: 'improving' | 'declining' | 'stable';
  change_percent: number;
}

interface PredictionAccuracy {
  confidence_bucket: string;
  predicted_probability: number;
  actual_frequency: number;
  count: number;
  brier_contribution: number;
}

interface HistoricalBrier {
  date: string;
  score: number;
}

interface BrierMetricsData {
  agent_scores: BrierScore[];
  calibration_curve: PredictionAccuracy[];
  historical_scores: HistoricalBrier[];
  best_performer: string;
  worst_performer: string;
  average_score: number;
}

interface BrierMetricsPanelProps {
  className?: string;
}

export default function BrierMetricsPanel({ className = '' }: BrierMetricsPanelProps) {
  const [selectedAgent, setSelectedAgent] = useState<string>('all');

  const endpoint = selectedAgent === 'all'
    ? '/api/v1/metrics/brier'
    : `/api/v1/metrics/brier?agent=${selectedAgent}`;
  const { data: metricsData, loading, error, refetch } = useApiData<BrierMetricsData>(
    endpoint,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.BACKGROUND },
  );

  const getScoreColor = (score: number) => {
    if (score <= 0.15) return 'text-green-400';
    if (score <= 0.20) return 'text-yellow-400';
    return 'text-red-400';
  };

  const getScoreGrade = (score: number) => {
    if (score <= 0.10) return 'Excellent';
    if (score <= 0.15) return 'Good';
    if (score <= 0.20) return 'Fair';
    return 'Poor';
  };

  const getTrendIcon = (trend: string) => {
    switch (trend) {
      case 'improving': return <TrendingDown className="w-4 h-4 text-green-400" />;
      case 'declining': return <TrendingUp className="w-4 h-4 text-red-400" />;
      default: return <div className="w-4 h-4" />;
    }
  };

  const agents = ['all', ...Array.from(new Set(metricsData?.agent_scores.map(s => s.agent_name) || []))];

  if (loading) {
    return (
      <div className={`bg-slate-800/50 rounded-lg border border-slate-700/50 p-6 ${className}`}>
        <div className="flex items-center justify-center">
          <RefreshCw className="w-6 h-6 animate-spin text-blue-500" />
          <span className="ml-2 text-gray-400">Loading Brier metrics...</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`space-y-6 ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Target className="w-6 h-6 text-blue-400" />
          <div>
            <h2 className="text-lg font-bold text-white">Brier Score Metrics</h2>
            <p className="text-sm text-gray-400">Prediction accuracy and calibration (lower is better)</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <select aria-label="Selected Agent"
            id="brier-agent-filter"
            name="agentFilter"
            value={selectedAgent}
            onChange={(e) => setSelectedAgent(e.target.value)}
            className="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500"
            title="Filter by agent"
          >
            {agents.map(agent => (
              <option key={agent} value={agent}>
                {agent === 'all' ? 'All Agents' : agent}
              </option>
            ))}
          </select>
          <button type="button"
            onClick={() => refetch()}
            className="p-2 hover:bg-slate-700 rounded-lg transition-colors"
            title="Refresh metrics"
           aria-label="Refresh">
            <RefreshCw className="w-4 h-4 text-gray-400" />
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-yellow-900/20 border border-yellow-600/50 rounded-lg p-4 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-yellow-500" />
          <div>
            <p className="text-yellow-500 font-medium">Data unavailable</p>
            <p className="text-sm text-gray-400">{error?.message ?? 'Unknown error'}</p>
          </div>
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Award className="w-4 h-4 text-green-400" />
            <p className="text-sm text-gray-400">Best Performer</p>
          </div>
          <p className="text-xl font-bold text-white">{metricsData?.best_performer}</p>
          <p className="text-sm text-green-400 mt-1">
            {metricsData?.agent_scores.find(s => s.agent_name === metricsData.best_performer)?.overall_score.toFixed(3)}
          </p>
        </div>

        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Target className="w-4 h-4 text-blue-400" />
            <p className="text-sm text-gray-400">Average Score</p>
          </div>
          <p className="text-xl font-bold text-white">{metricsData?.average_score.toFixed(3)}</p>
          <p className="text-sm text-gray-400 mt-1">{getScoreGrade(metricsData?.average_score || 0)}</p>
        </div>

        <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-4">
          <div className="flex items-center gap-2 mb-2">
            <TrendingDown className="w-4 h-4 text-purple-400" />
            <p className="text-sm text-gray-400">Total Predictions</p>
          </div>
          <p className="text-xl font-bold text-white">
            {metricsData?.agent_scores.reduce((sum, s) => sum + s.total_predictions, 0)}
          </p>
          <p className="text-sm text-gray-400 mt-1">Across all agents</p>
        </div>
      </div>

      {/* Agent Scores */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50">
        <div className="p-4 border-b border-slate-700/50">
          <h3 className="text-lg font-bold text-white">Agent Brier Scores</h3>
        </div>
        <div className="p-4 space-y-3">
          {metricsData?.agent_scores.map(agent => (
            <div key={agent.agent_name} className="bg-slate-900/50 p-4 rounded-lg">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-3">
                  <h4 className="text-white font-bold">{agent.agent_name}</h4>
                  {getTrendIcon(agent.trend)}
                  <span className={`text-sm ${agent.change_percent < 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {agent.change_percent > 0 ? '+' : ''}{agent.change_percent.toFixed(1)}%
                  </span>
                </div>
                <div className="text-right">
                  <p className={`text-2xl font-bold ${getScoreColor(agent.overall_score)}`}>
                    {agent.overall_score.toFixed(3)}
                  </p>
                  <p className="text-xs text-gray-400">{getScoreGrade(agent.overall_score)}</p>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <p className="text-gray-400">Predictions</p>
                  <p className="text-white font-medium">{agent.total_predictions}</p>
                </div>
                <div>
                  <p className="text-gray-400">Calibration</p>
                  <p className="text-white font-medium">{agent.calibration_score.toFixed(3)}</p>
                </div>
                <div>
                  <p className="text-gray-400">Resolution</p>
                  <p className="text-white font-medium">{agent.resolution_score.toFixed(3)}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Calibration Curve */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <h3 className="text-lg font-bold text-white mb-4">Calibration Curve</h3>
        <p className="text-sm text-gray-400 mb-6">
          Predicted probability vs actual frequency (perfect calibration = diagonal line)
        </p>
        
        <div className="space-y-2">
          {metricsData?.calibration_curve.map(point => {
            const diff = Math.abs(point.predicted_probability - point.actual_frequency);
            const isWellCalibrated = diff <= 0.05;
            
            return (
              <div key={point.confidence_bucket} className="space-y-1">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-gray-400 w-24">{point.confidence_bucket}</span>
                  <span className="text-gray-400 w-20">Pred: {(point.predicted_probability * 100).toFixed(0)}%</span>
                  <span className={`w-20 ${isWellCalibrated ? 'text-green-400' : 'text-yellow-400'}`}>
                    Act: {(point.actual_frequency * 100).toFixed(0)}%
                  </span>
                  <span className="text-gray-500 w-16">{point.count} pred</span>
                </div>
                <div className="relative h-6 bg-slate-700 rounded overflow-hidden">
                  <div
                    className="absolute h-full bg-blue-500/30"
                    style={{ width: `${point.predicted_probability * 100}%` }}
                  />
                  <div
                    className={`absolute h-full ${isWellCalibrated ? 'bg-green-500' : 'bg-yellow-500'}`}
                    style={{ width: `${point.actual_frequency * 100}%`, opacity: 0.7 }}
                  />
                </div>
              </div>
            );
          })}
        </div>

        <div className="mt-4 flex items-center gap-4 text-xs text-gray-400">
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 bg-blue-500/30 rounded" />
            <span>Predicted</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 bg-green-500 rounded" />
            <span>Actual (well calibrated)</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 bg-yellow-500 rounded" />
            <span>Actual (needs improvement)</span>
          </div>
        </div>
      </div>

      {/* Historical Trend */}
      <div className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-6">
        <h3 className="text-lg font-bold text-white mb-4">Historical Trend</h3>
        <div className="relative h-48 flex items-end gap-2">
          {metricsData?.historical_scores.map((point, index) => {
            const maxScore = Math.max(...(metricsData?.historical_scores.map(p => p.score) || []));
            const height = (point.score / maxScore) * 100;
            const isImproving = index === 0 || point.score < metricsData.historical_scores[index - 1].score;
            
            return (
              <div key={point.date} className="flex-1 flex flex-col items-center gap-2">
                <div className="flex-1 flex items-end w-full">
                  <div
                    className={`w-full rounded-t transition-all duration-500 ${
                      isImproving ? 'bg-green-500' : 'bg-red-500'
                    }`}
                    style={{ height: `${height}%` }}
                  />
                </div>
                <div className="text-xs text-gray-400">{point.date}</div>
                <div className={`text-xs font-medium ${getScoreColor(point.score)}`}>
                  {point.score.toFixed(3)}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Info Box */}
      <div className="bg-blue-900/20 border border-blue-600/50 rounded-lg p-4">
        <h4 className="text-blue-400 font-semibold mb-2">Understanding Brier Scores</h4>
        <ul className="text-sm text-gray-300 space-y-1">
          <li>• <strong>Lower is better:</strong> 0.0 = perfect predictions, 1.0 = worst possible</li>
          <li>• <strong>Excellent:</strong> ≤0.10 | <strong>Good:</strong> ≤0.15 | <strong>Fair:</strong> ≤0.20</li>
          <li>• <strong>Calibration:</strong> How well predicted probabilities match actual frequencies</li>
          <li>• <strong>Resolution:</strong> Ability to distinguish between different outcomes</li>
        </ul>
      </div>
    </div>
  );
}
