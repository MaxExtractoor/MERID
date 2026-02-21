# Phase 8 Analytics Under Production Governance

## Phase 8 Goal and Scope

**Goal**: Add an **Analytics lane** (signals, reports, model outputs) as a first-class, governed domain feeding the strategy lane, with **no silent quality failures**.

**Scope (initial)**:
- Signal generation for existing strategies (no automatic new strategies)
- Reporting/monitoring analytics (PnL, risk, venue health) that inform decisions but don't directly move capital
- All analytics outputs treated as **typed contracts** consumed by strategy

## Analytics SLIs and SLOs

### Core SLIs

- **Report Freshness**: Fraction of analytics artifacts delivered within freshness target (e.g., last N minutes)
- **Signal Latency**: p50/p95/p99 time from "raw data available" → "signal available to strategy"
- **Prediction/Feature Correctness**: Fraction of outputs passing schema + sanity checks (no NaNs, in expected ranges)
- **Prediction Quality** (where measurable): Rolling accuracy / calibration vs ground truth (e.g., hit rate, Brier score bucket)

### Initial SLOs (Phase 8, 30-day window)

- **Freshness SLO**: 99.9% of scheduled reports/signals available within 2 minutes of schedule
- **Latency SLO**:
  - 99% of signals ≤ 200 ms from trigger to publish
  - 99.9% ≤ 500 ms (Phase-7-aligned budgets)
- **Correctness SLO**: 99.99% of outputs pass schema + range checks; any violation is Sev-0 for Analytics
- **Quality SLO** (where labels exist): ≥95% hit-rate or "in band" behavior over the evaluation window, with explicit error budget for quality regressions

## Error Budgets and Burn Rates (Analytics)

### Budget Calculations

- **Freshness/Latency Budgets**: 99.9% → 0.1% budget; apply same 30-day window as Phase 7
- **Correctness Budget**: 99.99% → 0.01% budget; extremely small, treated almost like "no errors allowed"

### Burn-Rate Policy (same pattern as Phase 7)

- **Fast-Burn Alert**: 30-60 min window, burn rate ≥ 10 → incident + freeze analytics changes
- **Slow-Burn Alert**: 6-12 h window, burn rate ≥ 1 → investigation, schedule remediation
- **Budget Exhausted**: Pause Analytics-driven automation or downgrade to "advisory only" until review

## Constraints and Coupling to Strategy

### Analytics Constraint Envelope

- **Performance**: Obey the Phase-7 latency budgets end-to-end (so Analytics never becomes the bottleneck)
- **Resource**: CPU/memory ceilings per Analytics worker to avoid starving strategy/execution
- **Data**: Strict schema validation and backpressure if upstream data is incomplete or corrupt

### Integration Contract with Strategy

**All analytics outputs versioned and typed**: `{signal_type, version, schema_hash}`

**Strategy lane only consumes signals when**:
- Analytics freshness SLO is green over recent window
- Correctness SLO is green (no recent schema/range failures)
- No active Analytics Sev-0/Sev-1 incidents

**Degradation Modes**:
- If Analytics SLOs are breached or budgets heavily burned:
  - Strategy falls back to "baseline mode" (e.g., simpler rules, or ignore certain signals)
  - This is explicit behavior, not an implicit partial failure

## Phase 8 Executor and Promotion Gates

### `run_phase8_analytics_lane.py` Responsibilities

- Enforce Analytics-specific constraints (performance, resource, data checks)
- Emit SLIs to the existing SLO/error-budget framework and tracking tables
- Publish a clear contract object per cycle: `{freshness_ok, correctness_ok, quality_ok}`, which the strategy lane uses as gate inputs

### Promotion Gates (from Phase 8 → "governed Analytics lane")

Over a defined Phase-8 trial window (e.g., 2-4 weeks):

**SLO Compliance**:
- Freshness ≥99.9%, latency ≥99% within targets, correctness ≥99.99%

**Error Budgets**:
- <50% of any Analytics budget consumed, no fast-burn incidents left unresolved

**Incidents**:
- No unmitigated Sev-0, limited Sev-1 incidents with documented fixes

**Impact**:
- Demonstrated improvement in strategy lane metrics when Analytics signals are "on" vs "off" (e.g., better risk use, latency, or P&L stability), even if not yet gating

