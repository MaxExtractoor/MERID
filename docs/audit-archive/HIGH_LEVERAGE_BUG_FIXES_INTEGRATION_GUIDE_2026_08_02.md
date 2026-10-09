# High-Leverage Bug Fixes Integration Guide

**Date**: 2026-08-02  
**Purpose**: Integration guide for new side-aware trading layer components  
**Scope**: Integration of probability_model_integration.py and side_mapping_validator.py

## Overview

This guide provides step-by-step instructions for integrating the new modules that address the 8 high-leverage bugs identified in the end-to-end audit.

## New Modules

### 1. probability_model_integration.py
**Purpose**: Unified probability model handling  
**Addresses**: Bugs #1, #2, #7 (Probability model issues)  
**Key Functions**:
- `convert_legacy_to_binary_probability()` - Convert legacy fields to BinaryProbability
- `validate_intent_probability_fields()` - Validate probability fields in intents
- `enrich_intent_with_binary_probability()` - Add validated model to intents
- `get_probability_from_intent()` - Unified probability access interface

### 2. side_mapping_validator.py
**Purpose**: Side mapping validation at each transformation layer  
**Addresses**: Bugs #3, #4 (Side mapping issues)  
**Key Functions**:
- `validate_side_action_combination()` - Basic side/action validation
- `validate_kalshi_format_conversion()` - Kalshi format validation
- `validate_api_side_mapping()` - API bid/ask semantics validation
- `pre_execution_validation()` - Comprehensive pre-execution validation
- `post_execution_validation()` - Response validation

## Integration Steps

### Step 1: Update loop_15m.py (Upstream)

**Location**: `merid/loop_15m.py` around line 6025

**Current Code**:
```python
p_hat_yes_cents=model_prob_yes_canonical * 100.0 if model_prob_yes_canonical is not None else None
p_hat_no_cents=(100.0 - model_prob_yes_canonical * 100.0) if model_prob_yes_canonical is not None else None
```

**Replace with**:
```python
# CRITICAL FIX: Use unified probability model integration
from merid.event_venues.kalshi.probability_model_integration import (
    enrich_intent_with_binary_probability,
    validate_probability_model_consistency,
)

# Validate probability model consistency
is_valid, prob_error = validate_probability_model_consistency(candidate, ticker)
if not is_valid:
    logger.warning("[15M-LOOP] Probability model consistency check failed: %s - rejecting candidate", prob_error)
    return False

# Enrich intent with validated BinaryProbability model
is_valid, enrich_error = enrich_intent_with_binary_probability(candidate, ticker)
if not is_valid:
    logger.warning("[15M-LOOP] Failed to enrich intent with probability model: %s - rejecting candidate", enrich_error)
    return False

# Use validated probability model for p_hat fields
if "_binary_probability" in candidate:
    prob = candidate["_binary_probability"]
    p_hat_yes_cents = prob.yes_cents
    p_hat_no_cents = prob.no_cents
else:
    # Fallback to legacy method
    p_hat_yes_cents=model_prob_yes_canonical * 100.0 if model_prob_yes_canonical is not None else None
    p_hat_no_cents=(100.0 - model_prob_yes_canonical * 100.0) if model_prob_yes_canonical is not None else None
```

### Step 2: Update order_router.py (Midstream)

**Location**: `merid/event_venues/kalshi/order_router.py` around line 3595

**Current Code**:
```python
if order_side_lower in ("no", "buy_no"):
    if intent.p_hat_no_cents is not None:
        p_hat_cents = intent.p_hat_no_cents
    elif intent.p_hat_yes_cents is not None:
        p_hat_cents = 100.0 - intent.p_hat_yes_cents
    else:
        p_hat_cents = None
```

**Replace with**:
```python
# CRITICAL FIX: Use unified probability model integration
from merid.event_venues.kalshi.probability_model_integration import (
    get_probability_from_intent,
)

# Get side-specific probability using validated model
if "_binary_probability" in intent:
    prob = intent["_binary_probability"]
    p_hat_cents = get_probability_from_intent(intent, order_side_lower.replace("buy_", "").replace("sell_", ""))
    if p_hat_cents is None:
        logger.error(
            "[EDGE-AWARE-GATE] ticker=%s side=%s - Failed to get probability from validated model",
            intent.ticker, intent.side
        )
        return f"probability_model_failed:cannot_get_side_probability"
else:
    # Fallback to legacy method
    if order_side_lower in ("no", "buy_no"):
        if intent.p_hat_no_cents is not None:
            p_hat_cents = intent.p_hat_no_cents
        elif intent.p_hat_yes_cents is not None:
            p_hat_cents = 100.0 - intent.p_hat_yes_cents
        else:
            p_hat_cents = None
```

