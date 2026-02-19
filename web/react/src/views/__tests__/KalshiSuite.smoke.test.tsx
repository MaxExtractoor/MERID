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
import ExposureView from '../ExposureView';
import AgentHealthView from '../AgentHealthView';
import Orders from '../Orders';
import Risk from '../Risk';
import ObservabilityView from '../ObservabilityView';
import KalshiTerminalView from '../KalshiTerminalView';
import KalshiOrderbookPanel from '../../components/KalshiOrderbookPanel';
import KalshiActivityLog from '../../components/KalshiActivityLog';

describe('Kalshi Suite — Smoke Tests', () => {
  it('Overview mounts without errors', () => {
    const { container } = render(<Overview />);
    expect(container.firstChild).toBeTruthy();
  });

  it('KillSwitchView mounts and shows title', () => {
    render(<KillSwitchView />);
    expect(screen.getByText(/Kill Switch/i)).toBeTruthy();
  });

  it('ExposureView mounts without errors', () => {
    const { container } = render(<ExposureView />);
    expect(container.firstChild).toBeTruthy();
  });

  it('AgentHealthView mounts without errors', () => {
    const { container } = render(<AgentHealthView />);
    expect(container.firstChild).toBeTruthy();
  });

  it('Orders mounts without errors', () => {
    const { container } = render(<Orders />);
    expect(container.firstChild).toBeTruthy();
  });

  it('Risk mounts without errors', () => {
    const { container } = render(<Risk />);
    expect(container.firstChild).toBeTruthy();
  });

  it('ObservabilityView mounts without errors', () => {
    const { container } = render(<ObservabilityView />);
    expect(container.firstChild).toBeTruthy();
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
});
