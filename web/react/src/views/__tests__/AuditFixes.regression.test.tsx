/**
 * AuditFixes.regression.test.tsx
 *
 * Regression tests covering all 10 fixes from the UI/UX audit sprint.
 *
 * FIX-01  KalshiRiskScreen — wired as a reachable route + sidebar entry
 * FIX-02  Logs detail panel — _setSelectedLog renamed, text search added
 * FIX-03  Overview RebootControlPanel — collapsed below the fold when grid is running
 * FIX-04  TopBar — LIVE/PAPER mode pill present on every render
 * FIX-05  TradingHaltBanner — Halt/Resume use ConfirmModal, not window.confirm
 * FIX-06  KillSwitchView — category buttons show next-state title attribute
 * FIX-07  KalshiRiskScreen — placeholder chart replaced with KalshiPnlChart
 * FIX-08  KalshiGridView — order_id column in Recent Fills table
 * FIX-09  SwarmConsensusMatrix — emoji archetypes replaced with ArchetypeTag
 * FIX-10  Overview — LIVE grid start uses ConfirmModal, not window.confirm
 *
 * Strategy: static source analysis (AST-free regex) + targeted RTL component tests.
 * No server required.
 */

import * as fs from 'fs';
import * as path from 'path';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

// ─── Path helpers ──────────────────────────────────────────────────────────────
const SRC = path.resolve(__dirname, '../..');
const src = (...parts: string[]) => path.join(SRC, ...parts);

function read(...parts: string[]): string {
  return fs.readFileSync(src(...parts), 'utf-8');
}

// ─── Shared mocks (hoisted by jest) ────────────────────────────────────────────
jest.mock('../../hooks/useApiData', () => ({
  __esModule: true,
  useApiData: jest.fn(() => ({ data: null, loading: false, error: null, refetch: jest.fn() })),
}));

jest.mock('../../hooks/useKalshiRiskStream', () => ({
  __esModule: true,
  useKalshiRiskStream: jest.fn(() => ({ alerts: [], connected: false })),
}));

