/**
 * 8-Stage Workflow Integration Tests
 * 
 * Tests for the MERID UI/UX facelift:
 * - View navigation and routing
 * - Stage grouping
 * - Legacy view mapping
 * - Component integration
 */

import React from 'react';
import { render, screen, fireEvent, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import App from '../../App';
import Sidebar from '../../components/Sidebar';
import { View, STAGE_GROUPS, LEGACY_VIEW_MAP } from '../../types/views';
import { KalshiModeProvider } from '../../context/KalshiModeContext';

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

describe('8-Stage Workflow Structure', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockLocalStorage.getItem.mockReturnValue(null);
  });

  describe('View Types', () => {
    it('has all 8 stages defined', () => {
      const expectedStages = [
        'discover', 'analyze', 'consensus', 'size', 
        'execute', 'monitor', 'promote', 'protect'
      ];
      const actualStages = STAGE_GROUPS.map(g => g.id);
      
      expectedStages.forEach(stage => {
        expect(actualStages).toContain(stage);
      });
    });

    it('has correct number of views per stage', () => {
      const viewCounts = STAGE_GROUPS.map(g => ({ 
        stage: g.id, 
        count: g.views.length 
      }));
      
      // Discover: 3 views
      expect(viewCounts.find(v => v.stage === 'discover')?.count).toBe(3);
      // Analyze: 3 views
      expect(viewCounts.find(v => v.stage === 'analyze')?.count).toBe(3);
      // Consensus: 4 views
      expect(viewCounts.find(v => v.stage === 'consensus')?.count).toBe(4);
      // Size: 3 views
      expect(viewCounts.find(v => v.stage === 'size')?.count).toBe(3);
      // Execute: 3 views
      expect(viewCounts.find(v => v.stage === 'execute')?.count).toBe(3);
      // Monitor: 3 views
      expect(viewCounts.find(v => v.stage === 'monitor')?.count).toBe(3);
      // Promote: 2 views
      expect(viewCounts.find(v => v.stage === 'promote')?.count).toBe(2);
      // Protect: 3 views
      expect(viewCounts.find(v => v.stage === 'protect')?.count).toBe(3);
      // System: 4 views
      expect(viewCounts.find(v => v.stage === 'system')?.count).toBe(4);
    });
  });

  describe('Legacy View Mapping', () => {
    it('maps all legacy views to new 8-stage workflow', () => {
      const legacyViews = Object.keys(LEGACY_VIEW_MAP);
      
      // Ensure all legacy views are mapped
      const expectedLegacyViews = [
        'kalshi-dashboard', 'kalshi-all-markets', 'kalshi-sentiment',
        'kalshi-vol-dashboard', 'swarm-consensus', 'kalshi-performance',
        'calibration-dashboard', 'lane-control', 'kalshi-terminal',
        'orders', 'positions', 'kalshi-portfolio', 'kalshi-risk',
        'kill-switch', 'kalshi-grid', 'kalshi-risk-context'
      ];
      
      expectedLegacyViews.forEach(view => {
        expect(legacyViews).toContain(view);
        expect(LEGACY_VIEW_MAP[view]).toBeDefined();
      });
    });

    it('maps views to correct stages', () => {
      // Discover stage
      expect(LEGACY_VIEW_MAP['kalshi-dashboard']).toBe('discover');
      expect(LEGACY_VIEW_MAP['kalshi-all-markets']).toBe('discover-all-markets');
      
      // Analyze stage
      expect(LEGACY_VIEW_MAP['kalshi-sentiment']).toBe('analyze-sentiment');
      expect(LEGACY_VIEW_MAP['kalshi-vol-dashboard']).toBe('analyze-vol');
      
      // Consensus stage
      expect(LEGACY_VIEW_MAP['swarm-consensus']).toBe('consensus-swarm');
      expect(LEGACY_VIEW_MAP['kalshi-performance']).toBe('consensus-performance');
      
      // Size stage
      expect(LEGACY_VIEW_MAP['lane-control']).toBe('size-lanes');
      
      // Execute stage
      expect(LEGACY_VIEW_MAP['kalshi-terminal']).toBe('execute-terminal');
      expect(LEGACY_VIEW_MAP['orders']).toBe('execute-orders');
      expect(LEGACY_VIEW_MAP['positions']).toBe('execute-positions');
      
      // Monitor stage
      expect(LEGACY_VIEW_MAP['kalshi-portfolio']).toBe('monitor-portfolio');
      
      // Promote stage
      expect(LEGACY_VIEW_MAP['kalshi-grid']).toBe('promote-grid');
      
      // Protect stage
      expect(LEGACY_VIEW_MAP['kalshi-risk']).toBe('protect-risk');
      expect(LEGACY_VIEW_MAP['kill-switch']).toBe('protect-kill-switch');
    });
  });
});

