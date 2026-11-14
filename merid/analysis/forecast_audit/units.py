"""Evaluation population and fixed-horizon snapshot selection.

Canonical scoring unit
----------------------
``(ticker, horizon_seconds, model_version_id)`` scored in canonical YES
space. YES/NO complement rows are never counted as independent outcomes —
the audit DB stores one YES-space probability pair per decision, and the
model-cal log is filtered to ``side == 'yes'``.

Horizon contract
----------------
For each declared horizon ``h`` the target decision timestamp is
``close_ts - h``. The unit's snapshot is the LATEST decision record with
``decision_ts <= target_ts`` — never a record after it. A snapshot older
than ``max_age_seconds`` is rejected as ``stale_snapshot``. Missing
coverage is always recorded with an explicit reason, never repaired with
hindsight.
"""

from __future__ import annotations

import hashlib
import statistics
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .records import (
    AnchoredStageLog,
    AnchoredStageRecord,
    DecisionRow,
    LabelVersion,
    OfficialOutcomes,
    TickerProbe,
)

REASON_OK = "ok"
REASON_NO_CLOSE_TS = "no_close_ts"
REASON_NO_SNAPSHOT_BEFORE_TARGET = "no_snapshot_before_target"
REASON_STALE_SNAPSHOT = "stale_snapshot"
REASON_OUTCOME_UNRESOLVED = "outcome_unresolved"
REASON_OUTCOME_PENDING = "outcome_pending"
REASON_NO_DECISIONS = "no_decisions_for_ticker"
REASON_NO_ELIGIBLE = "no_eligible_snapshot"
REASON_QUARANTINED = "quarantined"

# Flag threshold: per-ticker close_ts should be a constant. Spread beyond
# this marks a contract-timing anomaly (visible in coverage, not repaired).
CLOSE_TS_SPREAD_FLAG_S = 5.0
# close_ts is RECONSTRUCTED per decision row as decision_ts +
# seconds_to_expiry (decision_audit_ledger.py). Spread beyond this is an
# unresolved contract-boundary error -> quarantine from scored units.
CLOSE_TS_SPREAD_QUARANTINE_S = 60.0
# settlement_timestamp_utc is the Kalshi settlement publication time, not
# the contract close: settlement can never precede close, so a materially
# negative (settlement - close) delta is a boundary contradiction.
SETTLEMENT_BEFORE_CLOSE_QUARANTINE_S = -30.0

# Where the JSONL has no observed_at, assume this grace after the exchange
# settlement timestamp for label availability.
LABEL_AVAILABILITY_GRACE_S = 300.0

# Anchored-stage (anch_wf) join classes. No event id exists in the
# model-calibration schema, so no match can be verified to be the same
# inference event — every accepted join is a bounded as-of match and the
# comparison it feeds stays PROVISIONAL.
JOIN_VERIFIED_EVENT = "verified_event"      # reserved: requires event id
JOIN_ASOF_BOUNDED = "asof_bounded"
JOIN_REJECT_FUTURE = "rejected_future"
JOIN_REJECT_TOLERANCE = "rejected_out_of_tolerance"
JOIN_NONE = "no_candidate"

# Default join bounds (seconds). rec.ts is the emission time inside the
# producing evaluation; decision_ts is evaluation-entry. Same-event
# emission lag is therefore ~0s positive (measured p95 +0.02s on the live
# ledger); a record predating the decision by more than
# ANCH_PAST_TOLERANCE_S is a stale as-of candidate from an earlier
# evaluation; a record postdating by more than ANCH_FUTURE_SLACK_S is
# future information relative to the audited snapshot and is rejected.
ANCH_PAST_TOLERANCE_S = 30.0
ANCH_FUTURE_SLACK_S = 5.0
# Two admissible candidates whose |offset| differ by less than this mark
# the choice ambiguous (multiple plausible inference events).
ANCH_AMBIGUITY_EPS_S = 2.0


