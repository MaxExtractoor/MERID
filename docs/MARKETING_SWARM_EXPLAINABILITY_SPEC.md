# Marketing Swarm Explainability Specification

## Purpose

Explainability is a platform invariant in MERID. This specification makes it
explicit for the marketing swarm by describing schemas, enforcement hooks, data
flows, storage, and UX exposure so every campaign, segment, and spend decision
ships with auditable rationales.

## Core Principles

1. **Dual payload contract** – every marketing agent call must return both the
   action/result and a `DecisionRationale`. Raw predictions without rationale are
   policy violations.
2. **Structured, replayable context** – explanations capture inputs, features,
   rules, counterfactuals, constraints, and telemetry references so governance
   and observability can replay or audit any decision.
3. **Unified storage + surfacing** – explanations flow into the governance
   telemetry stream and are queryable via observability dashboards and marketing
   operator UIs.
4. **Policy enforcement** – missing or low-quality explanations raise
   `ExplainabilityViolation`, block rollout, and alert governance.
5. **Human-readable rationales** – natural-language reasons are mandatory and
   accompany numerical evidence for GTM, compliance, and customer-facing usage.

## Shared Schema

### `core/explainability.py`

- `DecisionRationale`: cross-domain explanation payload.
- `ExplanationContext`, `ExplanationRecord`, `ExplainableResult`: capture
  metadata, telemetry, and policy enforcement.
- `ExplainabilityService`: central recorder that sanitizes inputs via
  `DataAccessPolicy`, logs to telemetry (`governance` stream), and enforces
  coverage with `ExplainabilityViolation`.
- Telemetry log includes domain, decision_id, features, rules, constraints, and
  expected effects for downstream analytics.

### Marketing Extensions (`marketing_swarm/explainability.py`)

- `MarketingDecisionInputs`: canonical snapshot of segment traits, engagement,
  budget state, and compliance flags.
- `MarketingDecisionContext`: ensures every agent supplies agent/campaign IDs,
  segment metadata, channel, tool invocations, and alternatives considered;
  converts into `ExplanationContext` with expected effects (e.g., campaign +
  segment IDs).
- `MarketingDecisionExplanation`: human-readable reason + structured evidence;
  converts seamlessly into `DecisionRationale` so marketing agents auto-satisfy
  the platform contract.
- `MarketingExplainabilityAdapter.record_decision`: convenience wrapper that
  enforces rationale completeness, emits telemetry, and returns
  `ExplainableResult` so agent workflows can chain the result + explanation.

## Enforcement Hooks

1. **Agent-level**: marketing orchestrator must wrap every decision through
   `MarketingExplainabilityAdapter.record_decision`. Missing reason/features or
   rule evidence throws `ExplainabilityViolation` and halts the workflow.
2. **Governance stream**: every explanation is emitted to `TelemetryManager`
   (`governance` stream) for auditing. Observability dashboards can measure
   coverage percentage and highlight missing/low-quality entries.
3. **Policy checks**: governance workflows treat actions without explanations as
   policy violations. Observability stack should alert on campaigns whose spend
   crosses thresholds without corresponding explanation records.
4. **Replay**: stored `DecisionRationale` objects reference telemetry spans so
   operators can drill from UI panels to raw logs/traces.

## Storage & Surfacing

- Explanations live in-memory via `ExplainabilityService` and are expected to be
  persisted/exported by observability sinks (Elasticsearch, lakehouse, etc.).
- Observability dashboards (web/merid-ui) must expose “show your work” panels:
  feature attributions, constraints fired, counterfactuals evaluated.
- Governance reviewers receive links from incidents/approvals to the underlying
  records; marketing swarm UIs provide plain-language rationales for every
  campaign action.

## Marketing Swarm Workflow Expectations

1. **Segmentation decisions** record why a cohort was targeted, which metrics
   crossed thresholds, and which alternatives were rejected.
2. **Spend allocation** must log constraints (budget caps, risk ceilings) and
   show counterfactuals (e.g., variants A/B/C) with reasons for rejection.
3. **Messaging/personalization** explains tool invocations (e.g., LLM copy
   generation) and exposes the telemetry that backed the selection or pause.
4. **Incident handling**: if compliance flags or safety systems intervene, the
   explanation chain continues with updated rationales referencing governance
   overrides.

## Integration Checklist

- [ ] Update marketing swarm orchestrator to depend on
      `MarketingExplainabilityAdapter` for every action.
- [ ] Ensure marketing analytics/services write telemetry IDs so operator UIs
      can deep-link to logs.
- [ ] Extend observability dashboards with “Explainability Coverage” widgets and
      filters by campaign, segment, and channel.
- [ ] Wire governance incident reviews to require attached explanation record
      IDs before approval or resolution.
- [ ] Teach marketing agents to include counterfactuals + human-readable
      summaries in every explanation payload.

## Future Enhancements

- Persistent storage + query APIs (e.g., `observability/explainability_store.py`).
- Automated quality scoring of explanations (completeness, clarity).
- Explainability Swarm watchdog: agent that audits coverage, generates
  higher-level narratives for leadership, and ensures marketing actions stay
  policy-compliant.
