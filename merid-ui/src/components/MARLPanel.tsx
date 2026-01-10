import { useMemo } from "react";

type MARLAgentMetrics = {
  agent_id: string;
  epsilon: number;
  total_reward: number;
  episode_count: number;
  memory_size: number;
};

type MARLMetrics = {
  status: string;
  metrics: {
    agents: MARLAgentMetrics[];
    algorithm: string;
  };
};

export function MARLPanel({ metrics }: { metrics: MARLMetrics | null }) {
  const avgReward = useMemo(() => {
    if (!metrics?.metrics?.agents?.length) return 0;
    const total = metrics.metrics.agents.reduce((sum, a) => sum + a.total_reward, 0);
    return total / metrics.metrics.agents.length;
  }, [metrics]);

  const avgEpsilon = useMemo(() => {
    if (!metrics?.metrics?.agents?.length) return 0;
    const total = metrics.metrics.agents.reduce((sum, a) => sum + a.epsilon, 0);
    return total / metrics.metrics.agents.length;
  }, [metrics]);

  if (!metrics || metrics.status === "not_initialized") {
    return (
      <article className="app__card">
        <h2>MARL Training</h2>
        <p className="app__muted">MARL engine not initialized</p>
      </article>
    );
  }

  return (
    <article className="app__card">
      <h2>MARL Training</h2>
      <div className="marl-panel__header">
        <span className="marl-panel__badge">{metrics.metrics.algorithm.toUpperCase()}</span>
        <span className="app__muted">{metrics.metrics.agents.length} agents</span>
      </div>

      <div className="marl-panel__metrics">
        <div className="marl-panel__metric">
          <span className="marl-panel__label">Avg Reward</span>
          <span className="marl-panel__value">{avgReward.toFixed(2)}</span>
        </div>
        <div className="marl-panel__metric">
          <span className="marl-panel__label">Avg Epsilon</span>
          <span className="marl-panel__value">{(avgEpsilon * 100).toFixed(1)}%</span>
        </div>
      </div>

      <div className="marl-panel__agents">
        <h3>Agent Performance</h3>
        {metrics.metrics.agents.slice(0, 5).map(agent => (
          <div key={agent.agent_id} className="marl-panel__agent">
            <div className="marl-panel__agent-header">
              <strong>{agent.agent_id}</strong>
              <span className="app__muted">ε {(agent.epsilon * 100).toFixed(1)}%</span>
            </div>
            <div className="marl-panel__agent-stats">
              <span>Reward: {agent.total_reward.toFixed(2)}</span>
              <span>Episodes: {agent.episode_count}</span>
              <span>Memory: {agent.memory_size}</span>
            </div>
          </div>
        ))}
      </div>
    </article>
  );
}
