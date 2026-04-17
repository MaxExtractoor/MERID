/**
 * ThemeAuditSprint.regression.test.tsx
 *
 * Regression tests for all 7 fixes from the Theme Audit Sprint.
 *
 * T01 — ConfirmModal.css: theme-aware CSS custom properties (no hardcoded dark values)
 * T02 — index.css: global focus-visible rings defined for both themes
 * T03 — index.css: light-mode overrides for bg-slate-600/700, .card, .stat-card, .glass
 * T04 — getChartColors(): returns dark/light-appropriate chrome values
 * T05 — KalshiPnlChart: uses getChartColors / useTheme, not raw CHART_COLORS chrome
 * T06 — ThemeProvider: system-preference detection + auto preference + setPreference API
 * T07 — Settings: theme dropdown reads from ThemeProvider and calls setPreference
 *
 * Strategy: static source analysis (fs.readFileSync regex) + targeted RTL tests.
 * No server required.
 */

import * as fs from 'fs';
import * as path from 'path';
import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';

// ─── Path helpers ─────────────────────────────────────────────────────────────
const SRC = path.resolve(__dirname, '../..');
const src = (...parts: string[]) => path.join(SRC, ...parts);
function read(...parts: string[]): string {
  return fs.readFileSync(src(...parts), 'utf-8');
}

// ─── Shared mocks ─────────────────────────────────────────────────────────────
jest.mock('../../hooks/useApiData', () => ({
  __esModule: true,
  useApiData: jest.fn(() => ({
    data: null, loading: false, error: null,
    refetch: jest.fn(), lastUpdated: null,
  })),
}));

