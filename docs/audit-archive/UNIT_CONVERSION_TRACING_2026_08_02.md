# Unit Conversion Tracing Checklist and Test Matrix
**Date**: 2026-08-02  
**Scope**: BTC, ETH, SOL, XRP, DOGE 15-minute Kalshi markets  
**Purpose**: Catch remaining sign, fraction/percent, or cents/USD mismatches before shadow replay

## Executive Summary

Unit conversion mismatches are a high-leverage bug class that can silently invert edge logic or threshold comparisons. This checklist traces all probability, price, and side conversions through the pipeline to ensure canonical consistency.

---

# UNIT CONVERSION INVENTORY

## 1. Probability Conversions

### 1.1 Signal Generation → Allocator
**Conversion**: Model probability (0-1 fraction) → Edge calculation (cents)

**Checklist**:
- [ ] **BTC**: Verify `p_hat_yes` from model is 0-1 fraction
- [ ] **BTC**: Verify edge calculation uses `p_hat_yes * 100` for cents
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: Model outputs 0-1 fraction, edge calculation converts to cents (0-100)

**Failure Mode**: 0.6 treated as 60c (10x error) or 60c treated as 0.6 (10x error)

### 1.2 Allocator → Gate
**Conversion**: Probability in cents (0-100) → Edge calculation (cents)

**Checklist**:
- [ ] **BTC**: Verify allocator passes `p_hat_yes_cents` (0-100) to gate
- [ ] **BTC**: Verify gate receives cents, not fraction
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: Allocator and gate both use cents (0-100) consistently

**Failure Mode**: Allocator passes fraction, gate expects cents (100x error)

### 1.3 Gate → Router
**Conversion**: Edge in cents → Order price in cents

**Checklist**:
- [ ] **BTC**: Verify edge calculation output is in cents
- [ ] **BTC**: Verify order price uses same cents unit
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: Edge and order price both use cents (0-100) consistently

**Failure Mode**: Edge in cents, order price in dollars (100x error)

---

## 2. Price Conversions

### 2.1 Market Data → Edge Calculation
**Conversion**: Market prices (cents) → Edge calculation (cents)

**Checklist**:
- [ ] **BTC**: Verify `yes_bid_cents`, `no_bid_cents` are in cents (0-100)
- [ ] **BTC**: Verify edge calculation uses cents consistently
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: All market prices in cents (0-100), edge calculation uses cents

**Failure Mode**: Market data in dollars, edge expects cents (100x error)

### 2.2 Edge Calculation → Risk Envelope
**Conversion**: Cents → USD (cents / 100)

**Checklist**:
- [ ] **BTC**: Verify risk envelope uses USD: `cents / 100.0`
- [ ] **BTC**: Verify conversion happens at envelope boundary
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: Risk envelope converts cents to USD explicitly

**Failure Mode**: Cents passed as USD (100x error) or USD passed as cents (0.01x error)

### 2.3 Order Submission → Venue
**Conversion**: Internal cents → Kalshi API format

**Checklist**:
- [ ] **BTC**: Verify Kalshi API receives prices in cents
- [ ] **BTC**: Verify no double conversion (cents → dollars → cents)
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: Kalshi API receives cents directly, no conversion

**Failure Mode**: Double conversion causes 100x or 0.01x errors

---

## 3. Side Conversions

### 3.1 Kalshi Format → Canonical Format
**Conversion**: Kalshi sides (BUY_YES, SELL_YES, BUY_NO, SELL_NO) → Canonical (yes, no)

**Checklist**:
- [ ] **BTC**: Verify `parse_kalshi_side()` converts correctly
- [ ] **BTC**: Verify BUY_YES → yes, SELL_YES → yes
- [ ] **BTC**: Verify BUY_NO → no, SELL_NO → no
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: All Kalshi sides convert to canonical yes/no correctly

**Failure Mode**: Side conversion error inverts trade direction

### 3.2 Canonical Format → Order Intent
**Conversion**: Canonical (yes, no) → Order intent side

**Checklist**:
- [ ] **BTC**: Verify order intent uses canonical yes/no
- [ ] **BTC**: Verify no side flip between gate and router
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: Canonical side preserved from gate to order submission

**Failure Mode**: Side flip causes YES order to execute as NO

### 3.3 Order Intent → Execution
**Conversion**: Order intent side → Execution side

