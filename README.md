# MERID

**v4.0.0** — Deploy-ready autonomous AI swarm for Kalshi prediction markets.

MERID deploys a grid of 35 specialized AI agents across 11 asset classes and multiple timeframes. Each agent independently analyzes markets, generates directional signals, and debates in a structured protocol before voting in swarm consensus. When the swarm agrees, MERID sizes positions using debate-weighted Kelly criterion and volatility targeting, then executes on Kalshi through a unified order pipeline with multi-layer risk controls.

> **Status:** 100% deployable. 0 critical / 0 high findings. Paper mode enforced by default with 3-layer order blocking. No agent can place real orders without explicit operator opt-in.

---

## What It Does

```text
DISCOVER → ANALYZE → CONSENSUS → SIZE → EXECUTE → MONITOR → PROMOTE → PROTECT
```

1. **Discover** — Browse Kalshi markets, find edge via implied vs model probability
2. **Analyze** — Score markets through sentiment (fear/greed), volatility, and volume signals
3. **Debate** — Agents argue YES/NO positions with structured arguments; Brier-weighted votes determine conviction
4. **Consensus** — Debate-weighted swarm votes on direction, probability, and confidence per asset/timeframe
5. **Size** — Debate-conviction-scaled Kelly fraction × vol-targeting × drawdown tier determines position size
6. **Execute** — Place orders on Kalshi (paper or live) via trade ticket or autonomous agent grid
7. **Monitor** — Track positions, orders, fills, PnL, debate PnL attribution, and risk limits in real-time
8. **Promote** — Move agents from paper → shadow → live based on performance + debate-quality gates
9. **Protect** — Kill switch, circuit breakers, drawdown halts, execution guards, per-category caps

---

## Tech Stack

**Backend** — Python 3.11, FastAPI, Uvicorn, Pydantic Settings, SQLite

**Frontend** — React 18, TypeScript, TailwindCSS, Lucide icons

**Kalshi Integration** — REST API client with circuit breaker, **real-time WebSocket streaming**, SSE orderbook feeds, RSA-PSS authentication, demo + production mode support

**AI Layer** — Custom agent framework with domain-based agents, consensus coordination, and performance-gated promotion

---

## UI

18 views organized into 5 workflow-aligned groups:

```text
LIVE TRADING               SWARM INTELLIGENCE
  Overview                   Agent Grid
  Terminal                   Swarm Matrix
  Markets (All Markets)      Performance
  Portfolio                  Calibration
  Positions                  Lane Control
  Orders

ANALYTICS                  COMMAND CENTER
  Fear / Greed               Operator
  Vol & Sizing               Kill Switch
  Risk Screen

SYSTEM
  Logs
  Settings
```

| View | Purpose |
|------|---------|
| **Overview** | System health, balance, PnL, agent activity, grid start/stop |
| **Terminal** | Execution cockpit — orderbook, trade ticket, Kelly sizing, focused market |
| **Markets** | Market discovery — search, filter, favorites, edge signals, trade ticket |
| **All Markets** | Full Kalshi universe browser — category tabs, coverage cards, universal agent launcher, exposure caps |
| **Portfolio** | Positions, orders, fills, risk metrics, order groups, batch operations, PnL chart |
| **Positions** | Deep-link into Portfolio positions tab — open positions with PnL |
| **Orders** | Deep-link into Portfolio orders tab — open/filled/cancelled orders |
| **Agent Grid** | 5 assets × 4 timeframes agent matrix — start/stop/pause, fills, paper ladder, debate quotas, PnL attribution |
| **Swarm Matrix** | Multi-agent consensus — direction, probability, confidence, debate verdicts per cell |
| **Performance** | Agent leaderboard — win rate, Sharpe, calibration, edge accuracy, debate contribution |
| **Calibration** | Forecaster Brier scores, weight correlation matrix, resolver accuracy |
| **Lane Control** | Cross-timeframe signals, deployment phases (paper → shadow → live), auto-promoter |
| **Fear/Greed** | Sentiment gauge (0–100), per-category breakdown, component scores |
| **Vol & Sizing** | Vol targeting, Kelly metrics, risk limit gauges, volume alerts, AI insights |
| **Risk Screen** | Dedicated risk dashboard — kill switch status, execution gate, drawdown, category caps |
| **Operator** | System ops — kill switch status, mode control, data freshness, alerts, operator assistant |
| **Kill Switch** | Emergency stop, reset, per-category toggles |
| **Logs** | System log viewer |
| **Settings** | User preferences |

