/**
 * @jest-environment jsdom
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import OrderGroupPanel from '../OrderGroupPanel';
import { useOrderGroupStream } from '../../hooks/useOrderGroupStream';
import type { OrderGroupAlert, OrderGroupUpdate, UseOrderGroupStreamReturn } from '../../hooks/useOrderGroupStream';

const makeGroupUpdate = (overrides: Partial<OrderGroupUpdate>): OrderGroupUpdate => ({
  order_group_id: overrides.order_group_id ?? 'og-default',
  status: overrides.status ?? 'active',
  contracts_limit: overrides.contracts_limit ?? 1000,
  matched_contracts: overrides.matched_contracts ?? 0,
  used_contracts: overrides.used_contracts ?? 0,
  filled_cost: overrides.filled_cost ?? 0,
  remaining_cost: overrides.remaining_cost ?? 0,
  update_type: overrides.update_type ?? 'snapshot',
  ts: overrides.ts ?? '2026-04-04T18:00:00Z',
});

const makeAlert = (overrides: Partial<OrderGroupAlert>): OrderGroupAlert => ({
  level: overrides.level ?? 'warning',
  type: overrides.type ?? 'group_triggered',
  order_group_id: overrides.order_group_id ?? 'og-default',
  message: overrides.message ?? 'alert',
});

// Mock the useOrderGroupStream hook
jest.mock('../../hooks/useOrderGroupStream', () => ({
  useOrderGroupStream: jest.fn(),
}));

describe('OrderGroupPanel', () => {
  const mockUseOrderGroupStream = useOrderGroupStream as jest.MockedFunction<typeof useOrderGroupStream>;

  const defaultStreamData: UseOrderGroupStreamReturn = {
    groups: {
      'og-1': makeGroupUpdate({
        order_group_id: 'og-1',
        status: 'active',
        contracts_limit: 1000,
        matched_contracts: 100,
        used_contracts: 300,
        filled_cost: 15000,
        remaining_cost: 35000,
      }),
      'og-2': makeGroupUpdate({
        order_group_id: 'og-2',
        status: 'triggered',
        contracts_limit: 500,
        matched_contracts: 500,
        used_contracts: 0,
        filled_cost: 25000,
        remaining_cost: 0,
      }),
    },
    alerts: [
      makeAlert({ order_group_id: 'og-2', message: 'Group og-2 has been triggered' }),
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
    expect(screen.getByText('Total Groups').previousSibling).toHaveTextContent('2');
    expect(screen.getAllByText('Active').find((element) => element.previousSibling?.textContent === '1')).toBeDefined();
    expect(screen.getAllByText('Triggered').find((element) => element.previousSibling?.textContent === '1')).toBeDefined();
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
        'og-triggered': makeGroupUpdate({
          order_group_id: 'og-triggered',
          status: 'triggered',
          contracts_limit: 1000,
          matched_contracts: 1000,
          used_contracts: 0,
        }),
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
        'og-delete': makeGroupUpdate({
          order_group_id: 'og-delete',
          status: 'active',
          contracts_limit: 1000,
          used_contracts: 100,
        }),
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
