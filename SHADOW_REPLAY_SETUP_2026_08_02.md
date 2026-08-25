# Phase 2: Shadow Replay Setup
**Date**: 2026-08-02  
**Scope**: BTC, ETH, SOL, XRP, DOGE 15-minute Kalshi markets  
**Purpose**: Select representative candidates for shadow replay execution

## Executive Summary

Shadow replay setup involves selecting representative candidates per asset to validate the complete pipeline from signal to execution. This provides end-to-end validation of all fixes and ensures no remaining hidden bugs.

---

# CANDIDATE SELECTION CRITERIA

## Selection Requirements

### Time Window
- **Recent candidates**: Within last 24-48 hours
- **Representative market conditions**: Normal volatility, not extreme events
- **Clear outcomes**: Well-defined accept/reject results

### Asset Coverage
- **BTC**: 1 accepted + 1 rejected candidate
- **ETH**: 1 accepted + 1 rejected candidate  
- **SOL**: 1 accepted + 1 rejected candidate
- **XRP**: 1 accepted + 1 rejected candidate
- **DOGE**: 1 accepted + 1 rejected candidate

### Candidate Types
- **Accepted candidates**: Valid trades that should execute successfully
- **Rejected candidates**: Trades that should fail with clear rejection reasons
- **Edge cases**: Boundary conditions (threshold edges, time-to-expiry transitions)

---

# CANDIDATE DATA STRUCTURE

## Required Fields for Shadow Replay

```python
@dataclass
class ShadowReplayCandidate:
    """Candidate data for shadow replay execution."""
    
    # Identification
    candidate_id: str
    tick_id: str
    asset_ticker: str
    timestamp: datetime
    
    # Signal Data
    p_hat_yes_fraction: float  # Model probability (0-1)
    p_hat_yes_cents: float     # Model probability in cents (0-100)
    signal_side: str           # "yes" or "no"
    
    # Market Data
    yes_bid_cents: int
    yes_ask_cents: int
    no_bid_cents: int
    no_ask_cents: int
    yes_bid_depth: int
    no_bid_depth: int
    time_to_expiry_seconds: int
    
    # Order Intent
    order_side: str            # "yes" or "no"
    order_action: str          # "buy" or "sell"
    order_price_cents: int
    order_count: int
    
    # Policy
    use_maker_economics: bool
    aggressiveness: float
    
    # Expected Outcome
    expected_decision: str      # "accept" or "reject"
    expected_reject_reason: Optional[str] = None
    
    # Metadata
    market_regime: str
    volatility_level: str
    liquidity_level: str
```

---

# MOCK CANDIDATE DATA (For Testing)

## BTC Candidates

### BTC Accepted Candidate
```python
btc_accepted = ShadowReplayCandidate(
    candidate_id="btc_accepted_001",
    tick_id="tick_20260802_001",
    asset_ticker="BTC",
    timestamp=datetime(2026, 8, 2, 10, 0, 0),
    
    # Signal Data
    p_hat_yes_fraction=0.58,
    p_hat_yes_cents=58.0,
    signal_side="yes",
    
    # Market Data
    yes_bid_cents=52,
    yes_ask_cents=53,
    no_bid_cents=47,
    no_ask_cents=48,
    yes_bid_depth=150,
    no_bid_depth=120,
    time_to_expiry_seconds=600,  # 10 minutes remaining
    
    # Order Intent
    order_side="yes",
    order_action="buy",
    order_price_cents=52,
    order_count=10,
    
    # Policy
    use_maker_economics=True,
    aggressiveness=0.3,
    
    # Expected Outcome
    expected_decision="accept",
    
    # Metadata
    market_regime="normal",
    volatility_level="low",
    liquidity_level="high"
)
```

