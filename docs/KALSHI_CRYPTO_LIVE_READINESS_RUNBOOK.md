# Kalshi Crypto Live-Trading Readiness Runbook

## Overview

This runbook provides a comprehensive pre-flight checklist for enabling live Kalshi crypto trading. It covers environment configuration, risk management, agent behavior validation, and market coverage verification.

**CRITICAL**: Do NOT enable live trading (`MERID_PM_TRADING_MODE=live`) until ALL sections pass validation.

---

## Quick Start

Run the automated readiness checker:

```bash
python scripts/kalshi_crypto_live_readiness.py
```

For verbose output with detailed diagnostics:

```bash
python scripts/kalshi_crypto_live_readiness.py --verbose
```

For machine-readable JSON output:

```bash
python scripts/kalshi_crypto_live_readiness.py --json
```

**Exit codes**:
- `0` = `LIVE_READY=YES` — All checks passed, safe to go live
- `1` = `LIVE_READY=NO` — Blocking failures detected, DO NOT go live

---

## Section 1: Environment and Mode Sanity Checklist

### Required Environment Variables

#### Kalshi API Configuration

| Variable | Purpose | Allowed Values | Required in Live? | Notes |
|----------|---------|----------------|-------------------|-------|
| `KALSHI_API_KEY_ID` | Kalshi API key identifier | Non-empty string, not 'demo' or 'change_me' | **YES** | Obtain from https://kalshi.com/profile/api |
| `KALSHI_PRIVATE_KEY_PATH` | Path to RSA private key file | Valid file path | **YES** (or use `KALSHI_PRIVATE_KEY_PEM`) | Must be valid PEM-formatted RSA private key |
| `KALSHI_PRIVATE_KEY_PEM` | Inline RSA private key (PEM string) | Multi-line PEM string | **YES** (or use `KALSHI_PRIVATE_KEY_PATH`) | Alternative to key file |
| `KALSHI_API_HOST` | Kalshi API base URL | `https://api.elections.kalshi.com/trade-api/v2` or `https://trading-api.kalshi.com` | **YES** | Production URL for live trading |
| `KALSHI_ENV` | Kalshi environment mode | `{paper, demo, live}` | **YES** | Must be `live` for production |
| `KALSHI_USE_DEMO` | Use demo/test API | `{true, false}` | **YES** | Must be `false` for live trading |

#### CF Benchmarks RTI (Settlement Feed)

| Variable | Purpose | Allowed Values | Required in Live? | Notes |
|----------|---------|----------------|-------------------|-------|
| `MERID_CFB_RTI_ENABLED` | Enable CF Benchmarks RTI feed | `{true, false}` | **YES** | Must be `true` for live; Kalshi requires CFTC-regulated settlement data |
| `MERID_CFB_RTI_POLL_URL` | CF Benchmarks RTI API endpoint | `https://api.cfbenchmarks.com/v1/...` | **YES** (when CFB enabled in live) | Requires paid CF Benchmarks subscription |
| `CFB_API_KEY` | CF Benchmarks API key | Non-empty string | **YES** (when CFB enabled in live) | X-Api-Key header for RTI endpoint |
| `MERID_CFB_RTI_ADAPTER` | RTI data adapter | `{live, simulation}` | **YES** | Must be `live` for production; `simulation` for paper/dev |
| `MERID_ALLOW_NULL_CFB` | Bypass CFB health gate | `{0, 1}` | NO | **Non-prod only!** Never use in live mode |

#### Trading Mode Controls

| Variable | Purpose | Allowed Values | Required in Live? | Notes |
|----------|---------|----------------|-------------------|-------|
| `MERID_PM_TRADING_MODE` | Prediction market trading mode | `{paper, live}` | **YES** | Must be `live` to enable real orders |
| `MERID_PM_LIVE_ENABLED` | Unlock PM live trading | `{true, false}` | **YES** | Safety interlock; must be explicitly enabled |
| `MERID_LIVE_TRADING_UNLOCKED` | Master live trading unlock | `{true, false}` | **YES** | Global safety interlock across all venues |
| `MERID_REQUIRE_CONFIRMATION` | Require order confirmation | `{true, false}` | Recommended | Adds manual approval step (optional) |

