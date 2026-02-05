# MERID Risk & Safety Policy

**Version**: 1.1  
**Last Updated**: 2026-02-01  
**Owner**: Risk & Safety Team

---

## 1. Overview

This document defines the risk management and safety policies for MERID trading operations, including:

- **Trading Guards**: Pre-trade risk validation and circuit breaker logic
- **Safety Systems**: Automatic lockdowns, kill switches, and failure recovery
- **Venue Protections**: Exchange-specific failure handling
- **Operational Procedures**: Incident response and manual overrides

---

## 2. Risk Guardrails

### 2.1 Daily Loss Limits

**Policy**: Trading is blocked when daily losses exceed configured thresholds.

**Configuration** (in `TradingGuardConfig`):
- `max_daily_loss_usd`: Maximum allowable daily loss (default: $10,000)

**Behavior**:
- Real-time P&L tracking via `PortfolioAggregator.get_daily_pnl()`
- Block triggers when `abs(daily_pnl) > max_daily_loss_usd`
- Resets at market open (configurable)

**API Response**:
```json
{
  "risk_limits": {
    "max_daily_loss_usd": 10000.0,
    "current_daily_pnl": -8500.0,
    "daily_loss_utilization_pct": 85.0
  }
}
```

### 2.2 Per-Symbol Exposure Caps

**Policy**: Maximum notional exposure per symbol to prevent concentration risk.

**Configuration**:
- `max_per_symbol_exposure_usd`: Per-symbol limit (default: $50,000)

**Behavior**:
- Calculates total exposure (long + short) per symbol
- Blocks trades that would exceed the cap
- Tracks across all venues for the same underlying

### 2.3 Maximum Open Orders

**Policy**: Limit concurrent orders to prevent queue overflow and operational issues.

**Configuration**:
- `max_open_orders`: Maximum outstanding orders (default: 100)

**Behavior**:
- Counts orders in `PENDING`, `SUBMITTED`, `PARTIAL_FILL` states
- Blocks new orders when limit reached
- Encourages position completion before new submissions

---

## 3. Circuit Breaker

### 3.1 States

The circuit breaker has three states:

| State | Color | Trading Status | Description |
|-------|-------|----------------|-------------|
| **CLOSED** | 🟢 Green | Allowed | Normal operation - all trades permitted |
| **OPEN** | 🔴 Red | Blocked | Too many errors - all trades blocked |
| **HALF_OPEN** | 🟡 Yellow | Limited | Testing recovery - limited trades allowed |

### 3.2 Configuration

```python
TradingGuardConfig(
    circuit_breaker_threshold=5,           # Errors to trip
    circuit_breaker_window_seconds=60.0,   # Error tracking window
    circuit_breaker_cooldown_seconds=300.0, # Time before half-open
    circuit_breaker_half_open_max=3,       # Successes needed to close
)
```

### 3.3 State Transitions

```
CLOSED ──[errors ≥ threshold]──> OPEN ──[cooldown expires]──> HALF_OPEN
  ↑                                                           │
  └────────[half_open_successes ≥ max]────────────────────────┘
```

**CLOSED → OPEN**: Triggered when `error_count ≥ threshold` within `window_seconds`

**OPEN → HALF_OPEN**: Automatic after `cooldown_seconds`

**HALF_OPEN → CLOSED**: After `half_open_max` consecutive successful requests

**HALF_OPEN → OPEN**: Any error during half-open returns to OPEN

### 3.4 API Endpoints

**Get Status**:
```bash
GET /api/risk/protections
```

**Manual Reset** (requires admin):
```bash
POST /api/risk/circuit-breaker/reset
```

Response:
```json
{
  "circuit_breaker": {
    "state": "CLOSED",
    "state_color": "green",
    "error_count": 0,
    "threshold": 5,
    "opened_at": null,
    "last_error_at": "2026-02-01T12:34:56Z"
  }
}
```

---

## 4. Kill Switch / Lockdown

### 4.1 Emergency Stop

**Policy**: Immediate halt of all trading activity via manual override.

**Activation**:
- Dashboard: Click "EMERGENCY LOCKDOWN" button
- API: `POST /api/risk/kill-switch/enable`
- Programmatic: Set `TradingGuardConfig.enable_trading_suite = False`

**Behavior**:
- All new trades are blocked with status `BLOCK`
- Reason logged: "Trading suite disabled via kill switch"
- Existing positions unaffected
- Can only be disabled manually

