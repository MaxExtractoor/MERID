# Edge Threshold Single Source of Truth

## Overview

This document establishes the single source of truth for minimum edge thresholds in the MERID 15m Kalshi crypto trading system. All edge threshold references across the codebase must align with this standard.

## Industry Research Summary

Based on 2026 industry research from Market Math and Beatpoly:

- **Kalshi 7% winner fee** turns edges below 2% into breakeven or negative EV
- **Industry standard minimum**: 3% raw edge for Kalshi prediction markets
- **Practical minimum**: +2¢ to +3¢ per contract after fees
- **Reference**: https://marketmath.io/blog/prediction-market-strategy

The 7% winner fee on Kalshi means a 2% edge is effectively ~0.5% after fees, which is noise rather than signal.

## Single Source of Truth

**File**: `config/profiles/kalshi_crypto_15m_v2.yaml`
**Section**: `edge_bands`
**Minimum Edge**: 2.5% (0.025) unified across all assets (BTC, ETH, SOL, XRP, DOGE)

### Edge Band Structure

```
edge_bands:
  enabled: true
  watch_band:
    min_edge_pct: 0.025  # 2.5% - log only
    max_edge_pct: 0.025
    action: "log_only"
    kelly_multiplier: 0.0
  small_band:
    min_edge_pct: 0.025  # 2.5% - trade with reduced size
    max_edge_pct: 0.05   # 5% - better band separation
    action: "trade_small"
    kelly_multiplier: 0.25
  standard_band:
    min_edge_pct: 0.025  # 2.5% - trade with standard size
    max_edge_pct: 1.0    # No upper limit
    action: "trade_standard"
    kelly_multiplier: 0.50
```

## Hierarchy (from highest to lowest priority)

1. **edge_bands.*.min_edge_pct** - PRIMARY: Used for trade execution (2.5% minimum)
2. strategy_policy.min_edge - LEGACY: Not actively used, kept for compatibility
3. strategies.*.policy.min_edge - Strategy-specific: Used by individual strategies
4. Per-asset min_edge_early/mid/late/terminal - **IGNORED**: Legacy fields, not used

## Code Implementation References

All code references must use the unified 2.5% threshold:

### Files Updated (2026-07-14)

1. **config/profiles/kalshi_crypto_15m_v2.yaml**
   - Raised edge_bands from 0.5% to 2.5%
   - Removed conflicting per-asset min_edge_early/mid/late/terminal fields

2. **merid/risk/profiles/global_allocator.py**
   - Updated per_asset_min_edge_pct from 0.005 to 0.025
   - Updated min_edge_pct from 0.005 to 0.025

3. **merid/event_venues/kalshi/risk_parameters.py**
   - Updated EDGE_BANDS_MINIMUM from 0.005 to 0.025

4. **merid/loop_15m.py**
   - Updated min_edge_threshold from 0.005 to 0.025

5. **merid/risk/profiles/window_allocator.py**
   - Updated edge threshold check from 0.005 to 0.025

6. **merid/prediction/risk/_prediction_risk.py**
   - Updated post_fee_edge threshold from 0.005 to 0.025

7. **merid/swarm/orchestrator.py**
   - Updated MIN_EDGE_BPS from 10.0 to 250.0 (2.5%)

### Deprecated Files

1. **config/profiles/kalshi_crypto_15m_strategy.yaml**
   - Marked as DEPRECATED for kalshi_crypto_15m_v2 profile
   - edge_thresholds section is IGNORED by production 15m stack
   - Retained for backward compatibility with other profiles only

## Validation

All edge threshold validations must use the centralized function:

```python
from merid.event_venues.kalshi.risk_parameters import validate_edge

is_valid, reason = validate_edge(edge_pct, asset, confidence)
```

This function enforces the unified 2.5% threshold across all assets.

## Test Coverage

Updated test files to reflect 2.5% threshold:

- `tests/test_edge_stack_fixes_2026_07_12.py`
- `tests/test_kalshi_crypto_15m_risk_envelope.py`
- `tests/test_2026_stack_optimizations.py`

All tests pass with the new threshold.

## Migration Notes

### Before (2026-07-13)
- Unified threshold: 0.5% (0.005)
- Per-asset thresholds: 1.25%-3.5% (ignored)
- Multiple conflicting sources

### After (2026-07-14)
- Unified threshold: 2.5% (0.025) - industry standard
- Per-asset thresholds: Removed (single source of truth)
- All code paths aligned with edge_bands

## Compliance Checklist

When modifying edge thresholds:

- [ ] Update `config/profiles/kalshi_crypto_15m_v2.yaml` edge_bands section
- [ ] Update `merid/event_venues/kalshi/risk_parameters.py` EDGE_BANDS_MINIMUM
- [ ] Update `merid/risk/profiles/global_allocator.py` per_asset_min_edge_pct
- [ ] Update `merid/loop_15m.py` min_edge_threshold
- [ ] Update `merid/risk/profiles/window_allocator.py` edge check
- [ ] Update `merid/prediction/risk/_prediction_risk.py` post_fee_edge threshold
- [ ] Update `merid/swarm/orchestrator.py` MIN_EDGE_BPS
- [ ] Update relevant test files
- [ ] Run tests to verify consistency
- [ ] Update this document

## References

- Market Math: https://marketmath.io/blog/prediction-market-strategy
- Beatpoly: https://beatpoly.com/learn/expected-value.html
- Kalshi Trading Strategies: https://www.botforkalshi.com/blog/kalshi-trading-strategies-guide

## Version History

- **2026-07-14**: Raised threshold from 0.5% to 2.5% based on industry research
- **2026-07-13**: Unified to 0.5% across all assets (below industry standard)
- **2026-07-07**: Initial edge_bands implementation with 0.5% threshold
