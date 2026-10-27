# Kalshi Integration Monitoring Cheat Sheet

Quick reference for operators monitoring the Merid-Kalshi integration.

---

## Health Check Commands

```bash
# Check WS Bridge health
curl -s http://localhost:8080/health/kalshi/ws_bridge | jq .

# Expected output:
# {
#   "status": "GREEN",
#   "recent_task_failures": 0,
#   "running": true,
#   "uptime_s": 3600.5
# }

# Check WS callback health
curl -s http://localhost:8080/health/kalshi/ws | jq .

# Expected output:
# {
#   "failure_count_60s": 0,
#   "healthy": true,
#   "last_failure_ts": 0
# }
```

---

## Critical Log Queries

### Check for CRASH-001 (WS Bridge Task Crash)
```bash
grep -E "CRASH-001|WS bridge task.*crashed" /var/log/merid/kalshi.log | tail -20
```
**Action if found:** Verify auto-reconnect succeeded; escalate if repeated.

---

### Check for CRASH-002 (Callback Failure Storm)
```bash
grep -E "CRASH-002|Too many callback failures" /var/log/merid/kalshi.log | tail -20
```
**Action if found:** System auto-reconnects; verify health returns to GREEN.

---

### Check for CRASH-004 (Position Cache Failures)
```bash
grep -E "CRASH-004|position_cache_unavailable" /var/log/merid/kalshi.log | tail -20
```
**Action if found:** Orders are safely rejected; check position cache connectivity.

---

### Check for CRASH-006 (Reconnect Storm)
```bash
grep -E "CRASH-006|Reconnecting to Kalshi" /var/log/merid/kalshi.log | tail -30
```
**Action if found:** Lock prevents concurrent reconnects; wait for exponential backoff.

---

## Metric Queries (Prometheus/Grafana)

### Callback Failure Rate
```promql
rate(kalshi_ws_callback_failure_total[5m])
```
**Alert if:** > 0.5 per second (30/min)

---

### Task Crash Count
```promql
increase(kalshi_ws_bridge_task_crash_total[5m])
```
**Alert if:** > 0

---

### Position Cache Failure Rate
```promql
rate(kalshi_position_cache_failure_total[5m])
```
**Alert if:** > 0.1 per second (6/min)

---

### Reconnect Rate
```promql
rate(kalshi_ws_reconnect_total[5m])
```
**Alert if:** > 0.02 per second (> 1/min)

---

## Status Color Guide

| Color | Meaning | Operator Action |
|-------|---------|-----------------|
| 🟢 **GREEN** | Healthy | None - normal operation |
| 🟡 **YELLOW** | Degraded, auto-recovering | Monitor, prepare for escalation |
| 🔴 **RED** | Critical, intervention needed | Investigate immediately, consider restart |

---

## Emergency Procedures

### If Health is RED

1. **Check logs immediately:**
   ```bash
   tail -100 /var/log/merid/kalshi.log | grep -E "ERROR|CRITICAL|CRASH"
   ```

2. **Verify connectivity:**
   ```bash
   curl -I https://api.elections.kalshi.com/trade-api/v2/exchanges 2>/dev/null | head -1
   ```

3. **If needed, restart bridge:**
   ```bash
   curl -X POST http://localhost:8080/admin/restart/kalshi/ws_bridge
   ```

4. **If still RED after restart, escalate to:** @sre-oncall @trading-leads

---

### If Order Rejection Rate Spikes

```bash
# Check rejection reasons
jq -r '.reason' /var/log/merid/orders.log | sort | uniq -c | sort -rn | head -10
```

**Common patterns:**
- `position_cache_unavailable` → Position cache issue (CRASH-004)
- `invalid_order_params` → Input validation firing (CRASH-007)
- `gate:duplicate` → Normal idempotency (not an issue)
- `stale_snapshot` → Market data delayed

---

## Contact Escalation

| Issue | Slack Channel | PagerDuty |
|-------|--------------|-----------|
| WS/Connectivity | #infra-kalshi | sre-oncall |
| Order Routing | #trading-systems | trading-leads |
| Risk/Gate | #risk-systems | risk-oncall |
| All RED alerts | #incidents | sre-oncall |
