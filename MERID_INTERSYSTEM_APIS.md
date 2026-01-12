# MERID INTER-SYSTEM API CONTRACTS — CANONICAL SPECIFICATION

**Version:** 1.0.0  
**Status:** FROZEN  
**Last Updated:** 2026-01-11  
**Authority:** Master Build Directive  

---

## PURPOSE

This document defines **explicit inter-system API contracts** with:

- Authority boundaries
- Request/response schemas
- Invariants and constraints
- Error handling requirements

This is **fund-grade internal documentation** for implementation without reinterpretation.

---

## CONTRACT 1: OPS → GOV

### Intent Proposal Contract

**Endpoint:** `POST /gov/intents/propose`

**Purpose:** OPS proposes trading intents to GOV for approval.

#### Request Schema

```json
{
  "intent_id": "uuid",
  "origin_system": "OPS",
  "strategy_id": "string",
  "regime": "TRENDING_BULL | TRENDING_BEAR | MEAN_REVERTING | HIGH_VOLATILITY | CRISIS | UNKNOWN",
  "confidence": 0.0-1.0,
  "risk_preview": {
    "max_drawdown_pct": "float",
    "corr_exposure": "float",
    "var_95": "float",
    "cvar_95": "float"
  },
  "shadow_simulation": {
    "expected_return": "float",
    "p_loss": "float",
    "sharpe_ratio": "float",
    "max_adverse_excursion": "float"
  },
  "position_request": {
    "asset": "string",
    "side": "LONG | SHORT",
    "notional_usd": "float",
    "leverage": "float"
  },
  "expiry_ts": "unix_timestamp",
  "metadata": {
    "signal_sources": ["string"],
    "epistemic_confidence": "float",
    "regime_confidence": "float"
  }
}
```

#### Response Schema

```json
{
  "intent_id": "uuid",
  "status": "PENDING | APPROVED | REJECTED | EXPIRED",
  "review_agents": ["string"],
  "constraints_applied": {
    "max_notional": "float",
    "slippage_bps": "int",
    "time_lock_sec": "int"
  },
  "rejection_reason": "string | null",
  "approval_ts": "unix_timestamp | null"
}
```

#### Invariants (Contract 1)

| Rule | Enforcement |
| ---- | ----------- |
| Must include shadow simulation | Request rejected without it |
| Must include regime | Request rejected without it |
| Expires automatically | `expiry_ts` enforced by GOV |
| Confidence threshold | `confidence >= 0.5` required |
| Risk preview mandatory | All fields required |

#### Error Codes (Contract 1)

| Code | Meaning |
| ---- | ------- |
| `ERR_MISSING_SHADOW_SIM` | Shadow simulation not provided |
| `ERR_MISSING_REGIME` | Regime not specified |
| `ERR_LOW_CONFIDENCE` | Confidence below threshold |
| `ERR_EXPIRED` | Intent expired before review |
| `ERR_RISK_LIMIT_BREACH` | Risk preview exceeds limits |

---

## CONTRACT 2: GOV → FIN

### Execution Authorization Contract

**Endpoint:** `POST /fin/execute/authorize`

**Purpose:** GOV authorizes FIN to execute an approved intent.

#### Request Schema (Contract 2)

```json
{
  "intent_id": "uuid",
  "approved_by": ["string"],
  "approval_quorum": {
    "required": "int",
    "achieved": "int"
  },
  "constraints": {
    "max_notional": "float",
    "slippage_bps": "int",
    "time_lock_sec": "int",
    "max_market_impact_bps": "int",
    "execution_deadline_ts": "unix_timestamp"
  },
  "mode": "AUTO | MANUAL_REQUIRED | SIMULATION_ONLY",
  "kill_switch": {
    "enabled": true,
    "trigger_conditions": ["string"]
  },
  "routing_preferences": {
    "preferred_venues": ["string"],
    "excluded_venues": ["string"],
    "mev_protection": "ENABLED | DISABLED"
  }
}
```

#### Response Schema (Contract 2)

```json
{
  "intent_id": "uuid",
  "execution_id": "uuid",
  "status": "ACCEPTED | REJECTED | QUEUED",
  "estimated_execution_ts": "unix_timestamp",
  "rejection_reason": "string | null"
}
```

