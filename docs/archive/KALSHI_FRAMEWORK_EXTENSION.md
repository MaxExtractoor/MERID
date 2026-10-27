# Kalshi Audit Framework Extension Plan

This document outlines how to extend the Kalshi audit framework to other categories and future short-tenor products.

## Current Scope

The current audit framework is optimized for:
- **Category:** Crypto
- **Frequency:** 15-minute (fifteen_min)
- **Assets:** BTC, ETH, SOL, XRP, DOGE
- **Contract Type:** Binary YES/NO based on price direction

## Extension Strategy

### Phase 1: Same Category, Different Frequencies

**Target:** Hourly, Daily, Weekly crypto markets

**Required Changes:**

1. **Manifest Generation**
   - Update `scripts/audit_kalshi_yes_no_manifest.py` to support multiple frequencies
   - Add frequency parameter: `--frequency {fifteen_min|hourly|daily|weekly}`
   - Update series ticker resolution in `merid/event_venues/kalshi/market_selector.py`

2. **Entry Window Configuration**
   - Add frequency-specific environment variables:
     - `MERID_PM_ENTRY_WINDOW_HOURLY_MINUTES`
     - `MERID_PM_ENTRY_WINDOW_DAILY_MINUTES`
     - `MERID_PM_ENTRY_WINDOW_WEEKLY_MINUTES`
   - Update `EntryWindowConfig` in `merid/prediction/agent_grid_config.py`

3. **Validation Scripts**
   - No changes needed - scripts are frequency-agnostic
   - Ensure logs include frequency metadata for filtering

**Implementation Effort:** Low (1-2 days)

---

### Phase 2: Different Categories (Same Binary Structure)

**Target:** Politics, Economics, Sports, Weather

**Required Changes:**

1. **Manifest Generation**
   - Category-specific YES/NO semantics (not all are price-direction based)
   - Example: Politics = "Candidate X wins" (not "price goes up")
   - Add category parameter to manifest script
   - Category-specific condition parsing logic

2. **Order Construction Validation**
   - Update `infer_economic_intent()` to handle non-price rationales
   - Add category-specific validation rules
   - Example: Sports = "Team A wins" vs "Team B wins"

3. **Settlement Validation**
   - Binary structure remains the same (YES/NO)
   - No changes needed for core validation logic

4. **Entry Windows**
   - Different timeframes require different window defaults
   - Politics (longer duration): 1-7 day windows
   - Sports (event-based): Pre-game windows

**Implementation Effort:** Medium (3-5 days)

---

### Phase 3: Scalar/Range Markets

**Target:** Markets with scalar outcomes (e.g., "BTC will be above $100k")

**Required Changes:**

1. **Manifest Structure**
   - Add `condition_type` field: `binary` vs `scalar` vs `range`
   - Scalar markets: YES/NO + strike price + direction
   - Example: "BTC > 100000" → YES if above, NO if below

2. **Order Construction Validation**
   - Validate strike price matches ticker encoding
   - Check direction logic (above/below/at)

3. **Settlement Validation**
   - P&L calculation differs for scalar markets
   - Need to validate payout formula

4. **Analytics**
   - Edge calibration needs bucketing by strike distance
   - Per-agent metrics need scalar-specific logic

**Implementation Effort:** High (1-2 weeks)

---

### Phase 4: Multi-Outcome Markets

**Target:** Markets with >2 outcomes (e.g., "BTC will be: <$90k, $90k-$100k, >$100k")

**Required Changes:**

1. **Manifest Structure**
   - Add `outcome_count` field
   - List all possible outcomes with conditions
   - Map internal side to specific outcome

2. **Order Construction Validation**
   - Validate outcome_id mapping
   - Check economic exposure per outcome

3. **Settlement Validation**
   - Validate winning outcome matches internal classification
   - Check P&L per outcome

4. **Analytics**
   - Win rate per outcome
   - Edge calibration per outcome
   - Side-specific performance becomes outcome-specific

**Implementation Effort:** Very High (2-3 weeks)

---

## Configuration Approach

### Category Configuration File

Create `config/kalshi_category_config.yaml`:

```yaml
categories:
  crypto:
    frequencies:
      fifteen_min:
        series_tickers: [KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M]
        entry_window_minutes: 10
        cutoff_minutes: 2
        condition_type: binary_price_direction
      hourly:
        series_tickers: [KXBTC, KXETH, KXSOL, KXXRP, KXDOGE]
        entry_window_minutes: 60
        cutoff_minutes: 10
        condition_type: binary_price_direction
      daily:
        series_tickers: [KXBTC-D, KXETH-D, KXSOL-D, KXXRP-D, KXDOGE-D]
        entry_window_minutes: 1440
        cutoff_minutes: 240
        condition_type: binary_price_direction

  politics:
    frequencies:
      daily:
        entry_window_minutes: 4320
        cutoff_minutes: 1440
        condition_type: binary_event_outcome

  sports:
    frequencies:
      event_based:
        entry_window_minutes: 120
        cutoff_minutes: 30
        condition_type: binary_event_outcome
```

### Dynamic Manifest Generation

Update manifest script to use config:

```python
# scripts/audit_kalshi_yes_no_manifest.py
def build_manifest_for_category(category: str, frequency: str):
    config = load_category_config()
    category_config = config['categories'][category]['frequencies'][frequency]
    
    series_tickers = category_config['series_tickers']
    condition_type = category_config['condition_type']
    
    # Generate manifest based on condition_type
    if condition_type == 'binary_price_direction':
        # Current logic
        pass
    elif condition_type == 'binary_event_outcome':
        # Event-specific parsing
        pass
```

---

## Migration Path

### Step 1: Abstract Current Logic

Refactor existing scripts to be category-agnostic:
- Extract category-specific logic into strategy pattern
- Define `CategoryStrategy` interface with methods:
  - `parse_yes_condition()`
  - `infer_economic_intent()`
  - `validate_order_construction()`

### Step 2: Implement Crypto Strategy

Move current crypto-specific logic into `CryptoCategoryStrategy`.

### Step 3: Add New Strategies

Implement `PoliticsCategoryStrategy`, `SportsCategoryStrategy`, etc.

### Step 4: Update Config

Add category selection to all scripts:
- `--category crypto`
- `--category politics`
- `--category sports`

---

## Backward Compatibility

Maintain backward compatibility by:
- Default to `--category crypto` if not specified
- Keep existing environment variable names for crypto
- Add new category-specific env vars as needed

---

## Testing Strategy

### Unit Tests
- Test each CategoryStrategy independently
- Mock API responses for different categories

### Integration Tests
- Test manifest generation for each category
- Test validation scripts with synthetic data

### Regression Tests
- Ensure crypto functionality unchanged after refactoring
- Run existing crypto validation suite

---

## Timeline Estimate

| Phase | Description | Effort | Priority |
|-------|-------------|--------|----------|
| Phase 1 | Crypto hourly/daily/weekly | 1-2 days | High |
| Phase 2 | Politics/Economics/Sports | 3-5 days | Medium |
| Phase 3 | Scalar markets | 1-2 weeks | Low |
| Phase 4 | Multi-outcome markets | 2-3 weeks | Low |

---

## Success Criteria

- Crypto hourly/daily/weekly markets auditable with same tooling
- Politics/Economics/Sports markets auditable with category-specific logic
- Validation scripts work across all categories
- Weekly reports include multi-category analysis
- Zero regression in existing crypto functionality
