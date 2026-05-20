/**
 * App Integration Tests
 * 
 * Tests for the MERID Kalshi-focused UI:
 * - App renders without crashing
 * - Code splitting with lazy loading
 */

import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import App from '../../App';

// Mock the API hooks to prevent actual network calls
jest.mock('../../hooks/useApiData', () => ({
  useApiData: jest.fn(() => ({ data: null, loading: false, error: null, refetch: jest.fn() })),
}));

jest.mock('../../hooks/useFillToast', () => ({
  useFillToast: jest.fn(),
}));

jest.mock('../../hooks/useDashboard', () => ({
  SystemHealthCard: () => <div data-testid="system-health-card">System Health</div>,
  KalshiHealthCard: () => <div data-testid="kalshi-health-card">Kalshi Health</div>,
  AgentStatusCard: () => <div data-testid="agent-status-card">Agent Status</div>,
  RiskProtectionCard: () => <div data-testid="risk-protection-card">Risk Protection</div>,
}));

// Mock useNetworkStatusProvider
jest.mock('../../hooks/useNetworkStatusProvider', () => ({
  useNetworkStatus: () => ({ isOnline: true, backendReachable: true }),
  NetworkProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Mock localStorage
const mockLocalStorage = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  removeItem: jest.fn(),
};
Object.defineProperty(window, 'localStorage', { value: mockLocalStorage });

describe('App Integration', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockLocalStorage.getItem.mockImplementation(() => null);
  });

  it('renders without crashing', () => {
    render(<App />);
    // App should render without crashing
    expect(screen.getByText('Overview')).toBeInTheDocument();
  });

  it('starts on overview view', () => {
    render(<App />);
    // Should start on overview view
    expect(screen.getByText('Overview')).toBeInTheDocument();
  });
});

describe('Code Splitting Optimizations', () => {
  it('all view components are lazy-loaded', () => {
    // Check that views are lazy-loaded for code splitting
    const appSource = require('fs').readFileSync(require.resolve('../../App.tsx'), 'utf-8');
    expect(appSource).toMatch(/lazy\(\(\) => import\(/);
  });
});
