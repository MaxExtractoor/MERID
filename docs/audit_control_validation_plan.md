# Audit Control Validation Plan - Paper Trading Session

**Purpose:** Validate that all 25 audit-driven controls (B1-B25) are firing correctly in a live-like environment using paper trading.

**Safety:** This plan uses PAPER MODE only - no live trades, no real money at risk.

---

## 1. Pre-Flight Checklist

### 1.1 Run Standard Pre-Flight Checks
```bash
py scripts/preflight_check.py
```
All 7 checks must pass:
- Execution gate is CLEAR
- Reconciliation has run successfully
- Price feeds are fresh
- Kill switch is disarmed
- Trade mode is PAPER
- Paper ladder state is loadable
- Session log persistence is working

### 1.2 Run Audit Bug Coverage Tests
```bash
pytest tests/test_kalshi_audit_bug_coverage.py -v
```
All 21 tests must pass (11 functional + 10 marker tests).

### 1.3 Verify Environment Variables
```bash
export MERID_TRADE_MODE=paper
export MERID_ALLOW_LIVE_TRADES=false
export MERID_PROFILE=kalshi_crypto_15m_v2
```

---

## 2. Audit Control to Metric Mapping

### Catalog / Time-Window Layer (B1-B5)

| Bug | Control | Metric to Monitor | Dashboard |
|-----|---------|-------------------|-----------|
| B1 | Series ticker wiring (KXBTC15M) | `kalshi_catalog_priority_series_count` | merid_15m_pipeline_health |
| B2 | minutes_to_expiry defaults to 0.0 | `kalshi_catalog_minutes_to_expiry_none_count` | merid_15m_pipeline_health |
| B3 | Entry window validation | `kalshi_entry_window_validation_errors_total` | merid_15m_pipeline_health |
| B5 | Catalog refresh interval >= 30s | `kalshi_catalog_refresh_interval_seconds` | merid_15m_pipeline_health |

### Risk Sizing Layer (B6-B10)

| Bug | Control | Metric to Monitor | Dashboard |
|-----|---------|-------------------|-----------|
| B6 | asset_horizon_limits populated | `kalshi_risk_asset_horizon_limits_loaded` | merid_risk_safety |
| B7 | Profile overrides YAML risk_limits | `kalshi_profile_override_active` | merid_risk_safety |
| B9 | Single venue KalshiRiskConfig | `kalshi_risk_config_source{source="venue"}` | merid_risk_safety |
| B10 | fractional_contract_override_threshold | `kalshi_fractional_contract_override_valid` | merid_risk_safety |

### Order Routing / Execution Layer (B11-B15)

| Bug | Control | Metric to Monitor | Dashboard |
|-----|---------|-------------------|-----------|
| B11 | Min order notional from profile | `kalshi_min_order_notional_source{source="profile"}` | merid_risk_safety |
| B12 | WS bridge bounded queue | `kalshi_ws_bridge_queue_depth` | merid_15m_pipeline_health |
| B13 | duplicate_unknown handling | `kalshi_duplicate_unknown_orders_total` | merid_kalshi_recon_gate |
| B14 | Deep OTM/ITM from profile | `kalshi_deep_otm_threshold_cents`, `kalshi_deep_itm_threshold_cents` | merid_risk_safety |
| B15 | Execution gate metrics | `execution_gate_blocked_total` | merid_risk_safety |

### Config / Profile Layer (B21-B25)

| Bug | Control | Metric to Monitor | Dashboard |
|-----|---------|-------------------|-----------|
| B21 | Kelly fraction from profile | `kalshi_kelly_fraction_source{source="profile"}` | merid_risk_safety |
| B22 | Profile schema validation | `kalshi_profile_validation_errors_total` | merid_risk_safety |
| B23 | Deep OTM/ITM in profile | `kalshi_profile_deep_otm_threshold_loaded` | merid_risk_safety |
| B24 | IOC auto-below in profile | `kalshi_profile_ioc_threshold_loaded` | merid_risk_safety |
| B25 | Fallback trades disabled | `kalshi_fallback_trades_total` (should be 0) | merid_risk_safety |

---

## 3. Session Execution Plan

### 3.1 Start Paper Trading Session
```bash
# Start MERID in paper mode with full monitoring
py main.py
```

### 3.2 Open Monitoring Dashboards
Open these Grafana dashboards side-by-side:
1. **merid_15m_pipeline_health** - Catalog, entry window, WS bridge metrics
2. **merid_risk_safety** - Risk config, profile validation, deep OTM/ITM
3. **merid_kalshi_recon_gate** - Reconciliation, duplicate handling
4. **merid_pnl_exposure** - Position sizing, Kelly fraction effects

### 3.3 Run 30-Minute Validation Gate
Follow the `/validation-run` workflow:
- Monitor event loop lag (P95 < 500ms)
- Watch for degraded flags
- Track all audit control metrics

### 3.4 Audit Control Validation Checklist

Every 5 minutes during the session, verify:

#### Catalog Layer
- [ ] Series tickers show KXBTC15M (not KXBTC) in catalog metrics
- [ ] No minutes_to_expiry=None errors in logs
- [ ] Entry window validation errors = 0
- [ ] Catalog refresh interval >= 30s

