# EXPIRY_CHAOS_GO_NO_GO.md

**Purpose:** Go/No-Go readiness checklist for Kalshi crypto expiry chaos scenarios.

**Part of:** Kalshi Expiry Chaos Audit

---

## Executive Summary

This document provides a binary go/no-go decision framework for expiry-adjacent trading operations. Each gate must pass before proceeding to the next phase.

**Phases:**
1. **Pre-Session** (Before any trading)
2. **Continuous** (During trading, per-expiry cycle)
3. **Critical Window** (T-5m to expiry)
4. **Post-Settlement** (After expiry resolution)

---

## 1. Pre-Session Go/No-Go Gates

### Gate 1: System Configuration ✅

| Check | Command/Method | Expected | Status |
|-------|----------------|----------|--------|
| `MERID_RTI_SETTLEMENT_FINAL_SECONDS` | `env \| grep MERID` | 60 | ⬜ |
| `MERID_FILTER_RTI_MIN_SECONDS` | `env \| grep MERID` | 61 | ⬜ |
| `MERID_RTI_EXTENDED_GUARD_SECONDS` | `env \| grep MERID` | 120 | ⬜ |
| `MERID_RTI_ALLOW_BUY_IF_SETTLEMENT_GRADE` | `env \| grep MERID` | unset/false | ⬜ |
| `MERID_RTI_SETTLEMENT_ORDER_POLICY` | `env \| grep MERID` | reduce_ok | ⬜ |

**Gate 1 Verdict:** ⬜ **GO** / ⬜ **NO-GO**

---

### Gate 2: Settlement Data Pipeline ✅

| Check | Method | Expected | Status |
|-------|--------|----------|--------|
| RTI buffer operational | Health endpoint | `status: "healthy"` | ⬜ |
| Buffer filling for all tickers | Check buffer counts | ≥50/60 slots for active tickers | ⬜ |
| CFB adapter responding | Ping adapter | <500ms latency | ⬜ |
| Settlement poller active | Process check | Running | ⬜ |

**Gate 2 Verdict:** ⬜ **GO** / ⬜ **NO-GO**

---

### Gate 3: Agent Kill-Switch Systems ✅

| Check | Method | Expected | Status |
|-------|--------|----------|--------|
| Agent expiry proximity check | Code review | `_get_seconds_to_expiry` used | ⬜ |
| 90s hard block active | Test signal | Blocked with reason logged | ⬜ |
| 120s warning logged | Test signal | Warning visible in logs | ⬜ |
| Circuit breaker functional | Trigger test error | Agent pauses after 3 errors | ⬜ |
| Operator kill-switch accessible | UI/API test | Can disable agent | ⬜ |

**Gate 3 Verdict:** ⬜ **GO** / ⬜ **NO-GO**

---

### Gate 4: Ledger Consistency ✅

| Check | Method | Expected | Status |
|-------|--------|----------|--------|
| Last checkpoint within 60s | Check timestamp | <60s old | ⬜ |
| Checksum valid | Verify checkpoint | Checksum matches | ⬜ |
| Venue reconciliation clean | Run reconciliation | Zero mismatches | ⬜ |
| Position hash matches | Compare hashes | Ledger == Venue | ⬜ |

**Gate 4 Verdict:** ⬜ **GO** / ⬜ **NO-GO**

---

### Gate 5: Time Synchronization ✅

| Check | Method | Expected | Status |
|-------|--------|----------|--------|
| NTP sync active | `ntpstat` or equivalent | Synchronized | ⬜ |
| Max clock skew <5s | Measure vs pool | <5 seconds | ⬜ |
| Venue time accessible | API call | Kalshi time returned | ⬜ |
| Venue-to-system skew <10s | Compare timestamps | <10 seconds | ⬜ |

**Gate 5 Verdict:** ⬜ **GO** / ⬜ **NO-GO**

---

## 2. Continuous Per-Expiry Go/No-Go Gates

### Applied Every Expiry Cycle (T-5m onward)

| Gate | Check | Auto-Breach Action | Operator Alert |
|------|-------|-------------------|----------------|
| C1 | Buffer health ≥50/60 slots | Extended guard (120s) | Warning at T-120s |
| C2 | No reconciliation mismatches | Block new orders | Immediate alert |
| C3 | Clock skew <10s | Halt trading | Immediate alert |
| C4 | Agent errors <3 consecutive | Pause agent | Immediate alert |
| C5 | Venue API responding | Fallback to cached data | Degraded mode alert |

**All Gates C1-C5 Must Pass for Trading to Continue**

---

## 3. Critical Window Go/No-Go (T-5m to Expiry)

### Phase A: T-5m to T-2m (Caution Zone)

| Criteria | Threshold | Action if Breached |
|----------|-----------|-------------------|
| Orders per minute | ≤ normal rate | Reduce rate by 50% |
| Signal-to-order latency | <5s average | Alert if >10s |
| Position exposure | ≤ max limit | Block new positions |
| Buffer health | ≥55/60 slots | Extended guard mode |

