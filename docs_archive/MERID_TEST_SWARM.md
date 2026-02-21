# MERID Test Swarm Specification

## 1. Objectives

- Treat automated testing as a first-class swarm with the same autonomy and guardrails as build/runtime swarms.
- Increase coverage, mutation score, and incident-derived regression depth across all modules.
- Reduce human toil for boilerplate tests while keeping human approval for merges and critical risk/execution code.

## 2. Swarm Topology

| Layer | Purpose | Notes |
| --- | --- | --- |
| **ReAct Planner** | Plans design → code → tests → docs loops, breaks tickets into subtasks, assigns agents, monitors status. | Extends `swarm.dev_swarm_orchestrator.DevSwarmOrchestrator` with planner/thinking states and explicit hooks for testing subtasks before merge. |
| **Module Unit Agents** | Per-module agents focused on unit-test creation, mutation gaps, and heuristics like “changed lines without tests.” | Triggered per file diff; leverage coverage reports + mutation diffs. |
| **Integration Boundary Agents** | Watch API/event/DB boundaries, learn flows from traces, generate integration tests with captured fixtures. | Boundaries aligned with `core`, `api`, `observability`, `promotion` services. |
| **Self-Healing/Test Maintainer** | Monitors flaky tests, brittle locators, fixtures; classifies failures and proposes resilient rewrites. | Acts when flakiness score or failure frequency breaches thresholds. |
| **Telemetry & Risk Monitors** | Track coverage %, mutation scores, defect density; feed priorities back into planner. | Persist metrics into MetaAudit telemetry stream for governance visibility. |

## 3. Agent Roles & Capabilities

1. **Planner (ReAct)**
   - Inputs: ticket description, diff, coverage gaps, guardrail policies.
   - Loop: `THOUGHT → ACTION (call coder/tester/docs agents) → OBSERVATION (build/test results)`.
   - Can create temp branches, scaffold files, run targeted pytest suites via guardrails.
   - Requires human approval for merges and edits to `core/execution`, `risk`, `governance` directories.

2. **Unit-Test Agents**
   - One agent per major package (`core`, `governance`, `agents`, `observability`, `web`).
   - Responsibilities: read module AST + docs, infer behaviors, generate/extend unit tests until coverage and mutation thresholds hit (e.g., ≥90% statements, ≥70% mutation score).
   - Triggers: new/changed files, missing tests for new public functions, or code complexity increases.

3. **Integration/E2E Agents**
   - Boundaries: API endpoints, event bus, persistence, external integrations (Neo4j, telemetry).
   - Behavior: observe real traffic/traces (recorded via observability stack), synthesize replayable scenarios, run them in hostile twin/sim harness, verify invariants (idempotency, telemetry emission, audit trails).

4. **Self-Healing Maintainer**
   - Listens for flaky test alerts (telemetry, CI retries) and classifies root cause (app bug vs brittle test).
   - For brittle tests, rewrites locators/fixtures, adds waits/factories, or parameterizes data. Changes require reviewer sign-off.

5. **Test Discovery Agent**
   - Mines incidents, logs, MetaAudit directives for missing regression coverage.
   - Produces scenario specs stored under `tests/incidents/<incident_id>.py` with metadata linking back to source incident.

## 4. Guardrails & Autonomy Constraints

- **Command Execution**: all shell/file actions go through `swarm.command_runner` + policy engine. Planner may create branches, run `pytest`, `coverage`, `mutmut`, but cannot push/merge without human approval.
- **Critical Paths**: edits to `core/execution`, `risk`, `governance`, `hardening`, `reality` require explicit reviewer approval and MetaAudit notification.
- **Telemetry Binding**: every agent emits structured events (`test_swarm:*`) via TelemetryManager `meta_audit` stream for auditability.
- **Incident Hooks**: when MetaAudit issues directives referencing lack of tests, planner auto-creates tasks to remediate before promotions.

## 5. CI / Runtime Wiring

1. **Triggers**
   - Pre-PR: diff analyzer invokes unit agents for touched modules.
   - Nightly: coverage+mutation scan; integration agents replay top traffic flows.
   - Incident ingestion: on new incident/log anomaly, discovery agent adds regression task.

2. **Pipelines**
   - `test_swarm_plan` job: planner decomposes tasks, schedules agents, ensures design/code/tests/docs pipeline completion.
   - `test_swarm_execute` job: runs generated tests, collects coverage/mutation, stores artifacts.
   - `test_swarm_selfheal` job: monitors flaky list, runs maintainer fixes in sandbox branch.

3. **Metrics**
   - Coverage per module, mutation score, flaky test count, mean time to add regression after incident.
   - Published to observability dashboards and MAS KPI board for governance review.

## 6. Implementation Steps

1. **Scaffold Planner**
   - Extend `DevSwarmOrchestrator` with ReAct loop + task phases.
   - Add new TaskTypes (`UNIT_TEST`, `INTEGRATION_TEST`, `TEST_SELF_HEAL`).
2. **Agent Registry**
   - Define agent configs (capabilities, scopes) in `swarm/test_agents.py`.
   - Provide factories for unit/integration/maintainer/discovery agents.
3. **Tooling Hooks**
   - Coverage/mutation via `pytest --cov`, `mutmut`, recorded per agent.
   - Trace ingestion from observability stack (APM traces/logs) for integration agents.
4. **CI Integration**
   - Add GitHub Actions / internal CI workflows invoking planner jobs, gating merges on green `test_swarm_execute`.
   - Store self-healing proposals as pending PRs for human review.
5. **Telemetry & Docs**
   - Update TelemetryManager to register `test_swarm` stream.
   - Document procedures in `docs/TESTING_AUTONOMY.md` (link to this spec).

## 7. Autonomy & Human Workflow

- Humans focus on high-level design and reviewing swarm outputs (diffs, rationale, telemetry).
- Swarm handles repetitive scaffolding, regression maintenance, and risk-driven coverage improvements.
- All outputs are explainable via structured logs and MAS oversight, ensuring compliance and trust.
