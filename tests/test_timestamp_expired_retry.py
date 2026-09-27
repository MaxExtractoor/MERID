"""Regression tests: 401 header_timestamp_expired must re-sign and retry,
and must never be classified as a permanent auth failure.

2026-09-27 incident: signed Kalshi requests sat ~37s in the httpx pool /
in flight during exchange-side congestion at a market boundary.  Kalshi
rejected them at the auth layer with ``header_timestamp_expired`` and the
balance path classified the transient congestion as BalancePermanentError.
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from typing import List
from unittest.mock import AsyncMock

import httpx
import pytest


# ---------------------------------------------------------------------------
# client_v2._request — re-sign + bounded retry on timestamp_expired
# ---------------------------------------------------------------------------

def _v2_client():
    """Minimal KalshiClientV2 test double: no config load, stubbed HTTP."""
    from merid.event_venues.kalshi.client_v2 import KalshiClientV2

    client = KalshiClientV2.__new__(KalshiClientV2)
    client._api_key_id = "test-key-id"
    client._requests_total = 0
    client._requests_failed = 0
    client._rate_limit_hits = 0
    client._sign_calls = 0

    def _sign(method: str, path: str):
        client._sign_calls += 1
        return {"KALSHI-ACCESS-TIMESTAMP": f"ts{client._sign_calls}"}

    client._sign_request = _sign
    return client


def _resp(status: int, body: str = "", url: str = "https://api.kalshi.test/x") -> httpx.Response:
    return httpx.Response(
        status,
        text=body,
        request=httpx.Request("GET", url),
    )


@pytest.mark.asyncio
async def test_v2_request_retries_timestamp_expired_with_fresh_signature():
    """A 401 timestamp_expired must be retried — the next attempt re-signs."""
    from merid.event_venues.kalshi import client_v2 as cv2

    client = _v2_client()
    responses = [
        _resp(401, '{"error":"header_timestamp_expired"}'),
        _resp(200, '{"balance": 100}'),
    ]
    calls: List[dict] = []

    class _FakeHTTP:
        async def request(self, method, path, headers=None, **kw):
            calls.append(dict(headers or {}))
            return responses[min(len(calls) - 1, len(responses) - 1)]

    async def _get_client():
        return _FakeHTTP()

    client._get_client = _get_client
    # Keep the retry sleep deterministic/fast.
    import asyncio as _a
    orig_sleep = _a.sleep
    async def _fast_sleep(_):
        await orig_sleep(0)
    cv2.asyncio.sleep = _fast_sleep
    try:
        resp = await client._request(
            "GET", "/portfolio/balance", skip_rate_limiter=True, allow_retry=False
        )
    finally:
        cv2.asyncio.sleep = orig_sleep

    assert resp.status_code == 200
    assert len(calls) == 2, f"expected re-sign+retry, got {len(calls)} sends"
    assert client._sign_calls == 2, "signature must be regenerated per attempt"
    # Fresh timestamp on the retry — the whole point of the fix.
    assert calls[0]["KALSHI-ACCESS-TIMESTAMP"] != calls[1]["KALSHI-ACCESS-TIMESTAMP"]


@pytest.mark.asyncio
async def test_v2_request_timestamp_expired_retries_are_bounded():
    """Persistent congestion must not loop forever — cap re-sign retries."""
    from merid.event_venues.kalshi import client_v2 as cv2

    client = _v2_client()

    class _Always401:
        def __init__(self):
            self.calls = 0

        async def request(self, method, path, headers=None, **kw):
            self.calls += 1
            return _resp(401, '{"error":"header_timestamp_expired"}')

    http = _Always401()

    async def _get_client():
        return http

    client._get_client = _get_client
    import asyncio as _a
    orig_sleep = _a.sleep
    async def _fast_sleep(_):
        await orig_sleep(0)
    cv2.asyncio.sleep = _fast_sleep
    try:
        resp = await client._request(
            "GET", "/portfolio/balance", skip_rate_limiter=True, allow_retry=False
        )
    finally:
        cv2.asyncio.sleep = orig_sleep

    assert resp.status_code == 401
    # 1 initial + _KALSHI_TS_EXPIRED_MAX_RETRIES re-sign retries.
    assert http.calls == 1 + cv2._KALSHI_TS_EXPIRED_MAX_RETRIES


@pytest.mark.asyncio
async def test_get_balance_timestamp_expired_is_temporary_not_permanent():
    """The incident's actual bug: expired timestamps → BalancePermanentError."""
    from merid.event_venues.kalshi.client_v2 import KalshiClientV2
    from merid.event_venues.kalshi.types import (
        BalanceTemporaryError,
        BalancePermanentError,
    )

    client = _v2_client()
    client._base_url = "https://api.kalshi.test"

    async def _fake_request(*a, **kw):
        return _resp(401, '{"code":"header_timestamp_expired"}')

    client._request = _fake_request
    result = await client.get_balance()

    assert isinstance(result, BalanceTemporaryError), (
        f"timestamp_expired must be transient congestion, got {type(result).__name__}"
    )
    assert not isinstance(result, BalancePermanentError)


@pytest.mark.asyncio
async def test_get_balance_real_auth_failure_stays_permanent():
    """Genuine auth failures must still halt — don't over-broaden the fix."""
    from merid.event_venues.kalshi.client_v2 import KalshiClientV2
    from merid.event_venues.kalshi.types import (
        BalancePermanentError,
    )

    client = _v2_client()
    client._base_url = "https://api.kalshi.test"

    async def _fake_request(*a, **kw):
        return _resp(401, '{"error":"invalid_signature"}')

    client._request = _fake_request
    result = await client.get_balance()

    assert isinstance(result, BalancePermanentError)


