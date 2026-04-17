/**
 * Centralized test utilities for MERID UI
 * Common mocks and setup functions for consistent testing
 */

import React from 'react';

// Mock data factories
export const createMockKalshiBalance = (overrides = {}) => ({
  available: 10000,
  locked: 2000,
  total: 12000,
  ...overrides,
});

export const createMockKalshiPosition = (overrides = {}) => ({
  id: 'pos-1',
  ticker: 'HIGH-25DEC2024',
  outcome: 'Yes',
  side: 'Yes',
  size: 10,
  avg_price: 0.45,
  unrealized_pnl: 50,
  ...overrides,
});

export const createMockKalshiOrder = (overrides = {}) => ({
  id: 'order-1',
  ticker: 'HIGH-25DEC2024',
  outcome: 'Yes',
  side: 'Yes',
  size: 10,
  price: 0.45,
  status: 'filled',
  created_at: '2024-01-01T00:00:00Z',
  ...overrides,
});

export const createMockAgentMetrics = (overrides = {}) => ({
  agent_id: 'kalshi-test-agent',
  total_fills: 100,
  total_closes: 80,
  total_volume_usd: 50000,
  win_rate: 0.65,
  avg_pnl_per_trade: 5.50,
  total_pnl: 550,
  sharpe_ratio: 1.8,
  edge_accuracy: 0.72,
  confidence_calibration_error: 0.05,
  last_trade_at: '2024-01-01T12:00:00Z',
  ...overrides,
});

// Mock component factories
export const createMockComponent = (name: string, testId: string) => {
  const MockComponent = () => React.createElement('div', { 'data-testid': testId }, name);
  MockComponent.displayName = `Mock${name}`;
  return MockComponent;
};

// Common mock components
export const MockKalshiModeBadge = createMockComponent('KalshiModeBadge', 'mode-badge');
export const MockExecutionGateStrip = createMockComponent('ExecutionGateStrip', 'execution-gate-strip');
export const MockKalshiInsightsPanel = createMockComponent('KalshiInsightsPanel', 'insights-panel');
export const MockPublishPipelinePanel = createMockComponent('PublishPipelinePanel', 'publish-pipeline');
export const MockErrorBar = createMockComponent('ErrorBar', 'error-bar');
export const MockKalshiPnlChart = createMockComponent('KalshiPnlChart', 'pnl-chart');
export const MockKalshiRiskFeed = createMockComponent('KalshiRiskFeed', 'risk-feed');
export const MockOrderGroupPanel = createMockComponent('OrderGroupPanel', 'order-group-panel');

// Mock hooks
export const mockUseApiData = jest.fn();

// Setup function for common mocks
export const setupMocks = () => {
  // Mock useApiData hook
  jest.mock('../../hooks/useApiData', () => ({
    useApiData: (...args: unknown[]) => mockUseApiData(...args),
  }));

  // Mock common components
  jest.mock('../../components/KalshiModeBadge', () => ({
    __esModule: true,
    default: MockKalshiModeBadge,
  }));

  jest.mock('../../components/ExecutionGateStrip', () => ({
    __esModule: true,
    default: MockExecutionGateStrip,
  }));

  jest.mock('../../components/KalshiInsightsPanel', () => ({
    __esModule: true,
    default: MockKalshiInsightsPanel,
  }));

  jest.mock('../../components/PublishPipelinePanel', () => ({
    __esModule: true,
    default: MockPublishPipelinePanel,
  }));

  jest.mock('../../components/ErrorBar', () => ({
    __esModule: true,
    default: MockErrorBar,
  }));

  jest.mock('../../components/KalshiPnlChart', () => ({
    __esModule: true,
    default: MockKalshiPnlChart,
  }));

  jest.mock('../../components/KalshiRiskFeed', () => ({
    __esModule: true,
    default: MockKalshiRiskFeed,
  }));

  jest.mock('../../components/OrderGroupPanel', () => ({
    __esModule: true,
    default: MockOrderGroupPanel,
  }));

  // Mock API constants
  jest.mock('../../config/constants', () => ({
    API_BASE_URL: 'http://localhost:8000',
    API_ENDPOINTS: {
      KALSHI_BALANCE: '/api/v1/kalshi/balance',
      KALSHI_POSITIONS: '/api/v1/kalshi/positions',
      KALSHI_ORDERS: '/api/v1/kalshi/orders',
      KALSHI_GRID_PERFORMANCE_AGENTS: '/api/v1/kalshi/grid/performance/agents',
      // Add more endpoints as needed
    },
    DEFAULTS: {
      POLLING_INTERVALS: {
        FAST: 1000,
        MEDIUM: 5000,
        SLOW: 10000,
      },
    },
  }));

  // Mock logger
  jest.mock('../../ui/logger', () => ({
    log: {
      debug: jest.fn(),
      info: jest.fn(),
      warn: jest.fn(),
      error: jest.fn(),
    },
  }));
};

// Helper functions for testing
import { screen } from '@testing-library/react';

export const waitForElement = (testId: string) => 
  screen.findByTestId(testId);

export const expectElementToExist = (testId: string) => 
  expect(screen.getByTestId(testId)).toBeInTheDocument();

export const expectElementNotToExist = (testId: string) => 
  expect(screen.queryByTestId(testId)).not.toBeInTheDocument();

// Reset all mocks
export const resetAllMocks = () => {
  jest.clearAllMocks();
  mockUseApiData.mockReset();
};

// Default export
export default {
  createMockKalshiBalance,
  createMockKalshiPosition,
  createMockKalshiOrder,
  createMockAgentMetrics,
  createMockComponent,
  MockKalshiModeBadge,
  MockExecutionGateStrip,
  MockKalshiInsightsPanel,
  MockPublishPipelinePanel,
  MockErrorBar,
  MockKalshiPnlChart,
  MockKalshiRiskFeed,
  MockOrderGroupPanel,
  mockUseApiData,
  setupMocks,
  waitForElement,
  expectElementToExist,
  expectElementNotToExist,
  resetAllMocks,
};
