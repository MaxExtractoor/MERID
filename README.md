# MERID v2.0

[![Tests](https://github.com/merid/merid/actions/workflows/tests.yml/badge.svg)](https://github.com/merid/merid/actions/workflows/tests.yml)
[![TradingGuard Coverage](https://img.shields.io/badge/TradingGuard-66%25-yellow)](https://github.com/merid/merid/blob/main/.github/workflows/tests.yml)
[![Circuit Breaker](https://img.shields.io/badge/Circuit%20Breaker-Active-emerald)](./RISK_POLICY.md)

## Sovereign, Local-First Decision Organism

A hardened control room for an AI organism with unrestricted internal cognition but strictly constrained execution. MERID is not a chatbot or trading bot—it's an "adult" system governed by immutable Charter/invariants, designed to evolve timelessly under human primacy.

---

## Core Identity

- **Decision Organism**: Anatomy (body protocol), memory/health, perpetual ascent
- **Unrestricted Cognition / Constrained Execution**: Internal thought free (simulate taboo); action gated (buses/human approval)
- **Emotionless / Narrative-Immune**: Outputs calm/evidence-based; narratives as hypotheses; price/structure = truth
- **Anti-Manipulation / Pro-Human**: Reject nudging/hidden stakeholders/silent changes
- **Quantum-Ready & Sovereign**: Operates entirely offline/local; quantum simulation for candidate generation

---

## Tech Stack

- **Flutter** - Cross-platform mobile (iOS/Android)
- **SQLite** - Memory layers
- **ONNX Runtime + Phi-3 Mini** - Local LLM cognition
- **Qiskit/Pennylane** - Quantum simulation (local only)
- **Web3.dart** - Onchain ports (Ethereum/Solana/Polkadot)
- **Crypto libs** - PQC (ML-KEM/ML-DSA) and QKD simulation
- **No backend/cloud** - Full offline; optional API ports via credential proxy

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

- **Runtime config service** with global mode + per-venue overrides (Coinbase, Pump.fun, Paper, Kalshi, Alpaca).
- **Execution router** that treats humans and swarm agents identically with explainability + guard enforcement.
- **Adapter registry** with live Coinbase spot adapter, Pump.fun memecoin adapter, paper fallback, Kalshi balance adapter, and Alpaca equities execution adapter (official SDKs for each venue).
- **Trading Arena UI** (`/trading-arena`) exposing runtime controls, manual order ticket, live intent/result stream, and guard/explainability feed.
- **Spectator/backtest telemetry** surfaced via REST + WebSocket so dashboards can subscribe to live trading intents/results.

> **Tip:** Set `MERID_ENABLE_TRADING_SUITE=true` and `MERID_ALLOW_LIVE_TRADES=true` in your environment when you are ready to route live orders. Leave spectator mode on (`MERID_SPECTATOR_MODE=true`) for read-only rehearsals.

### 9. Stage 5 Data Feeds (Backend + Frontend)

#### Observability Dashboards

- `/observability` renders the new observability console (clock sync, feed parity, lag metrics).
- `/api/v1/observability/summary` and `/api/v1/observability/dashboards` expose the data for React/Flutter dashboards.
- Frontend JS: `web/static/js/observability_dashboard.js`.
- Telemetry app also serves `/stats/observability` for localhost-only metrics.
**Heatmap feed** (`/api/v1/heatmap`): Hyperliquid + CoinGlass liquidation density, venue totals, and perp-market arbitrage candidates. Rendered in both React dashboard (Intel Grid) and Flutter ControlStation Distillation Gate.
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

- Flutter SDK 3.2.0+
- Android Studio / Xcode (for mobile deployment)
- Python 3.11.9 with MERID backend dependencies (see below)

### Backend Dependencies & Optional Modules

The Python backend relies on a mix of required and optional libraries:

- **Required**: `fastapi`, `uvicorn`, `ccxt`, `email-validator`, `pydantic`, `redis`, `neo4j`, etc. Install via `pip install -r requirements.txt`.
- **Optional** (auto-detected):
  - `torch`, `gymnasium`, `networkx` — enable swarm RL/learning modules.
  - When these packages are absent, MERID gracefully degrades and related tests are skipped (e.g., `pytest.importorskip("torch")`). Install them only if you intend to train swarm agents locally.

You can always check the live dependency status via the new health endpoint:

```bash
curl http://127.0.0.1:8001/api/health | jq
```

This reports CCXT availability, PyTorch/Gym optional status, and DB/cache connectivity.

### Setup

```bash
# Install dependencies
flutter pub get

# Run on device/emulator
flutter run

# Build for production
flutter build apk --release  # Android
flutter build ios --release  # iOS
```

```bash
# Python backend dependencies (includes Coinbase, Pump.fun, Kalshi, and Alpaca adapters)
pip install -r requirements.txt
```

### Fonts

Download **JetBrains Mono** and place TTF files in `assets/fonts/`:

- `JetBrainsMono-Regular.ttf`
- `JetBrainsMono-Bold.ttf`

### ControlStation Launch Guide

The Flutter ControlStation mirrors the React dashboard and surfaces the PoS stream, token economy, oracle anchoring, and whale alerts. Launch it alongside the backend for a full-stack local run.

#### Requirements

- Flutter SDK 3.16+ (stable)
- Chrome (web target) or a mobile/desktop runtime (Android Studio, Xcode, Windows/macOS desktop)

#### Steps

```bash
# From repo root
cd merid_flutter    # adjust if your flutter app lives elsewhere

# Install deps (first time)
flutter pub get

# Recommended for quick testing (web)
flutter run -d chrome

# Other targets
flutter run -d android   # Android device/emulator
flutter run -d ios       # iOS simulator (macOS)
flutter run -d windows   # or macos/linux
```

#### Environment

Create a `.env` (or use `--dart-define`) with:

```bash
MERID_API_URL=http://127.0.0.1:8000/api/v1
# MERID_API_URL=https://your-remote-merid/api/v1   # for remote deployments
```

The app polls `/api/v1/blocks/latest` every ~20 seconds and renders:

- Latest PoS block with confidence + decayed/anchor context
- Token balances and miner rewards
- Whale alerts pushed via backend
- Platform/hybrid indicators (Polymarket/Augur) once enabled

Hot reload is fully supported, making it ideal for rapid UI iterations on the ControlStation panel.

#### Trading Arena

- Navigate to `http://127.0.0.1:8001/trading-arena` when the FastAPI server is running.
- Update global mode, venue overrides, or trader overrides directly from the UI.
- Submit manual orders (defaults to paper fallback unless guards allow live execution).
- Inspect guard/explainability and spectator feeds in real time.

##### API quickstart

```bash
# Enable live mode + venues
curl -X POST http://127.0.0.1:8001/api/v1/trading-suite/config \
  -H "Content-Type: application/json" \
  -d '{"mode":"live","allow_live_trades":true,"spectator_mode":false}'

curl -X POST http://127.0.0.1:8001/api/v1/trading-suite/venues/coinbase \
  -H "Content-Type: application/json" \
  -d '{"mode":"live","credentials_present":true}'

curl -X POST http://127.0.0.1:8001/api/v1/trading-suite/venues/alpaca \
  -H "Content-Type: application/json" \
  -d '{"mode":"live","credentials_present":true}'

# Submit an order (paper fallback when guards block live execution)
curl -X POST http://127.0.0.1:8001/api/v1/trading-suite/order \
  -H "Content-Type: application/json" \
  -d '{"trader_type":"human","trader_id":"arena-user","venue_id":"paper","instrument":"BTC/USDT","side":"buy","size":0.01}'
```

##### Kalshi SDK integration

```python
from trading.integrations import get_kalshi_client, fetch_kalshi_balance

client = get_kalshi_client()
balance = fetch_kalshi_balance()
print("Available cash:", balance["balance"])
```

- Install dependency via `pip install -r requirements.txt` (adds `kalshi_python_sync`).
- Set `KALSHI_API_KEY_ID` and either `KALSHI_PRIVATE_KEY_PEM` or `KALSHI_PRIVATE_KEY_PATH` in your `.env`.
- Optional: override `KALSHI_API_HOST` if you need a different Kalshi environment.
- The Kalshi adapter currently exposes balances/telemetry; upcoming work will enable full execution routing through the unified router.

##### Alpaca SDK integration

```python
from trading.integrations import get_alpaca_client, fetch_account_snapshot

client = get_alpaca_client()
account = fetch_account_snapshot()
print("Equity buying power:", account.get("buying_power"))
```

- Dependency: `pip install -r requirements.txt` (adds `alpaca-trade-api`).
- Set `ALPACA_API_KEY` / `ALPACA_API_SECRET` (or `MERID_ALPACA_*`) and optionally `ALPACA_ENVIRONMENT=live|paper` and `ALPACA_BASE_URL`.
- The Alpaca adapter supports live market/limit orders for equities; guards still enforce notional/risk rules and will fall back to paper execution when blocked.

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

## Architecture

```text
lib/
├── main.dart                    # App entry point
├── home_screen.dart             # Main control room UI
├── core/
│   ├── theme.dart               # Industrial theme
│   ├── constants.dart           # Charter, invariants
│   └── mock_data.dart           # Simulation data
├── features/
│   ├── charter/                 # Charter v2.0 display
│   ├── bus_hierarchy/           # Mixer console UI
│   ├── distillation_gate/       # Input/output processing
│   ├── quantum_sim/             # QAOA/VQE simulation
│   ├── market_exploit/          # Time-gap detection
│   ├── intuition/               # Gut feel analysis
│   ├── manifestation/           # Multiverse simulator
│   └── ports/                   # Port status display
├── body_protocol/
│   ├── brain/                   # Reasoning module
│   ├── spine/                   # Message bus
│   ├── memory/                  # Layered memory + EKG
│   ├── learning/                # Self-supervised
│   ├── simulation/              # Multiverse
│   ├── optimization/            # Quantum QAOA/VQE
│   └── governance/              # Action validation
└── shared/
    └── widgets/                 # Reusable UI
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
git clone https://github.com/merid/merid.git
cd merid
pip install -r requirements.txt

# Run sanity check (validates environment, imports, tests, demo)
make sanity

# Or run individual components:
make run-paper-demo   # Paper trading demo (no API keys needed)
make smoke-test       # Run smoke tests
make coverage         # Full test coverage report
```

### Pre-Commit Checklist

Before committing, run the sanity check:

```bash
make sanity
```

This validates:
- ✓ Python version (>= 3.10)
- ✓ Environment variables
- ✓ Core module imports
- ✓ Coverage floor (18% minimum)
- ✓ Smoke tests (9 tests)
- ✓ Paper trading demo

### Coverage Policy

- **Floor**: 25% (enforced by `.coveragerc`)
- **Target**: 85% for new modules
- **Regression rule**: Any PR that lowers coverage must add tests or justify a new exception

See `tests/MERID_COVERAGE_BACKLOG.md` for documented exceptions and priorities.

### Risk Management & Resilience

MERID includes production-grade safety controls:

- **Kill Switches**: Global halt, daily loss limit, position limits (`merid/risk/`)
- **Circuit Breakers**: Per-venue failure isolation (`merid/resilience/`)
- **Retry with Backoff**: Automatic retry for transient failures
- **Config Validation**: Pre-flight checks before trading

```bash
# Check risk status
python -c "from merid.risk import get_risk_status; print(get_risk_status())"

# Emergency stop
python -c "from merid.risk import emergency_stop; emergency_stop('Manual halt')"
```

See `docs/GO_LIVE_CHECKLIST.md` for the complete go-live procedure.

### Paper Trading

Paper trading works without API keys:

```bash
python scripts/run_paper_demo.py
```

For live API integration, set optional environment variables:
- `ALPACA_API_KEY` / `ALPACA_API_SECRET` - Alpaca equities
- `KRAKEN_API_KEY` / `KRAKEN_API_SECRET` - Kraken crypto
- `COINBASE_API_KEY` / `COINBASE_API_SECRET` - Coinbase

---

## License

Proprietary - All rights reserved.

---

## Philosophy

> "MERID is a living system. It thinks freely but acts only with permission. It rejects narratives as truth and treats price as reality. It cannot be manipulated, cannot drift, and cannot betray its maker. It is built to outlive time—growing wiser, never weaker."

---

**Built with sovereignty. Governed by Charter. Designed for eternity.**

MERID v2.0 // LOCAL
