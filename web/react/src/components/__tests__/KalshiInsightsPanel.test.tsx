/**
 * Tests for KalshiInsightsPanel — AI-generated insights with type filters.
 */

import { render, screen, fireEvent } from '@testing-library/react';

const mockUseApiData = jest.fn();
jest.mock('../../hooks/useApiData', () => ({
  useApiData: (...args: unknown[]) => mockUseApiData(...args),
}));

import KalshiInsightsPanel from '../KalshiInsightsPanel';

// Reusable test fixture data matching current Insight interface
const MOCK_INSIGHTS = [
  { id: 'i-1', kind: 'suggestion', insight_type: 'performance', title: 'Profit factor declining', body: 'BTC 15m agent edge is narrowing.', details: 'The BTC 15-minute agent edge has shrunk 40%.', severity: 'warning', ts: '2026-02-21T10:00:00Z', action_label: 'Pause agent', action_endpoint: '/api/agents/btc15/pause', link_view: 'agents' },
  { id: 'i-2', kind: 'warning', insight_type: 'risk', title: 'Drawdown near limit', body: 'Drawdown approaching warning tier.', severity: 'critical', ts: '2026-02-21T10:01:00Z' },
  { id: 'i-3', kind: 'fact', insight_type: 'liquidity', title: 'ETH spreads widening', body: 'ETH hourly markets showing wider spreads.', severity: 'info', ts: '2026-02-21T10:02:00Z', link_view: 'terminal' },
  { id: 'i-4', kind: 'suggestion', insight_type: 'opportunity', title: 'SOL volume spike', body: 'SOL 15m markets have high volume.', severity: 'info', ts: '2026-02-21T10:03:00Z' },
];

describe('KalshiInsightsPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('shows empty state when API returns no insights', () => {
    mockUseApiData.mockReturnValue({ data: { insights: [] }, loading: false });
    render(<KalshiInsightsPanel />);
    expect(screen.getByText('AI Insights')).toBeInTheDocument();
    expect(screen.getByText(/No active insights/)).toBeInTheDocument();
  });

  it('renders insights from API data', () => {
    mockUseApiData.mockReturnValue({ data: { insights: MOCK_INSIGHTS }, loading: false });
    render(<KalshiInsightsPanel />);
    expect(screen.getByText('Profit factor declining')).toBeInTheDocument();
    expect(screen.getByText('Drawdown near limit')).toBeInTheDocument();
    expect(screen.getByText('ETH spreads widening')).toBeInTheDocument();
    expect(screen.getByText('SOL volume spike')).toBeInTheDocument();
  });

  it('renders type filter tabs', () => {
    mockUseApiData.mockReturnValue({ data: { insights: MOCK_INSIGHTS }, loading: false });
    render(<KalshiInsightsPanel />);
    expect(screen.getAllByText('Performance').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Risk').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Liquidity').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Opportunity').length).toBeGreaterThanOrEqual(1);
  });

  it('filters insights by type when clicking a type tab', () => {
    mockUseApiData.mockReturnValue({ data: { insights: MOCK_INSIGHTS }, loading: false });
    render(<KalshiInsightsPanel />);
    const riskButtons = screen.getAllByText('Risk');
    fireEvent.click(riskButtons[0]);
    expect(screen.getByText('Drawdown near limit')).toBeInTheDocument();
    expect(screen.queryByText('Profit factor declining')).not.toBeInTheDocument();
  });

  it('clicking All clears type filter', () => {
    mockUseApiData.mockReturnValue({ data: { insights: MOCK_INSIGHTS }, loading: false });
    render(<KalshiInsightsPanel />);
    const riskButtons = screen.getAllByText('Risk');
    fireEvent.click(riskButtons[0]);
    expect(screen.queryByText('SOL volume spike')).not.toBeInTheDocument();
    const allButtons = screen.getAllByText('All');
    fireEvent.click(allButtons[0]);
    expect(screen.getByText('SOL volume spike')).toBeInTheDocument();
  });

  it('shows active insight count', () => {
    mockUseApiData.mockReturnValue({ data: { insights: MOCK_INSIGHTS }, loading: false });
    render(<KalshiInsightsPanel />);
    expect(screen.getByText('4 active')).toBeInTheDocument();
  });

  it('dismissing an insight removes it', () => {
    mockUseApiData.mockReturnValue({ data: { insights: MOCK_INSIGHTS }, loading: false });
    render(<KalshiInsightsPanel />);
    const dismissButtons = screen.getAllByLabelText('Dismiss insight');
    expect(dismissButtons.length).toBe(4);
    fireEvent.click(dismissButtons[0]);
    expect(screen.getByText('3 active')).toBeInTheDocument();
  });

  it('expand/collapse details works', () => {
    mockUseApiData.mockReturnValue({ data: { insights: MOCK_INSIGHTS }, loading: false });
    render(<KalshiInsightsPanel />);
    const showBtn = screen.getAllByText('Show details')[0];
    fireEvent.click(showBtn);
    expect(screen.getByText(/BTC 15-minute agent edge has shrunk/)).toBeInTheDocument();
    fireEvent.click(screen.getByText('Hide details'));
    expect(screen.queryByText(/BTC 15-minute agent edge has shrunk/)).not.toBeInTheDocument();
  });

  it('renders View details links when onNavigate is provided', () => {
    const onNavigate = jest.fn();
    mockUseApiData.mockReturnValue({ data: { insights: MOCK_INSIGHTS }, loading: false });
    render(<KalshiInsightsPanel onNavigate={onNavigate} />);
    const viewLinks = screen.getAllByText('View details');
    expect(viewLinks.length).toBeGreaterThanOrEqual(1);
    fireEvent.click(viewLinks[0]);
    expect(onNavigate).toHaveBeenCalled();
  });

  it('does not render View details links when onNavigate is not provided', () => {
    mockUseApiData.mockReturnValue({ data: { insights: MOCK_INSIGHTS }, loading: false });
    render(<KalshiInsightsPanel />);
    // Without onNavigate prop, view links should not render
    expect(screen.queryAllByText('View details').length).toBe(0);
  });

  it('shows kind badge (Suggestion/Warning/Fact)', () => {
    mockUseApiData.mockReturnValue({ data: { insights: MOCK_INSIGHTS }, loading: false });
    render(<KalshiInsightsPanel />);
    expect(screen.getAllByText('Suggestion').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Warning').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Fact').length).toBeGreaterThanOrEqual(1);
  });

  it('shows type badges on insights', () => {
    mockUseApiData.mockReturnValue({ data: { insights: MOCK_INSIGHTS }, loading: false });
    render(<KalshiInsightsPanel />);
    const perfBadges = screen.getAllByText('Performance');
    expect(perfBadges.length).toBeGreaterThanOrEqual(1);
  });

  it('uses API data when available', () => {
    const apiInsights = {
      insights: [{
        id: 'api-1',
        kind: 'fact',
        insight_type: 'liquidity',
        title: 'Real API insight: market is liquid',
        body: 'This came from the real API.',
        severity: 'info',
        ts: new Date().toISOString(),
      }],
    };
    mockUseApiData.mockReturnValue({ data: apiInsights, loading: false });
    render(<KalshiInsightsPanel />);
    expect(screen.getByText('Real API insight: market is liquid')).toBeInTheDocument();
  });
});