**Checklist**:
- [ ] **BTC**: Verify execution side matches order intent
- [ ] **BTC**: Verify no side flip in order submission
- [ ] **ETH**: Same verification as BTC
- [ ] **SOL**: Same verification as BTC
- [ ] **XRP**: Same verification as BTC
- [ ] **DOGE**: Same verification as BTC

**Expected**: Execution side matches order intent side

**Failure Mode**: Side flip at execution causes wrong trade direction

---

# UNIT CONVERSION TEST MATRIX

## Test Matrix Overview

| Conversion Type | Test Case | BTC | ETH | SOL | XRP | DOGE |
|-----------------|-----------|-----|-----|-----|-----|------|
| Probability | Model 0-1 → Edge cents | [ ] | [ ] | [ ] | [ ] | [ ] |
| Probability | Allocator cents → Gate cents | [ ] | [ ] | [ ] | [ ] | [ ] |
| Probability | Gate cents → Router cents | [ ] | [ ] | [ ] | [ ] | [ ] |
| Price | Market cents → Edge cents | [ ] | [ ] | [ ] | [ ] | [ ] |
| Price | Edge cents → Risk USD | [ ] | [ ] | [ ] | [ ] | [ ] |
| Price | Order cents → API cents | [ ] | [ ] | [ ] | [ ] | [ ] |
| Side | Kalshi → Canonical | [ ] | [ ] | [ ] | [ ] | [ ] |
| Side | Canonical → Intent | [ ] | [ ] | [ ] | [ ] | [ ] |
| Side | Intent → Execution | [ ] | [ ] | [ ] | [ ] | [ ] |

---

# DETAILED TEST CASES

## Probability Conversion Tests

### Test 1.1: Model Probability to Edge Cents
**Objective**: Verify model probability (0-1) converts correctly to edge cents (0-100)

**Test Code**:
```python
def test_model_probability_to_edge_cents():
    """Test that model probability (0-1) converts to edge cents (0-100)."""
    # Model output: 0.60 (60% probability)
    p_hat_yes_fraction = 0.60
    
    # Expected edge in cents: 60c
    p_hat_yes_cents = p_hat_yes_fraction * 100
    
    assert p_hat_yes_cents == 60.0, f"Expected 60.0c, got {p_hat_yes_cents}c"
    
    # Verify edge calculation uses cents
    market_price_cents = 50
    edge_cents = p_hat_yes_cents - market_price_cents
    assert edge_cents == 10.0, f"Expected 10.0c edge, got {edge_cents}c"
```

**Expected**: 0.6 fraction → 60c → 10c edge (at 50c market price)

**Per-Asset Validation**:
- [ ] **BTC**: Test with typical BTC probability (0.55-0.65)
- [ ] **ETH**: Test with typical ETH probability (0.50-0.60)
- [ ] **SOL**: Test with typical SOL probability (0.70-0.85)
- [ ] **XRP**: Test with typical XRP probability (0.55-0.70)
- [ ] **DOGE**: Test with typical DOGE probability (0.20-0.40)

### Test 1.2: Allocator to Gate Probability Units
**Objective**: Verify allocator and gate both use cents (0-100)

**Test Code**:
```python
def test_allocator_to_gate_probability_units():
    """Test that allocator passes probability in cents to gate."""
    # Allocator output: 60c (60% probability)
    p_hat_yes_cents = 60.0
    
    # Gate should receive cents, not fraction
    # Verify no implicit conversion
    assert isinstance(p_hat_yes_cents, (int, float)), "Probability should be numeric"
    assert 0 <= p_hat_yes_cents <= 100, f"Probability cents should be 0-100, got {p_hat_yes_cents}"
    
    # Verify gate uses cents directly
    market_price_cents = 50
    edge_cents = p_hat_yes_cents - market_price_cents
    assert edge_cents == 10.0, f"Expected 10.0c edge, got {edge_cents}c"
```

**Expected**: Allocator passes 60c, gate receives 60c, edge = 10c

**Per-Asset Validation**:
- [ ] **BTC**: Test with BTC allocator output
- [ ] **ETH**: Test with ETH allocator output
- [ ] **SOL**: Test with SOL allocator output
- [ ] **XRP**: Test with XRP allocator output
- [ ] **DOGE**: Test with DOGE allocator output

---

## Price Conversion Tests

### Test 2.1: Market Data to Edge Calculation
**Objective**: Verify market prices in cents convert correctly to edge calculation

