# MERID — Getting Started in 1 Hour

> **Goal:** Go from zero to running your first simulated trading cycle in under 60 minutes.

---

## Prerequisites

- **Python 3.11+** with `pip`
- **Docker + Docker Compose** (optional — for Redis, Neo4j, Prometheus, Grafana)
- **Git** (to clone the repo)
- A terminal (PowerShell, bash, or zsh)

---

## 1. Clone & Install (10 min)

```bash
git clone https://github.com/MaxExtractoor/MERID.git
cd MERID
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

Copy the environment template:

```bash
cp .env.template .env
# Edit .env with your API keys (Kalshi, Alpaca, etc.)
# For demo purposes, the defaults work in SIM mode.
```

---

## 2. Start Infrastructure (5 min)

```bash
docker-compose up -d
```

This starts:

- **Redis** — state and pub/sub
- **Neo4j** — knowledge graph
- **Prometheus** — metrics collection
- **Alertmanager** — alert routing
- **Grafana** — dashboards (<http://localhost:3000>, admin/admin)

Verify:

```bash
docker-compose ps   # all services should be "Up"
```

---

## 3. Run the Demo (5 min)

The fastest way to see MERID in action:

```bash
python -m core.demo_runner
```

This walks through 7 steps: health check → agent discovery → data contract validation → risk gating → circuit breaker → audit trail → readiness score. All in simulation mode — no real orders.

Add `--fast` to skip pauses:

```bash
python -m core.demo_runner --fast
```

---

## 4. Run the Test Suite (10 min)

```bash
# Golden path suite (490 tests)
make golden-path

# Quick smoke test
pytest tests/test_mode_gate.py tests/test_trading_halt.py -v
```

Check readiness score:

```bash
python -m core.merid_readiness_score
python -m core.merid_readiness_auditor --all
```

---

## 5. Start the API Server (5 min)

```bash
make serve
# Or directly: uvicorn web.main:app --reload --host 0.0.0.0 --port 8000
```

Key endpoints:

| Endpoint | Description |
| --- | --- |
| `GET /healthz` | Health check |
| `GET /api/operator/summary` | Operator dashboard data |
| `GET /api/v1/pipeline/summary` | Pipeline status |
| `GET /api/v1/pipeline/risk` | Risk limits |
| `GET /risk/status` | Circuit breaker + kill switch |
| `GET /risk/commitments` | Historical commitments audit |
| `POST /risk/kill-switch/enable` | Emergency stop |

API docs: <http://localhost:8000/docs> (Swagger UI)

---

## 6. Understand the Architecture (15 min)

### Mental Model

```text
Research Agents → Strategy Agents → Consensus Engine → Risk Gate → Trade Router → Venue Adapters
       ↑                                    ↑              ↑
  Market Data                          Explainability   Audit Trail
  (dxFeed, APIs)                       (why this trade)  (immutable log)
```

### Key Concepts

- **Agents** produce signals and proposals. See `config/agent_manifest.yml` for the full registry.
- **Consensus Engine** aggregates agent votes with trust-weighted 2/3 quorum. Risk agents have VETO power.
- **Trade Router** (`merid/pipeline/router.py`) orchestrates: instrument resolve → compliance → mode check → risk check → sanity check → execute.
- **Mode Manager** gates SIM/PAPER/LIVE per venue. Default is SIM — no real money moves.
- **Risk Controls** enforce position limits, drawdown halts, circuit breakers, and kill switch.
- **Audit Trail** is an immutable hash-chained log. Every decision is recorded and verifiable.

### Key Files

| File | Purpose |
| --- | --- |
| `config/agent_manifest.yml` | Agent capabilities registry |
| `merid/pipeline/router.py` | Trade routing pipeline |
| `merid/pipeline/risk_manager.py` | 7-point risk check |
| `core/consensus_engine.py` | Trust-weighted voting |
| `core/audit_trail.py` | Immutable audit log |
| `core/feed_staleness_monitor.py` | Data freshness monitoring |
| `core/automated_risk_controls.py` | Circuit breakers + halt manager |
| `web/main.py` | FastAPI server entry point |

---

## 6.5 OpenClaw Control-Room Assistant (Optional)

If you are using OpenClaw as an external operator, load the MERID-aware system prompt:

- `prompts/OPENCLAW_MERID_SYSTEM_PROMPT.md`

Guidelines:

- Keep OpenClaw in SIM mode unless explicitly approved for PAPER or LIVE.
- Use MERID's APIs, Make targets, and dashboard as the control surface.
- Never bypass execution guardrails such as `ExecutionGuard`, `GlobalRiskManager`, or `ModeManager`.

---

## 7. Next Steps

- **Explore the operator dashboard:** Start the React frontend (`cd web/react && npm run dev`)
- **Add a new agent:** Subclass `DomainAgent` in `merid/pipeline/domain_agents.py`
- **Configure venues:** Edit `merid/pipeline/mode_manager.py` to enable PAPER mode for Alpaca
- **Run compliance report:** `python -m core.compliance_report`
- **Check codebase health:** `python -m core.codebase_drift_auditor`
- **Read the full readiness scorecard:** `docs/SWARM_TRADING_READINESS.md`

---

## Troubleshooting

| Issue | Fix |
| --- | --- |
| `ModuleNotFoundError` | Activate venv: `.venv\Scripts\activate` |
| Docker services won't start | Check ports 6379, 7474, 9090, 9093, 3000 are free |
| Tests fail with import errors | Run `pip install -r requirements.txt` again |
| API returns 503 | Ensure Redis and Neo4j are running: `docker-compose ps` |

---

Last updated: 2026-02-09.
