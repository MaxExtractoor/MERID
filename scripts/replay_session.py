#!/usr/bin/env python
"""C3: Live-replay mode — replay historical OHLCV through the current agent stack.

Fetches historical candlestick data from Kalshi (or a local CSV fallback) and
feeds it bar-by-bar through the EdgeModel + consensus pipeline, capturing every
signal, decision, and simulated fill in a replay report.

Usage
-----
  py scripts/replay_session.py --ticker KXBTC-24DEC31-B90000 --years 1 --resolution 1h
  py scripts/replay_session.py --ticker KXBTC-24DEC31-B90000 --csv data/btc.csv

Output
------
  replay_<ticker>_<timestamp>.json   – machine-readable signal/fill log
  (stdout)                           – summary table
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Project root on path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.logger import get_logger

logger = get_logger("scripts.replay_session")


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class ReplaySignal:
    bar_index: int
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    model_prob: float
    confidence: float
    edge: float
    decision: str          # "enter_yes" | "enter_no" | "hold"
    simulated_fill: Optional[float] = None   # fill price in cents


@dataclass
class ReplayReport:
    ticker: str
    resolution: str
    bars_replayed: int
    signals: List[ReplaySignal] = field(default_factory=list)
    total_entries: int = 0
    simulated_pnl_cents: float = 0.0
    edge_model_errors: int = 0
    started_at: float = field(default_factory=time.time)
    elapsed_s: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "resolution": self.resolution,
            "bars_replayed": self.bars_replayed,
            "total_entries": self.total_entries,
            "simulated_pnl_cents": round(self.simulated_pnl_cents, 2),
            "edge_model_errors": self.edge_model_errors,
            "elapsed_s": round(self.elapsed_s, 2),
            "signals": [asdict(s) for s in self.signals],
        }


# ── Candle helpers ─────────────────────────────────────────────────────────────

async def _fetch_candles(
    ticker: str,
    years: int,
    resolution: str,
) -> List[Dict[str, Any]]:
    try:
        from merid.backtesting.kalshi_backtest import fetch_kalshi_history
        candles = await fetch_kalshi_history(ticker, years=years, resolution=resolution)
        logger.info("replay: fetched %d candles for %s", len(candles), ticker)
        return candles
    except Exception as exc:
        logger.warning("replay: fetch failed (%s) — returning empty list", exc)
        return []


def _load_csv(path: str) -> List[Dict[str, Any]]:
    import csv
    candles: List[Dict[str, Any]] = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            candles.append({k: float(v) if v else 0.0 for k, v in row.items()})
    logger.info("replay: loaded %d candles from %s", len(candles), path)
    return candles


# ── Edge model probe ───────────────────────────────────────────────────────────

def _score_candle(candle: Dict[str, Any]) -> Dict[str, float]:
    """Call EdgeModel on a single candle.  Returns prob, confidence, edge."""
    try:
        from merid.prediction.edge_model import EdgeModel
        model = EdgeModel()
        result = model.predict(candle)
        prob = float(result.get("probability", 0.5))
        conf = float(result.get("confidence", 0.0))
        edge = abs(prob - 0.5) * 2 * conf
        return {"prob": prob, "confidence": conf, "edge": edge}
    except Exception:
        close = float(candle.get("c") or candle.get("close") or 50)
        prev = float(candle.get("prev_close", close))
        momentum = (close - prev) / prev if prev else 0
        prob = 0.5 + momentum * 0.5
        prob = max(0.01, min(0.99, prob))
        return {"prob": prob, "confidence": 0.3, "edge": abs(prob - 0.5) * 0.6}


# ── Decision rule ──────────────────────────────────────────────────────────────

_ENTRY_EDGE_THRESHOLD = 0.08
_ENTRY_CONF_THRESHOLD = 0.50


def _decide(prob: float, confidence: float, edge: float) -> str:
    if edge < _ENTRY_EDGE_THRESHOLD or confidence < _ENTRY_CONF_THRESHOLD:
        return "hold"
    return "enter_yes" if prob > 0.5 else "enter_no"


# ── Replay runner ──────────────────────────────────────────────────────────────

async def run_replay(
    ticker: str,
    candles: List[Dict[str, Any]],
    resolution: str = "1h",
    max_signals: int = 500,
) -> ReplayReport:
    """Feed candles through EdgeModel and capture signals."""
    report = ReplayReport(ticker=ticker, resolution=resolution, bars_replayed=len(candles))
    t0 = time.monotonic()
    position_entry: Optional[float] = None  # entry price in cents

    for i, candle in enumerate(candles):
        try:
            scores = _score_candle(candle)
        except Exception:
            report.edge_model_errors += 1
            continue

        prob = scores["prob"]
        conf = scores["confidence"]
        edge = scores["edge"]
        decision = _decide(prob, conf, edge)

        close_cents = (float(candle.get("c") or candle.get("close") or 50)) * 100

        # Simulate fill and PnL
        simulated_fill = None
        if decision != "hold":
            report.total_entries += 1
            simulated_fill = close_cents
            if position_entry is not None:
                pnl = (close_cents - position_entry) if decision == "enter_yes" else (position_entry - close_cents)
                report.simulated_pnl_cents += pnl
            position_entry = close_cents

        sig = ReplaySignal(
            bar_index=i,
            timestamp=float(candle.get("ts") or candle.get("timestamp") or i * 3600),
            open=float(candle.get("o") or candle.get("open") or 0),
            high=float(candle.get("h") or candle.get("high") or 0),
            low=float(candle.get("l") or candle.get("low") or 0),
            close=float(candle.get("c") or candle.get("close") or 0),
            model_prob=round(prob, 4),
            confidence=round(conf, 4),
            edge=round(edge, 4),
            decision=decision,
            simulated_fill=round(simulated_fill, 2) if simulated_fill else None,
        )
        report.signals.append(sig)
        if len(report.signals) >= max_signals:
            break

    report.elapsed_s = time.monotonic() - t0
    return report


# ── CLI ────────────────────────────────────────────────────────────────────────

def _print_summary(report: ReplayReport) -> None:
    entries = report.total_entries
    pnl = report.simulated_pnl_cents / 100
    print(f"\n{'='*60}")
    print(f"  Replay: {report.ticker}  ({report.resolution})")
    print(f"{'='*60}")
    print(f"  Bars replayed   : {report.bars_replayed}")
    print(f"  Edge model errors: {report.edge_model_errors}")
    print(f"  Total entries   : {entries}")
    print(f"  Simulated PnL   : ${pnl:+.2f}")
    print(f"  Elapsed         : {report.elapsed_s:.1f}s")
    print(f"{'='*60}\n")
    if report.signals:
        print("  Last 5 signals:")
        for s in report.signals[-5:]:
            print(f"    bar={s.bar_index:4d}  prob={s.model_prob:.3f}  edge={s.edge:.3f}  {s.decision}")
    print()


async def main() -> None:
    parser = argparse.ArgumentParser(description="C3: Replay historical OHLCV through the agent stack")
    parser.add_argument("--ticker", required=True, help="Kalshi market ticker")
    parser.add_argument("--years", type=int, default=1, help="Years of history to fetch")
    parser.add_argument("--resolution", default="1h", help="Candle resolution")
    parser.add_argument("--csv", default="", help="Local CSV path instead of API fetch")
    parser.add_argument("--max-signals", type=int, default=500)
    parser.add_argument("--output", default="", help="Output JSON path (auto if empty)")
    args = parser.parse_args()

    if args.csv:
        candles = _load_csv(args.csv)
    else:
        candles = await _fetch_candles(args.ticker, args.years, args.resolution)

    if not candles:
        print("ERROR: no candle data — aborting replay")
        sys.exit(1)

    report = await run_replay(
        ticker=args.ticker,
        candles=candles,
        resolution=args.resolution,
        max_signals=args.max_signals,
    )
    _print_summary(report)

    out_path = args.output or f"replay_{args.ticker}_{int(time.time())}.json"
    with open(out_path, "w") as f:
        json.dump(report.to_dict(), f, indent=2)
    print(f"  Report saved → {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
