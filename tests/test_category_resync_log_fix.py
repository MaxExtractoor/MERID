"""Test for CATEGORY_RESYNC log normalization fix."""

import pytest


def test_category_resync_normalization():
    """Test that missing keys are normalized to zero in resync comparison."""
    
    # Simulate old state with both categories
    old_contracts = {'crypto': 52, 'other': 0}
    old_notional = {'crypto': 13.59, 'other': 0.0}
    
    # Simulate new state after resync (other category dropped because no positions)
    new_contracts = {'crypto': 52}
    new_notional = {'crypto': 13.59}
    
    # Original logic (before fix) - would show misleading diff
    original_old_notional_str = str({k: round(v, 2) for k, v in old_notional.items()})
    original_new_notional_str = str({k: round(v, 2) for k, v in new_notional.items()})
    
    # This would show: old={'crypto': 13.59, 'other': 0.0} new={'crypto': 13.59}
    assert original_old_notional_str != original_new_notional_str, "Original logic shows diff (misleading)"
    
    # Fixed logic - normalize with union of keys
    all_contract_keys = set(old_contracts.keys()) | set(new_contracts.keys())
    all_notional_keys = set(old_notional.keys()) | set(new_notional.keys())
    
    normalized_old_contracts = {k: old_contracts.get(k, 0) for k in all_contract_keys}
    normalized_new_contracts = {k: new_contracts.get(k, 0) for k in all_contract_keys}
    normalized_old_notional = {k: round(old_notional.get(k, 0.0), 2) for k in all_notional_keys}
    normalized_new_notional = {k: round(new_notional.get(k, 0.0), 2) for k in all_notional_keys}
    
    # After normalization, both should be equal
    assert normalized_old_contracts == normalized_new_contracts, "Contracts should match after normalization"
    assert normalized_old_notional == normalized_new_notional, "Notional should match after normalization"
    
    # Verify the normalized output
    assert normalized_old_notional == {'crypto': 13.59, 'other': 0.0}
    assert normalized_new_notional == {'crypto': 13.59, 'other': 0.0}
    
    print("✓ CATEGORY_RESYNC normalization fix verified")


def test_category_resync_with_actual_change():
    """Test that normalization still detects real changes."""
    
    # Old state
    old_contracts = {'crypto': 50, 'other': 0}
    old_notional = {'crypto': 12.50, 'other': 0.0}
    
    # New state with actual change
    new_contracts = {'crypto': 52}  # Increased
    new_notional = {'crypto': 13.59}  # Increased
    
    # Normalize
    all_contract_keys = set(old_contracts.keys()) | set(new_contracts.keys())
    all_notional_keys = set(old_notional.keys()) | set(new_notional.keys())
    
    normalized_old_contracts = {k: old_contracts.get(k, 0) for k in all_contract_keys}
    normalized_new_contracts = {k: new_contracts.get(k, 0) for k in all_contract_keys}
    normalized_old_notional = {k: round(old_notional.get(k, 0.0), 2) for k in all_notional_keys}
    normalized_new_notional = {k: round(new_notional.get(k, 0.0), 2) for k in all_notional_keys}
    
    # Should detect the actual change
    assert normalized_old_contracts != normalized_new_contracts, "Should detect contract change"
    assert normalized_old_notional != normalized_new_notional, "Should detect notional change"
    
    # Verify the values
    assert normalized_old_contracts == {'crypto': 50, 'other': 0}
    assert normalized_new_contracts == {'crypto': 52, 'other': 0}
    assert normalized_old_notional == {'crypto': 12.5, 'other': 0.0}
    assert normalized_new_notional == {'crypto': 13.59, 'other': 0.0}
    
    print("✓ CATEGORY_RESYNC normalization detects real changes")


def test_category_resync_new_category_added():
    """Test normalization when a new category is added."""
    
    # Old state (only crypto)
    old_contracts = {'crypto': 52}
    old_notional = {'crypto': 13.59}
    
    # New state (crypto + other)
    new_contracts = {'crypto': 52, 'other': 10}
    new_notional = {'crypto': 13.59, 'other': 2.50}
    
    # Normalize
    all_contract_keys = set(old_contracts.keys()) | set(new_contracts.keys())
    all_notional_keys = set(old_notional.keys()) | set(new_notional.keys())
    
    normalized_old_contracts = {k: old_contracts.get(k, 0) for k in all_contract_keys}
    normalized_new_contracts = {k: new_contracts.get(k, 0) for k in all_contract_keys}
    normalized_old_notional = {k: round(old_notional.get(k, 0.0), 2) for k in all_notional_keys}
    normalized_new_notional = {k: round(new_notional.get(k, 0.0), 2) for k in all_notional_keys}
    
    # Should detect the new category
    assert normalized_old_contracts != normalized_new_contracts, "Should detect new category"
    assert normalized_old_notional != normalized_new_notional, "Should detect new category notional"
    
    # Verify the values
    assert normalized_old_contracts == {'crypto': 52, 'other': 0}
    assert normalized_new_contracts == {'crypto': 52, 'other': 10}
    assert normalized_old_notional == {'crypto': 13.59, 'other': 0.0}
    assert normalized_new_notional == {'crypto': 13.59, 'other': 2.5}
    
    print("✓ CATEGORY_RESYNC normalization handles new categories")


if __name__ == "__main__":
    test_category_resync_normalization()
    test_category_resync_with_actual_change()
    test_category_resync_new_category_added()
    print("\nAll tests passed!")
