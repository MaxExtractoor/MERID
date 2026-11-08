"""Live navigation wiring invariants: views.ts ↔ App.tsx ↔ Sidebar ↔ CommandPalette.

Guards the active seven-view console contract. The dormant
``web/api/sidebar_config.py`` (legacy multi-page stub, unmounted on the lean
app) is intentionally not the source of truth — see its module docstring.

Invariants enforced:
1. Every ``View`` union member in types/views.ts is routable in App.tsx
2. Every Sidebar item href is a valid View and has a route
3. Every CommandPalette command id is a valid View and has a route
4. No duplicate hrefs/ids within each surface
5. Sidebar and CommandPalette cover every View (no orphaned screens)
6. Keyboard shortcuts in App.tsx map 0-6 onto valid Views
"""

import re
import unittest
from pathlib import Path
from typing import Set

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read(relpath: str) -> str:
    p = PROJECT_ROOT / relpath
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _view_union() -> Set[str]:
    """All members of the exported `View` union in types/views.ts, including
    members pulled in via the `AgentView` alias."""
    src = _read("web/react/src/types/views.ts")
    members: Set[str] = set()
    for typename in ("AgentView", "View"):
        block = src.split(f"export type {typename}", 1)[1].split(";", 1)[0]
        members |= set(re.findall(r"'([a-z][a-z0-9-]*)'", block))
    return members


def _app_routes() -> Set[str]:
    """Views App.tsx can render: VIEW_COMPONENTS keys + the agent-detail
    special case handled outside the record."""
    src = _read("web/react/src/App.tsx")
    record = src.split("VIEW_COMPONENTS", 1)[1].split("};", 1)[0]
    keys = set(re.findall(r'(?:([a-z][a-z0-9-]*)|"([a-z][a-z0-9-]*)")\s*:', record))
    keys = {a or b for a, b in keys}
    if 'view === "agent-detail"' in src:
        keys.add("agent-detail")
    return keys


def _sidebar_hrefs() -> list:
    src = _read("web/react/src/components/Sidebar.tsx")
    return re.findall(r"href:\s*'([a-z][a-z0-9-]*)'", src)


def _palette_ids() -> list:
    src = _read("web/react/src/components/CommandPalette.tsx")
    return re.findall(r"\{ id: '([a-z][a-z0-9-]*)'", src)


class TestLiveNavigationWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.views = _view_union()
        cls.routes = _app_routes()
        cls.hrefs = _sidebar_hrefs()
        cls.palette = _palette_ids()

    def test_exactly_seven_views(self):
        self.assertEqual(
            self.views,
            {"agent-wall", "agent-detail", "mission-control",
             "terminal", "portfolio", "risk", "system"},
        )

    def test_every_view_is_routed(self):
        missing = self.views - self.routes
        self.assertEqual(missing, set(), f"Views without App.tsx routes: {missing}")

    def test_no_routes_without_view_type(self):
        extra = self.routes - self.views
        self.assertEqual(extra, set(), f"Routes not declared in views.ts: {extra}")

    def test_sidebar_hrefs_are_valid_views(self):
        invalid = set(self.hrefs) - self.views
        self.assertEqual(invalid, set(), f"Sidebar hrefs not in views.ts: {invalid}")

    def test_sidebar_covers_every_view(self):
        missing = self.views - set(self.hrefs)
        self.assertEqual(missing, set(), f"Views missing from Sidebar: {missing}")

    def test_sidebar_has_no_duplicate_hrefs(self):
        dupes = {h for h in self.hrefs if self.hrefs.count(h) > 1}
        self.assertEqual(dupes, set(), f"Duplicate sidebar hrefs: {dupes}")

    def test_palette_ids_are_valid_views(self):
        invalid = set(self.palette) - self.views
        self.assertEqual(invalid, set(), f"Palette ids not in views.ts: {invalid}")

    def test_palette_covers_every_view(self):
        missing = self.views - set(self.palette)
        self.assertEqual(missing, set(), f"Views missing from CommandPalette: {missing}")

    def test_palette_has_no_duplicates(self):
        dupes = {i for i in self.palette if self.palette.count(i) > 1}
        self.assertEqual(dupes, set(), f"Duplicate palette ids: {dupes}")

    def test_keyboard_shortcuts_cover_all_views(self):
        src = _read("web/react/src/App.tsx")
        shortcut_targets = set(re.findall(
            r"action:\s*\(\)\s*=>\s*handleNavigate\('([a-z][a-z0-9-]*)'\)", src))
        self.assertEqual(shortcut_targets, self.views,
                         "App keyboard shortcuts must cover every view")


class TestDormantConfigNotResurrected(unittest.TestCase):
    """sidebar_config.py must stay marked dormant so nothing trusts it."""

    def test_sidebar_config_marked_dormant(self):
        src = _read("web/api/sidebar_config.py")
        self.assertIn("DORMANT", src.split('"""', 2)[1])

    def test_lean_app_does_not_mount_sidebar_config(self):
        src = _read("web/main_15m_lean.py")
        self.assertNotIn("sidebar_config", src)


if __name__ == "__main__":
    unittest.main()
