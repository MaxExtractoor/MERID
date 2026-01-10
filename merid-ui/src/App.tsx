import { useCallback, useEffect, useMemo, useState } from "react";
import "./App.css";
import { MARLPanel } from "./components/MARLPanel";
import { PSOPanel } from "./components/PSOPanel";
import { SourceHealthPanel } from "./components/SourceHealthPanel";
import { AgentTrustPanel } from "./components/AgentTrustPanel";
import { ConsensusHistoryPanel } from "./components/ConsensusHistoryPanel";

type OracleFeedSnapshot = {
  name?: string;
  price?: number;
  updated_at?: number;
  source?: string;
};

type DecayMetadata = {
  decayed_confidence?: number;
  original_confidence?: number;
  age_blocks?: number;
};

type SimulationData = {
  oracle_gap?: number;
  oracle_snapshot?: Record<string, OracleFeedSnapshot>;
  feature_flags?: Record<string, unknown>;
  decay?: DecayMetadata;
};

type Block = {
  index: number;
  hash: string;
  timestamp: number;
  miner?: string;
  simulations?: Array<{
    sim_id: string;
    confidence: number;
    decayed_confidence?: number;
    data?: SimulationData;
    outcomes?: Array<{
      outcome: string;
      weight: number;
      expected_value: number;
      final_explanation: string;
    }>;
  }>;
};

type TokenSnapshot = {
  total_supply: number;
  balances: Record<string, number>;
  block_reward?: number;
};

type HeatmapSymbol = {
  symbol: string;
  long: number;
  short: number;
  total: number;
};

type HeatmapSnapshot = {
  generated_at?: number;
  symbols?: HeatmapSymbol[];
  venues?: Array<{ venue: string; volume: number }>;
  arbitrage?: Record<string, unknown> | null;
};

type TickerEntry = {
  venue?: string;
  symbol?: string;
  price?: number;
  index_price?: number;
  basis?: number;
  basis_pct?: number;
  funding_rate?: number;
  open_interest?: number;
  volume_24h?: number;
};

type TickerSnapshot = {
  generated_at?: number;
  tickers?: TickerEntry[];
  funding_extremes?: {
    most_negative?: FundingSnapshot[];
    most_positive?: FundingSnapshot[];
  };
};

type FundingSnapshot = {
  venue?: string;
  symbol?: string;
  funding_rate?: number;
  estimated_apr?: number;
  next_settlement_ms?: number;
};

type AssistSnapshot = {
  timestamp?: number;
  market?: string;
  platforms?: string[];
  selected_platform?: string;
  confidence?: number;
  summary?: string;
  drivers?: Array<{ label?: string; detail?: string; impact?: string }>;
  risk_flags?: Array<{ metric?: string; message?: string }>;
  news?: Array<{ source?: string; headline?: string; summary?: string }>;
  heatmap?: HeatmapSnapshot;
  ticker?: TickerSnapshot;
  oracle_gap?: number;
  arbitrage_gap?: number;
  decay?: Record<string, unknown>;
};

type HoverMetadata = {
  timestamp?: number;
  market?: string;
  platforms?: string[];
  oracle_gap?: number;
  hover_cards?: Array<{ label?: string; value?: unknown; detail?: string }>;
  explainability?: Record<string, unknown>;
  risk_flags?: Array<{ metric?: string; message?: string }>;
  funding_rate?: number;
  hours_to_resolution?: number;
};

type SwarmAgent = {
  instance_id: string;
  parent_id?: string | null;
  role: string;
  charter?: { name?: string; description?: string };
  current_score: number;
  last_active?: number;
  active: boolean;
  lineage?: string[];
};

type SwarmPopulationSnapshot = {
  total: number;
  active: number;
  inactive: number;
  limit: number;
  agents: SwarmAgent[];
};

type LineageEvent = {
  agent_id: string;
  parent_id?: string | null;
  role: string;
  event: string;
  timestamp: number;
  score: number;
  lineage?: string[];
};

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

type SourceHealth = {
  source: string;
  srw: number;
  success_rate: number;
  fallback_rate: number;
  avg_latency_ms: number;
  total_calls: number;
  updated_at: number;
};

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

const API_BASE =
  import.meta.env.VITE_MERID_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000/api/v1";
const API_KEY = import.meta.env.VITE_MERID_DASHBOARD_KEY;