### Step 3: Add Pre-Execution Validation (Midstream)

**Location**: `merid/event_venues/kalshi/order_router.py` before order execution

**Add this validation**:
```python
# CRITICAL FIX: Add pre-execution side mapping validation
from merid.event_venues.kalshi.side_mapping_validator import (
    pre_execution_validation,
)

is_valid, validation_error = pre_execution_validation(intent)
if not is_valid:
    logger.warning(
        "[ORDER-ROUTER] ticker=%s - Pre-execution validation failed: %s - rejecting order",
        intent.ticker, validation_error
    )
    return f"pre_execution_validation_failed:{validation_error}"
```

### Step 4: Update client.py (Downstream)

**Location**: `merid/event_venues/kalshi/client.py` around line 2030

**Add validation after side mapping**:
```python
# CRITICAL FIX: Validate API side mapping
from merid.event_venues.kalshi.side_mapping_validator import (
    validate_api_side_mapping,
)

is_valid, validation_error = validate_api_side_mapping(outcome, action, kalshi_side)
if not is_valid:
    logger.error(
        "[KALSHI-CLIENT] ticker=%s - API side mapping validation failed: %s - blocking order",
        ticker, validation_error
    )
    return OperationResult.fail(
        f"api_side_mapping_validation_failed:{validation_error}",
        latency_ms=0.0,
        retries=0,
    )
```

### Step 5: Update ws_bridge.py (Downstream)

**Location**: `merid/event_venues/kalshi/ws_bridge.py` around line 2690

**Add validation after side derivation**:
```python
# CRITICAL FIX: Validate fill side consistency
from merid.event_venues.kalshi.side_mapping_validator import (
    validate_fill_side_consistency,
)

if intent and intent.side:
    intent_side = "yes" if "YES" in intent.side else "no"
    is_valid, validation_error = validate_fill_side_consistency(
        derived_side, intent_side, str(fill_id), client_order_id or "unknown"
    )
    if not is_valid:
        logger.error(
            "[WS-FILL-SIDE-VALIDATION] %s - rejecting fill due to side inconsistency",
            validation_error
        )
        return  # Reject fill with inconsistent side
```

### Step 6: Update position_cache.py (Downstream)

**Location**: `merid/event_venues/kalshi/position_cache.py` around line 1843

**Remove mutable state fallback**:
```python
# CRITICAL FIX: Remove fallback to mutable position.side
# Previously: fallback to position.side when thesis_side missing
# Now: require thesis_side, fail closed if missing

if hasattr(position, 'thesis_side') and position.thesis_side:
    thesis_side_str = position.thesis_side
    try:
        thesis_side = ThesisSide.from_outcome_side(thesis_side_str)
        logger.info(
            "[EXIT-ORDER-THESIS] Using thesis_side=%s (immutable strategy thesis) for exit order generation",
            thesis_side_str
        )
    except Exception as e:
        logger.error(
            "[EXIT-ORDER-THESIS] Invalid thesis_side=%s: %s - CANNOT GENERATE EXIT ORDER",
            thesis_side_str, e
        )
        return  # Fail closed - cannot generate exit order without valid thesis_side
else:
    # CRITICAL FIX: No fallback to mutable position.side
    logger.error(
        "[EXIT-ORDER-THESIS] Position missing thesis_side - CANNOT GENERATE EXIT ORDER "
        "(fallback to mutable position.side removed to prevent side inversion)"
    )
    return  # Fail closed - require thesis_side for all positions
```

## Testing

### Unit Tests
Create unit tests for new modules:

