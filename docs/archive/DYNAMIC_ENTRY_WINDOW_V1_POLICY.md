# Dynamic Entry Window Policy v1 - Documentation and Rollback Plan

## Policy Overview

**Policy Name:** `kalshi_15m_*_v1`  
**Policy Version:** v1  
**Assets:** BTC, ETH, SOL, XRP, DOGE  
**Timeframe:** 15-minute Kalshi crypto prediction markets

### Policy Configuration

| Asset | Policy Name | Base Window | Terminal Enabled | Terminal Band | Terminal Edge Threshold |
|-------|-------------|-------------|------------------|---------------|-------------------------|
| BTC   | kalshi_15m_btc_v1 | 12-3 minutes | Yes | 0-3 minutes | ≥20% |
| ETH   | kalshi_15m_eth_v1 | 12-3 minutes | Yes | 0-3 minutes | ≥20% |
| SOL   | kalshi_15m_sol_v1 | 10-4 minutes | No | N/A | N/A |
| XRP   | kalshi_15m_xrp_v1 | 10-4 minutes | No | N/A | N/A |
| DOGE  | kalshi_15m_doge_v1 | 10-4 minutes | No | N/A | N/A |

### Configuration Source

- **Environment Variable:** `MERID_ENTRY_WINDOW_POLICY_VERSION=v1`
- **Module:** `merid/prediction/dynamic_entry_window.py`
- **Config File:** `.env` (lines 713-724)
- **Per-Asset Overrides:** Optional via `MERID_ENTRY_WINDOW_{ASSET}_*` env vars

### Policy Logic

1. **Base Window:** Trades allowed only when `minutes_to_expiry` is within the base window range
2. **Terminal Override:** For BTC/ETH only, if in terminal band (0-3 minutes), trades allowed only if edge ≥20%
3. **Fallback:** SOL/XRP/DOGE have terminal disabled - no trades allowed in terminal band regardless of edge

### Integration Points

The policy is enforced at three layers (defense-in-depth):

1. **Trading Agent** (`merid/prediction/trading_agent.py` - `_in_entry_window`)
   - First filter at signal evaluation
   - Strict mode - no fail-open
   
2. **Arbiter** (`merid/prediction/crypto_top_edge.py` - `submit_candidate`)
   - Second filter at cross-asset ranking
   - Strict mode - no fail-open
   
3. **Risk Layer** (`merid/event_venues/kalshi/kalshi_risk.py` - `_check_order_locked`)
   - Third filter at pre-trade risk checks
   - Fail-open on error (allows order if dynamic window check fails)

All three layers call the same resolver function: `merid.prediction.dynamic_entry_window.resolve_entry_window`

## Bad Outcomes (Triggers for Rollback)

### 1. Execution Freezes
- **Symptom:** Orders hang for >30 seconds without completion
- **Detection:** `[EXECUTION-TRACE]` logs show start but no completion
- **Threshold:** 3+ consecutive freezes or 5+ freezes in 1 hour
- **Action:** Immediate rollback to static config

### 2. Unexpected Rejection Rates
- **Symptom:** High rate of signals rejected by dynamic window
- **Detection:** >50% of signals rejected for `outside_window` or `terminal_disabled`
- **Threshold:** Sustained for 30+ minutes
- **Action:** Review policy parameters, consider rollback

### 3. Drawdown Exceeds Thresholds
- **Symptom:** Significant drawdown correlated with policy activation
- **Detection:** Drawdown >10% in single asset or >5% portfolio-wide within 24 hours
- **Threshold:** Any drawdown >10% triggers review
- **Action:** Immediate rollback and investigation

### 4. Scope Violations Spike
- **Symptom:** Sudden increase in out-of-scope rejections
- **Detection:** >100 scope violations in 15 minutes
- **Threshold:** Sustained spike for 30+ minutes
- **Action:** Check asset/timeframe configuration, rollback if needed

### 5. Terminal Override Not Triggering
- **Symptom:** High-edge trades rejected in terminal band
- **Detection:** Trades with edge ≥20% rejected for `terminal_edge_too_low`
- **Threshold:** 5+ rejections in terminal band with edge ≥20%
- **Action:** Review terminal edge threshold configuration

## Rollback Plan

### Immediate Rollback (Static Config)

If you need to immediately disable dynamic entry windows and revert to static config:

1. **Edit `.env`:**
   ```bash
   # Comment out or remove:
   # MERID_ENTRY_WINDOW_POLICY_VERSION=v1
   
   # Ensure static config is set:
   MERID_PM_ENTRY_WINDOW_15M_MINUTES=10
   MERID_PM_ENTRY_WINDOW_15M_CUTOFF=5
   ```

