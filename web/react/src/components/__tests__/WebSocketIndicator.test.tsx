/**
 * WebSocketIndicator unit tests
 */

import { render, screen } from '@testing-library/react';
import WebSocketIndicator from '../WebSocketIndicator';

// Mock the store
jest.mock('../../store', () => ({
  useKalshiStore: jest.fn(),
}));

describe('WebSocketIndicator', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders connected state', () => {
    const { useKalshiStore } = require('../../store');
    useKalshiStore.mockReturnValue(true);

    render(<WebSocketIndicator />);

    expect(screen.getByText('Connected')).toBeInTheDocument();
  });

  it('renders disconnected state', () => {
    const { useKalshiStore } = require('../../store');
    useKalshiStore.mockReturnValue(false);

    render(<WebSocketIndicator />);

    expect(screen.getByText('Disconnected')).toBeInTheDocument();
  });

  it('renders connecting state', () => {
    const { useKalshiStore } = require('../../store');
    useKalshiStore.mockReturnValue(null);

    render(<WebSocketIndicator />);

    expect(screen.getByText('Connecting...')).toBeInTheDocument();
  });
});
