/**
 * Tests for Overview view - Dashboard landing page
 * Focus: Deterministic testing of dashboard metrics and data display
 */

import { render, screen, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import Overview from '../Overview';

// Mock hooks
jest.mock('../../hooks/useApiData', () => ({
  __esModule: true,
  default: jest.fn(() => ({
    data: {
      portfolio_value: 100000,
      daily_pnl: 2500,
      daily_pnl_pct: 2.5,
      total_positions: 5,
      active_agents: 3,
    },
    loading: false,
    error: null,
  })),
}));

jest.mock('../../hooks/useMeridSocket', () => ({
  useMeridSocket: jest.fn(() => ({
    connected: true,
    lastMessage: null,
  })),
}));

describe('Overview', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Rendering', () => {
    it('renders overview dashboard', () => {
      render(
        <BrowserRouter>
          <Overview />
        </BrowserRouter>
      );
      
      expect(screen.getByText(/Overview/i)).toBeInTheDocument();
    });

    it('displays portfolio metrics', () => {
      render(
        <BrowserRouter>
          <Overview />
        </BrowserRouter>
      );
      
      expect(screen.getByText(/100,000/)).toBeInTheDocument();
      expect(screen.getByText(/2,500/)).toBeInTheDocument();
    });

    it('shows loading state', () => {
      const useApiData = require('../../hooks/useApiData').default;
      useApiData.mockReturnValue({
        data: null,
        loading: true,
        error: null,
      });

      render(
        <BrowserRouter>
          <Overview />
        </BrowserRouter>
      );
      
      expect(screen.getByText(/Loading/i)).toBeInTheDocument();
    });

    it('shows error state', () => {
      const useApiData = require('../../hooks/useApiData').default;
      useApiData.mockReturnValue({
        data: null,
        loading: false,
        error: 'Failed to load dashboard data',
      });

      render(
        <BrowserRouter>
          <Overview />
        </BrowserRouter>
      );
      
      expect(screen.getByText(/Failed to load/i)).toBeInTheDocument();
    });
  });

  describe('Metrics Display', () => {
    it('displays portfolio value', () => {
      render(
        <BrowserRouter>
          <Overview />
        </BrowserRouter>
      );
      
      expect(screen.getByText(/Portfolio Value/i)).toBeInTheDocument();
      expect(screen.getByText(/100,000/)).toBeInTheDocument();
    });

    it('displays daily P&L', () => {
      render(
        <BrowserRouter>
          <Overview />
        </BrowserRouter>
      );
      
      expect(screen.getByText(/Daily P&L/i)).toBeInTheDocument();
      expect(screen.getByText(/2,500/)).toBeInTheDocument();
    });

    it('displays position count', () => {
      render(
        <BrowserRouter>
          <Overview />
        </BrowserRouter>
      );
      
      expect(screen.getByText(/Positions/i)).toBeInTheDocument();
      expect(screen.getByText(/5/)).toBeInTheDocument();
    });

    it('displays active agents', () => {
      render(
        <BrowserRouter>
          <Overview />
        </BrowserRouter>
      );
      
      expect(screen.getByText(/Active Agents/i)).toBeInTheDocument();
      expect(screen.getByText(/3/)).toBeInTheDocument();
    });
  });

  describe('Real-time Updates', () => {
    it('updates metrics on WebSocket message', async () => {
      const { useMeridSocket } = require('../../hooks/useMeridSocket');
      useMeridSocket.mockReturnValue({
        connected: true,
        lastMessage: {
          type: 'portfolio_update',
          data: {
            portfolio_value: 105000,
            daily_pnl: 5000,
          },
        },
      });

      render(
        <BrowserRouter>
          <Overview />
        </BrowserRouter>
      );
      
      await waitFor(() => {
        expect(screen.getByText(/105,000/)).toBeInTheDocument();
      });
    });
  });

  describe('Edge Cases', () => {
    it('handles zero values', () => {
      const useApiData = require('../../hooks/useApiData').default;
      useApiData.mockReturnValue({
        data: {
          portfolio_value: 0,
          daily_pnl: 0,
          daily_pnl_pct: 0,
          total_positions: 0,
          active_agents: 0,
        },
        loading: false,
        error: null,
      });

      render(
        <BrowserRouter>
          <Overview />
        </BrowserRouter>
      );
      
      expect(screen.getAllByText(/0/).length).toBeGreaterThan(0);
    });

    it('handles negative P&L', () => {
      const useApiData = require('../../hooks/useApiData').default;
      useApiData.mockReturnValue({
        data: {
          portfolio_value: 95000,
          daily_pnl: -5000,
          daily_pnl_pct: -5.0,
          total_positions: 3,
          active_agents: 2,
        },
        loading: false,
        error: null,
      });

      render(
        <BrowserRouter>
          <Overview />
        </BrowserRouter>
      );
      
      expect(screen.getByText(/-5,000/)).toBeInTheDocument();
    });

    it('handles missing data fields', () => {
      const useApiData = require('../../hooks/useApiData').default;
      useApiData.mockReturnValue({
        data: {},
        loading: false,
        error: null,
      });

      render(
        <BrowserRouter>
          <Overview />
        </BrowserRouter>
      );
      
      expect(screen.getByText(/Overview/i)).toBeInTheDocument();
    });
  });

  describe('Accessibility', () => {
    it('has accessible metric cards', () => {
      render(
        <BrowserRouter>
          <Overview />
        </BrowserRouter>
      );
      
      const headings = screen.getAllByRole('heading');
      expect(headings.length).toBeGreaterThan(0);
    });
  });
});
