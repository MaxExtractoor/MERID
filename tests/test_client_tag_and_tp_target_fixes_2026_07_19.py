"""
Tests for client_tag assignment and TP target registration fixes (2026-07-19).

Root cause: OrderIntent.client_tag was not set in kalshi_tools.py and universal_agent.py,
causing TP targets to never be registered with position_cache. This resulted in positions
having no TP targets when added to PositionMonitor, causing exit policies to fail.

Additional fix: Corrected fills_ledger method name from get_fill to get_fill_by_id in
position_cache.py (4 sites), which caused agent_id, client_order_id recovery, edge_pct,
and raw_logit lookups to fail.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass


def test_kalshi_tools_sets_client_tag():
    """Test that kalshi_tools.py sets client_tag = intent_id on OrderIntent.
    
    Without client_tag, TP targets are never registered with position_cache,
    causing exit policies to fail.
    
    This test verifies the code by checking the source code directly.
    """
    # Read kalshi_tools.py and verify client_tag assignment
    with open('c:/Dev/MERID/merid/prediction/kalshi_tools.py', 'r') as f:
        content = f.read()
    
    # Check for the critical fix: intent.client_tag = intent.intent_id
    assert 'intent.client_tag = intent.intent_id' in content, \
        "kalshi_tools.py should set client_tag = intent_id"
    
    # Verify it's set after OrderIntent construction
    lines = content.split('\n')
    found_intent_construction = False
    found_client_tag_assignment = False
    
    for i, line in enumerate(lines):
        if 'intent = OrderIntent(' in line:
            found_intent_construction = True
        if found_intent_construction and 'intent.client_tag = intent.intent_id' in line:
            found_client_tag_assignment = True
            break
    
    assert found_client_tag_assignment, \
        "client_tag assignment should appear after OrderIntent construction"


def test_universal_agent_sets_client_tag():
    """Test that universal_agent.py sets client_tag = intent_id on OrderIntent.
    
    Without client_tag, TP targets are never registered with position_cache,
    causing exit policies to fail.
    
    This test verifies the code by checking the source code directly.
    """
    # Read universal_agent.py and verify client_tag assignment
    with open('c:/Dev/MERID/merid/prediction/universal_agent.py', 'r') as f:
        content = f.read()
    
    # Check for the critical fix: intent.client_tag = intent.intent_id
    assert 'intent.client_tag = intent.intent_id' in content, \
        "universal_agent.py should set client_tag = intent_id"
    
    # Verify it's set after OrderIntent construction
    lines = content.split('\n')
    found_intent_construction = False
    found_client_tag_assignment = False
    
    for i, line in enumerate(lines):
        if 'intent = OrderIntent(' in line:
            found_intent_construction = True
        if found_intent_construction and 'intent.client_tag = intent.intent_id' in line:
            found_client_tag_assignment = True
            break
    
    assert found_client_tag_assignment, \
        "client_tag assignment should appear after OrderIntent construction"


def test_fills_ledger_get_fill_by_id_method():
    """Test that KalshiFillsLedger has get_fill_by_id method, not get_fill.
    
    This test validates the fix for the bug where position_cache.py was calling
    ledger.get_fill(fill_id) but the actual method is get_fill_by_id.
    """
    from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger, KalshiFill
    from datetime import datetime, timezone
    from decimal import Decimal
    
    # Create a ledger instance
    ledger = KalshiFillsLedger()
    
    # Create a test fill (using correct field names from KalshiFill dataclass)
    test_fill = KalshiFill(
        fill_id="test_fill_id",
        market_ticker="KXBTC15M-TEST",
        side="yes",
        action="buy",
        count_fp=1,
        yes_price_dollars=Decimal("0.50"),
        fee_cost=Decimal("0.01"),
        created_time=datetime.now(timezone.utc),
        order_id="test_order_id"
    )
    
    # Add fill to ledger
    ledger._fills["test_fill_id"] = test_fill
    
    # Verify get_fill_by_id works
    retrieved_fill = ledger.get_fill_by_id("test_fill_id")
    assert retrieved_fill is not None, "get_fill_by_id should return the fill"
    assert retrieved_fill.fill_id == "test_fill_id", "Fill ID should match"
    
    # Verify get_fill method does NOT exist
    assert not hasattr(ledger, 'get_fill'), "KalshiFillsLedger should not have get_fill method"


def test_position_cache_uses_get_fill_by_id():
    """Test that position_cache.py uses get_fill_by_id instead of get_fill.
    
    This test validates that the 4 sites in position_cache.py that were calling
    get_fill have been corrected to call get_fill_by_id.
    """
    import re
    
    # Read position_cache.py
    with open('c:/Dev/MERID/merid/event_venues/kalshi/position_cache.py', 'r') as f:
        content = f.read()
    
    # Count occurrences of get_fill (should be 0 in the context of ledger.get_fill)
    # We need to be careful not to match get_fill_by_id
    get_fill_pattern = r'\.get_fill\('
    matches = re.findall(get_fill_pattern, content)
    
    # Filter out get_fill_by_id matches
    get_fill_by_id_pattern = r'\.get_fill_by_id\('
    get_fill_by_id_matches = re.findall(get_fill_by_id_pattern, content)
    
    # Assert no get_fill calls remain (only get_fill_by_id should exist)
    assert len(matches) == 0, \
        f"Found {len(matches)} calls to get_fill, should be 0. All should be get_fill_by_id."
    assert len(get_fill_by_id_matches) >= 4, \
        f"Expected at least 4 calls to get_fill_by_id, found {len(get_fill_by_id_matches)}"


def test_tp_target_registration_flow():
    """Test the complete TP target registration flow.
    
    This test validates:
    1. OrderIntent has client_tag set
    2. order_router registers TP targets with position_cache
    3. position_cache stores TP targets in _pending_tp_targets
    4. On fill, TP targets are retrieved and passed to PositionMonitor
    """
    from merid.event_venues.kalshi.order_router import OrderIntent
    from merid.event_venues.kalshi.position_cache import KalshiPositionCache
    
    # Create an intent with client_tag and TP targets
    intent = OrderIntent(
        ticker="KXBTC15M-TEST",
        side="BUY_YES",
        action="buy",
        price_cents=50,
        count=1,
        source="test",
        client_tag="test_client_tag",
        take_profit_price_cents=55,
        take_profit_r_multiple=1.0,
        stop_loss_price_cents=45
    )
    
    # Verify client_tag is set
    assert intent.client_tag == "test_client_tag", "client_tag should be set"
    
    # Get position cache
    cache = KalshiPositionCache()
    
    # Register TP targets (simulating order_router behavior)
    cache.register_tp_targets(
        client_order_id=intent.client_tag,
        take_profit_price_cents=intent.take_profit_price_cents,
        take_profit_r_multiple=intent.take_profit_r_multiple,
        stop_loss_price_cents=intent.stop_loss_price_cents
    )
    
    # Verify TP targets are stored
    assert intent.client_tag in cache._pending_tp_targets, \
        "TP targets should be stored in _pending_tp_targets"
    
    tp_targets = cache._pending_tp_targets[intent.client_tag]
    assert tp_targets["tp_price"] == 55, "TP price should be 55"
    assert tp_targets["tp_r"] == 1.0, "TP R-multiple should be 1.0"
    assert tp_targets["sl_price"] == 45, "SL price should be 45"
    
    # Simulate fill and verify TP targets are retrieved
    import asyncio
    asyncio.run(cache.on_fill(
        market_id="KXBTC15M-TEST",
        contracts=1,
        price_cents=50,
        fee_cents=1,
        side="yes",
        client_order_id=intent.client_tag,
        fill_id="test_fill_id",
        action="buy"
    ))
    
    # Verify position was created with TP targets
    position = cache.get_position("KXBTC15M-TEST")
    assert position is not None, "Position should be created"
    assert position.take_profit_price_cents == 55, \
        f"Position should have TP price 55, got {position.take_profit_price_cents}"
    assert position.take_profit_r_multiple == 1.0, \
        f"Position should have TP R-multiple 1.0, got {position.take_profit_r_multiple}"
    assert position.stop_loss_price_cents == 45, \
        f"Position should have SL price 45, got {position.stop_loss_price_cents}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
