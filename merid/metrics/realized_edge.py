"""Realized Edge Store — Track estimated vs actual edge per trade.

For each trade placed on Kalshi, captures the edge estimate at entry and
compares it to the realized outcome after settlement.  This answers the
question: "Are our edge estimates actually profitable after fees?"

Metrics tracked per (forecaster, bucket):
  - sum_est_edge, sum_realized_edge, count
  - ratio = realized / estimated  (>1.0 = under-estimating edge, <1.0 = leaking)
  - mean_slippage = est_edge - realized_edge  (positive = we lose edge)

Usage::

    store = get_realized_edge_store()
    store.record_trade_entry(
        trade_id="ord_123", forecaster_id="edge_model_v1", bucket="crypto",
        market_id="KXBTC-26FEB-T95000", side="yes", price_cents=55,
        p_model=0.62, p_implied=0.55, contracts=10, fee_cents=31,
    )
    # ... on settlement ...
    store.resolve_trade("ord_123", outcome=1, settlement_price_cents=100)
    stats = store.get_edge_stats("edge_model_v1", "crypto")
"""

from __future__ import annotations

import threading
import math
import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.metrics.realized_edge")

_PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_DEFAULT_DB_PATH = os.path.join(_PROJECT_ROOT, "data", "realized_edge.db")


@dataclass
class TradeEdgeRecord:
    """Edge snapshot captured at trade entry time."""
    trade_id: str
    forecaster_id: str
    bucket: str
    market_id: str
    side: str               # "yes" or "no"
    price_cents: int        # price paid per contract
    p_model: float          # model probability (YES)
    p_implied: float        # implied probability from price
    est_edge: float         # p_model - p_implied (sign-adjusted for side)
    contracts: int
    fee_cents: int          # total expected fee
    timestamp: float
    edge_type: str = "probability"  # "probability" or "velocity"
    resolved: bool = False
    outcome: Optional[int] = None
    realized_pnl_cents: Optional[int] = None
    realized_edge: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trade_id": self.trade_id,
            "forecaster_id": self.forecaster_id,
            "bucket": self.bucket,
            "market_id": self.market_id,
            "side": self.side,
            "price_cents": self.price_cents,
            "p_model": round(self.p_model, 6),
            "p_implied": round(self.p_implied, 6),
            "est_edge": round(self.est_edge, 6),
            "contracts": self.contracts,
            "fee_cents": self.fee_cents,
            "timestamp": self.timestamp,
            "resolved": self.resolved,
            "outcome": self.outcome,
            "realized_pnl_cents": self.realized_pnl_cents,
            "realized_edge": round(self.realized_edge, 6) if self.realized_edge is not None else None,
        }


@dataclass
class EdgeStats:
    """Aggregated realized-edge statistics for one (forecaster, bucket) pair."""
    forecaster_id: str
    bucket: str
    trade_count: int = 0
    resolved_count: int = 0
    sum_est_edge: float = 0.0
    sum_realized_edge: float = 0.0
    sum_pnl_cents: int = 0
    sum_fee_cents: int = 0
    winning_trades: int = 0
    losing_trades: int = 0

    @property
    def mean_est_edge(self) -> float:
        return self.sum_est_edge / self.resolved_count if self.resolved_count > 0 else 0.0

    @property
    def mean_realized_edge(self) -> float:
        return self.sum_realized_edge / self.resolved_count if self.resolved_count > 0 else 0.0

    @property
    def edge_ratio(self) -> float:
        """realized / estimated.  >1 = under-estimating, <1 = leaking edge."""
        if abs(self.sum_est_edge) < 1e-9:
            return 0.0
        return self.sum_realized_edge / self.sum_est_edge

    @property
    def mean_slippage(self) -> float:
        """est_edge - realized_edge.  Positive = losing edge vs estimate."""
        return self.mean_est_edge - self.mean_realized_edge

    @property
    def win_rate(self) -> float:
        total = self.winning_trades + self.losing_trades
        return self.winning_trades / total if total > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "forecaster_id": self.forecaster_id,
            "bucket": self.bucket,
            "trade_count": self.trade_count,
            "resolved_count": self.resolved_count,
            "mean_est_edge": round(self.mean_est_edge, 6),
            "mean_realized_edge": round(self.mean_realized_edge, 6),
            "edge_ratio": round(self.edge_ratio, 4),
            "mean_slippage": round(self.mean_slippage, 6),
            "sum_pnl_cents": self.sum_pnl_cents,
            "sum_fee_cents": self.sum_fee_cents,
            "win_rate": round(self.win_rate, 4),
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
        }


