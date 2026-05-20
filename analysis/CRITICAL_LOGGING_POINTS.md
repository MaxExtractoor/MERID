# Critical Logging Points Inventory

**Date:** 2026-05-13
**Purpose:** Identify critical logging points where structured logging should be implemented

## Current State

The codebase has a sophisticated logging infrastructure (`utils/logger.py`) with:
- JsonFormatter for structured JSON logs
- Context variables (correlation_id, task_venue, task_agent_id, task_mode, task_env, task_tick)
- SafeRotatingFileHandler for Windows compatibility
- Logging helpers (`utils/logging_helpers.py`) for common patterns

However, many critical paths still use basic logging without structured fields. This document identifies where structured logging should be added.

## Critical Logging Points

### 1. Trading Operations

#### 1.1 Order Submission
**File:** `merid/event_venues/kalshi/order_router.py`
**Function:** `_route_live()`, `_route_sync_non_live()`
**Current Logging:** Basic logger.info/error
**Required Fields:**
- market_id
- side (YES/NO)
- contracts
- price_cents
- notional_usd
- order_id
- source (CT, agent, manual)
**Helper:** `log_trading_operation()`

#### 1.2 Order Fills
**File:** `merid/event_venues/kalshi/order_router.py`
**Function:** Record fill handlers
**Current Logging:** Basic logger.info
**Required Fields:**
- order_id
- market_id
- fill_price_cents
- fill_quantity
- fill_timestamp
- latency_ms
- slippage_cents
**Helper:** `log_trading_operation()`

#### 1.3 Order Rejections
**File:** `merid/event_venues/kalshi/order_router.py`
**Function:** Rejection handlers
**Current Logging:** Basic logger.error
**Required Fields:**
- order_id
- market_id
- rejection_reason
- rejection_code
- requested_contracts
- requested_price
**Helper:** `log_error()`

#### 1.4 Position Updates
**File:** `merid/event_venues/kalshi/position_sizer.py`
**Function:** Position calculation
**Current Logging:** Basic logger.debug
**Required Fields:**
- market_id
- current_position
- new_position
- pnl_usd
- unrealized_pnl_usd
**Helper:** `log_trading_operation()`

### 2. Risk Checks

#### 2.1 Position Limit Checks
**File:** `merid/guards/global_risk_guard.py`
**Function:** `check_order()`
**Current Logging:** logger.critical on violations
**Required Fields:**
- risk_check: "position_limit"
- current_exposure_usd
- max_exposure_usd
- action: "allow" or "reject"
- ticker
- asset
- contracts
**Helper:** `log_risk_check()`

#### 2.2 Exposure Limit Checks
**File:** `merid/guards/global_risk_guard.py`
**Function:** `check_order()`
**Current Logging:** logger.critical on violations
**Required Fields:**
- risk_check: "exposure_limit"
- current_total_notional_usd
- max_total_notional_usd
- action: "allow" or "reject"
- proposed_notional_usd
**Helper:** `log_risk_check()`

#### 2.3 Drawdown Checks
**File:** `merid/risk/risk_guard.py`
**Function:** Drawdown monitoring
**Current Logging:** Basic logger.warning
**Required Fields:**
- risk_check: "drawdown"
- current_drawdown_pct
- drawdown_limit_pct
- action: "warning", "downsize", or "halt"
- daily_loss_usd
- daily_loss_limit_usd
**Helper:** `log_risk_check()`

#### 2.4 Daily Loss Cap Checks
**File:** `merid/prediction/paper_session.py`
**Function:** `_enforce_risk_limits()`
**Current Logging:** Basic logger.warning
**Required Fields:**
- risk_check: "daily_loss_cap"
- current_daily_loss_cents
- max_daily_loss_cents
- action: "allow", "downsize", or "halt"
- cell_name
**Helper:** `log_risk_check()`

#### 2.5 Cluster Cap Checks
**File:** `merid/prediction/paper_session.py`
**Function:** `_check_cluster_cap()`
**Current Logging:** Basic logger.warning
**Required Fields:**
- risk_check: "cluster_cap"
- cluster_name
- cluster_daily_loss_cents
- max_cluster_daily_loss_cents
- action: "allow" or "halt"
**Helper:** `log_risk_check()`

