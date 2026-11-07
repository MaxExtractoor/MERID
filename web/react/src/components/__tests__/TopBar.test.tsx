/**
 * TopBar balance chip regression tests.
 *
 * Bug: the chip read `portfolio.portfolio_value` (backend `portfolio_cents` —
 * open-positions value ONLY) and fell back to `cash`. With no open positions
 * it showed the account balance; the moment a fill landed it collapsed to
 * just that position's mark (e.g. $100.00 -> $4.70), then flipped back on
 * settlement. The chip must show equity (`balance` = available cash +
 * positions) so a fill only moves it by fees/mark.
 */

import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import TopBar from '../TopBar';
import { useKalshiStore } from '../../store';

jest.mock('lucide-react', () => {
  return new Proxy({}, {
    get: (_target, prop) => {
      if (typeof prop !== 'string') return undefined;
      const IconStub = ({ className }: { className?: string }) => (
        <span data-testid={`icon-${prop}`} className={className} />
      );
      IconStub.displayName = prop;
      return IconStub;
    },
  });
});

const fmt = (usd: number) =>
  usd.toLocaleString('en-US', { style: 'currency', currency: 'USD' });

function setPortfolio(p: { balance: number; cash: number; portfolio_value: number; daily_pnl?: number }) {
  useKalshiStore.setState(s => ({
    portfolio: {
      ...s.portfolio,
      balance: p.balance,
      cash: p.cash,
      portfolio_value: p.portfolio_value,
      daily_pnl: p.daily_pnl ?? 0,
      lastOk: Date.now(),
    },
  }));
}

describe('TopBar balance chip', () => {
  beforeEach(() => {
    useKalshiStore.setState(s => ({
      portfolio: { ...s.portfolio, balance: 0, cash: 0, portfolio_value: 0, daily_pnl: 0, lastOk: undefined },
      connected: true,
    }));
  });

  it('shows equity, not positions value, after a fill lands', () => {
    // $100 account -> bought 10 contracts @ 47c: $95.28 cash + $4.70 position.
    setPortfolio({ balance: 99.98, cash: 95.28, portfolio_value: 4.7 });
    render(<TopBar onMenuClick={jest.fn()} />);
    expect(screen.getByText(fmt(99.98))).toBeInTheDocument();
    expect(screen.queryByText(fmt(4.7))).not.toBeInTheDocument();
  });

  it('shows the account balance with no open positions', () => {
    setPortfolio({ balance: 100, cash: 100, portfolio_value: 0 });
    render(<TopBar onMenuClick={jest.fn()} />);
    expect(screen.getByText(fmt(100))).toBeInTheDocument();
  });

  it('falls back to cash when equity is unavailable', () => {
    setPortfolio({ balance: 0, cash: 50, portfolio_value: 0 });
    render(<TopBar onMenuClick={jest.fn()} />);
    expect(screen.getByText(fmt(50))).toBeInTheDocument();
  });

  it('shows n/a before the first authoritative fetch', () => {
    useKalshiStore.setState(s => ({ portfolio: { ...s.portfolio, lastOk: undefined } }));
    render(<TopBar onMenuClick={jest.fn()} />);
    expect(screen.getAllByText('n/a').length).toBeGreaterThan(0);
  });
});
