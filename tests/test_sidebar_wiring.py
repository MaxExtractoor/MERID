"""Sidebar ↔ Views ↔ App.tsx ↔ Backend wiring invariant tests.

Ensures the sidebar config, View type, App routes, and backend endpoints
never drift out of sync. Run after any navigation or routing change.

Invariants enforced:
1. Every sidebar item href exists in views.ts
2. Every sidebar item href has a route in App.tsx
3. Every links_to reference resolves to an existing sidebar item id
4. Every workflow phase view is a valid sidebar href
5. Sidebar config sections match Sidebar.tsx sections
6. No duplicate sidebar item ids
7. Backend endpoints referenced in sidebar config are reachable
8. Every sidebar endpoint has a matching API_ENDPOINTS constant
9. Frontend sidebarManifest.ts matches sidebar_config.py
10. Paper session infrastructure: paper-trading, trade-mode, reconciliation, audit-trail
"""

import json
import os
import re
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Set

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ── Helpers to parse source files ─────────────────────────────────

def _read(relpath: str) -> str:
    p = Path(PROJECT_ROOT) / relpath
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _get_sidebar_config():
    """Import the canonical sidebar config from Python."""
    from web.api.sidebar_config import SIDEBAR_SECTIONS, WORKFLOW_PHASES
    return SIDEBAR_SECTIONS, WORKFLOW_PHASES


def _extract_view_types() -> Set[str]:
    """Parse views.ts to extract all View union members."""
    src = _read("web/react/src/types/views.ts")
    return set(re.findall(r'"([a-z][a-z0-9-]*)"', src))


def _extract_app_routes() -> Set[str]:
    """Parse App.tsx to extract all view === "..." route keys."""
    src = _read("web/react/src/App.tsx")
    return set(re.findall(r'view === "([a-z][a-z0-9-]*)"', src))


def _extract_sidebar_tsx_hrefs() -> Set[str]:
    """Parse Sidebar.tsx to extract all href values from the component arrays."""
    src = _read("web/react/src/components/Sidebar.tsx")
    return set(re.findall(r"href:\s*'([a-z][a-z0-9-]*)'", src))


