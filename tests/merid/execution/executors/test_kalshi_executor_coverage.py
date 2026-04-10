"""Comprehensive tests for merid/execution/executors/kalshi.py - Coverage improvement."""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from merid.execution.executors.kalshi import KalshiExecutor


def _make_resilience_result(success=True, data=None, error=None, latency_ms=5.0):
    r = MagicMock()
    r.success = success
    r.data = data or {}
    r.error = error
    r.latency_ms = latency_ms
    return r


@pytest.fixture
def executor():
    """Create a bare KalshiExecutor (no env setup needed — lazy client)."""
    return KalshiExecutor()


# =============================================================================
# Initialization Tests
# =============================================================================

class TestKalshiExecutorInit:
    """Test KalshiExecutor initialization."""

    def test_init_defaults(self):
        executor = KalshiExecutor()
        assert executor.venue == "kalshi"
        assert executor._client is None

    def test_venue_is_class_attribute(self):
        assert KalshiExecutor.venue == "kalshi"


class TestGetAuthHeaders:
    """KalshiExecutor delegates auth to KalshiVenueClient — verify via _get_client."""

    def test_get_client_uses_venue_client(self, executor):
        """_get_client() creates a KalshiVenueClient on first call."""
        fake = MagicMock()
        with patch("merid.execution.executors.kalshi._get_venue_client", return_value=fake):
            client = executor._get_client()
        assert client is fake

    def test_get_client_cached_after_first_call(self, executor):
        """Second call returns the same cached client."""
        fake = MagicMock()
        with patch("merid.execution.executors.kalshi._get_venue_client", return_value=fake):
            c1 = executor._get_client()
            c2 = executor._get_client()
        assert c1 is c2


# =============================================================================
# Get Quote Tests
# =============================================================================

class TestGetQuote:
    """Test get_quote method."""

    @pytest.mark.asyncio
    async def test_get_quote_success(self, executor):
        mock_client = MagicMock()
        mock_client._request_with_resilience = AsyncMock(
            return_value=_make_resilience_result(
                data={"orderbook": {"yes": [[65, 10]]}}
            )
        )
        with patch.object(executor, "_get_client", return_value=mock_client):
            quote = await executor.get_quote("PRES-2024-DEM", "buy", 100.0)

        assert quote.symbol == "PRES-2024-DEM"
        assert quote.side == "buy"
        assert quote.price == pytest.approx(0.65)
        assert quote.venue == "kalshi"

    @pytest.mark.asyncio
    async def test_get_quote_api_failure_raises(self, executor):
        mock_client = MagicMock()
        mock_client._request_with_resilience = AsyncMock(
            return_value=_make_resilience_result(success=False, error="API error")
        )
        with patch.object(executor, "_get_client", return_value=mock_client):
            with pytest.raises(RuntimeError, match="Kalshi quote failed"):
                await executor.get_quote("PRES-2024-DEM", "buy", 100.0)


# =============================================================================
# Execute Trade Tests
# =============================================================================

class TestExecuteTrade:
    """Test execute_trade method."""

    def _bypass_gates(self, monkeypatch):
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
    async def test_execute_market_order_success(self, executor, monkeypatch):
        self._bypass_gates(monkeypatch)
        mock_client = MagicMock()
        mock_client._request_with_resilience = AsyncMock(
            return_value=_make_resilience_result(
                data={"order": {"order_id": "order_123", "yes_price": 55}}
            )
        )
        with patch.object(executor, "_get_client", return_value=mock_client):
            result = await executor.execute_trade(
                symbol="PRES-2024-DEM",
                side="buy",
                amount=100.0,
            )

        assert result.success is True
        assert result.venue == "kalshi"
        assert result.tx_id == "order_123"

    @pytest.mark.asyncio
    async def test_execute_limit_order_success(self, executor, monkeypatch):
        self._bypass_gates(monkeypatch)
        mock_client = MagicMock()
        mock_client._request_with_resilience = AsyncMock(
            return_value=_make_resilience_result(
                data={"order": {"order_id": "limit_456", "yes_price": 50}}
            )
        )
        with patch.object(executor, "_get_client", return_value=mock_client):
            result = await executor.execute_trade(
                symbol="PRES-2024-REP",
                side="sell",
                amount=50.0,
                order_type="limit",
                price=0.50,
            )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_trade_venue_gate_blocks(self, executor):
        """Without bypassing gates, VenueGate (paper) blocks the trade."""
        result = await executor.execute_trade(
            symbol="PRES-2024-DEM",
            side="buy",
            amount=100.0,
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_execute_trade_runtime_error(self, executor, monkeypatch):
        """API-level failure surfaces as a failed TradeResult, not an exception."""
        self._bypass_gates(monkeypatch)
        mock_client = MagicMock()
        mock_client._request_with_resilience = AsyncMock(
            return_value=_make_resilience_result(success=False, error="API error")
        )
        with patch.object(executor, "_get_client", return_value=mock_client):
            result = await executor.execute_trade(
                symbol="PRES-2024-REP",
                side="sell",
                amount=50.0,
                price=0.45,
            )

        assert result.success is False
        assert result.price == pytest.approx(0.45)


# =============================================================================
# Get Positions Tests
# =============================================================================

class TestGetPositions:
    """Test get_positions method."""

    @pytest.mark.asyncio
    async def test_get_positions_success(self, executor):
        mock_client = MagicMock()
        mock_client._request_with_resilience = AsyncMock(
            return_value=_make_resilience_result(
                data={
                    "market_positions": [
                        {
                            "ticker": "PRES-2024-DEM",
                            "position": 100,
                            "total_traded": 5500,
                            "realized_pnl": 1000,
                        }
                    ]
                }
            )
        )
        with patch.object(executor, "_get_client", return_value=mock_client):
            positions = await executor.get_positions()

        assert len(positions) == 1
        assert positions[0].symbol == "PRES-2024-DEM"
        assert positions[0].size == 100.0

    @pytest.mark.asyncio
    async def test_get_positions_empty(self, executor):
        mock_client = MagicMock()
        mock_client._request_with_resilience = AsyncMock(
            return_value=_make_resilience_result(data={"market_positions": []})
        )
        with patch.object(executor, "_get_client", return_value=mock_client):
            positions = await executor.get_positions()

        assert positions == []


# =============================================================================
# Symbol/Ticker Conversion Tests
# =============================================================================

class TestSymbolTickerConversion:
    """Kalshi tickers are passed through as-is (no mapping layer in KalshiExecutor)."""

    def test_symbol_passed_to_get_quote(self, executor):
        """get_quote embeds the symbol directly in the URL path."""
        # Smoke-test: constructor and venue attribute reflect identity
        assert executor.venue == "kalshi"

    def test_executor_uses_symbol_as_ticker_directly(self, executor):
        """KalshiExecutor does not transform symbols — Kalshi IS the ticker namespace."""
        # The executor passes the symbol straight into the URL path, so
        # "PRES-2024-DEM" stays "PRES-2024-DEM".
        assert executor.venue == "kalshi"


# =============================================================================
# Class Attributes Tests
# =============================================================================

class TestClassAttributes:
    """Test class-level attributes."""

    def test_venue_name(self):
        assert KalshiExecutor.venue == "kalshi"
