# Staging/Paper Deployment Runbook - Phase 1 + Phase 2 Validation

**Baseline:** Commit `c25d2702` + Phase 2 Operational Resilience Tests  
**Deployment Target:** Staging/Paper Mode  
**Duration:** 24-72 hours minimum soak test  
**Status:** Phase 2 Complete (52/54 tests passing)

## Pre-Deployment Checklist

### Code Readiness
- [ ] Phase 1 implementation merged to develop (commit `c25d2702`)
- [ ] Phase 2 test suites committed:
  - [ ] `tests/event_venues/kalshi/test_ws_resilience.py` (16/18 passing)
  - [ ] `tests/event_venues/kalshi/test_rate_limits.py` (17/17 passing)
  - [ ] `tests/prediction/test_trading_agent_explainability.py` (11/11 passing)
  - [ ] `tests/integration/test_swarm_health_gating.py` (8/8 passing)

### Environment Readiness
- [ ] Kalshi API credentials configured for staging environment
- [ ] Observability stack ready (logs, metrics, alerts)
- [ ] Paper trading mode verified in config
- [ ] Event bus and state layer operational
- [ ] Enhanced logging enabled for Phase 2 validation (see §6)

## Deployment Steps

### 1. Configure Kalshi API Credentials

**Environment Variables:**
```bash
export KALSHI_API_BASE="https://trading-api.kalshi.com"  # or demo-api for testing
export KALSHI_API_KEY="your_api_key_here"
export KALSHI_API_SECRET="your_api_secret_here"
export KALSHI_RATE_LIMIT_TIER="basic"  # basic, advanced, premier, prime
export TRADING_MODE="paper"  # paper mode for validation
```

**Verify Credentials:**
```bash
curl -X GET "https://trading-api.kalshi.com/trade-api/v2/exchange/status" \
  -H "Authorization: Bearer $KALSHI_API_KEY"
```

### 2. Deploy MERID Backend

```bash
# Pull latest develop
git checkout develop
git pull origin develop

# Verify on correct commit
git log -1 --oneline  # Should show c25d2702

# Install dependencies
pip install -r requirements.txt

# Run database migrations if needed
alembic upgrade head

# Start backend services
python -m uvicorn web.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Start Kalshi WS Bridge

```bash
# In separate terminal
python -m merid.event_venues.kalshi.ws_bridge_runner
```

**Expected Startup Logs:**
```
INFO: KalshiWebSocketBridge initialized
INFO: Subscribing to orderbook channels for tickers: ['KXBTC-24FEB16-B60000', ...]
INFO: WebSocket connected to wss://trading-api.kalshi.com/trade-api/ws/v2
INFO: Event bus publisher started
INFO: UI coalesce loop started
```

### 4. Start Trading Agent (Optional for Phase 1)

```bash
# In separate terminal
python -m merid.prediction.trading_agent_runner --mode paper
```

## Validation Checklist

### WebSocket Bridge Validation

**Monitor WS Connection:**
```bash
# Check bridge status
curl http://localhost:8000/api/v1/kalshi/ws/status

# Expected response:
{
  "connected": true,
  "subscribed_tickers": ["KXBTC-24FEB16-B60000", ...],
  "events_forwarded": 1234,
  "events_dropped": 0,
  "forward_errors": 0,
  "uptime_seconds": 3600
}
```

**Verify Orderbook Subscriptions:**
- [ ] Bridge subscribes to `orderbook_delta` for all tracked tickers
- [ ] Orderbook events published to event bus with correct contract: `_publish_to_bus(event_type, payload)`
- [ ] No dropped events or forward errors in first hour
- [ ] WS reconnect logic triggers on disconnect (simulate by killing connection)

**Key Metrics to Track:**
- WS message receipt rate: 10-100 messages/sec typical
- Event bus publish latency: <5ms P99
- Orderbook freshness: <1s since last update per ticker
- Reconnect frequency: should be rare (<1 per hour under normal conditions)

### Explainability API Validation

**Test Endpoint:**
```bash
# Query recent decisions
curl http://localhost:8000/api/v1/explainability/decisions?limit=10