### Validation Steps

1. **Check all required variables are set**:
   ```bash
   env | grep -E "(KALSHI|MERID|CFB)" | sort
   ```

2. **Verify Kalshi credentials are NOT demo keys**:
   - `KALSHI_API_KEY_ID` should NOT contain "demo", "test", or "change_me"
   - Private key file must exist and be readable

3. **Verify mode consistency**:
   - When `KALSHI_ENV=live`:
     - `MERID_PM_TRADING_MODE` must be `live`
     - `MERID_PM_LIVE_ENABLED` must be `true`
     - `MERID_LIVE_TRADING_UNLOCKED` must be `true`
     - `MERID_CFB_RTI_ENABLED` must be `true`
     - `KALSHI_USE_DEMO` must be `false`

4. **Run automated validation**:
   ```bash
   python scripts/go_live_preflight.py
   ```

### Common Issues and Fixes

| Issue | Fix |
|-------|-----|
| "KALSHI_API_KEY_ID not set" | Set in `.env`: `KALSHI_API_KEY_ID=your_key_id` |
| "Private key file not found" | Verify path or use `KALSHI_PRIVATE_KEY_PEM` |
| "CFB RTI unhealthy" | Check `MERID_CFB_RTI_POLL_URL` and `CFB_API_KEY`; verify network access to CF Benchmarks |
| "Kill switch active" | Reset: `POST /api/v1/operator/reset-kill-switch` or restart |

---

## Section 2: Formula and Sizing Conflicts

### Canonical Formulas

All risk and sizing calculations derive from these canonical formulas:

#### Kelly Fraction (Fee-Aware)

```python
# Location: merid/event_venues/kalshi/kalshi_risk.py
kelly_fraction = 0.25 * (edge / (1 - price))
# Where:
#   edge = abs(fair_price - market_price)
#   price = Kalshi contract price (0-1)
#   0.25 = quarter-Kelly conservative sizing
```

#### Per-Asset Risk Caps

```python
# Location: merid/event_venues/kalshi/crypto_kalshi_risk.py
# Asset: BTC
bankroll_share = 0.25  # 25% of total crypto bankroll
max_risk_pct_trade = 0.010  # 1.0% max per trade
cushion_pct_trade = 0.0025  # 0.25% safety cushion

# Asset: ETH
bankroll_share = 0.25
max_risk_pct_trade = 0.010
cushion_pct_trade = 0.0025

# Asset: SOL
bankroll_share = 0.10  # 10% of total crypto bankroll
max_risk_pct_trade = 0.0075  # 0.75% max per trade
cushion_pct_trade = 0.0025

# Asset: XRP
bankroll_share = 0.10
max_risk_pct_trade = 0.0075
cushion_pct_trade = 0.0025

# Asset: DOGE
bankroll_share = 0.10
max_risk_pct_trade = 0.005  # 0.5% max per trade
cushion_pct_trade = 0.0025
```

#### Portfolio-Wide Cap

```python
# Location: crypto_kalshi_risk.py:CryptoKalshiRiskConfig
max_risk_pct_portfolio = 0.03  # 3% max total open risk
max_total_drawdown_pct = 0.40  # 40% max drawdown stop-out
```

#### Confidence Thresholds

```python
# Location: merid/trading/kalshi_continuous_trader.py
MERID_MIN_CONFIDENCE = 0.55  # Default minimum confidence to trade
MERID_MIN_EDGE = 0.02  # 2% minimum edge required
MERID_MAX_YES_PRICE = 0.50  # Max price for YES orders (default)
```

### Validation Checklist

- [ ] **No double-application of risk caps**: Verify each formula is applied **once** per order
- [ ] **Per-asset vs global caps**: Confirm global portfolio cap (3%) is enforced AFTER per-asset sizing
- [ ] **No conflicting cap systems**: All modules use the same `CryptoKalshiRiskConfig` instance
- [ ] **Bankroll shares sum correctly**: BTC (25%) + ETH (25%) + SOL (10%) + XRP (10%) + DOGE (10%) = 80% (20% cash buffer)

