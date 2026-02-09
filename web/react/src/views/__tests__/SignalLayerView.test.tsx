/**
 * Tests for SignalLayerView — CQI dashboard, arb scanner, features, decay config.
 *
 * Covers:
 *   - Renders header with domain/signal counts
 *   - CQI dashboard tab: shows CQI cards with bands and component bars
 *   - Arb scanner tab: shows arb signal rows with edge/decay data
 *   - Decay config tab: shows decay config table with domain parameters
 *   - Tab switching between CQI / Arbs / Features / Decay
 *   - Empty states for CQI and arbs
 *   - Metrics sidebar renders store/arb/drift sections
 *   - Loading state
 */

import { render, screen, fireEvent } from "@testing-library/react";

// ── Mocks ────────────────────────────────────────────────────────────

const mockUseSignalCQI = jest.fn();
const mockUseSignalArbs = jest.fn();
const mockUseSignalMetrics = jest.fn();
const mockUseDecayConfigs = jest.fn();

jest.mock("../../hooks/useSignalLayer", () => ({
  useSignalCQI: (...args: unknown[]) => mockUseSignalCQI(...args),
  useSignalArbs: (...args: unknown[]) => mockUseSignalArbs(...args),
  useSignalMetrics: (...args: unknown[]) => mockUseSignalMetrics(...args),
  useDecayConfigs: (...args: unknown[]) => mockUseDecayConfigs(...args),
  useSignalFeatures: () => ({ data: null, loading: true, error: undefined }),
  useSignalSocial: () => ({ data: null, loading: true, error: undefined }),
}));

import SignalLayerView from "../SignalLayerView";

// ── Test data ────────────────────────────────────────────────────────

const MOCK_CQI = {
  domains: {
    crypto: {
      domain: "crypto",
      quality_index: 0.72,
      band: "good",
      window: "24h",
      components: { brier: 0.8, pnl: 0.6, drift: 0.7, decay: 0.75 },
      timestamp: Date.now() / 1000 - 60,
    },
    prediction: {
      domain: "prediction",
      quality_index: 0.45,
      band: "neutral",
      window: "24h",
      components: { brier: 0.5, pnl: 0.4, drift: 0.5, decay: 0.4 },
      timestamp: Date.now() / 1000 - 120,
    },
    sports: {
      domain: "sports",
      quality_index: 0.25,
      band: "poor",
      window: "24h",
      components: { brier: 0.2, pnl: 0.3, drift: 0.2, decay: 0.3 },
      timestamp: Date.now() / 1000 - 180,
    },
  },
  domain_count: 3,
};

const MOCK_ARBS = {
  signals: [
    {
      signal_id: "dis-abc123",
      domain: "crypto_cex",
      arb_type: "pure_arb",
      symbol: "BTC",
      gross_edge_bps: 25.3,
      net_edge_bps: 15.1,
      edge_usd: 7.55,
      ttl_seconds: 120,
      age_seconds: 45,
      is_actionable: true,
      decay_weight: 0.82,
      status: "active",
      venues: [],
    },
    {
      signal_id: "dis-def456",
      domain: "crypto_cex",
      arb_type: "dislocation",
      symbol: "ETH",
      gross_edge_bps: 18.0,
      net_edge_bps: 5.2,
      edge_usd: 2.60,
      ttl_seconds: 120,
      age_seconds: 95,
      is_actionable: false,
      decay_weight: 0.35,
      status: "expired",
      venues: [],
    },
  ],
  count: 2,
  metrics: {
    total_signals: 10,
    active_signals: 3,
    symbols_tracked: 5,
  },
};

const MOCK_METRICS = {
  store: {
    feature_snapshots: 42,
    signal_snapshots: 15,
    arb_signals_total: 10,
    cqi_entries: 8,
  },
  arb: {
    total_signals: 10,
    active_signals: 3,
    symbols_tracked: 5,
  },
  drift: {
    domains_tracked: ["crypto", "prediction"],
    total_outcomes: 200,
  },
};

const MOCK_DECAY_CONFIGS: Record<string, any> = {
  news: { domain: "news", tau_seconds: 1800, min_weight: 0.05, max_age_seconds: 43200, refresh_boost: 1.5 },
  social: { domain: "social", tau_seconds: 600, min_weight: 0.05, max_age_seconds: 7200, refresh_boost: 1.5 },
  arb: { domain: "arb", tau_seconds: 120, min_weight: 0.1, max_age_seconds: 1800, refresh_boost: 1.5 },
  macro: { domain: "macro", tau_seconds: 86400, min_weight: 0.1, max_age_seconds: 604800, refresh_boost: 1.5 },
};

// ── Helpers ──────────────────────────────────────────────────────────

function setupMocks(overrides?: {
  cqi?: any;
  arbs?: any;
  metrics?: any;
  configs?: any;
  loading?: boolean;
}) {
  const loading = overrides?.loading ?? false;
  mockUseSignalCQI.mockReturnValue({
    data: overrides?.cqi ?? MOCK_CQI,
    loading,
    error: undefined,
  });
  mockUseSignalArbs.mockReturnValue({
    data: overrides?.arbs ?? MOCK_ARBS,
    loading,
    error: undefined,
  });
  mockUseSignalMetrics.mockReturnValue({
    data: overrides?.metrics ?? MOCK_METRICS,
    loading: false,
    error: undefined,
  });
  mockUseDecayConfigs.mockReturnValue({
    data: overrides?.configs ?? MOCK_DECAY_CONFIGS,
    loading: false,
    error: undefined,
  });
}

