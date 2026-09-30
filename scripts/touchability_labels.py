"""Touchability / execution-feasibility labels for threshold-cell candidates.

DATA-ONLY.  Answers the compiler's stage-3 question honestly: could a
strictly-passive post-only order at the counterfactual's price plausibly
have filled?  Two evidence sources:

  1. Historical — forward book evolution in strategy_decision_snapshots.
     For each in-domain counterfactual row (asset, side, ticker, ts, px),
     the decision-time book must be trusted and we scan later snapshots on
     the same ticker inside a bounded window for the opposite-side ask to
     reach the resting limit.

  2. Live — logs/threshold_cell_lifecycle.jsonl funnel counters plus
     data/kalshi_order_attempts.db order outcomes, joined by decision_id /
     cell_id.  Live passive attempts are the primary evidence once the
     PROVISIONAL cells are running; historical labels only gate promotion.

NO FABRICATION RULE: rows without enough forward book coverage are labelled
UNKNOWN_BOOK_HISTORY and excluded from the touchable-rate denominator.  A
cell whose informative sample is too small stays FILL_FEASIBILITY_UNKNOWN —
it does not pass, and it does not fail.  The compiler caps such cells at
CANDIDATE_PENDING_EXECUTION_FEASIBILITY.

Venue mapping: BUY NO at p  <=>  SELL YES at 100-p.  A resting NO bid at
limit L fills passively when the NO ask descends to L (equivalently the
YES bid rises to 100-L).  We therefore test ``min forward no_ask <= L``.

Row labels (per user's promotion spec):
  TOUCHABLE             forward ask reached the resting limit
  NOT_TOUCHABLE         full window covered, ask never reached the limit
  UNKNOWN_BOOK_HISTORY  insufficient forward coverage to distinguish
  STALE_BOOK            decision-time or forward book untrusted/crossed
  CROSSING_ONLY         book already crossed at decision time (no passive
                        placement exists at that price)
  EXPIRED_BEFORE_TOUCH  market closed before the touch window elapsed

Cell verdicts (aggregate over informative rows only):
  TOUCHABILITY_PASS         rate>=MIN_TOUCH_RATE and LCB10-1c>0
  TOUCHABILITY_FAIL         enough data, gate failed
  FILL_FEASIBILITY_UNKNOWN  informative_n < MIN_TOUCH_N
"""

import json
import os
import sqlite3
from collections import defaultdict

DB = "data/decision_audit.db"
ATTEMPTS_DB = "data/kalshi_order_attempts.db"
LIFECYCLE = "logs/threshold_cell_lifecycle.jsonl"
ROWS = "data/cell_discovery_rows.jsonl"

# Passive placement: one cent inside the observed executable ask — the same
# construction the live post-only lane uses (XRP fill repriced 85c -> 82c).
PASSIVE_TICK_C = 1.0

# A resting order at decision time gets up to WINDOW_S of forward book
# coverage; the live lane TTL is shorter but this is an upper bound on
# counterfactual plausibility.
WINDOW_S = 60.0
MIN_WINDOW_S = 10.0          # don't score rows with a sliver of window
EXPIRY_GUARD_S = 5.0         # ignore the final seconds before close
STALE_BOOK_MS = 3000.0       # book_age_ms beyond this is untrusted
COVERAGE_FRACTION = 0.5      # forward snapshots must span >=50% of window
MIN_FORWARD_SNAPS = 2        # need at least this many to claim NOT_TOUCHABLE

# Stage-3 promotion gate (user-specified strict initial values).
MIN_TOUCH_N = 20
MIN_TOUCH_RATE = 0.20
MIN_TOUCHABLE_LCB10_STRESS_C = 0.0   # lcb10 of touchable PnL minus +1c > 0