## Incident Response for Analytics-Driven Issues

### Triggers

- Analytics SLO breach (freshness, correctness, quality)
- Downstream strategy P&L or behavior showing clear correlation to Analytics anomalies

### Standard Actions

- Immediately mark Analytics as "degraded"; strategy switches to baseline mode
- Investigate data sources, feature pipelines, and model outputs
- Only re-enable "full Analytics influence" when SLOs, budgets, and tests are back to green

## Analytics Task Backlog

### Signal Generation Tasks

- `phase8_analytics_signal_generation`
  - Title: Production signal generation with freshness guarantees
  - Module: swarm/analytics
  - Risk Level: medium
  - Baseline Hours: 3.0
  - Constraints: [freshness_2min, latency_200ms, schema_validation]

- `phase8_analytics_feature_pipeline`
  - Title: Feature pipeline with data quality enforcement
  - Module: swarm/analytics
  - Risk Level: medium_high
  - Baseline Hours: 3.5
  - Constraints: [data_quality_checks, backpressure_handling, resource_limits]

### Reporting Tasks

- `phase8_analytics_risk_reporting`
  - Title: Real-time risk analytics and reporting
  - Module: swarm/analytics
  - Risk Level: medium
  - Baseline Hours: 2.5
  - Constraints: [report_freshness, accuracy_validation, strategy_integration]

- `phase8_analytics_performance_monitoring`
  - Title: Analytics performance monitoring and SLO tracking
  - Module: swarm/analytics
  - Risk Level: medium
  - Baseline Hours: 2.0
  - Constraints: [slo_tracking, error_budget_monitoring, contract_publishing]

## Execution Plan

### Week 1-2: Analytics Foundation
- Focus: Signal generation and feature pipeline setup
- Tasks: `phase8_analytics_signal_generation`, `phase8_analytics_feature_pipeline`
- Target Hours: 6.5
- Risk Profile: Medium

### Week 3-4: Integration and Monitoring
- Focus: Strategy integration and performance monitoring
- Tasks: `phase8_analytics_risk_reporting`, `phase8_analytics_performance_monitoring`
- Target Hours: 4.5
- Risk Profile: Medium

## Analytics ROI Requirements

### Mandatory Fields
- task_type, risk_level, analytics_constraints, slo_metrics, error_budget_usage, contract_status, evidence_links

### Task Type Values
- signal_generation, feature_pipeline, risk_reporting, performance_monitoring

### Batch ID
- phase8_analytics_lane

### Analytics-Specific Metrics
- freshness_percent, latency_ms, correctness_percent, quality_score, contract_compliance, strategy_integration_status

## Joint Lane Integration

### Contract Publishing
- Analytics publishes contract object each cycle
- Strategy consumes only when contract is valid
- Joint SLO monitoring across lanes

### Error Budget Integration
- Analytics errors contribute to joint error budget
- Fast-burn in Analytics triggers joint incident response
- Recovery requires both lanes to be healthy

### Kill Switch Integration
- Analytics degradation triggers strategy fallback
- Joint kill switch can halt both lanes
- Recovery requires coordinated restart

## Promotion Checklist

### Requirements
- Two consecutive passes of all Analytics gates
- Joint SLO compliance with strategy lane
- Demonstrated positive impact on strategy metrics
- Analytics error budgets well within limits
- No unmitigated Analytics incidents
- Strategy fallback mode tested and validated
- Phase 8 completion report generated

## Success Metrics

### Primary Metrics
- Analytics SLO compliance ≥99.9%
- Error budget usage <50%
- Strategy improvement with Analytics signals
- Zero unmitigated Analytics incidents

### Secondary Metrics
- Signal freshness consistency
- Feature pipeline reliability
- Reporting accuracy and timeliness
- Contract validation success rate

## Next Steps

### Immediate
- Implement Phase 8 executor with Analytics constraints
- Set up Analytics SLO tracking and error budgeting
- Create contract publishing mechanism

### Short-term
- Run Phase 8 trial with strategy integration
- Validate fallback modes and incident response
- Generate Phase 8 completion report

### Long-term
- Promote Analytics to governed lane
- Expand Analytics scope (new signal types)
- Consider fourth domain integration
