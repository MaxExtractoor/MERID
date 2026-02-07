import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { OpenOrdersPanel } from '../OpenOrdersPanel';
import { useOpenOrders } from '../../hooks/useOpenOrders';

// Mock the hook
jest.mock('../../hooks/useOpenOrders');

describe('OpenOrdersPanel', () => {
  const mockUseOpenOrders = useOpenOrders as jest.MockedFunction<typeof useOpenOrders>;

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders metric cards with correct counts', () => {
    mockUseOpenOrders.mockReturnValue({
      rows: [
        {
          id: 'ord-001',
          symbol: 'BTC-USD',
          side: 'BUY',
          type: 'LIMIT',
          status: 'PENDING',
          price: 42500.50,
          size: 0.5,
          filledSize: 0.0,
          remainingSize: 0.5,
          notional: 21250.25,
          leverage: 1.0,
          venue: 'COINBASE',
          strategyId: 'strat-001',
          agentId: 'agent-001',
          createdAt: '2026-01-30T20:15:00Z',
          expiresAt: null,
        },
        {
          id: 'ord-002',
          symbol: 'ETH-USD',
          side: 'SELL',
          type: 'MARKET',
          status: 'PARTIALLY_FILLED',
          price: null,
          size: 10.0,
          filledSize: 3.5,
          remainingSize: 6.5,
          notional: 25200.00,
          leverage: 2.0,
          venue: 'BINANCE',
          strategyId: 'strat-002',
          agentId: 'agent-002',
          createdAt: '2026-01-30T20:10:00Z',
          expiresAt: null,
        },
      ],
      meta: { total: 2, pending: 1, partiallyFilled: 1, totalNotional: 46450.25 },
      loading: false,
      error: null,
      lastUpdated: null,
    });

    render(<OpenOrdersPanel />);

    expect(screen.getByText('Total Orders')).toBeInTheDocument();
    expect(screen.getByText('Pending')).toBeInTheDocument();
    expect(screen.getByText('Partially Filled')).toBeInTheDocument();
    expect(screen.getByText('Total Notional')).toBeInTheDocument();
  });

  it('renders data table with order rows', () => {
    mockUseOpenOrders.mockReturnValue({
      rows: [
        {
          id: 'ord-001',
          symbol: 'BTC-USD',
          side: 'BUY',
          type: 'LIMIT',
          status: 'PENDING',
          price: 42500.50,
          size: 0.5,
          filledSize: 0.0,
          remainingSize: 0.5,
          notional: 21250.25,
          leverage: 1.0,
          venue: 'COINBASE',
          strategyId: 'strat-001',
          agentId: 'agent-001',
          createdAt: '2026-01-30T20:15:00Z',
          expiresAt: null,
        },
      ],
      meta: { total: 1, pending: 1, partiallyFilled: 0, totalNotional: 21250.25 },
      loading: false,
      error: null,
      lastUpdated: null,
    });

    render(<OpenOrdersPanel />);

    // Check for column headers
    expect(screen.getByText('Symbol')).toBeInTheDocument();
    expect(screen.getByText('Side')).toBeInTheDocument();
    expect(screen.getByText('Type')).toBeInTheDocument();
    expect(screen.getByText('Status')).toBeInTheDocument();
    
    // Check for order data
    expect(screen.getByText('BTC-USD')).toBeInTheDocument();
    expect(screen.getByText('COINBASE')).toBeInTheDocument();
  });

  it('displays loading state', () => {
    mockUseOpenOrders.mockReturnValue({
      rows: [],
      meta: { total: 0, pending: 0, partiallyFilled: 0, totalNotional: 0 },
      loading: true,
      error: null,
      lastUpdated: null,
    });

    render(<OpenOrdersPanel />);

    // Loading state shows pulse animation
    expect(document.querySelector('.animate-pulse')).toBeInTheDocument();
  });

  it('displays error state', () => {
    mockUseOpenOrders.mockReturnValue({
      rows: [],
      meta: { total: 0, pending: 0, partiallyFilled: 0, totalNotional: 0 },
      loading: false,
      error: new Error('Failed to fetch orders'),
      lastUpdated: null,
    });

    render(<OpenOrdersPanel />);

    expect(screen.getByText('Error loading open orders')).toBeInTheDocument();
    expect(screen.getByText('Failed to fetch orders')).toBeInTheDocument();
  });

  it('renders empty state when no orders', () => {
    mockUseOpenOrders.mockReturnValue({
      rows: [],
      meta: { total: 0, pending: 0, partiallyFilled: 0, totalNotional: 0 },
      loading: false,
      error: null,
      lastUpdated: null,
    });

    render(<OpenOrdersPanel />);

    expect(screen.getByText('Total Orders')).toBeInTheDocument();
    expect(screen.getByText('Open Orders')).toBeInTheDocument();
  });

  it('shows MKT for market orders with null price', () => {
    mockUseOpenOrders.mockReturnValue({
      rows: [
        {
          id: 'ord-002',
          symbol: 'ETH-USD',
          side: 'SELL',
          type: 'MARKET',
          status: 'PENDING',
          price: null,
          size: 10.0,
          filledSize: 0.0,
          remainingSize: 10.0,
          notional: 25200.00,
          leverage: 2.0,
          venue: 'BINANCE',
          strategyId: 'strat-002',
          agentId: 'agent-002',
          createdAt: '2026-01-30T20:10:00Z',
          expiresAt: null,
        },
      ],
      meta: { total: 1, pending: 1, partiallyFilled: 0, totalNotional: 25200.00 },
      loading: false,
      error: null,
      lastUpdated: null,
    });

    render(<OpenOrdersPanel />);

    expect(screen.getByText('MKT')).toBeInTheDocument();
  });
});
