# MERID Autonomous SRE/DevOps Swarm Blueprint

A practical specification for deploying a 24/7 autonomous "dev team" that watches MERID, triages incidents, executes safe remediations, and escalates with full context under strict guardrails.

---

## 1. Scope of Autonomy

| Category | Examples | Autonomy Policy |
| --- | --- | --- |
| **Safe to automate (v0.1–v0.2)** | Restart crashed pods/services, enable/disable non-critical feature flags, scale replicas/resources within bounds, rotate logs/clear sandboxed disk space | Agent-executable, but only for whitelisted services & environments |
| **Recommend-only** | Code changes, infra re-architecture, strategy logic adjustments, contract parameters, production deploys affecting capital or risk | Agents produce playbooks + PRs; humans/governance must approve |
| **Out of bounds** | Direct on-chain transactions, private key access, bypassing governance, risk/custody parameter changes | Blocked for agents; escalate immediately |

Decision rule: if an action can impact capital, custody, compliance, or is novel → human-only. Otherwise, allow agent remediation only if a **tested playbook** exists.

---

## 2. Observability + Runbook Foundation

### Metrics, Logs, Traces
- Prometheus/Mimir for SLIs: availability, latency, error rate, resource usage, per-vault PnL/exposure/leverage, rebalance timeliness.
- Grafana dashboards for API health, strategy health, infra health, agent activity.
- Logs centralized via Loki/OpenSearch with searchable labels (`service`, `env`, `incident_id`, `agent_action`).
- Traces via Tempo/Jaeger for request-path debugging.

### SLO Examples
- API availability ≥ 99% / 30d; p95 latency < 500 ms; deposit/withdraw success ≥ 99.5%.
- Strategy correctness: balances vs on-chain match 100%; constraint adherence (exposure/leverage caps) enforced.
- Error-budget burn rules gate risky deploys.

### Runbooks & Playbooks
- Each incident type defined with: triggers, severity, metrics/log queries, diagnostics steps, remediation actions, verification criteria, escalation paths.
- Tag steps as `auto_allowed` vs `human_only`.
- Store runbooks in versioned repo + link via alert annotations.

---

## 3. Autonomous Swarm Roles

| Role | Responsibilities | Key Integrations |
| --- | --- | --- |
| **Watcher/Detector** | Subscribe to Prometheus/Alertmanager + logs; dedupe and cluster alerts into incidents; tag severity/impact | Prometheus HTTP API, Alertmanager webhooks, log search APIs |
| **Diagnoser/Analyst** | Pull recent metrics, logs, deploy diffs, config changes; match best playbook; propose root-cause hypothesis | Git history, CI/CD metadata, config registry, runbook DB |
| **Remediator** | Execute only whitelisted steps (restart, rollback last deploy, scale within caps); verify success; back off after N failures | Kubernetes API, Argo/Flux APIs, feature-flag service |
| **Escalation Agent** | When automation disallowed or fails, send structured PagerDuty event: impact, timeline, actions tried, next-step suggestions | PagerDuty Events API, Slack/Teams bridge |
| **Improver/Optimizer** | Periodically review incidents, alert noise, SLO burn; propose alert tuning, runbook updates, tooling upgrades | Analytics DB, runbook repo, Tool-Scout interface |

---

## 4. Guardrails (Policies, Auth, Environments)

### Policy-Driven Actions
- Map each playbook step to policy rules (who/where/when). Example YAML:
  ```yaml
  action: restart_service
  service: merid-status-api
  env: staging
  auto_allowed: true
  max_frequency: 2 per 30m
  verification: http_2xx_rate > 99% for 5m
  ```
- Only allow prod automation for incidents with proven success history and low blast radius.

### Auth & RBAC
- Per-agent OAuth2 client credentials (short-lived JWTs) and optional mTLS certs.
- Example scopes: `metrics.read`, `logs.read`, `config.read`, `k8s.restart:dev`, `deploy.rollback:staging`, `pagerduty.trigger`.
- Context-aware checks: environment, incident severity, playbook ID, time.
- All actions logged with agent ID, inputs, outputs.

### Environment Strategy
1. **Dev** – full autonomy for whitelisted actions.
2. **Staging** – autonomous restarts/rollbacks/scaling with tighter caps.
3. **Prod** – extremely narrow set (known safe restarts) + strict verification and auto-rollback; everything else escalated.

---

## 5. Implementation Phases

1. **Phase 0 – SRE Baseline**: finalize SLOs/SLIs, alert rules, runbooks; connect Prometheus + Grafana + PagerDuty.
2. **Phase 1 – Advisory Agents**: agents ingest alerts, produce diagnostics & recommended commands; humans execute.
3. **Phase 2 – Dev/Staging Auto-Remediation**: whitelist restart/scale/rollback actions; agents execute + verify in non-prod.
4. **Phase 3 – Narrow Prod Autonomy**: allow a handful of low-risk playbooks in prod under policy + SLO guardrails.
5. **Phase 4 – Continuous Learning**: incident outcomes feed back to improve runbooks, alerts, and policies; Tool-Scout agents evaluate OSS improvements.

