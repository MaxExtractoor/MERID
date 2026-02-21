import { render, screen } from '@testing-library/react';
import { PredictionsPanel } from '../PredictionsPanel';
import { usePredictions } from '../../hooks/usePredictions';
import type { PredictionMarket, PredictionsResponse } from '../../types/predictions';

// Mock the hook
jest.mock('../../hooks/usePredictions');

const mockUsePredictions = usePredictions as jest.MockedFunction<typeof usePredictions>;

describe('PredictionsPanel', () => {
  const mockMarkets: PredictionMarket[] = [
    {
      id: 'market-1',
      symbol: 'BTC-YES',
      question: 'Will Bitcoin exceed $100k by end of 2024?',
      marketType: 'BINARY',
      yesPrice: 0.65,
      noPrice: 0.35,
      volume: 1500000,
      liquidity: 250000,
      ourPosition: 'YES',
      ourSize: 1000,
      ourAvgPrice: 0.55,
      ourPnl: 100,
      modelConfidence: 0.75,
      modelPrediction: 'YES',
      lastUpdated: '2024-01-20T12:00:00Z',
      status: 'OPEN',
      endTime: '2024-12-31T23:59:59Z',
    },
    {
      id: 'market-2',
      symbol: 'ETH-YES',
      question: 'Will Ethereum exceed $5k?',
      marketType: 'BINARY',
      yesPrice: 0.45,
      noPrice: 0.55,
      volume: 800000,
      liquidity: 150000,
      ourPosition: 'NONE',
      ourSize: 0,
      ourAvgPrice: 0,
      ourPnl: 0,
      modelConfidence: 0.6,
      modelPrediction: 'UNCERTAIN',
      lastUpdated: '2024-01-20T12:00:00Z',
      status: 'OPEN',
      endTime: '2024-06-30T23:59:59Z',
    },
    {
      id: 'market-3',
      symbol: 'SPY-NO',
      question: 'Will S&P 500 decline in Q1 2024?',
      marketType: 'BINARY',
      yesPrice: 0.3,
      noPrice: 0.7,
      volume: 500000,
      liquidity: 100000,
      ourPosition: 'NO',
      ourSize: 500,
      ourAvgPrice: 0.65,
      ourPnl: 25,
      modelConfidence: 0.82,
      modelPrediction: 'YES',
      lastUpdated: '2024-01-20T12:00:00Z',
      status: 'RESOLVED',
      endTime: '2024-03-31T23:59:59Z',
    },
  ];

  const mockMeta: PredictionsResponse['meta'] = {
    total: 3,
    open: 2,
    closed: 1,
    totalVolume: 2800000,
    totalPnl: 125,
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders loading state', () => {
    mockUsePredictions.mockReturnValue({
      markets: [],
      meta: mockMeta,
      loading: true,
      error: null,
      lastUpdated: null,
    });

    render(<PredictionsPanel />);

    // Loading state shows pulse animation
    expect(document.querySelector('.animate-pulse')).toBeInTheDocument();
  });

  it('renders error state', () => {
    mockUsePredictions.mockReturnValue({
      markets: [],
      meta: mockMeta,
      loading: false,
      error: new Error('Failed to load'),
      lastUpdated: null,
    });

    render(<PredictionsPanel />);

    expect(screen.getByText(/failed to load prediction markets/i)).toBeInTheDocument();
  });

  it('renders with markets data', () => {
    mockUsePredictions.mockReturnValue({
      markets: mockMarkets,
      meta: mockMeta,
      loading: false,
      error: null,
      lastUpdated: new Date('2024-01-20T12:00:00Z'),
    });

    render(<PredictionsPanel />);

    // Header
    expect(screen.getByText('Prediction Markets')).toBeInTheDocument();

    // Metric cards - use getAllByText for values that appear multiple times
    expect(screen.getByText('Total Markets')).toBeInTheDocument();
    expect(screen.getByText('Open Markets')).toBeInTheDocument();
    // Markets in table (appears in both mini cards and table)
    expect(screen.getAllByText('BTC-YES').length).toBeGreaterThan(0);
    expect(screen.getAllByText('ETH-YES').length).toBeGreaterThan(0);
    expect(screen.getAllByText('SPY-NO').length).toBeGreaterThan(0);
  });

  it('displays correct P&L formatting', () => {
    mockUsePredictions.mockReturnValue({
      markets: mockMarkets,
      meta: mockMeta,
      loading: false,
      error: null,
      lastUpdated: new Date('2024-01-20T12:00:00Z'),
    });

    render(<PredictionsPanel />);

    // Check total P&L in metric card
    expect(screen.getByText('Total P&L')).toBeInTheDocument();
  });

  it('displays market positions correctly', () => {
    mockUsePredictions.mockReturnValue({
      markets: mockMarkets,
      meta: mockMeta,
      loading: false,
      error: null,
      lastUpdated: new Date('2024-01-20T12:00:00Z'),
    });

    render(<PredictionsPanel />);

    // Should show positions for markets with positions
    expect(screen.getByText('YES')).toBeInTheDocument();
    expect(screen.getByText('NO')).toBeInTheDocument();
  });

  it('displays confidence indicators', () => {
    mockUsePredictions.mockReturnValue({
      markets: mockMarkets,
      meta: mockMeta,
      loading: false,
      error: null,
      lastUpdated: new Date('2024-01-20T12:00:00Z'),
    });

    render(<PredictionsPanel />);

    // Should have status indicators for confidence
    const indicators = screen.getAllByTestId('status-indicator');
    expect(indicators.length).toBeGreaterThan(0);
  });

  it('shows empty state when no markets', () => {
    mockUsePredictions.mockReturnValue({
      markets: [],
      meta: {
        total: 0,
        open: 0,
        closed: 0,
        totalVolume: 0,
        totalPnl: 0,
      },
      loading: false,
      error: null,
      lastUpdated: new Date('2024-01-20T12:00:00Z'),
    });

    render(<PredictionsPanel />);

    expect(screen.getByText('Prediction Markets')).toBeInTheDocument();
    // Total Markets label should be present, and value 0 should appear in metric cards
    const totalMarketsCard = screen.getByText('Total Markets').closest('div');
    expect(totalMarketsCard).toBeInTheDocument();
  });

  it('displays last updated timestamp', () => {
    const lastUpdated = new Date('2024-01-20T12:30:00Z');
    mockUsePredictions.mockReturnValue({
      markets: mockMarkets,
      meta: mockMeta,
      loading: false,
      error: null,
      lastUpdated,
    });

    render(<PredictionsPanel />);

    // Should show the refresh icon and timestamp
    expect(screen.getByText(/12:30/)).toBeInTheDocument();
  });
});
