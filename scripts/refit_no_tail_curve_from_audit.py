#!/usr/bin/env python3
"""Re-fit the NO tail curve from real NO-held audit data while keeping the 7-day YES curve.

Reads `reports/decision_to_settlement_audit.csv` (or a similar audit CSV produced
by the live system), fits a per-side PAVA isotonic NO curve from the
closed/fully-settled NO-held rows, and merges it with the existing 7-day YES
calibration from `data/probability_tail_calibration.json`.

Also writes a shadow per-side reliability + π* audit report for the new NO
curve.  This is read-only with respect to exchange/order-router state.  The
output calibration is *not* promoted to `data/probability_tail_calibration.json`
unless `--promote` is passed, so the live process keeps using the old file.

Usage (safe, read-only):
    python scripts/refit_no_tail_curve_from_audit.py

Usage (promote to live default with backup):
    python scripts/refit_no_tail_curve_from_audit.py --promote
"""

import argparse
import csv
import datetime as _dt
import json
import math
import os
import shutil
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents
from merid.risk.probability.tail_calibrator import TailProbabilityCalibrator, _pava_isotonic


# Defaults mirror trade_decision.py
MERID_PI_STAR_TIERED = os.environ.get("MERID_PI_STAR_TIERED", "1").lower() in ("1", "true", "yes")
MERID_PI_STAR_FLAT_PREMIUM_CENTS = int(os.environ.get("MERID_PI_STAR_FLAT_PREMIUM_CENTS", "0"))
MERID_PI_STAR_TIERS_CENTS = os.environ.get("MERID_PI_STAR_TIERS_CENTS", "0:40,20:25,40:10,60:0")

# Promotion thresholds. A per-side NO calibration may not be promoted to the live
# default file unless it passes all of these.  The gate is fail-closed; --force
# bypasses the minimum-sample check for shadow fitting, but promotion still
# requires passing all validation criteria.
MIN_NO_TRADES_PROMOTION = 200
BRIER_THRESHOLD = 0.20
ECE_THRESHOLD = 0.05
MCE_THRESHOLD = 0.10
RELIABILITY_GAP_THRESHOLD = 0.10


def _parse_pi_star_tiers() -> List[Tuple[int, int]]:
    tiers: List[Tuple[int, int]] = []
    for part in MERID_PI_STAR_TIERS_CENTS.split(","):
        if not part:
            continue
        price, premium = part.split(":")
        tiers.append((int(price), int(premium)))
    tiers.sort(key=lambda x: x[0])
    return tiers


def _pi_star_risk_premium(held_price_cents: int) -> int:
    if not MERID_PI_STAR_TIERED:
        return MERID_PI_STAR_FLAT_PREMIUM_CENTS
    tiers = _parse_pi_star_tiers()
    premium = 0
    for price_threshold, tier_premium in tiers:
        if held_price_cents >= price_threshold:
            premium = tier_premium
    return premium


def _pi_star_threshold(held_price_cents: int, fee_cents: int) -> float:
    premium = _pi_star_risk_premium(held_price_cents)
    return (held_price_cents + fee_cents + premium) / 100.0


def _side_items(
    trades: List[Tuple[str, float, int, str]],
    cal: TailProbabilityCalibrator,
) -> Tuple[List[Tuple[float, int]], List[Tuple[float, int]]]:
    """Return (yes_items, no_items) where each item is (calibrated_p, win)."""
    yes: List[Tuple[float, int]] = []
    no: List[Tuple[float, int]] = []
    for held_side, held_price, _, market_result in trades:
        if held_side == "YES":
            p_cal = cal.p_yes(held_price)
            win = 1 if market_result == "yes" else 0
            yes.append((p_cal, win))
        else:
            p_cal = cal.p_no(held_price)
            win = 1 if market_result == "no" else 0
            no.append((p_cal, win))
    return yes, no