### 3. Execution Guards

#### 3.1 Spread Checks
**File:** `merid/guards/global_execution_guard.py`
**Function:** `check_order()`
**Current Logging:** Basic logger.warning
**Required Fields:**
- guardrail: "max_spread"
- current_spread_cents
- max_spread_cents
- passed: true/false
- market_id
**Helper:** `log_guardrail_check()`

#### 3.2 Depth Checks
**File:** `merid/guards/global_execution_guard.py`
**Function:** `check_order()`
**Current Logging:** Basic logger.warning
**Required Fields:**
- guardrail: "min_depth"
- current_depth_contracts
- min_depth_contracts
- passed: true/false
- market_id
**Helper:** `log_guardrail_check()`

#### 3.3 Slippage Checks
**File:** `merid/execution/execution_coordinator.py`
**Function:** Slippage monitoring
**Current Logging:** Basic logger.warning
**Required Fields:**
- guardrail: "max_slippage"
- expected_slippage_cents
- actual_slippage_cents
- max_slippage_cents
- passed: true/false
- market_id
**Helper:** `log_guardrail_check()`

#### 3.4 Circuit Breaker Checks
**File:** `merid/circuit_breaker.py`
**Function:** Circuit breaker logic
**Current Logging:** Basic logger.critical
**Required Fields:**
- guardrail: "circuit_breaker"
- error_count
- error_threshold
- window_seconds
- passed: true/false
- action: "trip" or "reset"
**Helper:** `log_guardrail_check()`

### 4. API Operations

#### 4.1 Request Receipt
**File:** `web/api/kalshi_api.py`
**Function:** All API endpoints
**Current Logging:** Basic logger.info
**Required Fields:**
- endpoint
- method (GET/POST/PUT/DELETE)
- client_ip
- correlation_id
- request_timestamp
**Helper:** `log_api_request()`

#### 4.2 Response Completion
**File:** `web/api/kalshi_api.py`
**Function:** All API endpoints
**Current Logging:** Basic logger.info
**Required Fields:**
- endpoint
- status_code
- duration_ms
- correlation_id
- response_timestamp
**Helper:** `log_api_response()`

#### 4.3 Error Responses
**File:** `web/api/kalshi_api.py`
**Function:** Exception handlers
**Current Logging:** Basic logger.error
**Required Fields:**
- endpoint
- status_code
- error_type
- error_message
- correlation_id
- duration_ms
**Helper:** `log_api_response()`

#### 4.4 Rate Limit Hits
**File:** `ratelimit/middleware.py`
**Function:** Rate limiting logic
**Current Logging:** Basic logger.warning
**Required Fields:**
- client_ip
- endpoint
- limit
- window_seconds
- current_requests
- action: "block" or "allow"
**Helper:** `log_risk_check()`

### 5. Continuous Trader Operations

#### 5.1 Cycle Start
**File:** `merid/trading/kalshi_continuous_trader.py`
**Function:** `run()` - cycle start
**Current Logging:** Basic logger.debug
**Required Fields:**
- operation: "cycle_start"
- tick_number
- mode (paper/live)
- venue (kalshi)
**Helper:** `log_execution()` with `log_trading_context()`

#### 5.2 Cycle End
**File:** `merid/trading/kalshi_continuous_trader.py`
**Function:** `run()` - cycle end
**Current Logging:** Basic logger.debug
**Required Fields:**
- operation: "cycle_end"
- tick_number
- orders_submitted
- orders_filled
- duration_ms
**Helper:** `log_execution()`

#### 5.3 Guard Check Results
**File:** `merid/trading/kalshi_continuous_trader.py`
**Function:** Guard check calls
**Current Logging:** Basic logger.warning
**Required Fields:**
- guard_check: "trading_guardian"
- current_value
- limit_value
- action: "allow" or "reject"
- asset
**Helper:** `log_risk_check()`

### 6. Agent Operations

#### 6.1 Agent Signal Generation
**File:** `merid/agents/kalshi_crypto/*.py`
**Function:** Signal generation methods
**Current Logging:** Basic logger.info
**Required Fields:**
- agent_id
- market_id
- signal_direction (bullish/bearish)
- confidence
- edge_pct
- timestamp
**Helper:** `log_trading_operation()`

