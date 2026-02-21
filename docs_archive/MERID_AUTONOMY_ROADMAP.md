# MERID Autonomy Roadmap

A staged plan for taking MERID from launch to a self-evolving, swarm-governed platform. Each maturity level lists the minimum feature set, success metrics, controls, and recommended open-source/free-tier tooling.

---

## Stage 0 — Launch-Ready (v0.1) Baseline

### Objectives
- Ship a **single, safe vault** with deposit/withdraw queue, rate limits, pause/kill-switch, and transparent accounting.
- Run **one low-risk automated strategy** per supported chain (e.g., conservative LP or basis trade) with paper-trade → small live path.
- Provide **radical transparency**: PnL/exposure dashboards, event logs, explainable assistant.
- Enforce a **governed change path**: PR → review → multisig/DAO for any fund-impacting change.
- Deploy a **read-only MERID assistant** that explains state/risk but cannot execute transactions.

### Minimum Feature Checklist
| Area | Requirements |
| --- | --- |
| Capital & Strategies | Vault contracts (caps, pause, kill-switch), simple strategy adapters, backtest/paper-trade harness, limited live deployment. |
| Observability | Metrics for PnL, exposure, latency, errors; logs for services/contracts; Grafana dashboard + alerts on drawdown/vault anomalies. |
| Governance | Multisig/DAO approval for parameters & releases; configuration registry vs ad-hoc edits. |
| Swarm v0 | Read-only agent roles accessing metrics/logs/state; ability to draft configs/PRs but no merges/deploys. |
| CI/CD & Infra | GitHub/GitLab Actions or Jenkins for build/test; Argo CD/Flux for GitOps deploys into dev/stage; Terraform/k8s manifests under version control. |

### Success Metrics
- **Safety:** zero user-fund incidents; 100% fund-impacting changes go through governance.
- **Reliability:** ≥99% availability on core API/dashboard; <0.1% error rate on deposit/withdraw/view flows.
- **Observability:** 100% of vaults report PnL/exposure; incident-to-alert time < target (define internally).
- **Assistant Usefulness:** ≥90% accuracy answering “positions/risk/actions” test set without manual log review.

---

## Stage 1 — Minimum Foundations (You Build)

MERID cannot self-evolve until fundamentals exist.

### Architecture & Boundaries
- Explicit module ownership (trading, risk, data, infra, governance, UI) with documented responsibilities and invariants.
- Constitution of **must-never-break rules** (custody, governance, security, observability, ethics/MEV) embedded in code and docs.

### DevOps & Infra Baseline
- CI/CD with unit/integration/security tests.
- IaC for environments (dev/stage/prod) + reproducible rollbacks.
- Monitoring/alerting with Prometheus + Grafana, logs in Loki/OpenObserve, traces via Tempo/Jaeger.
- Secrets & deployment credentials in HSM/secret manager.

### Deliverables
1. **Execution & Risk Layer:** contracts + off-chain services enforcing limits, liquidation logic, kill switches.
2. **Data & Telemetry Layer:** unified schemas + APIs for on-chain, market, and log data; OTEL instrumentation.
3. **Agent Framework Skeleton:** role registry, tool interfaces, secure messaging hooks.
4. **Governance Backbone:** multisig/DAO, parameter registry, upgrade playbooks.

Open-source defaults: Prometheus/Grafana/Loki/Tempo, GitHub Actions/GitLab CI/Tekton, Terraform + Argo/Flux CD, LangGraph/AutoGen/CrewAI for swarm orchestration.

---

## Stage 2 — Assisted Development (AI builds 30–60%)

### Preconditions
- Stable service templates, contract/vault patterns, coding standards, and linting enforced in CI.
- High-coverage tests on all critical paths (contracts, risk, routing, accounting).
- “Playbook” for end-to-end features (strategy → infra → UI) checked into repo.

### Capabilities
- Agents open PRs, edit configs/IaC, trigger CI jobs, and attach results.
- Automated checklists/release gates (No-Skips QA Orchestrator, breach detection, TruthGate, etc.).
- Change-classification policy defining auto-merge vs human-review vs governance-required changes.

### Tooling Enhancements
- **Tool-Scout Swarm** constantly hunts OSS/free CI/CD, observability, infra, and agent frameworks, producing proposal PRs with license/cost analysis.
- **Dynamic Tool Discovery** patterns (MCP/tool finder) so agents can register and use new tools safely.

### KPIs
- ≥80% of routine code/config updates pass CI on first attempt.
- Median human review time decreases as agents shoulder routine changes.
- OSS adoption backlog continuously triaged with swarm-generated reports/PoCs.

---

## Stage 3 — Self-Evolving / Autonomous Loop

