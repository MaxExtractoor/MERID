"""Simple functional test for new modules."""

from merid.event_venues.kalshi.probability_model_integration import (
    LegacyProbabilityFields,
    convert_legacy_to_binary_probability,
)
from merid.event_venues.kalshi.side_mapping_validator import (
    validate_side_action_combination,
    validate_api_side_mapping,
)
from merid.event_venues.kalshi.side_aware_trading_layer import (
    BinaryProbability,
)

print("Testing probability model integration...")

# Test 1: Convert with both p_hat fields
legacy = LegacyProbabilityFields(
    p_hat_yes_cents=65.0,
    p_hat_no_cents=35.0
)
prob, error = convert_legacy_to_binary_probability(legacy, "TEST_TICKER")
if prob and prob.yes_cents == 65.0 and prob.no_cents == 35.0:
    print("OK Test 1: Convert with both p_hat fields")
else:
    print(f"FAIL Test 1: {error}")

# Test 2: Convert with model_prob for NO side (Bug #7 fix)
legacy = LegacyProbabilityFields(
    model_prob=0.25,
    side="no"
)
prob, error = convert_legacy_to_binary_probability(legacy, "TEST_TICKER")
if prob and prob.no_cents == 25.0 and prob.yes_cents == 75.0:
    print("OK Test 2: Convert with model_prob NO (Bug #7 fix)")
else:
    print(f"FAIL Test 2: {error}")

print("\nTesting side mapping validator...")

# Test 3: Validate side/action combination
is_valid, error = validate_side_action_combination("yes", "buy")
if is_valid:
    print("OK Test 3: Validate side/action combination")
else:
    print(f"FAIL Test 3: {error}")

# Test 4: Validate API side mapping (Bug #3 fix)
is_valid, error = validate_api_side_mapping("no", "buy", "bid")
if is_valid:
    print("OK Test 4: Validate API side mapping BUY_NO->bid (Bug #3 fix)")
else:
    print(f"FAIL Test 4: {error}")

# Test 5: Detect incorrect API mapping (would cause side inversion)
is_valid, error = validate_api_side_mapping("no", "buy", "ask")
if not is_valid and "API side mapping error" in error:
    print("OK Test 5: Detect incorrect API mapping (side inversion prevention)")
else:
    print(f"FAIL Test 5: Should have detected incorrect mapping")

print("\nTesting BinaryProbability...")

# Test 6: Create BinaryProbability with duality
prob = BinaryProbability(yes_cents=65.0, no_cents=35.0)
if prob.yes_cents == 65.0 and prob.no_cents == 35.0:
    print("OK Test 6: Create BinaryProbability")
else:
    print("FAIL Test 6: BinaryProbability creation failed")

# Test 7: Duality violation detection
try:
    prob = BinaryProbability(yes_cents=80.0, no_cents=50.0)
    print("FAIL Test 7: Should have raised ValueError for duality violation")
except ValueError as e:
    if "duality" in str(e).lower():
        print("OK Test 7: Duality violation detection")
    else:
        print(f"FAIL Test 7: Wrong error: {e}")

print("\nAll functional tests completed")
