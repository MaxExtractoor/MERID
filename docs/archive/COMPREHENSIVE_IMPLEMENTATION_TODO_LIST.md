# Comprehensive Implementation TODO List

**Date**: 2026-06-24  
**Scope**: Complete end-to-end implementation of 5-phase alignment roadmap  
**Coverage**: Upstream, Midstream, Downstream, End-to-End

---

## Phase 1: Minimal Model Layer (Week 1 - Critical Path)

### 1.1 Profile Configuration (Upstream)

**File**: `config/profiles/kalshi_crypto_15m_v2.yaml`

**Changes Required**:
- [ ] Add `velocity_model` section to profile YAML
  - [ ] Add BTC: alpha_0, alpha_1 coefficients
  - [ ] Add ETH: alpha_0, alpha_1 coefficients
  - [ ] Add SOL: alpha_0, alpha_1 coefficients
  - [ ] Add XRP: alpha_0, alpha_1 coefficients
  - [ ] Add DOGE: alpha_0, alpha_1 coefficients
  - [ ] Add comments explaining logistic mapping formula
  - [ ] Add calibration notes for future tuning

**File**: `merid/risk/profiles/crypto_15m_profile.py`

**Changes Required**:
- [ ] Add velocity_model fields to Crypto15mProfile dataclass (line ~53)
  - [ ] velocity_model_alpha_0_btc: float
  - [ ] velocity_model_alpha_1_btc: float
  - [ ] velocity_model_alpha_0_eth: float
  - [ ] velocity_model_alpha_1_eth: float
  - [ ] velocity_model_alpha_0_sol: float
  - [ ] velocity_model_alpha_1_sol: float
  - [ ] velocity_model_alpha_0_xrp: float
  - [ ] velocity_model_alpha_1_xrp: float
  - [ ] velocity_model_alpha_0_doge: float
  - [ ] velocity_model_alpha_1_doge: float
- [ ] Add velocity_model parsing in Crypto15mProfileAdapter._load_profile (line ~363)
  - [ ] Parse velocity_model section from raw YAML
  - [ ] Extract per-asset coefficients
  - [ ] Assign to Crypto15mProfile fields
- [ ] Add velocity_model to schema validation (line ~303)
  - [ ] Add velocity_model to required_sections list
  - [ ] Validate all 5 assets have coefficients

### 1.2 Agent Configuration (Upstream)

**File**: `merid/prediction/agent_grid_15m.py`

**Changes Required**:
- [ ] Add velocity coefficients to LeanAgentConfig dataclass (line ~116)
  - [ ] alpha_0: float (intercept)
  - [ ] alpha_1: float (velocity coefficient)
- [ ] Update build_15m_agent_grid to pass coefficients (line ~783)
  - [ ] Load coefficients from profile
  - [ ] Pass to each LeanAgent15m instance
- [ ] Update LeanAgent15m.__init__ to accept coefficients (line ~135)
  - [ ] Add alpha_0 parameter
  - [ ] Add alpha_1 parameter
  - [ ] Store as instance variables
  - [ ] Log coefficient values for debugging

### 1.3 Signal Generation Logic (Midstream)

**File**: `merid/prediction/agent_grid_15m.py`

**Changes Required**:
- [ ] Fix model_prob computation in _generate_signal (line ~468-476)
  - [ ] Calculate p_mkt from bid/ask mid
  - [ ] Calculate raw = alpha_0 + alpha_1 * velocity
  - [ ] Calculate p_model = 1.0 / (1.0 + exp(-raw))
  - [ ] Remove old logic that used market price directly
  - [ ] Add clamping to [0.01, 0.99]
  - [ ] Add logging for p_mkt, p_model, raw
- [ ] Fix edge_pct computation in _generate_signal (line ~461)
  - [ ] Change from abs(velocity) * 100
  - [ ] Change to (p_model - p_mkt) * 100.0
  - [ ] Add logging for edge calculation
- [ ] Fix confidence computation in _generate_signal (line ~464-466)
  - [ ] Change from min(0.95, 0.50 + velocity_magnitude * 100)
  - [ ] Change to min(0.99, 0.50 + 2.0 * abs(p_model - 0.5))
  - [ ] Add logging for confidence calculation
