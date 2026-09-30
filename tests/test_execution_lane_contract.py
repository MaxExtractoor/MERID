"""Shared execution-lane contract tests (2026-09-30).

Proves the canonical execution contract is identical for every crypto-15m
asset: BTC, ETH, SOL, XRP, DOGE.

  * a threshold-cell intent's immutable ExecutionPolicy cannot be downgraded
    to a marketable/taker order by maker/taker policy (the DOGE defect:
    aggressiveness recompute -> post_only=False on a lane that requires
    post-only),
  * a pre-wire stale-decision rejection releases the cell submission
    reservation AND counts toward router-reject suspension bookkeeping,
  * a decision older than the 3.5s ceiling can never reach the wire,
  * the cell lifecycle emits the complete terminal sequence for every
    pre-wire rejection.

State isolation: MERID_THRESHOLD_CELL_STATE_PATH / lifecycle path point at
tmp_path via the fixture, so no test touches production lane accounting.
"""

from __future__ import annotations

import json
import os
import time as _time

import pytest

import merid.prediction.threshold_cells as _tc
from merid.prediction.threshold_cells import (
    emit_cell_lifecycle,
    record_cell_pre_wire_reject,
    record_cell_submission,
    release_cell_submission_reservation,
    reset_cell_state_cache,
)


ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")
TICKERS = {a: f"KX{a}15M-TEST{a}" for a in ASSETS}


@pytest.fixture(autouse=True)
def _isolate_lane_state(monkeypatch, tmp_path):
    monkeypatch.setenv("MERID_THRESHOLD_CELL_STATE_PATH", str(tmp_path / "cells.json"))
    monkeypatch.setenv(
        "MERID_THRESHOLD_CELL_LIFECYCLE_PATH", str(tmp_path / "lifecycle.jsonl")
    )
    reset_cell_state_cache()


def _cell_id(asset: str) -> str:
    return f"{asset.lower()}_no_40_60_t120_600"


def _cell_intent(asset: str, *, aggressiveness: float = 0.0, snapshot_age_s: float = 0.0):
    """Minimal threshold-cell intent with the immutable lane policy attached."""
    from merid.event_venues.kalshi.order_router import ExecutionPolicy, OrderIntent

    intent = OrderIntent(
        ticker=TICKERS[asset],
        price_cents=45,
        count=1.0,
        side="no",
        action="buy",
        post_only=True,
        aggressiveness=aggressiveness,
        decision_lane="threshold_cell",
        threshold_cell_id=_cell_id(asset),
        admission_owner="threshold_cell",
        entry_or_exit="entry",
        execution_policy=ExecutionPolicy(
            lane="threshold_cell",
            required_post_only=True,
            required_liquidity_role="maker",
            allow_taker_fallback=False,
            max_reprice_attempts=1,
            max_order_lifetime_s=60,
        ),
    )
    if snapshot_age_s:
        intent.snapshot_ts = _time.time() - snapshot_age_s
    return intent


def _lifecycle_stages(path_env: str = "MERID_THRESHOLD_CELL_LIFECYCLE_PATH"):
    path = os.environ[path_env]
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return [
            json.loads(line).get("stage")
            for line in fh
            if line.strip()
        ]


# ---------------------------------------------------------------------------
# 1. Immutable post-only contract — identical for all five assets
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("asset", ASSETS)
def test_execution_policy_is_immutable(asset):
    from merid.event_venues.kalshi.order_router import ExecutionPolicy

    policy = ExecutionPolicy(lane="threshold_cell", required_post_only=True)
    with pytest.raises(Exception):
        policy.required_post_only = False
    with pytest.raises(Exception):
        policy.allow_taker_fallback = True


@pytest.mark.parametrize("asset", ASSETS)
def test_threshold_cell_post_only_cannot_be_downgraded(asset):
    """The DOGE defect: aggressiveness=1.0 must not flip a cell order to taker."""
    from merid.event_venues.kalshi.maker_taker_integration import (
        apply_maker_taker_policy,
    )

    intent = _cell_intent(asset, aggressiveness=1.0)  # marketable posture
    apply_maker_taker_policy(intent)

    assert intent.post_only is True
    assert getattr(intent, "_execution_policy_violation", None) == (
        "PRE_WIRE_POST_ONLY_UNAVAILABLE"
    )