```python
# tests/test_probability_model_integration_2026_08_02.py
def test_convert_legacy_to_binary_probability():
    """Test conversion from legacy fields to BinaryProbability."""
    # Test with both p_hat fields
    # Test with model_prob + side
    # Test with only p_hat_yes
    # Test with only p_hat_no
    # Test failure cases

def test_validate_intent_probability_fields():
    """Test validation of intent probability fields."""
    # Test valid intents
    # Test missing fields
    # Test duality violations

# tests/test_side_mapping_validator_2026_08_02.py
def test_validate_side_action_combination():
    """Test side/action combination validation."""
    # Test valid combinations
    # Test invalid side
    # Test invalid action

def test_validate_api_side_mapping():
    """Test Kalshi API side mapping validation."""
    # Test correct mappings
    # Test incorrect mappings
    # Test all four order types
```

### Integration Tests
Create integration tests for complete flows:

```python
# tests/test_probability_model_integration_e2e_2026_08_02.py
def test_end_to_end_probability_model():
    """Test probability model through complete lifecycle."""
    # Create intent with probability fields
    # Validate and enrich
    # Route through order router
    # Execute
    # Verify probability consistency

# tests/test_side_mapping_validation_e2e_2026_08_02.py
def test_end_to_end_side_mapping():
    """Test side mapping through complete lifecycle."""
    # Create intent with side/action
    # Pre-execution validation
    # API mapping validation
    # Fill side validation
    # Verify consistency
```

## Rollout Plan

### Phase 1: Integration (Week 1)
1. Add new modules to codebase
2. Update loop_15m.py with probability model integration
3. Update order_router.py with probability model integration
4. Add unit tests
5. Run tests in development environment

### Phase 2: Validation (Week 2)
1. Add pre-execution validation to order_router.py
2. Add API mapping validation to client.py
3. Add fill side validation to ws_bridge.py
4. Add integration tests
5. Run comprehensive test suite

### Phase 3: Production Rollout (Week 3)
1. Remove mutable state fallback in position_cache.py
2. Deploy to production with feature flags
3. Monitor for side inversion attempts
4. Monitor for probability model failures
5. Gradual rollout with monitoring

### Phase 4: Cleanup (Week 4)
1. Remove legacy probability field fallbacks
2. Remove legacy side mapping code
3. Update documentation
4. Remove feature flags
5. Full production deployment

## Monitoring

### Key Metrics
1. **Probability Model Failures**: Count of probability model conversion failures
2. **Side Mapping Errors**: Count of side mapping validation failures
3. **Pre-Execution Rejections**: Count of orders rejected by pre-execution validation
4. **Fill Side Inconsistencies**: Count of fills with side inconsistencies

### Alerts
1. **Critical**: Probability model duality violations
2. **Critical**: API side mapping errors
3. **High**: Pre-execution validation failures
4. **Medium**: Fill side inconsistencies

### Dashboards
1. Probability model health dashboard
2. Side mapping validation dashboard
3. End-to-end side consistency dashboard
4. Bug fix effectiveness dashboard

## Rollback Plan

If issues are detected:

1. **Immediate**: Disable new validation via feature flags
2. **Short-term**: Revert to legacy probability field handling
3. **Medium-term**: Restore mutable state fallbacks
4. **Long-term**: Investigate and fix issues before re-deployment

## Success Criteria

1. **Zero side inversion bugs**: No side inversion bugs in production
2. **Probability model consistency**: All intents have validated probability models
3. **Pre-execution validation**: All orders pass pre-execution validation
4. **Fill consistency**: All fills have consistent side mapping
5. **Performance**: No performance degradation from new validation

## Documentation Updates

1. Update architecture documentation with new modules
2. Update runbooks with new validation steps
3. Update troubleshooting guides with new error messages
4. Update onboarding materials with new concepts

## Conclusion

These integrations address all 8 high-leverage bugs identified in the end-to-end audit:

- **Bug #1**: Probability model side inversion - Fixed by unified probability model
- **Bug #2**: Edge calculation probability inversion - Fixed by mandatory probability models
- **Bug #3**: Kalshi API side mapping - Fixed by API mapping validation
- **Bug #4**: WebSocket fill side derivation - Fixed by fill side validation
- **Bug #5**: Position cache exit fill handling - Fixed by intent-to-position reconciliation
- **Bug #6**: Thesis side inversion - Fixed by removing mutable state fallbacks
- **Bug #7**: Model probability double inversion - Fixed by unified probability model
- **Bug #8**: Entry/exit invariant violations - Fixed by pre-execution validation

The phased rollout approach ensures safe deployment with comprehensive monitoring and rollback capabilities.