- [ ] Update signal dict (line ~482-497)
  - [ ] Add p_mkt to signal for debugging
  - [ ] Add raw_logit to signal for debugging
  - [ ] Verify edge_pct, confidence, model_prob are set correctly

### 1.4 Router Validation (Downstream)

**File**: `merid/event_venues/kalshi/order_router.py`

**Changes Required**:
- [ ] Remove special case for agent_grid_15m in _validate_signal_metadata (line ~1494)
  - [ ] Remove if intent.source == "merid.prediction.agent_grid_15m" check
  - [ ] Remove skip of edge_pct and confidence validation
  - [ ] Keep model_prob validation (venue invariant)
  - [ ] Update error messages to reflect new logic
- [ ] Remove special case for agent_grid_15m in _validate_price_band (line ~1417)
  - [ ] Remove if intent.source == "merid.prediction.agent_grid_15m" check
  - [ ] Apply standard price band validation
  - [ ] Update error messages to reflect new logic
- [ ] Verify all validation paths use new logic
  - [ ] Check route_order_async path (line ~4309)
  - [ ] Check route_order_async path (line ~5153)
  - [ ] Check route_order_async path (line ~5457)

### 1.5 Profile Threshold Tuning (Upstream)

**File**: `config/profiles/kalshi_crypto_15m_v2.yaml`

**Changes Required**:
- [ ] Review and tune strategy_policy.min_edge (line ~685)
  - [ ] Current: 0.02 (2%)
  - [ ] May need adjustment for new edge calculation
  - [ ] Test with historical data
- [ ] Review and tune strategy_policy.min_confidence (line ~686)
  - [ ] Current: 0.60 (60%)
  - [ ] May need adjustment for new confidence calculation
  - [ ] Test with historical data

### 1.6 Testing & Validation (End-to-End)

**Testing Required**:
- [ ] Unit test logistic mapping function
- [ ] Unit test edge calculation (p_model - p_mkt)
- [ ] Unit test confidence calculation (distance from 0.5)
- [ ] Integration test signal → candidate → OrderIntent flow
- [ ] Integration test router validation with new logic
- [ ] Backtest with historical data to validate coefficients
- [ ] Monitor candidate→order conversion rate
- [ ] Monitor router rejection reasons
- [ ] Verify no regression in trading performance

---

## Phase 2: Strategy ID Fields (Week 1 - Parallel)

### 2.1 OrderIntent Schema (Downstream)

**File**: `merid/event_venues/kalshi/order_router.py`

**Changes Required**:
- [ ] Add strategy_id field to OrderIntent dataclass (line ~853)
  - [ ] strategy_id: Optional[str] = None
  - [ ] Add docstring explaining purpose
- [ ] Add strategy_type field to OrderIntent dataclass (line ~853)
  - [ ] strategy_type: Optional[str] = None
  - [ ] Add docstring explaining purpose (heuristic_velocity, model_based)
- [ ] Add regime field to OrderIntent dataclass (line ~853)
  - [ ] regime: Optional[str] = None
  - [ ] Add docstring explaining purpose (normal, one_sided_yes, one_sided_no)
- [ ] Verify field is already present (line ~931)
  - [ ] regime field exists but needs to be populated
  - [ ] Ensure consistency with other fields

### 2.2 Profile Strategy Configuration (Upstream)

**File**: `config/profiles/kalshi_crypto_15m_v2.yaml`

**Changes Required**:
- [ ] Add strategies section to profile YAML
  - [ ] Add kalshi_15m_velocity_v1 strategy definition
  - [ ] Add type: heuristic_velocity
  - [ ] Add price_band configuration
    - [ ] min_cents: 40
    - [ ] max_cents: 60
  - [ ] Add min_edge: 0.2 (relaxed for heuristic)
  - [ ] Add min_confidence: 0.50 (relaxed for heuristic)
  - [ ] Add description of strategy
- [ ] Add strategies section to schema validation (crypto_15m_profile.py)
  - [ ] Add strategies to required_sections
  - [ ] Validate strategy structure

**File**: `merid/risk/profiles/crypto_15m_profile.py`

**Changes Required**:
- [ ] Add strategies fields to Crypto15mProfile dataclass
  - [ ] strategies: Dict[str, Any] = field(default_factory=dict)