### 4.2 Automatic Lockdown

**Policy**: System may auto-lockdown under severe conditions.

**Triggers**:
- Circuit breaker remains OPEN for extended period (>15 minutes)
- Multiple venue failures simultaneously
- Critical error rate exceeds safety margin

### 4.3 Kill Switch API

**Enable** (block trading):
```bash
POST /api/risk/kill-switch/enable
```

**Disable** (resume trading):
```bash
POST /api/risk/kill-switch/disable
```

Response:
```json
{
  "success": true,
  "message": "Kill switch ENABLED - trading blocked",
  "trading_enabled": false,
  "timestamp": "2026-02-01T12:34:56Z"
}
```

---

## 5. Venue Failure Handling

### 5.1 Failure Types

| Type | Example | Circuit Impact | Action |
|------|---------|----------------|--------|
| Timeout | No response in 30s | Record error | Retry with backoff |
| Connection | TCP reset | Record error | Mark venue degraded |
| HTTP Error | 5xx response | Record error | Check venue status |
| Malformed | Invalid JSON | Record error | Log for investigation |

### 5.2 Retry Policy

```python
max_retries = 3
base_delay = 1.0  # seconds
max_delay = 30.0  # seconds

# Exponential backoff: 1s, 2s, 4s
```

### 5.3 Venue State Tracking

Each venue executor tracks:
- `consecutive_failures`: Count since last success
- `last_failure_at`: ISO timestamp
- `degraded`: Boolean flag for reduced capacity

---

## 6. Operational Procedures

### 6.1 Circuit Breaker Tripped

**Symptoms**:
- Dashboard shows "Circuit Open - Orders Blocked"
- Trades return `BLOCK` with reason "Circuit breaker open"
- Error count at or above threshold

**Response**:
1. **Immediate**: Check venue health in logs
2. **Investigate**: Identify root cause (venue outage, network issue, bug)
3. **Wait**: Allow automatic recovery (half-open after cooldown)
4. **Manual Reset** (if confident): Use dashboard or API reset

**Verification**:
```bash
curl /api/risk/protections | jq '.circuit_breaker.state'
# Should return "CLOSED" after recovery
```

### 6.2 Emergency Lockdown

**When to Use**:
- Suspected account compromise
- Runaway trading algorithm
- Market panic / flash crash
- Regulatory intervention required

**Procedure**:
1. Click "EMERGENCY LOCKDOWN" on dashboard
2. Verify lockdown: check `/api/risk/protections` shows `trading_suite_enabled: false`
3. Investigate issue
4. When resolved, click "Disable Kill Switch" or use API

**Post-Incident**:
- Document in incident log
- Review trigger conditions
- Adjust thresholds if needed

### 6.3 Recovery Procedures

**From Circuit Open**:
1. Wait `cooldown_seconds` (default: 5 min) for half-open
2. System automatically tests with limited traffic
3. On success, returns to CLOSED
4. On failure, returns to OPEN with reset timer

**From Lockdown**:
1. Manual intervention required
2. Admin must explicitly disable kill switch
3. Confirmation dialog required
4. Trading resumes immediately

---

## 7. Monitoring & Alerting

### 7.1 Key Metrics

| Metric | Threshold | Severity | Action |
|--------|-----------|----------|--------|
| Circuit State | OPEN | Critical | Page on-call |
| Kill Switch | Enabled | Critical | Page on-call |
| Daily Loss Utilization | >90% | Warning | Alert team |
| Error Rate | >10/min | Warning | Investigate |
| Venue Failures | >3 consecutive | Warning | Degrade venue |

### 7.2 Dashboard Widgets

**Live Risk Strip**:
- Circuit breaker status card (6th position)
- Color-coded: Green/Red/Yellow
- Click for detailed view

**Risk Protections Panel**:
- Full circuit breaker details
- Kill switch controls
- Risk limit utilization bars
- Recent events log

### 7.3 Polling Intervals

- `/api/risk/protections`: 5 seconds (dashboard)
- Circuit state: Real-time via WebSocket
- Risk metrics: 30 seconds
- System health: 10 seconds

---

## 8. Configuration Reference

### 8.1 TradingGuardConfig

