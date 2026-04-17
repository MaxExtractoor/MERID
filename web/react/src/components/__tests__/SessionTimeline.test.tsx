/**
 * SessionTimeline Component Tests
 *
 * Tests the session timeline component that displays structured
 * backend logs with real-time updates and freshness indicators.
 */

import { render, screen } from '@testing-library/react';
import SessionTimeline from '../SessionTimeline';

// Mock useApiData hook
jest.mock('../../hooks/useApiData', () => ({
  useApiData: jest.fn(),
}));

const mockUseApiData = require('../../hooks/useApiData').useApiData;

describe('SessionTimeline', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders loading state initially', () => {
    mockUseApiData.mockReturnValue({
      data: null,
      loading: true,
      error: null,
      lastUpdated: null,
    });

    render(<SessionTimeline />);

    expect(screen.getByText('Session Timeline')).toBeInTheDocument();
    // Should show skeleton loading
    expect(screen.getAllByTestId('skeleton')).toHaveLength(5);
  });

  it('renders error state when API fails', () => {
    mockUseApiData.mockReturnValue({
      data: null,
      loading: false,
      error: new Error('API Error'),
      lastUpdated: null,
    });

    render(<SessionTimeline />);

    expect(screen.getByText('Failed to load session logs')).toBeInTheDocument();
  });

  it('renders logs correctly', () => {
    const mockLogs = [
      {
        timestamp: '2024-01-01T10:00:00Z',
        level: 'info',
        component: 'agent_grid',
        message: 'Agent started successfully',
        metadata: { event_id: 'evt-1' },
      },
      {
        timestamp: '2024-01-01T10:05:00Z',
        level: 'warning',
        component: 'risk_manager',
        message: 'High volatility detected',
        metadata: { event_id: 'evt-2' },
      },
    ];

    mockUseApiData.mockReturnValue({
      data: { logs: mockLogs, total: 2 },
      loading: false,
      error: null,
      lastUpdated: new Date('2024-01-01T10:10:00Z'),
    });

    render(<SessionTimeline />);

    expect(screen.getByText('Agent started successfully')).toBeInTheDocument();
    expect(screen.getByText('High volatility detected')).toBeInTheDocument();
    expect(screen.getByText('2 events')).toBeInTheDocument();
    expect(screen.getByText('10:10:00 AM')).toBeInTheDocument();
  });

  it('renders empty state when no logs', () => {
    mockUseApiData.mockReturnValue({
      data: { logs: [], total: 0 },
      loading: false,
      error: null,
      lastUpdated: null,
    });

    render(<SessionTimeline />);

    expect(screen.getByText('No session events yet')).toBeInTheDocument();
  });

  it('displays correct log levels and components', () => {
    const mockLogs = [
      {
        timestamp: '2024-01-01T10:00:00Z',
        level: 'error',
        component: 'system',
        message: 'Critical system error',
        metadata: {},
      },
    ];

    mockUseApiData.mockReturnValue({
      data: { logs: mockLogs, total: 1 },
      loading: false,
      error: null,
      lastUpdated: null,
    });

    render(<SessionTimeline />);

    // Check that error level gets correct styling/icon
    const logEntry = screen.getByText('Critical system error');
    expect(logEntry).toBeInTheDocument();

    // Component name should be formatted
    expect(screen.getByText('System')).toBeInTheDocument();
  });

  it('handles metadata display', () => {
    const mockLogs = [
      {
        timestamp: '2024-01-01T10:00:00Z',
        level: 'info',
        component: 'consensus',
        message: 'Consensus reached',
        metadata: { event_id: 'evt-123', confidence: 0.85 },
      },
    ];

    mockUseApiData.mockReturnValue({
      data: { logs: mockLogs, total: 1 },
      loading: false,
      error: null,
      lastUpdated: null,
    });

    render(<SessionTimeline />);

    // Should have a details element for metadata
    const details = screen.getByText('Metadata');
    expect(details).toBeInTheDocument();
  });

  it('formats timestamps correctly', () => {
    const recentTime = new Date(Date.now() - 5 * 60 * 1000); // 5 minutes ago
    const mockLogs = [
      {
        timestamp: recentTime.toISOString(),
        level: 'info',
        component: 'agent',
        message: 'Agent check-in',
        metadata: {},
      },
    ];

    mockUseApiData.mockReturnValue({
      data: { logs: mockLogs, total: 1 },
      loading: false,
      error: null,
      lastUpdated: null,
    });

    render(<SessionTimeline />);

    expect(screen.getByText('5m ago')).toBeInTheDocument();
  });
});
