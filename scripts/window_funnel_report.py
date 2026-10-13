#!/usr/bin/env python3
"""Per-window candidate funnel report — standing audit, not an ad-hoc slice.

Reconstructs the full candidate funnel from ``data/decision_audit.db``:

    book snapshots
      -> unique episodes (candidate_id)
      -> model evaluations (decision rows = candidate x route)
      -> economically positive candidates ({side}_positive_ev passed)
      -> evidence/veto survivors (evidence + structural gates passed)
      -> emission-grade candidates (decision = ENTER)
      -> wire attempts (ORDER_SUBMITTED | ROUTER_REJECTED events)
      -> accepted orders (ORDER_SUBMITTED)
      -> fills (ORDER_FILLED)
      -> settled P&L (realized for fills, counterfactual for rejects)

Every stage is split by asset, side, TTE bucket, route, and settled W/L
where an outcome row exists.  Rejected candidates get a *marginal block*
attribution: the first failed gate in evaluation order — the cohort that
"passed all prior gates" — so the report ranks which gate is actually
costing volume instead of blaming gate classes collectively.

Design notes
------------
* ``strategy_decisions.gate_results_json`` is the authoritative gate
  vector (insertion order = evaluation order); ``all_failed_gates_json``
  is the set of failures (including non-blocking ones a lane overrode).
* ``strategy_decision_events`` is the append-only lifecycle; only
  emitted candidates generate downstream events, so the events join is
  bounded to the emitted subset via ``decision_id IN (...)`` chunks.
* ``strategy_decision_outcomes`` is joined via the ``settled_at`` index —
  one range scan, then local membership filtering.  Counterfactual P&L
  columns value rejected candidates at decision-time quotes.
* The live DB runs WAL under an active writer; ``--snapshot`` uses the
  SQLite backup API to copy the database first (recommended for the
  multi-week windows this report is built for).  The snapshot includes
  committed WAL contents as of the copy.

Usage::

    python scripts/window_funnel_report.py --days 14
    python scripts/window_funnel_report.py --days 28 --snapshot --out funnel.json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import time
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, Optional, Set, Tuple

try:
    import orjson as _fastjson

    _loads = _fastjson.loads
except ImportError:  # pragma: no cover - fallback for minimal envs
    _loads = json.loads

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(REPO_ROOT, "data", "decision_audit.db")

ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")
SIDES = ("yes", "no")

# Ordered lifecycle stages for the headline funnel.  ``key`` values are
# used as dict keys in the per-candidate furthest-stage record.
STAGE_EPISODE = "unique_episodes"
STAGE_EVAL = "model_evaluations"
STAGE_POS_EV = "positive_net_edge"
STAGE_VETO_SURV = "evidence_veto_survivors"
STAGE_EMIT = "emitted"
STAGE_WIRE = "wire_attempts"
STAGE_ACCEPTED = "router_accepted"
STAGE_FILLED = "filled"
STAGE_SETTLED = "settled"

FUNNEL_ORDER = [
    STAGE_EPISODE,
    STAGE_EVAL,
    STAGE_POS_EV,
    STAGE_VETO_SURV,
    STAGE_EMIT,
    STAGE_WIRE,
    STAGE_ACCEPTED,
    STAGE_FILLED,
    STAGE_SETTLED,
]
_STAGE_RANK = {s: i for i, s in enumerate(FUNNEL_ORDER)}

# Gates counted as "evidence / structural veto" for the survivor stage —
# per-side prefixed names ({yes|no}_gate) plus shared pre-decision
# evidence gates.  Order within a side is the pipeline order observed in
# gate_results_json.
_VETO_GATES = (
    "evidence",
    "tail_guard",
    "moneyness",
    "regime",
    "book_flow",
    "conviction",
    "qualified",
)

# TTE bucket edges (seconds_to_close at evaluation time).
_TTE_BUCKETS = ((0, 120), (120, 300), (300, 600), (600, 10**9))


def _tte_bucket(tte: Optional[float]) -> str:
    if tte is None:
        return "tte_?"
    for lo, hi in _TTE_BUCKETS:
        if lo <= tte < hi:
            return f"{lo}-{hi}s" if hi < 10**9 else f">={lo}s"
    return "tte_?"


def _connect(path: str) -> sqlite3.Connection:
    uri_path = os.path.abspath(path).replace("\\", "/")
    if not uri_path.startswith("/"):
        uri_path = "/" + uri_path  # -> file:///C:/... on Windows
    conn = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def _copy_locked(src: str, dst: str) -> None:
    """Copy a file the live process holds open.

    On Windows the server opens the WAL files without granting
    read-sharing to plain ``open()`` callers, so ``shutil.copyfile``
    fails with PermissionError.  Open the source via CreateFileW with
    FILE_SHARE_READ|FILE_SHARE_WRITE instead.
    """
    import shutil

    if os.name == "nt":
        import ctypes
        import msvcrt

        GENERIC_READ = 0x80000000
        SHARE_RW = 0x1 | 0x2
        OPEN_EXISTING = 3
        INVALID = ctypes.c_void_p(-1).value
        k32 = ctypes.windll.kernel32
        k32.CreateFileW.restype = ctypes.c_void_p
        h = k32.CreateFileW(
            os.path.abspath(src), GENERIC_READ, SHARE_RW, None,
            OPEN_EXISTING, 0, None,
        )
        if h == INVALID or h is None:
            raise OSError(f"CreateFile failed on {src}")
        try:
            fd = msvcrt.open_osfhandle(h, os.O_RDONLY)
        except Exception:
            k32.CloseHandle(ctypes.c_void_p(h))
            raise
        with os.fdopen(fd, "rb", closefd=True) as fsrc, open(dst, "wb") as fdst:
            shutil.copyfileobj(fsrc, fdst, 4 * 1024 * 1024)
    else:
        shutil.copyfile(src, dst)


def _snapshot(src_path: str) -> str:
    """Crash-consistent copy of the live WAL-mode DB.

    ``Connection.backup()`` starves under this writer (it retries
    indefinitely while pages keep changing).  A file-level copy of the
    ``db`` + ``-wal`` + ``-shm`` trio is crash-consistent instead: on
    first open, SQLite replays the copied WAL and exposes every
    transaction committed as of copy time.  The copy may be marginally
    newer than the moment it started — fine for analytics.
    """
    fd, dst_path = tempfile.mkstemp(
        prefix="decision_audit_snapshot_", suffix=".db"
    )
    os.close(fd)
    t0 = time.time()
    # Copy -wal first so its frames are at least as new as the db image.
    # -shm is deliberately skipped: it is a memory-mapped wal-index cache
    # (unreadable while the writer maps it) that SQLite rebuilds on open.
    for suffix in ("-wal", ""):
        src = src_path + suffix
        if not os.path.exists(src):
            if suffix:
                continue
            raise FileNotFoundError(src)
        _copy_locked(src, dst_path + suffix)
    print(
        f"[funnel] snapshot {os.path.getsize(dst_path)/1e6:.0f} MB "
        f"(+wal) in {time.time()-t0:.0f}s -> {dst_path}",
        file=sys.stderr,
    )
    return dst_path


def _chunks(seq: Iterable[str], size: int = 400) -> Iterable[Tuple[str, ...]]:
    buf = []
    for x in seq:
        buf.append(x)
        if len(buf) >= size:
            yield tuple(buf)
            buf = []
    if buf:
        yield tuple(buf)


def _side_from_gates(gates: Dict[str, Any]) -> Tuple[str, ...]:
    """Sides whose gate-prefixed checks appear in this row's vector."""
    out = []
    for s in SIDES:
        if any(k.startswith(f"{s}_") for k in gates):
            out.append(s)
    return tuple(out)


