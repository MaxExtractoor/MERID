"""Shim to load the repository-local `web/main.py` module and expose `app`.

This ensures tests import the lightweight app in this folder rather than a larger
`web` package that may exist at the repo root.
"""
import importlib.util
import os
import sys
import types

ROOT = os.path.dirname(__file__)

# Ensure local core modules are mapped before loading web.main so imports like
# `from core.orchestrator import MeridCore` resolve to our local stub.
try:
    import merid_core  # noqa: F401
except Exception:
    pass

# Prefer normal import so Python's package loader handles submodules correctly.
# This will import the local `web` package because the workspace path is inserted
# into sys.path by tests' conftest.
import importlib
mod = importlib.import_module("web.main")
app = getattr(mod, "app")
__all__ = ["app"]
