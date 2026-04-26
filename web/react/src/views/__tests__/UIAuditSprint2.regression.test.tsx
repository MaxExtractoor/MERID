/**
 * UIAuditSprint2.regression.test.tsx
 *
 * Regression tests covering all 16 fixes from the UI/UX audit sprint 2.
 *
 * FIX-01  ConfirmModal — checklist renders ABOVE action buttons; autoFocus removed when incomplete
 * FIX-02  EmergencyStopButton — canonical component created, forwardRef, ConfirmModal-based
 * FIX-03  modeColors.ts — single source of truth; LIVE=red in ModeBadge, GateStrip, Sidebar, TopBar
 * FIX-04  TopBar search — dead <input> replaced with button wired to CommandPalette
 * FIX-05  OperatorDashboard — ExecutionGateStrip added above TradingHaltBanner
 * FIX-06  OperatorDashboard — kill-switch toggle split into action-first labelled buttons
 * FIX-07  KalshiRiskScreen — catch + ackError surface on acknowledge handlers
 * FIX-08  KalshiRiskScreen — type=button on Ack/AckAll; pagination cap 50; dynamic border colors
 * FIX-09  Overview — kill-switch status card rendered above fold when grid running
 * FIX-10  Ctrl+Shift+K — focus-guard skips INPUT/TEXTAREA/SELECT in KalshiGridView
 * FIX-11  No window.confirm/alert/prompt — KillSwitchView + KalshiGridView fully converted
 * FIX-12  TopBar P&L — compact xs fallback added
 * FIX-13  Overview KalshiBalanceHero — hardcoded Live badge replaced with useKalshiMode
 * FIX-14  Stop Grid button — bg-red-600 replaced with bg-slate-600
 * FIX-15  KillSwitchView reset — alert() replaced with resetError inline state
 * FIX-16  KillSwitchView cycleMode — window.confirm replaced with ConfirmModal + blockConfirm state
 *
 * Strategy: static source analysis (regex) + targeted RTL component tests.
 */

import * as fs from 'fs';
import * as path from 'path';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

// ─── Path helpers ──────────────────────────────────────────────────────────────
const SRC = path.resolve(__dirname, '../..');
const src = (...parts: string[]) => path.join(SRC, ...parts);
function read(...parts: string[]): string {
  return fs.readFileSync(src(...parts), 'utf-8');
}

// ─── Shared mocks ──────────────────────────────────────────────────────────────
jest.mock('../../hooks/useApiData', () => ({
  __esModule: true,
  useApiData: jest.fn(() => ({ data: null, loading: false, error: null, refetch: jest.fn(), lastUpdated: null })),
}));

jest.mock('../../hooks/useKalshiRiskStream', () => ({
  __esModule: true,
  useKalshiRiskStream: jest.fn(() => ({ alerts: [], connected: false })),
}));

