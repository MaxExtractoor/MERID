"""HTTP Kalshi place_order uses order_router only (no merid_core REST fallback)."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_place_order_propagates_router_failure_no_rest_fallback():
    with patch("web.api.kalshi_api._get_default_order_mode", return_value="paper"):
        with patch("web.api.kalshi_api._get_risk", return_value=None):
            with patch(
                "merid.event_venues.kalshi.order_router.route_order_async",
                new_callable=AsyncMock,
            ) as mock_route:
                mock_route.side_effect = RuntimeError("router down")
                from fastapi import HTTPException

                from web.api.kalshi_api import place_order

                with pytest.raises(HTTPException) as ei:
                    await place_order(
                        ticker="KXTEST",
                        side="yes",
                        action="buy",
                        count=1,
                        price_cents=50,
                    )
                assert ei.value.status_code == 503