### BTC Rejected Candidate
```python
btc_rejected = ShadowReplayCandidate(
    candidate_id="btc_rejected_001",
    tick_id="tick_20260802_002",
    asset_ticker="BTC",
    timestamp=datetime(2026, 8, 2, 10, 15, 0),
    
    # Signal Data
    p_hat_yes_fraction=0.55,
    p_hat_yes_cents=55.0,
    signal_side="yes",
    
    # Market Data
    yes_bid_cents=50,
    yes_ask_cents=65,  # Wide spread (15c) - should reject
    no_bid_cents=35,
    no_ask_cents=50,
    yes_bid_depth=80,
    no_bid_depth=60,
    time_to_expiry_seconds=300,  # 5 minutes remaining
    
    # Order Intent
    order_side="yes",
    order_action="buy",
    order_price_cents=50,
    order_count=10,
    
    # Policy
    use_maker_economics=True,
    aggressiveness=0.3,
    
    # Expected Outcome
    expected_decision="reject",
    expected_reject_reason="spread_too_wide",
    
    # Metadata
    market_regime="normal",
    volatility_level="medium",
    liquidity_level="medium"
)
```

## ETH Candidates

### ETH Accepted Candidate
```python
eth_accepted = ShadowReplayCandidate(
    candidate_id="eth_accepted_001",
    tick_id="tick_20260802_003",
    asset_ticker="ETH",
    timestamp=datetime(2026, 8, 2, 10, 30, 0),
    
    # Signal Data
    p_hat_yes_fraction=0.53,
    p_hat_yes_cents=53.0,
    signal_side="yes",
    
    # Market Data
    yes_bid_cents=48,
    yes_ask_cents=50,
    no_bid_cents=50,
    no_ask_cents=52,
    yes_bid_depth=120,
    no_bid_depth=100,
    time_to_expiry_seconds=700,
    
    # Order Intent
    order_side="yes",
    order_action="buy",
    order_price_cents=48,
    order_count=15,
    
    # Policy
    use_maker_economics=True,
    aggressiveness=0.4,
    
    # Expected Outcome
    expected_decision="accept",
    
    # Metadata
    market_regime="normal",
    volatility_level="low",
    liquidity_level="high"
)
```

### ETH Rejected Candidate
```python
eth_rejected = ShadowReplayCandidate(
    candidate_id="eth_rejected_001",
    tick_id="tick_20260802_004",
    asset_ticker="ETH",
    timestamp=datetime(2026, 8, 2, 10, 45, 0),
    
    # Signal Data
    p_hat_yes_fraction=0.51,
    p_hat_yes_cents=51.0,
    signal_side="no",
    
    # Market Data
    yes_bid_cents=55,
    yes_ask_cents=70,  # Wide spread (15c) - should reject
    no_bid_cents=30,
    no_ask_cents=45,
    yes_bid_depth=70,
    no_bid_depth=50,
    time_to_expiry_seconds=200,
    
    # Order Intent
    order_side="no",
    order_action="sell",
    order_price_cents=45,
    order_count=15,
    
    # Policy
    use_maker_economics=False,
    aggressiveness=0.4,
    
    # Expected Outcome
    expected_decision="reject",
    expected_reject_reason="spread_too_wide",
    
    # Metadata
    market_regime="normal",
    volatility_level="high",
    liquidity_level="low"
)
```

## SOL Candidates

### SOL Accepted Candidate
```python
sol_accepted = ShadowReplayCandidate(
    candidate_id="sol_accepted_001",
    tick_id="tick_20260802_005",
    asset_ticker="SOL",
    timestamp=datetime(2026, 8, 2, 11, 0, 0),
    
    # Signal Data
    p_hat_yes_fraction=0.72,
    p_hat_yes_cents=72.0,
    signal_side="yes",
    
    # Market Data
    yes_bid_cents=65,
    yes_ask_cents=68,
    no_bid_cents=32,
    no_ask_cents=35,
    yes_bid_depth=80,
    no_bid_depth=60,
    time_to_expiry_seconds=800,
    
    # Order Intent
    order_side="yes",
    order_action="buy",
    order_price_cents=65,
    order_count=20,
    
    # Policy
    use_maker_economics=True,
    aggressiveness=0.5,
    
    # Expected Outcome
    expected_decision="accept",
    
    # Metadata
    market_regime="normal",
    volatility_level="medium",
    liquidity_level="medium"
)
```

