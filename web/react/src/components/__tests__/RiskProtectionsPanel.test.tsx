/**
 * Tests for RiskProtectionsPanel - Critical risk management UI
 * Focus: Deterministic testing of risk controls and protections
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { RiskProtectionsPanel } from '../RiskProtectionsPanel';

// Mock hooks — named exports to match the real module
const mockRefetch = jest.fn();
const mockResetCircuit = jest.fn().mockResolvedValue(true);
const mockToggleKillSwitch = jest.fn().mockResolvedValue(true);

const MOCK_DATA = {
  timestamp: '2024-01-01T00:00:00Z',
  circuit_breaker: {
    state: 'CLOSED' as const,
    state_color: 'green' as const,
    error_count: 2,
    window_seconds: 60,
    threshold: 5,
    last_error_at: null,
    opened_at: null,
    cooldown_seconds: 30,
    half_open_successes: 0,
  },
  lockdown: {
    trading_suite_enabled: true,
    global_mode: 'paper',
    spectator_mode: false,
    lockdown_reason: null,
  },
  risk_limits: {
    max_daily_loss_usd: 10000,
    current_daily_pnl: -1500,
    daily_loss_utilization_pct: 15,
    max_per_symbol_exposure_usd: 5000,
    max_open_orders: 20,
    current_open_orders: 3,
  },
  recent_events: [] as Array<{ timestamp: string; type: string; details: Record<string, unknown> }>,
};

jest.mock('../../hooks/useRiskProtections', () => ({
  __esModule: true,
  useRiskProtections: jest.fn(() => ({
    data: MOCK_DATA,
    loading: false,
    error: null,
    refetch: mockRefetch,
    resetCircuit: mockResetCircuit,
    toggleKillSwitch: mockToggleKillSwitch,
  })),
  getOverallRiskStatus: jest.fn(() => ({ status: 'good', message: 'System Operational' })),
  isTradingBlocked: jest.fn(() => false),
}));

// Must require after mock setup so overrides work
const hookModule = require('../../hooks/useRiskProtections');

describe('RiskProtectionsPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Reset to defaults
    hookModule.useRiskProtections.mockReturnValue({
      data: MOCK_DATA,
      loading: false,
      error: null,
      refetch: mockRefetch,
      resetCircuit: mockResetCircuit,
      toggleKillSwitch: mockToggleKillSwitch,
    });
    hookModule.getOverallRiskStatus.mockReturnValue({ status: 'good', message: 'System Operational' });
    hookModule.isTradingBlocked.mockReturnValue(false);
  });

  describe('Rendering', () => {
    it('renders risk protections panel header', () => {
      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );

      expect(screen.getByText(/Risk & Protections/i)).toBeInTheDocument();
    });

    it('displays circuit breaker section', () => {
      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );

      expect(screen.getByText(/Circuit Breaker/i)).toBeInTheDocument();
      expect(screen.getByText('CLOSED')).toBeInTheDocument();
    });

    it('displays kill switch section', () => {
      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );

      expect(screen.getByText(/Kill Switch/i)).toBeInTheDocument();
      expect(screen.getByText(/Trading Enabled/i)).toBeInTheDocument();
    });

    it('shows loading state', () => {
      hookModule.useRiskProtections.mockReturnValue({
        data: null,
        loading: true,
        error: null,
        refetch: mockRefetch,
        resetCircuit: mockResetCircuit,
        toggleKillSwitch: mockToggleKillSwitch,
      });

      const { container } = render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );

      expect(container.querySelector('.animate-pulse')).toBeInTheDocument();
    });

    it('shows error state', () => {
      hookModule.useRiskProtections.mockReturnValue({
        data: null,
        loading: false,
        error: 'Failed to load protections',
        refetch: mockRefetch,
        resetCircuit: mockResetCircuit,
        toggleKillSwitch: mockToggleKillSwitch,
      });

      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );

      expect(screen.getByText(/Unavailable/i)).toBeInTheDocument();
      expect(screen.getByText(/Failed to load/i)).toBeInTheDocument();
    });
  });

  describe('Circuit Breaker Status', () => {
    it('shows error count and threshold', () => {
      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );

      expect(screen.getByText('2 / 5')).toBeInTheDocument();
    });

    it('shows window and cooldown', () => {
      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );

      expect(screen.getByText('60s')).toBeInTheDocument();
      expect(screen.getByText('30s')).toBeInTheDocument();
    });

    it('shows reset button when circuit is OPEN', () => {
      const openData = {
        ...MOCK_DATA,
        circuit_breaker: { ...MOCK_DATA.circuit_breaker, state: 'OPEN' as const, state_color: 'red' as const },
      };
      hookModule.useRiskProtections.mockReturnValue({
        data: openData,
        loading: false,
        error: null,
        refetch: mockRefetch,
        resetCircuit: mockResetCircuit,
        toggleKillSwitch: mockToggleKillSwitch,
      });
      hookModule.getOverallRiskStatus.mockReturnValue({ status: 'critical', message: 'Circuit OPEN' });

      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );

      expect(screen.getByText('Reset Circuit Breaker')).toBeInTheDocument();
    });
  });

  describe('Kill Switch / Lockdown', () => {
    it('shows EMERGENCY LOCKDOWN button when trading is enabled', () => {
      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );

      expect(screen.getByText('EMERGENCY LOCKDOWN')).toBeInTheDocument();
    });

    it('shows Disable Kill Switch when trading is disabled', () => {
      const lockedData = {
        ...MOCK_DATA,
        lockdown: { ...MOCK_DATA.lockdown, trading_suite_enabled: false },
      };
      hookModule.useRiskProtections.mockReturnValue({
        data: lockedData,
        loading: false,
        error: null,
        refetch: mockRefetch,
        resetCircuit: mockResetCircuit,
        toggleKillSwitch: mockToggleKillSwitch,
      });

      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );

      expect(screen.getByText('TRADING DISABLED')).toBeInTheDocument();
      expect(screen.getByText('Disable Kill Switch')).toBeInTheDocument();
    });

    it('shows TRADING BLOCKED badge when blocked', () => {
      hookModule.isTradingBlocked.mockReturnValue(true);

      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );

      expect(screen.getByText('TRADING BLOCKED')).toBeInTheDocument();
    });
  });

  describe('Risk Limits', () => {
    it('renders risk limits section', () => {
      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );

      expect(screen.getByText(/Risk Limits/i)).toBeInTheDocument();
      expect(screen.getByText(/Daily Loss Limit/i)).toBeInTheDocument();
      expect(screen.getByText(/Max Symbol Exposure/i)).toBeInTheDocument();
      expect(screen.getByText(/Open Orders/i)).toBeInTheDocument();
    });

    it('shows open orders count', () => {
      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );

      expect(screen.getByText('3 / 20')).toBeInTheDocument();
    });
  });

  describe('User Interactions', () => {
    it('calls refetch on refresh button click', () => {
      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );

      const refreshBtn = screen.getByLabelText('Refresh');
      fireEvent.click(refreshBtn);

      expect(mockRefetch).toHaveBeenCalled();
    });

    it('calls resetCircuit on reset button click', async () => {
      window.confirm = jest.fn(() => true);
      const openData = {
        ...MOCK_DATA,
        circuit_breaker: { ...MOCK_DATA.circuit_breaker, state: 'OPEN' as const, state_color: 'red' as const },
      };
      hookModule.useRiskProtections.mockReturnValue({
        data: openData,
        loading: false,
        error: null,
        refetch: mockRefetch,
        resetCircuit: mockResetCircuit,
        toggleKillSwitch: mockToggleKillSwitch,
      });

      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );

      fireEvent.click(screen.getByText('Reset Circuit Breaker'));

      await waitFor(() => {
        expect(window.confirm).toHaveBeenCalled();
        expect(mockResetCircuit).toHaveBeenCalled();
      });
    });

    it('calls toggleKillSwitch on lockdown button click', async () => {
      window.confirm = jest.fn(() => true);

      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );

      fireEvent.click(screen.getByText('EMERGENCY LOCKDOWN'));

      await waitFor(() => {
        expect(window.confirm).toHaveBeenCalled();
        expect(mockToggleKillSwitch).toHaveBeenCalledWith('enable');
      });
    });

    it('does not act if confirm is cancelled', async () => {
      window.confirm = jest.fn(() => false);

      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );

      fireEvent.click(screen.getByText('EMERGENCY LOCKDOWN'));

      await waitFor(() => {
        expect(window.confirm).toHaveBeenCalled();
        expect(mockToggleKillSwitch).not.toHaveBeenCalled();
      });
    });
  });

  describe('Error retry', () => {
    it('shows retry button on error', () => {
      hookModule.useRiskProtections.mockReturnValue({
        data: null,
        loading: false,
        error: 'Network error',
        refetch: mockRefetch,
        resetCircuit: mockResetCircuit,
        toggleKillSwitch: mockToggleKillSwitch,
      });

      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );

      const retryBtn = screen.getByText('Retry');
      fireEvent.click(retryBtn);

      expect(mockRefetch).toHaveBeenCalled();
    });
  });

  describe('Accessibility', () => {
    it('has accessible refresh button', () => {
      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );

      expect(screen.getByLabelText('Refresh')).toBeInTheDocument();
    });
  });
});
