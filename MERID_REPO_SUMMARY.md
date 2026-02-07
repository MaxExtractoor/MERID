# MERID Repository Summary

## Architectural domains

- **Trading, strategy, and risk:** `core/`, `trading/`, `arbitrage/`, `prediction/`, `backtesting/`, `treasury/`, and `portfolio/` own agent orchestration, execution engines, hedging models, market-structure adapters, and capital controls.
- **Swarm intelligence and social systems:** `swarm/`, `agents/`, `cognitive_core/`, `collaborative/`, `social/`, `interfaces/`, and `learning/` host Lab/Swarm orchestrators, reflection loops, X/TG bot gateways, and reinforcement-learning curricula.
- **Observability, safety, compliance:** `observability/`, `monitoring/`, `notifications/`, `audit/`, `compliance/`, `governance/`, `security/`, `hardening/`, `ops/`, and `qa/` provide telemetry capture, anomaly detection, policy enforcement, and runbooks.
- **Platform, infra, surfaces:** `services/`, `backend/`, `web/`, `merid-ui/`, `merid-api/`, `infra/`, `deployment/`, `docs/`, `docs_archive/`, and `mobile/desktop` folders deliver FastAPI/Node gateways, Flutter/React clients, SDKs, knowledge artifacts, and deployment tooling.
- **Data & knowledge fabric:** `data/`, `db/`, `memory/`, `knowledge/`, `analytics/`, `streams/`, and `plugins/` manage persistence, feature stores, analytics pipelines, and extensibility hooks.

## Key human + agent roles

- **Strategy & risk engineers:** extend `core/`, `trading/`, `arbitrage/`, `treasury/`, and `risk/` tests; tune automated risk controls; certify new venues in `ops/` & `onboarding/`.
- **Swarm Lab stewards & AI researchers:** operate `swarm/` orchestrators, author charters in `agents/`, and evolve learning curricula in `learning/` & `cognitive_core/`.
- **Safety & compliance officers:** monitor `observability/`, `monitoring/`, `audit/`, `governance/`, `compliance/`, and `security/`, ensuring telemetry + policy guardrails remain green.
- **Ops & infra leads:** manage deployments (`infra/`, `deployment/`), data tiers, and reliability scripts in `scripts/`, `runbooks/`, `ops/`.
- **Marketing & growth swarm strategists:** plug into `analytics/`, `services/`, `social/`, `observability/`, and future `marketing/` modules to translate product telemetry into campaigns, revenue funnels, and CRM integrations.

### Data/telemetry touchpoints for marketing & growth

1. **Product usage + sentiment:** `analytics/`, `observability/analytics_dashboard.py`, `social/` intel streams.
2. **Revenue + trading performance:** `treasury/`, `portfolio/`, `metrics` stored under `data/reports/`.
3. **Customer & partner state:** `services/`, `merid-api/`, `merid-ui/`, `notifications/`.
4. **Recommended repo placement:** create `marketing_swarm/` (agents + playbooks), plus integrations in `analytics/` and `services/marketing.py` to bridge CRM/CDP feeds.

## Major surfaces & entrypoints

- **APIs & services:** `web/` FastAPI application, `merid-api/` Node gateway, `backend/` server.js, plus CLI utilities in `scripts/` and `tools.py`.
- **Clients:** `merid-ui/` React app, `lib/` Flutter sources, `interfaces/` messaging channels.
- **Automation scripts:** `run_tests.py`, `start_merid.py`, `merid_bootstrap.py`, `autonomous_soak_test.py`, plus numerous domain-specific scripts under `scripts/` and `deployment/scripts/`.

## Coordination flows

- **Trading stack:** Sensors (`data/`, `oracles/`) → analytics/ML (`analytics/`, `prediction/`) → strategy versions (`core/strategy_versioning.py`) → execution via `core/agent_orchestrator.py`, `trading/`, `arbitrage/`, with controls enforced by `governance/`, `security/`, `risk` suites.
- **Swarm stack:** `swarm/swarm_lab.py` orchestrates multi-role agents defined in `agents/` and `cognitive_core/`, with telemetry sent through `observability/` + `monitoring/` and surfaced via `web/api/swarm.py` & `social/x_bot_interface.py`.
- **Observability & compliance:** Telemetry streams registered in `core/telemetry_manager.py`, persisted via `observability/` and escalated through `monitoring/`, `notifications/`, `audit/`, and `compliance/` modules. Governance agents enforce policy loops across the repo.

## Top-level README files

| File | Size (bytes) | Last modified (UTC) | Notes |
| --- | --- | --- | --- |
| README.md | 11726 | 2026-01-16T03:53:59.7176889Z | Primary project overview & onboarding guide. |
| README_CURRENT.md | 1898 | 2026-01-12T20:44:40.1399959Z | Snapshot of current sprint/focus items. |
