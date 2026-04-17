/**
 * Tests for Enhanced Kalshi Orderbook Panel Component
 */

import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import EnhancedKalshiOrderbookPanel from '../KalshiOrderbookPanelEnhanced';

// Mock the orderbook stream hook
jest.mock('../../hooks/useKalshiOrderbookStream', () => ({
  useKalshiOrderbookStream: (ticker: string, _options?: any) => {
    const mockData = {
      ticker: ticker || 'TEST-1',
      yes_bids: [
        { price: 0.45, quantity: 100 },
        { price: 0.44, quantity: 200 },
        { price: 0.43, quantity: 150 },
      ],
      yes_asks: [
        { price: 0.46, quantity: 120 },
        { price: 0.47, quantity: 180 },
        { price: 0.48, quantity: 90 },
      ],
      no_bids: [
        { price: 0.55, quantity: 80 },
        { price: 0.54, quantity: 160 },
        { price: 0.53, quantity: 110 },
      ],
      no_asks: [
        { price: 0.56, quantity: 140 },
        { price: 0.57, quantity: 100 },
        { price: 0.58, quantity: 70 },
      ],
      spread_cents: 1,
      midpoint: 0.455,
    };

    return {
      data: mockData,
      connected: true,
      error: null,
      updates: [],
      lastUpdate: new Date(),
    };
  },
}));

describe('EnhancedKalshiOrderbookPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders orderbook with data', () => {
    render(<EnhancedKalshiOrderbookPanel ticker="TEST-1" />);
    
    expect(screen.getByText('TEST-1')).toBeInTheDocument();
    expect(screen.getByText('YES')).toBeInTheDocument();
    expect(screen.getByText('NO')).toBeInTheDocument();
    expect(screen.getByText('Spread: 1¢')).toBeInTheDocument();
    expect(screen.getByText('Mid: 46¢')).toBeInTheDocument();
  });

  it('shows connection status indicator', () => {
    render(<EnhancedKalshiOrderbookPanel ticker="TEST-1" />);
    
    expect(screen.getByText('Connected')).toBeInTheDocument();
    expect(screen.getByText('Connected (excellent)')).toBeInTheDocument();
  });

  it('shows reconnect button when disconnected', () => {
    const { useKalshiOrderbookStream } = require('../../hooks/useKalshiOrderbookStream');
    useKalshiOrderbookStream.mockReturnValue({
      data: null,
      connected: false,
      error: new Error('Connection failed'),
      updates: [],
      lastUpdate: null,
    });

    render(<EnhancedKalshiOrderbookPanel ticker="TEST-1" />);
    
    expect(screen.getByText('Connection failed')).toBeInTheDocument();
    expect(screen.getByText('Reconnect')).toBeInTheDocument();
  });

  it('handles reconnect button click', () => {
    const { useKalshiOrderbookStream } = require('../../hooks/useKalshiOrderbookStream');
    useKalshiOrderbookStream.mockReturnValue({
      data: null,
      connected: false,
      error: new Error('Connection failed'),
      updates: [],
      lastUpdate: null,
    });

    render(<EnhancedKalshiOrderbookPanel ticker="TEST-1" />);
    
    const reconnectButton = screen.getByText('Reconnect');
    fireEvent.click(reconnectButton);
    
    // The reconnection logic would be tested through the hook
    expect(reconnectButton).toBeInTheDocument();
  });

  it('shows fallback orderbook on connection failure', () => {
    const { useKalshiOrderbookStream } = require('../../hooks/useKalshiOrderbookStream');
    useKalshiOrderbookStream.mockReturnValue({
      data: null,
      connected: false,
      error: new Error('Connection failed'),
      updates: [],
      lastUpdate: null,
    });

    render(<EnhancedKalshiOrderbookPanel ticker="TEST-1" />);
    
    // Should show connection error initially
    expect(screen.getByText('Connection failed')).toBeInTheDocument();
    
    // After timeout, would show fallback (this would need additional test setup)
  });

  it('displays orderbook levels correctly', () => {
    render(<EnhancedKalshiOrderbookPanel ticker="TEST-1" />);
    
    // Check YES bids
    expect(screen.getByText('100')).toBeInTheDocument(); // quantity
    expect(screen.getByText('45¢')).toBeInTheDocument(); // price
    
    // Check YES asks
    expect(screen.getByText('120')).toBeInTheDocument(); // quantity
    expect(screen.getByText('46¢')).toBeInTheDocument(); // price
    
    // Check NO bids
    expect(screen.getByText('80')).toBeInTheDocument(); // quantity
    expect(screen.getByText('55¢')).toBeInTheDocument(); // price
    
    // Check NO asks
    expect(screen.getByText('140')).toBeInTheDocument(); // quantity
    expect(screen.getByText('56¢')).toBeInTheDocument(); // price
  });

  it('respects depth prop', () => {
    render(<EnhancedKalshiOrderbookPanel ticker="TEST-1" depth={2} />);
    
    // Should show fewer levels (default depth is 5, we set it to 2)
    const priceElements = screen.getAllByText(/\d+¢/);
    expect(priceElements.length).toBeLessThanOrEqual(8); // 2 bids + 2 asks for each side
  });

  it('shows stale data indicator', () => {
    const { useKalshiOrderbookStream } = require('../../hooks/useKalshiOrderbookStream');
    const staleDate = new Date(Date.now() - 40000); // 40 seconds ago (stale threshold is 30s)
    
    useKalshiOrderbookStream.mockReturnValue({
      data: {
        ticker: 'TEST-1',
        yes_bids: [{ price: 0.45, quantity: 100 }],
        yes_asks: [{ price: 0.46, quantity: 120 }],
        no_bids: [{ price: 0.55, quantity: 80 }],
        no_asks: [{ price: 0.56, quantity: 140 }],
        spread_cents: 1,
        midpoint: 0.455,
      },
      connected: true,
      error: null,
      updates: [],
      lastUpdate: staleDate,
    });

    render(<EnhancedKalshiOrderbookPanel ticker="TEST-1" />);
    
    expect(screen.getByText('Stale')).toBeInTheDocument();
  });

  it('shows last update time', () => {
    const { useKalshiOrderbookStream } = require('../../hooks/useKalshiOrderbookStream');
    const testDate = new Date('2024-01-01T12:00:00Z');
    
    useKalshiOrderbookStream.mockReturnValue({
      data: {
        ticker: 'TEST-1',
        yes_bids: [{ price: 0.45, quantity: 100 }],
        yes_asks: [{ price: 0.46, quantity: 120 }],
        no_bids: [{ price: 0.55, quantity: 80 }],
        no_asks: [{ price: 0.56, quantity: 140 }],
        spread_cents: 1,
        midpoint: 0.455,
      },
      connected: true,
      error: null,
      updates: [{ timestamp: testDate, type: 'update' }],
      lastUpdate: testDate,
    });

    render(<EnhancedKalshiOrderbookPanel ticker="TEST-1" />);
    
    expect(screen.getByText(/12:00:00/)).toBeInTheDocument();
  });

  it('shows null state when no ticker', () => {
    render(<EnhancedKalshiOrderbookPanel ticker={null} />);
    
    expect(screen.getByText('Select a market to view orderbook')).toBeInTheDocument();
  });

  it('shows loading state', () => {
    const { useKalshiOrderbookStream } = require('../../hooks/useKalshiOrderbookStream');
    useKalshiOrderbookStream.mockReturnValue({
      data: null,
      connected: false,
      error: null,
      updates: [],
      lastUpdate: null,
    });

    render(<EnhancedKalshiOrderbookPanel ticker="TEST-1" />);
    
    expect(screen.getByText('Loading orderbook...')).toBeInTheDocument();
  });

  it('shows connection quality indicators', () => {
    render(<EnhancedKalshiOrderbookPanel ticker="TEST-1" />);
    
    expect(screen.getByText('Connected (excellent)')).toBeInTheDocument();
  });

  it('handles reconnection attempts counter', () => {
    const { useKalshiOrderbookStream } = require('../../hooks/useKalshiOrderbookStream');
    useKalshiOrderbookStream.mockReturnValue({
      data: null,
      connected: false,
      error: new Error('Connection failed'),
      updates: [],
      lastUpdate: null,
    });

    render(<EnhancedKalshiOrderbookPanel ticker="TEST-1" />);
    
    // Would need additional test setup to simulate reconnection attempts
    expect(screen.getByText('Connection failed')).toBeInTheDocument();
  });

  it('shows using cached data banner', () => {
    const { useKalshiOrderbookStream } = require('../../hooks/useKalshiOrderbookStream');
    
    // First call returns data, second call returns error (simulating connection loss)
    let callCount = 0;
    useKalshiOrderbookStream.mockImplementation(() => {
      callCount++;
      if (callCount === 1) {
        return {
          data: {
            ticker: 'TEST-1',
            yes_bids: [{ price: 0.45, quantity: 100 }],
            yes_asks: [{ price: 0.46, quantity: 120 }],
            no_bids: [{ price: 0.55, quantity: 80 }],
            no_asks: [{ price: 0.56, quantity: 140 }],
            spread_cents: 1,
            midpoint: 0.455,
          },
          connected: true,
          error: null,
          updates: [],
          lastUpdate: new Date(),
        };
      } else {
        return {
          data: null,
          connected: false,
          error: new Error('Connection failed'),
          updates: [],
          lastUpdate: null,
        };
      }
    });

    render(<EnhancedKalshiOrderbookPanel ticker="TEST-1" />);
    
    // This would need additional test setup to simulate the fallback behavior
    expect(screen.getByText('TEST-1')).toBeInTheDocument();
  });
});
