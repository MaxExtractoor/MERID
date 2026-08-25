# Debug Checklist: Next Live Tick (2026-08-03)

## Purpose

Validate the end-to-end fixes in live 15-minute conditions and determine if the real fix is:
- Cap adjustment (measure actual spread distributions)
- Thesis-band adjustment (validate NO range alignment)
- Policy mismatch (identify remaining gating issues)
- Dynamic spread model validation (verify Avellaneda-Stoikov model is working correctly)

## Pre-Tick Setup

### 1. Environment Verification
- [ ] Verify all code changes are deployed
- [ ] Verify test suites pass: `pytest tests/test_book_validity_2026_08_03.py tests/test_cap_wiring_2026_08_03.py tests/test_thesis_band_alignment_2026_08_03.py tests/test_dynamic_spread_model_2026_08_03.py`
- [ ] Verify logging is enabled for all gate layers
- [ ] Verify market state store is initialized
- [ ] Verify dynamic spread model is available and functioning

### 2. Baseline Metrics
- [ ] Record current spread cap configuration:
  - [ ] Dynamic spread model: Avellaneda-Stoikov based
  - [ ] Maker vs. taker handling: Different spread compensation
  - [ ] Time-bucket-specific caps: 0-3min, 3-6min, 6-10min, 10-13min, 13-15min
  - [ ] Volatility-adjusted spreads: Widen in high volatility
  - [ ] Order flow imbalance detection: Adverse selection protection
  - [ ] Fallback profile cap: 20c (from YAML)
- [ ] Record current thesis band configuration:
  - [ ] YES: 10c-75c
  - [ ] NO: 25c-99c
- [ ] Record current book validity thresholds:
  - [ ] Degenerate book: ask >= 98c
  - [ ] Dust-only: both bids <= 2c
  - [ ] One-sided: only YES or only NO valid

## Live Tick Monitoring

### 3. Signal Generation Layer
**Watch for log patterns:**
```
[SIGNAL-GENERATION] asset=%s side=%s thesis_price=%dc
[PRICE-SIDE-CHECK] thesis_side=%s yes_price=%dc no_price=%dc price_range_ok=%s
[PRICE-SIDE-CHECK-REJECT] thesis_side=%s thesis_price=%dc outside %s range
```

**Record for each asset:**
- [ ] BTC: Signal generated? Thesis side? Price? In range?
- [ ] ETH: Signal generated? Thesis side? Price? In range?
- [ ] SOL: Signal generated? Thesis side? Price? In range?
- [ ] XRP: Signal generated? Thesis side? Price? In range?
- [ ] DOGE: Signal generated? Thesis side? Price? In range?

**Key questions:**
- Are any assets filtered out by thesis band?
- If so, which range is rejecting them (YES 10c-75c or NO 25c-99c)?
- Are the rejected prices actually valid for the current market?

### 4. Candidate Generation Layer
**Watch for log patterns:**
```
[CANDIDATE-GENERATION] asset=%s side=%s price=%dc edge=%.4f confidence=%.4f
[PRICE-SIDE-CHECK-INVARIANT] asset=%s thesis_side=%s signal_side=%s thesis_edge=%.4f
```

**Record for each asset:**
- [ ] BTC: Candidate created? Price? Edge? Confidence?
- [ ] ETH: Candidate created? Price? Edge? Confidence?
- [ ] SOL: Candidate created? Price? Edge? Confidence?
- [ ] XRP: Candidate created? Price? Edge? Confidence?
- [ ] DOGE: Candidate created? Price? Edge? Confidence?

**Key questions:**
- Are all assets generating candidates?
- If not, which gate is blocking them?
- Are the edge/confidence values reasonable?

### 5. Allocator Choice Layer
**Watch for log patterns:**
```
[ALLOCATOR-CHOICE] asset=%s side=%s price=%dc edge=%.4f notional_usd=%.2f
[ALLOCATOR-REJECT] asset=%s side=%s reason=%s
```

