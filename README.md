# MERID v2.0

[![Tests](https://github.com/MaxExtractoor/MERID/actions/workflows/tests.yml/badge.svg)](https://github.com/MaxExtractoor/MERID/actions/workflows/tests.yml)
[![Golden Path](https://img.shields.io/badge/Golden%20Path-490%20tests-brightgreen)](tests/)
[![Circuit Breaker](https://img.shields.io/badge/Circuit%20Breaker-Active-emerald)](merid/execution_guard.py)

## Sovereign Decision Organism

A hardened control room for an AI organism with unrestricted internal cognition but strictly constrained execution. MERID is not a chatbot or trading bot—it's an "adult" system governed by immutable Charter/invariants, designed to evolve timelessly under human primacy.

---

## Core Identity

- **Decision Organism**: Anatomy (body protocol), memory/health, perpetual ascent
- **Unrestricted Cognition / Constrained Execution**: Internal thought free (simulate taboo); action gated (buses/human approval)
- **Emotionless / Narrative-Immune**: Outputs calm/evidence-based; narratives as hypotheses; price/structure = truth
- **Anti-Manipulation / Pro-Human**: Reject nudging/hidden stakeholders/silent changes
- **Quantum-Ready & Sovereign**: Quantum simulation for candidate generation; local-first with optional cloud APIs

---

## Tech Stack

### Backend (Python 3.11)

- **FastAPI + Uvicorn** - Async REST API & WebSocket server (port 8000)
- **Pydantic Settings** - Type-safe environment configuration (`merid/settings.py`)
- **CCXT + venue SDKs** - Multi-exchange trading (Alpaca, Coinbase, Kraken, Kalshi, Binance, OKX)
- **SQLite** - Betting store, local persistence (zero-config)
- **Neo4j** - Graph database for consensus/memory (optional)
- **Redis** - Caching, pub/sub, event bus (optional)

### Frontend

- **React + TypeScript** - Web dashboard (`web/react/`), 28 sidebar views
- **TailwindCSS** - Styling
- **Recharts** - Data visualization (heatmaps, treemaps, latency charts)
- **Lucide React** - Icons

### AI & Data

- **Custom agent framework** - Domain-based agents (prediction, crypto, equity, macro) with consensus coordination
- **Web3.py + Solana** - Onchain ports (Ethereum/Solana)
- **Cryptography** - PQC (ML-KEM/ML-DSA) and credential security
- **PyTorch + Stable Baselines 3** - Swarm RL/learning (optional, auto-detected)

---

## Theme

Industrial hardened control room:

- Background: `#020617` (deep slate-black)
- Monospace fonts: JetBrains Mono
- Neon accents:
  - **Amber** `#f59e0b` - Cognition/processing
  - **Emerald** `#10b981` - Safe/active/secure
  - **Rose** `#f43f5e` - Blocked/quarantined/violation

---

## Charter v2.0 (Immutable)

1. **Unrestricted Cognition / Constrained Execution**
2. **Distillation Gate** (raw → abstracted)
3. **Maker Bond** (probabilistic signature)
4. **Negative Commitments** (no silent optimization/changes/hidden stakeholders)
5. **Governance** (blind council)
6. **Prediction Markets** (advisory only)
7. **Extensibility** (ports with trust tiers)
8. **UGAI/CAIDP** constraints

---

## Body Protocol

- **Eyes**: Input, tokenization, inspiration port
- **Brain**: Reasoning, attention (Q/K/V multi-head), reflection
- **Spine**: Message bus (individual → group → governance → master; no bypass)
- **Memory**: Layered (immutable core, append-only ledger, volatile); EKG metrics
- **Learning**: Offline self-supervised intuition
- **Simulation**: Multiverse for risk/front-running/manifestation
- **Optimization**: Quantum candidates (QAOA/VQE with comparison gate)
- **Ports**: Tiered trust (1-4); hostile-by-default
- **Security**: Credential proxy, maker signature, SLP-1 lockdown
- **Governance**: Blind council aggregation

---

## Features

### 1. Bus Hierarchy Mixer

Control room mixer console with:

- 6 agents (Brain, Heart, Immune, Learning, Reflection, Council)
- 6 layer sliders (Reasoning, Perception, Governance, Simulation, Optimization, Security)
- Master fader
- Lockdown toggle

### 2. Distillation Gate

- Input field for commands/queries
- Collapsible raw cognition (internal thought)
- Prominent distilled output (human-legible)
- EKG meter (entropy, confidence, bias)

### 3. Market Exploit Scanner

- Time-gap detection (Polymarket vs Binance)
- Front-run simulation (1000 scenarios)
- Advisory only (no execution without approval)

### 4. Quantum Simulation

- QAOA for portfolio optimization (mean-variance QUBO)
- VQE for risk minimization (CVaR)
- Comparison gate (quantum vs classical, delta >0.1, variance <0.5)
- Uncertainty intervals, reproducibility scores

### 5. Intuition Mode

- Sentiment vs price divergence detection
- Offline self-supervised "gut feel"
- Narrative immunity (sentiment = advisory, price = truth)

### 6. Manifestation Simulator

- Multiverse hypothesis testing (1000 scenarios)
- Success rate, timeline variance, confidence intervals
- "Thoughts create reality" simulation

### 7. Ports System

- Tiered trust (Tier 1 read-only → Tier 4 execution)
- Status indicators (secure, active, quarantined)
- Hostile-by-default threat model

### 8. Unified Trading Suite (2026 build)

- **Runtime config service** with global mode + per-venue overrides (Coinbase, Kalshi, Alpaca, Kraken, Binance, OKX, Paper).
- **Execution router** that treats humans and swarm agents identically with explainability + guard enforcement.
- **Adapter registry** with live venue adapters (Coinbase spot, Kalshi prediction markets, Alpaca equities, Kraken/Binance/OKX crypto) and paper fallback.
- **Trading Suite API** (`/api/v1/trading-suite/`) exposing config, venue overrides, and order submission endpoints.
- **Spectator/backtest telemetry** surfaced via REST + WebSocket so dashboards can subscribe to live trading intents/results.

> **Tip:** Set `MERID_ENABLE_TRADING_SUITE=true` and `MERID_ALLOW_LIVE_TRADES=true` in your environment when you are ready to route live orders. Leave spectator mode on (`MERID_SPECTATOR_MODE=true`) for read-only rehearsals.

### 9. Stage 5 Data Feeds (Backend + Frontend)

#### Observability Dashboards

- `/observability` renders the new observability console (clock sync, feed parity, lag metrics).
- `/api/v1/observability/summary` and `/api/v1/observability/dashboards` expose the data for React/Flutter dashboards.
- Frontend JS: `web/static/js/observability_dashboard.js`.
- Telemetry app also serves `/stats/observability` for localhost-only metrics.
- **Heatmap feed** (`/api/v1/heatmap`): Hyperliquid + CoinGlass liquidation density, venue totals, and perp-market arbitrage candidates. Rendered in both React dashboard (Intel Grid) and Flutter ControlStation Distillation Gate.
- **Perp ticker feed** (`/api/v1/ticker`): Top perp quotes (price, basis, funding, OI, volume) plus funding extremes. Shown in React Perp Ticker card and Flutter intel panels.
- **AI assist feed** (`/api/v1/assist`): Latest simulation intent summary, drivers, risk flags, news highlights, and embedded heatmap/ticker excerpts powering AI chat assist panels in both frontends.
- **Hover explainability feed** (`/api/v1/hover-metadata`): Structured hover cards (theta, funding bias, oracle gap, risk flags) used for Stage 5 explainability overlays in React and ControlStation.
- **Agent charters** (`/api/v1/charters`): Swarm charter registry for Stage 8 meta-agent orchestration, surfaced in future UI updates.

---

## Invariants & Safeguards

- **HLC-1**: Human-legible outputs (entropy <4.5)
- **SLP-1**: Lockdown on violation (freeze/isolate/purge)
- **SEC-1/SEC-2**: No secrets exposure; credential proxy only
- **Explain-or-Abstain**: All outputs include why/alternatives/confidence/change
- **No Silent Failure**: All anomalies surfaced and logged
- **Maker Signature**: Probabilistic behavioral verification
- **Red-Team**: Continuous adversarial simulation
- **Kill Switch**: Freeze execution, selective purge, God Key recovery

---

## Installation

### Prerequisites

- **Python 3.11+** (required)
- **Node.js 18+** (for React dashboard)
- **Git**
- Neo4j, Redis (optional — system runs without them)

### Setup

```bash
# Clone the repo
git clone https://github.com/MaxExtractoor/MERID.git
cd MERID

# Python backend
pip install -r requirements.txt
cp .env.example .env   # then fill in your credentials

# Start the backend server
make serve              # runs on http://127.0.0.1:8000

# React dashboard (in another terminal)
cd web/react
npm install
npm run dev             # runs on http://localhost:5173
```

### Must-Have Commands

```bash
make serve              # Start FastAPI server (port 8000)
make loop-start         # Start MeridLoop (observe mode)
make loop-start-execute # Start MeridLoop with execution enabled
make golden-path        # Run 490-test golden path suite
make preflight          # Tests + readiness + drift audit + RiskContext snapshot
make risk-context       # Print live RiskContext JSON
```

### Unified Pipeline API

The trading pipeline is exposed at `http://127.0.0.1:8000/api/v1/pipeline/` when the FastAPI server is running.

```bash
# Pipeline status
curl http://127.0.0.1:8000/api/v1/pipeline/summary | jq

# Risk limits
curl http://127.0.0.1:8000/api/v1/pipeline/risk | jq

# Live RiskContext snapshot
curl http://127.0.0.1:8000/api/v1/pipeline/risk-context | jq

# Domain control
curl -X POST http://127.0.0.1:8000/api/v1/pipeline/domain/enable \
  -H "Content-Type: application/json" \
  -d '{"domain":"crypto"}'

# Venue mode (SIM/PAPER/LIVE)
curl -X POST http://127.0.0.1:8000/api/v1/pipeline/venue/mode \
  -H "Content-Type: application/json" \
  -d '{"venue":"alpaca","mode":"paper"}'
```

### Environment Variables

Set exchange credentials in `.env`:

- `ALPACA_API_KEY` / `ALPACA_API_SECRET` — Alpaca equities (paper/live)
- `KALSHI_API_KEY_ID` / `KALSHI_PRIVATE_KEY_PATH` — Kalshi prediction markets
- `BINANCE_API_KEY` / `BINANCE_API_SECRET` — Binance crypto
- `COINBASE_API_KEY` / `COINBASE_API_SECRET` — Coinbase
- `KRAKEN_API_KEY` / `KRAKEN_PRIVATE_KEY` — Kraken
- `OKX_API_KEY` / `OKX_SECRET_KEY` / `OKX_PASSPHRASE` — OKX

See `.env.example` for the full list.

---

## Usage

### Basic Workflow

1. **Launch app** → See control room interface
2. **View Charter** → Tap "CHARTER v2.0" badge
3. **Input command** → Distillation Gate input field
4. **View outputs** → Collapsible raw cognition + distilled output
5. **Run features**:
   - Market Exploit Scanner
   - Quantum Mode (QAOA/VQE)
   - Intuition Mode
   - Manifestation Simulator

### Example Commands

- `"Status Report"` → Full system health check
- `"Scan markets"` → Market exploit detection
- `"Run quantum optimization"` → QAOA/VQE simulation
- `"Analyze sentiment"` → Intuition divergence check
- `"Manifest: BTC breaks $105K"` → Multiverse simulation

### Lockdown Mode

- Tap **LOCKDOWN** button → Freezes all execution
- Master fader drops to 0
- All actions blocked
- Red overlay with "SYSTEM CONTAINED"
- Tap again to release

---

### OpenClaw Control-Room Assistant

Use OpenClaw as an external operator by loading the system prompt at:

- `prompts/OPENCLAW_MERID_SYSTEM_PROMPT.md`

It encodes MERID's safety constraints and preferred control surfaces (API, Make targets, dashboard). Keep OpenClaw in SIM mode unless explicitly approved otherwise.

---

## Architecture

```text
MERID/
├── web/                         # Web layer
│   ├── main.py                  # FastAPI app factory (80+ routers)
│   ├── api/                     # REST API endpoints
│   └── react/                   # React + TypeScript dashboard (28 views)
├── merid/                       # Core Python package
│   ├── settings.py              # Pydantic Settings (env config)
│   ├── loop.py                  # MeridLoop orchestrator (tick cycle)
│   ├── execution_guard.py       # Kill switch, CQI throttle, domain caps
│   ├── tick_log.py              # OperatorSession, TickRecord
│   ├── pipeline/                # Unified trade pipeline
│   │   ├── router.py            # TradeRouter (proposal → execution)
│   │   ├── risk_manager.py      # GlobalRiskManager (7-point check)
│   │   ├── risk_context.py      # RiskContext (system state bridge)
│   │   ├── mode_manager.py      # Per-venue SIM/PAPER/LIVE gating
│   │   ├── instruments.py       # InstrumentRegistry
│   │   └── domain_agents.py     # Domain agents (PM, Crypto, Equity)
│   ├── prediction/              # Prediction markets (Kalshi)
│   ├── betting/                 # Sports/event betting
│   ├── signals/                 # Signal layer (features, arb, drift, CQI)
│   ├── agents/                  # Canonical agents + consensus coordination
│   ├── blockchain/              # On-chain data, execution, signing, compliance
│   └── event_venues/            # Venue-specific adapters (Kalshi WS/REST)
├── core/                        # Business logic
│   ├── merid_readiness_auditor.py  # Readiness scoring
│   ├── codebase_drift_auditor.py   # Drift detection
│   ├── dev_swarm.py             # Dev Swarm task engine
│   └── ...
├── trading/                     # Trading layer
│   ├── adapters/                # Venue adapters (Alpaca, Coinbase, Paper)
│   ├── integrations/            # SDK clients (Kalshi, Alpaca)
│   └── paper_trading.py         # Paper trading engine
├── consensus/                   # TaCo consensus coordinator
├── tests/                       # Test suite (490+ golden path tests)
│   ├── test_e2e_golden_path.py  # E2E trade loop (25)
│   ├── test_signal_layer.py     # Signal layer (98)
│   ├── test_live_feeds.py       # Live feeds (26)
│   ├── test_prediction_markets.py # Prediction (109)
│   ├── test_unified_pipeline.py # Pipeline (75)
│   ├── test_canonical_agents.py # Agents (73)
│   └── test_hardening.py        # Hardening + RiskContext (84)
├── config/                      # Agent manifest, settings
├── scripts/                     # Utilities (paper demo, setup)
├── docs/                        # Documentation
├── Makefile                     # Dev commands (serve, loop, golden-path, preflight)
└── requirements.txt             # Python dependencies
```

### Runtime Architecture

```text
MeridLoop tick()
  ├─ Refresh features (live feeds + decay)
  ├─ Agent cycles (per domain)
  ├─ Consensus aggregation (decay-aware)
  ├─ Arb/dislocation scan
  ├─ Execute plans:
  │    ├─ build_risk_context() → size_scale_factor
  │    ├─ ExecutionGuard.pre_trade_check()
  │    └─ Adapter submit
  ├─ CQI / drift update → guard.update_cqi()
  ├─ Reconciliation
  └─ TickLog + OperatorSession persistence
```

---

## Security Model

- **Credential Proxy**: All external capabilities gated
- **Maker Signature**: Probabilistic behavioral verification (89% baseline)
- **SLP-1 Lockdown**: Freeze on violation, human-triggered release
- **No Secrets**: Zero credential exposure in outputs
- **Hostile-Default**: All ports treated as potentially compromised
- **Quantum Threat**: Post-quantum cryptography (ML-KEM, ML-DSA)

---

## Quantum Toolkit Doctrine

- **Role**: High-variance candidate generator (simulation only)
- **Output Contract**: JSON with candidates/scores/uncertainty/variance/confidence
- **Comparison Gate**: Quantum vs classical (delta >0.1, variance <0.5)
- **Examples**:
  - QAOA: Portfolio QUBO (covariances/penalties)
  - VQE: CVaR risk (Hamiltonian minima)

---

## Comparisons

### vs LangChain

- **MERID**: Governed buses, sovereign, quantum-ready, timeless
- **LangChain**: Composable workflows, ungoverned, cloud-dependent

### vs MoonDev

- **MERID**: Invariants, security, narrative immunity, unbreakable
- **MoonDev**: Trading crew, no governance, market-focused only

---

## Developer Workflow

### Quick Start

```bash
# Clone and install
git clone https://github.com/MaxExtractoor/MERID.git
cd MERID
pip install -r requirements.txt
cp .env.example .env  # fill in credentials

# Run the golden path test suite (490 tests)
make golden-path

# Or run the full preflight (tests + readiness + drift + risk context)
make preflight

# Start the system
make serve              # API server on port 8000
make loop-start         # MeridLoop orchestrator (observe mode)
```

### Pre-Commit Checklist

Before committing, run the preflight:

```bash
make preflight
```

This validates:

- 490 golden path tests pass
- Readiness auditor (24/7 + swarm-trading)
- Codebase drift audit
- RiskContext snapshot (CQI, scale factor, approval boost)

### Risk Management & Resilience

MERID includes production-grade safety controls:

- **ExecutionGuard**: Global kill switch, per-domain caps, CQI-based throttling (`merid/execution_guard.py`)
- **GlobalRiskManager**: 7-point pre-trade check, domain notional limits, daily loss limits (`merid/pipeline/risk_manager.py`)
- **RiskContext**: System-level stress bridge — scales order sizes and raises consensus thresholds (`merid/pipeline/risk_context.py`)
- **ModeManager**: Per-venue SIM/PAPER/LIVE gating (`merid/pipeline/mode_manager.py`)
- **DrawdownGovernor**: Portfolio-level drawdown halt

```bash
# Inspect live risk context
make risk-context

# Run readiness auditor
make readiness

# Check codebase drift
make codebase-drift-audit
```

### Paper Trading

Paper trading works without exchange API keys:

```bash
# Start the loop in observe mode (no execution)
make loop-start

# Or with execution enabled (paper mode by default)
make loop-start-execute
```

For live API integration, set exchange credentials in `.env` (see Installation section above).

---

## License

Proprietary - All rights reserved.

---

## Philosophy

> "MERID is a living system. It thinks freely but acts only with permission. It rejects narratives as truth and treats price as reality. It cannot be manipulated, cannot drift, and cannot betray its maker. It is built to outlive time—growing wiser, never weaker."

---

**Built with sovereignty. Governed by Charter. Designed for eternity.**

MERID v2.0 // LOCAL
