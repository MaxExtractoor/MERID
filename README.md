# MERID

An autonomous multi-AI swarm intelligence platform for trading Kalshi prediction markets.

MERID deploys a grid of specialized AI agents across multiple assets and timeframes. Each agent independently analyzes markets, generates directional signals, and votes in a swarm consensus. When the swarm agrees, MERID sizes positions using Kelly criterion and volatility targeting, then executes on Kalshi through a unified order pipeline with multi-layer risk controls.

---

## What It Does

```text
DISCOVER → ANALYZE → CONSENSUS → SIZE → EXECUTE → MONITOR → PROMOTE → PROTECT
```

1. **Discover** — Browse Kalshi markets, find edge via implied vs model probability
2. **Analyze** — Score markets through sentiment (fear/greed), volatility, and volume signals
3. **Consensus** — Multi-agent swarm votes on direction, probability, and confidence per asset/timeframe
4. **Size** — Kelly fraction × vol-targeting × drawdown tier determines position size
5. **Execute** — Place orders on Kalshi (paper or live) via trade ticket or autonomous agent grid
6. **Monitor** — Track positions, orders, fills, PnL, and risk limits in real-time
7. **Promote** — Move agents from paper → shadow → live based on performance gates
8. **Protect** — Kill switch, circuit breakers, drawdown halts, execution guards

---

## Tech Stack

**Backend** — Python 3.11, FastAPI, Uvicorn, Pydantic Settings, SQLite

**Frontend** — React 18, TypeScript, TailwindCSS, Lucide icons

**Kalshi Integration** — REST API client with circuit breaker, WebSocket orderbook streaming, demo + production mode support

**AI Layer** — Custom agent framework with domain-based agents, consensus coordination, and performance-gated promotion

---

## UI

14 views organized into 5 workflow-aligned groups:

```text
TRADING                    SWARM INTELLIGENCE
  Overview                   Agent Grid
  Terminal                   Swarm Matrix
  Markets                    Performance
  Portfolio                  Lane Control

ANALYTICS                  OPERATOR
  Fear / Greed               Operator
  Vol & Sizing               Kill Switch

SYSTEM
  Logs
  Settings
```

| View | Purpose |
|------|---------|
| **Overview** | System health, balance, PnL, agent activity, grid start/stop |
| **Terminal** | Execution cockpit — orderbook, trade ticket, Kelly sizing, focused market |
| **Markets** | Market discovery — search, filter, favorites, edge signals, trade ticket |
| **Portfolio** | Positions, orders, fills, risk metrics, order groups, batch operations, PnL chart |
| **Agent Grid** | 5 assets × 4 timeframes agent matrix — start/stop/pause, fills, paper ladder |
| **Swarm Matrix** | Multi-agent consensus — direction, probability, confidence per cell |
| **Performance** | Agent leaderboard — win rate, Sharpe, calibration, edge accuracy |
| **Lane Control** | Cross-timeframe signals, deployment phases (paper → shadow → live), auto-promoter |
| **Fear/Greed** | Sentiment gauge (0–100), per-category breakdown, component scores |
| **Vol & Sizing** | Vol targeting, Kelly metrics, risk limit gauges, volume alerts, AI insights |
| **Operator** | System ops — kill switch status, mode control, data freshness, alerts |
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
│   ├── main.py                     # FastAPI app factory
│   ├── api/                        # REST + WebSocket endpoints
│   └── react/                      # React dashboard (14 views)
│       └── src/
│           ├── views/              # 14 active views
│           ├── components/         # 46 shared components
│           ├── hooks/              # 12 data hooks
│           ├── config/constants.ts # 140+ API endpoint constants
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
│   ├── prediction/                 # Prediction market model + strategy
│   ├── agents/                     # AI agents + consensus coordination
│   ├── signals/                    # Signal layer (features, drift, CQI)
│   └── event_venues/kalshi/        # Kalshi client, models, trading, WebSocket
├── tests/                          # Test suite
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

GET  /api/v1/kalshi-grid/status         # Agent grid status
POST /api/v1/kalshi-grid/start          # Start agent grid
POST /api/v1/kalshi-grid/stop           # Stop agent grid
POST /api/v1/kalshi-grid/mode           # Switch paper/live

GET  /api/v1/operator/kill-switch       # Kill switch status
POST /api/v1/operator/emergency-stop    # Emergency stop
POST /api/v1/operator/reset-kill-switch # Reset kill switch

WS   /ws/live                           # Real-time portfolio updates
WS   /ws/market                         # Orderbook streaming
```

---

## Safety & Risk Controls

MERID enforces a 6-layer execution safety stack:

1. **Kill Switch** — Global emergency stop, per-category toggles
2. **Execution Guard** — CQI-based throttling, domain caps, cooldown periods
3. **Risk Manager** — Pre-trade checks: notional limits, daily loss, drawdown, spread, depth
4. **Mode Gating** — Paper/live mode enforced at venue level, requires explicit `MERID_PM_LIVE_ENABLED=true`
5. **Agent Gauntlet** — 8-dimension SLO gate before any agent trades live (liveness, error rate, latency, Sharpe, drawdown, etc.)
6. **Drawdown Governor** — Portfolio-level drawdown halt with automatic position unwinding

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
|-----|---------|
| [`docs/ui/kalshi_workflow.md`](docs/ui/kalshi_workflow.md) | Operator workflow — 8 steps, view mapping, endpoint reference |
| [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md) | Onboarding guide |
| [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md) | API reference |
| [`docs/TESTING_GUIDE.md`](docs/TESTING_GUIDE.md) | Testing guide |
| [`docs/LOCAL_DEV.md`](docs/LOCAL_DEV.md) | Local development |
| [`ENV_SETUP.md`](ENV_SETUP.md) | Environment configuration |
| [`QUICKSTART.md`](QUICKSTART.md) | Quick start |

---

## License

Proprietary — All rights reserved.
