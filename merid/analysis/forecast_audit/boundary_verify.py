"""Verify ticker-parsed scheduled closes against venue metadata (P1 gate).

``forecast_event.scheduled_close_from_ticker`` parses the close datetime
embedded in a Kalshi 15m ticker name.  Until that parse is compared
against venue-supplied lifecycle fields it is reported as
``ticker_parsed_unverified`` — a string that looks like a datetime is not
evidence of its timezone or contractual meaning.

For each ticker this tool:
  * fetches ``GET /trade-api/v2/markets/{ticker}`` (public metadata),
  * preserves the RAW response with a fetch timestamp (a later metadata
    response must not silently rewrite what the scheduler saw),
  * compares the parsed time against ``expected_expiration_time``
    (contractual observation endpoint for the 15m series — see
    market_catalog.py: ticker inference is already the production-primary
    source for this series, close_time is the event/trading close),
    ``expiration_time``, and ``close_time``,
  * classifies: ``verified`` (a venue field matches within tolerance),
    ``disagreement`` (all fields differ beyond tolerance), or
    ``unreachable``.

Usage::

    python -m merid.analysis.forecast_audit.boundary_verify \\
        --tickers KXBTC15M-26OCT161445-45 ... --out reports/boundary_verify.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from merid.prediction.forecast_event import scheduled_close_from_ticker

_FIELDS = ("expected_expiration_time", "expiration_time", "close_time",
           "open_time", "latest_expiration_time")

# rules_primary phrase: "... the sixty seconds of CF Benchmarks' XRTI
# before 2:45 PM EDT on Oct 16, 2026 ..." — first occurrence is the
# CLOSING reference window end, second is the OPENING reference window
# end.  The stated wall time is ET; the sixty-second window precedes it.
_RULES_TIME_RE = None


def _rules_time_re():
    global _RULES_TIME_RE
    if _RULES_TIME_RE is None:
        import re
        _RULES_TIME_RE = re.compile(
            r"before\s+(\d{1,2}):(\d{2})\s*(AM|PM)\s+(E[DS]T)\s+on\s+"
            r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", re.IGNORECASE)
    return _RULES_TIME_RE


_MONTHS = {"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,"JUL":7,
           "AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}


def _parse_rules_windows(rules_primary: str) -> Dict[str, Any]:
    """Extract opening/closing reference-window boundaries from rules text.

    Returns window end timestamps (UTC epoch) parsed from the rules' own
    stated ET times, plus the exact supporting passages.  Never infers the
    window from API timestamp names — the rules text is the authority.
    """
    out: Dict[str, Any] = {"passages": [], "close_window_end_ts": None,
                           "open_window_end_ts": None}
    if not rules_primary:
        return out
    try:
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
    except Exception:
        return out
    from datetime import datetime, timezone
    matches = list(_rules_time_re().finditer(rules_primary))
    for i, m in enumerate(matches):
        hh, mm, ampm, _tz, mon_s, dd, yy = m.groups()
        mon = _MONTHS.get(mon_s[:3].upper())
        if mon is None:
            continue
        hour = int(hh) % 12 + (12 if ampm.upper() == "PM" else 0)
        try:
            dt = datetime(int(yy), mon, int(dd), hour, int(mm), tzinfo=et)
        except ValueError:
            continue
        span = rules_primary[max(0, m.start() - 120):m.end() + 10]
        out["passages"].append(span.strip())
        key = "close_window_end_ts" if i == 0 else "open_window_end_ts"
        if out.get(key) is None:
            out[key] = dt.astimezone(timezone.utc).timestamp()
    return out


def _iso_to_ts(v: Any) -> Optional[float]:
    if not v:
        return None
    s = str(v).replace("Z", "+00:00")
    try:
        from datetime import datetime
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def fetch_market(ticker: str, timeout_s: float = 10.0,
                 base: str = "https://external-api.kalshi.com/trade-api/v2",
                 ) -> Dict[str, Any]:
    """GET one market; return {"fetched_ts", "ticker", "raw"} or error."""
    url = f"{base}/markets/{ticker}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return {"fetched_ts": time.time(), "ticker": ticker,
                "raw": body.get("market") or body}
    except Exception as exc:
        return {"fetched_ts": time.time(), "ticker": ticker,
                "error": f"{type(exc).__name__}: {exc}"}


def verify_ticker(raw: Dict[str, Any], tolerance_s: float = 5.0) -> Dict[str, Any]:
    """Compare parsed ticker close against venue lifecycle fields."""
    ticker = raw.get("ticker")
    parsed = scheduled_close_from_ticker(ticker)
    out: Dict[str, Any] = {
        "ticker": ticker,
        "parsed_close_ts": parsed,
        "fetched_ts": raw.get("fetched_ts"),
        "status": "unparseable" if parsed is None else "unreachable",
    }
    if "error" in raw:
        out["error"] = raw["error"]
        return out
    m = raw.get("raw") or {}
    fields = {f: {"raw": m.get(f), "ts": _iso_to_ts(m.get(f))} for f in _FIELDS}
    out["venue_fields"] = fields

    # --- target definition (rules-backed, separate from field matching) ---
    rules_p = m.get("rules_primary") or ""
    rules_s = m.get("rules_secondary") or ""
    rw = _parse_rules_windows(rules_p)
    open_ts, close_ts = fields["open_time"]["ts"], fields["close_time"]["ts"]
    out["target_definition"] = {
        "trading_open_ts": open_ts,
        "trading_close_ts": close_ts,
        # The rules state "the sixty seconds of RTI before {T}" → the
        # reference window is [T-60, T).  Ends are parsed from the rules'
        # own stated ET times, never inferred from API field names.
        "opening_reference_window_start": (
            rw["open_window_end_ts"] - 60.0
            if rw["open_window_end_ts"] is not None else None),
        "opening_reference_window_end": rw["open_window_end_ts"],
        "closing_reference_window_start": (
            rw["close_window_end_ts"] - 60.0
            if rw["close_window_end_ts"] is not None else None),
        "closing_reference_window_end": rw["close_window_end_ts"],
        # expected_expiration_time is "when the outcome is expected to be
        # known" — outcome AVAILABILITY, not the observation endpoint.
        "expected_outcome_known_ts": fields["expected_expiration_time"]["ts"],
        "actual_outcome_observed_ts": _iso_to_ts(m.get("settlement_ts")),
        "settlement_ts": _iso_to_ts(m.get("settlement_ts")),
        "can_close_early": m.get("can_close_early"),
        "rules_source": "kalshi_api:market.rules_primary/rules_secondary",
        "rules_hash": __import__("hashlib").sha256(
            (rules_p + "|" + rules_s).encode()).hexdigest()[:16]
            if (rules_p or rules_s) else None,
        "rules_passages": rw["passages"],
    }
    if parsed is None:
        return out
    matches = {
        f: abs(v["ts"] - parsed) for f, v in fields.items()
        if v["ts"] is not None
    }
    out["field_deltas_s"] = matches
    hit = [f for f, d in matches.items() if d <= tolerance_s]
    td = out["target_definition"]
    rules_ok = (
        td["closing_reference_window_end"] is not None
        and close_ts is not None
        and abs(td["closing_reference_window_end"] - close_ts)
        <= tolerance_s
        and td["opening_reference_window_end"] is not None
        and open_ts is not None
        and abs(td["opening_reference_window_end"] - open_ts) <= tolerance_s
    )
    if hit and rules_ok:
        # Parsed ticker identifies the scheduled boundary; applicable rules
        # define the reference-index windows; expected_expiration describes
        # expected outcome availability only.
        out["status"] = "verified_rules_backed"
        out["matched_fields"] = hit
        out["boundary_verification_status"] = "verified_rules_backed"
    elif hit:
        out["status"] = "verified_timing_only"
        out["matched_fields"] = hit
        out["boundary_verification_status"] = "rules_unparsed_or_disagree"
    else:
        out["status"] = "disagreement"
        out["matched_fields"] = []
        out["boundary_verification_status"] = "quarantine"
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tickers", nargs="+", required=True)
    ap.add_argument("--events", default=None,
                    help="Forecast-event JSONL to derive tickers from.")
    ap.add_argument("--tolerance-s", type=float, default=5.0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--base",
                    default="https://external-api.kalshi.com/trade-api/v2")
    args = ap.parse_args(argv)

    tickers = list(args.tickers)
    if args.events:
        for line in Path(args.events).read_text().splitlines():
            try:
                t = json.loads(line).get("market_ticker")
            except Exception:
                continue
            if t and t not in tickers:
                tickers.append(t)

    results: List[Dict[str, Any]] = []
    for t in tickers:
        raw = fetch_market(t, base=args.base)
        res = verify_ticker(raw, args.tolerance_s)
        res["raw_response"] = raw.get("raw")  # preserved metadata version
        results.append(res)
    counts: Dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    report = {
        "generated_ts": time.time(),
        "tolerance_s": args.tolerance_s,
        "n_tickers": len(results),
        "status_counts": counts,
        "verified": bool(results) and all(
            r["status"] == "verified_rules_backed" for r in results),
        "results": results,
    }
    text = json.dumps(report, indent=2, default=str)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print(text if not args.out else f"wrote {args.out}: {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
