"""Pytest configuration for MERID tests."""

from __future__ import annotations

import asyncio
import os
import sys
import types
from pathlib import Path
import importlib.util
from importlib.machinery import ModuleSpec

# Disable live Neo4j connections for CI/unit tests.
os.environ.setdefault("MERID_DISABLE_NEO4J", "1")

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _force_prod_package(name: str, root: Path) -> None:
    """Load a package from the repo root even if tests add a namesake package."""

    package_init = root / "__init__.py"
    if not package_init.exists():  # pragma: no cover - sanity guard
        raise ModuleNotFoundError(f"{name} package not found at {root}")

    spec = importlib.util.spec_from_file_location(
        name,
        package_init,
        submodule_search_locations=[str(root)],
    )
    assert spec and spec.loader  # pragma: no cover - importlib contract

    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)


# Ensure absolute "hardening" imports resolve to the production package (tests ship a
# "tests.hardening" helper package that would otherwise shadow the real one).
_force_prod_package("hardening", PROJECT_ROOT / "hardening")


class _FakeNeo4jMemory:
    """Simple in-memory stand-in for Neo4jMemory used in tests."""

    def __init__(self):
        self._events: list = []

    def close(self):  # pragma: no cover - trivial
        self._events.clear()

    # The real memory object exposes log/query helpers. Tests only need safe stubs.
    def log_energy(self, *args, **kwargs):  # pragma: no cover - deterministic noop
        self._events.append(("energy", args, kwargs))

    def log_votes(self, *args, **kwargs):  # pragma: no cover - deterministic noop
        self._events.append(("votes", args, kwargs))

    def log_reality(self, *args, **kwargs):  # pragma: no cover
        self._events.append(("reality", args, kwargs))

    def evolve_trust(self, *args, **kwargs):  # pragma: no cover
        self._events.append(("trust", args, kwargs))

    def get_history(self, limit: int = 20):
        return self._events[-limit:]


_fake_db_module = types.ModuleType("db.neo4j")
_fake_db_module.Neo4jMemory = _FakeNeo4jMemory
_fake_db_module.memory = _FakeNeo4jMemory()
sys.modules["db.neo4j"] = _fake_db_module
