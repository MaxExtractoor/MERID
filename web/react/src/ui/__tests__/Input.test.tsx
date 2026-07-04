/**
 * Input unit tests
 */

import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Input } from '../Input';

describe('Input', () => {
  it('renders input with label', () => {
    render(<Input label="Test Label" />);
    expect(screen.getByLabelText('Test Label')).toBeInTheDocument();
  });

  it('renders error message', () => {
    render(<Input label="Test" error="Error message" />);
    expect(screen.getByText('Error message')).toBeInTheDocument();
    const input = screen.getByLabelText('Test');
    expect(input).toHaveAttribute('aria-invalid', 'true');
  });

  it('renders helper text', () => {
    render(<Input label="Test" helperText="Helper text" />);
    expect(screen.getByText('Helper text')).toBeInTheDocument();
  });

  it('allows typing in input', async () => {
    const user = userEvent.setup();
    render(<Input label="Test" />);
    const input = screen.getByLabelText('Test');
    
    await user.type(input, 'test value');
    expect(input).toHaveValue('test value');
  });

  it('disables input when disabled prop is set', () => {
    render(<Input label="Test" disabled />);
    const input = screen.getByLabelText('Test');
    expect(input).toBeDisabled();
  });
});
