# Phase 9 Risk/Capital Management Domain

## Phase 9 Goal and Role

**Goal**: Turn **risk and capital allocation** into a first-class lane that issues binding guardrails and allocation contracts, not ad-hoc rules.

**Role**: Make every unit of capital subject to explicit, measurable constraints (limits, drawdowns, concentration, VaR), enforced with the same SLO/error-budget rigor applied to strategy, execution, and analytics.

## Core SLIs and SLOs for Risk Lane

### SLIs

- **Capital Allocation Correctness**: Fraction of allocations that match intended constraints (venue, asset, size bounds)
- **Risk Limit Compliance**: Proportion of trades/positions that remain within risk limits (exposure caps, VaR, drawdown, concentration)
- **Guardrail Response Time**: Time from limit breach condition to risk lane action (signal or halt)
- **Capital Efficiency**: Utilization of allowed risk capital vs caps (useful exposure / allowable exposure)

### Initial SLOs (30-day window)

- **Allocation Correctness**: ≥99.9%
- **Risk Limit Compliance**: 100% (any breach is Sev-0 and consumes budget)
- **Guardrail Latency**: 99% ≤ 100ms, 99.9% ≤ 200ms from breach to signal/kill-switch
- **Capital Efficiency**: ≥95% utilization within constraints over window

## Constraints and Contracts

### Constraints

- **Position Sizing**: Per-instrument and per-strategy max notional and leverage (if any)
- **Exposure Caps**: Per venue, asset class, sector, and counterparty
- **Drawdown**: Intra-day and rolling drawdown thresholds that trigger de-risking
- **Concentration**: Max percentage of capital in any single asset or correlated cluster

### Contracts

- **Allocation Contracts**: Recommended/enforced capital per strategy, venue, and asset, including limit metadata
- **Guardrail Contracts**: Current risk posture and trading mode (`{normal, de_risk, halt}`)
- **Breach Event Contracts**: Structured events describing limit trigger, timing, and action taken

**Integration**: Strategy consumes allocation contracts; execution enforces guardrail mode; analytics monitors capital efficiency and risk posture.

## Error Budgets, Burn, and Escalation

### Error Budgets

- **Zero tolerance** for hard risk breaches (limit violations, unbounded leverage)
- **Tiny budgets** for softer issues (small allocation drift, minor efficiency gaps)

### Burn-Rate Policy

- **Fast-Burn Alert**: Clusters of risk events in 30-60min window → immediate incident
- **Slow-Burn Alert**: Drift over 6-12h window → investigation and remediation
- **Budget Exhaustion**: Change freeze, explicit review, possible capital reduction

### Escalation

- **First Breach**: Immediate de-risking and incident declaration
- **Repeated Breaches**: Capital scale-down, tighter caps
- **Budget Exhausted**: No further capital increases, forced reduction until remediation

## Integration into Existing Governance Spine

- **Joint SLO Policy**: Any hard risk breach can halt entire lane (strategy + execution + analytics + risk) via existing kill-switch
- **Shared Monitoring**: Dashboards show risk strip alongside SLOs, P&L, latency in same cockpit
- **Promotion Criteria**: Phase-9 trial window demonstrating high correctness, zero hard breaches, measurable capital efficiency improvements

## Risk Task Backlog

### Capital Allocation Tasks

- `phase9_risk_allocation_engine`
  - Title: Production capital allocation with constraint enforcement
  - Module: swarm/risk
  - Risk Level: high
  - Baseline Hours: 4.0
  - Constraints: [allocation_correctness_99.9, position_limits, exposure_caps]

- `phase9_risk_guardrail_system`
  - Title: Real-time risk guardrails and breach detection
  - Module: swarm/risk
  - Risk Level: high
  - Baseline Hours: 3.5
  - Constraints: [guardrail_latency_100ms, breach_detection, auto_halt]

### Risk Monitoring Tasks

