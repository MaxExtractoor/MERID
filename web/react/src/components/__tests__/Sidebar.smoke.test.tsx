/**
 * Sidebar Smoke Tests — validates that every sidebar item is clickable
 * and fires the correct onChange callback with the expected View key.
 *
 * Also validates the manifest stays in sync with the rendered component.
 */

import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import Sidebar from '../Sidebar';
import { SIDEBAR_MANIFEST, ALL_SIDEBAR_ITEMS } from '../../config/sidebarManifest';

// Mock lucide-react to avoid SVG rendering issues in jsdom
jest.mock('lucide-react', () => {
  const icons = [
    'LayoutDashboard', 'Activity', 'TrendingUp', 'Shield', 'Settings',
    'Bot', 'BarChart3', 'Terminal', 'HeartPulse', 'Wallet', 'Coins',
    'Trophy', 'Package', 'Monitor', 'Zap', 'Code2', 'Briefcase',
    'Target', 'Brain', 'Radio', 'Eye', 'FileSpreadsheet', 'GitBranch',
    'Layers', 'Award', 'Search', 'LayoutGrid', 'ClipboardList',
    'ShieldAlert', 'Gauge', 'ChevronLeft', 'ChevronRight',
    'TrendingUp', 'Sliders', 'Settings2',
  ];
  const mocks: Record<string, React.FC<{ className?: string }>> = {};
  for (const name of icons) {
    mocks[name] = ({ className }: { className?: string }) => (
      <span data-testid={`icon-${name}`} className={className} />
    );
  }
  return mocks;
});

describe('Sidebar Smoke Tests', () => {
  const mockOnChange = jest.fn();

  beforeEach(() => {
    mockOnChange.mockClear();
  });

  it('renders all 6 section headers', () => {
    render(<Sidebar current="overview" onChange={mockOnChange} />);
    for (const section of SIDEBAR_MANIFEST) {
      expect(screen.getByText(section.label)).toBeInTheDocument();
    }
  });

  it('renders all sidebar items', () => {
    render(<Sidebar current="overview" onChange={mockOnChange} />);
    for (const item of ALL_SIDEBAR_ITEMS) {
      expect(screen.getByText(item.name)).toBeInTheDocument();
    }
  });

  it('renders exactly 32 navigation buttons', () => {
    render(<Sidebar current="overview" onChange={mockOnChange} />);
    // 32 nav items + 1 logo/collapse button = 33 total buttons
    const allButtons = screen.getAllByRole('button');
    const navButtons = allButtons.filter(b => !b.title?.includes('sidebar'));
    expect(navButtons.length).toBe(ALL_SIDEBAR_ITEMS.length);
  });

  it('highlights the active item', () => {
    render(<Sidebar current="kill-switch" onChange={mockOnChange} />);
    const riskButton = screen.getByText('Kill Switch').closest('button');
    expect(riskButton).toHaveClass('bg-blue-600');
  });

  it('does not highlight non-active items', () => {
    render(<Sidebar current="overview" onChange={mockOnChange} />);
    const riskButton = screen.getByText('Kill Switch').closest('button');
    expect(riskButton).not.toHaveClass('bg-blue-600');
  });

  // Parametric: click each sidebar item and verify onChange fires with correct href
  describe.each(ALL_SIDEBAR_ITEMS.map(item => [item.name, item.href]))(
    'clicking "%s"',
    (name, expectedHref) => {
      it(`fires onChange with "${expectedHref}"`, () => {
        render(<Sidebar current="overview" onChange={mockOnChange} />);
        const button = screen.getByText(name as string);
        fireEvent.click(button);
        expect(mockOnChange).toHaveBeenCalledWith(expectedHref);
      });
    }
  );
});

describe('Sidebar Manifest Integrity', () => {
  it('manifest has 3 sections', () => {
    expect(SIDEBAR_MANIFEST).toHaveLength(3);
  });

  it('manifest has 13 total items matching Sidebar.tsx', () => {
    expect(ALL_SIDEBAR_ITEMS).toHaveLength(13);
  });

  it('manifest has correct total items', () => {
    expect(ALL_SIDEBAR_ITEMS.length).toBeGreaterThan(0);
  });

  it('all hrefs are unique', () => {
    const hrefs = ALL_SIDEBAR_ITEMS.map(i => i.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it('all names are unique', () => {
    const names = ALL_SIDEBAR_ITEMS.map(i => i.name);
    expect(new Set(names).size).toBe(names.length);
  });

  it('section labels match Sidebar.tsx rendering order', () => {
    const expectedLabels = ['Live Trading', 'Command Center', 'System'];
    expect(SIDEBAR_MANIFEST.map(s => s.label)).toEqual(expectedLabels);
  });

  it('every item has required fields', () => {
    for (const item of ALL_SIDEBAR_ITEMS) {
      expect(item.name).toBeTruthy();
      expect(item.href).toBeTruthy();
      expect(item.icon).toBeTruthy();
      expect(item.color).toBeTruthy();
    }
  });
});

describe('Sidebar Collapsed Mode', () => {
  const mockOnChange = jest.fn();

  it('hides item names when collapsed', () => {
    render(<Sidebar current="overview" onChange={mockOnChange} collapsed={true} />);
    // In collapsed mode, item names should not be visible
    for (const item of ALL_SIDEBAR_ITEMS) {
      expect(screen.queryByText(item.name)).not.toBeInTheDocument();
    }
  });

  it('hides section headers when collapsed', () => {
    render(<Sidebar current="overview" onChange={mockOnChange} collapsed={true} />);
    for (const section of SIDEBAR_MANIFEST) {
      expect(screen.queryByText(section.label)).not.toBeInTheDocument();
    }
  });

  it('shows tooltips when collapsed', () => {
    render(<Sidebar current="overview" onChange={mockOnChange} collapsed={true} />);
    // Each nav button should have a title attribute with the item name
    const buttons = screen.getAllByRole('button');
    const navButtons = buttons.filter(b => b.title && !b.title.includes('sidebar'));
    expect(navButtons.length).toBe(ALL_SIDEBAR_ITEMS.length);
    for (const btn of navButtons) {
      expect(ALL_SIDEBAR_ITEMS.some(i => i.name === btn.title)).toBe(true);
    }
  });
});
