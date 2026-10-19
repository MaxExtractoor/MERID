# MERID Trading Data Contracts

## Overview

This document defines the **canonical data sources**, **invariants**, and **flags** that govern the MERID trading system. It serves as the contract between upstream data producers (agents, risk, router) and downstream consumers (UI, analytics, alerts).

Any deviation from these contracts without explicit flagging (`synthetic`, `manual_or_external`, `chain_complete=false`) is considered a bug and should trigger CI failure.

---

## Canonical Sources

### Single Source of Truth Hierarchy

| Data Type | Canonical Source | Endpoint | Fallback | Never Use |
|-----------|------------------|----------|----------|-----------|
| **Orders** | `order_router.py` → fills ledger | `GET /api/v1/kalshi/orders` | REST client | Direct `client.place_order()` |
| **Positions** | fills ledger → derived | `GET /api/v1/kalshi/positions` | executor.get_positions() | Agent grid synthetic positions |
| **Balance** | Venue API (Kalshi) | `GET /api/v1/kalshi/balance` | cached | Estimated/historical |
| **PnL** | fills ledger realized | `GET /api/v1/kalshi/risk` | risk_controller | Unrealized estimates |
| **Kill Switch** | risk_controller | `GET /api/v1/kalshi/risk` | — | Any other source |
| **Reconciliation** | fills ledger vs venue | `GET /api/v1/kalshi/health/reconciliation` | — | Status quo assumptions |

### The Golden Path

```
signal → agent → consensus → risk_controller → order_router → Kalshi API
                                    ↓              ↓
                              kill_switch    fills_ledger
                                                    ↓
                                            /positions (derived)
                                            /orders (canonical)
                                            /fills (ground truth)
```

Any order that deviates from this path MUST be flagged as `manual_or_external=true`.

---

## Data Quality Flags

### Explicit Flags (No Implicit Defaults)

Every order and position returned by the API MUST explicitly set these fields:

| Flag | Type | Meaning | UI Indicator |
|------|------|---------|---------------|
| `synthetic` | `boolean` | Not from actual venue. Created by simulation, backtest, or agent prediction. | Purple "SIMULATED" badge |
| `manual_or_external` | `boolean` | Bypassed normal pipeline. Manual entry, migration tool, or external source. | Orange "EXTERNAL" badge |
| `chain_complete` | `boolean` | Full lineage trace available (signal→agent→risk→router). | Green "TRACED" badge |
| `source` | `string` | Origin: `executor`, `rest_client`, `synthetic_agent_signal`, etc. | Tooltip detail |

### Flag Combinations

| synthetic | manual_or_external | chain_complete | Interpretation |
|-----------|-------------------|----------------|----------------|
| `false` | `false` | `true` | **GOLD PATH**: Live order through canonical pipeline |
| `false` | `true` | `false` | External/manual order at venue (e.g., Kalshi web UI) |
| `true` | `false` | `false` | Simulated/backtest order |
| `true` | `true` | `false` | Synthetic external (e.g., imported historical paper trade) |
| `false` | `false` | `false` | **WARNING**: Live order with incomplete trace (investigate) |

---

## Lineage Contract

### `/orders/{id}/lineage` Response Schema

```typescript
{
  "order_id": string;           // Canonical order ID
  "found": boolean;             // Whether order exists in any source
  
  // Explicit flags (no defaults)
  "chain_complete": boolean;    // All 4 links present
  "chain_coverage": string;       // e.g., "3/4"
  "manual_or_external": boolean;
  "synthetic": boolean;
  
  "venue_source": string;         // executor, rest_client, unknown
  
  "chain": {
    "signal": {                   // Signal that initiated order
      "signal_id": string;
      "timestamp": string;
      "action": "buy" | "sell";
      "ticker": string;
      "fresh": boolean;          // staleness < 60s
    },
    "agent": {                    // Agent that submitted signal
      "agent_id": string;
      "agent_type": string;
      "timestamp": string;
    },
    "consensus": {                // TaCo/Consensus approval
      "consensus_id": string;
      "approved": boolean;
      "confidence": number;
    },
    "risk": {                     // Risk controller decision
      "risk_decision_id": string;
      "allowed": boolean;
      "checks_performed": string[];
    },
    "router": {                   // Order routing execution
      "route_call_id": string;
      "mode": "live" | "paper" | "shadow";
      "latency_ms": number;
    }
  },
  
  "warnings": string[];         // Human-readable investigation prompts
  "timestamp": string;          // ISO8601 UTC
}
```

### Lineage Invariants

1. **If `found=true` and `venue_source` is `executor` or `rest_client`, then `chain_complete` must be `true` OR `manual_or_external` must be `true`.**

2. **If `chain_complete=false` and `manual_or_external=false`, a warning must be present explaining the gap.**

3. **Every link in `chain` must include a `timestamp` for temporal ordering.**

---

## Reconciliation Contract

### `/reconciliation/breaks` Response Schema

```typescript
{
  "timestamp": string;
  "threshold_usd": number;        // Configurable sensitivity
  "status": "ok" | "degraded" | "broken";
  
  "summary": {
    "unmatched_fills": number;     // Fills without position impact
    "unmatched_positions": number; // Positions without fill backing
    "balance_drift": number;      // USD difference
    "pnl_divergence": number      // Risk vs fills ledger
  },
  
  "breaks": [
    {
      "type": "unmatched_fill" | "unmatched_position_impact" | "balance_drift" | "pnl_divergence",
      "severity": "high" | "medium" | "low",
      "message": string,          // Human-readable
      // Type-specific fields...
    }
  ],
  
  "break_count": number;
  "high_severity_count": number;
}
```