2. **Restart the server:**
   ```bash
   # Stop the current server process
   # Restart with new .env configuration
   ```

3. **Verify in logs:**
   - Look for `[PM_WINDOW_FILTER]` logs (static config)
   - Should NOT see `[PM_WINDOW_FILTER_DYNAMIC]` logs

### Per-Asset Rollback

If only specific assets need adjustment:

1. **Edit `.env` to override specific asset:**
   ```bash
   # Example: Widen BTC window to 15-5
   MERID_ENTRY_WINDOW_BTC_START_MINUTES=15
   MERID_ENTRY_WINDOW_BTC_END_MINUTES=5
   MERID_ENTRY_WINDOW_BTC_TERMINAL_ENABLED=true
   MERID_ENTRY_WINDOW_BTC_TERMINAL_EDGE_THRESHOLD=25.0
   MERID_ENTRY_WINDOW_BTC_POLICY_NAME=kalshi_15m_btc_v1_wide
   ```

2. **Restart the server**

3. **Verify with config sanity check:**
   ```bash
   py scripts\verify_entry_window_config.py
   ```

### Policy Version Rollback

If you need to revert to a previous policy version:

1. **Edit `.env`:**
   ```bash
   MERID_ENTRY_WINDOW_POLICY_VERSION=v0  # or previous version
   ```

2. **Restart the server**

## Verification Steps

### Pre-Restart Verification

1. **Run config sanity check:**
   ```bash
   py scripts\verify_entry_window_config.py
   ```
   - Expected: All 5 assets configured, no sanity issues

2. **Run unit tests:**
   ```bash
   py scripts\test_dynamic_entry_window.py
   ```
   - Expected: 31/31 tests passed

### Post-Restart Verification

1. **Check startup logs for policy header:**
   ```
   [DYNAMIC_WINDOW_POLICY_HEADER] version=v1 policies={...}
   ```
   - Expected: All assets show correct windows and terminal settings

2. **Verify signal logs include policy tags:**
   - Look for `entry_window_policy_name`, `entry_window_bucket`, `entry_window_decision_reason`
   - Expected: All signals have these fields populated

3. **Verify no execution freezes:**
   - Look for `[EXECUTION-TRACE]` logs
   - Expected: All signals have start and complete logs within 30 seconds

## Data Collection for Policy Tuning

### Metrics to Track

1. **Signal counts per asset and bucket**
2. **Signal rejection reasons per asset**
3. **Order rejection reasons at risk layer**
4. **Win rate per bucket**
5. **EV per trade per bucket**
6. **Drawdown per bucket**

### Analysis Script

After collecting sufficient data (≥100 trades per bucket), use:
- `scripts/analyze_entry_window_policy.py` (to be created)
- Aggregates metrics by asset × bucket
- Plots performance over time

### Policy Iteration Process

1. Run v1 for sufficient data collection
2. Analyze metrics by bucket
3. Identify underperforming buckets
4. Adjust window parameters or edge thresholds
5. Deploy as v2 with new policy names
6. Compare v1 vs v2 performance

## Support and Troubleshooting

### Logs to Check

- `[DYNAMIC_WINDOW_POLICY_HEADER]` - Policy loaded on startup
- `[PM_WINDOW_FILTER_DYNAMIC]` - Agent-level decisions
- `[CRYPTO_TOP_EDGE]` - Arbiter-level decisions
- `[RISK] Dynamic window rejection` - Risk-level decisions
- `[EXECUTION-TRACE]` - Execution flow and freeze detection

### Common Issues

**Issue:** All signals rejected for `outside_window`
- **Cause:** Window parameters too narrow or market expiry mismatch
- **Fix:** Widen window parameters or verify market end_date accuracy

**Issue:** Terminal override not triggering
- **Cause:** Edge calculation incorrect or threshold too high
- **Fix:** Lower `TERMINAL_EDGE_THRESHOLD` or verify edge calculation

**Issue:** Config not loading
- **Cause:** Env var not set or module import error
- **Fix:** Run `verify_entry_window_config.py` to diagnose

### Contact

For issues with dynamic entry window policy:
- Check logs first for error messages
- Run config sanity check script
- Verify unit tests pass
- Document the issue with logs before rollback

## Revision History

- **v1 (2026-05-12):** Initial deployment
  - BTC/ETH: 12-3 base, terminal 3-0 with ≥20% edge
  - SOL/XRP/DOGE: 10-4 base, terminal disabled
