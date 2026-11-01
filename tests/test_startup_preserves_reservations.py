"""Startup must not erase reservations based on an empty in-memory cache."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UNSAFE_RESETS = {
    "force_reset_window_exposure",
    "reset_category_notional",
    "clear_slots_on_empty_positions",
    "_reset_stale_window_exposure",
}


def _calls(node):
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                yield child.func.id
            elif isinstance(child.func, ast.Attribute):
                yield child.func.attr


def _function(tree, name):
    return next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)


def _constructor(tree, name):
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
    return _function(cls, "__init__")


def test_startup_does_not_clear_unverified_risk_reservations():
    tree = ast.parse((ROOT / "web" / "main_15m_lean.py").read_text(encoding="utf-8"))
    top_level = ast.Module(
        body=[node for node in tree.body if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))],
        type_ignores=[],
    )
    assert not (set(_calls(top_level)) & UNSAFE_RESETS)
    assert not (set(_calls(_function(tree, "_run_full_startup_in_lifespan"))) & UNSAFE_RESETS)


def test_position_and_loop_construction_preserve_reservations():
    cache = ast.parse((ROOT / "merid" / "event_venues" / "kalshi" / "position_cache.py").read_text(encoding="utf-8"))
    loop = ast.parse((ROOT / "merid" / "loop_15m.py").read_text(encoding="utf-8"))
    assert not (set(_calls(_constructor(cache, "KalshiPositionCache"))) & UNSAFE_RESETS)
    assert not (set(_calls(_constructor(loop, "Kalshi15mLoop"))) & UNSAFE_RESETS)


def test_rollover_and_router_do_not_clear_pending_reservations():
    loop = ast.parse((ROOT / "merid" / "loop_15m.py").read_text(encoding="utf-8"))
    router = ast.parse(
        (ROOT / "merid" / "event_venues" / "kalshi" / "order_router.py").read_text(encoding="utf-8")
    )
    loop_calls = set(_calls(_function(loop, "_run_loop")))
    assert not (loop_calls & (UNSAFE_RESETS | {"clear_open_positions_on_empty_cache"}))
    assert "clear_slots_on_empty_positions" not in set(_calls(router))