**Test Code**:
```python
def test_market_data_to_edge_calculation():
    """Test that market data in cents converts correctly to edge calculation."""
    # Market data: yes_bid=50c, no_bid=50c
    yes_bid_cents = 50
    no_bid_cents = 50
    
    # Verify units are cents (0-100)
    assert 0 <= yes_bid_cents <= 100, f"YES bid should be 0-100c, got {yes_bid_cents}c"
    assert 0 <= no_bid_cents <= 100, f"NO bid should be 0-100c, got {no_bid_cents}c"
    
    # Edge calculation uses cents
    p_hat_yes_cents = 60.0
    edge_cents = p_hat_yes_cents - yes_bid_cents
    assert edge_cents == 10.0, f"Expected 10.0c edge, got {edge_cents}c"
```

**Expected**: Market data 50c, edge calculation uses 50c, edge = 10c

**Per-Asset Validation**:
- [ ] **BTC**: Test with typical BTC market data (5-10c spreads)
- [ ] **ETH**: Test with typical ETH market data (6-12c spreads)
- [ ] **SOL**: Test with typical SOL market data (15-25c spreads)
- [ ] **XRP**: Test with typical XRP market data (15-25c spreads)
- [ ] **DOGE**: Test with typical DOGE market data (20-35c spreads)

### Test 2.2: Edge Cents to Risk Envelope USD
**Objective**: Verify edge cents convert correctly to risk envelope USD

**Test Code**:
```python
def test_edge_cents_to_risk_envelope_usd():
    """Test that edge cents convert correctly to risk envelope USD."""
    # Edge in cents: 10c
    edge_cents = 10.0
    
    # Convert to USD: cents / 100
    edge_usd = edge_cents / 100.0
    
    assert edge_usd == 0.10, f"Expected $0.10, got ${edge_usd}"
    
    # Verify risk envelope uses USD
    contract_count = 10
    total_exposure_usd = edge_usd * contract_count
    assert total_exposure_usd == 1.0, f"Expected $1.00 exposure, got ${total_exposure_usd}"
```

**Expected**: 10c edge → $0.10 → $1.00 exposure (10 contracts)

**Per-Asset Validation**:
- [ ] **BTC**: Test with BTC edge (5-15c typical)
- [ ] **ETH**: Test with ETH edge (5-15c typical)
- [ ] **SOL**: Test with SOL edge (10-25c typical)
- [ ] **XRP**: Test with XRP edge (10-25c typical)
- [ ] **DOGE**: Test with DOGE edge (10-30c typical)

---

## Side Conversion Tests

### Test 3.1: Kalshi Side to Canonical Side
**Objective**: Verify Kalshi sides convert correctly to canonical yes/no

**Test Code**:
```python
def test_kalshi_side_to_canonical():
    """Test that Kalshi sides convert correctly to canonical yes/no."""
    from merid.event_venues.kalshi.binary_price_space import parse_kalshi_side
    
    # Test all Kalshi side formats
    test_cases = [
        ("BUY_YES", "yes", "buy"),
        ("SELL_YES", "yes", "sell"),
        ("BUY_NO", "no", "buy"),
        ("SELL_NO", "no", "sell"),
    ]
    
    for kalshi_side, expected_canonical, expected_action in test_cases:
        canonical, action = parse_kalshi_side(kalshi_side)
        assert canonical == expected_canonical, f"Expected {expected_canonical}, got {canonical}"
        assert action == expected_action, f"Expected {expected_action}, got {action}"
```

**Expected**: All Kalshi sides convert to canonical yes/no correctly

**Per-Asset Validation**:
- [ ] **BTC**: Test with BTC order sides
- [ ] **ETH**: Test with ETH order sides
- [ ] **SOL**: Test with SOL order sides
- [ ] **XRP**: Test with XRP order sides
- [ ] **DOGE**: Test with DOGE order sides

### Test 3.2: Canonical Side to Order Intent
**Objective**: Verify canonical side preserved in order intent

**Test Code**:
```python
def test_canonical_side_to_order_intent():
    """Test that canonical side is preserved in order intent."""
    # Gate decision: yes side
    canonical_side = "yes"
    
    # Order intent should preserve side
    order_intent = {
        "side": canonical_side,
        "action": "buy",
        "price_cents": 50,
        "count": 10
    }
    
    assert order_intent["side"] == "yes", f"Expected 'yes', got {order_intent['side']}"
    
    # Verify no side flip
    assert order_intent["side"] != "no", "Side should not flip to no"
```

**Expected**: Canonical yes side preserved in order intent

**Per-Asset Validation**:
- [ ] **BTC**: Test with BTC YES order
- [ ] **ETH**: Test with ETH NO order
- [ ] **SOL**: Test with SOL YES order
- [ ] **XRP**: Test with XRP NO order
- [ ] **DOGE**: Test with DOGE YES order