### SOL Rejected Candidate
```python
sol_rejected = ShadowReplayCandidate(
    candidate_id="sol_rejected_001",
    tick_id="tick_20260802_006",
    asset_ticker="SOL",
    timestamp=datetime(2026, 8, 2, 11, 15, 0),
    
    # Signal Data
    p_hat_yes_fraction=0.68,
    p_hat_yes_cents=68.0,
    signal_side="yes",
    
    # Market Data
    yes_bid_cents=60,
    yes_ask_cents=85,  # Very wide spread (25c) - should reject
    no_bid_cents=15,
    no_ask_cents=40,
    yes_bid_depth=40,
    no_bid_depth=30,
    time_to_expiry_seconds=100,
    
    # Order Intent
    order_side="yes",
    order_action="buy",
    order_price_cents=60,
    order_count=20,
    
    # Policy
    use_maker_economics=True,
    aggressiveness=0.5,
    
    # Expected Outcome
    expected_decision="reject",
    expected_reject_reason="spread_too_wide",
    
    # Metadata
    market_regime="normal",
    volatility_level="high",
    liquidity_level="low"
)
```

## XRP Candidates

### XRP Accepted Candidate
```python
xrp_accepted = ShadowReplayCandidate(
    candidate_id="xrp_accepted_001",
    tick_id="tick_20260802_007",
    asset_ticker="XRP",
    timestamp=datetime(2026, 8, 2, 11, 30, 0),
    
    # Signal Data
    p_hat_yes_fraction=0.62,
    p_hat_yes_cents=62.0,
    signal_side="yes",
    
    # Market Data
    yes_bid_cents=55,
    yes_ask_cents=58,
    no_bid_cents=42,
    no_ask_cents=45,
    yes_bid_depth=70,
    no_bid_depth=50,
    time_to_expiry_seconds=750,
    
    # Order Intent
    order_side="yes",
    order_action="buy",
    order_price_cents=55,
    order_count=25,
    
    # Policy
    use_maker_economics=True,
    aggressiveness=0.4,
    
    # Expected Outcome
    expected_decision="accept",
    
    # Metadata
    market_regime="normal",
    volatility_level="medium",
    liquidity_level="medium"
)
```

### XRP Rejected Candidate
```python
xrp_rejected = ShadowReplayCandidate(
    candidate_id="xrp_rejected_001",
    tick_id="tick_20260802_008",
    asset_ticker="XRP",
    timestamp=datetime(2026, 8, 2, 11, 45, 0),
    
    # Signal Data
    p_hat_yes_fraction=0.58,
    p_hat_yes_cents=58.0,
    signal_side="no",
    
    # Market Data
    yes_bid_cents=52,
    yes_ask_cents=78,  # Very wide spread (26c) - should reject
    no_bid_cents=22,
    no_ask_cents=48,
    yes_bid_depth=35,
    no_bid_depth=25,
    time_to_expiry_seconds=150,
    
    # Order Intent
    order_side="no",
    order_action="sell",
    order_price_cents=48,
    order_count=25,
    
    # Policy
    use_maker_economics=False,
    aggressiveness=0.4,
    
    # Expected Outcome
    expected_decision="reject",
    expected_reject_reason="spread_too_wide",
    
    # Metadata
    market_regime="normal",
    volatility_level="high",
    liquidity_level="low"
)
```

## DOGE Candidates