**Phase A Verdict:** ⬜ **GO** / ⬜ **REDUCED MODE** / ⬜ **NO-GO**

---

### Phase B: T-2m to T-60s (Alert Zone)

| Criteria | Threshold | Action if Breached |
|----------|-----------|-------------------|
| New position openings | BLOCKED | N/A (always blocked) |
| Position reductions (sells) | ALLOWED with logging | Audit all sells |
| Buffer health | ≥58/60 slots | Alert, allow sells only |
| Checkpoint age | <30s | Emergency checkpoint |
| Any agent error | Any | Immediate halt |

**Phase B Verdict:** ⬜ **GO (Sells Only)** / ⬜ **NO-GO**

---

### Phase C: T-60s to Expiry (Critical Zone)

| Criteria | Threshold | Action if Breached |
|----------|-----------|-------------------|
| ANY new trading | **BLOCKED** | Emergency halt |
| Settlement buffer | Complete (60/60) | Alert if <60 |
| Process health | All green | Initiate graceful shutdown |
| Checkpoint freshness | <15s | Write emergency checkpoint |

**Phase C Verdict:** ⬜ **GO (Monitoring Only)** / ⬜ **EMERGENCY HALT**

---

## 4. Post-Settlement Go/No-Go Gates

### Settlement Verification (T+0 to T+5m)

| Check | Method | Expected | Status |
|-------|--------|----------|--------|
| Settlement price announced | Kalshi API | Price present | ⬜ |
| Price matches RTI calculation | Verify calculation | Within 1 cent | ⬜ |
| All positions marked settled | Ledger check | No open positions | ⬜ |
| Final PnL calculated | Ledger query | Value present | ⬜ |
| Settlement timestamp valid | Check ordering | After last trade | ⬜ |

**Post-Settlement Verdict:** ⬜ **GO** / ⬜ **AUDIT REQUIRED** / ⬜ **NO-GO**

---

## 5. Emergency Stop Criteria

**Immediate halt trading if ANY of the following occur:**

| Emergency Condition | Detection | Response |
|---------------------|-----------|----------|
| Ghost order detected | Reconciliation mismatch | Halt, audit, manual fix |
| Settlement price mismatch | LI-2 violation | Halt, verify with venue |
| Position resurrection | Venue shows closed position as open | Emergency halt, operator page |
| Clock skew >30s | NTP/venue comparison | Halt, investigate |
| Buffer corruption | Invalid slot data | Extended guard mode |
| Agent in restart loop | >2 restarts in 5m | Disable agent, alert |
| Settlement API unavailable | Timeout/error | Degraded mode, cache-only |

---

## 6. Recovery Procedures

### Recovery After Emergency Halt

1. **Assess:** Identify which gate failed and why
2. **Stabilize:** Fix root cause before resuming
3. **Verify:** Run all pre-session gates before restart
4. **Resume:** Start in paper mode for 1 expiry cycle
5. **Validate:** Confirm normal operation before live trading

### Recovery After Clean Shutdown (T-60s)

1. Wait for settlement announcement
2. Run settlement verification gates
3. Clear to proceed with next expiry cycle

---

## 7. Sign-Off Sheet

| Role | Name | Date | Signature |
|------|------|------|-----------|
| System Operator | | | |
| Risk Manager | | | |
| Technical Lead | | | |
| QA/Testing Lead | | | |

**All sign-offs required before expiry-adjacent trading begins.**

---

## 8. Quick Reference: Decision Tree

```
Pre-Session Check
├── Gate 1 (Config) → FAIL → NO-GO, fix config
├── Gate 2 (Pipeline) → FAIL → NO-GO, fix pipeline
├── Gate 3 (Kill-Switch) → FAIL → NO-GO, fix agent
├── Gate 4 (Ledger) → FAIL → NO-GO, run reconciliation
└── Gate 5 (Time) → FAIL → NO-GO, fix NTP
    └── ALL PASS → GO to Continuous

Continuous Check (T-5m)
├── C1-C5 All Pass → GO (Normal Mode)
│   └── T-2m → GO (Sells Only Mode)
│       └── T-60s → GO (Monitoring Only)
│           └── Settlement → Post-Settlement Gates
└── Any C1-C5 Fail → Apply Breach Action
    └── Critical → Emergency Halt
```

---

## 9. Related Documents

- `KALSHI_RTI_SETTLEMENT_WINDOW_REFERENCE.md` — RTI settlement rules
- `EXPIRY_BEHAVIOR_MAP.md` — Current system behavior
- `EXPIRY_CHAOS_TEST_PLAN.md` — Test scenarios
- `EXPIRY_LEDGER_INVARIANTS.md` — Ledger consistency rules

---

*Document Version: 1.0*
*Last Updated: 2025-01-26*
*Part of: Kalshi Expiry Chaos Audit*