- [ ] Add strategies parsing in Crypto15mProfileAdapter._load_profile
  - [ ] Parse strategies section from raw YAML
  - [ ] Assign to Crypto15mProfile field

### 2.3 Loop Execution (Midstream)

**File**: `merid/loop_15m.py`

**Changes Required**:
- [ ] Update _execute_candidate to set strategy_id (line ~2829)
  - [ ] Set strategy_id = "kalshi_15m_velocity_v1"
  - [ ] Add logging for strategy_id
- [ ] Update _execute_candidate to set strategy_type (line ~2829)
  - [ ] Set strategy_type = "heuristic_velocity"
  - [ ] Add logging for strategy_type
- [ ] Update _execute_candidate to set regime (line ~2829)
  - [ ] Get regime from candidate
  - [ ] Set regime on OrderIntent
  - [ ] Add logging for regime

### 2.4 Signal Generation (Upstream)

**File**: `merid/prediction/agent_grid_15m.py`

**Changes Required**:
- [ ] Add regime to signal dict in _generate_signal (line ~482)
  - [ ] Get regime from _validate_market_state
  - [ ] Add regime to signal dict
  - [ ] Add logging for regime
- [ ] Add regime to candidate dict in collect_order_candidate (line ~649)
  - [ ] Carry regime from signal to candidate
  - [ ] Add logging for regime

### 2.5 Router Logic Update (Downstream)

**File**: `merid/event_venues/kalshi/order_router.py`

**Changes Required**:
- [ ] Update _validate_signal_metadata to use strategy_type (line ~1476)
  - [ ] Change from intent.source check to intent.strategy_type check
  - [ ] Add logic for heuristic_velocity type (relaxed validation)
  - [ ] Add logic for model_based type (strict validation)
  - [ ] Keep model_prob validation for all types
- [ ] Update _validate_price_band to use strategy_type (line ~1401)
  - [ ] Change from intent.source check to intent.strategy_type check
  - [ ] Use strategy-specific price bands from profile
- [ ] Add helper function to get strategy policy
  - [ ] get_strategy_policy(strategy_id, profile)
  - [ ] Return strategy configuration
- [ ] Update all router paths to use new logic
  - [ ] route_order_async (line ~4309)
  - [ ] route_order_async (line ~5153)
  - [ ] route_order_async (line ~5457)

### 2.6 Backward Compatibility (Downstream)

**File**: `merid/event_venues/kalshi/order_router.py`

**Changes Required**:
- [ ] Keep source field for backward compatibility
  - [ ] Do not remove source field
  - [ ] Add deprecation warning if source is used
  - [ ] Log migration to strategy_id
- [ ] Add fallback logic for missing strategy_id
  - [ ] If strategy_id is None, infer from source
  - [ ] Log inference for debugging

### 2.7 Testing & Validation (End-to-End)

**Testing Required**:
- [ ] Unit test OrderIntent with new fields
- [ ] Unit test strategy policy lookup
- [ ] Integration test signal → candidate → OrderIntent with strategy fields
- [ ] Integration test router validation with strategy_type
- [ ] Test backward compatibility with source field
- [ ] Test strategy-specific validation logic
- [ ] Verify no regression in order acceptance rate

---

## Phase 3: Regime Propagation (Week 1 - Parallel)

### 3.1 Regime Classification (Upstream)

**File**: `merid/prediction/agent_grid_15m.py`

**Changes Required**:
- [ ] Extract regime classification from _validate_market_state (line ~273-284)
  - [ ] Create _classify_regime method
  - [ ] Move regime logic from _validate_market_state
  - [ ] Return regime from _classify_regime
- [ ] Update _validate_market_state to use _classify_regime
  - [ ] Call _classify_regime method
  - [ ] Use returned regime
  - [ ] Keep regime logging

### 3.2 Signal Generation (Upstream)

**File**: `merid/prediction/agent_grid_15m.py`

**Changes Required**:
- [ ] Add regime to signal dict in _generate_signal (line ~482)
  - [ ] Call _classify_regime from market state
  - [ ] Add regime to signal dict
  - [ ] Add logging for regime
- [ ] Verify regime is consistent with validation
  - [ ] Ensure same regime used in both places
  - [ ] Add assertion for consistency

