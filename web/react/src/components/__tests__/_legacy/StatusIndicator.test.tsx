import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import StatusIndicator from '../StatusIndicator';

describe('StatusIndicator', () => {
  it('renders online status', () => {
    render(<StatusIndicator status="ONLINE" />);
    expect(screen.getByText('Online')).toBeInTheDocument();
    expect(screen.getByTestId('status-dot')).toHaveClass('bg-green-500');
  });

  it('renders degraded status', () => {
    render(<StatusIndicator status="DEGRADED" />);
    expect(screen.getByText('Degraded')).toBeInTheDocument();
    expect(screen.getByTestId('status-dot')).toHaveClass('bg-yellow-500');
  });

  it('renders offline status', () => {
    render(<StatusIndicator status="OFFLINE" />);
    expect(screen.getByText('Offline')).toBeInTheDocument();
    expect(screen.getByTestId('status-dot')).toHaveClass('bg-red-500');
  });

  it('renders with custom text', () => {
    render(<StatusIndicator status="ONLINE" text="Connected" />);
    expect(screen.getByText('Connected')).toBeInTheDocument();
    expect(screen.queryByText('Online')).not.toBeInTheDocument();
  });

  it('renders without text', () => {
    render(<StatusIndicator status="ONLINE" showText={false} />);
    expect(screen.queryByText('Online')).not.toBeInTheDocument();
    expect(screen.getByTestId('status-dot')).toBeInTheDocument();
  });

  it('renders with tooltip', () => {
    render(<StatusIndicator status="ONLINE" tooltip="System is operational" />);
    const indicator = screen.getByTestId('status-indicator');
    expect(indicator).toHaveAttribute('title', 'System is operational');
  });

  it('applies custom size', () => {
    render(<StatusIndicator status="ONLINE" size="lg" />);
    const dot = screen.getByTestId('status-dot');
    expect(dot).toHaveClass('w-4', 'h-4');
  });

  it('applies custom className', () => {
    render(<StatusIndicator status="ONLINE" className="rounded-full" />);
    const container = screen.getByTestId('status-indicator');
    expect(container).toHaveClass('rounded-full');
  });
});