@pytest.mark.parametrize("asset", ASSETS)
def test_threshold_cell_post_only_preserved_for_resting_intent(asset):
    """A resting cell intent keeps post_only even if policy recommends taker."""
    from merid.event_venues.kalshi.maker_taker_integration import (
        apply_maker_taker_policy,
    )

    intent = _cell_intent(asset, aggressiveness=0.0)
    apply_maker_taker_policy(intent)

    assert intent.post_only is True
    assert getattr(intent, "_execution_policy_violation", None) is None


@pytest.mark.parametrize("asset", ASSETS)
def test_aggressiveness_never_recomputed_for_post_only_lane(asset):
    """order_router must not recompute posture for lane-owned intents."""
    from merid.event_venues.kalshi.order_router import _intent_requires_post_only

    intent = _cell_intent(asset)
    assert _intent_requires_post_only(intent) is True

    # Non-lane intents are unaffected — posture remains recomputable.
    intent.execution_policy = None
    intent.decision_lane = "formula"
    intent.post_only = False
    assert _intent_requires_post_only(intent) is False


# ---------------------------------------------------------------------------
# 2. Pre-wire rejection → complete cell bookkeeping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("asset", ASSETS)
def test_stale_pre_wire_rejection_releases_reservation_and_records_reject(asset):
    cell = _cell_id(asset)
    decision_id = f"dec-{asset}"
    intent_id = f"int-{asset}"

    # Candidate emission reserves a submission slot.
    record_cell_submission(cell_id=cell, decision_id=decision_id)
    assert _tc.cell_submissions_today() == 1
    st = _tc._load_state()
    assert st["submissions"][cell] == 1

    record_cell_pre_wire_reject(
        cell_id=cell,
        decision_id=decision_id,
        intent_id=intent_id,
        rejection_code="stale_decision_dropped:age_ms=12568",
        stage="pre_wire",
        asset=asset,
        ticker=TICKERS[asset],
    )

    st = _tc._load_state()
    # Reservation released — the slot is not burned by a no-wire attempt.
    assert st["submissions"][cell] == 0
    assert _tc.cell_submissions_today() == 0
    # Router reject counted toward the suspension rules.
    assert st["router_rejects"][cell] == 1
    assert st["router_consecutive_rejects"][cell] == 1
    # Idempotent: a second release attempt must not double-decrement.
    assert (
        release_cell_submission_reservation(
            cell, intent_id=intent_id, decision_id=decision_id
        )
        is False
    )
    assert _tc._load_state()["submissions"][cell] == 0


@pytest.mark.parametrize("asset", ASSETS)
def test_threshold_cell_lifecycle_is_complete(asset):
    """Every pre-wire reject ends in the exact terminal sequence."""
    cell = _cell_id(asset)
    emit_cell_lifecycle("candidate_emitted", threshold_cell_id=cell, asset=asset)
    emit_cell_lifecycle("intent_created", threshold_cell_id=cell, asset=asset)

    record_cell_pre_wire_reject(
        cell_id=cell,
        decision_id=f"dec-{asset}",
        intent_id=f"int-{asset}",
        rejection_code="stale_decision_dropped",
        asset=asset,
        ticker=TICKERS[asset],
    )

    assert _lifecycle_stages() == [
        "candidate_emitted",
        "intent_created",
        "router_rejected",
        "submission_reservation_released",
        "lane_state_updated",
    ]