### Core Systems
- **Swarm Lab + Orchestrators**: agents propose features/refactors, generate code/tests/infra, run simulations, stage/canary deploys, and emit Go/No-Go reports.
- **Guardrailed Autonomy**: policy engine allowing auto-ship of low-risk change classes (docs, dashboards, metrics) while high-impact work still requires governance.
- **Continuous Drift Detection**: config/code/behavior drift monitors triggering swarm remediation (LLM behavioral regression, drift pipeline, explainability storage, breach detection).
- **Closed-Loop Metrics**: experiments, telemetry, and incident data feed back into model prompts and tool routing.

### Human Role Shift
- Humans become **architects/governors**: define goals, constraints, incentives; approve high-impact changes.

### Automation Gates
- Auto-rollback for health/SLO breaches, canary + staged rollouts fully scripted.
- Deployment intents signed by agents, verified by policy engine, executed via CI/CD with HSM-held credentials.
- Agents operate within RBAC/ABAC framework and audited messaging fabric (mTLS + OAuth2 scopes).

---

## Supporting Pillars

### 1. Agent Security & RBAC
- **Identity:** per-agent OAuth2 client credentials (short-lived JWT access tokens) and/or mTLS certs (rotated 90–180 days).
- **Scopes:** `metrics.read`, `logs.read`, `vault.read`, `repo.write:dev`, `ci.trigger:dev`, `deploy.intent:stage`, etc., always environment-aware.
- **Context-Aware RBAC:** “Agent A may perform action X on resource R in context C (tenant, env, task, time).”
- **Time-Bounded Permissions:** repo write, CI triggers, prod metrics access, deployment intents all expire after the task/session.
- **Logging & Audit:** every agent action recorded (who/what/when/where) with anomaly detection.

### 2. Secure Agent-to-Agent Messaging
- Mutual TLS for all RPC, plus signed envelopes (Ed25519/ECDSA) with nonce/timestamp replay protection.
- Policy gateway/mesh (e.g., Dapr + Envoy/Istio) enforcing authZ, rate limits, scope policies.
- Full audit trail + retention in observability stack.

### 3. Observability Stack (OSS/Free Tier)
- Metrics: Prometheus or Mimir; dashboards in Grafana.
- Logs: Grafana Loki or OpenObserve.
- Traces: Jaeger or Grafana Tempo via OpenTelemetry.
- Alerting tied to incident management + anti-silent-failure agents.

### 4. CI/CD & Environments
- Build/Test: GitHub Actions, GitLab CI, Jenkins, or Tekton (K8s-native).
- Deploy: Argo CD or Flux CD for GitOps; canary + rollback baked in.
- Envs: dev → staging → prod with policy-controlled promotions; signed releases, IaC for clusters/nodes/contracts.

### 5. Training Data & Feedback
- Git + Infra history mapped to incidents/outcomes.
- Runtime/trading metrics with labels on “good vs bad” deploys.
- Human review artifacts (PR comments, Go/No-Go decisions, incident RCAs).
- Swarm uses telemetry as experience replay to refine prompts, routing, and tool selection.

### 6. OSS/Free-Tier Mandate
- Standing objective: always hunt open-source/free CI/CD, observability, infra, and agent tooling.
- Tool-Scout crew: research → evaluate → integrate via PoC branches with benchmarks.

### 7. Image/Multimodal Capability (Optional but Planned)
- **Backend:** self-hosted diffusion/SD models on GPUs or APIs (OpenAI, Stability) behind internal gateway.
- **Agent Roles:** prompt sanitizer, image generator, post-processor with structured `generate_image` tool schema.
- **Safety:** prompt/output filters, watermarks/metadata, prohibited-content policies, audit logs.
- **Infra:** GPU quotas, queues, caching; separation from trading workloads.
- **Use Cases:** dashboards, governance reports, gamified quests (NFTs/badges), UX illustrations.

---

## Stage Gates & KPIs Summary

| Gate | Key Evidence |
| --- | --- |
| **Stage 0 Exit** | Safe vault live, dashboards & alerts operational, governance approvals functioning, assistant answering transparency queries. |
| **Stage 1 Exit** | Stable module architecture, CI/CD+IaC baseline, OTEL observability, agent framework skeleton, governance + security invariants enforced. |
| **Stage 2 Exit** | Playbooks + templates in repo, high test coverage, change-classification policy live, Tool-Scout swarm producing accepted proposals, majority of routine updates AI-authored under supervision. |
| **Stage 3 Entry** | Swarm Lab orchestrating feature lifecycle, guardrailed autonomy policy engine live, autonomous drift detection/remediation, deployment intents + signed releases working, humans primarily governing high-impact changes. |

---

## Next Recommended Artifacts
1. `docs/merid_v0_1_spec.md` — canonical launch scope & KPIs.
2. `docs/merid_agent_security.md` — OAuth2/mTLS, RBAC scopes, rotation cadences.
3. `docs/merid_tool_scout_spec.md` — roles/prompts/workflows for OSS discovery.
4. `docs/merid_image_swarm_prompt.md` — safety-gated multimodal agent contract.

Each artifact should reference this roadmap and tie checklist items to specific repositories, CI pipelines, and governance processes.
