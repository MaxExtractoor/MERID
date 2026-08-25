"""Standalone, idempotent settlement-outcome exporter for 15m crypto markets.

Writes durable per-ticker settlement outcomes to ``logs/settlement_outcomes.jsonl``
so the offline calibration report (``merid.analysis.calibration_report``) can
compute settlement calibration, Brier scores, and fee-inclusive expectancy.

Design constraints (2026-08-17):
- STANDALONE: never imports or shares state with the live trading loop, order
  router, fills ledger, position monitor, or exit logic. The only reused
  component is the Kalshi API client configuration/response normalization.
- READ-ONLY with respect to the exchange: GET requests only.
- IDEMPOTENT: re-running over the same window appends zero duplicate outcome
  rows. A conflicting newly-observed outcome appends an explicit
  ``settlement_correction`` event instead of rewriting history.
- DRY-RUN by default; ``--write`` is required to mutate the output file.
- Outcomes are NEVER inferred from price, P&L, close time, or title. Only a
  definitive exchange ``result`` of ``yes``/``no`` on a ``settled`` market is
  exported.

CLI:
    python -m merid.analysis.settlement_outcome_exporter \
        --out logs/settlement_outcomes.jsonl --lookback-hours 72          # dry run
    python -m merid.analysis.settlement_outcome_exporter --write          # append
    python -m merid.analysis.settlement_outcome_exporter --write \
        --start 2026-08-01T00:00:00Z --end 2026-08-17T00:00:00Z           # backfill
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

EXPORTER_SCHEMA_VERSION = 1

SUPPORTED_SERIES: Tuple[str, ...] = (
    "KXBTC15M",
    "KXETH15M",
    "KXSOL15M",
    "KXXRP15M",
    "KXDOGE15M",
)

SERIES_TO_ASSET: Dict[str, str] = {
    "KXBTC15M": "BTC",
    "KXETH15M": "ETH",
    "KXSOL15M": "SOL",
    "KXXRP15M": "XRP",
    "KXDOGE15M": "DOGE",
}

DEFAULT_OUT_PATH = "logs/settlement_outcomes.jsonl"
DEFAULT_RUN_LOG_PATH = "logs/settlement_outcome_exporter_runs.jsonl"
DEFAULT_LOOKBACK_HOURS = 72
PAGE_LIMIT = 200
MAX_PAGES_PER_SERIES = 50  # hard bound: 10k markets per series per run


@dataclass
class OutcomeEvent:
    """A definitive settlement outcome for one market ticker."""

    ticker: str
    series_ticker: str
    asset: str
    outcome: str  # "yes" | "no"
    resolved_yes: int  # 1 | 0
    settlement_timestamp_utc: Optional[str]

    def to_row(self, observed_at_utc: str, export_run_id: str) -> Dict[str, Any]:
        return {
            "schema_version": EXPORTER_SCHEMA_VERSION,
            "event_type": "settlement_outcome",
            "observed_at_utc": observed_at_utc,
            "ticker": self.ticker,
            "series_ticker": self.series_ticker,
            "asset": self.asset,
            "outcome": self.outcome,
            "resolved_yes": self.resolved_yes,
            "settlement_source": "kalshi_rest",
            "settlement_timestamp_utc": self.settlement_timestamp_utc,
            "export_run_id": export_run_id,
        }


@dataclass
class ExportSummary:
    fetched: int = 0
    eligible_15m_crypto: int = 0
    definitive: int = 0
    appended: int = 0
    duplicates_skipped: int = 0
    ambiguous_skipped: int = 0
    corrections: int = 0
    api_errors: int = 0
    malformed_existing_rows: int = 0
    dry_run: bool = True
    export_run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


# ---------------------------------------------------------------------------
# Normalization (strict; never infers outcome)
# ---------------------------------------------------------------------------

def normalize_market_record(raw: Dict[str, Any]) -> Optional[OutcomeEvent]:
    """Normalize a raw /markets item into a definitive OutcomeEvent.

    Returns None unless the market is settled with an unambiguous yes/no
    result. Open, pending, voided, canceled, or ambiguous markets return None.
    """
    if not isinstance(raw, dict):
        return None
    status = str(raw.get("status") or "").strip().lower()
    # Kalshi reports settled 15m crypto markets as "finalized" when queried
    # with status=settled; both terminal states are accepted.
    if status not in ("settled", "finalized"):
        return None
    result = str(raw.get("result") or "").strip().lower()
    if result not in ("yes", "no"):
        return None
    ticker = str(raw.get("ticker") or "").strip().upper()
    if not ticker:
        return None
    series = str(raw.get("series_ticker") or ticker.split("-")[0]).strip().upper()
    if series not in SUPPORTED_SERIES:
        return None
    settle_ts = raw.get("settlement_time") or raw.get("close_time") or raw.get("expiration_time")
    return OutcomeEvent(
        ticker=ticker,
        series_ticker=series,
        asset=SERIES_TO_ASSET[series],
        outcome=result,
        resolved_yes=1 if result == "yes" else 0,
        settlement_timestamp_utc=str(settle_ts) if settle_ts else None,
    )


def _parse_ts_seconds(value: Any) -> Optional[float]:
    """Parse an ISO-8601 string or unix-seconds number into epoch seconds."""
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
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def _to_iso(value: Any) -> Optional[str]:
    ts = _parse_ts_seconds(value)
    return value if ts is not None else None


def market_within_window(raw: Dict[str, Any], start_ts: float, end_ts: float) -> Optional[bool]:
    """Client-side window check on close/expiration/settlement time.

    Returns True/False when a usable timestamp exists, None when the market
    carries no parseable timestamp (caller decides policy). The Kalshi
    /markets time filters are not trusted alone for bounded backfills.
    """
    if not isinstance(raw, dict):
        return None
    ts = None
    for key in ("close_time", "expiration_time", "settlement_time"):
        ts = _parse_ts_seconds(raw.get(key))
        if ts is not None:
            break
    if ts is None:
        return None
    return start_ts <= ts <= end_ts


def event_series_and_eligibility(raw: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Return (is_supported_15m_crypto, series) for summary accounting."""
    if not isinstance(raw, dict):
        return False, None
    ticker = str(raw.get("ticker") or "").strip().upper()
    series = str(raw.get("series_ticker") or (ticker.split("-")[0] if ticker else "")).strip().upper()
    return (series in SUPPORTED_SERIES), series or None


