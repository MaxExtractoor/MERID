/**
 * Tests for KalshiRiskFeed — Live risk event stream.
 */

import { render, screen } from '@testing-library/react';

const mockUseApiData = jest.fn();
jest.mock('../../hooks/useApiData', () => ({
  useApiData: (...args: unknown[]) => mockUseApiData(...args),
}));

jest.mock('../../hooks/useKalshiRiskStream', () => ({
  useKalshiRiskStream: () => ({
    alerts: [],
    summary: null,
    connected: false,
    clearAlerts: jest.fn(),
  }),
}));

import React from 'react';
import KalshiRiskFeed from '../KalshiRiskFeed';

const MOCK_EVENTS = {
  events: [
    { id: 'e1', ts: '2026-02-16T12:00:00Z', severity: 'critical', category: 'circuit_breaker', title: 'Circuit breaker tripped on BTC-1H' },
    { id: 'e2', ts: '2026-02-16T11:55:00Z', severity: 'warning', category: 'drawdown', title: 'Drawdown tier changed to Warning' },
    { id: 'e3', ts: '2026-02-16T11:50:00Z', severity: 'info', category: 'general', title: 'Agent restarted successfully' },
  ],
};

const MOCK_LIQ_ALERTS = {
  alerts: [
    { ticker: 'KXETH-15M', message: 'Wide spread detected (8c)', severity: 'warning', ts: '2026-02-16T11:52:00Z' },
  ],
};

describe('KalshiRiskFeed', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('shows loading state when no data', () => {
    mockUseApiData.mockReturnValue({ data: null, loading: true });
    render(<KalshiRiskFeed />);
    expect(screen.getByText(/Loading risk events/i)).toBeInTheDocument();
  });

  it('shows empty state when no events', () => {
    mockUseApiData.mockImplementation((endpoint: string) => {
      if (endpoint.includes('/events')) return { data: { events: [] }, loading: false };
      return { data: { alerts: [] }, loading: false };
    });
    render(<KalshiRiskFeed />);
    expect(screen.getByText(/No risk events/i)).toBeInTheDocument();
  });

  it('renders risk events', () => {
    mockUseApiData.mockImplementation((endpoint: string) => {
      if (endpoint.includes('/events')) return { data: MOCK_EVENTS, loading: false };
      return { data: { alerts: [] }, loading: false };
    });
    render(<KalshiRiskFeed />);
    expect(screen.getByText('Circuit breaker tripped on BTC-1H')).toBeInTheDocument();
    expect(screen.getByText('Drawdown tier changed to Warning')).toBeInTheDocument();
    expect(screen.getByText('Agent restarted successfully')).toBeInTheDocument();
  });

  it('shows CRITICAL badge when critical events exist', () => {
    mockUseApiData.mockImplementation((endpoint: string) => {
      if (endpoint.includes('/events')) return { data: MOCK_EVENTS, loading: false };
      return { data: { alerts: [] }, loading: false };
    });
    render(<KalshiRiskFeed />);
    expect(screen.getByText(/1 CRITICAL/)).toBeInTheDocument();
  });

  it('merges liquidity alerts into feed', () => {
    mockUseApiData.mockImplementation((endpoint: string) => {
      if (endpoint.includes('/events')) return { data: { events: [] }, loading: false };
      if (endpoint.includes('liquidity')) return { data: MOCK_LIQ_ALERTS, loading: false };
      return { data: null, loading: false };
    });
    render(<KalshiRiskFeed />);
    expect(screen.getByText(/KXETH-15M: Wide spread detected/)).toBeInTheDocument();
  });

  it('displays event count', () => {
    mockUseApiData.mockImplementation((endpoint: string) => {
      if (endpoint.includes('/events')) return { data: MOCK_EVENTS, loading: false };
      return { data: { alerts: [] }, loading: false };
    });
    render(<KalshiRiskFeed />);
    expect(screen.getByText('3 events')).toBeInTheDocument();
  });

  it('respects maxItems prop', () => {
    mockUseApiData.mockImplementation((endpoint: string) => {
      if (endpoint.includes('/events')) return { data: MOCK_EVENTS, loading: false };
      return { data: { alerts: [] }, loading: false };
    });
    render(<KalshiRiskFeed maxItems={2} />);
    expect(screen.getByText('2 events')).toBeInTheDocument();
  });
});