**Record for each asset:**
- [ ] BTC: Chosen by allocator? Notional? Edge?
- [ ] ETH: Chosen by allocator? Notional? Edge?
- [ ] SOL: Chosen by allocator? Notional? Edge?
- [ ] XRP: Chosen by allocator? Notional? Edge?
- [ ] DOGE: Chosen by allocator? Notional? Edge?

**Key questions:**
- Are candidates reaching the allocator?
- If not, which layer is blocking them?
- Are the chosen candidates the highest-edge ones?

### 6. Maker/Taker Mode Layer
**Watch for log patterns:**
```
[MAKER-TAKER-MODE] asset=%s side=%s mode=%s aggressiveness=%s
[TIF-RESOLUTION] asset=%s side=%s tif=%s ioc_below_seconds=%s
```

**Record for each asset:**
- [ ] BTC: Maker or taker? TIF? IOC below?
- [ ] ETH: Maker or taker? TIF? IOC below?
- [ ] SOL: Maker or taker? TIF? IOC below?
- [ ] XRP: Maker or taker? TIF? IOC below?
- [ ] DOGE: Maker or taker? TIF? IOC below?

**Key questions:**
- Are maker-intended orders being treated as maker?
- Are taker-intended orders being treated as taker?
- Is the IOC threshold appropriate for current time-to-expiry?

### 7. Book Validity Layer
**Watch for log patterns:**
```
[MICROSTRUCTURE-GATE] Refreshed degenerate book from market state: ticker=%s yes_bid %s->%s yes_ask %s->%s
[HEALTH-CIRCUIT-BREAKER] degenerate_book(%s)
[CATALOG-CROSS-VALIDATION] Exception during cross-validation for %s: %s
```

**Record for each asset:**
- [ ] BTC: Book valid? Degenerate? Catalog mismatch?
- [ ] ETH: Book valid? Degenerate? Catalog mismatch?
- [ ] SOL: Book valid? Degenerate? Catalog mismatch?
- [ ] XRP: Book valid? Degenerate? Catalog mismatch?
- [ ] DOGE: Book valid? Degenerate? Catalog mismatch?

**Key questions:**
- Are any books detected as degenerate?
- If so, are they being refreshed from market state?
- Are catalog cross-validation checks passing?

### 8. Dynamic Spread Model Layer
**Watch for log patterns:**
```
[EDGE-AWARE-GATE] Using dynamic spread model: ticker=%s side=%s mid=%.1fc inventory=%d tte=%s time_bucket=%s ofi=%s optimal_spread=%.1fc reservation_price=%.1fc confidence=%.2f
[EDGE-AWARE-GATE] ticker=%s side=%s p_hat=%.1fc passes=%s reason=%s
[TIME-BUCKET-SPREAD] bucket=%s base=%.1fc multiplier=%.1f adjusted=%.1fc
[VOLATILITY-SPREAD] base=%.1fc current_vol=%.3f hist_vol=%.3f ratio=%.2f adjustment=%.2f adjusted=%.1fc
[OFI] yes_bid=%d yes_ask=%d no_bid=%d no_ask=%d total_bid=%d total_ask=%d OFI=%.2f
[ADVERSE-SELECTION] OFI=%.2f price_move=%.1fc volume_ratio=%.1f risk_score=%.2f high_risk=%s
```

**Record for each asset:**
- [ ] BTC: Optimal spread? Reservation price? Time bucket? OFI? Pass? Reason?
- [ ] ETH: Optimal spread? Reservation price? Time bucket? OFI? Pass? Reason?
- [ ] SOL: Optimal spread? Reservation price? Time bucket? OFI? Pass? Reason?
- [ ] XRP: Optimal spread? Reservation price? Time bucket? OFI? Pass? Reason?
- [ ] DOGE: Optimal spread? Reservation price? Time bucket? OFI? Pass? Reason?

**Key questions:**
- Is the dynamic spread model being used (not profile fallback)?
- Are spreads adjusting based on time bucket (wider near expiry)?
- Are spreads adjusting based on volatility (wider in high volatility)?
- Are spreads adjusting based on order flow imbalance (wider with strong imbalance)?
- Are maker orders getting wider spreads than taker orders?
- Are rejections due to dynamic spread or other reasons?

