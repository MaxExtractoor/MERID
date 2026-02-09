import { render, screen, fireEvent } from "@testing-library/react";

// ── Hook mocks ───────────────────────────────────────────────────────

const mockUseFlowRadar = jest.fn();
const mockUseFlowMetrics = jest.fn();
const mockUseFlowSniper = jest.fn();
const mockUseFlowRisk = jest.fn();

jest.mock("../../hooks/useFlowRadar", () => ({
  useFlowRadar: (...args: unknown[]) => mockUseFlowRadar(...args),
  useFlowMetrics: (...args: unknown[]) => mockUseFlowMetrics(...args),
  useFlowSniper: (...args: unknown[]) => mockUseFlowSniper(...args),
  useFlowRisk: (...args: unknown[]) => mockUseFlowRisk(...args),
}));

import FlowRadarView from "../FlowRadarView";

// ── Mock data ────────────────────────────────────────────────────────

const MOCK_TOKENS = [
  {
    token_id: "tok-1",
    symbol: "BONK",
    name: "Bonk",
    chain: "solana",
    contract_address: "abc123",
    liquidity_usd: 2000000,
    price_usd: 0.00002,
    age_hours: 3.5,
    flow_score: 75,
    event_summary: {
      total: 5, whale_buys: 2, whale_sells: 1,
      kol_buys: 1, kol_mentions: 1, lp_adds: 0, lp_removes: 0,
    },
    opinion_summary: {
      total: 3,
      stance_distribution: { spec_long: 2, watch: 1, avoid: 0, spec_short: 0 },
      dominant_stance: "spec_long",
      avg_confidence: 0.75,
    },
    plan_summary: { meme_plans: 1, whale_plans: 1, kol_plans: 0, active_plans: 2 },
  },
  {
    token_id: "tok-2",
    symbol: "WIF",
    name: "dogwifhat",
    chain: "solana",
    contract_address: "def456",
    liquidity_usd: 500000,
    price_usd: 1.5,
    age_hours: 48,
    flow_score: 45,
    event_summary: {
      total: 2, whale_buys: 0, whale_sells: 1,
      kol_buys: 0, kol_mentions: 1, lp_adds: 0, lp_removes: 0,
    },
    opinion_summary: {
      total: 1,
      stance_distribution: { spec_long: 0, watch: 1, avoid: 0, spec_short: 0 },
      dominant_stance: "watch",
      avg_confidence: 0.5,
    },
    plan_summary: { meme_plans: 0, whale_plans: 0, kol_plans: 0, active_plans: 0 },
  },
];

const MOCK_ENTITIES = [
  {
    id: "ent-1", address: "whale-addr-1", chain: "solana",
    entity_type: "whale", label: "Big Whale", tags: ["degen"],
    social_handle: "", follower_count: 0,
    historical_pnl_usd: 250000, hit_rate: 0.68, trade_count: 120, quality: "elite",
  },
];

const MOCK_EVENTS = [
  {
    id: "ev-1", event_type: "large_buy", chain: "solana",
    token_id: "tok-1", token_symbol: "BONK",
    entity_id: "ent-1", entity_address: "whale-addr-1", entity_type: "whale",
    size_usd: 50000, direction: "buy",
    timestamp: Date.now() / 1000 - 300,
    mention_text: "", mention_sentiment: 0,
  },
];

const DEFAULT_RADAR = {
  tokens: MOCK_TOKENS,
  entities: MOCK_ENTITIES,
  recentEvents: MOCK_EVENTS,
  source: "stub",
  tokenCount: 2,
  entityCount: 1,
  eventCount: 1,
  loading: false,
  error: undefined,
  rawResponse: null,
};

const DEFAULT_METRICS = {
  metrics: {
    tokens_tracked: 2, entities_tracked: 5, whale_count: 3, kol_count: 2,
    events_24h: 15, opinions_total: 8,
    plans: { meme: {}, whale: {}, kol: {} },
    sniper: {
      total_fills: 10, success_rate: 0.85, total_volume_usd: 5000,
      avg_slippage_bps: 120, avg_latency_ms: 250, mev_incidents: 1, mev_loss_usd: 3.5,
    },
  },
  loading: false, error: undefined, rawResponse: null,
};

const DEFAULT_SNIPER = {
  status: {
    is_live: false,
    route_health: {
      solana: {
        chain: "solana",
        routes: [
          { dex_router: "jupiter", route_type: "mev_protected", mev_relay: "jito", is_healthy: true, avg_latency_ms: 150, failure_rate: 0 },
          { dex_router: "jupiter", route_type: "standard", mev_relay: "", is_healthy: true, avg_latency_ms: 100, failure_rate: 0 },
        ],
        has_mev_protection: true, healthy_count: 2, total_count: 2,
      },
    },
  },
  fills: [],
  fillCount: 0,
  loading: false,
  error: undefined,
};

