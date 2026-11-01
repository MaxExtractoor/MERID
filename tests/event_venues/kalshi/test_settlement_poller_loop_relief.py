"""Event-loop relief regression tests for the settlement poller.

The 24h-lookback settlement poll used to run ``_hydrate_pnl_from_ledger``
(a full in-memory fills-ledger scan) for EVERY fetched row before the dedupe
check — O(settlements x fills) on the event loop every 60s, the measured
cause of ~1s loop stalls and WS/REST book divergence at order time.

These tests pin the fixed behavior:

- dedupe + gradable checks run BEFORE hydration (hydrate = new rows only)
- graded dedupe keys persist to a durable watermark file so restarts do not
  re-grade the entire lookback
- synchronous audit-ledger work in the orphan sweep runs off the event loop
"""

from __future__ import annotations

import threading
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from merid.event_venues.kalshi import settlement_poller as settlement_module
from merid.event_venues.kalshi.settlement_poller import (
    KalshiSettlement,
    KalshiSettlementPoller,
    PollerConfig,
)


def _settled(market_id: str, settled_time: str, result: str = "yes") -> KalshiSettlement:
    return KalshiSettlement.from_api(
        {
            "market_id": market_id,
            "ticker": market_id.split("-")[0],
            "market_result": result,
            "value": 100 if result == "yes" else 0,
            "settled_time": settled_time,
        }
    )


def _cancelled(market_id: str, settled_time: str) -> KalshiSettlement:
    return KalshiSettlement.from_api(
        {
            "market_id": market_id,
            "ticker": market_id.split("-")[0],
            "market_result": "cancelled",
            "settled_time": settled_time,
        }
    )


def _make_poller(monkeypatch: pytest.MonkeyPatch, tmp_path) -> KalshiSettlementPoller:
    monkeypatch.setenv("MERID_SETTLEMENT_GRADED_PATH", str(tmp_path / "graded.jsonl"))
    poller = KalshiSettlementPoller(MagicMock(), PollerConfig())
    poller._sweep_orphaned_decision_outcomes = AsyncMock()
    poller._publish_settlements_to_bus = AsyncMock(return_value=True)
    return poller