# Expected response structure:
{
  "total": 10,
  "decisions": [
    {
      "decision_id": "uuid",
      "agent": "KalshiTradingAgent",
      "decision_type": "trade",
      "timestamp": "2026-02-16T19:15:00Z",
      "outcome": "executed",
      "confidence": 0.75,
      "primary_reasoning": "...",
      "supporting_factors": [...],
      "contrary_factors": [...],
      "data_sources": ["kalshi:orderbook", ...],
      "alternatives_considered": [...],
      "execution_time_ms": 45
    }
  ]
}
```

**Verify:**
- [ ] Endpoint returns real decision records (check timestamps are recent)
- [ ] No `_stub: true` metadata in response
- [ ] Agent filtering works: `?agent=KalshiTradingAgent`
- [ ] Schema matches UI expectations (no missing fields)
- [ ] ISO timestamps formatted correctly
- [ ] Empty tracker returns `{"total": 0, "decisions": []}`, not fabricated data

### Trading Agent Validation (If Running)

**Monitor Decision Recording:**
```bash
# Check agent status
curl http://localhost:8000/api/v1/agents/status

# Review recent decisions
curl http://localhost:8000/api/v1/explainability/decisions?agent=KalshiTradingAgent&limit=50
```

**Verify:**
- [ ] Agent emits explainability records for all decisions
- [ ] Risk-blocked signals include rule_id and thresholds
- [ ] Allowed signals include confidence and feature attribution
- [ ] Decision recording latency <10ms P99
- [ ] No missing or corrupted decision records

## Monitoring & Alerts

### Key Logs to Watch

**WS Bridge:**
```bash
tail -f logs/kalshi_ws_bridge.log | grep -E "(ERROR|WARNING|connected|disconnected|sequence_gap)"
```

**Explainability:**
```bash
tail -f logs/explainability.log | grep -E "(decision_recorded|ERROR)"
```

**Trading Agent:**
```bash
tail -f logs/trading_agent.log | grep -E "(signal_generated|order_placed|risk_blocked)"
```

### Metrics Dashboard

Monitor these metrics in your observability stack (Prometheus/Grafana/etc.):

**WS Bridge Metrics:**
- `kalshi_ws_events_forwarded_total` - should be steadily increasing
- `kalshi_ws_events_dropped_total` - should stay at 0
- `kalshi_ws_publish_latency_seconds` - P99 <0.005s
- `kalshi_ws_connected` - should be 1 (connected)

**Explainability Metrics:**
- `explainability_decisions_recorded_total` - per agent
- `explainability_recording_latency_seconds` - P99 <0.010s
- `explainability_api_query_latency_seconds` - P99 <0.020s

**Trading Agent Metrics:**
- `trading_agent_signals_generated_total` - per outcome (executed/blocked/skipped)
- `trading_agent_risk_blocks_total` - per rule_id
- `trading_agent_decision_latency_seconds` - P99 <0.030s

### Alert Rules

Configure alerts for:

1. **WS Disconnected** (Warning)
   - Trigger: `kalshi_ws_connected == 0` for >30 seconds
   - Action: Check network, Kalshi API status, review logs

2. **High Event Drop Rate** (Critical)
   - Trigger: `rate(kalshi_ws_events_dropped_total[5m]) > 10`
   - Action: Investigate backpressure, queue sizes, event bus health

3. **Sequence Gap Detected** (Warning)
   - Trigger: Log message contains "sequence_gap"
   - Action: Verify snapshot refresh triggered, orderbook re-sync

4. **High Explainability Recording Latency** (Warning)
   - Trigger: `explainability_recording_latency_seconds{quantile="0.99"} > 0.020`
   - Action: Check for contention, database performance

5. **No Decision Activity** (Warning)
   - Trigger: `rate(explainability_decisions_recorded_total[15m]) == 0` (if agent running)
   - Action: Check agent health, market activity, risk blocks

## Known Issues & Workarounds

### Issue: WS Connection Drops Frequently
**Symptoms:** `kalshi_ws_connected` flapping, reconnect logs every few minutes  
**Potential Causes:**
- Network instability
- Kalshi API rate limiting (check tier)
- Firewall/proxy issues

**Workaround:**
- Verify rate-limit tier configuration
- Check network logs for TCP resets
- Consider increasing reconnect backoff parameters

### Issue: Empty Explainability Records
**Symptoms:** `/api/v1/explainability/decisions` returns `{"total": 0, "decisions": []}`  
**Potential Causes:**
- Trading agent not running or not generating decisions
- Explainability tracker not initialized
- Agent name mismatch in queries

**Workaround:**
- Verify trading agent is running: `curl /api/v1/agents/status`
- Check agent logs for decision activity
- Try query without agent filter to see all records

### Issue: Orderbook Data Stale
**Symptoms:** `orderbook_freshness` metric >10 seconds  
**Potential Causes:**
- WS subscription failed
- Market not active/closed
- Sequence gap not handled properly

**Workaround:**
- Check WS subscription status in bridge summary
- Verify market is open via REST: `GET /markets/{ticker}`
- Force reconnect if stale >60 seconds

## Phase 2 Enhanced Monitoring Requirements

### WS Resilience Validation

**Additional Logging:**
```python
# Enable in merid/event_venues/kalshi/ws.py
logger.info(f"WS reconnect attempt {attempt}/{max_retries}, backoff={backoff:.2f}s")
logger.warning(f"Sequence gap detected: expected {expected}, got {actual}")
logger.info(f"Orderbook cache invalidated for {ticker}, requesting snapshot")
```

**Metrics to Track:**
- `kalshi_ws_reconnect_attempts_total` - Count of reconnect attempts
- `kalshi_ws_reconnect_backoff_seconds` - Current backoff duration
- `kalshi_ws_sequence_gaps_total` - Sequence gap detections per ticker
- `kalshi_ws_snapshot_refreshes_total` - Orderbook snapshot refresh triggers
- `kalshi_ws_uptime_seconds` - Continuous connection time

**Validation Tests:**
- [ ] Simulate disconnect (kill connection) and verify exponential backoff (1s→2s→4s)
- [ ] Inject sequence gap and verify cache invalidation + snapshot refresh
- [ ] Monitor for spontaneous disconnects during 24h period
- [ ] Verify no orderbook staleness >10 seconds

### Rate-Limit Enforcement Validation

**Additional Logging:**
```python
# Enable in merid/event_venues/kalshi/client.py
logger.warning(f"429 response, Retry-After: {retry_after}s, waiting...")
logger.info(f"Token bucket: {available_tokens}/{capacity} available")
logger.warning(f"Request throttled, waiting {wait_time:.2f}s for token")
```

**Metrics to Track:**
- `kalshi_api_429_responses_total` - Count of rate-limit responses
- `kalshi_api_retry_after_seconds` - Retry-After header values observed
- `kalshi_token_bucket_tokens_available` - Current token count
- `kalshi_token_bucket_wait_seconds` - Time spent waiting for tokens
- `kalshi_api_request_latency_seconds` - Total request time including waits

**Validation Tests:**
- [ ] Monitor 429 responses (should be rare with self-throttling)
- [ ] Verify Retry-After headers honored exactly
- [ ] Confirm token bucket prevents burst >20 req/sec (Basic tier)
- [ ] Check no retries on 400/401/403/422 errors
- [ ] Measure actual request rate vs tier limit

### Risk Rejection Explainability Validation

**Additional Logging:**
```python
# Enable in merid/prediction/trading_agent.py
logger.info(f"Risk block: {check.reason}, recorded explainability decision_id={reasoning.decision_id}")
logger.debug(f"Explainability record: agent={agent}, allowed={allowed}, rule_id={rule_id}")
```

**Metrics to Track:**
- `trading_agent_decisions_recorded_total{outcome}` - Count by allowed/blocked/skipped
- `trading_agent_risk_blocks_total{rule_id}` - Count per risk rule
- `explainability_records_by_rule_id_total` - Exposure cap, daily loss, swarm health
- `explainability_recording_latency_seconds` - Time to emit decision record

**Validation Tests:**
- [ ] Verify all risk blocks create explainability records
- [ ] Check rule_id present in all blocked decisions
- [ ] Confirm allowed signals also create records
- [ ] Query `/api/v1/explainability/decisions?agent=KalshiTradingAgent`
- [ ] Verify schema: `agent_id`, `primary_reason`, `risk_assessment`, `data_sources`
- [ ] No missing explainability records under load (compare decision count to record count)

### Swarm Health Gating Validation

**Additional Logging:**
```python
# Enable in merid/prediction/trading_agent.py and web/api/
logger.warning(f"Swarm health degraded: {component} at {health_pct:.1f}%, required {min_required}%")
logger.info(f"Trading blocked due to swarm health: {health_summary}")
logger.info(f"Health recovered: {component} now {health_pct:.1f}%")
```

**Metrics to Track:**
- `swarm_component_health_pct{component}` - Per-component health score
- `swarm_health_blocks_total` - Trades blocked due to health
- `swarm_health_check_latency_seconds` - Health check overhead
- `trading_agent_health_gate_status` - Boolean: healthy/degraded

**Validation Tests:**
- [ ] Mock degraded consensus engine (health <100%) and verify trade blocked
- [ ] Check explainability record includes health state snapshot
- [ ] Verify dashboard API surfaces health warnings when degraded
- [ ] Test recovery: degrade → heal and verify trading resumes
- [ ] Simulate rapid health fluctuations and verify no race conditions

## Success Criteria (24-72 Hour Validation)

### Phase 1 Criteria
- [ ] WS bridge maintains stable connection (>99% uptime)
- [ ] Orderbook updates received for all subscribed tickers
- [ ] No event drops or forward errors
- [ ] Explainability API returns real decision records
- [ ] Decision recording latency within targets (<10ms P99)
- [ ] No fabricated/stub data in any endpoint

### Phase 2 Criteria
- [ ] WS reconnect logic works correctly (exponential backoff observed)
- [ ] Sequence gaps detected and handled (cache invalidation + refresh)
- [ ] Rate limits respected (self-throttling effective, no 429 storms)
- [ ] All risk blocks emit explainability records with rule_id
- [ ] Swarm health checks block trading when health <100%
- [ ] No missing explainability records (100% decision coverage)
- [ ] Logs clean (no ERROR/CRITICAL messages)

## Post-Validation Actions

Once validation successful:

1. **Document Findings:**
   - Actual latencies observed vs targets
   - Any unexpected behaviors or edge cases
   - Rate-limit headroom (actual vs tier limit)

2. **Create Phase 2 GitHub Issues:**
   - Use specs from `.windsurf/tickets/`
   - Link to this validation report
   - Prioritize based on observed gaps

3. **Phase 2 Kickoff:**
   - Begin WS resilience tests first (highest priority)
   - Then rate-limit enforcement
   - Then risk explainability breadth

## Rollback Plan

If critical issues found during validation:

```bash
# Stop all services
pkill -f "uvicorn web.main"
pkill -f "ws_bridge_runner"
pkill -f "trading_agent_runner"

# Revert to previous stable commit
git checkout <previous_stable_commit>
pip install -r requirements.txt
alembic downgrade -1  # if migrations applied

# Restart services
python -m uvicorn web.main:app --host 0.0.0.0 --port 8000
```

## Contact & Escalation

**For Issues:**
- WS connectivity: Check Kalshi status page, network team
- Explainability bugs: Review commit `c25d2702` changes
- Performance issues: Profile with py-spy, check resource limits

**Phase 2 Ready?**
- Complete 24-72 hour validation period
- All success criteria met
- Findings documented
- GitHub issues created for Phase 2/3 work
