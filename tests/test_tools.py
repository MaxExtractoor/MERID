"""Tests for tools module utility stubs."""

from __future__ import annotations

from typing import Any, Dict

import httpx
import pytest

from tools import web_search, x_keyword_search, view_image


class _DummyResponse:
    def __init__(self, status_code: int, payload: Dict[str, Any]):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Dict[str, Any]:
        return self._payload


class _DummyClient:
    def __init__(self, response: _DummyResponse):
        self._response = response
        self._calls = []

    def __enter__(self) -> "_DummyClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ARG002
        return None

    def get(self, url: str, params: Dict[str, Any]) -> _DummyResponse:
        self._calls.append((url, params))
        return self._response


class _TimeoutClient:
    def __enter__(self):
        raise httpx.TimeoutException("timeout")

    def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
        return None


def test_web_search_returns_abstract_and_related_topics(monkeypatch):
    payload = {
        "Heading": "MERID",
        "Abstract": "MERID overview text",
        "AbstractURL": "https://example.com/merid",
        "RelatedTopics": [
            {"Text": "Topic 1 detail", "FirstURL": "https://example.com/t1"},
            {"Text": "Topic 2 detail", "FirstURL": "https://example.com/t2"},
        ],
    }
    dummy_response = _DummyResponse(status_code=200, payload=payload)
    dummy_client = _DummyClient(dummy_response)

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: dummy_client)

    result = web_search("merid", max_results=2)

    assert result["query"] == "merid"
    assert len(result["results"]) == 2
    assert result["results"][0]["title"] == "MERID"
    assert result["results"][1]["url"] == "https://example.com/t1"


def test_web_search_handles_timeout(monkeypatch):
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: _TimeoutClient())

    result = web_search("slow query")

    assert result == {"query": "slow query", "results": []}


def test_web_search_non_200_returns_empty(monkeypatch):
    dummy_response = _DummyResponse(status_code=500, payload={})
    dummy_client = _DummyClient(dummy_response)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: dummy_client)

    result = web_search("merid")

    assert result["results"] == []


def test_x_keyword_search_stub_response():
    result = x_keyword_search("finance")

    assert result["query"] == "finance"
    assert "note" in result


def test_view_image_stub_response():
    result = view_image("https://example.com/image.png")

    assert result == {"url": "https://example.com/image.png", "status": "Image URL recorded"}