### 9. Final Reject Reason Layer
**Watch for log patterns:**
```
[PIPELINE-TRACE] ticker=%s side=%s canonical_edge_yes=%.4f canonical_edge_no=%.4f decision=BLOCK_REASON=%s
[EDGE THRESHOLD BLOCK] ticker=%s edge_yes=%.4f edge_no=%.4f min_edge=%.4f
[MICROSTRUCTURE-GATE] ticker=%s side=%s reason=%s
```

**Record for each asset:**
- [ ] BTC: Final decision? Reject reason? Edge values?
- [ ] ETH: Final decision? Reject reason? Edge values?
- [ ] SOL: Final decision? Reject reason? Edge values?
- [ ] XRP: Final decision? Reject reason? Edge values?
- [ ] DOGE: Final decision? Reject reason? Edge values?

**Key questions:**
- Which layer is the final blocker?
- Are edge thresholds too strict?
- Are microstructure gates too restrictive?

## Post-Tick Analysis

### 10. Dynamic Spread Model Validation
**Record dynamic spread parameters:**
- [ ] BTC: Optimal spread? Reservation price? Inventory adjustment? Volatility adjustment? Time adjustment? Liquidity adjustment?
- [ ] ETH: Optimal spread? Reservation price? Inventory adjustment? Volatility adjustment? Time adjustment? Liquidity adjustment?
- [ ] SOL: Optimal spread? Reservation price? Inventory adjustment? Volatility adjustment? Time adjustment? Liquidity adjustment?
- [ ] XRP: Optimal spread? Reservation price? Inventory adjustment? Volatility adjustment? Time adjustment? Liquidity adjustment?
- [ ] DOGE: Optimal spread? Reservation price? Inventory adjustment? Volatility adjustment? Time adjustment? Liquidity adjustment?

**Key questions:**
- Is the Avellaneda-Stoikov model producing reasonable spreads?
- Are inventory adjustments working correctly (long inventory lowers reservation price)?
- Are volatility adjustments working correctly (high volatility widens spread)?
- Are time adjustments working correctly (wider spread near expiry)?
- Are liquidity adjustments working correctly (low liquidity widens spread)?

### 11. Spread Distribution Collection
**Record actual spread values:**
- [ ] BTC: Best bid? Best ask? Spread? Time bucket? Dynamic spread? Difference?
- [ ] ETH: Best bid? Best ask? Spread? Time bucket? Dynamic spread? Difference?
- [ ] SOL: Best bid? Best ask? Spread? Time bucket? Dynamic spread? Difference?
- [ ] XRP: Best bid? Best ask? Spread? Time bucket? Dynamic spread? Difference?
- [ ] DOGE: Best bid? Best ask? Spread? Time bucket? Dynamic spread? Difference?

**Key questions:**
- What are the actual spread distributions per asset?
- How do they vary by time bucket (0-3min, 3-6min, 6-10min, 10-13min, 13-15min)?
- Are the dynamic spreads aligned with the actual distributions?
- Is the dynamic spread model over- or under-estimating actual spreads?

### 12. False Reject Analysis
**Record false rejects:**
- [ ] BTC: Rejected but had valid edge? Spread? Dynamic spread? Time bucket? Volatility? OFI?
- [ ] ETH: Rejected but had valid edge? Spread? Dynamic spread? Time bucket? Volatility? OFI?
- [ ] SOL: Rejected but had valid edge? Spread? Dynamic spread? Time bucket? Volatility? OFI?
- [ ] XRP: Rejected but had valid edge? Spread? Dynamic spread? Time bucket? Volatility? OFI?
- [ ] DOGE: Rejected but had valid edge? Spread? Dynamic spread? Time bucket? Volatility? OFI?

**Key questions:**
- What percentage of rejections are false rejects?
- Are false rejects concentrated in specific assets or time buckets?
- Are false rejects due to dynamic spread model over-estimating spreads?
- Would adjusting dynamic spread parameters reduce false rejects without increasing risk?

