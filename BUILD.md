# MERID — Build & Development Guide

## Prerequisites

- **Python 3.11+**
- **Node.js 18+** (React dashboard)
- **make** (Windows: `choco install make`)

---

## Backend

```bash
pip install -r requirements.txt       # Latest FastAPI 0.135.1, pandas 3.0.1, pytest 9.0.2
cp .env.example .env                  # optional — runs without credentials in paper mode
make serve                            # FastAPI on http://127.0.0.1:8000
```

API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) (Swagger UI)

---

## Frontend

```bash
cd web/react
npm install
npm run dev                           # Vite dev server on http://localhost:5173
```

Production build:

```bash
npm run build                         # Output in web/react/dist/
```

---

## MeridLoop

The MeridLoop orchestrator runs the full agent cycle: market scan → analysis → consensus → sizing → execution → PnL.

```bash
make loop-start                       # observe mode (no execution)
make loop-start-execute               # paper execution enabled
```

---

## Testing

```bash
make golden-path                  # full test suite
make preflight                    # tests + readiness + drift audit + risk context
make risk-context                 # print live RiskContext JSON
```

---

## Makefile Reference

| Command | Description |
|---------|-------------|
| `make serve` | FastAPI server (port 8000) |
| `make loop-start` | MeridLoop — observe mode |
| `make loop-start-execute` | MeridLoop — paper execution |
| `make golden-path` | Run test suite |
| `make preflight` | Tests + readiness + drift + risk context |
| `make risk-context` | Print risk state JSON |
| `make readiness` | Run readiness auditor |
| `make codebase-drift-audit` | Check for code drift |
| `make pm-test` | Prediction market tests only |
| `make pipeline-test` | Pipeline tests only |

---

## Environment

Create `.env` for Kalshi credentials (see [ENV_SETUP.md](ENV_SETUP.md) for full reference):

```bash
KALSHI_API_KEY_ID=your_key_id
KALSHI_PRIVATE_KEY_PATH=path/to/private_key.pem
KALSHI_USE_DEMO=true
MERID_PM_TRADING_MODE=paper
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError` | `pip install -r requirements.txt` |
| `make` not found (Windows) | `choco install make` |
| Tests fail | Check Python 3.11+ and reinstall deps |
| API returns errors | Ensure `make serve` is running |
| React build fails | `npm install` in `web/react/` |