### YES/NO Side Handling

**Rule**: Size is computed ONCE at contract level, then applied to EITHER YES or NO side based on edge sign.

```python
# Correct pattern:
if edge > 0:
    side = "YES"
    contracts = compute_contracts_for_order(bankroll, price, asset)
else:
    side = "NO"
    contracts = compute_contracts_for_order(bankroll, price, asset)

# NEVER:
# - Open offsetting YES and NO positions simultaneously (unless explicit hedge)
# - Use different sizing for YES vs NO on the same market
```

**Verification**: Run the formula checker:

```bash
python scripts/kalshi_crypto_live_readiness.py | grep "Formula and Sizing"
```

---

## Section 3: Agent Proposals, Confidence, and Hardcoding

### Proposal Pipeline

All trading signals flow through this unified path:

```
Strategy/Agent → AgentProposal/Signal → ConsensusAggregator → ApprovedSignal → KalshiContinuousTrader → Order
```

**No agent should bypass this path** with direct REST API calls.

### Confidence Sources

| Agent | Confidence Source | Status |
|-------|-------------------|--------|
| `TradingAgent` | Derived from model output | ✓ OK |
| `OpinionStrategy` | Consensus from `OpinionEstimate` | ✓ OK |
| `KalshiContinuousTrader` | Unified signal path via `TradingCandidate` | ✓ OK |

### Hardcoded Confidence Detection

The readiness script scans for patterns like:

```python
# AVOID:
confidence = 0.6  # Hardcoded
min_confidence = 0.55  # Hardcoded

# PREFER:
confidence = model.predict(features)  # Derived
min_confidence = settings.MERID_MIN_CONFIDENCE  # Config
```

**Acceptable hardcoded values**:
- Default/fallback confidence (e.g., `default=0.5` in function signature)
- Config defaults (e.g., `MERID_MIN_CONFIDENCE = 0.55` in settings)

**Unacceptable hardcoded values**:
- Primary confidence assignment in trading logic
- Confidence values that override model outputs

### YES/NO Decision Logic

All agents must:
1. Explicitly specify `side` (`yes` or `no`) in every proposal
2. Provide rationale for side selection (edge sign, trend, regime)
3. Ensure confidence and side are not contradictory

**Validation Tags**:
- `OK` — Derived confidence and side, unified path ✓
- `HARD_CODED_CONFIDENCE` — Needs review ⚠
- `BYPASS_UNIFIED_PATH` — Must be refactored ✗
- `YES_NO_LOGIC_RISKY` — Ambiguous side selection ⚠

---

## Section 4: Market Coverage Matrix (Asset × Timeframe)

### Supported Universe

**Assets**: BTC, ETH, SOL, XRP, DOGE (5 total)
**Timeframes**: 15m, 1h, daily, weekly, monthly (5 total)
**Total Markets**: 5 × 5 = **25 asset/timeframe pairs**

### Coverage Requirements

For each (asset, timeframe) pair:

| Check | Description | Validation |
|-------|-------------|------------|
| **Discover** | Market appears in MERID catalog | `KalshiMarketCatalog` can find it |
| **Analyze/Consensus** | At least one strategy generates proposals | Strategy config has profile for it |
| **Size** | Risk engine accepts ticker and computes contracts | `KalshiCryptoRiskEngine.compute_contracts_for_order()` succeeds |
| **Execute** | Continuous trader can place order (dry-run) | Order flow completes without errors |
| **Monitor/Protect** | Metrics and kill switches track it | Not marked as "unknown" or untracked |

### Timeframe Mapping

| Canonical Timeframe | Legacy Name | Strategy Profile |
|---------------------|-------------|------------------|
| 15m | scalp | `scalp` |
| 1h | intraday | `intraday` |
| daily | swing | `swing` |
| weekly | (unmapped) | Future work |
| monthly | (unmapped) | Future work |

**Note**: Weekly and monthly timeframes are defined in `config/crypto_universe.py` but not yet mapped to strategy profiles in `crypto_kalshi_risk.py`. These will show as "not mapped" in the coverage matrix.