- `phase9_risk_drawdown_monitoring`
  - Title: Intra-day and rolling drawdown monitoring
  - Module: swarm/risk
  - Risk Level: medium_high
  - Baseline Hours: 3.0
  - Constraints: [drawdown_limits, real_time_monitoring, alert_thresholds]

- `phase9_risk_concentration_control`
  - Title: Position concentration and correlation monitoring
  - Module: swarm/risk
  - Risk Level: medium_high
  - Baseline Hours: 3.0
  - Constraints: [concentration_limits, correlation_analysis, diversification_enforcement]

## Execution Plan

### Week 1-2: Risk Foundation
- Focus: Capital allocation engine and guardrail system
- Tasks: `phase9_risk_allocation_engine`, `phase9_risk_guardrail_system`
- Target Hours: 7.5
- Risk Profile: High

### Week 3-4: Risk Monitoring
- Focus: Drawdown monitoring and concentration control
- Tasks: `phase9_risk_drawdown_monitoring`, `phase9_risk_concentration_control`
- Target Hours: 6.0
- Risk Profile: Medium-High

## Risk ROI Requirements

### Mandatory Fields
- task_type, risk_level, risk_constraints, slo_metrics, error_budget_usage, contract_status, evidence_links

### Task Type Values
- allocation_engine, guardrail_system, drawdown_monitoring, concentration_control

### Batch ID
- phase9_risk_lane

### Risk-Specific Metrics
- allocation_correctness, risk_limit_compliance, guardrail_latency_ms, capital_efficiency, breach_events, contract_compliance

## Joint Lane Integration

### Contract Publishing
- Risk publishes allocation contracts for strategy consumption
- Risk publishes guardrail contracts for execution enforcement
- Analytics monitors capital efficiency and risk posture

### Error Budget Integration
- Risk breaches consume joint error budget
- Hard risk breaches trigger joint incident response
- Recovery requires all domains to be healthy

### Kill Switch Integration
- Risk limit breaches trigger coordinated lane halt
- Joint kill switch can halt all four domains
- Recovery requires coordinated restart with risk validation

## Promotion Checklist

### Requirements
- Two consecutive passes of all risk gates
- Joint SLO compliance with strategy/execution/analytics lanes
- Demonstrated capital efficiency improvements
- Risk error budgets well within limits
- Zero unmitigated hard risk breaches
- Guardrail response times validated
- Phase 9 completion report generated

## Success Metrics

### Primary Metrics
- Risk SLO compliance ≥99.9%
- Error budget usage <10% (hard breaches)
- Capital efficiency ≥95%
- Guardrail response time ≤100ms
- Zero hard risk limit violations

### Secondary Metrics
- Allocation accuracy and consistency
- Drawdown control effectiveness
- Concentration limit compliance
- Contract validation success rate

## Next Steps

### Immediate
- Implement Phase 9 executor with risk constraints
- Set up risk SLO tracking and error budgeting
- Create allocation and guardrail contract publishing

### Short-term
- Run Phase 9 trial with multi-domain integration
- Validate guardrail response and incident coordination
- Generate Phase 9 completion report

### Long-term
- Promote Risk to governed lane
- Expand risk scope (VaR models, stress testing)
- Consider fifth domain integration (e.g., Portfolio Optimization)

## Risk Management Framework

### Risk Limits
- **Position Limits**: $25k per strategy, $50k per lane
- **Exposure Caps**: $100k daily, $500k per venue
- **Drawdown Limits**: 2% intra-day, 5% rolling
- **Concentration Limits**: 30% single asset, 60% correlated cluster

### Guardrail Actions
- **Normal**: Full trading within limits
- **De-Risk**: Reduced position sizing, tighter limits
- **Halt**: No new positions, unwind existing

### Breach Classification
- **Hard Breach**: Limit violation, unbounded leverage
- **Soft Breach**: Efficiency gap, minor drift
- **Warning**: Approaching limits, increased volatility
