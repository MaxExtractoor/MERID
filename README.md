# MERID

Production trading system for Kalshi **15-minute crypto markets** (BTC, ETH, SOL, XRP, DOGE).

- **Entrypoint:** `web.main_15m_lean:app`
- **Startup:** `.\start_15m.ps1` (default port **8011**)
- **Profile:** `kalshi_crypto_15m_v2` (`config/profiles/kalshi_crypto_15m_v2.yaml`)
- **API docs:** `http://localhost:8011/docs`

> Architectural boundaries and forbidden imports are defined in [`ARCHITECTURE_15M.md`](ARCHITECTURE_15M.md). The legacy platform (`web.main_legacy.py`) is quarantined and must not be run for production.

---

## What It Does

```text
SPOT SIGNAL → EDGE vs BOOK → EV GATE → SIZE → EXECUTE → MONITOR → EXIT → SETTLE
```

Each 15-minute cycle, per asset:

1. **Signal** — RTI/CF Benchmarks spot reference + Kalshi orderbook snapshots feed a Bachelier/TWAP probability baseline. Hybrid delta overlays stay disabled unless an OOS calibration artifact approves them.
2. **Edge gate** — Model probability vs. executable book price must clear a per-asset dynamic edge threshold plus a slippage-adjusted cost gate before an intent is created.
3. **Size** — Bounded sizing: `MERID_MAX_CONTRACTS_PER_ORDER`, `MERID_FIXED_EXPOSURE_CAP_USD`, held-price floor (`MERID_MIN_HELD_PRICE_CENTS`).
4. **Execute** — Orders route through the Kalshi order gate with deterministic `client_order_id` idempotency, pre-trade risk checks, and submission-unknown reconciliation.
5. **Monitor** — Position monitor + exit policy track held positions through the window; hard profit lock and stop-candidate paths are enforced.
6. **Settle** — Positions resolve at window close; a post-close grace period prevents phantom-active positions blocking the next window.

## Quick Start

### Prerequisites

- Python 3.11+, Node.js 18+
- Kalshi API credentials (key ID + RSA private key file). Demo environment is the safe default.

### Launch (canonical)

See [`QUICKSTART.md`](QUICKSTART.md) for a safe first run — `start_15m.ps1` is the **live-production launcher** and sets every live-trading latch itself. To run read-only against live data, set `MERID_OBSERVE_ONLY=1` first; to validate configuration without starting, use `-DryRun`.

```powershell
# .env must set:
#   MERID_PROFILE=kalshi_crypto_15m_v2
#   KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PATH
.\start_15m.ps1 -Port 8011 -Profile kalshi_crypto_15m_v2
```

The startup script refuses to double-launch on an already-bound port and derives `MERID_OBSERVE_ONLY` from `auto_execution_mode` in `AGENTS.md` (an explicit `MERID_OBSERVE_ONLY=1` always wins).

### Verify

```powershell
curl http://localhost:8011/api/v1/health | ConvertFrom-Json | Select-Object app, profile
# expected: app=merid_15m_kalshi_crypto, profile=kalshi_crypto_15m_v2

curl http://localhost:8011/api/v1/self-check   # runtime invariant check
```

### React dashboard

```powershell
cd web/react
npm install
npm run dev   # http://localhost:5173
```

## Trading Modes & Safety

A bare `uvicorn` launch without the production flags stays non-live (paper/simulation), and `MERID_OBSERVE_ONLY=1` runs the full live-data stack without ever submitting an order. Production live trading is governed by the durable operator contract in [`AGENTS.md`](AGENTS.md):

- `auto_execution_mode: 1` is standing authorization: on each production restart the system runs the full startup preflight and transitions `STARTING → PREFLIGHT_RUNNING → LIVE_ENTRIES_ENABLED` — no per-run approval token. Any failed check → `LIVE_ENTRIES_HALTED`.
- `start_15m.ps1` is the live launcher: it sets the four entry latches (`TRADING_ENABLED`, `MERID_PM_TRADING_MODE=live`, `MERID_PM_LIVE_ENABLED`, `MERID_ALLOW_LIVE_TRADES`), pins `MERID_KALSHI_ENV=prod` / `KALSHI_USE_DEMO=false`, strips legacy exchange credentials from the process, and fails closed if required safety controls are missing or mismatched.
- Preflight fails closed on test/demo/sandbox/mock/paper/shadow/simulation/replay routing, missing or mismatched credentials, wrong Kalshi endpoint/account, noncanonical order router, disabled reconciliation/trusted-fill/exit protections, unapproved models, or missing calibration artifacts.