# ---------------------------------------------------------------------------
# Existing-history loading (deterministic latest-event-wins)
# ---------------------------------------------------------------------------

def load_existing_outcomes(path: str | Path) -> Tuple[Dict[str, Dict[str, Any]], int]:
    """Load the outcome history file, keyed by normalized ticker.

    Latest valid event wins (file order is append order). Malformed rows are
    skipped and counted. Returns (ticker -> latest row, malformed_count).
    """
    latest: Dict[str, Dict[str, Any]] = {}
    malformed = 0
    p = Path(path)
    if not p.exists():
        return latest, malformed
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if not isinstance(row, dict):
                malformed += 1
                continue
            ticker = row.get("ticker")
            outcome = row.get("outcome")
            if not ticker or str(outcome).lower() not in ("yes", "no"):
                malformed += 1
                continue
            latest[str(ticker).strip().upper()] = row
    return latest, malformed


# ---------------------------------------------------------------------------
# Fetching (Kalshi /markets, cursor pagination, bounded)
# ---------------------------------------------------------------------------

async def _client_get(client: Any, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Call the Kalshi client using the same request surface as the
    settlement poller (_request_with_resilience -> request -> _request)."""
    if hasattr(client, "_request_with_resilience"):
        result = await asyncio.wait_for(
            client._request_with_resilience(
                "GET", endpoint, params=params, operation_name="settlement_outcome_export"
            ),
            timeout=30.0,
        )
        if getattr(result, "success", False):
            return result.data or {}
        raise RuntimeError(f"Kalshi API request failed: {getattr(result, 'error', 'unknown')}")
    if hasattr(client, "request"):
        return await asyncio.wait_for(client.request("GET", endpoint, params=params), timeout=30.0)
    if hasattr(client, "_request"):
        return await asyncio.wait_for(client._request("GET", endpoint, params=params), timeout=30.0)
    raise AttributeError(
        f"{type(client).__name__!r} has no known request method "
        f"(tried: _request_with_resilience, request, _request)"
    )


async def fetch_settled_markets(
    client: Any,
    series: str,
    start_ts: float,
    end_ts: float,
    limit: int = PAGE_LIMIT,
) -> Tuple[List[Dict[str, Any]], int]:
    """Fetch settled markets for one series with cursor pagination.

    Window bounds are unix seconds (Kalshi /markets min_close_ts/max_close_ts
    convention). Returns (raw_market_items, api_error_count). On API error
    the partial page is NOT returned; items from earlier successful pages are
    returned alongside the error count so the caller can abort the write.
    """
    items: List[Dict[str, Any]] = []
    errors = 0
    cursor: Optional[str] = None
    for _ in range(MAX_PAGES_PER_SERIES):
        params: Dict[str, Any] = {
            "series_ticker": series,
            "status": "settled",
            "min_close_ts": int(start_ts),
            "max_close_ts": int(end_ts),
            "limit": limit,
        }
        if cursor:
            params["cursor"] = cursor
        response = None
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            try:
                response = await _client_get(client, "/markets", params)
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                if attempt < 2:
                    await asyncio.sleep(2.0 * (attempt + 1))
        if last_exc is not None:
            logger.error("[SETTLEMENT-EXPORTER] API error fetching %s: %s", series, last_exc)
            errors += 1
            break
        page = response.get("markets") or []
        items.extend(page)
        cursor = response.get("cursor") or None
        if not cursor or not page:
            break
    return items, errors


# ---------------------------------------------------------------------------
# Export pipeline
# ---------------------------------------------------------------------------

def plan_appends(
    events: List[OutcomeEvent],
    existing: Dict[str, Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], ExportSummary]:
    """Decide which rows to append. Pure function (no I/O).

    - Same ticker + same outcome -> duplicate, skipped.
    - Same ticker + conflicting outcome -> settlement_correction event.
    - New ticker -> settlement_outcome row.
    """
    rows: List[Dict[str, Any]] = []
    summary = ExportSummary()
    observed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    run_id = summary.export_run_id
    for event in events:
        prior = existing.get(event.ticker)
        if prior is None:
            rows.append(event.to_row(observed_at, run_id))
            summary.appended += 1
            continue
        prior_outcome = str(prior.get("outcome", "")).lower()
        if prior_outcome == event.outcome:
            summary.duplicates_skipped += 1
            continue
        rows.append({
            "schema_version": EXPORTER_SCHEMA_VERSION,
            "event_type": "settlement_correction",
            "observed_at_utc": observed_at,
            "ticker": event.ticker,
            "prior_outcome": prior_outcome,
            "outcome": event.outcome,
            "resolved_yes": event.resolved_yes,
            "settlement_source": "kalshi_rest",
            "settlement_timestamp_utc": event.settlement_timestamp_utc,
            "export_run_id": run_id,
        })
        summary.corrections += 1
    return rows, summary


def append_rows(path: str | Path, rows: List[Dict[str, Any]]) -> None:
    """Append rows with flush+fsync. Never rewrites existing history."""
    if not rows:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


async def run_export(
    *,
    out_path: str | Path,
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    start_iso: Optional[str] = None,
    end_iso: Optional[str] = None,
    series_filter: Optional[List[str]] = None,
    limit: int = PAGE_LIMIT,
    write: bool = False,
    client: Any = None,
    verbose: bool = False,
    run_log_path: Optional[str | Path] = DEFAULT_RUN_LOG_PATH,
) -> Tuple[ExportSummary, int]:
    """Run one export. Returns (summary, exit_code).

    Exit code is nonzero on any API error; no rows are written in that case.
    """
    started_at = datetime.now(timezone.utc)
    now = started_at
    end_ts = _parse_ts_seconds(end_iso) if end_iso else now.timestamp()
    start_ts = (_parse_ts_seconds(start_iso) if start_iso
                else (now - timedelta(hours=lookback_hours)).timestamp())
    if end_ts is None or start_ts is None:
        logger.error("[SETTLEMENT-EXPORTER] unparseable start/end timestamp")
        return ExportSummary(dry_run=not write), 2

    series_list = [s.upper() for s in (series_filter or SUPPORTED_SERIES)]
    summary = ExportSummary(dry_run=not write)
    exit_status = 0

    # Phase 1: fetch everything. Any API error aborts before any write.
    owns_client = client is None
    if client is None:
        from merid.event_venues.kalshi.client import KalshiVenueClient
        client = KalshiVenueClient()
    raw_items: List[Dict[str, Any]] = []
    try:
        for series in series_list:
            items, errors = await fetch_settled_markets(client, series, start_ts, end_ts, limit)
            summary.fetched += len(items)
            summary.api_errors += errors
            raw_items.extend(items)
            if verbose:
                logger.info("[SETTLEMENT-EXPORTER] series=%s fetched=%d errors=%d",
                            series, len(items), errors)
    finally:
        if owns_client:
            try:
                close = getattr(client, "close", None)
                if close is not None:
                    maybe = close()
                    if asyncio.iscoroutine(maybe):
                        await maybe
            except Exception:
                pass

    if summary.api_errors > 0:
        logger.error("[SETTLEMENT-EXPORTER] %d API error(s); aborting without writes", summary.api_errors)
        exit_status = 1
        _write_run_log(run_log_path, summary, started_at, lookback_hours, exit_status,
                       start_ts, end_ts)
        return summary, exit_status

    # Phase 2: client-side window filter + normalize. The API time filters
    # are not trusted alone for bounded backfills; items without a parseable
    # timestamp are excluded rather than silently admitted.
    events: List[OutcomeEvent] = []
    for raw in raw_items:
        eligible, _series = event_series_and_eligibility(raw)
        if not eligible:
            continue
        if market_within_window(raw, start_ts, end_ts) is not True:
            summary.ambiguous_skipped += 1
            continue
        summary.eligible_15m_crypto += 1
        event = normalize_market_record(raw)
        if event is None:
            summary.ambiguous_skipped += 1
            continue
        summary.definitive += 1
        events.append(event)

    # Within-run dedupe: identical tickers across pages collapse to one event.
    seen_tickers = set()
    unique_events: List[OutcomeEvent] = []
    for event in events:
        if event.ticker in seen_tickers:
            continue
        seen_tickers.add(event.ticker)
        unique_events.append(event)
    events = unique_events

    # Phase 3: dedupe against existing history.
    existing, malformed = load_existing_outcomes(out_path)
    summary.malformed_existing_rows = malformed
    planned, plan_summary = plan_appends(events, existing)
    summary.appended = plan_summary.appended
    summary.duplicates_skipped = plan_summary.duplicates_skipped
    summary.corrections = plan_summary.corrections
    summary.export_run_id = plan_summary.export_run_id

    # Phase 4: write (only with --write).
    if write and planned:
        append_rows(out_path, planned)
    elif planned and not write:
        logger.info("[SETTLEMENT-EXPORTER] dry-run: %d row(s) would be appended; pass --write", len(planned))

    logger.info("[SETTLEMENT-EXPORTER-SUMMARY] %s", json.dumps(summary.as_dict(), default=str))
    _write_run_log(run_log_path, summary, started_at, lookback_hours, exit_status,
                   start_ts, end_ts)
    return summary, exit_status


def _write_run_log(
    run_log_path: Optional[str | Path],
    summary: ExportSummary,
    started_at: datetime,
    lookback_hours: int,
    exit_status: int,
    start_ts: float,
    end_ts: float,
) -> None:
    """Append a machine-readable exporter health record. Non-fatal."""
    if not run_log_path:
        return
    record = {
        "type": "exporter_run",
        "schema_version": EXPORTER_SCHEMA_VERSION,
        "export_run_id": summary.export_run_id,
        "started_at_utc": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "lookback_hours": lookback_hours,
        "window_start_utc": datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        "window_end_utc": datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        **{k: v for k, v in summary.as_dict().items() if k != "export_run_id"},
        "exit_status": exit_status,
    }
    try:
        append_rows(run_log_path, [record])
    except Exception as exc:
        logger.warning("[SETTLEMENT-EXPORTER] run-log write failed (non-fatal): %s", exc)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Export durable settlement outcomes for 15m crypto markets")
    parser.add_argument("--out", default=DEFAULT_OUT_PATH, help="Output JSONL path")
    parser.add_argument("--lookback-hours", type=int, default=DEFAULT_LOOKBACK_HOURS)
    parser.add_argument("--start", default=None, help="Backfill window start (ISO 8601)")
    parser.add_argument("--end", default=None, help="Backfill window end (ISO 8601)")
    parser.add_argument("--series", nargs="*", default=None,
                        help="Restrict to specific series tickers")
    parser.add_argument("--limit", type=int, default=PAGE_LIMIT, help="API page size")
    parser.add_argument("--write", action="store_true", help="Actually append (default: dry-run)")
    parser.add_argument("--run-log", default=DEFAULT_RUN_LOG_PATH,
                        help="Exporter health run-log JSONL path ('' to disable)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    # httpx request/response DEBUG noise is never needed for operations.
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.INFO)

    summary, rc = asyncio.run(run_export(
        out_path=args.out,
        lookback_hours=args.lookback_hours,
        start_iso=args.start,
        end_iso=args.end,
        series_filter=args.series,
        limit=args.limit,
        write=args.write,
        verbose=args.verbose,
        run_log_path=args.run_log or None,
    ))
    print(json.dumps(summary.as_dict(), default=str))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
