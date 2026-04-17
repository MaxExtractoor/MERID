# RB-OPS-003: On-Call & Escalation Policy

**Last updated:** 2026-02-07
**Owner:** Operations
**Review cadence:** Monthly

---

## Escalation Tiers

| Tier | Role | Response SLA | Channel | Hours |
|------|------|-------------|---------|-------|
| T0 | Automated | Immediate | Kill switch / circuit breaker | 24/7 |
| T1 | On-call operator | < 5 min | Telegram bot alert | 24/7 |
| T2 | Engineering lead | < 15 min | Telegram group + phone | Business hours + on-call |
| T3 | Incident commander | < 30 min | All channels | As needed |

---

## Automated Response (T0)

These fire **without human intervention**:

| Trigger | Action | Module |
|---------|--------|--------|
| Daily loss > 5% | Halt all trading | `TradingHaltManager.check_daily_loss()` |
| Drawdown > 15% | Halt all trading | `TradingHaltManager.check_drawdown()` |
| ≥ 2 circuit breakers open | Halt all trading | `TradingHaltManager.check_circuit_breakers()` |
| Emergency anomaly detected | Halt all trading | `AnomalyDetectionStack.should_halt()` |
| Stale data feed | Halt affected domain | `FeedStalenessMonitor.on_stale()` |
| Kill switch activated | Halt all trading | `DomainControlPanel` UI or API |

---

## T1: On-Call Operator

### Notification Channels

1. **Telegram Bot** (primary) — `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`
   - All P1/P2 alerts forwarded automatically
   - Bot commands: `/status`, `/halt`, `/resume`, `/positions`

2. **Alertmanager → Telegram** (backup)
   - Critical severity alerts routed to `telegram-critical` receiver
   - Configured in `monitoring/alertmanager.yml`

3. **Email** (audit trail)
   - All alerts cc'd to `ops-team@merid.com` via default receiver

### On-Call Schedule

| Day | Primary | Backup |
|-----|---------|--------|
| Mon-Fri | Operator A | Operator B |
| Sat-Sun | Operator B | Operator A |

> **Note:** Update this table with actual names. For single-operator deployments,
> the Telegram bot serves as the always-on notification layer.

### On-Call Responsibilities

1. Acknowledge alerts within 5 minutes
2. Assess severity (P1/P2/P3)
3. For P1: Verify automated halt fired, begin investigation
4. For P2: Monitor, escalate to T2 if not resolved in 15 min
5. For P3: Log and address during business hours

---

## T2: Engineering Escalation

### When to Escalate

- Automated halt fired but root cause unclear
- Data corruption suspected
- Multiple systems affected
- Recovery requires code changes

### How to Escalate

```bash
# Via Telegram group
/escalate "Brief description of issue"

# Via API
curl -X POST http://localhost:8000/api/v1/pipeline/domain/halt \
  -d '{"domain":"all","reason":"Escalating to T2 - <description>"}'
```

---

## T3: Incident Commander

### When to Activate

- Financial loss exceeding $1,000
- System-wide outage > 30 minutes
- Data breach or security incident
- External dependency failure affecting all trading

### Incident Commander Duties

1. Coordinate response across all tiers
2. Make go/no-go decisions on recovery actions
3. Authorize rollbacks (see `RB-OPS-001-rollback-procedure.md`)
4. Initiate PIR process (see `RB-OPS-002-post-incident-review.md`)
5. Handle external communications if needed

---

## Severity Classification

| Severity | Description | Response | Example |
|----------|-------------|----------|---------|
| P1 | Trading halted, active loss | T0 auto + T1 < 5 min | Circuit breaker cascade, data corruption |
| P2 | Degraded but operational | T1 < 15 min | Single venue down, stale feed |
| P3 | Minor issue, no impact | Next business day | Dashboard glitch, non-critical log errors |

---

## Verification Checklist

Run periodically to verify escalation chain works:

- [ ] Telegram bot responds to `/status` command
- [ ] Alertmanager test alert reaches Telegram (`python monitoring/verify-alertmanager.py --test-telegram`)
- [ ] TLS verification passes (`bash infra/verify-tls.sh`)
- [ ] Kill switch halts trading within 1 second
- [ ] On-call operator acknowledges test alert within 5 minutes
- [ ] Rollback procedure rehearsed (quarterly drill via `ops/drills/3am_simulation.py`)

---

## Tools Quick Reference

| Action | Command |
|--------|---------|
| Check system health | `curl localhost:8000/healthz` |
| Check readiness | `curl localhost:8000/readyz` |
| Halt all trading | `curl -X POST localhost:8000/api/v1/pipeline/domain/halt -d '{"domain":"all"}'` |
| Resume trading | `curl -X POST localhost:8000/api/v1/pipeline/domain/resume -d '{"domain":"all"}'` |
| View positions | `curl localhost:8000/api/v1/trading/portfolio/summary` |
| View open orders | `curl localhost:8000/api/v1/trading/orders/open` |
| Run backup | `python -m ops.backup_restore backup` |
| List backups | `python -m ops.backup_restore list` |
| Validate alerts | `python monitoring/verify-alertmanager.py` |
| Validate TLS | `bash infra/verify-tls.sh` |