---

# CANONICAL SIDE BASIS VERIFICATION

## Canonical Side Definition

**Canonical Format**: yes, no (lowercase)  
**Kalshi Format**: BUY_YES, SELL_YES, BUY_NO, SELL_NO (uppercase)  
**Conversion Function**: `parse_kalshi_side()` in `binary_price_space.py`

## Verification Checklist

### Signal Generation
- [ ] **BTC**: Verify signal generation uses canonical yes/no
- [ ] **ETH**: Verify signal generation uses canonical yes/no
- [ ] **SOL**: Verify signal generation uses canonical yes/no
- [ ] **XRP**: Verify signal generation uses canonical yes/no
- [ ] **DOGE**: Verify signal generation uses canonical yes/no

### Allocator
- [ ] **BTC**: Verify allocator uses canonical yes/no
- [ ] **ETH**: Verify allocator uses canonical yes/no
- [ ] **SOL**: Verify allocator uses canonical yes/no
- [ ] **XRP**: Verify allocator uses canonical yes/no
- [ ] **DOGE**: Verify allocator uses canonical yes/no

### Gate
- [ ] **BTC**: Verify gate uses canonical yes/no
- [ ] **ETH**: Verify gate uses canonical yes/no
- [ ] **SOL**: Verify gate uses canonical yes/no
- [ ] **XRP**: Verify gate uses canonical yes/no
- [ ] **DOGE**: Verify gate uses canonical yes/no

### Router
- [ ] **BTC**: Verify router uses canonical yes/no
- [ ] **ETH**: Verify router uses canonical yes/no
- [ ] **SOL**: Verify router uses canonical yes/no
- [ ] **XRP**: Verify router uses canonical yes/no
- [ ] **DOGE**: Verify router uses canonical yes/no

### Execution
- [ ] **BTC**: Verify execution uses canonical yes/no
- [ ] **ETH**: Verify execution uses canonical yes/no
- [ ] **SOL**: Verify execution uses canonical yes/no
- [ ] **XRP**: Verify execution uses canonical yes/no
- [ ] **DOGE**: Verify execution uses canonical yes/no

**Expected**: All pipeline stages use canonical yes/no consistently

**Failure Mode**: Side basis flip at any stage inverts trade direction

---

# INTEGRATION TESTS FOR GATE ORCHESTRATOR

## Test 4.1: Orchestrator Gate Order
**Objective**: Verify orchestrator calls gates in intended order

**Test Code**:
```python
def test_orchestrator_gate_order():
    """Test that orchestrator calls gates in intended order."""
    from merid.event_venues.kalshi.gate_orchestrator import get_gate_orchestrator, GateStage
    
    orchestrator = get_gate_orchestrator()
    
    # Mock candidate data
    candidate_data = {"agent_id": "test_agent", "venue": "kalshi"}
    market_data = {
        "yes_bid_cents": 50,
        "no_bid_cents": 50,
        "yes_ask_cents": 51,
        "no_ask_cents": 49,
        "yes_bid_depth": 100,
        "no_bid_depth": 100,
        "time_to_expiry_seconds": 900
    }
    order_intent = {"side": "yes", "price_cents": 50, "count": 10}
    
    # Evaluate through orchestrator
    decision = orchestrator.evaluate_candidate(
        candidate_data, market_data, order_intent, "BTC", is_15m_market=True
    )
    
    # Verify gate order in trace
    gate_stages = [result.stage for result in decision.gate_trace]
    expected_order = [
        GateStage.LANE_ENFORCEMENT,
        GateStage.VENUE,
        GateStage.MARKET_REGIME,
        GateStage.MICROSTRUCTURE,
        GateStage.ORDER
    ]
    
    assert gate_stages == expected_order, f"Expected {expected_order}, got {gate_stages}"
```

**Expected**: Gates called in order: Lane → Venue → Regime → Microstructure → Order

## Test 4.2: First Reject Reason Preserved
**Objective**: Verify first reject reason is preserved and returned