See [`docs/ui/kalshi_workflow.md`](docs/ui/kalshi_workflow.md) for the full operator workflow reference.

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+

### Setup

```bash
git clone https://github.com/MaxExtractoor/MERID.git
cd MERID

# Backend
pip install -r requirements.txt
cp .env.example .env

# Start API server
make serve                  # http://127.0.0.1:8000

# React dashboard (separate terminal)
cd web/react
npm install
npm run dev                 # http://localhost:5173
```

### 15m Lean Stack (Production Entrypoint)

For Kalshi 15m crypto trading, use the lean stack:

```bash
# Set profile in .env
MERID_PROFILE=kalshi_crypto_15m_v2
MERID_TRADING_MODE=demo
TRADING_ENABLED=false

# Start lean stack
python -m web.main_15m_lean    # http://127.0.0.1:8000
```

The lean stack (`web/main_15m_lean.py`) is the production entrypoint for the `kalshi_crypto_15m_v2` profile. It provides:
- Minimal dependencies (no PM runtime, paper trading engine, reflection system)
- 5 crypto 15m agents (BTC, ETH, SOL, XRP, DOGE)
- Live bankroll service with `is_demo`/`is_live` mode flags
- Runtime invariants checking via `/api/v1/self-check`
- Normalized observability endpoints with schema versions

See `merid/kalshi_15m_runtime_check.py` for production invariants.

### Environment

MERID runs in paper mode with zero configuration. For Kalshi API access:

```bash
# .env
KALSHI_API_KEY_ID=your_key_id
KALSHI_PRIVATE_KEY_PATH=path/to/private_key.pem
KALSHI_USE_DEMO=true            # use demo environment (recommended to start)
MERID_PM_TRADING_MODE=paper     # sim | paper | live
MERID_PM_LIVE_ENABLED=false     # must be true to enable live trading
```

### Commands

```bash
make serve                  # Start FastAPI server (port 8000)
make loop-start             # Start MeridLoop (observe mode)
make loop-start-execute     # Start MeridLoop with execution
make golden-path            # Run test suite
make preflight              # Tests + readiness + drift audit + risk context
make risk-context           # Print live RiskContext JSON
```

---

## Architecture

