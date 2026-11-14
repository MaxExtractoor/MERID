"""Contract-boundary resolver for the forecast audit (P1a boundary fix).

Replaces the ledger's *reconstructed* ``close_ts``
(``decision_ts + seconds_to_expiry`` — drifts when decisions log after the
scheduled close) with an explicit, versioned, provenance-carrying boundary
record per ticker.

Boundary schema (per operator spec 2026-11-13)
---------------------------------------------
- ``contract_boundary_ts``: scheduled end of the contract's price-measurement
  interval.  For the KX*15M crypto series this equals venue ``close_time``
  (verified <1s on sampled tickers by ``boundary_verify``) and the
  ticker-embedded window end in America/New_York.
- ``trading_close_ts``: when orders cease to be eligible (venue ``close_time``;
  same instant for this series, kept separate because the concepts differ).
- ``determination_ts``: when the outcome is expected to be known
  (``expected_expiration_time`` — outcome *availability*, ~close+300s; NOT the
  observation endpoint and NOT ``expiration_time``/``latest_expiration_time``,
  which sit ~7 days out and are settlement deadlines).
- ``settlement_ts``: payout publication time (official outcomes export).
- ``metadata_observed_at``: when MERID captured the venue metadata used.
- ``boundary_source`` / ``boundary_version``: provenance + resolver version.

Trust order per ticker
----------------------
1. ``venue_metadata`` — ``archive_markets.raw_market`` captured at discovery
   (close_time + rules_primary reference windows + lifecycle fields).
2. ``ticker_parsed_et`` — ``parse_kalshi_15m_window_end_utc`` (canonical
   YYMONDDHHMM ET window end; DST-aware).  Verified against venue close_time
   on archive overlap + optional REST sample; carries its own verification
   status so unverified parses are never silently treated as venue facts.
3. ``ledger_reconstructed`` — last-resort fallback (median ledger close_ts),
   flagged untrusted; only when the ticker does not parse.

Official ``result`` outcomes remain the payout authority; a boundary
reconstruction mismatch is an investigation target, never a relabeling.

CLI::

    py -3 -m merid.analysis.forecast_audit.boundaries \
        --db data/decision_audit.db \
        --archive data/kalshi_book_archive.db \
        --archive data/kalshi_book_archive_active.db \
        --archive data/kalshi_book_archive_live2.db \
        --archive data/kalshi_book_archive_live3.db \
        --outcomes logs/settlement_outcomes.jsonl \
        --out data/contract_boundaries_v1.jsonl \
        --report reports/boundary_resolution_2026-11-13.json \
        --verify-rest-sample 150 --verify-rest-seed 20261113
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from merid.analysis.forecast_audit.records import asset_from_ticker

# Heavy imports are deferred to call time: ``expiry_fallback`` pulls in the
# venue base classes and ``boundary_verify`` pulls ``forecast_event`` — both
# drag the full merid config/strategy init chain.  The audit CLI must stay
# import-light like the rest of this package.


def _ticker_window_end_utc(ticker: str):
    from merid.ticker_time import parse_kalshi_15m_window_end_utc
    return parse_kalshi_15m_window_end_utc(ticker)


def _rules_windows(rules_primary: str):
    from merid.analysis.forecast_audit.rules_windows import (
        parse_rules_windows,
    )
    return parse_rules_windows(rules_primary)


def _fetch_market(ticker: str):
    from merid.analysis.forecast_audit.boundary_verify import fetch_market
    return fetch_market(ticker)


def _verify_ticker(raw: Dict[str, Any], tolerance_s: float):
    from merid.analysis.forecast_audit.boundary_verify import verify_ticker
    return verify_ticker(raw, tolerance_s)

BOUNDARY_SCHEMA_VERSION = 1
BOUNDARY_RESOLVER_VERSION = "boundary_resolver_v1"
DEFAULT_TOLERANCE_S = 5.0

# boundary_source values
SRC_VENUE_METADATA = "venue_metadata"          # archive_markets.raw_market
SRC_TICKER_PARSED = "ticker_parsed_et"         # canonical ticker window end
SRC_LEDGER_RECONSTRUCTED = "ledger_reconstructed"  # untrusted fallback
SRC_UNRESOLVED = "unresolved"

# verification_status values
VERIFIED_RULES_BACKED = "verified_rules_backed"
VERIFIED_TIMING_ONLY = "verified_timing_only"
VERIFIED_VENUE_FIELD = "verified_venue_field"  # venue close_time match, rules unparsed
TICKER_ONLY = "ticker_only"                    # parsed, no venue cross-check yet
TICKER_VS_VENUE_AGREE = "ticker_venue_agree"   # archive/REST field match w/o rules parse
DISAGREEMENT = "disagreement"
UNPARSEABLE = "unparseable"
RECONSTRUCTED_ONLY = "reconstructed_only"


@dataclass(slots=True)
class BoundaryRecord:
    """One ticker's resolved contract boundary (JSONL row)."""

    ticker: str
    asset: Optional[str]
    contract_boundary_ts: Optional[float] = None
    trading_close_ts: Optional[float] = None
    determination_ts: Optional[float] = None
    settlement_ts: Optional[float] = None
    open_ts: Optional[float] = None
    reference_window: Dict[str, Optional[float]] = field(default_factory=dict)
    boundary_source: str = SRC_UNRESOLVED
    boundary_version: str = BOUNDARY_RESOLVER_VERSION
    verification_status: str = UNPARSEABLE
    metadata_observed_at: Optional[float] = None
    rules_hash: Optional[str] = None
    venue_status: Optional[str] = None
    venue_exchange_index: Optional[int] = None
    field_deltas_s: Dict[str, float] = field(default_factory=dict)
    # Audit-convention ledger values: close_ts_last = close_ts of the latest
    # decision row (what the old probe used as the boundary); spread =
    # |last - first| decision-row close_ts drift flag.
    ledger_close_ts_last: Optional[float] = None
    ledger_close_spread_s: Optional[float] = None
    notes: List[str] = field(default_factory=list)

    def to_row(self) -> Dict[str, Any]:
        return {
            "schema_version": BOUNDARY_SCHEMA_VERSION,
            "boundary_version": self.boundary_version,
            "ticker": self.ticker,
            "asset": self.asset,
            "contract_boundary_ts": self.contract_boundary_ts,
            "trading_close_ts": self.trading_close_ts,
            "determination_ts": self.determination_ts,
            "settlement_ts": self.settlement_ts,
            "open_ts": self.open_ts,
            "reference_window": self.reference_window,
            "boundary_source": self.boundary_source,
            "verification_status": self.verification_status,
            "metadata_observed_at": self.metadata_observed_at,
            "rules_hash": self.rules_hash,
            "venue_status": self.venue_status,
            "venue_exchange_index": self.venue_exchange_index,
            "field_deltas_s": self.field_deltas_s,
            "ledger_close_ts_last": self.ledger_close_ts_last,
            "ledger_close_spread_s": self.ledger_close_spread_s,
            "notes": self.notes,
        }

    @staticmethod
    def from_row(row: Dict[str, Any]) -> "BoundaryRecord":
        return BoundaryRecord(
            ticker=row["ticker"],
            asset=row.get("asset"),
            contract_boundary_ts=row.get("contract_boundary_ts"),
            trading_close_ts=row.get("trading_close_ts"),
            determination_ts=row.get("determination_ts"),
            settlement_ts=row.get("settlement_ts"),
            open_ts=row.get("open_ts"),
            reference_window=dict(row.get("reference_window") or {}),
            boundary_source=row.get("boundary_source", SRC_UNRESOLVED),
            boundary_version=row.get("boundary_version", BOUNDARY_RESOLVER_VERSION),
            verification_status=row.get("verification_status", UNPARSEABLE),
            metadata_observed_at=row.get("metadata_observed_at"),
            rules_hash=row.get("rules_hash"),
            venue_status=row.get("venue_status"),
            venue_exchange_index=row.get("venue_exchange_index"),
            field_deltas_s=dict(row.get("field_deltas_s") or {}),
            ledger_close_ts_last=row.get("ledger_close_ts_last"),
            ledger_close_spread_s=row.get("ledger_close_spread_s"),
            notes=list(row.get("notes") or []),
        )


