import os

import pytest


def test_redis_circuitbreaker_trips(monkeypatch):
    fakeredis = pytest.importorskip("fakeredis")
    monkeypatch.setenv("MERID_CIRCUITBACKEND", "redis")

    # Patch Redis.from_url to return a fakeredis client
    import redis as _redis

    monkeypatch.setattr(_redis.Redis, "from_url", lambda url: fakeredis.FakeRedis())

    from trading.risk import CircuitBreaker

    CircuitBreaker.reset()
    assert CircuitBreaker.is_tripped() is False

    # Default threshold is 5
    for _ in range(5):
        CircuitBreaker.record_error()

    assert CircuitBreaker.is_tripped() is True

    CircuitBreaker.reset()
    assert CircuitBreaker.is_tripped() is False


def test_redis_status_reports_counts(monkeypatch):
    fakeredis = pytest.importorskip("fakeredis")
    monkeypatch.setenv("MERID_CIRCUITBACKEND", "redis")
    import redis as _redis
    monkeypatch.setattr(_redis.Redis, "from_url", lambda url: fakeredis.FakeRedis())

    from trading.risk import CircuitBreaker

    CircuitBreaker.reset()
    for _ in range(3):
        CircuitBreaker.record_error()
    s = CircuitBreaker.status()
    assert s["errors"] == 3
    assert s["tripped"] is False
    # force trip
    CircuitBreaker.record_error()
    CircuitBreaker.record_error()
    assert CircuitBreaker.status()["tripped"] is True
