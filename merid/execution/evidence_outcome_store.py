"""Incremental evidence-outcome store for the live-entry evidence refresh.

The rolling ``live_entry_evidence.json`` artifact used to rescan the whole
configured window (4-48h) of the multi-GB ``decision_audit`` DB on every
refresh.  On the production spindle that scan routinely exceeded the
query deadline (``query: interrupted``), so the artifact aged toward the
staleness cliff and evidence cells starved — the evidence layer was
blocking admissions on *old, sparse* data it could no longer refresh.

Settled outcomes are append-only events, so the correct pattern is
incremental consumption with a watermark (the same approach as Doris
table-streams / Redshift incremental statistics): extract each settled
market's evidence rows ONCE into this small companion store, then rebuild
the artifact by reading only the window from the store.  Backfill walks
newest-first so the freshest 15-minute-market evidence lands immediately
while older chunks trickle in on subsequent refreshes.
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_STORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence_outcome_rows (
    row_key TEXT PRIMARY KEY,
    src TEXT NOT NULL,
    asset TEXT,
    side TEXT,
    ticker TEXT,
    decision_id TEXT,
    mkey TEXT,
    seconds_to_close REAL,
    entry_cents REAL,
    fill_px_cents REAL,
    decision_px_cents REAL,
    exp_slip_cents REAL,
    lane TEXT,
    calibrated_probability REAL,
    settled_yes INTEGER,
    settled_at REAL,
    decision_ts REAL,
    exclusion_reason TEXT,
    passed_edge_gate INTEGER,
    cf_status TEXT,
    net_ev REAL,
    esrc TEXT,
    q_assumed REAL,
    cf_yes REAL,
    cf_no REAL
);
CREATE INDEX IF NOT EXISTS idx_eor_settled_at
    ON evidence_outcome_rows(settled_at);
CREATE TABLE IF NOT EXISTS evidence_extract_state (
    k TEXT PRIMARY KEY,
    v TEXT
);
"""

# Extraction SQL mirrors the three refresh queries verbatim, plus an upper
# bound ``o.settled_at < ?`` so each call covers a bounded chunk.  Params:
# (lo, hi, lo - 3600) for settled_at range + decision_ts pad.
_FILL_SQL = """
SELECT d.asset AS asset,
       d.selected_side AS side,
       d.ticker AS ticker,
       d.decision_id AS decision_id,
       d.seconds_to_close AS seconds_to_close,
       COALESCE(o.actual_fill_price_cents,
                se.executable_entry_price_cents) AS entry_cents,
       o.actual_fill_price_cents AS fill_px_cents,
       se.executable_entry_price_cents AS decision_px_cents,
       se.expected_entry_slippage_cents AS exp_slip_cents,
       COALESCE(se.decision_lane, d.admission_lane) AS lane,
       se.calibrated_probability AS calibrated_probability,
       o.settled_yes AS settled_yes,
       o.settled_at AS settled_at,
       'fill' AS src,
       d.decision_ts AS decision_ts,
       d.ticker || '|' || d.selected_side AS mkey
FROM strategy_decision_outcomes o INDEXED BY idx_outcomes_settled_at
JOIN strategy_decisions d ON d.decision_id = o.decision_id
LEFT JOIN strategy_decision_side_ev se
  ON se.decision_id = d.decision_id
 AND se.side = d.selected_side
WHERE o.outcome_status = 'SETTLED'
  AND o.settled_at >= ?
  AND o.settled_at <= ?
  AND d.decision_ts >= ?
  AND d.decision = 'ENTER'
  AND d.selected_side IN ('yes', 'no')
  AND d.is_eligible_for_research = 1
"""

_VETO_SQL = """
SELECT d.asset AS asset,
       se.side AS side,
       d.ticker AS ticker,
       d.decision_id AS decision_id,
       d.seconds_to_close AS seconds_to_close,
       se.executable_entry_price_cents AS entry_cents,
       NULL AS fill_px_cents,
       NULL AS decision_px_cents,
       NULL AS exp_slip_cents,
       NULL AS lane,
       se.calibrated_probability AS calibrated_probability,
       o.settled_yes AS settled_yes,
       o.settled_at AS settled_at,
       'veto' AS src,
       d.decision_ts AS decision_ts,
       se.exclusion_reason AS exclusion_reason,
       se.passed_edge_gate AS passed_edge_gate,
       se.counterfactual_execution_status AS cf_status,
       d.ticker || '|' || se.side AS mkey
FROM strategy_decision_outcomes o INDEXED BY idx_outcomes_settled_at
JOIN strategy_decisions d ON d.decision_id = o.decision_id
JOIN strategy_decision_side_ev se
  ON se.decision_id = d.decision_id
WHERE o.outcome_status = 'SETTLED'
  AND o.settled_at >= ?
  AND o.settled_at <= ?
  AND d.decision_ts >= ?
  AND d.decision = 'NO_TRADE'
  AND se.side IN ('yes', 'no')
  AND se.executable_entry_price_cents IS NOT NULL
  AND se.executable_entry_price_cents BETWEEN 1 AND 100
  AND d.is_eligible_for_research = 1
"""