### 3.3 Candidate Propagation (Midstream)

**File**: `merid/prediction/agent_grid_15m.py`

**Changes Required**:
- [ ] Add regime to candidate dict in collect_order_candidate (line ~649)
  - [ ] Carry regime from signal to candidate
  - [ ] Add logging for regime
- [ ] Verify regime is carried correctly
  - [ ] Add assertion for regime presence
  - [ ] Add logging for regime propagation

### 3.4 Loop Execution (Midstream)

**File**: `merid/loop_15m.py`

**Changes Required**:
- [ ] Remove regime recomputation in _execute_candidate (line ~2689-2706)
  - [ ] Delete regime classification logic
  - [ ] Delete market state retrieval for regime
  - [ ] Delete depth threshold retrieval for regime
  - [ ] Delete regime classification logic
- [ ] Use regime from candidate in _execute_candidate (line ~2719)
  - [ ] Get regime from candidate
  - [ ] Pass to resolve_window_policy
  - [ ] Pass to resolve_exit_policy
  - [ ] Add logging for regime usage
- [ ] Verify regime is consistent across components
  - [ ] Add assertion for regime consistency
  - [ ] Add logging for regime flow

### 3.5 Window Policy Resolution (Downstream)

**File**: `merid/event_venues/kalshi/order_router.py`

**Changes Required**:
- [ ] Verify resolve_window_policy uses regime correctly (line ~374)
  - [ ] Ensure regime parameter is used
  - [ ] Verify regime-based logic works
  - [ ] Add logging for regime usage
- [ ] Test regime-based policy resolution
  - [ ] Test normal regime
  - [ ] Test one_sided_yes regime
  - [ ] Test one_sided_no regime

### 3.6 Exit Policy Resolution (Downstream)

**File**: `merid/event_venues/kalshi/order_router.py`

**Changes Required**:
- [ ] Verify resolve_exit_policy uses regime correctly (line ~265)
  - [ ] Ensure regime parameter is used
  - [ ] Verify regime-based logic works
  - [ ] Add logging for regime usage
- [ ] Test regime-based policy resolution
  - [ ] Test normal regime
  - [ ] Test one_sided_yes regime
  - [ ] Test one_sided_no regime

### 3.7 Testing & Validation (End-to-End)

**Testing Required**:
- [ ] Unit test _classify_regime method
- [ ] Unit test regime propagation through signal
- [ ] Unit test regime propagation through candidate
- [ ] Integration test regime flow from signal to router
- [ ] Test regime-based window policy resolution
- [ ] Test regime-based exit policy resolution
- [ ] Verify regime consistency across all components
- [ ] Verify no regime recomputation in downstream layers

---

## Phase 4: Multi-Window Momentum (Week 2-3)

### 4.1 Multi-Window Velocity Calculation (Upstream)

**File**: `merid/prediction/agent_grid_15m.py`

**Changes Required**:
- [ ] Add velocity windows to LeanAgent15m.__init__ (line ~135)
  - [ ] Add _velocity_windows list [10, 30, 60]
  - [ ] Add _velocity_history dict with deques
  - [ ] Initialize deques for each window
  - [ ] Add logging for window initialization
- [ ] Update _update_price_history to update all windows (line ~176)
  - [ ] Update each window's deque
  - [ ] Add logging for window updates
- [ ] Add _calculate_multi_window_velocity method (new method)
  - [ ] Calculate velocity for each window
  - [ ] Return list of velocities
  - [ ] Add logging for each window's velocity
- [ ] Update _generate_signal to use multi-window velocity (line ~353)
  - [ ] Call _calculate_multi_window_velocity
  - [ ] Combine velocities with weights
  - [ ] Use combined velocity for signal
  - [ ] Add logging for combined velocity

### 4.2 Profile Momentum Weights (Upstream)

**File**: `config/profiles/kalshi_crypto_15m_v2.yaml`

**Changes Required**:
- [ ] Add momentum_weights section to profile YAML
  - [ ] Add roc_10s_weight: 0.5
  - [ ] Add roc_30s_weight: 0.3
  - [ ] Add roc_60s_weight: 0.2
  - [ ] Add comments explaining weight rationale