jest.mock('../../context/KalshiModeContext', () => ({
  __esModule: true,
  useKalshiMode: jest.fn(() => ({ isLive: false, data: { mode: 'paper', is_live: false }, loading: false })),
  KalshiModeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

jest.mock('../../config/featureFlags', () => ({
  __esModule: true,
  useFeatureFlags: jest.fn(() => ({ kalshiOnly: false })),
}));

jest.mock('../../api/auth', () => ({
  authHeaders: jest.fn(() => ({ 'Content-Type': 'application/json' })),
}));

// Mock useNetworkStatusProvider
jest.mock('../../hooks/useNetworkStatusProvider', () => ({
  useNetworkStatus: () => ({ isOnline: true, backendReachable: true }),
  NetworkProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
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

// Heavy sub-component stubs
jest.mock('../../components/ExecutionGateStrip',         () => ({ __esModule: true, default: () => <div data-testid="execution-gate-strip" /> }));
jest.mock('../../components/CollapsibleConsole',         () => ({ __esModule: true, default: () => <div data-testid="collapsible-console" /> }));
jest.mock('../../components/AgentActivityPanel',         () => ({ __esModule: true, default: () => <div data-testid="agent-activity" /> }));
jest.mock('../../components/KalshiPnlChart',             () => ({ __esModule: true, default: () => <div data-testid="pnl-chart" /> }));
jest.mock('../../components/ConnectionStatusIndicator',  () => ({ __esModule: true, default: () => <div data-testid="conn-status" /> }));
jest.mock('../../components/LiveNotifications',          () => ({ __esModule: true, default: () => <div data-testid="live-notif" /> }));
jest.mock('../../components/KalshiModeBadge',            () => ({ __esModule: true, default: () => <div data-testid="mode-badge" /> }));
jest.mock('../../components/ModeSafetyPanel',            () => ({ __esModule: true, default: () => <div data-testid="mode-safety" /> }));
jest.mock('../../components/PnLConsistencyWidget',       () => ({ __esModule: true, default: () => <div data-testid="pnl-consistency" /> }));
jest.mock('../../components/SessionLogPanel',            () => ({ __esModule: true, default: () => <div data-testid="session-log" /> }));
jest.mock('../../components/TradingHaltBanner',          () => ({ __esModule: true, default: () => <div data-testid="trading-halt-banner" /> }));
jest.mock('../../components/ErrorAlert',                 () => ({ __esModule: true, default: ({ message }: { message: string }) => <div data-testid="error-alert">{message}</div> }));
jest.mock('../../hooks/useDashboard', () => ({
  SystemHealthCard:   () => <div data-testid="system-health-card" />,
  KalshiHealthCard:   () => <div data-testid="kalshi-health-card" />,
  AgentStatusCard:    () => <div data-testid="agent-status-card" />,
  RiskProtectionCard: () => <div data-testid="risk-protection-card" />,
}));
jest.mock('../../theme', () => ({
  useTheme: () => ({ theme: 'dark', toggleTheme: jest.fn() }),
  ThemeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
jest.mock('../../config/constants', () => ({
  API_BASE_URL: '',
  AUTH_TOKEN_KEY: 'merid-access',
  API_ENDPOINTS: {
    KALSHI_PNL: '/api/v1/kalshi/pnl',
    KALSHI_BALANCE: '/api/v1/kalshi/balance',
    SYSTEM_EXECUTION_GATE: '/api/v1/system/execution-gate',
    KALSHI_RISK: '/api/v1/kalshi/risk',
    KALSHI_GRID_MODE: '/api/v1/kalshi-grid/mode',
    OPERATOR_EMERGENCY_STOP: '/api/v1/operator/emergency-stop',
    OPERATOR_RESET_KILL_SWITCH: '/api/v1/operator/reset-kill-switch',
    KALSHI_CATEGORIES: '/api/v1/kalshi/categories',
    RISK_SUMMARY: '/api/v1/risk/summary',
    RISK_ALERTS: '/api/v1/risk/alerts',
    RISK_ALERT_ACKNOWLEDGE: (id: string) => `/api/v1/risk/alerts/${id}/acknowledge`,
    RISK_ALERTS_ACKNOWLEDGE_ALL: '/api/v1/risk/alerts/acknowledge-all',
    OPERATOR_KILL_SWITCH: '/api/v1/operator/kill-switch',
    OPERATOR_RISK_STATE: '/api/v1/operator/risk-state',
  },
  DEFAULTS: { POLLING_INTERVALS: { FAST_REFRESH: 5000, STANDARD: 30000, SLOW: 60000 }, TIMEOUTS: { DEBOUNCE: 100 } },
  GRID_CELL_STATUS: {},
}));

import React from 'react';

// ══════════════════════════════════════════════════════════════════════════════
// FIX-01 — ConfirmModal layout: checklist ABOVE buttons, no autoFocus bypass
// ══════════════════════════════════════════════════════════════════════════════
describe('FIX-01 — ConfirmModal layout', () => {
  it('checklist items appear BEFORE the confirm button in JSX order', () => {
    const src = read('components', 'ConfirmModal.tsx');
    const checklistIdx = src.indexOf('confirm-modal-checklist');
    const actionsIdx   = src.indexOf('confirm-modal-actions');
    expect(checklistIdx).toBeGreaterThan(0);
    expect(actionsIdx).toBeGreaterThan(0);
    expect(checklistIdx).toBeLessThan(actionsIdx);
  });

  it('autoFocus is conditional on checklistItems.length === 0', () => {
    const src = read('components', 'ConfirmModal.tsx');
    expect(src).toMatch(/autoFocus=\{checklistItems\.length === 0\}/);
  });

  it('confirm button does NOT have unconditional autoFocus', () => {
    const src = read('components', 'ConfirmModal.tsx');
    expect(src).not.toMatch(/autoFocus(?!=\{checklistItems)/);
  });

  it('RTL: checklist label DOM position is before confirm button DOM position', async () => {
    const { ConfirmModal } = await import('../../components/ConfirmModal');
    render(
      <ConfirmModal
        isOpen
        title="Test"
        message="Are you sure?"
        confirmText="Confirm"
        cancelText="Cancel"
        confirmVariant="danger"
        onConfirm={jest.fn()}
        onCancel={jest.fn()}
        checklistItems={[{ id: 'chk1', label: 'I confirm this action' }]}
      />
    );
    const all = document.body.querySelectorAll('*');
    const nodes = Array.from(all);
    const checkboxIdx = nodes.findIndex(n => n.getAttribute('type') === 'checkbox');
    const confirmIdx  = nodes.findIndex(n => n.textContent === 'Confirm' && n.tagName === 'BUTTON');
    expect(checkboxIdx).toBeGreaterThan(-1);
    expect(confirmIdx).toBeGreaterThan(-1);
    expect(checkboxIdx).toBeLessThan(confirmIdx);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// FIX-02 — EmergencyStopButton component
// ══════════════════════════════════════════════════════════════════════════════
describe('FIX-02 — EmergencyStopButton component', () => {
  it('EmergencyStopButton.tsx exists', () => {
    expect(() => read('components', 'EmergencyStopButton.tsx')).not.toThrow();
  });

  it('uses forwardRef', () => {
    const src = read('components', 'EmergencyStopButton.tsx');
    expect(src).toMatch(/forwardRef/);
  });

  it('uses ConfirmModal, not window.confirm (excluding comments)', () => {
    const raw = read('components', 'EmergencyStopButton.tsx');
    // Strip block comments (/** ... */) so comment text mentioning window.confirm doesn't false-positive
    const src = raw.replace(/\/\*[\s\S]*?\*\//g, '');
    expect(src).toMatch(/import.*ConfirmModal/);
    expect(src).not.toMatch(/window\.confirm\s*\(/);
  });

  it('posts to OPERATOR_EMERGENCY_STOP', () => {
    const src = read('components', 'EmergencyStopButton.tsx');
    expect(src).toMatch(/OPERATOR_EMERGENCY_STOP/);
    expect(src).toMatch(/method.*POST|POST.*method/);
  });

  it('has inline error state for failed POSTs', () => {
    const src = read('components', 'EmergencyStopButton.tsx');
    expect(src).toMatch(/setError/);
    expect(src).toMatch(/catch.*err|err.*catch/s);
  });

  it('RTL: opens ConfirmModal on button click', async () => {
    const EmergencyStopButton = (await import('../../components/EmergencyStopButton')).default;
    render(<EmergencyStopButton />);
    const triggerBtn = screen.getByRole('button', { name: 'Emergency Stop' });
    fireEvent.click(triggerBtn);
    // After click, the ConfirmModal confirm button "Stop All Trading" should appear
    const confirmBtn = await screen.findByRole('button', { name: 'Stop All Trading' });
    expect(confirmBtn).toBeInTheDocument();
  });

  it('RTL: compact variant renders "KILL" label', async () => {
    const { default: EmergencyStopButton } = await import('../../components/EmergencyStopButton');
    const { unmount } = render(<EmergencyStopButton compact />);
    expect(screen.getByText('KILL')).toBeInTheDocument();
    unmount();
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// FIX-03 — modeColors.ts token file + LIVE=red everywhere
// ══════════════════════════════════════════════════════════════════════════════
describe('FIX-03 — modeColors.ts single source of truth', () => {
  it('modeColors.ts exists and exports MODE_COLORS', () => {
    const src = read('config', 'modeColors.ts');
    expect(src).toMatch(/export const MODE_COLORS/);
  });

  it('live badge uses red, not green', () => {
    const src = read('config', 'modeColors.ts');
    const liveBlock = src.slice(src.indexOf('live:'), src.indexOf('paper:'));
    expect(liveBlock).toMatch(/red/);
    expect(liveBlock).not.toMatch(/green/);
  });

  it('paper badge uses amber, not green', () => {
    const src = read('config', 'modeColors.ts');
    const paperBlock = src.slice(src.indexOf('paper:'), src.indexOf('shadow:'));
    expect(paperBlock).toMatch(/amber/);
    expect(paperBlock).not.toMatch(/green/);
  });

  it('exports resolveModeKey function', () => {
    const src = read('config', 'modeColors.ts');
    expect(src).toMatch(/export function resolveModeKey/);
  });

  it('resolveModeKey(undefined, true) returns "live"', async () => {
    const { resolveModeKey } = await import('../../config/modeColors');
    expect(resolveModeKey(undefined, true)).toBe('live');
  });

  it('resolveModeKey("paper", false) returns "paper"', async () => {
    const { resolveModeKey } = await import('../../config/modeColors');
    expect(resolveModeKey('paper', false)).toBe('paper');
  });

  it('resolveModeKey("shadow", false) returns "shadow"', async () => {
    const { resolveModeKey } = await import('../../config/modeColors');
    expect(resolveModeKey('shadow', false)).toBe('shadow');
  });

  it('KalshiModeBadge.tsx imports MODE_COLORS from modeColors', () => {
    const src = read('components', 'KalshiModeBadge.tsx');
    expect(src).toMatch(/import.*MODE_COLORS.*modeColors/);
  });

  it('KalshiModeBadge.tsx does NOT hardcode bg-green for live', () => {
    const src = read('components', 'KalshiModeBadge.tsx');
    expect(src).not.toMatch(/bg-green-\d+.*LIVE|LIVE.*bg-green-\d+/);
  });

  it('ExecutionGateStrip.tsx imports MODE_COLORS', () => {
    const src = read('components', 'ExecutionGateStrip.tsx');
    expect(src).toMatch(/import.*MODE_COLORS.*modeColors/);
  });

  it('Sidebar.tsx imports MODE_COLORS', () => {
    const src = read('components', 'Sidebar.tsx');
    expect(src).toMatch(/import.*MODE_COLORS.*modeColors/);
  });

  it('TopBar.tsx imports MODE_COLORS', () => {
    const src = read('components', 'TopBar.tsx');
    expect(src).toMatch(/import.*MODE_COLORS.*modeColors/);
  });

  it('TopBar.tsx does NOT hardcode the old red/amber inline class strings for mode badge', () => {
    const src = read('components', 'TopBar.tsx');
    expect(src).not.toMatch(/from-red-500\/20.*to-rose-500\/20.*border-red-400/);
    expect(src).not.toMatch(/from-amber-500\/20.*to-yellow-500\/20.*border-amber-400/);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// FIX-04 — TopBar search wired to CommandPalette
// ══════════════════════════════════════════════════════════════════════════════
describe('FIX-04 — TopBar search opens CommandPalette', () => {
  it('TopBar.tsx has no <input> for global-search', () => {
    const src = read('components', 'TopBar.tsx');
    expect(src).not.toMatch(/id="global-search"/);
  });

  it('TopBar.tsx has onOpenSearch prop', () => {
    const src = read('components', 'TopBar.tsx');
    expect(src).toMatch(/onOpenSearch/);
  });

  it('search element is now a <button>, not an <input>', () => {
    const src = read('components', 'TopBar.tsx');
    expect(src).toMatch(/onClick=\{onOpenSearch\}/);
  });

  it('search button shows Ctrl K kbd shortcut hint', () => {
    const src = read('components', 'TopBar.tsx');
    expect(src).toMatch(/Ctrl K|Ctrl\+K/);
  });

  it('CommandPalette.tsx exports onOpen prop', () => {
    const src = read('components', 'CommandPalette.tsx');
    expect(src).toMatch(/onOpen\?/);
  });

  it('App.tsx passes onOpenSearch to TopBar', () => {
    const src = read('App.tsx');
    expect(src).toMatch(/onOpenSearch/);
  });

  it('App.tsx has openPaletteRef wiring CommandPalette → TopBar', () => {
    const src = read('App.tsx');
    expect(src).toMatch(/openPaletteRef/);
    expect(src).toMatch(/onOpen.*openPaletteRef|openPaletteRef.*onOpen/s);
  });

  it('RTL: TopBar calls onOpenSearch when search button is clicked', async () => {
    const TopBar = (await import('../../components/TopBar')).default;
    const onOpenSearch = jest.fn();
    render(<TopBar onMenuClick={jest.fn()} onOpenSearch={onOpenSearch} />);
    const btn = screen.getByRole('button', { name: /Search symbols/i });
    fireEvent.click(btn);
    expect(onOpenSearch).toHaveBeenCalledTimes(1);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// FIX-05 — ExecutionGateStrip in OperatorDashboard
// ══════════════════════════════════════════════════════════════════════════════
describe('FIX-05 — ExecutionGateStrip added to OperatorDashboard', () => {
  it('OperatorDashboard.tsx imports ExecutionGateStrip', () => {
    const src = read('views', 'OperatorDashboard.tsx');
    expect(src).toMatch(/import ExecutionGateStrip/);
  });

  it('ExecutionGateStrip renders before TradingHaltBanner in JSX order', () => {
    const src = read('views', 'OperatorDashboard.tsx');
    const gateIdx  = src.indexOf('<ExecutionGateStrip');
    const haltIdx  = src.indexOf('<TradingHaltBanner');
    expect(gateIdx).toBeGreaterThan(0);
    expect(haltIdx).toBeGreaterThan(0);
    expect(gateIdx).toBeLessThan(haltIdx);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// FIX-06 — OperatorDashboard kill-switch toggle: action-first labels
// ══════════════════════════════════════════════════════════════════════════════
describe('FIX-06 — OperatorDashboard kill-switch action-first labelling', () => {
  it('has "Activate Kill Switch" button label', () => {
    const src = read('views', 'OperatorDashboard.tsx');
    expect(src).toMatch(/Activate Kill Switch/);
  });

  it('has "Deactivate Kill Switch" button label', () => {
    const src = read('views', 'OperatorDashboard.tsx');
    expect(src).toMatch(/Deactivate Kill Switch/);
  });

  it('does NOT use the ambiguous dual-state label "Execution Enabled"', () => {
    const src = read('views', 'OperatorDashboard.tsx');
    expect(src).not.toMatch(/Execution Enabled/);
  });

  it('Deactivate button uses amber styling (not green)', () => {
    const src = read('views', 'OperatorDashboard.tsx');
    const deactivateBlock = src.slice(
      src.indexOf('Deactivate Kill Switch') - 300,
      src.indexOf('Deactivate Kill Switch') + 50
    );
    expect(deactivateBlock).toMatch(/amber/);
    expect(deactivateBlock).not.toMatch(/bg-green/);
  });

  it('Activate button uses red styling', () => {
    const src = read('views', 'OperatorDashboard.tsx');
    const activateBlock = src.slice(
      src.indexOf('Activate Kill Switch') - 300,
      src.indexOf('Activate Kill Switch') + 50
    );
    expect(activateBlock).toMatch(/red/);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// FIX-07 — KalshiRiskScreen: catch + ackError surface on handlers
// ══════════════════════════════════════════════════════════════════════════════
describe('FIX-07 — KalshiRiskScreen acknowledge error handling', () => {
  it('has ackError state variable', () => {
    const src = read('views', 'KalshiRiskScreen.tsx');
    expect(src).toMatch(/ackError/);
    expect(src).toMatch(/setAckError/);
  });

  it('handleAcknowledgeAlert has a catch block', () => {
    const src = read('views', 'KalshiRiskScreen.tsx');
    const fnStart = src.indexOf('handleAcknowledgeAlert');
    const fnBlock = src.slice(fnStart, fnStart + 600);
    expect(fnBlock).toMatch(/catch\s*\(/);
    expect(fnBlock).toMatch(/setAckError/);
  });

  it('handleAcknowledgeAll has a catch block', () => {
    const src = read('views', 'KalshiRiskScreen.tsx');
    const fnStart = src.indexOf('handleAcknowledgeAll');
    const fnBlock = src.slice(fnStart, fnStart + 600);
    expect(fnBlock).toMatch(/catch\s*\(/);
    expect(fnBlock).toMatch(/setAckError/);
  });

  it('handleAcknowledgeAlert checks res.ok and throws on failure', () => {
    const src = read('views', 'KalshiRiskScreen.tsx');
    const fnStart = src.indexOf('handleAcknowledgeAlert');
    const fnBlock = src.slice(fnStart, fnStart + 500);
    expect(fnBlock).toMatch(/res\.ok/);
    expect(fnBlock).toMatch(/throw new Error/);
  });

  it('ackError is rendered in the JSX (dismiss button present)', () => {
    const src = read('views', 'KalshiRiskScreen.tsx');
    const errIdx = src.indexOf('{ackError &&');
    expect(errIdx).toBeGreaterThan(0);
    // The dismissal button sets ackError to null
    const block = src.slice(errIdx, errIdx + 300);
    expect(block).toMatch(/setAckError\(null\)/);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// FIX-08 — KalshiRiskScreen: type=button, pagination, dynamic borders
// ══════════════════════════════════════════════════════════════════════════════
describe('FIX-08 — KalshiRiskScreen button/pagination/border fixes', () => {
  it('Acknowledge All button has type="button"', () => {
    const src = read('views', 'KalshiRiskScreen.tsx');
    // type="button" appears on the button immediately wrapping handleAcknowledgeAll
    const ackStart = src.indexOf('onClick={handleAcknowledgeAll}');
    const surrounding = src.slice(ackStart - 200, ackStart + 50);
    expect(surrounding).toMatch(/type="button"/);
  });

  it('individual Ack button has type="button"', () => {
    const src = read('views', 'KalshiRiskScreen.tsx');
    // type="button" appears on the button immediately wrapping handleAcknowledgeAlert
    const ackStart = src.indexOf('onClick={() => handleAcknowledgeAlert(');
    const surrounding = src.slice(ackStart - 200, ackStart + 50);
    expect(surrounding).toMatch(/type="button"/);
  });

  it('alerts are sliced to 50 for default display', () => {
    const src = read('views', 'KalshiRiskScreen.tsx');
    expect(src).toMatch(/slice\(0,\s*50\)/);
  });

  it('showAllAlerts state variable is present', () => {
    const src = read('views', 'KalshiRiskScreen.tsx');
    expect(src).toMatch(/showAllAlerts/);
    expect(src).toMatch(/setShowAllAlerts/);
  });

  it('show-all button is only rendered when total > 50', () => {
    const src = read('views', 'KalshiRiskScreen.tsx');
    expect(src).toMatch(/allAlerts\.length > 50/);
  });

  it('Position Risk card border is dynamic (not hardcoded green)', () => {
    const src = read('views', 'KalshiRiskScreen.tsx');
    // The old hardcoded "border-green-500" for Position Risk must be gone
    const posRiskSection = src.slice(src.indexOf('Position Risk'), src.indexOf('Leverage'));
    expect(posRiskSection).not.toMatch(/border-l-4 border-green-500/);
    expect(posRiskSection).toMatch(/border-red-500|border-yellow-500|border-green-500/); // dynamic
  });

  it('Leverage card border is dynamic (not hardcoded green)', () => {
    const src = read('views', 'KalshiRiskScreen.tsx');
    // The dynamic border is on the <div> that wraps the Leverage label.
    // Search for the template literal containing leverage_ratio border logic.
    expect(src).toMatch(/leverage_ratio.*border-red-500|border-red-500.*leverage_ratio/s);
    // The old static border-green-500 must not appear next to leverage_ratio
    expect(src).not.toMatch(/leverage_ratio[^}]{0,20}border-l-4 border-green-500/);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// FIX-09 — Overview: kill-switch card above fold when grid running
// ══════════════════════════════════════════════════════════════════════════════
describe('FIX-09 — Overview kill-switch status above fold', () => {
  it('kill-switch status block renders BEFORE the <details> system controls', () => {
    const src = read('views', 'Overview.tsx');
    const statusBlock = src.indexOf('Kill Switch ACTIVE');
    const detailsIdx  = src.indexOf('<details');
    expect(statusBlock).toBeGreaterThan(0);
    expect(detailsIdx).toBeGreaterThan(0);
    expect(statusBlock).toBeLessThan(detailsIdx);
  });

  it('kill-switch block is gated on gridStatus.running', () => {
    const src = read('views', 'Overview.tsx');
    const runningIdx = src.indexOf('Boolean(gridStatus?.running)');
    const statusIdx  = src.indexOf('Kill Switch ACTIVE');
    // The kill switch block should be after the first gridStatus.running check
    expect(statusIdx).toBeGreaterThan(runningIdx);
  });

  it('both ACTIVE and Clear states are represented', () => {
    const src = read('views', 'Overview.tsx');
    expect(src).toMatch(/Kill Switch ACTIVE/);
    expect(src).toMatch(/Kill Switch Clear/);
  });

  it('kill reason is displayed inline when present', () => {
    const src = read('views', 'Overview.tsx');
    expect(src).toMatch(/kill_reason.*reason|reason.*kill_reason/s);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// FIX-10 — Ctrl+Shift+K focus-guard skips form fields
// ══════════════════════════════════════════════════════════════════════════════
describe('FIX-10 — Ctrl+Shift+K focus-guard in KalshiGridView', () => {
  it('keyboard handler checks active element tagName', () => {
    const src = read('views', 'KalshiGridView.tsx');
    expect(src).toMatch(/tagName/);
    expect(src).toMatch(/INPUT/);
    expect(src).toMatch(/TEXTAREA/);
    expect(src).toMatch(/SELECT/);
  });

  it('focus-guard uses return (early exit) when focused on form field', () => {
    const src = read('views', 'KalshiGridView.tsx');
    const guardSection = src.slice(src.indexOf('INPUT'), src.indexOf('INPUT') + 200);
    expect(guardSection).toMatch(/return/);
  });

  it('Ctrl+Shift+K binding is registered via addEventListener("keydown")', () => {
    const src = read('views', 'KalshiGridView.tsx');
    expect(src).toMatch(/addEventListener\(['"]keydown['"]/);
    expect(src).toMatch(/e\.ctrlKey.*e\.shiftKey|e\.shiftKey.*e\.ctrlKey/);
    expect(src).toMatch(/e\.key === 'K'/);
  });

  it('keyboard handler cleans up via removeEventListener', () => {
    const src = read('views', 'KalshiGridView.tsx');
    expect(src).toMatch(/removeEventListener\(['"]keydown['"]/);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// FIX-11 — No window.confirm/alert/prompt in safety-critical components
// ══════════════════════════════════════════════════════════════════════════════
describe('FIX-11 — window.confirm/alert/prompt eliminated from safety paths', () => {
  const SAFETY_FILES: [string, string][] = [
    ['views', 'KillSwitchView.tsx'],
    ['views', 'KalshiGridView.tsx'],
    ['views', 'Overview.tsx'],
    ['components', 'TradingHaltBanner.tsx'],
  ];

  it.each(SAFETY_FILES)('%s/%s has no window.confirm()', (dir, file) => {
    expect(read(dir, file)).not.toMatch(/window\.confirm\s*\(/);
  });

  it.each(SAFETY_FILES)('%s/%s has no window.alert()', (dir, file) => {
    expect(read(dir, file)).not.toMatch(/window\.alert\s*\(/);
  });

  it.each(SAFETY_FILES)('%s/%s has no window.prompt()', (dir, file) => {
    expect(read(dir, file)).not.toMatch(/window\.prompt\s*\(/);
  });

  it.each(SAFETY_FILES)('%s/%s has no bare confirm() call', (dir, file) => {
    // Exclude string literals containing "confirm" (e.g. button text)
    const content = read(dir, file).replace(/"[^"]*confirm[^"]*"/gi, '""').replace(/'[^']*confirm[^']*'/gi, "''");
    expect(content).not.toMatch(/(?<![.\w])confirm\s*\(/);
  });

  it('KillSwitchView has EmergencyStopButton for the stop action', () => {
    const src = read('views', 'KillSwitchView.tsx');
    expect(src).toMatch(/import EmergencyStopButton/);
    expect(src).toMatch(/<EmergencyStopButton/);
  });

  it('KalshiGridView has EmergencyStopButton for the kill action', () => {
    const src = read('views', 'KalshiGridView.tsx');
    expect(src).toMatch(/import EmergencyStopButton/);
    expect(src).toMatch(/<EmergencyStopButton/);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// FIX-12 — TopBar P&L compact fallback for small screens
// ══════════════════════════════════════════════════════════════════════════════
describe('FIX-12 — TopBar P&L compact fallback', () => {
  it('TopBar.tsx has an sm:hidden compact P&L element', () => {
    const src = read('components', 'TopBar.tsx');
    expect(src).toMatch(/sm:hidden/);
  });

  it('TopBar.tsx has a hidden sm:flex full P&L panel', () => {
    const src = read('components', 'TopBar.tsx');
    expect(src).toMatch(/hidden sm:flex/);
  });

  it('compact element renders daily P&L value', () => {
    const src = read('components', 'TopBar.tsx');
    const compactBlock = src.slice(src.indexOf('sm:hidden'), src.indexOf('hidden sm:flex'));
    expect(compactBlock).toMatch(/dailyPnl/);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// FIX-13 — Overview hardcoded Live badge replaced
// ══════════════════════════════════════════════════════════════════════════════
describe('FIX-13 — Overview KalshiBalanceHero uses useKalshiMode', () => {
  it('Overview.tsx imports useKalshiMode', () => {
    const src = read('views', 'Overview.tsx');
    expect(src).toMatch(/import.*useKalshiMode/);
  });

  it('Overview.tsx imports MODE_COLORS and resolveModeKey', () => {
    const src = read('views', 'Overview.tsx');
    expect(src).toMatch(/import.*MODE_COLORS.*resolveModeKey|import.*resolveModeKey.*MODE_COLORS/);
  });

  it('Overview.tsx does NOT contain hardcoded "text-emerald-400" + "Live" badge', () => {
    const src = read('views', 'Overview.tsx');
    // The specific hardcoded combination that was replaced
    expect(src).not.toMatch(/text-emerald-400.*animate-pulse.*\/ Live/s);
  });

  it('KalshiBalanceLiveIndicator function is defined', () => {
    const src = read('views', 'Overview.tsx');
    expect(src).toMatch(/function KalshiBalanceLiveIndicator/);
  });

  it('KalshiBalanceLiveIndicator uses colors.dot and colors.text from MODE_COLORS', () => {
    const src = read('views', 'Overview.tsx');
    const fnStart = src.indexOf('function KalshiBalanceLiveIndicator');
    const fnBlock = src.slice(fnStart, fnStart + 700);
    expect(fnBlock).toMatch(/colors\.dot/);
    expect(fnBlock).toMatch(/colors\.text/);
  });

  it('<KalshiBalanceLiveIndicator /> is rendered inside the balance hero', () => {
    const src = read('views', 'Overview.tsx');
    expect(src).toMatch(/<KalshiBalanceLiveIndicator/);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// FIX-14 — Stop Grid button uses slate-600 not red-600
// ══════════════════════════════════════════════════════════════════════════════
describe('FIX-14 — Stop Grid button color standardised', () => {
  it('KalshiGridView Stop Grid uses bg-slate-600', () => {
    const src = read('views', 'KalshiGridView.tsx');
    const stopIdx = src.indexOf('Stop Grid');
    const btnBlock = src.slice(stopIdx - 400, stopIdx + 100);
    expect(btnBlock).toMatch(/bg-slate-600/);
    expect(btnBlock).not.toMatch(/bg-red-600/);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// FIX-15 — KillSwitchView reset: alert() → inline resetError state
// ══════════════════════════════════════════════════════════════════════════════
describe('FIX-15 — KillSwitchView handleResetKillSwitch inline error', () => {
  it('resetError state variable is declared', () => {
    const src = read('views', 'KillSwitchView.tsx');
    expect(src).toMatch(/resetError/);
    expect(src).toMatch(/setResetError/);
  });

  it('handleResetKillSwitch has a catch block that calls setResetError', () => {
    const src = read('views', 'KillSwitchView.tsx');
    const fnStart = src.indexOf('handleResetKillSwitch');
    const fnBlock = src.slice(fnStart, fnStart + 600);
    expect(fnBlock).toMatch(/catch\s*\(/);
    expect(fnBlock).toMatch(/setResetError/);
  });

  it('resetError is rendered inline with a dismiss button', () => {
    const src = read('views', 'KillSwitchView.tsx');
    const errIdx = src.indexOf('{resetError &&');
    expect(errIdx).toBeGreaterThan(0);
    const block = src.slice(errIdx, errIdx + 300);
    expect(block).toMatch(/setResetError\(null\)/);
  });

  it('handleResetKillSwitch does NOT call alert()', () => {
    const src = read('views', 'KillSwitchView.tsx');
    const fnStart = src.indexOf('handleResetKillSwitch');
    const fnBlock = src.slice(fnStart, fnStart + 700);
    expect(fnBlock).not.toMatch(/alert\s*\(/);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// FIX-16 — KillSwitchView cycleMode: window.confirm → ConfirmModal
// ══════════════════════════════════════════════════════════════════════════════
describe('FIX-16 — KillSwitchView cycleMode uses ConfirmModal', () => {
  it('blockConfirm state variable is declared', () => {
    const src = read('views', 'KillSwitchView.tsx');
    expect(src).toMatch(/blockConfirm/);
    expect(src).toMatch(/setBlockConfirm/);
  });

  it('cycleMode calls setBlockConfirm instead of window.confirm', () => {
    const src = read('views', 'KillSwitchView.tsx');
    const fnStart = src.indexOf('const cycleMode');
    const fnBlock = src.slice(fnStart, fnStart + 500);
    expect(fnBlock).toMatch(/setBlockConfirm/);
    expect(fnBlock).not.toMatch(/window\.confirm\s*\(/);
  });

  it('ConfirmModal for category block is rendered in JSX', () => {
    const src = read('views', 'KillSwitchView.tsx');
    expect(src).toMatch(/isOpen=\{blockConfirm !== null\}/);
  });

  it('block ConfirmModal has confirmVariant="warning"', () => {
    const src = read('views', 'KillSwitchView.tsx');
    const modalStart = src.indexOf('isOpen={blockConfirm !== null}');
    const modalBlock = src.slice(modalStart, modalStart + 400);
    expect(modalBlock).toMatch(/confirmVariant="warning"/);
  });

  it('block ConfirmModal calls cycleMode with confirmed=true on confirm', () => {
    const src = read('views', 'KillSwitchView.tsx');
    const modalStart = src.indexOf('isOpen={blockConfirm !== null}');
    const modalBlock = src.slice(modalStart, modalStart + 500);
    expect(modalBlock).toMatch(/cycleMode\(.*true\)/);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// Cross-cutting: all modified files are non-empty, brace-balanced, conflict-free
// ══════════════════════════════════════════════════════════════════════════════
describe('Cross-cutting — modified files are well-formed', () => {
  const MODIFIED: [string, string, string][] = [
    ['App.tsx',                         '',           'App.tsx'                    ],
    ['components/ConfirmModal.tsx',      'components', 'ConfirmModal.tsx'           ],
    ['components/EmergencyStopButton',   'components', 'EmergencyStopButton.tsx'   ],
    ['components/ExecutionGateStrip',    'components', 'ExecutionGateStrip.tsx'    ],
    ['components/KalshiModeBadge',       'components', 'KalshiModeBadge.tsx'       ],
    ['components/Sidebar.tsx',           'components', 'Sidebar.tsx'               ],
    ['components/TopBar.tsx',            'components', 'TopBar.tsx'                ],
    ['components/CommandPalette.tsx',    'components', 'CommandPalette.tsx'        ],
    ['config/modeColors.ts',             'config',     'modeColors.ts'             ],
    ['views/KalshiGridView.tsx',         'views',      'KalshiGridView.tsx'        ],
    ['views/KalshiRiskScreen.tsx',       'views',      'KalshiRiskScreen.tsx'      ],
    ['views/KillSwitchView.tsx',         'views',      'KillSwitchView.tsx'        ],
    ['views/OperatorDashboard.tsx',      'views',      'OperatorDashboard.tsx'     ],
    ['views/Overview.tsx',               'views',      'Overview.tsx'              ],
  ];

  const readEntry = (dir: string, file: string) =>
    dir === '' ? read(file) : read(dir, file);

  it.each(MODIFIED)('%s is non-empty', (_label, dir, file) => {
    expect(readEntry(dir, file).trim().length).toBeGreaterThan(100);
  });

  it.each(MODIFIED)('%s has no git conflict markers', (_label, dir, file) => {
    const content = readEntry(dir, file);
    expect(content).not.toMatch(/<<<<<<< HEAD/);
    expect(content).not.toMatch(/>>>>>>> /);
    expect(content).not.toMatch(/=======/);
  });

  it.each(MODIFIED)('%s has balanced curly braces (±2 tolerance)', (_label, dir, file) => {
    const content = readEntry(dir, file)
      .replace(/`[^`]*`/gs, '``')
      .replace(/"(?:[^"\\]|\\.)*"/g, '""')
      .replace(/'(?:[^'\\]|\\.)*'/g, "''");
    const opens  = (content.match(/\{/g) ?? []).length;
    const closes = (content.match(/\}/g) ?? []).length;
    expect(Math.abs(opens - closes)).toBeLessThanOrEqual(2);
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// Cross-cutting: ConfirmModal RTL smoke — renders and closes correctly
// ══════════════════════════════════════════════════════════════════════════════
describe('ConfirmModal RTL smoke', () => {
  it('renders title and message', async () => {
    const { ConfirmModal } = await import('../../components/ConfirmModal');
    render(
      <ConfirmModal
        isOpen title="Delete item" message="This is permanent."
        confirmText="Delete" cancelText="Go back"
        confirmVariant="danger" onConfirm={jest.fn()} onCancel={jest.fn()}
      />
    );
    expect(screen.getByText('Delete item')).toBeInTheDocument();
    expect(screen.getByText('This is permanent.')).toBeInTheDocument();
  });

  it('calls onCancel when cancel button is clicked', async () => {
    const { ConfirmModal } = await import('../../components/ConfirmModal');
    const onCancel = jest.fn();
    render(
      <ConfirmModal
        isOpen title="T" message="M"
        confirmText="Yes" cancelText="No"
        confirmVariant="primary" onConfirm={jest.fn()} onCancel={onCancel}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: 'No' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('confirm button is disabled until all checklist items checked', async () => {
    const { ConfirmModal } = await import('../../components/ConfirmModal');
    render(
      <ConfirmModal
        isOpen title="T" message="M"
        confirmText="Confirm" cancelText="Cancel"
        confirmVariant="danger" onConfirm={jest.fn()} onCancel={jest.fn()}
        checklistItems={[
          { id: 'a', label: 'Step A' },
          { id: 'b', label: 'Step B' },
        ]}
      />
    );
    const confirmBtn = screen.getByRole('button', { name: 'Confirm' });
    expect(confirmBtn).toBeDisabled();

    const checkboxes = screen.getAllByRole('checkbox');
    fireEvent.click(checkboxes[0]);
    expect(confirmBtn).toBeDisabled();

    fireEvent.click(checkboxes[1]);
    expect(confirmBtn).not.toBeDisabled();
  });

  it('calls onConfirm when all checklist items checked and confirm clicked', async () => {
    const { ConfirmModal } = await import('../../components/ConfirmModal');
    const onConfirm = jest.fn();
    render(
      <ConfirmModal
        isOpen title="T" message="M"
        confirmText="Go" cancelText="Back"
        confirmVariant="warning" onConfirm={onConfirm} onCancel={jest.fn()}
        checklistItems={[{ id: 'x', label: 'I confirm' }]}
      />
    );
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'Go' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('does not render when isOpen is false', async () => {
    const { ConfirmModal } = await import('../../components/ConfirmModal');
    render(
      <ConfirmModal
        isOpen={false} title="Hidden" message="Hidden"
        confirmText="OK" cancelText="Cancel"
        confirmVariant="primary" onConfirm={jest.fn()} onCancel={jest.fn()}
      />
    );
    expect(screen.queryByText('Hidden')).not.toBeInTheDocument();
  });
});
