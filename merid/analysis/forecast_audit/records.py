"""Data access layer for the forecast audit scorer.

Read-only loaders over the existing ledgers. The scorer recomputes losses
from probabilities and official outcomes; it never trusts strategy-provided
edge/EV fields.

Sources
-------
- ``data/decision_audit.db`` (primary): ``strategy_decisions`` joined to
  ``strategy_decision_snapshots`` and ``strategy_decision_outcomes``.
  ``raw_p_yes`` is the pre-anchor model probability (written from
  ``decision.p_yes_raw``); ``calibrated_p_yes`` is the final emitted
  probability (``decision.p_yes_calibrated``, post anchor + walk-forward +
  EPC + tail caps + lane bounds). Verified against
  ``merid/prediction/trade_decision.py`` (anchor blend reproduced exactly).
- ``logs/model_calibration_observations.jsonl``: the post-anchor +
  walk-forward stage (pre EPC/tail), logged once per
  ``(ticker, side, TTE-minute)``. Only covers 2026-10-14 onward and is the
  ONLY persisted post-anchor stage — the pure post-anchor probability and
  ``market_anchor_prob`` are not persisted anywhere.
- ``logs/settlement_outcomes.jsonl``: official Kalshi outcomes. Used to
  (a) cross-check audit-DB labels and (b) provide label-availability
  timestamps (``observed_at_utc``) where the audit DB only stores the
  exchange settlement time.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


_TICKER_ASSET_RE = re.compile(r"^KX([A-Z]+)15M-")


def asset_from_ticker(ticker: str) -> Optional[str]:
    """Resolve asset from the Kalshi 15m ticker stem (KXBTC15M-... -> BTC).

    Single source of truth shared by probe filtering and expected-population
    construction. Returns None for non-target-series tickers.
    """
    m = _TICKER_ASSET_RE.match(str(ticker).strip().upper())
    return m.group(1) if m else None


@dataclass(slots=True)
class DecisionRow:
    """One decision-cycle row joined with its market snapshot and outcome."""

    decision_id: str
    ticker: str
    asset: str
    decision_ts: float
    close_ts: Optional[float]
    seconds_to_close: Optional[float]
    raw_p_yes: Optional[float]
    calibrated_p_yes: Optional[float]
    yes_bid_cents: Optional[float]
    yes_ask_cents: Optional[float]
    no_bid_cents: Optional[float]
    no_ask_cents: Optional[float]
    model_version: Optional[str]
    calibration_version: Optional[str]
    config_version: Optional[str]
    build_sha: Optional[str]
    policy_epoch: Optional[str]
    record_environment: Optional[str]
    record_source: Optional[str]
    selected_side: Optional[str]
    decision: Optional[str]
    settled_yes: Optional[int]
    settled_at: Optional[float]
    outcome_status: Optional[str]
    realized_net_pnl_cents: Optional[float]
    fill_id: Optional[str]

    @property
    def yes_mid(self) -> Optional[float]:
        if self.yes_bid_cents is None or self.yes_ask_cents is None:
            return None
        return (float(self.yes_bid_cents) + float(self.yes_ask_cents)) / 200.0


# Column list shared by the full-scan loader and the probe loader.
# sqlite3.Row keys are the unqualified column names, which must match
# ``DecisionRow`` field names — construction is by name, never positional.
_ROW_COLS = """d.decision_id, d.ticker, d.asset, d.decision_ts, d.close_ts,
       d.seconds_to_close,
       s.raw_p_yes, s.calibrated_p_yes,
       s.yes_bid_cents, s.yes_ask_cents, s.no_bid_cents, s.no_ask_cents,
       d.model_version, d.calibration_version, d.config_version,
       d.build_sha, d.policy_epoch, d.record_environment, d.record_source,
       d.selected_side, d.decision,
       o.settled_yes, o.settled_at, o.outcome_status,
       o.realized_net_pnl_cents, o.fill_id"""

_ROW_JOINS = """
FROM strategy_decisions d
LEFT JOIN strategy_decision_snapshots s USING (decision_id)
LEFT JOIN strategy_decision_outcomes o USING (decision_id)
"""

_DECISION_SQL = f"""
SELECT {_ROW_COLS} {_ROW_JOINS}
WHERE d.ticker != ''
"""


def load_decisions(
    db_path: str | Path,
    *,
    since_ts: Optional[float] = None,
    until_ts: Optional[float] = None,
    assets: Optional[List[str]] = None,
    require_production: bool = True,
    require_research: bool = True,
) -> List[DecisionRow]:
    """Load joined decision rows (unordered; callers sort per-ticker).

    ``require_research`` applies the ledger's own research-population flag
    (``is_eligible_for_research``) — the same contract the ledger's evidence
    queries use. No ORDER BY in SQL: the filesort over the full join is the
    dominant cost on this DB; per-ticker sort happens in
    ``build_population`` instead.
    """
    sql = _DECISION_SQL
    params: List[Any] = []
    clauses: List[str] = []
    if since_ts is not None:
        clauses.append("d.decision_ts >= ?")
        params.append(float(since_ts))
    if until_ts is not None:
        clauses.append("d.decision_ts <= ?")
        params.append(float(until_ts))
    if assets:
        clauses.append(f"d.asset IN ({','.join('?' for _ in assets)})")
        params.extend(a.upper() for a in assets)
    if require_production:
        clauses.append("d.record_environment = 'production'")
    if require_research:
        clauses.append("d.is_eligible_for_research = 1")
    if clauses:
        sql = sql.replace("WHERE d.ticker != ''", "WHERE d.ticker != '' AND " + " AND ".join(clauses))

    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, params)
        return [DecisionRow(**dict(r)) for r in cur.fetchall()]
    finally:
        conn.close()


def count_decision_rows(
    db_path: str | Path,
    *,
    assets: Optional[List[str]] = None,
) -> Dict[str, int]:
    """Population accounting: total vs research-eligible decision rows.

    A full table scan (the audit DB has no partial index); run once for the
    manifest's coverage accounting.
    """
    clauses = ["ticker != ''"]
    params: List[Any] = []
    if assets:
        clauses.append(f"asset IN ({','.join('?' for _ in assets)})")
        params.extend(a.upper() for a in assets)
    where = " AND ".join(clauses)
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        total, prod, res = conn.execute(
            f"""SELECT COUNT(*),
                       SUM(record_environment = 'production'),
                       SUM(record_environment = 'production'
                           AND is_eligible_for_research = 1)
                FROM strategy_decisions WHERE {where}""",
            params,
        ).fetchone()
    finally:
        conn.close()
    return {
        "decision_rows_total": int(total or 0),
        "decision_rows_production": int(prod or 0),
        "decision_rows_research_eligible": int(res or 0),
    }


# ---------------------------------------------------------------------------
# Probe-based population loader (production path)
# ---------------------------------------------------------------------------
#
# ``load_decisions`` performs a full join scan over ``strategy_decisions``
# (~700k rows / multi-GB on the live box). The evaluation population needs
# only ~one row per (ticker, horizon) — the latest ELIGIBLE decision
# at-or-before ``close_ts - horizon``. ``idx_decisions_ticker`` covers
# (ticker, decision_ts), so per-ticker probing is a handful of index seeks
# instead of a table scan. This is also what makes the audit safe to run on
# the live host: bounded reads, small working set, no page-cache thrash.


@dataclass
class HorizonProbe:
    """Selection evidence for one (ticker, horizon).

    ``row`` is the latest eligible decision at-or-before the target, or None.
    ``latest_ts_any`` is the latest decision_ts at-or-before the target with
    NO eligibility filters — distinguishes "no rows before target" from
    "rows exist but none eligible" and bounds the stale check.
    """

    horizon_s: float
    target_ts: float
    row: Optional[DecisionRow]
    latest_ts_any: Optional[float]


@dataclass
class TickerProbe:
    ticker: str
    asset: Optional[str]
    close_ts_first: Optional[float]
    close_ts_last: Optional[float]
    first_decision_ts: Optional[float]
    last_decision_ts: Optional[float]
    ledger_outcome: Optional[Tuple[Optional[int], Optional[float], Optional[str]]]
    horizons: List[HorizonProbe]
    # Ticker-stem asset vs decisions' asset column disagreement -> quarantined
    # downstream (never silently prefer one source).
    asset_mismatch: bool = False


@dataclass
class ProbeRun:
    probes: List[TickerProbe]
    universe_query: str            # "indexed" | "unhinted_fallback"
    warnings: List[str] = field(default_factory=list)
    asset_mismatch_tickers: List[str] = field(default_factory=list)
    tickers_discovered: int = 0
    tickers_after_asset_filter: int = 0
    tickers_excluded_close_window: int = 0

    def __len__(self) -> int:
        return len(self.probes)


def _eligibility_clauses(
    require_production: bool, require_research: bool
) -> List[str]:
    clauses = ["d.ticker != ''"]
    if require_production:
        clauses.append("d.record_environment = 'production'")
    if require_research:
        clauses.append("d.is_eligible_for_research = 1")
    return clauses


def probe_horizon_population(
    db_path: str | Path,
    *,
    horizons_s: Sequence[float],
    assets: Optional[List[str]] = None,
    require_production: bool = True,
    require_research: bool = True,
    probe_limit: Optional[int] = None,
    since_close_ts: Optional[float] = None,
    until_close_ts: Optional[float] = None,
    progress_cb: Optional[Any] = None,
) -> ProbeRun:
    """Index-assisted per-ticker probe of the evaluation population.

    For each ticker: two extreme-row probes establish ``close_ts`` (last
    decision row = most informed value; first row for the drift flag) and the
    decision window. For each horizon: one probe for the latest eligible row
    at-or-before ``close_ts - horizon``; on miss, one unfiltered probe to
    bound the missing reason. Ledger outcome is fetched per ticker (for the
    official-outcome cross-check and as label fallback).

    Roughly 6-10 index seeks per ticker — no table scan. When
    ``idx_decisions_ticker`` is absent the ticker universe falls back to an
    unhinted DISTINCT scan (expensive on the live DB; reported in
    ``ProbeRun.warnings``).
    """
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    # Read-only friendliness on the live host: mapped reads hit the OS page
    # cache directly (good for random probes on a multi-GB DB); small temp
    # store keeps incidental state off disk. Failures are non-fatal.
    for pragma in (
        "PRAGMA temp_store=MEMORY",
        "PRAGMA mmap_size=8589934592",
        "PRAGMA cache_size=-262144",
    ):
        try:
            conn.execute(pragma)
        except sqlite3.Error:
            pass
    elig = " AND ".join(_eligibility_clauses(require_production, require_research))
    warnings: List[str] = []
    try:
        # Ticker universe: covering scan of idx_decisions_ticker when present.
        universe_query = "indexed"
        try:
            t0_rows = conn.execute(
                "SELECT DISTINCT ticker FROM strategy_decisions "
                "INDEXED BY idx_decisions_ticker WHERE ticker != ''"
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such index" not in str(exc).lower():
                raise
            universe_query = "unhinted_fallback"
            warnings.append(
                "idx_decisions_ticker missing — ticker universe resolved by "
                "unhinted DISTINCT scan (expensive on the live DB)")
            t0_rows = conn.execute(
                "SELECT DISTINCT ticker FROM strategy_decisions "
                "WHERE ticker != ''"
            ).fetchall()
        tickers = sorted(r[0] for r in t0_rows)
        n_discovered = len(tickers)
        if assets:
            wanted = {a.upper() for a in assets}
            tickers = [
                t for t in tickers if asset_from_ticker(t) in wanted
            ]
        n_after_asset = len(tickers)
        if probe_limit:
            tickers = tickers[:probe_limit]
        n_excluded_window = 0

        out: List[TickerProbe] = []
        for tk_i, ticker in enumerate(tickers):
            if progress_cb and tk_i and tk_i % 250 == 0:
                progress_cb(f"  probed {tk_i}/{len(tickers)} tickers")
            first = conn.execute(
                "SELECT close_ts, decision_ts, asset FROM strategy_decisions "
                "WHERE ticker = ? ORDER BY decision_ts ASC LIMIT 1",
                (ticker,),
            ).fetchone()
            last = conn.execute(
                "SELECT close_ts, decision_ts, asset FROM strategy_decisions "
                "WHERE ticker = ? ORDER BY decision_ts DESC LIMIT 1",
                (ticker,),
            ).fetchone()
            if first is None or last is None:
                continue
            close_first = first["close_ts"]
            close_last = last["close_ts"]
            close_ts = close_last if close_last is not None else close_first
            asset = last["asset"] or first["asset"]
            stem_asset = asset_from_ticker(ticker)
            mismatch = (
                stem_asset is not None
                and asset is not None
                and str(asset).upper() != stem_asset
            )
            if close_ts is not None:
                if since_close_ts is not None and close_ts < since_close_ts:
                    n_excluded_window += 1
                    continue
                if until_close_ts is not None and close_ts > until_close_ts:
                    n_excluded_window += 1
                    continue

            # Ledger outcome for this ticker, newest decision row first —
            # outcome status backfills onto recent rows, so a settled ticker
            # hits in ~1-5 seeks. (An ORDER BY o.settled_at variant forced a
            # full per-ticker join+sort — ~300 seeks/ticker — and was the
            # dominant cost on the live DB.)
            ledger_outcome: Optional[
                Tuple[Optional[int], Optional[float], Optional[str]]
            ] = None
            o_row = conn.execute(
                "SELECT o.settled_yes, o.settled_at, o.outcome_status "
                "FROM strategy_decisions d "
                "JOIN strategy_decision_outcomes o USING (decision_id) "
                "WHERE d.ticker = ? AND o.settled_yes IS NOT NULL "
                "ORDER BY d.decision_ts DESC LIMIT 1",
                (ticker,),
            ).fetchone()
            if o_row is not None:
                ledger_outcome = (
                    int(o_row[0]), o_row[1], o_row[2],
                )
            else:
                s_row = conn.execute(
                    "SELECT o.outcome_status, o.settled_at "
                    "FROM strategy_decisions d "
                    "JOIN strategy_decision_outcomes o USING (decision_id) "
                    "WHERE d.ticker = ? AND o.outcome_status IS NOT NULL "
                    "ORDER BY d.decision_ts DESC LIMIT 1",
                    (ticker,),
                ).fetchone()
                if s_row is not None:
                    ledger_outcome = (None, s_row[1], s_row[0])

            h_probes: List[HorizonProbe] = []
            if close_ts is not None:
                for h in horizons_s:
                    target = close_ts - h
                    row = conn.execute(
                        f"SELECT {_ROW_COLS} {_ROW_JOINS} "
                        f"WHERE d.ticker = ? AND d.decision_ts <= ? AND {elig} "
                        "ORDER BY d.decision_ts DESC LIMIT 1",
                        (ticker, target),
                    ).fetchone()
                    latest_any: Optional[float] = None
                    if row is None:
                        any_row = conn.execute(
                            "SELECT decision_ts FROM strategy_decisions "
                            "WHERE ticker = ? AND decision_ts <= ? "
                            "ORDER BY decision_ts DESC LIMIT 1",
                            (ticker, target),
                        ).fetchone()
                        latest_any = (
                            float(any_row[0]) if any_row is not None else None
                        )
                    h_probes.append(HorizonProbe(
                        horizon_s=float(h),
                        target_ts=float(target),
                        # Named construction: sqlite3.Row keys match
                        # DecisionRow field names; positional unpacking would
                        # silently scramble fields on any column drift.
                        row=DecisionRow(**dict(row)) if row is not None else None,
                        latest_ts_any=latest_any,
                    ))
            out.append(TickerProbe(
                ticker=ticker,
                asset=asset,
                close_ts_first=close_first,
                close_ts_last=close_last,
                first_decision_ts=(
                    float(first["decision_ts"])
                    if first["decision_ts"] is not None else None),
                last_decision_ts=(
                    float(last["decision_ts"])
                    if last["decision_ts"] is not None else None),
                ledger_outcome=ledger_outcome,
                horizons=h_probes,
                asset_mismatch=mismatch,
            ))
        mismatched = [p.ticker for p in out if p.asset_mismatch]
        return ProbeRun(
            probes=out,
            universe_query=universe_query,
            warnings=warnings,
            asset_mismatch_tickers=mismatched,
            tickers_discovered=n_discovered,
            tickers_after_asset_filter=n_after_asset,
            tickers_excluded_close_window=n_excluded_window,
        )
    finally:
        conn.close()


def load_fill_economics(
    db_path: str | Path,
    *,
    assets: Optional[List[str]] = None,
    require_production: bool = True,
    require_research: bool = True,
) -> List[Tuple[str, float]]:
    """Descriptive fill economics: (asset, realized_net_pnl_cents) for
    settled ENTER decisions. Scans the outcomes table once — opt-in only.
    """
    clauses = ["d.ticker != ''", "o.realized_net_pnl_cents IS NOT NULL",
               "d.decision = 'ENTER'"]
    params: List[Any] = []
    if assets:
        clauses.append(f"d.asset IN ({','.join('?' for _ in assets)})")
        params.extend(a.upper() for a in assets)
    if require_production:
        clauses.append("d.record_environment = 'production'")
    if require_research:
        clauses.append("d.is_eligible_for_research = 1")
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        return [
            (str(a) if a else "UNKNOWN", float(p)) for a, p in conn.execute(
                "SELECT d.asset, o.realized_net_pnl_cents "
                "FROM strategy_decision_outcomes o "
                "JOIN strategy_decisions d USING (decision_id) "
                f"WHERE {' AND '.join(clauses)}",
                params,
            ).fetchall()
        ]
    finally:
        conn.close()


@dataclass
class AnchoredStageRecord:
    ts: float          # emission time inside the producing decision evaluation
    p_model: float


@dataclass
class AnchoredStageLog:
    """Post-anchor+WF observations keyed by (ticker, tte_minute_bucket).

    ``by_key`` holds ALL yes-side records per bucket (ts-sorted), not a
    first-wins survivor — the producer's in-memory dedupe already collapses
    to one write per (ticker, side, minute), so on-disk duplicates are
    restart/dupe writes the join must be able to arbitrate between.

    Timestamp semantics (verified in ``model_calibration_log.py``): ``ts``
    is ``time.time()`` at synchronous emission inside the producing
    decision evaluation. It structurally postdates that decision's
    ``decision_ts`` (which is stamped at evaluation entry) by the
    evaluation duration — measured p95 lag +0.02s on the live ledger.
    No event id, model version, or decision id is persisted, so no record
    can be verified to belong to a specific inference event; every join is
    a bounded as-of match.
    """

    by_key: Dict[Tuple[str, int], List[AnchoredStageRecord]]
    rows: int
    complement_mismatches: int
    first_ts: Optional[float]
    last_ts: Optional[float]


def load_anchored_stage(path: str | Path) -> AnchoredStageLog:
    """Load model-calibration observations (post-anchor+WF, pre-EPC/tail).

    Only ``side == 'yes'`` rows are kept (YES space). Complement consistency
    is checked on (ticker, minute) pairs where both sides exist.
    """
    by_key: Dict[Tuple[str, int], List[AnchoredStageRecord]] = {}
    no_side: Dict[Tuple[str, int], float] = {}
    rows = 0
    mismatches = 0
    first_ts: Optional[float] = None
    last_ts: Optional[float] = None
    p = Path(path)
    if not p.exists():
        return AnchoredStageLog(by_key, 0, 0, None, None)
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            ticker = r.get("ticker")
            p_model = r.get("p_model")
            tte = r.get("seconds_to_expiry")
            ts = r.get("ts")
            side = str(r.get("side") or "").lower()
            if not ticker or p_model is None or tte is None or ts is None:
                continue
            rows += 1
            ts = float(ts)
            first_ts = ts if first_ts is None else min(first_ts, ts)
            last_ts = ts if last_ts is None else max(last_ts, ts)
            minute = int(float(tte) // 60)
            key = (str(ticker), minute)
            if side == "yes":
                by_key.setdefault(key, []).append(
                    AnchoredStageRecord(ts=ts, p_model=float(p_model)))
            elif side == "no":
                no_side[key] = float(p_model)
    for recs in by_key.values():
        recs.sort(key=lambda r: r.ts)
    for key, p_no in no_side.items():
        recs = by_key.get(key)
        if recs and any(
            abs((rec.p_model + p_no) - 1.0) > 0.02 for rec in recs
        ):
            mismatches += 1
    return AnchoredStageLog(by_key, rows, mismatches, first_ts, last_ts)


@dataclass
class LabelVersion:
    """One outcome event as observed at a point in time.

    ``observed_ts`` is the exporter's ``observed_at_utc`` — a documented
    availability bound (when OUR export first saw the label). None means
    availability is undocumented; under the ``grace`` policy it is assumed
    ``settlement_ts + LABEL_AVAILABILITY_GRACE_S``, under ``observed_only``
    such versions may not be used for historical training.
    """

    observed_ts: Optional[float]
    settlement_ts: Optional[float]
    resolved_yes: int


@dataclass
class OfficialOutcome:
    resolved_yes: int
    observed_at_ts: Optional[float]
    settlement_ts: Optional[float]
    asset: Optional[str] = None
    versions: List[LabelVersion] = field(default_factory=list)


@dataclass
class OfficialOutcomes:
    by_ticker: Dict[str, OfficialOutcome]
    corrections: int
    malformed: int


def _parse_ts_seconds(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    try:
        from datetime import datetime, timezone

        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def load_official_outcomes(path: str | Path) -> OfficialOutcomes:
    """Load the settlement-outcome JSONL.

    Scoring uses the latest valid event per ticker (corrections applied,
    exporter semantics). The full per-ticker version list is preserved so
    walk-forward training can use the label AS OF a fold boundary — a
    correction published after the boundary must not leak back into that
    fold's training set.
    """
    by_ticker: Dict[str, OfficialOutcome] = {}
    corrections = 0
    malformed = 0
    p = Path(path)
    if not p.exists():
        return OfficialOutcomes(by_ticker, 0, 0)
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if not isinstance(r, dict):
                malformed += 1
                continue
            etype = r.get("event_type")
            ticker = r.get("ticker")
            if etype == "settlement_correction":
                corrections += 1
            if not ticker:
                malformed += 1
                continue
            resolved = r.get("resolved_yes")
            if resolved not in (0, 1):
                try:
                    resolved = int(resolved)
                except (TypeError, ValueError):
                    malformed += 1
                    continue
                if resolved not in (0, 1):
                    malformed += 1
                    continue
            key = str(ticker).strip().upper()
            ver = LabelVersion(
                observed_ts=_parse_ts_seconds(r.get("observed_at_utc")),
                settlement_ts=_parse_ts_seconds(r.get("settlement_timestamp_utc")),
                resolved_yes=int(resolved),
            )
            cur = by_ticker.get(key)
            if cur is None:
                by_ticker[key] = OfficialOutcome(
                    resolved_yes=ver.resolved_yes,
                    observed_at_ts=ver.observed_ts,
                    settlement_ts=ver.settlement_ts,
                    asset=(str(r.get("asset")).upper() if r.get("asset") else None),
                    versions=[ver],
                )
            else:
                cur.versions.append(ver)
                cur.resolved_yes = ver.resolved_yes
                cur.observed_at_ts = ver.observed_ts
                cur.settlement_ts = ver.settlement_ts
                if cur.asset is None and r.get("asset"):
                    cur.asset = str(r.get("asset")).upper()
    for o in by_ticker.values():
        o.versions.sort(key=lambda v: (v.observed_ts is None, v.observed_ts))
    return OfficialOutcomes(by_ticker, corrections, malformed)
