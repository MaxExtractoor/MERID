# Phase 2: Risk Rejection Explainability Tests

**Priority:** High  
**Baseline:** Commit `c25d2702` - Kalshi WS bridge + explainability integration  
**Component:** `merid/prediction/trading_agent.py`, `agents/explainability.py`

## Summary

Validate that all risk rejection scenarios in `KalshiTradingAgent` emit complete, structured explainability records with rule IDs, thresholds, current state, and human-readable reasoning.

## Acceptance Criteria

### 1. Exposure Cap Block

- [ ] Create signal that exceeds per-market notional limit
- [ ] Verify `_record_explainability_decision` called with risk block details
- [ ] Assert explainability record includes:
  - `decision_type: "trade_blocked"`
  - `outcome: "rejected"`
  - `rule_id: "exposure_cap"`
  - Current exposure amount
  - Configured threshold
  - Signal size that would breach limit
- [ ] Verify `primary_reasoning` contains human-readable explanation

### 2. Daily Loss Limit Block

- [ ] Mock portfolio state with current P&L near daily loss threshold
- [ ] Create signal that would breach limit
- [ ] Verify explainability record includes:
  - `rule_id: "daily_loss_limit"`
  - Current day P&L
  - Configured daily loss threshold
  - Market/symbol context
- [ ] Assert `data_sources` includes risk engine state snapshot

### 3. Swarm Health Block

- [ ] Mock degraded agent/component (e.g., consensus engine health at 50%)
- [ ] Attempt trade decision
- [ ] Verify explainability record includes:
  - `rule_id: "swarm_health_block"`
  - Degraded component name
  - Current health score
  - Required minimum health threshold
- [ ] Assert trading agent refuses to place orders when health < 100%

### 4. Explainability Format Validation

- [ ] All risk blocks write entries with consistent schema
- [ ] `decision_type` always set to `"trade_blocked"`
- [ ] `outcome` always set to `"rejected"`
- [ ] `primary_reasoning` contains non-empty human-readable explanation
- [ ] `data_sources` includes relevant risk state (exposure, P&L, health)
- [ ] `timestamp` is ISO-formatted
- [ ] Records retrievable via `/api/v1/explainability/decisions?agent=KalshiTradingAgent`

## Test File Location

`tests/prediction/test_trading_agent_explainability.py`

## Implementation Notes

- Mock `PredictionMarketRisk` to simulate different rejection scenarios
- Use `agents.explainability.ExplainabilityTracker` to verify record storage
- Mock `get_session_guard` and `get_venue_gate` for swarm health scenarios
- Verify explainability records match dashboard API schema expectations

## Definition of Done

- [ ] All risk rejection scenarios covered
- [ ] Explainability records include all required fields
- [ ] Human-readable reasoning is clear and actionable
- [ ] Dashboard API can retrieve and display rejection records
- [ ] CI green
