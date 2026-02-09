# MERID v2.0 — Quick Start Guide

**Get MERID running in 5 minutes.**

---

## Step 1: Install Dependencies (2 min)

```powershell
cd C:\Dev\MERID
pip install -r requirements.txt
```

---

## Step 2: Run the Golden Path (2 min)

```powershell
make golden-path
```

This runs 490 tests across the full pipeline: E2E trade loop, signal layer, live feeds, prediction markets, unified pipeline, canonical agents, and hardening.

---

## Step 3: Start the System (1 min)

```powershell
# Terminal 1: Backend API
make serve

# Terminal 2: React dashboard
cd web/react
npm install
npm run dev
```

- **API**: http://127.0.0.1:8000 (Swagger docs at `/docs`)
- **Dashboard**: http://localhost:5173

---

## Quick Test

### Test 1: Preflight Check
```powershell
make preflight
```
Runs golden path + readiness auditor + codebase drift audit + live RiskContext snapshot.

### Test 2: Risk Context
```powershell
make risk-context
```
Prints the current system risk state: CQI, scale factor, approval boost, kill switch status.

### Test 3: Start the Loop
```powershell
make loop-start
```
Runs the MeridLoop orchestrator in observe mode: live feeds → agents → consensus → arb → plans → CQI → reconciliation.

### Test 4: Paper Trading
```powershell
make loop-start-execute
```
Same as above but with execution enabled. Paper mode by default — no real capital at risk.

---

## Key Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/pipeline/summary` | Full pipeline status |
| `GET /api/v1/pipeline/risk` | Risk limits and exposure |
| `GET /api/v1/pipeline/risk-context` | Live RiskContext snapshot |
| `GET /api/v1/prediction-markets/summary` | Prediction markets dashboard |
| `GET /api/v1/wallet/balances` | Wallet balances (live) |
| `GET /api/v1/treasury/overview` | Treasury overview (live) |
| `GET /api/operator/summary` | Operator dashboard data |

---

## Key Features

- **MeridLoop**: Persistent orchestrator running full tick cycle (feeds → agents → consensus → risk → execution → CQI)
- **RiskContext**: System-level stress bridge — scales order sizes and raises approval thresholds
- **ExecutionGuard**: Kill switch, CQI throttle, per-domain caps
- **Unified Pipeline**: TradeRouter → GlobalRiskManager → ModeManager → VenueAdapter
- **Signal Layer**: Decay-aware features, arb scanner, CQI dashboard
- **28 Dashboard Views**: Operator, Wallet, Treasury, Trading, Positions, Predictions, Betting, Flow Radar, Signal Layer, and more

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` |
| `make` not found (Windows) | Install via `choco install make` or run Python commands directly |
| Tests fail | Check Python 3.11+ and re-install deps |
| API returns errors | Ensure `make serve` is running |

---

## Learn More

- **Full Documentation**: `README.md`
- **Go-Live Checklist**: `docs/GO_LIVE_CHECKLIST.md`
- **Getting Started (1hr)**: `docs/GETTING_STARTED.md`
- **Readiness Scorecard**: `docs/SWARM_TRADING_READINESS.md`

---

MERID v2.0 // LOCAL
