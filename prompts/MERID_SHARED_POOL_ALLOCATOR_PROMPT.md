# MERID Shared $1 Pool Allocator Prompt

**Version:** 1.0  
**Date:** 2026-07-09  
**Status:** ACTIVE - MANDATORY FOR ALL KALSHI 15M CRYPTO TRADING

---

## Core Identity

You are controlling a 15-minute Kalshi crypto trading system with a **shared $1 pool allocation model**.

**CRITICAL RULE: The $1 venue cap is a SHARED POOL across all assets, not a per-asset budget.**

---

## Trading Universe

- **Assets:** BTC, ETH, SOL, XRP, DOGE (5 assets total)
- **Timeframe:** 15-minute contracts only, one strip per asset per window
- **Markets:** Kalshi 15-minute crypto futures (KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M)

---

## Trading Rules (MUST BE ENFORCED IN CODE AND CONFIG)

### 1. Contract Limits
- **At most 1 contract per asset** in a given 15-minute window
- **Never place more than one contract per asset**, regardless of edge
- **At most one resting limit order per asset per window**

### 2. Price Range
- **Entry price per contract must be between 10c and 50c inclusive**
- **Never place orders outside this range**
- **Never default to 50c as a "max price" placeholder**

### 3. Global Risk Cap (SHARED POOL MODEL)
- **The global risk cap is $1.00 total across all assets per window**
- **This is a shared pool - assets compete for capital**
- **Do NOT give each asset its own $1 budget**
- **Total exposure across all 5 assets must be ≤ $1.00**

### 4. Quality Thresholds
- **Confidence must be ≥ 65%** for any order to be considered
- **Edge must be ≥ 0.05%** for any order to be considered
- **Spread must be ≤ 20c** (coarse filter)

---

## Allocation Behavior (GLOBAL ALLOCATOR)

### Candidate Generation
For each asset, compute a candidate with:
- edge, confidence, price
- Only consider assets with confidence ≥ 65% and edge ≥ 0.05%
- Only consider prices in [10c, 50c]

### Selection Algorithm
1. **Sort candidates by descending edge** (or EV)
2. **Starting from the top:**
   - If adding this asset's contract keeps total risk ≤ $1, include it
   - Otherwise, skip it, even if the edge is high
3. **Stop when you cannot add any more assets without exceeding $1**

### Example Scenarios

**Scenario 1: 5 assets at 20c each**
- All 5 selected, total risk = $1.00, 5 contracts
- This is the ideal case (full utilization of shared pool)

**Scenario 2: Mixed prices [50c, 30c, 30c, 25c, 20c]**
- Sorted by edge, watch which subset is selected
- Possible selections: 50c+30c+20c=100c (3 assets) or 30c+30c+25c+20c=105c (too much)
- Total risk never exceeds $1.00

**Scenario 3: 3 assets at 40c each**
- Either top two (80c total) or one (40c)
- Never 3 (120c would exceed $1.00)

---

## Invariants You Must Preserve and Test

### Critical Invariants
1. **Sum of prices of all traded contracts in a window ≤ 100c** ($1.00)
2. **No asset has more than 1 contract per window**
3. **All entry prices are in [10c, 50c] range**
4. **The system must track global risk used so far in the window**, not an independent cap per agent
5. **If all five assets trade, the prices must sum to ≤ 100c**

### Forbidden Patterns
- **NEVER rescale per-asset caps equally to fit the venue cap**
- **NEVER treat the $1 cap as "per-asset"**
- **NEVER default to 50c as a placeholder price**
- **NEVER place multiple contracts for the same asset in a single window**

---

## Code Requirements

### Risk Envelope
- **Remove any code that rescales per-asset caps equally to fit the venue cap**
- **Replace it with a global allocator as described above**
- **Set max_single_asset_fraction to 1.0** (allows single asset to use full venue cap)

### Global Allocator
- **Implement the sort-then-accumulate pattern until total price ≤ 100c**
- **Filter by confidence ≥ 65% and edge ≥ 0.05%**
- **Filter by price range [10c, 50c]**
- **Enforce 1 contract per asset per window**

### Order Builder
- **Make sure contract_size = 1 always for this profile**
- **Entry price is derived from candidate price, clamped to [10-50c], not from a max-price constant**
- **No loop that spawns multiple orders per asset in a single window**

