import { render, screen, fireEvent } from '@testing-library/react';
import Agents from '../Agents';

jest.mock('../../hooks/useApiData');
jest.mock('../../hooks/useMeridSocket');
jest.mock('../../hooks/useAgentsHealth');

import { useApiData } from '../../hooks/useApiData';
import { useMeridSocket } from '../../hooks/useMeridSocket';
import { useAgentsHealth } from '../../hooks/useAgentsHealth';

const mockEmit = jest.fn();
const mockOn = jest.fn();
const mockOff = jest.fn();

beforeEach(() => {
  jest.clearAllMocks();

  (useAgentsHealth as jest.Mock).mockReturnValue({
    rows: [],
    meta: { total: 0, online: 0, offline: 0, degraded: 0, avgConfidence: 0 },
    loading: false,
    error: null,
    lastUpdated: null,
  });

  (useApiData as jest.Mock).mockReturnValue({
    data: [],
    loading: false,
    error: null,
    refetch: jest.fn(),
    lastUpdated: null,
  });

  (useMeridSocket as jest.Mock).mockReturnValue({
    socket: { emit: mockEmit, on: mockOn, off: mockOff, connected: true },
    connected: true,
  });
});

describe('Agents View Flow', () => {
  it('renders without crashing', () => {
    (useApiData as jest.Mock).mockReturnValue({
      data: [
        { id: 'agent-1', name: 'Alpha', role: 'market_maker', status: 'online', confidence: 0.85, pnl: 1200, winRate: 0.65, totalTrades: 100 },
        { id: 'agent-2', name: 'Beta', role: 'trend_follower', status: 'online', confidence: 0.78, pnl: 800, winRate: 0.58, totalTrades: 80 },
      ],
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date('2026-01-30T12:00:00Z'),
    });

    const { container } = render(<Agents />);
    expect(container).toBeTruthy();
    
    // Check for tab buttons - use getAllByText since icons also contain the text
    expect(screen.getAllByText(/Fleet/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Health/i).length).toBeGreaterThanOrEqual(1);
  });

  it('handles tab switching without crashing', () => {
    (useApiData as jest.Mock).mockReturnValue({
      data: [{ id: 'agent-1', name: 'Alpha', role: 'market_maker', status: 'online', confidence: 0.85, pnl: 1200, winRate: 0.65, totalTrades: 100 }],
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date('2026-01-30T12:00:00Z'),
    });

    (useAgentsHealth as jest.Mock).mockReturnValue({
      rows: [{ id: 'agent-1', name: 'Alpha', status: 'online', confidence: 0.85, role: 'market_maker', strategy: 'trend', cpuPercent: 15, memoryMb: 256, taskCount: 5, latencyMs: 12, lastSeen: Date.now() }],
      meta: { total: 1, online: 1, offline: 0, degraded: 0, avgConfidence: 0.85 },
      loading: false,
      error: null,
      lastUpdated: new Date('2026-01-30T12:00:00Z'),
    });

    render(<Agents />);

    // Get tab buttons using role instead of text to avoid ambiguity
    const tabs = screen.getAllByRole('button');
    const healthTab = tabs.find(b => b.textContent?.includes('Health'));
    const fleetTab = tabs.find(b => b.textContent?.includes('Fleet'));
    
    expect(healthTab).toBeTruthy();
    expect(fleetTab).toBeTruthy();
    expect(() => {
      if (healthTab) {
        fireEvent.click(healthTab);
      }
    }).not.toThrow();

    // Click Fleet tab
    expect(() => {
      if (fleetTab) {
        fireEvent.click(fleetTab);
      }
    }).not.toThrow();
  });

  it('handles agent updates without crashing', () => {
    const setAgentsState: {
      data?: Array<Record<string, unknown>>;
      rows?: Array<Record<string, unknown>>;
      meta?: Record<string, number>;
    } = {};

    (useApiData as jest.Mock).mockImplementation(() => ({
      data: setAgentsState.data ?? [],
      loading: false,
      error: null,
      refetch: jest.fn(),
      lastUpdated: new Date('2026-01-30T12:00:00Z'),
    }));

    (useAgentsHealth as jest.Mock).mockImplementation(() => ({
      rows: setAgentsState.rows ?? [],
      meta: setAgentsState.meta ?? { total: 0, online: 0, offline: 0, degraded: 0, avgConfidence: 0 },
      loading: false,
      error: null,
      lastUpdated: new Date('2026-01-30T12:00:00Z'),
    }));

    const { rerender } = render(<Agents />);

    // Simulate agent going offline
    expect(() => {
      setAgentsState.data = [
        { id: 'agent-1', name: 'Alpha', role: 'market_maker', status: 'offline', confidence: 0.5, pnl: 1100, winRate: 0.64, totalTrades: 101 },
      ];
      setAgentsState.rows = [
        { id: 'agent-1', name: 'Alpha', status: 'offline', confidence: 0.5, role: 'market_maker', strategy: 'trend', cpuPercent: 0, memoryMb: 0, taskCount: 0, latencyMs: 0, lastSeen: Date.now() - 60000 },
      ];
      setAgentsState.meta = { total: 1, online: 0, offline: 1, degraded: 0, avgConfidence: 0.5 };
      rerender(<Agents />);
    }).not.toThrow();

    // Simulate new agent joining
    expect(() => {
      setAgentsState.data = [
        { id: 'agent-1', name: 'Alpha', role: 'market_maker', status: 'offline', confidence: 0.5, pnl: 1100, winRate: 0.64, totalTrades: 101 },
        { id: 'agent-3', name: 'Gamma', role: 'arbitrage', status: 'online', confidence: 0.92, pnl: 500, winRate: 0.71, totalTrades: 45 },
      ];
      setAgentsState.rows = [
        { id: 'agent-1', name: 'Alpha', status: 'offline', confidence: 0.5, role: 'market_maker', strategy: 'trend', cpuPercent: 0, memoryMb: 0, taskCount: 0, latencyMs: 0, lastSeen: Date.now() - 60000 },
        { id: 'agent-3', name: 'Gamma', status: 'online', confidence: 0.92, role: 'arbitrage', strategy: 'mean_rev', cpuPercent: 20, memoryMb: 300, taskCount: 8, latencyMs: 8, lastSeen: Date.now() },
      ];
      setAgentsState.meta = { total: 2, online: 1, offline: 1, degraded: 0, avgConfidence: 0.71 };
      rerender(<Agents />);
    }).not.toThrow();
  });
});
