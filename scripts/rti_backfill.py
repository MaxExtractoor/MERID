"""CF Benchmarks RTI historical backfill via Kalshi REST passthrough.

Fetches tick-level index history from
``GET /trade-api/v2/cfbenchmarks/history/values`` (forwards to
``cfbenchmarks.com/api/v1/history/values``) using standard Kalshi RSA
request signing.  Each request costs 50 read tokens upstream; the script
self-throttles (default 3 req/s < 4/s sustained budget).

Provenance discipline (per audit requirements):
  * Backfilled ticks go to a SEPARATE database (``data/rti_backfill.db``),
    never mixed into ``cf_rti_ticks`` live captures.
  * Every stored tick records ``retrieved_at_ms`` and the exact request
    parameters; ``src_ts_ms`` is CF's own tick timestamp.
  * Historical data validates settlement reconstruction; it must NOT be
    presented as information the live strategy possessed at decision time.

Window semantics (verified 2026-11-14): ``timespan=HOUR&timestamp=T``
returns ticks in ``[T, T+3600s)`` at ~5Hz for the 15m crypto indices.
``timestamp`` must be truncated to the timespan granularity.

CLI::

    py -3 scripts/rti_backfill.py --scope live --rate 3
    py -3 scripts/rti_backfill.py --scope sample --per-asset-day 2 --rate 3
    py -3 scripts/rti_backfill.py --scope incident --rate 3
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

INDEX_BY_ASSET = {
    "BTC": "BRTI", "ETH": "ETHUSD_RTI", "SOL": "SOLUSD_RTI",
    "XRP": "XRPUSD_RTI", "DOGE": "DOGEUSD_RTI",
}
ASSET_BY_INDEX = {v: k for k, v in INDEX_BY_ASSET.items()}

PASSTHROUGH_PATH = "/trade-api/v2/cfbenchmarks/history/values"
BASE_URL = "https://external-api.kalshi.com"
TIMESPAN_S = 3600
PAD_S = 75  # cover open-window start (close-900-60) with margin

SCHEMA = """
CREATE TABLE IF NOT EXISTS backfill_requests (
    req_id INTEGER PRIMARY KEY AUTOINCREMENT,
    index_id TEXT NOT NULL,
    req_timestamp TEXT NOT NULL,
    timespan TEXT NOT NULL,
    retrieved_at_ms INTEGER NOT NULL,
    http_status INTEGER,
    n_ticks INTEGER,
    bytes INTEGER,
    error TEXT,
    UNIQUE(index_id, req_timestamp)
);
CREATE TABLE IF NOT EXISTS backfill_ticks (
    index_id TEXT NOT NULL,
    src_ts_ms INTEGER NOT NULL,
    value TEXT NOT NULL,
    req_timestamp TEXT NOT NULL,
    retrieved_at_ms INTEGER NOT NULL,
    UNIQUE(index_id, src_ts_ms, req_timestamp)
);
CREATE INDEX IF NOT EXISTS idx_bt_idx_ts ON backfill_ticks(index_id, src_ts_ms);
"""


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO / ".env")
    except Exception:
        pass


def _signer():
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    key_path = os.environ["KALSHI_PRIVATE_KEY_PATH"]
    api_key = os.environ["KALSHI_API_KEY_ID"]
    key = serialization.load_pem_private_key(
        Path(key_path).read_bytes(), password=None)

    def sign(method: str, path: str) -> dict:
        ts = str(int(time.time() * 1000))
        msg = ts + method.upper() + path.split("?")[0]
        sig = key.sign(
            msg.encode(),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256())
        return {
            "KALSHI-ACCESS-KEY": api_key,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
        }
    return sign


def _hour_floor(ts_s: float) -> str:
    dt = datetime.fromtimestamp(ts_s, timezone.utc)
    dt = dt.replace(minute=0, second=0, microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _hours_needed(t0_s: float, t1_s: float) -> list[str]:
    """All hour-aligned request timestamps covering [t0, t1]."""
    out = []
    cur = int(t0_s // TIMESPAN_S) * TIMESPAN_S
    while cur <= t1_s:
        out.append(_hour_floor(float(cur)))
        cur += TIMESPAN_S
    return out


def _iso_to_ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def collect_targets(scope: str, args) -> dict[str, set[str]]:
    """Return {index_id: {hour_timestamp,...}} needed for the scope."""
    needed: dict[str, set[str]] = {idx: set() for idx in INDEX_BY_ASSET.values()}

    def add_contract(asset: str, open_ts: float, close_ts: float):
        idx = INDEX_BY_ASSET.get(asset.upper())
        if not idx:
            return
        for h in _hours_needed(open_ts - PAD_S, close_ts):
            needed[idx].add(h)

    if scope in ("live", "all", "incident"):
        # live-traded contracts: windows from boundary sidecar
        bp = REPO / "data" / "contract_boundaries_v1.jsonl"
        fills_db = REPO / "data" / "kalshi_fills.db"
        live_tickers = set()
        if fills_db.exists():
            c = sqlite3.connect(f"file:{fills_db}?mode=ro", uri=True)
            live_tickers = {r[0] for r in c.execute(
                "SELECT DISTINCT market_ticker FROM kalshi_fills "
                "WHERE is_live=1")}
            c.close()
        n = 0
        for line in bp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            tk = rec.get("ticker")
            if scope == "incident":
                if tk != "KXXRP15M-26NOV130630-30":
                    continue
            elif tk not in live_tickers:
                continue
            op, cl = rec.get("open_ts"), rec.get("contract_boundary_ts")
            asset = (rec.get("asset") or "").upper()
            if cl and asset in INDEX_BY_ASSET:
                # ticker_parsed records lack open_ts; 15m window => open=close-900
                op = float(op) if op else float(cl) - 900.0
                add_contract(asset, op, float(cl))
                n += 1
        print(f"[{scope}] contracts mapped: {n}")

    if scope in ("sample", "all"):
        # stratified sample: settled outcomes, per asset per UTC day
        outcomes = REPO / "logs" / "settlement_outcomes.jsonl"
        bp = REPO / "data" / "contract_boundaries_v1.jsonl"
        bounds = {}
        for line in bp.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("ticker") and rec.get("contract_boundary_ts"):
                bounds[rec["ticker"]] = rec
        per_asset_day: dict[tuple, list] = {}
        seen = set()
        for line in outcomes.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("event_type") != "settlement_outcome":
                continue
            tk = rec.get("ticker")
            if not tk or tk in seen or tk not in bounds:
                continue
            seen.add(tk)
            b = bounds[tk]
            asset = (b.get("asset") or rec.get("asset") or "").upper()
            if asset not in INDEX_BY_ASSET:
                continue
            close = float(b["contract_boundary_ts"])
            op = float(b.get("open_ts") or close - 900)
            day = datetime.fromtimestamp(close, timezone.utc).strftime("%Y-%m-%d")
            per_asset_day.setdefault((asset, day), []).append((op, close))
        k = args.per_asset_day
        total = 0
        for (asset, day), lst in sorted(per_asset_day.items()):
            lst.sort()
            # deterministic evenly-spaced sample of up to k contracts
            if len(lst) > k:
                step = len(lst) / k
                picks = [lst[int(i * step)] for i in range(k)]
            else:
                picks = lst
            for op, cl in picks:
                add_contract(asset, op, cl)
                total += 1
        print(f"[{scope}] stratified contracts mapped: {total} "
              f"across {len(per_asset_day)} asset-days")
    return needed


def fetch_hour(sign, idx: str, hour_ts: str, conn, rate: float) -> dict:
    params = {"id": idx, "timespan": "HOUR", "timestamp": hour_ts}
    url = BASE_URL + PASSTHROUGH_PATH + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={**sign("GET", PASSTHROUGH_PATH),
                      "Content-Type": "application/json"})
    retrieved_ms = int(time.time() * 1000)
    status, body, err = None, b"", None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                status, body = r.status, r.read()
            break
        except urllib.error.HTTPError as e:
            status = e.code
            body = e.read()[:400]
            err = f"HTTP {e.code}: {body[:200]!r}"
            if e.code in (429, 503):
                time.sleep(min(2 ** attempt * 2, 30))
                continue
            break
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
            time.sleep(min(2 ** attempt * 2, 30))
    n_ticks = 0
    if status == 200:
        try:
            payload = json.loads(body)["data"]["payload"]
            cur = conn.execute(
                "INSERT OR IGNORE INTO backfill_requests "
                "(index_id, req_timestamp, timespan, retrieved_at_ms, "
                "http_status, n_ticks, bytes, error) "
                "VALUES (?,?,?,?,?,?,?,NULL)",
                (idx, hour_ts, "HOUR", retrieved_ms, status,
                 len(payload), len(body)))
            req_id = cur.lastrowid
            rows = [(idx, int(t["time"]), str(t["value"]), hour_ts,
                     retrieved_ms) for t in payload]
            conn.executemany(
                "INSERT OR IGNORE INTO backfill_ticks "
                "(index_id, src_ts_ms, value, req_timestamp, retrieved_at_ms) "
                "VALUES (?,?,?,?,?)", rows)
            n_ticks = len(rows)
            conn.execute(
                "UPDATE backfill_requests SET n_ticks=? WHERE req_id=?",
                (n_ticks, req_id))
        except Exception as e:  # noqa: BLE001
            err = f"parse: {type(e).__name__}: {e}"
            conn.execute(
                "INSERT OR IGNORE INTO backfill_requests "
                "(index_id, req_timestamp, timespan, retrieved_at_ms, "
                "http_status, n_ticks, bytes, error) "
                "VALUES (?,?,?,?,?,0,?,?)",
                (idx, hour_ts, "HOUR", retrieved_ms, status,
                 len(body), err))
    else:
        conn.execute(
            "INSERT OR IGNORE INTO backfill_requests "
            "(index_id, req_timestamp, timespan, retrieved_at_ms, "
            "http_status, n_ticks, bytes, error) "
            "VALUES (?,?,?,?,?,0,?,?)",
            (idx, hour_ts, "HOUR", retrieved_ms, status,
             len(body), err))
    conn.commit()
    return {"index_id": idx, "hour": hour_ts, "status": status,
            "ticks": n_ticks, "error": err}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scope", choices=["live", "incident", "sample", "all"],
                    default="live")
    ap.add_argument("--assets", default="BTC,ETH,SOL,XRP,DOGE")
    ap.add_argument("--per-asset-day", type=int, default=2)
    ap.add_argument("--rate", type=float, default=3.0,
                    help="requests per second (50 tokens each)")
    ap.add_argument("--out", default="data/rti_backfill.db")
    ap.add_argument("--limit-hours", type=int, default=0,
                    help="cap total requests (0=unlimited)")
    args = ap.parse_args(argv)

    _load_env()
    sign = _signer()
    wanted_assets = {a.strip().upper() for a in args.assets.split(",")}
    needed = collect_targets(args.scope, args)
    # flatten to request list, filtered by asset
    reqs = [(idx, h) for idx, hs in needed.items()
            if ASSET_BY_INDEX[idx] in wanted_assets
            for h in sorted(hs)]
    print(f"total requests needed: {len(reqs)}")

    conn = sqlite3.connect(args.out)
    conn.executescript(SCHEMA)
    done = {(r[0], r[1]) for r in conn.execute(
        "SELECT index_id, req_timestamp FROM backfill_requests "
        "WHERE http_status=200")}
    todo = [(i, h) for i, h in reqs if (i, h) not in done]
    print(f"already fetched: {len(done)}; todo: {len(todo)}")
    if args.limit_hours:
        todo = todo[: args.limit_hours]

    t0 = time.time()
    ok = err_n = 0
    min_dt = 1.0 / max(args.rate, 0.1)
    for n, (idx, h) in enumerate(todo, 1):
        start = time.time()
        res = fetch_hour(sign, idx, h, conn, args.rate)
        if res["status"] == 200:
            ok += 1
        else:
            err_n += 1
        if n % 25 == 0 or n == len(todo):
            el = time.time() - t0
            print(f"[{n}/{len(todo)}] ok={ok} err={err_n} "
                  f"elapsed={el:.0f}s eta={el/n*(len(todo)-n):.0f}s")
        dt = time.time() - start
        if dt < min_dt:
            time.sleep(min_dt - dt)
    print(f"done: {ok} ok, {err_n} errors -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