def _side_gate_verdicts(
    gates: Dict[str, Any], side: str
) -> Dict[str, Optional[bool]]:
    """Ordered {gate_suffix: passed} for one side + shared (unprefixed) gates."""
    verdicts: Dict[str, Optional[bool]] = {}
    for name, gv in gates.items():
        if not isinstance(gv, dict):
            continue
        if name.startswith(f"{side}_"):
            verdicts[name[len(side) + 1:]] = gv.get("passed")
        elif not name.startswith("yes_") and not name.startswith("no_"):
            verdicts[name] = gv.get("passed")
    return verdicts


def _first_failed_gate(verdicts: Dict[str, Optional[bool]]) -> Optional[str]:
    """First gate in evaluation order that explicitly failed."""
    for name, passed in verdicts.items():
        if passed is False:
            return name
    return None


def _passed(verdicts: Dict[str, Optional[bool]], name: str) -> bool:
    return verdicts.get(name) is True


class Funnel:
    """Streaming aggregation state for the decisions window."""

    def __init__(self) -> None:
        # per-candidate furthest funnel rank + identity facts
        self.cand_stage: Dict[str, int] = {}
        self.cand_asset: Dict[str, str] = {}
        self.cand_ticker: Dict[str, str] = {}
        self.cand_side: Dict[str, Set[str]] = {}
        self.cand_tte: Dict[str, str] = {}
        self.cand_day: Dict[str, str] = {}

        self.eval_rows = 0
        self.eval_rows_by_asset = Counter()
        self.eval_rows_by_route = Counter()
        self.candidates_by_asset = defaultdict(set)
        self.candidates_by_day = defaultdict(set)

        # per-(asset, side) stage counters — a candidate counts once per
        # stage it reached for that side.
        self.stage_asset_side = Counter()  # (stage, asset, side) -> n

        # marginal-block attribution: first failed gate per rejected row
        self.first_fail = Counter()          # (gate, asset, side) -> n
        self.co_failed = Counter()           # gate -> n rows listing it

        # emitted subset for downstream joins
        self.emitted_decisions: Set[str] = set()
        self.emit_by_asset_side = Counter()
        self.emit_by_lane = Counter()

        # downstream stage facts filled by the events pass
        self.wire_attempt: Set[str] = set()      # decision_ids
        self.accepted: Set[str] = set()
        self.filled: Set[str] = set()
        self.pre_wire_rejects = Counter()        # (event_type, asset) -> n
        self.cand_downstream: Dict[str, str] = {}  # candidate -> best stage

        # outcomes: decision_id -> (realized_pnl, counterfactual pnl, won?)
        self.outcomes: Dict[str, Dict[str, Any]] = {}
        self.settled_pnl_cents = 0.0
        self.settled_n = 0
        self.counterfactual = defaultdict(
            lambda: [0, 0, 0.0]
        )  # (asset, side) -> [wins, losses, pnl]

    # ------------------------------------------------------------------
    def add_decision_row(self, row: Tuple[Any, ...]) -> None:
        (did, cid, ts, ticker, asset, side, decision, prc, lane,
         tte, afg_json, gates_json) = row
        self.eval_rows += 1
        route = did.rsplit(":", 1)[-1] if ":" in (did or "") else "?"
        self.eval_rows_by_route[route] += 1
        a = (asset or "?").upper()
        self.eval_rows_by_asset[a] += 1

        day = time.strftime("%Y-%m-%d", time.gmtime(ts or 0))
        self.candidates_by_asset[a].add(cid)
        self.candidates_by_day[day].add(cid)

        self.cand_asset.setdefault(cid, a)
        self.cand_ticker.setdefault(cid, ticker or "?")
        self.cand_tte.setdefault(cid, _tte_bucket(tte))
        self.cand_day.setdefault(cid, day)

        try:
            gates = _loads(gates_json or "{}")
        except Exception:
            gates = {}
        try:
            failed_list = set(_loads(afg_json or "[]"))
        except Exception:
            failed_list = set()
        for g in failed_list:
            self.co_failed[g] += 1
        shared_gates = {
            k for k in gates
            if not k.startswith("yes_") and not k.startswith("no_")
        }

        row_sides = _side_from_gates(gates)
        if side:
            s = side.lower()
            if s not in row_sides:
                row_sides = row_sides + (s,)
        self.cand_side.setdefault(cid, set()).update(row_sides)

        emitted = decision == "ENTER"
        if emitted:
            self.emitted_decisions.add(did)
            self.emit_by_lane[lane or "?"] += 1
            for s in row_sides or ("?",):
                self.emit_by_asset_side[(a, s)] += 1

        # Per-side funnel assignment for this row.
        for s in row_sides:
            verdicts = _side_gate_verdicts(gates, s)
            pos = _passed(verdicts, "positive_ev") or emitted
            veto_ok = pos and all(
                _passed(verdicts, vg) or verdicts.get(vg) is None
                for vg in _VETO_GATES
            )
            # marginal-block attribution on non-emitted rows.  Shared
            # pre-decision gates (book_trusted, market_time, ...) block
            # BOTH sides in one eval — attribute them once as "both"
            # instead of double-counting per side.
            if not emitted and failed_list:
                ff = _first_failed_gate(verdicts)
                if ff:
                    if ff in shared_gates:
                        self.first_fail[(ff, a, "both")] += 1
                    else:
                        self.first_fail[(f"{s}_{ff}", a, s)] += 1
            # stage counting (per asset×side)
            self.stage_asset_side[(STAGE_EVAL, a, s)] += 1
            if pos:
                self.stage_asset_side[(STAGE_POS_EV, a, s)] += 1
            if veto_ok:
                self.stage_asset_side[(STAGE_VETO_SURV, a, s)] += 1
            if emitted:
                self.stage_asset_side[(STAGE_EMIT, a, s)] += 1
            # candidate furthest-stage bookkeeping
            rank = (
                _STAGE_RANK[STAGE_EMIT] if emitted else
                _STAGE_RANK[STAGE_VETO_SURV] if veto_ok else
                _STAGE_RANK[STAGE_POS_EV] if pos else
                _STAGE_RANK[STAGE_EVAL]
            )
            if rank > self.cand_stage.get(cid, _STAGE_RANK[STAGE_EPISODE]):
                self.cand_stage[cid] = rank

    # ------------------------------------------------------------------
    def add_events(self, conn: sqlite3.Connection) -> None:
        """Join lifecycle events for emitted decisions."""
        for chunk in _chunks(sorted(self.emitted_decisions)):
            ph = ",".join("?" * len(chunk))
            for did, etype, stage, rcode in conn.execute(
                f"SELECT decision_id, event_type, stage, reason_code "
                f"FROM strategy_decision_events WHERE decision_id IN ({ph})",
                chunk,
            ):
                if etype == "ORDER_SUBMITTED":
                    self.wire_attempt.add(did)
                    self.accepted.add(did)
                elif etype == "ORDER_FILLED":
                    self.filled.add(did)
                elif etype == "ROUTER_REJECTED":
                    self.wire_attempt.add(did)
                    cid = did.rsplit(":", 1)[0]
                    self.pre_wire_rejects[(rcode or "router", self.cand_asset.get(cid, "?"))] += 1
                elif etype in ("LANE_SUPPRESSED", "ALLOCATION_REJECTED",
                               "RISK_REJECTED", "COOLDOWN_REJECTED"):
                    cid = did.rsplit(":", 1)[0]
                    self.pre_wire_rejects[(etype, self.cand_asset.get(cid, "?"))] += 1

        # roll downstream stages up to candidate level
        for did in self.wire_attempt | self.accepted | self.filled:
            cid = did.rsplit(":", 1)[0]
            st = (STAGE_FILLED if did in self.filled else
                  STAGE_ACCEPTED if did in self.accepted else STAGE_WIRE)
            prev = self.cand_downstream.get(cid)
            if prev is None or _STAGE_RANK[st] > _STAGE_RANK[prev]:
                self.cand_downstream[cid] = st
            if _STAGE_RANK[st] > self.cand_stage.get(cid, 0):
                self.cand_stage[cid] = _STAGE_RANK[st]

    # ------------------------------------------------------------------
    def add_outcomes(self, conn: sqlite3.Connection, lo_ts: float) -> None:
        """Join settled outcomes via the settled_at index (one scan)."""
        for did, rpnl, cf_yes, cf_no, settled_yes, status in conn.execute(
            "SELECT decision_id, realized_net_pnl_cents, "
            "counterfactual_yes_pnl_cents, counterfactual_no_pnl_cents, "
            "settled_yes, outcome_status "
            "FROM strategy_decision_outcomes WHERE settled_at > ?",
            (lo_ts,),
        ):
            cid = did.rsplit(":", 1)[0]
            if cid not in self.cand_asset:
                continue
            sides = self.cand_side.get(cid) or {"?"}
            rec = self.outcomes.setdefault(cid, {})
            if rpnl is not None:
                rec["realized"] = rec.get("realized", 0.0) + rpnl
                self.settled_n += 1
                self.settled_pnl_cents += rpnl
                if self.cand_stage.get(cid, 0) < _STAGE_RANK[STAGE_SETTLED]:
                    self.cand_stage[cid] = _STAGE_RANK[STAGE_SETTLED]
            # Per-side counterfactual: each side is valued at its own
            # hypothetical entry (cf_yes / cf_no), never cross-attributed.
            for s in sides:
                cf_side = cf_yes if s == "yes" else cf_no if s == "no" else None
                if cf_side is None:
                    cf_side = cf_yes if settled_yes else cf_no
                if cf_side is not None:
                    key = (self.cand_asset[cid], s)
                    self.counterfactual[key][0 if cf_side > 0 else 1] += 1
                    self.counterfactual[key][2] += cf_side

    # ------------------------------------------------------------------
    def heartbeat_summary(self, conn: sqlite3.Connection, lo_iso: str):
        try:
            n_cycles = conn.execute(
                "SELECT COUNT(*), SUM(decisions_persisted), "
                "SUM(snapshots_persisted), SUM(side_ev_persisted), "
                "SUM(ledger_error_count) FROM decision_audit_heartbeats "
                "WHERE created_at > ?", (lo_iso,)).fetchone()
        except Exception:
            return None
        return n_cycles


