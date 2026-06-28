from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient


def test_repo_root_main_delegates_to_web_main_app():
    # SKIPPED: main.py and web.main deleted - legacy delegation not applicable to 15m stack
    pytest.skip("Legacy main.py and web.main deleted - delegation test not applicable to 15m stack")


def test_canonical_lifespan_marker_runs_in_test_mode(monkeypatch):
    # SKIPPED: main.py and web.main deleted - legacy lifespan marker not applicable to 15m stack
    pytest.skip("Legacy main.py and web.main deleted - lifespan marker test not applicable to 15m stack")


def test_compute_kalshi_ws_tickers_non_empty_and_dedupes():
    # SKIPPED: web.main deleted - compute_kalshi_ws_tickers not used in 15m production stack
    pytest.skip("Legacy web.main deleted - function not applicable to 15m stack")
