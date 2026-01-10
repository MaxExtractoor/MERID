type SourceHealth = {
  source: string;
  srw: number;
  success_rate: number;
  fallback_rate: number;
  avg_latency_ms: number;
  total_calls: number;
  updated_at: number;
};

export function SourceHealthPanel({ sources }: { sources: Record<string, SourceHealth> }) {
  const sourceList = Object.values(sources);
  const sortedSources = sourceList.sort((a, b) => b.srw - a.srw);

  if (sourceList.length === 0) {
    return (
      <article className="app__card">
        <h2>Source Health</h2>
        <p className="app__muted">No source health data available</p>
      </article>
    );
  }

  const avgSRW = sourceList.reduce((sum, s) => sum + s.srw, 0) / sourceList.length;
  const avgSuccessRate = sourceList.reduce((sum, s) => sum + s.success_rate, 0) / sourceList.length;

  return (
    <article className="app__card">
      <h2>Source Health</h2>
      <div className="source-health__summary">
        <div className="source-health__metric">
          <span className="source-health__label">Avg SRW</span>
          <span className="source-health__value">{avgSRW.toFixed(3)}</span>
        </div>
        <div className="source-health__metric">
          <span className="source-health__label">Avg Success</span>
          <span className="source-health__value">{(avgSuccessRate * 100).toFixed(1)}%</span>
        </div>
        <div className="source-health__metric">
          <span className="source-health__label">Sources</span>
          <span className="source-health__value">{sourceList.length}</span>
        </div>
      </div>

      <div className="source-health__list">
        {sortedSources.slice(0, 8).map(source => {
          const srwClass = source.srw >= 0.8 ? "high" : source.srw >= 0.6 ? "medium" : "low";
          const statusClass = `source-health__status source-health__status--${srwClass}`;

          return (
            <div key={source.source} className="source-health__item">
              <div className="source-health__item-header">
                <strong>{source.source}</strong>
                <span className={statusClass}>SRW {source.srw.toFixed(3)}</span>
              </div>
              <div className="source-health__item-stats">
                <span>Success: {(source.success_rate * 100).toFixed(1)}%</span>
                <span>Fallback: {(source.fallback_rate * 100).toFixed(1)}%</span>
                <span>Latency: {source.avg_latency_ms.toFixed(0)}ms</span>
              </div>
              <div className="source-health__item-meta">
                <span className="app__muted">
                  {source.total_calls} calls · Updated {formatRelativeTime(source.updated_at)}
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
