"""RTI-path settlement-aware backtest for Kalshi 15m crypto binaries.

Replays ``data/cf_rti_ticks.db`` (the same CF Benchmarks feed Kalshi settles
on) through the REAL production pricer —
``merid.prediction.settlement_distribution.compute_settlement_distribution``
— instead of pricing candles/terminal spot.  This is the artifact the
2026-11-19 external review asked for: a backtest that models the actual
instrument (the 60-print settlement average with observed slots fixed and
remaining variance on the exact discrete schedule), not an OHLC proxy.

Contract reconstruction (offline, no venue metadata needed):
  * Expiries sit on the :00/:15/:30/:45 UTC grid — the ET window-end minute
    marks are preserved under the whole-hour ET<->UTC offset.
  * Window = [expiry - 900s, expiry]; settlement average = mean of the 60
    one-second prints in (expiry - 60s, expiry].
  * Strike ≈ first RTI print at/after window open (``strike_source =
    rti_open_approx``).  The venue's ``floor_strike`` is authoritative in
    production; offline we approximate it with the opening print — flagged,
    not silent.
  * Outcome y = 1{settlement_avg > strike}; contracts with < ``min_coverage``
    settlement-slot coverage are scored but flagged (the archive may miss
    prints the venue actually published).

Decision evaluation: at each TTE in ``--tte-grid`` before expiry, feed all
ticks up to that instant into a replayed ``RealizedVolTracker`` (the same
estimator live uses, incl. the ``MERID_REALIZED_VOL_ESTIMATOR`` jump-robust
variants), build a ``SettlementState`` via ``build_settlement_state`` with
the observed settlement-window samples, and score ``p_yes`` against the
realized outcome.  Vol-starved instants (tracker below min samples/span)
are skipped and counted — matching live behavior where vol gates entries.

Baselines reported alongside the model:
  * ``const_half`` — 0.5 (the floor every forecast must beat to matter).
  * ``terminal_spot`` — Bachelier on TERMINAL spot (ignores the 60-print
    average and any already-observed settlement samples).  The gap between
    this and the model isolates the value of settlement-aware pricing —
    the exact error candle/OHLC backtests make.

Market-mid baseline is NOT available offline (book history is not retained
in the tick DB); join ``decision_audit.db`` mids for the overlapping live
window when comparing against the deployed forecast — see AGENTS.md
2026-11-19 section.  Brier here measures the MODEL's raw forecast quality
on the settlement instrument, not its edge over the market.

CLI::

    .venv/Scripts/python.exe -m merid.backtesting.rti_path_backtest \
        --db data/cf_rti_ticks.db --assets BTC,ETH \
        --from 2026-11-01 --to 2026-11-08 \
        --tte-grid 900,600,300,120,60,45 \
        --out reports/rti_path_2026-11-08.json
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import sqlite3
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from utils.logger import get_logger

logger = get_logger("merid.backtesting.rti_path_backtest")

# 15m grid: windows end at :00/:15/:30/:45 (minute marks preserved across the
# whole-hour ET<->UTC offset, incl. DST).
_WINDOW_S = 900.0
_SETTLEMENT_S = 60.0
_GRID_MINUTES = (0, 15, 30, 45)


# ---------------------------------------------------------------------------
# Tick loading
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RtiTick:
    """One effective-timestamp RTI observation (ms epoch + price)."""

    ts_ms: int
    value: float


@dataclass(frozen=True)
class RtiObs:
    """Observation shape consumed by ``_group_observations_by_second``."""

    source_ts_ms: int
    value: float


def _effective_ts_ms(row: sqlite3.Row) -> Optional[int]:
    for col in ("src_ts_ms", "recv_ts_ms", "local_ts_ms"):
        v = row[col]
        if v is not None:
            return int(v)
    return None


def load_ticks(
    db_path: str,
    assets: Sequence[str],
    t0_ms: int,
    t1_ms: int,
) -> Dict[str, List[RtiTick]]:
    """Load (eff_ts_ms, value) ticks per asset in [t0_ms, t1_ms).

    Uses the ``idx_rti_ticks_asset_effts`` expression index.  Rows with NULL
    value or non-positive price are dropped (the settlement grouper would
    reject them anyway).
    """
    out: Dict[str, List[RtiTick]] = {a.upper(): [] for a in assets}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        for asset in out:
            rows = con.execute(
                """
                SELECT src_ts_ms, recv_ts_ms, local_ts_ms, value
                FROM rti_ticks
                WHERE asset = ?
                  AND COALESCE(src_ts_ms, recv_ts_ms, local_ts_ms) >= ?
                  AND COALESCE(src_ts_ms, recv_ts_ms, local_ts_ms) < ?
                  AND value IS NOT NULL AND value > 0
                ORDER BY COALESCE(src_ts_ms, recv_ts_ms, local_ts_ms)
                """,
                (asset, t0_ms, t1_ms),
            )
            ticks: List[RtiTick] = []
            for r in rows:
                ts = _effective_ts_ms(r)
                if ts is None:
                    continue
                ticks.append(RtiTick(ts_ms=ts, value=float(r["value"])))
            out[asset] = ticks
            logger.info(
                "[rti-bt] %s: %d ticks in range", asset, len(ticks)
            )
    finally:
        con.close()
    return out


# ---------------------------------------------------------------------------
# Contract-window utilities
# ---------------------------------------------------------------------------


def window_expiries(t0: datetime, t1: datetime) -> List[datetime]:
    """All :00/:15/:30/:45 UTC expiries in [t0, t1]."""
    out: List[datetime] = []
    day = t0.replace(hour=0, minute=0, second=0, microsecond=0)
    end_day = t1 + timedelta(days=1)
    cur = day
    while cur <= end_day:
        for hour in range(24):
            for m in _GRID_MINUTES:
                exp = cur.replace(hour=hour, minute=m)
                if t0 <= exp <= t1:
                    out.append(exp)
        cur += timedelta(days=1)
    return sorted(out)


def _tick_at_or_after(
    times: Sequence[int], ticks: Sequence[RtiTick], ts_ms: int
) -> Optional[RtiTick]:
    i = bisect.bisect_left(times, ts_ms)
    if i < len(ticks):
        return ticks[i]
    return None


def _ticks_between_idx(
    times: Sequence[int], lo_ms: int, hi_ms: int
) -> Tuple[int, int]:
    """Slice bounds for ticks with lo_ms < ts <= hi_ms (right-endpoint cadence)."""
    return bisect.bisect_right(times, lo_ms), bisect.bisect_right(times, hi_ms)


def strike_at_open(
    times: Sequence[int], ticks: Sequence[RtiTick], window_open_ms: int
) -> Optional[float]:
    """First RTI print at/after window open within 30s — strike approximation."""
    t = _tick_at_or_after(times, ticks, window_open_ms)
    if t is None or t.ts_ms - window_open_ms > 30_000:
        return None
    return t.value


def settlement_average(
    times: Sequence[int], ticks: Sequence[RtiTick], expiry_ms: int
) -> Tuple[Optional[float], int]:
    """Mean of the 60 one-second prints in (expiry-60s, expiry].

    Groups by whole second (latest print wins), mirroring the venue's
    one-second cadence.  Returns (average, slots_covered).
    """
    i0, i1 = _ticks_between_idx(times, expiry_ms - 60_000, expiry_ms)
    by_second: Dict[int, float] = {}
    for t in ticks[i0:i1]:
        sec = (t.ts_ms // 1000) * 1000
        by_second[sec] = t.value  # ticks are ts-ordered: latest wins
    if not by_second:
        return None, 0
    # Official settlement averages exactly 60 prints; we average observed
    # slots and report coverage so low-archive-coverage contracts are
    # visible rather than silently exact.
    avg = sum(by_second.values()) / len(by_second)
    return avg, len(by_second)


# ---------------------------------------------------------------------------
# Decision evaluation
# ---------------------------------------------------------------------------


def _terminal_spot_p_yes(
    latest: float, strike: float, annualized_vol: float, tte_s: float
) -> float:
    """Bachelier on TERMINAL spot — the candle-backtest baseline.

    Ignores the 60-print average and every already-observed settlement
    sample; variance is sigma^2 * tte.  This is the systematic error an
    OHLC/terminal-spot backtest makes on this instrument.
    """
    if tte_s <= 0:
        return 1.0 if latest >= strike else 0.0
    year_s = 365.0 * 24.0 * 3600.0
    sigma_price = annualized_vol * latest
    std = sigma_price * math.sqrt(tte_s / year_s)
    if std <= 0:
        return 1.0 if latest >= strike else 0.0
    return statistics.NormalDist().cdf((latest - strike) / std)


def _model_p_yes(
    *,
    asset: str,
    ticker: str,
    strike: float,
    expiry_dt: datetime,
    now_dt: datetime,
    latest_tick: RtiTick,
    hist_ticks: Sequence[RtiTick],
    annualized_vol: float,
    max_missing_samples: int,
) -> float:
    """Production settlement-distribution probability at one instant."""
    from merid.prediction.settlement_distribution import (
        build_settlement_state,
        compute_settlement_distribution,
    )

    obs = [RtiObs(source_ts_ms=t.ts_ms, value=t.value) for t in hist_ticks]
    state = build_settlement_state(
        ticker=ticker,
        asset=asset,
        strike_price=float(strike),
        expiry_ts=expiry_dt,
        now_ts=now_dt,
        latest_rti=float(latest_tick.value),
        latest_rti_decimal=None,
        latest_rti_ts=datetime.fromtimestamp(
            latest_tick.ts_ms / 1000.0, tz=timezone.utc
        ),
        rti_history=obs,
        source="cf_rti",
        settlement_reference="cfb_rti_backtest",
    )
    dist = compute_settlement_distribution(
        state, annualized_vol, max_missing_samples=max_missing_samples
    )
    return float(dist.p_yes_raw)


def _brier(ps: Sequence[float], ys: Sequence[int]) -> Optional[float]:
    if not ps:
        return None
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ps)


def _logloss(ps: Sequence[float], ys: Sequence[int], eps: float = 1e-6) -> Optional[float]:
    if not ps:
        return None
    tot = 0.0
    for p, y in zip(ps, ys):
        pc = min(max(p, eps), 1.0 - eps)
        tot += -(y * math.log(pc) + (1 - y) * math.log(1 - pc))
    return tot / len(ps)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def run_rti_path_backtest(
    *,
    db_path: str,
    assets: Sequence[str],
    t_start: datetime,
    t_end: datetime,
    tte_grid_s: Sequence[float],
    min_coverage: float = 0.9,
    max_missing_samples: int = 5,
    progress: bool = False,
) -> Dict[str, Any]:
    """Replay RTI ticks through the settlement model; return score tables."""
    from merid.prediction.realized_vol import RealizedVolTracker

    t0_ms = int(t_start.timestamp() * 1000)
    # Pad the load window: vol tracker needs warm-up history before the
    # first decision, and settlement windows precede expiries.
    load_start_ms = t0_ms - 3600_000
    t1_ms = int(t_end.timestamp() * 1000) + 1000
    ticks_by_asset = load_ticks(db_path, assets, load_start_ms, t1_ms)

    expiries = window_expiries(t_start, t_end)
    # Decisions per expiry: expiry - tte for each grid TTE (whole seconds).
    decisions: List[Tuple[str, datetime, datetime, float]] = []
    # (asset, expiry_dt, now_dt, tte_s)
    tte_set = sorted({float(t) for t in tte_grid_s})
    for exp in expiries:
        for tte in tte_set:
            now = exp - timedelta(seconds=tte)
            if now < t_start:
                continue
            for a in assets:
                decisions.append((a.upper(), exp, now, tte))
    decisions.sort(key=lambda d: (d[0], d[2]))  # per-asset chronological

    records: List[Dict[str, Any]] = []
    skipped = {"no_ticks": 0, "no_strike": 0, "no_vol": 0,
               "model_error": 0, "low_coverage": 0}

    for asset in sorted({d[0] for d in decisions}):
        ticks = ticks_by_asset.get(asset, [])
        times = [t.ts_ms for t in ticks]
        tracker = RealizedVolTracker()
        cursor = 0  # ticks fed to tracker so far (chronological)
        asset_decisions = [d for d in decisions if d[0] == asset]

        for _asset, expiry_dt, now_dt, tte in asset_decisions:
            now_ms = int(now_dt.timestamp() * 1000)
            exp_ms = int(expiry_dt.timestamp() * 1000)
            # Feed all ticks up to `now` into the vol tracker.
            while cursor < len(ticks) and ticks[cursor].ts_ms <= now_ms:
                tracker.record(asset, ticks[cursor].value, ticks[cursor].ts_ms / 1000.0)
                cursor += 1
            if cursor == 0:
                skipped["no_ticks"] += 1
                continue
            latest = ticks[cursor - 1]
            if latest.ts_ms > now_ms:
                skipped["no_ticks"] += 1
                continue

            window_open_ms = exp_ms - int(_WINDOW_S * 1000)
            strike = strike_at_open(times, ticks, window_open_ms)
            if strike is None:
                skipped["no_strike"] += 1
                continue

            vol_est = tracker.annualized_vol(asset, now=now_dt.timestamp())
            if vol_est is None:
                skipped["no_vol"] += 1
                continue

            # Observed settlement-window samples: ticks in (expiry-60, now].
            h0, h1 = _ticks_between_idx(times, exp_ms - 60_000, now_ms)
            hist = ticks[h0:h1]
            ticker = f"KX{asset}15M-BT-{expiry_dt:%Y%m%d%H%M}"
            try:
                p_model = _model_p_yes(
                    asset=asset,
                    ticker=ticker,
                    strike=strike,
                    expiry_dt=expiry_dt,
                    now_dt=now_dt,
                    latest_tick=latest,
                    hist_ticks=hist,
                    annualized_vol=vol_est.value,
                    max_missing_samples=max_missing_samples,
                )
            except Exception as exc:
                skipped["model_error"] += 1
                if progress:
                    logger.debug("[rti-bt] model error %s %s: %s",
                                 asset, expiry_dt, exc)
                continue

            p_spot = _terminal_spot_p_yes(
                latest.value, strike, vol_est.value, tte
            )

            # Outcome: realized 60-print settlement average vs strike.
            avg, coverage = settlement_average(times, ticks, exp_ms)
            if avg is None:
                continue
            y = 1 if avg > strike else 0
            cov_frac = coverage / _SETTLEMENT_S
            if cov_frac < min_coverage:
                skipped["low_coverage"] += 1

            records.append({
                "asset": asset,
                "expiry_ts": expiry_dt.timestamp(),
                "decision_ts": now_dt.timestamp(),
                "tte_s": tte,
                "strike": strike,
                "strike_source": "rti_open_approx",
                "settlement_avg": avg,
                "settlement_coverage": cov_frac,
                "y": y,
                "p_model": p_model,
                "p_terminal_spot": p_spot,
                "p_half": 0.5,
                "vol_annualized": vol_est.value,
                "vol_estimator": vol_est.estimator,
                "vol_samples": vol_est.samples,
            })
            if progress and len(records) % 500 == 0:
                logger.info("[rti-bt] %d decisions scored", len(records))

    # ---- score tables -------------------------------------------------------
    def _table(key_fn) -> Dict[str, Any]:
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for r in records:
            groups.setdefault(key_fn(r), []).append(r)
        out: Dict[str, Any] = {}
        for k, rows in sorted(groups.items()):
            ys = [r["y"] for r in rows]
            out[k] = {
                "n": len(rows),
                "brier_model": _brier([r["p_model"] for r in rows], ys),
                "brier_terminal_spot": _brier([r["p_terminal_spot"] for r in rows], ys),
                "brier_half": _brier([0.5] * len(rows), ys),
                "logloss_model": _logloss([r["p_model"] for r in rows], ys),
                "logloss_terminal_spot": _logloss([r["p_terminal_spot"] for r in rows], ys),
                "mean_coverage": sum(r["settlement_coverage"] for r in rows) / len(rows),
            }
        return out

    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "db_path": db_path,
        "range": [t_start.isoformat(), t_end.isoformat()],
        "assets": list(assets),
        "tte_grid_s": list(tte_grid_s),
        "n_expiries": len(expiries),
        "n_decisions_scored": len(records),
        "skipped": skipped,
        "strike_source": "rti_open_approx — venue floor_strike unavailable offline",
        "settlement_rule": "y = 1{mean(60 one-second prints in (expiry-60s, expiry]) > strike}",
        "vol_source": "RealizedVolTracker replay (live estimator; env-gated variant)",
        "baselines": {
            "const_half": "0.5 — floor",
            "terminal_spot": "Bachelier on terminal spot — ignores 60-print average + observed samples",
            "market_mid": "NOT AVAILABLE offline — join decision_audit.db for live-window comparison",
        },
        "by_tte": _table(lambda r: f"tte_{int(r['tte_s'])}s"),
        "by_asset": _table(lambda r: r["asset"]),
        "by_asset_tte": _table(lambda r: f"{r['asset']}_tte_{int(r['tte_s'])}s"),
        "records": records,
    }
    return report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="data/cf_rti_ticks.db")
    ap.add_argument("--assets", default="BTC,ETH,SOL,XRP,DOGE")
    ap.add_argument("--from", dest="t_from", required=True,
                    help="UTC start, e.g. 2026-11-01 or 2026-11-01T00:00:00Z")
    ap.add_argument("--to", dest="t_to", required=True)
    ap.add_argument("--tte-grid", default="900,600,300,120,60,45,30",
                    help="comma-separated seconds-to-expiry decision grid")
    ap.add_argument("--min-coverage", type=float, default=0.9,
                    help="flag (not drop) contracts below this settlement-slot coverage")
    ap.add_argument("--max-missing-samples", type=int, default=5,
                    help="bounded forward-fill inside the settlement window")
    ap.add_argument("--out", default=None)
    ap.add_argument("--progress", action="store_true")
    args = ap.parse_args(argv)

    def _parse_ts(s: str) -> datetime:
        s = s.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    tte_grid = [float(x) for x in args.tte_grid.split(",") if x.strip()]
    assets = [a.strip().upper() for a in args.assets.split(",") if a.strip()]

    t_start = time.time()
    report = run_rti_path_backtest(
        db_path=args.db,
        assets=assets,
        t_start=_parse_ts(args.t_from),
        t_end=_parse_ts(args.t_to),
        tte_grid_s=tte_grid,
        min_coverage=args.min_coverage,
        max_missing_samples=args.max_missing_samples,
        progress=args.progress,
    )
    report["elapsed_s"] = round(time.time() - t_start, 2)

    # Console summary
    print(f"expiries={report['n_expiries']} scored={report['n_decisions_scored']} "
          f"skipped={report['skipped']} elapsed={report['elapsed_s']}s")
    print(f"{'group':<22} {'n':>6} {'Brier(model)':>13} {'Brier(spot)':>12} "
          f"{'Brier(0.5)':>11} {'LL(model)':>10}")
    for section in ("by_tte", "by_asset"):
        for k, row in report[section].items():
            print(f"{k:<22} {row['n']:>6} "
                  f"{row['brier_model'] if row['brier_model'] is not None else float('nan'):>13.4f} "
                  f"{row['brier_terminal_spot'] if row['brier_terminal_spot'] is not None else float('nan'):>12.4f} "
                  f"{row['brier_half'] if row['brier_half'] is not None else float('nan'):>11.4f} "
                  f"{row['logloss_model'] if row['logloss_model'] is not None else float('nan'):>10.4f}")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
