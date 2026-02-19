import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import PriceTicker from '../PriceTicker';

describe('PriceTicker', () => {
  const baseData = {
    symbol: 'BTC/USD',
    last: 45000.5,
    change: 500.25,
    changePercent: 1.12,
    volume: 1_234_567,
    timestamp: '2024-01-30T15:00:00Z',
  };

  const renderTicker = (overrides: Partial<typeof baseData> = {}, props: Partial<React.ComponentProps<typeof PriceTicker>> = {}) => {
    const data = { ...baseData, ...overrides };
    return render(
      <PriceTicker
        symbol={data.symbol}
        initialData={data}
        {...props}
      />
    );
  };

  it('renders basic price information', () => {
    const { container } = renderTicker();
    expect(screen.getByText('BTC/USD')).toBeInTheDocument();
    expect(screen.getByText('$45,000.50')).toBeInTheDocument();
    // Change is split across elements, check container content
    expect(container.textContent).toContain('↑');
    expect(container.textContent).toContain('500.25');
    expect(container.textContent).toContain('112.00%');
  });

  it('renders negative price changes', () => {
    const { container } = renderTicker({ change: -250.75, changePercent: -0.56 });
    expect(container.textContent).toContain('↓');
    expect(container.textContent).toContain('250.75');
    expect(container.textContent).toContain('56.00%');
  });

  it('renders volume and timestamp when enabled', () => {
    renderTicker({}, { showVolume: true, showTimestamp: true });
    // Volume is formatted with formatNumber (no decimals)
    expect(screen.getByText(/1,234,567/)).toBeInTheDocument();
    // Time format is HH:MM:SS
    expect(screen.getByText(/\d{1,2}:\d{2}:\d{2}/)).toBeInTheDocument();
  });

  it('applies positive delta styles', () => {
    renderTicker();
    // Find the container with the delta color class
    const changeContainer = screen.getByText('↑').parentElement;
    expect(changeContainer).toHaveClass('text-green-500');
  });

  it('applies negative delta styles', () => {
    renderTicker({ change: -250.75, changePercent: -0.56 });
    const changeContainer = screen.getByText('↓').parentElement;
    expect(changeContainer).toHaveClass('text-red-500');
  });

  it('updates price when rerendered with new data', async () => {
    const { rerender, container } = renderTicker();
    const updatedData = {
      ...baseData,
      last: 45500.75,
      change: 1000.5,
      changePercent: 2.24,
    };

    rerender(
      <PriceTicker
        symbol={updatedData.symbol}
        initialData={updatedData}
      />
    );

    // Verify updated price renders using container text content
    await waitFor(() => {
      expect(container.textContent).toContain('$45,500.75');
    });
    
    // Verify change values appear somewhere in the document
    expect(container.textContent).toContain('1,000.50');
    expect(container.textContent).toContain('224.00%');
  });
});
