import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import MetricCard from '../MetricCard';

describe('MetricCard', () => {
  const defaultProps = {
    label: 'Test Metric',
    value: '$1,234.56',
  };

  it('renders basic metric card', () => {
    render(<MetricCard {...defaultProps} />);
    expect(screen.getByText('Test Metric')).toBeInTheDocument();
    expect(screen.getByText('$1,234.56')).toBeInTheDocument();
  });

  it('renders with delta and trend', () => {
    render(
      <MetricCard
        {...defaultProps}
        delta={12.5}
        trend="up"
      />
    );
    expect(screen.getByText('+12.5%')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /trend/i })).toBeInTheDocument();
  });

  it('renders with negative delta', () => {
    render(
      <MetricCard
        {...defaultProps}
        delta={-5.2}
        trend="down"
      />
    );
    expect(screen.getByText('-5.2%')).toBeInTheDocument();
  });

  it('renders with status indicator', () => {
    render(
      <MetricCard
        {...defaultProps}
        status="GOOD"
      />
    );
    expect(screen.getByTestId('status-indicator')).toBeInTheDocument();
  });

  it('applies correct CSS classes based on status', () => {
    const { container } = render(
      <MetricCard
        {...defaultProps}
        status="BAD"
      />
    );
    expect(container.firstChild).toHaveClass('border-red-500');
  });

  it('handles missing optional props', () => {
    render(<MetricCard label="Test" value="123" />);
    expect(screen.getByText('Test')).toBeInTheDocument();
    expect(screen.getByText('123')).toBeInTheDocument();
    expect(screen.queryByTestId('status-indicator')).not.toBeInTheDocument();
  });

  it('formats delta with custom precision', () => {
    render(
      <MetricCard
        {...defaultProps}
        deltaPercent={0.1234}
        trend="up"
      />
    );
    expect(screen.getByText('+0.12%')).toBeInTheDocument();
  });
});
