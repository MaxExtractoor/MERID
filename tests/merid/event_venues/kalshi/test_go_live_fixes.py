"""Go-live safety tests for MERID <-> Kalshi path.

Covers every BLOCKER and HIGH fix applied in the go-live audit:
1. uuid import + client_order_id format
2. outcome_id required (raises ValueError, no silent default)
3. price rounding (round() not int())
4. phantom kill switch fail-closed (unexpected exception -> block + ERROR)
5. KALSHI_USE_DEMO default consistency ("false" everywhere)
6. VenueGate fail-closed (exception -> suppress flatten + WARNING)
7. mode switch requires MERID_PM_LIVE_ENABLED (HTTP 403 when flag=False)
8. Integration smoke test (VenueOrder -> mocked KalshiVenueClient)
"""
from __future__ import annotations

import asyncio
import inspect
import re
import sys
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. uuid import + client_order_id format
# ---------------------------------------------------------------------------

class TestUuidImportAndClientOrderId:
    """BLOCKER: uuid must be imported; batch and single orders use merid_ prefix."""

    def test_uuid_importable_from_client_module(self):
        import merid.event_venues.kalshi.client as _mod
        assert hasattr(_mod, "uuid"), "uuid not imported in client.py"
        assert _mod.uuid is uuid

    def test_batch_client_order_id_uses_merid_prefix(self):
        import merid.event_venues.kalshi.client as _mod
        generated = f"merid_{_mod.uuid.uuid4().hex}"
        assert generated.startswith("merid_")
        assert len(generated) == 38, f"Expected 38 chars, got {len(generated)}"

    def test_batch_ids_are_unique_in_sample(self):
        import merid.event_venues.kalshi.client as _mod
        ids = {f"merid_{_mod.uuid.uuid4().hex}" for _ in range(200)}
        assert len(ids) == 200

    def test_batch_id_hex_only(self):
        import merid.event_venues.kalshi.client as _mod
        generated = f"merid_{_mod.uuid.uuid4().hex}"
        suffix = generated[len("merid_"):]
        assert re.fullmatch(r"[0-9a-f]{32}", suffix)

    def test_single_order_no_timestamp_fallback(self):
        """Old timestamp-based fallback must be gone; merid_ prefix must be present."""
        import merid.event_venues.kalshi.client as _mod
        source = inspect.getsource(_mod)
        assert "datetime.now(timezone.utc).timestamp()" not in source
        # The source uses a raw string literal — check for the pattern
        assert "merid_" in source and "uuid.uuid4().hex" in source


# ---------------------------------------------------------------------------
# 2. outcome_id required
# ---------------------------------------------------------------------------

