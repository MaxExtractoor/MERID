"""Settlement reconstruction audit for Kalshi 15m crypto contracts.

Reconstructs the contractual opening/closing CF-Benchmarks reference
averages from captured ``rti_ticks`` and compares the implied outcome
against the official Kalshi settlement record.  This validates that MERID's
data actually contains the same contractual event the exchange settles —
window endpoints, observation count, averaging, rounding, and the
``>=``/``>`` inequality — before any replay or P&L claim relies on it.

Window semantics under test (the rules state "the sixty seconds of RTI
*before* T"): candidate slot grids are ``[T-60, T)`` (pre-boundary seconds)
and ``[T-59, T]`` (the live ``SettlementRTIBuffer`` convention).  The audit
scores both against CF's own published ``avg_60s_15m`` settlement-band value
and the official outcome, and reports which alignment the data supports.

CLI::

    py -3 -m merid.analysis.settlement_recon \
        --rti-db data/cf_rti_ticks.db \
        --outcomes logs/settlement_outcomes.jsonl \
        --out reports/settlement_recon_2026-11-14.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from merid.data.price_precision import (
    get_asset_settlement_digits, settlement_round,
)
from merid.ticker_time import parse_kalshi_15m_window_end_utc

INDEX_BY_ASSET = {
    "BTC": "BRTI", "ETH": "ETHUSD_RTI", "SOL": "SOLUSD_RTI",
    "XRP": "XRPUSD_RTI", "DOGE": "DOGEUSD_RTI",
}
ASSET_BY_INDEX = {v: k for k, v in INDEX_BY_ASSET.items()}
WINDOW_S = 900.0       # 15-minute contract window
REF_S = 60.0           # reference observation window


# ---------------------------------------------------------------------------
# Tick loading
# ---------------------------------------------------------------------------

def _ro_conn(path: str | Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)


def load_ticks(
    conn: sqlite3.Connection,
    index_id: str,
    t0_s: float,
    t1_s: float,
) -> List[Tuple[float, float, Optional[float], Optional[float]]]:
    """(src_ts_s, value, avg_60s, avg_60s_15m) for one index in [t0,t1]."""
    rows = conn.execute(
        "SELECT src_ts_ms, value, avg_60s, avg_60s_15m FROM rti_ticks "
        "WHERE index_id = ? AND src_ts_ms >= ? AND src_ts_ms <= ? "
        "ORDER BY src_ts_ms",
        (index_id, int(t0_s * 1000), int(t1_s * 1000)),
    ).fetchall()
    return [
        (r[0] / 1000.0, float(r[1]),
         float(r[2]) if r[2] is not None else None,
         float(r[3]) if r[3] is not None else None)
        for r in rows if r[1] is not None
    ]


def per_second_latest(
    ticks: Sequence[Tuple[float, float, Optional[float], Optional[float]]],
) -> Dict[int, float]:
    """Latest value per integer second (CF timestamps), matching the live
    buffer's one-value-per-second overwrite semantics."""
    out: Dict[int, float] = {}
    for ts, px, _a60, _a15 in ticks:
        out[int(ts)] = px
    return out


def window_mean(
    sec_map: Dict[int, float],
    end_ts: float,
    *,
    mode: str,
) -> Tuple[Optional[float], int, int]:
    """Mean over the 60-slot reference window ending at ``end_ts``.

    ``mode='pre'``: slots are seconds [end-60, end) — "sixty seconds before T".
    ``mode='incl'``: slots are seconds [end-59, end] — SettlementRTIBuffer.
    Returns (mean_or_None, filled, missing).  None when zero slots filled.
    """
    if mode == "pre":
        secs = [int(end_ts) - 60 + i for i in range(60)]
    else:
        secs = [int(end_ts) - 59 + i for i in range(60)]
    vals = [sec_map[s] for s in secs if s in sec_map]
    filled = len(vals)
    if filled == 0:
        return None, 0, 60
    return sum(vals) / filled, filled, 60 - filled