```python
@dataclass
class TradingGuardConfig:
    # Risk Limits
    max_daily_loss_usd: float = 10000.0
    max_per_symbol_exposure_usd: float = 50000.0
    max_open_orders: int = 100
    
    # Circuit Breaker
    circuit_breaker_threshold: int = 5
    circuit_breaker_window_seconds: float = 60.0
    circuit_breaker_cooldown_seconds: float = 300.0
    circuit_breaker_half_open_max: int = 3
    
    # Kill Switch
    enable_trading_suite: bool = True
    
    # Trading Mode
    allow_live_trades: bool = False
    vpn_only: bool = True
    max_notional_usd: float = 25000.0
```

### 8.2 Environment Variables

```bash
# Risk thresholds
MERID_MAX_DAILY_LOSS_USD=10000.0
MERID_MAX_SYMBOL_EXPOSURE_USD=50000.0
MERID_CIRCUIT_BREAKER_THRESHOLD=5

# Safety timeouts
MERID_CIRCUIT_BREAKER_WINDOW_SECONDS=60
MERID_CIRCUIT_BREAKER_COOLDOWN_SECONDS=300

# Feature flags
MERID_ENABLE_TRADING_SUITE=true
MERID_ALLOW_LIVE_TRADES=false
```

---

## 9. Testing

### 9.1 Unit Tests

```bash
# Risk limit tests
pytest tests/risk/test_risk_limits.py -v

# Circuit breaker tests
pytest tests/safety/test_circuit_breaker.py -v

# Venue failure tests
pytest tests/integration/test_venue_failure_modes.py -v
```

### 9.2 E2E Chaos Tests

```bash
# Stress test circuit breaker
pytest tests/e2e/test_circuit_breaker_chaos.py -v
```

### 9.3 Coverage Requirements

| Module | Minimum Coverage |
|--------|------------------|
| `trading/guards/trading_guard.py` | 85% |
| `merid/execution/portfolio.py` | 80% |
| `merid/execution/executors/kalshi.py` | 75% |
| `merid/execution/executors/coinbase.py` | 75% |

---

## 10. Incident Response

### 10.1 Severity Levels

**SEV-0 (Critical)**:
- Trading locked down unexpectedly
- Circuit breaker stuck OPEN
- Data corruption in risk calculations
- **Response**: Immediate rollback, page all on-call

**SEV-1 (High)**:
- Elevated error rate from venue
- Risk limits not enforcing correctly
- **Response**: Within 30 minutes, senior engineer

**SEV-2 (Medium)**:
- Dashboard displaying stale data
- Minor threshold miscalculations
- **Response**: Within 4 hours, next business day OK

### 10.2 Contacts

| Role | Contact | Escalation |
|------|---------|------------|
| Primary | risk-oncall@merid.io | 15 min |
| Secondary | eng-leads@merid.io | 30 min |
| Executive | ceo@merid.io | 1 hour |

---

## 11. Change Management

### 11.1 Risk Policy Changes

All changes to this policy require:
1. Risk team review
2. Engineering approval
3. Compliance sign-off (if regulatory impact)
4. 48-hour notice (unless emergency)

### 11.2 Threshold Modifications

**Emergency Changes** (SEV-0/SEV-1):
- May be made immediately
- Must be documented within 1 hour
- Requires post-incident review

**Standard Changes**:
- Require RFC process
- Test in staging environment
- Gradual rollout with monitoring

---

## 12. Glossary

| Term | Definition |
|------|------------|
| **Circuit Breaker** | State machine that blocks trading after consecutive errors |
| **Kill Switch** | Manual override to immediately halt all trading |
| **Lockdown** | State when kill switch is enabled |
| **Guard Decision** | Result of risk evaluation (ALLOW, BLOCK, SIMULATE) |
| **Error Window** | Time period for counting circuit breaker errors |
| **Half-Open** | Testing state after cooldown before full recovery |
| **Exposure** | Total notional position in a symbol |
| **Daily Drawdown** | Peak-to-trough decline in daily P&L |

---

## 13. Related Documents

- [Risk Enforcement Gate](risk_enforcement_gate.md) - Production readiness criteria
- [Risk Shadow Mode Design](risk_shadow_mode_design.md) - Implementation details
- [Operational Runbooks](./runbooks/) - Step-by-step incident procedures
- [API Reference](./api/risk.py) - Endpoint specifications

---

**Document History**

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-15 | Initial policy draft |
| 1.1 | 2026-02-01 | Added circuit breaker details, UI documentation, operational procedures |