#### Invariants (Contract 2)

| Rule | Enforcement |
| ---- | ----------- |
| FIN cannot modify constraints | Immutable after authorization |
| Kill-switch always available | Cannot be disabled by FIN |
| Quorum must be achieved | `approval_quorum.achieved >= approval_quorum.required` |
| Execution deadline enforced | Auto-cancel after deadline |
| Mode respected | MANUAL_REQUIRED blocks auto-execution |

#### Error Codes (Contract 2)

| Code | Meaning |
| ---- | ------- |
| `ERR_INVALID_INTENT` | Intent ID not found or expired |
| `ERR_QUORUM_NOT_MET` | Insufficient approvals |
| `ERR_CONSTRAINT_VIOLATION` | Constraints cannot be satisfied |
| `ERR_VENUE_UNAVAILABLE` | Preferred venues offline |
| `ERR_KILL_SWITCH_ACTIVE` | Execution blocked by kill switch |

---

## CONTRACT 3: FIN → GOV

### Execution Report Contract

**Endpoint:** `POST /gov/executions/report`

**Purpose:** FIN reports execution outcomes to GOV.

#### Request Schema (Contract 3)

```json
{
  "execution_id": "uuid",
  "intent_id": "uuid",
  "status": "COMPLETED | PARTIAL | FAILED | CANCELLED",
  "execution_details": {
    "filled_notional": "float",
    "avg_price": "float",
    "slippage_bps": "int",
    "fees_usd": "float",
    "venue": "string",
    "execution_ts": "unix_timestamp"
  },
  "market_impact": {
    "estimated_bps": "int",
    "actual_bps": "int"
  },
  "anomalies_detected": [
    {
      "type": "string",
      "severity": "LOW | MEDIUM | HIGH | CRITICAL",
      "description": "string"
    }
  ],
  "mev_analysis": {
    "front_run_detected": "boolean",
    "sandwich_detected": "boolean",
    "estimated_mev_loss_usd": "float"
  }
}
```

#### Response Schema (Contract 3)

```json
{
  "execution_id": "uuid",
  "acknowledged": true,
  "follow_up_actions": ["string"],
  "alert_triggered": "boolean"
}
```

#### Invariants (Contract 3)

| Rule | Enforcement |
| ---- | ----------- |
| All executions must be reported | FIN cannot suppress reports |
| Anomalies escalate automatically | HIGH/CRITICAL trigger alerts |
| MEV losses tracked | Cumulative tracking in GOV |

---

## CONTRACT 4: FIN → TREASURY

### Profit Routing Contract

**Endpoint:** `POST /treasury/profits/deposit`

**Purpose:** FIN routes realized profits to TREASURY.

#### Request Schema (Contract 4)

```json
{
  "source_intent": "uuid",
  "execution_id": "uuid",
  "amount": "float",
  "asset": "string",
  "classification": "PROFIT_ONLY",
  "source_strategy": "string",
  "realized_ts": "unix_timestamp",
  "verification": {
    "pnl_calculation": {
      "entry_price": "float",
      "exit_price": "float",
      "quantity": "float",
      "fees_deducted": "float"
    },
    "audit_hash": "string"
  }
}
```

#### Response Schema (Contract 4)

```json
{
  "deposit_id": "uuid",
  "status": "ACCEPTED | REJECTED | PENDING_VERIFICATION",
  "vault_assigned": "string",
  "rejection_reason": "string | null"
}
```

#### Invariants (Contract 4)

| Rule | Enforcement |
| ---- | ----------- |
| Losses never routed | `amount > 0` required |
| Principal never touched | Classification enforced |
| Verification required | PnL calculation must match |
| Audit hash immutable | Stored in ARCHIVE |

#### Error Codes (Contract 4)

| Code | Meaning |
| ---- | ------- |
| `ERR_NEGATIVE_AMOUNT` | Cannot deposit losses |
| `ERR_PRINCIPAL_VIOLATION` | Attempted principal access |
| `ERR_VERIFICATION_FAILED` | PnL calculation mismatch |
| `ERR_INVALID_ASSET` | Asset not in approved list |