class TestDedupePrecedesHydration:
    async def test_hydrate_runs_only_for_new_gradable_rows(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        poller = _make_poller(monkeypatch, tmp_path)

        already = _settled("KXBTC15M-A", "2026-09-27T19:00:00Z")
        fresh = _settled("KXSOL15M-B", "2026-09-27T19:15:00Z")
        voided = _cancelled("KXETH15M-C", "2026-09-27T19:30:00Z")

        poller._graded_settlements.add(already.dedupe_key)

        hydrate_calls: list[str] = []
        original_hydrate = poller._hydrate_pnl_from_ledger

        def _spy(settlement: KalshiSettlement) -> KalshiSettlement:
            hydrate_calls.append(settlement.market_id)
            return settlement

        monkeypatch.setattr(poller, "_hydrate_pnl_from_ledger", _spy)
        poller._fetch_all_settlements = AsyncMock(
            return_value=[already, fresh, voided]
        )

        await poller._poll_once()

        assert hydrate_calls == ["KXSOL15M-B"]
        assert poller._settlement_count == 1

    async def test_new_graded_key_reaches_durable_watermark(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        poller = _make_poller(monkeypatch, tmp_path)
        fresh = _settled("KXDOGE15M-D", "2026-09-27T19:45:00Z")
        poller._fetch_all_settlements = AsyncMock(return_value=[fresh])

        await poller._poll_once()

        path = tmp_path / "graded.jsonl"
        assert path.exists()
        lines = path.read_text().splitlines()
        keys = [line.split("|", 1)[0] for line in lines]
        assert fresh.dedupe_key in keys


class TestDurableWatermarkReload:
    def test_graded_keys_survive_restart(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        path = tmp_path / "graded.jsonl"
        monkeypatch.setenv("MERID_SETTLEMENT_GRADED_PATH", str(path))

        poller1 = KalshiSettlementPoller(MagicMock(), PollerConfig())
        poller1._graded_keys_dirty.append("kalshi:KXBTC15M-Z:2026-09-27T00:00:00Z")
        poller1._graded_keys_dirty.append("kalshi:KXSOL15M-Z:2026-09-27T00:15:00Z")
        poller1._flush_graded_keys()

        poller2 = KalshiSettlementPoller(MagicMock(), PollerConfig())
        assert "kalshi:KXBTC15M-Z:2026-09-27T00:00:00Z" in poller2._graded_settlements
        assert "kalshi:KXSOL15M-Z:2026-09-27T00:15:00Z" in poller2._graded_settlements

    def test_stale_keys_pruned_on_load(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        path = tmp_path / "graded.jsonl"
        monkeypatch.setenv("MERID_SETTLEMENT_GRADED_PATH", str(path))
        path.write_text(
            "kalshi:OLD:2020-01-01T00:00:00Z|1577836800.000\n"
        )
        poller = KalshiSettlementPoller(MagicMock(), PollerConfig())
        assert "kalshi:OLD:2020-01-01T00:00:00Z" not in poller._graded_settlements


class TestSweepOffloadsSyncWork:
    async def test_pending_query_runs_off_event_loop(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        monkeypatch.setenv("MERID_SETTLEMENT_SWEEP_ENABLED", "1")
        poller = _make_poller(monkeypatch, tmp_path)
        # _poll_once stubs the sweep; here we test the real method
        del poller._sweep_orphaned_decision_outcomes

        seen_threads: list[threading.Thread] = []
        ledger = MagicMock()

        def _pending(**kwargs):
            seen_threads.append(threading.current_thread())
            return []

        ledger.pending_unsettled_tickers = _pending

        monkeypatch.setattr(
            "merid.execution.decision_audit_ledger.get_decision_audit_ledger",
            lambda: ledger,
        )

        await poller._sweep_orphaned_decision_outcomes()

        assert len(seen_threads) == 1
        assert seen_threads[0] is not threading.main_thread()


async def test_batch_audit_joins_every_settlement(monkeypatch, tmp_path):
    monkeypatch.setenv("MERID_SETTLEMENT_GRADED_PATH", str(tmp_path / "graded.jsonl"))
    poller = KalshiSettlementPoller(MagicMock(), PollerConfig())
    audit = MagicMock()
    bus = MagicMock()
    bus.publish = AsyncMock()
    monkeypatch.setattr(
        "merid.execution.decision_audit_ledger.get_decision_audit_ledger",
        lambda: audit,
    )
    monkeypatch.setattr(settlement_module, "get_event_bus", lambda: bus)
    batch = [
        _settled("KXBTC15M-A", "2026-09-27T19:00:00Z"),
        _settled("KXETH15M-B", "2026-09-27T19:15:00Z", result="no"),
        _settled("KXSOL15M-C", "2026-09-27T19:30:00Z"),
    ]

    assert await poller._publish_settlements_to_bus(batch)
    assert [call.kwargs["ticker"] for call in audit.record_settlement.call_args_list] == [
        s.market_id for s in batch
    ]
    assert bus.publish.await_count == 3


def test_normalization_preserves_fractional_settlement_evidence(monkeypatch, tmp_path):
    poller = _make_poller(monkeypatch, tmp_path)
    raw = {
        "ticker": "KXBTC15M-26NOV010000-00",
        "market_result": "yes",
        "value": 100,
        "settled_time": "2026-11-01T04:00:00Z",
        "yes_count_fp": "0.25",
        "no_count_fp": "0.00",
        "revenue": 25,
    }
    original = KalshiSettlement.from_api(raw)
    normalized = poller._normalize_settlement(original)
    assert normalized.ticker != original.ticker
    assert normalized.yes_count_fp == Decimal("0.25")
    assert normalized.no_count_fp == Decimal("0.00")
    assert normalized.raw_payload == raw
    assert normalized.exchange_revenue_cents == original.exchange_revenue_cents


async def test_pagination_follows_cursor_after_partial_page_and_deduplicates(
    monkeypatch, tmp_path,
):
    poller = _make_poller(monkeypatch, tmp_path)
    first = {"ticker": "KXBTC15M-A", "market_result": "yes", "value": 100,
             "settled_time": "2026-11-01T04:00:00Z"}
    second = {"ticker": "KXETH15M-B", "market_result": "no", "value": 0,
              "settled_time": "2026-11-01T04:15:00Z"}
    poller._api_call_with_retry = AsyncMock(side_effect=[
        {"settlements": [first], "cursor": "next"},
        {"settlements": [first, second], "cursor": ""},
    ])
    result = await poller._fetch_all_settlements(
        "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z",
    )
    assert [s.market_id for s in result] == [first["ticker"], second["ticker"]]
    calls = poller._api_call_with_retry.await_args_list
    assert calls[0].kwargs["params"]["min_ts"] == 1793491200
    assert calls[0].kwargs["params"]["max_ts"] == 1793577600
    assert calls[1].kwargs["params"]["cursor"] == "next"


@pytest.mark.parametrize("response", [
    {},
    {"settlements": [], "cursor": "next"},
])
async def test_incomplete_settlement_scan_raises(monkeypatch, tmp_path, response):
    poller = _make_poller(monkeypatch, tmp_path)
    poller.config.max_pages = 1
    poller._api_call_with_retry = AsyncMock(return_value=response)
    with pytest.raises(RuntimeError):
        await poller._fetch_all_settlements(
            "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z",
        )


async def test_settlement_api_timeout_is_not_an_empty_success(monkeypatch, tmp_path):
    poller = _make_poller(monkeypatch, tmp_path)
    poller.config.max_retries = 1
    poller.client = MagicMock()
    poller.client.request = AsyncMock(side_effect=TimeoutError())
    with pytest.raises(TimeoutError):
        await poller._api_call_with_retry("GET", "/portfolio/settlements")


async def test_repeated_cursor_and_later_page_failure_are_not_clean_scans(
    monkeypatch, tmp_path,
):
    poller = _make_poller(monkeypatch, tmp_path)
    poller._api_call_with_retry = AsyncMock(side_effect=[
        {"settlements": [], "cursor": "a"},
        {"settlements": [], "cursor": "b"},
        {"settlements": [], "cursor": "a"},
    ])
    with pytest.raises(RuntimeError, match="Cursor repeated"):
        await poller._fetch_all_settlements(
            "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z",
        )

    poller._api_call_with_retry = AsyncMock(side_effect=[
        {"settlements": [], "cursor": "next"},
        ConnectionError("page failed"),
    ])
    with pytest.raises(ConnectionError, match="page failed"):
        await poller._fetch_all_settlements(
            "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z",
        )


async def test_failed_callback_is_not_watermarked_and_retries(monkeypatch, tmp_path):
    poller = _make_poller(monkeypatch, tmp_path)
    settlement = _settled("KXBTC15M-A", "2026-11-01T04:00:00Z")
    poller._fetch_all_settlements = AsyncMock(return_value=[settlement])
    callback = AsyncMock(side_effect=[RuntimeError("failed"), None])
    poller.add_callback(callback)

    with pytest.raises(RuntimeError, match="Settlement callbacks failed"):
        await poller._poll_once()

    assert settlement.dedupe_key not in poller._graded_settlements
    assert not (tmp_path / "graded.jsonl").exists()
    poller._publish_settlements_to_bus.assert_not_awaited()

    await poller._poll_once()
    assert callback.await_count == 2
    assert settlement.dedupe_key in poller._graded_settlements
    assert settlement.dedupe_key in (tmp_path / "graded.jsonl").read_text()
    poller._publish_settlements_to_bus.assert_awaited_once()


def test_failed_watermark_write_keeps_keys_for_retry(monkeypatch, tmp_path):
    poller = _make_poller(monkeypatch, tmp_path)
    key = "kalshi:KXBTC15M-A:2026-11-01T04:00:00Z"
    poller._graded_keys_dirty.append(key)
    monkeypatch.setattr(poller, "_graded_keys_path", lambda: str(tmp_path))

    poller._flush_graded_keys()
    assert poller._graded_keys_dirty == [key]
    assert poller._last_error.startswith("graded_keys_persist_failed:")

    path = tmp_path / "retry.jsonl"
    monkeypatch.setattr(poller, "_graded_keys_path", lambda: str(path))
    poller._flush_graded_keys()
    assert poller._graded_keys_dirty == []
    assert key in path.read_text()


async def test_proceeds_write_error_propagates_from_grading_bridge(monkeypatch, tmp_path):
    poller = _make_poller(monkeypatch, tmp_path)
    bridge = settlement_module.SettlementToGradingBridge(poller)
    settlement = KalshiSettlement.from_api({
        "ticker": "KXBTC15M-A",
        "market_result": "yes",
        "value": 100,
        "settled_time": "2026-11-01T04:00:00Z",
        "yes_count_fp": "0.25",
    })
    ledger = MagicMock()
    ledger.record_settlement_proceeds_async = AsyncMock(
        side_effect=RuntimeError("disk failure"),
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.fills_ledger.get_fills_ledger", lambda: ledger,
    )
    with pytest.raises(RuntimeError, match="disk failure"):
        await bridge._on_settlement(settlement)
    ledger.record_settlement_proceeds_async.assert_awaited_once()
