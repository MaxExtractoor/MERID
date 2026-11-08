# MERID React Dashboard

The operator console uses React 18, TypeScript, Vite, Tailwind CSS, and Zustand. Work in this directory; do not scaffold another application or install a second UI stack.

## Development and verification

```bash
npm ci
npm run dev
npm run type-check
npm test -- --runInBand
npm run lint
npm run build
```

Vite listens on port 5173 and proxies `/api` and `/ws` to the existing backend on port 8011. `VITE_API_BASE` supports separate deployments; same-origin requests are the default. Starting Vite does not start the backend. Do not start or restart the production trading process just to test UI changes.

The production application is `web/main_15m_lean.py`, launched through `start_15m.ps1`. `web/main.py`, the old Streamlit dashboard instructions, and `web/api/sidebar_config.py` do not describe the active seven-view console.

## Navigation and ownership

| View | Operator purpose |
| --- | --- |
| Agent Wall | Five-asset fleet overview and current decisions |
| Mission Control | Distance-readable runtime, health, and lane monitoring |
| Agent Detail | Selected asset, decisions, provenance, and lane detail |
| Terminal | Market inspection, open orders, and execution records |
| Portfolio | Positions, fills, and backend-reported account results |
| Risk | Exposure, limits, kill switch, and runtime entry controls |
| System | Service health, freshness, and operational diagnostics |

`src/types/views.ts`, `src/App.tsx`, and `src/components/Sidebar.tsx` define the active navigation. Do not restore retired screens merely because historical docs or tests reference them.

- `src/agents/api.ts`: typed backend adapters and authenticated requests.
- `src/agents/session.ts`: local operator session lifecycle.
- `src/agents/useAgentWall.ts`: fleet telemetry and independent source health.
- `src/store/index.ts`: shared portfolio, risk, and system state.
- `src/hooks`: shared UI behavior and lifecycle helpers.
- `src/components` and `src/ui`: reusable presentation and interaction primitives.
- `src/views`: the seven operator workflows.

## Canonical backend contracts

Use `/api/v1/kalshi-grid/agents`, `/summary`, and `/decision-feed` for fleet telemetry; `/api/v1/kalshi/{balance,positions,orders,fills,pnl,risk,kill-switch}` for account state; and `/api/v1/live-runtime-state/` for entry authorization state. Health endpoints answer different questions: `/api/v1/health` is liveness, `/api/v1/ready` is startup/loop/safety readiness, and `/api/v1/unified-health` is diagnostics. API readiness does not authorize a trade.

Never interpret an unavailable source as an empty account, zero risk, or healthy execution. Retained snapshots must remain distinguishable from fresh data. Live venue mode and permission to submit entries are separate concepts: a halted live account is not a paper account. The backend remains authoritative for all trading gates and PnL; UI controls must not bypass its state machine.

Order quantities may be fractional centi-contracts. Order size, filled quantity, and remaining quantity are distinct fields. Prices must refer to the held/order side, not unconditionally the YES leg. Currency labels must distinguish dollars from cents.

## Browser-test safety

The historical `e2e/*.spec.ts` suites include retired view names and controls. They are not proof that the current seven-view console works. Do not run mutation-capable browser suites against the production backend. Isolate network traffic with Playwright routes or a dedicated non-production test service; mocks validate UI behavior, not real venue integration. Unit tests use jsdom and mocked API boundaries.

## Audit references

See `UI_WIRING_AUDIT.md` for the current audit scope, verified fixes, remaining risks, and the primary-source research used to select solutions. Historical reports should not be treated as current runtime evidence.
