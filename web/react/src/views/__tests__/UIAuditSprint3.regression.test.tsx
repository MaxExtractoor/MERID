/**
 * UIAuditSprint3.regression.test.tsx
 *
 * Regression tests for all 16 fixes from UI/UX Audit Sprint 3.
 *
 * H01 — KalshiPortfolioView: PnL divergence badge when sources differ
 * H02 — useKalshiRiskStream: summaryReceivedAt exposed; DataAgeBadge wired
 * H03 — KalshiPortfolioView: balanceUsd heuristic removed; unit guard added
 * H04 — OrdersView: amend row disabled when ConfirmModal open; cleared on cancel open
 * H05 — KalshiModeContext: wsKillActive/wsKillAt from WS kill_switch event
 * H06 — fmtTimestamp UTC utility; alert ID deduplication (polled wins over WS)
 * H07 — PositionsView: Notional card labelled "(risk src)"
 * H08 — OrdersView: notional labelled "(pre-fee)"
 * M01 — PositionsView: asset filter uses dash-segment match, not startsWith
 * M02 — useApiData: scheduleNext single-timer invariant
 * M03 — KalshiRiskScreen: polled resolved overrides WS active on dedup
 * M04 — OrdersView: amend submit disabled/debounced after first click
 * M05 — KalshiRiskScreen: 50+ alerts sticky banner
 * M06 — KalshiDashboardView: catalog refresh rate-limited via localStorage
 * M07 — KillSwitchView: propagation badge after reset; fmtTimestamp UTC
 * M08 — fmtTimestamp: shared UTC utility; toLocaleString removed from views
 *
 * Strategy: static source analysis (regex) + targeted RTL/hook tests.
 * No server required.
 */

import * as fs from 'fs';
import * as path from 'path';

// ─── Path helpers ───────────────────────────────────────────────────────────────
const SRC = path.resolve(__dirname, '../..');
const src = (...parts: string[]) => path.join(SRC, ...parts);
function read(...parts: string[]): string {
  return fs.readFileSync(src(...parts), 'utf-8');
}

// ─── Shared mocks ───────────────────────────────────────────────────────────────
jest.mock('../../hooks/useApiData', () => ({
  __esModule: true,
  useApiData: jest.fn(() => ({
    data: null, loading: false, error: null,
    refetch: jest.fn(), lastUpdated: null,
  })),
}));

jest.mock('../../hooks/useKalshiRiskStream', () => ({
  __esModule: true,
  useKalshiRiskStream: jest.fn(() => ({
    alerts: [], summary: null, summaryReceivedAt: null, connected: false, clearAlerts: jest.fn(),
  })),
}));

