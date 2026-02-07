import { render, screen, act } from '@testing-library/react';
import Predictions from '../Predictions';

jest.mock('../../hooks/usePredictions');

import { usePredictions } from '../../hooks/usePredictions';

beforeEach(() => {
  jest.clearAllMocks();

  (usePredictions as jest.Mock).mockReturnValue({
    markets: [],
    meta: { total: 0, open: 0, closed: 0, totalVolume: 0, totalPnl: 0 },
    loading: false,
    error: null,
    lastUpdated: null,
  });
});

describe('Predictions View Flow', () => {
  it('renders without crashing', () => {
    (usePredictions as jest.Mock).mockReturnValue({
      markets: [
        {
          id: 'market-1',
          symbol: 'BTC-YES',
          question: 'Will Bitcoin exceed $100k?',
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
          status: 'OPEN',
          endTime: '2026-12-31T23:59:59Z',
          lastUpdated: '2026-01-30T12:00:00Z',
        },
      ],
      meta: { total: 1, open: 1, closed: 0, totalVolume: 1500000, totalPnl: 100 },
      loading: false,
      error: null,
      lastUpdated: new Date('2026-01-30T12:00:00Z'),
    });

    const { container } = render(<Predictions />);
    expect(container).toBeTruthy();
    // Header text appears in both page title and possibly panel - use getAllByText
    expect(screen.getAllByText(/Prediction Markets/i).length).toBeGreaterThanOrEqual(1);
  });

  it('handles price updates without crashing', () => {
    const setMarketState: any = {};

    (usePredictions as jest.Mock).mockImplementation(() => ({
      markets: setMarketState.markets ?? [],
      meta: setMarketState.meta ?? { total: 0, open: 0, closed: 0, totalVolume: 0, totalPnl: 0 },
      loading: false,
      error: null,
      lastUpdated: new Date('2026-01-30T12:00:00Z'),
    }));

    const { rerender } = render(<Predictions />);

    // Simulate price change
    expect(() => {
      act(() => {
        setMarketState.markets = [
          {
            id: 'market-1',
            symbol: 'BTC-YES',
            question: 'Will Bitcoin exceed $100k?',
            marketType: 'BINARY',
            yesPrice: 0.75, // Changed from 0.65
            noPrice: 0.25,
            volume: 1600000,
            liquidity: 260000,
            ourPosition: 'YES',
            ourSize: 1000,
            ourAvgPrice: 0.55,
            ourPnl: 200, // Increased due to price move
            modelConfidence: 0.78,
            modelPrediction: 'YES',
            status: 'OPEN',
            endTime: '2026-12-31T23:59:59Z',
            lastUpdated: '2026-01-30T12:05:00Z',
          },
        ];
        setMarketState.meta = { total: 1, open: 1, closed: 0, totalVolume: 1600000, totalPnl: 200 };
        rerender(<Predictions />);
      });
    }).not.toThrow();
  });

  it('handles position + resolution updates without crashing', () => {
    const setMarketState: any = {};

    (usePredictions as jest.Mock).mockImplementation(() => ({
      markets: setMarketState.markets ?? [],
      meta: setMarketState.meta ?? { total: 0, open: 0, closed: 0, totalVolume: 0, totalPnl: 0 },
      loading: false,
      error: null,
      lastUpdated: new Date('2026-01-30T12:00:00Z'),
    }));

    const { rerender } = render(<Predictions />);

    // Simulate new position added
    expect(() => {
      act(() => {
        setMarketState.markets = [
          {
            id: 'market-1',
            symbol: 'BTC-YES',
            question: 'Will Bitcoin exceed $100k?',
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
            status: 'OPEN',
            endTime: '2026-12-31T23:59:59Z',
            lastUpdated: '2026-01-30T12:00:00Z',
          },
          {
            id: 'market-2',
            symbol: 'ETH-YES',
            question: 'Will Ethereum exceed $10k?',
            marketType: 'BINARY',
            yesPrice: 0.40,
            noPrice: 0.60,
            volume: 800000,
            liquidity: 120000,
            ourPosition: 'NO',
            ourSize: 500,
            ourAvgPrice: 0.58,
            ourPnl: -40,
            modelConfidence: 0.62,
            modelPrediction: 'NO',
            status: 'OPEN',
            endTime: '2026-12-31T23:59:59Z',
            lastUpdated: '2026-01-30T12:10:00Z',
          },
        ];
        setMarketState.meta = { total: 2, open: 2, closed: 0, totalVolume: 2300000, totalPnl: 60 };
        rerender(<Predictions />);
      });
    }).not.toThrow();

    // Simulate market resolution
    expect(() => {
      act(() => {
        setMarketState.markets = [
          {
            id: 'market-1',
            symbol: 'BTC-YES',
            question: 'Will Bitcoin exceed $100k?',
            marketType: 'BINARY',
            yesPrice: 1.0, // Resolved YES
            noPrice: 0.0,
            volume: 2000000,
            liquidity: 250000,
            ourPosition: 'YES',
            ourSize: 1000,
            ourAvgPrice: 0.55,
            ourPnl: 450, // Max profit
            modelConfidence: 1.0,
            modelPrediction: 'YES',
            status: 'CLOSED', // Changed to closed
            endTime: '2026-12-31T23:59:59Z',
            lastUpdated: '2026-12-31T23:59:59Z',
          },
          {
            id: 'market-2',
            symbol: 'ETH-YES',
            question: 'Will Ethereum exceed $10k?',
            marketType: 'BINARY',
            yesPrice: 0.40,
            noPrice: 0.60,
            volume: 800000,
            liquidity: 120000,
            ourPosition: 'NO',
            ourSize: 500,
            ourAvgPrice: 0.58,
            ourPnl: -40,
            modelConfidence: 0.62,
            modelPrediction: 'NO',
            status: 'OPEN',
            endTime: '2026-12-31T23:59:59Z',
            lastUpdated: '2026-01-30T12:10:00Z',
          },
        ];
        setMarketState.meta = { total: 2, open: 1, closed: 1, totalVolume: 2800000, totalPnl: 410 };
        rerender(<Predictions />);
      });
    }).not.toThrow();
  });

  it('does not crash under rapid updates', () => {
    const setMarketState: any = {};

    (usePredictions as jest.Mock).mockImplementation(() => ({
      markets: setMarketState.markets ?? [],
      meta: setMarketState.meta ?? { total: 0, open: 0, closed: 0, totalVolume: 0, totalPnl: 0 },
      loading: false,
      error: null,
      lastUpdated: new Date('2026-01-30T12:00:00Z'),
    }));

    const { rerender } = render(<Predictions />);

    expect(() => {
      for (let i = 0; i < 50; i++) {
        act(() => {
          setMarketState.markets = [
            {
              id: `market-${i}`,
              symbol: `SYM-${i}-YES`,
              question: `Test market ${i}?`,
              marketType: 'BINARY',
              yesPrice: Math.random(),
              noPrice: 1 - Math.random(),
              volume: 1000000 + i * 1000,
              liquidity: 100000 + i * 100,
              ourPosition: i % 2 === 0 ? 'YES' : 'NO',
              ourSize: 100 + i,
              ourAvgPrice: 0.5,
              ourPnl: i * 10,
              modelConfidence: 0.5 + Math.random() * 0.5,
              modelPrediction: i % 2 === 0 ? 'YES' : 'NO',
              status: i % 10 === 0 ? 'CLOSED' : 'OPEN',
              endTime: '2026-12-31T23:59:59Z',
              lastUpdated: new Date().toISOString(),
            },
          ];
          setMarketState.meta = { total: 1, open: i % 10 === 0 ? 0 : 1, closed: i % 10 === 0 ? 1 : 0, totalVolume: 1000000 + i * 1000, totalPnl: i * 10 };
          rerender(<Predictions />);
        });
      }
    }).not.toThrow();
  });
});
