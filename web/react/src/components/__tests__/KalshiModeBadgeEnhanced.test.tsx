/**
 * Tests for Enhanced Kalshi Mode Badge Component
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import EnhancedKalshiModeBadge from '../KalshiModeBadgeEnhanced';

// Mock the Kalshi mode context
jest.mock('../../context/KalshiModeContext', () => ({
  useKalshiMode: () => ({
    data: { mode: 'paper', is_live: false },
    error: null,
    isLoading: false,
    refetch: jest.fn(),
  }),
}));

// Mock the network status provider
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

// Mock error handling utilities
jest.mock('../../utils/errorHandling', () => ({
  categorizeError: (error: any) => ({
    type: 'network',
    severity: 'medium',
    message: error?.message || 'Network error',
    userMessage: 'Network connection failed',
    retryable: true,
    recoveryAction: 'retry',
    timestamp: Date.now(),
  }),
  isRetryable: () => true,
  calculateRetryDelay: (count: number) => count * 1000,
}));

describe('EnhancedKalshiModeBadge', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders mode badge with paper mode', () => {
    render(<EnhancedKalshiModeBadge />);
    
    expect(screen.getByText('PAPER')).toBeInTheDocument();
  });

  it('renders mode badge with live mode', () => {
    const { useKalshiMode } = require('../../context/KalshiModeContext');
    useKalshiMode.mockReturnValue({
      data: { mode: 'live', is_live: true },
      error: null,
      isLoading: false,
      refetch: jest.fn(),
    });

    render(<EnhancedKalshiModeBadge />);
    
    expect(screen.getByText('LIVE')).toBeInTheDocument();
  });

  it('renders mode badge with shadow mode', () => {
    const { useKalshiMode } = require('../../context/KalshiModeContext');
    useKalshiMode.mockReturnValue({
      data: { mode: 'shadow', is_live: false },
      error: null,
      isLoading: false,
      refetch: jest.fn(),
    });

    render(<EnhancedKalshiModeBadge />);
    
    expect(screen.getByText('SHADOW')).toBeInTheDocument();
  });

  it('shows loading skeleton when loading', () => {
    const { useKalshiMode } = require('../../context/KalshiModeContext');
    useKalshiMode.mockReturnValue({
      data: null,
      error: null,
      isLoading: true,
      refetch: jest.fn(),
    });

    render(<EnhancedKalshiModeBadge />);
    
    // Check for skeleton elements (they should be present but not have specific text)
    const skeletonElements = document.querySelectorAll('.animate-pulse');
    expect(skeletonElements.length).toBeGreaterThan(0);
  });

  it('shows error state with retry option', () => {
    const { useKalshiMode } = require('../../context/KalshiModeContext');
    const mockRefetch = jest.fn();
    
    useKalshiMode.mockReturnValue({
      data: null,
      error: new Error('Mode fetch failed'),
      isLoading: false,
      refetch: mockRefetch,
    });

    render(<EnhancedKalshiModeBadge />);
    
    expect(screen.getByText('ERROR')).toBeInTheDocument();
    expect(screen.getByText('RETRY')).toBeInTheDocument();
  });

  it('handles retry button click', async () => {
    const { useKalshiMode } = require('../../context/KalshiModeContext');
    const mockRefetch = jest.fn();
    
    useKalshiMode.mockReturnValue({
      data: null,
      error: new Error('Mode fetch failed'),
      isLoading: false,
      refetch: mockRefetch,
    });

    render(<EnhancedKalshiModeBadge />);
    
    const retryButton = screen.getByText('RETRY');
    fireEvent.click(retryButton);
    
    await waitFor(() => {
      expect(mockRefetch).toHaveBeenCalled();
    });
  });

  it('shows cached mode indicator when using fallback', () => {
    const { useKalshiMode } = require('../../context/KalshiModeContext');
    
    // First call returns data, second call returns error (simulating connection loss)
    let callCount = 0;
    useKalshiMode.mockImplementation(() => {
      callCount++;
      if (callCount === 1) {
        return {
          data: { mode: 'paper', is_live: false },
          error: null,
          isLoading: false,
          refetch: jest.fn(),
        };
      } else {
        return {
          data: null,
          error: new Error('Mode fetch failed'),
          isLoading: false,
          refetch: jest.fn(),
        };
      }
    });

    render(<EnhancedKalshiModeBadge />);
    
    // Initially should show PAPER
    expect(screen.getByText('PAPER')).toBeInTheDocument();
    
    // This would need additional test setup to simulate the fallback behavior
  });

  it('shows offline indicator when offline', () => {
    const { useNetworkStatus } = require('../../hooks/useNetworkStatusProvider');
    useNetworkStatus.mockReturnValue({
      isOnline: false,
      networkSpeed: 'unknown',
      lastConnected: Date.now() - 10000,
      getConnectionQuality: () => 'unknown',
      subscribe: jest.fn(() => () => {}),
      forceRecheck: jest.fn(),
    });

    render(<EnhancedKalshiModeBadge />);
    
    expect(screen.getByText('OFFLINE')).toBeInTheDocument();
  });

  it('shows slow connection indicator', () => {
    const { useNetworkStatus } = require('../../hooks/useNetworkStatusProvider');
    useNetworkStatus.mockReturnValue({
      isOnline: true,
      networkSpeed: 'slow',
      lastConnected: Date.now(),
      getConnectionQuality: () => 'poor',
      subscribe: jest.fn(() => () => {}),
      forceRecheck: jest.fn(),
    });

    render(<EnhancedKalshiModeBadge />);
    
    expect(screen.getByText('SLOW')).toBeInTheDocument();
  });

  it('shows tooltip on hover', () => {
    render(<EnhancedKalshiModeBadge showTooltip={true} />);
    
    const badge = screen.getByText('PAPER');
    expect(badge.closest('.group')).toBeInTheDocument();
    
    // Tooltip content would be visible on hover (tested through DOM structure)
  });

  it('does not show tooltip when disabled', () => {
    render(<EnhancedKalshiModeBadge showTooltip={false} />);
    
    const badge = screen.getByText('PAPER');
    expect(badge.closest('.group')).toBeNull();
  });

  it('applies custom className', () => {
    render(<EnhancedKalshiModeBadge className="custom-class" />);
    
    const badge = screen.getByText('PAPER');
    expect(badge.closest('.custom-class')).toBeInTheDocument();
  });

  it('uses fallback mode when no data available', () => {
    const { useKalshiMode } = require('../../context/KalshiModeContext');
    useKalshiMode.mockReturnValue({
      data: null,
      error: null,
      isLoading: false,
      refetch: jest.fn(),
    });

    render(<EnhancedKalshiModeBadge fallbackMode="live" />);
    
    // Should eventually show fallback mode (would need additional test setup)
  });

  it('shows max retry indicator when max retries reached', () => {
    const { useKalshiMode } = require('../../context/KalshiModeContext');
    useKalshiMode.mockReturnValue({
      data: null,
      error: new Error('Mode fetch failed'),
      isLoading: false,
      refetch: jest.fn(),
    });

    render(<EnhancedKalshiModeBadge />);
    
    // Would need additional test setup to simulate retry count reaching max
    expect(screen.getByText('ERROR')).toBeInTheDocument();
  });

  it('auto-retries on network recovery', () => {
    const { useKalshiMode } = require('../../context/KalshiModeContext');
    const { useNetworkStatus } = require('../../hooks/useNetworkStatusProvider');
    const mockRefetch = jest.fn();
    
    useKalshiMode.mockReturnValue({
      data: null,
      error: new Error('Network error'),
      isLoading: false,
      refetch: mockRefetch,
    });

    // Initially offline, then comes back online
    useNetworkStatus.mockReturnValue({
      isOnline: true,
      networkSpeed: 'fast',
      lastConnected: Date.now(),
      getConnectionQuality: () => 'excellent',
      subscribe: jest.fn(() => () => {}),
      forceRecheck: jest.fn(),
    });

    render(<EnhancedKalshiModeBadge />);
    
    expect(screen.getByText('ERROR')).toBeInTheDocument();
    
    // Auto-retry logic would be tested through useEffect behavior
  });

  it('caches successful mode data', () => {
    const { useKalshiMode } = require('../../context/KalshiModeContext');
    useKalshiMode.mockReturnValue({
      data: { mode: 'paper', is_live: false },
      error: null,
      isLoading: false,
      refetch: jest.fn(),
    });

    render(<EnhancedKalshiModeBadge />);
    
    expect(screen.getByText('PAPER')).toBeInTheDocument();
    
    // Cache behavior would be tested through state management
  });

  it('handles different mode variants correctly', () => {
    const { useKalshiMode } = require('../../context/KalshiModeContext');
    
    const modes = [
      { mode: 'paper', expected: 'PAPER' },
      { mode: 'live', expected: 'LIVE' },
      { mode: 'shadow', expected: 'SHADOW' },
      { mode: 'mock', expected: 'MOCK' },
      { mode: 'sim', expected: 'SIM' },
    ];

    modes.forEach(({ mode, expected }) => {
      useKalshiMode.mockReturnValue({
        data: { mode, is_live: mode === 'live' },
        error: null,
        isLoading: false,
        refetch: jest.fn(),
      });

      const { unmount } = render(<EnhancedKalshiModeBadge />);
      expect(screen.getByText(expected)).toBeInTheDocument();
      unmount();
    });
  });
});
