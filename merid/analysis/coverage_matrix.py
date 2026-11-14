"""Five-asset coverage matrix for the audit program.

Produces the per-asset x stage evidence table required by the audit
protocol: every requested asset must appear at every stage, with explicit
missingness — never silently omitted, never zero-filled.

Stages: market_discovery, boundary_resolution, reference_inputs,
book_reconstruction, current_code_decisions, execution_replay,
settlement_accounting, statistical_evaluation.

Read-only. CLI::

    py -3 -m merid.analysis.coverage_matrix --out reports/coverage_matrix_2026-11-14.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # repo root (merid/analysis/x.py)
ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
IDX = {"BTC": "BRTI", "ETH": "ETHUSD_RTI", "SOL": "SOLUSD_RTI",
       "XRP": "XRPUSD_RTI", "DOGE": "DOGEUSD_RTI"}


def _ro(p: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{REPO / p}?mode=ro", uri=True)


def _asset_of(ticker: str) -> str:
    for a in ASSETS:
        if ticker.startswith("KX" + a):
            return a
    return "?"


def _iter_jsonl(path: Path):
    if not path.exists():
        return
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def collect() -> dict:
    m = {a: {} for a in ASSETS}
    m["?"] = {}

    # --- boundary resolution ---
    bsrc, bver = Counter(), Counter()
    for r in _iter_jsonl(REPO / "data/contract_boundaries_v1.jsonl"):
        a = (r.get("asset") or "?").upper()
        if a in ASSETS or a == "?":
            bsrc[(a, r.get("boundary_source"))] += 1
            bver[(a, r.get("verification_status"))] += 1
    for a in ASSETS + ["?"]:
        m[a]["boundary"] = {
            "n_records": sum(v for (aa, _), v in bsrc.items() if aa == a),
            "by_source": {s: v for (aa, s), v in bsrc.items() if aa == a},
            "by_verification": {s: v for (aa, s), v in bver.items() if aa == a},
        }

    # --- settlement outcomes (market discovery + settlement) ---
    sout = Counter()
    for r in _iter_jsonl(REPO / "logs/settlement_outcomes.jsonl"):
        if r.get("event_type") == "settlement_outcome":
            a = (r.get("asset") or "?").upper()
            if a in ASSETS or a == "?":
                sout[a] += 1
    for a in ASSETS + ["?"]:
        m[a]["settlement_outcomes"] = sout[a]

    # --- fills ---
    try:
        conn = _ro("data/kalshi_fills.db")
        fall, flive = Counter(), Counter()
        for tk, live in conn.execute(
                "SELECT market_ticker, is_live FROM kalshi_fills "
                "WHERE fill_id NOT LIKE 'settlement:%'"):
            a = _asset_of(tk)
            if a not in m:
                continue
            fall[a] += 1
            if live:
                flive[a] += 1
        lm = Counter()
        for (tk,) in conn.execute(
                "SELECT DISTINCT market_ticker FROM kalshi_fills "
                "WHERE is_live=1 AND fill_id NOT LIKE 'settlement:%'"):
            lm[_asset_of(tk)] += 1
        conn.close()
        for a in ASSETS + ["?"]:
            m[a]["fills"] = {"all": fall[a], "live": flive[a],
                             "live_markets": lm[a]}
    except Exception as exc:  # noqa: BLE001
        for a in ASSETS + ["?"]:
            m[a]["fills"] = {"all": 0, "live": 0, "live_markets": 0,
                             "error": str(exc)}

    # --- RTI reference inputs ---
    try:
        conn = _ro("data/cf_rti_ticks.db")
        rti = {}
        for idx, mn, mx, n in conn.execute(
                "SELECT index_id, MIN(src_ts_ms), MAX(src_ts_ms), COUNT(*) "
                "FROM rti_ticks GROUP BY 1"):
            rti[idx] = (mn, mx, n)
        conn.close()
    except Exception as exc:  # noqa: BLE001
        rti = {}
        print("rti read error:", exc)
    try:
        conn = _ro("data/rti_backfill.db")
        bf = {r[0]: r[1] for r in conn.execute(
            "SELECT index_id, COUNT(*) FROM backfill_ticks GROUP BY 1")}
        conn.close()
    except Exception:
        bf = {}
    f = lambda ms: (datetime.fromtimestamp(ms / 1000, timezone.utc)
                    .strftime("%Y-%m-%d %H:%M") if ms else None)
    for a in ASSETS:
        idx = IDX[a]
        mn, mx, n = rti.get(idx, (None, None, 0))
        m[a]["reference_inputs"] = {
            "rti_live_index": idx,
            "live_ticks": n,
            "live_window_utc": [f(mn), f(mx)],
            "backfill_ticks": bf.get(idx, 0),
        }
    m["?"]["reference_inputs"] = {"rti_live_index": None, "live_ticks": 0,
                                  "live_window_utc": [None, None],
                                  "backfill_ticks": 0}

    # --- book reconstruction (archive DBs) ---
    book = Counter()
    for db in ("data/kalshi_book_archive.db",
               "data/kalshi_book_archive_live3.db",
               "data/kalshi_book_archive_active.db"):
        try:
            conn = _ro(db)
            tabs = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            if "archive_markets" in tabs:
                for (tk,) in conn.execute("SELECT ticker FROM archive_markets"):
                    book[_asset_of(tk)] += 1
            conn.close()
        except Exception:
            continue
    for a in ASSETS + ["?"]:
        m[a]["book_markets_approx"] = book[a]

    # --- decisions + audit units ---
    try:
        conn = _ro("data/_audit_hot/decision_audit.db")
        dec = Counter()
        for a2, n in conn.execute(
                "SELECT asset, COUNT(*) FROM strategy_decisions GROUP BY 1"):
            dec[a2.upper()] += n
        conn.close()
    except Exception:
        dec = Counter()
    aunits = Counter()
    for r in _iter_jsonl(REPO / "reports/pop_authoritative_2026-11-14.jsonl"):
        if r.get("record_type") == "unit":
            a = (r.get("asset") or "?").upper()
            if a in ASSETS:
                aunits[a] += 1
    for a in ASSETS + ["?"]:
        m[a]["decisions"] = {"decision_rows": dec[a], "audit_units": aunits[a]}

    # --- evaluability verdicts ---
    for a in ASSETS + ["?"]:
        e = m[a]
        stages = {
            "market_discovery": e["settlement_outcomes"] > 0,
            "boundary_resolution": e["boundary"]["n_records"] > 0,
            "reference_inputs": (e["reference_inputs"]["live_ticks"] > 0
                                 or e["reference_inputs"]["backfill_ticks"] > 0),
            "book_reconstruction": e["book_markets_approx"] > 0,
            "current_code_decisions": e["decisions"]["decision_rows"] > 0,
            "execution_replay": e["fills"]["live"] > 0,
            "settlement_accounting": e["settlement_outcomes"] > 0,
            "statistical_evaluation": e["decisions"]["audit_units"] > 0,
        }
        missing = [s for s, ok in stages.items() if not ok]
        e["stage_present"] = stages
        e["missing_stages"] = missing
        e["coverage_status"] = ("insufficient_coverage" if missing
                                else "covered")
    return {"generated_utc": datetime.now(timezone.utc).isoformat(),
            "assets": m}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    rep = collect()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    print(f"{'asset':5} {'status':22} {'missing':40} units fills_live outcomes")
    for a in ASSETS + ["?"]:
        e = rep["assets"][a]
        print(f"{a:5} {e['coverage_status']:22} "
              f"{','.join(e['missing_stages']) or '-':40} "
              f"{e['decisions']['audit_units']:>5} {e['fills']['live']:>9} "
              f"{e['settlement_outcomes']:>8}")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
