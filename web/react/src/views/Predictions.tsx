import { PredictionsPanel } from './PredictionsPanel';

/**
 * Predictions View
 * 
 * Displays prediction markets with real-time updates.
 * Uses PredictionsPanel component following the same pattern as Agents/Orders/Risk.
 */
export default function Predictions() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Prediction Markets</h1>
      <PredictionsPanel />
    </div>
  );
}
