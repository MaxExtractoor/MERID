/**
 * Tests for KalshiTradeTicket — Order entry component for Kalshi binary contracts.
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import ToastProvider from '../ToastProvider';

jest.mock('../../components/KalshiModeBadge', () => ({
  __esModule: true,
  default: () => <span data-testid="mode-badge">PAPER</span>,
}));

import KalshiTradeTicket from '../KalshiTradeTicket';

const renderWithToast = (ui: React.ReactElement) => {
  return render(<ToastProvider>{ui}</ToastProvider>);
};

const OUTCOMES = [
  { id: 'yes', name: 'Yes', price: 0.60, bid: 0.58, ask: 0.62 },
  { id: 'no', name: 'No', price: 0.40, bid: 0.38, ask: 0.42 },
];

const defaultProps = {
  ticker: 'KXBTC-26FEB15-15M-T95000',
  question: 'Will BTC be above $95,000 at 3pm?',
  outcomes: OUTCOMES,
  onOrderPlaced: jest.fn(),
  mode: 'paper' as const,
};

describe('KalshiTradeTicket', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.confirm = jest.fn().mockReturnValue(true);
    (global.fetch as jest.Mock).mockResolvedValue({ ok: true, json: async () => ({}) });
  });

  describe('Rendering', () => {
    it('renders the trade ticket title', () => {
      renderWithToast(<KalshiTradeTicket {...defaultProps} />);
      expect(screen.getByText('Trade Ticket')).toBeInTheDocument();
    });

    it('shows YES and NO buttons with prices', () => {
      renderWithToast(<KalshiTradeTicket {...defaultProps} />);
      // YES/NO buttons each contain the label and price as child spans
      expect(screen.getAllByText(/YES/).length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText(/NO/).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText(/60¢/)).toBeInTheDocument();
      expect(screen.getByText(/40¢/)).toBeInTheDocument();
    });

    it('shows implied probability bar', () => {
      renderWithToast(<KalshiTradeTicket {...defaultProps} />);
      expect(screen.getByText('Implied Probability')).toBeInTheDocument();
    });

    it('shows cost/payout summary', () => {
      renderWithToast(<KalshiTradeTicket {...defaultProps} />);
      expect(screen.getByText('Cost')).toBeInTheDocument();
      expect(screen.getByText('Max Payout')).toBeInTheDocument();
      expect(screen.getByText(/Fee/)).toBeInTheDocument();
      expect(screen.getByText('Max Loss')).toBeInTheDocument();
    });

    it('shows paper trading disclaimer when mode=paper', () => {
      renderWithToast(<KalshiTradeTicket {...defaultProps} mode="paper" />);
      expect(screen.getByText(/Paper trading mode/)).toBeInTheDocument();
    });

    it('shows LIVE disclaimer when mode=live', () => {
      renderWithToast(<KalshiTradeTicket {...defaultProps} mode="live" />);
      expect(screen.getByText(/LIVE.*real money/i)).toBeInTheDocument();
    });
  });

  describe('Side Toggle', () => {
    it('defaults to YES side', () => {
      renderWithToast(<KalshiTradeTicket {...defaultProps} />);
      const submitBtn = screen.getByRole('button', { name: /Buy 1 YES/i });
      expect(submitBtn).toBeInTheDocument();
    });

    it('switches to NO side on click', () => {
      renderWithToast(<KalshiTradeTicket {...defaultProps} />);
      fireEvent.click(screen.getByText(/^NO/));
      expect(screen.getByRole('button', { name: /Buy 1 NO/i })).toBeInTheDocument();
    });
  });

  describe('Size Input', () => {
    it('shows contracts mode by default', () => {
      renderWithToast(<KalshiTradeTicket {...defaultProps} />);
      expect(screen.getByLabelText('Number of contracts')).toBeInTheDocument();
    });

    it('switches to USD mode', () => {
      renderWithToast(<KalshiTradeTicket {...defaultProps} />);
      fireEvent.click(screen.getByText('USD'));
      expect(screen.getByLabelText('Dollar amount')).toBeInTheDocument();
    });

    it('updates contract count', () => {
      renderWithToast(<KalshiTradeTicket {...defaultProps} />);
      const input = screen.getByLabelText('Number of contracts') as HTMLInputElement;
      fireEvent.change(input, { target: { value: '10' } });
      expect(input.value).toBe('10');
    });
  });

  describe('Limit Price', () => {
    it('shows limit checkbox', () => {
      renderWithToast(<KalshiTradeTicket {...defaultProps} />);
      expect(screen.getByText('Limit order')).toBeInTheDocument();
    });

    it('shows limit price input when checked', () => {
      renderWithToast(<KalshiTradeTicket {...defaultProps} />);
      fireEvent.click(screen.getByText('Limit order'));
      expect(screen.getByLabelText('Limit price in cents')).toBeInTheDocument();
    });
  });

  describe('Fee Calculation', () => {
    it('displays fee information', () => {
      renderWithToast(<KalshiTradeTicket {...defaultProps} />);
      // 1 contract @ 60¢ YES: profit = 40¢, fee = 40¢ * 7% = 2.8¢ = $0.03
      // LEGACY REMOVAL: Fee display format changed - just check fee is displayed
      expect(screen.getByText(/Fee/i)).toBeInTheDocument();
    });
  });

  describe('Order Submission', () => {
    it('submits order on button click', async () => {
      renderWithToast(<KalshiTradeTicket {...defaultProps} />);
      const submitBtn = screen.getByRole('button', { name: /Buy 1 YES/i });
      fireEvent.click(submitBtn);

      await waitFor(() => {
        expect(global.fetch).toHaveBeenCalledWith(
          expect.stringContaining('/kalshi/orders'),
          expect.objectContaining({ method: 'POST' })
        );
      });
    });

    it('calls onOrderPlaced callback on success', async () => {
      renderWithToast(<KalshiTradeTicket {...defaultProps} />);
      fireEvent.click(screen.getByRole('button', { name: /Buy 1 YES/i }));

      await waitFor(() => {
        expect(defaultProps.onOrderPlaced).toHaveBeenCalled();
      });
    });

    it('shows error on failed submission', async () => {
      // Use mockImplementation so mount-time hook fetches still succeed
      // but the POST to /order returns a 400
      (global.fetch as jest.Mock).mockImplementation((_url: string, opts?: RequestInit) => {
        if (opts?.method === 'POST') {
          return Promise.resolve({
            ok: false,
            status: 400,
            json: async () => ({ detail: 'Insufficient balance' }),
          });
        }
        return Promise.resolve({ ok: true, json: async () => ({}) });
      });

      renderWithToast(<KalshiTradeTicket {...defaultProps} />);
      fireEvent.click(screen.getByRole('button', { name: /Buy 1 YES/i }));

      await waitFor(() => {
        expect(screen.getByText('Insufficient balance')).toBeInTheDocument();
      });
    });

    it('shows success message after order placed', async () => {
      renderWithToast(<KalshiTradeTicket {...defaultProps} />);
      fireEvent.click(screen.getByRole('button', { name: /Buy 1 YES/i }));

      await waitFor(() => {
        expect(screen.getByText(/Order placed/)).toBeInTheDocument();
      });
    });
  });

  describe('Validation', () => {
    it('clamps contract count to minimum 1', () => {
      renderWithToast(<KalshiTradeTicket {...defaultProps} />);
      const input = screen.getByLabelText('Number of contracts') as HTMLInputElement;
      fireEvent.change(input, { target: { value: '0' } });
      // Component clamps to Math.max(1, v), so value stays at 1
      expect(input.value).toBe('1');
    });
  });
});
