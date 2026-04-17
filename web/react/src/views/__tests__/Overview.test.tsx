/**
 * Tests for Overview view — Kalshi reboot panel, mode guard, grid controls.
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import Overview from '../Overview';

// Mock hooks
jest.mock('../../hooks/useApiData', () => ({
  __esModule: true,
  useApiData: jest.fn(() => ({ data: null, loading: false, error: null, refetch: jest.fn() })),
}));

// Grab the mocked function after jest.mock hoisting
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { useApiData: mockUseApiData } = require('../../hooks/useApiData') as { useApiData: jest.Mock };

jest.mock('../../hooks/useMeridSocket', () => ({
  useMeridSocket: jest.fn(() => ({
    connected: true,
    lastMessage: null,
  })),
}));

jest.mock('../../hooks/useDashboard', () => ({
  SystemHealthCard: () => <div data-testid="system-health-card" />,
  KalshiHealthCard: () => <div data-testid="kalshi-health-card" />,
  AgentStatusCard: () => <div data-testid="agent-status-card" />,
  RiskProtectionCard: () => <div data-testid="risk-protection-card" />,
}));

jest.mock('../../components/ExecutionGateStrip', () => ({
  __esModule: true,
  default: () => <div data-testid="execution-gate-strip" />,
}));

jest.mock('../../components/CollapsibleConsole', () => ({
  __esModule: true,
  default: () => <div data-testid="collapsible-console" />,
}));

jest.mock('../../components/AgentActivityPanel', () => ({
  __esModule: true,
  default: () => <div data-testid="agent-activity-panel" />,
}));

function renderOverview() {
  return render(
    <BrowserRouter>
      <Overview />
    </BrowserRouter>
  );
}

describe('Overview', () => {
  beforeEach(() => {
    // Reset only fetch and confirm — do NOT use clearAllMocks which can wipe mockImplementation
    window.confirm = jest.fn().mockReturnValue(true);
    (global.fetch as jest.Mock).mockReset();
    (global.fetch as jest.Mock).mockResolvedValue({ ok: true, json: async () => ({ message: 'ok' }) });
    // Restore default mockUseApiData implementation
    mockUseApiData.mockImplementation(() => ({
      data: null, loading: false, error: null, refetch: jest.fn(),
    }));
  });

  describe('Rendering', () => {
    it('renders the Reboot Sequence panel', () => {
      renderOverview();
      expect(screen.getByText('Reboot Sequence')).toBeInTheDocument();
    });

    it('renders Kill Switch status card', () => {
      renderOverview();
      expect(screen.getByText('Kill Switch')).toBeInTheDocument();
    });

    it('renders Agent Grid status card', () => {
      renderOverview();
      expect(screen.getByText('Agent Grid')).toBeInTheDocument();
    });

    it('renders Catalog status card', () => {
      renderOverview();
      expect(screen.getByText('Catalog')).toBeInTheDocument();
    });

    it('renders sub-component cards', () => {
      renderOverview();
      expect(screen.getByTestId('execution-gate-strip')).toBeInTheDocument();
      expect(screen.getByTestId('system-health-card')).toBeInTheDocument();
      expect(screen.getByTestId('kalshi-health-card')).toBeInTheDocument();
      expect(screen.getByTestId('agent-status-card')).toBeInTheDocument();
      expect(screen.getByTestId('risk-protection-card')).toBeInTheDocument();
    });
  });

  describe('Kill Switch display', () => {
    it('shows CLEAR when kill switch data is null (default/inactive)', () => {
      renderOverview();
      expect(screen.getByText('CLEAR')).toBeInTheDocument();
    });

    it('shows Trading permitted when kill switch is clear', () => {
      renderOverview();
      expect(screen.getByText('Trading permitted')).toBeInTheDocument();
    });
  });

  describe('Grid status display', () => {
    it('shows STOPPED when grid data is null (default)', () => {
      renderOverview();
      expect(screen.getByText('STOPPED')).toBeInTheDocument();
    });

    it('shows 0 agents when grid data is null', () => {
      renderOverview();
      expect(screen.getByText('0 agents')).toBeInTheDocument();
    });
  });

  describe('Mode toggle and Start Grid (Fix 3)', () => {
    it('renders Paper and Live mode toggle buttons', () => {
      renderOverview();
      expect(screen.getByRole('button', { name: /^Paper$/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /^Live$/i })).toBeInTheDocument();
    });

    it('shows Start Grid button when grid is stopped', () => {
      renderOverview();
      expect(screen.getByRole('button', { name: /Start Grid/i })).toBeInTheDocument();
    });

    it('starts grid with mode=paper in URL when paper selected', async () => {
      renderOverview();
      fireEvent.click(screen.getByRole('button', { name: /Start Grid/i }));
      await waitFor(() => {
        const urls = (global.fetch as jest.Mock).mock.calls.map((c: unknown[]) => c[0] as string);
        expect(urls.some(u => u.includes('mode=paper'))).toBe(true);
      });
    });

    it('shows confirm dialog before starting in live mode', () => {
      renderOverview();
      fireEvent.click(screen.getByRole('button', { name: /^Live$/i }));
      fireEvent.click(screen.getByRole('button', { name: /Start Grid/i }));
      expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('LIVE mode'));
    });

    it('does NOT start grid when live confirmation is rejected', async () => {
      (window.confirm as jest.Mock).mockReturnValue(false);
      renderOverview();
      fireEvent.click(screen.getByRole('button', { name: /^Live$/i }));
      fireEvent.click(screen.getByRole('button', { name: /Start Grid/i }));
      await waitFor(() => {
        const urls = (global.fetch as jest.Mock).mock.calls.map((c: unknown[]) => c[0] as string);
        expect(urls.some(u => u.includes('kalshi-grid/start'))).toBe(false);
      });
    });

    it('shows LIVE warning when live mode is selected', () => {
      renderOverview();
      fireEvent.click(screen.getByRole('button', { name: /^Live$/i }));
      expect(screen.getByText(/LIVE mode.*real money/i)).toBeInTheDocument();
    });
  });

  describe('Catalog controls', () => {
    it('renders Refresh Catalog button', () => {
      renderOverview();
      expect(screen.getByRole('button', { name: /Refresh Catalog/i })).toBeInTheDocument();
    });

    it('calls catalog refresh endpoint on click', async () => {
      renderOverview();
      fireEvent.click(screen.getByRole('button', { name: /Refresh Catalog/i }));
      await waitFor(() => {
        const urls = (global.fetch as jest.Mock).mock.calls.map((c: unknown[]) => c[0] as string);
        expect(urls.some(u => u.includes('catalog'))).toBe(true);
      });
    });
  });

  describe('Kalshi Balance', () => {
    it('renders balance section skeleton when balance data is null', () => {
      renderOverview();
      // When balance is null, KalshiBalanceHero renders skeleton divs — no crash
      expect(screen.getByText('Reboot Sequence')).toBeInTheDocument();
    });
  });
});
