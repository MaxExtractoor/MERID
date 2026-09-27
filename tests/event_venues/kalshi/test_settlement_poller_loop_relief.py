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
from unittest.mock import AsyncMock, MagicMock

import pytest

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