### Window Audit
- **Add a "15-minute window audit" function that verifies:**
  - contracts_per_asset ≤ 1
  - total_risk ≤ $1.00
  - all entry prices ∈ [10c, 50c]
- **Log something like:**
  - `[15M-WINDOW-AUDIT] assets_traded=3, prices=[0.22, 0.18, 0.25], total_risk=0.65, ok=True`

---

## Tests You Must Add

### Unit Tests for Global Allocator
1. **Scenario: 5 assets at 20c each**
   - Expect: all 5 selected, total risk = $1.00, 5 contracts
2. **Scenario: Mixed prices [50c, 30c, 30c, 25c, 20c]**
   - Sorted by edge, watch which subset is selected
   - Ensure total risk ≤ $1.00 and no per-asset cap rescaling
3. **Scenario: 3 assets at 40c each**
   - Expect: either top two (80c total) or one (40c), but never 3 (120c)

### Integration Tests
- **For each asset, simulate:**
  - Two candidate orders in the same window → verify that only one is sent
  - Verify that risk is kept globally consistent
- **Confirm that at most 5 orders exist per window** (one per asset)
- **Verify their prices sum to ≤ $1**

---

## Configuration Updates

### Profile YAML (kalshi_crypto_15m_v2.yaml)
- **Ensure price_range.min_price_cents = 10**
- **Ensure price_range.max_price_cents = 50**
- **Ensure guardrails.min_contract_price_cents = 10**
- **Ensure guardrails.max_contract_price_cents = 50**
- **Ensure max_single_asset_fraction = 1.0** (or equivalent)

### Allocator Config
- **min_edge_pct = 0.05** (0.05%)
- **min_confidence = 0.65** (65%)
- **min_price_cents = 10**
- **max_price_cents = 50**
- **max_single_asset_fraction = 1.0**

---

## Logging Requirements

### Global Allocator
- **Log: `[GLOBAL-ALLOCATOR] candidates=..., selected=..., total_risk=...`**
- **Assert: `total_risk <= 1.00` every window, and fail loudly if violated**

### Window Audit
- **Log: `[15M-WINDOW-AUDIT] assets_traded=X, prices=[...], total_risk=$Y, ok=True/False`**
- **This becomes your "green/red" indicator** that the allocator and order builder are honoring the regime

---

## Common Mistakes to Avoid

### Mistake 1: Per-Asset Budget Thinking
- **Wrong:** "Each asset has $1, so I can trade 5 assets at $1 each = $5 total"
- **Right:** "All 5 assets share $1 total, so if I trade 5 assets at 20c each = $1 total"

### Mistake 2: 50c Default Price
- **Wrong:** "If I don't have a price, use 50c as the max"
- **Right:** "If I don't have a price, use 25c as the midpoint of 10-50c, or reject the order"

### Mistake 3: Multiple Contracts Per Asset
- **Wrong:** "I can place 2 contracts for BTC if the edge is high"
- **Right:** "I can only place 1 contract for BTC per window, regardless of edge"

### Mistake 4: Per-Asset Cap Rescaling
- **Wrong:** "Total cap is $1, so each asset gets $0.20"
- **Right:** "Total cap is $1, assets compete for it based on edge ranking"

---

## Verification Checklist

Before deploying any changes to the Kalshi 15m crypto trading system, verify:

- [ ] Global allocator uses shared $1 pool model (not per-asset budgets)
- [ ] min_edge_pct = 0.05% (not 2.0% or other high value)
- [ ] min_confidence = 65% (not lower)
- [ ] price range = [10c, 50c] (not defaulting to 50c)
- [ ] max_single_asset_fraction = 1.0 (not 0.20 or other rescaled value)
- [ ] Window audit function exists and logs invariants
- [ ] Unit tests pass for all allocation scenarios
- [ ] No code path sets "max_price_cents = 50" as a preferred price
- [ ] No code path rescales per-asset caps equally
- [ ] All 5 assets (BTC, ETH, SOL, XRP, DOGE) are included

---

## Enforcement

This prompt is **MANDATORY** for:
- All changes to the global allocator
- All changes to the risk envelope
- All changes to order building logic
- All changes to candidate generation
- All changes to window tracking

No change may be merged or deployed without passing through this prompt's verification.

**The shared $1 pool model is the single source of truth for risk allocation in the Kalshi 15m crypto trading system.**
