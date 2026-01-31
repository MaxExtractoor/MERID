"""Additional tests to raise coverage for CLI/helper modules."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from importlib.util import module_from_spec, spec_from_file_location

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, relative_path: str):
    spec = spec_from_file_location(name, REPO_ROOT / relative_path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load module {name} from {relative_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


rag_agent = _load_module("rag_agent_module", "lib/agents/rag_agent.py")
voice_agent = _load_module("voice_agent_module", "lib/agents/voice-agent.py")
relay_module = _load_module("relay_module", "lib/merid/relay.py")


def test_scan_knowledge_directory_missing(tmp_path):
    target = tmp_path / "missing"
    result = rag_agent.scan_knowledge_directory(str(target))
    assert result["status"] == "error"
    assert "not found" in result["message"]


def test_scan_knowledge_directory_with_files(tmp_path):
    file_path = tmp_path / "note.txt"
    file_path.write_text("alpha beta", encoding="utf-8")

    result = rag_agent.scan_knowledge_directory(str(tmp_path))

    assert result["status"] == "success"
    assert result["files_found"] == ["note.txt"]
    assert "alpha beta" in result["content"]


def test_voice_agent_run_cli_with_command(monkeypatch, capsys):
    class DummyVoiceAgent:
        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr(voice_agent, "VoiceAgent", DummyVoiceAgent)

    voice_agent.run_cli("Hello MERID")

    out = json.loads(capsys.readouterr().out.strip())
    assert out["response"].startswith("Spoke: Hello MERID")


class _DummyCompletions:
    def __init__(self, text: str):
        self._text = text

    def create(self, *args, **kwargs):
        message = SimpleNamespace(content=self._text)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


class _DummyClient:
    def __init__(self, text: str):
        self.chat = SimpleNamespace(completions=_DummyCompletions(text))


def test_run_relay_local_path(monkeypatch):
    monkeypatch.setattr(relay_module, "_build_openai_clients", lambda: (_DummyClient("stay local"), None))
    monkeypatch.setattr(relay_module, "_build_supabase_client", lambda: None)

    result = relay_module.run_relay("test query")

    assert "[MERID-LOCAL]" in result


def test_run_relay_cloud_path(monkeypatch):
    monkeypatch.setattr(relay_module, "_build_openai_clients", lambda: (_DummyClient("RELAY"), _DummyClient("cloud summary")))
    monkeypatch.setattr(relay_module, "_build_supabase_client", lambda: None)

    class DummyTwitter:
        def get_market_sentiment(self, query: str):
            return [f"tweet about {query}"]

    monkeypatch.setattr(relay_module, "MERIDTwitterAgent", lambda: DummyTwitter())

    result = relay_module.run_relay("market conditions")

    assert "[MERID-X-RELAY]" in result
    assert "cloud summary" in result
