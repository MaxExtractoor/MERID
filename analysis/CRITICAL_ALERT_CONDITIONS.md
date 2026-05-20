# Critical Alert Conditions

**Date:** 2026-05-13
**Purpose:** Define critical conditions that should trigger alerts

## Alert Severity Levels

### CRITICAL (Immediate Action Required)
- System-wide failures
- Risk limit violations
- Emergency halt conditions
- Data corruption or loss

### WARNING (Attention Required)
- Approaching risk limits
- Performance degradation
- Configuration issues
- Unusual patterns

### INFO (Informational)
- Normal operational events
- Scheduled maintenance
- Status updates

## Critical Alert Conditions

### Risk Management Alerts

#### RC-1: Global Risk Cap Exceeded
- **Severity:** CRITICAL
- **Condition:** Total risk exceeds configured cap (e.g., 8% of equity)
- **Source:** `merid/guards/global_risk_guard.py`
- **Field:** `risk_check: total_risk_cap`
- **Action:** Halt all trading, investigate exposure
- **Escalation:** Immediate notification to ops team

#### RC-2: Cycle Risk Cap Exceeded
- **Severity:** CRITICAL
- **Condition:** Cycle risk exceeds configured cap (e.g., 3% of equity)
- **Source:** `merid/guards/global_risk_guard.py`
- **Field:** `risk_check: cycle_risk_cap`
- **Action:** Halt current cycle, investigate orders
- **Escalation:** Immediate notification to ops team

#### RC-3: Drawdown Threshold Exceeded
- **Severity:** CRITICAL
- **Condition:** Portfolio drawdown exceeds threshold (e.g., 12%)
- **Source:** `merid/prediction/paper_session.py`
- **Field:** `risk_check: drawdown`
- **Action:** Auto-halt trading, manual review required
- **Escalation:** Immediate notification to ops team

#### RC-4: Daily Loss Cap Exceeded
- **Severity:** CRITICAL
- **Condition:** Daily loss exceeds configured cap (e.g., $50)
- **Source:** `merid/prediction/paper_session.py`
- **Field:** `risk_check: daily_loss_cap`
- **Action:** Halt affected cell, investigate losses
- **Escalation:** Notification to trading team

#### RC-5: Cluster Cap Exceeded
- **Severity:** CRITICAL
- **Condition:** Correlated cluster daily loss exceeds cap (e.g., $100)
- **Source:** `merid/prediction/paper_session.py`
- **Field:** `risk_check: cluster_cap`
- **Action:** Halt all cells in cluster, investigate
- **Escalation:** Notification to trading team

#### RC-6: Approaching Risk Limit
- **Severity:** WARNING
- **Condition:** Risk usage exceeds 80% of configured limit
- **Source:** `merid/guards/global_risk_guard.py`
- **Field:** `risk_check: total_risk_cap` with `action: allow`
- **Action:** Monitor closely, consider reducing exposure
- **Escalation:** Warning notification to ops team

### Execution Guard Alerts

#### EG-1: Emergency Halt Triggered
- **Severity:** CRITICAL
- **Condition:** Emergency halt activated
- **Source:** `merid/guards/global_execution_guard.py`
- **Field:** `guardrail: emergency_halt_triggered`
- **Action:** All trading halted, manual intervention required
- **Escalation:** Immediate notification to ops team

#### EG-2: Bankroll Cap Exceeded
- **Severity:** CRITICAL
- **Condition:** Total notional exceeds 2% bankroll cap
- **Source:** `merid/guards/global_execution_guard.py`
- **Field:** `risk_check: global_bankroll_cap`
- **Action:** Order rejected, investigate exposure
- **Escalation:** Notification to ops team

#### EG-3: Rate Limit Exceeded
- **Severity:** WARNING
- **Condition:** Order rate exceeds limits (minute/hour)
- **Source:** `merid/guards/global_execution_guard.py`
- **Field:** `risk_check: rate_limit_minute` or `rate_limit_hour`
- **Action:** Orders rejected, investigate activity
- **Escalation:** Warning notification to ops team

#### EG-4: Scalper Mode Block
- **Severity:** WARNING
- **Condition:** Scalper mode blocking orders
- **Source:** `merid/guards/global_risk_guard.py`
- **Field:** `guardrail: scalper_existing_risk` or `scalper_max_trades_per_batch`
- **Action:** Orders rejected, expected behavior in scalper mode
- **Escalation:** Informational (no action required if expected)

### Trading Operation Alerts

#### TO-1: Order Rejection
- **Severity:** WARNING
- **Condition:** Order rejected by guard/risk check
- **Source:** Order submission paths
- **Field:** `operation: order_rejection`
- **Action:** Investigate rejection reason
- **Escalation:** Warning notification if rejection rate > 10%

#### TO-2: Fill Failure
- **Severity:** WARNING
- **Condition:** Order submitted but not filled within expected time
- **Source:** Order execution paths
- **Field:** `operation: fill_failure`
- **Action:** Investigate order status
- **Escalation:** Warning notification if failure rate > 5%

#### TO-3: High Slippage
- **Severity:** WARNING
- **Condition:** Fill price deviates significantly from expected
- **Source:** Order execution paths
- **Field:** `guardrail: max_slippage` with `passed: false`
- **Action:** Investigate market conditions
- **Escalation:** Warning notification if slippage > 5%

#### TO-4: Position Mismatch
- **Severity:** WARNING
- **Condition:** Position tracking mismatch detected
- **Source:** Position reconciliation
- **Field:** `operation: position_mismatch`
- **Action:** Reconcile positions, investigate
- **Escalation:** Warning notification to ops team

### System Health Alerts