def _full_reliability_buckets(
    items: List[Tuple[float, int]],
    n_bins: int = 20,
) -> List[Dict[str, Any]]:
    """Bin calibrated probabilities into equal-width [0,1] bins for a reliability diagram."""
    if not items:
        return []
    bin_width = 1.0 / n_bins
    buckets: List[List[Tuple[float, int]]] = [[] for _ in range(n_bins)]
    for p, w in items:
        bin_idx = min(n_bins - 1, int(p / bin_width))
        buckets[bin_idx].append((p, w))

    out: List[Dict[str, Any]] = []
    for i, bucket in enumerate(buckets):
        lo = i * bin_width
        hi = (i + 1) * bin_width
        if not bucket:
            out.append({
                "bin": f"{lo:.2f}-{hi:.2f}",
                "n": 0,
                "mean_calibrated_p": None,
                "realized_win_rate": None,
                "gap": None,
            })
            continue
        n = len(bucket)
        mean_p = sum(p for p, _ in bucket) / n
        win_rate = sum(w for _, w in bucket) / n
        out.append({
            "bin": f"{lo:.2f}-{hi:.2f}",
            "n": n,
            "mean_calibrated_p": round(mean_p, 4),
            "realized_win_rate": round(win_rate, 4),
            "gap": round(mean_p - win_rate, 4),
        })
    return out


def _ece_mce(
    items: List[Tuple[float, int]],
    n_bins: int = 20,
) -> Tuple[float, float]:
    """Compute Expected Calibration Error (ECE) and Maximum Calibration Error (MCE)."""
    if not items:
        return float("nan"), float("nan")
    bin_width = 1.0 / n_bins
    buckets: List[List[Tuple[float, int]]] = [[] for _ in range(n_bins)]
    for p, w in items:
        bin_idx = min(n_bins - 1, int(p / bin_width))
        buckets[bin_idx].append((p, w))

    total = len(items)
    ece = 0.0
    mce = 0.0
    for bucket in buckets:
        if not bucket:
            continue
        n = len(bucket)
        mean_p = sum(p for p, _ in bucket) / n
        win_rate = sum(w for _, w in bucket) / n
        gap = abs(mean_p - win_rate)
        ece += (n / total) * gap
        mce = max(mce, gap)
    return ece, mce


def _validate_for_promotion(
    cal: TailProbabilityCalibrator,
    no_items: List[Tuple[float, int]],
    yes_items: List[Tuple[float, int]],
    min_no_trades: int = MIN_NO_TRADES_PROMOTION,
    brier_threshold: float = BRIER_THRESHOLD,
    ece_threshold: float = ECE_THRESHOLD,
    mce_threshold: float = MCE_THRESHOLD,
    reliability_gap_threshold: float = RELIABILITY_GAP_THRESHOLD,
) -> Tuple[bool, List[str], Dict[str, Any]]:
    """Fail-closed validation for promoting a per-side NO calibration to live use.

    Returns (passed, errors, diagnostics).
    """
    errors: List[str] = []
    diagnostics: Dict[str, Any] = {}

    # 1. NO curve must be fit on real NO-held data, not the YES dual.
    diagnostics["no_curve_is_dual"] = cal.no_curve_is_dual
    if cal.no_curve_is_dual:
        errors.append(
            "NO curve is the YES dual (1 - p_yes); a real NO-held fit is required for promotion"
        )

    # 2. Sample count threshold.
    n_no = len(no_items)
    n_yes = len(yes_items)
    diagnostics["n_no"] = n_no
    diagnostics["n_yes"] = n_yes
    if n_no < min_no_trades:
        errors.append(
            f"NO-held sample count {n_no} < promotion threshold {min_no_trades}"
        )

    # 3. Brier score.
    no_brier = sum((p - w) ** 2 for p, w in no_items) / n_no if n_no else float("nan")
    diagnostics["no_brier"] = round(no_brier, 4) if not math.isnan(no_brier) else None
    if not math.isnan(no_brier) and no_brier > brier_threshold:
        errors.append(f"NO-side Brier {no_brier:.4f} > threshold {brier_threshold}")

    # 4. ECE / MCE.
    no_ece, no_mce = _ece_mce(no_items)
    diagnostics["no_ece"] = round(no_ece, 4) if not math.isnan(no_ece) else None
    diagnostics["no_mce"] = round(no_mce, 4) if not math.isnan(no_mce) else None
    if not math.isnan(no_ece) and no_ece > ece_threshold:
        errors.append(f"NO-side ECE {no_ece:.4f} > threshold {ece_threshold}")
    if not math.isnan(no_mce) and no_mce > mce_threshold:
        errors.append(f"NO-side MCE {no_mce:.4f} > threshold {mce_threshold}")

    # 5. Per-bucket reliability.
    no_buckets = _full_reliability_buckets(no_items)
    diagnostics["no_reliability_buckets"] = no_buckets
    for bucket in no_buckets:
        if bucket["n"] == 0:
            continue
        gap = bucket["gap"]
        if gap is None:
            continue
        if abs(gap) > reliability_gap_threshold:
            errors.append(
                f"NO reliability bucket {bucket['bin']} gap {gap:+.4f} exceeds "
                f"threshold ±{reliability_gap_threshold} (n={bucket['n']})"
            )

    return (not errors), errors, diagnostics


