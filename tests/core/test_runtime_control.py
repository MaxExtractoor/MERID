import asyncio
import importlib.util
from pathlib import Path
import sys

import pytest

from merid.execution_guard import ExecutionGuard

RUNTIME_PATH = Path(__file__).parents[2] / "core" / "runtime.py"
runtime_spec = importlib.util.spec_from_file_location("runtime_local", RUNTIME_PATH)
runtime = importlib.util.module_from_spec(runtime_spec)
assert runtime_spec and runtime_spec.loader
sys.modules["runtime_local"] = runtime
runtime_spec.loader.exec_module(runtime)  # type: ignore[arg-type]

SystemController = runtime.SystemController
SystemMode = runtime.SystemMode
Subsystem = runtime.Subsystem
TaskManager = runtime.TaskManager


@pytest.mark.asyncio
async def test_system_block_gates_execution():
    guard = ExecutionGuard()
    guard.deactivate_kill_switch()
    controller = SystemController()
    controller.attach_execution_guard(guard)

    # Blocked while system is booting
    verdict_blocked = guard.pre_trade_check(
        plan_id="p1", symbol="BTC", domain="crypto", size_usd=10
    )
    assert verdict_blocked.allowed is False
    assert "system_block" in verdict_blocked.reason

    # Clear block and allow trading
    controller.allow_trading()
    verdict_allowed = guard.pre_trade_check(
        plan_id="p2", symbol="BTC", domain="crypto", size_usd=10
    )
    assert verdict_allowed.allowed is True


@pytest.mark.asyncio
async def test_readiness_timeout_marks_failure():
    controller = SystemController()
    controller.set_mode(SystemMode.WARMUP)

    # Event never set should mark failure after timeout
    await controller.watch_readiness(
        Subsystem.PRICE_FEED, asyncio.Event(), timeout=0.05
    )
    snapshot = controller.snapshot()
    assert snapshot["status"][Subsystem.PRICE_FEED.value] == "failed"


@pytest.mark.asyncio
async def test_task_manager_stops_tasks():
    manager = TaskManager()
    stopped = asyncio.Event()

    async def worker():
        while True:
            await asyncio.sleep(0.01)

    async def stop_worker():
        stopped.set()

    manager.create_task("worker", worker(), stop=stop_worker, critical=True)
    await asyncio.sleep(0.05)
    await manager.stop_all()
    assert stopped.is_set()
