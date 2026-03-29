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
import KillSwitchView from '../KillSwitchView';
import KalshiTerminalView from '../KalshiTerminalView';
import KalshiOrderbookPanel from '../../components/KalshiOrderbookPanel';
import KalshiActivityLog from '../../components/KalshiActivityLog';
import KalshiSentimentView from '../KalshiSentimentView';
import KalshiAgentPerformanceView from '../KalshiAgentPerformanceView';
import DiscoverHealthView from '../DiscoverHealthView';

describe('Kalshi Suite — Smoke Tests', () => {
  it('Overview mounts without errors', () => {
    const { container } = render(<Overview />);
    expect(container.firstChild).toBeTruthy();
  });

  it('KillSwitchView mounts and shows title', () => {
    render(<KillSwitchView />);
    // Use heading role to avoid ambiguity with other "Kill Switch" text in the view
    expect(screen.getByRole('heading', { name: /Kill Switch/i })).toBeTruthy();
  });


  it('ExecutionGateStrip renders on Overview', () => {
    const { container } = render(<Overview />);
    expect(container.querySelector('[class*="rounded-xl"]')).toBeTruthy();
  });

  it('KalshiTerminalView mounts and shows Terminal title', () => {
    render(<KalshiTerminalView />);
    expect(screen.getByText(/Terminal/i)).toBeTruthy();
  });

  it('KalshiTerminalView shows search input', () => {
    render(<KalshiTerminalView />);
    expect(screen.getByPlaceholderText(/Search markets/i)).toBeTruthy();
  });

  it('KalshiTerminalView shows "Select a market" placeholder', () => {
    render(<KalshiTerminalView />);
    expect(screen.getByText(/Select a market to trade/i)).toBeTruthy();
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
    expect(screen.getByText(/Agent Performance/i)).toBeTruthy();
  });

  it('DiscoverHealthView mounts and shows "Discover Health" title', () => {
    render(<DiscoverHealthView />);
    expect(screen.getByText(/Discover Health/i)).toBeTruthy();
  });

  it('DiscoverHealthView shows all five crypto assets', () => {
    render(<DiscoverHealthView />);
    for (const asset of ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']) {
      expect(screen.getAllByText(asset).length).toBeGreaterThan(0);
    }
  });

  it('DiscoverHealthView shows all four timeframe labels', () => {
    render(<DiscoverHealthView />);
    expect(screen.getAllByText(/15 Min/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Hourly/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Daily/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Weekly/i).length).toBeGreaterThan(0);
  });

  it('DiscoverHealthView renders 5×4 mood grid section', () => {
    render(<DiscoverHealthView />);
    expect(screen.getByText(/Asset × Timeframe × Mood Grid/i)).toBeTruthy();
  });

});
