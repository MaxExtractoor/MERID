import importlib.util
import sys
import types
from pathlib import Path

import pytest


def _load_module(module_name: str, path: Path):
    # Stub external deps to avoid heavy installs in unit scope
    class _DummyCompiled:
        def invoke(self, state):
            return {
                "risk_approved": True,
                "execution_result": {"order_id": "mock-123"},
                "messages": [],
            }

    class _DummyStateGraph:
        def __init__(self, *_args, **_kwargs):
            self._compiled = _DummyCompiled()

        def add_node(self, *_args, **_kwargs):
            return None

        def set_entry_point(self, *_args, **_kwargs):
            return None

        def add_edge(self, *_args, **_kwargs):
            return None

        def add_conditional_edges(self, *_args, **_kwargs):
            return None

        def compile(self):
            return self._compiled

    dummy_graph = types.SimpleNamespace(StateGraph=_DummyStateGraph, END="END")
    sys.modules.setdefault("langgraph", types.SimpleNamespace(graph=dummy_graph))
    sys.modules.setdefault("langgraph.graph", dummy_graph)

    dummy_messages = types.SimpleNamespace(
        BaseMessage=object,
        HumanMessage=types.SimpleNamespace,
        AIMessage=types.SimpleNamespace,
    )
    sys.modules.setdefault("langchain_core", types.SimpleNamespace(messages=dummy_messages))
    sys.modules.setdefault("langchain_core.messages", dummy_messages)

    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[2]
swarm_mod = _load_module("swarm_langgraph", ROOT / "core" / "swarm_langgraph.py")
LangGraphTradingSwarm = swarm_mod.LangGraphTradingSwarm


@pytest.mark.asyncio
async def test_langgraph_swarm_labels_mock_mode():
    swarm = LangGraphTradingSwarm(use_mock=True)
    result = await swarm.execute_trade({"symbol": "BTC", "confidence": 0.9})

    assert result["mode"] == "mock"
    assert result["execution"]["order_id"] == "mock-123"


@pytest.mark.asyncio
async def test_langgraph_swarm_labels_live_mode():
    swarm = LangGraphTradingSwarm(use_mock=False)
    result = await swarm.execute_trade({"symbol": "ETH", "confidence": 0.8})

    assert result["mode"] == "live"
