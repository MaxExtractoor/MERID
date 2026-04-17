# Kalshi Service Level Objectives (SLOs)

**Version:** 1.0  
**Date:** 2026-03-04  
**Scope:** Kalshi prediction market trading venue  

---

## Overview

These SLOs define the reliability targets for the Kalshi trading integration. They are based on the metrics now exported via `monitoring.kalshi_metrics` and alerted via `monitoring.alert_rules.yml`.

---

## SLO Summary Table

| SLO | Target | Measurement Window | Alert Threshold | Severity |
|-----|--------|-------------------|-------------------|----------|
| **API Availability** | 99.9% | 30 days | < 99.5% | Critical |
| **p99 API Latency** | < 500ms | 1 hour | > 1000ms | Warning |
| **p99.9 API Latency** | < 1000ms | 1 hour | > 2000ms | Critical |
| **Order Rejection Rate** | < 5% | 5 minutes | > 10% | Warning |
| **Circuit Breaker Open Rate** | < 0.1% | 24 hours | > 1% | Critical |
| **Kill Switch Triggers** | < 1 per week | 7 days | > 2 per week | Critical |
| **Error Rate (5xx)** | < 0.1% | 5 minutes | > 5% | Critical |
| **Correlation Risk Events** | < 2 per day | 24 hours | > 5 per day | Warning |
| **Regime Change Alerts** | < 10 per day | 24 hours | > 20 per day | Info |

---

## Detailed SLO Definitions

### 1. API Availability

**Target:** 99.9% over 30 days  
**Definition:** Percentage of successful API calls (2xx/3xx) vs total calls  
**Measurement:** `kalshi_api_requests_total` vs `kalshi_api_errors_total`  

**Error Budget:** 43 minutes of downtime per 30 days  

```promql
# Availability calculation
1 - (
  sum(rate(kalshi_api_errors_total[30d]))
  /
  sum(rate(kalshi_api_requests_total[30d]))
) > 0.999
```

---

### 2. API Latency (p99)

**Target:** < 500ms for 99th percentile over 1 hour  
**Definition:** 99% of API calls complete within 500ms  
**Measurement:** `kalshi_api_latency_seconds_bucket`  

**Alerting:**
- Warning: p99 > 1000ms for 3 minutes
- Critical: p99 > 2000ms for 1 minute

```promql
# p99 latency
histogram_quantile(0.99,
  sum(rate(kalshi_api_latency_seconds_bucket[1h])) by (le)
) < 0.5
```

---

### 3. Order Rejection Rate

**Target:** < 5% of orders rejected (excluding user-triggered)  
**Definition:** Percentage of orders rejected due to system/risk issues  
**Measurement:** `kalshi_orders_rejected_total` / `kalshi_orders_total`  

**Exclusions:**
- Kill switch triggered (expected)
- Circuit breaker open (expected)
- Invalid user parameters (user error)

```promql
# Rejection rate (excluding expected rejections)
rate(kalshi_orders_rejected_total{error_code!="kill_switch_active"}[5m])
/
rate(kalshi_orders_total[5m]) < 0.05
```

---

### 4. Circuit Breaker Health

**Target:** < 0.1% of time with circuit breaker open  
**Definition:** Percentage of 24h windows where CB was open > 1 minute  
**Measurement:** `kalshi_circuit_breaker_open`  

**Targets by State:**
- Closed: > 99.5% of time
- Half-Open: < 0.4% of time  
- Open: < 0.1% of time

---

### 5. Kill Switch Reliability

**Target:** < 1 kill switch trigger per week  
**Definition:** Manual/automatic kill switch activations  
**Measurement:** `kalshi_kill_switch_active` transitions to 1  

**Rationale:** Frequent kill switch triggers indicate:
- Risk limits too tight
- Market conditions outside model range
- Potential system issues

---

### 6. Error Rate (Infrastructure)

**Target:** < 0.1% 5xx errors from Kalshi API  
**Definition:** Percentage of requests returning 5xx status  
**Measurement:** `kalshi_api_errors_total{error_type="5xx"}`  

**Alerting:**
- Warning: > 1% error rate for 2 minutes
- Critical: > 5% error rate for 1 minute

---

### 7. Correlation Risk Events

**Target:** < 2 high-correlation events per day  
**Definition:** Number of times max correlation exceeds 0.85 for > 5 minutes  
**Measurement:** `kalshi_correlation_max > 0.85`  

**Business Impact:** High correlation reduces diversification benefits.

---

### 8. Regime Change Frequency

**Target:** < 10 regime changes per day per asset  
**Definition:** Number of regime transitions with confidence > 70%  
**Measurement:** `kalshi_regime` changes  

**Rationale:** Excessive regime flipping indicates:
- Noisy signals
- Choppy markets
- Potential over-trading

---

## Burn Rate Alerts

For critical SLOs, we use burn rate alerting to detect fast consumption of error budget:

| Burn Rate | Alert Window | Burn Time | Action |
|-----------|--------------|-----------|--------|
| 2% per hour | 1 hour | 50 hours | Page on-call |
| 5% per day | 24 hours | 20 days | Page on-call |
| 10% per week | 7 days | 10 weeks | Create ticket |

---

## Dashboard Requirements

### Primary Dashboard: "Kalshi SLOs"

**Panels:**
1. **Availability (30d)** - Gauge showing current vs target
2. **Latency Percentiles** - p50/p95/p99 lines over 1h
3. **Error Rate** - 5m rolling error percentage
4. **Order Rejection Rate** - Rejected vs total orders
5. **Circuit Breaker State** - Time series of CB state
6. **Kill Switch Timeline** - Markers for KS triggers
7. **Error Budget Burn** - Remaining budget for month
8. **Correlation Matrix** - Heatmap of asset correlations

### Secondary Dashboard: "Kalshi Performance"

**Panels:**
1. **API Request Rate** - RPS by endpoint
2. **Order Throughput** - Orders per minute by mode
3. **PnL Tracking** - Daily/weekly PnL
4. **Regime Distribution** - Pie chart of regime states
5. **Latency Distribution** - Histogram of latencies

---

## Runbook Links

| Alert | Runbook |
|-------|---------|
| Kalshi_Circuit_Breaker_Open | https://docs.merid.com/runbooks/kalshi-circuit-breaker |
| Kalshi_API_High_Latency | https://docs.merid.com/runbooks/kalshi-latency |
| Kalshi_Order_Rejection_Rate_High | https://docs.merid.com/runbooks/kalshi-order-rejections |
| Kalshi_Kill_Switch_Active | https://docs.merid.com/runbooks/kalshi-kill-switch |
| Kalshi_High_Volatility_Regime | https://docs.merid.com/runbooks/kalshi-regime-changes |
| Kalshi_High_Correlation_Risk | https://docs.merid.com/runbooks/kalshi-correlation-risk |

---

## Escalation Policy

| Severity | Response Time | Action |
|----------|---------------|--------|
| **Critical** | 5 minutes | Page on-call, auto-create incident |
| **Warning** | 30 minutes | Slack notification, create ticket |
| **Info** | 4 hours | Log only, daily digest |

---

## Review Cadence

- **Weekly:** Review SLO dashboards, check error budget burn
- **Monthly:** Adjust SLO targets based on observed performance
- **Quarterly:** Full SLO review with trading team

---

## Changelog

| Date | Change | Author |
|------|--------|--------|
| 2026-03-04 | Initial SLO definition | System |