```text
MERID/
├── web/
│   ├── main.py                     # FastAPI app factory (MERID_PROFILE gating)
│   ├── api/                        # REST + WebSocket endpoints
│   │   ├── debate_*.py             # Debate protocol API (5 routers)
│   │   ├── kalshi_*.py             # Kalshi trading, grid, signals, universe
│   │   ├── notification_*.py       # Notification dispatch + formatting
│   │   ├── replay_*.py             # Replay harness + scenario testing
│   │   ├── slo_api.py              # SLO tracking
│   │   ├── incentive_api.py        # Agent reward pool + tier promotions
│   │   └── assistant_api.py        # Operator assistant (LLM-backed)
│   └── react/                      # React dashboard (18 views)
│       └── src/
│           ├── views/              # 18 active views
│           ├── components/         # 60+ shared components
│           ├── hooks/              # 15+ data hooks
│           ├── config/constants.ts # 160+ API endpoint constants
│           └── types/              # TypeScript types (views, kalshi, api)
├── merid/
│   ├── settings.py                 # Pydantic Settings (env config)
│   ├── loop.py                     # MeridLoop orchestrator
│   ├── execution_guard.py          # Kill switch, CQI throttle, domain caps
│   ├── agent_gauntlet.py           # Agent promotion gate (8 SLO dimensions)
│   ├── pipeline/
│   │   ├── router.py               # TradeRouter (proposal → execution)
│   │   ├── risk_manager.py         # GlobalRiskManager (pre-trade checks)
│   │   ├── risk_context.py         # RiskContext (system state → sizing)
│   │   └── mode_manager.py         # SIM/PAPER/LIVE gating
│   ├── prediction/                 # Prediction market model, forecasters, strategy
│   │   ├── debate_orchestrator.py  # Full debate lifecycle (propose→argue→vote)
│   │   ├── debate_position_sizing.py # Debate-conviction-scaled Kelly sizing
│   │   ├── pnl_attribution.py      # Per-agent PnL by debate contribution
│   │   ├── universal_agent.py      # Market-agnostic sweep agent
│   │   └── forecasters/            # 6 heterogeneous forecasters + registry
│   ├── swarm/                      # Consensus aggregator, critic, auction resolver
│   ├── agents/                     # AI agents + consensus coordination
│   ├── signals/                    # Signal layer (features, drift, CQI)
│   ├── lanes/                      # BTC15M lane, RCK solver, GARCH vol
│   └── event_venues/kalshi/        # Kalshi client, models, trading, WebSocket
│       ├── universe.py             # KalshiUniverse (liquidity filter, coverage)
│       ├── category_exposure.py    # Per-category USD caps + stacking guard
│       └── order_router.py         # Per-order market validation + sanity checks
├── trading/
│   └── trade_mode.py               # Canonical TradeMode enum (single source)
├── tests/                          # 90+ test files
├── RUNBOOK.md                      # Kill-switch policy, halt checklists
├── docs/
│   └── ui/kalshi_workflow.md       # Canonical operator workflow
├── Makefile
└── requirements.txt
```

### Kalshi API Endpoints

Key backend routes powering the UI:

```text
GET  /api/v1/kalshi/markets             # Market catalog
GET  /api/v1/kalshi/markets/{ticker}    # Market detail
GET  /api/v1/kalshi/positions           # Open positions
GET  /api/v1/kalshi/orders              # Open orders
GET  /api/v1/kalshi/fills               # Trade fills
GET  /api/v1/kalshi/balance             # Account balance
GET  /api/v1/kalshi/risk                # Risk summary
GET  /api/v1/kalshi/health              # System health
GET  /api/v1/kalshi/edge                # Edge signals
GET  /api/v1/kalshi/sizing-metrics      # Kelly + vol targeting
POST /api/v1/kalshi/orders              # Submit order
POST /api/v1/kalshi/order-groups        # Create order group

GET  /api/v1/kalshi/universe/coverage   # All-markets coverage summary
GET  /api/v1/kalshi/universe/pool       # Liquidity-filtered market pool
GET  /api/v1/kalshi/universe/category-modes  # Per-category paper/live mode
GET  /api/v1/kalshi/universe/category-caps   # Per-category notional caps
GET  /api/v1/kalshi/universe/agents     # Universal agent registry
POST /api/v1/kalshi/universe/agents/{name}/start  # Launch universal agent
POST /api/v1/kalshi/universe/agents/{name}/stop   # Stop universal agent

GET  /api/v1/kalshi-grid/status         # Agent grid status
POST /api/v1/kalshi-grid/start          # Start agent grid
POST /api/v1/kalshi-grid/stop           # Stop agent grid
POST /api/v1/kalshi-grid/mode           # Switch paper/live

GET  /api/v1/debate/status              # Debate session status
POST /api/v1/debate/start               # Start debate round
GET  /api/v1/debate/results             # Debate verdicts + contribution scores
GET  /api/v1/debate/data/pnl-attribution  # Per-agent PnL by debate weight
GET  /api/v1/debate/data/stats          # Debate system statistics
GET  /api/v1/debate/health              # Debate health + latency

GET  /api/v1/operator/kill-switch       # Kill switch status
POST /api/v1/operator/emergency-stop    # Emergency stop
POST /api/v1/operator/reset-kill-switch # Reset kill switch
POST /api/v1/assistant/query            # Operator assistant LLM query
GET  /api/v1/assistant/contexts         # Available assistant domains

GET  /api/v1/slo/status                 # System SLO tracking
GET  /api/v1/incentives/rewards         # Agent reward pool + tier standings

WS   /ws/live                           # Real-time portfolio updates
WS   /ws/market                         # Orderbook streaming
SSE  /api/v1/kalshi/markets/{t}/orderbook/stream  # Live orderbook SSE
```

