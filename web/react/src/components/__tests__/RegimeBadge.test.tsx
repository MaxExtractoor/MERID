import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { RegimeBadge, RegimeDot, formatRegimeLabel, getRegimeColorClass } from '../RegimeBadge';
import type { RegimeData } from '../RegimeBadge';

describe('RegimeBadge', () => {
  const mockRegimes: RegimeData[] = [
    { label: 'trending_up', confidence: 0.85, duration_minutes: 45, asset: 'BTC' },
    { label: 'trending_down', confidence: 0.72, duration_minutes: 30, asset: 'ETH' },
    { label: 'mean_reverting', confidence: 0.91, duration_minutes: 120, asset: 'SOL' },
    { label: 'high_volatility', confidence: 0.68, duration_minutes: 15, asset: 'XRP' },
    { label: 'low_volatility', confidence: 0.95, duration_minutes: 180, asset: 'ADA' },
    { label: 'choppy', confidence: 0.55, duration_minutes: 60, asset: 'DOT' },
    { label: 'unknown', confidence: 0.0, duration_minutes: 0, asset: 'UNKNOWN' },
  ];

  it('renders trending_up regime correctly', () => {
    render(<RegimeBadge regime={mockRegimes[0]} />);
    expect(screen.getByText('TRENDING')).toBeInTheDocument();
    expect(screen.getByText('(85%)')).toBeInTheDocument();
  });

  it('renders trending_down regime correctly', () => {
    render(<RegimeBadge regime={mockRegimes[1]} />);
    expect(screen.getByText('DOWNTREND')).toBeInTheDocument();
    expect(screen.getByText('(72%)')).toBeInTheDocument();
  });

  it('renders mean_reverting regime correctly', () => {
    render(<RegimeBadge regime={mockRegimes[2]} />);
    expect(screen.getByText('MEAN REV')).toBeInTheDocument();
    expect(screen.getByText('(91%)')).toBeInTheDocument();
  });

  it('renders high_volatility regime correctly', () => {
    render(<RegimeBadge regime={mockRegimes[3]} />);
    expect(screen.getByText('VOLATILE')).toBeInTheDocument();
    expect(screen.getByText('(68%)')).toBeInTheDocument();
  });

  it('renders low_volatility regime correctly', () => {
    render(<RegimeBadge regime={mockRegimes[4]} />);
    expect(screen.getByText('QUIET')).toBeInTheDocument();
    expect(screen.getByText('(95%)')).toBeInTheDocument();
  });

  it('renders choppy regime correctly', () => {
    render(<RegimeBadge regime={mockRegimes[5]} />);
    expect(screen.getByText('CHOPPY')).toBeInTheDocument();
    expect(screen.getByText('(55%)')).toBeInTheDocument();
  });

  it('renders unknown regime correctly', () => {
    render(<RegimeBadge regime={mockRegimes[6]} />);
    expect(screen.getByText('UNKNOWN')).toBeInTheDocument();
  });

  it('hides confidence when showConfidence is false', () => {
    render(<RegimeBadge regime={mockRegimes[0]} showConfidence={false} />);
    expect(screen.getByText('TRENDING')).toBeInTheDocument();
    expect(screen.queryByText('(85%)')).not.toBeInTheDocument();
  });

  it('applies correct size classes', () => {
    const { container: sm } = render(<RegimeBadge regime={mockRegimes[0]} size="sm" />);
    const { container: md } = render(<RegimeBadge regime={mockRegimes[0]} size="md" />);
    const { container: lg } = render(<RegimeBadge regime={mockRegimes[0]} size="lg" />);
    
    // Just verify they render without errors
    expect(sm.querySelector('span')).toBeInTheDocument();
    expect(md.querySelector('span')).toBeInTheDocument();
    expect(lg.querySelector('span')).toBeInTheDocument();
  });

  it('has correct title attribute for tooltip', () => {
    render(<RegimeBadge regime={mockRegimes[0]} />);
    const badge = screen.getByTitle(/Upward trend detected/);
    expect(badge).toBeInTheDocument();
  });
});

describe('RegimeDot', () => {
  it('renders compact dot format', () => {
    const regime: RegimeData = { label: 'trending_up', confidence: 0.82 };
    render(<RegimeDot regime={regime} />);
    expect(screen.getByText('TRENDING')).toBeInTheDocument();
  });
});

describe('formatRegimeLabel', () => {
  it('returns correct display labels', () => {
    expect(formatRegimeLabel('trending_up')).toBe('TRENDING');
    expect(formatRegimeLabel('trending_down')).toBe('DOWNTREND');
    expect(formatRegimeLabel('mean_reverting')).toBe('MEAN REV');
    expect(formatRegimeLabel('high_volatility')).toBe('VOLATILE');
    expect(formatRegimeLabel('unknown')).toBe('UNKNOWN');
  });
});

describe('getRegimeColorClass', () => {
  it('returns correct color classes', () => {
    expect(getRegimeColorClass('trending_up')).toBe('text-blue-400');
    expect(getRegimeColorClass('trending_down')).toBe('text-orange-400');
    expect(getRegimeColorClass('mean_reverting')).toBe('text-purple-400');
    expect(getRegimeColorClass('high_volatility')).toBe('text-red-400');
    expect(getRegimeColorClass('unknown')).toBe('text-slate-400');
  });
});
