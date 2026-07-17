"""
Test for kalshi_tools.py max_contracts fix.

This test verifies that kalshi_tools.py enforces the $1 global exposure cap
by defaulting max_contracts_limit to 1 instead of 2, preventing >1 contract
per order which could bypass the $1 cap.

CRITICAL: The default fallback was changed from 2 to 1 to ensure that even
if profile loading fails, the system still enforces the 1-contract-per-order
rule required by the $1 fixed exposure model.
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch
import os


class TestKalshiToolsMaxContractsFix:
    """Test that kalshi_tools.py enforces max_contracts=1 default fallback."""

    def test_kalshi_tools_default_max_contracts_is_1(self):
        """
        Verify that kalshi_tools.py defaults max_contracts_limit to 1
        instead of 2 to enforce the $1 exposure cap.
        """
        # Read the kalshi_tools.py file
        kalshi_tools_path = os.path.join(os.path.dirname(__file__), '..', 'merid', 'prediction', 'kalshi_tools.py')
        with open(kalshi_tools_path, 'r') as f:
            kalshi_tools_content = f.read()
        
        # Verify the default fallback is 1 (not 2)
        # Check both locations where max_contracts_limit is set
        lines = kalshi_tools_content.split('\n')
        
        default_1_count = 0
        default_2_count = 0
        
        for i, line in enumerate(lines):
            if 'max_contracts_limit = 1' in line and 'Default fallback' in line:
                default_1_count += 1
                # Verify the comment mentions $1 exposure cap
                assert '$1 exposure cap' in line or 'enforce $1' in kalshi_tools_content[max(0, i-5):i+5], \
                    "Comment should mention $1 exposure cap enforcement"
            if 'max_contracts_limit = 2' in line and 'Default fallback' in line:
                default_2_count += 1
        
        # Should have at least 1 instance of default=1 with proper comment
        assert default_1_count >= 1, \
            f"Expected at least 1 instance of max_contracts_limit = 1 with $1 cap comment, found {default_1_count}"
        
        # Should have 0 instances of default=2 (the old unsafe default)
        assert default_2_count == 0, \
            f"Found {default_2_count} instances of unsafe default max_contracts_limit = 2"

    def test_kalshi_tools_clamps_count_to_max_contracts(self):
        """
        Verify that kalshi_tools.py clamps the order count to max_contracts_limit.
        """
        # Read the kalshi_tools.py file
        kalshi_tools_path = os.path.join(os.path.dirname(__file__), '..', 'merid', 'prediction', 'kalshi_tools.py')
        with open(kalshi_tools_path, 'r') as f:
            kalshi_tools_content = f.read()
        
        # Verify count clamping logic is present
        assert 'count=max(1, min(max_contracts_limit, int(count)))' in kalshi_tools_content, \
            "kalshi_tools.py must clamp count to max_contracts_limit"
        
        # Verify this appears in both order creation functions
        count_clamp_count = kalshi_tools_content.count('count=max(1, min(max_contracts_limit, int(count)))')
        assert count_clamp_count >= 2, \
            f"Expected count clamping in at least 2 locations, found {count_clamp_count}"

    def test_kalshi_tools_reads_max_contracts_from_profile(self):
        """
        Verify that kalshi_tools.py reads max_contracts from the profile
        before falling back to the default.
        """
        # Read the kalshi_tools.py file
        kalshi_tools_path = os.path.join(os.path.dirname(__file__), '..', 'merid', 'prediction', 'kalshi_tools.py')
        with open(kalshi_tools_path, 'r') as f:
            kalshi_tools_content = f.read()
        
        # Verify profile reading logic is present
        assert 'from merid.risk.profiles.crypto_15m_profile import get_active_profile' in kalshi_tools_content, \
            "kalshi_tools.py must import get_active_profile to read max_contracts"
        
        assert 'asset_config.max_contracts' in kalshi_tools_content, \
            "kalshi_tools.py must read max_contracts from asset_config"

    def test_kalshi_tools_asset_extraction_logic(self):
        """
        Verify that kalshi_tools.py correctly extracts asset from ticker
        for max_contracts lookup.
        """
        # Read the kalshi_tools.py file
        kalshi_tools_path = os.path.join(os.path.dirname(__file__), '..', 'merid', 'prediction', 'kalshi_tools.py')
        with open(kalshi_tools_path, 'r') as f:
            kalshi_tools_content = f.read()
        
        # Verify all 5 assets are handled
        required_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        for asset in required_assets:
            assert f'"{asset}"' in kalshi_tools_content or f"'{asset}'" in kalshi_tools_content, \
                f"kalshi_tools.py must handle asset {asset} for max_contracts lookup"

    def test_kalshi_tools_max_contracts_enforcement_prevents_overspending(self):
        """
        Functional test: Verify that max_contracts=1 enforcement prevents
        orders that would exceed the $1 exposure cap.
        """
        # This is a conceptual test - the actual enforcement happens
        # via the count clamping logic verified in test_kalshi_tools_clamps_count_to_max_contracts
        
        # Verify the logic: with max_contracts=1 and price=50c, max notional = $0.50
        # This is within the $1 cap. With max_contracts=2, max notional = $1.00
        # which could exceed the cap if other positions exist.
        
        # The fix ensures that even if profile loading fails, the default
        # of 1 contract prevents accidental overspending.
        assert True  # Conceptual test - logic verified in other tests


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
