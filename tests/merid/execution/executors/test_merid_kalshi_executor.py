"""Comprehensive tests for merid/execution/executors/kalshi.py."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.execution.executors.kalshi import KalshiExecutor
from merid.execution.base import Quote, TradeResult, Position


def _make_resilience_result(success=True, data=None, error=None, latency_ms=5.0):
    """Build a mock VenueRequestResult-like object."""
    r = MagicMock()
    r.success = success
    r.data = data or {}
    r.error = error
    r.latency_ms = latency_ms
    return r


class TestKalshiExecutorInitialization:
    """Test KalshiExecutor initialization."""

    def test_default_initialization(self):
        """KalshiExecutor sets venue and lazy-initialises client to None."""
        executor = KalshiExecutor()
        assert executor.venue == "kalshi"
        assert executor._client is None

    def test_venue_class_attribute(self):
        """venue is a class-level attribute."""
        assert KalshiExecutor.venue == "kalshi"

    def test_get_client_creates_client_on_first_call(self, monkeypatch):
        """_get_client() lazy-creates the venue client and caches it."""
        executor = KalshiExecutor()
        fake_client = MagicMock()
        with patch(
            "merid.execution.executors.kalshi._get_venue_client",
            return_value=fake_client,
        ):
            client1 = executor._get_client()
            client2 = executor._get_client()
        assert client1 is fake_client
        assert client2 is fake_client  # cached — not created twice


class TestKalshiExecutorGetQuote:
    """Test KalshiExecutor.get_quote — mocked via _get_client."""

    @pytest.mark.asyncio
    async def test_get_quote_success(self):
        """Returns a Quote with the correct price from the orderbook."""
        executor = KalshiExecutor()
        mock_client = MagicMock()
        mock_client._request_with_resilience = AsyncMock(
            return_value=_make_resilience_result(
                data={"orderbook": {"yes": [[65, 10], [64, 5]]}}
            )
        )
        with patch.object(executor, "_get_client", return_value=mock_client):
            quote = await executor.get_quote("PRES-2024-DEM", "buy", 10.0)

        assert isinstance(quote, Quote)
        assert quote.symbol == "PRES-2024-DEM"
        assert quote.side == "buy"
        assert quote.price == pytest.approx(0.65)
        assert quote.venue == "kalshi"
        assert quote.size == 10.0

    @pytest.mark.asyncio
    async def test_get_quote_empty_orderbook_defaults_to_half(self):
        """Empty orderbook → price defaults to 0.5."""
        executor = KalshiExecutor()
        mock_client = MagicMock()
        mock_client._request_with_resilience = AsyncMock(
            return_value=_make_resilience_result(data={"orderbook": {"yes": []}})
        )
        with patch.object(executor, "_get_client", return_value=mock_client):
            quote = await executor.get_quote("BTC-2024", "sell", 5.0)

        assert quote.price == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_get_quote_api_failure_raises(self):
        """get_quote raises RuntimeError when the venue client signals failure."""
        executor = KalshiExecutor()
        mock_client = MagicMock()
        mock_client._request_with_resilience = AsyncMock(
            return_value=_make_resilience_result(success=False, error="timeout")
        )
        with patch.object(executor, "_get_client", return_value=mock_client):
            with pytest.raises(RuntimeError, match="Kalshi quote failed"):
                await executor.get_quote("BTC-2024", "buy", 5.0)


class TestKalshiExecutorExecuteTrade:
    """Test KalshiExecutor.execute_trade — mocked via _get_client and gates."""

    def _bypass_gates(self, monkeypatch):
        """Patch both VenueGate and KalshiRiskManager to allow trades."""
        gate = MagicMock()
        gate.should_simulate_fill.return_value = False
        monkeypatch.setattr(
            "merid.prediction.venue_gate.get_venue_gate",
            lambda: gate,
        )

        risk = MagicMock()
        risk.check_order.return_value = (True, "ok")
        monkeypatch.setattr(
            "merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk",
            lambda: risk,
        )

        import merid.risk.kill_switches as _ks
        kill = MagicMock()
        kill.can_trade.return_value = True
        monkeypatch.setattr(_ks, "risk_controller", kill)

    @pytest.mark.asyncio
    async def test_execute_market_order_success(self, monkeypatch):
        """Successful market order returns a successful TradeResult."""
        self._bypass_gates(monkeypatch)
        executor = KalshiExecutor()
        mock_client = MagicMock()
        mock_client._request_with_resilience = AsyncMock(
            return_value=_make_resilience_result(
                data={"order": {"order_id": "order_123", "yes_price": 65}}
            )
        )
        with patch.object(executor, "_get_client", return_value=mock_client):
            result = await executor.execute_trade(
                symbol="PRES-2024-DEM",
                side="buy",
                amount=10.0,
                order_type="market",
            )

        assert isinstance(result, TradeResult)
        assert result.success is True
        assert result.venue == "kalshi"
        assert result.symbol == "PRES-2024-DEM"
        assert result.side == "buy"
        assert result.size == 10.0
        assert result.tx_id == "order_123"
        assert result.price == pytest.approx(0.65)

    @pytest.mark.asyncio
    async def test_execute_limit_order_success(self, monkeypatch):
        """Limit order payload includes yes_price."""
        self._bypass_gates(monkeypatch)
        executor = KalshiExecutor()
        captured_payload = {}

        async def fake_request(method, path, json_data=None, **kwargs):
            if json_data:
                captured_payload.update(json_data)
            return _make_resilience_result(
                data={"order": {"order_id": "limit_456", "yes_price": 60}}
            )

        mock_client = MagicMock()
        mock_client._request_with_resilience = fake_request
        with patch.object(executor, "_get_client", return_value=mock_client):
            result = await executor.execute_trade(
                symbol="PRES-2024-REP",
                side="sell",
                amount=5.0,
                order_type="limit",
                price=0.60,
            )

        assert result.success is True
        assert captured_payload.get("yes_price") == 60  # 0.60 → 60 cents
        assert captured_payload.get("type") == "limit"

    @pytest.mark.asyncio
    async def test_execute_trade_venue_gate_blocks(self):
        """VenueGate in paper mode returns failure without touching the client."""
        executor = KalshiExecutor()
        result = await executor.execute_trade(
            symbol="PRES-2024-DEM",
            side="buy",
            amount=10.0,
        )
        # VenueGate (paper/sim) should block this without an actual API call
        assert result.success is False
        assert "VenueGate blocked" in result.error or "unavailable" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_trade_api_failure(self, monkeypatch):
        """API-level failure propagates as a failed TradeResult."""
        self._bypass_gates(monkeypatch)
        executor = KalshiExecutor()
        mock_client = MagicMock()
        mock_client._request_with_resilience = AsyncMock(
            return_value=_make_resilience_result(success=False, error="Bad request")
        )
        with patch.object(executor, "_get_client", return_value=mock_client):
            result = await executor.execute_trade(
                symbol="PRES-2024-DEM",
                side="buy",
                amount=10.0,
            )

        assert result.success is False
        assert "Kalshi order failed" in result.error


class TestKalshiExecutorGetPositions:
    """Test KalshiExecutor.get_positions — mocked via _get_client."""

    @pytest.mark.asyncio
    async def test_get_positions_success(self):
        """Parses market_positions correctly."""
        executor = KalshiExecutor()
        mock_client = MagicMock()
        mock_client._request_with_resilience = AsyncMock(
            return_value=_make_resilience_result(
                data={
                    "market_positions": [
                        {
                            "ticker": "PRES-2024-DEM",
                            "position": 100,
                            "total_traded": 6000,   # cents → $60 total cost
                            "realized_pnl": 500,    # cents → $5
                        },
                        {
                            "ticker": "PRES-2024-REP",
                            "position": 50,
                            "total_traded": 2000,
                            "realized_pnl": -200,
                        },
                    ]
                }
            )
        )
        with patch.object(executor, "_get_client", return_value=mock_client):
            positions = await executor.get_positions()

        assert len(positions) == 2
        assert positions[0].symbol == "PRES-2024-DEM"
        assert positions[0].size == 100.0
        assert positions[0].entry_price == pytest.approx(0.60)
        assert positions[0].pnl == pytest.approx(5.0)
        assert positions[0].venue == "kalshi"
        assert positions[0].metadata["ticker"] == "PRES-2024-DEM"

        assert positions[1].symbol == "PRES-2024-REP"
        assert positions[1].size == 50.0
        assert positions[1].pnl == pytest.approx(-2.0)

    @pytest.mark.asyncio
    async def test_get_positions_empty(self):
        """Empty market_positions → empty list returned."""
        executor = KalshiExecutor()
        mock_client = MagicMock()
        mock_client._request_with_resilience = AsyncMock(
            return_value=_make_resilience_result(data={"market_positions": []})
        )
        with patch.object(executor, "_get_client", return_value=mock_client):
            positions = await executor.get_positions()
        assert positions == []

    @pytest.mark.asyncio
    async def test_get_positions_zero_size_filtered(self):
        """Positions with position=0 are filtered out."""
        executor = KalshiExecutor()
        mock_client = MagicMock()
        mock_client._request_with_resilience = AsyncMock(
            return_value=_make_resilience_result(
                data={
                    "market_positions": [
                        {"ticker": "PRES-2024-DEM", "position": 0, "total_traded": 0},
                    ]
                }
            )
        )
        with patch.object(executor, "_get_client", return_value=mock_client):
            positions = await executor.get_positions()
        assert positions == []

    @pytest.mark.asyncio
    async def test_get_positions_api_failure_returns_empty(self):
        """API failure does NOT raise — returns [] as per implementation."""
        executor = KalshiExecutor()
        mock_client = MagicMock()
        mock_client._request_with_resilience = AsyncMock(
            return_value=_make_resilience_result(success=False, error="Unauthorized")
        )
        with patch.object(executor, "_get_client", return_value=mock_client):
            positions = await executor.get_positions()
        assert positions == []