_EBIAS_SQL = """
SELECT d.asset AS asset,
       se.side AS side,
       d.ticker AS ticker,
       d.decision_id AS decision_id,
       se.expected_net_ev_cents AS net_ev,
       se.counterfactual_entry_source AS esrc,
       se.counterfactual_execution_status AS cf_status,
       se.counterfactual_assumed_filled_contracts AS q_assumed,
       o.counterfactual_yes_pnl_cents AS cf_yes,
       o.counterfactual_no_pnl_cents AS cf_no,
       o.settled_at AS settled_at,
       'ebias' AS src,
       d.decision_ts AS decision_ts,
       d.ticker || '|' || se.side AS mkey
FROM strategy_decision_outcomes o INDEXED BY idx_outcomes_settled_at
JOIN strategy_decisions d ON d.decision_id = o.decision_id
JOIN strategy_decision_side_ev se
  ON se.decision_id = d.decision_id
WHERE o.outcome_status = 'SETTLED'
  AND o.settled_at >= ?
  AND o.settled_at <= ?
  AND d.decision_ts >= ?
  AND se.side IN ('yes', 'no')
  AND se.expected_net_ev_cents IS NOT NULL
  AND (se.counterfactual_execution_status IS NULL
       OR se.counterfactual_execution_status IN
          ('FULLY_EXECUTABLE', 'PARTIALLY_EXECUTABLE'))
  AND d.is_eligible_for_research = 1
"""

# Extraction queries (see module docstring for the watermark design).
_QUERIES = (_FILL_SQL, _VETO_SQL, _EBIAS_SQL)

_ROW_COLS = (
    "src", "asset", "side", "ticker", "decision_id", "mkey",
    "seconds_to_close", "entry_cents", "fill_px_cents",
    "decision_px_cents", "exp_slip_cents", "lane",
    "calibrated_probability", "settled_yes", "settled_at",
    "decision_ts", "exclusion_reason", "passed_edge_gate", "cf_status",
    "net_ev", "esrc", "q_assumed", "cf_yes", "cf_no",
)


def store_path_for(db_path: Any) -> Path:
    """Companion store path derived from the audit DB path (test-isolated)."""
    override = os.environ.get("MERID_EVIDENCE_OUTCOME_STORE", "").strip()
    if override:
        return Path(override)
    p = Path(str(db_path))
    return p.with_name(p.stem + "_evidence_outcomes.db")


