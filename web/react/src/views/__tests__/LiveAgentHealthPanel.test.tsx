import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { LiveAgentHealthPanel } from '../LiveAgentHealthPanel';
import { useAgentsHealth } from '../../hooks/useAgentsHealth';

// Mock the hook
jest.mock('../../hooks/useAgentsHealth');

describe('LiveAgentHealthPanel', () => {
  const mockUseAgentsHealth = useAgentsHealth as jest.MockedFunction<typeof useAgentsHealth>;

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders metric cards with correct counts', () => {
    mockUseAgentsHealth.mockReturnValue({
      rows: [
        {
          id: 'agent-001',
          name: 'Alpha',
          role: 'SCALPER',
          strategy: 'MEAN_REVERSION',
          cluster: 'primary',
          status: 'ONLINE',
          cpuPercent: 23.4,
          memoryMb: 512,
          taskCount: 3,
          latencyMs: 12,
          lastSeen: '2026-01-30T23:40:00Z',
        },
        {
          id: 'agent-002',
          name: 'Beta',
          role: 'ARBITRAGE',
          strategy: 'CROSS_EXCHANGE',
          cluster: 'primary',
          status: 'DEGRADED',
          cpuPercent: 78.2,
          memoryMb: 1024,
          taskCount: 8,
          latencyMs: 145,
          lastSeen: '2026-01-30T23:41:12Z',
        },
      ],
      meta: { total: 2, online: 1, degraded: 1, offline: 0 },
      loading: false,
      error: null,
      lastUpdated: null,
    });

    render(<LiveAgentHealthPanel />);

    expect(screen.getByText('Total Agents')).toBeInTheDocument();
    expect(screen.getByText('Online')).toBeInTheDocument();
    expect(screen.getByText('Degraded')).toBeInTheDocument();
    expect(screen.getByText('Offline')).toBeInTheDocument();
    
    // Counts appear in metric cards - use getAllByText for values that appear multiple times
    expect(screen.getAllByText('2')).toHaveLength(1); // total
    expect(screen.getAllByText('1')).toHaveLength(2); // online + degraded
    expect(screen.getAllByText('0')).toHaveLength(1); // offline
  });

  it('renders data table with agent rows', () => {
    mockUseAgentsHealth.mockReturnValue({
      rows: [
        {
          id: 'agent-001',
          name: 'Alpha',
          role: 'SCALPER',
          strategy: 'MEAN_REVERSION',
          cluster: 'primary',
          status: 'ONLINE',
          cpuPercent: 23.4,
          memoryMb: 512,
          taskCount: 3,
          latencyMs: 12,
          lastSeen: '2026-01-30T23:40:00Z',
        },
      ],
      meta: { total: 1, online: 1, degraded: 0, offline: 0 },
      loading: false,
      error: null,
      lastUpdated: null,
    });

    render(<LiveAgentHealthPanel />);

    // Check for column headers
    expect(screen.getByText('Agent')).toBeInTheDocument();
    expect(screen.getByText('Role')).toBeInTheDocument();
    expect(screen.getByText('Status')).toBeInTheDocument();
    
    // Check for agent data
    expect(screen.getByText('Alpha')).toBeInTheDocument();
    expect(screen.getByText('SCALPER')).toBeInTheDocument();
  });

  it('displays loading state', () => {
    mockUseAgentsHealth.mockReturnValue({
      rows: [],
      meta: { total: 0, online: 0, degraded: 0, offline: 0 },
      loading: true,
      error: null,
      lastUpdated: null,
    });

    render(<LiveAgentHealthPanel />);

    expect(screen.getByText('Loading agents...')).toBeInTheDocument();
  });

  it('displays error state', () => {
    mockUseAgentsHealth.mockReturnValue({
      rows: [],
      meta: { total: 0, online: 0, degraded: 0, offline: 0 },
      loading: false,
      error: new Error('Failed to fetch agents'),
      lastUpdated: null,
    });

    render(<LiveAgentHealthPanel />);

    expect(screen.getByText('Error loading agent health')).toBeInTheDocument();
    expect(screen.getByText('Failed to fetch agents')).toBeInTheDocument();
  });

  it('renders empty state when no agents', () => {
    mockUseAgentsHealth.mockReturnValue({
      rows: [],
      meta: { total: 0, online: 0, degraded: 0, offline: 0 },
      loading: false,
      error: null,
      lastUpdated: null,
    });

    render(<LiveAgentHealthPanel />);

    expect(screen.getByText('Total Agents')).toBeInTheDocument();
    // All counts are 0 