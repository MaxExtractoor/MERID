import { render, screen } from '@testing-library/react';
import ConsensusPill from '../ConsensusPill';
import type { UseConsensusSummaryResult, ConsensusSymbolSummary } from '../../hooks/useConsensusSummary';

function makeSummary(
  symbols: ConsensusSymbolSummary[],
  stub = false,
): UseConsensusSummaryResult {
  const bySymbol: Record<string, ConsensusSymbolSummary> = {};
  for (const s of symbols) bySymbol[s.symbol] = s;
  return {
    symbols,
    bySymbol,
    rawResponse: stub ? { _stub: true, _stub_message: 'sim' } : { stub: false },
    loading: false,
  };
}

const BTC_STRONG_LONG: ConsensusSymbolSummary = {
  symbol: 'BTC-USD',
  asset_class: 'crypto',
  stance: 'strong_long',
  confidence: 0.82,
  supporting_agents: 5,
  opposing_agents: 1,
  active_plans: { proposed: 0, approved: 1, executing: 0 },
};

const ETH_NEUTRAL: ConsensusSymbolSummary = {
  symbol: 'ETH-USD',
  asset_class: 'crypto',
  stance: 'neutral',
  confidence: 0.41,
  supporting_agents: 2,
  opposing_agents: 2,
  active_plans: { proposed: 0, approved: 0, executing: 0 },
};

describe('ConsensusPill', () => {
  it('renders strong_long pill with correct text and green styling', () => {
    const summary = makeSummary([BTC_STRONG_LONG]);
    render(<ConsensusPill symbol="BTC-USD" summary={summary} />);
    const pill = screen.getByTestId('consensus-pill');
    expect(pill).toHaveTextContent('Consensus: Strong Long');
    expect(pill).toHaveAttribute('data-stance', 'strong_long');
    expect(pill.className).toContain('emerald');
  });

  it('renders neutral pill for neutral stance', () => {
    const summary = makeSummary([ETH_NEUTRAL]);
    render(<ConsensusPill symbol="ETH-USD" summary={summary} />);
    const pill = screen.getByTestId('consensus-pill');
    expect(pill).toHaveTextContent('Consensus: Neutral');
    expect(pill).toHaveAttribute('data-stance', 'neutral');
    expect(pill.className).toContain('slate');
  });

  it('renders "No data" pill when symbol not in summary', () => {
    const summary = makeSummary([BTC_STRONG_LONG]);
    render(<ConsensusPill symbol="AAPL" summary={summary} />);
    const pill = screen.getByTestId('consensus-pill');
    expect(pill).toHaveTextContent('Consensus: No data (simulation)');
    expect(pill).toHaveAttribute('data-stance', 'none');
  });

  it('renders "No data" pill when rawResponse is stubbed', () => {
    const summary = makeSummary([BTC_STRONG_LONG], true);
    render(<ConsensusPill symbol="BTC-USD" summary={summary} />);
    const pill = screen.getByTestId('consensus-pill');
    expect(pill).toHaveTextContent('Consensus: No data (simulation)');
    expect(pill).toHaveAttribute('data-stance', 'none');
  });
});
