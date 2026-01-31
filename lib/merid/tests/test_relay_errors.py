import os
import pytest
from unittest.mock import patch, MagicMock

from relay import run_relay
from merid_core import ExternalServiceError


def test_run_relay_missing_clients(monkeypatch):
    # Ensure OpenAI client builder raises (simulate missing package)
    monkeypatch.setenv("OLLAMA_API_KEY", "")

    with patch("relay.OpenAI", None):
        with pytest.raises(Exception):
            run_relay("test")


def test_run_relay_external_service_error(monkeypatch):
    # Simulate local client returning RELAY decision but missing cloud client
    class DummyLocalClient:
        class chat:
            class completions:
                @staticmethod
                def create(*args, **kwargs):
                    class A:
                        class choices:
                            pass
                    # craft object with choices[0].message.content
                    class Choice:
                        class message:
                            content = "RELAY"
                    obj = MagicMock()
                    obj.choices = [Choice()]
                    return obj

    monkeypatch.setattr("relay.OpenAI", MagicMock(return_value=None))
    monkeypatch.setattr("relay._build_openai_clients", lambda: (DummyLocalClient(), None))

    with pytest.raises(ExternalServiceError):
        run_relay("bitcoin vibe")
