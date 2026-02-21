import { render, screen } from '@testing-library/react';
import ConsensusTable from '../ConsensusTable';
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

const SYMBOLS: ConsensusSymbolSummary[] = [
  {
    symbol: 'BTC-USD',
    asset_class: 'crypto',
    stance: 'strong_long',
    confidence: 0.82,
    supporting_agents: 5,
    opposing_agents: 1,
    active_plans: { proposed: 1, approved: 1, executing: 0 },
  },
  {
    symbol: 'AAPL',
    asset_class: 'equity',
    stance: 'neutral',
    confidence: 0.45,
    supporting_agents: 2,
    opposing_agents: 2,
    active_plans: { proposed: 0, approved: 0, executing: 0 },
  },
  {
    symbol: 'ETH-USD',
    asset_class: 'crypto',
    stance: 'strong_short',
    confidence: 0.78,
    supporting_agents: 0,
    opposing_agents: 4,
    active_plans: { proposed: 0, approved: 0, executing: 1 },
  },
];

describe('ConsensusTable', () => {
  it('renders rows for each symbol with correct text', () => {
    const summary = makeSummary(SYMBOLS);
    render(<ConsensusTable summary={summary} />);
    expect(screen.getByTestId('consensus-table')).toBeInTheDocument();
    expect(screen.getByTestId('consensus-row-BTC-USD')).toBeInTheDocument();
    expect(screen.getByTestId('consensus-row-AAPL')).toBeInTheDocument();
    expect(screen.getByTestId('consensus-row-ETH-USD')).toBeInTheDocument();
    expect(screen.getByText('Strong Long')).toBeInTheDocument();
    expect(screen.getByText('Neutral')).toBeInTheDocument();
    expect(screen.getByText('Strong Short')).toBeInTheDocument();
  });

  it('shows stub banner when rawResponse is stubbed', () => {
    const summary = makeSummary(SYMBOLS, true);
    render(<ConsensusTable summary={summary} />);
    expect(screen.getByTestId('consensus-table-stub')).toBeInTheDocument();
    expect(screen.getByText(/not available/i)).toBeInTheDocument();
    expect(screen.queryByTestId('consensus-table')).not.toBeInTheDocument();
  });

  it('shows empty state when no symbols', () => {
    const summary = makeSummary([]);
    render(<ConsensusTable summary={summary} />);
    expect(screen.getByTestId('consensus-table-empty')).toBeInTheDocument();
  });
});