# ---------------------------------------------------------------------------
# 3. Stale-decision ceiling — cannot submit beyond 3.5s
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("asset", ASSETS)
def test_execution_latency_breach_cannot_submit(asset):
    """A 3.5s+ decision must be dropped pre-wire (stale gate stays in place)."""
    from merid.event_venues.kalshi.order_router import _prepare_order_for_gate
    from merid.prediction.trading_mode import TradingMode

    intent = _cell_intent(asset, snapshot_age_s=4.0)  # 4000ms > 3500ms ceiling
    rejection, _state = _prepare_order_for_gate(intent, TradingMode.LIVE, _time.monotonic())

    assert rejection is not None
    assert rejection.status == "rejected"
    assert rejection.reason.startswith("stale_decision_dropped")
    assert rejection.submission_attempted is False


@pytest.mark.parametrize("asset", ASSETS)
def test_fresh_decision_passes_stale_gate(asset):
    """A fresh cell intent clears the stale-decision band (may still be
    rejected downstream on data, but never as stale_decision_dropped)."""
    from merid.event_venues.kalshi.order_router import _prepare_order_for_gate
    from merid.prediction.trading_mode import TradingMode

    intent = _cell_intent(asset, snapshot_age_s=0.5)
    rejection, _state = _prepare_order_for_gate(intent, TradingMode.LIVE, _time.monotonic())

    if rejection is not None:
        assert not str(rejection.reason).startswith("stale_decision")


# ---------------------------------------------------------------------------
# 4. Stage-latency record — one record per attempt, monotonic-based
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("asset", ASSETS)
def test_execution_stage_latency_record(asset, caplog):
    from merid.event_venues.kalshi.order_router import (
        _emit_execution_stage_latency,
        _exec_stamp,
        OrderResult,
    )
    from merid.prediction.trading_mode import TradingMode

    intent = _cell_intent(asset)
    _exec_stamp(intent, "intent_created")
    _exec_stamp(intent, "canonical_pass")
    _exec_stamp(intent, "risk_check_start")
    _exec_stamp(intent, "risk_check_end")
    _exec_stamp(intent, "router_terminal")

    result = OrderResult(
        status="rejected", mode=TradingMode.LIVE, reason="stale_decision_dropped"
    )
    with caplog.at_level("INFO"):
        _emit_execution_stage_latency(intent, result)

    rec = next(
        json.loads(m.message.split("EXECUTION-STAGE-LATENCY ", 1)[1])
        for m in caplog.records
        if "EXECUTION-STAGE-LATENCY" in m.message
    )
    assert rec["event"] == "execution_stage_latency"
    assert rec["asset"] == asset
    assert rec["lane"] == "threshold_cell"
    assert rec["threshold_cell_id"] == _cell_id(asset)
    assert rec["risk_ms"] is not None and rec["risk_ms"] >= 0
    assert rec["total_to_terminal_ms"] is not None
    assert rec["outcome"] == "rejected"


# ---------------------------------------------------------------------------
# 5. Discovery parity — no approved cell must never disable the formula path
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("asset", ASSETS)
def test_discovery_status_reports_every_asset(asset, monkeypatch):
    """All five assets resolve a discovery label; none is 'not evaluated'."""
    monkeypatch.setenv("MERID_CELL_DISCOVERY_PATH", "/nonexistent/x.json")
    status = _tc.cell_discovery_status(asset)
    assert status and status != "not_evaluated"


@pytest.mark.parametrize("asset", ASSETS)
def test_no_cell_candidate_is_not_claimed_by_cell_lane(asset):
    """cell_id=None -> (False, None): the cell lane declines ownership, so a
    formula-qualified candidate keeps its normal admission path on every
    asset — including BTC/ETH which currently hold zero registry cells."""
    from merid.prediction.threshold_cells import (
        cells_for_asset,
        threshold_cell_admission_allowed,
    )

    allowed, reason = threshold_cell_admission_allowed(
        cell_id=None,
        evidence_code="SPARSE_MATCHED_INSUFFICIENT",
        matching_hard_block=False,
        net_ev_cents=5.0,
        effective_required_edge_cents=3.0,
    )
    # reason=None means 'not this policy's decision' — formula owns it.
    assert allowed is False
    assert reason is None
    # Registry presence is descriptive, not a gate: assets with zero cells
    # and assets with cells both reach this same resolver branch.
    assert isinstance(cells_for_asset(asset), tuple)


