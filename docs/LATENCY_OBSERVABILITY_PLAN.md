# MERID Latency Observability Plan

## Goals

1. Provide unified visibility into latency budgets across trading, dev swarm, LLM, and social workflows.
2. Surface critical-path bottlenecks and fallback activations in dashboards.
3. Alert operators when SLOs breach or decision fallbacks engage repeatedly.

## Metrics

All metrics emitted on telemetry stream `latency` via `latency_optimizer.telemetry.emit_latency_metric`.

| Metric Name | Tags | Description |
| --- | --- | --- |
| `trading.tick_to_order` | `symbol`, `side`, `strategy` | End-to-end latency (ms) from tick ingestion through order submission. |
| `social.signal_gate` | `strategy_id`, `asset`, `version` | Latency for social signal evaluation + gating. |
| `dev_swarm.command_execution` | `task_id`, `agent_id`, `command` | Guardrail-protected command latency per dev task. |
| `llm.default_request` | `task_id`, `agent_id`, `task_type` | LLM request latency inside dev swarm tasks. |

### Derived Metrics (ObservabilityStack rollups)

- p50/p95/p99 latency per workflow (pre-aggregate via ObservabilityStack scripting).
- Critical-path length per trace (calculated by ObservabilityStack using latency probe spans).
- Fallback activations per workflow (count of latency decisions with `status in {"breached_slo", "deadline_violation"}` and `fallback` set).

## Dashboards

### 1. Latency Overview

- Multi-panel layout per domain (Trading, Social, Dev Swarm, LLM).
- Each panel: p50/p95 time series, heatmap by tag (symbol/strategy/task_type).
- Critical-path waterfall widget fed by trace spans to highlight bottlenecks.

### 2. Fallback Activations & Budget Burn-down

- Bar chart of fallback strategy counts per 1h window.
- Table of top offenders (workflow + tags) sorted by % over budget.
- Sparkline of remaining latency budget vs. observed latency for current window.

### 3. Social Signal Gate Health

- Gauge for `social.signal_gate` p95 vs. SLO (80 ms target).
- Table of slowest strategies/assets with links to logs/traces.
- Overlay chart showing correlation between latency spikes and deny decisions from `evaluate_social_trade`.

### 4. Dev Swarm Critical Path

- Timeline view of LLM + command spans per task.
- Distribution of command latency by guardrail decision.
- Alert feed for tasks flipped into fallback (cached diff) paths.

## Alerts

| Alert | Condition | Action |
| --- | --- | --- |
| Trading SLO Breach | `trading.tick_to_order` p95 > 12 ms over 5 min | Page trading ops (OpsGenie) + auto-create incident ticket. |
| Social Gate Degraded | `social.signal_gate` p95 > 80 ms for 3 consecutive windows OR fallback ratio > 0.3 | Notify social strategy lead via Slack + throttle low-priority ingestion. |
| Dev Swarm Latency Regression | `dev_swarm.command_execution` p95 > 750 ms for 10 min OR >5 fallback activations per hour | Page platform on-call + flip orchestrator into "fast" preset (lighter LLM, cached diffs). |
| LLM Latency Exhaustion | `llm.default_request` p95 > 3500 ms and fallback activations > 10% | Route to model serving team; trigger automatic routing to smaller model. |

## Explainability & Governance Integration

- **Explainability Records** – Every guardrail-enforced command now persists `latency_domain`, `latency_workflow`, `latency_status`, `latency_observed_ms`, and `latency_fallback_strategy` inside `core.explainability.ExplanationRecord`. This guarantees that incident reviews can correlate slow paths with specific guardrail decisions.
- **Command Execution Artifacts** – `swarm.dev_swarm_orchestrator.CommandExecutionRecord` mirrors the latency metadata so that task artifacts and audit trails show breach/fallback context even without querying telemetry backends.
- **Governance Reporting** – Latency metrics feed into Board-level MI via ObservabilityStack exports (total invocations, fallback counts, breach rates). Future quarterly reports will surface workflow-specific breach ratios alongside existing risk utilizations.

## Data Sources & Traceability

- Metrics: TelemetryManager (`latency` stream, HOT tier, 30-day retention).
- Traces: LatencyTracer spans accessible via ObservabilityStack trace explorer.
- Logs: Structured logs enriched with `latency_decision` in explainability records (see command runner integration).

## Next Steps

1. Wire ObservabilityStack metric scrapers to the `latency` stream.
2. Implement dashboards above in `web/templates/observability.html` and JS layer.
3. Configure alert rules in OpsGenie/New Relic per table.

## Validation & Regression Coverage

- `pytest tests/test_command_runner.py` – Verifies guardrail command execution records persist latency metadata (domain, workflow, status, observed_ms, fallback strategy) and guards against regressions in explainability propagation.
- Import-time checks for `trading.execution` now succeed after re-aligning async methods; this keeps latency decision keys flowing through the social gating pathway during test bootstrap.