export default function App() {
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [status, setStatus] = useState<"connected" | "connecting" | "error">("connecting");
  const [err, setErr] = useState<string | null>(null);
  const [isMining, setIsMining] = useState(false);

  useEffect(() => {
    const source = new EventSource(`${API_BASE}/blocks`);
    source.onopen = () => {
      setStatus("connected");
      setErr(null);
    };
    source.onerror = () => {
      setStatus("error");
      setErr("Stream disconnected. Retrying…");
    };
    source.onmessage = event => {
      try {
        const block: Block = JSON.parse(event.data);
        setBlocks((prev: Block[]) => {
          const dedupe = prev.filter((existing: Block) => existing.index !== block.index);
          const next = [...dedupe, block];
          return next.sort((a: Block, b: Block) => b.index - a.index).slice(0, 25);
        });
      } catch (error) {
        console.error("Failed to parse block message", error);
      }

function useSwarmAgentsSnapshot() {
  const [snapshot, setSnapshot] = useState<SwarmPopulationSnapshot | null>(null);

  useEffect(() => {
    let mounted = true;
    const fetchSnapshot = async () => {
      try {
        const headers: Record<string, string> = {};
        if (API_KEY) headers["X-API-Key"] = API_KEY;
        const res = await fetch(`${API_BASE}/swarm/agents?limit=40`, { headers });
        if (!res.ok) throw new Error("Failed to fetch swarm agents");
        const data = await res.json();
        if (mounted) setSnapshot(data);
      } catch (error) {
        console.error(error);
      }
    };
    fetchSnapshot();
    const interval = setInterval(fetchSnapshot, 30000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  return snapshot;
}

function useLineageEvents(limit = 50) {
  const [events, setEvents] = useState<LineageEvent[]>([]);

  useEffect(() => {
    let mounted = true;
    const fetchEvents = async () => {
      try {
        const headers: Record<string, string> = {};
        if (API_KEY) headers["X-API-Key"] = API_KEY;
        const res = await fetch(`${API_BASE}/swarm/lineage?limit=${limit}`, { headers });
        if (!res.ok) throw new Error("Failed to fetch lineage events");
        const data = await res.json();
        if (mounted) setEvents(data.events ?? []);
      } catch (error) {
        console.error(error);
      }
    };
    fetchEvents();
    const interval = setInterval(fetchEvents, 15000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [limit]);

  return events;
}

function useMARLMetrics() {
  const [metrics, setMetrics] = useState<MARLMetrics | null>(null);

  useEffect(() => {
    let mounted = true;
    const fetchMetrics = async () => {
      try {
        const headers: Record<string, string> = {};
        if (API_KEY) headers["X-API-Key"] = API_KEY;
        const res = await fetch(`${API_BASE}/marl/metrics`, { headers });
        if (!res.ok) throw new Error("Failed to fetch MARL metrics");
        const data = await res.json();
        if (mounted) setMetrics(data);
      } catch (error) {
        console.error(error);
      }
    };
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 30000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  return metrics;
}

function usePSOMetrics() {
  const [metrics, setMetrics] = useState<PSOMetrics | null>(null);

  useEffect(() => {
    let mounted = true;
    const fetchMetrics = async () => {
      try {
        const headers: Record<string, string> = {};
        if (API_KEY) headers["X-API-Key"] = API_KEY;
        const res = await fetch(`${API_BASE}/pso/metrics`, { headers });
        if (!res.ok) throw new Error("Failed to fetch PSO metrics");
        const data = await res.json();
        if (mounted) setMetrics(data);
      } catch (error) {
        console.error(error);
      }
    };
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 30000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  return metrics;
}

function useSourceHealth() {
  const [sources, setSources] = useState<Record<string, SourceHealth>>({});

  useEffect(() => {
    let mounted = true;
    const fetchSources = async () => {
      try {
        const headers: Record<string, string> = {};
        if (API_KEY) headers["X-API-Key"] = API_KEY;
        const res = await fetch(`${API_BASE}/observability/sources`, { headers });
        if (!res.ok) throw new Error("Failed to fetch source health");
        const data = await res.json();
        if (mounted) setSources(data.sources ?? {});
      } catch (error) {
        console.error(error);
      }
    };
    fetchSources();
    const interval = setInterval(fetchSources, 20000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  return sources;
}

function useAgentTrust() {
  const [agents, setAgents] = useState<Record<string, AgentTrust>>({});

  useEffect(() => {
    let mounted = true;
    const fetchAgents = async () => {
      try {
        const headers: Record<string, string> = {};
        if (API_KEY) headers["X-API-Key"] = API_KEY;
        const res = await fetch(`${API_BASE}/observability/agents/trust`, { headers });
        if (!res.ok) throw new Error("Failed to fetch agent trust");
        const data = await res.json();
        if (mounted) setAgents(data.agents ?? {});
      } catch (error) {
        console.error(error);
      }
    };
    fetchAgents();
    const interval = setInterval(fetchAgents, 20000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  return agents;
}

function useConsensusHistory(limit = 50) {
  const [history, setHistory] = useState<ConsensusHistory[]>([]);

  useEffect(() => {
    let mounted = true;
    const fetchHistory = async () => {
      try {
        const headers: Record<string, string> = {};
        if (API_KEY) headers["X-API-Key"] = API_KEY;
        const res = await fetch(`${API_BASE}/observability/consensus/history?limit=${limit}`, { headers });
        if (!res.ok) throw new Error("Failed to fetch consensus history");
        const data = await res.json();
        if (mounted) setHistory(data.history ?? []);
      } catch (error) {
        console.error(error);
      }
    };
    fetchHistory();
    const interval = setInterval(fetchHistory, 20000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [limit]);

  return history;
}

function useHardeningStatus() {
  const [status, setStatus] = useState<HardeningStatus | null>(null);

  useEffect(() => {
    let mounted = true;
    const fetchStatus = async () => {
      try {
        const headers: Record<string, string> = {};
        if (API_KEY) headers["X-API-Key"] = API_KEY;
        const res = await fetch(`${API_BASE}/observability/hardening/status`, { headers });
        if (!res.ok) throw new Error("Failed to fetch hardening status");
        const data = await res.json();
        if (mounted) setStatus(data);
      } catch (error) {
        console.error(error);
      }
    };
    fetchStatus();
    const interval = setInterval(fetchStatus, 15000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  return status;
}
    };
    return () => source.close();
  }, []);

  const triggerMining = useCallback(async () => {
    setIsMining(true);
    try {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (API_KEY) {
        headers["X-API-Key"] = API_KEY;
      }
      const res = await fetch(`${API_BASE}/mine`, {
        method: "POST",
        headers,
        body: JSON.stringify({ premium: true, miner_id: "dashboard" }),
      });
      if (!res.ok) throw new Error(`Mine request failed (${res.status})`);
      setErr(null);
    } catch (error) {
      setErr((error as Error).message);
    } finally {
      setIsMining(false);
    }
  }, []);

  const latest = blocks[0];
  const tokenSnapshot = useTokenEconomy();
  const latestOracle = useMemo(() => extractOracleContext(latest), [latest]);
  const heatmap = useHeatmapSnapshot();
  const ticker = useTickerSnapshot();
  const assist = useAssistSnapshot();
  const hoverMeta = useHoverMetadata();
  const swarmSnapshot = useSwarmAgentsSnapshot();
  const lineageEvents = useLineageEvents(60);
  const marlMetrics = useMARLMetrics();
  const psoMetrics = usePSOMetrics();
  const sourceHealth = useSourceHealth();
  const agentTrust = useAgentTrust();
  const consensusHistory = useConsensusHistory(50);
  const hardeningStatus = useHardeningStatus();

  const statusBadgeClass = `app__status-badge app__status-badge--${status}`;

  return (
    <main className="app">
      <header className="app__header">
        <div>
          <h1 className="app__title">MERID // Proof-of-Simulation</h1>
          <p className="app__subtitle">Live swarm consensus blocks streamed from FastAPI.</p>
        </div>
        <div className="app__status-group">
          <span className={statusBadgeClass}>{status.toUpperCase()}</span>
          <button className="app__button" onClick={triggerMining} disabled={isMining}>
            {isMining ? "Mining…" : "Initiate Simulation"}
          </button>
        </div>
      </header>

      {err && <p className="app__error">{err}</p>}

      <section className="app__grid">
        <article className="app__card">
          <h2>Latest Block</h2>
          {latest ? (
            <>
              <p>
                #{latest.index} — {latest.hash.slice(0, 10)}…
              </p>
              <p>Miner: {latest.miner ?? "unknown"}</p>
              <div className="app__latest-meta">
                <span>Simulations: {latest.simulations?.length ?? 0}</span>
                <ConfidenceLine block={latest} />
              </div>
              <OutcomeList block={latest} />
              <OraclePanel label="Anchored Oracle Snapshot" info={latestOracle} />
            </>
          ) : (
            <p className="app__muted">No blocks streamed yet.</p>
          )}
        </article>

        <article className="app__card">
          <h2>Token Economy</h2>
          {tokenSnapshot ? (
            <>
              <p>Total Supply: {tokenSnapshot.total_supply.toFixed(2)} MRT</p>
              <pre className="app__pre">{JSON.stringify(tokenSnapshot.balances, null, 2)}</pre>
            </>
          ) : (
            <p className="app__muted">Loading balances…</p>
          )}
        </article>
      </section>

      <section className="app__intel-grid">
        <HeatmapPanel heatmap={heatmap} />
        <TickerPanel ticker={ticker} />
        <AssistPanel assist={assist} />
        <HoverExplainPanel hover={hoverMeta} />
      </section>

      <SwarmLineagePanel snapshot={swarmSnapshot} events={lineageEvents} />

      <section className="app__intel-grid">
        <MARLPanel metrics={marlMetrics} />
        <PSOPanel metrics={psoMetrics} />
      </section>

      <section className="app__intel-grid">
        <SourceHealthPanel sources={sourceHealth} />
        <AgentTrustPanel agents={agentTrust} />
      </section>

      <ConsensusHistoryPanel history={consensusHistory} hardeningStatus={hardeningStatus} />

      <section className="app__card app__card--full">
        <h2>Recent Blocks</h2>
        <div className="app__block-list">
          {blocks.length === 0 ? (
            <p className="app__muted">Awaiting stream data…</p>
          ) : (
            blocks.map(block => (
              <div key={block.index} className="app__block-row">
                <div className="app__block-meta">
                  <strong>#{block.index}</strong>
                  <span>{block.timestamp ? new Date(block.timestamp * 1000).toLocaleString() : "Unknown"}</span>
                </div>
                <div className="app__block-meta">
                  <span>Miner: {block.miner ?? "dashboard"}</span>
                  <span>
                    Confidence: {((block.simulations?.[0]?.confidence ?? 0) * 100).toFixed(1)}%
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
      </section>
    </main>
  );
}

type SwarmTreeNodeProps = {
  node: SwarmTreeNode;
  depth?: number;
};

type SwarmTreeNode = SwarmAgent & { children: SwarmTreeNode[] };

function SwarmLineagePanel({
  snapshot,
  events,
}: {
  snapshot: SwarmPopulationSnapshot | null;
  events: LineageEvent[];
}) {
  const tree = useMemo(() => {
    if (!snapshot?.agents?.length) return [];
    const nodes = new Map<string, SwarmTreeNode>();
    snapshot.agents.forEach(agent => {
      nodes.set(agent.instance_id, { ...agent, children: [] });
    });
    const roots: SwarmTreeNode[] = [];
    nodes.forEach(node => {
      if (node.parent_id && nodes.has(node.parent_id)) {
        nodes.get(node.parent_id)!.children.push(node);
      } else {
        roots.push(node);
      }
    });
    const sortNodes = (list: SwarmTreeNode[]) => {
      list.sort((a, b) => b.current_score - a.current_score);
      list.forEach(child => sortNodes(child.children));
    };
    sortNodes(roots);
    return roots;
  }, [snapshot]);

  return (
    <section className="app__card app__card--full swarm-lineage">
      <div className="swarm-lineage__header">
        <div>
          <h2>Swarm Lineage</h2>
          <p className="app__muted">
            {snapshot
              ? `${snapshot.active} active / ${snapshot.total} total agents (cap ${snapshot.limit})`
              : "Loading swarm snapshot…"}
          </p>
        </div>
        {snapshot && (
          <div className="swarm-lineage__stats">
            <span>Active {snapshot.active}</span>
            <span>Inactive {snapshot.inactive}</span>
          </div>
        )}
      </div>

      {!snapshot ? (
        <p className="app__muted">Fetching swarm state…</p>
      ) : (
        <div className="swarm-lineage__content">
          <div className="swarm-lineage__tree">
            {tree.length === 0 ? (
              <p className="app__muted">No agents instantiated yet.</p>
            ) : (
              tree.map(node => <SwarmTree key={node.instance_id} node={node} />)
            )}
          </div>
          <div className="swarm-lineage__events">
            <h3>Recent Events</h3>
            {events.length === 0 ? (
              <p className="app__muted">Awaiting lineage updates…</p>
            ) : (
              <ul>
                {events
                  .slice()
                  .reverse()
                  .map(event => (
                    <li key={`${event.agent_id}-${event.timestamp}`} className="swarm-lineage__event">
                      <span className={`swarm-lineage__badge swarm-lineage__badge--${event.event}`}>
                        {event.event.toUpperCase()}
                      </span>
                      <div>
                        <strong>{event.role}</strong> · {event.agent_id.slice(0, 8)}
                        <div className="app__muted">
                          {formatRelativeTime(event.timestamp)} · score {(event.score * 100).toFixed(1)}%
                        </div>
                      </div>
                    </li>
                  ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function SwarmTree({ node, depth = 0 }: SwarmTreeNodeProps) {
  const charterName = node.charter?.name ?? node.role;
  return (
    <div className="swarm-tree__node" style={{ marginLeft: depth * 16 }}>
      <div className="swarm-tree__label">
        <span className={`swarm-tree__status ${node.active ? "active" : "inactive"}`} />
        <div>
          <strong>{charterName}</strong>
          <span className="app__muted">
            {node.role} · {(node.current_score * 100).toFixed(1)}% ·{" "}
            {node.active ? "active" : "inactive"}
          </span>
        </div>
      </div>
      {node.charter?.description && <p className="swarm-tree__description">{node.charter.description}</p>}
      {node.children.length > 0 && (
        <div className="swarm-tree__children">
          {node.children.map(child => (
            <SwarmTree key={child.instance_id} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

function OutcomeList({ block }: { block: Block }) {
  if (!block.simulations?.length) return null;
  const outcomes = block.simulations[0].outcomes ?? [];
  const oracle = extractOracleContext(block);
  const decay = extractDecayContext(block);
  const oracleText = oracle.hasData
    ? `Oracle baseline ${(oracle.oracleAverage * 100).toFixed(1)}% → Gap ${formatGap(oracle.gap)}`
    : "Oracle data unavailable";
  return (
    <div className="app__outcomes">
      <h3>Outcomes</h3>
      {outcomes.map(outcome => (
        <div key={outcome.outcome} className="app__outcome">
          <strong>{outcome.outcome}</strong>
          <span>Weight {(outcome.weight * 100).toFixed(1)}%</span>
          <span>EV {(outcome.expected_value * 100).toFixed(2)}%</span>
          <small>
            {outcome.final_explanation}
            <br />
            <em>
              {oracleText} — decayed confidence {decay.display} (orig {decay.originalDisplay})
            </em>
          </small>
        </div>
      ))}
    </div>
  );
}

function useTokenEconomy() {
  const [snapshot, setSnapshot] = useState<TokenSnapshot | null>(null);

  useEffect(() => {
    let mounted = true;
    const fetchSnapshot = async () => {
      try {
        const headers: Record<string, string> = {};
        if (API_KEY) {
          headers["X-API-Key"] = API_KEY;
        }
        const res = await fetch(`${API_BASE}/tokens/balances`, { headers });
        if (!res.ok) throw new Error("Failed to fetch token balances");
        const data = await res.json();
        if (mounted) setSnapshot(data);
      } catch (error) {
        console.error(error);
      }
    };
    fetchSnapshot();
    const interval = setInterval(fetchSnapshot, 15000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  return snapshot;
}

function useHeatmapSnapshot() {
  const [snapshot, setSnapshot] = useState<HeatmapSnapshot | null>(null);

  useEffect(() => {
    let mounted = true;
    const fetchHeatmap = async () => {
      try {
        const headers: Record<string, string> = {};
        if (API_KEY) headers["X-API-Key"] = API_KEY;
        const res = await fetch(`${API_BASE}/heatmap?limit=12`, { headers });
        if (!res.ok) throw new Error("Failed to fetch heatmap feed");
        const data = await res.json();
        if (mounted) setSnapshot(data);
      } catch (error) {
        console.error(error);
      }
    };
    fetchHeatmap();
    const interval = setInterval(fetchHeatmap, 10000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  return snapshot;
}

function useTickerSnapshot() {
  const [snapshot, setSnapshot] = useState<TickerSnapshot | null>(null);

  useEffect(() => {
    let mounted = true;
    const fetchTicker = async () => {
      try {
        const headers: Record<string, string> = {};
        if (API_KEY) headers["X-API-Key"] = API_KEY;
        const res = await fetch(`${API_BASE}/ticker?limit=15`, { headers });
        if (!res.ok) throw new Error("Failed to fetch ticker feed");
        const data = await res.json();
        if (mounted) setSnapshot(data);
      } catch (error) {
        console.error(error);
      }
    };
    fetchTicker();
    const interval = setInterval(fetchTicker, 8500);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  return snapshot;
}

function useAssistSnapshot() {
  const [snapshot, setSnapshot] = useState<AssistSnapshot | null>(null);

  useEffect(() => {
    let mounted = true;
    const fetchAssist = async () => {
      try {
        const headers: Record<string, string> = {};
        if (API_KEY) headers["X-API-Key"] = API_KEY;
        const res = await fetch(`${API_BASE}/assist`, { headers });
        if (!res.ok) throw new Error("Failed to fetch assist feed");
        const data = await res.json();
        if (mounted) setSnapshot(data);
      } catch (error) {
        console.error(error);
      }
    };
    fetchAssist();
    const interval = setInterval(fetchAssist, 7000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  return snapshot;
}

function useHoverMetadata() {
  const [snapshot, setSnapshot] = useState<HoverMetadata | null>(null);

  useEffect(() => {
    let mounted = true;
    const fetchHover = async () => {
      try {
        const headers: Record<string, string> = {};
        if (API_KEY) headers["X-API-Key"] = API_KEY;
        const res = await fetch(`${API_BASE}/hover-metadata`, { headers });
        if (!res.ok) throw new Error("Failed to fetch hover metadata feed");
        const data = await res.json();
        if (mounted) setSnapshot(data);
      } catch (error) {
        console.error(error);
      }
    };
    fetchHover();
    const interval = setInterval(fetchHover, 6500);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  return snapshot;
}

function ConfidenceLine({ block }: { block: Block }) {
  const oracle = extractOracleContext(block);
  const decay = extractDecayContext(block);
  return (
    <div className="app__confidence-line" title={oracle.tooltip}>
      <span>
        Decayed Confidence: {decay.display}
        <span className="app__confidence-sub">
          (orig {decay.originalDisplay}
          {decay.ageBlocks !== null ? `, age ${decay.ageBlocks} blocks` : ""})
        </span>
      </span>
      <OracleBadge info={oracle} />
    </div>
  );
}

type OracleContext = {
  gap: number | null;
  hasData: boolean;
  snapshot: Record<string, OracleFeedSnapshot> | null;
  tooltip: string;
  oracleAverage: number;
};

function extractOracleContext(block?: Block): OracleContext {
  const sim = block?.simulations?.[0];
  const data = sim?.data;
  const snapshot = (data?.oracle_snapshot ?? null) as Record<string, OracleFeedSnapshot> | null;
  const gap = typeof data?.oracle_gap === "number" ? data?.oracle_gap : null;
  const feeds = Object.entries(snapshot ?? {});
  const oracleAverage =
    feeds.length > 0
      ? feeds.reduce((sum, [, feed]) => sum + feedProbability(feed), 0) / feeds.length
      : 0;
  const tooltip =
    feeds.length === 0
      ? "Oracle data unavailable"
      : feeds
          .map(([key, feed]) => `${feed.name ?? key}: ${feed.price ? `$${feed.price.toFixed(2)}` : "n/a"}`)
          .join("\n");
  return {
    gap,
    hasData: feeds.length > 0,
    snapshot,
    tooltip,
    oracleAverage,
  };
}

type DecayContext = {
  decayed: number;
  original: number;
  display: string;
  originalDisplay: string;
  hasDecay: boolean;
  ageBlocks: number | null;
};

function extractDecayContext(block?: Block): DecayContext {
  const sim = block?.simulations?.[0];
  const raw = (sim?.confidence ?? 0) * 100;
  const dataDecay = sim?.data?.decay;
  const decayedValue =
    ((sim?.decayed_confidence ??
      (typeof dataDecay?.decayed_confidence === "number" ? dataDecay.decayed_confidence : sim?.confidence ?? 0)) *
      100) || 0;
  const age =
    typeof dataDecay?.age_blocks === "number" && Number.isFinite(dataDecay.age_blocks)
      ? Math.max(0, Math.trunc(dataDecay.age_blocks))
      : null;
  return {
    decayed: decayedValue,
    original: raw,
    display: `${decayedValue.toFixed(1)}%`,
    originalDisplay: `${raw.toFixed(1)}%`,
    hasDecay: typeof dataDecay?.decayed_confidence === "number",
    ageBlocks: age,
  };
}

function OracleBadge({ info }: { info: OracleContext }) {
  const { gap, hasData } = info;
  let level: "aligned" | "warning" | "risk" | "na" = "na";
  if (hasData && typeof gap === "number") {
    const gapPct = Math.abs(gap) * 100;
    if (gapPct < 5) level = "aligned";
    else if (gapPct < 15) level = "warning";
    else level = "risk";
  } else if (!hasData) {
    level = "na";
  }

  const labelMap: Record<typeof level, string> = {
    aligned: "Oracle Verified",
    warning: "Oracle Drift",
    risk: "Oracle Divergent",
    na: "Oracle N/A",
  };

  const detail =
    typeof gap === "number" ? `Gap ${formatGap(gap)} (${level.toUpperCase()})` : "Awaiting oracle data";

  return (
    <span className={`app__oracle-badge app__oracle-badge--${level}`} title={detail}>
      {labelMap[level]}
    </span>
  );
}

function OraclePanel({ label, info }: { label: string; info: OracleContext }) {
  const feeds = Object.entries(info.snapshot ?? {});
  if (!info.hasData) {
    return (
      <div className="app__oracle-card">
        <h3>{label}</h3>
        <p className="app__muted">Oracle data unavailable (pre-anchoring block).</p>
      </div>
    );
  }

  return (
    <div className="app__oracle-card">
      <h3>{label}</h3>
      <div className="app__oracle-gap">
        Reality Gap: <strong>{formatGap(info.gap)}</strong>
      </div>
      <div className="app__oracle-feeds">
        {feeds.map(([key, feed]) => (
          <div key={key} className="app__oracle-feed">
            <span>{feed.name ?? key}</span>
            <span>{feed.price ? `$${feed.price.toFixed(2)}` : "n/a"}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function HeatmapPanel({ heatmap }: { heatmap: HeatmapSnapshot | null }) {
  return (
    <article className="app__card app__intel-card">
      <div className="app__card-header">
        <h2>Liquidation Heatmap</h2>
        {heatmap?.generated_at && (
          <span className="app__timestamp">
            {new Date(heatmap.generated_at * 1000).toLocaleTimeString()}
          </span>
        )}
      </div>
      {!heatmap ? (
        <p className="app__muted">Loading heatmap snapshot…</p>
      ) : (
        <>
          <div className="app__heatmap-grid">
            {(heatmap.symbols ?? []).slice(0, 6).map(symbol => (
              <div key={symbol.symbol} className="app__heatmap-row">
                <strong>{symbol.symbol}</strong>
                <span className="app__heatmap-bar">
                  <span style={{ width: `${Math.min(100, (symbol.long / symbol.total) * 100)}%` }}>
                    Long {formatMillions(symbol.long)}
                  </span>
                </span>
                <span className="app__heatmap-bar app__heatmap-bar--short">
                  <span style={{ width: `${Math.min(100, (symbol.short / symbol.total) * 100)}%` }}>
                    Short {formatMillions(symbol.short)}
                  </span>
                </span>
                <span className="app__muted">{formatMillions(symbol.total)} total</span>
              </div>
            ))}
          </div>
          {heatmap.arbitrage && (
            <p className="app__muted">
              Arbitrage signal detected across venues.{" "}
              <em>Spread {(heatmap.arbitrage as Record<string, unknown>)?.spread ?? "—"}</em>
            </p>
          )}
        </>
      )}
    </article>
  );
}

function TickerPanel({ ticker }: { ticker: TickerSnapshot | null }) {
  const entries = ticker?.tickers ?? [];
  return (
    <article className="app__card app__intel-card">
      <div className="app__card-header">
        <h2>Perp Ticker</h2>
        {ticker?.generated_at && (
          <span className="app__timestamp">
            {new Date(ticker.generated_at * 1000).toLocaleTimeString()}
          </span>
        )}
      </div>
      {entries.length === 0 ? (
        <p className="app__muted">Fetching perp markets…</p>
      ) : (
        <div className="app__ticker-list">
          {entries.slice(0, 8).map(entry => (
            <div key={`${entry.venue}-${entry.symbol}`} className="app__ticker-row">
              <div>
                <strong>{entry.symbol}</strong>
                <span className="app__muted">{entry.venue}</span>
              </div>
              <div>
                <span>${entry.price?.toFixed(2)}</span>
                <span className={entry.basis && entry.basis >= 0 ? "is-positive" : "is-negative"}>
                  {entry.basis ? entry.basis.toFixed(2) : "0.00"} ({((entry.basis_pct ?? 0) * 100).toFixed(2)}%)
                </span>
              </div>
              <div className="app__muted">
                Funding {(entry.funding_rate ?? 0).toFixed(4)} | OI {formatMillions(entry.open_interest ?? 0)}
              </div>
            </div>
          ))}
        </div>
      )}
      {ticker?.funding_extremes && (
        <div className="app__funding-extremes">
          <FundingList title="Highest Funding" list={ticker.funding_extremes.most_positive ?? []} />
          <FundingList title="Most Negative" list={ticker.funding_extremes.most_negative ?? []} />
        </div>
      )}
    </article>
  );
}

function FundingList({ title, list }: { title: string; list: FundingSnapshot[] }) {
  if (!list.length) return null;
  return (
    <div>
      <h4>{title}</h4>
      {list.map(item => (
        <div key={`${item.venue}-${item.symbol}`} className="app__funding-row">
          <span>
            {item.symbol} — {item.venue}
          </span>
          <strong>{((item.funding_rate ?? 0) * 100).toFixed(3)}%</strong>
        </div>
      ))}
    </div>
  );
}

function AssistPanel({ assist }: { assist: AssistSnapshot | null }) {
  if (!assist) {
    return (
      <article className="app__card app__intel-card">
        <h2>AI Assist Context</h2>
        <p className="app__muted">Awaiting latest simulation payload…</p>
      </article>
    );
  }

  return (
    <article className="app__card app__intel-card">
      <div className="app__card-header">
        <h2>AI Assist Context</h2>
        {assist.timestamp && <span className="app__timestamp">{new Date(assist.timestamp * 1000).toLocaleTimeString()}</span>}
      </div>
      <p className="app__muted">
        Market: <strong>{assist.market ?? "unknown"}</strong> · Platform: {assist.selected_platform ?? "n/a"}
      </p>
      <p>
        <strong>Summary</strong>
        <br />
        {assist.summary ?? "No summary provided"}
      </p>
      <div className="app__drivers">
        {(assist.drivers ?? []).map(driver => (
          <div key={driver.label} className="app__driver">
            <strong>{driver.label}</strong>
            <p>{driver.detail}</p>
            {driver.impact && <small>{driver.impact}</small>}
          </div>
        ))}
      </div>
      <div className="app__risk-flags">
        {(assist.risk_flags ?? []).map(flag => (
          <span key={flag.metric} className="app__risk-flag">
            {flag.metric}: {flag.message}
          </span>
        ))}
      </div>
      <div className="app__assist-news">
        <h4>News Highlights</h4>
        {(assist.news ?? []).map((item, idx) => (
          <div key={`${item.source}-${idx}`} className="app__news-row">
            <strong>{item.source}</strong>
            <span>{item.headline}</span>
          </div>
        ))}
      </div>
    </article>
  );
}

function HoverExplainPanel({ hover }: { hover: HoverMetadata | null }) {
  if (!hover) {
    return (
      <article className="app__card app__intel-card">
        <h2>Explainability Hover Metadata</h2>
        <p className="app__muted">Awaiting hover metadata…</p>
      </article>
    );
  }

  return (
    <article className="app__card app__intel-card">
      <div className="app__card-header">
        <h2>Explainability Hover Metadata</h2>
        {hover.timestamp && <span className="app__timestamp">{new Date(hover.timestamp * 1000).toLocaleTimeString()}</span>}
      </div>
      <p className="app__muted">
        Market: <strong>{hover.market ?? "unknown"}</strong> · Oracle Gap {formatGap(hover.oracle_gap ?? null)}
      </p>
      <div className="app__hover-grid">
        {(hover.hover_cards ?? []).map(card => (
          <div key={card.label} className="app__hover-card">
            <strong>{card.label}</strong>
            {typeof card.value === "object" ? (
              <pre className="app__pre">{JSON.stringify(card.value, null, 2)}</pre>
            ) : (
              <span>{String(card.value ?? "n/a")}</span>
            )}
            <small>{card.detail ?? "Supplemental detail"}</small>
          </div>
        ))}
      </div>
      <div className="app__risk-flags">
        {(hover.risk_flags ?? []).map(flag => (
          <span key={flag.metric} className="app__risk-flag">
            {flag.metric}: {flag.message}
          </span>
        ))}
      </div>
    </article>
  );
}

function formatGap(gap?: number | null): string {
  if (gap === null || Number.isNaN(gap)) return "N/A";
  return `${(gap / 60).toFixed(1)}h`;
}

function formatMillions(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toFixed(0);
}

function formatRelativeTime(timestamp?: number): string {
  if (!timestamp) return "unknown";
  const now = Date.now();
  const deltaSeconds = Math.max(0, (now - timestamp * 1000) / 1000);
  if (deltaSeconds < 60) return `${Math.floor(deltaSeconds)}s ago`;
  if (deltaSeconds < 3600) return `${Math.floor(deltaSeconds / 60)}m ago`;
  return `${Math.floor(deltaSeconds / 3600)}h ago`;
}

function feedProbability(feed: OracleFeedSnapshot): number {
  const price = typeof feed.price === "number" ? feed.price : 0;
  const scale = typeof (feed as any).scale_hint === "number" ? (feed as any).scale_hint : price || 1;
  if (!scale) return 0;
  const ratio = price / scale;
  return Math.max(0, Math.min(1, ratio));
}