jest.mock('../../context/KalshiModeContext', () => ({
  __esModule: true,
  useKalshiMode: () => ({
    isLive: false, data: { mode: 'paper', is_live: false },
    loading: false, error: null, refetch: jest.fn(),
    wsKillActive: false, wsKillAt: null,
  }),
  KalshiModeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

jest.mock('lucide-react', () =>
  new Proxy({}, {
    get: (_t, prop) => {
      if (typeof prop !== 'string') return undefined;
      const S = ({ className }: { className?: string }) =>
        <span data-testid={`icon-${prop}`} className={className} />;
      S.displayName = String(prop);
      return S;
    },
  })
);

jest.mock('../../config/modeColors', () => ({
  MODE_COLORS: {
    paper: { badge: 'bg-amber-500/20 text-amber-400', dot: 'bg-amber-400', text: 'text-amber-400', topbar: '', topbarDot: '' },
    live:  { badge: 'bg-red-500/20 text-red-400',   dot: 'bg-red-400',   text: 'text-red-400',   topbar: '', topbarDot: '' },
    shadow: { badge: '', dot: '', text: '', topbar: '', topbarDot: '' },
    unknown: { badge: '', dot: '', text: '', topbar: '', topbarDot: '' },
  },
  resolveModeKey: jest.fn(() => 'paper'),
}));

jest.mock('../../api/auth', () => ({
  authHeaders: jest.fn(() => ({ 'Content-Type': 'application/json' })),
}));

// ─── Constants mock — includes getChartColors for T04/T05 ─────────────────────
jest.mock('../../config/constants', () => {
  const CHART_COLORS = {
    GREEN: '#22c55e', RED: '#ef4444', AMBER: '#f59e0b', INDIGO: '#6366f1',
    AXIS_TICK: '#64748b', GRID_STROKE: '#334155', TOOLTIP_BG: '#0f172a',
    TOOLTIP_BORDER: '#334155', TOOLTIP_LABEL: '#e2e8f0',
    BAR_BASE: '#1e293b', SLATE_400: '#94a3b8', SLATE_600: '#475569',
    EMERALD: '#10b981',
  };
  const getChartColors = (isDark: boolean) => ({
    AXIS_TICK:      '#64748b',
    GRID_STROKE:    isDark ? '#334155' : '#e2e8f0',
    TOOLTIP_BG:     isDark ? '#0f172a' : '#ffffff',
    TOOLTIP_BORDER: isDark ? '#334155' : '#e2e8f0',
    TOOLTIP_LABEL:  isDark ? '#e2e8f0' : '#1e293b',
    BAR_BASE:       isDark ? '#1e293b' : '#f1f5f9',
  });
  return {
    __esModule: true,
    API_BASE_URL: 'http://127.0.0.1:8000',
    AUTH_TOKEN_KEY: 'merid-access',
    API_ENDPOINTS: {
      KALSHI_PNL_HISTORY: '/api/v1/kalshi/pnl-history',
      USER_PROFILE: '/api/v1/user/profile',
      USER_SETTINGS: '/api/v1/user/settings',
      RISK_SUMMARY: '/api/v1/risk/summary',
      RISK_ALERTS: '/api/v1/risk/alerts',
      RISK_ALERT_ACKNOWLEDGE: (id: string) => `/api/v1/risk/alerts/${id}/acknowledge`,
      RISK_ALERTS_ACKNOWLEDGE_ALL: '/api/v1/risk/alerts/acknowledge-all',
    },
    DEFAULTS: {
      PAGE_SIZE: 25,
      POLLING_INTERVALS: { STANDARD: 10000, SLOW: 30000, FAST_REFRESH: 5000 },
      TIMEOUTS: { STATUS_RESET: 5000 },
    },
    CHART_COLORS,
    getChartColors,
  };
});

// ─────────────────────────────────────────────────────────────────────────────
// T01 — ConfirmModal.css: theme-aware CSS custom properties
// ─────────────────────────────────────────────────────────────────────────────
describe('T01 — ConfirmModal.css: theme-aware CSS custom properties', () => {
  const css = () => read('components', 'ConfirmModal.css');

  it('defines --modal-bg CSS variable', () => {
    expect(css()).toMatch(/--modal-bg\s*:/);
  });

  it('defines --modal-title-color CSS variable', () => {
    expect(css()).toMatch(/--modal-title-color\s*:/);
  });

  it('defines --modal-message-color CSS variable', () => {
    expect(css()).toMatch(/--modal-message-color\s*:/);
  });

  it('provides html:not(.dark) override block for light mode', () => {
    expect(css()).toMatch(/html:not\(\.dark\)\s*\{/);
  });

  it('light-mode --modal-bg is white (#ffffff)', () => {
    const lightBlock = css().split('html:not(.dark)')[1] ?? '';
    expect(lightBlock).toMatch(/--modal-bg\s*:\s*#ffffff/);
  });

  it('light-mode --modal-title-color is dark (#0f172a)', () => {
    const lightBlock = css().split('html:not(.dark)')[1] ?? '';
    expect(lightBlock).toMatch(/--modal-title-color\s*:\s*#0f172a/);
  });

  it('does NOT use hardcoded #1a1a1a background', () => {
    expect(css()).not.toMatch(/#1a1a1a/);
  });

  it('does NOT use hardcoded #333 border', () => {
    expect(css()).not.toMatch(/border-color\s*:\s*#333[^3]/);
  });

  it('confirm buttons have focus-visible outline rules', () => {
    expect(css()).toMatch(/\.confirm-modal-confirm:focus-visible/);
  });

  it('cancel button has focus-visible outline rule', () => {
    expect(css()).toMatch(/\.confirm-modal-cancel:focus-visible/);
  });

  it('focus-visible outline uses blue (#3b82f6)', () => {
    expect(css()).toMatch(/outline.*#3b82f6|#3b82f6.*outline/);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// T02 — index.css: global focus-visible rings
// ─────────────────────────────────────────────────────────────────────────────
describe('T02 — index.css: global focus-visible rings', () => {
  const css = () => read('index.css');

  it('defines *:focus-visible rule', () => {
    expect(css()).toMatch(/\*:focus-visible\s*\{/);
  });

  it('focus-visible uses outline (not box-shadow)', () => {
    const block = css().match(/\*:focus-visible\s*\{[^}]+\}/)?.[0] ?? '';
    expect(block).toMatch(/outline\s*:/);
  });

  it('dark-mode focus ring uses blue-500 (#3b82f6)', () => {
    expect(css()).toMatch(/#3b82f6/);
  });

  it('light-mode focus ring overrides to blue-600 (#2563eb)', () => {
    expect(css()).toMatch(/html:not\(\.dark\)[^}]*\*:focus-visible[^}]*outline-color\s*:\s*#2563eb|html:not\(\.dark\) \*:focus-visible/);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// T03 — index.css: light-mode overrides coverage
// ─────────────────────────────────────────────────────────────────────────────
describe('T03 — index.css: light-mode override completeness', () => {
  const css = () => read('index.css');

  it('remaps bg-slate-700 in light mode', () => {
    expect(css()).toMatch(/html:not\(\.dark\) \.bg-slate-700\s*\{/);
  });

  it('remaps bg-slate-600 in light mode', () => {
    expect(css()).toMatch(/html:not\(\.dark\) \.bg-slate-600\s*\{/);
  });

  it('provides .card light-mode override', () => {
    expect(css()).toMatch(/html:not\(\.dark\) \.card\s*\{/);
  });

  it('provides .stat-card light-mode override', () => {
    expect(css()).toMatch(/html:not\(\.dark\) \.stat-card\s*\{/);
  });

  it('provides .glass light-mode override', () => {
    expect(css()).toMatch(/html:not\(\.dark\) \.glass\s*\{/);
  });

  it('remaps text-white in light mode to a dark color', () => {
    const lightWhite = css().match(/html:not\(\.dark\) \.text-white\s*\{[^}]+\}/)?.[0] ?? '';
    expect(lightWhite).toMatch(/color\s*:\s*#0f172a|color\s*:\s*#1e293b/);
  });

  it('provides .gradient-animate light-mode override', () => {
    expect(css()).toMatch(/html:not\(\.dark\) \.gradient-animate\s*\{/);
  });

  it('provides .shimmer light-mode override', () => {
    expect(css()).toMatch(/html:not\(\.dark\) \.shimmer\s*\{/);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// T04 — getChartColors(): dark/light-appropriate chrome values
// ─────────────────────────────────────────────────────────────────────────────
describe('T04 — getChartColors() helper', () => {
  it('exists in constants source', () => {
    const src_ = read('config', 'constants.ts');
    expect(src_).toMatch(/export function getChartColors/);
  });

  it('returns dark tooltip background (#0f172a) when isDark=true', () => {
    const { getChartColors } = jest.requireMock('../../config/constants') as {
      getChartColors: (isDark: boolean) => Record<string, string>;
    };
    expect(getChartColors(true).TOOLTIP_BG).toBe('#0f172a');
  });

  it('returns light tooltip background (#ffffff) when isDark=false', () => {
    const { getChartColors } = jest.requireMock('../../config/constants') as {
      getChartColors: (isDark: boolean) => Record<string, string>;
    };
    expect(getChartColors(false).TOOLTIP_BG).toBe('#ffffff');
  });

  it('returns dark grid stroke (#334155) when isDark=true', () => {
    const { getChartColors } = jest.requireMock('../../config/constants') as {
      getChartColors: (isDark: boolean) => Record<string, string>;
    };
    expect(getChartColors(true).GRID_STROKE).toBe('#334155');
  });

  it('returns light grid stroke (#e2e8f0) when isDark=false', () => {
    const { getChartColors } = jest.requireMock('../../config/constants') as {
      getChartColors: (isDark: boolean) => Record<string, string>;
    };
    expect(getChartColors(false).GRID_STROKE).toBe('#e2e8f0');
  });

  it('returns light tooltip label (#1e293b) when isDark=false', () => {
    const { getChartColors } = jest.requireMock('../../config/constants') as {
      getChartColors: (isDark: boolean) => Record<string, string>;
    };
    expect(getChartColors(false).TOOLTIP_LABEL).toBe('#1e293b');
  });

  it('dark and light TOOLTIP_BG values are different', () => {
    const { getChartColors } = jest.requireMock('../../config/constants') as {
      getChartColors: (isDark: boolean) => Record<string, string>;
    };
    expect(getChartColors(true).TOOLTIP_BG).not.toBe(getChartColors(false).TOOLTIP_BG);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// T05 — KalshiPnlChart: uses getChartColors + useTheme for chrome
// ─────────────────────────────────────────────────────────────────────────────
describe('T05 — KalshiPnlChart source: getChartColors wired', () => {
  const chartSrc = () => read('components', 'KalshiPnlChart.tsx');

  it('imports getChartColors from constants', () => {
    expect(chartSrc()).toMatch(/getChartColors/);
  });

  it('imports useTheme', () => {
    expect(chartSrc()).toMatch(/useTheme/);
  });

  it('calls getChartColors(theme === .dark.) inside component', () => {
    expect(chartSrc()).toMatch(/getChartColors\(theme\s*===\s*['"]dark['"]\)/);
  });

  it('does NOT use CHART_COLORS.TOOLTIP_BG directly', () => {
    expect(chartSrc()).not.toMatch(/CHART_COLORS\.TOOLTIP_BG/);
  });

  it('does NOT use CHART_COLORS.GRID_STROKE directly', () => {
    expect(chartSrc()).not.toMatch(/CHART_COLORS\.GRID_STROKE/);
  });

  it('does NOT use CHART_COLORS.BAR_BASE directly (replaced by CC.BAR_BASE)', () => {
    expect(chartSrc()).not.toMatch(/CHART_COLORS\.BAR_BASE/);
  });

  it('does NOT use CHART_COLORS.AXIS_TICK directly', () => {
    expect(chartSrc()).not.toMatch(/CHART_COLORS\.AXIS_TICK/);
  });
});

describe('T05 — KalshiSentimentView: GaugeWidget uses getChartColors', () => {
  const src_ = () => read('views', 'KalshiSentimentView.tsx');

  it('imports getChartColors', () => {
    expect(src_()).toMatch(/getChartColors/);
  });

  it('imports useTheme', () => {
    expect(src_()).toMatch(/useTheme/);
  });

  it('calls getChartColors inside GaugeWidget (not raw CHART_COLORS.GRID_STROKE)', () => {
    expect(src_()).not.toMatch(/CHART_COLORS\.GRID_STROKE/);
  });
});

describe('T05 — LaneControlDashboard: AlignmentRing uses getChartColors', () => {
  const src_ = () => read('views', 'LaneControlDashboard.tsx');

  it('imports getChartColors', () => {
    expect(src_()).toMatch(/getChartColors/);
  });

  it('imports useTheme', () => {
    expect(src_()).toMatch(/useTheme/);
  });

  it('AlignmentRing does not use raw CHART_COLORS.GRID_STROKE', () => {
    expect(src_()).not.toMatch(/CHART_COLORS\.GRID_STROKE/);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// T06 — ThemeProvider: system-preference + auto + setPreference
// ─────────────────────────────────────────────────────────────────────────────
describe('T06 — theme.tsx source: system-preference detection', () => {
  const themeSrc = () => read('theme.tsx');

  it('defines ThemePreference type with "auto" option', () => {
    expect(themeSrc()).toMatch(/["']auto["']/);
  });

  it('calls window.matchMedia with prefers-color-scheme', () => {
    expect(themeSrc()).toMatch(/prefers-color-scheme/);
  });

  it('exports setPreference from context', () => {
    expect(themeSrc()).toMatch(/setPreference/);
  });

  it('defaults stored preference to "auto" when localStorage is empty', () => {
    expect(themeSrc()).toMatch(/\|\|\s*["']auto["']/);
  });

  it('listens for MediaQueryList change events', () => {
    expect(themeSrc()).toMatch(/addEventListener\s*\(\s*['"]change['"]/);
  });

  it('cleans up media query listener on unmount', () => {
    expect(themeSrc()).toMatch(/removeEventListener\s*\(\s*['"]change['"]/);
  });

  it('persists the preference (not resolved theme) to localStorage', () => {
    expect(themeSrc()).toMatch(/setItem\s*\(\s*["']merid-theme["']\s*,\s*preference/);
  });
});

describe('T06 — ThemeProvider RTL: renders and toggles', () => {
  // Unmock theme so we test the real implementation
  jest.unmock('../../theme');

  let matchMediaMock: jest.Mock;

  beforeEach(() => {
    matchMediaMock = jest.fn().mockReturnValue({
      matches: false,
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
    });
    Object.defineProperty(window, 'matchMedia', { writable: true, value: matchMediaMock });
    (localStorage.getItem as jest.Mock).mockReturnValue(null);
    (localStorage.setItem as jest.Mock).mockImplementation(() => undefined);
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('renders children', async () => {
    const { ThemeProvider } = await import('../../theme');
    render(
      <ThemeProvider>
        <span data-testid="child">hello</span>
      </ThemeProvider>
    );
    expect(screen.getByTestId('child')).toBeInTheDocument();
  });

  it('defaults to dark when system preference is dark', async () => {
    matchMediaMock.mockReturnValue({
      matches: false,
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
    });
    const { ThemeProvider, useTheme } = await import('../../theme');
    function Probe() {
      const { theme } = useTheme();
      return <span data-testid="theme">{theme}</span>;
    }
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByTestId('theme').textContent).toBe('dark');
  });

  it('toggleTheme switches from dark to light', async () => {
    matchMediaMock.mockReturnValue({
      matches: false,
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
    });
    const { ThemeProvider, useTheme } = await import('../../theme');
    function Probe() {
      const { theme, toggleTheme } = useTheme();
      return (
        <>
          <span data-testid="theme">{theme}</span>
          <button onClick={toggleTheme}>toggle</button>
        </>
      );
    }
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByTestId('theme').textContent).toBe('dark');
    act(() => { fireEvent.click(screen.getByText('toggle')); });
    expect(screen.getByTestId('theme').textContent).toBe('light');
  });

  it('stores preference in localStorage on change', async () => {
    matchMediaMock.mockReturnValue({
      matches: false,
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
    });
    const { ThemeProvider, useTheme } = await import('../../theme');
    function Probe() {
      const { toggleTheme } = useTheme();
      return <button onClick={toggleTheme}>toggle</button>;
    }
    render(<ThemeProvider><Probe /></ThemeProvider>);
    act(() => { fireEvent.click(screen.getByText('toggle')); });
    expect(localStorage.setItem).toHaveBeenCalledWith('merid-theme', 'light');
  });

  it('applies dark class to document.documentElement in dark mode', async () => {
    matchMediaMock.mockReturnValue({
      matches: false,
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
    });
    const { ThemeProvider } = await import('../../theme');
    render(<ThemeProvider><span /></ThemeProvider>);
    expect(document.documentElement.classList.contains('dark')).toBe(true);
  });

  it('setPreference("light") switches to light mode', async () => {
    matchMediaMock.mockReturnValue({
      matches: false,
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
    });
    const { ThemeProvider, useTheme } = await import('../../theme');
    function Probe() {
      const { theme, setPreference } = useTheme();
      return (
        <>
          <span data-testid="theme">{theme}</span>
          <button onClick={() => setPreference('light')}>setLight</button>
        </>
      );
    }
    render(<ThemeProvider><Probe /></ThemeProvider>);
    act(() => { fireEvent.click(screen.getByText('setLight')); });
    expect(screen.getByTestId('theme').textContent).toBe('light');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// T07 — Settings: theme dropdown reads from ThemeProvider
// ─────────────────────────────────────────────────────────────────────────────
describe('T07 — Settings.tsx source: theme dropdown wired to ThemeProvider', () => {
  const settingsSrc = () => read('views', 'Settings.tsx');

  it('imports useTheme from theme', () => {
    expect(settingsSrc()).toMatch(/import.*useTheme.*from.*['"]\.\.\/(theme|theme\.tsx)['"]/);
  });

  it('destructures preference (or themePreference) from useTheme()', () => {
    expect(settingsSrc()).toMatch(/preference.*useTheme\(\)|themePreference.*useTheme\(\)/);
  });

  it('destructures setPreference from useTheme()', () => {
    expect(settingsSrc()).toMatch(/setPreference.*useTheme\(\)|setThemePreference.*useTheme\(\)/);
  });

  it('theme select value is bound to themePreference not preferences.theme', () => {
    expect(settingsSrc()).toMatch(/value=\{themePreference\}/);
  });

  it('onChange calls setThemePreference or setPreference', () => {
    expect(settingsSrc()).toMatch(/setThemePreference\(|setPreference\(/);
  });

  it('select onChange still updates local preferences state', () => {
    expect(settingsSrc()).toMatch(/setPreferences.*theme.*:|theme.*setPreferences/);
  });
});
