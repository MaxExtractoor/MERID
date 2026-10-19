# MERID — Quick Start

MERID is a production trading system for **Kalshi 15-minute crypto markets** (BTC, ETH, SOL, XRP, DOGE). This guide gets you from a fresh clone to a running server — **safely**.

> **Read this first:** the production launcher (`start_15m.ps1`) enables **real-money live trading** the moment valid Kalshi credentials are present — it sets every live latch itself (`TRADING_ENABLED`, `MERID_PM_TRADING_MODE=live`, `MERID_ALLOW_LIVE_TRADES`, `KALSHI_USE_DEMO=false`) and points at `external-api.kalshi.com`. Use one of the **safe modes below** unless you are deploying to production.

---

## 1. Prerequisites

- **Python 3.11+** and `pip`
- **Node.js 18+** (optional — only for the React dashboard)
- **Windows** for the production launcher (`start_15m.ps1`); the app itself is plain FastAPI/uvicorn and runs anywhere
- **Kalshi API credentials** (key ID + RSA private key file) — *not required* for the safe modes below

## 2. Install

```powershell
cd MERID
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```bash
# Linux/macOS equivalent
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Start — choose a mode

### A. Observe-only against live data (recommended first run)

Consumes real Kalshi market data, runs the full decision pipeline, and **never submits an order**:

```powershell
$env:MERID_OBSERVE_ONLY = "1"
.\start_15m.ps1 -Port 8011 -Profile kalshi_crypto_15m_v2
```

Without Kalshi credentials the startup preflight fails closed into `LIVE_ENTRIES_HALTED`, but the API, dashboard, and self-check endpoints still serve normally — enough to explore the system safely.

### B. Bare server, no live flags (paper/simulation)

Skip the launcher entirely — without its live latches the app stays non-live:

```powershell
.\.venv\Scripts\python.exe -m uvicorn web.main_15m_lean:app --host 127.0.0.1 --port 8011
```

### C. Config validation only

`start_15m.ps1` supports a `-DryRun` switch that resolves the environment, prints the startup fingerprint, and exits **without launching**:

```powershell
.\start_15m.ps1 -DryRun
```

## 4. Verify

```powershell
curl http://localhost:8011/api/v1/health | ConvertFrom-Json | Select-Object app, profile
# expected: app=merid_15m_kalshi_crypto, profile=kalshi_crypto_15m_v2

curl http://localhost:8011/api/v1/self-check   # runtime invariant check
```

Interactive API docs: **http://localhost:8011/docs**

## 5. Dashboard (optional)

```powershell
cd web/react
npm install
npm run dev        # http://localhost:5173
```

Wired views: **Dashboard, Markets (Kalshi dashboard), Portfolio, Trade, Grid (5-asset agent grid), Risk, Calibration, Monitor, Logs, Settings**.

## 6. Going live — production only

Live trading is deliberately hard to reach by accident. All of the following must hold:

| Layer | Requirement |
|-------|-------------|
| Launcher | `.\start_15m.ps1` (sets `TRADING_ENABLED`, `MERID_PM_TRADING_MODE=live`, `MERID_PM_LIVE_ENABLED`, `MERID_ALLOW_LIVE_TRADES`, `MERID_KALSHI_ENV=prod`, `KALSHI_USE_DEMO=false`) |
| Credentials | `KALSHI_API_KEY_ID` + `KALSHI_PRIVATE_KEY_PATH` in `.env`, matching the intended live account |
| Operator contract | `auto_execution_mode: 1` in `AGENTS.md` front-matter — durable authorization for live entries after preflight |
| Read-only override | `MERID_OBSERVE_ONLY=0` (derived automatically from `auto_execution_mode`; `=1` always wins) |
| Preflight | `STARTING → PREFLIGHT_RUNNING → LIVE_ENTRIES_ENABLED`; any failure → `LIVE_ENTRIES_HALTED` |

If preflight fails, the server still runs — entries halt, exits/cancels stay active. The full state machine, halt conditions, and safety invariants are defined in **[AGENTS.md](AGENTS.md)**; read it before operating live.

**Never** put real credentials in `.env.example`, committed configs, or docs. `.env` is gitignored.

---

## Key Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/api/v1/health` | Liveness + profile identity |
| `/api/v1/self-check` | Runtime invariant self-check |
| `/docs` | OpenAPI/Swagger UI |

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError` | Activate `.venv`, `pip install -r requirements.txt` |
| `REFUSED: port 8011 is already bound` | An instance is already running — the launcher refuses duplicates by design |
| `LIVE MODE REFUSED: ...` | A required safety control is missing/mismatched; read the message, do not unset protections |
| `LIVE_ENTRIES_HALTED` at startup | A preflight step failed closed — check the structured denial reason in logs; entries stay blocked while exits/cancels remain active |
| React build fails | `npm install` inside `web/react/` first |

## Next

- [README.md](README.md) — architecture, execution flow, repository layout
- [AGENTS.md](AGENTS.md) — **the live-trading operational contract (read before production)**
- [ARCHITECTURE_15M.md](ARCHITECTURE_15M.md) — 15m/legacy boundaries and forbidden imports
- [ENV_SETUP.md](ENV_SETUP.md) — full environment variable reference
- [RUNBOOK.md](RUNBOOK.md) — kill-switch policy, halt conditions, operator checklists
- [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) — detailed onboarding
- [docs/API_REFERENCE.md](docs/API_REFERENCE.md) — API reference