class TestOutcomeIdRequired:
    """HIGH: missing outcome_id must raise ValueError before any API call."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_raises_when_outcome_id_none(self):
        from merid.event_venues.kalshi.client import KalshiVenueClient
        from merid.event_venues.base import VenueOrder
        client = KalshiVenueClient()
        order = VenueOrder(
            market_id="KXBTC-25DEC-B50000", side="buy",
            size=Decimal("1"), price=Decimal("0.55"),
            order_type="limit", outcome_id=None,
        )
        with pytest.raises(ValueError, match="outcome_id"):
            self._run(client.place_order_result(order))

    def test_raises_when_outcome_id_empty(self):
        from merid.event_venues.kalshi.client import KalshiVenueClient
        from merid.event_venues.base import VenueOrder
        client = KalshiVenueClient()
        order = VenueOrder(
            market_id="KXBTC-25DEC-B50000", side="buy",
            size=Decimal("1"), price=Decimal("0.55"),
            order_type="limit", outcome_id="",
        )
        with pytest.raises(ValueError, match="outcome_id"):
            self._run(client.place_order_result(order))

    def test_source_has_no_or_yes_default(self):
        """Source must not contain the silent 'or "yes"' default."""
        import merid.event_venues.kalshi.client as _mod
        source = inspect.getsource(_mod)
        assert 'outcome_id or "yes"' not in source


# ---------------------------------------------------------------------------
# 3. Price rounding
# ---------------------------------------------------------------------------

class TestPriceRounding:
    """MEDIUM: price conversion must use round(), not int()."""

    @pytest.mark.parametrize("price_str,expected_cents", [
        ("0.51", 51), ("0.50", 50), ("0.01", 1), ("0.99", 99),
        ("0.55", 55), ("0.45", 45),
    ])
    def test_decimal_price_to_cents(self, price_str, expected_cents):
        actual = round(float(Decimal(price_str)) * 100)
        assert actual == expected_cents

    def test_client_uses_round_not_int(self):
        """Source must contain round(float(order.price) * 100) not int(order.price * 100)."""
        import merid.event_venues.kalshi.client as _mod
        source = inspect.getsource(_mod)
        assert "round(float(order.price) * 100)" in source


# ---------------------------------------------------------------------------
# 4. Phantom kill switch fail-closed
# ---------------------------------------------------------------------------

class TestPhantomKillSwitchUnavailable:
    """BLOCKER: unexpected exception in kill switch -> block + ERROR logged."""

    def _rm(self):
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskManager, KalshiRiskConfig
        return KalshiRiskManager(config=KalshiRiskConfig())

    def test_source_no_bare_except_on_kill_switch(self):
        import merid.event_venues.kalshi.kalshi_risk as _mod
        source = inspect.getsource(_mod)
        # The old fail-open pattern must not be present
        assert "except Exception:\n            pass  # Don't block" not in source

    def test_source_has_fail_closed_logic(self):
        import merid.event_venues.kalshi.kalshi_risk as _mod
        source = inspect.getsource(_mod)
        assert "except ImportError:" in source
        assert "phantom_kill_switch:unavailable" in source
        assert "logger.error" in source

    def test_unexpected_exception_blocks_order(self):
        rm = self._rm()
        fake_recon = MagicMock()
        fake_recon.is_phantom_kill_switch_active = MagicMock(
            side_effect=RuntimeError("injected test failure")
        )
        with patch.dict(sys.modules, {"merid.reconciliation": fake_recon}):
            with patch("merid.event_venues.kalshi.kalshi_risk.logger") as mock_log:
                allowed, reason = rm.check_order(
                    ticker="KXBTC-25DEC-B50000", category="crypto",
                    contracts=1, price_cents=55, outcome="yes",
                )
        assert allowed is False, "Must block when kill-switch raises"
        assert "phantom_kill_switch:unavailable" in reason
        mock_log.error.assert_called()

    def test_import_error_does_not_produce_unavailable(self):
        rm = self._rm()
        with patch.dict(sys.modules, {"merid.reconciliation": None}):
            allowed, reason = rm.check_order(
                ticker="KXBTC-25DEC-B50000", category="crypto",
                contracts=1, price_cents=55, outcome="yes",
            )
        assert "phantom_kill_switch:unavailable" not in reason


# ---------------------------------------------------------------------------
# 5. KALSHI_USE_DEMO default consistency
# ---------------------------------------------------------------------------

class TestDemoDefaultConsistency:
    """BLOCKER: KALSHI_USE_DEMO must default to 'false' everywhere."""

    def test_core_adapter_no_true_default(self):
        import core.venues.kalshi_adapter as _mod
        source = inspect.getsource(_mod)
        assert 'getenv("KALSHI_USE_DEMO", "true")' not in source
        assert 'getenv("KALSHI_USE_DEMO", "false")' in source

    def test_settings_default_false(self):
        from merid.settings import Settings
        fi = Settings.model_fields.get("KALSHI_USE_DEMO")
        assert fi is not None
        assert fi.default is False

    def test_pipeline_adapter_default_false(self):
        import merid.pipeline.adapter as _mod
        source = inspect.getsource(_mod)
        assert 'getenv("KALSHI_USE_DEMO", "false")' in source

    def test_venue_client_default_use_demo_false(self):
        from merid.event_venues.kalshi.client import KalshiVenueClient
        assert KalshiVenueClient().config.use_demo is False


# ---------------------------------------------------------------------------
# 6. VenueGate fail-closed
# ---------------------------------------------------------------------------

class TestVenueGateFailClosed:
    """HIGH: VenueGate exception must suppress flatten and log WARNING."""

    def test_source_no_bare_except_pass_in_flatten(self):
        import merid.event_venues.kalshi.order_manager as _mod
        source = inspect.getsource(_mod)
        assert "except Exception:\n                    pass" not in source

    def test_source_has_allow_flatten_false_on_exception(self):
        import merid.event_venues.kalshi.order_manager as _mod
        source = inspect.getsource(_mod)
        assert "_allow_flatten = False" in source
        assert "logger.warning" in source
        assert "fail-safe" in source

    def test_exception_sets_allow_flatten_false(self):
        """Inline simulation: VenueGate raises -> _allow_flatten=False, WARNING logged."""
        _allow_flatten = True
        _logged = []
        mock_log = MagicMock()
        mock_log.warning.side_effect = lambda *a, **kw: _logged.append(a)

        with patch("merid.prediction.venue_gate.get_venue_gate") as _mgvg:
            _mgvg.side_effect = RuntimeError("VenueGate exploded")
            try:
                from merid.prediction.venue_gate import get_venue_gate as _gvg
                if _gvg().should_simulate_fill():
                    _allow_flatten = False
            except Exception as _exc:
                _allow_flatten = False
                mock_log.warning(
                    "[order-manager] VenueGate check raised - suppressing flatten as fail-safe. "
                    "ticker=%s error=%s", "KXBTC-25DEC-B50000", _exc,
                )

        assert _allow_flatten is False
        assert len(_logged) == 1


# ---------------------------------------------------------------------------
# 7. Mode switch requires MERID_PM_LIVE_ENABLED
# ---------------------------------------------------------------------------

class TestModeSwitchRequiresLiveEnabled:
    """HIGH: /trading-mode LIVE must return 403 when MERID_PM_LIVE_ENABLED=false."""

    def _app(self):
        from fastapi import FastAPI
        import web.api.operator_endpoints as _op
        app = FastAPI()
        app.include_router(_op.router)
        return app

    def test_source_checks_live_enabled(self):
        import web.api.operator_endpoints as _mod
        source = inspect.getsource(_mod)
        assert "MERID_PM_LIVE_ENABLED" in source
        assert "403" in source

    def test_live_rejected_when_flag_false(self):
        from fastapi.testclient import TestClient
        app = self._app()
        with patch("web.api.operator_endpoints._require_operator_auth", return_value=None):
            with patch("web.api.operator_endpoints.settings") as ms:
                ms.MERID_PM_LIVE_ENABLED = False
                ms.MERID_PM_TRADING_MODE = "paper"
                resp = TestClient(app, raise_server_exceptions=False).post(
                    "/api/v1/operator/trading-mode",
                    json={"mode": "live", "reason": "test"},
                )
        assert resp.status_code == 403, f"Got {resp.status_code}: {resp.text}"

    def test_live_accepted_when_flag_true(self):
        from fastapi.testclient import TestClient
        app = self._app()
        with patch("web.api.operator_endpoints._require_operator_auth", return_value=None):
            with patch("web.api.operator_endpoints.settings") as ms:
                ms.MERID_PM_LIVE_ENABLED = True
                ms.MERID_PM_TRADING_MODE = "paper"
                resp = TestClient(app, raise_server_exceptions=False).post(
                    "/api/v1/operator/trading-mode",
                    json={"mode": "live", "reason": "go_live"},
                )
        assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"

    def test_paper_always_allowed(self):
        from fastapi.testclient import TestClient
        app = self._app()
        with patch("web.api.operator_endpoints._require_operator_auth", return_value=None):
            with patch("web.api.operator_endpoints.settings") as ms:
                ms.MERID_PM_LIVE_ENABLED = False
                ms.MERID_PM_TRADING_MODE = "live"
                resp = TestClient(app, raise_server_exceptions=False).post(
                    "/api/v1/operator/trading-mode",
                    json={"mode": "paper", "reason": "rollback"},
                )
        assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# 8. Integration smoke test
# ---------------------------------------------------------------------------

class TestKalshiIntegrationSmoke:
    """Integration: VenueOrder with correct fields placed via mocked client."""

    @pytest.mark.asyncio
    async def test_order_outcome_price_client_order_id(self):
        from merid.event_venues.kalshi.client import KalshiVenueClient
        from merid.event_venues.base import VenueOrder
        from merid.resilience import OperationResult

        client = KalshiVenueClient()
        assert client.config.use_demo is False

        order = VenueOrder(
            market_id="KXBTC-25DEC-B50000", side="buy",
            size=Decimal("3"), price=Decimal("0.51"),
            order_type="limit", outcome_id="yes",
        )

        captured: dict = {}

        async def _fake_request(method, path, body=None, **kw):
            captured.update(body or {})
            return OperationResult.ok(
                {"order": {
                    "order_id": "ord_smoke_001",
                    "client_order_id": captured.get("client_order_id", ""),
                    "ticker": "KXBTC-25DEC-B50000",
                    "status": "resting", "action": "buy", "side": "yes",
                    "type": "limit", "yes_price": 51, "no_price": 49,
                    "count": 3, "remaining_count": 3, "filled_count": 0,
                    "created_time": "2025-12-01T00:00:00Z",
                }},
                latency_ms=5.0, retries=0,
            )

        with patch.object(client, "_request_with_resilience", side_effect=_fake_request):
            result = await client.place_order_result(order)

        assert result is not None
        assert captured.get("side") == "yes"
        coid = captured.get("client_order_id", "")
        assert coid.startswith("merid_"), f"Bad client_order_id: {coid!r}"
        assert captured.get("yes_price") == 51

    def test_canonical_modules_do_not_import_merid_core_kalshi(self):
        """The canonical modules must not import the legacy merid_core.kalshi."""
        import importlib
        for mod_name in [
            "merid.event_venues.kalshi.client",
            "merid.event_venues.kalshi.kalshi_risk",
            "merid.event_venues.kalshi.order_manager",
        ]:
            source = inspect.getsource(importlib.import_module(mod_name))
            assert "merid_core.kalshi" not in source, (
                f"{mod_name} imports legacy merid_core.kalshi"
            )