beforeEach(() => {
  jest.clearAllMocks();
});

// ── Tests ────────────────────────────────────────────────────────────

describe("SignalLayerView", () => {
  test("renders header with Signal Layer title", () => {
    setupMocks();
    render(<SignalLayerView />);
    expect(screen.getByText("Signal Layer")).toBeInTheDocument();
  });

  test("shows domain and signal counts in header", () => {
    setupMocks();
    render(<SignalLayerView />);
    expect(screen.getByText("3 domains")).toBeInTheDocument();
    expect(screen.getByText("2 arb signals")).toBeInTheDocument();
  });

  test("renders four tab buttons", () => {
    setupMocks();
    render(<SignalLayerView />);
    expect(screen.getByText("📊 CQI Dashboard")).toBeInTheDocument();
    expect(screen.getByText("⚡ Arb Scanner")).toBeInTheDocument();
    expect(screen.getByText("🔬 Signal Features")).toBeInTheDocument();
    expect(screen.getByText("⏱️ Decay Config")).toBeInTheDocument();
  });

  test("CQI tab shows CQI cards with domain names", () => {
    setupMocks();
    render(<SignalLayerView />);
    const cards = screen.getAllByTestId("cqi-card");
    expect(cards.length).toBe(3);
    expect(screen.getByText("crypto")).toBeInTheDocument();
    expect(screen.getByText("prediction")).toBeInTheDocument();
    expect(screen.getByText("sports")).toBeInTheDocument();
  });

  test("CQI cards show quality index percentages", () => {
    setupMocks();
    render(<SignalLayerView />);
    expect(screen.getByText("72.0%")).toBeInTheDocument();
    expect(screen.getByText("45.0%")).toBeInTheDocument();
    expect(screen.getByText("25.0%")).toBeInTheDocument();
  });

  test("CQI cards show band labels", () => {
    setupMocks();
    render(<SignalLayerView />);
    expect(screen.getByText("good")).toBeInTheDocument();
    expect(screen.getByText("neutral")).toBeInTheDocument();
    expect(screen.getByText("poor")).toBeInTheDocument();
  });

  test("switching to Arb Scanner tab shows arb signals", () => {
    setupMocks();
    render(<SignalLayerView />);
    fireEvent.click(screen.getByText("⚡ Arb Scanner"));
    const rows = screen.getAllByTestId("arb-signal-row");
    expect(rows.length).toBe(2);
    expect(screen.getByText("BTC")).toBeInTheDocument();
    expect(screen.getByText("ETH")).toBeInTheDocument();
  });

  test("arb rows show edge metrics", () => {
    setupMocks();
    render(<SignalLayerView />);
    fireEvent.click(screen.getByText("⚡ Arb Scanner"));
    expect(screen.getByText("25.3 bps")).toBeInTheDocument();
    expect(screen.getByText("15.1 bps")).toBeInTheDocument();
    expect(screen.getByText("$7.55")).toBeInTheDocument();
  });

  test("arb rows show actionable status", () => {
    setupMocks();
    render(<SignalLayerView />);
    fireEvent.click(screen.getByText("⚡ Arb Scanner"));
    expect(screen.getByText("LIVE")).toBeInTheDocument();
    expect(screen.getByText("EXPIRED")).toBeInTheDocument();
  });

  test("switching to Decay Config tab shows config table", () => {
    setupMocks();
    render(<SignalLayerView />);
    fireEvent.click(screen.getByText("⏱️ Decay Config"));
    expect(screen.getByTestId("decay-config-table")).toBeInTheDocument();
    expect(screen.getByText("news")).toBeInTheDocument();
    expect(screen.getByText("social")).toBeInTheDocument();
    expect(screen.getByText("arb")).toBeInTheDocument();
    expect(screen.getByText("macro")).toBeInTheDocument();
  });

  test("metrics sidebar shows store metrics", () => {
    setupMocks();
    render(<SignalLayerView />);
    const sidebar = screen.getByTestId("signal-metrics");
    expect(sidebar).toBeInTheDocument();
    expect(screen.getByText("Signal Metrics")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument(); // feature_snapshots
    expect(screen.getByText("15")).toBeInTheDocument(); // signal_snapshots
  });

  test("empty CQI state", () => {
    setupMocks({ cqi: { domains: {}, domain_count: 0 } });
    render(<SignalLayerView />);
    expect(screen.getByTestId("cqi-empty")).toBeInTheDocument();
  });

  test("empty arb state", () => {
    setupMocks({ arbs: { signals: [], count: 0, metrics: {} } });
    render(<SignalLayerView />);
    fireEvent.click(screen.getByText("⚡ Arb Scanner"));
    expect(screen.getByTestId("arb-empty")).toBeInTheDocument();
  });

  test("loading state", () => {
    setupMocks({ loading: true, cqi: { domains: {}, domain_count: 0 }, arbs: { signals: [], count: 0, metrics: {} } });
    render(<SignalLayerView />);
    expect(screen.getByTestId("signal-loading")).toBeInTheDocument();
  });

  test("empty decay configs state", () => {
    setupMocks({ configs: {} });
    render(<SignalLayerView />);
    fireEvent.click(screen.getByText("⏱️ Decay Config"));
    expect(screen.getByTestId("decay-empty")).toBeInTheDocument();
  });
});
