/**
 * Tests for RiskProtectionsPanel - Critical risk management UI
 * Focus: Deterministic testing of risk controls and protections
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import RiskProtectionsPanel from '../RiskProtectionsPanel';

// Mock hooks
jest.mock('../../hooks/useRiskProtections', () => ({
  __esModule: true,
  default: jest.fn(() => ({
    protections: [
      {
        id: 'max-position',
        name: 'Max Position Size',
        enabled: true,
        value: 10000,
        threshold: 10000,
        status: 'active',
      },
      {
        id: 'stop-loss',
        name: 'Stop Loss',
        enabled: true,
        value: -5000,
        threshold: -5000,
        status: 'active',
      },
    ],
    loading: false,
    error: null,
    toggleProtection: jest.fn(),
    updateThreshold: jest.fn(),
  })),
}));

describe('RiskProtectionsPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Rendering', () => {
    it('renders risk protections panel', () => {
      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );
      
      expect(screen.getByText(/Risk Protections/i)).toBeInTheDocument();
    });

    it('displays protection items', () => {
      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );
      
      expect(screen.getByText(/Max Position Size/i)).toBeInTheDocument();
      expect(screen.getByText(/Stop Loss/i)).toBeInTheDocument();
    });

    it('shows loading state', () => {
      const useRiskProtections = require('../../hooks/useRiskProtections').default;
      useRiskProtections.mockReturnValue({
        protections: [],
        loading: true,
        error: null,
        toggleProtection: jest.fn(),
        updateThreshold: jest.fn(),
      });

      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );
      
      expect(screen.getByText(/Loading/i)).toBeInTheDocument();
    });

    it('shows error state', () => {
      const useRiskProtections = require('../../hooks/useRiskProtections').default;
      useRiskProtections.mockReturnValue({
        protections: [],
        loading: false,
        error: 'Failed to load protections',
        toggleProtection: jest.fn(),
        updateThreshold: jest.fn(),
      });

      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );
      
      expect(screen.getByText(/Failed to load/i)).toBeInTheDocument();
    });
  });

  describe('Protection Status', () => {
    it('displays enabled protections', () => {
      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );
      
      const toggles = screen.getAllByRole('switch');
      expect(toggles.length).toBeGreaterThan(0);
    });

    it('shows protection thresholds', () => {
      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );
      
      expect(screen.getByText(/10000/)).toBeInTheDocument();
      expect(screen.getByText(/-5000/)).toBeInTheDocument();
    });

    it('indicates active protection status', () => {
      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );
      
      expect(screen.getAllByText(/active/i).length).toBeGreaterThan(0);
    });
  });

  describe('User Interactions', () => {
    it('handles protection toggle', async () => {
      const mockToggle = jest.fn();
      const useRiskProtections = require('../../hooks/useRiskProtections').default;
      useRiskProtections.mockReturnValue({
        protections: [
          {
            id: 'max-position',
            name: 'Max Position Size',
            enabled: true,
            value: 10000,
            threshold: 10000,
            status: 'active',
          },
        ],
        loading: false,
        error: null,
        toggleProtection: mockToggle,
        updateThreshold: jest.fn(),
      });

      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );
      
      const toggle = screen.getByRole('switch');
      fireEvent.click(toggle);
      
      await waitFor(() => {
        expect(mockToggle).toHaveBeenCalledWith('max-position');
      });
    });

    it('handles threshold update', async () => {
      const mockUpdate = jest.fn();
      const useRiskProtections = require('../../hooks/useRiskProtections').default;
      useRiskProtections.mockReturnValue({
        protections: [
          {
            id: 'max-position',
            name: 'Max Position Size',
            enabled: true,
            value: 10000,
            threshold: 10000,
            status: 'active',
          },
        ],
        loading: false,
        error: null,
        toggleProtection: jest.fn(),
        updateThreshold: mockUpdate,
      });

      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );
      
      const input = screen.getByDisplayValue('10000');
      fireEvent.change(input, { target: { value: '15000' } });
      fireEvent.blur(input);
      
      await waitFor(() => {
        expect(mockUpdate).toHaveBeenCalledWith('max-position', 15000);
      });
    });
  });

  describe('Edge Cases', () => {
    it('handles empty protections list', () => {
      const useRiskProtections = require('../../hooks/useRiskProtections').default;
      useRiskProtections.mockReturnValue({
        protections: [],
        loading: false,
        error: null,
        toggleProtection: jest.fn(),
        updateThreshold: jest.fn(),
      });

      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );
      
      expect(screen.getByText(/No protections/i)).toBeInTheDocument();
    });

    it('handles invalid threshold input', async () => {
      const mockUpdate = jest.fn();
      const useRiskProtections = require('../../hooks/useRiskProtections').default;
      useRiskProtections.mockReturnValue({
        protections: [
          {
            id: 'max-position',
            name: 'Max Position Size',
            enabled: true,
            value: 10000,
            threshold: 10000,
            status: 'active',
          },
        ],
        loading: false,
        error: null,
        toggleProtection: jest.fn(),
        updateThreshold: mockUpdate,
      });

      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );
      
      const input = screen.getByDisplayValue('10000');
      fireEvent.change(input, { target: { value: 'invalid' } });
      fireEvent.blur(input);
      
      await waitFor(() => {
        expect(mockUpdate).not.toHaveBeenCalled();
      });
    });
  });

  describe('Accessibility', () => {
    it('has accessible toggle controls', () => {
      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );
      
      const toggles = screen.getAllByRole('switch');
      toggles.forEach(toggle => {
        expect(toggle).toHaveAttribute('aria-checked');
      });
    });

    it('has accessible input fields', () => {
      render(
        <BrowserRouter>
          <RiskProtectionsPanel />
        </BrowserRouter>
      );
      
      const inputs = screen.getAllByRole('spinbutton');
      expect(inputs.length).toBeGreaterThan(0);
    });
  });
});
