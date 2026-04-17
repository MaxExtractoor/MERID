"""Tests for core.error_store — frontend error persistence.

Tests:
- FrontendErrorStore CRUD (record, list, stats, rotation)
- Singleton accessor (double-checked locking)
- Convenience API (record_frontend_error)
- kalshi_shims.py endpoint wiring (POST /errors/report, GET /errors/recent, GET /errors/stats)
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

# ── Store tests ──────────────────────────────────────────────────────


class TestFrontendErrorStore(unittest.TestCase):
    """Core CRUD operations on FrontendErrorStore."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._tmpdir, "test_errors.db")
        from core.error_store import FrontendErrorStore
        self.store = FrontendErrorStore(db_path=self._db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_record_and_list(self):
        from core.error_store import FrontendError
        err = FrontendError(message="test error", route="/dashboard")
        self.store.record(err)
        errors = self.store.list_errors(limit=10)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].message, "test error")
        self.assertEqual(errors[0].route, "/dashboard")
        self.assertEqual(errors[0].id, err.id)

    def test_record_returns_error_with_id(self):
        from core.error_store import FrontendError
        err = FrontendError(message="x")
        result = self.store.record(err)
        self.assertTrue(result.id.startswith("fe-"))

    def test_list_with_limit(self):
        from core.error_store import FrontendError
        for i in range(5):
            self.store.record(FrontendError(message=f"err-{i}"))
        errors = self.store.list_errors(limit=3)
        self.assertEqual(len(errors), 3)

    def test_list_since_ms(self):
        from core.error_store import FrontendError
        old = FrontendError(message="old", created_at=time.time() - 7200)
        new = FrontendError(message="new", created_at=time.time())
        self.store.record(old)
        self.store.record(new)
        since = int((time.time() - 3600) * 1000)
        errors = self.store.list_errors(since_ms=since)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].message, "new")

    def test_list_by_route(self):
        from core.error_store import FrontendError
        self.store.record(FrontendError(message="a", route="/page-a"))
        self.store.record(FrontendError(message="b", route="/page-b"))
        errors = self.store.list_errors(route="/page-a")
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].message, "a")

    def test_total_count(self):
        from core.error_store import FrontendError
        self.assertEqual(self.store.total_count(), 0)
        self.store.record(FrontendError(message="x"))
        self.assertEqual(self.store.total_count(), 1)

    def test_get_stats(self):
        from core.error_store import FrontendError
        self.store.record(FrontendError(message="x", route="/foo"))
        stats = self.store.get_stats()
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["last_1h"], 1)
        self.assertEqual(stats["last_24h"], 1)
        self.assertTrue(stats["healthy"])
        self.assertIn("/foo", stats["top_routes"])

    def test_get_stats_empty(self):
        stats = self.store.get_stats()
        self.assertEqual(stats["total"], 0)
        self.assertIsNone(stats["last_error_at"])
        self.assertTrue(stats["healthy"])

    def test_to_dict(self):
        from core.error_store import FrontendError
        err = FrontendError(
            message="test",
            stack="Error: test\n  at foo.js:1",
            route="/portfolio",
            client_tag="v1.2.3",
        )
        self.store.record(err)
        errors = self.store.list_errors()
        d = errors[0].to_dict()
        self.assertEqual(d["message"], "test")
        self.assertEqual(d["route"], "/portfolio")
        self.assertEqual(d["client_tag"], "v1.2.3")
        self.assertIn("Error: test", d["stack"])
        self.assertIn("id", d)


