/**
 * Tests for BettingConsensusView — swarm-driven sports betting page.
 *
 * Covers:
 *   - Renders header and filter bar
 *   - Shows stub banner when data is stubbed
 *   - Renders event cards with correct data
 *   - Shows live badge for in-play events
 *   - Empty state when no events match filter
 *   - Metrics sidebar renders when data is available
 */

import { render, screen, fireEvent } from "@testing-library/react";

// ── Mocks ────────────────────────────────────────────────────────────

const mockUseBettingConsensus = jest.fn();
const mockUseBettingMetrics = jest.fn();

jest.mock("../../hooks/useBettingConsensus", () => ({
  useBettingConsensus: (...args: unknown[]) => mockUseBettingConsensus(...args),
  useBettingMetrics: (...args: unknown[]) => mockUseBettingMetrics(...args),
}));

jest.mock("../../utils/stub", () => ({
  isStub: (raw: unknown) =>
    raw != null && typeof raw === "object" && "_stub" in (raw as Record<string, unknown>),
}));

import BettingConsensusView from "../BettingConsensusView";

// ── Helpers ──────────────────────────────────────────────────────────

const MOCK_EVENTS = [
  {
    event_id: "nfl-1",
    event: {
      id: "nfl-1",
      sport: "nfl",
      league: "NFL",
      title: "Chiefs @ 49ers",
      home_team: "49ers",
      away_team: "Chiefs",
      start_time: Date.now() / 1000 + 86400,
      state: "pre" as const,
      score_home: null,
      score_away: null,
      period: "",
      clock: "",
      outcomes: [
        { id: "h", name: "49ers", market_type: "moneyline" },
        { id: "a", name: "Chiefs", market_type: "moneyline" },
      ],
      market_types: ["moneyline"],
      kalshi_event_id: null,
    },
    sportsbook_consensus_prob: { h: 0.5, a: 0.5 },
    sharp_book_prob: {},
    best_book_odds: {},
    book_count: 5,
    prediction_market_prob: {},
    prediction_market_source: "",
    swarm_prob: { h: 0.55, a: 0.45 },
    swarm_confidence: 0.72,
    swarm_supporting_agents: 4,
    swarm_opposing_agents: 2,
    swarm_opinion_count: 6,
    edge_vs_books: { h: 0.05, a: -0.05 },
    edge_vs_prediction: {},
    stance: "weak_yes",
    max_edge: 0.05,
    active_plans: { proposed: 1, approved: 0, executing: 0 },
    state: "pre" as const,
    last_update_ts: Date.now() / 1000,
    arbitrage_flag: false,
  },
  {
    event_id: "nba-live",
    event: {
      id: "nba-live",
      sport: "nba",
      league: "NBA",
      title: "Nuggets @ Warriors",
      home_team: "Warriors",
      away_team: "Nuggets",
      start_time: Date.now() / 1000 - 3600,
      state: "live" as const,
      score_home: 67,
      score_away: 72,
      period: "Q3",
      clock: "4:23",
      outcomes: [
        { id: "h2", name: "Warriors", market_type: "moneyline" },
        { id: "a2", name: "Nuggets", market_type: "moneyline" },
      ],
      market_types: ["moneyline"],
      kalshi_event_id: null,
    },
    sportsbook_consensus_prob: { h2: 0.42, a2: 0.58 },
    sharp_book_prob: {},
    best_book_odds: {},
    book_count: 3,
    prediction_market_prob: {},
    prediction_market_source: "",
    swarm_prob: { h2: 0.38, a2: 0.62 },
    swarm_confidence: 0.65,
    swarm_supporting_agents: 3,
    swarm_opposing_agents: 1,
    swarm_opinion_count: 4,
    edge_vs_books: { h2: -0.04, a2: 0.04 },
    edge_vs_prediction: {},
    stance: "weak_yes",
    max_edge: 0.04,
    active_plans: { proposed: 0, approved: 0, executing: 0 },
    state: "live" as const,
    last_update_ts: Date.now() / 1000,
    arbitrage_flag: false,
  },
];

