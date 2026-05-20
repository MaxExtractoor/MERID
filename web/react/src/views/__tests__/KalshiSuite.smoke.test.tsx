/**
 * Kalshi Suite Smoke Tests
 *
 * Mount each active Kalshi view and assert that core widgets render
 * without JS errors. These are NOT behavioral tests — they verify
 * that the component tree mounts cleanly with mocked API data.
 *
 * Run: npx jest --testPathPattern KalshiSuite.smoke
 */
import React from 'react';
import { render, screen } from '@testing-library/react';

// Mock portfolioClient to avoid WebSocket connection errors
jest.mock('../../lib/portfolioClient', () => ({
  PortfolioClient: jest.fn().mockImplementation(() => ({
    connect: jest.fn(),
    subscribe: jest.fn(),
    disconnect: jest.fn(),
  })),
  subscribeToPortfolio: jest.fn(),
}));

// Mock API_ENDPOINTS to include PORTFOLIO_WEBSOCKET function
jest.mock('../../config/constants', () => ({
  ...jest.requireActual('../../config/constants'),
  API_ENDPOINTS: {
    ...jest.requireActual('../../config/constants').API_ENDPOINTS,
    PORTFOLIO_WEBSOCKET: jest.fn((accountId: string = "default") => `/api/v1/portfolio/ws/${accountId}`),
  },
}));

// Mock useApiData to return stub data for all endpoints
jest.mock('../../hooks/useApiData', () => ({
  useApiData: () => ({
    data: null,
    loading: false,
    error: null,
    refetch: jest.fn(),
    lastUpdated: new Date(),
    rawResponse: null,
    isStub: false,
  }),
}));

// Mock useMeridSocket
jest.mock('../../hooks/useMeridSocket', () => ({
  useMeridSocket: () => ({ socket: null, connected: false }),
  useNativeWebSocket: () => ({ socket: null, connected: false, disconnectedSince: null }),
}));

// Mock useFeatureFlags
jest.mock('../../config/featureFlags', () => ({
  useFeatureFlags: () => ({ kalshiOnly: true }),
  setKalshiOnly: jest.fn(),
}));

// Mock useRiskProtections — used by Overview and other views
jest.mock('../../hooks/useRiskProtections', () => ({
  useRiskProtections: () => ({ data: null, loading: false, error: null, refetch: jest.fn(), resetCircuit: jest.fn(), toggleKillSwitch: jest.fn() }),
  getOverallRiskStatus: () => ({ status: 'good', message: 'OK' }),
  isTradingBlocked: () => false,
}));

// Mock useKalshiMode context
jest.mock('../../context/KalshiModeContext', () => ({
  useKalshiMode: () => ({ data: null, isLive: false }),
}));

