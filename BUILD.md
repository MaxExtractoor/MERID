# MERID v2.0 — Build & Development Guide

## Prerequisites

- **Python 3.11+** (required)
- **Node.js 18+** (for React dashboard)
- **make** (Windows: `choco install make`, or use Python commands directly)

---

## Backend Setup

```bash
cd C:\Dev\MERID
pip install -r requirements.txt
cp .env.example .env   # fill in exchange credentials
```

### Run Tests

```bash
# Golden path suite (490 tests)
make golden-path

# Full preflight (tests + readiness + drift + risk context)
make preflight
```

### Start the Server

```bash
make serve              # FastAPI on http://127.0.0.1:8000
```

API docs available at http://127.0.0.1:8000/docs (Swagger UI).

---

## Frontend Setup

```bash
cd web/react
npm install
npm run dev             # Vite dev server on http://localhost:5173
```

### Production Build

```bash
cd web/react
npm run build           # Output in web/react/dist/
```

---

## MeridLoop (Orchestrator)

```bash
# Observe mode (no execution)
make loop-start

# With execution enabled (paper mode by default)
make loop-start-execute

# Custom domains/symbols
python -m merid.loop --domains crypto,prediction --symbols BTC,ETH,SOL
```

---

## Makefile Quick Reference

| Command | Description |
|---------|-------------|
| `make serve` | Start FastAPI server (port 8000) |
| `make loop-start` | Start MeridLoop (observe mode) |
| `make loop-start-execute` | Start MeridLoop with execution |
| `make golden-path` | Run 490-test golden path suite |
| `make preflight` | Tests + readiness + drift + RiskContext |
| `make risk-context` | Print live RiskContext JSON |
| `make readiness` | Run readiness auditor |
| `make codebase-drift-audit` | Check codebase drift |
| `make pm-test` | Run prediction market tests |
| `make pipeline-test` | Run pipeline tests |

---

## Environment Variables

Create `.env` file (see `ENV_SETUP.md` for full reference):

```env
# Exchange credentials (for paper/live trading)
ALPACA_API_KEY=your-key
ALPACA_API_SECRET=your-secret
KALSHI_API_KEY_ID=your-key-id
KALSHI_PRIVATE_KEY_PATH=/path/to/key.pem

# Capital configuration
MERID_TOTAL_CAPITAL_USD=50000
MERID_PM_TRADING_MODE=sim
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` |
| `make` not found (Windows) | Install via `choco install make` or run Python commands directly |
| Tests fail with import errors | Check Python 3.11+ and re-install deps |
| API returns errors | Ensure `make serve` is running |
| React build fails | Run `npm install` in `web/react/` |

---

**MERID v2.0 — Built for Sovereignty**