const DEFAULT_CONSENSUS_RETURN = {
  events: MOCK_EVENTS,
  byEventId: { "nfl-1": MOCK_EVENTS[0], "nba-live": MOCK_EVENTS[1] },
  liveCount: 1,
  rawResponse: null,
  loading: false,
  error: undefined,
  refetch: jest.fn(),
};

const DEFAULT_METRICS_RETURN = {
  metrics: null,
  rawResponse: null,
  loading: false,
  error: undefined,
};

// ── Tests ────────────────────────────────────────────────────────────

describe("BettingConsensusView", () => {
  beforeEach(() => {
    mockUseBettingConsensus.mockReturnValue(DEFAULT_CONSENSUS_RETURN);
    mockUseBettingMetrics.mockReturnValue(DEFAULT_METRICS_RETURN);
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it("renders the main view with header", () => {
    render(<BettingConsensusView />);
    expect(screen.getByTestId("betting-consensus-view")).toBeInTheDocument();
    expect(screen.getByText(/Swarm Betting/)).toBeInTheDocument();
  });

  it("renders event cards", () => {
    render(<BettingConsensusView />);
    const cards = screen.getAllByTestId("betting-event-card");
    expect(cards).toHaveLength(2);
  });

  it("shows LIVE badge for in-play event", () => {
    render(<BettingConsensusView />);
    const liveBadges = screen.getAllByText("LIVE");
    expect(liveBadges.length).toBeGreaterThanOrEqual(1);
  });

  it("shows stub banner when data is stubbed", () => {
    mockUseBettingConsensus.mockReturnValue({
      ...DEFAULT_CONSENSUS_RETURN,
      rawResponse: { _stub: true },
    });
    render(<BettingConsensusView />);
    expect(screen.getByTestId("betting-stub-banner")).toBeInTheDocument();
  });

  it("shows empty state when no events match filter", () => {
    mockUseBettingConsensus.mockReturnValue({
      ...DEFAULT_CONSENSUS_RETURN,
      events: [],
      liveCount: 0,
    });
    render(<BettingConsensusView />);
    expect(screen.getByTestId("betting-empty")).toBeInTheDocument();
  });

  it("renders sport filter buttons", () => {
    render(<BettingConsensusView />);
    expect(screen.getByText("All")).toBeInTheDocument();
    // NFL/NBA appear in both filter buttons and event badges
    expect(screen.getAllByText("NFL").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("NBA").length).toBeGreaterThanOrEqual(1);
  });

  it("filters events by sport when clicking filter button", () => {
    render(<BettingConsensusView />);
    // Click NBA filter
    fireEvent.click(screen.getByText("NBA"));
    // Only NBA event should be visible (Nuggets @ Warriors)
    const cards = screen.getAllByTestId("betting-event-card");
    expect(cards).toHaveLength(1);
    expect(screen.getByText("Nuggets @ Warriors")).toBeInTheDocument();
  });

  it("shows metrics sidebar with performance data", () => {
    mockUseBettingMetrics.mockReturnValue({
      metrics: {
        total_bets: 10,
        wins: 6,
        losses: 4,
        win_rate: 0.6,
        total_staked_usd: 1000,
        total_pnl_usd: 200,
        roi: 0.2,
        active_events: 5,
        live_events: 1,
        plans: { proposed: 2, approved: 1, executing: 0, placed: 3, settled: 4 },
      },
      rawResponse: {},
      loading: false,
      error: undefined,
    });
    render(<BettingConsensusView />);
    expect(screen.getByText("Performance")).toBeInTheDocument();
    // Win rate appears as "60%" — may appear multiple times
    const winRateElements = screen.getAllByText("60%");
    expect(winRateElements.length).toBeGreaterThanOrEqual(1);
  });

  it("shows live count in header badge", () => {
    render(<BettingConsensusView />);
    expect(screen.getByText("1 LIVE")).toBeInTheDocument();
  });

  it("renders score for live events", () => {
    render(<BettingConsensusView />);
    // The live NBA game should show scores in a combined string
    const scoreElements = screen.getAllByText(/67|72/);
    expect(scoreElements.length).toBeGreaterThanOrEqual(1);
  });
});
