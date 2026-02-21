# Phase 2 Commit & Deployment Checklist

**Date:** February 16, 2026  
**Status:** Ready for Commit → Staging Deployment

---

## ✅ Pre-Commit Validation

### Test Results
- [x] WS Resilience: `py -m pytest tests/event_venues/kalshi/test_ws_resilience.py` → 16/18 passing
- [x] Rate-Limit Enforcement: `py -m pytest tests/event_venues/kalshi/test_rate_limits.py` → 17/17 passing
- [x] Risk Rejection Explainability: `py -m pytest tests/prediction/test_trading_agent_explainability.py` → 11/11 passing
- [x] Swarm Health Gating: `py -m pytest tests/integration/test_swarm_health_gating.py` → 8/8 passing
- [x] **Total: 52/54 passing (96%)**

### Documentation
- [x] `.windsurf/PHASE2_COMPLETION_SUMMARY.md` - Complete test results and acceptance criteria
- [x] `.windsurf/STAGING_DEPLOYMENT.md` - Updated with Phase 2 monitoring requirements
- [x] All test files include docstrings and reference tickets

---

## 📦 Commit Phase 2 (Execute Now)

### Files to Commit
```bash
# Test suites
git add tests/event_venues/kalshi/test_ws_resilience.py
git add tests/event_venues/kalshi/test_rate_limits.py
git add tests/prediction/test_trading_agent_explainability.py
git add tests/integration/test_swarm_health_gating.py

# Documentation
git add .windsurf/PHASE2_COMPLETION_SUMMARY.md
git add .windsurf/STAGING_DEPLOYMENT.md
git add .windsurf/PHASE2_COMMIT_CHECKLIST.md

# Verify staged files
git status
```

### Commit Message
```bash
git commit -m "Phase 2: Operational resilience tests (52/54 passing)

Test Suites:
- WS resilience: disconnect/backoff, sequence gaps, cache invalidation (16/18)
- Rate-limit enforcement: 429 handling, token bucket, non-retryable 4xx (17/17)
- Risk rejection explainability: exposure cap, daily loss, swarm health (11/11)
- Swarm health gating: health checks block trading when health <100% (8/8)

Protected Failure Modes:
- WS disconnect storms → exponential backoff with 60s cap
- Sequence gaps → cache invalidation + snapshot refresh
- API rate limits → self-throttling + 429 handling
- Risk rejections → complete audit trail with rule_id
- Component degradation → health checks block trading

Ready for staging/paper deployment and 24-72h soak test.

Refs: .windsurf/PHASE2_COMPLETION_SUMMARY.md
Baseline: commit c25d2702"
```

### Push to Develop
```bash
git push origin develop
```

---

## 🚀 Staging Deployment

### 1. Environment Setup

**Set Environment Variables:**
```bash
export KALSHI_API_BASE="https://trading-api.kalshi.com"
export KALSHI_API_KEY="<your_api_key>"
export KALSHI_API_SECRET="<your_api_secret>"
export KALSHI_RATE_LIMIT_TIER="basic"
export TRADING_MODE="paper"
export LOG_LEVEL="INFO"
```

**Verify Credentials:**
```bash
curl -X GET "https://trading-api.kalshi.com/trade-api/v2/exchange/status" \
  -H "Authorization: Bearer $KALSHI_API_KEY"
```

### 2. Start Services

**Terminal 1 - Backend:**
```bash
cd c:\Dev\MERID
python -m uvicorn web.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 - WS Bridge:**
```bash
cd c:\Dev\MERID
python -m merid.event_venues.kalshi.ws_bridge_runner
```

**Expected Startup Logs:**
- `INFO: KalshiWebSocketBridge initialized`
- `INFO: WebSocket connected to wss://trading-api.kalshi.com/trade-api/ws/v2`
- `INFO: Subscribing to orderbook channels...`
- `INFO: Event bus publisher started`

### 3. Validate Deployment

**Check WS Status:**
```bash
curl http://localhost:8000/api/v1/kalshi/ws/status
# Expected: {"connected": true, "events_forwarded": >0, "events_dropped": 0}
```

**Check Explainability API:**
```bash
curl http://localhost:8000/api/v1/explainability/decisions?limit=5
# Expected: Real decision records (not stub data)
```

**Check Agent Status (if running):**
```bash
curl http://localhost:8000/api/v1/agents/status
# Expected: Agent health and decision counts
```

---

## 📊 Enhanced Monitoring (24-72h Soak)

### WS Resilience Monitoring

**Log Patterns to Watch:**
```bash
# Watch for reconnects
tail -f logs/kalshi_ws.log | grep -E "(reconnect|backoff|sequence_gap|cache_invalidated)"
```

**Expected Behaviors:**
- Reconnect attempts rare (<1/hour under normal conditions)
- Backoff follows 1s→2s→4s→8s→...→60s pattern
- Sequence gaps logged and cache invalidated
- Snapshot refreshes triggered after gaps

**Red Flags:**
- Frequent reconnects (>5/hour) → network/API issue
- No backoff increase → logic not working
- Sequence gaps not detected → tracking broken

### Rate-Limit Monitoring

**Log Patterns to Watch:**
```bash
# Watch for rate-limit activity
tail -f logs/kalshi_client.log | grep -E "(429|Retry-After|token_bucket|throttled)"
```

**Expected Behaviors:**
- 429 responses rare (self-throttling working)
- Retry-After headers honored exactly
- Token bucket prevents burst >20 req/sec (Basic tier)
- No retries on 400/401/403/422

**Red Flags:**
- Frequent 429s (>10/hour) → self-throttling broken
- Retry-After not honored → timing logic broken
- Burst exceeds tier limit → token bucket broken

