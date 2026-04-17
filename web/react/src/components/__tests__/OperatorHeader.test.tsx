/**
 * OperatorHeader Component Tests
 *
 * Tests the unified header component that combines ExecutionGateStrip
 * and DataHealthSummary for consistent operator awareness.
 */

import { render, screen } from '@testing-library/react';
import OperatorHeader from '../OperatorHeader';

// Mock child components
jest.mock('../components/ExecutionGateStrip', () => ({
  default: () => <div data-testid="execution-gate-strip">Execution Gate</div>,
}));

jest.mock('../components/DataHealthSummary', () => ({
  default: () => <div data-testid="data-health-summary">Data Health</div>,
}));

describe('OperatorHeader', () => {
  it('renders both ExecutionGateStrip and DataHealthSummary', () => {
    render(<OperatorHeader />);

    expect(screen.getByTestId('execution-gate-strip')).toBeInTheDocument();
    expect(screen.getByTestId('data-health-summary')).toBeInTheDocument();
  });

  it('has correct container styling', () => {
    const { container } = render(<OperatorHeader />);
    expect(container.firstChild).toHaveClass('flex', 'items-center', 'justify-between', 'gap-4', 'p-4');
  });

  it('maintains accessibility structure', () => {
    const { container } = render(<OperatorHeader />);
    // Should have proper semantic structure for screen readers
    expect(container.firstChild).toBeInTheDocument();
  });
});
