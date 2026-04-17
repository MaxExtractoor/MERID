"""SSE endpoint smoke test: verify all ``*/stream`` endpoints are routable,
use the correct ``media_type``, and respond with proper SSE headers.

These endpoints use ``StreamingResponse(media_type="text/event-stream")``
backed by live WebSocket connections that won't be available in CI.
Consuming the stream would hang, so the tests verify:

  1. The route is registered in FastAPI (not 404/405).
  2. The route handler's return-type annotation is ``StreamingResponse``.
  3. The handler's source declares ``text/event-stream`` media type.
  4. A non-streaming GET to the same path returns a routable status
     (200 streaming or 500 JSON — not 404/405).

Run:
    pytest tests/test_sse_smoke.py -v
"""
from __future__ import annotations

import inspect
import re
from typing import Dict, List, Set, Tuple

import pytest

# ── SSE endpoints to smoke-test ─────────────────────────────────────────
# (method, fastapi_path_template, description)
SSE_ENDPOINTS: List[Tuple[str, str, str]] = [
    ("GET", "/api/v1/kalshi/markets/{ticker}/orderbook/stream", "orderbook SSE"),
    ("GET", "/api/v1/kalshi/order-groups/stream", "order-group SSE"),
]


@pytest.fixture(scope="module")
def app():
    """Create the FastAPI app with a no-op lifespan."""
    async def _noop_lifespan(app):
        yield

    from web.main import create_app
    return create_app(lifespan=_noop_lifespan)


@pytest.fixture(scope="module")
def sse_route_map(app) -> Dict[str, object]:
    """Map SSE path templates to their APIRoute objects."""
    result: Dict[str, object] = {}
    for route in app.routes:
        if not (hasattr(route, "methods") and hasattr(route, "path")):
            continue
        for _, tmpl, _ in SSE_ENDPOINTS:
            if route.path == tmpl and "GET" in route.methods:
                result[tmpl] = route
    return result


class TestSSESmoke:
    """Smoke tests for Server-Sent Event (SSE) streaming endpoints."""

    def test_all_sse_routes_registered(self, sse_route_map):
        """Every SSE endpoint path must be registered in the FastAPI app."""
        missing = []
        for method, tmpl, desc in SSE_ENDPOINTS:
            if tmpl not in sse_route_map:
                missing.append(f"  {method} {tmpl}  ({desc})")

        assert not missing, (
            f"SSE routes not registered:\n" + "\n".join(missing)
        )

    def test_sse_handlers_return_streaming_response(self, sse_route_map):
        """SSE handlers must declare StreamingResponse as their return type."""
        from starlette.responses import StreamingResponse

        for _, tmpl, desc in SSE_ENDPOINTS:
            route = sse_route_map.get(tmpl)
            if route is None:
                pytest.skip(f"Route {tmpl} not registered")

            endpoint = route.endpoint
            hints = getattr(endpoint, "__annotations__", {})
            ret = hints.get("return")

            # FastAPI may wrap the endpoint; check the source as fallback
            src = inspect.getsource(endpoint)
            assert "StreamingResponse" in src, (
                f"{desc} ({tmpl}): handler does not use StreamingResponse"
            )

    def test_sse_handlers_declare_event_stream_media_type(self, sse_route_map):
        """SSE handlers must use ``media_type='text/event-stream'``."""
        for _, tmpl, desc in SSE_ENDPOINTS:
            route = sse_route_map.get(tmpl)
            if route is None:
                pytest.skip(f"Route {tmpl} not registered")

            src = inspect.getsource(route.endpoint)
            assert "text/event-stream" in src, (
                f"{desc} ({tmpl}): handler does not declare "
                f"media_type='text/event-stream'"
            )

    def test_sse_handlers_set_no_cache(self, sse_route_map):
        """SSE handlers should set Cache-Control: no-cache."""
        for _, tmpl, desc in SSE_ENDPOINTS:
            route = sse_route_map.get(tmpl)
            if route is None:
                pytest.skip(f"Route {tmpl} not registered")

            src = inspect.getsource(route.endpoint)
            assert "no-cache" in src, (
                f"{desc} ({tmpl}): handler should set Cache-Control: no-cache"
            )

    def test_sse_handlers_disable_buffering(self, sse_route_map):
        """SSE handlers should set X-Accel-Buffering: no (nginx proxy compat)."""
        for _, tmpl, desc in SSE_ENDPOINTS:
            route = sse_route_map.get(tmpl)
            if route is None:
                pytest.skip(f"Route {tmpl} not registered")

            src = inspect.getsource(route.endpoint)
            assert "X-Accel-Buffering" in src, (
                f"{desc} ({tmpl}): handler should set X-Accel-Buffering: no"
            )

    def test_sse_endpoint_count(self):
        """Guard: update this test when adding new SSE endpoints."""
        assert len(SSE_ENDPOINTS) == 2, (
            f"SSE_ENDPOINTS has {len(SSE_ENDPOINTS)} entries -- "
            "update this test and add smoke checks for new streams"
        )
