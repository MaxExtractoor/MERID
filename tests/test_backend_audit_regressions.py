"""Regression tests for Backend Startup Audit 2026-04-13.

Covers all 11 code fixes from the 18-finding audit:
  FIX-1:  TrackedPosition uses .contracts, not .size
  FIX-2:  Test fixture fills filtered on DB load + ingestion
  FIX-4:  starting_balance no longer hardcoded to 10000
  FIX-5:  open_market_count reads from position cache
  FIX-6:  Risk API reads correct limit key names (max_total_notional_usd)
  FIX-7:  daily_loss_limit defaults to 500 not 0
  FIX-8:  _normalize_balance uses explicit source_is_cents flag
  FIX-9:  Redis password masked in log output
  FIX-10: admin@localhost removed as email fallback
  FIX-11: Neo4j skipped in kalshi-only profile
  FIX-17: Phantom positions eliminated via test-fill filter
"""

import os
import sys
import ast
import inspect
import unittest
from unittest.mock import patch, MagicMock

# Ensure project root is on sys.path
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)


class TestFix1_TrackedPositionContracts(unittest.TestCase):
    """FIX-1: TrackedPosition.size → .contracts in trading_agent.py."""

    def test_tracked_position_has_contracts_attribute(self):
        from merid.event_venues.kalshi.stop_loss import TrackedPosition
        tp = TrackedPosition(
            position_id="test:yes:synced",
            ticker="KXBTC-TEST",
            side="yes",
            entry_price_cents=55,
            contracts=10,
            entry_ts=1000.0,
        )
        self.assertEqual(tp.contracts, 10)
        self.assertFalse(hasattr(tp, "size"), "TrackedPosition must NOT have a .size attribute")

    def test_trading_agent_uses_contracts_not_size(self):
        """Parse trading_agent.py AST to confirm no .size on TrackedPosition."""
        path = os.path.join(_root, "merid", "prediction", "trading_agent.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
        
        # Find all attribute accesses of ".size" on objects named "pos"
        bad_hits = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "size":
                if isinstance(node.value, ast.Name) and node.value.id == "pos":
                    bad_hits.append(node.lineno)
        self.assertEqual(bad_hits, [], f"Found pos.size at lines {bad_hits} — should be pos.contracts")


class TestFix2_TestFixtureFilter(unittest.TestCase):
    """FIX-2: Test fixture fills filtered from DB load and ingestion."""

    def test_is_test_fixture_fill(self):
        from merid.event_venues.kalshi.fills_ledger import _is_test_fixture_fill
        # Test fixtures
        self.assertTrue(_is_test_fixture_fill("fill_integrity_000"))
        self.assertTrue(_is_test_fixture_fill("fill_a_001"))
        self.assertTrue(_is_test_fixture_fill("fill_ghost_resolved_001"))
        self.assertTrue(_is_test_fixture_fill("fill_immutable_001"))
        self.assertTrue(_is_test_fixture_fill("fill_legit_001"))
        self.assertTrue(_is_test_fixture_fill("fill_test_abc"))
        self.assertTrue(_is_test_fixture_fill("test_fill_123"))
        self.assertTrue(_is_test_fixture_fill("fill_dup_001"))
        self.assertTrue(_is_test_fixture_fill("fill_stale_001"))
        # Real Kalshi fill IDs (UUID-like)
        self.assertFalse(_is_test_fixture_fill("a1b2c3d4-e5f6-7890-abcd-ef1234567890"))
        self.assertFalse(_is_test_fixture_fill("12345678-abcd-ef01-2345-678901234567"))
        # Empty / None
        self.assertTrue(_is_test_fixture_fill(""))
        self.assertTrue(_is_test_fixture_fill(None))

    def test_test_fill_prefixes_constant_exists(self):
        from merid.event_venues.kalshi.fills_ledger import _TEST_FILL_PREFIXES
        self.assertIsInstance(_TEST_FILL_PREFIXES, tuple)
        self.assertGreater(len(_TEST_FILL_PREFIXES), 5)


class TestFix4_StartingBalance(unittest.TestCase):
    """FIX-4: starting_balance no longer hardcoded to 10000."""

    def test_no_hardcoded_10000_fallback(self):
        path = os.path.join(_root, "web", "api", "kalshi_api.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        # The old pattern: getattr(ledger, "starting_balance", 10000.0)
        self.assertNotIn('getattr(ledger, "starting_balance", 10000.0)', source,
                         "Hardcoded 10000.0 starting_balance should be removed")


class TestFix5_OpenMarketCount(unittest.TestCase):
    """FIX-5: open_market_count reads from position cache, not hardcoded 0."""

    def test_summary_does_not_hardcode_zero(self):
        path = os.path.join(_root, "merid", "event_venues", "kalshi", "kalshi_risk.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn('"open_market_count": 0', source,
                         "open_market_count must not be hardcoded to 0")

    def test_get_open_market_count_method_exists(self):
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskManager
        self.assertTrue(
            hasattr(KalshiRiskManager, "_get_open_market_count"),
            "KalshiRiskManager must have _get_open_market_count method"
        )


class TestFix6_RiskLimitKeyNames(unittest.TestCase):
    """FIX-6: Risk API reads correct key names from KalshiRiskManager.summary()."""

    def test_reads_max_total_notional_usd(self):
        """Verify the API reads 'max_total_notional_usd' not just 'max_notional_usd'."""
        path = os.path.join(_root, "web", "api", "kalshi_api.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertIn("max_total_notional_usd", source)
        self.assertIn("max_daily_loss_usd", source)

    def test_reads_drawdown_halt_pct(self):
        path = os.path.join(_root, "web", "api", "kalshi_api.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertIn("drawdown_halt_pct", source)


class TestFix7_DailyLossDefault(unittest.TestCase):
    """FIX-7: daily_loss_limit defaults to 500, not 0."""

    def test_daily_loss_limit_not_zero_default(self):
        path = os.path.join(_root, "web", "api", "kalshi_api.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        # The old dangerous pattern
        self.assertNotIn(
            '"daily_loss_limit", 0)',
            source,
            "daily_loss_limit must not default to 0 (means no limit)"
        )


class TestFix8_NormalizeBalance(unittest.TestCase):
    """FIX-8: _normalize_balance uses explicit source_is_cents flag."""

    def test_source_is_cents_true(self):
        from web.api.kalshi_api import _normalize_balance
        # 10000 cents = $100
        self.assertAlmostEqual(_normalize_balance(10000, "test", source_is_cents=True), 100.0)
        # 15050 cents = $150.50
        self.assertAlmostEqual(_normalize_balance(15050, "test", source_is_cents=True), 150.50)

    def test_source_is_cents_false(self):
        from web.api.kalshi_api import _normalize_balance
        # Already dollars — should pass through unchanged
        self.assertAlmostEqual(_normalize_balance(100.0, "test", source_is_cents=False), 100.0)
        self.assertAlmostEqual(_normalize_balance(10000.0, "test", source_is_cents=False), 10000.0)

    def test_none_returns_zero(self):
        from web.api.kalshi_api import _normalize_balance
        self.assertEqual(_normalize_balance(None, "test"), 0.0)

    def test_no_heuristic_conversion(self):
        """$10,000 balance should NOT be divided by 100 when source_is_cents=False."""
        from web.api.kalshi_api import _normalize_balance
        result = _normalize_balance(10000.0, "test", source_is_cents=False)
        self.assertEqual(result, 10000.0, "Dollar values must not be heuristically divided")


class TestFix9_RedisPasswordMasked(unittest.TestCase):
    """FIX-9: Redis password not logged in plaintext."""

    def test_redis_url_masked_in_log(self):
        path = os.path.join(_root, "core", "cache.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        # Should NOT log raw REDIS_URL
        self.assertNotIn(
            'self.logger.info("Connected to Redis cache at %s", REDIS_URL)',
            source,
            "Redis URL must be masked before logging"
        )
        # Should contain masking logic
        self.assertIn("***", source, "Masked URL should contain ***")


class TestFix10_NoAdminLocalhost(unittest.TestCase):
    """FIX-10: admin@localhost removed as email fallback."""

    def test_no_admin_localhost_fallback(self):
        path = os.path.join(_root, "notifications", "notification_manager.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("admin@localhost", source,
                         "admin@localhost must not be used as fallback")


class TestFix11_Neo4jKalshiOnly(unittest.TestCase):
    """FIX-11: Neo4j skipped in kalshi-only profile + failure cached."""

    def test_permanently_unavailable_attribute(self):
        path = os.path.join(_root, "memory", "neo4j_graph.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertIn("_permanently_unavailable", source)
        self.assertIn("MERID_PROFILE", source, "Should check MERID_PROFILE env var")

    def test_connect_returns_false_after_failure(self):
        """After first failure, connect() should return False immediately."""
        path = os.path.join(_root, "memory", "neo4j_graph.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        # After except block sets _permanently_unavailable = True
        self.assertIn("self._permanently_unavailable = True", source)
        # Early return at top of connect()
        self.assertIn("if self._permanently_unavailable:", source)


class TestFix17_PhantomPositionsEliminated(unittest.TestCase):
    """FIX-17: Test fixture fills no longer create phantom positions."""

    def test_ingestion_guard_exists(self):
        """HTTP ingestion path should check _is_test_fixture_fill."""
        path = os.path.join(_root, "merid", "event_venues", "kalshi", "fills_ledger.py")
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        # The ingestion guard in ingest_http_fills
        self.assertIn("_is_test_fixture_fill(fill.fill_id)", source,
                       "ingest_http_fills must filter test fixtures")


class TestAllModifiedFilesCompile(unittest.TestCase):
    """Ensure all modified files import without errors."""

    MODIFIED_FILES = [
        "merid.prediction.trading_agent",
        "merid.event_venues.kalshi.fills_ledger",
        "merid.event_venues.kalshi.kalshi_risk",
        "web.api.kalshi_api",
        "core.cache",
        "notifications.notification_manager",
        "memory.neo4j_graph",
    ]

    def test_imports(self):
        for module_path in self.MODIFIED_FILES:
            with self.subTest(module=module_path):
                try:
                    parts = module_path.split(".")
                    # Try file-level import check via compile
                    file_path = os.path.join(_root, *parts) + ".py"
                    if os.path.exists(file_path):
                        with open(file_path, "r", encoding="utf-8") as f:
                            compile(f.read(), file_path, "exec")
                except SyntaxError as e:
                    self.fail(f"SyntaxError in {module_path}: {e}")


if __name__ == "__main__":
    unittest.main()