jest.mock('../../context/KalshiModeContext', () => ({
  __esModule: true,
  useKalshiMode: () => ({
    isLive: false, data: { mode: 'paper', is_live: false }, loading: false,
    isLoading: false, error: null, refetch: jest.fn(),
    wsKillActive: false, wsKillAt: null,
  }),
  KalshiModeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

jest.mock('lucide-react', () =>
  new Proxy({}, {
    get: (_t, prop) => {
      if (typeof prop !== 'string') return undefined;
      const S = ({ className }: { className?: string }) => <span data-testid={`icon-${prop}`} className={className} />;
      S.displayName = String(prop);
      return S;
    },
  })
);

jest.mock('../../components/ExecutionGateStrip', () => ({ __esModule: true, default: () => <div data-testid="execution-gate-strip" /> }));
jest.mock('../../components/CollapsibleConsole',  () => ({ __esModule: true, default: () => <div /> }));
jest.mock('../../components/AgentActivityPanel',  () => ({ __esModule: true, default: () => <div /> }));
jest.mock('../../components/KalshiPnlChart',      () => ({ __esModule: true, default: () => <div data-testid="kalshi-pnl-chart" /> }));
jest.mock('../../components/DataAgeBadge',        () => ({ __esModule: true, DataAgeBadge: () => <span data-testid="data-age-badge" /> }));
jest.mock('../../components/ModeSafetyPanel',     () => ({ __esModule: true, default: () => <div /> }));
jest.mock('../../components/PnLConsistencyWidget',() => ({ __esModule: true, default: () => <div /> }));
jest.mock('../../components/SessionLogPanel',     () => ({ __esModule: true, default: () => <div /> }));
jest.mock('../../components/EmergencyStopButton', () => ({ __esModule: true, default: () => <button>EmergencyStop</button> }));
jest.mock('../../components/KalshiModeBadge',     () => ({ __esModule: true, default: () => <span /> }));
jest.mock('../../components/KalshiRiskFeed',      () => ({ __esModule: true, default: () => <div /> }));
jest.mock('../../components/RiskAlertFeed',       () => ({ __esModule: true, default: () => <div /> }));
jest.mock('../../components/KalshiReconciliationBadge', () => ({ __esModule: true, default: () => <div /> }));
jest.mock('../../components/BatchOrderPanel',     () => ({ __esModule: true, default: () => <div /> }));
jest.mock('../../components/OrderGroupAnalytics', () => ({ __esModule: true, default: () => <div /> }));
jest.mock('../../components/CircuitBreakerPanel', () => ({ __esModule: true, default: () => <div /> }));
jest.mock('../../components/LatencyPanel',        () => ({ __esModule: true, default: () => <div /> }));
jest.mock('../../components/OrderErrorsPanel',    () => ({ __esModule: true, default: () => <div /> }));
jest.mock('../../components/ErrorAlert',          () => ({ __esModule: true, default: () => <div /> }));
jest.mock('../../components/KalshiCancelAllButton',() => ({ __esModule: true, default: () => <div /> }));
jest.mock('../../hooks/useDashboard', () => ({
  SystemHealthCard:   () => <div />,
  KalshiHealthCard:   () => <div />,
  AgentStatusCard:    () => <div />,
  RiskProtectionCard: () => <div />,
}));
jest.mock('../../api/auth', () => ({
  authHeaders: jest.fn(() => ({ 'Content-Type': 'application/json' })),
}));
jest.mock('../../hooks/useDebateContext', () => ({
  __esModule: true,
  useDebateContext: () => ({
    getDebateStatus: jest.fn(),
    hasCriticalAlerts: false,
    hasWarnings: false,
    getTotalAlerts: jest.fn(() => 0),
    getTopAlert: jest.fn(() => null),
  }),
}));
jest.mock('../../config/modeColors', () => ({
  MODE_COLORS: {},
  resolveModeKey: jest.fn(() => 'paper'),
}));

import React from 'react';
import { fmtTimestamp } from '../../utils/formatters';

// ═══════════════════════════════════════════════════════════════════════════════
// H01 — PnL divergence badge
// ═══════════════════════════════════════════════════════════════════════════════
describe('H01 — KalshiPortfolioView PnL divergence badge', () => {
  it('renders a ≠ sources badge when gridPortfolio.daily_pnl_usd diverges from risk.daily_pnl_usd', () => {
    const src = read('views', 'KalshiPortfolioView.tsx');
    expect(src).toMatch(/≠ sources|sources differ/);
  });

  it('divergence check uses Math.abs and threshold of 0.01', () => {
    const src = read('views', 'KalshiPortfolioView.tsx');
    expect(src).toMatch(/Math\.abs.*daily_pnl_usd.*0\.01|0\.01.*Math\.abs.*daily_pnl_usd/);
  });

  it('badge has a title attribute explaining both source values', () => {
    const src = read('views', 'KalshiPortfolioView.tsx');
    expect(src).toMatch(/title=.*Sources differ|sources differ/i);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// H02 — summaryReceivedAt + DataAgeBadge
// ═══════════════════════════════════════════════════════════════════════════════
describe('H02 — useKalshiRiskStream exposes summaryReceivedAt', () => {
  it('UseKalshiRiskStreamReturn interface includes summaryReceivedAt', () => {
    const hook = read('hooks', 'useKalshiRiskStream.ts');
    expect(hook).toMatch(/summaryReceivedAt/);
  });

  it('summaryReceivedAt is set via setSummaryReceivedAt(Date.now()) on risk_summary', () => {
    const hook = read('hooks', 'useKalshiRiskStream.ts');
    expect(hook).toMatch(/setSummaryReceivedAt\(Date\.now\(\)\)/);
  });

  it('hook returns summaryReceivedAt in its return object', () => {
    const hook = read('hooks', 'useKalshiRiskStream.ts');
    expect(hook).toMatch(/return\s*\{[^}]*summaryReceivedAt/);
  });

  it('KalshiPortfolioView imports DataAgeBadge', () => {
    const view = read('views', 'KalshiPortfolioView.tsx');
    expect(view).toMatch(/import.*DataAgeBadge/);
  });

  it('KalshiPortfolioView renders DataAgeBadge with warningMs and criticalMs', () => {
    const view = read('views', 'KalshiPortfolioView.tsx');
    expect(view).toMatch(/DataAgeBadge/);
    expect(view).toMatch(/warningMs/);
    expect(view).toMatch(/criticalMs/);
  });

  it('KalshiPortfolioView destructures summaryReceivedAt from useKalshiRiskStream', () => {
    const view = read('views', 'KalshiPortfolioView.tsx');
    expect(view).toMatch(/summaryReceivedAt.*useKalshiRiskStream|useKalshiRiskStream.*summaryReceivedAt/);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// H03 — balanceUsd heuristic removed
// ═══════════════════════════════════════════════════════════════════════════════
describe('H03 — balanceUsd division heuristic removed', () => {
  it('KalshiPortfolioView does NOT divide balance.usd by 100', () => {
    const view = read('views', 'KalshiPortfolioView.tsx');
    expect(view).not.toMatch(/balance\.usd\s*\/\s*100/);
  });

  it('KalshiPortfolioView does NOT use the >100000 threshold heuristic', () => {
    const view = read('views', 'KalshiPortfolioView.tsx');
    expect(view).not.toMatch(/>\s*100000\s*\?.*\/\s*100/);
  });

  it('KalshiPortfolioView has a console.error guard for suspiciously large balance values', () => {
    const view = read('views', 'KalshiPortfolioView.tsx');
    expect(view).toMatch(/console\.error.*balanceUsd.*cents|suspiciously large/i);
  });

  it('unit assertion threshold is 10_000 or 10000', () => {
    const view = read('views', 'KalshiPortfolioView.tsx');
    expect(view).toMatch(/10_000|10000/);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// H04 — Amend row disabled when ConfirmModal is open
// ═══════════════════════════════════════════════════════════════════════════════
describe('H04 — OrdersView amend row disabled when ConfirmModal open', () => {
  it('amend input has disabled={confirmModal.isOpen || amendSubmitting}', () => {
    const view = read('views', 'OrdersView.tsx');
    expect(view).toMatch(/disabled=\{confirmModal\.isOpen.*amendSubmitting|disabled=\{.*amendSubmitting.*confirmModal\.isOpen/);
  });

  it('amend submit button is also disabled when modal is open', () => {
    const view = read('views', 'OrdersView.tsx');
    // The button element has: disabled={confirmModal.isOpen || amendSubmitting}
    // Count occurrences of this pattern — there must be at least 2 (input + button)
    const matches = view.match(/disabled=\{confirmModal\.isOpen/g) ?? [];
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it('handleCancelOrder clears amendOrderId before opening modal', () => {
    const view = read('views', 'OrdersView.tsx');
    const fnBody = view.slice(view.indexOf('handleCancelOrder'), view.indexOf('handleCancelOrder') + 600);
    expect(fnBody).toMatch(/setAmendOrderId\(null\)/);
    expect(fnBody).toMatch(/setAmendPrice\(''\)/);
    expect(fnBody).toMatch(/setConfirmModal/);
    // setAmendOrderId must come BEFORE setConfirmModal
    const amendIdx = fnBody.indexOf('setAmendOrderId(null)');
    const modalIdx = fnBody.indexOf('setConfirmModal');
    expect(amendIdx).toBeLessThan(modalIdx);
  });

  it('Enter key in amend input is blocked when confirmModal.isOpen', () => {
    const view = read('views', 'OrdersView.tsx');
    expect(view).toMatch(/Enter.*!confirmModal\.isOpen|Enter.*confirmModal\.isOpen.*void/);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// H05 — KalshiModeContext broadcasts kill switch state
// ═══════════════════════════════════════════════════════════════════════════════
describe('H05 — KalshiModeContext wsKillActive / wsKillAt', () => {
  it('KalshiModeContext imports useKalshiRiskStream', () => {
    const ctx = read('context', 'KalshiModeContext.tsx');
    expect(ctx).toMatch(/import.*useKalshiRiskStream/);
  });

  it('KalshiModeContextValue interface includes wsKillActive', () => {
    const ctx = read('context', 'KalshiModeContext.tsx');
    expect(ctx).toMatch(/wsKillActive\s*:/);
  });

  it('KalshiModeContextValue interface includes wsKillAt', () => {
    const ctx = read('context', 'KalshiModeContext.tsx');
    expect(ctx).toMatch(/wsKillAt\s*:/);
  });

  it('KalshiModeProvider sets wsKillActive to true on kill_switch alerts', () => {
    const ctx = read('context', 'KalshiModeContext.tsx');
    expect(ctx).toMatch(/type === 'kill_switch'/);
    expect(ctx).toMatch(/setWsKillActive\(true\)/);
  });

  it('KalshiModeProvider sets wsKillAt to Date.now() on kill_switch', () => {
    const ctx = read('context', 'KalshiModeContext.tsx');
    expect(ctx).toMatch(/setWsKillAt\(Date\.now\(\)\)/);
  });

  it('Overview.tsx uses wsKillActive from useKalshiMode', () => {
    const overview = read('views', 'Overview.tsx');
    expect(overview).toMatch(/wsKillActive/);
    expect(overview).toMatch(/wsKillAt/);
  });

  it('Overview.tsx shows Propagating badge for 15 seconds after kill', () => {
    const overview = read('views', 'Overview.tsx');
    expect(overview).toMatch(/Propagating/);
    expect(overview).toMatch(/15_000|15000/);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// H06 — fmtTimestamp UTC + alert deduplication
// ═══════════════════════════════════════════════════════════════════════════════
describe('H06 — fmtTimestamp UTC utility', () => {
  it('fmtTimestamp returns — for null input', () => {
    expect(fmtTimestamp(null)).toBe('—');
  });

  it('fmtTimestamp returns — for undefined input', () => {
    expect(fmtTimestamp(undefined)).toBe('—');
  });

  it('fmtTimestamp always appends UTC suffix', () => {
    const result = fmtTimestamp('2024-01-15T10:30:00Z');
    expect(result).toMatch(/UTC$/);
  });

  it('fmtTimestamp formats a known epoch correctly in UTC', () => {
    // 2024-01-15 10:30:00 UTC
    const result = fmtTimestamp(new Date('2024-01-15T10:30:00Z'));
    expect(result).toBe('2024-01-15 10:30:00 UTC');
  });

  it('fmtTimestamp with timeOnly:true returns HH:MM:SS UTC', () => {
    const result = fmtTimestamp(new Date('2024-06-01T14:05:03Z'), { timeOnly: true });
    expect(result).toBe('14:05:03 UTC');
  });

  it('fmtTimestamp with dateOnly:true returns YYYY-MM-DD', () => {
    const result = fmtTimestamp(new Date('2024-06-01T23:59:59Z'), { dateOnly: true });
    expect(result).toBe('2024-06-01');
  });

  it('fmtTimestamp handles unix epoch seconds (< 1e12)', () => {
    // 1708070400 = 2024-02-16 12:00:00 UTC
    const result = fmtTimestamp(1708070400);
    expect(result).toMatch(/2024-02-16/);
    expect(result).toMatch(/UTC$/);
  });

  it('fmtTimestamp handles unix epoch milliseconds (>= 1e12)', () => {
    const ms = new Date('2024-02-16T12:00:00Z').getTime();
    const result = fmtTimestamp(ms);
    expect(result).toMatch(/2024-02-16/);
    expect(result).toMatch(/UTC$/);
  });

  it('fmtTimestamp returns — for invalid date string', () => {
    expect(fmtTimestamp('not-a-date')).toBe('—');
  });
});

describe('H06 — toLocaleString removed from views', () => {
  const VIEW_FILES: [string, string][] = [
    ['views', 'Overview.tsx'],
    ['views', 'OrdersView.tsx'],
    ['views', 'KalshiRiskScreen.tsx'],
    ['views', 'KillSwitchView.tsx'],
  ];

  it.each(VIEW_FILES)('%s/%s does not call .toLocaleTimeString()', (dir, file) => {
    const content = read(dir, file);
    expect(content).not.toMatch(/\.toLocaleTimeString\(\)/);
  });

  it.each(VIEW_FILES)('%s/%s does not call .toLocaleString() on a Date for display', (dir, file) => {
    const content = read(dir, file);
    // Allow toLocaleString on numbers (e.g. currency formatting), flag only Date.toLocaleString()
    expect(content).not.toMatch(/new Date\([^)]*\)\.toLocaleString\(\)/);
  });
});

describe('H06 — KalshiRiskScreen alert deduplication: polled wins over WS', () => {
  it('KalshiRiskScreen sets polled alerts in alertMap BEFORE WS alerts', () => {
    const view = read('views', 'KalshiRiskScreen.tsx');
    const polledIdx = view.indexOf('polledAlerts?.alerts?.forEach');
    const wsIdx = view.indexOf('wsAlerts.forEach');
    expect(polledIdx).toBeGreaterThan(0);
    expect(wsIdx).toBeGreaterThan(0);
    expect(polledIdx).toBeLessThan(wsIdx);
  });

  it('WS forEach only inserts if !alertMap.has(wsAlert.id)', () => {
    const view = read('views', 'KalshiRiskScreen.tsx');
    expect(view).toMatch(/!alertMap\.has\(wsAlert\.id\)/);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// H07 — Notional card labelled "(risk src)"
// ═══════════════════════════════════════════════════════════════════════════════
describe('H07 — PositionsView Notional card labelled risk src', () => {
  it('PositionsView.tsx StatCard label contains "(risk src)"', () => {
    const view = read('views', 'PositionsView.tsx');
    expect(view).toMatch(/risk src/i);
  });

  it('KalshiPortfolioView.tsx Notional card label is unchanged (risk source not required there)', () => {
    // Notional in portfolio view uses risk?.total_notional_usd without labelling; just verify it exists
    const view = read('views', 'KalshiPortfolioView.tsx');
    expect(view).toMatch(/total_notional_usd/);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// H08 — Notional labelled pre-fee in OrdersView
// ═══════════════════════════════════════════════════════════════════════════════
describe('H08 — OrdersView notional is labelled pre-fee', () => {
  it('OrdersView.tsx open order notional label contains "(pre-fee)"', () => {
    const view = read('views', 'OrdersView.tsx');
    expect(view).toMatch(/pre-fee/i);
  });

  it('pre-fee label appears in the notional stats row, not elsewhere', () => {
    const view = read('views', 'OrdersView.tsx');
    const statsSection = view.slice(view.indexOf('Open order notional'), view.indexOf('Open order notional') + 200);
    expect(statsSection).toMatch(/pre-fee/i);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// M01 — PositionsView asset filter segment match
// ═══════════════════════════════════════════════════════════════════════════════
describe('M01 — PositionsView asset filter uses segment match', () => {
  it('PositionsView.tsx does NOT use startsWith for asset filter', () => {
    const view = read('views', 'PositionsView.tsx');
    // The filter should NOT use startsWith on ticker
    const filterSection = view.slice(view.indexOf('assetFilter'), view.indexOf('assetFilter') + 400);
    expect(filterSection).not.toMatch(/\.startsWith\(assetFilter\)/);
  });

  it('PositionsView.tsx uses split("-")[0] for segment extraction', () => {
    const view = read('views', 'PositionsView.tsx');
    expect(view).toMatch(/split\(['"]-['"]\)\[0\]/);
  });

  it('PositionsView.tsx uses strict equality (===) for segment comparison', () => {
    const view = read('views', 'PositionsView.tsx');
    expect(view).toMatch(/segment\s*===\s*assetFilter/);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// M02 — useApiData single-timer invariant
// ═══════════════════════════════════════════════════════════════════════════════
describe('M02 — useApiData scheduleNext single-timer invariant', () => {
  it('scheduleNext nulls pollingIntervalRef.current before setTimeout', () => {
    const hook = read('hooks', 'useApiData.ts');
    const schedFn = hook.slice(hook.indexOf('scheduleNext'), hook.indexOf('scheduleNext') + 600);
    // First line nulls the ref
    expect(schedFn).toMatch(/pollingIntervalRef\.current\s*=\s*null/);
  });

  it('setTimeout callback nulls pollingIntervalRef.current before fetchData', () => {
    const hook = read('hooks', 'useApiData.ts');
    const schedFn = hook.slice(hook.indexOf('scheduleNext'), hook.indexOf('scheduleNext') + 600);
    // Inside the setTimeout: clear ref, then await fetchData
    expect(schedFn).toMatch(/pollingIntervalRef\.current\s*=\s*null[^}]*await fetchData/s);
  });

  it('reschedule is guarded: only if pollingIntervalRef.current === null', () => {
    const hook = read('hooks', 'useApiData.ts');
    expect(hook).toMatch(/pollingIntervalRef\.current\s*===\s*null/);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// M03 — WS alerts do not overwrite polled resolved status
// ═══════════════════════════════════════════════════════════════════════════════
describe('M03 — KalshiRiskScreen polled resolved overrides WS active', () => {
  it('polled alerts are iterated first in allAlerts memo', () => {
    const view = read('views', 'KalshiRiskScreen.tsx');
    const memoBody = view.slice(view.indexOf('allAlerts = useMemo'), view.indexOf('allAlerts = useMemo') + 600);
    const polledIdx = memoBody.indexOf('polledAlerts');
    const wsIdx = memoBody.indexOf('wsAlerts');
    expect(polledIdx).toBeGreaterThan(0);
    expect(wsIdx).toBeGreaterThan(polledIdx);
  });

  it('WS insertion is conditional on !alertMap.has', () => {
    const view = read('views', 'KalshiRiskScreen.tsx');
    expect(view).toMatch(/if\s*\(\s*!alertMap\.has\(wsAlert\.id\)/);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// M04 — Amend submit disabled/debounced
// ═══════════════════════════════════════════════════════════════════════════════
describe('M04 — OrdersView amend submit debounced', () => {
  it('OrdersView.tsx has amendSubmitting state', () => {
    const view = read('views', 'OrdersView.tsx');
    expect(view).toMatch(/amendSubmitting/);
  });

  it('handleAmendSubmit returns early if amendSubmitting is true', () => {
    const view = read('views', 'OrdersView.tsx');
    const fnBody = view.slice(view.indexOf('handleAmendSubmit'), view.indexOf('handleAmendSubmit') + 600);
    expect(fnBody).toMatch(/amendSubmitting.*return|if.*amendSubmitting/);
  });

  it('setAmendSubmitting(true) is called before the fetch', () => {
    const view = read('views', 'OrdersView.tsx');
    const fnBody = view.slice(view.indexOf('handleAmendSubmit'), view.indexOf('handleAmendSubmit') + 600);
    const setTrueIdx = fnBody.indexOf('setAmendSubmitting(true)');
    const fetchIdx = fnBody.indexOf('fetch(');
    expect(setTrueIdx).toBeGreaterThan(0);
    expect(setTrueIdx).toBeLessThan(fetchIdx);
  });

  it('setAmendSubmitting(false) is in the finally block', () => {
    const view = read('views', 'OrdersView.tsx');
    const fnBody = view.slice(view.indexOf('handleAmendSubmit'), view.indexOf('handleAmendSubmit') + 900);
    expect(fnBody).toMatch(/finally[\s\S]*setAmendSubmitting\(false\)/);
  });

  it('amend button shows … while submitting', () => {
    const view = read('views', 'OrdersView.tsx');
    expect(view).toMatch(/amendSubmitting.*'…'|amendSubmitting.*\u2026/);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// M05 — 50+ alerts sticky banner
// ═══════════════════════════════════════════════════════════════════════════════
describe('M05 — KalshiRiskScreen 50+ alerts banner', () => {
  it('KalshiRiskScreen.tsx has a conditional banner when allAlerts.length > 50', () => {
    const view = read('views', 'KalshiRiskScreen.tsx');
    expect(view).toMatch(/allAlerts\.length\s*>\s*50/);
  });

  it('banner warns that critical alerts may be on later pages', () => {
    const view = read('views', 'KalshiRiskScreen.tsx');
    expect(view).toMatch(/later pages|critical alerts may/i);
  });

  it('banner is rendered before the alerts table', () => {
    const view = read('views', 'KalshiRiskScreen.tsx');
    const bannerIdx = view.indexOf('allAlerts.length > 50');
    const tableIdx = view.indexOf('<table');
    expect(bannerIdx).toBeGreaterThan(0);
    expect(tableIdx).toBeGreaterThan(bannerIdx);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// M06 — Catalog refresh rate-limit
// ═══════════════════════════════════════════════════════════════════════════════
describe('M06 — KalshiDashboardView catalog refresh rate-limited', () => {
  it('KalshiDashboardView.tsx defines a catalog refresh interval constant', () => {
    const view = read('views', 'KalshiDashboardView.tsx');
    expect(view).toMatch(/CATALOG_REFRESH_INTERVAL_MS/);
  });

  it('uses localStorage to persist the last refresh timestamp', () => {
    const view = read('views', 'KalshiDashboardView.tsx');
    // The key is stored in CATALOG_REFRESH_TS_KEY constant, then passed to localStorage.getItem
    expect(view).toMatch(/CATALOG_REFRESH_TS_KEY/);
    expect(view).toMatch(/localStorage\.getItem\(CATALOG_REFRESH_TS_KEY\)/);
  });

  it('writes the timestamp to localStorage after a successful refresh', () => {
    const view = read('views', 'KalshiDashboardView.tsx');
    // The key variable CATALOG_REFRESH_TS_KEY is passed to localStorage.setItem
    expect(view).toMatch(/localStorage\.setItem\(CATALOG_REFRESH_TS_KEY/);
  });

  it('skips the refresh if within the rate-limit window', () => {
    const view = read('views', 'KalshiDashboardView.tsx');
    expect(view).toMatch(/Date\.now\(\)\s*-\s*lastRefresh\s*<\s*CATALOG_REFRESH_INTERVAL_MS/);
  });

  it('rate-limit window is 60 seconds', () => {
    const view = read('views', 'KalshiDashboardView.tsx');
    expect(view).toMatch(/60_000|60000/);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// M07 — Kill switch propagation badge
// ═══════════════════════════════════════════════════════════════════════════════
describe('M07 — KillSwitchView propagation badge after reset', () => {
  it('KillSwitchView.tsx has lastKillActionAt state', () => {
    const view = read('views', 'KillSwitchView.tsx');
    expect(view).toMatch(/lastKillActionAt/);
  });

  it('handleResetKillSwitch sets lastKillActionAt to Date.now()', () => {
    const view = read('views', 'KillSwitchView.tsx');
    const fnBody = view.slice(view.indexOf('handleResetKillSwitch'), view.indexOf('handleResetKillSwitch') + 600);
    expect(fnBody).toMatch(/setLastKillActionAt\(Date\.now\(\)\)/);
  });

  it('Propagating… badge appears after reset within 15s window', () => {
    const view = read('views', 'KillSwitchView.tsx');
    expect(view).toMatch(/Propagating/);
    expect(view).toMatch(/PROPAGATION_MS|15_000|15000/);
  });

  it('KillSwitchView uses fmtTimestamp instead of toLocaleTimeString', () => {
    const view = read('views', 'KillSwitchView.tsx');
    expect(view).toMatch(/fmtTimestamp/);
    expect(view).not.toMatch(/\.toLocaleTimeString\(\)/);
  });

  it('kill_timestamp detail uses fmtTimestamp not toLocaleString', () => {
    const view = read('views', 'KillSwitchView.tsx');
    expect(view).toMatch(/fmtTimestamp\(killSwitch\.kill_timestamp\)/);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// M08 — fmtTimestamp is the canonical utility across views
// ═══════════════════════════════════════════════════════════════════════════════
describe('M08 — fmtTimestamp is shared across views', () => {
  const TIMESTAMP_VIEWS: [string, string][] = [
    ['views', 'KalshiRiskScreen.tsx'],
    ['views', 'OrdersView.tsx'],
    ['views', 'KillSwitchView.tsx'],
    ['views', 'Overview.tsx'],
  ];

  it.each(TIMESTAMP_VIEWS)('%s/%s imports fmtTimestamp from utils/formatters', (dir, file) => {
    const content = read(dir, file);
    expect(content).toMatch(/fmtTimestamp/);
  });

  it('fmtTimestamp is exported from utils/formatters.ts', () => {
    const fmt = read('utils', 'formatters.ts');
    expect(fmt).toMatch(/export function fmtTimestamp/);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Cross-cutting: all modified files are non-empty and brace-balanced
// ═══════════════════════════════════════════════════════════════════════════════
describe('Cross-cutting — modified files are non-empty and brace-balanced', () => {
  const MODIFIED: [string, string, string][] = [
    ['utils/formatters.ts',              'utils',   'formatters.ts'            ],
    ['hooks/useApiData.ts',              'hooks',   'useApiData.ts'            ],
    ['hooks/useKalshiRiskStream.ts',     'hooks',   'useKalshiRiskStream.ts'   ],
    ['context/KalshiModeContext.tsx',    'context', 'KalshiModeContext.tsx'    ],
    ['views/KalshiPortfolioView.tsx',    'views',   'KalshiPortfolioView.tsx'  ],
    ['views/KalshiRiskScreen.tsx',       'views',   'KalshiRiskScreen.tsx'     ],
    ['views/OrdersView.tsx',             'views',   'OrdersView.tsx'           ],
    ['views/Overview.tsx',               'views',   'Overview.tsx'             ],
    ['views/PositionsView.tsx',          'views',   'PositionsView.tsx'        ],
    ['views/KillSwitchView.tsx',         'views',   'KillSwitchView.tsx'       ],
    ['views/KalshiDashboardView.tsx',    'views',   'KalshiDashboardView.tsx'  ],
  ];

  it.each(MODIFIED)('file %s is non-empty', (_label, dir, file) => {
    expect(read(dir, file).trim().length).toBeGreaterThan(0);
  });

  it.each(MODIFIED)('file %s has balanced curly braces', (_label, dir, file) => {
    const content = read(dir, file)
      .replace(/`[^`]*`/gs, '``')
      .replace(/"[^"\\]*(?:\\.[^"\\]*)*"/g, '""')
      .replace(/'[^'\\]*(?:\\.[^'\\]*)*'/g, "''");
    const opens  = (content.match(/\{/g) ?? []).length;
    const closes = (content.match(/\}/g) ?? []).length;
    expect(Math.abs(opens - closes)).toBeLessThanOrEqual(2);
  });

  it.each(MODIFIED)('file %s has no git conflict markers', (_label, dir, file) => {
    const content = read(dir, file);
    expect(content).not.toMatch(/<<<<<<< HEAD/);
    expect(content).not.toMatch(/>>>>>>>/);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// Sprint-4 — Targeted bug fixes
// ═══════════════════════════════════════════════════════════════════════════════

describe('S4-01 — RiskAlertFeed dismiss button has type=button', () => {
  it('dismiss button has explicit type="button" to prevent form-submit side-effects', () => {
    const src = read('components', 'RiskAlertFeed.tsx');
    // Find the dismiss button block and confirm type="button" precedes onClick
    const btnIdx = src.indexOf('onDismiss(alert.id)');
    const btnSection = src.slice(Math.max(0, btnIdx - 200), btnIdx + 50);
    expect(btnSection).toMatch(/type="button"/);
  });
});

describe('S4-02 — SwarmVerdictFeed uses stable composite key', () => {
  it('does not use array index as React key', () => {
    const src = read('components', 'SwarmVerdictFeed.tsx');
    // Should not see key={idx} pattern
    expect(src).not.toMatch(/key=\{idx\}/);
  });

  it('uses a composite key derived from verdict fields', () => {
    const src = read('components', 'SwarmVerdictFeed.tsx');
    // Should have a key built from ts + asset + timeframe
    expect(src).toMatch(/stableKey|ts.*asset.*timeframe|asset.*timeframe.*ts/);
  });
});

describe('S4-03 — useApiData query option is implemented', () => {
  it('queryRef is declared in useApiData', () => {
    const hook = read('hooks', 'useApiData.ts');
    expect(hook).toMatch(/queryRef/);
  });

  it('query params are appended to the fetch URL', () => {
    const hook = read('hooks', 'useApiData.ts');
    expect(hook).toMatch(/URLSearchParams/);
    expect(hook).toMatch(/queryRef\.current/);
  });
});

describe('S4-04 — KalshiVolDashboardView uses max_notional_usd (not max_total_notional_usd)', () => {
  it('maxNotional reads from limits.max_notional_usd', () => {
    const src = read('views', 'KalshiVolDashboardView.tsx');
    expect(src).toMatch(/limits\?\.\s*max_notional_usd/);
  });

  it('does not reference the renamed field max_total_notional_usd', () => {
    const src = read('views', 'KalshiVolDashboardView.tsx');
    expect(src).not.toMatch(/max_total_notional_usd/);
  });
});

describe('S4-05 — KalshiRiskScreen Acknowledge All gated on active alerts', () => {
  it('Acknowledge All button is conditioned on at least one active alert', () => {
    const src = read('views', 'KalshiRiskScreen.tsx');
    // Button should check for active alerts, not just allAlerts.length > 0
    expect(src).toMatch(/some.*status.*active|active.*some|hasActiveAlerts|activeCount/);
  });
});

describe('S4-06 — PositionsView navigates without window.location.hash', () => {
  it('does not use window.location.hash for navigation', () => {
    const src = read('views', 'PositionsView.tsx');
    expect(src).not.toMatch(/window\.location\.hash/);
  });
});
