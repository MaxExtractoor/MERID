# MERID Dev Swarm Specification

_Last updated: 2026-01-17_

MERID’s development swarm focuses on reliability, observability, and guardrails—not sheer agent count. This spec defines the core roles, shared capabilities, safety model, and operational workflows for a compact crew that can deliver explainable changes across code, tests, infra, and telemetry.

---

## 1. Core Roles & Responsibilities

| Role | Responsibilities | Interfaces |
| --- | --- | --- |
| **Orchestrator / Dev Lead** | Translates intents (e.g., “fix social-strategy syntax errors, get tests green”) into concrete task graphs; sequences agents, tracks progress, enforces guardrails, and provides status to humans. | Workflows registry, approval queue, explainability log, CI triggers |
| **Code & Refactor Agent** | Implements refactors, features, dead-code removal, type fixes, doc updates. Ensures every code change references tests/docs and follows MERID safety boundaries (no secret leakage, no policy violations). | Repo tree, code search/index, `.env.example` + audits (read-only), explainability service, diff generator |
| **Test & Safety Agent** | Owns unit/integration/prop/safety tests; triages failures; proposes minimal fixes; keeps suites like social-strategy and safety_ci green; flags hacks that weaken guardrails. | `tests/`, `run_tests.py`, CI logs, safety harness (breach detection, kill-switch) |
| **Observability & Perf Agent** | Ingests logs/traces/metrics (observability/, monitoring/), identifies hotspots, flaky paths, and regression sources; suggests code-level fixes and telemetry enhancements. | Telemetry manager, ObservabilityStack APIs, metrics dashboards |
| **Infra / DevOps Agent** | Manages CI/CD configs, ephemeral envs, env var wiring; keeps pipelines deterministic; aligns `.env.example` + `MERID_ENV_AUDIT.md` across environments; proposes (never auto-runs) destructive infra changes. | `infra/`, `deployment/`, `scripts/`, env audit, secrets registry |

---

## 2. Unified Context Layer

Each agent works atop a shared context service providing:

1. **Repo topology** – `MERID_REPO_TREE.txt`, `.SUMMARY`, README inventory for targeted navigation.
2. **Code search + embeddings** – access to `tmp/env_var_refs.txt`, architecture summaries, module overviews.
3. **Env & secret audit** – `.env.example`, `MERID_ENV_AUDIT.md`, rotation guidance (read-only). Production secrets live outside git.
4. **Telemetry hooks** – ability to log structured rationales via `core.explainability` + `TelemetryManager` for every substantive action.
5. **Intent log** – orchestrator records the human intent, decomposition, and agent assignments for auditing.

---

## 3. Safety & Guardrails

### 3.1 Approval Workflow

- **Destructive/privileged ops** (DB migrations, wallet/treasury actions, infra deletes) must be emitted as proposals requiring explicit human `GO` before execution.
- **Environment mutations** (writing `.env`, touching secrets) are forbidden; agents update `.env.example` or docs only.
- Every action logs: agent, rationale, files touched, tests run, approvals referenced.

### 3.2 Command Sandbox

- Agents run commands via orchestrator-approved templates (e.g., `pytest tests/test_social_strategy_integration.py`), with resource/time caps.
- CI integration allows scoped runs (single module, lint, py_compile) to minimize noise.
- Observability agent can query logs/metrics but cannot modify prod telemetry configs without approval.

### 3.3 Explainability Contract

- Use `ExplainabilityService.record_explainable_result` for major changes.
- Reward vectors (per `reward_design.md`) tie into explainability records so governance can trace which agent did what and why.

### 3.4 Guardrail Matrix

| Surface | Prohibited Actions | Required Safeguards | Escalation |
| --- | --- | --- | --- |
| Databases / Treasury | Direct writes, migrations, key export | Proposal-only + human approval; dry-run scripts; checksum verification | Immediate human owner paging + governance ticket |
| Secrets / `.env` | Editing real `.env`, printing secrets | Use `.env.example`, env audit; mask outputs | Security lead notification |
| Infra / CI runners | Destroying runners, altering prod pipelines | PR + approval; CI dry-run; rollback plan | DevOps owner approval |
| Telemetry | Disabling monitoring, deleting logs | Read-only for agents; config changes through change board | Observability lead review |
| External APIs | Live trading/marketing actions | Sandbox creds; feature flags; recorded intent | Business owner approval |

Agents must include guardrail references in explainability logs (e.g., "Guardrail: Secrets-001").

### 3.5 Escalation Flow

1. Agent detects risky intent → mark task **Escalated**.
2. Orchestrator bundles rationale, diffs, test evidence, guardrail mapping.
3. Human approver receives package via governance queue, must respond `GO/NO-GO`.
4. Post-action, orchestrator records verification evidence (tests, telemetry snapshots) and closes the escalation ticket.

---

## 4. Workflow Examples

### 4.1 Bug Fix (Social Strategy Tests)