Execution-path controls:

- **Kill switches** — global, per-platform, and per-market; fail-closed circuit breaker (`MERID_CIRCUIT_BREAKER_OBSERVE_ONLY=0`)
- **Order gate** — deterministic `client_order_id`, order identity/attempt tracking, idempotent resubmission
- **Drawdown protection** — cycle-level and multi-timeframe drawdown halts
- **Shard collateral** — Kalshi crypto markets live on exchange shard 2; startup preflight and the loop move idle cash onto the trading shard
- **Stale-decision revalidation** — entry economics are rechecked against fresh spot before submission; stale or decayed-edge intents are vetoed

Environment templates live in `config/profiles/env.*.example`. See [`ENV_SETUP.md`](ENV_SETUP.md).

## UI

React dashboard (`web/react`) — 10 wired views:

| Section | Views |
|---------|-------|
| Trading | Dashboard, Kalshi Dashboard (markets), Kalshi Portfolio, Trade |
| Agents | Grid (5-asset agent grid status/control) |
| Analytics | Risk, Calibration |
| Operator | Monitor |
| System | Logs, Settings |

## Repository Layout (production-relevant)

```text
web/main_15m_lean.py              # Canonical FastAPI entrypoint
web/api/                          # kalshi_*, agent_grid, health, loop, paper_session, system endpoints
web/react/                        # Operator dashboard
merid/loop_15m.py                 # 15m trading loop
merid/prediction/agent_grid_15m*  # 15m agent grid (NOT legacy agent_grid)
merid/event_venues/kalshi/        # Client, WS, order router/gate, reconciliation
merid/risk/                       # Kill switches, drawdown, platform kill switch
merid/position_management/        # Position monitor, exit policy, hard profit lock
data/unified_spot_service.py      # Spot price service
config/profiles/kalshi_crypto_15m_v2.yaml
start_15m.ps1                     # Production launcher (port-guarded)
tests/                            # Regression suite incl. 15m invariant/architecture tests
.github/workflows/                # kalshi-15m-ci, safety, paper-gate, data-guards, reconciliation
Dockerfile, docker-compose.yml, supervisor/, prometheus/, grafana/, merid_15m_lean.service
```

## Legacy Code

- `web/main.py` / `web/main.py.legacy`, `merid/loop.py`, `core/orchestrator.py` and related modules are **historical reference only** — forbidden in the 15m stack (boundaries enforced by `tests/test_15m_architectural_separation.py`; see [`ARCHITECTURE_15M.md`](ARCHITECTURE_15M.md)).
- The pre-15m codebase is archived on branch [`archive/main-pre-15m`](../../tree/archive/main-pre-15m). Not a supported execution stack.
- Legacy top-level packages (old `swarm/`, `archive/`, flat `risk/`, `analytics/`, etc.) and unmounted `web/api/*` routers have been retired from the tree; they remain in git history and on the archive branch.

## Testing

```powershell
# Architectural separation (legacy-import firewall)
python -m pytest tests/test_15m_architectural_separation.py -v

# Full suite via make
make test
```

CI gates on `main` include: `kalshi-15m-ci`, `merid-safety-ci`, `kill-switch-ci`, `paper-gate`, `production-data-guards`, `reconciliation-safety`, `red-team-invariants`, `rti-settlement-safety`.

## Documentation

| Doc | Purpose |
|-----|---------|
| [`QUICKSTART.md`](QUICKSTART.md) | Zero-to-running in safe modes + live-launch requirements |
| [`AGENTS.md`](AGENTS.md) | Live-trading operational contract (startup state machine, halt/recovery, invariants) |
| [`ARCHITECTURE_15M.md`](ARCHITECTURE_15M.md) | 15m/legacy boundaries, forbidden imports, safeguards |
| [`RUNBOOK.md`](RUNBOOK.md) | Kill-switch policy, halt conditions, checklists |
| [`ENV_SETUP.md`](ENV_SETUP.md) | Environment configuration |
| [`docs/UI/kalshi_workflow.md`](docs/UI/kalshi_workflow.md) | Operator workflow |
| [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md) | Onboarding |
| [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) | API reference |
| [`docs/trader_tracker_exposure_layers.md`](docs/trader_tracker_exposure_layers.md) | Exposure-cap layers |
| [`LIVE_TRADING_STATUS.md`](LIVE_TRADING_STATUS.md) | Current production state |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Dev workflow, code style, CI gates |
| [`SECURITY.md`](SECURITY.md) | Vulnerability reporting + security scope |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history |

## License

Proprietary — All rights reserved. See [`LICENSE`](LICENSE).
