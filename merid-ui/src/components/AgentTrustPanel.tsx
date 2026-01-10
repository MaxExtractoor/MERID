type AgentTrust = {
  agent_id: string;
  trust: number;
  last_active_at: number;
  total_votes: number;
  correct_votes: number;
  accuracy: number;
  avg_srw_used: number;
  trust_max: number;
};

export function AgentTrustPanel({ agents }: { agents: Record<string, AgentTrust> }) {
  const agentList = Object.values(agents);
  const sortedAgents = agentList.sort((a, b) => b.trust - a.trust);

  if (agentList.length === 0) {
    return (
      <article className="app__card">
        <h2>Agent Trust</h2>
        <p className="app__muted">No agent trust data available</p>
      </article>
    );
  }

  const avgTrust = agentList.reduce((sum, a) => sum + a.trust, 0) / agentList.length;
  const avgAccuracy = agentList.reduce((sum, a) => sum + a.accuracy, 0) / agentList.length;

  return (
    <article className="app__card">
      <h2>Agent Trust</h2>
      <div className="agent-trust__summary">
        <div className="agent-trust__metric">
          <span className="agent-trust__label">Avg Trust</span>
          <span className="agent-trust__value">{avgTrust.toFixed(3)}</span>
        </div>
        <div className="agent-trust__metric">
          <span className="agent-trust__label">Avg Accuracy</span>
          <span className="agent-trust__value">{(avgAccuracy * 100).toFixed(1)}%</span>
        </div>
        <div className="agent-trust__metric">
          <span className="agent-trust__label">Agents</span>
          <span className="agent-trust__value">{agentList.length}</span>
        </div>
      </div>

      <div className="agent-trust__list">
        {sortedAgents.slice(0, 8).map(agent => {
          const trustClass = agent.trust >= 1.5 ? "high" : agent.trust >= 1.0 ? "medium" : "low";
          const statusClass = `agent-trust__status agent-trust__status--${trustClass}`;
          const capped = agent.trust >= agent.trust_max;

          return (
            <div key={agent.agent_id} className="agent-trust__item">
              <div className="agent-trust__item-header">
                <strong>{agent.agent_id.slice(0, 12)}</strong>
                <span className={statusClass}>
                  Trust {agent.trust.toFixed(3)}
                  {capped && " (capped)"}
                </span>
              </div>
              <div className="agent-trust__item-stats">
                <span>Accuracy: {(agent.accuracy * 100).toFixed(1)}%</span>
                <span>Votes: {agent.correct_votes}/{agent.total_votes}</span>
                <span>Avg SRW: {agent.avg_srw_used.toFixed(3)}</span>
              </div>
              <div className="agent-trust__item-meta">
                <span className="app__muted">
                  Last active {formatRelativeTime(agent.last_active_at)}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </article>
  );
}

function formatRelativeTime(timestamp: number): string {
  const now = Date.now() / 1000;
  const diff = now - timestamp;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}
