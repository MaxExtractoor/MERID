"""Conviction-band report: net PnL by |p_cal - 0.5| bands.

Answers the calibration question for the post_drawdown conviction gate: is
the per-asset distance floor too strict or too loose for current-build fills?

Bands (|p_selected - 0.5|):  0.00-0.04 / 0.04-0.06 / 0.06-0.08 / 0.08-0.12 / >0.12
Segments: asset x side x conviction band, plus price bucket, TTE bucket,
and regime (--by-price / --by-tte / --by-regime stack additively).

Data source: data/decision_audit.db — strategy_decision_side_ev joined to
strategy_decision_outcomes (realized PnL) and strategy_decisions
(policy_epoch, dir_regime).  Counterfactual/never-filled rows are excluded;
only decisions with a realized outcome count.

Usage:
    python scripts/_conviction_band_report.py [--epoch EPOCH]
        [--by-regime] [--by-price] [--by-tte]
"""
import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.environ.get("MERID_DECISION_AUDIT_DB_PATH", "data/decision_audit.db")

BANDS = [
    ("0.00-0.04", 0.00, 0.04),
    ("0.04-0.06", 0.04, 0.06),
    ("0.06-0.08", 0.06, 0.08),
    ("0.08-0.12", 0.08, 0.12),
    (">0.12", 0.12, 99.0),
]


def _band(dist: float) -> str:
    for name, lo, hi in BANDS:
        if lo <= dist < hi:
            return name
    return ">0.12"


# Executable-price buckets aligned to the live domain bands (skewed_low /
# transition / balanced / transition_high / skewed_high / trend_yes_hi /
# disabled tail).
PRICE_BUCKETS = [
    ("<=9c", None, 10),
    ("10-19c", 10, 20),
    ("20-34c", 20, 35),
    ("35-65c", 35, 66),
    ("66-85c", 66, 86),
    ("86-90c", 86, 91),
    ("91-94c", 91, 95),
    ("95c+", 95, None),
]

TTE_BUCKETS = [
    ("<120s", None, 120),
    ("120-300s", 120, 300),
    ("300-600s", 300, 600),
    (">600s", 600, None),
]


def _bucket(value, buckets) -> str:
    if value is None:
        return "n/a"
    v = float(value)
    for name, lo, hi in buckets:
        if (lo is None or v >= lo) and (hi is None or v < hi):
            return name
    return buckets[-1][0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epoch", default=os.environ.get("MERID_POLICY_EPOCH", "post_drawdown_2026-10-01"))
    ap.add_argument("--by-regime", action="store_true")
    ap.add_argument("--by-price", action="store_true")
    ap.add_argument("--by-tte", action="store_true")
    ap.add_argument("--all-epochs", action="store_true", help="ignore epoch filter (includes legacy rows)")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # settled decisions with realized PnL + per-side calibrated probability.
    # The selected side's side_ev row carries the p the gates saw.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(strategy_decisions)")}
    regime_col = "d.dir_regime" if "dir_regime" in cols else "NULL"
    rows = conn.execute(
        f"""
        SELECT d.asset, d.selected_side AS side,
               e.calibrated_probability AS p_sel,
               e.executable_entry_price_cents AS price_c,
               o.realized_net_pnl_cents AS pnl,
               {regime_col} AS dir_regime,
               d.seconds_to_close AS tte
        FROM strategy_decision_outcomes o
        JOIN strategy_decisions d ON d.decision_id = o.decision_id
        LEFT JOIN strategy_decision_side_ev e
               ON e.decision_id = o.decision_id AND e.side = d.selected_side
        WHERE o.realized_net_pnl_cents IS NOT NULL
          AND d.selected_side IS NOT NULL
        {"AND d.policy_epoch = ?" if not args.all_epochs else ""}
        """,
        (() if args.all_epochs else (args.epoch,)),
    ).fetchall()

    buckets = {}
    for r in rows:
        p = r["p_sel"]
        dist = abs(float(p) - 0.5) if p is not None else None
        band = _band(dist) if dist is not None else "no_p"
        key = (r["asset"], r["side"], band)
        if args.by_price:
            key = key + (_bucket(r["price_c"], PRICE_BUCKETS),)
        if args.by_tte:
            key = key + (_bucket(r["tte"], TTE_BUCKETS),)
        if args.by_regime:
            key = key + (r["dir_regime"] or "n/a",)
        b = buckets.setdefault(key, {"n": 0, "wins": 0, "pnl": 0.0})
        b["n"] += 1
        b["wins"] += 1 if (r["pnl"] or 0.0) > 0 else 0
        b["pnl"] += float(r["pnl"] or 0.0)

    hdr = f"{'asset':5} {'side':4} {'|p-0.5|':>9}"
    if args.by_price:
        hdr += "  px_bucket"
    if args.by_tte:
        hdr += "  tte_bucket"
    if args.by_regime:
        hdr += "  regime"
    hdr += "  n    win%    net_pnl_c"
    print(hdr)
    print("-" * len(hdr))
    for key in sorted(buckets):
        b = buckets[key]
        asset, side, band = key[:3]
        extra = ""
        for i, on in enumerate((args.by_price, args.by_tte, args.by_regime)):
            if on:
                extra += f"  {key[3 + i]:<10}"
        print(
            f"{asset:5} {side:4} {band:>9}{extra}  {b['n']:3}  "
            f"{100.0*b['wins']/b['n']:5.1f}  {b['pnl']:+9.2f}"
        )
    print(f"\ntotal settled rows: {len(rows)} (epoch={'ALL' if args.all_epochs else args.epoch})")


if __name__ == "__main__":
    main()