### DOGE Accepted Candidate
```python
doge_accepted = ShadowReplayCandidate(
    candidate_id="doge_accepted_001",
    tick_id="tick_20260802_009",
    asset_ticker="DOGE",
    timestamp=datetime(2026, 8, 2, 12, 0, 0),
    
    # Signal Data
    p_hat_yes_fraction=0.32,
    p_hat_yes_cents=32.0,
    signal_side="yes",
    
    # Market Data
    yes_bid_cents=28,
    yes_ask_cents=32,
    no_bid_cents=68,
    no_ask_cents=72,
    yes_bid_depth=50,
    no_bid_depth=40,
    time_to_expiry_seconds=650,
    
    # Order Intent
    order_side="yes",
    order_action="buy",
    order_price_cents=28,
    order_count=30,
    
    # Policy
    use_maker_economics=True,
    aggressiveness=0.6,
    
    # Expected Outcome
    expected_decision="accept",
    
    # Metadata
    market_regime="normal",
    volatility_level="medium",
    liquidity_level="medium"
)
```

### DOGE Rejected Candidate
```python
doge_rejected = ShadowReplayCandidate(
    candidate_id="doge_rejected_001",
    tick_id="tick_20260802_010",
    asset_ticker="DOGE",
    timestamp=datetime(2026, 8, 2, 12, 15, 0),
    
    # Signal Data
    p_hat_yes_fraction=0.28,
    p_hat_yes_cents=28.0,
    signal_side="yes",
    
    # Market Data
    yes_bid_cents=25,
    yes_ask_cents=60,  # Extremely wide spread (35c) - should reject
    no_bid_cents=40,
    no_ask_cents=75,
    yes_bid_depth=20,
    no_bid_depth=15,
    time_to_expiry_seconds=50,
    
    # Order Intent
    order_side="yes",
    order_action="buy",
    order_price_cents=25,
    order_count=30,
    
    # Policy
    use_maker_economics=True,
    aggressiveness=0.6,
    
    # Expected Outcome
    expected_decision="reject",
    expected_reject_reason="spread_too_wide",
    
    # Metadata
    market_regime="normal",
    volatility_level="high",
    liquidity_level="low"
)
```

---

# SHADOW REPLAY EXECUTION PLAN

## Phase 3: Shadow Replay Execution

### Execution Steps
1. **Load candidate data** for each asset (accepted + rejected)
2. **Initialize gate orchestrator** with production configuration
3. **Execute each candidate** through complete pipeline
4. **Capture decision trace** with full metadata
5. **Compare vs expected outcome** (accept/reject, reject reason)
6. **Log discrepancies** for analysis

### Success Criteria
- **Accepted candidates**: Should pass all gates and execute successfully
- **Rejected candidates**: Should fail at expected gate with expected reason
- **Decision trace**: Should contain complete gate execution history
- **Asset-specific calibration**: Should use correct thresholds per asset

---

# EXPECTED REPLAY RESULTS

## Expected Acceptance Rates
- **BTC**: 1/2 accepted (50%)
- **ETH**: 1/2 accepted (50%)
- **SOL**: 1/2 accepted (50%)
- **XRP**: 1/2 accepted (50%)
- **DOGE**: 1/2 accepted (50%)

## Expected Rejection Reasons
- **Spread too wide**: Primary rejection reason for rejected candidates
- **Insufficient depth**: Potential rejection for low-liquidity cases
- **Crossed book**: Should not occur with valid market data

---

# NEXT STEPS

1. **Implement shadow replay execution** using gate orchestrator
2. **Execute replay for all 10 candidates** (5 assets × 2 candidates each)
3. **Analyze results** and identify any discrepancies
4. **Classify bugs** by stage (signal, gate, policy, router)
5. **Remediate issues** if any found

---

# REFERENCES

- End-to-end audit checklist: `END_TO_END_PIPELINE_AUDIT_2026_08_02.md`
- Gate orchestrator: `merid/event_venues/kalshi/gate_orchestrator.py`
- Unit conversion tracing: `UNIT_CONVERSION_TRACING_2026_08_02.md`
- Microstructure gate spec: `MICROSTRUCTURE_GATE_15M_SPEC_2026_08_02.md`