def _safe_bool(value: Any) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes", "t")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        v = float(value)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _held_from_row(row: Dict[str, Any]) -> Optional[Tuple[str, float, int, str]]:
    """Return (held_side, held_price_dollars, quantity_cc, market_result) for a closed trade.

    Uses the canonical position side/action and the leg price from the audit CSV.
    """
    side = (row.get("canonical_position_side") or "").lower()
    action = (row.get("canonical_position_action") or "").lower()
    price_cents = _safe_int(row.get("canonical_leg_price_cents"), 0)
    if price_cents <= 0 or price_cents > 100:
        return None
    if side not in ("yes", "no") or action not in ("buy", "sell"):
        return None

    # Buy the named side => held is that side at the leg price.
    # Sell the named side => held is the opposite side at 1 - leg price.
    if action == "buy":
        held_side = side.upper()
        held_price_dollars = price_cents / 100.0
    else:
        held_side = "YES" if side == "no" else "NO"
        held_price_dollars = (100 - price_cents) / 100.0

    quantity_cc = _safe_int(row.get("quantity_cc"), 0)
    if quantity_cc <= 0:
        quantity_cc = _safe_int(row.get("quantity_abs_cc"), 0)

    market_result = (row.get("market_result") or "").strip().lower()
    if market_result not in ("yes", "no"):
        return None

    return held_side, held_price_dollars, quantity_cc, market_result


def _load_closed_trades(csv_path: Path) -> List[Tuple[str, float, int, str]]:
    trades: List[Tuple[str, float, int, str]] = []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if not _safe_bool(row.get("is_fully_closed")):
                continue
            held = _held_from_row(row)
            if held:
                trades.append(held)
    return trades


def _fit_no_curve(no_trades: List[Tuple[str, float, int, str]]) -> Tuple[List[float], List[float], int, int]:
    """Fit PAVA isotonic NO curve from (held_side, held_price_dollars, quantity_cc, market_result).

    Returns (held_prices, actual_probs, n_no_wins, n_no_trades).
    """
    prices: List[float] = []
    wins: List[int] = []
    for _, held_price, _, market_result in no_trades:
        prices.append(held_price)
        wins.append(1 if market_result == "no" else 0)

    if len(prices) < 5:
        raise ValueError(f"Need at least 5 NO-held trades to fit, got {len(prices)}")

    xs, ys = _pava_isotonic(prices, wins)
    return xs, ys, sum(wins), len(prices)