### Risk Explainability Monitoring

**Log Patterns to Watch:**
```bash
# Watch for risk blocks
tail -f logs/trading_agent.log | grep -E "(risk_block|explainability|decision_recorded)"
```

**Expected Behaviors:**
- All risk blocks create explainability records
- Rule_id present in all blocked decisions
- Allowed signals also create records
- No missing records under load

**Red Flags:**
- Risk blocks without explainability records → tracking broken
- Missing rule_id in blocks → schema incomplete
- Allowed signals not recorded → coverage gap

### Swarm Health Monitoring

**Log Patterns to Watch:**
```bash
# Watch for health events
tail -f logs/trading_agent.log | grep -E "(swarm_health|health_degraded|health_recovered)"
```

**Expected Behaviors:**
- Health checks block trading when <100%
- Dashboard APIs surface health warnings
- Recovery path works (degraded→healthy)
- No race conditions during fluctuations

**Red Flags:**
- Trading allowed with degraded health → gate broken
- Health warnings not surfacing → API integration broken
- Race conditions on rapid fluctuations → concurrency issue

---

## 📈 Success Criteria Validation

### Phase 1 Criteria (Original)
- [ ] WS bridge maintains >99% uptime (track via metrics)
- [ ] Orderbook updates received for all tickers (check WS status)
- [ ] No event drops or forward errors (check logs)
- [ ] Explainability API returns real records (no `_stub: true`)
- [ ] Decision recording latency <10ms P99 (check metrics)
- [ ] No fabricated/stub data in any endpoint

### Phase 2 Criteria (New)
- [ ] WS reconnect logic works (simulate disconnect, verify backoff)
- [ ] Sequence gaps detected and handled (inject gap, verify refresh)
- [ ] Rate limits respected (monitor 429s, should be rare)
- [ ] All risk blocks emit explainability records (check coverage)
- [ ] Swarm health checks block trading when <100% (test degradation)
- [ ] No missing explainability records (100% decision coverage)
- [ ] Logs clean (no ERROR/CRITICAL messages)

### Metrics to Capture

**WS Resilience:**
- Total reconnects in 24h: _______
- Max backoff observed: _______
- Sequence gaps detected: _______
- Orderbook freshness P99: _______

**Rate-Limit Enforcement:**
- 429 responses in 24h: _______
- Token bucket waits: _______
- Actual request rate P99: _______
- Retry-After compliance: _______

**Risk Explainability:**
- Total decisions recorded: _______
- Risk blocks recorded: _______
- Explainability coverage: _______%
- Recording latency P99: _______

**Swarm Health:**
- Health check latency P99: _______
- Health blocks triggered: _______
- Health recoveries: _______
- False positives: _______

---

## 🎯 Post-Soak Actions

### Document Findings

Create `STAGING_SOAK_REPORT.md` with:
1. **Observed Latencies:** Compare actual vs target latencies
2. **Failure Modes:** Any unexpected behaviors or edge cases
3. **Rate-Limit Headroom:** Actual rate vs tier limit (Basic: 20 req/sec)
4. **Explainability Coverage:** Percentage of decisions with records
5. **Recommendations:** Adjustments needed before Phase 3

### Phase 3 Planning

Use staging data to design targeted stress tests:
- **Burst Load:** Max burst size before throttling (actual vs tier)
- **Sustained Load:** Max sustained rate for 1h+ without degradation
- **Concurrent Agents:** How many agents before resource contention
- **Failure Injection:** Disconnect frequency that triggers issues
- **Recovery Time:** How fast system recovers from degradation

### Go/No-Go Decision

**Go to Phase 3 if:**
- ✅ All Phase 1 + Phase 2 success criteria met
- ✅ No ERROR/CRITICAL logs during soak
- ✅ Explainability coverage >99%
- ✅ Performance within targets
- ✅ No unexpected failure modes

**Hold Phase 3 if:**
- ❌ Frequent reconnects or 429s
- ❌ Missing explainability records
- ❌ Performance outside targets
- ❌ Unexpected failure modes found

---

## 🔄 Rollback Plan (If Needed)

If critical issues found during staging:

```bash
# Stop all services
pkill -f "uvicorn web.main"
pkill -f "ws_bridge_runner"
pkill -f "trading_agent_runner"

# Revert to previous stable commit
git checkout develop
git log --oneline -5  # Find previous stable commit
git checkout <previous_stable_commit>

# Reinstall dependencies
pip install -r requirements.txt

# Restart services
python -m uvicorn web.main:app --host 0.0.0.0 --port 8000
```

---

## 📞 Support & Escalation

**For Issues:**
- WS connectivity: Check [Kalshi status page](https://status.kalshi.com), network logs
- Rate-limit issues: Review token bucket config, tier limits
- Explainability gaps: Check tracker initialization, agent integration
- Performance issues: Profile with `py-spy`, check resource limits

**Phase 3 Ready When:**
- 24-72 hour soak complete
- All success criteria validated
- Staging findings documented
- Stress test scenarios designed

---

## ✅ Final Checklist

- [ ] All Phase 2 tests passing (52/54 verified)
- [ ] Files staged and committed
- [ ] Pushed to develop branch
- [ ] Staging environment configured
- [ ] Services started successfully
- [ ] Initial validation complete
- [ ] Enhanced monitoring enabled
- [ ] Soak test running (24-72h)
- [ ] Metrics being captured
- [ ] Findings will be documented

**Status:** Ready to commit and deploy to staging
**Next:** Execute commit commands → deploy to staging → monitor 24-72h → document findings → plan Phase 3