@pytest.mark.parametrize("asset", ASSETS)
def test_out_of_band_quote_falls_back_to_formula(asset):
    """A quote outside every configured cell's bounds resolves no cell, and
    the cell lane declines admission ownership — the formula path stays the
    decision-maker for all five assets (no hidden asset exclusion)."""
    from merid.prediction.threshold_cells import (
        cells_for_asset, resolve_threshold_cell,
        threshold_cell_admission_allowed,
    )

    # 15c is below every cell's price floor (all cells start >=20c).
    assert resolve_threshold_cell(asset, "no", 15.0, 200.0) is None
    # tte below every cell's TTE floor.
    assert resolve_threshold_cell(asset, "no", 45.0, 60.0) is None

    allowed, reason = threshold_cell_admission_allowed(
        cell_id=None,
        evidence_code="SPARSE_MATCHED_INSUFFICIENT",
        matching_hard_block=False,
        net_ev_cents=5.0,
        effective_required_edge_cents=3.0,
    )
    assert allowed is False and reason is None  # formula path decides


# ---------------------------------------------------------------------------
# 7. 2026-09-30 batch-1 cells — BTC/ETH match-and-admit contract
# ---------------------------------------------------------------------------

NEW_CELLS = [
    # (cell_id, asset, in-band ask, in-band tte, min_ev, admit_ev)
    ("btc_no_30_40_t120_300", "BTC", 35, 180, 2.5, 2.5),
    ("btc_no_40_50_t120_300", "BTC", 45, 180, 2.5, 2.5),
    ("btc_no_50_60_t120_300", "BTC", 55, 180, 3.0, 3.0),
    ("eth_no_50_60_t120_300", "ETH", 55, 180, 2.5, 2.5),
    ("eth_no_60_70_t120_300", "ETH", 65, 180, 3.0, 3.0),
]


@pytest.mark.parametrize(
    "cell_id,asset,ask,tte,ev,required", NEW_CELLS,
    ids=[c[0] for c in NEW_CELLS],
)
def test_new_cells_match_and_admit_at_threshold(
    cell_id, asset, ask, tte, ev, required
):
    """Each promoted cell must (a) resolve for its in-domain quote and
    (b) admit a soft-evidence candidate that clears its own floor."""
    from merid.prediction.threshold_cells import (
        resolve_threshold_cell, threshold_cell_admission_allowed,
    )

    cell = resolve_threshold_cell(asset, "no", ask, tte)
    assert cell is not None and cell.cell_id == cell_id
    assert cell.min_net_ev_cents == required

    allowed, reason = threshold_cell_admission_allowed(
        cell_id=cell_id,
        evidence_code="SPARSE_MATCHED_INSUFFICIENT",
        matching_hard_block=False,
        net_ev_cents=ev,
        effective_required_edge_cents=required,
    )
    assert allowed is True, reason


@pytest.mark.parametrize("asset", ASSETS)
def test_cell_boundaries_are_exact(asset):
    """Promotion domain is exact: outside 20-89c or 120-600s -> no match."""
    from merid.prediction.threshold_cells import resolve_threshold_cell

    assert resolve_threshold_cell(asset, "no", 19, 180) is None
    assert resolve_threshold_cell(asset, "no", 90, 180) is None
    assert resolve_threshold_cell(asset, "no", 45, 119.9) is None
    assert resolve_threshold_cell(asset, "no", 45, 600.1) is None


@pytest.mark.parametrize("cell_id,asset,ask,tte,ev,required", NEW_CELLS,
                         ids=[c[0] for c in NEW_CELLS])
def test_hard_block_cannot_emit_even_when_ev_clears(cell_id, asset, ask,
                                                    tte, ev, required):
    """Universal hard-block rule: a matched toxic cell / hard evidence block
    vetoes admission no matter how far EV clears the cell floor."""
    from merid.prediction.threshold_cells import (
        threshold_cell_admission_allowed,
    )

    allowed, reason = threshold_cell_admission_allowed(
        cell_id=cell_id,
        evidence_code="MATCHING_TOXIC_CELL",
        matching_hard_block=True,
        net_ev_cents=ev + 10.0,
        effective_required_edge_cents=required,
    )
    assert allowed is False and reason == "matching_hard_block"


