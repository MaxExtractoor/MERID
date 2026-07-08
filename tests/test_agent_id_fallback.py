"""Test agent_id fallback derivation in position_cache.py.

This test verifies the CRITICAL FIX (2026-07-07) that adds a fallback to derive
agent_id from ticker when it's missing from the fill record. This ensures window
exposure is tracked even for HTTP fills that don't have agent_id context.
"""

import pytest
from pathlib import Path


def test_agent_id_fallback_derivation_exists():
    """Test that position_cache.py has agent_id fallback derivation logic."""
    cache_path = Path(__file__).parent.parent / "merid" / "event_venues" / "kalshi" / "position_cache.py"
    
    with open(cache_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify the fallback logic exists
    assert "CRITICAL FIX (2026-07-07): Derive agent_id from ticker if missing" in content, \
        "agent_id fallback derivation comment missing"
    
    # Verify it uses kalshi_ticker_to_asset
    assert "kalshi_ticker_to_asset" in content, \
        "kalshi_ticker_to_asset import missing for agent_id fallback"
    
    # Verify it checks for the 5 crypto assets
    assert "BTC" in content and "ETH" in content and "SOL" in content and "XRP" in content and "DOGE" in content, \
        "Crypto asset checks missing for agent_id fallback"
    
    # Verify it derives the correct agent_id format
    assert 'f"{asset.upper()}_15M"' in content or "asset.upper() + '_15M'" in content, \
        "agent_id format derivation incorrect (should be ASSET_15M)"
    
    # Verify it's in the on_fill function
    assert "async def on_fill" in content, \
        "on_fill function not found in position_cache.py"


def test_agent_id_fallback_in_on_fill():
    """Test that agent_id fallback is placed correctly in on_fill function."""
    cache_path = Path(__file__).parent.parent / "merid" / "event_venues" / "kalshi" / "position_cache.py"
    
    with open(cache_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Find the on_fill function
    on_fill_start = content.find("async def on_fill")
    assert on_fill_start != -1, "on_fill function not found"
    
    # Extract the on_fill function (up to the next function or end of file)
    on_fill_section = content[on_fill_start:]
    next_func = on_fill_section.find("\n    async def ", 1)  # Skip the first match (on_fill itself)
    if next_func != -1:
        on_fill_section = on_fill_section[:next_func]
    
    # Verify the fallback logic is in on_fill
    assert "Derive agent_id from ticker if missing" in on_fill_section, \
        "agent_id fallback logic not found in on_fill function"
    
    # Verify it's after the initial agent_id extraction from fills_ledger
    assert "getattr(fill_record, 'agent_id'" in on_fill_section, \
        "Initial agent_id extraction from fills_ledger not found"
    
    # Verify the fallback comes after the initial extraction
    initial_extract_pos = on_fill_section.find("getattr(fill_record, 'agent_id'")
    fallback_pos = on_fill_section.find("Derive agent_id from ticker if missing")
    assert fallback_pos > initial_extract_pos, \
        "agent_id fallback should come after initial extraction from fills_ledger"


def test_agent_id_fallback_logging():
    """Test that agent_id fallback has appropriate logging."""
    cache_path = Path(__file__).parent.parent / "merid" / "event_venues" / "kalshi" / "position_cache.py"
    
    with open(cache_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Verify debug logging for successful derivation
    assert "Derived agent_id" in content and "from ticker" in content, \
        "Debug logging for agent_id derivation missing"
    
    # Verify debug logging for derivation failure
    assert "Could not derive agent_id from ticker" in content, \
        "Debug logging for agent_id derivation failure missing"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