LABELS = (
    "TOUCHABLE", "NOT_TOUCHABLE", "UNKNOWN_BOOK_HISTORY",
    "STALE_BOOK", "CROSSING_ONLY", "EXPIRED_BEFORE_TOUCH",
)
INFORMATIVE = ("TOUCHABLE", "NOT_TOUCHABLE", "CROSSING_ONLY",
               "EXPIRED_BEFORE_TOUCH")


def _lcb10(pnls):
    """mean - 1.2816 * se, matching the discovery report's bound."""
    n = len(pnls)
    if n == 0:
        return None
    mean = sum(pnls) / n
    var = sum((x - mean) ** 2 for x in pnls) / n
    return mean - 1.2816 * (var ** 0.5) / (n ** 0.5)


def _side_cols(side):
    return ("no_ask", "no_bid") if side == "no" else ("yes_ask", "yes_bid")


def _load_ticker_books(conn, tickers):
    """ticker -> chronologically sorted list of per-decision book rows."""
    books = {}
    q = """
        SELECT d.decision_ts, s.yes_bid_cents, s.yes_ask_cents,
               s.no_bid_cents, s.no_ask_cents, s.book_age_ms,
               s.book_is_crossed, s.book_is_executable, s.book_sequence
        FROM strategy_decision_snapshots s
        JOIN strategy_decisions d ON d.decision_id = s.decision_id
        WHERE d.ticker = ?
        ORDER BY d.decision_ts
    """
    for tick in tickers:
        books[tick] = [
            {
                "ts": r[0], "yes_bid": r[1], "yes_ask": r[2],
                "no_bid": r[3], "no_ask": r[4], "age_ms": r[5],
                "crossed": r[6], "exec": r[7], "seq": r[8],
            }
            for r in conn.execute(q, (tick,))
        ]
    return books


def classify_row(row, book):
    """Label one counterfactual row against its ticker's forward book."""
    side = row["side"]
    ask_col, bid_col = _side_cols(side)
    ts = float(row["ts"])
    px = float(row["px"])
    close_ts = row.get("close_ts")
    limit = px - PASSIVE_TICK_C          # strictly passive resting price
    window = WINDOW_S
    if close_ts is not None:
        window = min(window, float(close_ts) - ts - EXPIRY_GUARD_S)

    if not book:
        return "UNKNOWN_BOOK_HISTORY", None

    # Decision-time book = last snapshot at-or-before ts.
    cur = None
    for b in book:
        if b["ts"] <= ts + 1e-6:
            cur = b
        else:
            break
    if cur is None:
        return "UNKNOWN_BOOK_HISTORY", None
    if cur["crossed"] or cur["exec"] == 0:
        return "STALE_BOOK", None
    if cur["age_ms"] is not None and float(cur["age_ms"]) > STALE_BOOK_MS:
        return "STALE_BOOK", None
    bid0, ask0 = cur[bid_col], cur[ask_col]
    if ask0 is None or bid0 is None:
        return "UNKNOWN_BOOK_HISTORY", None
    if float(bid0) >= float(ask0):
        # Crossed-through quote at decision time: no passive price exists.
        return "CROSSING_ONLY", None

    if window <= 0:
        return "EXPIRED_BEFORE_TOUCH", None

    fwd = [b for b in book if ts < b["ts"] <= ts + window]
    if not fwd:
        if close_ts is not None and float(close_ts) - ts <= WINDOW_S + EXPIRY_GUARD_S:
            return "EXPIRED_BEFORE_TOUCH", None
        return "UNKNOWN_BOOK_HISTORY", None

    n_stale = sum(
        1 for b in fwd
        if b["crossed"] or (b["age_ms"] is not None
                            and float(b["age_ms"]) > STALE_BOOK_MS)
    )
    if fwd and n_stale / len(fwd) > 0.5:
        return "STALE_BOOK", None

    span = fwd[-1]["ts"] - fwd[0]["ts"]
    covered = len(fwd) >= MIN_FORWARD_SNAPS and (
        window < MIN_WINDOW_S or span >= COVERAGE_FRACTION * window
    )

    asks = [float(b[ask_col]) for b in fwd if b[ask_col] is not None]
    touched = bool(asks) and min(asks) <= limit
    if touched:
        return "TOUCHABLE", limit
    if not covered:
        return "UNKNOWN_BOOK_HISTORY", limit
    return "NOT_TOUCHABLE", limit


