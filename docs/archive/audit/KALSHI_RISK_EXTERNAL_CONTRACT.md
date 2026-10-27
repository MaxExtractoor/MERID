# Kalshi Risk Infrastructure External Contract

**SPEC_VERSION:** 1.0.0  
**Date:** 2026-05-16  
**Purpose:** Codify risk behavior for Kalshi 1-dollar binary crypto markets, including exposure caps, PnL computation, and kill-switch interaction with reconciliation and gate.

## Context

Kalshi prediction markets use 1-dollar binary contracts. For 15-minute crypto markets (BTC/ETH/SOL/XRP/DOGE), the risk model must enforce position limits, compute accurate PnL based on Kalshi's payoff + fee schedule, and integrate with the reconciliation → gate control loop.

## Risk Contract Specifications

### 1. Position Exposure Caps

#### Per-Asset Maximum Exposure
- **BTC:** Max 500 contracts per side (YES/NO) per 15-minute market
- **ETH:** Max 500 contracts per side per 15-minute market
- **SOL:** Max 500 contracts per side per 15-minute market
- **XRP:** Max 500 contracts per side per 15-minute market
- **DOGE:** Max 500 contracts per side per 15-minute market

**Rationale:** $500 max exposure per market per side = $1000 total per market. With 5 assets and multiple expiries, this limits total exposure while allowing meaningful position sizing.

#### Per-Time-Bucket Limits
- **15-minute markets:** Max 250 contracts per side across all expiries in same 15-minute window
- **Hourly markets:** Max 500 contracts per side across all expiries in same hour
- **Daily markets:** Max 1000 contracts per side across all expiries in same day

**Rationale:** Prevents concentration in correlated markets within same time horizon.

#### Total Account Exposure
- **Max total notional:** $10,000 across all Kalshi crypto markets
- **Max single-asset exposure:** $2,000 per asset (BTC/ETH/SOL/XRP/DOGE)

**Rationale:** Limits overall portfolio risk to 1% of typical trading bankroll.

### 2. PnL Computation

#### Kalshi Payoff Structure
- **Binary contract:** Pays $1.00 if correct, $0.00 if incorrect
- **YES position:** Profit = (settlement_price - entry_price) × contracts
- **NO position:** Profit = ((1 - settlement_price) - entry_price) × contracts

**Settlement prices:**
- Binary markets settle at 0 or 1 based on outcome
- Early exit: sell at current market price (midpoint of bid/ask)

#### Fee Schedule
Based on Kalshi's fee schedule (https://kalshi.com/docs/kalshi-fee-schedule.pdf):

- **Taker fee:** 1¢ per contract ($0.01)
- **Maker fee:** 0.5¢ per contract ($0.005)
- **Maximum fee:** 7¢ per contract ($0.07) cap

**Fee computation:**
```
fee = min(taker_fee * contracts, 0.07 * contracts)
or
fee = min(maker_fee * contracts, 0.07 * contracts)
```

#### PnL Formula
```
realized_pnl = (exit_price - entry_price) * contracts - fees
unrealized_pnl = (current_price - entry_price) * contracts - fees
```

Where prices are in dollars (0.00 to 1.00 range for binary contracts).

### 3. Risk Enforcement

#### Pre-Order Risk Checks
Before any order reaches the Kalshi adapter, the risk engine must enforce:

1. **Position cap check:** New position must not exceed per-asset or per-market caps
2. **Total exposure check:** New position must not exceed total account exposure limit
3. **Time-bucket check:** New position must not exceed per-time-bucket limits
4. **Correlation check:** (Optional) For highly correlated assets (e.g., BTC/ETH), enforce combined exposure limits

#### Risk Breach Response
- **Warning threshold:** 80% of cap → Log warning, allow order
- **Critical threshold:** 90% of cap → Log critical, allow order but flag for review
- **Hard limit:** 100% of cap → Block order, trigger gate LIMITED state

### 4. Kill-Switch Integration

#### Kill-Switch Triggers
The kill-switch must be activated when ANY of the following occur:

1. **Reconciliation critical discrepancy:** Phantom position or side inversion detected
2. **Risk breach:** Hard limit exceeded (order blocked)
3. **Gate state:** Gate transitions to BLOCKED state
4. **Manual activation:** Operator-initiated kill-switch

#### Kill-Switch Behavior
When kill-switch is activated:
1. **Immediate:** Cancel all pending orders for affected venue
2. **Position reduction:** Auto-flatten positions (reduce-only mode) for affected markets
3. **Gate state:** Force gate to BLOCKED state
4. **Alerting:** Send PagerDuty/Slack alert with breach details

#### Kill-Switch Recovery
To recover from kill-switch:
1. **Root cause analysis:** Identify and resolve the trigger (recon discrepancy, risk breach, etc.)
2. **Manual review:** Operator confirms safe to resume trading
3. **Gate reset:** Manually reset gate state to CLEAR
4. **Resume trading:** New orders allowed after gate reset

### 5. Integration with Reconciliation → Gate

#### Reconciliation Feedback to Risk
- **Phantom position:** Immediate kill-switch, auto-flatten affected market
- **Quantity mismatch:** If > 10 contracts difference, trigger risk review
- **Side inversion:** Immediate kill-switch, auto-flatten entire asset

#### Risk Feedback to Gate
- **Risk breach (hard limit):** Gate transitions to LIMITED (reduce-only) or BLOCKED
- **Risk breach (warning):** Gate remains CLEAR but logs warning
- **Risk breach (critical):** Gate transitions to LIMITED, flag for review

#### Gate Decision Logic
```
if (reconciliation_critical_discrepancy OR risk_hard_limit_breach):
    gate_state = BLOCKED
    kill_switch = ACTIVATE
elif (reconciliation_warning_discrepancy OR risk_critical_threshold):
    gate_state = LIMITED
    # Reduce-only mode
elif (reconciliation_clean AND risk_within_limits):
    gate_state = CLEAR
    # Normal trading
```

## Test Requirements

### Risk Test Suite (tests/risk/test_kalshi_crypto_risk.py)

#### Test Cases

1. **Position cap enforcement**
   - Test that orders exceeding per-asset caps are blocked
   - Test that orders exceeding per-market caps are blocked
   - Test that orders exceeding total exposure are blocked

2. **PnL computation accuracy**
   - Replay fills into risk engine
   - Assert computed PnL matches Kalshi payoff + fee schedule
   - Test edge cases: max fee cap, maker vs taker fees

3. **Risk cap breach response**
   - Simulate risk breach at warning threshold (80%)
   - Simulate risk breach at critical threshold (90%)
   - Simulate risk breach at hard limit (100%)
   - Assert gate state transitions and kill-switch behavior

4. **Kill-switch integration**
   - Test kill-switch activation on reconciliation critical discrepancy
   - Test kill-switch activation on risk hard limit breach
   - Test kill-switch activation on manual trigger
   - Test kill-switch recovery flow

5. **Time-bucket limits**
   - Test per-time-bucket limits across multiple expiries
   - Test correlation limits for BTC/ETH

## Implementation Notes

### Metrics to Emit
- `merid_risk_exposure_total{venue="kalshi", asset="BTC"}` - Total exposure per asset
- `merid_risk_position_count{venue="kalshi", asset="BTC", side="yes"}` - Position count per side
- `merid_risk_breach_count{venue="kalshi", severity="warning|critical|hard"}` - Risk breach count
- `merid_risk_cap_utilization{venue="kalshi", asset="BTC"}` - Cap utilization percentage

### API Endpoints
- `GET /api/v1/risk/limits` - Current risk limits and utilization
- `GET /api/v1/risk/exposure` - Current exposure by asset
- `POST /api/v1/risk/kill-switch` - Manual kill-switch activation
- `POST /api/v1/risk/reset` - Reset kill-switch and resume trading

## References

- Kalshi Fee Schedule: https://kalshi.com/docs/kalshi-fee-schedule.pdf
- Kalshi Market Integrity: https://kalshi.com/policy-center/market-integrity
- CFTC Rules: https://www.cftc.gov/filings/orgrules/rules1114248723.pdf
- Abstra Reconciliation Guide: https://www.abstra.io/en/articles/reconciliation-discrepancies