class TestErrorStoreRotation(unittest.TestCase):
    """Automatic rotation / pruning of old entries."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._tmpdir, "test_errors.db")
        from core.error_store import FrontendErrorStore
        self.store = FrontendErrorStore(db_path=self._db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_rotate_by_age(self):
        from core.error_store import FrontendError
        old = FrontendError(message="old", created_at=time.time() - 100 * 86400)
        new = FrontendError(message="new", created_at=time.time())
        self.store.record(old)
        self.store.record(new)
        deleted = self.store.rotate(max_age_days=30)
        self.assertGreaterEqual(deleted, 1)
        self.assertEqual(self.store.total_count(), 1)

    def test_rotate_by_row_cap(self):
        from core.error_store import FrontendError
        for i in range(10):
            self.store.record(FrontendError(message=f"err-{i}"))
        deleted = self.store.rotate(max_age_days=9999, max_rows=5)
        self.assertEqual(self.store.total_count(), 5)
        self.assertGreaterEqual(deleted, 5)

    def test_rotate_noop_when_fresh(self):
        from core.error_store import FrontendError
        self.store.record(FrontendError(message="fresh"))
        deleted = self.store.rotate()
        self.assertEqual(deleted, 0)
        self.assertEqual(self.store.total_count(), 1)


class TestErrorStoreSingleton(unittest.TestCase):
    """Singleton accessor with double-checked locking."""

    def test_singleton_returns_same_instance(self):
        import core.error_store as mod
        # Reset singleton
        mod._store = None
        with patch.object(mod, '_DB_PATH', os.path.join(tempfile.mkdtemp(), "s.db")):
            mod._store = None
            s1 = mod.get_error_store()
            s2 = mod.get_error_store()
            self.assertIs(s1, s2)

    def test_convenience_record(self):
        import core.error_store as mod
        tmpdir = tempfile.mkdtemp()
        db = os.path.join(tmpdir, "conv.db")
        mod._store = mod.FrontendErrorStore(db_path=db)
        try:
            err = mod.record_frontend_error(
                message="convenience test",
                route="/test",
                client_tag="v0.1",
            )
            self.assertTrue(err.id.startswith("fe-"))
            self.assertEqual(err.message, "convenience test")
            errors = mod.get_error_store().list_errors()
            self.assertEqual(len(errors), 1)
        finally:
            mod._store = None
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── Endpoint wiring tests ────────────────────────────────────────────


class TestErrorEndpointWiring(unittest.TestCase):
    """Verify kalshi_shims.py has the expected error endpoints."""

    _shims_path = Path(__file__).resolve().parent.parent / "web" / "api" / "kalshi_shims.py"

    def test_errors_report_endpoint_exists(self):
        source = self._shims_path.read_text(encoding="utf-8")
        self.assertIn('@router.post("/api/v1/errors/report")', source)

    def test_errors_recent_endpoint_exists(self):
        source = self._shims_path.read_text(encoding="utf-8")
        self.assertIn('@router.get("/api/v1/errors/recent")', source)

    def test_errors_stats_endpoint_exists(self):
        source = self._shims_path.read_text(encoding="utf-8")
        self.assertIn('@router.get("/api/v1/errors/stats")', source)

    def test_errors_report_calls_real_store(self):
        source = self._shims_path.read_text(encoding="utf-8")
        self.assertIn("from core.error_store import record_frontend_error", source)

    def test_errors_report_returns_persisted_true(self):
        source = self._shims_path.read_text(encoding="utf-8")
        self.assertIn('"persisted": True', source)

    def test_errors_report_no_stub_message(self):
        """The old 'storage not yet wired' message should be gone."""
        source = self._shims_path.read_text(encoding="utf-8")
        self.assertNotIn("storage not yet wired", source)


class TestErrorStoreModuleStructure(unittest.TestCase):
    """Verify core/error_store.py module structure."""

    def test_module_imports(self):
        import core.error_store as mod
        self.assertTrue(hasattr(mod, "FrontendError"))
        self.assertTrue(hasattr(mod, "FrontendErrorStore"))
        self.assertTrue(hasattr(mod, "get_error_store"))
        self.assertTrue(hasattr(mod, "record_frontend_error"))

    def test_frontend_error_id_prefix(self):
        from core.error_store import FrontendError
        err = FrontendError(message="test")
        self.assertTrue(err.id.startswith("fe-"))

    def test_frontend_error_default_created_at(self):
        from core.error_store import FrontendError
        before = time.time()
        err = FrontendError(message="test")
        after = time.time()
        self.assertGreaterEqual(err.created_at, before)
        self.assertLessEqual(err.created_at, after)


if __name__ == "__main__":
    unittest.main()
