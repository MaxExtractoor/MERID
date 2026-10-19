# MERID — Getting Started

Go from zero to a running MERID server in under 15 minutes. MERID is a production trading system for **Kalshi 15-minute crypto markets** (BTC, ETH, SOL, XRP, DOGE).

> **Safety first:** a bare `uvicorn` launch without production flags stays non-live, and `MERID_OBSERVE_ONLY=1` runs the full live-data stack without ever submitting an order. The production launcher `start_15m.ps1` enables real-money trading — see [Going Live](#5-going-live).

---

## Prerequisites

- **Python 3.11+** with `pip`
- **Node.js 18+** (for the React dashboard, optional)
- **Git**
- Windows PowerShell for the production launcher; the app itself runs anywhere via uvicorn

## 1. Clone & Install

```powershell
git clone https://github.com/MaxExtractoor/MERID.git
cd MERID
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # Windows
# source .venv/bin/activate       # macOS/Linux
pip install -r requirements.txt
```

No Docker, Redis, or external infrastructure is required.

## 2. Start the Server

**Safe first run (observe-only, real data, no orders):**

```powershell
$env:MERID_OBSERVE_ONLY = "1"
.\start_15m.ps1 -Port 8011 -Profile kalshi_crypto_15m_v2
```

**Or bare uvicorn (non-live by default):**

```powershell
.\.venv\Scripts\python.exe -m uvicorn web.main_15m_lean:app --host 127.0.0.1 --port 8011
```

Verify:

```powershell
curl http://localhost:8011/api/v1/health | ConvertFrom-Json | Select-Object app, profile
# expected: app=merid_15m_kalshi_crypto, profile=kalshi_crypto_15m_v2
curl http://localhost:8011/api/v1/self-check
```

API docs: **http://localhost:8011/docs**

## 3. Dashboard

```powershell
cd web/react
npm install
npm run dev     # http://localhost:5173
```

Wired views: Dashboard, Kalshi Dashboard (markets), Kalshi Portfolio, Trade, Grid, Risk, Calibration, Monitor, Logs, Settings.

## 4. Understand the Architecture

### Execution flow (per asset, per 15-minute window)

```text
SPOT SIGNAL → EDGE vs BOOK → EV GATE → SIZE → EXECUTE → MONITOR → EXIT → SETTLE
```

- **Signal** — CF Benchmarks RTI/spot reference + Kalshi orderbook snapshots feed a Bachelier/TWAP probability baseline.
- **Edge gate** — model probability vs executable book price must clear a per-asset dynamic edge threshold plus a slippage-adjusted cost gate.
- **Size** — bounded by `MERID_MAX_CONTRACTS_PER_ORDER`, `MERID_FIXED_EXPOSURE_CAP_USD`, held-price floor `MERID_MIN_HELD_PRICE_CENTS`.
- **Execute** — canonical Kalshi order router with deterministic `client_order_id` idempotency and submission-unknown reconciliation.
- **Monitor/Exit** — position monitor + exit policy (hard profit lock, stop paths), reduce-only exits.
- **Settle** — positions resolve at window close with a post-close grace period.

### Key files

| File | Purpose |
|------|---------|
| `web/main_15m_lean.py` | Canonical FastAPI entrypoint (startup preflight state machine) |
| `start_15m.ps1` | Production launcher — sets live latches, strips legacy creds, port-guarded |
| `merid/loop_15m.py` | 15m trading loop |
| `merid/prediction/agent_grid_15m.py` | 5-asset agent grid |
| `merid/event_venues/kalshi/` | Kalshi client, WebSocket, order router/gate, reconciliation |
| `merid/risk/` | Kill switches, drawdown, platform kill switch |
| `merid/position_management/` | Position monitor, exit policy, hard profit lock |
| `config/profiles/kalshi_crypto_15m_v2.yaml` | Single source of truth for 15m risk config |
| `AGENTS.md` | **Live-trading operational contract** |

`web/main.py`, `merid/loop.py`, and the legacy swarm/consensus modules are **quarantined reference code** — boundaries are enforced by `tests/test_15m_architectural_separation.py`; see [`ARCHITECTURE_15M.md`](../ARCHITECTURE_15M.md).

## 5. Going Live

Live trading requires ALL of:

1. `.\start_15m.ps1` (sets `TRADING_ENABLED`, `MERID_PM_TRADING_MODE=live`, `MERID_PM_LIVE_ENABLED`, `MERID_ALLOW_LIVE_TRADES`, `MERID_KALSHI_ENV=prod`, `KALSHI_USE_DEMO=false`)
2. Valid `KALSHI_API_KEY_ID` + `KALSHI_PRIVATE_KEY_PATH` in `.env` for the intended live account
3. `auto_execution_mode: 1` in `AGENTS.md` (durable authorization — already the repo default)
4. `MERID_OBSERVE_ONLY` unset/`0` (explicit `=1` always wins)
5. A passing startup preflight → `LIVE_ENTRIES_ENABLED`

If preflight fails, entries halt while exits/cancels remain active (`LIVE_ENTRIES_HALTED`). Read [`AGENTS.md`](../AGENTS.md) before operating live.

## 6. Tests

```powershell
# Architectural separation (legacy-import firewall)
python -m pytest tests/test_15m_architectural_separation.py -v

# Canonical smoke slice
python -m pytest tests/test_15m_lean_smoke.py -v --tb=short
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError` | Activate `.venv`, reinstall `requirements.txt` |
| `REFUSED: port 8011 already bound` | Another instance is running — duplicate launches are refused by design |
| `LIVE_ENTRIES_HALTED` | Preflight failed closed — read the structured denial reason in the logs |
| Dashboard blank | Start the backend first; check `web/react` console |

## Next

- [QUICKSTART.md](../QUICKSTART.md) — terse operator quickstart
- [RUNBOOK.md](../RUNBOOK.md) — kill-switch policy, halt conditions
- [docs/API_REFERENCE.md](API_REFERENCE.md) — API reference
- [docs/UI/kalshi_workflow.md](UI/kalshi_workflow.md) — operator workflow
