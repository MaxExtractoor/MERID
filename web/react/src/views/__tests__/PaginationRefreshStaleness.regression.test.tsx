/**
 * PaginationRefreshStaleness.regression.test.tsx
 *
 * Regression tests covering all 10 fixes from the Pagination/Refresh/Staleness audit.
 *
 * BUG-007  useApiData — double polling chain on endpoint change (timer cleared at effect top)
 * BUG-001  DataTableEnhanced — currentPage not clamped when dataset shrinks
 * BUG-002  Logs.tsx — refreshInterval selector state had no effect (wired to hardcoded constant)
 * BUG-003  KalshiAllMarketsView — pagination not reset synchronously on category-tab switch
 * BUG-004  KalshiAllMarketsView — no auto-refresh (mount-only fetch)
 * BUG-005  OrdersView — fills hard-capped at 20 with no UX signal
 * BUG-006  KalshiRiskScreen — "show all" DOM bomb replaced with pagination
 * MED-003  DataFreshnessIndicator — frozen age display (no setInterval clock tick)
 * MED-002  OperatorActivityStream — stale fetch from old tab overwrites active tab state
 * MED-004  KalshiPortfolioView — WS refetch storm on every summary message
 *
 * Strategy: source-level static analysis (regex) + targeted RTL component tests.
 */

import * as fs from 'fs';
import * as path from 'path';
import React from 'react';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

// ─── Path helpers ─────────────────────────────────────────────────────────────
const SRC = path.resolve(__dirname, '../..');
const src = (...parts: string[]) => path.join(SRC, ...parts);
function read(...parts: string[]): string {
  return fs.readFileSync(src(...parts), 'utf-8');
}

// ─── Shared mocks ─────────────────────────────────────────────────────────────
jest.mock('../../hooks/useStubRegistry', () => ({
  __esModule: true,
  useStubRegistry: jest.fn(() => ({ register: jest.fn() })),
}));

jest.mock('../../hooks/useApiData', () => ({
  __esModule: true,
  useApiData: jest.fn(() => ({
    data: null,
    loading: false,
    error: null,
    refetch: jest.fn(),
    lastUpdated: null,
    isLoading: false,
    rawResponse: null,
    isStub: false,
    stubMessage: '',
  })),
}));

jest.mock('../../hooks/useKalshiRiskStream', () => ({
  __esModule: true,
  useKalshiRiskStream: jest.fn(() => ({ alerts: [], connected: false, summary: null, clearAlerts: jest.fn() })),
}));