---

## CONTRACT 5: TREASURY → GOV

### Capital Request Contract

**Endpoint:** `POST /gov/capital/request`

**Purpose:** TREASURY requests capital allocation approval from GOV.

#### Request Schema (Contract 5)

```json
{
  "request_id": "uuid",
  "request_type": "YIELD_DEPLOYMENT | REBALANCE | EMERGENCY_WITHDRAWAL",
  "amount": "float",
  "asset": "string",
  "destination": {
    "protocol": "string",
    "vault_type": "string",
    "risk_tier": "LOW | MEDIUM | HIGH"
  },
  "risk_assessment": {
    "protocol_risk_score": "float",
    "smart_contract_audit": "boolean",
    "tvl_usd": "float",
    "time_in_market_days": "int"
  },
  "time_lock_requested_sec": "int"
}
```

#### Response Schema (Contract 5)

```json
{
  "request_id": "uuid",
  "status": "APPROVED | REJECTED | PENDING_REVIEW",
  "approved_amount": "float",
  "constraints": {
    "max_allocation_pct": "float",
    "time_lock_sec": "int",
    "withdrawal_notice_sec": "int"
  },
  "rejection_reason": "string | null"
}
```

#### Invariants (Contract 5)

| Rule | Enforcement |
| ---- | ----------- |
| GOV approval required | No autonomous deployment |
| Risk tier limits | HIGH tier capped at 5% |
| Time-lock enforced | Minimum 24h for large amounts |
| Protocol whitelist | Only approved protocols |

---

## CONTRACT 6: OPS → ARCHIVE

### Decision Record Contract

**Endpoint:** `POST /archive/record`

**Purpose:** OPS records all decisions for audit trail.

#### Request Schema (Contract 6)

```json
{
  "record_id": "uuid",
  "event_type": "INTENT_PROPOSED | INTENT_APPROVED | INTENT_REJECTED | INTENT_EXECUTED | INTENT_EXPIRED | ANOMALY_DETECTED | REGIME_CHANGE",
  "timestamp": "unix_timestamp",
  "intent_id": "uuid | null",
  "regime": "string",
  "data": {
    "key": "value"
  },
  "outcome": {
    "pnl": "float | null",
    "slippage": "float | null",
    "success": "boolean"
  },
  "hash_chain": {
    "previous_hash": "string",
    "current_hash": "string"
  }
}
```

#### Response Schema (Contract 6)

```json
{
  "record_id": "uuid",
  "stored": true,
  "block_number": "int",
  "verification_hash": "string"
}
```

#### Invariants (Contract 6)

| Rule | Enforcement |
| ---- | ----------- |
| Immutable | No updates or deletes |
| Append-only | Sequential block numbers |
| Hash chain integrity | Previous hash must match |
| All events recorded | No silent failures |

---

## CONTRACT 7: GOV → ALL

### Emergency Control Contract

**Endpoint:** `POST /gov/emergency/freeze`

**Purpose:** GOV issues emergency freeze to any system.

#### Request Schema (Contract 7)

```json
{
  "freeze_id": "uuid",
  "scope": "ALL | OPS | FIN | TREASURY",
  "reason": "ANOMALY_DETECTED | SECURITY_BREACH | MARKET_HALT | MANUAL_OVERRIDE",
  "severity": "WARNING | CRITICAL | EMERGENCY",
  "duration_sec": "int",
  "actions": {
    "halt_new_intents": "boolean",
    "cancel_pending_executions": "boolean",
    "freeze_withdrawals": "boolean",
    "enable_emergency_unwind": "boolean"
  },
  "authorized_by": ["string"],
  "override_code": "string | null"
}
```

#### Response Schema (Contract 7)

```json
{
  "freeze_id": "uuid",
  "acknowledged_by": ["string"],
  "effective_ts": "unix_timestamp",
  "expiry_ts": "unix_timestamp",
  "systems_affected": ["string"]
}
```

#### Invariants (Contract 7)

| Rule | Enforcement |
| ---- | ----------- |
| Overrides everything | No system can ignore |
| Logged permanently | Immutable in ARCHIVE |
| Requires authorization | Multi-sig for EMERGENCY |
| Auto-expiry | Duration enforced |
| Cannot be silently cancelled | Requires explicit unfreeze |