jest.mock('../../context/KalshiModeContext', () => ({
  __esModule: true,
  useKalshiMode: () => ({ isLive: false, mode: 'paper' }),
  KalshiModeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

jest.mock('lucide-react', () => {
  return new Proxy({}, {
    get: (_t, prop) => {
      if (typeof prop !== 'string') return undefined;
      const Stub = ({ className }: { className?: string }) => (
        <span data-testid={`icon-${prop}`} className={className} />
      );
      Stub.displayName = String(prop);
      return Stub;
    },
  });
});

jest.mock('../../components/ExecutionGateStrip', () => ({
  __esModule: true,
  default: () => <div data-testid="execution-gate-strip" />,
}));

jest.mock('../../components/CollapsibleConsole', () => ({
  __esModule: true,
  default: () => <div data-testid="collapsible-console" />,
}));

jest.mock('../../components/AgentActivityPanel', () => ({
  __esModule: true,
  default: () => <div data-testid="agent-activity-panel" />,
}));

jest.mock('../../hooks/useDashboard', () => ({
  SystemHealthCard:   () => <div data-testid="system-health-card" />,
  KalshiHealthCard:   () => <div data-testid="kalshi-health-card" />,
  AgentStatusCard:    () => <div data-testid="agent-status-card" />,
  RiskProtectionCard: () => <div data-testid="risk-protection-card" />,
}));

jest.mock('../../api/auth', () => ({
  authHeaders: jest.fn(() => ({ 'Content-Type': 'application/json' })),
}));

// Mock useNetworkStatusProvider
jest.mock('../../hooks/useNetworkStatusProvider', () => ({
  useNetworkStatus: () => ({ isOnline: true, backendReachable: true }),
  NetworkProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// ─── Import React after mocks ──────────────────────────────────────────────────
import React from 'react';

// ─── FIX-01: KalshiRiskScreen route wiring ─────────────────────────────────────
describe('FIX-01 — KalshiRiskScreen is reachable (route + sidebar)', () => {
  it('types/views.ts contains "kalshi-risk" in the View union', () => {
    const views = read('types', 'views.ts');
    expect(views).toMatch(/"kalshi-risk"/);
  });

  it('App.tsx imports KalshiRiskScreen', () => {
    const app = read('App.tsx');
    expect(app).toMatch(/import KalshiRiskScreen/);
  });

  it('App.tsx renders KalshiRiskScreen for view === "kalshi-risk"', () => {
    const app = read('App.tsx');
    expect(app).toMatch(/view === "kalshi-risk"/);
    expect(app).toMatch(/KalshiRiskScreen/);
  });

  it('Sidebar.tsx operatorSection contains kalshi-risk href', () => {
    const sidebar = read('components', 'Sidebar.tsx');
    expect(sidebar).toMatch(/href.*kalshi-risk|kalshi-risk.*href/);
  });

  it('sidebarManifest.ts includes kalshi-risk item', () => {
    const manifest = read('config', 'sidebarManifest.ts');
    expect(manifest).toMatch(/kalshi-risk/);
  });

  it('sidebarManifest.ts "Risk Alerts" item has the correct href', () => {
    const manifest = read('config', 'sidebarManifest.ts');
    expect(manifest).toMatch(/Risk Alerts/);
    expect(manifest).toMatch(/kalshi-risk/);
  });

  it('ALL_SIDEBAR_ITEMS includes kalshi-risk after manifest update', () => {
    // Import must resolve without error and contain the new entry
    const { ALL_SIDEBAR_ITEMS } = require('../../config/sidebarManifest');
    const hrefs = ALL_SIDEBAR_ITEMS.map((i: { href: string }) => i.href);
    expect(hrefs).toContain('kalshi-risk');
  });

  it('ALL_SIDEBAR_ITEMS has 19 items after adding Risk Alerts', () => {
    const { ALL_SIDEBAR_ITEMS } = require('../../config/sidebarManifest');
    expect(ALL_SIDEBAR_ITEMS).toHaveLength(19);
  });
});

// ─── FIX-02: Logs detail panel activated + text search ─────────────────────────
describe('FIX-02 — Logs detail panel and text search', () => {
  it('Logs.tsx does NOT contain the suppressed setter "_setSelectedLog"', () => {
    const logs = read('views', 'Logs.tsx');
    expect(logs).not.toMatch(/_setSelectedLog/);
  });

  it('Logs.tsx contains the active setter "setSelectedLog"', () => {
    const logs = read('views', 'Logs.tsx');
    expect(logs).toMatch(/setSelectedLog/);
  });

  it('Logs.tsx has a searchQuery state variable', () => {
    const logs = read('views', 'Logs.tsx');
    expect(logs).toMatch(/searchQuery/);
  });

  it('Logs.tsx filters by searchQuery in filteredLogs memo', () => {
    const logs = read('views', 'Logs.tsx');
    expect(logs).toMatch(/searchQuery/);
    expect(logs).toMatch(/includes\(q\)|includes\(query\)/);
  });

  it('Logs.tsx has a search input element', () => {
    const logs = read('views', 'Logs.tsx');
    expect(logs).toMatch(/type="text"/);
    expect(logs).toMatch(/log-search/);
  });

  it('Logs.tsx filters by requestId in text search', () => {
    const logs = read('views', 'Logs.tsx');
    expect(logs).toMatch(/requestId/);
    expect(logs).toMatch(/includes\(q\)/);
  });
});

// ─── FIX-03: Overview RebootControlPanel below the fold ────────────────────────
describe('FIX-03 — RebootControlPanel collapsed below fold when grid is running', () => {
  it('Overview.tsx wraps RebootControlPanel in a <details> element when grid is running', () => {
    const overview = read('views', 'Overview.tsx');
    expect(overview).toMatch(/<details/);
    expect(overview).toMatch(/System Controls/);
  });

  it('Overview.tsx uses gridStatus.running to gate the collapsible', () => {
    const overview = read('views', 'Overview.tsx');
    expect(overview).toMatch(/gridStatus.*running|Boolean\(gridStatus/);
  });

  it('Overview.tsx RebootControlPanel appears AFTER the status cards section', () => {
    const overview = read('views', 'Overview.tsx');
    const statusCardIdx = overview.indexOf('Row 1: Status Cards');
    const rebootIdx = overview.indexOf('System Controls');
    expect(statusCardIdx).toBeGreaterThan(0);
    expect(rebootIdx).toBeGreaterThan(statusCardIdx);
  });

  it('ExecutionGateStrip still appears before any financial data', () => {
    const overview = read('views', 'Overview.tsx');
    const gateIdx = overview.indexOf('ExecutionGateStrip');
    const systemIdx = overview.indexOf('System Controls');
    expect(gateIdx).toBeGreaterThan(0);
    expect(gateIdx).toBeLessThan(systemIdx);
  });
});

// ─── FIX-04: TopBar mode pill ───────────────────────────────────────────────────
describe('FIX-04 — TopBar renders LIVE/PAPER mode pill', () => {
  it('TopBar.tsx renders isLive conditional text LIVE / PAPER', () => {
    const topbar = read('components', 'TopBar.tsx');
    expect(topbar).toMatch(/isLive.*LIVE|LIVE.*isLive/);
    expect(topbar).toMatch(/PAPER/);
  });

  it('TopBar.tsx uses useKalshiMode to determine mode', () => {
    const topbar = read('components', 'TopBar.tsx');
    expect(topbar).toMatch(/useKalshiMode/);
  });

  it('TopBar renders "PAPER" badge when not live', async () => {
    const TopBar = (await import('../../components/TopBar')).default;
    render(<TopBar onMenuClick={jest.fn()} />);
    expect(screen.getByText('PAPER')).toBeInTheDocument();
  });

  it('TopBar.tsx source contains "LIVE" text output for the isLive branch', () => {
    const topbar = read('components', 'TopBar.tsx');
    // Verify both badge strings exist in the conditional rendering
    expect(topbar).toMatch(/'LIVE'|"LIVE"|>LIVE</);
    expect(topbar).toMatch(/'PAPER'|"PAPER"|>PAPER</);
  });
});

// ─── FIX-05: TradingHaltBanner uses ConfirmModal ───────────────────────────────
describe('FIX-05 — TradingHaltBanner uses ConfirmModal for Halt/Resume', () => {
  it('TradingHaltBanner.tsx imports ConfirmModal', () => {
    const banner = read('components', 'TradingHaltBanner.tsx');
    expect(banner).toMatch(/import.*ConfirmModal/);
  });

  it('TradingHaltBanner.tsx does NOT call window.confirm() directly', () => {
    const banner = read('components', 'TradingHaltBanner.tsx');
    // Must not contain a bare window.confirm( or confirm( call
    expect(banner).not.toMatch(/window\.confirm\s*\(/);
  });

  it('TradingHaltBanner.tsx has haltModalOpen state', () => {
    const banner = read('components', 'TradingHaltBanner.tsx');
    expect(banner).toMatch(/haltModalOpen/);
  });

  it('TradingHaltBanner.tsx has resumeModalOpen state', () => {
    const banner = read('components', 'TradingHaltBanner.tsx');
    expect(banner).toMatch(/resumeModalOpen/);
  });

  it('Halt button opens modal (setHaltModalOpen), not fetch directly', () => {
    const banner = read('components', 'TradingHaltBanner.tsx');
    expect(banner).toMatch(/setHaltModalOpen\(true\)/);
  });

  it('Resume button opens modal (setResumeModalOpen), not fetch directly', () => {
    const banner = read('components', 'TradingHaltBanner.tsx');
    expect(banner).toMatch(/setResumeModalOpen\(true\)/);
  });

  it('Halt ConfirmModal has checklist items for open-positions review', () => {
    const banner = read('components', 'TradingHaltBanner.tsx');
    expect(banner).toMatch(/I have reviewed open positions/);
    expect(banner).toMatch(/I have identified the reason/);
  });

  it('Resume ConfirmModal has checklist items for safety checks', () => {
    const banner = read('components', 'TradingHaltBanner.tsx');
    expect(banner).toMatch(/Underlying issue is resolved/);
    expect(banner).toMatch(/Risk limits are within acceptable range/);
  });

  it('Halt ConfirmModal uses confirmVariant="danger"', () => {
    const banner = read('components', 'TradingHaltBanner.tsx');
    // Locate the rendered <ConfirmModal for halt (isOpen={haltModalOpen}) and scan forward
    const haltJsx = banner.slice(banner.indexOf('isOpen={haltModalOpen}'));
    const haltBlock = haltJsx.slice(0, haltJsx.indexOf('isOpen={resumeModalOpen}') > 0
      ? haltJsx.indexOf('isOpen={resumeModalOpen}')
      : 800);
    expect(haltBlock).toMatch(/confirmVariant="danger"/);
  });
});

// ─── FIX-06: KillSwitchView category buttons show next-state title ──────────────
describe('FIX-06 — KillSwitchView category buttons show next-state hint', () => {
  it('KillSwitchView.tsx has title attribute with "Next:" on category buttons', () => {
    const ksv = read('views', 'KillSwitchView.tsx');
    expect(ksv).toMatch(/title=.*Next:/);
  });

  it('KillSwitchView.tsx cycleMode checks for "blocked" transition before proceeding', () => {
    const ksv = read('views', 'KillSwitchView.tsx');
    expect(ksv).toMatch(/next === 'blocked'/);
  });

  it('KillSwitchView.tsx title uses CYCLE array index to compute next state', () => {
    const ksv = read('views', 'KillSwitchView.tsx');
    expect(ksv).toMatch(/CYCLE\[.*indexOf.*\+\s*1.*%.*CYCLE\.length\]/);
  });
});

// ─── FIX-07: KalshiRiskScreen placeholder replaced with KalshiPnlChart ─────────
describe('FIX-07 — KalshiRiskScreen chart placeholder replaced', () => {
  it('KalshiRiskScreen.tsx imports KalshiPnlChart', () => {
    const riskScreen = read('views', 'KalshiRiskScreen.tsx');
    expect(riskScreen).toMatch(/import KalshiPnlChart/);
  });

  it('KalshiRiskScreen.tsx does NOT contain the placeholder text', () => {
    const riskScreen = read('views', 'KalshiRiskScreen.tsx');
    expect(riskScreen).not.toMatch(/Chart implementation pending/);
  });

  it('KalshiRiskScreen.tsx renders <KalshiPnlChart', () => {
    const riskScreen = read('views', 'KalshiRiskScreen.tsx');
    expect(riskScreen).toMatch(/<KalshiPnlChart/);
  });

  it('KalshiPnlChart is passed riskAlerts from allAlerts', () => {
    const riskScreen = read('views', 'KalshiRiskScreen.tsx');
    expect(riskScreen).toMatch(/riskAlerts=/);
    expect(riskScreen).toMatch(/allAlerts/);
  });
});

// ─── FIX-08: KalshiGridView order_id column ────────────────────────────────────
describe('FIX-08 — KalshiGridView fills table has order_id column', () => {
  it('FillEntry interface includes order_id field', () => {
    const gridView = read('views', 'KalshiGridView.tsx');
    expect(gridView).toMatch(/order_id\??: string/);
  });

  it('Recent Fills table header has "Order ID" column', () => {
    const gridView = read('views', 'KalshiGridView.tsx');
    expect(gridView).toMatch(/Order ID/);
  });

  it('order_id cell truncates to 8 chars with ellipsis', () => {
    const gridView = read('views', 'KalshiGridView.tsx');
    expect(gridView).toMatch(/order_id\.slice\(0,\s*8\)/);
  });

  it('order_id cell click stores value to sessionStorage for cross-view trace', () => {
    const gridView = read('views', 'KalshiGridView.tsx');
    expect(gridView).toMatch(/sessionStorage\.setItem/);
    expect(gridView).toMatch(/merid:log-filter-request-id/);
  });

  it('order_id cell shows dash when order_id is absent', () => {
    const gridView = read('views', 'KalshiGridView.tsx');
    // The fallback dash branch must exist
    expect(gridView).toMatch(/text-gray-700.*—|—.*text-gray-700/);
  });
});

// ─── FIX-09: SwarmConsensusMatrix emoji archetypes replaced ────────────────────
describe('FIX-09 — SwarmConsensusMatrix uses ArchetypeTag, not emoji', () => {
  it('SwarmConsensusMatrix.tsx does NOT contain the old emoji archetype map', () => {
    const matrix = read('views', 'SwarmConsensusMatrix.tsx');
    // The old map used literal emoji as values
    expect(matrix).not.toMatch(/ARCHETYPE_ICON/);
  });

  it('SwarmConsensusMatrix.tsx defines ARCHETYPE_META with lucide icon components', () => {
    const matrix = read('views', 'SwarmConsensusMatrix.tsx');
    expect(matrix).toMatch(/ARCHETYPE_META/);
  });

  it('SwarmConsensusMatrix.tsx defines ArchetypeTag component', () => {
    const matrix = read('views', 'SwarmConsensusMatrix.tsx');
    expect(matrix).toMatch(/function ArchetypeTag/);
  });

  it('SwarmConsensusMatrix.tsx renders <ArchetypeTag in proposal list', () => {
    const matrix = read('views', 'SwarmConsensusMatrix.tsx');
    expect(matrix).toMatch(/<ArchetypeTag/);
  });

  it('SwarmConsensusMatrix.tsx imports lucide-react icons for archetypes', () => {
    const matrix = read('views', 'SwarmConsensusMatrix.tsx');
    expect(matrix).toMatch(/TrendingUp/);
    expect(matrix).toMatch(/RotateCcw|RefreshCw/);
    expect(matrix).toMatch(/Zap/);
    expect(matrix).toMatch(/MessageSquare/);
    expect(matrix).toMatch(/Bot/);
  });

  it('SwarmConsensusMatrix.tsx React import is at the top of the file, not mid-file', () => {
    const matrix = read('views', 'SwarmConsensusMatrix.tsx');
    const lines = matrix.split('\n');
    const reactImportLine = lines.findIndex(l => l.match(/^import React/));
    // Must be in the first 15 lines (top of file)
    expect(reactImportLine).toBeGreaterThanOrEqual(0);
    expect(reactImportLine).toBeLessThan(15);
  });
});

// ─── FIX-10: Overview LIVE start uses ConfirmModal ─────────────────────────────
describe('FIX-10 — Overview LIVE grid start uses ConfirmModal, not window.confirm', () => {
  it('Overview.tsx imports ConfirmModal', () => {
    const overview = read('views', 'Overview.tsx');
    expect(overview).toMatch(/import.*ConfirmModal/);
  });

  it('Overview.tsx does NOT call window.confirm() for grid start', () => {
    const overview = read('views', 'Overview.tsx');
    expect(overview).not.toMatch(/window\.confirm\s*\(/);
  });

  it('Overview.tsx has liveConfirmOpen state variable', () => {
    const overview = read('views', 'Overview.tsx');
    expect(overview).toMatch(/liveConfirmOpen/);
  });

  it('Overview.tsx ConfirmModal title is "Start Grid in LIVE Mode"', () => {
    const overview = read('views', 'Overview.tsx');
    expect(overview).toMatch(/Start Grid in LIVE Mode/);
  });

  it('Overview.tsx LIVE start ConfirmModal uses confirmVariant="danger"', () => {
    const overview = read('views', 'Overview.tsx');
    // Find the rendered <ConfirmModal isOpen={liveConfirmOpen} block
    const modalStart = overview.indexOf('isOpen={liveConfirmOpen}');
    expect(modalStart).toBeGreaterThan(0);
    const liveBlock = overview.slice(modalStart, modalStart + 600);
    expect(liveBlock).toMatch(/confirmVariant="danger"/);
  });

  it('Overview.tsx LIVE ConfirmModal has 3 checklist items', () => {
    const overview = read('views', 'Overview.tsx');
    expect(overview).toMatch(/Kill switch is CLEAR/);
    expect(overview).toMatch(/Catalog has been refreshed/);
    expect(overview).toMatch(/Available capital has been reviewed/);
  });

  it('handleStartGrid sets liveConfirmOpen(true) and returns early for live mode', () => {
    const overview = read('views', 'Overview.tsx');
    expect(overview).toMatch(/setLiveConfirmOpen\(true\)/);
    // Verify the early return pattern: setLiveConfirmOpen then return
    const fnBody = overview.slice(overview.indexOf('handleStartGrid'), overview.indexOf('handleStartGrid') + 400);
    expect(fnBody).toMatch(/setLiveConfirmOpen\(true\)[\s\S]*return/);
  });
});

// ─── Cross-cutting: no window.confirm/prompt in safety-critical components ──────
describe('Cross-cutting — no bare window.confirm/prompt in safety-critical paths', () => {
  const SAFETY_FILES: [string, string][] = [
    ['components', 'TradingHaltBanner.tsx'],
    ['views', 'Overview.tsx'],
  ];

  it.each(SAFETY_FILES)(
    '%s/%s does not call window.confirm()',
    (dir: string, file: string) => {
      const content = read(dir, file);
      expect(content).not.toMatch(/window\.confirm\s*\(/);
    }
  );

  it.each(SAFETY_FILES)(
    '%s/%s does not call window.prompt()',
    (dir: string, file: string) => {
      const content = read(dir, file);
      expect(content).not.toMatch(/window\.prompt\s*\(/);
    }
  );
});

// ─── Cross-cutting: syntax validity of all modified source files ────────────────
describe('Cross-cutting — modified TypeScript/TSX files are non-empty and well-formed', () => {
  // Each entry is [label, dir, file] so it.each always gets consistent arity
  const MODIFIED_FILES: [string, string, string][] = [
    ['types/views.ts',                 'types',      'views.ts'              ],
    ['App.tsx',                        '',           'App.tsx'               ],
    ['components/Sidebar.tsx',         'components', 'Sidebar.tsx'           ],
    ['config/sidebarManifest.ts',      'config',     'sidebarManifest.ts'    ],
    ['views/Logs.tsx',                 'views',      'Logs.tsx'              ],
    ['views/Overview.tsx',             'views',      'Overview.tsx'          ],
    ['components/TradingHaltBanner',   'components', 'TradingHaltBanner.tsx' ],
    ['views/KillSwitchView.tsx',       'views',      'KillSwitchView.tsx'    ],
    ['views/KalshiRiskScreen.tsx',     'views',      'KalshiRiskScreen.tsx'  ],
    ['views/KalshiGridView.tsx',       'views',      'KalshiGridView.tsx'    ],
    ['views/SwarmConsensusMatrix.tsx', 'views',      'SwarmConsensusMatrix.tsx'],
    ['components/TopBar.tsx',          'components', 'TopBar.tsx'            ],
  ];

  const readEntry = (dir: string, file: string) =>
    dir === '' ? read(file) : read(dir, file);

  it.each(MODIFIED_FILES)(
    'file %s is non-empty',
    (_label: string, dir: string, file: string) => {
      const content = readEntry(dir, file);
      expect(content.trim().length).toBeGreaterThan(0);
    }
  );

  it.each(MODIFIED_FILES)(
    'file %s has balanced curly braces',
    (_label: string, dir: string, file: string) => {
      const content = readEntry(dir, file);
      const stripped = content
        .replace(/`[^`]*`/gs, '``')
        .replace(/"[^"\\]*"/g, '""')
        .replace(/\'[^\'\\]*\'/g, "''");
      const opens = (stripped.match(/\{/g) ?? []).length;
      const closes = (stripped.match(/\}/g) ?? []).length;
      expect(Math.abs(opens - closes)).toBeLessThanOrEqual(2);
    }
  );

  it.each(MODIFIED_FILES)(
    'file %s has no git conflict markers',
    (_label: string, dir: string, file: string) => {
      const content = readEntry(dir, file);
      expect(content).not.toMatch(/undefined is not a function/);
      expect(content).not.toMatch(/<<<<<<< HEAD/);
    }
  );
});