@dataclass(slots=True)
class EvalUnit:
    """One (ticker, horizon, model_version) scoring unit in YES space."""

    ticker: str
    asset: str
    horizon_s: float
    model_version_id: str
    target_ts: float
    snapshot_ts: Optional[float]
    snapshot_offset_s: Optional[float]
    close_ts: Optional[float]
    close_ts_source: Optional[str]
    p_raw: Optional[float]
    p_final: Optional[float]
    m_mid: Optional[float]
    p_anch_wf: Optional[float]
    anch_wf_offset_s: Optional[float]
    y: Optional[int]
    label_ts: Optional[float]
    decision: Optional[str]
    selected_side: Optional[str]
    realized_net_pnl_cents: Optional[float]
    run_version_fields: Dict[str, Any] = field(default_factory=dict)
    # P0 attribution fields
    decision_id: Optional[str] = None
    label_source: Optional[str] = None          # "official_jsonl" | "audit_db" | None
    label_versions: List[LabelVersion] = field(default_factory=list)
    anch_join_class: Optional[str] = None        # JOIN_* constant
    anch_n_candidates: int = 0
    anch_ambiguous: bool = False
    anch_reused: bool = False


@dataclass
class PopulationEntry:
    ticker: str
    asset: Optional[str]
    horizon_s: float
    status: str
    reason: Optional[str]
    snapshot_ts: Optional[float] = None
    snapshot_offset_s: Optional[float] = None


@dataclass
class Population:
    units: List[EvalUnit]
    entries: List[PopulationEntry]
    close_ts_spread_tickers: int
    label_source_counts: Dict[str, int]
    boundary_classes: Dict[str, str] = field(default_factory=dict)
    boundary_evidence: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    quarantined_tickers: List[str] = field(default_factory=list)
    anch_join_counts: Dict[str, int] = field(default_factory=dict)
    anch_reused_records: int = 0

    def reason_counts(self) -> Dict[Tuple[float, str], int]:
        out: Dict[Tuple[float, str], int] = {}
        for e in self.entries:
            key = (e.horizon_s, e.status if e.status == REASON_OK else e.reason or e.status)
            out[key] = out.get(key, 0) + 1
        return out


def model_version_id(row: DecisionRow) -> str:
    """Composite provenance identity. NOTE: code changes that do not alter
    config/build fields are invisible to this id (no per-decision commit
    recorded beyond ``build_sha``) — documented in the report manifest."""
    parts = [
        str(row.model_version),
        str(row.calibration_version),
        str(row.config_version),
        str(row.build_sha),
        str(row.policy_epoch),
    ]
    return hashlib.sha1("|".join(parts).encode(), usedforsecurity=False).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Anchored-stage join (bounded as-of; same-event is not provable)
# ---------------------------------------------------------------------------

@dataclass
class AnchJoin:
    record: Optional[AnchoredStageRecord]
    join_class: str
    reason: Optional[str]
    offset_s: Optional[float]   # rec.ts - decision_ts of the chosen candidate
    n_candidates: int           # admissible candidates after filters
    n_bucket_records: int       # all records in the permitted buckets
    ambiguous: bool


