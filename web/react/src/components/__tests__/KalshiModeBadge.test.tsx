/**
 * Tests for KalshiModeBadge Component (consolidated with Enhanced features)
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import KalshiModeBadge from '../KalshiModeBadge';

// Mock the Kalshi mode context with mutable mock
const mockUseKalshiMode = jest.fn();
jest.mock('../../context/KalshiModeContext', () => ({
  useKalshiMode: () => mockUseKalshiMode(),
}));

// Mock the network status provider
const mockUseNetworkStatus = jest.fn();
jest.mock('../../hooks/useNetworkStatusProvider', () => ({
  useNetworkStatus: () => mockUseNetworkStatus(),
}));

describe('KalshiModeBadge', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Default mock implementations
    mockUseKalshiMode.mockReturnValue({
      data: { mode: 'paper', is_live: false },
      error: null,
      isLoading: false,
      refetch: jest.fn(),
    });
    mockUseNetworkStatus.mockReturnValue({
      isOnline: true,
      networkSpeed: 'fast',
    });
  });

  describe('Base Mode (enhanced=false)', () => {
    it('renders paper mode badge', () => {
      render(<KalshiModeBadge />);
      expect(screen.getByText('PAPER')).toBeInTheDocument();
    });

    it('renders live mode badge', () => {
      mockUseKalshiMode.mockReturnValue({
        data: { mode: 'live', is_live: true },
        error: null,
        isLoading: false,
        refetch: jest.fn(),
      });
      render(<KalshiModeBadge />);
      expect(screen.getByText('LIVE')).toBeInTheDocument();
    });

    it('renders shadow mode badge', () => {
      mockUseKalshiMode.mockReturnValue({
        data: { mode: 'shadow', is_live: false },
        error: null,
        isLoading: false,
        refetch: jest.fn(),
      });
      render(<KalshiModeBadge />);
      expect(screen.getByText('SHADOW')).toBeInTheDocument();
    });

    it('shows loading state when loading', () => {
      mockUseKalshiMode.mockReturnValue({
        data: null,
        error: null,
        isLoading: true,
        refetch: jest.fn(),
      });
      render(<KalshiModeBadge />);
      // When loading with no data, shows ellipsis indicator
      expect(document.querySelector('svg')).toBeInTheDocument();
    });
  });

  describe('Enhanced Mode (enhanced=true)', () => {
    it('renders with enhanced features', () => {
      render(<KalshiModeBadge enhanced />);
      expect(screen.getByText('PAPER')).toBeInTheDocument();
    });

    it('shows offline indicator when offline', () => {
      mockUseNetworkStatus.mockReturnValue({
        isOnline: false,
        networkSpeed: 'unknown',
      });
      render(<KalshiModeBadge enhanced />);
      expect(screen.getByText('OFFLINE')).toBeInTheDocument();
    });

    it('shows retry button when error occurs and enhanced mode is on', () => {
      // When there's an error and enhanced mode, should show retry
      mockUseKalshiMode.mockReturnValue({
        data: null,
        error: new Error('Network error'),
        isLoading: false,
        refetch: jest.fn(),
      });
      
      render(<KalshiModeBadge enhanced />);
      
      // Retry button should appear due to error
      expect(screen.getByText('RETRY')).toBeInTheDocument();
    });

    it('shows error state with retry button when error occurs', () => {
      mockUseKalshiMode.mockReturnValue({
        data: null,
        error: new Error('Mode fetch failed'),
        isLoading: false,
        refetch: jest.fn(),
      });
      render(<KalshiModeBadge enhanced />);
      
      // Should show error after max retries reached
      // (We need to trigger retries to reach error state)
      const retryButton = screen.getByText('RETRY');
      expect(retryButton).toBeInTheDocument();
    });

    it('handles retry button click', async () => {
      const mockRefetch = jest.fn();
      mockUseKalshiMode.mockReturnValue({
        data: null,
        error: new Error('Mode fetch failed'),
        isLoading: false,
        refetch: mockRefetch,
      });
      
      render(<KalshiModeBadge enhanced />);
      
      const retryButton = screen.getByText('RETRY');
      fireEvent.click(retryButton);
      
      await waitFor(() => {
        expect(mockRefetch).toHaveBeenCalled();
      });
    });

    it('applies custom className', () => {
      render(<KalshiModeBadge enhanced className="custom-class" />);
      const badge = screen.getByText('PAPER');
      expect(badge.closest('.custom-class')).toBeInTheDocument();
    });

    it('uses fallback mode when no data available', () => {
      mockUseKalshiMode.mockReturnValue({
        data: null,
        error: null,
        isLoading: false,
        refetch: jest.fn(),
      });
      render(<KalshiModeBadge enhanced fallbackMode="shadow" />);
      
      // Should eventually show fallback mode (SHADOW)
      // This may require useEffect to complete
      expect(screen.getByText('SHADOW')).toBeInTheDocument();
    });
  });

  describe('Mode Variants', () => {
    const modes = [
      { mode: 'paper', expected: 'PAPER', is_live: false },
      { mode: 'live', expected: 'LIVE', is_live: true },
      { mode: 'shadow', expected: 'SHADOW', is_live: false },
      { mode: 'unknown', expected: 'UNKNOWN', is_live: false },
    ];

    modes.forEach(({ mode, expected, is_live }) => {
      it(`renders ${expected} for mode="${mode}"`, () => {
        mockUseKalshiMode.mockReturnValue({
          data: { mode, is_live },
          error: null,
          isLoading: false,
          refetch: jest.fn(),
        });
        
        const { unmount } = render(<KalshiModeBadge />);
        expect(screen.getByText(expected)).toBeInTheDocument();
        unmount();
      });
    });
  });
});
