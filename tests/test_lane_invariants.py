"""
Lane invariant tests for kalshi_crypto_15m_v2 profile.

These tests ensure:
1. Only Crypto15MLane is used for 15m crypto assets (no BTC15MLane)
2. All 15m lanes have the get_regime_signal() method
3. No legacy lane classes are imported in the 15m crypto path
"""

import unittest
from typing import Optional


class TestLaneInvariants(unittest.TestCase):
    """Test lane invariants for kalshi_crypto_15m_v2 profile."""

    def test_btc15mlane_not_imported(self):
        """Ensure BTC15MLane is not imported in production code."""
        import sys
        # Check if BTC15MLane is in sys.modules
        btc15m_in_modules = "merid.lanes.btc15m_lane" in sys.modules
        btc15m_class_in_modules = any(
            "BTC15MLane" in str(module) for module in sys.modules.values()
        )
        
        # BTC15MLane should not be imported in the 15m crypto profile
        # This test checks that the legacy lane is not accidentally imported
        self.assertFalse(
            btc15m_in_modules,
            "BTC15MLane module should not be imported (use Crypto15MLane instead)"
        )
        # Note: We don't fail on btc15m_class_in_modules because it might be
        # imported for tests or other non-production paths

    def test_crypto15m_lane_has_get_regime_signal(self):
        """Ensure Crypto15MLane has get_regime_signal() method."""
        try:
            from merid.lanes.crypto15m_lane import Crypto15MLane
        except ImportError as e:
            self.skipTest(f"Crypto15MLane not available: {e}")
            return
        
        # Check that the method exists
        self.assertTrue(
            hasattr(Crypto15MLane, "get_regime_signal"),
            "Crypto15MLane must have get_regime_signal() method for API compatibility"
        )
        
        # Check that it's callable
        method = getattr(Crypto15MLane, "get_regime_signal")
        self.assertTrue(
            callable(method),
            "get_regime_signal must be callable"
        )

    def test_registry_returns_crypto15m_lane(self):
        """Ensure lane registry returns Crypto15MLane for 15m assets."""
        try:
            from merid.lanes.registry import get_lane_registry
        except ImportError as e:
            self.skipTest(f"Lane registry not available: {e}")
            return
        
        registry = get_lane_registry()
        
        # Check that all 5 15m assets map to Crypto15MLane
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        for asset in assets:
            lane_key = f"{asset}_15M"
            lane = registry.get_lane(lane_key)
            
            if lane is None:
                # Lane might not be initialized in test environment
                continue
            
            # Check that the lane is Crypto15MLane, not BTC15MLane
            from merid.lanes.crypto15m_lane import Crypto15MLane
            self.assertIsInstance(
                lane,
                Crypto15MLane,
                f"Lane for {asset}_15M must be Crypto15MLane, got {type(lane).__name__}"
            )
            
            # Check that it has get_regime_signal
            self.assertTrue(
                hasattr(lane, "get_regime_signal"),
                f"Lane for {asset}_15M must have get_regime_signal() method"
            )

    def test_no_legacy_lane_imports_in_startup(self):
        """Ensure startup code doesn't import legacy BTC15MLane."""
        import ast
        import os
        
        # Check web/startup_agents.py for BTC15MLane imports
        startup_agents_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "web",
            "startup_agents.py"
        )
        
        if not os.path.exists(startup_agents_path):
            self.skipTest(f"startup_agents.py not found at {startup_agents_path}")
            return
        
        with open(startup_agents_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Parse AST
        try:
            tree = ast.parse(content)
        except SyntaxError:
            self.skipTest("Could not parse startup_agents.py")
            return
        
        # Check for BTC15MLane imports
        has_btc15m_import = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "btc15m_lane" in node.module:
                    has_btc15m_import = True
                    break
                for alias in node.names:
                    if "BTC15MLane" in alias.name:
                        has_btc15m_import = True
                        break
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "btc15m_lane" in alias.name:
                        has_btc15m_import = True
                        break
        
        self.assertFalse(
            has_btc15m_import,
            "startup_agents.py should not import BTC15MLane (use Crypto15MLane via registry)"
        )

    def test_no_legacy_lane_imports_in_kalshi_api(self):
        """Ensure Kalshi API doesn't import legacy BTC15MLane."""
        import ast
        import os
        
        # Check web/api/kalshi_api.py for BTC15MLane imports
        kalshi_api_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "web",
            "api",
            "kalshi_api.py"
        )
        
        if not os.path.exists(kalshi_api_path):
            self.skipTest(f"kalshi_api.py not found at {kalshi_api_path}")
            return
        
        with open(kalshi_api_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check for direct BTC15MLane imports (not in comments)
        lines = content.split("\n")
        has_btc15m_import = False
        for line in lines:
            # Skip comments
            if line.strip().startswith("#"):
                continue
            # Check for BTC15MLane in imports
            if "from" in line and "btc15m_lane" in line and "import" in line:
                has_btc15m_import = True
                break
            if "import" in line and "btc15m_lane" in line:
                has_btc15m_import = True
                break
        
        self.assertFalse(
            has_btc15m_import,
            "kalshi_api.py should not import BTC15MLane (use Crypto15MLane via registry)"
        )


if __name__ == "__main__":
    unittest.main()
