# Unified Edge Deployment Checklist

## Pre-Deployment Checklist

### 1. Configuration Setup
- [ ] Set `MERID_UNIFIED_EDGE_ENABLED=false` (start disabled)
- [ ] Set `MERID_CALIBRATION_VERSION=placeholder` (initial value)
- [ ] Verify `MERID_LIVE_SESSION_MAX_RISK_USD` is set (default: 300)
- [ ] Verify `MERID_PROFILE=kalshi_crypto_15m_v2` or appropriate profile
- [ ] Verify `MERID_PM_PROFILE=baseline` or appropriate profile

### 2. Calibration Data Collection
- [ ] Collect historical Kalshi contract data (30+ days)
- [ ] Collect CF Benchmarks RTI data for all 5 assets
- [ ] Collect spot price data from multiple exchanges
- [ ] Collect order book depth and spread history
- [ ] Collect slippage data (expected vs actual fills)

### 3. Calibration Fitting
- [ ] Run `notebooks/per_asset_calibration_outline.md` to fit parameters
- [ ] Fit per-asset spot-contract mappings (f_a)
- [ ] Fit per-asset 15m volatility estimates (σ_a)
- [ ] Fit per-asset slippage models
- [ ] Validate calibration on hold-out set
- [ ] Export calibration parameters to config

### 4. CFB API Integration
- [ ] Integrate CF Benchmarks API for RTI proxy
- [ ] Test CFB proxy spot price retrieval
- [ ] Verify CFB proxy matches settlement reference
- [ ] Set `is_rti_proxy=True` in SpotReference when CFB available
- [ ] Add CFB API authentication and rate limiting

### 5. Validation Scripts
- [ ] Run `scripts/validate_contract_metadata.py` - verify strike extraction
- [ ] Run `scripts/trace_one_market.py` - verify end-to-end pipeline
- [ ] Run `scripts/production_bug_hunt.py` - check for bugs
- [ ] Run `scripts/shadow_unified_edge.py` - compare vs production

### 6. Startup Validation
- [ ] Run `validate_unified_edge_configuration()` - passes with placeholder
- [ ] Run `validate_all()` - all validations pass
- [ ] Verify startup logs show no errors
- [ ] Verify configuration signature logged

### 7. Shadow Mode Testing
- [ ] Enable unified edge in shadow mode (observe only)
- [ ] Run for 2-4 hours in staging
- [ ] Compare unified edge decisions vs production
- [ ] Check for pathological cases (edge_R > 5.0, negative edge_R)
- [ ] Verify no NaN/None propagation
- [ ] Verify alignment checks working

### 8. Gradual Rollout
- [ ] Set `MERID_CALIBRATION_VERSION=v1` (actual version)
- [ ] Enable unified edge: `MERID_UNIFIED_EDGE_ENABLED=true`
- [ ] Start with reduced risk budget (50% of normal)
- [ ] Monitor for 24-48 hours
- [ ] Check logs for `[UNIFIED-EDGE-APPLIED]` entries
- [ ] Check logs for `[ALIGNMENT-DEGRADED]` entries
- [ ] Verify edge values are reasonable (0.01-0.10 range)
- [ ] Verify edge_R values are reasonable (0.5-2.0 range)

### 9. Full Deployment
- [ ] Restore normal risk budget
- [ ] Monitor for 48-72 hours
- [ ] Check realized PnL vs expected
- [ ] Check fill rate improvement
- [ ] Check slippage vs model predictions
- [ ] Verify no alignment degradation
- [ ] Verify no NaN/None propagation

### 10. Ongoing Monitoring
- [ ] Monitor edge distribution per asset
- [ ] Monitor edge_R distribution per asset
- [ ] Monitor alignment gaps per asset
- [ ] Monitor degraded mode activations
- [ ] Monitor calibration drift
- [ ] Re-fit calibration parameters weekly (initially)
- [ ] Re-fit calibration parameters monthly (after stable)

## Rollback Plan

If issues occur during deployment:

1. **Immediate Rollback:**
   ```bash
   # Disable unified edge
   $env:MERID_UNIFIED_EDGE_ENABLED = "false"
   # Restart system
   ```

2. **Partial Rollback:**
   - Keep unified edge enabled but reduce risk budget
   - Monitor for 24 hours before deciding

3. **Investigation:**
   - Check logs for `[UNIFIED-EDGE-ERROR]` entries
   - Check logs for `[ALIGNMENT-DEGRADED]` entries
   - Run `scripts/production_bug_hunt.py`
   - Run `scripts/shadow_unified_edge.py`

## Success Criteria

Deployment is successful when:

- All startup validations pass
- No `[UNIFIED-EDGE-ERROR]` entries in logs
- No `[ALIGNMENT-DEGRADED]` entries in logs
- Edge values in reasonable range (0.01-0.10)
- Edge_R values in reasonable range (0.5-2.0)
- Fill rate improves vs baseline
- Realized PnL improves vs baseline
- No NaN/None propagation
- Alignment gaps < 50 cents for all assets

## Failure Criteria

Deployment fails if:

- Startup validation fails
- Frequent `[UNIFIED-EDGE-ERROR]` entries
- Frequent `[ALIGNMENT-DEGRADED]` entries
- Edge values outside reasonable range
- Edge_R values outside reasonable range
- Fill rate degrades vs baseline
- Realized PnL degrades vs baseline
- NaN/None propagation detected
- Alignment gaps > 50 cents for any asset
- Risk routing violations detected

## Contact

For issues during deployment:
- Check logs for `[UNIFIED-EDGE-*]` tags
- Check logs for `[ALIGNMENT-*]` tags
- Check logs for `[RISK-ROUTING-*]` tags
- Run validation scripts to diagnose
- Rollback if issues cannot be resolved quickly