def cell_verdict(labels, pnls):
    """Aggregate row labels -> stage-3 cell verdict + metrics."""
    counts = {l: 0 for l in LABELS}
    for l in labels:
        counts[l] = counts.get(l, 0) + 1
    informative = sum(counts[l] for l in INFORMATIVE)
    touch_pnls = [p for l, p in zip(labels, pnls) if l == "TOUCHABLE"]
    rate = (counts["TOUCHABLE"] / informative) if informative else None
    lcb = _lcb10(touch_pnls)
    if informative < MIN_TOUCH_N:
        verdict = "FILL_FEASIBILITY_UNKNOWN"
    elif rate is not None and rate < MIN_TOUCH_RATE:
        verdict = "TOUCHABILITY_FAIL"
    elif lcb is None or lcb - 1.0 <= MIN_TOUCHABLE_LCB10_STRESS_C:
        verdict = "TOUCHABILITY_FAIL"
    else:
        verdict = "TOUCHABILITY_PASS"
    return {
        "verdict": verdict,
        "label_counts": counts,
        "informative_n": informative,
        "touchable_rate": round(rate, 4) if rate is not None else None,
        "touchable_lcb10_cents": round(lcb, 3) if lcb is not None else None,
    }


def live_attempts(lifecycle_path=LIFECYCLE):
    """Live measurement feed: lifecycle funnel counts + order outcomes per
    cell.  Unknown when a stage never fired — never fabricated."""
    cells = defaultdict(lambda: defaultdict(int))
    if os.path.exists(lifecycle_path):
        with open(lifecycle_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                cid = ev.get("threshold_cell_id")
                stage = ev.get("stage")
                if cid and stage:
                    cells[cid][stage] += 1
                # funnel block carries cumulative counters — take the max
                # seen rather than summing (each event repeats history).
                fun = ev.get("funnel") or {}
                if cid and isinstance(fun, dict):
                    for k, v in fun.items():
                        try:
                            cells[cid][f"funnel_{k}"] = max(
                                cells[cid][f"funnel_{k}"], int(v or 0)
                            )
                        except Exception:
                            pass
    out = {}
    for cid, c in cells.items():
        emitted = c.get("candidate_emitted") or c.get("funnel_emitted")
        filled = c.get("filled") or c.get("funnel_filled")
        submitted = c.get("submitted") or c.get("funnel_submitted")
        out[cid] = dict(c)
        out[cid]["live_fill_rate"] = (
            round(filled / submitted, 4)
            if submitted and filled is not None else None
        )
        out[cid]["live_submission_rate"] = (
            round(submitted / emitted, 4)
            if emitted and submitted is not None else None
        )
    return out


def classify_all(rows_path=ROWS, db_path=DB):
    """Label every in-domain discovery row; returns bucket -> verdict."""
    rows = []
    with open(rows_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    if not rows:
        return {}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        books = _load_ticker_books(conn, {r["ticker"] for r in rows})
    finally:
        conn.close()

    per_bucket = defaultdict(lambda: {"labels": [], "pnls": []})
    for r in rows:
        label, _limit = classify_row(r, books.get(r["ticker"]))
        b = per_bucket[r["bucket"]]
        b["labels"].append(label)
        b["pnls"].append(float(r["cf"]))

    return {
        bucket: cell_verdict(v["labels"], v["pnls"])
        for bucket, v in per_bucket.items()
    }


if __name__ == "__main__":
    import sys
    res = classify_all(*sys.argv[1:])
    print(json.dumps(res, indent=1, sort_keys=True))