def _flatten_sidebar_items(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten all sidebar items from all sections."""
    items = []
    for section in sections:
        items.extend(section.get("items", []))
    return items


# ── Test Classes ──────────────────────────────────────────────────

class TestSidebarConfigCompleteness(unittest.TestCase):
    """Every sidebar item has a matching View type and App route."""

    @classmethod
    def setUpClass(cls):
        cls.sections, cls.phases = _get_sidebar_config()
        cls.items = _flatten_sidebar_items(cls.sections)
        cls.view_types = _extract_view_types()
        cls.app_routes = _extract_app_routes()
        cls.sidebar_tsx_hrefs = _extract_sidebar_tsx_hrefs()

    def test_sidebar_has_items(self):
        self.assertGreaterEqual(len(self.items), 17, "Expected at least 17 sidebar items")

    def test_every_sidebar_href_in_view_types(self):
        """Every sidebar item href must exist in views.ts."""
        missing = []
        for item in self.items:
            href = item["href"]
            if href not in self.view_types:
                missing.append(f"{item['id']} → href='{href}'")
        self.assertEqual(missing, [], f"Sidebar hrefs missing from views.ts: {missing}")

    def test_every_sidebar_href_in_app_routes(self):
        """Every sidebar item href must have a route in App.tsx."""
        missing = []
        for item in self.items:
            href = item["href"]
            if href not in self.app_routes:
                missing.append(f"{item['id']} → href='{href}'")
        self.assertEqual(missing, [], f"Sidebar hrefs missing from App.tsx routes: {missing}")

    def test_sidebar_config_matches_sidebar_tsx(self):
        """Every href in sidebar_config.py should also appear in Sidebar.tsx."""
        config_hrefs = {item["href"] for item in self.items}
        missing = config_hrefs - self.sidebar_tsx_hrefs
        self.assertEqual(missing, set(), f"Config hrefs missing from Sidebar.tsx: {missing}")

    def test_sidebar_tsx_matches_sidebar_config(self):
        """Every href in Sidebar.tsx should also appear in sidebar_config.py."""
        config_hrefs = {item["href"] for item in self.items}
        extra = self.sidebar_tsx_hrefs - config_hrefs
        self.assertEqual(extra, set(), f"Sidebar.tsx hrefs not in config: {extra}")

    def test_five_sections(self):
        self.assertEqual(len(self.sections), 5, "Expected exactly 5 sidebar sections")

    def test_section_ids_unique(self):
        ids = [s["id"] for s in self.sections]
        self.assertEqual(len(ids), len(set(ids)), f"Duplicate section ids: {ids}")


class TestSidebarItemIntegrity(unittest.TestCase):
    """Each sidebar item has required fields and no duplicates."""

    @classmethod
    def setUpClass(cls):
        cls.sections, _ = _get_sidebar_config()
        cls.items = _flatten_sidebar_items(cls.sections)
        cls.item_ids = {item["id"] for item in cls.items}

    def test_no_duplicate_ids(self):
        ids = [item["id"] for item in self.items]
        dupes = [x for x in ids if ids.count(x) > 1]
        self.assertEqual(dupes, [], f"Duplicate sidebar item ids: {set(dupes)}")

    def test_required_fields(self):
        required = {"id", "label", "href", "icon", "color", "endpoints", "workflow_phase", "links_to"}
        for item in self.items:
            missing = required - set(item.keys())
            self.assertEqual(missing, set(), f"Item '{item.get('id', '?')}' missing fields: {missing}")

    def test_every_links_to_resolves(self):
        """Every links_to reference must point to an existing sidebar item id."""
        broken = []
        for item in self.items:
            for link in item.get("links_to", []):
                if link not in self.item_ids:
                    broken.append(f"{item['id']} → links_to '{link}'")
        self.assertEqual(broken, [], f"Broken links_to references: {broken}")

    def test_endpoints_are_strings(self):
        for item in self.items:
            for ep in item.get("endpoints", []):
                self.assertIsInstance(ep, str, f"Item '{item['id']}' has non-string endpoint: {ep}")
                self.assertTrue(ep.startswith("/api"), f"Item '{item['id']}' endpoint doesn't start with /api: {ep}")


class TestWorkflowPhases(unittest.TestCase):
    """Workflow phases reference only valid sidebar hrefs."""

    @classmethod
    def setUpClass(cls):
        cls.sections, cls.phases = _get_sidebar_config()
        cls.items = _flatten_sidebar_items(cls.sections)
        cls.valid_hrefs = {item["href"] for item in cls.items}

    def test_phases_exist(self):
        self.assertGreaterEqual(len(self.phases), 5)

    def test_phase_views_are_valid_hrefs(self):
        """Every view in a workflow phase must be a valid sidebar href."""
        broken = []
        for phase in self.phases:
            for view in phase.get("views", []):
                if view not in self.valid_hrefs:
                    broken.append(f"phase '{phase['id']}' → view '{view}'")
        self.assertEqual(broken, [], f"Workflow phase views not in sidebar: {broken}")

    def test_phase_order_sequential(self):
        orders = [p["order"] for p in self.phases]
        self.assertEqual(orders, sorted(orders), "Workflow phases not in order")


class TestAnalyticsSectionExists(unittest.TestCase):
    """Analytics section exists with sentiment and vol views."""

    @classmethod
    def setUpClass(cls):
        cls.sections, _ = _get_sidebar_config()
        cls.items = _flatten_sidebar_items(cls.sections)

    def test_analytics_section_exists(self):
        """There should be an 'analytics' section."""
        section_ids = [s["id"] for s in self.sections]
        self.assertIn("analytics", section_ids)

    def test_sentiment_view_exists(self):
        """Analytics should contain kalshi-sentiment."""
        hrefs = [item["href"] for item in self.items]
        self.assertIn("kalshi-sentiment", hrefs)

    def test_vol_dashboard_exists(self):
        """Analytics should contain kalshi-vol-dashboard."""
        hrefs = [item["href"] for item in self.items]
        self.assertIn("kalshi-vol-dashboard", hrefs)


class TestBackendEndpointReachability(unittest.TestCase):
    """Sidebar endpoints exist as registered FastAPI routes."""

    @classmethod
    def setUpClass(cls):
        cls.sections, _ = _get_sidebar_config()
        cls.items = _flatten_sidebar_items(cls.sections)
        # Collect all unique endpoints from sidebar config
        cls.all_endpoints = set()
        for item in cls.items:
            for ep in item.get("endpoints", []):
                cls.all_endpoints.add(ep)

        # Get all registered FastAPI routes from the module-level app
        cls.registered_routes = set()
        try:
            from web.main import app
            for route in app.routes:
                if hasattr(route, "path"):
                    cls.registered_routes.add(route.path)
            # Also check sub-routers (mounted apps have nested routes)
            if not cls.registered_routes:
                from web.main import create_app
                test_app = create_app()
                for route in test_app.routes:
                    if hasattr(route, "path"):
                        cls.registered_routes.add(route.path)
        except Exception as exc:
            print(f"WARNING: Could not load FastAPI routes: {exc}")
            cls.registered_routes = set()

    def test_has_registered_routes(self):
        if not self.registered_routes:
            self.skipTest("Could not load FastAPI app (missing optional deps in test env)")
        self.assertGreater(len(self.registered_routes), 50,
                           "Expected at least 50 registered FastAPI routes")

    def test_sidebar_endpoints_registered(self):
        """Every endpoint in sidebar config should be a registered FastAPI route."""
        if not self.registered_routes:
            self.skipTest("Could not load FastAPI routes")

        missing = []
        for ep in sorted(self.all_endpoints):
            if ep not in self.registered_routes:
                missing.append(ep)
        self.assertEqual(missing, [],
                         f"Sidebar endpoints not registered in FastAPI: {missing}")


class TestFrontendConstants(unittest.TestCase):
    """Key API constants exist in constants.ts."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read("web/react/src/config/constants.ts")

    def test_trade_mode_constant(self):
        self.assertIn("TRADE_MODE", self.src)

    def test_reconciliation_constants(self):
        self.assertIn("RECONCILIATION_RUN", self.src)
        self.assertIn("RECONCILIATION_STATUS", self.src)

    def test_audit_trail_constants(self):
        self.assertIn("AUDIT_TRAIL_SUMMARY", self.src)
        self.assertIn("AUDIT_TRAIL_ENTRIES", self.src)

    def test_ui_sidebar_constants(self):
        self.assertIn("UI_SIDEBAR", self.src)
        self.assertIn("UI_MODE_INDICATOR", self.src)
        self.assertIn("UI_WORKFLOW", self.src)

    def test_kalshi_grid_constants(self):
        self.assertIn("KALSHI_GRID_STATUS", self.src)
        self.assertIn("KALSHI_GRID_MATRIX", self.src)
        self.assertIn("KALSHI_GRID_AGENTS", self.src)

    def test_kalshi_deep_constants(self):
        self.assertIn("KALSHI_MARKETS", self.src)
        self.assertIn("KALSHI_POSITIONS", self.src)
        self.assertIn("KALSHI_PNL", self.src)
        self.assertIn("KALSHI_HEALTH", self.src)


class TestEndpointConstantCoverage(unittest.TestCase):
    """Every sidebar endpoint has a matching API_ENDPOINTS constant in constants.ts."""

    @classmethod
    def setUpClass(cls):
        cls.sections, _ = _get_sidebar_config()
        cls.items = _flatten_sidebar_items(cls.sections)
        cls.constants_src = _read("web/react/src/config/constants.ts")
        # Extract all static string endpoint values from API_ENDPOINTS
        cls.constant_values = set(
            re.findall(r':\s*"(/api/[^"]+)"', cls.constants_src)
        )

    def test_every_sidebar_endpoint_has_constant(self):
        """Every endpoint in sidebar config items should appear as a value in API_ENDPOINTS."""
        missing = []
        for item in self.items:
            for ep in item.get("endpoints", []):
                if ep not in self.constant_values:
                    missing.append(f"{item['id']}: {ep}")
        self.assertEqual(
            missing, [],
            f"Sidebar endpoints without a matching API_ENDPOINTS constant:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )

    def test_sidebar_manifest_matches_config_count(self):
        """The frontend sidebarManifest.ts should have the same item count as sidebar_config.py."""
        manifest_src = _read("web/react/src/config/sidebarManifest.ts")
        manifest_hrefs = set(re.findall(r"href:\s*'([a-z][a-z0-9-]*)'", manifest_src))
        config_hrefs = {item["href"] for item in self.items}
        missing_from_manifest = config_hrefs - manifest_hrefs
        extra_in_manifest = manifest_hrefs - config_hrefs
        self.assertEqual(
            missing_from_manifest, set(),
            f"Config hrefs missing from sidebarManifest.ts: {missing_from_manifest}"
        )
        self.assertEqual(
            extra_in_manifest, set(),
            f"sidebarManifest.ts hrefs not in config: {extra_in_manifest}"
        )


class TestExecutionInfrastructureWiring(unittest.TestCase):
    """Execution infrastructure is wired: positions, orders, portfolio in sidebar."""

    @classmethod
    def setUpClass(cls):
        cls.sections, cls.phases = _get_sidebar_config()
        cls.items = _flatten_sidebar_items(cls.sections)
        cls.item_map = {item["id"]: item for item in cls.items}
        cls.constants_src = _read("web/react/src/config/constants.ts")

    def test_positions_sidebar_item_exists(self):
        self.assertIn("positions", self.item_map)

    def test_orders_sidebar_item_exists(self):
        self.assertIn("orders", self.item_map)

    def test_portfolio_sidebar_item_exists(self):
        self.assertIn("kalshi-portfolio", self.item_map)

    def test_positions_in_execution_phase(self):
        for phase in self.phases:
            if phase["id"] == "execution":
                self.assertIn("positions", phase["views"])
                return
        self.fail("No 'execution' workflow phase found")

    def test_trade_mode_endpoint_in_constants(self):
        self.assertIn("/api/v1/trade-mode", self.constants_src)

    def test_reconciliation_endpoints_in_constants(self):
        self.assertIn("/api/v1/reconciliation/run", self.constants_src)
        self.assertIn("/api/v1/reconciliation/status", self.constants_src)

    def test_audit_trail_endpoints_in_constants(self):
        self.assertIn("/api/v1/audit-trail/summary", self.constants_src)
        self.assertIn("/api/v1/audit-trail/entries", self.constants_src)

    def test_orders_links_to_valid(self):
        orders = self.item_map["orders"]
        for link in orders.get("links_to", []):
            self.assertIn(link, self.item_map,
                          f"orders links_to '{link}' not found in sidebar")

    def test_execution_views_in_manifest(self):
        """Key execution views exist in the frontend manifest."""
        manifest_src = _read("web/react/src/config/sidebarManifest.ts")
        exec_views = ["overview", "positions", "orders", "kalshi-portfolio"]
        for v in exec_views:
            self.assertIn(f"href: '{v}'", manifest_src,
                          f"Execution view '{v}' missing from sidebarManifest.ts")


if __name__ == "__main__":
    unittest.main()