def _fmt_table(headers, rows) -> str:
    widths = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(str(c)))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    sep = "  ".join("-" * w for w in widths)
    body = "\n".join(
        "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r))
        for r in rows
    )
    return f"{line}\n{sep}\n{body}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=float, default=14.0,
                    help="window length in days (default 14)")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--snapshot", action="store_true",
                    help="backup-copy the live DB first (recommended "
                         "for multi-week windows under an active writer)")
    ap.add_argument("--out", help="write JSON summary to this path")
    args = ap.parse_args()

    db_path = args.db
    snap_path = None
    if args.snapshot:
        snap_path = _snapshot(db_path)
        db_path = snap_path
    conn = _connect(db_path)

    try:
        hi = conn.execute(
            "SELECT MAX(decision_ts) FROM strategy_decisions").fetchone()[0]
        if hi is None:
            print("[funnel] no decisions recorded", file=sys.stderr)
            return 1
        lo = hi - args.days * 86400.0
        lo_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(lo))
        hi_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(hi))
        print(f"[funnel] window {lo_iso} .. {hi_iso} ({args.days}d)",
              file=sys.stderr)

        fn = Funnel()
        q = (
            "SELECT decision_id, candidate_id, decision_ts, ticker, asset, "
            "selected_side, decision, primary_reason_code, admission_lane, "
            "seconds_to_close, all_failed_gates_json, gate_results_json "
            "FROM strategy_decisions WHERE decision_ts > ? "
            "ORDER BY decision_ts"
        )
        t0 = time.time()
        n = 0
        for row in conn.execute(q, (lo,)):
            fn.add_decision_row(row)
            n += 1
            if n % 200000 == 0:
                print(f"[funnel] .. {n} decisions "
                      f"({time.time()-t0:.0f}s)", file=sys.stderr)
        print(f"[funnel] {n} decision rows in {time.time()-t0:.0f}s",
              file=sys.stderr)

        t0 = time.time()
        fn.add_events(conn)
        fn.add_outcomes(conn, lo)
        hb = fn.heartbeat_summary(conn, lo_iso)
        print(f"[funnel] joins in {time.time()-t0:.0f}s", file=sys.stderr)
    finally:
        conn.close()
        if snap_path:
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.unlink(snap_path + suffix)
                except OSError:
                    pass

    # ---------------- headline funnel ---------------------------------
    eps = len(fn.cand_stage)
    stage_counts = {s: 0 for s in FUNNEL_ORDER}
    for cid, rank in fn.cand_stage.items():
        for st, r in _STAGE_RANK.items():
            if rank >= r and st != STAGE_EPISODE:
                stage_counts[st] += 1
    stage_counts[STAGE_EPISODE] = eps
    stage_counts[STAGE_EVAL] = eps  # episodes are candidate-deduped evals

    rows = []
    prev = eps or 1
    for st in FUNNEL_ORDER:
        c = stage_counts[st]
        rows.append((st, c, f"{100.0*c/prev:.1f}%", f"{100.0*c/eps:.1f}%"))
        if c:
            prev = c
    print("\n=== CANDIDATE FUNNEL (unique candidates reaching each stage) ===")
    print(_fmt_table(("stage", "candidates", "conv", "of_episodes"), rows))
    print(f"  (model evaluation rows scanned: {fn.eval_rows:,})")

    # ---------------- per-asset x stage --------------------------------
    print("\n=== PER-ASSET FUNNEL (candidates) ===")
    head = ("stage",) + ASSETS
    arows = []
    # asset-stage candidate counts: dedupe candidates per (asset, stage)
    per_asset_stage = {a: Counter() for a in ASSETS}
    for cid, rank in fn.cand_stage.items():
        a = fn.cand_asset.get(cid, "?")
        if a not in per_asset_stage:
            continue
        for st, r in _STAGE_RANK.items():
            if rank >= r:
                per_asset_stage[a][st] += 1
    for st in (STAGE_EPISODE, STAGE_POS_EV, STAGE_VETO_SURV, STAGE_EMIT,
               STAGE_WIRE, STAGE_ACCEPTED, STAGE_FILLED):
        arows.append([st] + [per_asset_stage[a][st] for a in ASSETS])
    print(_fmt_table(head, arows))

    # eval rows per asset for context
    print("\n  model eval rows by asset: "
          + ", ".join(f"{a}={fn.eval_rows_by_asset.get(a,0):,}" for a in ASSETS))
    print("  eval rows by route: "
          + ", ".join(f"{r}={n:,}" for r, n in fn.eval_rows_by_route.most_common()))

    # ---------------- marginal block attribution -----------------------
    print("\n=== MARGINAL BLOCKERS (first failed gate on rejected rows; "
          "the cohort that passed all prior gates) ===")
    gf = Counter()
    gf_assets = defaultdict(Counter)
    for (gate, asset, side), n in fn.first_fail.items():
        gf[gate] += n
        gf_assets[gate][asset] += n
    brows = []
    for gate, n in gf.most_common(20):
        split = " ".join(f"{a}={gf_assets[gate][a]}" for a in ASSETS
                         if gf_assets[gate].get(a))
        brows.append((gate, n, split))
    print(_fmt_table(("gate", "blocks", "by asset"), brows))

    # ---------------- emission / wire / fills --------------------------
    print("\n=== EMISSION & EXECUTION ===")
    print(f"  emitted decisions: {len(fn.emitted_decisions):,} "
          f"(lanes: {', '.join(f'{k}={v}' for k,v in fn.emit_by_lane.most_common())})")
    print(f"  wire attempts: {len(fn.wire_attempt):,}  "
          f"accepted: {len(fn.accepted):,}  fills: {len(fn.filled):,}")
    if fn.pre_wire_rejects:
        print("  pre-wire attrition:")
        for (et, a), cnt in fn.pre_wire_rejects.most_common(12):
            print(f"    {et:24s} {a:5s} {cnt}")

    # ---------------- settled outcomes ---------------------------------
    print("\n=== SETTLED OUTCOMES ===")
    print(f"  realized fills settled: {fn.settled_n}  "
          f"net P&L: {fn.settled_pnl_cents:+.1f}c")
    cf_rows = []
    for (a, s), (w, l, pnl) in sorted(
            fn.counterfactual.items(),
            key=lambda kv: -kv[1][2]):
        cf_rows.append((a, s, w, l, f"{pnl:+.1f}c"))
    if cf_rows:
        print("  counterfactual per (asset,side) — rejected-candidate value "
              "at decision-time quotes:")
        print(_fmt_table(("asset", "side", "cf_w", "cf_l", "cf_pnl"), cf_rows[:15]))

    # ---------------- coverage -----------------------------------------
    if hb and hb[0]:
        print("\n=== INSTRUMENTATION COVERAGE (heartbeats) ===")
        print(f"  cycles={hb[0]}  decisions_persisted={hb[1]}  "
              f"snapshots={hb[2]}  side_ev={hb[3]}  ledger_errors={hb[4]}")
    days = sorted(fn.candidates_by_day)
    print(f"\n  days covered: {len(days)} "
          f"({days[0]} .. {days[-1]})" if days else "")
    zero_days = [d for d in days if not any(
        fn.cand_stage.get(cid, 0) >= _STAGE_RANK[STAGE_EMIT]
        for cid in fn.candidates_by_day[d])]
    print(f"  days with zero emitted candidates: {len(zero_days)}"
          + (f"  {zero_days[:10]}{'...' if len(zero_days)>10 else ''}"
             if zero_days else ""))

    if args.out:
        payload = {
            "window": {"lo": lo_iso, "hi": hi_iso, "days": args.days},
            "eval_rows": fn.eval_rows,
            "funnel_candidates": {s: stage_counts[s] for s in FUNNEL_ORDER},
            "per_asset": {a: dict(per_asset_stage[a]) for a in ASSETS},
            "marginal_blockers": [
                {"gate": g, "n": n, "by_asset": dict(gf_assets[g])}
                for g, n in gf.most_common()
            ],
            "emitted": len(fn.emitted_decisions),
            "wire_attempts": len(fn.wire_attempt),
            "accepted": len(fn.accepted),
            "fills": len(fn.filled),
            "settled_n": fn.settled_n,
            "settled_pnl_cents": fn.settled_pnl_cents,
            "counterfactual": {
                f"{a}:{s}": {"w": w, "l": l, "pnl": pnl}
                for (a, s), (w, l, pnl) in fn.counterfactual.items()
            },
            "emit_by_lane": dict(fn.emit_by_lane),
            "pre_wire_rejects": {
                f"{et}:{a}": c for (et, a), c in fn.pre_wire_rejects.items()
            },
        }
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
        print(f"\n[funnel] wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
