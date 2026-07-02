# First Day Playbook - 15m Crypto Trading Restart

## Purpose
This playbook provides a step-by-step operational guide for the first restart window of the 15m crypto trading system.

## Pre-Restart Checklist (T-30 minutes)

### Environment Validation
- [ ] Verify `MERID_PROFILE=kalshi_crypto_15m_v2` is set
- [ ] Verify `MERID_PM_PROFILE=baseline` is set (or appropriate profile)
- [ ] Check Kalshi API credentials are valid (test with `GET /me`)
- [ ] Verify bankroll service is accessible
- [ ] Verify spot price feeds are operational (BTC, ETH, SOL, XRP, DOGE)

### System Health Checks
- [ ] Run `python scripts/validate_btc_wiring.py` - ensure BTC is wired end-to-end
- [ ] Run catalog refresh and verify all 5 series tickers have markets
- [ ] Check log directory exists and is writable
- [ ] Verify kill-switch is enabled and functional

### Guardrails Verification
- [ ] Review `config/live_session_guardrails.yaml` values
- [ ] Verify per-market caps are appropriate for bankroll size
- [ ] Verify rate limits are within Kalshi API expectations
- [ ] Test kill-switch activation (dry-run)

## T-0 to T+60m: Monitoring and Response

### T-0: Restart Initiation
**Time:** 0 minutes
**Action:** Start the trading system
**Watch:** System startup logs
**Expected:** All agents initialize, catalog refresh succeeds, no startup errors

**Abort if:**
- Startup fails with critical error
- Catalog refresh returns 0 markets for any series
- Bankroll service fails to initialize

### T+5m: First Cycle Check
**Time:** 5 minutes
**Action:** Check first trading cycle logs
**Watch:**
- `[ASSET-SIGNAL-PARITY]` logs for all 5 assets
- `[SCHEDULER-CHECK]` logs for window decisions
- `[ORDER-SUBMIT]` logs for order submissions

**Expected:**
- All 5 assets generate some signals
- At least 1-2 orders submitted per cycle
- No scheduler rejections for all assets

**Abort if:**
- 0 signals for any asset (especially BTC)
- 0 orders submitted across all assets
- All orders rejected by scheduler

### T+15m: Fill Rate Check
**Time:** 15 minutes
**Action:** Check fill rates
**Watch:**
- `[FILL]` logs for order executions
- Fill rate per asset (orders → fills)
- Run `python scripts/health_dashboard.py --log-dir /path/to/logs`

**Expected:**
- Fill rate > 50% for at least 3 assets
- At least 1 fill per asset with signals
- No stuck orders (orders submitted but no fill for >5 minutes)

**Abort if:**
- 0 fills across all assets
- Fill rate < 20% for all assets
- Orders stuck for >10 minutes

### T+30m: API Health Check
**Time:** 30 minutes
**Action:** Check API health
**Watch:**
- API error codes in logs
- Rate limit warnings (429 errors)
- Latency metrics

**Expected:**
- API error rate < 10%
- No sustained rate limit errors
- Order latency < 5s

**Abort if:**
- API error rate > 50%
- Sustained 429 errors for >5 minutes
- API becomes unresponsive

### T+60m: Stability Assessment
**Time:** 60 minutes
**Action:** Full system assessment
**Watch:**
- Net PnL per asset
- Position counts
- Rejection patterns
- Run `python scripts/log_sweep_per_asset.py --log-dir /path/to/logs --hours 1`

**Expected:**
- At least 10 fills total across all assets
- No catastrophic losses (> $100)
- Rejection patterns are reasonable (not blocking all trades)

**Decision point:** Continue or pause for investigation

## Pre-Planned Experiments

### Experiment 1: Manual BTC Order Validation
**Purpose:** Validate BTC discovery and execution independently of strategy logic
**Steps:**
1. Manually submit a 1-contract YES order on a BTC 15m market
2. Verify order reaches Kalshi API
3. Verify order fills or is rejected with clear reason
4. Cancel order if not filled

**Success criteria:** Order reaches API and gets clear response

### Experiment 2: Per-Asset Signal Parity Check
**Purpose:** Verify all assets generate signals at similar rates
**Steps:**
1. Monitor `[ASSET-SIGNAL-PARITY]` logs for 30 minutes
2. Compare signal counts per asset
3. Compare avg_edge and avg_confidence per asset

**Success criteria:** All assets generate signals with similar edge/confidence

### Experiment 3: Risk Limit Validation
**Purpose:** Verify risk limits are enforced correctly
**Steps:**
1. Attempt to exceed per-market cap (submit larger order)
2. Verify order is rejected by risk check
3. Check `[RISK-DECISION]` log for rejection reason

**Success criteria:** Risk limits enforced with clear rejection reason

## Abort Thresholds

### Immediate Abort (Stop Trading)
- 0 fills for 15 minutes across all assets
- API error rate > 50% for 5 minutes
- Daily loss > $500
- Position stuck for 30 minutes
- Kill-switch activated (auto or manual)

### Pause for Investigation (Continue Exits, Block Entries)
- 0 signals for BTC for 10 minutes (but other assets trading)
- Fill rate < 20% for 20 minutes
- Unexpected rejection pattern (e.g., all orders rejected for same reason)
- Clock skew detected (> 10 seconds vs Kalshi)

### Continue Monitoring (No Action)
- Low fill rate for single asset (others trading normally)
- Occasional API errors (< 10% rate)
- Small losses (< $50)

## Ownership and Communication

### Roles
- **Operator:** Monitors dashboard, makes abort/continue decisions
- **Engineer:** Investigates technical issues, implements fixes
- **Risk Manager:** Monitors PnL and risk limits, approves larger positions

### Communication Channels
- **Primary:** Slack channel #merid-live
- **Urgent:** Direct message to Operator
- **Incident:** Create incident ticket if abort occurs

### Decision Framework
1. Operator identifies issue from dashboard/logs
2. Operator posts issue to Slack with severity (IMMEDIATE/INVESTIGATE/MONITOR)
3. Engineer investigates and proposes action
4. Risk Manager approves if action affects risk limits
5. Operator executes action (abort/pause/continue)

## Post-Restart (T+60m to T+24h)

### T+2h: Full Log Analysis
- Run `python scripts/log_sweep_per_asset.py --log-dir /path/to/logs --hours 2`
- Analyze rejection patterns per asset
- Identify bottlenecks (signal generation, scheduler, risk, execution)

### T+4h: Timing Analysis
- Correlate `[ENTRY-TIMING]` with `[SCHEDULER-CHECK]` logs
- Compute early entry cost per trade
- Identify if early entries are causing poor performance

### T+24h: Decision on P2 Deployment
- Based on funnel analysis, decide whether to deploy P2 entry timing improvements
- If bottleneck is NOT early entry, defer P2
- If bottleneck IS early entry, deploy least invasive P2 element first

## Appendix: Quick Reference Commands

```bash
# Validate BTC wiring
python scripts/validate_btc_wiring.py

# Health dashboard
python scripts/health_dashboard.py --log-dir /path/to/logs

# Log sweep per asset
python scripts/log_sweep_per_asset.py --log-dir /path/to/logs --hours 24

# Shadow session (dry-run)
python scripts/shadow_session.py --dry-run

# Check clock skew
python scripts/check_clock_skew.py
```

## Emergency Contacts
- Operator: [CONTACT]
- Engineer: [CONTACT]
- Risk Manager: [CONTACT]