### Validation Output

```
Asset    Timeframe    Catalog    Strategy   Sizing     Execution    Monitor    Notes
------------------------------------------------------------------------
BTC      15m          ✓          ✓          ✓          ✓            ✓          -
BTC      1h           ✓          ✓          ✓          ✓            ✓          -
BTC      daily        ✓          ✓          ✓          ✓            ✓          -
BTC      weekly       ✓          ✗          ✗          ✗            ✓          Timeframe not mapped to strategy profile
...
```

---

## Section 5: Pre-Flight Dry-Run Script

### One-Shot Readiness Check

The `kalshi_crypto_live_readiness.py` script performs:

1. **Config/env validation**: All required vars present and valid
2. **Data/feeds sanity**: Kalshi API reachable, CFB RTI healthy
3. **Dry-run trade across matrix**: Sample BTC/ETH/SOL markets sized and validated
4. **UI state probe**: Dashboards show correct mode and healthy status

### Running the Script

```bash
# Standard run
python scripts/kalshi_crypto_live_readiness.py

# Verbose (shows all details)
python scripts/kalshi_crypto_live_readiness.py --verbose

# JSON output (for automation)
python scripts/kalshi_crypto_live_readiness.py --json
```

### Expected Output (PASS)

```
LIVE_READY=YES - All checks passed! Safe to enable live trading.
```

### Expected Output (FAIL)

```
LIVE_READY=NO - Blocking failures detected. DO NOT enable live trading.

Blocking Failures:
  1. Env var KALSHI_API_KEY_ID: Missing or empty
  2. Data feeds unhealthy - CFB RTI required in live mode
  3. No markets have full coverage (catalog + strategy + sizing + execution)
```

### What the Script Checks

| Check | Pass Condition | Failure Impact |
|-------|---------------|----------------|
| **Config validation** | All required env vars set and valid | **BLOCKING** — Cannot initialize trading system |
| **CFB RTI health** | At least one tick received in last 3 minutes | **BLOCKING** (live mode only) — Kalshi requires settlement feed |
| **Sample dry-runs** | BTC/ETH/SOL sizing succeeds | **WARNING** — Partial coverage OK, but verify manually |
| **UI state** | Mode indicators show correct state | **WARNING** — Risk of operator confusion |

---

## Pre-Launch Checklist

### Prerequisites

- [ ] **CF Benchmarks RTI subscription active**: Paid subscription required for live mode
- [ ] **Kalshi live API credentials configured**: Non-demo API key and RSA private key
- [ ] **All environment variables set**: See Section 1 table
- [ ] **Initial bankroll deposited**: Verify via `GET /portfolio/balance`
- [ ] **Kill switches operational**: Test `POST /api/v1/operator/trigger-kill-switch`

### Configuration Steps

1. **Set environment variables** (`.env` file):
   ```bash
   # Kalshi
   KALSHI_API_KEY_ID=your_live_key_id
   KALSHI_PRIVATE_KEY_PATH=/path/to/private_key.pem
   KALSHI_API_HOST=https://api.elections.kalshi.com/trade-api/v2
   KALSHI_ENV=live
   KALSHI_USE_DEMO=false

   # CF Benchmarks
   MERID_CFB_RTI_ENABLED=true
   MERID_CFB_RTI_POLL_URL=https://api.cfbenchmarks.com/v1/values
   CFB_API_KEY=your_cfb_api_key
   MERID_CFB_RTI_ADAPTER=live

   # Trading mode
   MERID_PM_TRADING_MODE=live
   MERID_PM_LIVE_ENABLED=true
   MERID_LIVE_TRADING_UNLOCKED=true
   ```

2. **Verify credentials**:
   ```bash
   python scripts/go_live_preflight.py
   ```

3. **Run full readiness check**:
   ```bash
   python scripts/kalshi_crypto_live_readiness.py --verbose
   ```

4. **Verify kill switches**:
   ```bash
   curl -X POST http://localhost:8000/api/v1/operator/trigger-kill-switch
   # Should block all new orders
   curl -X POST http://localhost:8000/api/v1/operator/reset-kill-switch
   # Should re-enable trading
   ```

