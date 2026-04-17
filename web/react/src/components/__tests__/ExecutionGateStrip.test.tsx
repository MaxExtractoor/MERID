/**
 * Tests for ExecutionGateStrip — gate state, mode badge, near-limit warnings.
 */

import { render, screen } from '@testing-library/react';

const mockUseApiData = jest.fn();
jest.mock('../../hooks/useApiData', () => ({
  useApiData: (...args: unknown[]) => mockUseApiData(...args),
}));

jest.mock('../../config/constants', () => ({
  API_BASE_URL: '',
  AUTH_TOKEN_KEY: 'merid-access',
  API_ENDPOINTS: {
    SYSTEM_EXECUTION_GATE: '/api/v1/system/execution-gate',
    KALSHI_RISK: '/api/v1/kalshi/risk',
    KALSHI_GRID_MODE: '/api/v1/kalshi-grid/mode',
  },
  DEFAULTS: { POLLING_INTERVALS: { FAST_REFRESH: 5000, STANDARD: 30000 } },
}));

const mockUseKalshiMode = jest.fn();
jest.mock('../../context/KalshiModeContext', () => ({
  useKalshiMode: (...args: unknown[]) => mockUseKalshiMode(...args),
}));

import ExecutionGateStrip from '../ExecutionGateStrip';

interface MockReason { source: string; severity: string; message: string; hint: string | null; }
interface MockGate { blocked: boolean; safe_to_trade: boolean; gate_state: string; reasons: MockReason[]; }

const GATE_CLEAR: MockGate   = { blocked: false, safe_to_trade: true,  gate_state: 'clear',   reasons: [] };
const GATE_LIMITED: MockGate = { blocked: false, safe_to_trade: true,  gate_state: 'limited', reasons: [{ source: 'risk', severity: 'warning',  message: 'Near exposure limit', hint: 'Reduce size'        }] };
const GATE_BLOCKED: MockGate = { blocked: true,  safe_to_trade: false, gate_state: 'blocked', reasons: [{ source: 'kill', severity: 'critical', message: 'Kill switch active',  hint: 'Reset kill switch' }] };

const RISK_SAFE = { total_exposure: 20, max_exposure: 100, daily_pnl: -5, max_daily_loss: 50, position_count: 2, max_positions: 10 };
const RISK_NEAR = { total_exposure: 80, max_exposure: 100, daily_pnl: -40, max_daily_loss: 50, position_count: 2, max_positions: 10 };

const MODE_PAPER = { mode: 'paper', is_live: false };
const MODE_LIVE  = { mode: 'live',  is_live: true  };

function setupMocks(gate = GATE_CLEAR, risk = RISK_SAFE, mode = MODE_PAPER) {
  mockUseApiData.mockImplementation((endpoint: unknown) => {
    if (typeof endpoint !== 'string') return { data: null };
    if (endpoint.includes('execution-gate')) return { data: gate };
    if (endpoint.includes('kalshi/risk'))    return { data: risk };
    if (endpoint.includes('kalshi-grid/mode')) return { data: mode };
    return { data: null };
  });
  mockUseKalshiMode.mockReturnValue({ data: mode, isLive: mode.is_live });
}

describe('ExecutionGateStrip', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseKalshiMode.mockReturnValue({ data: null, isLive: false });
  });

  describe('Gate state display', () => {
    it('renders nothing when gate data is null', () => {
      mockUseApiData.mockReturnValue({ data: null });
      const { container } = render(<ExecutionGateStrip />);
      expect(container.firstChild).toBeNull();
    });

    it('shows CLEAR when gate is clear', () => {
      setupMocks(GATE_CLEAR);
      render(<ExecutionGateStrip />);
      expect(screen.getByText('CLEAR')).toBeInTheDocument();
    });

    it('shows LIMITED when gate is limited', () => {
      setupMocks(GATE_LIMITED);
      render(<ExecutionGateStrip />);
      expect(screen.getByText('LIMITED')).toBeInTheDocument();
    });

    it('shows BLOCKED when gate is blocked', () => {
      setupMocks(GATE_BLOCKED);
      render(<ExecutionGateStrip />);
      expect(screen.getByText('BLOCKED')).toBeInTheDocument();
    });

    it('shows critical reason message when blocked', () => {
      setupMocks(GATE_BLOCKED);
      render(<ExecutionGateStrip />);
      expect(screen.getByText('Kill switch active')).toBeInTheDocument();
    });

    it('shows hint alongside critical reason', () => {
      setupMocks(GATE_BLOCKED);
      render(<ExecutionGateStrip />);
      expect(screen.getByText(/Reset kill switch/)).toBeInTheDocument();
    });

    it('shows warning message when limited', () => {
      setupMocks(GATE_LIMITED);
      render(<ExecutionGateStrip />);
      expect(screen.getByText(/Near exposure limit/)).toBeInTheDocument();
    });
  });

  describe('Mode badge', () => {
    it('shows PAPER badge in paper mode', () => {
      setupMocks(GATE_CLEAR, RISK_SAFE, MODE_PAPER);
      render(<ExecutionGateStrip />);
      expect(screen.getByText('PAPER')).toBeInTheDocument();
    });

    it('shows LIVE badge in live mode', () => {
      setupMocks(GATE_CLEAR, RISK_SAFE, MODE_LIVE);
      render(<ExecutionGateStrip />);
      expect(screen.getByText('LIVE')).toBeInTheDocument();
    });

    it('defaults to PAPER when mode data unavailable', () => {
      mockUseApiData.mockImplementation((endpoint: unknown) => {
        if (typeof endpoint !== 'string') return { data: null };
        if (endpoint.includes('execution-gate')) return { data: GATE_CLEAR };
        return { data: null };
      });
      render(<ExecutionGateStrip />);
      expect(screen.getByText('PAPER')).toBeInTheDocument();
    });
  });

  describe('Near-limit warnings', () => {
    it('shows exposure utilization', () => {
      setupMocks(GATE_CLEAR, RISK_SAFE);
      render(<ExecutionGateStrip />);
      expect(screen.getByText('Exp: 20%')).toBeInTheDocument();
    });

    it('shows daily loss utilization', () => {
      setupMocks(GATE_CLEAR, RISK_SAFE);
      render(<ExecutionGateStrip />);
      expect(screen.getByText('Loss: 10%')).toBeInTheDocument();
    });

    it('highlights exposure when >= 75%', () => {
      setupMocks(GATE_CLEAR, RISK_NEAR);
      render(<ExecutionGateStrip />);
      expect(screen.getByText('Exp: 80%')).toBeInTheDocument();
    });

    it('highlights loss when >= 75%', () => {
      setupMocks(GATE_CLEAR, RISK_NEAR);
      render(<ExecutionGateStrip />);
      expect(screen.getByText('Loss: 80%')).toBeInTheDocument();
    });

    it('does not render utilization labels when risk data unavailable', () => {
      mockUseApiData.mockImplementation((endpoint: unknown) => {
        if (typeof endpoint !== 'string') return { data: null };
        if (endpoint.includes('execution-gate')) return { data: GATE_CLEAR };
        return { data: null };
      });
      render(<ExecutionGateStrip />);
      // Component only renders Exp/Loss when risk data is present
      expect(screen.queryByText(/Exp:/)).not.toBeInTheDocument();
      expect(screen.queryByText(/Loss:/)).not.toBeInTheDocument();
    });
  });
});