jest.mock('../../context/KalshiModeContext', () => ({
  __esModule: true,
  useKalshiMode: jest.fn(() => ({ isLive: false, data: { mode: 'paper', is_live: false }, loading: false })),
  KalshiModeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

jest.mock('../../api/auth', () => ({
  authHeaders: jest.fn(() => ({ 'Content-Type': 'application/json' })),
}));

jest.mock('lucide-react', () =>
  new Proxy({}, {
    get: (_t, prop) => {
      if (typeof prop !== 'string') return undefined;
      const Stub = ({ className }: { className?: string }) => (
        <span data-testid={`icon-${prop}`} className={className} />
      );
      Stub.displayName = String(prop);
      return Stub;
    },
  })
);

jest.mock('../../components/ExecutionGateStrip', () => ({ __esModule: true, default: () => <div data-testid="exec-gate" /> }));
jest.mock('../../components/KalshiModeBadge',    () => ({ __esModule: true, default: () => <div data-testid="mode-badge" /> }));
jest.mock('../../components/KalshiPnlChart',     () => ({ __esModule: true, default: () => <div data-testid="pnl-chart" /> }));
jest.mock('../../components/KalshiCancelAllButton', () => ({ __esModule: true, default: () => <div data-testid="cancel-all" /> }));
jest.mock('../../components/ConfirmModal',       () => ({ ConfirmModal: () => <div data-testid="confirm-modal" /> }));
jest.mock('../../components/ErrorAlert',         () => ({ __esModule: true, default: () => <div data-testid="error-alert" /> }));
jest.mock('../../components/EmptyState',         () => ({ __esModule: true, default: () => <div data-testid="empty-state" /> }));
jest.mock('../../utils/logger',                  () => ({ logUiError: jest.fn() }));
jest.mock('../../utils/formatters',              () => ({ formatDateTime: (v: string) => v }));
jest.mock('../../ui/icons', () =>
  new Proxy({}, {
    get: (_t, prop) => {
      if (typeof prop !== 'string') return undefined;
      const Stub = ({ className }: { className?: string }) => <span className={className} />;
      Stub.displayName = String(prop);
      return Stub;
    },
  })
);
jest.mock('../../config/constants', () => ({
  API_BASE_URL: 'http://localhost:8011',
  AUTH_TOKEN_KEY: 'merid-access',
  DEFAULTS: {
    POLLING_INTERVALS: {
      FAST_REFRESH: 5000, STANDARD: 10000, SLOW: 30000,
      LOGS: 10000, LOG_STATS: 60000, MEDIUM: 20000,
    },
    PAGE_SIZE: 25,
  },
  API_ENDPOINTS: {
    KALSHI_ORDERS: '/api/v1/kalshi/orders',
    KALSHI_FILLS: '/api/v1/kalshi/fills',
    KALSHI_ORDER_CANCEL: (id: string) => `/api/v1/kalshi/orders/${id}`,
    KALSHI_ORDER_AMEND: (id: string) => `/api/v1/kalshi/orders/${id}/amend`,
    KALSHI_ORDERS_BATCH_CANCEL: '/api/v1/kalshi/orders/batch-cancel',
    RISK_SUMMARY: '/api/v1/risk/summary',
    RISK_ALERTS: '/api/v1/risk/alerts',
    RISK_ALERT_ACKNOWLEDGE: (id: string) => `/api/v1/risk/alerts/${id}/acknowledge`,
    RISK_ALERTS_ACKNOWLEDGE_ALL: '/api/v1/risk/alerts/acknowledge-all',
    LOGS: '/api/v1/logs',
    LOGS_STATS: '/api/v1/logs/stats',
    LOGS_CLEAR: '/api/v1/logs/clear',
    OPERATOR_ORDERS: '/api/v1/operator/orders',
    SYSTEM_DECISIONS: '/api/v1/system/decisions',
    OPERATOR_AUDIT_TRAIL: '/api/v1/operator/audit',
  },
  ORDER_STATUS: { RESTING: 'resting', PENDING: 'pending', FILLED: 'filled', CANCELED: 'canceled', CANCELLED: 'cancelled' },
  LOG_LEVELS: { error: 'error', warn: 'warn', info: 'info', debug: 'debug' },
  KALSHI_CATEGORY_COLORS: {},
}));

// ══════════════════════════════════════════════════════════════════════════════
// BUG-007 — useApiData: no double polling chain on endpoint/pollingInterval change
// ══════════════════════════════════════════════════════════════════════════════
describe('BUG-007 — useApiData no double polling chain', () => {
  it('clears prior pollingIntervalRef timer at the top of the polling effect', () => {
    const source = read('hooks', 'useApiData.ts');
    // The fix must clear pollingIntervalRef.current BEFORE the first fetchData() inside the polling branch
    const clearIdx = source.indexOf('clearTimeout(pollingIntervalRef.current)');
    // Find the "// Initial fetch" comment, then the fetchData() call that follows it
    const commentIdx = source.indexOf('// Initial fetch');
    const fetchIdx = source.indexOf('fetchData();', commentIdx);
    expect(clearIdx).toBeGreaterThan(-1);
    expect(commentIdx).toBeGreaterThan(-1);
    expect(fetchIdx).toBeGreaterThan(-1);
    // clear must appear before the initial fetchData call
    expect(clearIdx).toBeLessThan(fetchIdx);
  });

  it('sets pollingIntervalRef.current to null after clearing', () => {
    const source = read('hooks', 'useApiData.ts');
    expect(source).toMatch(/pollingIntervalRef\.current = null/);
  });

  it('timer clear happens inside the pollingInterval > 0 branch', () => {
    const source = read('hooks', 'useApiData.ts');
    const branchIdx = source.indexOf('if (pollingInterval && pollingInterval > 0)');
    const clearIdx  = source.indexOf('clearTimeout(pollingIntervalRef.current)');
    expect(branchIdx).toBeGreaterThan(-1);
    expect(clearIdx).toBeGreaterThan(branchIdx);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// BUG-001 — DataTableEnhanced: currentPage clamped when dataset shrinks
// ══════════════════════════════════════════════════════════════════════════════
describe('BUG-001 — DataTableEnhanced currentPage clamped on data shrink', () => {
  it('source contains a useEffect that clamps currentPage to totalPages', () => {
    const source = read('components', 'DataTableEnhanced.tsx');
    expect(source).toMatch(/useEffect\(/);
    expect(source).toMatch(/currentPage > totalPages/);
    expect(source).toMatch(/setCurrentPage\(totalPages\)/);
  });

  it('RTL: page resets to last valid page when data shrinks below current page', async () => {
    // DataTableEnhanced has no useApiData dependency — import directly
    const { default: DataTableEnhanced } = await import('../../components/DataTableEnhanced');

    type Row = { id: number; name: string };
    const cols = [
      { key: 'id' as keyof Row, label: 'ID', sortable: false },
      { key: 'name' as keyof Row, label: 'Name', sortable: false },
    ];

    // 30 rows → 2 pages at pageSize=25
    const bigData: Row[] = Array.from({ length: 30 }, (_, i) => ({ id: i + 1, name: `Item ${i + 1}` }));
    const smallData: Row[] = Array.from({ length: 5 }, (_, i) => ({ id: i + 1, name: `Item ${i + 1}` }));

    const { rerender } = render(
      <DataTableEnhanced data={bigData} columns={cols} pageSize={25} showPagination />
    );

    // Navigate to page 2
    const nextBtn = screen.getByRole('button', { name: /next/i });
    fireEvent.click(nextBtn);
    await waitFor(() => expect(screen.queryByText('Item 26')).toBeInTheDocument());

    // Shrink data to only 1 page worth — page 2 no longer valid
    await act(async () => {
      rerender(<DataTableEnhanced data={smallData} columns={cols} pageSize={25} showPagination />);
    });

    // Should have auto-clamped back to page 1 and show items
    await waitFor(() => expect(screen.getByText('Item 1')).toBeInTheDocument());
    // Page 2 nav should be gone (only 1 page now)
    expect(screen.queryByRole('button', { name: /next/i })).not.toBeInTheDocument();
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// BUG-002 — Logs.tsx: refreshInterval state is passed to useApiData
// ══════════════════════════════════════════════════════════════════════════════
describe('BUG-002 — Logs refreshInterval wired to useApiData', () => {
  it('Logs.tsx passes refreshInterval state variable (not a constant) to useApiData pollingInterval', () => {
    const source = read('views', 'Logs.tsx');
    // Must use the refreshInterval state variable, not the hardcoded constant
    expect(source).toMatch(/pollingInterval: autoRefresh \? refreshInterval : undefined/);
  });

  it('Logs.tsx does NOT pass the hardcoded DEFAULTS.POLLING_INTERVALS.LOGS as pollingInterval', () => {
    const source = read('views', 'Logs.tsx');
    // The old bug: pollingInterval: autoRefresh ? DEFAULTS.POLLING_INTERVALS.LOGS : undefined
    expect(source).not.toMatch(/pollingInterval: autoRefresh \? DEFAULTS\.POLLING_INTERVALS\.LOGS/);
  });

  it('refreshInterval state has an initial value and is set by the select', () => {
    const source = read('views', 'Logs.tsx');
    expect(source).toMatch(/useState\(5000\)/); // initial 5s
    expect(source).toMatch(/setRefreshInterval\(Number/);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// BUG-003 — KalshiAllMarketsView: page reset is synchronous on category change
// ══════════════════════════════════════════════════════════════════════════════
describe('BUG-003 — KalshiAllMarketsView synchronous page reset on category change', () => {
  it('calls setPage(1) before fetchPool inside the activeCategory useEffect', () => {
    const source = read('views', 'KalshiAllMarketsView.tsx');
    // Find the effect block that depends on activeCategory
    const effectStart = source.indexOf("}, [activeCategory, fetchPool]);");
    expect(effectStart).toBeGreaterThan(-1);
    // The setPage(1) call must appear BEFORE the fetchPool call within this effect
    const effectBlock = source.slice(
      source.lastIndexOf('useEffect(() => {', effectStart),
      effectStart
    );
    const setPageIdx  = effectBlock.indexOf('setPage(1)');
    const fetchPoolIdx = effectBlock.indexOf('fetchPool(activeCategory)');
    expect(setPageIdx).toBeGreaterThan(-1);
    expect(fetchPoolIdx).toBeGreaterThan(-1);
    expect(setPageIdx).toBeLessThan(fetchPoolIdx);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// BUG-004 — KalshiAllMarketsView: auto-refresh intervals are set up
// ══════════════════════════════════════════════════════════════════════════════
describe('BUG-004 — KalshiAllMarketsView auto-refresh timers', () => {
  it('source calls setInterval for fetchCoverage', () => {
    const source = read('views', 'KalshiAllMarketsView.tsx');
    expect(source).toMatch(/setInterval\(fetchCoverage,/);
  });

  it('source calls setInterval for fetchPool', () => {
    const source = read('views', 'KalshiAllMarketsView.tsx');
    expect(source).toMatch(/setInterval\(\(\) => fetchPool\(activeCategory\)/);
  });

  it('source calls setInterval for fetchCaps', () => {
    const source = read('views', 'KalshiAllMarketsView.tsx');
    expect(source).toMatch(/setInterval\(fetchCaps,/);
  });

  it('source calls setInterval for fetchAgentState', () => {
    const source = read('views', 'KalshiAllMarketsView.tsx');
    expect(source).toMatch(/setInterval\(fetchAgentState,/);
  });

  it('all setInterval timers are cleared in the effect cleanup', () => {
    const source = read('views', 'KalshiAllMarketsView.tsx');
    const clearCount = (source.match(/clearInterval\(/g) || []).length;
    // At least 4 clearInterval calls — one per timer
    expect(clearCount).toBeGreaterThanOrEqual(4);
  });

  it('coverage polls at 60s and agentState polls at 30s', () => {
    const source = read('views', 'KalshiAllMarketsView.tsx');
    expect(source).toMatch(/setInterval\(fetchCoverage, 60_000\)/);
    expect(source).toMatch(/setInterval\(fetchAgentState, 30_000\)/);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// BUG-005 — OrdersView: fills are paginated, not silently truncated at 20
// ══════════════════════════════════════════════════════════════════════════════
describe('BUG-005 — OrdersView fills pagination', () => {
  it('source does NOT use .slice(0, 20) for fills', () => {
    const source = read('views', 'OrdersView.tsx');
    expect(source).not.toMatch(/\.slice\(0, 20\)/);
  });

  it('source defines fillsPage state and FILLS_PAGE_SIZE', () => {
    const source = read('views', 'OrdersView.tsx');
    expect(source).toMatch(/fillsPage/);
    expect(source).toMatch(/FILLS_PAGE_SIZE/);
  });

  it('source calculates fillsTotalPages', () => {
    const source = read('views', 'OrdersView.tsx');
    expect(source).toMatch(/fillsTotalPages/);
  });

  it('source renders fills total count, not just last N', () => {
    const source = read('views', 'OrdersView.tsx');
    expect(source).toMatch(/allFills\.length/);
    expect(source).toMatch(/total/);
  });

  it('source includes previous/next pagination buttons for fills', () => {
    const source = read('views', 'OrdersView.tsx');
    expect(source).toMatch(/Previous fills page|previous fills page|aria-label="Previous fills page"/i);
    expect(source).toMatch(/Next fills page|next fills page|aria-label="Next fills page"/i);
  });

  it('fills page clamp useEffect is present', () => {
    const source = read('views', 'OrdersView.tsx');
    expect(source).toMatch(/fillsPage > fillsTotalPages/);
    expect(source).toMatch(/setFillsPage\(fillsTotalPages\)/);
  });

  it('RTL: fills section shows total count when data present', async () => {
    const { useApiData } = await import('../../hooks/useApiData');
    const mockUseApiData = useApiData as jest.Mock;
    mockUseApiData.mockImplementation((endpoint: string) => {
      if (endpoint === '/api/v1/kalshi/orders') {
        return { data: { orders: [] }, loading: false, error: null, refetch: jest.fn(), lastUpdated: null, isLoading: false, rawResponse: null, isStub: false, stubMessage: '' };
      }
      if (endpoint === '/api/v1/kalshi/fills') {
        return {
          data: {
            fills: Array.from({ length: 25 }, (_, i) => ({
              trade_id: `t${i}`, ticker: 'BTCX', side: 'yes',
              size: 1, price: 0.5, fee: 0.01, timestamp: new Date().toISOString(),
            })),
          },
          loading: false, error: null, refetch: jest.fn(), lastUpdated: null, isLoading: false, rawResponse: null, isStub: false, stubMessage: '',
        };
      }
      return { data: null, loading: false, error: null, refetch: jest.fn(), lastUpdated: null, isLoading: false, rawResponse: null, isStub: false, stubMessage: '' };
    });

    const { default: OrdersView } = await import('../../views/OrdersView');
    render(<OrdersView />);

    // Should show "25 total" not "Last 20"
    await waitFor(() => expect(screen.getByText(/25 total/i)).toBeInTheDocument());
    // Pagination controls should be present (25 fills, page size 20 → 2 pages)
    expect(screen.getByLabelText('Next fills page')).toBeInTheDocument();
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// BUG-006 — KalshiRiskScreen: paginated alerts, no show-all DOM bomb
// ══════════════════════════════════════════════════════════════════════════════
describe('BUG-006 — KalshiRiskScreen alerts pagination', () => {
  it('source does NOT contain showAllAlerts state', () => {
    const source = read('views', 'KalshiRiskScreen.tsx');
    expect(source).not.toMatch(/showAllAlerts/);
  });

  it('source does NOT render "Show all N alerts"', () => {
    const source = read('views', 'KalshiRiskScreen.tsx');
    expect(source).not.toMatch(/Show all.*alerts/);
  });

  it('source uses alertsPage state and pagedAlerts slice', () => {
    const source = read('views', 'KalshiRiskScreen.tsx');
    expect(source).toMatch(/alertsPage/);
    expect(source).toMatch(/pagedAlerts/);
    expect(source).toMatch(/ALERTS_PAGE_SIZE/);
  });

  it('source calculates realAlertsTotalPages', () => {
    const source = read('views', 'KalshiRiskScreen.tsx');
    expect(source).toMatch(/realAlertsTotalPages/);
  });

  it('source clamps page to realAlertsTotalPages', () => {
    const source = read('views', 'KalshiRiskScreen.tsx');
    expect(source).toMatch(/clampedAlertsPage/);
    expect(source).toMatch(/Math\.min\(alertsPage, realAlertsTotalPages\)/);
  });

  it('source renders Previous/Next pagination buttons for alerts', () => {
    const source = read('views', 'KalshiRiskScreen.tsx');
    expect(source).toMatch(/Previous alerts page|aria-label="Previous alerts page"/i);
    expect(source).toMatch(/Next alerts page|aria-label="Next alerts page"/i);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// MED-003 — DataFreshnessIndicator: live clock tick (not frozen at render)
// ══════════════════════════════════════════════════════════════════════════════
describe('MED-003 — DataFreshnessIndicator live clock tick', () => {
  it('source imports useState and useEffect from react', () => {
    const source = read('components', 'DataFreshnessIndicator.tsx');
    expect(source).toMatch(/import \{[^}]*useState[^}]*\} from 'react'/);
    expect(source).toMatch(/import \{[^}]*useEffect[^}]*\} from 'react'/);
  });

  it('source has a setInterval that calls setNow', () => {
    const source = read('components', 'DataFreshnessIndicator.tsx');
    // The callback is `() => setNow(Date.now())` — use a pattern that tolerates nested parens
    expect(source).toMatch(/setInterval\(.*setNow/);
  });

  it('source uses the now state variable (not bare Date.now()) for age computation', () => {
    const source = read('components', 'DataFreshnessIndicator.tsx');
    // ageMs must be derived from `now` state, not a bare Date.now() call outside state
    expect(source).toMatch(/const ageMs = now - last/);
  });

  it('setInterval for clock tick is cleaned up', () => {
    const source = read('components', 'DataFreshnessIndicator.tsx');
    expect(source).toMatch(/clearInterval\(/);
  });

  it('RTL: displayed age text updates when clock ticks', async () => {
    jest.useFakeTimers();
    const fixedNow = new Date('2024-01-01T12:00:00.000Z');
    const tenSecondsAgo = new Date(fixedNow.getTime() - 10_000);
    jest.setSystemTime(fixedNow);

    const { DataFreshnessIndicator } = await import('../../components/DataFreshnessIndicator');
    render(<DataFreshnessIndicator lastUpdated={tenSecondsAgo} thresholdMs={30000} />);

    expect(screen.getByText('10s ago')).toBeInTheDocument();

    // Advance clock by 5 more seconds
    await act(async () => { jest.advanceTimersByTime(5000); });
    expect(screen.getByText('15s ago')).toBeInTheDocument();

    jest.useRealTimers();
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// MED-002 — OperatorActivityStream: AbortController on tab switch
// ══════════════════════════════════════════════════════════════════════════════
describe('MED-002 — OperatorActivityStream abort on tab switch', () => {
  it('fetchTab accepts a signal parameter', () => {
    const source = read('views', 'OperatorActivityStream.tsx');
    expect(source).toMatch(/fetchTab\s*=\s*useCallback\s*\(async\s*\(t:\s*Tab,\s*signal:\s*AbortSignal\)/);
  });

  it('fetch calls pass signal to the request', () => {
    const source = read('views', 'OperatorActivityStream.tsx');
    expect(source).toMatch(/fetch\(endpoint, \{ headers, signal \}\)/);
  });

  it('AbortError is caught and silently ignored', () => {
    const source = read('views', 'OperatorActivityStream.tsx');
    expect(source).toMatch(/err\.name === 'AbortError'/);
  });

  it('useEffect creates an AbortController and calls abort on cleanup', () => {
    const source = read('views', 'OperatorActivityStream.tsx');
    expect(source).toMatch(/new AbortController\(\)/);
    expect(source).toMatch(/controller\.abort\(\)/);
  });

  it('manual refresh button passes a fresh AbortController signal', () => {
    const source = read('views', 'OperatorActivityStream.tsx');
    expect(source).toMatch(/fetchTab\(tab, new AbortController\(\)\.signal\)/);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// MED-004 — KalshiPortfolioView: WS refetch is debounced
// ══════════════════════════════════════════════════════════════════════════════
describe('MED-004 — KalshiPortfolioView WS refetch debounce', () => {
  it('source imports useRef', () => {
    const source = read('views', 'KalshiPortfolioView.tsx');
    expect(source).toMatch(/useRef/);
  });

  it('source defines a wsRefetchTimerRef', () => {
    const source = read('views', 'KalshiPortfolioView.tsx');
    expect(source).toMatch(/wsRefetchTimerRef/);
  });

  it('WS refetch uses setTimeout with 500ms debounce', () => {
    const source = read('views', 'KalshiPortfolioView.tsx');
    expect(source).toMatch(/setTimeout\(/);
    expect(source).toMatch(/500/);
  });

  it('WS refetch timer is cleared on cleanup and on every new summary event', () => {
    const source = read('views', 'KalshiPortfolioView.tsx');
    const clearCount = (source.match(/clearTimeout\(wsRefetchTimerRef\.current\)/g) || []).length;
    // Should appear at least twice: once before setting new timer, once in cleanup
    expect(clearCount).toBeGreaterThanOrEqual(2);
  });

  it('summary guard prevents refetch when summary is null/undefined', () => {
    const source = read('views', 'KalshiPortfolioView.tsx');
    expect(source).toMatch(/if \(!summary\) return/);
  });
});