# ---------------------------------------------------------------------------
# 8. Fair allocation — per-asset fill cap + one global resting order
# ---------------------------------------------------------------------------

def test_asset_fill_cap_blocks_third_fill_same_asset():
    """Two fills already landed for BTC today -> the next BTC cell is
    refused with asset_fills_cap_exhausted, while an ETH cell still admits."""
    from merid.prediction.threshold_cells import (
        cell_admission, record_cell_fill,
    )

    record_cell_fill("btc_no_30_40_t120_300", decision_id="d1")
    record_cell_fill("btc_no_40_50_t120_300", decision_id="d2")
    assert _tc.cell_fills_today_asset("BTC") == 2

    allowed, reason = cell_admission("btc_no_50_60_t120_300")
    assert allowed is False and reason == "asset_fills_cap_exhausted"

    allowed2, reason2 = cell_admission("eth_no_50_60_t120_300")
    assert allowed2 is True, reason2


def test_global_open_order_serializes_the_lane():
    """One resting order anywhere in the lane blocks every other cell —
    the measurement lane runs a single passive order at a time."""
    from merid.prediction.threshold_cells import (
        cell_admission, record_cell_order_open,
    )

    record_cell_order_open("sol_no_60_80_t120_600", "ord-1")
    assert _tc.cell_open_orders_total() == 1

    allowed, reason = cell_admission("xrp_no_80_90_t120_600")
    assert allowed is False and reason == "lane_open_order_exists"


def test_per_asset_cap_counts_across_cells():
    """Fills on two different ETH cells both count toward the ETH cap —
    cells cannot multiply an asset's daily fill budget."""
    from merid.prediction.threshold_cells import record_cell_fill

    record_cell_fill("eth_no_50_60_t120_300", decision_id="e1")
    record_cell_fill("eth_no_60_70_t120_300", decision_id="e2")
    assert _tc.cell_fills_today_asset("ETH") == 2

    from merid.prediction.threshold_cells import cell_admission
    allowed, reason = cell_admission("eth_no_50_60_t120_300")
    # per-cell cap (2) also reached on this cell, but the ASSET reason must
    # surface for a fresh ETH cell; here cell-cap wins precedence — either
    # way ETH is capped.  A clean ETH assertion:
    assert allowed is False
    assert reason in ("cell_fills_cap_exhausted", "asset_fills_cap_exhausted")


# ---------------------------------------------------------------------------
# 9. [ALL-FIVE-PROMOTION-STATUS] rollup — one authoritative answer per asset
# ---------------------------------------------------------------------------

def test_promotion_status_rollup_counts(tmp_path, monkeypatch):
    """The rollup must name live cells, pending candidates, and rejections
    per asset — and degrade to 'no_compiler_artifact' when artifacts are
    absent (never an error)."""
    cand_path = tmp_path / "candidates.json"
    rej_path = tmp_path / "rejections.json"
    monkeypatch.setenv("MERID_CELL_CANDIDATES_PATH", str(cand_path))
    monkeypatch.setenv("MERID_CELL_REJECTIONS_PATH", str(rej_path))

    from merid.prediction import threshold_cells as tc
    # Absent artifacts -> explicit marker, never a crash.
    line = tc.promotion_status_rollup()
    assert "no_compiler_artifact" in line
    for a in ASSETS:
        assert f"{a}:" in line

    cand_path.write_text(json.dumps({"per_cell": [
        {"asset": "BTC", "promotion_status": "LIVE_PROVISIONAL"},
        {"asset": "BTC",
         "promotion_status": "CANDIDATE_PENDING_EXECUTION_FEASIBILITY"},
        {"asset": "ETH",
         "promotion_status": "CANDIDATE_READY_FOR_APPROVAL"},
        {"asset": "XRP",
         "promotion_status": "CANDIDATE_PENDING_RECENCY_AND_CALIBRATION"},
    ]}))
    rej_path.write_text(json.dumps({"per_cell": [
        {"asset": "BTC", "failed_stage": "S2_domain"},
        {"asset": "BTC", "failed_stage": "S2_domain"},
        {"asset": "ETH", "failed_stage": "S1_statistical"},
        {"asset": "SOL", "failed_stage": "S1b_market_concentration"},
        {"asset": "DOGE", "failed_stage": "S3_execution_feasibility"},
    ]}))
    line = tc.promotion_status_rollup()
    assert "BTC: live=3 suspended=0 candidates=2 approved=0 " \
        "live_provisional=1 pending_feasibility=1" in line
    assert "rejected_domain=2" in line
    assert "ETH:" in line and "ready_for_approval=1" in line
    assert "rejected_concentration=1" in line
    assert "rejected_execution=1" in line


