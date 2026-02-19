/**
 * Tests for KalshiInsightsPanel — AI-generated insights with type filters.
 */

import { render, screen, fireEvent } from '@testing-library/react';

const mockUseApiData = jest.fn();
jest.mock('../../hooks/useApiData', () => ({
  useApiData: (...args: unknown[]) => mockUseApiData(...args),
}));

import KalshiInsightsPanel from '../KalshiInsightsPanel';

describe('KalshiInsightsPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('shows mock insights when API returns empty', () => {
    mockUseApiData.mockReturnValue({ data: { insights: [] }, loading: false });
    render(<KalshiInsightsPanel />);
    expect(screen.getByText('AI Insights')).toBeInTheDocument();
    // Mock data should be shown
    expect(screen.getByText(/BTC 15m: Profit factor dropped/)).toBeInTheDocument();
    expect(screen.getByText(/Drawdown approaching warning tier/)).toBeInTheDocument();
    expect(screen.getByText(/ETH hourly markets showing wider spreads/)).toBeInTheDocument();
    expect(screen.getByText(/SOL 15m markets have high volume/)).toBeInTheDocument();
  });

  it('renders type filter tabs', () => {
    mockUseApiData.mockReturnValue({ data: { insights: [] }, loading: false });
    render(<KalshiInsightsPanel />);
    // Type names appear in both filter tabs and insight badges
    expect(screen.getAllByText('Performance').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Risk').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Liquidity').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Opportunity').length).toBeGreaterThanOrEqual(1);
  });

  it('filters insights by type when clicking a type tab', () => {
    mockUseApiData.mockReturnValue({ data: { insights: [] }, loading: false });
    render(<KalshiInsightsPanel />);
    // Click the Risk filter tab (first match is the filter button)
    const riskButtons = screen.getAllByText('Risk');
    fireEvent.click(riskButtons[0]);
    // Should show only risk insight
    expect(screen.getByText(/Drawdown approaching warning tier/)).toBeInTheDocument();
    // Performance insight should be hidden
    expect(screen.queryByText(/BTC 15m: Profit factor dropped/)).not.toBeInTheDocument();
  });

  it('clicking All clears type filter', () => {
    mockUseApiData.mockReturnValue({ data: { insights: [] }, loading: false });
    render(<KalshiInsightsPanel />);
    // Click Risk filter
    const riskButtons = screen.getAllByText('Risk');
    fireEvent.click(riskButtons[0]);
    // Only risk shown
    expect(screen.queryByText(/SOL 15m markets/)).not.toBeInTheDocument();
    // Click All filter tab (first 'All' button)
    const allButtons = screen.getAllByText('All');
    fireEvent.click(allButtons[0]);
    // All insights should be back
    expect(screen.getByText(/SOL 15m markets/)).toBeInTheDocument();
  });

  it('shows active insight count', () => {
    mockUseApiData.mockReturnValue({ data: { insights: [] }, loading: false });
    render(<KalshiInsightsPanel />);
    expect(screen.getByText('4 active')).toBeInTheDocument();
  });

  it('dismissing an insight removes it', () => {
    mockUseApiData.mockReturnValue({ data: { insights: [] }, loading: false });
    render(<KalshiInsightsPanel />);
    const dismissButtons = screen.getAllByLabelText('Dismiss insight');
    expect(dismissButtons.length).toBe(4);
    fireEvent.click(dismissButtons[0]);
    // One fewer insight
    expect(screen.getByText('3 active')).toBeInTheDocument();
  });

  it('expand/collapse details works', () => {
    mockUseApiData.mockReturnValue({ data: { insights: [] }, loading: false });
    render(<KalshiInsightsPanel />);
    const showBtn = screen.getAllByText('Show details')[0];
    fireEvent.click(showBtn);
    expect(screen.getByText(/The BTC 15-minute agent has seen declining edge/)).toBeInTheDocument();
    fireEvent.click(screen.getByText('Hide details'));
    expect(screen.queryByText(/The BTC 15-minute agent has seen declining edge/)).not.toBeInTheDocument();
  });

  it('renders View details links when onNavigate is provided', () => {
    const onNavigate = jest.fn();
    mockUseApiData.mockReturnValue({ data: { insights: [] }, loading: false });
    render(<KalshiInsightsPanel onNavigate={onNavigate} />);
    const viewLinks = screen.getAllByText('View details');
    expect(viewLinks.length).toBeGreaterThanOrEqual(1);
    fireEvent.click(viewLinks[0]);
    expect(onNavigate).toHaveBeenCalled();
  });

  it('does not render View details links when onNavigate is not provided', () => {
    mockUseApiData.mockReturnValue({ data: { insights: [] }, loading: false });
    render(<KalshiInsightsPanel />);
    expect(screen.queryByText('View details')).not.toBeInTheDocument();
  });

  it('shows kind badge (Suggestion/Warning/Fact)', () => {
    mockUseApiData.mockReturnValue({ data: { insights: [] }, loading: false });
    render(<KalshiInsightsPanel />);
    expect(screen.getAllByText('Suggestion').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Warning').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Fact').length).toBeGreaterThanOrEqual(1);
  });

  it('shows type badges on insights', () => {
    mockUseApiData.mockReturnValue({ data: { insights: [] }, loading: false });
    render(<KalshiInsightsPanel />);
    // Type badges in the card body
    const perfBadges = screen.getAllByText('Performance');
    expect(perfBadges.length).toBeGreaterThanOrEqual(1);
  });

  it('uses API data when available instead of mocks', () => {
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
    // Mock insights should NOT appear
    expect(screen.queryByText(/BTC 15m: Profit factor dropped/)).not.toBeInTheDocument();
  });
});