5. **Test CFB RTI feed**:
   ```bash
   python -c "
   from merid.data.settlement_rti_buffer import SettlementRtiBuffer
   import os
   buf = SettlementRtiBuffer(
       adapter_type='live',
       poll_url=os.getenv('MERID_CFB_RTI_POLL_URL'),
       api_key=os.getenv('CFB_API_KEY'),
       poll_interval_s=60.0
   )
   tick = buf.poll_once()
   print(f'CFB RTI healthy: {tick is not None}')
   if tick:
       print(f'  {tick.index_name} = {tick.value:.2f}')
   "
   ```

6. **Place test order (paper mode)**:
   ```bash
   # Temporarily set to paper mode
   export MERID_PM_TRADING_MODE=paper
   # Place small test order
   # Verify order appears in logs and UI
   # Switch back to live mode
   export MERID_PM_TRADING_MODE=live
   ```

7. **Final pre-launch verification**:
   ```bash
   # All gates must pass
   python scripts/kalshi_crypto_live_readiness.py
   # Exit code 0 = LIVE_READY=YES
   echo $?
   ```

### Go-Live Decision

**Do NOT enable live trading unless**:
- ✅ `kalshi_crypto_live_readiness.py` exits with code `0` (LIVE_READY=YES)
- ✅ `go_live_preflight.py` shows all gates PASS
- ✅ CFB RTI feed healthy (tick received in last 3 minutes)
- ✅ Kill switches verified operational
- ✅ All team members briefed on emergency procedures

**If ANY check fails**:
1. Document the failure
2. Fix the underlying issue
3. Re-run all checks
4. Do NOT proceed to live mode

---

## Emergency Procedures

### Immediate Kill Switch

**Web API**:
```bash
curl -X POST http://localhost:8000/api/v1/operator/trigger-kill-switch \
  -H "Content-Type: application/json" \
  -d '{"reason": "Emergency stop"}'
```

**Environment variable**:
```bash
# Set in .env or shell
export MERID_EMERGENCY_KILL=true
# Restart application
```

### Graceful Shutdown

```bash
# Step 1: Stop accepting new orders
curl -X POST http://localhost:8000/api/v1/operator/pause-trading

# Step 2: Close all open positions (if needed)
curl -X POST http://localhost:8000/api/v1/operator/close-all-positions

# Step 3: Switch to paper mode
export MERID_PM_TRADING_MODE=paper
# Restart application
```

### Rollback to Paper Mode

```bash
# Update .env
MERID_PM_TRADING_MODE=paper
MERID_PM_LIVE_ENABLED=false

# Restart
systemctl restart merid  # or your process manager
```

---

## Monitoring and Alerts

### Key Metrics to Monitor

1. **CFB RTI staleness**: Alert if no tick in 3+ minutes
2. **Kill switch status**: Alert if triggered
3. **Order rejection rate**: Alert if > 10% of orders rejected
4. **Portfolio drawdown**: Alert at 20%, kill switch at 40%
5. **Per-asset exposure**: Alert if approaching caps

### Recommended Alert Thresholds

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| CFB RTI staleness | 3 min | 5 min | Pause trading, investigate feed |
| Daily loss | 10% | 20% | Review positions, reduce exposure |
| Total drawdown | 20% | 40% | Kill switch triggers at 40% |
| Order rejection rate | 5% | 10% | Check API connectivity, review logs |
| Open positions | 15 | 20 | Reduce new order flow |

---

## References

- **Kalshi API Documentation**: https://kalshi.com/docs
- **CF Benchmarks RTI**: https://docs.cfbenchmarks.com/api/websocket/value/
- **MERID Risk Management**: `/merid/event_venues/kalshi/crypto_kalshi_risk.py`
- **Readiness Script**: `/scripts/kalshi_crypto_live_readiness.py`
- **Pre-flight Script**: `/scripts/go_live_preflight.py`

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-03-31 | 1.0 | Initial comprehensive runbook created |

---

**REMEMBER**: Live trading involves real money and real risk. When in doubt, stay in paper mode.
