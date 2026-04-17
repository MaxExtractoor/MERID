# Phase 2: Risk Rejection Explainability Tests

**Priority:** High  
**Baseline:** Commit `c25d2702` - Kalshi WS bridge + explainability integration  
**Component:** `merid/prediction/trading_agent.py`, `agents/explainability.py`

## Summary

Validate that all risk rejection scenarios in `KalshiTradingAgent` emit complete, structured explainability records with rule IDs, thresholds, current state, and human-readable reasoning.

## Acceptance Criteria

### 1. Exposure Cap Block

- [x] Create signal that exceeds per-market notional limit
- [x] Verify `_record_explainability_decision` called with risk block details
- [x] Assert explainability record includes:
  - `decision_type: "trade_blocked"`
  - `outcome: "rejected"`
  - `rule_id: "exposure_cap"`
  - Current exposure amount
  - Configured threshold
  - Signal size that would breach limit
- [x] Verify `primary_reasoning` contains human-readable explanation

### 2. Daily Loss Limit Block

- [x] Mock portfolio state with current P&L near daily loss threshold
- [x] Create signal that would breach limit
- [x] Verify explainability record includes:
  - `rule_id: "daily_loss_limit"`
  - Current day P&L
  - Configured daily loss threshold
  - Market/symbol context
- [x] Assert `data_sources` includes risk engine state snapshot

### 3. Swarm Health Block

- [x] Mock degraded agent/component (e.g., consensus engine health at 50%)
- [x] Attempt trade decision
- [x] Verify explainability record includes:
  - `rule_id: "swarm_health_block"`
  - Degraded component name
  - Current health score
  - Required minimum health threshold
- [x] Assert trading agent refuses to place orders when health < 100%

### 4. Explainability Format Validation

- [x] All risk blocks write entries with consistent schema
- [x] `decision_type` always set to `"trade_blocked"`
- [x] `outcome` always set to `"rejected"`
- [x] `primary_reasoning` contains non-empty human-readable explanation
- [x] `data_sources` includes relevant risk state (exposure, P&L, health)
- [x] `timestamp` is ISO-formatted
- [x] Records retrievable via `/api/v1/explainability/decisions?agent=KalshiTradingAgent`

## Test File Location

`tests/prediction/test_trading_agent_explainability.py`

## Implementation Notes

- Mock `PredictionMarketRisk` to simulate different rejection scenarios
- Use `agents.explainability.ExplainabilityTracker` to verify record storage
- Mock `get_session_guard` and `get_venue_gate` for swarm health scenarios
- Verify explainability records match dashboard API schema expectations

## Definition of Done

- [x] All risk rejection scenarios covered (11/11 passed)
- [x] Explainability records include all required fields
- [x] Human-readable reasoning is clear and actionable
- [x] Dashboard API can retrieve and display rejection records
- [x] CI green — added to `hardening-tests` job
