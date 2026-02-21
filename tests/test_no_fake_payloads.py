"""
Regression tests: no fabricated data in stub/fallback API responses.

Every endpoint served by ``missing_endpoints_router`` that returns ``_stub: True``
MUST also carry ``data_mode: "offline"`` and ``_stub_message``.

Additionally, no endpoint in ``real_data_endpoints`` should embed ``Math.random``-style
fabricated numbers when it falls back — every fallback dict must include
``_stub: True`` or ``data_mode: "offline"``.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _build_missing_client() -> TestClient:
    """TestClient with only the missing_endpoints router."""
    from web.api.missing_endpoints import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _build_real_client() -> TestClient:
    """TestClient with only the real_data_endpoints router."""
    from web.api.real_data_endpoints import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# GET endpoints from missing_endpoints that ALWAYS return stub data.
# Endpoints that try real data first (and may succeed) are excluded.
STUB_ENDPOINTS = [
    "/api/v1/wallet/balances",
    "/api/v1/treasury/overview",
    "/api/v1/explainability/decisions",
    "/api/v1/risk-metrics/agents",
    "/api/v1/swarm/status",
    "/api/v1/arbitrage/scanner",
    "/api/v1/mining/overview",
    "/api/v1/institutional/overview",
    "/api/v1/plugins/list",
    "/api/v1/markets/all",
    "/api/v1/pipeline/leaderboard",
]

# Endpoints that try real data first; when they DO stub, they must still carry flags.
REAL_FIRST_ENDPOINTS = [
    "/api/v1/social/feed",
    "/api/v1/consensus/plans",
    "/api/v1/consensus/metrics",
    "/api/v1/consensus/opinions",
    "/api/v1/consensus/summary",
]


class TestStubEndpointsCarryOfflineFlags(unittest.TestCase):
    """Every stub endpoint MUST have _stub, _stub_message, and data_mode."""

    @classmethod
    def setUpClass(cls):
        cls.client = _build_missing_client()

    def test_all_stub_endpoints_have_stub_flag(self):
        """_stub: True must be present on every stub response."""
        for ep in STUB_ENDPOINTS:
            with self.subTest(endpoint=ep):
                resp = self.client.get(ep)
                self.assertEqual(resp.status_code, 200, f"{ep} returned {resp.status_code}")
                data = resp.json()
                self.assertTrue(
                    data.get("_stub") is True,
                    f"{ep} missing _stub: True — got keys: {list(data.keys())}"
                )

    def test_all_stub_endpoints_have_data_mode_offline(self):
        """data_mode: 'offline' must be present on every stub response."""
        for ep in STUB_ENDPOINTS:
            with self.subTest(endpoint=ep):
                resp = self.client.get(ep)
                data = resp.json()
                self.assertEqual(
                    data.get("data_mode"), "offline",
                    f"{ep} missing data_mode: 'offline'"
                )

    def test_all_stub_endpoints_have_stub_message(self):
        """_stub_message must be a non-empty string on every stub response."""
        for ep in STUB_ENDPOINTS:
            with self.subTest(endpoint=ep):
                resp = self.client.get(ep)
                data = resp.json()
                msg = data.get("_stub_message", "")
                self.assertIsInstance(msg, str, f"{ep} _stub_message is not a string")
                self.assertTrue(len(msg) > 0, f"{ep} _stub_message is empty")


class TestNoRandomInStubEndpoints(unittest.TestCase):
    """Stub endpoints must not import or use random."""

    def test_missing_endpoints_does_not_import_random(self):
        """The missing_endpoints module should not import random."""
        import web.api.missing_endpoints as mod
        source_file = mod.__file__
        with open(source_file, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn(
            "import random",
            source,
            "missing_endpoints.py still imports random — potential fake data source"
        )
        self.assertNotIn(
            "from random",
            source,
            "missing_endpoints.py still imports from random — potential fake data source"
        )

    def test_missing_endpoints_no_random_calls(self):
        """No random.random(), random.uniform(), etc. in module source."""
        import web.api.missing_endpoints as mod
        with open(mod.__file__, "r", encoding="utf-8") as f:
            source = f.read()
        for fn in ["random()", "random.uniform", "random.randint", "random.choice"]:
            self.assertNotIn(
                fn, source,
                f"missing_endpoints.py contains '{fn}' — fake data source"
            )


def _non_comment_lines(filepath: str) -> str:
    """Return source with comment-only lines stripped (to avoid false positives)."""
    lines = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.lstrip()
            if stripped.startswith("#") or stripped.startswith("//"):
                continue
            lines.append(line)
    return "".join(lines)


class TestNoRandomInRealEndpoints(unittest.TestCase):
    """real_data_endpoints.py must not use random for data generation."""

    def test_real_endpoints_no_random_import(self):
        import web.api.real_data_endpoints as mod
        source = _non_comment_lines(mod.__file__)
        self.assertNotIn(
            "import random",
            source,
            "real_data_endpoints.py still imports random"
        )

    def test_real_endpoints_no_random_calls(self):
        import web.api.real_data_endpoints as mod
        source = _non_comment_lines(mod.__file__)
        for fn in ["random.uniform", "random.randint", "random.choice"]:
            self.assertNotIn(
                fn, source,
                f"real_data_endpoints.py contains '{fn}' — fake data"
            )


class TestRealEndpointFallbacksAreTagged(unittest.TestCase):
    """Every _offline() call in real_data_endpoints should produce _stub: True."""

    def test_offline_helper_tags_correctly(self):
        """The _offline helper must set _stub, _stub_message, data_mode."""
        from web.api.real_data_endpoints import _offline
        result = _offline({"foo": "bar"}, reason="test offline")
        self.assertTrue(result["_stub"])
        self.assertEqual(result["data_mode"], "offline")
        self.assertEqual(result["_stub_message"], "test offline")

    def test_offline_helper_preserves_data(self):
        """The _offline helper must not destroy existing keys."""
        from web.api.real_data_endpoints import _offline
        original = {"count": 5, "items": [1, 2, 3]}
        result = _offline(original, reason="x")
        self.assertEqual(result["count"], 5)
        self.assertEqual(result["items"], [1, 2, 3])


class TestNoFakeDataInFrontendCatchBlocks(unittest.TestCase):
    """Scan frontend source for fabricated fallback data patterns."""

    FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "web", "react", "src")

    def _scan_files(self, extensions=(".tsx", ".ts")):
        """Yield (filepath, content) for all matching files."""
        for root, _dirs, files in os.walk(self.FRONTEND_DIR):
            for f in files:
                if any(f.endswith(ext) for ext in extensions):
                    path = os.path.join(root, f)
                    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                        yield path, fh.read()

    # Files where Math.random() is used for legitimate non-data purposes
    # (e.g., WebSocket reconnect jitter)
    MATH_RANDOM_ALLOWLIST = {"TradeFloor.tsx"}

    def test_no_math_random_in_views(self):
        """Views should not use Math.random() for data generation."""
        views_dir = os.path.join(self.FRONTEND_DIR, "views")
        if not os.path.isdir(views_dir):
            self.skipTest("views directory not found")
        for root, _dirs, files in os.walk(views_dir):
            if "__tests__" in root or "__test__" in root:
                continue
            for f in files:
                if f.endswith(".tsx") and not f.startswith("__") and f not in self.MATH_RANDOM_ALLOWLIST:
                    path = os.path.join(root, f)
                    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                        content = fh.read()
                    self.assertNotIn(
                        "Math.random()",
                        content,
                        f"{f} contains Math.random() — potential fake data"
                    )

    def test_no_fallback_mock_data_comment(self):
        """No '// Fallback mock data' comments should remain in views/components."""
        for path, content in self._scan_files():
            basename = os.path.basename(path)
            if "__test" in basename.lower():
                continue
            self.assertNotIn(
                "// Fallback mock data",
                content,
                f"{basename} still contains '// Fallback mock data' comment"
            )


if __name__ == "__main__":
    unittest.main()
