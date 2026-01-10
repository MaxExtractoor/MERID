import { useMemo } from "react";

type PSOMetrics = {
  status: string;
  metrics: {
    iteration: number;
    global_best_fitness: number;
    global_best_position: number[] | null;
    fitness_history: number[];
    diversity_history: number[];
    num_particles: number;
    particles: Array<{
      position: number[];
      fitness: number;
      best_fitness: number;
    }>;
  };
};

export function PSOPanel({ metrics }: { metrics: PSOMetrics | null }) {
  const convergenceRate = useMemo(() => {
    if (!metrics?.metrics?.fitness_history?.length) return 0;
    const history = metrics.metrics.fitness_history;
    if (history.length < 10) return 0;
    const recent = history.slice(-10);
    const improvement = recent[recent.length - 1] - recent[0];
    return improvement;
  }, [metrics]);

  const avgDiversity = useMemo(() => {
    if (!metrics?.metrics?.diversity_history?.length) return 0;
    const recent = metrics.metrics.diversity_history.slice(-10);
    return recent.reduce((sum, d) => sum + d, 0) / recent.length;
  }, [metrics]);

  if (!metrics || metrics.status === "not_initialized") {
    return (
      <article className="app__card">
        <h2>PSO Optimization</h2>
        <p className="app__muted">PSO optimizer not initialized</p>
      </article>
    );
  }

  const progress = metrics.metrics.iteration / 100;

  return (
    <article className="app__card">
      <h2>PSO Optimization</h2>
      <div className="pso-panel__header">
        <span className="pso-panel__badge">
          Iteration {metrics.metrics.iteration}
        </span>
        <span className="app__muted">{metrics.metrics.num_particles} particles</span>
      </div>

      <div className="pso-panel__progress">
        <div className="pso-panel__progress-bar">
          <div
            className="pso-panel__progress-fill"
            data-progress={progress}
          />
        </div>
        <span className="app__muted">{(progress * 100).toFixed(0)}% complete</span>
      </div>

      <div className="pso-panel__metrics">
        <div className="pso-panel__metric">
          <span className="pso-panel__label">Best Fitness</span>
          <span className="pso-panel__value">
            {metrics.metrics.global_best_fitness.toFixed(4)}
          </span>
        </div>
        <div className="pso-panel__metric">
          <span className="pso-panel__label">Convergence</span>
          <span className="pso-panel__value">
            {convergenceRate >= 0 ? "+" : ""}
            {convergenceRate.toFixed(4)}
          </span>
        </div>
        <div className="pso-panel__metric">
          <span className="pso-panel__label">Diversity</span>
          <span className="pso-panel__value">{avgDiversity.toFixed(3)}</span>
        </div>
      </div>

      {metrics.metrics.global_best_position && (
        <div className="pso-panel__position">
          <h3>Best Position</h3>
          <div className="pso-panel__position-grid">
            {metrics.metrics.global_best_position.slice(0, 6).map((val, idx) => (
              <div key={idx} className="pso-panel__position-item">
                <span className="app__muted">P{idx}</span>
                <span>{val.toFixed(4)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {metrics.metrics.particles?.length > 0 && (
        <div className="pso-panel__particles">
          <h3>Top Particles</h3>
          {metrics.metrics.particles.slice(0, 3).map((particle, idx) => (
            <div key={idx} className="pso-panel__particle">
              <div className="pso-panel__particle-header">
                <strong>Particle {idx + 1}</strong>
                <span className="app__muted">
                  Fitness: {particle.fitness.toFixed(4)}
                </span>
              </div>
              <div className="pso-panel__particle-best">
                <span className="app__muted">
                  Best: {particle.best_fitness.toFixed(4)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </article>
  );
}
