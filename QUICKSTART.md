# MERID — Quick Start

Get MERID running in 5 minutes. No API keys required for paper mode.

---

## 1. Install (2 min)

```bash
cd MERID
pip install -r requirements.txt
```

> **Note**: Uses latest stable dependencies (FastAPI 0.135.1, pandas 3.0.1, pytest 9.0.2)

## 2. Start (1 min)

```bash
# Terminal 1 — Backend
make serve                      # http://127.0.0.1:8000

# Terminal 2 — Dashboard
cd web/react && npm install && npm run dev   # http://localhost:5173
```

## 3. Verify (2 min)

```bash
make preflight                  # Tests + readiness + drift audit + risk context
```

---

## What You'll See

Open **http://localhost:5173** to see the operator dashboard with 17 views:

- **Overview** — System health, balance, PnL
- **Markets** — Browse Kalshi markets, edge signals, trade ticket
- **Terminal** — Execution cockpit with orderbook and Kelly sizing
- **Portfolio** — Positions, orders, fills, risk, PnL chart
- **Agent Grid** — Start/stop the 5×4 agent matrix
- **Swarm Matrix** — Multi-agent consensus visualization
- **Operator** — Kill switch, mode control, system alerts

API docs at **http://127.0.0.1:8000/docs** (Swagger UI).

---

## Start Paper Trading

```bash
make loop-start-execute         # MeridLoop with paper execution
```

This runs the full agent cycle: market scan → AI analysis → swarm consensus → Kelly sizing → paper execution → PnL tracking. No real money, no API keys needed.

---

## Connect to Kalshi

Add to `.env` for live market data and trading:

```bash
KALSHI_API_KEY_ID=your_key_id
KALSHI_PRIVATE_KEY_PATH=path/to/private_key.pem
KALSHI_USE_DEMO=true
MERID_PM_TRADING_MODE=paper
```

---

## Key Commands

| Command | What it does |
|---------|-------------|
| `make serve` | Start API server (port 8000) |
| `make loop-start` | MeridLoop in observe mode |
| `make loop-start-execute` | MeridLoop with paper execution |
| `make golden-path` | Run test suite |
| `make preflight` | Full system check |
| `make risk-context` | Print risk state JSON |

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError` | `pip install -r requirements.txt` |
| `make` not found (Windows) | `choco install make` |
| API returns errors | Ensure `make serve` is running |
| React build fails | `npm install` in `web/react/` |

---

## Next

- [README.md](README.md) — Full project overview
- [docs/ui/kalshi_workflow.md](docs/ui/kalshi_workflow.md) — Operator workflow (8 steps, 17 views)
- [ENV_SETUP.md](ENV_SETUP.md) — Environment configuration
- [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) — Detailed onboarding