### 13. Maker vs Taker Analysis
**Record maker/taker breakdown:**
- [ ] BTC: Maker rejections? Taker rejections? Maker acceptance rate? Maker spread vs. taker spread ratio?
- [ ] ETH: Maker rejections? Taker rejections? Maker acceptance rate? Maker spread vs. taker spread ratio?
- [ ] SOL: Maker rejections? Taker rejections? Maker acceptance rate? Maker spread vs. taker spread ratio?
- [ ] XRP: Maker rejections? Taker rejections? Maker acceptance rate? Maker spread vs. taker spread ratio?
- [ ] DOGE: Maker rejections? Taker rejections? Maker acceptance rate? Maker spread vs. taker spread ratio?

**Key questions:**
- Are maker-intended orders being rejected more than taker-intended?
- Is the dynamic spread model correctly handling maker vs. taker orders?
- Are maker spreads wider than taker spreads (as expected)?
- Is the spread gate maker-aware or taker-biased?

## Decision Matrix

### 14. Determine Root Cause
Based on the collected data, determine the root cause:

**If the issue is dynamic spread model adjustment:**
- [ ] Spread distributions show dynamic spreads are misaligned with actual spreads
- [ ] False reject rate is high (>5%) due to dynamic spread model over-estimating spreads
- [ ] False rejects are concentrated in specific time buckets or volatility conditions
- [ ] Adjusting dynamic spread parameters would reduce false rejects without increasing risk

**If the issue is thesis-band adjustment:**
- [ ] Valid NO theses are being rejected by 25c-99c range
- [ ] YES theses are being rejected by 10c-75c range
- [ ] The range bounds are not aligned with current market conditions
- [ ] Adjusting bounds would not increase risk

**If the issue is maker vs. taker policy mismatch:**
- [ ] Maker-intended orders are being treated as taker
- [ ] Maker spreads are not wider than taker spreads (as expected)
- [ ] The dynamic spread model is not correctly handling maker vs. taker orders
- [ ] Policy alignment would not increase risk

**If the issue is time-bucket adjustment:**
- [ ] Spreads are not adjusting correctly based on time-to-expiry
- [ ] Time bucket multipliers are not aligned with actual volatility patterns
- [ ] Late window spreads are not wide enough (or too wide)
- [ ] Adjusting time bucket parameters would improve alignment

**If the issue is volatility adjustment:**
- [ ] Spreads are not adjusting correctly based on volatility
- [ ] High volatility conditions are not widening spreads enough
- [ ] Low volatility conditions are not tightening spreads enough
- [ ] Adjusting volatility parameters would improve alignment

**If the issue is order flow imbalance adjustment:**
- [ ] Spreads are not adjusting correctly based on order flow imbalance
- [ ] Strong imbalance conditions are not widening spreads enough (adverse selection protection)
- [ ] Weak imbalance conditions are not tightening spreads enough
- [ ] Adjusting OFI parameters would improve alignment

### 15. Recommend Action
Based on the root cause, recommend the appropriate action:

**If dynamic spread model adjustment:**
- [ ] Adjust Avellaneda-Stoikov parameters (risk aversion, volatility, order book liquidity)
- [ ] Update maker vs. taker spread compensation
- [ ] Adjust time bucket multipliers
- [ ] Adjust volatility adjustment factors
- [ ] Adjust order flow imbalance adjustment factors
- [ ] Update `dynamic_spread_model.py` parameters

**If thesis-band adjustment:**
- [ ] Adjust YES range bounds (currently 10c-75c)
- [ ] Adjust NO range bounds (currently 25c-99c)
- [ ] Consider asset-specific thesis bands
- [ ] Update `agent_grid_15m.py` price range checks

**If maker vs. taker policy mismatch:**
- [ ] Align maker/taker policies across all gates
- [ ] Ensure dynamic spread model correctly handles maker vs. taker orders
- [ ] Consider unified policy framework
- [ ] Update relevant gate implementations