class EvidenceOutcomeStore:
    """Small append-only SQLite store of per-settlement evidence rows."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.executescript(_STORE_SCHEMA)
        self._migrate_key_version(conn)
        return conn

    # Canonical market-side key version.  v1 stored ``mkey`` as the bare
    # ticker for 'fill' rows but ``ticker|side`` for 'veto'/'ebias' rows,
    # so one market-side could occupy two normalization groups and carry
    # ~2x weight.  v2 unifies every source on ``ticker|side`` -- venue,
    # market, and outcome side, the independence unit.
    KEY_VERSION = 2
    _KEY_VERSION_STATE_KEY = "evidence_key_version"

    def key_version(self, conn: sqlite3.Connection) -> int:
        try:
            return int(
                self.state_get(conn, self._KEY_VERSION_STATE_KEY) or "1"
            )
        except (TypeError, ValueError):
            return 1

    def _migrate_key_version(self, conn: sqlite3.Connection) -> None:
        """Re-key stored rows to canonical ``ticker|side`` mkeys (v1 -> v2).

        The canonical key is derivable from stored authoritative columns
        (``ticker``, ``side``), so retained rows are re-keyed in place
        rather than re-extracted from the multi-GB audit DB.  ``row_key``
        is rebuilt with the same formula ``extract_range`` uses so future
        overlap re-extraction stays idempotent; ``UPDATE OR IGNORE``
        protects the PRIMARY KEY against any unforeseen collision.
        Idempotent and cheap -- runs once per store connection.
        """
        if self.key_version(conn) >= self.KEY_VERSION:
            return
        conn.execute(
            "UPDATE evidence_outcome_rows "
            "SET mkey = ticker || '|' || side "
            "WHERE mkey IS NULL OR mkey != ticker || '|' || side"
        )
        conn.execute(
            "UPDATE OR IGNORE evidence_outcome_rows "
            "SET row_key = src || '|' || "
            "COALESCE(decision_id, 'None') || '|' || "
            "COALESCE(side, 'None') || '|' || "
            "COALESCE(mkey, 'None')"
        )
        self.state_set(
            conn, self._KEY_VERSION_STATE_KEY, str(self.KEY_VERSION)
        )
        conn.commit()

    # -- cursor state -----------------------------------------------------

    def state_get(self, conn: sqlite3.Connection, key: str) -> Optional[str]:
        row = conn.execute(
            "SELECT v FROM evidence_extract_state WHERE k = ?", (key,)
        ).fetchone()
        return row["v"] if row else None

    def state_set(
        self, conn: sqlite3.Connection, key: str, value: str
    ) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO evidence_extract_state (k, v) VALUES (?, ?)",
            (key, value),
        )

    # -- extraction --------------------------------------------------------

    def extract_range(
        self,
        audit_conn: sqlite3.Connection,
        store_conn: sqlite3.Connection,
        lo: float,
        hi: float,
        include_vetoes: bool = True,
    ) -> int:
        """Extract evidence rows for settlements in ``[lo, hi]``.

        Bounds are inclusive on both ends; adjacent backfill chunks and the
        live-trickle overlap share boundary timestamps, and ``row_key``
        dedup (``INSERT OR IGNORE``) makes re-extraction idempotent.  The
        inclusive upper bound also matters under frozen test clocks where
        ``settled_at == now`` exactly.

        Runs the three refresh queries bounded to the chunk on the audit
        connection (sharing its progress-handler deadline) and upserts into
        the store.  ``INSERT OR IGNORE`` makes overlapping ranges idempotent.
        Returns the number of newly inserted rows.
        """
        params = (lo, hi, lo - 3600.0)
        inserted = 0
        for sql in _QUERIES:
            if "'veto' AS src" in sql and not include_vetoes:
                continue
            for r in audit_conn.execute(sql, params).fetchall():
                keys = set(r.keys())
                row_key = "|".join(
                    str(r[k]) for k in ("src", "decision_id", "side", "mkey")
                )
                cols = [c for c in _ROW_COLS if c != "row_key"]
                cur = store_conn.execute(
                    "INSERT OR IGNORE INTO evidence_outcome_rows "
                    f"(row_key, {','.join(cols)}) VALUES "
                    f"(?,{','.join('?' for _ in cols)})",
                    (row_key, *[r[c] if c in keys else None for c in cols]),
                )
                inserted += cur.rowcount
        store_conn.commit()
        return inserted

    # -- reads / maintenance ----------------------------------------------

    def read_since(
        self,
        conn: sqlite3.Connection,
        since_ts: float,
        include_vetoes: bool = True,
    ) -> List[Dict[str, Any]]:
        sql = (
            "SELECT * FROM evidence_outcome_rows WHERE settled_at >= ?"
        )
        params: List[Any] = [since_ts]
        if not include_vetoes:
            sql += " AND src != 'veto'"
        sql += " ORDER BY settled_at"
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        for r in rows:
            # Read-time canonical override: grouping identity is
            # derived from authoritative ticker+side columns, not the
            # stored mkey.  A v1 writer (pre-migration code) can still
            # append bare-ticker fill keys after the store version
            # marker advances; overriding here keeps every consumer
            # on canonical keys regardless of mixed-version writes.
            # The stored value is preserved as provenance.
            _tk, _sd = r.get("ticker"), r.get("side")
            if _tk and _sd:
                r["stored_mkey"] = r.get("mkey")
                r["mkey"] = f"{_tk}|{_sd}"
            if r.get("src") == "fill":
                observed = r.get("fill_px_cents") is not None
                # ENTER decisions carry no order-type field, so an
                # unfilled ENTER is classified by its price basis
                # (executable taker price), not by assumed order style.
                r["evidence_kind"] = (
                    "observed_fill" if observed else "counterfactual_taker"
                )
                r["price_source"] = (
                    "actual_fill" if observed else "executable_fallback"
                )
                r["execution_observed"] = observed
            else:
                # 'veto'/'ebias' rows are settlement-labeled
                # counterfactuals at recorded executable prices --
                # never observed executions.
                r["evidence_kind"] = "counterfactual_taker"
                r["price_source"] = "counterfactual_executable"
                r["execution_observed"] = False
        return rows

    def max_settled_at(self, conn: sqlite3.Connection) -> Optional[float]:
        row = conn.execute(
            "SELECT MAX(settled_at) AS m FROM evidence_outcome_rows"
        ).fetchone()
        return row["m"] if row else None

    def prune(self, conn: sqlite3.Connection, before_ts: float) -> int:
        cur = conn.execute(
            "DELETE FROM evidence_outcome_rows WHERE settled_at < ?",
            (before_ts,),
        )
        conn.commit()
        return cur.rowcount