---

## 6. Decision Matrix (Template)

| Impact | Playbook | Novelty | Confidence | Outcome |
| --- | --- | --- | --- | --- |
| Funds/Security | Any | Any | Any | Human-only |
| Infra-only | Tested | Known | High | Agent-execute |
| Infra-only | Draft | Known | Medium | Agent-recommend |
| Infra-only | None | New | Any | Human-only |

Implementation: encode matrix evaluation in incident schema so policies can check fields directly.

---

## 7. Escalation Windows & PagerDuty Integration

### Severity Bands
- **Sev1 (capital/security):** no auto-remediation; immediate PagerDuty page.
- **Sev2 (user-visible outage):** agents try ≤5 min of safe actions; if unresolved, trigger PagerDuty level 1; escalate to level 2 after +10 min.
- **Sev3 (degraded/non-critical):** agents attempt for up to 30 min; notify via low-urgency channel if still open.
- **Sev4 (noise/info):** no paging; ticket/log only.

### PagerDuty Flow
1. Agents send Events API `trigger` with routing key matched to service.
2. Include `custom_details`: metrics snapshots, deploy IDs, playbook ID, actions run.
3. Use `dedup_key` per incident for acknowledge/resolve updates.
4. PagerDuty policies map severity to on-call schedules (SRE, backend, strategy/risk).
5. Human notes feed back to runbook updates.

---

## 8. Tooling Checklist

- **Monitoring**: Prometheus + Alertmanager; Grafana dashboards; Tempo/Jaeger for traces.
- **Logging**: Loki/OpenSearch with dashboards showing agent actions.
- **CI/CD**: GitHub/GitLab Actions or Jenkins for build/test; Argo/Flux for deploy/rollback automation.
- **Incident Mgmt**: PagerDuty (or incident.io) for escalation workflows.
- **Agent Platform**: LangGraph, CrewAI, AutoGen, or similar multi-agent framework with MCP/tool discovery for new OSS integrations.
- **Runbook Store**: Git repo (Markdown/YAML) + searchable index; annotate alerts with runbook IDs.

---

## 9. RBAC Policy Examples

| Agent Role | Dev | Staging | Prod |
| --- | --- | --- | --- |
| Watcher | `metrics.read`, `logs.read` | same | same |
| Diagnoser | watcher scopes + `config.read` | same | same |
| Remediator | `k8s.restart:*`, `scale.adjust:bounded`, `deploy.rollback:last` | `k8s.restart:allowlist`, `scale.adjust:bounded`, `deploy.rollback:last` | `k8s.restart:critical-services` only |
| Deploy-Intent | `deploy.intent:dev` | `deploy.intent:staging` | none (requests go through governance) |
| Tool-Scout | `repo.read`, search/web tools | same | same |

All scopes expire quickly (minutes); tokens tied to incident context.

---

## 10. Converting Runbooks to Playbooks

1. **Define triggers** (`expr`, `for`, severity, impacted services) and annotate alerts with `playbook_id` + `auto_allowed` flag.
2. **Encode workflow** as state machine (YAML/JSON) with states: `diagnose`, `action_n`, `verify`, `success`, `escalate`.
3. **Implement verification checks** (metrics returning to normal for N minutes, absence of errors, etc.).
4. **Log every action** with incident ID, command, result, next state.
5. **Post-incident review** updates playbooks + automation eligibility.

---

## 11. Dashboards & Analytics

- **Agent Activity Dashboard**: incidents handled (auto vs manual), success/failure rate per action, MTTR comparisons.
- **Incident Overview**: open incidents by severity/service, time-to-detect/mitigate/resolve segmented by agent vs human.
- **Agent Logs View**: Grafana panels for `agent-action`, `agent-error`, `agent-escalation` streams.

Use dashboards for audit + tuning; alerts still come from Prometheus/Alertmanager.

---

## 12. Next Steps for MERID

1. Finalize SLOs, alert rules, and runbooks (Phase 0) and store them in `runbooks/` with IDs.
2. Instrument services with Prometheus metrics covering infra + business KPIs.
3. Stand up PagerDuty services/policies aligned to MERID modules.
4. Implement advisory-only agents (Phase 1) hooked into observability + PagerDuty.
5. Gradually enable automation in dev/stage, then tightly scoped prod paths once success data exists.
6. Capture all agent actions in audit logs + dashboards; review weekly to adjust policies and expand safe autonomy.

This blueprint gives a concrete path to a 24/7 autonomous dev/SRE swarm that augments MERID while keeping capital, security, and governance firmly under human control.