**Test Code**:
```python
def test_first_reject_reason_preserved():
    """Test that first reject reason is preserved and returned."""
    from merid.event_venues.kalshi.gate_orchestrator import get_gate_orchestrator, GateStage
    
    orchestrator = get_gate_orchestrator()
    
    # Create crossed book data (should fail at microstructure stage)
    candidate_data = {"agent_id": "test_agent", "venue": "kalshi"}
    market_data = {
        "yes_bid_cents": 60,  # Crossed: bid > ask
        "no_bid_cents": 50,
        "yes_ask_cents": 50,
        "no_ask_cents": 49,
        "yes_bid_depth": 100,
        "no_bid_depth": 100,
        "time_to_expiry_seconds": 900
    }
    order_intent = {"side": "yes", "price_cents": 50, "count": 10}
    
    decision = orchestrator.evaluate_candidate(
        candidate_data, market_data, order_intent, "BTC", is_15m_market=True
    )
    
    # Verify first reject is microstructure
    assert not decision.accepted, "Should be rejected"
    assert decision.first_reject_stage == GateStage.MICROSTRUCTURE
    assert decision.first_reject_reason == "crossed_book"
```

**Expected**: First reject reason (crossed_book) preserved in decision

## Test 4.3: Asset-Specific Calibration
**Objective**: Verify BTC/ETH/SOL/XRP/DOGE flow through same path with asset-specific parameters

**Test Code**:
```python
@pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL", "XRP", "DOGE"])
def test_asset_specific_calibration(asset):
    """Test that all assets flow through same path with asset-specific parameters."""
    from merid.event_venues.kalshi.gate_orchestrator import get_gate_orchestrator
    
    orchestrator = get_gate_orchestrator()
    
    candidate_data = {"agent_id": "test_agent", "venue": "kalshi"}
    market_data = {
        "yes_bid_cents": 50,
        "no_bid_cents": 50,
        "yes_ask_cents": 51,
        "no_ask_cents": 49,
        "yes_bid_depth": 100,
        "no_bid_depth": 100,
        "time_to_expiry_seconds": 900
    }
    order_intent = {"side": "yes", "price_cents": 50, "count": 10}
    
    decision = orchestrator.evaluate_candidate(
        candidate_data, market_data, order_intent, asset, is_15m_market=True
    )
    
    # Verify asset ticker in metadata
    assert decision.metadata["asset_ticker"] == asset
    
    # Verify same gate order for all assets
    gate_stages = [result.stage for result in decision.gate_trace]
    assert len(gate_stages) == 5  # All 5 gates
```

**Expected**: All assets use same gate flow with asset-specific parameters

---

# FEE-AWARE GATE DEPRECATION TEST

## Test 5.1: Fee-Aware Gate Raises for 15m Markets
**Objective**: Verify fee-aware gate raises explicit error for 15-minute markets

**Test Code**:
```python
def test_fee_aware_gate_deprecation_15m():
    """Test that fee-aware gate raises error for 15-minute markets."""
    from merid.event_venues.kalshi.order_router import check_fee_aware_edge
    
    edge_pct = 0.10
    contract_price_cents = 50
    
    # Should raise RuntimeError for 15m markets
    with pytest.raises(RuntimeError) as exc_info:
        check_fee_aware_edge(
            edge_pct, contract_price_cents, is_15m_market=True
        )
    
    assert "deprecated" in str(exc_info.value).lower()
    assert "15-minute" in str(exc_info.value).lower()
```

**Expected**: RuntimeError raised with deprecation message for 15m markets

---

# SUCCESS CRITERIA

## Unit Conversion Success Criteria
- [ ] All probability conversions verified (model → allocator → gate → router)
- [ ] All price conversions verified (market → edge → risk → API)
- [ ] All side conversions verified (Kalshi → canonical → intent → execution)
- [ ] Canonical side basis established across all pipeline stages
- [ ] No double conversions or missing conversions found

## Test Success Criteria
- [ ] All unit conversion tests pass for BTC, ETH, SOL, XRP, DOGE
- [ ] Gate orchestrator integration tests pass
- [ ] Fee-aware gate deprecation test passes
- [ ] Asset-specific calibration tests pass
- [ ] First reject reason preservation test passes

---

# NEXT STEPS

1. **Implement unit conversion tests** in test suite
2. **Run unit conversion tests** for all 5 assets
3. **Add unit conversion logging** at conversion boundaries
4. **Proceed to shadow replay** with validated unit conversions

---

# REFERENCES

- Unit conversion checklist: This document
- Gate inventory: `GATE_INVENTORY_PHASE1_ANALYSIS_2026_08_02.md`
- Gate orchestrator: `merid/event_venues/kalshi/gate_orchestrator.py`
- Binary price space: `merid/event_venues/kalshi/binary_price_space.py`
- Order router: `merid/event_venues/kalshi/order_router.py`
