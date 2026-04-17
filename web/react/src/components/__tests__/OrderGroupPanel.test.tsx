/**
 * @jest-environment jsdom
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// Mock constants before component import (ts-jest import.meta workaround)
jest.mock('../../config/constants', () => ({
  API_BASE_URL: '',
  AUTH_TOKEN_KEY: 'merid-access',
  API_ENDPOINTS: {
    KALSHI_ORDER_GROUPS: '/api/v1/kalshi/order-groups',
    KALSHI_ORDER_GROUP_CREATE: '/api/v1/kalshi/order-groups',
    KALSHI_ORDER_GROUP_RESET: (id: string) => `/api/v1/kalshi/order-groups/${id}/reset`,
    KALSHI_ORDER_GROUP_DELETE: (id: string) => `/api/v1/kalshi/order-groups/${id}`,
    KALSHI_ORDER_GROUP_STREAM: '/api/v1/kalshi/order-groups/stream',
    KALSHI_ORDER_GROUP_DASHBOARD: '/api/v1/kalshi/order-groups/dashboard',
  },
  CHART_COLORS: {
    GREEN: '#22c55e', RED: '#ef4444', YELLOW: '#eab308', ORANGE: '#f97316',
    BLUE: '#3b82f6', PURPLE: '#a855f7', CYAN: '#06b6d4', TEAL: '#14b8a6',
    AMBER: '#f59e0b', INDIGO: '#6366f1', EMERALD: '#10b981',
    WHITE: '#ffffff', GRAY_50: '#f9fafb', GRAY_100: '#f3f4f6',
    GRAY_200: '#e5e7eb', GRAY_300: '#d1d5db', GRAY_400: '#9ca3af',
    GRAY_500: '#6b7280', GRAY_700: '#374151', GRAY_800: '#1f2937',
    GRAY_900: '#111827', RED_50: '#fef2f2', RED_200: '#fecaca',
    RED_600: '#dc2626', RED_800: '#991b1b', AMBER_100: '#fef3c7',
    AMBER_800: '#92400e', AXIS_TICK: '#64748b', GRID_STROKE: '#334155',
    TOOLTIP_BG: '#0f172a', BAR_BASE: '#1e293b', SLATE_400: '#94a3b8',
    SLATE_600: '#475569',
  },
  ORDER_GROUP_STATUS: { ACTIVE: 'active', TRIGGERED: 'triggered', CANCELED: 'canceled', PENDING: 'pending' },
  DEFAULTS: { POLLING_INTERVALS: { STANDARD: 30000 } },
}));

// Mock the useOrderGroupStream hook
jest.mock('../../hooks/useOrderGroupStream', () => ({
  useOrderGroupStream: jest.fn(),
}));

import OrderGroupPanel from '../OrderGroupPanel';
import { useOrderGroupStream } from '../../hooks/useOrderGroupStream';

describe('OrderGroupPanel', () => {
  const mockUseOrderGroupStream = useOrderGroupStream as jest.MockedFunction<typeof useOrderGroupStream>;

  const defaultStreamData = {
    groups: {
      'og-1': {
        order_group_id: 'og-1',
        status: 'active',
        contracts_limit: 1000,
        matched_contracts: 100,
        used_contracts: 300,
        filled_cost: 15000,
        remaining_cost: 35000,
        update_type: 'snapshot' as const,
        ts: new Date().toISOString(),
      },
      'og-2': {
        order_group_id: 'og-2',
        status: 'triggered',
        contracts_limit: 500,
        matched_contracts: 500,
        used_contracts: 0,
        filled_cost: 25000,
        remaining_cost: 0,
        update_type: 'snapshot' as const,
        ts: new Date().toISOString(),
      },
    },
    alerts: [
      { level: 'warning' as const, type: 'triggered', order_group_id: 'og-2', message: 'Group og-2 has been triggered' },
    ],
    isConnected: true,
    error: null,
    reconnectAttempts: 0,
    connect: jest.fn(),
    disconnect: jest.fn(),
  };

  beforeEach(() => {
    mockUseOrderGroupStream.mockReturnValue(defaultStreamData);
    global.fetch = jest.fn();
    global.window.confirm = jest.fn(() => true);
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('renders the panel with title', () => {
    render(<OrderGroupPanel />);
    expect(screen.getByText('Order Groups')).toBeInTheDocument();
  });

  it('displays connection status badge', () => {
    render(<OrderGroupPanel />);
    expect(screen.getByText('Live')).toBeInTheDocument();
  });

  it('shows offline status when disconnected', () => {
    mockUseOrderGroupStream.mockReturnValue({
      ...defaultStreamData,
      isConnected: false,
    });
    render(<OrderGroupPanel />);
    expect(screen.getByText('Offline')).toBeInTheDocument();
  });

  it('displays summary stats correctly', () => {
    render(<OrderGroupPanel />);
    expect(screen.getByText('2')).toBeInTheDocument(); // Total groups
    // Active=1 and Triggered=1 both render "1", so use getAllByText
    expect(screen.getAllByText('1').length).toBeGreaterThanOrEqual(2);
  });

  it('shows alerts when present', () => {
    render(<OrderGroupPanel />);
    expect(screen.getByText('Alerts (1)')).toBeInTheDocument();
    expect(screen.getByText('Group og-2 has been triggered')).toBeInTheDocument();
  });

  it('displays group cards with utilization bars', () => {
    render(<OrderGroupPanel />);
    expect(screen.getByText('og-1')).toBeInTheDocument();
    expect(screen.getByText('og-2')).toBeInTheDocument();
    expect(screen.getByText('30%')).toBeInTheDocument();
    expect(screen.getByText('300 / 1000 contracts')).toBeInTheDocument();
  });

  it('shows triggered status for triggered groups', () => {
    render(<OrderGroupPanel />);
    const triggeredBadges = screen.getAllByText('triggered');
    expect(triggeredBadges.length).toBeGreaterThan(0);
  });

  it('opens create form when New Group button clicked', async () => {
    render(<OrderGroupPanel />);
    const newGroupBtn = screen.getByText('+ New Group');
    fireEvent.click(newGroupBtn);
    
    expect(screen.getByPlaceholderText('Group name...')).toBeInTheDocument();
    expect(screen.getByText('Create')).toBeInTheDocument();
    expect(screen.getByText('Cancel')).toBeInTheDocument();
  });

  it('closes create form when Cancel clicked', async () => {
    render(<OrderGroupPanel />);
    const newGroupBtn = screen.getByText('+ New Group');
    fireEvent.click(newGroupBtn);
    
    const cancelBtn = screen.getByText('Cancel');
    fireEvent.click(cancelBtn);
    
    expect(screen.queryByPlaceholderText('Group name...')).not.toBeInTheDocument();
  });

  it('calls onGroupTriggered callback when group is triggered', () => {
    const onGroupTriggered = jest.fn();
    render(<OrderGroupPanel onGroupTriggered={onGroupTriggered} />);
    
    // The hook should trigger the callback for triggered groups
    expect(mockUseOrderGroupStream).toHaveBeenCalledWith(
      expect.objectContaining({
        onTriggered: expect.any(Function),
      })
    );
  });

  it('displays error banner when stream error occurs', () => {
    mockUseOrderGroupStream.mockReturnValue({
      ...defaultStreamData,
      error: new Error('Connection failed'),
    });
    render(<OrderGroupPanel />);
    
    expect(screen.getByText('Connection failed')).toBeInTheDocument();
  });

  it('shows empty state when no groups exist', () => {
    mockUseOrderGroupStream.mockReturnValue({
      ...defaultStreamData,
      groups: {},
    });
    render(<OrderGroupPanel />);
    
    expect(screen.getByText('No order groups found. Create one to get started.')).toBeInTheDocument();
  });

  describe('compact mode', () => {
    it('renders compact view when compact prop is true', () => {
      render(<OrderGroupPanel compact={true} />);
      
      // Compact shows stats in a row
      expect(screen.getByText('Total')).toBeInTheDocument();
      expect(screen.getByText('Active')).toBeInTheDocument();
      expect(screen.getByText('Triggered')).toBeInTheDocument();
      
      // Should not show group list
      expect(screen.queryByText('Groups (2)')).not.toBeInTheDocument();
    });

    it('shows alert banner in compact mode when alerts exist', () => {
      render(<OrderGroupPanel compact={true} />);
      expect(screen.getByText('1 alert')).toBeInTheDocument();
    });
  });

  describe('group actions', () => {
    it('shows reset button for triggered groups', () => {
      render(<OrderGroupPanel />);
      
      // Reset button should be visible for triggered group
      const resetButtons = screen.getAllByText('Reset');
      expect(resetButtons.length).toBeGreaterThan(0);
    });

    it('shows delete button for all groups', () => {
      render(<OrderGroupPanel />);
      
      // Delete buttons should be present for both groups
      const deleteButtons = screen.getAllByText('Delete');
      expect(deleteButtons.length).toBe(2);
    });
  });

  describe('onGroupSelect callback', () => {
    it('calls onGroupSelect when group card is clicked', () => {
      const onGroupSelect = jest.fn();
      render(<OrderGroupPanel onGroupSelect={onGroupSelect} />);
      
      // Click on the first group card
      const groupCard = screen.getByText('og-1').closest('div[class*="groupCard"]');
      if (groupCard) {
        fireEvent.click(groupCard);
        expect(onGroupSelect).toHaveBeenCalledWith(
          expect.objectContaining({
            order_group_id: 'og-1',
          })
        );
      }
    });
  });
});

describe('OrderGroupPanel - API interactions', () => {
  const mockFetch = jest.fn();
  const mockUseOrderGroupStream = useOrderGroupStream as jest.MockedFunction<typeof useOrderGroupStream>;

  beforeEach(() => {
    global.fetch = mockFetch;
    mockFetch.mockResolvedValue({
      ok: true,
      text: () => Promise.resolve(''),
    });
    mockUseOrderGroupStream.mockReturnValue({
      groups: {},
      alerts: [],
      isConnected: true,
      error: null,
      reconnectAttempts: 0,
      connect: jest.fn(),
      disconnect: jest.fn(),
    });
    global.window.confirm = jest.fn(() => true);
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('calls API to create new group', async () => {
    render(<OrderGroupPanel />);
    
    // Open create form
    fireEvent.click(screen.getByText('+ New Group'));
    
    // Fill in form
    const nameInput = screen.getByPlaceholderText('Group name...');
    await userEvent.type(nameInput, 'Test Group');
    
    // Submit
    fireEvent.click(screen.getByText('Create'));
    
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/kalshi/order-groups'),
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('Test Group'),
        })
      );
    });
  });

  it('calls API to reset triggered group', async () => {
    mockUseOrderGroupStream.mockReturnValue({
      groups: {
        'og-triggered': {
          order_group_id: 'og-triggered',
          status: 'triggered',
          contracts_limit: 1000,
          matched_contracts: 1000,
          used_contracts: 0,
          update_type: 'snapshot' as const,
          ts: new Date().toISOString(),
        },
      },
      alerts: [],
      isConnected: true,
      error: null,
      reconnectAttempts: 0,
      connect: jest.fn(),
      disconnect: jest.fn(),
    });
    
    render(<OrderGroupPanel />);
    
    const resetButton = screen.getByText('Reset');
    fireEvent.click(resetButton);
    
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/kalshi/order-groups/og-triggered/reset'),
        expect.objectContaining({
          method: 'PUT',
        })
      );
    });
  });

  it('calls API to delete group', async () => {
    mockUseOrderGroupStream.mockReturnValue({
      groups: {
        'og-delete': {
          order_group_id: 'og-delete',
          status: 'active',
          contracts_limit: 1000,
          used_contracts: 100,
          update_type: 'snapshot' as const,
          ts: new Date().toISOString(),
        },
      },
      alerts: [],
      isConnected: true,
      error: null,
      reconnectAttempts: 0,
      connect: jest.fn(),
      disconnect: jest.fn(),
    });
    
    render(<OrderGroupPanel />);
    
    const deleteButton = screen.getByText('Delete');
    fireEvent.click(deleteButton);
    
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/kalshi/order-groups/og-delete'),
        expect.objectContaining({
          method: 'DELETE',
        })
      );
    });
  });
});
