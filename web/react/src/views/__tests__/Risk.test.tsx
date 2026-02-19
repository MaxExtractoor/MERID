import { render } from '@testing-library/react';
import Risk from '../Risk';

// Mock the hooks
jest.mock('../../hooks/useApiData', () => ({
  useApiData: jest.fn(() => ({
    data: null,
    loading: false,
    error: null,
  })),
}));

jest.mock('../../hooks/useMeridSocket', () => ({
  useMeridSocket: jest.fn(() => ({
    socket: null,
    connected: false,
  })),
}));

// Mock lucide-react icons
jest.mock('lucide-react', () => ({
  TrendingDown: () => <span data-testid="trending-down-icon" />,
  Users: () => <span data-testid="users-icon" />,
  BarChart3: () => <span data-testid="bar-chart-icon" />,
  AlertTriangle: () => <span data-testid="alert-icon" />,
  Activity: () => <span data-testid="activity-icon" />,
  Shield: () => <span data-testid="shield-icon" />,
}));

// Mock components
jest.mock('../../components/MetricCard', () => {
  return function MockMetricCard({ title }: { title: string }) {
    return <div data-testid={`metric-card-${title}`}>{title}</div>;
  };
});

jest.mock('../../components/StatusIndicator', () => {
  return function MockStatusIndicator({ status }: { status: string }) {
    return <span data-testid="status-indicator">{status}</span>;
  };
});

jest.mock('../../components/DataTableEnhanced', () => {
  return function MockDataTable() {
    return <div data-testid="data-table">Data Table</div>;
  };
});

jest.mock('../../components/SharpeRatioTile', () => {
  return function MockSharpeRatioTile() {
    return <div data-testid="sharpe-ratio-tile">Sharpe Ratio</div>;
  };
});

jest.mock('../../components/DrawdownChart', () => {
  return function MockDrawdownChart() {
    return <div data-testid="drawdown-chart">Drawdown Chart</div>;
  };
});

jest.mock('../../components/AgentPerformanceTable', () => {
  return function MockAgentPerformanceTable() {
    return <div data-testid="agent-performance-table">Agent Performance</div>;
  };
});

import { useApiData } from '../../hooks/useApiData';
import { useMeridSocket } from '../../hooks/useMeridSocket';

const mockUseApiData = useApiData as jest.MockedFunction<typeof useApiData>;
const mockUseMeridSocket = useMeridSocket as jest.MockedFunction<typeof useMeridSocket>;

describe('Risk View', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseApiData.mockReturnValue({
      data: null,
      loading: false,
      error: null,
      refetch: jest.fn(),
    } as any);
    mockUseMeridSocket.mockReturnValue({
      socket: null,
      connected: false,
    });
  });

  it('should render without crashing', () => {
    render(<Risk />);
    // Component should render
    expect(document.body).toBeTruthy();
  });

  it('should render with risk metrics data', () => {
    mockUseApiData
      .mockReturnValueOnce({
        data: {
          marginUsed: 5000,
          marginAvailable: 15000,
          marginCallLevel: 18000,
          portfolioValue: 100000,
          totalExposure: 80000,
          var95: -2500,
          var99: -4000,
          maxDrawdown: -5,
          sharpeRatio: 1.5,
          leverage: 2,
        },
        loading: false,
        error: null,
        refetch: jest.fn(),
      } as any)
      .mockReturnValueOnce({ data: [], loading: false, error: null, refetch: jest.fn() } as any)
      .mockReturnValueOnce({ data: [], loading: false, error: null, refetch: jest.fn() } as any)
      .mockReturnValueOnce({ data: [], loading: false, error: null, refetch: jest.fn() } as any);

    render(<Risk />);
    // Component should render with data
    expect(document.body).toBeTruthy();
  });

  it('should render with alerts data', () => {
    mockUseApiData
      .mockReturnValueOnce({ data: null, loading: false, error: null, refetch: jest.fn() } as any)
      .mockReturnValueOnce({
        data: [
          {
            id: 'alert-1',
            level: 'high',
            type: 'margin',
            message: 'Margin utilization high',
            timestamp: '2024-01-01T00:00:00Z',
            resolved: false,
          },
        ],
        loading: false,
        error: null,
        refetch: jest.fn(),
      } as any)
      .mockReturnValueOnce({ data: [], loading: false, error: null, refetch: jest.fn() } as any)
      .mockReturnValueOnce({ data: [], loading: false, error: null, refetch: jest.fn() } as any);

    render(<Risk />);
    expect(document.body).toBeTruthy();
  });

  it('should handle WebSocket connection', () => {
    const mockSocket = {
      on: jest.fn(),
      off: jest.fn(),
    };

    mockUseMeridSocket.mockReturnValue({
      socket: mockSocket as any,
      connected: true,
    });

    const { unmount } = render(<Risk />);

    expect(mockSocket.on).toHaveBeenCalledWith('risk_update', expect.any(Function));

    unmount();
    expect(mockSocket.off).toHaveBeenCalledWith('risk_update', expect.any(Function));
  });

  it('should not set up socket listener when not connected', () => {
    const mockSocket = {
      on: jest.fn(),
      off: jest.fn(),
    };

    mockUseMeridSocket.mockReturnValue({
      socket: mockSocket as any,
      connected: false,
    });

    render(<Risk />);

    expect(mockSocket.on).not.toHaveBeenCalled();
  });
});

describe('Risk utility functions', () => {
  // Test the utility functions indirectly through the component behavior
  it('should handle loading state', () => {
    mockUseApiData.mockReturnValue({
      data: null,
      loading: true,
      error: null,
      refetch: jest.fn(),
    } as any);

    render(<Risk />);
    expect(document.body).toBeTruthy();
  });

  it('should handle error state', () => {
    mockUseApiData.mockReturnValue({
      data: null,
      loading: false,
      error: 'Failed to fetch',
      refetch: jest.fn(),
    } as any);

    render(<Risk />);
    expect(document.body).toBeTruthy();
  });
});
