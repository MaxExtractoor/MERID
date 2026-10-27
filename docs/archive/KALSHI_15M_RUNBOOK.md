# Kalshi 15m Crypto Runbook

This runbook provides operational guidance for the Kalshi 15-minute crypto sealed stack (kalshi_crypto_15m_v2 profile).

## Table of Contents
- [Startup Requirements](#startup-requirements)
- [Pre-Deploy Checks](#pre-deploy-checks)
- [Metrics and Health](#metrics-and-health)
- [Feed Lag & Edge Calibration](#feed-lag--edge-calibration)
- [Troubleshooting](#troubleshooting)

---

## Startup Requirements

### Environment Variables

The following environment variables MUST be set for the Kalshi 15m crypto stack to operate correctly:

**Required Profile:**
- `MERID_PROFILE=kalshi_crypto_15m_v2` - MUST be set to enable the sealed 15m stack

**Kalshi Credentials:**
- `KALSHI_ENV` - Kalshi environment (`demo` or `live`)
- `KALSHI_API_KEY` - Kalshi API key for trading
- `KALSHI_PRIVATE_KEY` - Private key for order signing

**Operator Security:**
- `MERID_OPERATOR_TOKEN` - Operator token for accessing kill switch and emergency controls (REQUIRED in production)

**Configuration:**
- `KALSHI_15M_CONFIG_SIGNATURE` - (Optional) Expected config signature for change detection

### Profile Validation

On startup, the system validates:
1. **Profile Assertion**: Confirms `MERID_PROFILE=kalshi_crypto_15m_v2` is set
2. **Router Isolation**: Validates only the 30 minimal routers are registered
3. **Import Isolation**: Checks that forbidden modules (swarm, sentiment, governance, debate, non-Kalshi venues) are not imported
4. **Config Signature**: Computes and logs the Kalshi 15m config signature

If any validation fails, the system will crash with a clear error message.

---

## Pre-Deploy Checks

### 1. Router Isolation Verification

Verify that only the minimal router set is registered:

```bash
# Check router registration in logs
grep "ROUTER REGISTRATION" logs/merid.log
# Should show: "🎯 Registering MINIMAL router set for kalshi_crypto_15m_v2 (sealed 15m stack)"
# Should show: "✅ Registered 30 minimal routers for kalshi_crypto_15m_v2"
```

Verify forbidden routers are NOT registered:

```bash
# Check for forbidden router prefixes
curl http://localhost:8000/api/v1/swarm/health
# Should return 404 (Not Found) - swarm router should not be registered

curl http://localhost:8000/api/v1/sentiment/status
# Should return 404 (Not Found) - sentiment router should not be registered
```

### 2. Pytest Test Suite

Run the Kalshi 15m test suite:

```bash
# Set environment variables
export MERID_PROFILE=kalshi_crypto_15m_v2
export MERID_TEST_MODE=1

# Run Kalshi 15m tests
pytest tests/kalshi_15m/ -m kalshi_15m -v --tb=short
```

Expected: All tests should pass

### 3. Config Signature Verification

Verify the config signature matches expected value (if set):

```bash
# Get current config signature
export MERID_PROFILE=kalshi_crypto_15m_v2
python -c "from merid.config.signature import get_kalshi_15m_config_signature; print(get_kalshi_15m_config_signature())"

# Compare with expected signature (if set)
echo $KALSHI_15M_CONFIG_SIGNATURE
```

### 4. Agent Grid Configuration

Verify the agent grid has the correct 15m agents:

```bash
curl http://localhost:8000/api/v1/kalshi-grid/agents
# Should return: BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M
# Each agent should have series_tickers: ["KXBTC15M"], ["KXETH15M"], etc.
```

### 5. Market Catalog Verification

Verify the market catalog includes 15m crypto markets:

```bash
curl http://localhost:8000/api/v1/kalshi/markets?series_ticker=KXBTC15M
# Should return BTC 15-minute markets

curl http://localhost:8000/api/v1/kalshi/markets?series_ticker=KXETH15M
# Should return ETH 15-minute markets
```

---

## Metrics and Health

### Health Endpoints

**System Health:**
```bash
curl http://localhost:8000/api/v1/health
# Returns overall system health status
```

**Kalshi Venue Health:**
```bash
curl http://localhost:8000/api/v1/kalshi/health
# Returns Kalshi venue health (WS connection, catalog, bankroll)
```

**Agent Grid Health:**
```bash
curl http://localhost:8000/api/v1/kalshi-grid/health
# Returns agent grid health (agent status, cycle counts)
```

### Key Metrics

**Reconciliation Metrics:**
- `kalshi_recon_critical_count` - Number of CRITICAL reconciliation issues
- `kalshi_recon_warning_count` - Number of WARNING reconciliation issues
- `kalshi_recon_last_run_seconds` - Time since last reconciliation run

**Risk Metrics:**
- `kalshi_risk_total_notional_usd` - Total portfolio notional exposure
- `kalshi_risk_max_notional_per_asset_usd` - Per-asset notional caps
- `kalshi_risk_max_daily_loss_usd` - Daily loss cap

**Execution Metrics:**
- `kalshi_orders_submitted` - Total orders submitted
- `kalshi_orders_filled` - Total orders filled
- `kalshi_orders_rejected` - Total orders rejected

### Expected Healthy States

**Reconciliation:**
- `kalshi_recon_critical_count = 0` - No critical discrepancies
- `kalshi_recon_warning_count <= 5` - Minimal warning-level discrepancies acceptable
- `kalshi_recon_last_run_seconds < 60` - Reconciliation should run every 30-60 seconds

**Risk:**
- `kalshi_risk_total_notional_usd < max_total_notional` - Within portfolio cap
- Per-asset notional within configured limits
- `kalshi_risk_max_daily_loss_usd` not exceeded

**Execution:**
- Orders being submitted and filled at expected rate
- Rejection rate < 5% (normal rate limit rejections acceptable)

---

## Feed Lag & Edge Calibration

This section provides practical trading rules for feed lag calibration and edge gating, aligned with Kalshi's RTI-based crypto settlement mechanism.

### Reference Price

**Always treat the CFB RTI 60-second average as the true settlement anchor for crypto contracts.**

- Kalshi crypto contracts settle on a 60-second average of CFB RTIs around event time
- For "BTC > X in 15 minutes", the model computes P(60-second RTI average > strike)
- Reference: https://help.kalshi.com/en/articles/13823838-crypto-markets
- CFB Benchmarks: https://www.cfbenchmarks.com/data/indices/BRTI

### Staleness Rule

**Never trade when spot_age_sec > 5.**

- Spot data older than 5 seconds is considered stale
- Kalshi RTIs update every second, so stale data misrepresents settlement conditions
- If `spot_stale_total` metric spikes, treat it as an infrastructure incident
- Check: `merid_15m_spot_stale_total{asset="BTC",source="cfbenchmarks"}`

### Edge Rule

**Only trade when:**
1. `model_win_prob` is computed versus the Kalshi settlement definition (60-second RTI average)
2. `raw_edge >= latency_buffer(symbol, regime)`

The latency buffer accounts for:
- Feed lag (spot to Kalshi book propagation)
- Spread (crossing the spread for taker orders)
- Slippage (execution impact)
- Safety margin (regime uncertainty)

The buffer is calibrated from historical TradeTrace data via `scripts/calibrate_feed_lag.py`.

### Execution Mode

**Use `choose_execution_mode()` decisions:**

- **Near expiry, large edge, tight spreads** → taker (speed priority)
- **Wide spreads, moderate edge, enough time** → maker or split (fee savings)
- Execution mode affects latency buffer (maker gets 20% discount on lag buffer)

### Calibration Cadence

**Run `scripts/calibrate_feed_lag.py`:**

- **Initially:** Nightly after accumulating sufficient samples (≥10 per asset)
- **Then:** Daily/weekly per volatility regime
- **Before deployment:** Review updated `config/feed_lag_calibration.json`
- **Rollback:** If new buffers cause pass rate collapse, revert to previous config

**Calibration script usage:**
```bash
# Run calibration on trade trace data
python scripts/calibrate_feed_lag.py \
  --input data/kalshi_trade_trace.jsonl \
  --output config/feed_lag_calibration.json \
  --min-samples 10
```

### Monitoring Metrics

**Key metrics for tuning buffer conservatism:**

- `merid_15m_edge_latency_buffer_pass_total{symbol, result}` - Counter for pass/fail events
- **Pass rate:** `pass / (pass + fail)` by symbol and time
- **Target:** 60-80% pass rate (balance between opportunity and safety)
- `merid_15m_trade_trace_samples_total{symbol}` - TradeTrace records per symbol
- `merid_15m_signal_to_fill_latency_ms{symbol}` - Signal to fill latency histogram
- `merid_15m_slippage_ticks{symbol, size_bucket}` - Slippage distribution

**Interpretation:**
- **Pass rate too high (>90%):** Buffer too conservative, missing opportunities
- **Pass rate too low (<50%):** Buffer too aggressive, accepting too much risk
- **Sudden drop in pass rate:** Regime change or infrastructure issue
- **Increasing slippage:** Market impact or execution degradation

### Incident Triggers

**Pause new deployments and investigate if:**

1. **`edge_latency_buffer_pass_rate` collapses** - Sudden drop indicates buffer misalignment
2. **`post_fill_move` distributions deteriorate** - Settlement outcomes diverging from model
3. **PnL deviates from expected edge** - Model or calibration assumptions broken
4. **`spot_stale_total` spikes** - Infrastructure issue with spot feed

**Investigation steps:**
1. Check RTI variance assumptions in `settlement_risk_model.py`
2. Review latency buffers in `config/feed_lag_calibration.json`
3. Check for recent infrastructure or Kalshi API changes
4. Verify TradeTrace data quality (missing timestamps, outliers)
5. Re-run calibration with recent data if regime changed

**Reference:**
- Kalshi settlement API: https://docs.kalshi.com/fix/market-settlement
- CME CF benchmarks FAQ: https://www.cmegroup.com/articles/faqs/cme-cf-cryptocurrency-benchmarks-faq.html

---

## Troubleshooting

### Profile Violation Error

**Error:** `PROFILE VIOLATION: _init_kalshi_crypto_15m_app called with MERID_PROFILE='...', expected 'kalshi_crypto_15m_v2'`

**Cause:** `MERID_PROFILE` environment variable is not set to `kalshi_crypto_15m_v2`

**Fix:**
```bash
export MERID_PROFILE=kalshi_crypto_15m_v2
# Restart the application
```

### Router Isolation Check Failed

**Error:** `ROUTER ISOLATION CHECK FAILED: Forbidden router registered`

**Cause:** A forbidden router (swarm, sentiment, governance, etc.) was registered

**Fix:**
- Check the router registration logs
- Ensure `_register_routers_for_profile()` is called with the correct profile
- Verify no legacy router imports are present in the sealed stack

### Import Isolation Check Failed

**Error:** `Import isolation check failed: Forbidden module imported`

**Cause:** A forbidden module (swarm, sentiment, governance, etc.) was imported

**Fix:**
- Check the import stack trace in the error
- Remove the import from the sealed stack code
- Ensure the module is only imported in legacy paths

### Config Signature Mismatch

**Error:** `Config signature mismatch! Expected: ..., Current: ...`

**Cause:** Kalshi 15m config has changed (intentional or accidental)

**Fix:**
- If intentional: Update `KALSHI_15M_CONFIG_SIGNATURE` environment variable
- If accidental: Review config changes and revert if needed

### Agent Not Generating Signals

**Symptom:** Agent shows 0 cycle count or no recent decisions

**Checks:**
1. Verify agent is enabled in agent grid config
2. Check agent has correct series_tickers (e.g., `["KXBTC15M"]` for BTC_15M)
3. Verify market catalog includes 15m markets for the asset
4. Check trading mode is not in kill switch state

### Reconciliation Critical Discrepancies

**Symptom:** `kalshi_recon_critical_count > 0`

**Checks:**
1. Check reconciliation report for details: `GET /api/v1/kalshi/reconciliation/report`
2. Verify Kalshi API credentials are valid
3. Check WebSocket connection to Kalshi is healthy
4. Review fills ledger for missing or phantom positions

---

## Quick Live Dry-Run Plan

For a quick live dry-run without real trading:

1. **Set Demo Mode:**
   ```bash
   export KALSHI_ENV=demo
   export MERID_PROFILE=kalshi_crypto_15m_v2
   ```

2. **Disable Order Submission:**
   - Add `dry_run: true` to kalshi_crypto_15m.yaml profile config
   - Or use the sandbox/dry-run flag (see Extra 1)

3. **Run Pre-Deploy Checks:**
   ```bash
   pytest tests/kalshi_15m/ -m kalshi_15m -v
   ```

4. **Start Application:**
   ```bash
   python -m uvicorn web.main:app --reload
   ```

5. **Monitor Logs:**
   - Check for successful startup
   - Verify router isolation
   - Verify import isolation
   - Check config signature

6. **Verify Health:**
   ```bash
   curl http://localhost:8000/api/v1/health
   curl http://localhost:8000/api/v1/kalshi/health
   ```

7. **Review Metrics:**
   - Check agent cycle counts
   - Check reconciliation status
   - Verify no critical discrepancies

---

## Contact and Escalation

For issues not covered in this runbook:
- Check the [Kalshi Contract Audit Report](./KALSHI_CONTRACT_AUDIT_REPORT.md) for detailed implementation notes
- Review the [Kalshi 15m Implementation Plan](../KALSHI_15M_IMPLEMENTATION_PLAN.md) for design decisions
- Check system logs in `logs/merid.log` for detailed error messages