- [ ] Add momentum_weights to schema validation (crypto_15m_profile.py)
  - [ ] Add momentum_weights to required_sections
  - [ ] Validate weight structure

**File**: `merid/risk/profiles/crypto_15m_profile.py`

**Changes Required**:
- [ ] Add momentum_weights fields to Crypto15mProfile dataclass
  - [ ] momentum_weights_roc_10s: float
  - [ ] momentum_weights_roc_30s: float
  - [ ] momentum_weights_roc_60s: float
- [ ] Add momentum_weights parsing in Crypto15mProfileAdapter._load_profile
  - [ ] Parse momentum_weights section from raw YAML
  - [ ] Assign to Crypto15mProfile fields

### 4.3 Mean Reversion Signal (Upstream)

**File**: `merid/prediction/agent_grid_15m.py`

**Changes Required**:
- [ ] Add SMA window to LeanAgent15m.__init__ (line ~135)
  - [ ] Add _sma_window_size = 120 (2 minutes)
  - [ ] Add _sma_history deque
  - [ ] Initialize SMA history deque
  - [ ] Add logging for SMA initialization
- [ ] Update _update_price_history to update SMA (line ~176)
  - [ ] Update SMA history deque
  - [ ] Add logging for SMA updates
- [ ] Add _calculate_mean_reversion method (new method)
  - [ ] Calculate 2-minute SMA
  - [ ] Calculate deviation from SMA
  - [ ] Check if deviation > 0.3% threshold
  - [ ] Return reversion signal
  - [ ] Add logging for reversion calculation
- [ ] Update _generate_signal to use mean reversion (line ~353)
  - [ ] Call _calculate_mean_reversion
  - [ ] Add reversion signal to signal dict
  - [ ] Add logging for reversion signal

### 4.4 Logit-Space Fusion (Upstream)

**File**: `merid/prediction/agent_grid_15m.py`

**Changes Required**:
- [ ] Add logit fusion weights to profile (kalshi_crypto_15m_v2.yaml)
  - [ ] Add logit_momentum_weight: 2.0
  - [ ] Add logit_reversion_weight: 1.5
  - [ ] Add comments explaining logit fusion
- [ ] Add logit fusion fields to Crypto15mProfile (crypto_15m_profile.py)
  - [ ] logit_momentum_weight: float
  - [ ] logit_reversion_weight: float
- [ ] Add logit fusion parsing in Crypto15mProfileAdapter._load_profile
  - [ ] Parse logit weights from profile
  - [ ] Assign to Crypto15mProfile fields
- [ ] Add _apply_logit_fusion method to LeanAgent15m (new method)
  - [ ] Convert p_mkt to logit space
  - [ ] Add momentum adjustment
  - [ ] Add reversion adjustment
  - [ ] Convert back to probability space
  - [ ] Clamp to [0.01, 0.99]
  - [ ] Add logging for logit fusion
- [ ] Update _generate_signal to use logit fusion (line ~468)
  - [ ] Call _apply_logit_fusion
  - [ ] Use fused probability as p_model
  - [ ] Add logging for fused probability

### 4.5 Near-Expiry Guard (Upstream)

**File**: `merid/prediction/agent_grid_15m.py`

**Changes Required**:
- [ ] Add near_expiry_guard_sec to profile (kalshi_crypto_15m_v2.yaml)
  - [ ] Add near_expiry_guard_sec: 5
  - [ ] Add comment explaining guard
- [ ] Add near_expiry_guard_sec to Crypto15mProfile (crypto_15m_profile.py)
  - [ ] near_expiry_guard_sec: int
- [ ] Add near_expiry_guard_sec parsing in Crypto15mProfileAdapter._load_profile
  - [ ] Parse near_expiry_guard_sec from profile
  - [ ] Assign to Crypto15mProfile field
- [ ] Update _generate_signal to check near expiry (line ~468)
  - [ ] Check if time_to_expiry <= near_expiry_guard_sec
  - [ ] If true, skip logit fusion
  - [ ] Use base probability only
  - [ ] Add logging for near expiry guard

### 4.6 Testing & Validation (End-to-End)