#### 6.2 Agent Opinion Submission
**File:** `merid/prediction/trading_agent.py`
**Function:** `_execute_signal_body()`
**Current Logging:** Basic logger.info
**Required Fields:**
- agent_id
- opinion_id
- market_id
- side
- contracts
- confidence
**Helper:** `log_trading_operation()`

#### 6.3 Agent Circuit Breaker Trips
**File:** `merid/prediction/trading_agent.py`
**Function:** Circuit breaker logic
**Current Logging:** Basic logger.warning
**Required Fields:**
- agent_id
- circuit_breaker_type
- error_count
- threshold
- action: "trip" or "reset"
**Helper:** `log_guardrail_check()`

## Implementation Priority

### High Priority (Immediate - Safety Critical)
1. **Global Risk Guard** - All check_order() calls
2. **Global Execution Guard** - All check_order() calls
3. **Order Rejections** - All rejection handlers
4. **Circuit Breaker** - Trip events
5. **Drawdown Checks** - Warning/downsize/halt actions

### Medium Priority (Short-term - Operational Visibility)
1. **Order Submission** - All order paths
2. **Order Fills** - Fill handlers
3. **Guardrail Checks** - Spread/depth/slippage
4. **API Error Responses** - All 4xx/5xx responses
5. **Agent Signal Generation** - Signal quality metrics

### Low Priority (Long-term - Enhanced Observability)
1. **Position Updates** - Position tracking
2. **API Request/Response** - All endpoints
3. **Cycle Start/End** - CT lifecycle
4. **Agent Opinions** - Opinion submission
5. **Rate Limit Hits** - Rate limiting events

## Migration Strategy

### Phase 1: Safety-Critical Logging (Week 1)
1. Add structured logging to GlobalRiskGuard.check_order()
2. Add structured logging to GlobalExecutionGuard.check_order()
3. Add structured logging to order rejection handlers
4. Add structured logging to circuit breaker trips
5. Add structured logging to drawdown checks

### Phase 2: Operational Logging (Week 2)
1. Add structured logging to order submission paths
2. Add structured logging to order fill handlers
3. Add structured logging to guardrail checks
4. Add structured logging to API error responses
5. Add structured logging to agent signal generation

### Phase 3: Enhanced Observability (Week 3-4)
1. Add structured logging to position updates
2. Add structured logging to all API endpoints
3. Add structured logging to CT cycle lifecycle
4. Add structured logging to agent opinions
5. Add structured logging to rate limiting events

## Testing Strategy

### Unit Tests
- Test each logging helper function with various field combinations
- Verify JSON output format matches schema
- Test context variable propagation

### Integration Tests
- Test end-to-end logging flow for order submission
- Verify log aggregation by correlation_id
- Test logging under error conditions

### Regression Tests
- Ensure no performance degradation from structured logging
- Verify log file rotation still works
- Test logging under high load

## Log Aggregation Setup

### Recommended Tools
- **ELK Stack** (Elasticsearch, Logstash, Kibana) - Full-featured log aggregation
- **Grafana Loki** - Lightweight log aggregation with Prometheus
- **CloudWatch Logs** - AWS-native (if using AWS)

### Indexing Strategy
- Index by: correlation_id, timestamp, level, domain
- Retention policy: 30 days hot, 90 days warm, 1 year cold
- Alert on: ERROR/CRITICAL levels, specific risk_check failures

### Dashboard Recommendations
- Trading operations dashboard (orders, fills, rejections)
- Risk checks dashboard (limit violations, drawdown events)
- Execution guards dashboard (guardrail failures)
- API performance dashboard (latency, error rates)
- Agent performance dashboard (signal quality, opinion counts)

## Success Criteria

1. All safety-critical paths emit structured logs
2. All logs include required domain-specific fields
3. Context variables (correlation_id, venue, agent_id) propagate correctly
4. Log aggregation system can query logs by correlation_id
5. Alerting configured for ERROR/CRITICAL events
6. No performance degradation from structured logging
7. Log rotation and retention policies working correctly
