/**
 * ContextStrip Component Tests
 *
 * Tests the context strip component that displays venue/lane/profile/mode
 * with warnings for unsupported combinations and freshness indicators.
 */

import { render, screen } from '@testing-library/react';
import ContextStrip from '../ContextStrip';

// Mock useApiData hook
jest.mock('../../hooks/useApiData', () => ({
  useApiData: jest.fn(),
}));

const mockUseApiData = require('../../hooks/useApiData').useApiData;

describe('ContextStrip', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders loading state when no data', () => {
    mockUseApiData.mockReturnValue({
      data: null,
      lastUpdated: null,
    });

    render(<ContextStrip />);

    // Should show skeleton loading
    const skeletons = screen.getAllByTestId('skeleton');
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it('displays correct venue, lane, profile, mode', () => {
    mockUseApiData
      .mockReturnValueOnce({
        data: { lane: { mode: 'BTC 15m' }, trade_mode: 'live' },
        lastUpdated: new Date('2024-01-01T10:00:00Z'),
      })
      .mockReturnValueOnce({
        data: { running: true },
        lastUpdated: new Date('2024-01-01T10:01:00Z'),
      })
      .mockReturnValueOnce({
        data: { enable_execution: true, kill_switch_active: false },
        lastUpdated: new Date('2024-01-01T10:02:00Z'),
      });

    render(<ContextStrip />);

    expect(screen.getByText('Venue:')).toBeInTheDocument();
    expect(screen.getByText('Kalshi')).toBeInTheDocument();

    expect(screen.getByText('Lane:')).toBeInTheDocument();
    expect(screen.getByText('BTC 15m')).toBeInTheDocument();

    expect(screen.getByText('Profile:')).toBeInTheDocument();
    expect(screen.getByText('LIVE')).toBeInTheDocument();

    expect(screen.getByText('Mode:')).toBeInTheDocument();
    expect(screen.getByText('Live Trading')).toBeInTheDocument();
  });

  it('shows warnings for unsupported combinations', () => {
    // Live profile with execution disabled
    mockUseApiData
      .mockReturnValueOnce({
        data: { trade_mode: 'live' },
        lastUpdated: null,
      })
      .mockReturnValueOnce({
        data: { running: false },
        lastUpdated: null,
      })
      .mockReturnValueOnce({
        data: { enable_execution: false, kill_switch_active: false },
        lastUpdated: null,
      });

    render(<ContextStrip />);

    expect(screen.getByText('Live profile with execution disabled')).toBeInTheDocument();
  });

  it('displays kill switch active mode', () => {
    mockUseApiData
      .mockReturnValueOnce({
        data: { trade_mode: 'live' },
        lastUpdated: null,
      })
      .mockReturnValueOnce({
        data: { running: true },
        lastUpdated: null,
      })
      .mockReturnValueOnce({
        data: { enable_execution: true, kill_switch_active: true },
        lastUpdated: null,
      });

    render(<ContextStrip />);

    expect(screen.getByText('Halted')).toBeInTheDocument();
    expect(screen.getByText('HALTED')).toBeInTheDocument();
  });

  it('shows freshness timestamp', () => {
    const recentTime = new Date('2024-01-01T10:00:00Z');

    mockUseApiData
      .mockReturnValueOnce({
        data: { lane: { mode: 'BTC 15m' }, trade_mode: 'paper' },
        lastUpdated: recentTime,
      })
      .mockReturnValueOnce({
        data: { running: true },
        lastUpdated: recentTime,
      })
      .mockReturnValueOnce({
        data: { enable_execution: true, kill_switch_active: false },
        lastUpdated: recentTime,
      });

    render(<ContextStrip />);

    expect(screen.getByText('10:00:00 AM')).toBeInTheDocument();
  });

  it('applies warning styling when warnings present', () => {
    mockUseApiData
      .mockReturnValueOnce({
        data: { trade_mode: 'live' },
        lastUpdated: null,
      })
      .mockReturnValueOnce({
        data: { running: false },
        lastUpdated: null,
      })
      .mockReturnValueOnce({
        data: { enable_execution: false, kill_switch_active: false },
        lastUpdated: null,
      });

    const { container } = render(<ContextStrip />);

    // Should have warning background classes
    expect(container.firstChild).toHaveClass('bg-amber-950/20', 'border-amber-600/40');
  });

  it('handles unknown lane gracefully', () => {
    mockUseApiData
      .mockReturnValueOnce({
        data: { lane: { mode: null }, trade_mode: 'paper' },
        lastUpdated: null,
      })
      .mockReturnValueOnce({
        data: { running: true },
        lastUpdated: null,
      })
      .mockReturnValueOnce({
        data: { enable_execution: true, kill_switch_active: false },
        lastUpdated: null,
      });

    render(<ContextStrip />);

    expect(screen.getByText('Unknown')).toBeInTheDocument();
  });
});