class RealizedEdgeStore:
    """SQLite-backed realized edge tracking per trade.

    Thread-safe via SQLite locking.  Supports :memory: for tests.
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or os.getenv("MERID_EDGE_DB", _DEFAULT_DB_PATH)
        in_memory = self._db_path == ":memory:"
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=True if in_memory else False,
            timeout=10,  # Connection timeout
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=5000")  # Wait up to 5s if DB is locked
        self._conn.execute("PRAGMA journal_mode=WAL")  # Enable WAL for better concurrency
        self._init_tables()

    def _init_tables(self) -> None:
        with self._conn:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS trade_edges (
                    trade_id       TEXT PRIMARY KEY,
                    forecaster_id  TEXT NOT NULL,
                    bucket         TEXT NOT NULL,
                    market_id      TEXT NOT NULL,
                    side           TEXT NOT NULL,
                    action         TEXT NOT NULL,
                    price_cents    INTEGER NOT NULL,
                    p_model        REAL NOT NULL,
                    p_implied      REAL NOT NULL,
                    est_edge       REAL NOT NULL,
                    contracts      INTEGER NOT NULL,
                    fee_cents      INTEGER NOT NULL,
                    timestamp      REAL NOT NULL,
                    edge_type      TEXT DEFAULT 'probability',
                    resolved       INTEGER DEFAULT 0,
                    outcome        INTEGER,
                    realized_pnl_cents INTEGER,
                    realized_edge  REAL
                );

                CREATE INDEX IF NOT EXISTS idx_trade_edges_market
                    ON trade_edges(market_id);
                CREATE INDEX IF NOT EXISTS idx_trade_edges_unresolved
                    ON trade_edges(resolved) WHERE resolved = 0;

                CREATE TABLE IF NOT EXISTS edge_stats (
                    forecaster_id   TEXT NOT NULL,
                    bucket          TEXT NOT NULL,
                    trade_count     INTEGER DEFAULT 0,
                    resolved_count  INTEGER DEFAULT 0,
                    sum_est_edge    REAL DEFAULT 0.0,
                    sum_realized_edge REAL DEFAULT 0.0,
                    sum_pnl_cents   INTEGER DEFAULT 0,
                    sum_fee_cents   INTEGER DEFAULT 0,
                    winning_trades  INTEGER DEFAULT 0,
                    losing_trades  INTEGER DEFAULT 0,
                    PRIMARY KEY (forecaster_id, bucket)
                );
            """)

    # ── Record trade entry ───────────────────────────────────────────────

    def record_trade_entry(
        self,
        trade_id: str,
        forecaster_id: str,
        bucket: str,
        market_id: str,
        side: str,
        action: str,
        price_cents: int,
        p_model: float,
        p_implied: float,
        contracts: int,
        fee_cents: int,
        timestamp: Optional[float] = None,
        edge_type: str = "probability",
    ) -> None:
        """Log edge estimates at the time a trade is placed.

        Args:
            trade_id: Unique order/trade identifier.
            forecaster_id: Which model produced the signal.
            bucket: Category bucket (crypto, macro, etc.).
            market_id: Kalshi market ticker.
            side: "yes" or "no".
            action: "buy" or "sell".
            price_cents: Price paid per contract (0-99).
            p_model: Model's YES probability.
            p_implied: Implied YES probability from price.
            contracts: Number of contracts.
            fee_cents: Total expected fee in cents.
            timestamp: Unix timestamp (defaults to now).
            edge_type: Type of edge - "probability" or "velocity".
        """
        ts = timestamp or time.time()

        # Compute estimated edge (sign-adjusted for side)
        if side.lower() == "yes":
            est_edge = p_model - p_implied
        else:
            est_edge = (1.0 - p_model) - (1.0 - p_implied)

        with self._conn:
            # INSERT OR IGNORE prevents a duplicate trade_id from silently
            # overwriting an existing edge record (D05 fix).  The trade_count
            # increment below only fires when a genuinely new row was inserted.
            cursor = self._conn.execute(
                """INSERT OR IGNORE INTO trade_edges
                   (trade_id, forecaster_id, bucket, market_id, side, action,
                    price_cents, p_model, p_implied, est_edge, contracts,
                    fee_cents, timestamp, edge_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (trade_id, forecaster_id, bucket, market_id, side.lower(), action.lower(),
                 price_cents, p_model, p_implied, est_edge, contracts,
                 fee_cents, ts, edge_type),
            )
            # Only increment trade_count for genuinely new rows
            if cursor.rowcount > 0:
                self._conn.execute(
                    """INSERT INTO edge_stats (forecaster_id, bucket, trade_count)
                       VALUES (?, ?, 1)
                       ON CONFLICT(forecaster_id, bucket)
                       DO UPDATE SET trade_count = trade_count + 1""",
                    (forecaster_id, bucket),
                )
            else:
                logger.debug(
                    "record_trade_entry: duplicate trade_id '%s' ignored (already recorded)",
                    trade_id,
                )

    # ── Resolve trades ───────────────────────────────────────────────────

    def resolve_trade(
        self,
        trade_id: str,
        outcome: int,
        settlement_price_cents: Optional[int] = None,
    ) -> bool:
        """Resolve a trade after market settlement.

        For Kalshi binary contracts:
        - YES buyer wins: payout = 100 - price, loss = price (outcome=1)
        - YES buyer loses: payout = 0, loss = price (outcome=0)
        - NO buyer wins: payout = price, loss = 100-price (outcome=0)
        - NO buyer loses: payout = 0, loss = 100-price (outcome=1)

        Args:
            trade_id: The trade to resolve.
            outcome: 1 if YES won, 0 if NO won.
            settlement_price_cents: Override settlement price (default: 100 or 0).

        Returns:
            True if trade was found and resolved, False if not found or already resolved.
        """
        if outcome not in (0, 1):
            raise ValueError(f"outcome must be 0 or 1, got {outcome}")

        row = self._conn.execute(
            "SELECT * FROM trade_edges WHERE trade_id = ?",
            (trade_id,),
        ).fetchone()

        if row is None or row["resolved"]:
            return False

        side = row["side"]
        action = row["action"]
        price = row["price_cents"]
        contracts = row["contracts"]
        fee = row["fee_cents"]

        # Compute realized PnL in cents
        # For BUY trades: pay price upfront, receive payout at settlement
        # For SELL trades: receive price upfront, pay payout at settlement
        if action == "buy":
            if side == "yes":
                if outcome == 1:
                    # YES buyer wins: payout = (100 - price) * contracts - fees
                    pnl = (100 - price) * contracts - fee
                else:
                    # YES buyer loses: lose stake
                    pnl = -price * contracts
            else:  # side == "no"
                if outcome == 0:
                    # NO buyer wins: payout = price * contracts - fees
                    pnl = price * contracts - fee
                else:
                    # NO buyer loses: lose stake
                    pnl = -(100 - price) * contracts
        else:  # action == "sell"
            if side == "yes":
                if outcome == 1:
                    # YES seller loses: received price, must pay 100
                    pnl = price * contracts - (100 * contracts) - fee
                else:
                    # YES seller wins: received price, pay 0
                    pnl = price * contracts - fee
            else:  # side == "no"
                if outcome == 0:
                    # NO seller loses: received price, must pay 0
                    pnl = price * contracts - fee
                else:
                    # NO seller wins: received price, pay 100
                    pnl = price * contracts - (100 * contracts) - fee

        # Realized edge as fraction of stake
        stake = price * contracts if side == "yes" else (100 - price) * contracts
        realized_edge = pnl / stake if stake > 0 else 0.0

        with self._conn:
            self._conn.execute(
                """UPDATE trade_edges
                   SET resolved = 1, outcome = ?, realized_pnl_cents = ?,
                       realized_edge = ?
                   WHERE trade_id = ?""",
                (outcome, pnl, realized_edge, trade_id),
            )

            # Update aggregate stats
            est_edge = row["est_edge"]
            is_win = pnl > 0

            self._conn.execute(
                """UPDATE edge_stats
                   SET resolved_count = resolved_count + 1,
                       sum_est_edge = sum_est_edge + ?,
                       sum_realized_edge = sum_realized_edge + ?,
                       sum_pnl_cents = sum_pnl_cents + ?,
                       sum_fee_cents = sum_fee_cents + ?,
                       winning_trades = winning_trades + ?,
                       losing_trades = losing_trades + ?
                   WHERE forecaster_id = ? AND bucket = ?""",
                (est_edge, realized_edge, pnl, fee,
                 1 if is_win else 0, 0 if is_win else 1,
                 row["forecaster_id"], row["bucket"]),
            )

        logger.info(
            f"Resolved trade {trade_id}: market={row['market_id']} "
            f"side={side} outcome={'YES' if outcome else 'NO'} "
            f"pnl={pnl}c realized_edge={realized_edge:.4f}"
        )
        return True

    def resolve_market(self, market_id: str, outcome: int) -> int:
        """Resolve all unresolved trades for a market.

        Returns number of trades resolved.
        """
        rows = self._conn.execute(
            "SELECT trade_id FROM trade_edges WHERE market_id = ? AND resolved = 0",
            (market_id,),
        ).fetchall()

        resolved = 0
        for row in rows:
            if self.resolve_trade(row["trade_id"], outcome):
                resolved += 1
        return resolved

    # ── Query methods ────────────────────────────────────────────────────

    def get_edge_stats(self, forecaster_id: str, bucket: str) -> EdgeStats:
        """Get aggregated edge stats for a (forecaster, bucket) pair."""
        row = self._conn.execute(
            "SELECT * FROM edge_stats WHERE forecaster_id = ? AND bucket = ?",
            (forecaster_id, bucket),
        ).fetchone()
        if row is None:
            return EdgeStats(forecaster_id=forecaster_id, bucket=bucket)
        return EdgeStats(
            forecaster_id=row["forecaster_id"],
            bucket=row["bucket"],
            trade_count=row["trade_count"],
            resolved_count=row["resolved_count"],
            sum_est_edge=row["sum_est_edge"],
            sum_realized_edge=row["sum_realized_edge"],
            sum_pnl_cents=row["sum_pnl_cents"],
            sum_fee_cents=row["sum_fee_cents"],
            winning_trades=row["winning_trades"],
            losing_trades=row["losing_trades"],
        )

    def get_all_edge_stats(self) -> List[EdgeStats]:
        """Get stats for all (forecaster, bucket) pairs."""
        rows = self._conn.execute("SELECT * FROM edge_stats").fetchall()
        return [
            EdgeStats(
                forecaster_id=r["forecaster_id"],
                bucket=r["bucket"],
                trade_count=r["trade_count"],
                resolved_count=r["resolved_count"],
                sum_est_edge=r["sum_est_edge"],
                sum_realized_edge=r["sum_realized_edge"],
                sum_pnl_cents=r["sum_pnl_cents"],
                sum_fee_cents=r["sum_fee_cents"],
                winning_trades=r["winning_trades"],
                losing_trades=r["losing_trades"],
            )
            for r in rows
        ]

    def get_trade(self, trade_id: str) -> Optional[TradeEdgeRecord]:
        """Get a single trade edge record."""
        row = self._conn.execute(
            "SELECT * FROM trade_edges WHERE trade_id = ?", (trade_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_trades_for_market(self, market_id: str) -> List[TradeEdgeRecord]:
        """Get all trade edge records for a market."""
        rows = self._conn.execute(
            "SELECT * FROM trade_edges WHERE market_id = ? ORDER BY timestamp",
            (market_id,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def get_unresolved_markets(self) -> List[str]:
        """Get market IDs with unresolved trades."""
        rows = self._conn.execute(
            "SELECT DISTINCT market_id FROM trade_edges WHERE resolved = 0"
        ).fetchall()
        return [r["market_id"] for r in rows]

    def _row_to_record(self, r: sqlite3.Row) -> TradeEdgeRecord:
        return TradeEdgeRecord(
            trade_id=r["trade_id"],
            forecaster_id=r["forecaster_id"],
            bucket=r["bucket"],
            market_id=r["market_id"],
            side=r["side"],
            price_cents=r["price_cents"],
            p_model=r["p_model"],
            p_implied=r["p_implied"],
            est_edge=r["est_edge"],
            contracts=r["contracts"],
            fee_cents=r["fee_cents"],
            timestamp=r["timestamp"],
            resolved=bool(r["resolved"]),
            outcome=r["outcome"],
            realized_pnl_cents=r["realized_pnl_cents"],
            realized_edge=r["realized_edge"],
        )

    def reset(self) -> None:
        """Clear all edge data."""
        with self._conn:
            self._conn.execute("DELETE FROM trade_edges")
            self._conn.execute("DELETE FROM edge_stats")
        logger.info("Realized edge store reset")


# ── Singleton ────────────────────────────────────────────────────────────

_store: Optional[RealizedEdgeStore] = None
_store_lock = threading.Lock()


def get_realized_edge_store(db_path: Optional[str] = None) -> RealizedEdgeStore:
    """Get or create the singleton RealizedEdgeStore."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = RealizedEdgeStore(db_path=db_path)
    return _store
