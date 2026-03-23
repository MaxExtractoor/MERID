import importlib.util
import sys
import types
from pathlib import Path

import pytest


def _load_module(module_name: str, path: Path):
    # Stub external dependencies that are not required for these unit tests
    neo4j_stub = types.SimpleNamespace(GraphDatabase=types.SimpleNamespace)
    sys.modules.setdefault("neo4j", neo4j_stub)
    telegram_error = types.SimpleNamespace(TelegramError=Exception)
    telegram_stub = types.SimpleNamespace(Bot=types.SimpleNamespace, error=telegram_error)
    sys.modules.setdefault("telegram", telegram_stub)
    sys.modules.setdefault("telegram.error", telegram_error)

    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[2]
agent_grid_mod = _load_module("agent_grid", ROOT / "merid" / "prediction" / "agent_grid.py")
AgentGrid = agent_grid_mod.AgentGrid
run_startup_steps = agent_grid_mod.run_startup_steps


@pytest.mark.asyncio
async def test_run_startup_steps_rolls_back_on_failure():
    events = []

    async def start_ok():
        events.append("start1")

    async def stop_ok():
        events.append("stop1")

    async def start_fail():
        events.append("start2")
        raise RuntimeError("boom")

    async def stop_fail():
        events.append("stop2")

    with pytest.raises(RuntimeError):
        await run_startup_steps([
            ("one", start_ok, stop_ok),
            ("two", start_fail, stop_fail),
        ])

    assert events == ["start1", "start2", "stop1"]


def test_backoff_delay_caps_growth():
    delays = [AgentGrid._backoff_delay(i) for i in range(6)]
    assert delays[0] == 1.0
    assert delays[1] == 2.0
    assert delays[-1] <= 60.0
