"""Tests for Kalshi historical data archiver."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from merid.event_venues.kalshi.archiver import (
    SnapshotArchiver,
    get_archiver,
)
from merid.event_venues.kalshi.backtest import MarketSnapshot


# ── Helpers ────────────────────────────────────────────────────────────

def _make_snap(ticker: str = "BTC-HOURLY", ts: float = None, price: int = 55) -> MarketSnapshot:
    return MarketSnapshot(
        ts=ts or time.time(),
        ticker=ticker,
        yes_book=[[price, 10], [price - 1, 20]],
        no_book=[[100 - price, 10]],
        last_trade_price=price,
        volume=100,
    )


# ── Recording ─────────────────────────────────────────────────────────

class TestRecording:
    def test_record_creates_file(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        snap = _make_snap(ts=1739664000.0)  # 2025-02-16 00:00:00 UTC
        archiver.record(snap)
        archiver.close()

        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1
        assert "BTC-HOURLY" in files[0].name

    def test_record_appends_lines(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        for i in range(5):
            archiver.record(_make_snap(ts=1739664000.0 + i))
        archiver.close()

        files = list(tmp_path.glob("*.jsonl"))
        lines = files[0].read_text().strip().split("\n")
        assert len(lines) == 5

    def test_record_many(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        snaps = [_make_snap(ts=1739664000.0 + i) for i in range(10)]
        count = archiver.record_many(snaps)
        archiver.close()
        assert count == 10

    def test_stats_tracking(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        archiver.record(_make_snap("BTC-HOURLY", ts=1739664000.0))
        archiver.record(_make_snap("BTC-HOURLY", ts=1739664001.0))
        archiver.record(_make_snap("ETH-HOURLY", ts=1739664000.0))
        assert archiver.stats["BTC-HOURLY"] == 2
        assert archiver.stats["ETH-HOURLY"] == 1
        archiver.close()

    def test_separate_files_per_day(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        # Day 1: 2025-02-16
        archiver.record(_make_snap(ts=1739664000.0))
        # Day 2: 2025-02-17 (86400 seconds later)
        archiver.record(_make_snap(ts=1739664000.0 + 86400))
        archiver.close()

        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 2

    def test_separate_files_per_ticker(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        archiver.record(_make_snap("BTC-HOURLY", ts=1739664000.0))
        archiver.record(_make_snap("ETH-HOURLY", ts=1739664000.0))
        archiver.close()

        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 2


# ── Loading ───────────────────────────────────────────────────────────

class TestLoading:
    def test_load_returns_snapshots(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        for i in range(3):
            archiver.record(_make_snap(ts=1739664000.0 + i, price=55 + i))
        archiver.close()

        loaded = archiver.load("BTC-HOURLY", "2025-02-16")
        assert len(loaded) == 3
        assert loaded[0].last_trade_price == 55
        assert loaded[2].last_trade_price == 57

    def test_load_sorted_chronologically(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        # Write out of order
        archiver.record(_make_snap(ts=1739664003.0))
        archiver.record(_make_snap(ts=1739664001.0))
        archiver.record(_make_snap(ts=1739664002.0))
        archiver.close()

        loaded = archiver.load("BTC-HOURLY", "2025-02-16")
        assert loaded[0].ts < loaded[1].ts < loaded[2].ts

    def test_load_missing_date_returns_empty(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        assert archiver.load("BTC-HOURLY", "2099-01-01") == []

    def test_load_preserves_orderbook(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        snap = _make_snap(ts=1739664000.0, price=60)
        archiver.record(snap)
        archiver.close()

        loaded = archiver.load("BTC-HOURLY", "2025-02-16")
        assert loaded[0].yes_book == [[60, 10], [59, 20]]
        assert loaded[0].no_book == [[40, 10]]

    def test_load_range(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        # Two days
        archiver.record(_make_snap(ts=1739664000.0))        # 2025-02-16
        archiver.record(_make_snap(ts=1739664000.0 + 86400)) # 2025-02-17
        archiver.close()

        loaded = archiver.load_range("BTC-HOURLY", "2025-02-16", "2025-02-17")
        assert len(loaded) == 2

    def test_load_range_empty(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        loaded = archiver.load_range("BTC-HOURLY", "2099-01-01", "2099-01-02")
        assert loaded == []


# ── Discovery ─────────────────────────────────────────────────────────

class TestDiscovery:
    def test_available_dates(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        archiver.record(_make_snap(ts=1739664000.0))
        archiver.record(_make_snap(ts=1739664000.0 + 86400))
        archiver.close()

        dates = archiver.available_dates("BTC-HOURLY")
        assert len(dates) == 2
        assert "2025-02-16" in dates

    def test_available_tickers(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        archiver.record(_make_snap("BTC-HOURLY", ts=1739664000.0))
        archiver.record(_make_snap("ETH-HOURLY", ts=1739664000.0))
        archiver.close()

        tickers = archiver.available_tickers()
        assert "BTC-HOURLY" in tickers
        assert "ETH-HOURLY" in tickers

    def test_archive_summary(self, tmp_path):
        archiver = SnapshotArchiver(archive_dir=tmp_path)
        archiver.record(_make_snap(ts=1739664000.0))
        archiver.close()

        summary = archiver.archive_summary()
        assert summary["total_files"] >= 1
        assert "BTC-HOURLY" in summary["tickers"]


# ── Integration with backtest engine ──────────────────────────────────

class TestBacktestIntegration:
    def test_archived_snapshots_work_with_backtest(self, tmp_path):
        """Verify archived snapshots can be loaded and fed to backtest()."""
        from merid.event_venues.kalshi.backtest import backtest, BacktestState, TradeDecision

        archiver = SnapshotArchiver(archive_dir=tmp_path)
        for i in range(10):
            archiver.record(_make_snap(ts=1739664000.0 + i * 60, price=50 + i % 5))
        archiver.close()

        loaded = archiver.load("BTC-HOURLY", "2025-02-16")
        assert len(loaded) == 10

        # Simple strategy: buy when price < 52
        def strategy(snap, state):
            if snap.last_trade_price and snap.last_trade_price < 52:
                return [TradeDecision(
                    ticker=snap.ticker, side="yes", action="buy",
                    price_cents=snap.last_trade_price, count=1,
                )]
            return []

        result = backtest(loaded, initial_cash_cents=100_000, strategy_fn=strategy)
        assert result.total_trades > 0
        assert len(result.pnl_history) == 10


# ── Singleton ─────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_archiver_returns_same_instance(self):
        import merid.event_venues.kalshi.archiver as mod
        old = mod._archiver
        try:
            mod._archiver = None
            a1 = get_archiver()
            a2 = get_archiver()
            assert a1 is a2
        finally:
            mod._archiver = old
