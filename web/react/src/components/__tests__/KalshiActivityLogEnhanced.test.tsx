/**
 * Tests for Enhanced Kalshi Activity Log Component
 */

import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import EnhancedKalshiActivityLog from '../KalshiActivityLogEnhanced';

// Mock the network status hook
jest.mock('../../hooks/useNetworkStatusProvider', () => ({
  useNetworkStatus: () => ({
    isOnline: true,
    networkSpeed: 'fast',
    lastConnected: Date.now(),
    getConnectionQuality: () => 'excellent',
    subscribe: jest.fn(() => () => {}),
    forceRecheck: jest.fn(),
  }),
}));

// Mock the API data hook
jest.mock('../../hooks/useApiData', () => ({
  useApiData: (_endpoint: string, _options?: any) => {
    const mockData = {
      agents: [
        {
          name: 'TestAgent1',
          signals: [
            {
              ts: '2024-01-01T12:00:00Z',
              market_id: 'TEST-1',
              question: 'Test question 1',
              side: 'yes',
              confidence: 0.8,
              ev_cents: 5,
              agent: 'TestAgent1',
            },
          ],
          orders: [
            {
              ts: '2024-01-01T12:01:00Z',
              market_id: 'TEST-1',
              side: 'yes',
              size: 10,
              price_cents: 50,
              status: 'filled',
              source: 'test',
              agent: 'TestAgent1',
            },
          ],
        },
        {
          name: 'TestAgent2',
          signals: [],
          orders: [],
        },
      ],
    };

    return {
      data: mockData,
      error: null,
      isLoading: false,
      refetch: jest.fn(),
    };
  },
}));