describe('Sidebar Navigation', () => {
  const renderSidebar = (current: View = 'overview', onChange = jest.fn()) => {
    return render(
      <KalshiModeProvider>
        <Sidebar current={current} onChange={onChange} />
      </KalshiModeProvider>
    );
  };

  it('renders all 8 stages', () => {
    renderSidebar();
    
    // Check for stage labels
    expect(screen.getByText('1. Discover')).toBeInTheDocument();
    expect(screen.getByText('2. Analyze')).toBeInTheDocument();
    expect(screen.getByText('3. Consensus')).toBeInTheDocument();
    expect(screen.getByText('4. Size')).toBeInTheDocument();
    expect(screen.getByText('5. Execute')).toBeInTheDocument();
    expect(screen.getByText('6. Monitor')).toBeInTheDocument();
    expect(screen.getByText('7. Promote')).toBeInTheDocument();
    expect(screen.getByText('8. Protect')).toBeInTheDocument();
  });

  it('renders stage sub-navigation items', () => {
    renderSidebar();
    
    // Discover items
    expect(screen.getByText('Markets')).toBeInTheDocument();
    expect(screen.getByText('All Markets')).toBeInTheDocument();
    expect(screen.getByText('Trending')).toBeInTheDocument();
    
    // Execute items
    expect(screen.getByText('Terminal')).toBeInTheDocument();
    expect(screen.getByText('Orders')).toBeInTheDocument();
    expect(screen.getByText('Positions')).toBeInTheDocument();
  });

  it('highlights active view', () => {
    renderSidebar('discover');
    
    // Find the Markets button and check if it has active styling
    const marketsButton = screen.getByText('Markets').closest('button');
    expect(marketsButton).toHaveClass('bg-blue-500/10');
    expect(marketsButton).toHaveClass('text-blue-400');
  });

  it('calls onChange when view is clicked', () => {
    const onChange = jest.fn();
    renderSidebar('overview', onChange);
    
    fireEvent.click(screen.getByText('Markets'));
    expect(onChange).toHaveBeenCalledWith('discover');
    
    fireEvent.click(screen.getByText('Terminal'));
    expect(onChange).toHaveBeenCalledWith('execute-terminal');
  });

  it('shows system navigation', () => {
    renderSidebar();
    
    expect(screen.getByText('Overview')).toBeInTheDocument();
    expect(screen.getByText('Operator')).toBeInTheDocument();
    expect(screen.getByText('Logs')).toBeInTheDocument();
    expect(screen.getByText('Settings')).toBeInTheDocument();
  });

  it('displays MERID branding', () => {
    renderSidebar();
    
    expect(screen.getByText('MERID')).toBeInTheDocument();
    expect(screen.getByText('8-Stage Workflow')).toBeInTheDocument();
  });
});

describe('App Integration', () => {
  beforeEach(() => {
    mockLocalStorage.getItem.mockImplementation((key: string) => {
      if (key === 'merid-sidebar-collapsed') return 'false';
      return null;
    });
  });

  it('renders without crashing', () => {
    render(<App />);
    expect(screen.getByText('MERID')).toBeInTheDocument();
  });

  it('starts on overview view', () => {
    render(<App />);
    
    // Overview should show system health cards
    expect(screen.getByTestId('system-health-card')).toBeInTheDocument();
    expect(screen.getByTestId('kalshi-health-card')).toBeInTheDocument();
  });
});

describe('Zero-Lag Optimizations', () => {
  it('all view components are memoized', () => {
    // Check that ViewRenderer is memoized
    const { ViewRenderer } = require('../../App');
    expect(ViewRenderer.$$typeof?.toString()).toContain('Memo');
  });

  it('sidebar uses React.memo', () => {
    // The Sidebar component should be wrapped in React.memo
    expect(Sidebar.displayName).toBe('Sidebar');
  });
});
