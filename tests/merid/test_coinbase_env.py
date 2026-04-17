"""Unit tests for merid.coinbase_env credential resolution."""

import pytest

from merid.coinbase_env import coinbase_api_key, coinbase_api_secret


def test_coinbase_env_prefers_merid_over_client_over_plain(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (
        "MERID_COINBASE_API_KEY",
        "COINBASE_CLIENT_API_KEY",
        "COINBASE_API_KEY",
        "MERID_COINBASE_API_SECRET",
        "COINBASE_CLIENT_API_SECRET",
        "COINBASE_API_SECRET",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("COINBASE_API_KEY", "plain_k")
    monkeypatch.setenv("COINBASE_API_SECRET", "plain_s")
    monkeypatch.setenv("COINBASE_CLIENT_API_KEY", "client_k")
    monkeypatch.setenv("COINBASE_CLIENT_API_SECRET", "client_s")
    monkeypatch.setenv("MERID_COINBASE_API_KEY", "merid_k")
    monkeypatch.setenv("MERID_COINBASE_API_SECRET", "merid_s")
    assert coinbase_api_key() == "merid_k"
    assert coinbase_api_secret() == "merid_s"


def test_coinbase_env_client_alias_when_no_merid(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (
        "MERID_COINBASE_API_KEY",
        "COINBASE_CLIENT_API_KEY",
        "COINBASE_API_KEY",
        "MERID_COINBASE_API_SECRET",
        "COINBASE_CLIENT_API_SECRET",
        "COINBASE_API_SECRET",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("COINBASE_CLIENT_API_KEY", "client_k")
    monkeypatch.setenv("COINBASE_CLIENT_API_SECRET", "client_s")
    assert coinbase_api_key() == "client_k"
    assert coinbase_api_secret() == "client_s"


def test_coinbase_env_empty_means_none(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in (
        "MERID_COINBASE_API_KEY",
        "COINBASE_CLIENT_API_KEY",
        "COINBASE_API_KEY",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("COINBASE_API_KEY", "")
    assert coinbase_api_key() is None
