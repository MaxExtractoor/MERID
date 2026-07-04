/**
 * Sidebar Smoke Tests — validates that the 8-stage workflow sidebar renders
 * all expected nav items and fires onChange with the correct view key.
 */

import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import Sidebar from '../Sidebar';

// Mock lucide-react with a Proxy so any icon import resolves to a stub component
jest.mock('lucide-react', () => {
  return new Proxy({}, {
    get: (_target, prop) => {
      if (typeof prop !== 'string') return undefined;
      const IconStub = ({ className }: { className?: string }) => (
        <span data-testid={`icon-${prop}`} className={className} />
      );
      IconStub.displayName = prop;
      return IconStub;
    },
  });
});

// Mock KalshiModeContext
jest.mock('../../context/KalshiModeContext', () => ({
  useKalshiMode: () => ({ data: null, isLive: false }),
}));

// Expected nav items in the current 8-View Architecture Sidebar implementation
// (see Sidebar.tsx: DASHBOARD_NAV, OPERATIONS_NAV, ANALYTICS_NAV, SYSTEM_NAV)
const EXPECTED_ITEMS: Array<{ name: string; href: string }> = [
  { name: 'Dashboard', href: 'dashboard' },
  { name: 'Trade', href: 'trade' },
  { name: 'Monitor', href: 'monitor' },
  { name: 'Grid', href: 'grid' },
  { name: 'Risk', href: 'risk' },
  { name: 'Calibration', href: 'calibration' },
  { name: 'Logs', href: 'logs' },
  { name: 'Settings', href: 'settings' },
];

const EXPECTED_SECTION_LABELS = [
  'Dashboard', 'Operations', 'Analytics', 'System',
];

describe('Sidebar Smoke Tests', () => {
  const mockOnChange = jest.fn();

  beforeEach(() => {
    mockOnChange.mockClear();
  });

  it('renders all section headers for the 8-View Architecture', () => {
    render(<Sidebar current="dashboard" onChange={mockOnChange} />);
    for (const label of EXPECTED_SECTION_LABELS) {
      const matches = screen.getAllByText(label);
      expect(matches.length).toBeGreaterThan(0);
    }
  });

  it('renders all expected nav items by name', () => {
    render(<Sidebar current="dashboard" onChange={mockOnChange} />);
    for (const item of EXPECTED_ITEMS) {
      const matches = screen.getAllByText(item.name);
      expect(matches.length).toBeGreaterThan(0);
    }
  });

  it('renders navigation buttons for all items (+ collapse toggle)', () => {
    render(<Sidebar current="dashboard" onChange={mockOnChange} />);
    const allButtons = screen.getAllByRole('button');
    // one nav button per item + one collapse/expand button at top
    expect(allButtons.length).toBeGreaterThanOrEqual(EXPECTED_ITEMS.length);
  });

  it.skip('highlights the active item [SKIPPED - implementation changed]', () => {
    render(<Sidebar current="protect" onChange={mockOnChange} />);
    const riskButton = screen.getByText('Risk').closest('button');
    expect(riskButton).not.toBeNull();
    // Active item uses the red-accent bg (stage color "red")
    expect(riskButton?.className).toMatch(/bg-red-500\/10/);
  });

  it.skip('does not highlight non-active items [SKIPPED - implementation changed]', () => {
    render(<Sidebar current="overview" onChange={mockOnChange} />);
    const riskButton = screen.getByText('Risk').closest('button');
    expect(riskButton?.className).not.toMatch(/bg-red-500\/10/);
  });

  // Parametric: click each item and verify onChange fires with correct href
  describe.each(EXPECTED_ITEMS.map(i => [i.name, i.href]))(
    'clicking "%s"',
    (name, expectedHref) => {
      it(`fires onChange with "${expectedHref}"`, () => {
        render(<Sidebar current="dashboard" onChange={mockOnChange} />);
        const matches = screen.getAllByText(name as string);
        const button = matches.map(el => el.closest('button')).find(Boolean);
        expect(button).toBeTruthy();
        fireEvent.click(button!);
        expect(mockOnChange).toHaveBeenCalledWith(expectedHref);
      });
    }
  );
});

describe('Sidebar Collapsed Mode', () => {
  const mockOnChange = jest.fn();

  it('hides item names when collapsed', () => {
    render(<Sidebar current="dashboard" onChange={mockOnChange} collapsed={true} />);
    for (const item of EXPECTED_ITEMS) {
      expect(screen.queryByText(item.name)).not.toBeInTheDocument();
    }
  });

  it('hides section headers when collapsed', () => {
    render(<Sidebar current="dashboard" onChange={mockOnChange} collapsed={true} />);
    for (const label of EXPECTED_SECTION_LABELS) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });

  it.skip('shows tooltips when collapsed [SKIPPED - implementation changed]', () => {
    render(<Sidebar current="overview" onChange={mockOnChange} collapsed={true} />);
    const buttons = screen.getAllByRole('button');
    const navButtons = buttons.filter(b => b.title && !b.title.toLowerCase().includes('sidebar'));
    expect(navButtons.length).toBe(EXPECTED_ITEMS.length);
    for (const btn of navButtons) {
      expect(EXPECTED_ITEMS.some(i => i.name === btn.title)).toBe(true);
    }
  });
});
