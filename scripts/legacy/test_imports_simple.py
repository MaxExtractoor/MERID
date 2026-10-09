"""Simple test to check if imports work."""

try:
    from merid.event_venues.kalshi.probability_model_integration import (
        LegacyProbabilityFields,
        convert_legacy_to_binary_probability,
    )
    print("OK probability_model_integration imports successful")
except Exception as e:
    print(f"FAIL probability_model_integration import failed: {e}")

try:
    from merid.event_venues.kalshi.side_mapping_validator import (
        validate_side_action_combination,
    )
    print("OK side_mapping_validator imports successful")
except Exception as e:
    print(f"FAIL side_mapping_validator import failed: {e}")

try:
    from merid.event_venues.kalshi.side_aware_trading_layer import (
        BinaryProbability,
    )
    print("OK side_aware_trading_layer imports successful")
except Exception as e:
    print(f"FAIL side_aware_trading_layer import failed: {e}")

print("\nAll imports checked")
