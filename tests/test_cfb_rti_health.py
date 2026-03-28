"""CFB RTI health gate tests.

Covers:
- ``SettlementRtiBuffer`` simulation adapter produces ticks.
- ``SettlementRtiBuffer.is_healthy()`` / ``health_dict()`` semantics.
- ``require_cfb_for_live_trading()`` safety gate:
    * passes silently in non-live environments.
    * passes when MERID_ALLOW_NULL_CFB=1 is set.
    * passes in live mode when the buffer has a fresh tick.
    * raises ``CfbRtiUnhealthyError`` in live mode when no tick is buffered.
    * raises ``CfbRtiUnhealthyError`` in live mode when the only tick is stale.
- Rolling buffer caps at RTI_BUFFER_SIZE.
- ``get_rti_buffer()`` returns the same singleton on repeated calls.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from merid.data.settlement_rti_buffer import (
    CfbRtiUnhealthyError,
    RTI_BUFFER_SIZE,
    RTI_STALE_THRESHOLD_S,
    RtiTick,
    SettlementRtiBuffer,
    get_rti_buffer,
    require_cfb_for_live_trading,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sim_buffer(**kwargs) -> SettlementRtiBuffer:
    """Return a simulation-mode buffer with a short poll interval."""
    return SettlementRtiBuffer(adapter_type="simulation", poll_interval_s=0.05, **kwargs)


def _fresh_tick(index_name: str = "BRTI_SIM", value: float = 95_000.0) -> RtiTick:
    return RtiTick(index_name=index_name, value=value, received_at=time.time())


def _stale_tick(index_name: str = "BRTI_SIM", value: float = 90_000.0) -> RtiTick:
    return RtiTick(
        index_name=index_name,
        value=value,
        received_at=time.time() - RTI_STALE_THRESHOLD_S - 1,
    )


# ---------------------------------------------------------------------------
# SettlementRtiBuffer — simulation adapter
# ---------------------------------------------------------------------------

class TestSimulationAdapter:
    def test_poll_once_returns_tick(self) -> None:
        buf = _sim_buffer()
        tick = buf.poll_once()

        assert tick is not None
        assert tick.index_name == "BRTI_SIM"
        assert isinstance(tick.value, float)

    def test_poll_once_stores_tick(self) -> None:
        buf = _sim_buffer()
        buf.poll_once()

        assert buf.tick_count == 1
        assert buf.last_tick is not None

    def test_multiple_polls_accumulate(self) -> None:
        buf = _sim_buffer()
        for _ in range(5):
            buf.poll_once()

        assert buf.tick_count == 5

    def test_buffer_caps_at_max_size(self) -> None:
        buf = _sim_buffer()
        for _ in range(RTI_BUFFER_SIZE + 10):
            buf.poll_once()

        assert buf.tick_count == RTI_BUFFER_SIZE


# ---------------------------------------------------------------------------
# is_healthy / health_dict
# ---------------------------------------------------------------------------

class TestHealthStatus:
    def test_empty_buffer_not_healthy(self) -> None:
        buf = _sim_buffer()
        assert not buf.is_healthy()

    def test_fresh_tick_is_healthy(self) -> None:
        buf = _sim_buffer()
        buf._push(_fresh_tick())
        assert buf.is_healthy()

    def test_stale_tick_not_healthy(self) -> None:
        buf = _sim_buffer()
        buf._push(_stale_tick())
        assert not buf.is_healthy()

    def test_health_dict_status_healthy(self) -> None:
        buf = _sim_buffer()
        buf._push(_fresh_tick())
        d = buf.health_dict()

        assert d["status"] == "healthy"
        assert d["adapter"] == "simulation"
        assert d["tick_count"] == 1
        assert d["last_tick"] is not None
        assert "age_seconds" in d["last_tick"]

    def test_health_dict_status_no_data_when_empty(self) -> None:
        buf = _sim_buffer()
        d = buf.health_dict()

        assert d["status"] == "no_data"
        assert d["last_tick"] is None

    def test_health_dict_status_no_data_when_stale(self) -> None:
        buf = _sim_buffer()
        buf._push(_stale_tick())
        d = buf.health_dict()

        assert d["status"] == "no_data"

    def test_health_dict_contains_required_fields(self) -> None:
        buf = _sim_buffer()
        d = buf.health_dict()
        for key in ("status", "adapter", "tick_count", "last_tick",
                    "stale_threshold_s", "poll_interval_s", "timestamp"):
            assert key in d, f"Missing field: {key}"


# ---------------------------------------------------------------------------
# require_cfb_for_live_trading — safety gate
# ---------------------------------------------------------------------------

class TestRequireCfbForLiveTrading:
    def test_noop_in_paper_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Gate is inactive for non-live environments."""
        monkeypatch.setenv("KALSHI_ENV", "paper")
        # Should not raise regardless of buffer state
        require_cfb_for_live_trading()

    def test_noop_in_demo_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KALSHI_ENV", "demo")
        require_cfb_for_live_trading()

    def test_noop_when_kalshi_env_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("KALSHI_ENV", raising=False)
        require_cfb_for_live_trading()

    def test_allow_null_cfb_bypasses_gate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MERID_ALLOW_NULL_CFB=1 unblocks trading even with empty buffer."""
        monkeypatch.setenv("KALSHI_ENV", "live")
        monkeypatch.setenv("MERID_ALLOW_NULL_CFB", "1")
        # Reset singleton so we get a fresh (empty) buffer
        with patch(
            "merid.data.settlement_rti_buffer._singleton",
            _sim_buffer(),
        ):
            require_cfb_for_live_trading()  # must not raise

    def test_raises_when_live_and_empty_buffer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("KALSHI_ENV", "live")
        monkeypatch.delenv("MERID_ALLOW_NULL_CFB", raising=False)

        empty_buf = _sim_buffer()
        with patch("merid.data.settlement_rti_buffer._singleton", empty_buf):
            with pytest.raises(CfbRtiUnhealthyError):
                require_cfb_for_live_trading()

    def test_raises_when_live_and_stale_tick(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("KALSHI_ENV", "live")
        monkeypatch.delenv("MERID_ALLOW_NULL_CFB", raising=False)

        stale_buf = _sim_buffer()
        stale_buf._push(_stale_tick())
        with patch("merid.data.settlement_rti_buffer._singleton", stale_buf):
            with pytest.raises(CfbRtiUnhealthyError):
                require_cfb_for_live_trading()

    def test_passes_when_live_and_healthy_tick(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("KALSHI_ENV", "live")
        monkeypatch.delenv("MERID_ALLOW_NULL_CFB", raising=False)

        healthy_buf = _sim_buffer()
        healthy_buf._push(_fresh_tick())
        with patch("merid.data.settlement_rti_buffer._singleton", healthy_buf):
            require_cfb_for_live_trading()  # must not raise

    def test_error_message_mentions_poll_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("KALSHI_ENV", "live")
        monkeypatch.delenv("MERID_ALLOW_NULL_CFB", raising=False)

        empty_buf = _sim_buffer()
        with patch("merid.data.settlement_rti_buffer._singleton", empty_buf):
            with pytest.raises(CfbRtiUnhealthyError, match="MERID_CFB_RTI_POLL_URL"):
                require_cfb_for_live_trading()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestGetRtiBuffer:
    def test_same_instance_returned_twice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MERID_CFB_RTI_ADAPTER", "simulation")
        import merid.data.settlement_rti_buffer as _mod
        # Reset singleton so env change takes effect
        monkeypatch.setattr(_mod, "_singleton", None)
        buf_a = get_rti_buffer()
        buf_b = get_rti_buffer()
        assert buf_a is buf_b

    def test_singleton_is_settlement_rti_buffer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MERID_CFB_RTI_ADAPTER", "simulation")
        import merid.data.settlement_rti_buffer as _mod
        monkeypatch.setattr(_mod, "_singleton", None)
        assert isinstance(get_rti_buffer(), SettlementRtiBuffer)


# ---------------------------------------------------------------------------
# Live adapter — missing URL raises ValueError
# ---------------------------------------------------------------------------

class TestLiveAdapterMissingUrl:
    def test_raises_value_error_without_poll_url(self) -> None:
        with pytest.raises(ValueError, match="MERID_CFB_RTI_POLL_URL"):
            SettlementRtiBuffer(adapter_type="live", poll_url="")


# ---------------------------------------------------------------------------
# Live adapter — successful fetch (mocked httpx)
# ---------------------------------------------------------------------------

class TestLiveAdapterFetch:
    def test_fetch_parses_cfb_envelope(self) -> None:
        payload = {"name": "BRTI", "value": 96_500.0}

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = payload

        with patch("httpx.get", return_value=mock_response):
            buf = SettlementRtiBuffer(
                adapter_type="live",
                poll_url="https://api.cfbenchmarks.com/v1/rtis/BRTI/value",
            )
            tick = buf.poll_once()

        assert tick is not None
        assert tick.index_name == "BRTI"
        assert tick.value == pytest.approx(96_500.0)

    def test_fetch_returns_none_on_http_error(self) -> None:
        import httpx as _httpx

        with patch(
            "httpx.get",
            side_effect=_httpx.HTTPStatusError(
                "403", request=MagicMock(), response=MagicMock()
            ),
        ):
            buf = SettlementRtiBuffer(
                adapter_type="live",
                poll_url="https://api.cfbenchmarks.com/v1/rtis/BRTI/value",
            )
            tick = buf.poll_once()

        assert tick is None
        assert buf.tick_count == 0