1. **Intent** – human or orchestrator issues task: “Fix `test_social_trade_evaluation_success`”.
2. **Plan** – orchestrator decomposes into analysis → code change → targeted tests → summary.
3. **Execution** – Code agent patches `social/social_aware_quant.py`; Test agent runs scoped `pytest tests/test_social_strategy_integration.py`; Observability agent inspects recent telemetry for related errors.
4. **Explainability** – Each step logs rationale + diff summary; orchestrator compiles final report (files changed, tests run, metrics).

### 4.2 Infra Change (CI Pipeline tweak)

1. Infra agent drafts modifications to `.github/workflows/*` or `run_tests.py` to parallelize suites.
2. Test agent validates by running relevant matrix locally.
3. Governance requires human approval before merging because pipelines affect prod.
4. Explainability log references reward components (performance gain vs. safety coverage).

---

## 5. Required Integrations

1. **CI/CD Hooks** – Agents can trigger dry-run workflows, read artifacts/logs, and annotate failures.
2. **Observability APIs** – Access to `observability/observability_stack.py` telemetry outputs, metrics snapshots, and log queries.
3. **Safety Harness** – Interface with breach detection, kill-switch, compliance modules for regression checks.
4. **Documentation Sync** – auto-link code changes to docs (e.g., update `MERID_REWARD_AND_AGENCY_CHARTER.md` when reward logic changes).
5. **Metrics & SLOs** – Observability agent exports swarm health metrics (mean time to fix tests, % tasks with explanations, guardrail violation count) into dashboards.

### 5.1 CI/Test Coupling

- Standard command catalog (pytest module, `pyproject lint`, `mypy subset`, `npm test -- web`), each with resource budgets.
- Test agent records: command, exit code, duration, failing tests, remediation steps.
- If a command exceeds limits, orchestrator pauses and requests human input (no infinite loops).
- Infra agent keeps cached envs aligned with `.env.example`; any mismatch triggers audit alert.

### 5.2 Observability Dashboard Integration

- **Metrics surfaced**: test pass rate, MTTR (mean time to repair), % tasks with DecisionRationale, guardrail violations, escalations pending, CI duration deltas.
- **Dashboards**:
  - `observability/dashboard_dev_swarm.json`: panel definitions for Grafana/Chronograf.
  - Drill-down links to telemetry traces and reward vectors.
- **Data pipeline**:
  1. Orchestrator emits structured events (`dev_swarm.metric`, `dev_swarm.escalation`).
  2. Observability agent writes to telemetry streams (`governance`, `strategy`).
  3. Dashboards query via `ObservabilityStack.get_dev_swarm_metrics()`.
- **Alerting thresholds**:
  - MTTR > 6h (warning), > 12h (critical).
  - Explanation coverage < 95%.
  - Guardrail violations ≥ 1 per 24h → immediate pager to governance lead.
- **Audit trail**: dashboard panels link back to intent IDs and explainability record IDs.

---

## 6. Logging & Auditability

- Every agent action recorded with: timestamp, intent ID, files touched, tests executed, approvals, structured explanation ID.
- Logs stored in `analytics/rewards/records/` + governance dashboards for traceability.
- Failed or aborted actions include reason + rollback state.
- Observability agent publishes weekly swarm KPIs: test pass rate, mean time to repair, # escalations, explainability coverage.

---

## 7. Future Enhancements

1. **Explainability watchdog** – monitors dev swarm outputs for missing rationales or failed tests.
2. **Automated diff reviewers** – static analyzers that comment on risky changes before human review.
3. **Adaptive scheduling** – orchestrator adjusts agent focus based on telemetry (e.g., allocate more cycles to Test agent when failure rate spikes).
4. **Human-in-the-loop dashboards** – single pane showing intents, status, explainability logs, reward vectors, and approval needs.
5. **Chaos drills** – scheduled resilience tests where orchestrator simulates failures (CI outage, flaky tests) to ensure escalation flow works.
6. **Policy-as-code** – encode guardrails in `core/policy_engine.py` so agents get programmatic allow/deny signals.

### 7.1 Policy-as-Code Interface

- **Module**: `core/policy_engine.py` provides:
  ```python
  class PolicyDecision(Enum):
      ALLOW = "allow"
      REQUIRE_APPROVAL = "require_approval"
      DENY = "deny"

  @dataclass
  class GuardrailContext:
      surface: str
      action: str
      metadata: Dict[str, Any]
      agent_id: str
      intent_id: str

  def evaluate_guardrail(context: GuardrailContext) -> Tuple[PolicyDecision, str]:
      ...
  ```
- **Inputs**: guardrail matrix entries (IDs, prohibited actions, escalation rules) stored in YAML/JSON under `policy/guardrails.yml`.
- **Outputs**: decision + rationale string (e.g., "Guardrail Secrets-001: editing real .env is forbidden"). Orchestrator logs rationale in explainability record.
- **Integration**: before executing any command/change, agent calls `evaluate_guardrail`; `REQUIRE_APPROVAL` triggers escalation flow; `DENY` blocks action.
- **Testing**: add policy unit tests ensuring surfaces map correctly and regressions fail CI.