def join_anchored(
    anchored: AnchoredStageLog,
    ticker: str,
    decision_ts: float,
    close_ts: Optional[float],
    *,
    past_tolerance_s: float = ANCH_PAST_TOLERANCE_S,
    future_slack_s: float = ANCH_FUTURE_SLACK_S,
    ambiguity_eps_s: float = ANCH_AMBIGUITY_EPS_S,
) -> AnchJoin:
    """Bounded as-of join for the post-anchor+WF stage.

    Candidates are ALL yes-side records in TTE-minute buckets {m-1, m, m+1}
    around the snapshot's own TTE. A candidate is admissible iff its
    emission ``offset = rec.ts - decision_ts`` lies in
    ``[-past_tolerance_s, +future_slack_s]``. The asymmetry is documented
    timestamp semantics: ``decision_ts`` is evaluation-entry time while
    ``rec.ts`` is synchronous emission inside an evaluation, so a same-event
    record lands at offset ~= 0+ (measured p95 +0.02s); ``future_slack_s``
    covers emission lag only, and anything beyond it is rejected as
    potential future information.

    The admissible candidate with smallest |offset| wins (ties -> earliest
    ts). No record carries an inference-event id, so every accepted join is
    ``asof_bounded`` — never ``verified_event``.
    """
    if not anchored.by_key or close_ts is None:
        return AnchJoin(None, JOIN_NONE, "no_anchored_log", None, 0, 0, False)
    tte_min = int((close_ts - decision_ts) // 60)
    admissible: List[Tuple[float, float, AnchoredStageRecord]] = []
    n_bucket = 0
    n_future = 0
    n_stale = 0
    for dm in (0, -1, 1):
        for rec in anchored.by_key.get((ticker, tte_min + dm), ()):
            n_bucket += 1
            off = rec.ts - decision_ts
            if off > future_slack_s:
                n_future += 1
            elif off < -past_tolerance_s:
                n_stale += 1
            else:
                admissible.append((abs(off), off, rec))
    if not admissible:
        if n_future:
            return AnchJoin(None, JOIN_REJECT_FUTURE, "future_join",
                            None, 0, n_bucket, False)
        if n_stale:
            return AnchJoin(None, JOIN_REJECT_TOLERANCE, "out_of_tolerance",
                            None, 0, n_bucket, False)
        return AnchJoin(None, JOIN_NONE, "no_candidate_in_bucket",
                        None, 0, n_bucket, False)
    admissible.sort(key=lambda c: (c[0], c[2].ts))
    abs_off, off, best = admissible[0]
    ambiguous = (
        len(admissible) > 1
        and (admissible[1][0] - abs_off) < ambiguity_eps_s
    )
    return AnchJoin(
        best, JOIN_ASOF_BOUNDED, None, off,
        len(admissible), n_bucket, ambiguous)


# ---------------------------------------------------------------------------
# Outcome resolution (official primary, ledger fallback) with label versions
# ---------------------------------------------------------------------------

@dataclass
class OutcomeResolution:
    y: Optional[int]
    label_ts: Optional[float]
    status: str                  # "settled" | "missing" | ledger status string
    source: Optional[str]        # "official_jsonl" | "audit_db" | None
    versions: List[LabelVersion]


def _resolve_outcome(
    ticker: str,
    official: OfficialOutcomes,
    ledger_outcome: Optional[Tuple[Optional[int], Optional[float], Optional[str]]],
    label_src: Dict[str, int],
) -> OutcomeResolution:
    """(y, label_ts, status, source, versions) — official export primary,
    audit-DB outcome fallback. Scoring uses the latest version; historical
    training eligibility is derived per-version from ``versions``."""
    official_outcome = official.by_ticker.get(ticker.upper())
    if official_outcome is not None:
        label_ts = official_outcome.observed_at_ts or (
            (official_outcome.settlement_ts or 0.0) + LABEL_AVAILABILITY_GRACE_S
            if official_outcome.settlement_ts else None
        )
        label_src["official_jsonl"] += 1
        return OutcomeResolution(
            y=official_outcome.resolved_yes,
            label_ts=label_ts,
            status="settled",
            source="official_jsonl",
            versions=list(official_outcome.versions),
        )
    if ledger_outcome is not None and ledger_outcome[0] is not None:
        settled_at = ledger_outcome[1]
        label_src["audit_db"] += 1
        return OutcomeResolution(
            y=ledger_outcome[0],
            label_ts=(settled_at + LABEL_AVAILABILITY_GRACE_S)
            if settled_at else None,
            status="settled",
            source="audit_db",
            # Ledger outcomes carry no documented availability: the version
            # is usable for retrospective scoring but trains only under the
            # grace policy (settled_at + grace).
            versions=[LabelVersion(None, settled_at, ledger_outcome[0])],
        )
    label_src["none"] += 1
    status = (ledger_outcome[2] or "missing") if ledger_outcome else "missing"
    return OutcomeResolution(None, None, status, None, [])


# ---------------------------------------------------------------------------
# Contract-boundary classification (ledger close_ts is reconstructed;
# settlement_timestamp_utc is publication time — never an anchor)
# ---------------------------------------------------------------------------

BOUNDARY_OK = "ok"
BOUNDARY_DRIFT = "reconstruction_drift"          # spread 5-60s, expected
BOUNDARY_SETTLE_LAG = "settlement_lag"           # settle - close > 2h, informational
BOUNDARY_NO_OFFICIAL = "no_official_match"
BOUNDARY_INVERTED = "inverted_settlement"        # settle << close: quarantine
BOUNDARY_EXTREME_SPREAD = "extreme_close_spread"  # spread > 60s: quarantine
BOUNDARY_ASSET_MISMATCH = "asset_column_mismatch"  # quarantine
BOUNDARY_QUARANTINE_CLASSES = frozenset(
    {BOUNDARY_INVERTED, BOUNDARY_EXTREME_SPREAD, BOUNDARY_ASSET_MISMATCH})


def classify_boundary(
    ticker: str,
    close_first: Optional[float],
    close_last: Optional[float],
    official: OfficialOutcomes,
    *,
    asset_mismatch: bool = False,
) -> Tuple[str, Optional[float], Optional[float]]:
    """(class, close_spread_s, settle_delta_s) for one ticker.

    ``settle_delta = settlement_ts - close``; Kalshi settlement publication
    is expected >= close, so a materially negative delta contradicts the
    contract boundary (quarantine). Large positive deltas are delayed-
    settlement information, not a scoring error.
    """
    spread = (
        abs(close_last - close_first)
        if close_first is not None and close_last is not None else None
    )
    o = official.by_ticker.get(ticker.upper())
    settle_delta = (
        o.settlement_ts - close_last
        if o is not None and o.settlement_ts is not None
        and close_last is not None else None
    )
    if asset_mismatch:
        cls = BOUNDARY_ASSET_MISMATCH
    elif settle_delta is not None and settle_delta < SETTLEMENT_BEFORE_CLOSE_QUARANTINE_S:
        cls = BOUNDARY_INVERTED
    elif spread is not None and spread > CLOSE_TS_SPREAD_QUARANTINE_S:
        cls = BOUNDARY_EXTREME_SPREAD
    elif settle_delta is not None and settle_delta > 7200.0:
        cls = BOUNDARY_SETTLE_LAG
    elif spread is not None and spread > CLOSE_TS_SPREAD_FLAG_S:
        cls = BOUNDARY_DRIFT
    elif settle_delta is None and o is None:
        cls = BOUNDARY_NO_OFFICIAL
    else:
        cls = BOUNDARY_OK
    return cls, spread, settle_delta


# ---------------------------------------------------------------------------
# Authoritative-boundary classification (boundary_mode="authoritative")
# ---------------------------------------------------------------------------
#
# With a resolved contract boundary (boundaries.py sidecar) the ledger's
# reconstructed close_ts is demoted to drift evidence: it no longer drives
# target selection, so its pathologies cannot corrupt the population.  The
# quarantine contract narrows to contradictions between TRUSTED sources:
#
#   * asset-column mismatch (unchanged),
#   * official settlement_ts materially BEFORE the contract boundary —
#     settlement cannot precede the observation window's end,
#   * boundary resolution itself absent (no contract_boundary_ts anywhere).
#
# Ledger first/last spread and |boundary - ledger_last| are reported as
# evidence (reconstruction_drift / boundary_ledger_divergence) but do NOT
# quarantine: they measure how wrong the OLD implementation was, which is
# the migration report's subject, not a contract defect.

BOUNDARY_LEDGER_DIVERGENCE_REVIEW_S = 300.0


def classify_boundary_authoritative(
    ticker: str,
    boundary_ts: Optional[float],
    boundary_source: Optional[str],
    ledger_first: Optional[float],
    ledger_last: Optional[float],
    official: OfficialOutcomes,
    *,
    asset_mismatch: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    """(class, evidence) under the authoritative-boundary regime.

    ``boundary_ts`` is the resolved contract_boundary_ts (may be None when
    even the sidecar could not resolve one — then the ledger value was used
    and the ticker is flagged ``boundary_fallback_ledger``).
    """
    o = official.by_ticker.get(ticker.upper())
    settle_ts = o.settlement_ts if o is not None else None
    ledger_spread = (
        abs(ledger_last - ledger_first)
        if ledger_first is not None and ledger_last is not None else None
    )
    ledger_delta = (
        boundary_ts - ledger_last
        if boundary_ts is not None and ledger_last is not None else None
    )
    settle_delta = (
        settle_ts - boundary_ts
        if settle_ts is not None and boundary_ts is not None else None
    )
    used_fallback = (
        boundary_source in (None, "ledger_reconstructed", "unresolved")
    )
    evidence = {
        "boundary_ts": boundary_ts,
        "boundary_source": boundary_source,
        "used_ledger_fallback": used_fallback,
        "ledger_close_spread_s": ledger_spread,
        "boundary_minus_ledger_last_s": ledger_delta,
        "settle_delta_s": settle_delta,
    }
    if asset_mismatch:
        return BOUNDARY_ASSET_MISMATCH, evidence
    if boundary_ts is None:
        # No authoritative boundary AND no usable ledger close: the probe
        # already marks these no_close_ts downstream; classify honestly.
        return "boundary_unresolved", evidence
    if used_fallback:
        # Boundary came from the reconstructed ledger — same trust level as
        # the old regime; keep the old quarantine semantics on it.
        if settle_delta is not None and settle_delta < SETTLEMENT_BEFORE_CLOSE_QUARANTINE_S:
            return BOUNDARY_INVERTED, evidence
        if ledger_spread is not None and ledger_spread > CLOSE_TS_SPREAD_QUARANTINE_S:
            return BOUNDARY_EXTREME_SPREAD, evidence
        return "boundary_fallback_ledger", evidence
    if settle_delta is not None and settle_delta < SETTLEMENT_BEFORE_CLOSE_QUARANTINE_S:
        return BOUNDARY_INVERTED, evidence
    if settle_delta is not None and settle_delta > 7200.0:
        return BOUNDARY_SETTLE_LAG, evidence
    if ledger_delta is not None and abs(ledger_delta) > BOUNDARY_LEDGER_DIVERGENCE_REVIEW_S:
        return "boundary_ledger_divergence", evidence
    if ledger_spread is not None and ledger_spread > CLOSE_TS_SPREAD_FLAG_S:
        return BOUNDARY_DRIFT, evidence
    if settle_delta is None and o is None:
        return BOUNDARY_NO_OFFICIAL, evidence
    return BOUNDARY_OK, evidence


def _ticker_close_ts(rows: List[DecisionRow]) -> Tuple[Optional[float], str, float]:
    """Robust per-ticker close time. The ledger's per-row ``close_ts`` can
    drift slightly after close (up to ~40s observed), so the median of
    observed values is used; the spread is returned for anomaly flagging."""
    vals = [r.close_ts for r in rows if r.close_ts is not None]
    if not vals:
        return None, "none", 0.0
    med = statistics.median(vals)
    return med, "ledger_median", max(vals) - min(vals)


def build_population(
    rows: List[DecisionRow],
    *,
    horizons_s: List[float],
    max_age_s: float,
    anchored: AnchoredStageLog,
    official: OfficialOutcomes,
    expected_tickers: Optional[List[str]] = None,
    anch_past_tolerance_s: float = ANCH_PAST_TOLERANCE_S,
    anch_future_slack_s: float = ANCH_FUTURE_SLACK_S,
) -> Population:
    """Build the evaluation population and scoring units.

    ``expected_tickers`` optionally extends the ticker universe (e.g., from
    the official outcomes file) so contracts with zero decision rows are
    counted as ``no_decisions_for_ticker`` rather than invisible.
    """
    by_ticker: Dict[str, List[DecisionRow]] = {}
    for r in rows:
        by_ticker.setdefault(r.ticker, []).append(r)

    ticker_universe = set(by_ticker)
    if expected_tickers:
        ticker_universe.update(expected_tickers)

    units: List[EvalUnit] = []
    entries: List[PopulationEntry] = []
    spread_flags = 0
    label_src: Dict[str, int] = {"audit_db": 0, "official_jsonl": 0, "none": 0}
    boundary_classes: Dict[str, str] = {}
    boundary_evidence: Dict[str, Dict[str, Any]] = {}
    quarantined_tickers: List[str] = []
    anch_counts: Dict[str, int] = {}

    for ticker in sorted(ticker_universe):
        trows = by_ticker.get(ticker)
        asset = trows[0].asset if trows else None
        if not trows:
            for h in horizons_s:
                entries.append(PopulationEntry(ticker, asset, h, REASON_NO_DECISIONS, REASON_NO_DECISIONS))
            continue

        trows.sort(key=lambda r: r.decision_ts)
        close_ts, close_src, spread = _ticker_close_ts(trows)
        if spread > CLOSE_TS_SPREAD_FLAG_S:
            spread_flags += 1

        close_vals = [r.close_ts for r in trows if r.close_ts is not None]
        b_cls, b_spread, b_delta = classify_boundary(
            ticker,
            min(close_vals) if close_vals else None,
            max(close_vals) if close_vals else None,
            official)
        boundary_classes[ticker] = b_cls
        boundary_evidence[ticker] = {
            "close_spread_s": b_spread, "settle_delta_s": b_delta}
        quarantined = b_cls in BOUNDARY_QUARANTINE_CLASSES

        # Outcome: prefer official jsonl label (authoritative export),
        # fall back to the audit-DB joined outcome; record which source.
        ledger_outcome: Optional[Tuple[int, Optional[float], Optional[str]]] = None
        for r in trows:
            if r.settled_yes is not None:
                ledger_outcome = (int(r.settled_yes), r.settled_at, r.outcome_status)
                break
            if r.outcome_status:
                ledger_outcome = (None, r.settled_at, r.outcome_status)
        oc = _resolve_outcome(ticker, official, ledger_outcome, label_src)
        y, label_ts, outcome_status = oc.y, oc.label_ts, oc.status

        if quarantined:
            quarantined_tickers.append(ticker)
            for h in horizons_s:
                entries.append(PopulationEntry(
                    ticker, asset, h, "quarantined", b_cls))
            continue

        ts_list = [r.decision_ts for r in trows]  # already sorted by load order

        for h in horizons_s:
            if close_ts is None:
                entries.append(PopulationEntry(ticker, asset, h, "excluded", REASON_NO_CLOSE_TS))
                continue
            target_ts = close_ts - h
            idx = bisect_right(ts_list, target_ts) - 1
            if idx < 0:
                entries.append(PopulationEntry(
                    ticker, asset, h, "missing", REASON_NO_SNAPSHOT_BEFORE_TARGET))
                continue
            row = trows[idx]
            offset = target_ts - row.decision_ts
            if offset > max_age_s:
                entries.append(PopulationEntry(
                    ticker, asset, h, "missing", REASON_STALE_SNAPSHOT,
                    snapshot_ts=row.decision_ts, snapshot_offset_s=offset))
                continue

            if outcome_status == "missing":
                status, reason = "unscored", REASON_OUTCOME_UNRESOLVED
            elif outcome_status != "settled":
                status, reason = "unscored", REASON_OUTCOME_PENDING
            else:
                status, reason = REASON_OK, None

            # Anchored-stage join: bounded as-of match (see join_anchored).
            j = join_anchored(
                anchored, ticker, row.decision_ts, close_ts,
                past_tolerance_s=anch_past_tolerance_s,
                future_slack_s=anch_future_slack_s)
            anch_counts[j.join_class] = anch_counts.get(j.join_class, 0) + 1

            units.append(EvalUnit(
                ticker=ticker,
                asset=row.asset or asset,
                horizon_s=h,
                model_version_id=model_version_id(row),
                target_ts=target_ts,
                snapshot_ts=row.decision_ts,
                snapshot_offset_s=offset,
                close_ts=close_ts,
                close_ts_source=close_src,
                p_raw=row.raw_p_yes,
                p_final=row.calibrated_p_yes,
                m_mid=row.yes_mid,
                p_anch_wf=j.record.p_model if j.record else None,
                anch_wf_offset_s=j.offset_s,
                y=y,
                label_ts=label_ts,
                decision=row.decision,
                selected_side=row.selected_side,
                realized_net_pnl_cents=row.realized_net_pnl_cents,
                run_version_fields={
                    "model_version": row.model_version,
                    "calibration_version": row.calibration_version,
                    "config_version": row.config_version,
                    "build_sha": row.build_sha,
                    "policy_epoch": row.policy_epoch,
                    "record_source": row.record_source,
                },
                decision_id=row.decision_id,
                label_source=oc.source,
                label_versions=oc.versions,
                anch_join_class=j.join_class,
                anch_n_candidates=j.n_candidates,
                anch_ambiguous=j.ambiguous,
            ))
            entries.append(PopulationEntry(
                ticker, asset, h, status, reason,
                snapshot_ts=row.decision_ts, snapshot_offset_s=offset))

    reused = _flag_anchored_reuse(units)
    return Population(
        units=units,
        entries=entries,
        close_ts_spread_tickers=spread_flags,
        label_source_counts=label_src,
        boundary_classes=boundary_classes,
        boundary_evidence=boundary_evidence,
        quarantined_tickers=quarantined_tickers,
        anch_join_counts=anch_counts,
        anch_reused_records=reused,
    )


# ---------------------------------------------------------------------------
# Probe-based population build (same contract as build_population)
# ---------------------------------------------------------------------------

def _flag_anchored_reuse(units: List[EvalUnit]) -> int:
    """Flag units whose anchored record is shared across DISTINCT decision
    identities. Reuse across horizons of the same decision is legitimate;
    reuse across different decision_ts marks a stale as-of binding."""
    rec_users: Dict[Tuple[str, float], List[EvalUnit]] = {}
    for u in units:
        if u.anch_join_class == JOIN_ASOF_BOUNDED and u.anch_wf_offset_s is not None:
            rec_ts = u.snapshot_ts + u.anch_wf_offset_s
            rec_users.setdefault((u.ticker, rec_ts), []).append(u)
    reused = 0
    for us in rec_users.values():
        if len({u.decision_id for u in us}) > 1:
            reused += 1
            for u in us:
                u.anch_reused = True
    return reused


BOUNDARY_MODE_LEDGER = "ledger"
BOUNDARY_MODE_AUTHORITATIVE = "authoritative"


def build_population_from_probes(
    probes: List[TickerProbe],
    *,
    horizons_s: List[float],
    max_age_s: float,
    anchored: AnchoredStageLog,
    official: OfficialOutcomes,
    expected_tickers: Optional[List[str]] = None,
    anch_past_tolerance_s: float = ANCH_PAST_TOLERANCE_S,
    anch_future_slack_s: float = ANCH_FUTURE_SLACK_S,
    boundary_mode: str = BOUNDARY_MODE_LEDGER,
) -> Population:
    """Build the evaluation population from per-ticker probe results.

    Same contract as ``build_population`` but consumes the index-probe
    loader's output — the production path on the large live DB.

    ``boundary_mode``:
      * ``"ledger"`` — legacy behavior: close_ts is the LAST decision row's
        reconstructed value (``close_ts_last`` fallback ``close_ts_first``);
        boundary classification uses the old drift/quarantine rules.
      * ``"authoritative"`` — close_ts is the probe's
        ``effective_close_ts``: the resolved contract boundary when the
        sidecar provides one, else the ledger value (per-ticker fallback).
        Horizon targets were already computed against it at probe time.
        Boundary classification uses ``classify_boundary_authoritative``.
    """
    authoritative = boundary_mode == BOUNDARY_MODE_AUTHORITATIVE
    probe_by_ticker = {p.ticker: p for p in probes}
    ticker_universe = set(probe_by_ticker)
    if expected_tickers:
        ticker_universe.update(expected_tickers)

    units: List[EvalUnit] = []
    entries: List[PopulationEntry] = []
    spread_flags = 0
    label_src: Dict[str, int] = {"audit_db": 0, "official_jsonl": 0, "none": 0}
    boundary_classes: Dict[str, str] = {}
    boundary_evidence: Dict[str, Dict[str, Any]] = {}
    quarantined_tickers: List[str] = []
    anch_counts: Dict[str, int] = {}

    for ticker in sorted(ticker_universe):
        probe = probe_by_ticker.get(ticker)
        if probe is None:
            for h in horizons_s:
                entries.append(PopulationEntry(
                    ticker, None, h, REASON_NO_DECISIONS, REASON_NO_DECISIONS))
            continue

        asset = probe.asset
        if authoritative:
            # Probe already resolved the fallback chain:
            # contract_boundary_ts -> ledger close_last -> close_first.
            close_ts = probe.effective_close_ts
            if close_ts is None:
                close_ts = (
                    probe.close_ts_last
                    if probe.close_ts_last is not None
                    else probe.close_ts_first
                )
            boundary_ts = (
                getattr(probe.boundary, "contract_boundary_ts", None)
                if probe.boundary is not None else None
            )
            boundary_source = probe.boundary_source
            close_source = (
                boundary_source
                if boundary_ts is not None and boundary_source
                else "ledger_last_row"
            )
        else:
            close_ts = (
                probe.close_ts_last
                if probe.close_ts_last is not None else probe.close_ts_first
            )
            boundary_ts = None
            boundary_source = None
            close_source = "ledger_last_row"
        if (
            probe.close_ts_first is not None
            and probe.close_ts_last is not None
            and abs(probe.close_ts_last - probe.close_ts_first) > CLOSE_TS_SPREAD_FLAG_S
        ):
            spread_flags += 1

        if authoritative:
            b_cls, b_evidence = classify_boundary_authoritative(
                ticker, boundary_ts, boundary_source,
                probe.close_ts_first, probe.close_ts_last, official,
                asset_mismatch=probe.asset_mismatch)
            b_spread = b_evidence.get("ledger_close_spread_s")
            b_delta = b_evidence.get("settle_delta_s")
        else:
            b_cls, b_spread, b_delta = classify_boundary(
                ticker, probe.close_ts_first, probe.close_ts_last, official,
                asset_mismatch=probe.asset_mismatch)
            b_evidence = {"close_spread_s": b_spread, "settle_delta_s": b_delta}
        boundary_classes[ticker] = b_cls
        boundary_evidence[ticker] = b_evidence if authoritative else {
            "close_spread_s": b_spread, "settle_delta_s": b_delta}
        if b_cls in BOUNDARY_QUARANTINE_CLASSES:
            quarantined_tickers.append(ticker)
            for h in horizons_s:
                entries.append(PopulationEntry(
                    ticker, asset, h, "quarantined", b_cls))
            continue

        oc = _resolve_outcome(ticker, official, probe.ledger_outcome, label_src)
        y, label_ts, outcome_status = oc.y, oc.label_ts, oc.status

        hp_by_h = {hp.horizon_s: hp for hp in probe.horizons}
        for h in horizons_s:
            if close_ts is None:
                entries.append(PopulationEntry(
                    ticker, asset, h, "excluded", REASON_NO_CLOSE_TS))
                continue
            hp = hp_by_h.get(float(h))
            if hp is None:
                # Probe did not cover this horizon (shouldn't happen — the
                # loader probes every declared horizon).
                entries.append(PopulationEntry(
                    ticker, asset, h, "missing", REASON_NO_SNAPSHOT_BEFORE_TARGET))
                continue
            target_ts = hp.target_ts
            row = hp.row
            if row is None:
                if hp.latest_ts_any is None:
                    entries.append(PopulationEntry(
                        ticker, asset, h, "missing",
                        REASON_NO_SNAPSHOT_BEFORE_TARGET))
                elif target_ts - hp.latest_ts_any > max_age_s:
                    entries.append(PopulationEntry(
                        ticker, asset, h, "missing", REASON_STALE_SNAPSHOT,
                        snapshot_ts=hp.latest_ts_any,
                        snapshot_offset_s=target_ts - hp.latest_ts_any))
                else:
                    # Rows exist inside the age window but every one was
                    # filtered by env/research eligibility.
                    entries.append(PopulationEntry(
                        ticker, asset, h, "missing", REASON_NO_ELIGIBLE,
                        snapshot_ts=hp.latest_ts_any,
                        snapshot_offset_s=target_ts - hp.latest_ts_any))
                continue

            offset = target_ts - row.decision_ts
            if offset > max_age_s:
                entries.append(PopulationEntry(
                    ticker, asset, h, "missing", REASON_STALE_SNAPSHOT,
                    snapshot_ts=row.decision_ts, snapshot_offset_s=offset))
                continue

            if outcome_status == "missing":
                status, reason = "unscored", REASON_OUTCOME_UNRESOLVED
            elif outcome_status != "settled":
                status, reason = "unscored", REASON_OUTCOME_PENDING
            else:
                status, reason = REASON_OK, None

            j = join_anchored(
                anchored, ticker, row.decision_ts, close_ts,
                past_tolerance_s=anch_past_tolerance_s,
                future_slack_s=anch_future_slack_s)
            anch_counts[j.join_class] = anch_counts.get(j.join_class, 0) + 1

            units.append(EvalUnit(
                ticker=ticker,
                asset=row.asset or asset,
                horizon_s=h,
                model_version_id=model_version_id(row),
                target_ts=target_ts,
                snapshot_ts=row.decision_ts,
                snapshot_offset_s=offset,
                close_ts=close_ts,
                close_ts_source=close_source,
                p_raw=row.raw_p_yes,
                p_final=row.calibrated_p_yes,
                m_mid=row.yes_mid,
                p_anch_wf=j.record.p_model if j.record else None,
                anch_wf_offset_s=j.offset_s,
                y=y,
                label_ts=label_ts,
                decision=row.decision,
                selected_side=row.selected_side,
                realized_net_pnl_cents=row.realized_net_pnl_cents,
                run_version_fields={
                    "model_version": row.model_version,
                    "calibration_version": row.calibration_version,
                    "config_version": row.config_version,
                    "build_sha": row.build_sha,
                    "policy_epoch": row.policy_epoch,
                    "record_source": row.record_source,
                },
                decision_id=row.decision_id,
                label_source=oc.source,
                label_versions=oc.versions,
                anch_join_class=j.join_class,
                anch_n_candidates=j.n_candidates,
                anch_ambiguous=j.ambiguous,
            ))
            entries.append(PopulationEntry(
                ticker, asset, h, status, reason,
                snapshot_ts=row.decision_ts, snapshot_offset_s=offset))

    reused = _flag_anchored_reuse(units)
    return Population(
        units=units,
        entries=entries,
        close_ts_spread_tickers=spread_flags,
        label_source_counts=label_src,
        boundary_classes=boundary_classes,
        boundary_evidence=boundary_evidence,
        quarantined_tickers=quarantined_tickers,
        anch_join_counts=anch_counts,
        anch_reused_records=reused,
    )
