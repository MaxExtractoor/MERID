"""Kalshi Historical Data Archiver — Stream and store snapshots for backtesting.

Archives orderbook snapshots and trades for BTC/ETH hourlies (and any other
tickers) to JSONL files, one file per day per ticker.  Archived data can be
replayed through the existing ``backtest()`` engine.

Storage layout::

    data/kalshi_archive/
        BTC-HOURLY-2026-02-15.jsonl
        ETH-HOURLY-2026-02-15.jsonl
        ...

Each line is a JSON-serialised ``MarketSnapshot`` dict.

Usage::

    archiver = SnapshotArchiver()
    archiver.record(snapshot)                # single snapshot
    snapshots = archiver.load("BTC-HOURLY", "2026-02-15")  # replay
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from merid.event_venues.kalshi.backtest import MarketSnapshot
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.archiver")

_ARCHIVE_DIR = Path("data/kalshi_archive")


class SnapshotArchiver:
    """Append-only archiver that writes MarketSnapshot objects to JSONL files.

    Thread-safe for single-writer usage (one archiver per process).
    Files are flushed after every write for crash safety.
    """

    def __init__(self, archive_dir: Optional[Path] = None) -> None:
        self._dir = archive_dir or _ARCHIVE_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._handles: Dict[str, Any] = {}
        self._stats: Dict[str, int] = {}

    # ── Recording ──────────────────────────────────────────────────

    def record(self, snapshot: MarketSnapshot) -> None:
        """Append a snapshot to the day's JSONL file."""
        dt = datetime.fromtimestamp(snapshot.ts, tz=timezone.utc)
        date_str = dt.strftime("%Y-%m-%d")
        key = f"{snapshot.ticker}-{date_str}"

        fh = self._handles.get(key)
        if fh is None or fh.closed:
            path = self._dir / f"{key}.jsonl"
            fh = open(path, "a", encoding="utf-8")
            self._handles[key] = fh

        line = json.dumps({
            "ts": snapshot.ts,
            "ticker": snapshot.ticker,
            "yes_book": snapshot.yes_book,
            "no_book": snapshot.no_book,
            "last_trade_price": snapshot.last_trade_price,
            "volume": snapshot.volume,
        })
        fh.write(line + "\n")
        fh.flush()

        self._stats[snapshot.ticker] = self._stats.get(snapshot.ticker, 0) + 1

    def record_many(self, snapshots: List[MarketSnapshot]) -> int:
        """Record a batch of snapshots. Returns count written."""
        for snap in snapshots:
            self.record(snap)
        return len(snapshots)

    # ── Loading / replay ──────────────────────────────────────────

    def load(self, ticker: str, date_str: str) -> List[MarketSnapshot]:
        """Load all snapshots for a ticker on a given date.

        Args:
            ticker: Market ticker (e.g. "BTC-HOURLY")
            date_str: Date string "YYYY-MM-DD"

        Returns:
            Chronologically ordered list of MarketSnapshot objects.
        """
        path = self._dir / f"{ticker}-{date_str}.jsonl"
        if not path.exists():
            return []

        snapshots: List[MarketSnapshot] = []
        for line in path.read_text(encoding="utf-8").strip().split("\n"):
            if not line:
                continue
            try:
                d = json.loads(line)
                snapshots.append(MarketSnapshot(
                    ts=d["ts"],
                    ticker=d["ticker"],
                    yes_book=d.get("yes_book", []),
                    no_book=d.get("no_book", []),
                    last_trade_price=d.get("last_trade_price"),
                    volume=d.get("volume", 0),
                ))
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Skipping corrupt line in {path}: {e}")

        return sorted(snapshots, key=lambda s: s.ts)

    def load_range(
        self, ticker: str, start_date: str, end_date: str
    ) -> List[MarketSnapshot]:
        """Load snapshots across a date range (inclusive).

        Args:
            ticker: Market ticker
            start_date: "YYYY-MM-DD"
            end_date: "YYYY-MM-DD"

        Returns:
            Chronologically ordered snapshots across all days.
        """
        from datetime import timedelta

        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        all_snaps: List[MarketSnapshot] = []
        current = start
        while current <= end:
            day_str = current.strftime("%Y-%m-%d")
            all_snaps.extend(self.load(ticker, day_str))
            current += timedelta(days=1)

        return sorted(all_snaps, key=lambda s: s.ts)

    def available_dates(self, ticker: str) -> List[str]:
        """List available archive dates for a ticker."""
        prefix = f"{ticker}-"
        dates = []
        for f in sorted(self._dir.glob(f"{prefix}*.jsonl")):
            # Extract date from filename: TICKER-YYYY-MM-DD.jsonl
            name = f.stem  # TICKER-YYYY-MM-DD
            date_part = name[len(prefix):]
            dates.append(date_part)
        return dates

    def available_tickers(self) -> List[str]:
        """List all tickers that have archived data."""
        tickers = set()
        for f in self._dir.glob("*.jsonl"):
            # Parse ticker from TICKER-YYYY-MM-DD.jsonl
            parts = f.stem.rsplit("-", 3)
            if len(parts) >= 4:
                # e.g. BTC-HOURLY-2026-02-15 → ticker = BTC-HOURLY
                ticker = "-".join(parts[:-3])
                tickers.add(ticker)
        return sorted(tickers)

    # ── Stats ─────────────────────────────────────────────────────

    @property
    def stats(self) -> Dict[str, int]:
        """Snapshot counts per ticker since archiver creation."""
        return dict(self._stats)

    def archive_summary(self) -> Dict[str, Any]:
        """Summary of all archived data."""
        tickers = self.available_tickers()
        total_files = len(list(self._dir.glob("*.jsonl")))
        total_size_bytes = sum(f.stat().st_size for f in self._dir.glob("*.jsonl"))

        by_ticker: Dict[str, Dict[str, Any]] = {}
        for ticker in tickers:
            dates = self.available_dates(ticker)
            by_ticker[ticker] = {
                "days": len(dates),
                "first_date": dates[0] if dates else None,
                "last_date": dates[-1] if dates else None,
            }

        return {
            "archive_dir": str(self._dir),
            "total_files": total_files,
            "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
            "tickers": by_ticker,
            "session_stats": self.stats,
        }

    # ── Cleanup ───────────────────────────────────────────────────

    def close(self) -> None:
        """Close all open file handles."""
        for fh in self._handles.values():
            if not fh.closed:
                fh.close()
        self._handles.clear()

    def __del__(self) -> None:
        self.close()


# ── Singleton ────────────────────────────────────────────────────────────

_archiver: Optional[SnapshotArchiver] = None


def get_archiver(archive_dir: Optional[Path] = None) -> SnapshotArchiver:
    """Get or create the singleton SnapshotArchiver."""
    global _archiver
    if _archiver is None:
        _archiver = SnapshotArchiver(archive_dir)
    return _archiver