### Reconciliation Status Meanings

| Status | Condition | Operator Action |
|--------|-----------|-----------------|
| `ok` | No breaks, or all below threshold | None |
| `degraded` | Minor breaks (balance drift < $10, single unmatched fill) | Monitor, investigate within 1 hour |
| `broken` | Major breaks (PnL divergence > $5, multiple unmatched fills > $100) | **STOP TRADING**, manual reconciliation required |

---

## UI/UX Contracts

### DataSourceBadge Component

```tsx
// SIMULATED (purple) — synthetic data
<DataSourceBadge synthetic={true} source="agent_grid" />

// EXTERNAL (orange) — manual or bypassed pipeline
<DataSourceBadge manualOrExternal={true} source="manual_entry" />

// TRACED (green) — full lineage
<OrderLineageBadge chainComplete={true} chainCoverage="4/4" />

// PARTIAL (yellow) — incomplete trace
<OrderLineageBadge chainComplete={false} warningCount={2} />
```

### GlobalModeBanner

Must display at top of every view when:
- Profile is not `prod`
- Synthetic data is present
- External orders are present
- Kill switch is active
- Reconciliation is `degraded` or `broken`

| Mode | Color | Text |
|------|-------|------|
| LIVE | Green gradient | "LIVE MODE — Real orders, real capital" |
| PAPER | Blue | "PAPER MODE — Simulated orders, no real capital" |
| SIM | Purple | "SIMULATION MODE — Full simulation" |
| HALTED | Red + pulse | "HALTED — Trading disabled by kill switch" |
| MIXED | Orange | "MIXED — Synthetic/external data present" |

---

## Invariant Testing

### Cross-View Invariants (Enforced in CI)

| Invariant | Test | Failure Action |
|-----------|------|----------------|
| `positions_have_fills` | Every non-synthetic position has ≥1 backing fill | CI hard block |
| `fills_have_position_impact` | Every fill has corresponding position change | CI hard block |
| `balance_consistency` | Balance drift < $5 | CI warning |
| `pnl_consistency` | Risk PnL ≈ Portfolio PnL | CI hard block |
| `order_lineage_complete` | Live orders have full trace or external flag | CI hard block |
| `reconciliation_exposed` | All endpoints expose reconciliation_status | CI hard block |
| `synthetic_gating` | No synthetic in default (ungated) responses | CI hard block |
| `kill_switch_consistency` | /risk and /operator agree | CI hard block |

### Running Invariants

```bash
# Unit tests
pytest tests/test_cross_view_invariants.py -v

# Red team CI (60-second smoke test)
python scripts/ci_red_team.py --duration 60

# Reconciliation stress
python scripts/stress_test_reconciliation.py --scenario all

# Venue touchpoint guardrail
bash scripts/ci_guardrail_venue_touchpoints.sh
```

---

## State Transition Logging

Critical transitions are logged with full context for incident reconstruction:

| Transition Type | Logged Fields | Alert Threshold |
|-----------------|---------------|-----------------|
| `reconciliation` | `previous_status`, `new_status`, `break_count`, `affected_orders` | `ok → broken` = CRITICAL |
| `kill_switch` | `triggered_by`, `reason`, `affected_positions` | Any change = CRITICAL |
| `trading_mode` | `previous_mode`, `new_mode`, `initiated_by` | `→ halted` = CRITICAL, `→ live` = WARNING |

### Querying Transitions

```python
from merid.observability.state_transitions import get_state_transition_logger

stl = get_state_transition_logger()

# Recent kill switch changes
recent_ks = stl.get_recent_transitions(
    transition_type=TransitionType.KILL_SWITCH,
    since_minutes=60
)

# Export incident timeline
incident = stl.export_incident_timeline(
    start_time="2026-03-24T00:00:00Z",
    end_time="2026-03-24T01:00:00Z"
)
```

---

## Whitelist for Exceptions

Files permitted to bypass canonical pipeline (via `.ci/venue_touchpoint_whitelist.txt`):

- `scripts/migrate_positions_legacy.py` — One-time migrations
- `scripts/manual_order_correction.py` — Emergency corrections
- `scripts/emergency_kill_and_flatten.py` — Emergency procedures

**Requirements for whitelisted files:**
1. Must set `manual_or_external=true` on all created orders
2. Must be marked with `--manual` flag or similar
3. Must be reviewed by two maintainers
4. Must have corresponding test in `TestOrderLineageInvariants`

---

## Version

- **Contract Version**: 1.0.0
- **Last Updated**: 2026-03-24
- **Maintainer**: MERID Trading Systems Team

## References

- [FIA Automated Trading Risk Controls](https://www.fia.org/sites/default/files/2024-07/FIA_WP_AUTOMATED%20TRADING%20RISK%20CONTROLS_FINAL_0.pdf)
- [Data Lineage Best Practices](https://www.ovaledge.com/blog/data-lineage-best-practices)
- [DeFi Exploit Detection via Invariants](https://dev.to/ohmygod/building-a-defi-exploit-detection-lab-foundry-invariant-tests-that-would-have-caught-100m-in-hacks-4jm5)
