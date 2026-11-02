"""Shared canonical-fill classification contract for Kalshi ledger consumers.

Economic-event identity rules:

  verified_venue        - venue-evidenced row (non-mirror source, real
                          trade_id), trusted canonicalization state. Counted
                          once per exchange trade_id; distinct trade_ids on
                          one order/qty/second are genuine partial fills.
  mirror_matched        - live_router_*/order_router row whose order's venue
                          fills fully cover it on qty AND consistent direction
                          (signed position delta), account scope, and market.
                          Telemetry-only; excluded from financial/position math.
  mirror_partial        - venue coverage < mirror qty: incomplete coverage,
                          unmatched balance is not a verified fill.
  side_conflict         - mirror signed delta opposes the venue aggregate on
                          the same order (direction contested). ALL rows on the
                          order quarantine from authoritative calculation.
  unpaired_provisional  - mirror row with no venue twin. Neither verified nor
                          duplicate: excluded from authoritative totals and
                          reported with explicit coverage status.
  non_execution         - settlement pseudo-fills / non-execution rows.

Contract version: bump whenever classification semantics change so every
consumer can assert it shares one version.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, Tuple

CANONICAL_CONTRACT_VERSION = "canonical-fill-view/1.0"

VERIFIED_VENUE = "verified_venue"
MIRROR_MATCHED = "mirror_matched"
MIRROR_PARTIAL = "mirror_partial"
SIDE_CONFLICT = "side_conflict"
UNPAIRED_PROVISIONAL = "unpaired_provisional"
NON_EXECUTION = "non_execution"

_MIRROR_SOURCES = frozenset({"order_router"})
_NON_EXEC_LIQUIDITY = frozenset({"settlement"})
_UNTRUSTED_STATES = frozenset(
    {"UNTRUSTED_LEGACY", "UNTRUSTED_RAW", "UNTRUSTED_SIDE_CONFLICT"}
)


def _get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]  # sqlite3.Row
    except Exception:
        return getattr(row, key, default)


def is_mirror_row(row: Any) -> bool:
    fid = _get(row, "fill_id", "") or ""
    src = (_get(row, "ingestion_source", "") or "").lower()
    return fid.startswith("live_router_") or src in _MIRROR_SOURCES


def classify_fill_rows(rows: Iterable[Any]) -> Dict[str, Tuple[str, str]]:
    """Classify every row -> {fill_id: (class, evidence)}.

    Rows may be sqlite3.Row, dicts, or objects exposing the kalshi_fills
    column names as attributes.
    """
    rows = list(rows)
    by_order: Dict[str, list] = defaultdict(list)
    for r in rows:
        oid = _get(r, "order_id")
        if oid:
            by_order[oid].append(r)

    out: Dict[str, Tuple[str, str]] = {}
    venue_trade_ids: Dict[str, list] = defaultdict(list)

    for r in rows:
        fid = _get(r, "fill_id")
        if not fid:
            continue
        if _get(r, "liquidity_role") in _NON_EXEC_LIQUIDITY or fid.startswith("settlement:"):
            out[fid] = (NON_EXECUTION, "settlement/non-execution row")
            continue
        if is_mirror_row(r):
            continue
        state = _get(r, "canonicalization_state")
        if state in _UNTRUSTED_STATES:
            out[fid] = (SIDE_CONFLICT, f"untrusted canonicalization state {state}")
            continue
        tid = _get(r, "trade_id") or fid
        venue_trade_ids[tid].append(r)
        out[fid] = (VERIFIED_VENUE, f"trade_id={tid}")

    # same exchange trade_id twice -> same execution, count once
    for tid, rs in venue_trade_ids.items():
        if len(rs) > 1:
            rs.sort(key=lambda x: _get(x, "fill_id") or "")
            for r in rs[1:]:
                out[_get(r, "fill_id")] = (
                    NON_EXECUTION,
                    f"duplicate venue trade_id {tid} (kept {_get(rs[0], 'fill_id')})",
                )

    # mirrors: classify per order — coverage requires same market scope,
    # consistent signed position effect, and full quantity coverage
    for oid, ors in by_order.items():
        mirrors = [r for r in ors if is_mirror_row(r)]
        if not mirrors:
            continue
        venue = [
            r for r in ors
            if not is_mirror_row(r) and out.get(_get(r, "fill_id"), (None,))[0] == VERIFIED_VENUE
        ]
        venue_qty = sum(_get(r, "quantity_cc") or 0 for r in venue)
        venue_delta = sum(_get(r, "canonical_yes_delta_cc") or 0 for r in venue)
        for m in mirrors:
            mfid = _get(m, "fill_id")
            m_qty = _get(m, "quantity_cc") or 0
            m_d = _get(m, "canonical_yes_delta_cc") or 0
            if not venue:
                out[mfid] = (UNPAIRED_PROVISIONAL, "no venue twin on order")
                continue
            # scope check: mirror and venue rows must share market + account scope
            m_tk = _get(m, "market_ticker")
            m_sub = _get(m, "subaccount_number")
            v_tks = {_get(v, "market_ticker") for v in venue}
            v_subs = {_get(v, "subaccount_number") for v in venue}
            if (m_tk and v_tks and m_tk not in v_tks) or (
                m_sub is not None and v_subs and m_sub not in v_subs
            ):
                out[mfid] = (
                    SIDE_CONFLICT,
                    f"mirror scope {m_tk}/{m_sub} differs from venue {v_tks}/{v_subs} on {str(oid)[:18]}",
                )
                for v in venue:
                    out[_get(v, "fill_id")] = (
                        SIDE_CONFLICT,
                        f"venue rows conflict with mirror scope on {str(oid)[:18]}",
                    )
                continue
            # position-effect check: signed delta must agree
            if (m_d > 0) != (venue_delta > 0) and m_d != 0 and venue_delta != 0:
                out[mfid] = (
                    SIDE_CONFLICT,
                    f"mirror delta {m_d} vs venue delta {venue_delta} on {str(oid)[:18]}",
                )
                for v in venue:
                    out[_get(v, "fill_id")] = (
                        SIDE_CONFLICT,
                        f"venue rows conflict with mirror-signed record on {str(oid)[:18]}",
                    )
                continue
            if venue_qty >= m_qty:
                out[mfid] = (
                    MIRROR_MATCHED,
                    f"order {str(oid)[:18]} venue qty {venue_qty} >= mirror {m_qty}",
                )
            else:
                out[mfid] = (
                    MIRROR_PARTIAL,
                    f"order {str(oid)[:18]} venue qty {venue_qty} < mirror {m_qty}; "
                    f"unmatched balance {m_qty - venue_qty} unverified",
                )
    return out


def canonical_fill_id_set(rows: Iterable[Any]) -> set:
    """fill_ids comprising the verified authoritative view."""
    cls = classify_fill_rows(rows)
    return {fid for fid, (c, _) in cls.items() if c == VERIFIED_VENUE}


def market_coverage(rows_for_market: Iterable[Any]) -> Dict[str, Any]:
    """Coverage metadata for one market's accounting surface.

    Consumers must surface this alongside verified values so a zero
    residual is never silently read as 'verified flat' and a verified-only
    total is never silently read as complete market truth.
    """
    rows = list(rows_for_market)
    cls = classify_fill_rows(rows)
    excl: Dict[str, int] = defaultdict(int)
    reasons = []
    verified = 0
    for r in rows:
        fid = _get(r, "fill_id")
        c, ev = cls.get(fid, (None, ""))
        if c == VERIFIED_VENUE:
            verified += 1
        elif c in (MIRROR_MATCHED, MIRROR_PARTIAL, SIDE_CONFLICT, UNPAIRED_PROVISIONAL):
            excl[c] += 1
            reasons.append(f"{fid}:{c}:{ev}")
    if excl.get(SIDE_CONFLICT):
        status = "conflict_quarantined"
    elif excl.get(MIRROR_PARTIAL):
        status = "incomplete_coverage"
    elif excl.get(UNPAIRED_PROVISIONAL):
        status = "provisional_unverified"
    elif excl.get(MIRROR_MATCHED):
        status = "verified_with_excluded_mirrors"
    else:
        status = "verified_complete"
    return {
        "verified_record_count": verified,
        "coverage_status": status,
        "excluded_record_count": sum(excl.values()),
        "excluded_by_class": dict(excl),
        "exclusion_reasons": reasons,
        "canonical_contract_version": CANONICAL_CONTRACT_VERSION,
    }
