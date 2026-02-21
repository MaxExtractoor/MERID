import { render, screen, fireEvent } from "@testing-library/react";

// Mock the hooks before importing the component
const mockUsePredictionConsensus = jest.fn();
const mockUsePredictionMetrics = jest.fn();

jest.mock("../../hooks/usePredictionConsensus", () => ({
  usePredictionConsensus: (...args: unknown[]) => mockUsePredictionConsensus(...args),
  usePredictionMetrics: (...args: unknown[]) => mockUsePredictionMetrics(...args),
}));

jest.mock("../../utils/stub", () => ({
  isStub: (raw: unknown) => !!(raw && typeof raw === "object" && (raw as Record<string, unknown>)._stub),
}));

import PredictionConsensusView from "../PredictionConsensusView";

const SAMPLE_SYMBOLS = [
  {
    symbol: "PRED:KALSHI:FED-25MAR-T4.50:YES",
    venue: "kalshi",
    event_id: "FED-25MAR",
    ticker: "FED-25MAR-T4.50",
    outcome: "YES",
    category: "macro",
    title: "Fed holds rates at 4.50%",
    expiry: "2025-03-19T18:00:00+00:00",
    swarm_prob: 0.72,
    market_prob: 0.65,
    edge: 0.07,
    stance: "weak_yes" as const,
    confidence: 0.68,
    supporting_agents: 4,
    opposing_agents: 1,
    active_plans: { proposed: 1, approved: 0, executing: 0 },
    opinion_count: 5,
    volume: 12500,
  },
  {
    symbol: "PRED:KALSHI:BTC-25MAR-100K:YES",
    venue: "kalshi",
    event_id: "BTC-25MAR",
    ticker: "BTC-25MAR-100K",
    outcome: "YES",
    category: "crypto",
    title: "Bitcoin above $100K",
    expiry: "2025-03-31T23:59:59+00:00",
    swarm_prob: 0.45,
    market_prob: 0.52,
    edge: -0.07,
    stance: "weak_no" as const,
    confidence: 0.55,
    supporting_agents: 2,
    opposing_agents: 3,
    active_plans: { proposed: 0, approved: 1, executing: 0 },
    opinion_count: 5,
    volume: 8200,
  },
];

const SAMPLE_METRICS = {
  brier: {
    swarm_brier: 0.18,
    market_brier: 0.22,
    swarm_vs_market: "better",
    agent_ranking: [
      { agent_id: "macro-analyst", brier: 0.12 },
      { agent_id: "quant-model", brier: 0.20 },
    ],
    resolved_count: 15,
    total_pnl_usd: 350.0,
    calibration: [],
  },
  universe: { total_instruments: 50, active_instruments: 35 },
  plans: { proposed: 5, approved: 3, executing: 2, closed: 10 },
};

function setupMocks({
  symbols = SAMPLE_SYMBOLS,
  metrics = SAMPLE_METRICS,
  loading = false,
  stubbed = false,
}: {
  symbols?: typeof SAMPLE_SYMBOLS;
  metrics?: typeof SAMPLE_METRICS | null;
  loading?: boolean;
  stubbed?: boolean;
} = {}) {
  const bySymbol: Record<string, (typeof SAMPLE_SYMBOLS)[number]> = {};
  for (const s of symbols) bySymbol[s.symbol] = s;

  mockUsePredictionConsensus.mockReturnValue({
    symbols,
    bySymbol,
    rawResponse: stubbed ? { _stub: true } : {},
    loading,
    error: undefined,
    refetch: jest.fn(),
  });

  mockUsePredictionMetrics.mockReturnValue({
    metrics,
    rawResponse: stubbed ? { _stub: true } : {},
    loading: false,
    error: undefined,
  });
}

describe("PredictionConsensusView", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders the view with market cards", () => {
    setupMocks();
    render(<PredictionConsensusView />);
    expect(screen.getByTestId("prediction-consensus-view")).toBeInTheDocument();
    expect(screen.getAllByTestId("prediction-market-card")).toHaveLength(2);
  });

  it("shows stub banner when data is stubbed", () => {
    setupMocks({ stubbed: true });
    render(<PredictionConsensusView />);
    expect(screen.getByTestId("prediction-stub-banner")).toBeInTheDocument();
  });

  it("does not show stub banner for live data", () => {
    setupMocks({ stubbed: false });
    render(<PredictionConsensusView />);
    expect(screen.queryByTestId("prediction-stub-banner")).not.toBeInTheDocument();
  });

  it("shows loading state when no data", () => {
    setupMocks({ symbols: [], loading: true });
    render(<PredictionConsensusView />);
    expect(screen.getByText(/Loading prediction markets/)).toBeInTheDocument();
  });

  it("shows empty state when no markets match filter", () => {
    setupMocks({ symbols: [] });
    render(<PredictionConsensusView />);
    expect(screen.getByTestId("prediction-empty")).toBeInTheDocument();
  });

  it("filters by category", () => {
    setupMocks();
    render(<PredictionConsensusView />);
    // Click "Crypto" filter
    fireEvent.click(screen.getByText("Crypto"));
    // Only crypto card should remain
    const cards = screen.getAllByTestId("prediction-market-card");
    expect(cards).toHaveLength(1);
  });

  it("displays market title and ticker in cards", () => {
    setupMocks();
    render(<PredictionConsensusView />);
    expect(screen.getByText("Fed holds rates at 4.50%")).toBeInTheDocument();
    expect(screen.getByText("Bitcoin above $100K")).toBeInTheDocument();
  });

  it("displays Brier sidebar with agent leaderboard", () => {
    setupMocks();
    render(<PredictionConsensusView />);
    expect(screen.getByText("Brier Scores")).toBeInTheDocument();
    expect(screen.getByText("macro-analyst")).toBeInTheDocument();
    expect(screen.getByText("quant-model")).toBeInTheDocument();
  });

  it("shows header metrics when available", () => {
    setupMocks();
    render(<PredictionConsensusView />);
    expect(screen.getByText("Active Markets")).toBeInTheDocument();
    // "35" may appear in multiple places (header + sidebar), just check at least one exists
    expect(screen.getAllByText("35").length).toBeGreaterThanOrEqual(1);
  });

  it("expands card on click to show detail", () => {
    setupMocks();
    render(<PredictionConsensusView />);
    const cards = screen.getAllByTestId("prediction-market-card");
    // Click the first card's button
    const button = cards[0].querySelector("button");
    if (button) fireEvent.click(button);
    // Expanded detail should show "Probability Comparison"
    expect(screen.getByText("Probability Comparison")).toBeInTheDocument();
  });
});