---

## CONTRACT 8: GOV → GOV

### Unfreeze Contract

**Endpoint:** `POST /gov/emergency/unfreeze`

**Purpose:** GOV lifts an emergency freeze.

#### Request Schema (Contract 8)

```json
{
  "freeze_id": "uuid",
  "unfreeze_reason": "string",
  "authorized_by": ["string"],
  "verification": {
    "anomaly_resolved": "boolean",
    "security_audit_passed": "boolean",
    "manual_review_completed": "boolean"
  }
}
```

#### Response Schema (Contract 8)

```json
{
  "freeze_id": "uuid",
  "status": "UNFROZEN",
  "effective_ts": "unix_timestamp",
  "systems_restored": ["string"]
}
```

#### Invariants (Contract 8)

| Rule | Enforcement |
| ---- | ----------- |
| Requires higher quorum than freeze | 2x approval count |
| Verification mandatory | All checks must pass |
| Logged permanently | Immutable in ARCHIVE |

---

## CONTRACT 9: ANY → ARCHIVE

### Audit Query Contract

**Endpoint:** `GET /archive/query`

**Purpose:** Any system queries historical records.

#### Request Schema (Contract 9)

```json
{
  "query_type": "BY_INTENT | BY_TIME_RANGE | BY_EVENT_TYPE | BY_SYSTEM",
  "filters": {
    "intent_id": "uuid | null",
    "start_ts": "unix_timestamp | null",
    "end_ts": "unix_timestamp | null",
    "event_types": ["string"],
    "origin_system": "string | null"
  },
  "pagination": {
    "offset": "int",
    "limit": "int"
  }
}
```

#### Response Schema (Contract 9)

```json
{
  "records": [
    {
      "record_id": "uuid",
      "event_type": "string",
      "timestamp": "unix_timestamp",
      "data": {}
    }
  ],
  "total_count": "int",
  "has_more": "boolean"
}
```

#### Invariants (Contract 9)

| Rule | Enforcement |
| ---- | ----------- |
| Read-only | No modifications via query |
| Rate limited | 100 queries/minute |
| Audit logged | All queries recorded |

---

## AUTHORITY ENFORCEMENT SUMMARY

| Contract | Caller | Callee | Authority Check |
| -------- | ------ | ------ | --------------- |
| Intent Proposal | OPS | GOV | OPS cannot execute |
| Execution Auth | GOV | FIN | GOV approval required |
| Execution Report | FIN | GOV | FIN must report all |
| Profit Routing | FIN | TREASURY | Profits only |
| Capital Request | TREASURY | GOV | GOV approval required |
| Decision Record | OPS | ARCHIVE | Append-only |
| Emergency Freeze | GOV | ALL | Overrides everything |
| Unfreeze | GOV | GOV | Higher quorum |
| Audit Query | ANY | ARCHIVE | Read-only |

---

## ERROR HANDLING REQUIREMENTS

### All Contracts Must

1. **Return structured errors** — JSON with `error_code`, `message`, `details`
2. **Log all failures** — To ARCHIVE with full context
3. **Timeout gracefully** — Default 30s, configurable
4. **Retry with backoff** — Exponential, max 3 attempts
5. **Alert on repeated failures** — 3+ failures trigger GOV alert

### Error Response Schema

```json
{
  "success": false,
  "error": {
    "code": "string",
    "message": "string",
    "details": {},
    "timestamp": "unix_timestamp",
    "request_id": "uuid"
  }
}
```

---

## VERSIONING

| Field | Value |
| ----- | ----- |
| API Version | `v1` |
| Schema Version | `1.0.0` |
| Breaking Change Policy | Major version bump required |
| Deprecation Notice | 90 days minimum |

---

## DOCUMENT CONTROL

| Field | Value |
| ----- | ----- |
| Document ID | `MERID-API-CONTRACTS-001` |
| Classification | INTERNAL |
| Review Cycle | Quarterly |
| Owner | MERID-GOV |
| Hash | `SHA256:TO_BE_COMPUTED_ON_FREEZE` |

---

## End of Document
