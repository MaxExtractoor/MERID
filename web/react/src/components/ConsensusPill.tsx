import React from 'react';

interface ConsensusPillProps {
  label?: string;
  direction?: 'bullish' | 'bearish' | 'neutral';
  confidence?: number;
  agents?: string[];
}

const ConsensusPill: React.FC<ConsensusPillProps> = ({ label, direction, confidence, agents }) => {
  if (label) {
    return <span className="consensus-pill">{label}</span>;
  }

  const directionColors: Record<string, string> = {
    bullish: 'bg-green-500/20 text-green-400 border-green-500/40',
    bearish: 'bg-red-500/20 text-red-400 border-red-500/40',
    neutral: 'bg-slate-500/20 text-slate-400 border-slate-500/40',
  };

  const directionLabels: Record<string, string> = {
    bullish: 'BULLISH',
    bearish: 'BEARISH',
    neutral: 'NEUTRAL',
  };

  return (
    <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full border text-sm font-medium ${directionColors[direction || 'neutral']}`}>
      <span>{directionLabels[direction || 'neutral']}</span>
      {confidence !== undefined && (
        <span className="opacity-80">({(confidence * 100).toFixed(0)}%)</span>
      )}
      {agents && agents.length > 0 && (
        <span className="text-xs opacity-60">· {agents.length} agents</span>
      )}
    </div>
  );
};

const MemoizedConsensusPill = React.memo(ConsensusPill);
MemoizedConsensusPill.displayName = 'ConsensusPill';
export default MemoizedConsensusPill;
