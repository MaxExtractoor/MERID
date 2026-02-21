# Phase 7 SLO and Error Budget Reference

## Production SLO Targets for Phase 7

### Core SLIs (Service Level Indicators)

| SLI | Measurement | Target | Notes |
|-----|-------------|--------|-------|
| **Availability** | Successful strategy+execution cycles / total attempts | 99.9% | Production lane availability |
| **Decision Latency** | Strategy decision time (signal → decision) | p50 ≤ 100ms, p95 ≤ 200ms | Hard cap at 500ms (kill switch) |
| **Execution Latency** | Order submit → acknowledgment | p50 ≤ 200ms, p95 ≤ 400ms | Hard cap at 1000ms (kill switch) |
| **Error Rate** | Failed requests / total requests | ≤ 0.1% | Kill switch at 1% |
| **Correctness** | Correct symbol/side/size/venue trades | ≥ 99.99% | Any violation is Sev-0 |
| **P&L Risk** | Daily loss and drawdown limits | Loss ≤ $500, Drawdown ≤ 2% | Hard safety constraints |

### Error Budget Calculations

**Monthly Error Budget (30 days):**
- 99.9% SLO → Error budget = 0.1% = 0.001
- For 1,000,000 requests/month → **1,000 failed requests allowed**
- For 10,000 trading decisions/month → **10 failed decisions allowed**

**Downtime Equivalents:**
- 99.9% availability → **43.2 minutes downtime/month**
- 99.99% availability → **4.3 minutes downtime/month**
- 99.999% availability → **26 seconds downtime/month**

### Burn Rate Formulas and Thresholds

**Burn Rate Calculation:**
```
B = E_used / E_budget
```
Where:
- `E_used` = errors in current window
- `E_budget` = total errors allowed in 30-day period

**Alert Thresholds:**

| Alert Type | Window | Trigger | Action |
|------------|--------|---------|--------|
| **Fast Burn (Critical)** | 30-60 minutes | B ≥ 10 | Immediate incident, halt lane |
| **Slow Burn (Warning)** | 6-12 hours | B ≥ 1 | Investigate, freeze deploys |
| **Budget Exhausted** | 30 days | Cumulative ≥ 100% | Change freeze, post-incident review |

**Examples:**
- 60 errors in 30 minutes (budget 1000) → B = 0.06 → Not critical
- 200 errors in 30 minutes → B = 0.2 → Fast burn alert
- 1000 errors in 1 hour → B = 1.0 → Exhaust daily budget quickly

### Production-Specific SLIs

#### Trading Lane SLIs
- **Order Success Rate**: Successful orders / total orders ≥ 99.95%
- **Slippage Control**: Orders with ≤ 5bps slippage ≥ 99%
- **Position Limits**: Orders respecting concentration limits ≥ 99.99%
- **Venue Health**: Venue API success rate ≥ 99.9%

#### Risk Management SLIs
- **Limit Enforcement**: Orders respecting capital/position limits ≥ 99.99%
- **Kill Switch Response**: Time from trigger to lane halt ≤ 10 seconds
- **Rollback Success**: Successful position unwind on halt ≥ 99.9%

### Mobile Login Reference (for comparison)

**SLIs:**
- Success Rate: Successful authenticated sessions / total login attempts
- Latency: Fraction completing under threshold (tap → home screen)

**Latency Targets:**
- p50: ≤ 300-400ms
- p95: ≤ 800-1000ms  
- p99: ≤ 2000-2500ms

### Weekly/Yearly Downtime Allowances

| SLO | Weekly Downtime | Yearly Downtime |
|-----|-----------------|-----------------|
| 99.9% | ~10 minutes | ~8.8 hours |
| 99.99% | ~1 minute | ~52 minutes |
| 99.999% | ~6 seconds | ~5 minutes |

### Escalation Policy for Phase 7

**Level 1 (Fast Burn):**
- Trigger: B ≥ 10 in 30-60 minutes
- Actions: 
  - Immediate lane halt
  - Page on-call engineer
  - Roll back recent changes
  - Incident documentation

**Level 2 (Slow Burn):**
- Trigger: B ≥ 1 in 6-12 hours
- Actions:
  - Investigate root cause
  - Freeze new deployments
  - Consider reducing capital/venue scope
  - Schedule reliability work

**Level 3 (Budget Exhausted):**
- Trigger: Cumulative errors ≥ 100% of monthly budget
- Actions:
  - Maintain change freeze
  - Post-incident review required
  - Update SLOs/runbooks
  - Executive notification for production impact

### Implementation Notes for Phase 7

1. **Real-time Monitoring**: Track SLIs continuously with 1-minute granularity
2. **Automated Alerts**: Configure burn rate alerts in monitoring system
3. **Kill Switch Integration**: Wire SLO breaches to automatic lane halt
4. **Dashboard Visibility**: Display current error budget usage and burn rate
5. **Post-Incident Process**: Document all breaches and update safeguards

### Quick Reference Formulas

**Error Budget Percentage:**
```
Error Budget % = 100% - SLO %
```

**Monthly Failed Requests:**
```
Failed Requests = Monthly Requests × Error Budget %
```

**Burn Rate:**
```
Burn Rate = Errors in Window / Monthly Error Budget
```

**Time to Exhaust:**
```
Time to Exhaust = Window Length / Burn Rate
```

**Example Calculation:**
- SLO: 99.9% (Error Budget: 0.1%)
- Monthly Requests: 1,000,000
- Allowed Failures: 1,000
- Current: 100 errors in 1 hour
- Burn Rate: 100/1000 = 0.1
- Time to Exhaust: 1 hour / 0.1 = 10 hours

This reference provides the mathematical foundation for Phase 7 production SLO monitoring and error budget management.