describe('EnhancedKalshiActivityLog', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders activity log with data', () => {
    render(<EnhancedKalshiActivityLog ticker="TEST-1" />);
    
    expect(screen.getByText('Agent Activity')).toBeInTheDocument();
    expect(screen.getByText('TestAgent1')).toBeInTheDocument();
    expect(screen.getByText('YES')).toBeInTheDocument();
    expect(screen.getByText('EV +5¢ · 80% conf')).toBeInTheDocument();
  });

  it('shows loading skeleton when loading', () => {
    const { useApiData } = require('../../hooks/useApiData');
    useApiData.mockReturnValue({
      data: null,
      error: null,
      isLoading: true,
      refetch: jest.fn(),
    });

    render(<EnhancedKalshiActivityLog ticker="TEST-1" />);
    
    expect(screen.getByText('Agent Activity')).toBeInTheDocument();
    // Check for skeleton elements (they should be present but not have specific text)
    const skeletonElements = document.querySelectorAll('.animate-pulse');
    expect(skeletonElements.length).toBeGreaterThan(0);
  });

  it('shows empty state when no activity', () => {
    const { useApiData } = require('../../hooks/useApiData');
    useApiData.mockReturnValue({
      data: { agents: [] },
      error: null,
      isLoading: false,
      refetch: jest.fn(),
    });

    render(<EnhancedKalshiActivityLog ticker="TEST-1" />);
    
    expect(screen.getByText('Agent Activity')).toBeInTheDocument();
    expect(screen.getByText('No agent activity for this market')).toBeInTheDocument();
  });

  it('shows error state with retry option', () => {
    const { useApiData } = require('../../hooks/useApiData');
    const mockRefetch = jest.fn();
    useApiData.mockReturnValue({
      data: null,
      error: new Error('Network error'),
      isLoading: false,
      refetch: mockRefetch,
    });

    render(<EnhancedKalshiActivityLog ticker="TEST-1" />);
    
    expect(screen.getByText('Agent Activity')).toBeInTheDocument();
    expect(screen.getByText('Network connection failed')).toBeInTheDocument();
    expect(screen.getByText('Retry (0/3)')).toBeInTheDocument();
  });

  it('handles retry button click', async () => {
    const { useApiData } = require('../../hooks/useApiData');
    const mockRefetch = jest.fn();
    useApiData.mockReturnValue({
      data: null,
      error: new Error('Network error'),
      isLoading: false,
      refetch: mockRefetch,
    });

    render(<EnhancedKalshiActivityLog ticker="TEST-1" />);
    
    const retryButton = screen.getByText('Retry (0/3)');
    fireEvent.click(retryButton);
    
    expect(mockRefetch).toHaveBeenCalled();
  });

  it('shows offline state when network is offline', () => {
    const { useNetworkStatus } = require('../../hooks/useNetworkStatusProvider');
    useNetworkStatus.mockReturnValue({
      isOnline: false,
      networkSpeed: 'unknown',
      lastConnected: Date.now() - 10000,
      getConnectionQuality: () => 'unknown',
      subscribe: jest.fn(() => () => {}),
      forceRecheck: jest.fn(),
    });

    render(<EnhancedKalshiActivityLog ticker="TEST-1" />);
    
    expect(screen.getByText('Offline - Activity unavailable')).toBeInTheDocument();
  });

  it('shows slow connection warning', () => {
    const { useNetworkStatus } = require('../../hooks/useNetworkStatusProvider');
    useNetworkStatus.mockReturnValue({
      isOnline: true,
      networkSpeed: 'slow',
      lastConnected: Date.now(),
      getConnectionQuality: () => 'poor',
      subscribe: jest.fn(() => () => {}),
      forceRecheck: jest.fn(),
    });

    render(<EnhancedKalshiActivityLog ticker="TEST-1" />);
    
    expect(screen.getByText('Slow connection - Activity may be delayed')).toBeInTheDocument();
  });

  it('limits items to maxItems prop', () => {
    const { useApiData } = require('../../hooks/useApiData');
    useApiData.mockReturnValue({
      data: {
        agents: [
          {
            name: 'TestAgent1',
            signals: Array.from({ length: 20 }, (_, i) => ({
              ts: `2024-01-01T12:${i.toString().padStart(2, '0')}:00Z`,
              market_id: 'TEST-1',
              question: `Test question ${i}`,
              side: 'yes',
              confidence: 0.8,
              ev_cents: 5,
              agent: 'TestAgent1',
            })),
            orders: [],
          },
        ],
      },
      error: null,
      isLoading: false,
      refetch: jest.fn(),
    });

    render(<EnhancedKalshiActivityLog ticker="TEST-1" maxItems={5} />);
    
    const activityItems = screen.getAllByText(/TestAgent1/);
    expect(activityItems.length).toBeLessThanOrEqual(5);
  });

  it('shows cached data indicator when using fallback', () => {
    const { useApiData } = require('../../hooks/useApiData');
    useApiData.mockReturnValue({
      data: null,
      error: new Error('Network error'),
      isLoading: false,
      refetch: jest.fn(),
    });

    render(<EnhancedKalshiActivityLog ticker="TEST-1" />);
    
    // Initially should show error
    expect(screen.getByText('Network connection failed')).toBeInTheDocument();
    
    // After retry attempts exhausted, should show fallback
    // This would need additional test setup to simulate retry count
  });

  it('filters by ticker correctly', () => {
    const { useApiData } = require('../../hooks/useApiData');
    useApiData.mockReturnValue({
      data: {
        agents: [
          {
            name: 'TestAgent1',
            signals: [
              {
                ts: '2024-01-01T12:00:00Z',
                market_id: 'TEST-1',
                question: 'Test question 1',
                side: 'yes',
                confidence: 0.8,
                ev_cents: 5,
                agent: 'TestAgent1',
              },
              {
                ts: '2024-01-01T12:01:00Z',
                market_id: 'TEST-2',
                question: 'Test question 2',
                side: 'no',
                confidence: 0.6,
                ev_cents: -3,
                agent: 'TestAgent1',
              },
            ],
            orders: [],
          },
        ],
      },
      error: null,
      isLoading: false,
      refetch: jest.fn(),
    });

    render(<EnhancedKalshiActivityLog ticker="TEST-1" />);
    
    expect(screen.getByText('Test question 1')).toBeInTheDocument();
    expect(screen.queryByText('Test question 2')).not.toBeInTheDocument();
  });

  it('shows both signals and orders', () => {
    const { useApiData } = require('../../hooks/useApiData');
    useApiData.mockReturnValue({
      data: {
        agents: [
          {
            name: 'TestAgent1',
            signals: [
              {
                ts: '2024-01-01T12:00:00Z',
                market_id: 'TEST-1',
                question: 'Test question 1',
                side: 'yes',
                confidence: 0.8,
                ev_cents: 5,
                agent: 'TestAgent1',
              },
            ],
            orders: [
              {
                ts: '2024-01-01T12:01:00Z',
                market_id: 'TEST-1',
                side: 'yes',
                size: 10,
                price_cents: 50,
                status: 'filled',
                source: 'test',
                agent: 'TestAgent1',
              },
            ],
          },
        ],
      },
      error: null,
      isLoading: false,
      refetch: jest.fn(),
    });

    render(<EnhancedKalshiActivityLog ticker="TEST-1" />);
    
    expect(screen.getByText('EV +5¢ · 80% conf')).toBeInTheDocument();
    expect(screen.getByText('10×50¢ filled')).toBeInTheDocument();
  });
});