// Mock useNetworkStatusProvider
jest.mock('../../hooks/useNetworkStatusProvider', () => ({
  useNetworkStatus: () => ({ isOnline: true, backendReachable: true }),
  NetworkProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Mock useDashboard — used by Overview (must include component exports)
jest.mock('../../hooks/useDashboard', () => ({
  useDashboard: () => ({ trading: null, risk: null, agents: null, loading: false, error: null }),
  useSystemHealth: () => ({ health: null, loading: false }),
  useKalshiHealth: () => ({ health: null, loading: false }),
  useAgentsSummary: () => ({ agents: [], loading: false }),
  SystemHealthCard: () => <div data-testid="stub-card" />,
  KalshiHealthCard: () => <div data-testid="stub-card" />,
  AgentStatusCard: () => <div data-testid="stub-card" />,
  RiskProtectionCard: () => <div data-testid="stub-card" />,
}));

// Mock RiskProtectionsPanel component exports (RiskProtectionCard re-exported from useDashboard)
jest.mock('../../components/RiskProtectionsPanel', () => ({
  __esModule: true,
  default: () => <div data-testid="risk-panel" />,
  RiskProtectionsCard: () => <div data-testid="risk-card" />,
}));

// Mock child components used by Overview
jest.mock('../../components/CollapsibleConsole', () => ({
  __esModule: true,
  default: () => <div data-testid="console" />,
}));
jest.mock('../../components/AgentActivityPanel', () => ({
  __esModule: true,
  default: () => <div data-testid="agent-panel" />,
}));
jest.mock('../../components/ExecutionGateStrip', () => ({
  __esModule: true,
  default: () => <div data-testid="execution-gate" className="rounded-xl" />,
}));

// Mock constants for predictable test behavior
jest.mock('../../config/constants', () => ({
  API_BASE_URL: '',
  API_ENDPOINTS: new Proxy({}, { get: () => '' }),
  AUTH_TOKEN_KEY: 'merid-access',
  DEFAULTS: {
    POLLING_INTERVALS: {
      FAST_REFRESH: 5000, STANDARD: 10000, SLOW: 30000, MEDIUM: 15000,
      SENTIMENT: 30000, BACKGROUND: 60000, INFREQUENT: 120000,
    },
    TIMEOUTS: { STATUS_RESET: 5000 },
  },
  CHART_COLORS: new Proxy({}, { get: () => '#000' }),
  HEALTH_STATUS: { HEALTHY: 'healthy', DEGRADED: 'degraded', UNHEALTHY: 'unhealthy' },
  AGENT_STATUS: { RUNNING: 'running', PAUSED: 'paused', STOPPED: 'stopped' },
  GRID_CELL_STATUS: { ACTIVE: 'active', COVERING: 'covering' },
  ORDER_STATUS: { RESTING: 'resting', PENDING: 'pending', FILLED: 'filled', CANCELED: 'canceled', CANCELLED: 'cancelled' },
  WS_URL: '',
  WS_PORTFOLIO_URL: '',
}));

// Mock lucide-react with Proxy so any icon import resolves to a stub
jest.mock('lucide-react', () => {
  return new Proxy({}, {
    get: (_target: Record<string, unknown>, prop: string | symbol) => {
      if (typeof prop !== 'string') return undefined;
      const Stub = ({ className }: { className?: string }) => (
        <span data-testid={`icon-${prop}`} className={className} />
      );
      Stub.displayName = prop;
      return Stub;
    },
  });
});

// Mock recharts to avoid canvas errors in test env
jest.mock('recharts', () => {
  const Original = jest.requireActual('recharts');
  return {
    ...Original,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="responsive-container">{children}</div>
    ),
  };
});

// Lazy imports to allow mocks to settle
import Overview from '../Overview';
import ProtectView from '../ProtectView';
import ExecuteView from '../ExecuteView';
import KalshiOrderbookPanel from '../../components/KalshiOrderbookPanel';
import KalshiActivityLog from '../../components/KalshiActivityLog';
import KalshiSentimentView from '../KalshiSentimentView';
import KalshiAgentPerformanceView from '../KalshiAgentPerformanceView';

describe('Kalshi Suite — Smoke Tests', () => {
  it('Overview mounts without errors', () => {
    const { container } = render(<Overview />);
    expect(container.firstChild).toBeTruthy();
  });

  it('ProtectView mounts and shows title', () => {
    render(<ProtectView />);
    expect(screen.getByText(/Protect/i)).toBeTruthy();
  });

  it('ExecutionGateStrip renders on Overview', () => {
    const { container } = render(<Overview />);
    expect(container.querySelector('[class*="rounded-xl"]')).toBeTruthy();
  });

  it('ExecuteView mounts and shows Execute title', () => {
    render(<ExecuteView />);
    expect(screen.getByText(/Execute/i)).toBeTruthy();
  });

  it('KalshiOrderbookPanel renders nothing when no ticker', () => {
    const { container } = render(<KalshiOrderbookPanel ticker={null} />);
    expect(container.innerHTML).toBe('');
  });

  it('KalshiActivityLog renders nothing when no ticker', () => {
    const { container } = render(<KalshiActivityLog ticker={null} />);
    expect(container.innerHTML).toBe('');
  });

  it('KalshiSentimentView mounts and shows Fear/Greed title', () => {
    render(<KalshiSentimentView />);
    expect(screen.getByText(/Fear \/ Greed/i)).toBeTruthy();
  });

  it('KalshiSentimentView shows empty state when no data', () => {
    render(<KalshiSentimentView />);
    expect(screen.getByText(/No sentiment data yet/i)).toBeTruthy();
  });

  it('KalshiAgentPerformanceView mounts and shows title', () => {
    render(<KalshiAgentPerformanceView />);
    expect(screen.getAllByText(/Agent Performance/i).length).toBeGreaterThan(0);
  });

});