**Testing Required**:
- [ ] Unit test multi-window velocity calculation
- [ ] Unit test mean reversion signal
- [ ] Unit test logit-space fusion
- [ ] Unit test near-expiry guard
- [ ] Integration test signal generation with all components
- [ ] Backtest with historical data
- [ ] Compare single-window vs multi-window performance
- [ ] Tune weights based on backtest results
- [ ] Monitor signal quality metrics

---

## Phase 5: Probability Calibration (Week 4-5)

### 5.1 Platt Scaler Module (Upstream)

**File**: `merid/risk/probability/platt_scaler.py` (NEW FILE)

**Changes Required**:
- [ ] Create PlattScaler class
  - [ ] __init__ method
  - [ ] add_sample(p_raw, outcome) method
  - [ ] fit() method
  - [ ] calibrate(p_raw) method
  - [ ] can_fit() method
  - [ ] get_stats() method
  - [ ] reset() method
- [ ] Implement logistic regression fitting
  - [ ] Use sklearn LogisticRegression or custom implementation
  - [ ] Handle edge cases (insufficient samples)
  - [ ] Add logging for fitting process
- [ ] Implement calibration
  - [ ] Apply sigmoid transformation
  - [ ] Clamp to [0.01, 0.99]
  - [ ] Add logging for calibration
- [ ] Add calibration metrics
  - [ ] Brier score calculation
  - [ ] Expected Calibration Error (ECE)
  - [ ] Maximum Calibration Error (MCE)
- [ ] Add unit tests
  - [ ] Test fitting with synthetic data
  - [ ] Test calibration with synthetic data
  - [ ] Test edge cases

### 5.2 Profile Calibration Configuration (Upstream)

**File**: `config/profiles/kalshi_crypto_15m_v2.yaml`

**Changes Required**:
- [ ] Add calibration_config section to profile YAML
  - [ ] enable_platt_scaling: true
  - [ ] min_samples: 50
  - [ ] auto_fit: true
  - [ ] calibration_window: 200
  - [ ] Add comments explaining calibration
- [ ] Add calibration_config to schema validation (crypto_15m_profile.py)
  - [ ] Add calibration_config to required_sections
  - [ ] Validate calibration structure

**File**: `merid/risk/profiles/crypto_15m_profile.py`

**Changes Required**:
- [ ] Add calibration_config fields to Crypto15mProfile dataclass
  - [ ] calibration_enable_platt_scaling: bool
  - [ ] calibration_min_samples: int
  - [ ] calibration_auto_fit: bool
  - [ ] calibration_calibration_window: int
- [ ] Add calibration_config parsing in Crypto15mProfileAdapter._load_profile
  - [ ] Parse calibration_config section from raw YAML
  - [ ] Assign to Crypto15mProfile fields

### 5.3 Signal Generation Integration (Upstream)

**File**: `merid/prediction/agent_grid_15m.py`

**Changes Required**:
- [ ] Add PlattScaler to LeanAgent15m.__init__ (line ~135)
  - [ ] Import PlattScaler
  - [ ] Initialize _platt_scaler instance
  - [ ] Load calibration config from profile
  - [ ] Add logging for scaler initialization
- [ ] Update _generate_signal to use calibration (line ~468)
  - [ ] Check if calibration is enabled
  - [ ] Check if scaler is fitted
  - [ ] If yes, apply calibration
  - [ ] If no, use raw probability
  - [ ] Clamp to [0.01, 0.99]
  - [ ] Add logging for calibration
- [ ] Add outcome recording method
  - [ ] record_outcome(ticker, p_predicted, actual_outcome)
  - [ ] Add sample to scaler
  - [ ] Check if auto_fit is enabled
  - [ ] Check if min_samples reached
  - [ ] Fit scaler if conditions met
  - [ ] Add logging for outcome recording

### 5.4 Outcome Recording (Midstream)

**File**: `merid/loop_15m.py`

**Changes Required**:
- [ ] Add outcome recording to trade resolution
  - [ ] When market resolves, record outcome
  - [ ] Get predicted probability from trade
  - [ ] Call agent.record_outcome
  - [ ] Add logging for outcome recording
- [ ] Add outcome recording to summary
  - [ ] Track calibration metrics
  - [ ] Track sample count
  - [ ] Track fitted status
  - [ ] Add logging for calibration status

### 5.5 Calibration Metrics Tracking (Downstream)

**File**: `merid/loop_15m.py`

