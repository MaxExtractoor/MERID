"""Live Kalshi API orders must fail closed when gate or risk checks error."""

from __future__ import annotations

import unittest
from unittest import mock

from fastapi import HTTPException


class TestKalshiPlaceOrderFailClosed(unittest.TestCase):
    def test_live_gate_raises_returns_503_not_silent_proceed(self) -> None:
        from web.api import kalshi_api

        with mock.patch.object(kalshi_api, "_get_risk", return_value=None):
            with mock.patch.object(
                kalshi_api,
                "_get_default_order_mode",
                return_value="live",
            ):
                with mock.patch(
                    "core.execution_gate.check_execution_gate",
                    side_effect=RuntimeError("boom"),
                ):
                    with mock.patch(
                        "merid.risk.kill_switches.risk_controller",
                    ) as rc:
                        rc.can_trade.return_value = True
                        import asyncio

                        result = asyncio.run(
                            kalshi_api.place_order(
                                ticker="KXTEST-1",
                                side="yes",
                                action="buy",
                                count=1,
                                price_cents=50,
                                mode="live",
                            )
                        )
        assert result["status"] == "rejected"
        assert "execution_gate_unavailable" in (result.get("reason") or "")

    def test_live_risk_check_raises_returns_503(self) -> None:
        from web.api import kalshi_api

        class _Risk:
            def check_order(self, *a, **k):
                raise RuntimeError("risk down")

        with mock.patch.object(kalshi_api, "_get_risk", return_value=_Risk()):
            with mock.patch(
                "core.execution_gate.check_execution_gate",
                return_value=mock.Mock(blocked=False),
            ):
                with self.assertRaises(HTTPException) as ctx:
                    import asyncio

                    asyncio.run(
                        kalshi_api.place_order(
                            ticker="KXTEST-1",
                            side="yes",
                            action="buy",
                            count=1,
                            price_cents=50,
                            mode="live",
                        )
                    )
        self.assertEqual(ctx.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