#### SH-1: Non-Positive Equity
- **Severity:** CRITICAL
- **Condition:** Equity reported as non-positive
- **Source:** `merid/guards/global_risk_guard.py`
- **Field:** `risk_check: non_positive_equity`
- **Action:** Fail-closed, trading halted
- **Escalation:** Immediate notification to ops team

#### SH-2: Configuration Error
- **Severity:** CRITICAL
- **Condition:** Configuration loading fails
- **Source:** Configuration loading paths
- **Field:** `operation: config_error`
- **Action:** Use fallback or halt, investigate
- **Escalation:** Immediate notification to ops team

#### SH-3: API Error Rate High
- **Severity:** WARNING
- **Condition:** API error rate exceeds threshold (e.g., 10%)
- **Source:** API endpoints
- **Field:** `operation: api_error` with high rate
- **Action:** Investigate API health, consider failover
- **Escalation:** Warning notification to ops team

#### SH-4: Database Error
- **Severity:** CRITICAL
- **Condition:** Database connection or query failure
- **Source:** Database operations
- **Field:** `operation: database_error`
- **Action:** Investigate database, attempt recovery
- **Escalation:** Immediate notification to ops team

#### SH-5: Log Write Failure
- **Severity:** WARNING
- **Condition:** Unable to write to log file
- **Source:** Logging infrastructure
- **Field:** `operation: log_write_failure`
- **Action:** Check disk space, permissions
- **Escalation:** Warning notification to ops team

### Agent Operation Alerts

#### AO-1: Agent Circuit Breaker Trip
- **Severity:** WARNING
- **Condition:** Agent circuit breaker triggered
- **Source:** Agent execution paths
- **Field:** `guardrail: circuit_breaker` with `action: trip`
- **Action:** Agent paused, investigate errors
- **Escalation:** Warning notification to ops team

#### AO-2: Agent Signal Quality Degradation
- **Severity:** WARNING
- **Condition:** Agent signal quality below threshold
- **Source:** Agent performance tracking
- **Field:** `operation: signal_quality_degradation`
- **Action:** Monitor agent, consider disabling
- **Escalation:** Warning notification to trading team

#### AO-3: Agent Failure
- **Severity:** CRITICAL
- **Condition:** Agent crashes or fails repeatedly
- **Source:** Agent execution paths
- **Field:** `operation: agent_failure`
- **Action:** Disable agent, investigate
- **Escalation:** Immediate notification to ops team

### Market Data Alerts

#### MD-1: Market Data Feed Failure
- **Severity:** CRITICAL
- **Condition:** Market data feed unavailable
- **Source:** Market data providers
- **Field:** `operation: market_data_feed_failure`
- **Action:** Switch to backup feed, halt trading if unavailable
- **Escalation:** Immediate notification to ops team

#### MD-2: Stale Market Data
- **Severity:** WARNING
- **Condition:** Market data not updating
- **Source:** Market data providers
- **Field:** `operation: stale_market_data`
- **Action:** Investigate feed, consider refresh
- **Escalation:** Warning notification to ops team

#### MD-3: Price Discrepancy
- **Severity:** WARNING
- **Condition:** Significant price discrepancy between sources
- **Source:** Market data validation
- **Field:** `operation: price_discrepancy`
- **Action:** Investigate sources, use most reliable
- **Escalation:** Warning notification to ops team

## Alert Aggregation Rules

### Rate Limiting
- **Same alert:** Maximum 1 notification per 5 minutes
- **Same severity:** Maximum 5 notifications per minute
- **Total:** Maximum 20 notifications per minute

### Deduplication
- **Correlation ID:** Group alerts by correlation_id
- **Same condition:** Deduplicate identical conditions within time window
- **Context:** Include context in alert for deduplication

### Escalation
- **CRITICAL:** Immediate notification + escalation to ops team
- **WARNING:** Notification to ops team
- **INFO:** No notification (log only)

## Alert Context Requirements

### Required Fields
- `alert_id`: Unique identifier
- `severity`: CRITICAL/WARNING/INFO
- `condition`: Alert condition name
- `timestamp`: Alert timestamp
- `source`: Source module/component
- `message**: Human-readable message

### Optional Fields
- `correlation_id`: Request correlation ID
- `agent_id`: Agent identifier
- `market_id`: Market identifier
- `current_value`: Current metric value
- `threshold_value`: Threshold value
- `action_taken`: Action taken by system
- `recommended_action`: Recommended action for ops team

## Alert Routing

### CRITICAL Alerts
- **Primary:** Ops team on-call
- **Secondary:** Trading team
- **Tertiary:** Engineering team
- **Channels:** PagerDuty, Slack #ops-critical, SMS

### WARNING Alerts
- **Primary:** Ops team
- **Secondary:** Trading team
- **Channels:** Slack #ops-warnings, email

### INFO Alerts
- **Primary:** Ops team
- **Channels:** Slack #ops-info, log aggregation

## Testing Alert Conditions

### Unit Tests
- Test each alert condition triggers correctly
- Test alert context includes required fields
- Test alert aggregation rules work correctly
- Test rate limiting prevents spam

### Integration Tests
- Test alert routing to correct channels
- Test escalation paths work correctly
- Test alert context propagates through system
- Test alert deduplication works end-to-end

### Manual Tests
- Simulate critical conditions (in test environment)
- Verify alerts are received by correct teams
- Verify alert context is actionable
- Verify escalation paths work correctly

## Success Criteria

1. All critical conditions defined with clear thresholds
2. Alert severity levels clearly defined
3. Alert routing and escalation documented
4. Alert context requirements specified
5. Testing strategy defined
6. Integration points identified
