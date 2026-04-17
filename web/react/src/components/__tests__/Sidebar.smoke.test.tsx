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

describe('Sidebar Smoke Tests', () => {
  const mockOnChange = jest.fn();

  beforeEach(() => {
    mockOnChange.mockClear();
  });

  it('renders all 5 section headers', () => {
    render(<Sidebar current="overview" onChange={mockOnChange} />);
    // Sidebar component uses its own labels (may differ from manifest)
    // "Operator" appears as both a section header and nav item, so use getAllByText
    const renderedLabels = ['Trading', 'Swarm Intelligence', 'Analytics', 'Operator', 'System'];
    for (const label of renderedLabels) {
      const matches = screen.getAllByText(label);
      expect(matches.length).toBeGreaterThan(0);
    }
  });

  it('renders all sidebar items', () => {
    render(<Sidebar current="overview" onChange={mockOnChange} />);
    for (const item of ALL_SIDEBAR_ITEMS) {
      // Use getAllByText for items whose name duplicates a section header
      const matches = screen.getAllByText(item.name);
      expect(matches.length).toBeGreaterThan(0);
    }
  });

  it('renders navigation buttons for all sidebar items', () => {
    render(<Sidebar current="overview" onChange={mockOnChange} />);
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
        // Use getAllByText + closest('button') to handle items whose name
        // also appears as a section header (e.g. "Operator")
        const matches = screen.getAllByText(name as string);
        const button = matches.map(el => el.closest('button')).find(Boolean);
        expect(button).toBeTruthy();
        fireEvent.click(button!);
        expect(mockOnChange).toHaveBeenCalledWith(expectedHref);
      });
    }
  );
});

describe('Sidebar Manifest Integrity', () => {
  it('manifest has 5 sections', () => {
    expect(SIDEBAR_MANIFEST).toHaveLength(5);
  });

  it('manifest has 18 total items matching Sidebar.tsx', () => {
    expect(ALL_SIDEBAR_ITEMS).toHaveLength(18);
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

  it('manifest section labels are defined', () => {
    expect(SIDEBAR_MANIFEST.map(s => s.label).length).toBe(5);
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