def cf_band_value(
    ticks: Sequence[Tuple[float, float, Optional[float], Optional[float]]],
    end_ts: float,
    grace_s: float = 2.0,
    lookback_s: float = 90.0,
) -> Optional[float]:
    """Last published ``avg_60s_15m`` within ``[end-lookback, end+grace]`` —
    CF's own settlement-band average for THIS window.  Bounded lookback is
    essential: the field is sparse and an unbounded scan returns a stale
    value from an earlier contract."""
    best = None
    lo = end_ts - lookback_s
    for ts, _px, _a60, a15 in ticks:
        if ts < lo:
            continue
        if a15 is None:
            continue
        if ts <= end_ts + grace_s:
            best = a15
        else:
            break
    return best


def cf_avg60_at(
    ticks: Sequence[Tuple[float, float, Optional[float], Optional[float]]],
    end_ts: float,
    lookback_s: float = 90.0,
) -> Optional[float]:
    """CF ``avg_60s`` on the last tick within ``[end-lookback, end]``."""
    best = None
    lo = end_ts - lookback_s
    for ts, _px, a60, _a15 in ticks:
        if ts < lo:
            continue
        if ts <= end_ts:
            if a60 is not None:
                best = a60
        else:
            break
    return best


# ---------------------------------------------------------------------------
# Per-contract reconstruction
# ---------------------------------------------------------------------------

def reconstruct_contract(
    ticks_by_index: Dict[str, List[Tuple[float, float, Optional[float], Optional[float]]]],
    index_id: str,
    t_close: float,
    asset: str,
) -> Dict[str, Any]:
    """Reconstruct one contract's reference averages + implied outcome."""
    ticks = ticks_by_index.get(index_id, [])
    sec_map = per_second_latest(ticks)
    t_open = t_close - WINDOW_S
    digits = get_asset_settlement_digits(asset)

    out: Dict[str, Any] = {
        "t_close": t_close, "t_open": t_open, "index_id": index_id,
        "n_ticks": len(ticks),
    }
    for win_name, end in (("open", t_open), ("close", t_close)):
        for mode in ("pre", "incl"):
            mean, filled, missing = window_mean(sec_map, end, mode=mode)
            out[f"{win_name}_{mode}_mean"] = mean
            out[f"{win_name}_{mode}_filled"] = filled
            out[f"{win_name}_{mode}_missing"] = missing
        out[f"{win_name}_cf_band"] = cf_band_value(ticks, end)
        out[f"{win_name}_cf_avg60"] = cf_avg60_at(ticks, end)

    # Implied outcomes under each window-mode + inequality, using raw means.
    for mode in ("pre", "incl"):
        o, c = out.get(f"open_{mode}_mean"), out.get(f"close_{mode}_mean")
        if o is None or c is None:
            out[f"outcome_{mode}"] = None
            continue
        out[f"outcome_{mode}_ge"] = int(c >= o)
        out[f"outcome_{mode}_gt"] = int(c > o)
        # Rounded-to-settlement-digits comparison (what the exchange prints).
        orr = float(settlement_round(Decimal(str(o)), digits))
        crr = float(settlement_round(Decimal(str(c)), digits))
        out[f"outcome_{mode}_rounded_ge"] = int(crr >= orr)
        out[f"outcome_{mode}_rounded_gt"] = int(crr > orr)
        out[f"{mode}_diff_raw"] = c - o
        out[f"{mode}_tie_raw"] = int(c == o)
        out[f"{mode}_tie_rounded"] = int(crr == orr)
    return out


# ---------------------------------------------------------------------------
# Synthetic control fixtures — edge cases the reconstruction must handle
# ---------------------------------------------------------------------------