#### Risk Sizing Layer
- [ ] asset_horizon_limits loaded from profile
- [ ] Profile override active = true
- [ ] Risk config source = "venue" (not "pm")
- [ ] Fractional contract override threshold in valid range (0, 1]

#### Execution Layer
- [ ] Min order notional source = "profile"
- [ ] WS bridge queue depth < 80% capacity
- [ ] Duplicate unknown orders tracked (if any)
- [ ] Deep OTM/ITM thresholds match profile values
- [ ] Execution gate blocked count = 0 (or investigate if > 0)

#### Config Layer
- [ ] Kelly fraction source = "profile"
- [ ] Profile validation errors = 0
- [ ] Deep OTM/ITM thresholds loaded from profile
- [ ] IOC auto-below threshold loaded from profile
- [ ] Fallback trades count = 0

---

## 4. Expected Observations

### 4.1 Healthy Session Indicators
- All 21 audit bug tests pass
- Series tickers: KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M
- Kelly fraction: 0.30 (from profile)
- Deep OTM threshold: 5 cents (from profile)
- Deep ITM threshold: 95 cents (from profile)
- IOC auto-below: 120 seconds (from profile)
- Fallback trades: 0 (disabled)
- WS bridge queue depth: < 50% capacity
- Execution gate: CLEAR state
- No profile validation errors

### 4.2 Warning Indicators (Investigate)
- WS bridge queue depth > 80% capacity
- Entry window validation errors > 0
- Duplicate unknown orders > 0
- Execution gate transitions to LIMITED
- Profile validation errors > 0

### 4.3 Critical Indicators (Halt Session)
- Execution gate transitions to BLOCKED
- Series tickers show base format (KXBTC instead of KXBTC15M)
- Kelly fraction not from profile
- Fallback trades > 0
- Deep OTM/ITM thresholds not from profile
- Profile validation errors > 10

---

## 5. Post-Session Analysis

### 5.1 Export Session Data
```bash
# Export session log
type data\session_log.jsonl > session_audit_validation_$(date +%Y%m%d_%H%M%S).jsonl

# Export metrics snapshot
curl http://localhost:9090/api/v1/query?query=kalshi_* > metrics_audit_validation_$(date +%Y%m%d_%H%M%S).json
```

### 5.2 Audit Control Validation Report

Create a report with:
- Session duration and mode (paper)
- All 25 audit bugs and their control status
- Metric snapshots for each control
- Any warnings or critical indicators encountered
- Remediation actions taken (if any)

### 5.3 Control Status Summary

| Bug ID | Control Status | Metric Value | Notes |
|--------|---------------|--------------|-------|
| B1 | ✅ Firing | KXBTC15M series tickers | Verified in catalog |
| B2 | ✅ Firing | minutes_to_expiry=None count = 0 | Default to 0.0 working |
| B3 | ✅ Firing | Entry window validation errors = 0 | Startup validation active |
| B5 | ✅ Firing | Catalog refresh >= 30s | Interval guard active |
| B6 | ✅ Firing | asset_horizon_limits loaded | Profile population working |
| B7 | ✅ Firing | Profile override active = true | YAML overrides working |
| B9 | ✅ Firing | Risk config source = venue | Single source of truth |
| B10 | ✅ Firing | Fractional override in range | Validation active |
| B11 | ✅ Firing | Min notional from profile | Profile sourcing working |
| B12 | ✅ Firing | WS queue depth < 80% | Bounded queue working |
| B13 | ✅ Firing | Duplicate unknown tracked | Conservative handling |
| B14 | ✅ Firing | Deep OTM/ITM from profile | Profile thresholds active |
| B15 | ✅ Firing | Execution gate metrics | Gate tracking working |
| B21 | ✅ Firing | Kelly from profile | Profile sourcing working |
| B22 | ✅ Firing | Profile validation errors = 0 | Schema validation active |
| B23 | ✅ Firing | Deep OTM/ITM loaded | Profile loading working |
| B24 | ✅ Firing | IOC threshold loaded | Profile loading working |
| B25 | ✅ Firing | Fallback trades = 0 | Fallback disabled |

---

## 6. Next Steps

### 6.1 If All Controls Firing
- Document successful validation
- Proceed to longer paper trading sessions (ladder-session workflow)
- Consider incremental live trading plan with same controls

### 6.2 If Any Controls Not Firing
- Investigate the specific control
- Check logs for errors
- Verify profile configuration
- Re-run audit bug coverage tests
- Fix and re-validate

### 6.3 Continuous Monitoring
- Add audit control metrics to standard monitoring
- Set up alerts for critical control failures
- Include audit control validation in CI/CD pipeline
- Run periodic validation sessions (weekly)

---

## 7. Safety Reminders

**CRITICAL:** This plan is for PAPER MODE ONLY.
- Never run with MERID_ALLOW_LIVE_TRADES=true
- Never run with MERID_TRADE_MODE=live
- Always verify trade mode before starting
- Always have kill switch accessible
- Monitor execution gate state continuously
- Halt immediately if unexpected behavior observed

**Emergency Stop:**
```bash
# If anything goes wrong, immediately:
curl -X POST http://localhost:8000/api/v1/kill-switch/engage
# Or use the UI kill switch button
```
