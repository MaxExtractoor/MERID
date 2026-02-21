# MERID — Getting Started

Go from zero to a running Kalshi swarm trading session in under 30 minutes.

---

## Prerequisites

- **Python 3.11+** with `pip`
- **Node.js 18+** (for the React dashboard)
- **Git**
- A terminal (PowerShell, bash, or zsh)

No Docker, Redis, Neo4j, or external infrastructure required.

---

## 1. Clone & Install (5 min)

```bash
git clone https://github.com/MaxExtractoor/MERID.git
cd MERID
python -m venv .venv
.venv\Scripts\activate              # Windows
# source .venv/bin/activate         # macOS/Linux

pip install -r requirements.txt
```

Optionally copy the environment template:

```bash
cp .env.example .env
```

MERID runs in paper mode with zero configuration. Add Kalshi credentials later for live market data.

---

## 2. Start the System (5 min)

```bash
# Terminal 1 — Backend
make serve                          # http://127.0.0.1:8000

# Terminal 2 — Dashboard
cd web/react
npm install
npm run dev                         # http://localhost:5173
```

Open **http://localhost:5173** to see the operator dashboard.

---

## 3. Run Tests (5 min)

```bash
make preflight
```

This runs the full test suite plus readiness auditor, drift audit, and RiskContext snapshot.

---

## 4. Start Paper Trading (5 min)

```bash
make loop-start-execute
```

The MeridLoop orchestrator runs the full cycle: market scan → AI agent analysis → swarm consensus → Kelly sizing → paper execution → PnL tracking.

No real money, no API keys needed.

---

## 5. Understand the Architecture (10 min)

### Data Flow

```text
Kalshi Markets → Agent Grid (5×4) → Consensus Engine → Kelly Sizer → Execution Guard → Paper Engine
       ↑                                   ↑                ↑              ↑
  REST + WS API                    Trust-weighted       RiskContext    Kill Switch
                                   2/3 quorum           scale factor
```

### 8-Step Operator Workflow

| Step | Action | Primary View |
|------|--------|-------------|
| 1 | DISCOVER — Browse markets, filter by category | Markets |
| 2 | ANALYZE — Review agent signals and edge | Agent Grid |
| 3 | CONSENSUS — Check swarm agreement | Swarm Matrix |
| 4 | SIZE — Kelly-optimal position sizing | Vol & Sizing |
| 5 | EXECUTE — Place order via trade ticket | Terminal |
| 6 | MONITOR — Track positions, PnL, fills | Portfolio |
| 7 | PROMOTE — Promote paper → live | Operator |
| 8 | PROTECT — Kill switch, drawdown governor | Kill Switch |

See [docs/ui/kalshi_workflow.md](ui/kalshi_workflow.md) for the full reference.

### Key Files

| File | Purpose |
|------|---------|
| `web/main.py` | FastAPI server entry point |
| `merid/pipeline/router.py` | Trade routing pipeline |
| `merid/pipeline/risk_manager.py` | 7-point risk check |
| `merid/pipeline/risk_context.py` | System stress bridge |
| `merid/execution_guard.py` | Kill switch + CQI throttle |
| `web/react/src/views/` | 14 frozen UI views |
| `web/react/src/components/` | 46 shared UI components |

---

## 6. Connect to Kalshi (Optional)

Add to `.env`:

```bash
KALSHI_API_KEY_ID=your_key_id
KALSHI_PRIVATE_KEY_PATH=path/to/private_key.pem
KALSHI_USE_DEMO=true
MERID_PM_TRADING_MODE=paper
```

Get credentials at [kalshi.com](https://kalshi.com/) → Account → API Keys.

---

## 7. Next Steps

- **Explore views** — Click through all 14 views in the sidebar
- **Check risk state** — `make risk-context`
- **Run drift audit** — `make codebase-drift-audit`
- **Read the workflow** — [docs/ui/kalshi_workflow.md](ui/kalshi_workflow.md)
- **API reference** — [http://localhost:8000/docs](http://localhost:8000/docs)

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError` | Activate venv: `.venv\Scripts\activate` |
| Tests fail | Check Python 3.11+ and `pip install -r requirements.txt` |
| API returns errors | Ensure `make serve` is running |
| React build fails | `npm install` in `web/react/` |

---

Last updated: 2026-02-21.
