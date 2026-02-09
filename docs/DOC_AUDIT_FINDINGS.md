# Documentation Audit Findings — 2026-02-09

## Summary

Audited 10 documentation files. Found **53 issues** across all docs. All have been fixed.

| Doc | Issues Found | Severity Breakdown |
|-----|-------------|-------------------|
| README.md | 14 | 8 High, 4 Medium, 2 Minor |
| QUICKSTART.md | 8 | 3 Critical, 3 High, 2 Medium |
| BUILD.md | 5 | 2 Critical, 2 High, 1 Medium |
| ENV_SETUP.md | 5 | 3 High, 2 Medium |
| CONTRIBUTING.md | 4 | 2 High, 2 Medium |
| CHANGELOG.md | 3 | 1 Critical, 1 High, 1 Medium |
| docs/API_REFERENCE.md | 4 | 1 Critical, 2 High, 1 Medium |
| docs/GO_LIVE_CHECKLIST.md | 4 | 3 High, 1 Medium |
| docs/GETTING_STARTED.md | 3 | 1 Medium, 2 Minor |
| docs/LOCAL_DEV.md | 4 | 3 High, 1 Medium |

---

## Items Removed / No Longer Exist

### Dead File References
- `README_TRADING_SYSTEM.md` — referenced in QUICKSTART.md, never existed
- `PROJECT_SUMMARY.md` — referenced in QUICKSTART.md, never existed
- `MASTER_DOCUMENTATION.md` — referenced in ENV_SETUP.md, never existed
- `MERID_IMPLEMENTATION_CHECKLIST.md` — referenced in CONTRIBUTING.md, never existed
- `RISK_POLICY.md` — linked in README badge, never existed
- `agents/__init__.py` — referenced in CONTRIBUTING pre-commit, outdated path
- `core/settings.py` — referenced in CONTRIBUTING pre-commit, outdated path
- `db/neo4j.py` — referenced in CONTRIBUTING pre-commit, outdated path

### Dead Environment Variables
- `MERID_TRADING_MODE` — replaced by per-venue ModeManager
- `MERID_LIVE_TRADING_UNLOCKED` — removed, use ModeManager
- `MERID_ENABLE_TRADING_SUITE` — never existed
- `MERID_SPECTATOR_MODE` — never existed
- `MERID_MAX_ORDER_SIZE_USD` — replaced by GlobalRiskManager domain configs
- `MERID_MAX_POSITION_SIZE_USD` — replaced by GlobalRiskManager
- `MERID_REQUIRE_CONFIRMATION` — removed
- `QUANTUM_API_KEY` — never existed
- `BLOCKCHAIN_RPC_URL` — never existed

### Dead API Endpoints
- All `/institutional/*` endpoints — replaced by `/api/v1/pipeline/`, `/api/v1/prediction-markets/`, etc.
- `/api/v1/trading-suite/*` — never existed
- `/api/v1/heatmap`, `/api/v1/ticker`, `/api/v1/assist` — never existed as described
- `/api/v1/hover-metadata`, `/api/v1/charters` — never existed

### Dead Commands
- `python main.py` — replaced by `make serve` / `uvicorn web.main:app`
- `python -m merid.run` — replaced by `python -m merid.loop` / `make loop-start`
- `make validate-config` — never existed
- `make go-live-dry-run` — never existed
- `make show-mode` — never existed
- `make show-risk` — never existed
- `make emergency-stop` — never existed
- `make sanity` — never existed
- `flutter pub get` / `flutter run` — Flutter UI is legacy

### Dead Import Paths
- `from trading.integrations import get_kalshi_client` — doesn't exist
- `from merid.risk import can_trade, emergency_stop` — doesn't exist; use ExecutionGuard
- `from merid.risk import risk_controller, KillSwitchEvent` — doesn't exist
- `from merid.resilience import get_all_breakers` — doesn't exist

### Outdated Concepts
- "6 agents (Brain, Heart, Immune...)" — replaced by domain-based agents (PredictionMarket, CryptoArb, Equity, Macro)
- "Coverage Floor: 40%" — stale; golden path is 490 tests
- "393+ tests" / "488+ tests" — actual is 490 golden path
- "Primary test file: test_dev_swarm.py" — golden path spans 7 test files
- "Polymarket credentials" — Polymarket is prohibited by ComplianceRegistry
- "Virtual $10,000 balance" — paper engine starts at $50,000 (MERID_TOTAL_CAPITAL_USD)
- "No Backend: Fully offline/local" — backend exists and is required
- Kubernetes/gRPC/Kafka/ClickHouse/Vault architecture — none exist
- `merid/accounts/`, `merid/positions/`, `merid/orders/`, `merid/strategies/` directories — don't exist
- Flutter as primary UI — React dashboard is primary (28 views)
- PyTorch/LangChain/CrewAI as core deps — optional or unused
- Neo4j/Redis/Celery as required deps — optional
- MIT License reference — project is Proprietary

---

## What Was Fixed

### README.md
- Updated badge from "40% coverage" to "490 tests Golden Path"
- Removed Neo4j/Redis/Celery from required deps (now optional)
- Removed Flutter as primary frontend
- Removed PyTorch/LangChain/CrewAI from core deps
- Replaced entire Installation section with correct `make` commands
- Replaced ControlStation/Flutter/Trading Suite sections with Unified Pipeline API
- Replaced architecture tree with current file structure + runtime diagram
- Replaced Developer Workflow with current `make` commands and risk management

### QUICKSTART.md
- Complete rewrite: Flutter-first → Python/React-first
- Added correct `make` commands, endpoints, features, troubleshooting

### BUILD.md
- Complete rewrite: Flutter-only → Python backend + React frontend
- Added Makefile quick reference, correct env vars

### ENV_SETUP.md
- Fixed startup command (`python main.py` → `make serve`)
- Replaced required deps with "None — runs in SIM mode"
- Added correct exchange credentials and capital/risk vars
- Fixed documentation links

### CONTRIBUTING.md
- Replaced `meridctl_simple.py status` with `make preflight` / `make golden-path`
- Fixed logging convention (`merid_logging_config` → `utils.logger.get_logger()`)
- Fixed documentation links (removed dead files, added real ones)
- Fixed pre-commit checklist

### CHANGELOG.md
- Added comprehensive v2.0.0 entry (Added, Changed, Removed, Security)
- Updated version history
- Fixed license from MIT to Proprietary

### docs/API_REFERENCE.md
- Complete rewrite: all `/institutional/` endpoints replaced with actual v2.0 endpoints
- Fixed base URL from `:8001` to `:8000`
- Updated version from 1.0.0 to 2.0.0

### docs/GO_LIVE_CHECKLIST.md
- Replaced all stale env vars with ModeManager/ExecutionGuard approach
- Fixed `python -m merid.run` → `make loop-start`
- Removed Polymarket credential section (prohibited)
- Replaced `merid.risk` imports with ExecutionGuard/RiskContext
- Fixed Windows workaround commands
- Updated quick reference table

### docs/GETTING_STARTED.md
- Marked Docker as optional
- Updated test count to 490
- Prefer `make serve` over direct uvicorn

### docs/LOCAL_DEV.md
- Fixed `uvicorn merid_api:app` → `uvicorn web.main:app`
- Marked PostgreSQL as unused
- Fixed React dashboard port to 5173
- Replaced test commands with `make golden-path`