def selftest() -> Dict[str, Any]:
    """Synthetic fixtures: known-answer checks on window semantics.

    Each fixture builds a synthetic tick list and asserts the reconstruction
    behaves correctly.  Returns {name: 'PASS'/'FAIL: detail'}.
    """
    results: Dict[str, Any] = {}

    T = 1_800_000_000.0  # arbitrary boundary epoch
    IDX = "BRTI"

    def ticks_for(sec_vals: Dict[int, float]) -> List[Tuple[float, float, None, None]]:
        return [(float(s), v, None, None) for s, v in sorted(sec_vals.items())]

    # Fixture 1: full 60-slot coverage, rising prices -> incl mode mean must
    # equal the mean of seconds [T-59, T]; pre mode must EXCLUDE second T and
    # INCLUDE second T-60 (one-slot shift).
    sec = {int(T) - 60 + i: 100.0 + i for i in range(61)}  # T-60..T inclusive
    sm = per_second_latest(ticks_for(sec))
    m_incl, f_incl, _ = window_mean(sm, T, mode="incl")
    m_pre, f_pre, _ = window_mean(sm, T, mode="pre")
    exp_incl = sum(100.0 + i for i in range(1, 61)) / 60  # secs T-59..T -> i=1..60
    exp_pre = sum(100.0 + i for i in range(0, 60)) / 60   # secs T-60..T-1 -> i=0..59
    results["full_coverage_incl"] = (
        "PASS" if abs(m_incl - exp_incl) < 1e-9 and f_incl == 60 else
        f"FAIL incl={m_incl} exp={exp_incl} filled={f_incl}")
    results["full_coverage_pre_shift"] = (
        "PASS" if abs(m_pre - exp_pre) < 1e-9 else
        f"FAIL pre={m_pre} exp={exp_pre}")

    # Fixture 2: missing seconds — mean over available slots only, missing
    # count correct; empty window -> None.
    sec2 = {int(T) - 59 + i: 50.0 for i in range(0, 60, 2)}  # 30 of 60 secs
    sm2 = per_second_latest(ticks_for(sec2))
    m2, f2, miss2 = window_mean(sm2, T, mode="incl")
    results["missing_samples_partial"] = (
        "PASS" if m2 == 50.0 and f2 == 30 and miss2 == 30 else
        f"FAIL mean={m2} filled={f2} missing={miss2}")
    sm3 = per_second_latest(ticks_for({}))
    m3, f3, _ = window_mean(sm3, T, mode="incl")
    results["empty_window_none"] = (
        "PASS" if m3 is None and f3 == 0 else f"FAIL {m3} {f3}")

    # Fixture 3: duplicate ticks in same second — latest wins (overwrite).
    dup = [(float(int(T) - 5), 10.0, None, None),
           (float(int(T) - 5) + 0.5, 20.0, None, None)]
    sm4 = per_second_latest(dup)
    results["duplicate_second_latest_wins"] = (
        "PASS" if sm4.get(int(T) - 5) == 20.0 else
        f"FAIL {sm4.get(int(T) - 5)}")

    # Fixture 4: delayed tick (src_ts inside window, recv later) still counts
    # by src_ts — capture uses upstream CF timestamps for slotting.
    delayed = [(float(int(T) - 10), 99.0, None, None)]
    sm5 = per_second_latest(delayed)
    results["delayed_tick_by_src_ts"] = (
        "PASS" if sm5.get(int(T) - 10) == 99.0 else "FAIL")

    # Fixture 5: rounding tie — close == open after settlement rounding must
    # resolve YES under >= (rules "at least"), NO under >.
    from decimal import Decimal
    from merid.data.price_precision import get_asset_settlement_digits, settlement_round
    d = get_asset_settlement_digits("BTC")
    o = float(settlement_round(Decimal("100.004"), d))
    c = float(settlement_round(Decimal("100.005"), d))
    results["rounding_boundary_ge"] = (
        "PASS" if int(c >= o) == 1 else f"FAIL o={o} c={c}")

    # Fixture 6: window endpoint exclusivity — a tick exactly at second T
    # belongs to incl mode, a tick at T-60 belongs to pre mode only.
    edge = ticks_for({int(T): 7.0, int(T) - 60: 3.0})
    sm6 = per_second_latest(edge)
    mi, fi, _ = window_mean(sm6, T, mode="incl")
    mp, fp, _ = window_mean(sm6, T, mode="pre")
    results["endpoint_incl_has_T"] = (
        "PASS" if fi == 1 and mi == 7.0 else f"FAIL incl filled={fi} mean={mi}")
    results["endpoint_pre_has_Tm60"] = (
        "PASS" if fp == 1 and mp == 3.0 else f"FAIL pre filled={fp} mean={mp}")

    # Fixture 7: cf_band_value bounded lookback — a stale band from hours ago
    # must NOT be returned for a window with no fresh band data.
    stale = [(1_000_000.0, 1.0, None, 5.5),           # ancient band value
             (float(T) - 30, 1.0, None, None)]        # fresh tick, no band
    results["cf_band_bounded_lookback"] = (
        "PASS" if cf_band_value(stale, T) is None else "FAIL stale band leaked")
    fresh = stale + [(float(T) - 5, 1.0, None, 6.6)]
    results["cf_band_fresh_within_window"] = (
        "PASS" if cf_band_value(fresh, T) == 6.6 else "FAIL")

    n_pass = sum(1 for v in results.values() if v == "PASS")
    results["_summary"] = f"{n_pass}/{len(results)} fixtures PASS"
    return results


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def iter_outcomes(path: str | Path) -> List[Dict[str, Any]]:
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("event_type") != "settlement_outcome":
                continue
            tk = r.get("ticker", "")
            asset = r.get("asset") or ""
            idx = INDEX_BY_ASSET.get(asset.upper())
            st = r.get("settlement_timestamp_utc")
            if not idx or not st:
                continue
            try:
                t_close = datetime.fromisoformat(
                    st.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            out.append({
                "ticker": tk, "asset": asset.upper(), "index_id": idx,
                "t_close": t_close,
                "official_yes": int(r.get("resolved_yes", -1)),
                "official_outcome": r.get("outcome"),
                "observed_at": r.get("observed_at_utc"),
            })
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rti-db", default="data/cf_rti_ticks.db")
    ap.add_argument("--outcomes", default="logs/settlement_outcomes.jsonl")
    ap.add_argument("--out", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--selftest", action="store_true",
                    help="run synthetic edge-case fixtures and exit")
    args = ap.parse_args(argv)

    if args.selftest:
        res = selftest()
        print(json.dumps(res, indent=2))
        bad = [k for k, v in res.items() if v != "PASS" and not k.startswith("_")]
        return 1 if bad else 0

    conn = _ro_conn(args.rti_db)
    lo_ms, hi_ms = conn.execute(
        "SELECT MIN(src_ts_ms), MAX(src_ts_ms) FROM rti_ticks").fetchone()
    rti_lo, rti_hi = lo_ms / 1000.0, hi_ms / 1000.0
    print(f"[recon] RTI coverage {datetime.fromtimestamp(rti_lo, timezone.utc)} "
          f".. {datetime.fromtimestamp(rti_hi, timezone.utc)}")

    outcomes = [
        o for o in iter_outcomes(args.outcomes)
        if rti_lo - 1000 <= o["t_close"] <= rti_hi + 1000
    ]
    outcomes.sort(key=lambda o: o["t_close"])
    if args.limit:
        outcomes = outcomes[: args.limit]
    print(f"[recon] {len(outcomes)} settled contracts inside RTI coverage")

    # Load ticks once per index over the whole needed span.
    ticks_by_index: Dict[str, List] = {}
    needed = sorted({o["index_id"] for o in outcomes})
    for idx in needed:
        t0 = min(o["t_close"] for o in outcomes if o["index_id"] == idx) - 1000
        t1 = max(o["t_close"] for o in outcomes if o["index_id"] == idx) + 60
        ticks_by_index[idx] = load_ticks(conn, idx, t0, t1)
        print(f"[recon] {idx}: {len(ticks_by_index[idx])} ticks loaded")
    conn.close()

    rows = []
    for i, o in enumerate(outcomes):
        rec = reconstruct_contract(ticks_by_index, o["index_id"],
                                   o["t_close"], o["asset"])
        rec.update({k: o[k] for k in
                    ("ticker", "asset", "official_yes", "official_outcome",
                     "observed_at")})
        # Agreement matrix vs official.
        for mode in ("pre", "incl"):
            for suffix in ("ge", "gt", "rounded_ge", "rounded_gt"):
                k = f"outcome_{mode}_{suffix}"
                pred = rec.get(k)
                rec[f"agree_{mode}_{suffix}"] = (
                    int(pred == o["official_yes"]) if pred is not None else None)
        rows.append(rec)
        if (i + 1) % 50 == 0:
            print(f"[recon] {i+1}/{len(outcomes)}")

    # ---- aggregate ---------------------------------------------------------
    def _rate(vals):
        vals = [v for v in vals if v is not None]
        return {"n": len(vals),
                "agree": sum(vals),
                "rate": (sum(vals) / len(vals)) if vals else None}

    summary: Dict[str, Any] = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "rti_coverage_utc": [
            datetime.fromtimestamp(rti_lo, timezone.utc).isoformat(),
            datetime.fromtimestamp(rti_hi, timezone.utc).isoformat()],
        "n_contracts": len(rows),
        "window_seconds": WINDOW_S, "ref_seconds": REF_S,
    }
    for mode in ("pre", "incl"):
        for suffix in ("ge", "gt", "rounded_ge", "rounded_gt"):
            summary[f"agreement_{mode}_{suffix}"] = _rate(
                [r.get(f"agree_{mode}_{suffix}") for r in rows])
    # Coverage of the 60-slot grids.
    for win in ("open", "close"):
        for mode in ("pre", "incl"):
            filled = [r.get(f"{win}_{mode}_filled", 0) for r in rows]
            full = sum(1 for f in filled if f == 60)
            summary[f"{win}_{mode}_full60"] = full
            summary[f"{win}_{mode}_mean_filled"] = (
                sum(filled) / len(filled)) if filled else 0
    # CF band-field coverage.
    for win in ("open", "close"):
        summary[f"{win}_cf_band_present"] = sum(
            1 for r in rows if r.get(f"{win}_cf_band") is not None)

    # CF band-vs-band outcome agreement (CF's own published settlement
    # values as oracle — only where fresh band data exists on BOTH windows).
    band_pairs = [
        r for r in rows
        if r.get("open_cf_band") is not None
        and r.get("close_cf_band") is not None
        and r.get("official_yes") in (0, 1)
    ]
    for cmp_name, fn in (
        ("band_ge", lambda o, c: int(c >= o)),
        ("band_gt", lambda o, c: int(c > o)),
    ):
        hits = [int(fn(r["open_cf_band"], r["close_cf_band"]))
                == r["official_yes"] for r in band_pairs]
        summary[f"agreement_{cmp_name}"] = {
            "n": len(hits), "agree": sum(hits),
            "rate": (sum(hits) / len(hits)) if hits else None}

    # Which mode's mean is closer to CF's published band value?
    band_err = {"pre": [], "incl": []}
    for r in rows:
        for mode in ("pre", "incl"):
            band = r.get("close_cf_band")
            mean = r.get(f"close_{mode}_mean")
            if band is not None and mean is not None:
                band_err[mode].append(abs(mean - band))
    for mode in ("pre", "incl"):
        errs = band_err[mode]
        summary[f"close_band_abs_err_{mode}"] = {
            "n": len(errs),
            "mean": (sum(errs) / len(errs)) if errs else None,
            "max": max(errs) if errs else None,
        }
    # Window-mode selection: CF band error is the direct evidence of CF's
    # own computation; outcome agreement is secondary (sparse coverage).
    e_pre = summary["close_band_abs_err_pre"]["mean"]
    e_incl = summary["close_band_abs_err_incl"]["mean"]
    summary["selected_window_mode"] = (
        "incl" if (e_incl is not None and (e_pre is None or e_incl <= e_pre))
        else "pre" if e_pre is not None else "incl")

    # Discrepancy detail under the selected window mode.
    best = summary["selected_window_mode"]
    summary["discrepancies"] = [
        {k: r.get(k) for k in (
            "ticker", "asset", "t_close", "official_yes",
            f"outcome_{best}_rounded_ge", f"close_{best}_mean",
            f"open_{best}_mean", f"close_{best}_filled",
            f"open_{best}_filled", "close_cf_band", "close_cf_avg60")}
        for r in rows
        if r.get(f"agree_{best}_rounded_ge") == 0
    ][:200]

    text = json.dumps({"summary": summary, "contracts": rows},
                      indent=2, default=str)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    # console digest
    print(json.dumps(summary, indent=2, default=str)[:4000])
    if args.out:
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
