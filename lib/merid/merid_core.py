"""Compatibility shim to expose local core modules under a stable import name.

Ensures tests and local scripts use the repo-local `core` implementations even when
an unrelated top-level `core` package exists in the repo root.
"""

import importlib.util
import os
import sys
import types

ROOT = os.path.dirname(__file__)


def _load_module(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    # pre-register a placeholder if other code expects 'core.*' names
    pkgname = name.rsplit('.', 1)[0]
    if pkgname not in sys.modules:
        sys.modules[pkgname] = types.ModuleType(pkgname)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod

_energy_mod = _load_module("merid_core.energy", os.path.join(ROOT, "core", "energy.py"))
_orch_mod = _load_module("merid_core.orchestrator", os.path.join(ROOT, "core", "orchestrator.py"))
_lock_mod = _load_module("merid_core.lockdown", os.path.join(ROOT, "core", "lockdown.py"))
_err_mod = _load_module("merid_core.error_handling", os.path.join(ROOT, "core", "error_handling.py"))

# Also map into 'core.*' names so that other modules importing 'core.*' will
# get our local modules while tests prefer the shim.
sys.modules["core.energy"] = _energy_mod
sys.modules["core.orchestrator"] = _orch_mod
sys.modules["core.lockdown"] = _lock_mod
sys.modules["core.error_handling"] = _err_mod

create_energy = _energy_mod.create_energy
MeridCore = _orch_mod.MeridCore
set_lockdown = _lock_mod.set_lockdown
is_lockdown = _lock_mod.is_lockdown

# Expose error types
ExternalServiceError = _err_mod.ExternalServiceError

__all__ = ["create_energy", "MeridCore", "set_lockdown", "is_lockdown", "ExternalServiceError"]