def _build_calibrator(
    yes_cal_path: Path,
    no_trades: List[Tuple[float, int, str]],
    buffer: float,
    source_csv: Path,
) -> TailProbabilityCalibrator:
    """Load YES from existing calibration and replace NO with the newly fit curve."""
    with open(yes_cal_path, "r", encoding="utf-8") as f:
        old = TailProbabilityCalibrator.from_dict(json.load(f))

    no_xs, no_ys, no_wins, no_n = _fit_no_curve(no_trades)

    return TailProbabilityCalibrator(
        yes_held_prices=old.yes_held_prices,
        yes_actual_probs=old.yes_actual_probs,
        no_held_prices=no_xs,
        no_actual_probs=no_ys,
        buffer=buffer,
        n_trades=old.n_trades + no_n,
        metadata={
            "source": "refit_no_tail_curve_from_audit",
            "yes_source": str(old.metadata.get("source", "unknown")),
            "no_source": str(source_csv),
            "fit_method": "per_side_pava_isotonic_regression",
            "held_side": "both",
            "yes_n_trades": old.n_trades,
            "no_n_trades": no_n,
            "no_wins": no_wins,
            "buffer": buffer,
            "refit_at_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        },
    )


def _reliability_buckets(trades: List[Tuple[str, float, int, str]], cal: TailProbabilityCalibrator) -> List[Dict[str, Any]]:
    """Bucket trades by calibrated p and compare to realized win rate."""
    buckets: Dict[str, List[Tuple[float, int]]] = {}
    for held_side, held_price, _, market_result in trades:
        if held_side == "YES":
            p_cal = cal.p_yes(held_price)
            win = 1 if market_result == "yes" else 0
        else:
            p_cal = cal.p_no(held_price)
            win = 1 if market_result == "no" else 0

        # 0.05-wide buckets from 0.50 to 1.00
        bucket_idx = min(9, int((p_cal - 0.50) / 0.05))
        bucket_idx = max(0, bucket_idx)
        lo = 0.50 + bucket_idx * 0.05
        hi = lo + 0.05
        key = f"{lo:.2f}-{hi:.2f}"
        buckets.setdefault(key, []).append((p_cal, win))

    def _key_sort(k: str) -> float:
        return float(k.split("-")[0])

    out: List[Dict[str, Any]] = []
    for key in sorted(buckets, key=_key_sort):
        items = buckets[key]
        n = len(items)
        mean_p = sum(p for p, _ in items) / n
        win_rate = sum(w for _, w in items) / n
        out.append({
            "bucket": key,
            "n": n,
            "mean_calibrated_p": round(mean_p, 4),
            "realized_win_rate": round(win_rate, 4),
            "gap": round(mean_p - win_rate, 4),
        })
    return out


def _per_side_summary(
    yes_items: List[Tuple[float, int]],
    no_items: List[Tuple[float, int]],
) -> Dict[str, Any]:
    def _summ(items: List[Tuple[float, int]]) -> Dict[str, Any]:
        if not items:
            return {
                "n": 0,
                "mean_calibrated_p": None,
                "realized_win_rate": None,
                "brier": None,
                "ece": None,
                "mce": None,
            }
        n = len(items)
        mean_p = sum(p for p, _ in items) / n
        win_rate = sum(w for _, w in items) / n
        brier = sum((p - w) ** 2 for p, w in items) / n
        ece, mce = _ece_mce(items)
        return {
            "n": n,
            "mean_calibrated_p": round(mean_p, 4),
            "realized_win_rate": round(win_rate, 4),
            "brier": round(brier, 4),
            "ece": round(ece, 4),
            "mce": round(mce, 4),
        }

    return {"yes_side": _summ(yes_items), "no_side": _summ(no_items)}


def _pi_star_audit(
    trades: List[Tuple[str, float, int, str]],
    cal: TailProbabilityCalibrator,
) -> Dict[str, Any]:
    """Approximate π* gate using the calibrated probability as p_selected.

    This is a shadow check: it shows, had the model trusted the calibrated
    win probability, what fraction of trades would clear the π* EV gate and
    what their realized win rate would be.
    """
    pass_trades: List[int] = []
    all_trades: List[int] = []
    for held_side, held_price, quantity_cc, market_result in trades:
        held_price_cents = int(round(held_price * 100))
        contracts = max(1, quantity_cc // 100)
        fee_cents = calculate_kalshi_fee_cents(contracts, held_price_cents)
        pi_threshold = _pi_star_threshold(held_price_cents, fee_cents)

        if held_side == "YES":
            p_cal = cal.p_yes(held_price)
            win = 1 if market_result == "yes" else 0
        else:
            p_cal = cal.p_no(held_price)
            win = 1 if market_result == "no" else 0

        all_trades.append(win)
        if p_cal >= pi_threshold - 1e-9:
            pass_trades.append(win)

    n_all = len(all_trades)
    n_pass = len(pass_trades)
    return {
        "n_all": n_all,
        "all_win_rate": round(sum(all_trades) / n_all, 4) if n_all else None,
        "n_pass": n_pass,
        "pass_win_rate": round(sum(pass_trades) / n_pass, 4) if n_pass else None,
        "pass_rate": round(n_pass / n_all, 4) if n_all else None,
        "note": "p_selected approximated by the per-side calibrated probability; fee from Kalshi formula",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-fit NO tail curve from real audit data")
    parser.add_argument(
        "--audit-csv",
        type=Path,
        default=Path("reports/decision_to_settlement_audit.csv"),
        help="Decision-to-settlement audit CSV with canonical_position_side, canonical_position_action, canonical_leg_price_cents, market_result",
    )
    parser.add_argument(
        "--yes-cal",
        type=Path,
        default=Path("data/probability_tail_calibration.json"),
        help="Existing calibration whose YES curve will be preserved",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output calibration JSON path (default: reports/probability_tail_calibration_per_side_<ts>.json)",
    )
    parser.add_argument(
        "--audit-out",
        type=Path,
        default=None,
        help="Output audit JSON path (default: reports/no_tail_refit_audit_<ts>.json)",
    )
    parser.add_argument("--buffer", type=float, default=0.05, help="Calibration cap buffer")
    parser.add_argument("--min-no-trades", type=int, default=50, help="Minimum NO trades to proceed without --force")
    parser.add_argument("--force", action="store_true", help="Proceed even with small NO sample")
    parser.add_argument(
        "--promote",
        action="store_true",
        help=f"Also copy the output to {Path('data/probability_tail_calibration.json')} (backs up the old file)",
    )
    args = parser.parse_args()

    if not args.audit_csv.exists():
        print(f"ERROR: audit CSV not found: {args.audit_csv}")
        return 1
    if not args.yes_cal.exists():
        print(f"ERROR: YES calibration not found: {args.yes_cal}")
        return 1

    trades = _load_closed_trades(args.audit_csv)
    no_trades = [t for t in trades if t[0] == "NO"]
    yes_trades = [t for t in trades if t[0] == "YES"]

    print(f"Closed trades in {args.audit_csv}: {len(trades)}")
    print(f"  YES-held: {len(yes_trades)}")
    print(f"  NO-held:  {len(no_trades)}")

    if len(no_trades) < args.min_no_trades and not args.force:
        print(
            f"ERROR: only {len(no_trades)} NO-held trades (min={args.min_no_trades}). "
            "Pass --force to fit anyway, or collect more data in a paper/live window."
        )
        return 2

    cal = _build_calibrator(args.yes_cal, no_trades, args.buffer, args.audit_csv)
    yes_items, no_items = _side_items(trades, cal)

    # Fail-closed promotion validation.  Even without --promote we compute it
    # and include the result in the audit so operators can see the gate state.
    promotion_ok, promotion_errors, promotion_diagnostics = _validate_for_promotion(
        cal, no_items, yes_items
    )

    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = args.output or Path(f"reports/probability_tail_calibration_per_side_{ts}.json")
    audit_path = args.audit_out or Path(f"reports/no_tail_refit_audit_{ts}.json")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(cal.to_dict(), f, indent=2, default=str)
    print(f"Wrote per-side calibration: {output_path}")

    if args.promote:
        if not promotion_ok:
            print("ERROR: promotion validation failed; the new NO curve was NOT promoted:")
            for err in promotion_errors:
                print(f"  - {err}")
            return 3
        live_path = Path("data/probability_tail_calibration.json")
        if live_path.exists():
            backup = live_path.with_suffix(f".json.bak.{ts}")
            shutil.copy2(live_path, backup)
            print(f"Backed up live calibration: {backup}")
        shutil.copy2(output_path, live_path)
        print(f"Promoted to live calibration: {live_path}")

    # Shadow audit
    yes_buckets = _reliability_buckets(yes_trades, cal)
    no_buckets = _reliability_buckets(no_trades, cal)
    yes_full_buckets = _full_reliability_buckets(yes_items)
    no_full_buckets = _full_reliability_buckets(no_items)
    per_side = _per_side_summary(yes_items, no_items)
    pi_star = _pi_star_audit(trades, cal)

    audit = {
        "_meta": {
            "generated_at_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "audit_csv": str(args.audit_csv),
            "yes_cal_source": str(args.yes_cal),
            "output_calibration": str(output_path),
            "note": "In-sample audit on the same trades used to fit NO; hold-out / paper window required for conclusive validation",
        },
        "sample_counts": {
            "total_closed": len(trades),
            "yes_held": len(yes_trades),
            "no_held": len(no_trades),
        },
        "promotion_validation": {
            "passed": promotion_ok,
            "errors": promotion_errors,
            "diagnostics": promotion_diagnostics,
            "thresholds": {
                "min_no_trades": MIN_NO_TRADES_PROMOTION,
                "brier": BRIER_THRESHOLD,
                "ece": ECE_THRESHOLD,
                "mce": MCE_THRESHOLD,
                "reliability_gap": RELIABILITY_GAP_THRESHOLD,
            },
        },
        "per_side_summary": per_side,
        "yes_buckets": yes_buckets,
        "no_buckets": no_buckets,
        "yes_full_reliability": yes_full_buckets,
        "no_full_reliability": no_full_buckets,
        "pi_star_gate": pi_star,
    }

    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, default=str)
    print(f"Wrote shadow audit report: {audit_path}")

    print("\nNew NO curve (held NO price -> actual P(NO wins)):")
    for x, y in zip(cal.no_held_prices, cal.no_actual_probs):
        print(f"  ${x:.2f} -> {y:.3f}")

    if cal.no_curve_is_dual:
        print("\nWARNING: the new NO curve is still the YES dual (1 - p_yes).")
        print("         Check that the input CSV really contains NO-held decisions.")
    else:
        print("\nNew NO curve is NOT the YES dual.")

    print(f"\nPer-side Brier (lower is better):")
    print(f"  YES: {audit['per_side_summary']['yes_side']['brier']}")
    print(f"  NO:  {audit['per_side_summary']['no_side']['brier']}")

    print(f"\nPer-side ECE / MCE (lower is better):")
    print(f"  YES: ECE={audit['per_side_summary']['yes_side']['ece']}, MCE={audit['per_side_summary']['yes_side']['mce']}")
    print(f"  NO:  ECE={audit['per_side_summary']['no_side']['ece']}, MCE={audit['per_side_summary']['no_side']['mce']}")

    print(f"\nPromotion validation: {'PASSED' if promotion_ok else 'FAILED'}")
    if not promotion_ok:
        print("Errors:")
        for err in promotion_errors:
            print(f"  - {err}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