# ---------------------------------------------------------------------------
# client.py._request_with_resilience — same stale-signature fast path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_v1_request_retries_timestamp_expired_without_reauthenticate(monkeypatch):
    """timestamp_expired needs a fresh signature, NOT _authenticate()."""
    from merid.event_venues.kalshi import client as kc

    client = kc.KalshiVenueClient.__new__(kc.KalshiVenueClient)
    client.config = SimpleNamespace(rest_base_url="https://api.kalshi.test")
    client._auth_mode = "rsa"
    client._sign_calls = 0
    client._auth_warned = False

    def _sign(method, path):
        client._sign_calls += 1
        return {"KALSHI-ACCESS-TIMESTAMP": f"ts{client._sign_calls}"}

    client._sign_headers = _sign
    client._ensure_async_network_resources = lambda: None
    client._authenticate = AsyncMock()

    class _RL:
        async def acquire(self, is_write=False):
            return 0.0

    class _CB:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    client._rate_limiter = _RL()
    client._request_semaphore = asyncio.Semaphore(5)
    client._circuit_breaker = _CB()
    client._circuit_open_log_count = 0

    sends = []

    class _FakeHTTP:
        async def request(self, method, url, params=None, json=None, headers=None):
            sends.append(dict(headers or {}))
            status = 401 if len(sends) == 1 else 200
            body = '{"error":"header_timestamp_expired"}' if status == 401 else "{}"
            return httpx.Response(
                status, text=body, request=httpx.Request(method, url)
            )

    async def _ensure_client():
        return _FakeHTTP()

    client._ensure_client = _ensure_client

    monkeypatch.setattr(kc, "emit_api_metrics", lambda **kw: None)
    monkeypatch.setattr(kc, "record_ingress", lambda *a, **kw: None)
    orig_sleep = asyncio.sleep
    async def _fast_sleep(_):
        await orig_sleep(0)
    monkeypatch.setattr(kc.asyncio, "sleep", _fast_sleep)

    result = await client._request_with_resilience(
        "GET", "/portfolio/orders", operation_name="get_open_orders"
    )

    assert result.success, f"expected retry to succeed, got {result.error}"
    assert len(sends) == 2, f"expected re-sign+retry, got {len(sends)} sends"
    client._authenticate.assert_not_called(), (
        "timestamp_expired must not trigger _authenticate — signature was stale, not creds"
    )
    assert sends[0]["KALSHI-ACCESS-TIMESTAMP"] != sends[1]["KALSHI-ACCESS-TIMESTAMP"]


# ---------------------------------------------------------------------------
# client_v2._request — transient transport errors (RemoteProtocolError et al.)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_v2_request_retries_remote_protocol_error_on_reads():
    """Server dropping a half-open keep-alive conn is transient for reads —
    retry on a fresh connection with a fresh signature."""
    from merid.event_venues.kalshi import client_v2 as cv2

    client = _v2_client()
    client._client = None
    drops = []

    orig_drop = client._drop_http_client
    async def _drop():
        drops.append(1)
    client._drop_http_client = _drop

    calls: List[dict] = []

    class _FakeHTTP:
        async def request(self, method, path, headers=None, **kw):
            calls.append(dict(headers or {}))
            if len(calls) == 1:
                raise httpx.RemoteProtocolError(
                    "Server disconnected without sending a response."
                )
            return _resp(200, '{"balance": 100}')

    async def _get_client():
        return _FakeHTTP()

    client._get_client = _get_client

    import asyncio as _a
    orig_sleep = _a.sleep
    async def _fast_sleep(_):
        await orig_sleep(0)
    cv2.asyncio.sleep = _fast_sleep
    try:
        resp = await client._request(
            "GET", "/portfolio/positions", skip_rate_limiter=True
        )
    finally:
        cv2.asyncio.sleep = orig_sleep

    assert resp.status_code == 200
    assert len(calls) == 2, f"expected retry, got {len(calls)} sends"
    assert drops, "pool must be dropped so the retry uses a fresh connection"
    assert calls[0]["KALSHI-ACCESS-TIMESTAMP"] != calls[1]["KALSHI-ACCESS-TIMESTAMP"]


@pytest.mark.asyncio
async def test_v2_request_remote_protocol_error_on_writes_raises():
    """On a WRITE the outcome is ambiguous (request may have been processed
    before the drop) — must surface for reconciliation, never blind-retry."""
    from merid.event_venues.kalshi import client_v2 as cv2

    client = _v2_client()
    client._client = None
    calls = 0

    class _FakeHTTP:
        async def request(self, method, path, headers=None, **kw):
            nonlocal calls
            calls += 1
            raise httpx.RemoteProtocolError(
                "Server disconnected without sending a response."
            )

    async def _get_client():
        return _FakeHTTP()

    client._get_client = _get_client

    with pytest.raises(httpx.RemoteProtocolError):
        await client._request(
            "POST", "/portfolio/orders", is_write=True, skip_rate_limiter=True
        )
    assert calls == 1, f"write must not be retried, got {calls} sends"


@pytest.mark.asyncio
async def test_v2_request_transport_error_honors_allow_retry_false():
    """allow_retry=False callers (get_balance) classify the result themselves."""
    from merid.event_venues.kalshi import client_v2 as cv2

    client = _v2_client()
    client._client = None
    calls = 0

    class _FakeHTTP:
        async def request(self, method, path, headers=None, **kw):
            nonlocal calls
            calls += 1
            raise httpx.RemoteProtocolError(
                "Server disconnected without sending a response."
            )

    async def _get_client():
        return _FakeHTTP()

    client._get_client = _get_client

    with pytest.raises(httpx.RemoteProtocolError):
        await client._request(
            "GET", "/portfolio/balance",
            skip_rate_limiter=True, allow_retry=False,
        )
    assert calls == 1