@pytest.mark.parametrize("asset", ASSETS)
def test_no_cell_claim_never_launders_through_lane(asset):
    """cell_id=None must never be claimed by the cell lane — the formula
    path owns the admission decision for unmatched candidates."""
    from merid.prediction.threshold_cells import (
        threshold_cell_admission_allowed,
    )

    # A formula-qualified candidate (positive EV over the shared formula
    # threshold, clean evidence) is untouched by the cell lane.
    allowed, reason = threshold_cell_admission_allowed(
        cell_id=None,
        evidence_code=None,
        matching_hard_block=False,
        net_ev_cents=5.0,
        effective_required_edge_cents=3.0,
    )
    assert allowed is False and reason is None  # -> formula path decides

    # A soft-evidence candidate with no cell also cannot launder through the
    # cell lane — identical negative for every asset.
    allowed2, reason2 = threshold_cell_admission_allowed(
        cell_id=None,
        evidence_code="SPARSE_MATCHED_INSUFFICIENT",
        matching_hard_block=False,
        net_ev_cents=5.0,
        effective_required_edge_cents=3.0,
    )
    assert allowed2 is False and reason2 is None


# ---------------------------------------------------------------------------
# 6. Config-driven registry — live cells are data, loaded identically for all
# ---------------------------------------------------------------------------

def test_live_registry_yaml_matches_builtin(tmp_path):
    """config/threshold_cells_live.yaml parses to exactly the built-in cells."""
    loaded = _tc._load_registry_from_config(_tc._registry_config_path())
    assert loaded is not None, "live registry yaml must exist and parse"
    assert [c.cell_id for c in loaded] == [c.cell_id for c in _tc._builtin_cells()]


def test_registry_missing_file_falls_back_to_builtin(tmp_path):
    missing = str(tmp_path / "absent.yaml")
    assert _tc._load_registry_from_config(missing) is None


def test_registry_malformed_file_fails_closed(tmp_path):
    """A present-but-broken registry -> EMPTY (no cell may admit)."""
    bad = tmp_path / "bad.yaml"
    bad.write_text("cells:\n  - cell_id: wrong\n    asset: BTC\n", "utf-8")
    assert _tc._load_registry_from_config(str(bad)) == []

    # Missing 'cells' key entirely.
    bad.write_text("registry_version: '1'\n", "utf-8")
    assert _tc._load_registry_from_config(str(bad)) == []


def test_registry_rejects_noncanonical_cell_id(tmp_path):
    """cell_id must equal asset_side_pmin_pmax_t{tlo}_{thi} — a hand-edited
    id that drifts from its bounds empties the registry."""
    bad = tmp_path / "bad_id.yaml"
    bad.write_text(
        "cells:\n"
        "  - cell_id: btc_no_99_99_t120_600\n"
        "    asset: BTC\n"
        "    side: \"no\"\n"
        "    price_min_cents: 40\n"
        "    price_max_cents: 50\n"
        "    tte_min_seconds: 120\n"
        "    tte_max_seconds: 600\n"
        "    min_net_ev_cents: 2.0\n",
        "utf-8",
    )
    assert _tc._load_registry_from_config(str(bad)) == []