def load_boundaries(path: str | Path) -> Dict[str, BoundaryRecord]:
    """Load a boundaries JSONL sidecar -> {ticker: BoundaryRecord}."""
    out: Dict[str, BoundaryRecord] = {}
    p = Path(path)
    if not p.exists():
        return out
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            rec = BoundaryRecord.from_row(row)
            out[rec.ticker] = rec
    return out


# ---------------------------------------------------------------------------
# Universe discovery
# ---------------------------------------------------------------------------

def tickers_from_decision_db(db_path: str | Path) -> List[str]:
    """Distinct tickers in strategy_decisions (covering index scan)."""
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        rows = conn.execute(
            "SELECT DISTINCT ticker FROM strategy_decisions "
            "WHERE ticker != '' ORDER BY ticker"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def tickers_from_archive_dbs(paths: Sequence[str | Path]) -> Dict[str, Dict[str, Any]]:
    """{ticker: newest archive_markets row} across archive DBs.

    ``raw_market`` JSON is parsed lazily by the caller; here we keep the raw
    columns plus ``discovered_at_utc_ns`` for metadata_observed_at.
    """
    best: Dict[str, Dict[str, Any]] = {}
    for path in paths:
        p = Path(path)
        if not p.exists():
            continue
        uri = f"file:{p.as_posix()}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True)
        except sqlite3.Error:
            continue
        try:
            conn.row_factory = sqlite3.Row
            for r in conn.execute(
                "SELECT ticker, series, asset, status, open_ts, close_ts, "
                "expiration_ts, raw_market, discovered_at_utc_ns, "
                "execution_metadata_version "
                "FROM archive_markets"
            ):
                t = r["ticker"]
                prev = best.get(t)
                # Prefer the row with the latest discovery timestamp.
                if prev is None or (
                    (r["discovered_at_utc_ns"] or 0)
                    > (prev.get("discovered_at_utc_ns") or 0)
                ):
                    best[t] = dict(r)
        except sqlite3.Error:
            continue
        finally:
            conn.close()
    return best


def tickers_from_outcomes_jsonl(path: str | Path) -> Dict[str, Dict[str, Any]]:
    """{ticker: {settlement_ts, settlement_timestamp_utc, observed_at_ts}}."""
    out: Dict[str, Dict[str, Any]] = {}
    p = Path(path)
    if not p.exists():
        return out
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = row.get("ticker")
            if not t:
                continue
            settle_raw = row.get("settlement_timestamp_utc")
            settle_ts = None
            if settle_raw:
                try:
                    from datetime import datetime
                    settle_ts = datetime.fromisoformat(
                        str(settle_raw).replace("Z", "+00:00")
                    ).timestamp()
                except Exception:
                    settle_ts = None
            obs_raw = row.get("observed_at_utc")
            obs_ts = None
            if obs_raw:
                try:
                    from datetime import datetime
                    obs_ts = datetime.fromisoformat(
                        str(obs_raw).replace("Z", "+00:00")
                    ).timestamp()
                except Exception:
                    obs_ts = None
            # Corrections: keep the LATEST observed version's settlement ts.
            prev = out.get(t)
            if prev is None or (obs_ts or 0) >= (prev.get("observed_at_ts") or 0):
                out[t] = {
                    "settlement_ts": settle_ts,
                    "settlement_timestamp_utc": settle_raw,
                    "observed_at_ts": obs_ts,
                    "resolved_yes": row.get("resolved_yes"),
                }
    return out


# ---------------------------------------------------------------------------
# Per-ticker resolution
# ---------------------------------------------------------------------------

def _iso_to_ts(v: Any) -> Optional[float]:
    if not v:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _parse_archive_market(raw_market: str) -> Dict[str, Any]:
    try:
        return json.loads(raw_market)
    except Exception:
        return {}


def resolve_ticker(
    ticker: str,
    *,
    archive_row: Optional[Dict[str, Any]] = None,
    outcome: Optional[Dict[str, Any]] = None,
    ledger_median_close: Optional[float] = None,
    ledger_close_spread: Optional[float] = None,
    tolerance_s: float = DEFAULT_TOLERANCE_S,
) -> BoundaryRecord:
    """Resolve one ticker's boundary record (pure function — testable)."""
    rec = BoundaryRecord(
        ticker=ticker,
        asset=asset_from_ticker(ticker),
        settlement_ts=(outcome or {}).get("settlement_ts"),
        ledger_close_ts_last=ledger_median_close,
        ledger_close_spread_s=ledger_close_spread,
    )

    # --- candidate from ticker parse (always attempted) ---
    parsed_dt = _ticker_window_end_utc(ticker)
    parsed_ts = parsed_dt.timestamp() if parsed_dt is not None else None

    # --- venue metadata (archive) ---
    venue: Dict[str, Any] = {}
    venue_close_ts: Optional[float] = None
    archive_close_ts: Optional[float] = None
    if archive_row is not None:
        try:
            archive_close_ts = (
                float(archive_row["close_ts"])
                if archive_row.get("close_ts") is not None else None
            )
        except (TypeError, ValueError):
            archive_close_ts = None
    if archive_row is not None and archive_row.get("raw_market"):
        venue = _parse_archive_market(archive_row["raw_market"])
        venue_close_ts = _iso_to_ts(venue.get("close_time"))
        rec.trading_close_ts = venue_close_ts
        rec.determination_ts = _iso_to_ts(venue.get("expected_expiration_time"))
        rec.open_ts = _iso_to_ts(venue.get("open_time"))
        rec.venue_status = venue.get("status")
        try:
            rec.venue_exchange_index = int(venue.get("exchange_index"))
        except (TypeError, ValueError):
            rec.venue_exchange_index = None
        rules_p = venue.get("rules_primary") or ""
        rules_s = venue.get("rules_secondary") or ""
        if rules_p or rules_s:
            rec.rules_hash = hashlib.sha256(
                (rules_p + "|" + rules_s).encode()).hexdigest()[:16]
            rw = _rules_windows(rules_p)
            win_s = rw.get("window_seconds") or 60.0
            close_end = rw.get("close_window_end_ts")
            open_end = rw.get("open_window_end_ts")
            rec.reference_window = {
                "closing_reference_window_end": close_end,
                "opening_reference_window_end": open_end,
                "closing_reference_window_start": (
                    close_end - win_s if close_end is not None else None),
                "opening_reference_window_start": (
                    open_end - win_s if open_end is not None else None),
                "window_seconds": win_s,
            }
        disc_ns = archive_row.get("discovered_at_utc_ns")
        if disc_ns:
            rec.metadata_observed_at = float(disc_ns) / 1e9

    if venue_close_ts is not None:
        # Venue metadata is authoritative for the boundary itself.
        rec.contract_boundary_ts = venue_close_ts
        rec.boundary_source = SRC_VENUE_METADATA
        deltas: Dict[str, float] = {}
        if parsed_ts is not None:
            deltas["ticker_parse_minus_close_time"] = parsed_ts - venue_close_ts
        if rec.open_ts is not None:
            deltas["open_to_close_s"] = venue_close_ts - rec.open_ts
        if rec.determination_ts is not None:
            deltas["close_to_expected_expiration_s"] = (
                rec.determination_ts - venue_close_ts)
        rec.field_deltas_s = deltas

        rw_end = (rec.reference_window or {}).get("closing_reference_window_end")
        rules_ok = (
            rw_end is not None and rec.open_ts is not None
            and abs(rw_end - venue_close_ts) <= tolerance_s
            and abs(
                ((rec.reference_window or {}).get("opening_reference_window_end") or 0)
                - rec.open_ts) <= tolerance_s
        )
        if rules_ok:
            rec.verification_status = VERIFIED_RULES_BACKED
        elif parsed_ts is not None and abs(parsed_ts - venue_close_ts) <= tolerance_s:
            rec.verification_status = TICKER_VS_VENUE_AGREE
        else:
            rec.verification_status = DISAGREEMENT
            rec.notes.append(
                f"ticker parse delta {deltas.get('ticker_parse_minus_close_time')}s "
                f"vs venue close_time; rules_ok={rules_ok}")
        return rec

    # raw_market missing/unparseable but the archive row still carries the
    # collector-normalized close_ts — venue-sourced, weaker provenance.
    if venue_close_ts is None and archive_close_ts is not None:
        rec.contract_boundary_ts = archive_close_ts
        rec.trading_close_ts = archive_close_ts
        rec.boundary_source = SRC_VENUE_METADATA
        rec.verification_status = VERIFIED_VENUE_FIELD
        rec.notes.append("venue close_ts from archive_markets row "
                         "(raw_market unavailable)")
        if parsed_ts is not None:
            rec.field_deltas_s = {
                "ticker_parse_minus_archive_close_s": parsed_ts - archive_close_ts}
        return rec

    # --- ticker parse only ---
    if parsed_ts is not None:
        rec.contract_boundary_ts = parsed_ts
        rec.trading_close_ts = parsed_ts  # same instant for this series
        rec.boundary_source = SRC_TICKER_PARSED
        rec.verification_status = TICKER_ONLY
        return rec

    # --- ledger fallback (untrusted) ---
    if ledger_median_close is not None:
        rec.contract_boundary_ts = ledger_median_close
        rec.trading_close_ts = ledger_median_close
        rec.boundary_source = SRC_LEDGER_RECONSTRUCTED
        rec.verification_status = RECONSTRUCTED_ONLY
        rec.notes.append("ticker unparseable; boundary is reconstructed ledger value")
        return rec

    rec.boundary_source = SRC_UNRESOLVED
    rec.verification_status = UNPARSEABLE
    return rec


# ---------------------------------------------------------------------------
# REST spot-verification sample
# ---------------------------------------------------------------------------

def rest_verify_sample(
    records: Sequence[BoundaryRecord],
    *,
    n: int,
    seed: int,
    tolerance_s: float = DEFAULT_TOLERANCE_S,
    progress: bool = True,
) -> Dict[str, Any]:
    """Fetch venue metadata for a deterministic sample of tickers and compare
    the resolved boundary against venue ``close_time`` / rules windows.

    This is the broad parser-vs-venue agreement check for the
    ``ticker_parsed_et`` majority that has no archive coverage.  Returns a
    summary dict; per-ticker detail is merged into ``field_deltas_s`` notes
    on the records (verification_status upgraded to
    ``verified_venue_field``/``verified_rules_backed`` or flagged
    ``disagreement``).
    """
    if n <= 0:
        return {"requested": 0, "checked": 0}
    # Deterministic stratified sample: sort by ticker, step through evenly so
    # the sample spans the full date range rather than clustering.
    eligible = sorted(
        (r for r in records if r.boundary_source == SRC_TICKER_PARSED),
        key=lambda r: r.ticker,
    )
    if not eligible:
        return {"requested": n, "checked": 0, "note": "no ticker_parsed records"}
    step = max(1, len(eligible) // n)
    # Random start offset (seeded) + fixed stride: spans the full date range
    # deterministically without clustering on one period.
    rng = random.Random(seed)  # noqa: S311 - deterministic audit sampling
    start = rng.randrange(min(step, len(eligible)))
    sample = eligible[start::step][:n]

    counts: Dict[str, int] = {}
    details: List[Dict[str, Any]] = []
    for i, rec in enumerate(sample):
        if progress and i and i % 25 == 0:
            print(f"  rest-verify {i}/{len(sample)}", flush=True)
        raw = _fetch_market(rec.ticker)
        verdict = _verify_ticker(raw, tolerance_s)
        status = verdict.get("status", "unreachable")
        counts[status] = counts.get(status, 0) + 1
        td = verdict.get("target_definition") or {}
        close_ts = (td.get("trading_close_ts"))
        parsed = rec.contract_boundary_ts
        delta = (
            abs(close_ts - parsed)
            if close_ts is not None and parsed is not None else None
        )
        details.append({
            "ticker": rec.ticker,
            "status": status,
            "close_time_delta_s": delta,
            "matched_fields": verdict.get("matched_fields"),
        })
        # Upgrade the record's verification status from venue evidence.
        if status == "verified_rules_backed":
            rec.verification_status = VERIFIED_RULES_BACKED
            rec.boundary_source = SRC_VENUE_METADATA
            rec.metadata_observed_at = raw.get("fetched_ts")
            m = (raw.get("raw") or {})
            rec.determination_ts = _iso_to_ts(m.get("expected_expiration_time"))
            rec.open_ts = _iso_to_ts(m.get("open_time"))
            rec.venue_status = m.get("status")
            try:
                rec.venue_exchange_index = int(m.get("exchange_index"))
            except (TypeError, ValueError):
                pass
            rw = _rules_windows(m.get("rules_primary") or "")
            win_s = rw.get("window_seconds") or 60.0
            close_end = rw.get("close_window_end_ts")
            open_end = rw.get("open_window_end_ts")
            rec.reference_window = {
                "closing_reference_window_end": close_end,
                "opening_reference_window_end": open_end,
                "closing_reference_window_start": (
                    close_end - win_s if close_end is not None else None),
                "opening_reference_window_start": (
                    open_end - win_s if open_end is not None else None),
                "window_seconds": win_s,
            }
            rp = m.get("rules_primary") or ""
            rs = m.get("rules_secondary") or ""
            if rp or rs:
                rec.rules_hash = hashlib.sha256(
                    (rp + "|" + rs).encode()).hexdigest()[:16]
        elif status == "verified_timing_only":
            rec.verification_status = VERIFIED_VENUE_FIELD
            rec.metadata_observed_at = raw.get("fetched_ts")
        elif status == "disagreement":
            rec.verification_status = DISAGREEMENT
            rec.notes.append(
                f"REST verify disagreement: {verdict.get('field_deltas_s')}")
        # unreachable: leave TICKER_ONLY — absence of evidence, not disagreement
    return {
        "requested": n,
        "checked": len(sample),
        "status_counts": counts,
        "max_abs_close_delta_s": max(
            (d["close_time_delta_s"] for d in details
             if d["close_time_delta_s"] is not None), default=None),
        "details": details,
    }


# ---------------------------------------------------------------------------
# Ledger close_ts stats (drift measurement inputs)
# ---------------------------------------------------------------------------

def ledger_close_stats(db_path: str | Path, tickers: Sequence[str]) -> Dict[str, Tuple[Optional[float], Optional[float]]]:
    """{ticker: (close_ts_last, spread_s)} from strategy_decisions.

    Matches the audit probe's convention exactly: ``close_ts_last`` is the
    close_ts of the LATEST decision row (``ORDER BY decision_ts DESC LIMIT 1``)
    and spread is ``|last - first|`` over the same two extreme rows.  Two
    index seeks per ticker.
    """
    out: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
    if not tickers:
        return out
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        for tk in tickers:
            first = conn.execute(
                "SELECT close_ts FROM strategy_decisions WHERE ticker = ? "
                "ORDER BY decision_ts ASC LIMIT 1", (tk,)).fetchone()
            last = conn.execute(
                "SELECT close_ts FROM strategy_decisions WHERE ticker = ? "
                "ORDER BY decision_ts DESC LIMIT 1", (tk,)).fetchone()
            first_v = first[0] if first else None
            last_v = last[0] if last else None
            if last_v is None and first_v is None:
                out[tk] = (None, None)
                continue
            close_last = last_v if last_v is not None else first_v
            spread = (
                abs(float(last_v) - float(first_v))
                if last_v is not None and first_v is not None else 0.0
            )
            out[tk] = (float(close_last), float(spread))
    finally:
        conn.close()
    return out


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def resolve_boundaries(
    tickers: Sequence[str],
    *,
    archive_rows: Dict[str, Dict[str, Any]],
    outcomes: Dict[str, Dict[str, Any]],
    ledger_stats: Optional[Dict[str, Tuple[Optional[float], Optional[float]]]] = None,
    tolerance_s: float = DEFAULT_TOLERANCE_S,
) -> List[BoundaryRecord]:
    records: List[BoundaryRecord] = []
    for tk in tickers:
        ledger_last, spread = (ledger_stats or {}).get(tk, (None, None))
        records.append(resolve_ticker(
            tk,
            archive_row=archive_rows.get(tk),
            outcome=outcomes.get(tk),
            ledger_median_close=ledger_last,
            ledger_close_spread=spread,
            tolerance_s=tolerance_s,
        ))
    return records


def summarize(records: Sequence[BoundaryRecord]) -> Dict[str, Any]:
    by_source: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    by_asset: Dict[str, Dict[str, int]] = {}
    deltas: List[float] = []
    for r in records:
        by_source[r.boundary_source] = by_source.get(r.boundary_source, 0) + 1
        by_status[r.verification_status] = (
            by_status.get(r.verification_status, 0) + 1)
        a = r.asset or "UNKNOWN"
        by_asset.setdefault(a, {})
        by_asset[a][r.boundary_source] = by_asset[a].get(r.boundary_source, 0) + 1
        if (
            r.contract_boundary_ts is not None
            and r.ledger_close_ts_last is not None
        ):
            deltas.append(r.contract_boundary_ts - r.ledger_close_ts_last)
    import numpy as np
    dsum: Dict[str, Any] = {"n": len(deltas)}
    if deltas:
        arr = np.asarray(deltas)
        dsum.update({
            "mean": float(arr.mean()),
            "p50": float(np.percentile(arr, 50)),
            "p90": float(np.percentile(arr, 90)),
            "p99": float(np.percentile(arr, 99)),
            "min": float(arr.min()),
            "max": float(arr.max()),
            "abs_gt_5s": int((np.abs(arr) > 5).sum()),
            "abs_gt_30s": int((np.abs(arr) > 30).sum()),
            "abs_gt_300s": int((np.abs(arr) > 300).sum()),
        })
    return {
        "n_tickers": len(records),
        "by_source": by_source,
        "by_verification_status": by_status,
        "by_asset_source": by_asset,
        "boundary_minus_ledger_close_s": dsum,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="data/decision_audit.db",
                    help="decision audit DB for ticker universe + ledger stats")
    ap.add_argument("--archive", action="append", default=[],
                    help="book-archive DB path (repeatable)")
    ap.add_argument("--outcomes", default="logs/settlement_outcomes.jsonl")
    ap.add_argument("--out", required=True, help="boundaries JSONL output")
    ap.add_argument("--report", default=None, help="summary JSON output")
    ap.add_argument("--tickers-file", default=None,
                    help="optional file with one ticker per line (overrides DB universe)")
    ap.add_argument("--no-ledger-stats", action="store_true",
                    help="skip per-ticker ledger close probes (faster; "
                         "ledger drift fields left null)")
    ap.add_argument("--verify-rest-sample", type=int, default=0,
                    help="N ticker_parsed records to verify against live "
                         "Kalshi REST (deterministic sample)")
    ap.add_argument("--verify-rest-seed", type=int, default=20261113)
    ap.add_argument("--tolerance-s", type=float, default=DEFAULT_TOLERANCE_S)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    t0 = time.time()
    if args.tickers_file:
        tickers = [
            ln.strip() for ln in Path(args.tickers_file).read_text().splitlines()
            if ln.strip()
        ]
    else:
        tickers = tickers_from_decision_db(args.db)
    if not args.quiet:
        print(f"[boundaries] universe: {len(tickers)} tickers", flush=True)

    archive_rows = tickers_from_archive_dbs(args.archive)
    outcomes = tickers_from_outcomes_jsonl(args.outcomes)
    # Union the universe with archive/outcomes tickers: boundaries are cheap
    # per-ticker resolutions and extra coverage helps downstream settlement
    # work; ledger stats simply miss for tickers absent from the audit DB.
    extra = (set(archive_rows) | set(outcomes)) - set(tickers)
    if extra:
        tickers = sorted(set(tickers) | extra)
    if not args.quiet:
        print(f"[boundaries] archive markets: {len(archive_rows)}, "
              f"outcomes: {len(outcomes)}, universe+{len(extra)} "
              f"-> {len(tickers)}", flush=True)

    ledger_stats = (
        None if args.no_ledger_stats
        else ledger_close_stats(args.db, tickers)
    )
    if not args.quiet and ledger_stats is not None:
        print(f"[boundaries] ledger close stats done "
              f"({time.time()-t0:.0f}s)", flush=True)

    records = resolve_boundaries(
        tickers,
        archive_rows=archive_rows,
        outcomes=outcomes,
        ledger_stats=ledger_stats,
        tolerance_s=args.tolerance_s,
    )

    rest_summary: Optional[Dict[str, Any]] = None
    if args.verify_rest_sample > 0:
        if not args.quiet:
            print(f"[boundaries] REST-verifying sample of "
                  f"{args.verify_rest_sample} ...", flush=True)
        rest_summary = rest_verify_sample(
            records, n=args.verify_rest_sample, seed=args.verify_rest_seed,
            tolerance_s=args.tolerance_s, progress=not args.quiet)
        if not args.quiet:
            print(f"[boundaries] REST verify: {rest_summary['status_counts']}",
                  flush=True)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r.to_row(), default=str) + "\n")

    summary = summarize(records)
    summary.update({
        "generated_ts": time.time(),
        "resolver_version": BOUNDARY_RESOLVER_VERSION,
        "schema_version": BOUNDARY_SCHEMA_VERSION,
        "inputs": {
            "db": args.db,
            "archive_dbs": list(args.archive),
            "outcomes": args.outcomes,
            "tickers_file": args.tickers_file,
            "ledger_stats": not args.no_ledger_stats,
        },
        "parameters": {
            "tolerance_s": args.tolerance_s,
            "rest_verify_sample": args.verify_rest_sample,
            "rest_verify_seed": args.verify_rest_seed,
        },
        "rest_verify": (
            {k: v for k, v in rest_summary.items() if k != "details"}
            if rest_summary else None
        ),
        "elapsed_s": time.time() - t0,
    })
    if args.report:
        rp = Path(args.report)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(summary, indent=2, default=str),
                      encoding="utf-8")
    if not args.quiet:
        print(json.dumps({k: summary[k] for k in
                          ("n_tickers", "by_source", "by_verification_status",
                           "boundary_minus_ledger_close_s")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
