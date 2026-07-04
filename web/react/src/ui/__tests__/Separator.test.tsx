/**
 * Separator unit tests
 */

import { render, screen } from '@testing-library/react';
import { Separator } from '../Separator';

describe('Separator', () => {
  it('renders horizontal separator by default', () => {
    render(<Separator />);
    const separator = screen.getByRole('separator');
    expect(separator).toBeInTheDocument();
    expect(separator).toHaveAttribute('aria-orientation', 'horizontal');
  });

  it('renders vertical separator when specified', () => {
    render(<Separator orientation="vertical" />);
    const separator = screen.getByRole('separator');
    expect(separator).toHaveAttribute('aria-orientation', 'vertical');
  });

  it('applies custom className', () => {
    render(<Separator className="custom-class" />);
    const separator = screen.getByRole('separator');
    expect(separator).toHaveClass('custom-class');
  });
});
