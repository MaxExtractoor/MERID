import { Bot } from 'lucide-react';
import { LiveAgentHealthPanel } from './LiveAgentHealthPanel';
import StrategyLeaderboard from '../components/StrategyLeaderboard';
import { OperatorActivityStream } from './OperatorActivityStream';
import DataHealthCard from '../components/DataHealthCard';

export default function AgentHealthView() {
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Bot className="w-6 h-6 text-cyan-400" />
        <h1 className="text-xl font-bold text-slate-100">Agent Health</h1>
      </div>

      {/* Live Agent Health */}
      <LiveAgentHealthPanel />

      {/* Strategy Leaderboard */}
      <StrategyLeaderboard />

      {/* Activity Stream */}
      <OperatorActivityStream />

      {/* Data Health */}
      <DataHealthCard />
    </div>
  );
}
