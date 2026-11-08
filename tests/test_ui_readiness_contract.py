import ast
import asyncio
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest


@pytest.mark.parametrize(
    "startup,loop_alive,safety_ok,expected",
    [(False, False, True, 503), (True, False, True, 503),
     (True, True, False, 503), (True, True, True, 200)],
)
def test_readiness_http_status_matches_payload(startup, loop_alive, safety_ok, expected):
    path = Path(__file__).resolve().parents[1] / "web/main_15m_lean.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "readiness_check")
    function.decorator_list = []
    module = ast.Module(body=[function], type_ignores=[])
    task = SimpleNamespace(done=lambda: not loop_alive)
    namespace = {
        "app": SimpleNamespace(state=SimpleNamespace(kalshi_15m_task=task, startup_completed=startup)),
        "startup_state": SimpleNamespace(started=True, error=None, started_at=None, completed_at=None),
    }
    validations = ModuleType("merid.startup_validations")

    def validate():
        if not safety_ok:
            raise RuntimeError("safety unavailable")

    validations.validate_order_safety_controls = validate
    exec(compile(module, str(path), "exec"), namespace)
    with patch.dict(sys.modules, {"merid.startup_validations": validations}):
        response = asyncio.run(namespace["readiness_check"]())
    assert getattr(response, "status_code", 200) == expected
    payload = json.loads(response.body) if hasattr(response, "body") else response
    assert payload["status"] == ("ready" if expected == 200 else "not_ready")


def test_ui_summary_inherits_account_session_gate():
    from fastapi import APIRouter, Depends

    path = Path(__file__).resolve().parents[1] / "web/api/kalshi_ui.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assignment = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "router" for target in node.targets)
    )
    session_gate = lambda: None
    namespace = {"APIRouter": APIRouter, "Depends": Depends, "get_current_session": session_gate}
    exec(compile(ast.Module(body=[assignment], type_ignores=[]), str(path), "exec"), namespace)
    assert any(dependency.dependency is session_gate for dependency in namespace["router"].dependencies)
