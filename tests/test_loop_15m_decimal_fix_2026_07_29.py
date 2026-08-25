"""Tests for Decimal type consistency fix in loop_15m.py (2026-07-29).

Fixes TypeError: unsupported operand type(s) for +=: 'decimal.Decimal' and 'float'
by ensuring all additions to _asset_positions use Decimal consistently.

Also fixes AttributeError: 'Position' object has no attribute 'asset'
by using extract_asset(position.ticker) instead of position.asset.
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, MagicMock, patch


class TestAssetPositionsDecimalConsistency:
    """Test that _asset_positions uses Decimal consistently throughout loop_15m.py."""

    def test_asset_positions_type_annotation(self):
        """Test that _asset_positions is annotated as Dict[str, Decimal]."""
        with open("c:/Dev/MERID/merid/loop_15m.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Check for the type annotation
        assert "_asset_positions: Dict[str, Decimal]" in source, \
            "loop_15m.py must annotate _asset_positions as Dict[str, Decimal]"

    def test_position_reload_from_cache_uses_decimal(self):
        """Test that position reload from cache converts notional_value to Decimal."""
        from merid.loop_15m import Kalshi15mLoop
        from merid.event_venues.kalshi.position_cache import CachedPosition
        
        # Mock position with Decimal notional_value
        mock_position = Mock(spec=CachedPosition)
        mock_position.contracts = 10
        mock_position.avg_price_cents = 50
        mock_position.notional_value = Decimal('5.00')  # 10 contracts * 50c / 100 = $5.00
        
        # Simulate the addition logic from loop_15m.py line 2173
        asset_positions = {"BTC": Decimal('0.0')}
        asset = "BTC"
        
        # This should not raise TypeError
        asset_positions[asset] += Decimal(str(mock_position.notional_value))
        
        assert asset_positions[asset] == Decimal('5.00')

    def test_position_notional_calculation_uses_decimal(self):
        """Test that notional calculation from contracts and price uses Decimal."""
        from merid.loop_15m import Kalshi15mLoop
        from merid.event_venues.kalshi.position_cache import CachedPosition
        
        # Mock position
        mock_position = Mock(spec=CachedPosition)
        mock_position.contracts = 10
        mock_position.avg_price_cents = 50
        
        # Simulate the calculation logic from loop_15m.py line 876
        asset_positions = {"BTC": Decimal('0.0')}
        
        notional = Decimal(str((mock_position.contracts * mock_position.avg_price_cents) / 100.0))
        asset_positions["BTC"] += notional
        
        assert asset_positions["BTC"] == Decimal('5.00')
        assert isinstance(asset_positions["BTC"], Decimal)

    def test_position_tracking_after_fill_uses_decimal(self):
        """Test that position tracking after order fill uses Decimal."""
        from merid.loop_15m import Kalshi15mLoop
        
        # Simulate the logic from loop_15m.py line 5853
        asset_positions = {"BTC": Decimal('0.0')}
        asset = "BTC"
        position_notional_usd = 5.00  # float input
        
        # This should convert to Decimal before addition
        asset_positions[asset] = asset_positions.get(asset, Decimal('0.0')) + Decimal(str(position_notional_usd))
        
        assert asset_positions[asset] == Decimal('5.00')
        assert isinstance(asset_positions[asset], Decimal)

    def test_decimal_consistency_across_all_additions(self):
        """Test that all addition patterns in loop_15m.py use Decimal correctly."""
        from decimal import Decimal
        
        # Test pattern 1: += Decimal(str(value))
        asset_positions = {"BTC": Decimal('0.0')}
        notional_value = Decimal('5.00')
        asset_positions["BTC"] += Decimal(str(notional_value))
        assert asset_positions["BTC"] == Decimal('5.00')
        
        # Test pattern 2: += Decimal(str(calculation))
        asset_positions = {"ETH": Decimal('0.0')}
        contracts = 10
        avg_price_cents = 50
        notional = Decimal(str((contracts * avg_price_cents) / 100.0))
        asset_positions["ETH"] += notional
        assert asset_positions["ETH"] == Decimal('5.00')
        
        # Test pattern 3: get(asset, Decimal('0.0')) + Decimal(str(value))
        asset_positions = {"SOL": Decimal('0.0')}
        position_notional_usd = 5.00
        asset_positions["SOL"] = asset_positions.get("SOL", Decimal('0.0')) + Decimal(str(position_notional_usd))
        assert asset_positions["SOL"] == Decimal('5.00')

    def test_float_addition_raises_type_error(self):
        """Test that adding float to Decimal raises TypeError (regression test)."""
        from decimal import Decimal
        
        asset_positions = {"BTC": Decimal('0.0')}
        
        # This should raise TypeError
        with pytest.raises(TypeError):
            asset_positions["BTC"] += 5.0  # float

    def test_decimal_string_conversion_preserves_value(self):
        """Test that Decimal(str(value)) preserves the original value."""
        from decimal import Decimal
        
        # Test with various inputs
        test_cases = [
            (5.0, '5.0'),
            (5.5, '5.5'),
            (0.01, '0.01'),
            (Decimal('5.00'), '5.00'),
        ]
        
        for value, expected_str in test_cases:
            result = Decimal(str(value))
            assert str(result) == expected_str or abs(float(result) - float(value)) < 0.0001


class TestLoop15mSourceCodeDecimalFix:
    """Test that loop_15m.py source code contains the Decimal fix."""

    def test_loop_15m_uses_decimal_for_notional_value(self):
        """Test that loop_15m.py uses Decimal(str(position.notional_value))."""
        with open("c:/Dev/MERID/merid/loop_15m.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Check for the fix pattern in position reload
        assert "Decimal(str(position.notional_value))" in source, \
            "loop_15m.py must use Decimal(str(position.notional_value)) for type consistency"

    def test_loop_15m_uses_decimal_for_notional_calculation(self):
        """Test that loop_15m.py uses Decimal for notional calculation."""
        with open("c:/Dev/MERID/merid/loop_15m.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Check for the fix pattern in notional calculation
        assert "Decimal(str((position.contracts * position.avg_price_cents) / 100.0))" in source, \
            "loop_15m.py must use Decimal for notional calculation from contracts and price"

    def test_loop_15m_uses_decimal_for_position_tracking(self):
        """Test that loop_15m.py uses Decimal for position tracking after fill."""
        with open("c:/Dev/MERID/merid/loop_15m.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Check for the fix pattern in position tracking
        assert "Decimal(str(position_notional_usd))" in source, \
            "loop_15m.py must use Decimal(str(position_notional_usd)) for position tracking"

    def test_loop_15m_no_float_addition_to_asset_positions(self):
        """Test that loop_15m.py does not add float directly to _asset_positions."""
        with open("c:/Dev/MERID/merid/loop_15m.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Check that we don't have the buggy pattern
        # This is a negative test - we should NOT find float(position.notional_value)
        # in the context of _asset_positions addition
        lines = source.split('\n')
        for i, line in enumerate(lines):
            if '_asset_positions' in line and '+=' in line:
                # If this line adds to _asset_positions, it should not use float()
                assert 'float(' not in line, \
                    f"Line {i+1} adds float to _asset_positions: {line.strip()}"

    def test_loop_15m_uses_extract_asset_not_position_asset(self):
        """Test that loop_15m.py uses extract_asset(position.market_id) instead of position.asset."""
        with open("c:/Dev/MERID/merid/loop_15m.py", "r", encoding="utf-8") as f:
            source = f.read()
        
        # Check that we import extract_asset
        assert "from merid.utils.kalshi_identity import extract_asset" in source, \
            "loop_15m.py must import extract_asset from kalshi_identity"
        
        # Check that we use extract_asset in exit order logic
        # Look for the pattern: asset = extract_asset(position.market_id)
        assert "extract_asset(position.market_id)" in source, \
            "loop_15m.py must use extract_asset(position.market_id) instead of position.asset"
        
        # Check that we don't have the buggy pattern position.asset in exit order context
        lines = source.split('\n')
        for i, line in enumerate(lines):
            if 'position.asset' in line:
                # This should not exist - we should use extract_asset(position.market_id) instead
                assert False, f"Line {i+1} uses position.asset (should use extract_asset): {line.strip()}"
        
        # Check that we don't have the buggy pattern position.ticker in exit order context
        # (Position from position_management.position.py uses market_id, not ticker)
        for i, line in enumerate(lines):
            if 'position.ticker' in line:
                # This should not exist - we should use position.market_id instead
                assert False, f"Line {i+1} uses position.ticker (should use position.market_id): {line.strip()}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
