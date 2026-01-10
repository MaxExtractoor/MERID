type ConsensusHistory = {
  market: string;
  timestamp: number;
  consensus_score: number;
  confidence: number;
  approved: boolean;
  poisoning_detected: boolean;
  trust_updates_allowed: boolean;
  degraded_mode: boolean;
  temporal_violations: number;
  collusion_detected: boolean;
  shadow_divergence: boolean;
};

type HardeningStatus = {
  trust_updates_frozen: boolean;
  poisoning_alert_count: number;
  temporal_profiles_tracked: number;
  suspect_clusters: string[][];
  shadow_divergence_suspected: boolean;
};

export function ConsensusHistoryPanel({
  history,
  hardeningStatus,
}: {
  history: ConsensusHistory[];
  hardeningStatus: HardeningStatus | null;
}) {
  const recentPoisoning = history.filter(h => h.poisoning_detected).length;
  const avgConsensus = history.length > 0
    ? history.reduce((sum, h) => sum + h.consensus_score, 0) / history.length
    : 0;
  const approvalRate = history.length > 0
    ? history.filter(h => h.approved).length / history.length
    : 0;

  return (
    <section className="app__card app__card--full consensus-history">
      <div className="consensus-history__header">
        <div>
          <h2>Consensus History & Hardening</h2>
          <p className="app__muted">
            {history.length} recent consensus events · {recentPoisoning} poisoning alerts
          </p>
        </div>
        {hardeningStatus && (
          <div className="consensus-history__hardening-badge">
            {hardeningStatus.trust_updates_frozen ? (
              <span className="consensus-history__badge consensus-history__badge--frozen">
                TRUST FROZEN
              </span>
            ) : (
              <span className="consensus-history__badge consensus-history__badge--active">
                TRUST ACTIVE
              </span>
            )}
          </div>
        )}
      </div>

      <div className="consensus-history__summary">
        <div className="consensus-history__metric">
          <span className="consensus-history__label">Avg Consensus</span>
          <span className="consensus-history__value">{avgConsensus.toFixed(3)}</span>
        </div>
        <div className="consensus-history__metric">
          <span className="consensus-history__label">Approval Rate</span>
          <span className="consensus-history__value">{(approvalRate * 100).toFixed(1)}%</span>
        </div>
        <div className="consensus-history__metric">
          <span className="consensus-history__label">Poisoning Alerts</span>
          <span className="consensus-history__value">{hardeningStatus?.poisoning_alert_count ?? 0}</span>
        </div>
        <div className="consensus-history__metric">
          <span className="consensus-history__label">Temporal Profiles</span>
          <span className="consensus-history__value">{hardeningStatus?.temporal_profiles_tracked ?? 0}</span>
        </div>
      </div>

      {hardeningStatus && hardeningStatus.suspect_clusters.length > 0 && (
        <div className="consensus-history__alert">
          <strong>⚠️ Collusion Detected</strong>
          <p>
            {hardeningStatus.suspect_clusters.length} suspect cluster(s) identified.
            Trust updates may be restricted.
          </p>
        </div>
      )}

      <div className="consensus-history__list">
        <h3>Recent Events</h3>
        {history.length === 0 ? (
          <p className="app__muted">No consensus history available</p>
        ) : (
          <div className="consensus-history__events">
            {history.slice(0, 20).map((event, idx) => {
              const statusClass = event.poisoning_detected
                ? "poisoned"
                : event.degraded_mode
                ? "degraded"
                : event.approved
                ? "approved"
                : "rejected";

              return (
                <div key={idx} className={`consensus-history__event consensus-history__event--${statusClass}`}>
                  <div className="consensus-history__event-header">
                    <strong>{event.market}</strong>
                    <span className={`consensus-history__event-badge consensus-history__event-badge--${statusClass}`}>
                      {event.poisoning_detected ? "POISONED" : event.approved ? "APPROVED" : "REJECTED"}
                    </span>
                  </div>
                  <div className="consensus-history__event-stats">
                    <span>Score: {event.consensus_score.toFixed(3)}</span>
                    <span>Confidence: {(event.confidence * 100).toFixed(1)}%</span>
                    <span>{formatRelativeTime(event.timestamp)}</span>
                  </div>
                  {event.poisoning_detected && (
                    <div className="consensus-history__event-details">
                      <span className="consensus-history__warning">
                        Temporal: {event.temporal_violations} · 
                        Collusion: {event.collusion_detected ? "Yes" : "No"} · 
                        Shadow Div: {event.shadow_divergence ? "Yes" : "No"}
                      </span>
                    </div>
                  )}
                  {event.degraded_mode && !event.poisoning_detected && (
                    <div className="consensus-history__event-details">
                      <span className="app__muted">Degraded mode: Low source diversity</span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
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