const DEFAULT_RISK = {
  risk: {
    config: { max_nav_pct: 0.05, max_domain_notional_usd: 2500 },
    state: {
      domain_exposure_usd: 150, daily_pnl_usd: 25, daily_loss_usd: 0,
      is_throttled: false, is_halted: false, halt_reason: "",
      active_plan_count: 2,
    },
    nav_usd: 50000, effective_max_domain_usd: 2500, utilization_pct: 6.0,
  },
  loading: false, error: undefined,
};

// ── Setup ────────────────────────────────────────────────────────────

beforeEach(() => {
  mockUseFlowRadar.mockReturnValue(DEFAULT_RADAR);
  mockUseFlowMetrics.mockReturnValue(DEFAULT_METRICS);
  mockUseFlowSniper.mockReturnValue(DEFAULT_SNIPER);
  mockUseFlowRisk.mockReturnValue(DEFAULT_RISK);
});

afterEach(() => {
  jest.restoreAllMocks();
});

// ── Tests ────────────────────────────────────────────────────────────

describe("FlowRadarView", () => {
  it("renders the main view with header", () => {
    render(<FlowRadarView />);
    expect(screen.getByText("Flow Radar")).toBeInTheDocument();
    expect(screen.getAllByTestId("flow-token-card").length).toBe(2);
  });

  it("renders token cards with symbols", () => {
    render(<FlowRadarView />);
    expect(screen.getByText("BONK")).toBeInTheDocument();
    expect(screen.getByText("WIF")).toBeInTheDocument();
  });

  it("shows STUB DATA banner when source is stub", () => {
    render(<FlowRadarView />);
    expect(screen.getByTestId("flow-stub-banner")).toBeInTheDocument();
  });

  it("shows stance badges on token cards", () => {
    render(<FlowRadarView />);
    expect(screen.getByText("SPEC LONG")).toBeInTheDocument();
    expect(screen.getByText("WATCH")).toBeInTheDocument();
  });

  it("shows chain filter buttons", () => {
    render(<FlowRadarView />);
    expect(screen.getByText("All Chains")).toBeInTheDocument();
  });

  it("shows tab navigation", () => {
    render(<FlowRadarView />);
    expect(screen.getAllByText(/Radar/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Entities/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Events/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Sniper/i).length).toBeGreaterThan(0);
  });

  it("switches to entities tab and shows entity rows", () => {
    render(<FlowRadarView />);
    const entitiesTab = screen.getByText(/Entities/);
    fireEvent.click(entitiesTab);
    expect(screen.getByTestId("flow-entity-row")).toBeInTheDocument();
    expect(screen.getByText("Big Whale")).toBeInTheDocument();
  });

  it("switches to events tab and shows event rows", () => {
    render(<FlowRadarView />);
    const eventsTab = screen.getByText(/📊 Events/);
    fireEvent.click(eventsTab);
    expect(screen.getByTestId("flow-event-row")).toBeInTheDocument();
  });

  it("switches to sniper tab and shows sniper panel", () => {
    render(<FlowRadarView />);
    const sniperTab = screen.getByText(/Sniper\/MEV/);
    fireEvent.click(sniperTab);
    expect(screen.getByTestId("sniper-panel")).toBeInTheDocument();
  });

  it("renders metrics sidebar", () => {
    render(<FlowRadarView />);
    expect(screen.getByTestId("flow-metrics")).toBeInTheDocument();
  });

  it("expands token card on click to show contract address", () => {
    render(<FlowRadarView />);
    const cards = screen.getAllByTestId("flow-token-card");
    fireEvent.click(cards[0]);
    expect(screen.getByText("abc123")).toBeInTheDocument();
  });

  it("shows empty state when no tokens", () => {
    mockUseFlowRadar.mockReturnValue({
      ...DEFAULT_RADAR,
      tokens: [],
      tokenCount: 0,
    });
    render(<FlowRadarView />);
    expect(screen.getByTestId("flow-empty")).toBeInTheDocument();
  });

  it("shows live counts in header", () => {
    render(<FlowRadarView />);
    expect(screen.getByText(/2\s*tokens/)).toBeInTheDocument();
    expect(screen.getByText(/1\s*entit/)).toBeInTheDocument();
  });
});
