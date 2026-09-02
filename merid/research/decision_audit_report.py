"""Read-only decision/audit ledger report.

Prints integrity checks, completeness, provenance, and decision summaries
without drawing model-quality conclusions until enough settled, eligible
observations are available.

Example:
    .\\.venv\\Scripts\\python.exe -m merid.research.decision_audit_report `
        --db data/decision_audit.db `
        --since 2026-09-01T00:00:00Z `
        --exclude-nonproduction `
        --validate-integrity
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


MIN_SETTLED_FOR_MODEL_QUALITY = 100


def _parse_since(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _ts_to_iso(ts: Optional[float]) -> str:
    if ts is None:
        return "N/A"
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class DecisionAuditReport:
    def __init__(self, db_path: Path, since: Optional[float], exclude_nonproduction: bool) -> None:
        self.db_path = db_path
        self.since = since
        self.exclude_nonproduction = exclude_nonproduction

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _integrity(self, conn: sqlite3.Connection) -> Dict[str, Any]:
        base, params = self._base_filter()

        # Decisions with a side-EV count other than exactly two (one per side).
        side_invariant = conn.execute(
            f"""
            SELECT d.decision_id, d.ticker, d.decision, COUNT(ev.side) AS side_rows,
                   GROUP_CONCAT(ev.side) AS sides
            FROM strategy_decisions AS d
            LEFT JOIN strategy_decision_side_ev AS ev ON ev.decision_id = d.decision_id
            {base}
            GROUP BY d.decision_id
            HAVING COUNT(ev.side) != 2 OR COUNT(DISTINCT ev.side) != 2
            """,
            params,
        ).fetchall()

        # Pending outcomes that already carry settlement/counterfactual data.
        pending_with_settlement = conn.execute(
            f"""
            SELECT decision_id
            FROM strategy_decision_outcomes
            WHERE outcome_status != 'SETTLED'
              AND (
                  settled_at IS NOT NULL
                  OR settled_yes IS NOT NULL
                  OR counterfactual_yes_pnl_cents IS NOT NULL
                  OR counterfactual_no_pnl_cents IS NOT NULL
              )
            """
        ).fetchall()

        # Decisions with no snapshot row.
        missing_snapshots = conn.execute(
            f"""
            SELECT d.decision_id
            FROM strategy_decisions AS d
            LEFT JOIN strategy_decision_snapshots AS s ON s.decision_id = d.decision_id
            {base.replace('d.', 'd.')}
            AND s.decision_id IS NULL
            """,
            params,
        ).fetchall() if base else conn.execute(
            """
            SELECT d.decision_id
            FROM strategy_decisions AS d
            LEFT JOIN strategy_decision_snapshots AS s ON s.decision_id = d.decision_id
            WHERE s.decision_id IS NULL
            """
        ).fetchall()

        # Decisions with no side-EV rows at all.
        missing_side_ev = conn.execute(
            f"""
            SELECT d.decision_id
            FROM strategy_decisions AS d
            LEFT JOIN strategy_decision_side_ev AS ev ON ev.decision_id = d.decision_id
            {base}
            AND ev.decision_id IS NULL
            """,
            params,
        ).fetchall() if base else conn.execute(
            """
            SELECT d.decision_id
            FROM strategy_decisions AS d
            LEFT JOIN strategy_decision_side_ev AS ev ON ev.decision_id = d.decision_id
            WHERE ev.decision_id IS NULL
            """
        ).fetchall()

        # Outcome rows with no parent decision.
        orphan_outcomes = conn.execute(
            """
            SELECT o.decision_id
            FROM strategy_decision_outcomes AS o
            LEFT JOIN strategy_decisions AS d ON d.decision_id = o.decision_id
            WHERE d.decision_id IS NULL
            """
        ).fetchall()

        # ENTER decisions that have no linked outcome after a 5-minute grace.
        # Outcomes are created immediately, so this checks for missing outcome rows.
        enter_missing_outcome = conn.execute(
            f"""
            SELECT d.decision_id
            FROM strategy_decisions AS d
            LEFT JOIN strategy_decision_outcomes AS o ON o.decision_id = d.decision_id
            {base}
            AND d.decision = 'ENTER'
            AND o.decision_id IS NULL
            """,
            params,
        ).fetchall() if base else conn.execute(
            """
            SELECT d.decision_id
            FROM strategy_decisions AS d
            LEFT JOIN strategy_decision_outcomes AS o ON o.decision_id = d.decision_id
            WHERE d.decision = 'ENTER'
              AND o.decision_id IS NULL
            """
        ).fetchall()

        return {
            "side_invariant_violations": len(side_invariant),
            "side_invariant_rows": [dict(r) for r in side_invariant[:10]],
            "pending_with_settlement_fields": len(pending_with_settlement),
            "missing_snapshots": len(missing_snapshots),
            "missing_side_ev": len(missing_side_ev),
            "orphan_outcomes": len(orphan_outcomes),
            "enter_missing_outcome": len(enter_missing_outcome),
        }

    def _counts(self, conn: sqlite3.Connection) -> Dict[str, Any]:
        base, params = self._base_filter()

        total_decisions = conn.execute(
            f"SELECT COUNT(*) FROM strategy_decisions AS d {base}", params
        ).fetchone()[0]
        total_snapshots = conn.execute(
            f"""
            SELECT COUNT(*) FROM strategy_decision_snapshots AS s
            WHERE EXISTS (
                SELECT 1 FROM strategy_decisions AS d WHERE d.decision_id = s.decision_id
                {base.replace('WHERE', 'AND') if base else ''}
            )
            """,
            params,
        ).fetchone()[0]
        total_side_ev = conn.execute(
            f"""
            SELECT COUNT(*) FROM strategy_decision_side_ev AS ev
            WHERE EXISTS (
                SELECT 1 FROM strategy_decisions AS d WHERE d.decision_id = ev.decision_id
                {base.replace('WHERE', 'AND') if base else ''}
            )
            """,
            params,
        ).fetchone()[0]

        outcome_status = conn.execute(
            f"""
            SELECT o.outcome_status, COUNT(*)
            FROM strategy_decision_outcomes AS o
            JOIN strategy_decisions AS d ON d.decision_id = o.decision_id
            {base}
            GROUP BY o.outcome_status
            """,
            params,
        ).fetchall()

        return {
            "total_decisions": total_decisions,
            "total_snapshots": total_snapshots,
            "total_side_ev": total_side_ev,
            "expected_side_ev_rows": 2 * total_decisions,
            "outcome_status": {r["outcome_status"]: r[1] for r in outcome_status},
            "settled_count": sum(r[1] for r in outcome_status if r["outcome_status"] == "SETTLED"),
        }

    def _provenance(self, conn: sqlite3.Connection) -> Dict[str, Any]:
        # Provenance is intentionally shown for all records, not just the research subset,
        # so contamination can be surfaced even when --exclude-nonproduction is used.
        clauses: List[str] = []
        params: List[Any] = []
        if self.since is not None:
            clauses.append("decision_ts >= ?")
            params.append(self.since)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        rows = conn.execute(
            f"""
            SELECT record_environment, record_source, is_eligible_for_research, COUNT(*)
            FROM strategy_decisions
            {where}
            GROUP BY record_environment, record_source, is_eligible_for_research
            ORDER BY COUNT(*) DESC
            """,
            params,
        ).fetchall()
        return {
            "breakdown": [
                {
                    "record_environment": r["record_environment"],
                    "record_source": r["record_source"],
                    "is_eligible_for_research": bool(r["is_eligible_for_research"]),
                    "count": r[3],
                }
                for r in rows
            ]
        }

    def _base_filter(self) -> Tuple[str, List[Any]]:
        """Build a WHERE clause for the decisions table."""
        clauses: List[str] = []
        params: List[Any] = []
        if self.since is not None:
            clauses.append("d.decision_ts >= ?")
            params.append(self.since)
        if self.exclude_nonproduction:
            clauses.append("d.record_environment = 'production'")
            clauses.append("d.is_eligible_for_research = 1")
        if not clauses:
            return "", []
        return "WHERE " + " AND ".join(clauses), params

    def _reasons(self, conn: sqlite3.Connection) -> List[Dict[str, Any]]:
        base, params = self._base_filter()
        rows = conn.execute(
            f"""
            SELECT d.asset, d.decision, d.primary_reason_code, COUNT(*) AS n
            FROM strategy_decisions AS d
            {base}
            GROUP BY d.asset, d.decision, d.primary_reason_code
            ORDER BY d.asset, d.decision, n DESC
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def _time_buckets(self, conn: sqlite3.Connection) -> List[Dict[str, Any]]:
        base, params = self._base_filter()
        rows = conn.execute(
            f"""
            SELECT
                CASE
                    WHEN d.seconds_to_close < 60 THEN '0-60s'
                    WHEN d.seconds_to_close < 300 THEN '1-5m'
                    WHEN d.seconds_to_close < 600 THEN '5-10m'
                    ELSE '10-15m'
                END AS time_bucket,
                d.asset,
                COUNT(*) AS n
            FROM strategy_decisions AS d
            {base}
            GROUP BY time_bucket, d.asset
            ORDER BY time_bucket, d.asset
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def _side_dimensions(self, conn: sqlite3.Connection) -> List[Dict[str, Any]]:
        base, params = self._base_filter()
        rows = conn.execute(
            f"""
            SELECT
                ev.side,
                SUM(ev.model_evaluated) AS model_evaluated,
                SUM(ev.policy_eligible) AS policy_eligible,
                SUM(ev.executable) AS executable,
                SUM(ev.passed_net_ev) AS passed_net_ev,
                SUM(ev.selected) AS selected,
                SUM(CASE WHEN ev.passed_net_ev = 0 AND ev.policy_eligible = 1 THEN 1 ELSE 0 END) AS policy_excluded_with_positive_ev,
                COUNT(*) AS total
            FROM strategy_decision_side_ev AS ev
            JOIN strategy_decisions AS d ON d.decision_id = ev.decision_id
            {base}
            GROUP BY ev.side
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def _null_rates(self, conn: sqlite3.Connection) -> Dict[str, Any]:
        base, params = self._base_filter()
        snapshot_cols = [
            "spot_price",
            "spot_source",
            "spot_source_ts",
            "settlement_reference_price",
            "settlement_reference_source",
            "settlement_reference_ts",
            "yes_bid_cents",
            "yes_ask_cents",
            "no_bid_cents",
            "no_ask_cents",
            "vol_forecast",
            "vol_source",
            "realized_vol_1m",
            "zscore",
            "velocity",
            "velocity_source",
        ]
        snapshot_nulls = {}
        if base:
            for col in snapshot_cols:
                total = conn.execute(
                    f"""
                    SELECT COUNT(*) FROM strategy_decision_snapshots AS s
                    JOIN strategy_decisions AS d ON d.decision_id = s.decision_id
                    {base}
                    """,
                    params,
                ).fetchone()[0]
                nulls = conn.execute(
                    f"""
                    SELECT COUNT(*) FROM strategy_decision_snapshots AS s
                    JOIN strategy_decisions AS d ON d.decision_id = s.decision_id
                    {base}
                    AND s.{col} IS NULL
                    """,
                    params,
                ).fetchone()[0]
                snapshot_nulls[col] = (nulls, total)
        else:
            total = conn.execute("SELECT COUNT(*) FROM strategy_decision_snapshots").fetchone()[0]
            for col in snapshot_cols:
                nulls = conn.execute(
                    f"SELECT COUNT(*) FROM strategy_decision_snapshots WHERE {col} IS NULL"
                ).fetchone()[0]
                snapshot_nulls[col] = (nulls, total)

        side_nulls = {}
        side_cols = [
            "executable_entry_price_cents",
            "raw_probability",
            "calibrated_probability",
            "gross_edge_cents",
            "expected_net_ev_cents",
        ]
        if base:
            total = conn.execute(
                f"""
                SELECT COUNT(*) FROM strategy_decision_side_ev AS ev
                JOIN strategy_decisions AS d ON d.decision_id = ev.decision_id
                {base}
                """,
                params,
            ).fetchone()[0]
            for col in side_cols:
                nulls = conn.execute(
                    f"""
                    SELECT COUNT(*) FROM strategy_decision_side_ev AS ev
                    JOIN strategy_decisions AS d ON d.decision_id = ev.decision_id
                    {base}
                    AND ev.{col} IS NULL
                    """,
                    params,
                ).fetchone()[0]
                side_nulls[col] = (nulls, total)
        else:
            total = conn.execute("SELECT COUNT(*) FROM strategy_decision_side_ev").fetchone()[0]
            for col in side_cols:
                nulls = conn.execute(
                    f"SELECT COUNT(*) FROM strategy_decision_side_ev WHERE {col} IS NULL"
                ).fetchone()[0]
                side_nulls[col] = (nulls, total)

        return {
            "snapshot_total": total if not base else None,
            "snapshot_nulls": snapshot_nulls,
            "side_total": total if not base else None,
            "side_nulls": side_nulls,
        }

    def run(self, validate_integrity: bool = False, pending_only: bool = False) -> str:
        if not self.db_path.exists():
            return f"DB not found: {self.db_path}"

        lines: List[str] = []
        lines.append("=" * 60)
        lines.append("MERID decision-audit report")
        lines.append(f"DB: {self.db_path}")
        lines.append(f"Since: {_ts_to_iso(self.since) if self.since else 'all time'}")
        lines.append(f"Exclude non-production: {self.exclude_nonproduction}")
        lines.append(f"Report time: {datetime.now(timezone.utc).isoformat()}")
        lines.append("=" * 60)

        with self._conn() as conn:
            if validate_integrity:
                lines.append("\n--- Integrity checks ---")
                integrity = self._integrity(conn)
                for key, value in integrity.items():
                    if isinstance(value, list):
                        lines.append(f"{key}: {len(value)}")
                        for item in value[:5]:
                            lines.append(f"  {item}")
                    else:
                        lines.append(f"{key}: {value}")

            lines.append("\n--- Table counts ---")
            counts = self._counts(conn)
            for key, value in counts.items():
                if key == "outcome_status":
                    lines.append(f"  outcome_status:")
                    for status, n in value.items():
                        lines.append(f"    {status}: {n}")
                else:
                    lines.append(f"  {key}: {value}")

            lines.append("\n--- Provenance ---")
            provenance = self._provenance(conn)
            for row in provenance["breakdown"]:
                lines.append(
                    f"  env={row['record_environment']} source={row['record_source']} "
                    f"eligible={row['is_eligible_for_research']} count={row['count']}"
                )

            if not pending_only:
                lines.append("\n--- Decision reasons by asset ---")
                for row in self._reasons(conn):
                    lines.append(
                        f"  asset={row['asset']} decision={row['decision']} "
                        f"reason={row['primary_reason_code']} count={row['n']}"
                    )

                lines.append("\n--- Time-to-close buckets by asset ---")
                for row in self._time_buckets(conn):
                    lines.append(
                        f"  bucket={row['time_bucket']} asset={row['asset']} count={row['n']}"
                    )

                lines.append("\n--- Side evaluation dimensions ---")
                for row in self._side_dimensions(conn):
                    lines.append(
                        f"  side={row['side']} total={row['total']} "
                        f"model_evaluated={row['model_evaluated']} "
                        f"policy_eligible={row['policy_eligible']} "
                        f"executable={row['executable']} "
                        f"passed_net_ev={row['passed_net_ev']} "
                        f"selected={row['selected']} "
                        f"policy_excluded_with_positive_ev={row['policy_excluded_with_positive_ev']}"
                    )

                lines.append("\n--- Null/default rates ---")
                nulls = self._null_rates(conn)
                lines.append("  Snapshot columns:")
                for col, (nulls_count, total) in nulls["snapshot_nulls"].items():
                    pct = 100.0 * nulls_count / total if total else 0.0
                    lines.append(f"    {col}: {nulls_count}/{total} ({pct:.1f}%)")
                lines.append("  Side-EV columns:")
                for col, (nulls_count, total) in nulls["side_nulls"].items():
                    pct = 100.0 * nulls_count / total if total else 0.0
                    lines.append(f"    {col}: {nulls_count}/{total} ({pct:.1f}%)")

        lines.append("\n--- Research readiness ---")
        settled = counts.get("settled_count", 0)
        if counts.get("total_decisions", 0) == 0:
            lines.append("  No decisions match the filter; nothing to report.")
        elif settled < MIN_SETTLED_FOR_MODEL_QUALITY:
            lines.append(
                f"  Settled, eligible decisions: {settled} "
                f"(need {MIN_SETTLED_FOR_MODEL_QUALITY} before model-quality conclusions)."
            )
            lines.append("  Refusing to emit Brier/reliability/calibration output.")
        else:
            lines.append(
                f"  Settled, eligible decisions: {settled} "
                f"(sufficient for model-quality reporting; extend this module to add it)."
            )

        return "\n".join(lines)


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only decision audit report")
    parser.add_argument("--db", type=Path, default=Path("data/decision_audit.db"))
    parser.add_argument("--since", type=str, default=None)
    parser.add_argument("--exclude-nonproduction", action="store_true")
    parser.add_argument("--pending-only", action="store_true")
    parser.add_argument("--validate-integrity", action="store_true")
    args = parser.parse_args(argv)

    since = _parse_since(args.since)
    report = DecisionAuditReport(
        db_path=args.db,
        since=since,
        exclude_nonproduction=args.exclude_nonproduction,
    )
    print(report.run(validate_integrity=args.validate_integrity, pending_only=args.pending_only))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