**Changes Required**:
- [ ] Add calibration metrics to summary (line ~2873)
  - [ ] Add brier_score
  - [ ] Add expected_calibration_error
  - [ ] Add max_calibration_error
  - [ ] Add sample_count
  - [ ] Add fitted_status
- [ ] Add calibration metrics to API
  - [ ] Expose via summary endpoint
  - [ ] Add logging for metrics

### 5.6 Testing & Validation (End-to-End)

**Testing Required**:
- [ ] Unit test PlattScaler with synthetic data
- [ ] Unit test calibration with synthetic data
- [ ] Integration test outcome recording
- [ ] Integration test auto-fit logic
- [ ] Test calibration with historical data
- [ ] Monitor calibration metrics over time
- [ ] Validate calibration improves probabilities
- [ ] Tune calibration parameters based on results

---

## Cross-Phase Tasks

### Documentation

**File**: `docs/15M_STACK_ALIGNMENT_RESEARCH_AND_ROADMAP.md`

**Changes Required**:
- [ ] Update roadmap with implementation progress
- [ ] Add lessons learned from implementation
- [ ] Update coefficient calibration notes
- [ ] Add performance metrics

**File**: `docs/5_PHASE_PLAN_VS_CURRENT_STATE_ANALYSIS.md`

**Changes Required**:
- [ ] Update gap analysis as implementation progresses
- [ ] Mark completed items
- [ ] Add new gaps discovered during implementation

### Monitoring & Telemetry

**File**: `merid/loop_15m.py`

**Changes Required**:
- [ ] Add telemetry for model_prob vs p_mkt
- [ ] Add telemetry for edge_pct distribution
- [ ] Add telemetry for confidence distribution
- [ ] Add telemetry for regime distribution
- [ ] Add telemetry for strategy_id usage
- [ ] Add telemetry for calibration metrics

### Configuration Management

**File**: `config/profiles/kalshi_crypto_15m_v2.yaml`

**Changes Required**:
- [ ] Add version tracking for profile
- [ ] Add change log for profile updates
- [ ] Add validation for coefficient ranges
- [ ] Add comments for all new sections

### Error Handling

**File**: `merid/prediction/agent_grid_15m.py`

**Changes Required**:
- [ ] Add error handling for missing coefficients
- [ ] Add error handling for invalid probabilities
- [ ] Add error handling for calibration failures
- [ ] Add fallback logic for missing profile sections

**File**: `merid/event_venues/kalshi/order_router.py`

**Changes Required**:
- [ ] Add error handling for missing strategy_id
- [ ] Add error handling for missing strategy_type
- [ ] Add error handling for missing regime
- [ ] Add fallback logic for missing fields

### Performance Optimization

**File**: `merid/prediction/agent_grid_15m.py`

**Changes Required**:
- [ ] Profile multi-window velocity calculation
- [ ] Optimize deque operations if needed
- [ ] Cache profile lookups if needed
- [ ] Add performance logging

---

## Summary Statistics

**Total Tasks**: ~150+ individual tasks across 5 phases

**File Count**: ~10 files to modify
- config/profiles/kalshi_crypto_15m_v2.yaml
- merid/risk/profiles/crypto_15m_profile.py
- merid/prediction/agent_grid_15m.py
- merid/loop_15m.py
- merid/event_venues/kalshi/order_router.py
- merid/risk/probability/platt_scaler.py (NEW)
- docs/15M_STACK_ALIGNMENT_RESEARCH_AND_ROADMAP.md
- docs/5_PHASE_PLAN_VS_CURRENT_STATE_ANALYSIS.md

**Estimated Effort**:
- Phase 1: ~3 hours (critical path)
- Phase 2: ~1 hour (parallel)
- Phase 3: ~25 minutes (parallel)
- Phase 4: ~4 hours
- Phase 5: ~3 hours
- Cross-phase: ~2 hours
- **Total**: ~13.5 hours

**Risk Level**: Medium
- Phase 1 has highest risk (coefficient calibration)
- Other phases have lower risk (can be disabled if needed)

**Dependencies**:
- Phase 1 must complete before Phase 4
- Phase 2 and 3 can run in parallel with Phase 1
- Phase 5 requires data collection from Phase 1-4