**If time-bucket adjustment:**
- [ ] Adjust time bucket multipliers based on volatility patterns
- [ ] Consider more granular time buckets
- [ ] Update `calculate_time_bucket_spread()` in `dynamic_spread_model.py`

**If volatility adjustment:**
- [ ] Adjust volatility adjustment factors
- [ ] Consider different volatility windows
- [ ] Update `calculate_volatility_adjusted_spread()` in `dynamic_spread_model.py`

**If order flow imbalance adjustment:**
- [ ] Adjust OFI adjustment factors
- [ ] Consider more sophisticated OFI models
- [ ] Update `calculate_order_flow_imbalance()` in `dynamic_spread_model.py`

## Validation Checklist

### 16. Post-Fix Validation
After implementing the recommended action:
- [ ] Re-run live tick monitoring
- [ ] Verify spread distributions are now aligned with dynamic spreads
- [ ] Verify false reject rate is below target (5%)
- [ ] Verify NO theses at 78-86c are accepted
- [ ] Verify maker-intended orders are not over-rejected
- [ ] Verify maker spreads are wider than taker spreads
- [ ] Verify spreads adjust correctly based on time bucket
- [ ] Verify spreads adjust correctly based on volatility
- [ ] Verify spreads adjust correctly based on order flow imbalance
- [ ] Run regression tests to ensure no regressions

### 17. Monitoring Plan
- [ ] Set up continuous monitoring of spread distributions
- [ ] Set up alerts for high false reject rates
- [ ] Set up alerts for degenerate book detection
- [ ] Set up alerts for catalog cross-validation mismatches
- [ ] Set up alerts for dynamic spread model parameter drift
- [ ] Set up alerts for maker vs. taker spread ratio anomalies
- [ ] Set up alerts for time bucket spread adjustment anomalies
- [ ] Set up alerts for volatility adjustment anomalies
- [ ] Set up alerts for order flow imbalance adjustment anomalies
- [ ] Schedule weekly dynamic spread model calibration reviews

## Expected Outcomes

### If fixes are working correctly:
- [ ] No degenerate books detected (or detected and refreshed)
- [ ] Dynamic spread model is used (not profile fallback)
- [ ] NO theses at 78-86c are accepted
- [ ] Spread distributions are aligned with dynamic spreads
- [ ] False reject rate is below 5%
- [ ] Maker spreads are wider than taker spreads (approximately 1.5-2.0x)
- [ ] Spreads adjust correctly based on time bucket (wider near expiry)
- [ ] Spreads adjust correctly based on volatility (wider in high volatility)
- [ ] Spreads adjust correctly based on order flow imbalance (wider with strong imbalance)

### If further adjustment is needed:
- [ ] Spread distributions show dynamic spreads are misaligned with actual spreads
- [ ] False reject rate is still high
- [ ] Valid opportunities are still being missed
- [ ] Maker vs. taker spread ratio is not as expected
- [ ] Time bucket adjustments are not aligned with volatility patterns
- [ ] Volatility adjustments are not aligned with market conditions
- [ ] Order flow imbalance adjustments are not providing adequate adverse selection protection
- [ ] Recalibration is needed based on actual data

## Notes

- This checklist should be run for at least 10-20 live ticks to collect sufficient data
- Data should be collected across different time buckets and market conditions
- False reject rate should be calculated as: (false rejects / total rejections) * 100
- A false reject is a rejection where the candidate had valid edge and would have been profitable

## References

- `END_TO_END_FIX_SUMMARY_2026_08_03.md`: Comprehensive fix summary
- `SPREAD_CAP_VALIDATION_PLAN.md`: Spread cap calibration methodology
- `SPREAD_CAP_ADJUSTMENT_2026_08_02.md`: Original cap adjustment documentation
- `test_book_validity_2026_08_03.py`: Book validity test suite
- `test_cap_wiring_2026_08_03.py`: Cap wiring test suite
- `test_thesis_band_alignment_2026_08_03.py`: Thesis band alignment test suite