---

## Safety & Risk Controls

### 3-Layer Order Blocking (prevents accidental real trades)

| Layer | Protection | Default |
|-------|-----------|--------|
| **Environment** | `MERID_TRADE_MODE=paper`, `MERID_ALLOW_LIVE_TRADES=false`, `KALSHI_USE_DEMO=true` | Safe |
| **VenueGate** | If mode resolves to LIVE but `MERID_ALLOW_LIVE_TRADES` is not set → forces PAPER | Safe |
| **kalshi_tools** | If `KALSHI_USE_DEMO=true` → blocks all real orders, returns simulated fill | Safe |

All three must be explicitly overridden to place real orders. No single misconfiguration can reach production.

### 7-Layer Execution Safety Stack

1. **Kill Switch** — Global emergency stop, per-category toggles, persistent to disk
2. **Execution Guard** — CQI-based throttling, domain caps, cooldown periods
3. **Risk Manager** — Pre-trade checks: notional limits, daily loss, drawdown, spread, depth
4. **Category Exposure Caps** — Per-category USD notional limits with correlated-market stacking guard
5. **Mode Gating** — Paper/live mode enforced at venue level with dual-flag requirement
6. **Agent Gauntlet** — 8-dimension SLO gate + debate-quality score before any agent trades live
7. **Drawdown Governor** — Portfolio-level drawdown halt with automatic position unwinding

**Kalshi exposure (three parallel layers):** Continuous Trader skip gates (cents, per-asset + global), `BankrollManager` sizing (`KALSHI_TRADER_MAX_EXPOSURE`), and `CategoryExposureTracker` USD caps for routed orders are **separate**. See [docs/trader_tracker_exposure_layers.md](docs/trader_tracker_exposure_layers.md).

### Agent Risk Caps (paper-safe defaults)

- **$250 max notional** per market per agent
- **500 max contracts** per position per agent
- **10 max orders** per window per agent
- **$500 daily loss limit** (kill switch triggers)
- **$1,000 max position value** system-wide

All kill switch and mode state flows through single backend endpoints — no divergent state machines across views.

---

## Paper Trading

Paper trading works without any API keys:

```bash
make loop-start-execute     # Runs in paper mode by default
```

The paper engine simulates fills, tracks PnL, and enforces the same risk controls as live. Use it to validate agents before promotion.

---

## Documentation

| Doc | Purpose |
|-----|--------|
| [`docs/ui/kalshi_workflow.md`](docs/ui/kalshi_workflow.md) | Operator workflow — 9 steps, view mapping, endpoint reference |
| [`RUNBOOK.md`](RUNBOOK.md) | Kill-switch policy, halt conditions, pre-open/post-close checklists |
| [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md) | Onboarding guide |
| [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) | API reference |
| [`docs/KALSHI_WIRING_AUDIT_2026_02_23.md`](docs/KALSHI_WIRING_AUDIT_2026_02_23.md) | End-to-end trade flow verification |
| [`docs/SYSTEM_AUDIT_2026_02_23.md`](docs/SYSTEM_AUDIT_2026_02_23.md) | 21-dimension security + robustness audit |
| [`docs/KALSHI_SWARM_GAP_ANALYSIS.md`](docs/KALSHI_SWARM_GAP_ANALYSIS.md) | 62/62 A+ gap analysis |
| [`CHANGELOG.md`](CHANGELOG.md) | Full version history |
| [`ENV_SETUP.md`](ENV_SETUP.md) | Environment configuration |

---

## License

Proprietary — All rights reserved.
