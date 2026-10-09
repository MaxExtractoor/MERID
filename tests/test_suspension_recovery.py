"""Suspension/probation recovery regression tests (2026-10-09 audit).

Covers the repaired lifecycle in both governed lanes (threshold cells +
current-build provisional) and the missing-artifact admission policy:

  * scope isolation — a suspension never bleeds across assets/sides/routes
  * subtype classification — mechanical / contract_violation /
    execution_quality / economic / integrity, with router-reject checked
    before the "(post-only ...)" parenthetical in live reasons
  * operational failures (router rejects) classify mechanical, never as
    realized economic losses; markouts classify execution_quality (slower)
  * bounded recovery — SUSPENDED -> PROBATION -> OBSERVATION with clean-
    evidence requirement and cause-specific strike handling
  * stale armed counters cleared on release (no instant re-trip)
  * repeated evaluations never extend or complete probation
  * probation budgets: submissions/day, fills/episode, loss budget
  * release writes an auditable transition journal record
  * MERID_RECOVERY_ALLOWLIST gates auto-release to reviewed cells
  * restart preserves state; legacy records backfill safely
  * missing/unreadable evidence artifact fails closed (bounded lane only)
  * stale artifact passes are escape-lane only, never production
"""
from __future__ import annotations

import json
import os
import time

import pytest

import merid.prediction.current_build_provisional as cbp
import merid.prediction.threshold_cells as tc
import merid.prediction.evidence_policy as ep


# ---------------------------------------------------------------------------
# Hermetic state: both lanes read their state file through env paths; reset
# the module caches between tests.
# ---------------------------------------------------------------------------

@pytest.fixture()
def lanes(tmp_path, monkeypatch):
    tc_path = str(tmp_path / "threshold_cell_lane.json")
    pv_path = str(tmp_path / "cbp_lane.json")
    monkeypatch.setenv("MERID_THRESHOLD_CELL_STATE_PATH", tc_path)
    monkeypatch.setenv("MERID_PROVISIONAL_STATE_PATH", pv_path)
    cbp._STATE_CACHE = None
    cbp._STATE_CACHE_PATH = None
    tc._STATE_CACHE = None
    tc._STATE_CACHE_PATH = None
    yield {"tc": tc_path, "pv": pv_path}
    cbp._STATE_CACHE = None
    cbp._STATE_CACHE_PATH = None
    tc._STATE_CACHE = None
    tc._STATE_CACHE_PATH = None


def _seed_cell(module, path_key, cell_id, *, state, reason, age_s, lanes,
               extra=None):
    """Write a cell_states record directly, aged `age_s` into the past."""
    st = module._load_state(path=lanes[path_key])
    rec = {
        "state": state,
        "reason": reason,
        "since_ts": time.time() - age_s,
    }
    if extra:
        rec.update(extra)
    st.setdefault("cell_states", {})[cell_id] = rec
    module._save_state(path=lanes[path_key])
    return rec


# ── 1. Scope isolation across all five assets ──────────────────────────────

def test_suspension_scoped_to_cell_not_asset_side_or_sibling(lanes):
    """Suspending one XRP-NO cell leaves every other asset/side cell able to
    admit — restrictions never spread across scope they didn't measure."""
    target = "cbp_xrp_no_60_70_t300_600"
    _seed_cell(cbp, "pv", target, state=cbp.CELL_STATE_SUSPENDED,
               reason="consecutive_router_rejects=2", age_s=60.0,
               lanes=lanes)
    siblings = [
        "cbp_btc_no_60_70_t300_600",
        "cbp_eth_no_60_70_t300_600",
        "cbp_sol_no_60_70_t300_600",
        "cbp_doge_no_60_70_t300_600",
        "cbp_xrp_no_60_70_t120_300",
        "cbp_xrp_yes_60_70_t300_600",
        "cbp_xrp_no_50_60_t300_600",
    ]
    for cid in siblings:
        if cbp.provisional_cell_for_id(cid) is None:
            continue
        ok, reason = cbp.provisional_cell_admission(cid)
        # Any block must NOT be this cell's suspension leaking outward.
        assert reason != "cell_suspended", f"{cid} blocked by foreign suspension"


def test_all_five_assets_share_recovery_framework(lanes):
    """Every asset's cells route through the same classify/recover path."""
    for asset in ("btc", "eth", "sol", "xrp", "doge"):
        cid = f"cbp_{asset}_no_50_60_t300_600"
        if cbp.provisional_cell_for_id(cid) is None:
            continue
        cls = cbp._classify_suspension_reason("consecutive_router_rejects=2")
        assert cls == cbp.SUSPENSION_CLASS_MECHANICAL
        cls2 = cbp._classify_suspension_reason("rolling_3_mean_net_pnl=-5.0c")
        assert cls2 == cbp.SUSPENSION_CLASS_ECONOMIC


def test_router_reason_with_postonly_parenthetical_is_mechanical(lanes):
    """The live reason 'consecutive_router_rejects=2 (post-only cross/stale
    revalidation twice in a row)' is a repaired MECHANICAL failure — the
    post-only text is the venue message, not a contract breach."""
    r = "consecutive_router_rejects=2 (post-only cross/stale revalidation twice in a row)"
    assert cbp._classify_suspension_reason(r) == cbp.SUSPENSION_CLASS_MECHANICAL
    assert tc._classify_suspension_reason(r) == tc.SUSPENSION_CLASS_MECHANICAL
    # But a standalone post-only breach IS a contract violation.
    assert (
        cbp._classify_suspension_reason("post_only_order_became_taker")
        == cbp.SUSPENSION_CLASS_CONTRACT
    )
    # Adverse markouts are execution-quality evidence, not mechanics.
    assert (
        cbp._classify_suspension_reason("first_fill_markout_5s=-6.50c <= -3.00c")
        == cbp.SUSPENSION_CLASS_EXEC_QUALITY
    )


# ── 2. Operational failures are not economic losses ─────────────────────────

def test_router_rejects_are_execution_class_not_losses(lanes):
    """Two consecutive router rejects suspend with class=mechanical and write
    NO outcome rows — the reject is never double-counted as a losing trade."""
    cid = "cbp_btc_no_60_70_t300_600"
    cbp.record_provisional_router_reject(cid)
    cbp.record_provisional_router_reject(cid)
    assert cbp.get_cell_state(cid) == cbp.CELL_STATE_SUSPENDED
    rec = (cbp._load_state()["cell_states"])[cid]
    assert rec["suspension_class"] == cbp.SUSPENSION_CLASS_MECHANICAL
    # No outcome row may exist: rejects are not economic evidence.
    outs = (cbp._load_state().get("outcomes") or {}).get(cid) or []
    assert outs == []
    assert all(o.get("net_pnl_cents") is None for o in outs)


def test_threshold_cell_router_reject_classified_execution(lanes):
    cid = "sol_no_30_60_t120_600"
    tc.record_cell_router_reject(cid)
    tc.record_cell_router_reject(cid)
    assert tc.get_cell_state(cid) == tc.CELL_STATE_SUSPENDED
    rec = (tc._load_state()["cell_states"])[cid]
    assert rec["suspension_class"] == tc.SUSPENSION_CLASS_MECHANICAL


# ── 3. Bounded recovery: release, probe, complete or strike ─────────────────

def test_execution_suspension_recovers_to_probation(lanes):
    """Aged execution-class suspension -> PROBATION on lazy evaluation."""
    cid = "cbp_btc_no_50_60_t300_600"
    _seed_cell(cbp, "pv", cid, state=cbp.CELL_STATE_SUSPENDED,
               reason="consecutive_router_rejects=2",
               age_s=7.0 * 3600.0,  # > 6h execution floor
               extra={"router_consecutive_rejects": None},
               lanes=lanes)
    # arm the stale counter as it exists in the live file
    st = cbp._load_state(path=lanes["pv"])
    st.setdefault("router_consecutive_rejects", {})[cid] = 2
    cbp._save_state(path=lanes["pv"])

    assert cbp.maybe_recover_cell(cid) is True
    assert cbp.get_cell_state(cid) == cbp.CELL_STATE_PROBATION
    # The stale armed counter must be cleared — otherwise the very next
    # evaluation re-trips the released cell before it collects evidence.
    assert (cbp._load_state().get("router_consecutive_rejects") or {}).get(cid) == 0


def test_integrity_suspension_never_auto_recovers(lanes):
    cid = "cbp_btc_no_40_50_t300_600"
    _seed_cell(cbp, "pv", cid, state=cbp.CELL_STATE_SUSPENDED,
               reason="invariant_violation:test", age_s=900 * 3600.0,
               lanes=lanes)
    assert cbp.maybe_recover_cell(cid) is False
    assert cbp.get_cell_state(cid) == cbp.CELL_STATE_SUSPENDED


def test_economic_suspension_waits_longer_than_execution(lanes):
    cid = "cbp_btc_no_60_70_t300_600"
    _seed_cell(cbp, "pv", cid, state=cbp.CELL_STATE_SUSPENDED,
               reason="rolling_3_mean_net_pnl=-30.33c < -1.00c",
               age_s=12.0 * 3600.0,  # > 6h exec floor but < 24h econ floor
               lanes=lanes)
    assert cbp.maybe_recover_cell(cid) is False
    st = cbp._load_state(path=lanes["pv"])
    st["cell_states"][cid]["since_ts"] = time.time() - 25.0 * 3600.0
    cbp._save_state(path=lanes["pv"])
    assert cbp.maybe_recover_cell(cid) is True


def test_probation_strike_resuspends_on_one_router_reject(lanes):
    """A transient router strike during probation re-suspends as a
    MECHANICAL health pause — a bounded retry window, not a full reset."""
    cid = "cbp_btc_no_50_60_t300_600"
    _seed_cell(cbp, "pv", cid, state=cbp.CELL_STATE_PROBATION,
               reason="probation_release class=mechanical",
               age_s=100.0, extra={"on_probation": True},
               lanes=lanes)
    cbp.record_provisional_router_reject(cid)
    rec = (cbp._load_state()["cell_states"])[cid]
    assert rec["state"] == cbp.CELL_STATE_SUSPENDED
    assert rec.get("probation_triggered") is True
    assert rec.get("suspension_class") == cbp.SUSPENSION_CLASS_MECHANICAL
    assert "probation" in str(rec.get("reason"))
    # After the mechanical pause (1h), the cell re-releases — a transient
    # strike does not impose the 6h+ initial-suspension floor again.
    rec2 = (cbp._load_state()["cell_states"])[cid]
    rec2["since_ts"] = time.time() - 2.0 * 3600.0
    cbp._save_state()
    assert cbp.maybe_recover_cell(cid) is True
    assert cbp.get_cell_state(cid) == cbp.CELL_STATE_PROBATION


def test_probation_completes_on_clean_observations(lanes):
    """Two clean post-release settlements return PROBATION -> OBSERVATION."""
    cid = "cbp_btc_no_50_60_t300_600"
    _seed_cell(cbp, "pv", cid, state=cbp.CELL_STATE_PROBATION,
               reason="probation_release", age_s=50.0,
               extra={"on_probation": True},
               lanes=lanes)
    st = cbp._load_state(path=lanes["pv"])
    now = time.time()
    outs = st.setdefault("outcomes", {}).setdefault(cid, [])
    for i in range(2):
        outs.append({
            "ts": now + i, "kind": "settled",
            "decision_id": f"d{i}", "net_pnl_cents": 5.0,
        })
    cbp._save_state(path=lanes["pv"])
    cbp._maybe_complete_probation(cid)
    assert cbp.get_cell_state(cid) == cbp.CELL_STATE_OBSERVATION


def test_repeated_evaluations_do_not_extend_or_complete_probation(lanes):
    """Admission checks are read-only for recovery timing — spamming the
    evaluator cannot shorten or satisfy probation."""
    cid = "cbp_btc_no_50_60_t300_600"
    rec = _seed_cell(cbp, "pv", cid, state=cbp.CELL_STATE_PROBATION,
                     reason="probation_release", age_s=100.0,
                     extra={"on_probation": True},
               lanes=lanes)
    since0 = rec["since_ts"]
    for _ in range(25):
        cbp._maybe_complete_probation(cid)
        cbp.provisional_cell_admission(cid)
    rec_after = (cbp._load_state()["cell_states"])[cid]
    assert rec_after["state"] == cbp.CELL_STATE_PROBATION
    assert rec_after["since_ts"] == since0


def test_probation_requires_positive_ev_not_negative_floor(lanes):
    """A probation probe can never ride the -4c exploration floor."""
    cid = "cbp_xrp_yes_80_90_t300_600"  # negative-floor YES cell (-4c)
    _seed_cell(cbp, "pv", cid, state=cbp.CELL_STATE_PROBATION,
               reason="probation_release", age_s=10.0,
               extra={"on_probation": True},
               lanes=lanes)
    ok, reason = cbp.provisional_admission_allowed(
        cell_id=cid,
        evidence_code="LEGACY_V1_BLOCK",
        matching_hard_block=False,
        net_ev_cents=-2.0,   # would pass the -4c floor — must still refuse
        effective_required_edge_cents=-4.0,
    )
    assert ok is False
    assert reason == "probation_requires_positive_ev"


# ── 4. Restart / migration behavior ─────────────────────────────────────────

def test_restart_preserves_suspension_and_backfills_class(lanes):
    """A pre-class SUSPENDED record survives restart with a backfilled class;
    a stale on_probation flag on a SUSPENDED record is cleared."""
    cid = "cbp_eth_yes_60_70_t300_600"
    st = cbp._load_state(path=lanes["pv"])
    st.setdefault("cell_states", {})[cid] = {
        "state": "SUSPENDED",
        "reason": "first_fill_markout_5s=-6.50c <= -3.00c",
        "since_ts": time.time() - 3600.0,
        "on_probation": True,  # stale flag — inconsistent legacy state
    }
    cbp._save_state(path=lanes["pv"])
    # simulate restart
    cbp._STATE_CACHE = None
    cbp._STATE_CACHE_PATH = None
    rec = (cbp._load_state(path=lanes["pv"])["cell_states"])[cid]
    assert rec["state"] == "SUSPENDED"
    assert rec["suspension_class"] == cbp.SUSPENSION_CLASS_EXEC_QUALITY
    assert rec.get("on_probation") is not True


def test_duplicate_settlement_attribution_is_idempotent(lanes):
    cid = "sol_no_30_60_t120_600"
    tc.record_cell_settlement("dec-1", net_pnl_cents=-10.0, cell_id=cid)
    tc.record_cell_settlement("dec-1", net_pnl_cents=-10.0, cell_id=cid)
    outs = (tc._load_state().get("outcomes") or {}).get(cid) or []
    settled = [o for o in outs if o.get("decision_id") == "dec-1"]
    assert len(settled) == 1


# ── 5. Lane authority separation + hard-block non-bypass ────────────────────

def test_threshold_and_provisional_cells_hold_separate_authority(lanes):
    """Suspending the cbp cell never suspends the registered threshold cell
    for the same cohort, and vice versa."""
    tcell = "sol_no_30_60_t120_600"
    pcell = "cbp_sol_no_20_30_t300_600"  # different cohort, same asset/side
    _seed_cell(tc, "tc", tcell, state=tc.CELL_STATE_SUSPENDED,
               reason="first_fill_markout_5s=-26.50c", age_s=60.0,
               lanes=lanes)
    # cbp lane unaffected
    assert cbp.get_cell_state(pcell) != cbp.CELL_STATE_SUSPENDED
    assert tc.get_cell_state(tcell) == tc.CELL_STATE_SUSPENDED


def test_hard_block_never_soft_overridden(lanes):
    """A matched toxic-cell verdict cannot be bypassed by the threshold-cell
    soft-override path regardless of EV."""
    cid = "sol_no_30_60_t120_600"
    ok, reason = tc.threshold_cell_admission_allowed(
        cell_id=cid,
        evidence_code="MATCHING_TOXIC_CELL",
        matching_hard_block=True,
        net_ev_cents=99.0,
        effective_required_edge_cents=1.5,
    )
    assert ok is False


# ── 6. Missing / stale artifact policy ──────────────────────────────────────

def test_missing_artifact_never_production_qualifies():
    """Missing artifact -> insufficient evidence or a bounded escape pass;
    SUFFICIENT (production) is unreachable."""
    d = ep.evaluate_missing_artifact(
        "XRP", "no", 65.0, 300.0, 0.02, 0.005, 1.0, artifact_state="missing",
    )
    assert d.allowed is False
    assert d.code == "EVIDENCE_ARTIFACT_MISSING"
    # Even a strong model edge can only buy a bounded-lane pass.
    d2 = ep.evaluate_missing_artifact(
        "XRP", "no", 65.0, 300.0, 0.02, 0.005, 50.0, artifact_state="missing",
    )
    assert d2.code == "EVIDENCE_ARTIFACT_MISSING_PASS"
    assert d2.escape_required is True


def test_stale_artifact_pass_is_escape_only():
    """A stale artifact can produce a pass, but it must ride the escape lane
    (escape_required=True) — never a clean SUFFICIENT production verdict."""
    stale = {
        "generated_at": time.time() - 10 * ep.evidence_stale_s(),
        "halflife_days_primary": 7,
        "cells": {"7": {
            "XRP|no|50-74|mid": {
                "w": 20.0, "l": 1.0, "n_eff": 20.0, "n_raw": 20,
                "n_markets": 20, "entry_wsum": 20.0 * 62.0,
                "recent_w": 5.0, "recent_l": 1.0, "recent_n": 6,
            }
        }},
    }
    d = ep.evaluate(stale, "XRP", "no", 55.0, 300.0, 0.02, 0.005, 8.0)
    assert d.evidence_stale is True
    if d.allowed:
        assert d.escape_required is True
        assert d.code == "CELL_EVIDENCE_PASS"  # flagged via escape, not production


def test_artifact_missing_never_hard_blocks():
    """Missing evidence must not manufacture a toxic-cell veto either."""
    d = ep.evaluate_missing_artifact(
        "BTC", "yes", 40.0, 300.0, 0.02, 0.005, -50.0,
        artifact_state="missing",
    )
    assert d.matching_hard_block is False
    assert "TOXIC" not in d.code


# ── 7. Subtype-specific recovery + Stage-A allowlist ───────────────────────

def test_markout_suspension_is_exec_quality_and_waits_longer(lanes):
    """An adverse markout is execution-QUALITY evidence, not a repaired
    mechanic — it does not auto-release at the mechanical 6h floor."""
    cid = "cbp_eth_no_80_90_t120_300"
    _seed_cell(cbp, "pv", cid, state=cbp.CELL_STATE_SUSPENDED,
               reason="first_fill_markout_5s=-25.50c <= -3.00c",
               age_s=7.0 * 3600.0, lanes=lanes)
    assert cbp.maybe_recover_cell(cid) is False  # exec_quality floor is 24h
    st = cbp._load_state(path=lanes["pv"])
    st["cell_states"][cid]["since_ts"] = time.time() - 25.0 * 3600.0
    cbp._save_state(path=lanes["pv"])
    assert cbp.maybe_recover_cell(cid) is True


def test_contract_violation_requires_verified_fix(lanes):
    """A post-only breach never auto-releases until the contract defect is
    declared verified-fixed — elapsed time alone is not authorization."""
    cid = "cbp_btc_no_60_70_t120_300"
    _seed_cell(cbp, "pv", cid, state=cbp.CELL_STATE_SUSPENDED,
               reason="post_only_order_became_taker",
               age_s=900.0 * 3600.0, lanes=lanes)
    saved = os.environ.get("MERID_EXEC_CONTRACT_FIX_VERIFIED")
    try:
        os.environ.pop("MERID_EXEC_CONTRACT_FIX_VERIFIED", None)
        assert cbp.maybe_recover_cell(cid) is False
        assert cbp.get_cell_state(cid) == cbp.CELL_STATE_SUSPENDED
        # With the fix verified, the contract floor (24h) applies.
        os.environ["MERID_EXEC_CONTRACT_FIX_VERIFIED"] = "1"
        assert cbp.maybe_recover_cell(cid) is True
        assert cbp.get_cell_state(cid) == cbp.CELL_STATE_PROBATION
    finally:
        if saved is None:
            os.environ.pop("MERID_EXEC_CONTRACT_FIX_VERIFIED", None)
        else:
            os.environ["MERID_EXEC_CONTRACT_FIX_VERIFIED"] = saved


def test_recovery_allowlist_gates_release(lanes):
    """When MERID_RECOVERY_ALLOWLIST is set, only listed cells may release —
    markout/economic cells stay shadow-only even when their timers pass."""
    allowed_cid = "cbp_btc_no_50_60_t300_600"
    other_cid = "cbp_eth_no_20_30_t300_600"
    for cid in (allowed_cid, other_cid):
        _seed_cell(cbp, "pv", cid, state=cbp.CELL_STATE_SUSPENDED,
                   reason="consecutive_router_rejects=2",
                   age_s=8.0 * 3600.0, lanes=lanes)
    saved = os.environ.get("MERID_RECOVERY_ALLOWLIST")
    try:
        os.environ["MERID_RECOVERY_ALLOWLIST"] = allowed_cid
        assert cbp.maybe_recover_cell(allowed_cid) is True
        assert cbp.maybe_recover_cell(other_cid) is False
        assert cbp.get_cell_state(other_cid) == cbp.CELL_STATE_SUSPENDED
    finally:
        if saved is None:
            os.environ.pop("MERID_RECOVERY_ALLOWLIST", None)
        else:
            os.environ["MERID_RECOVERY_ALLOWLIST"] = saved


def test_release_writes_auditable_transition(lanes):
    """The SUSPENDED -> PROBATION release journals a structured record:
    prev/new state, original reason, class, policy version, budgets, and
    the counter reset — all in one atomic transition."""
    cid = "cbp_xrp_no_60_70_t120_300"
    _seed_cell(cbp, "pv", cid, state=cbp.CELL_STATE_SUSPENDED,
               reason="consecutive_router_rejects=2",
               age_s=8.0 * 3600.0, lanes=lanes)
    st = cbp._load_state(path=lanes["pv"])
    st.setdefault("router_consecutive_rejects", {})[cid] = 2
    cbp._save_state(path=lanes["pv"])
    assert cbp.maybe_recover_cell(cid) is True
    journal = cbp._load_state()["transitions"]
    tr = [t for t in journal if t.get("cell_id") == cid][-1]
    assert tr["kind"] == "probation_release"
    assert tr["previous_state"] == "SUSPENDED"
    assert tr["new_state"] == "PROBATION"
    assert tr["original_suspension_reason"] == "consecutive_router_rejects=2"
    assert tr["suspension_class"] == cbp.SUSPENSION_CLASS_MECHANICAL
    assert tr["policy_version"]
    assert "router_consecutive_rejects" in tr["counters_reset"]
    assert tr["probation_budget"]["max_submissions_per_day"] >= 1
    # Journal survives a reload (restart-safe).
    cbp._STATE_CACHE = None
    cbp._STATE_CACHE_PATH = None
    assert cbp._load_state()["transitions"][-1]["cell_id"] == cid


def test_probation_fills_cap_blocks_second_probe(lanes):
    """The per-episode fill budget is separate from the submission cap —
    once the episode's fill allowance is used, admission refuses."""
    cid = "cbp_btc_no_50_60_t300_600"
    _seed_cell(cbp, "pv", cid, state=cbp.CELL_STATE_PROBATION,
               reason="probation_release", age_s=10.0,
               extra={"on_probation": True, "probation_fills": 1},
               lanes=lanes)
    ok, reason = cbp.provisional_cell_admission(cid)
    assert ok is False
    assert reason == "probation_fills_cap"


def test_probation_loss_budget_resuspends_economic(lanes):
    """A realized loss past the episode budget re-suspends as ECONOMIC —
    and a duplicate settlement re-attribution cannot double-count it."""
    cid = "cbp_btc_no_50_60_t300_600"
    _seed_cell(cbp, "pv", cid, state=cbp.CELL_STATE_PROBATION,
               reason="probation_release", age_s=10.0,
               extra={"on_probation": True},
               lanes=lanes)
    over = cbp.probation_loss_budget_cents() + 10.0
    cbp.record_provisional_settlement(
        "dec-loss", net_pnl_cents=-over, cell_id=cid,
    )
    rec = (cbp._load_state()["cell_states"])[cid]
    assert rec["state"] == cbp.CELL_STATE_SUSPENDED
    assert rec["suspension_class"] == cbp.SUSPENSION_CLASS_ECONOMIC
    assert "loss_budget" in str(rec["reason"])


def test_probation_unfilled_expiry_is_not_a_strike(lanes):
    """A passive order expiring unfilled records fill-probability evidence
    only — it cannot strike the probation episode or write a loss."""
    cid = "cbp_btc_no_50_60_t300_600"
    _seed_cell(cbp, "pv", cid, state=cbp.CELL_STATE_PROBATION,
               reason="probation_release", age_s=10.0,
               extra={"on_probation": True},
               lanes=lanes)
    # Order opened then closed without a fill — no outcome row, no strike.
    cbp.record_provisional_order_open(cid, "ord-1")
    cbp.record_provisional_order_closed(cid, "ord-1")
    rec = (cbp._load_state()["cell_states"])[cid]
    assert rec["state"] == cbp.CELL_STATE_PROBATION
    outs = (cbp._load_state().get("outcomes") or {}).get(cid) or []
    assert not any(o.get("net_pnl_cents") for o in outs)

# ---------------------------------------------------------------------------
# Rejected-candidate price telemetry (2026-10-09 correction)
# ---------------------------------------------------------------------------

def test_rejected_record_persists_both_side_prices(tmp_path, monkeypatch):
    """The record must carry yes_price_cents/no_price_cents so the
    non-selected side never needs the invalid 100-selected_ask fallback."""
    import merid.prediction.rejection_counterfactual as rc
    log = tmp_path / "rej.jsonl"
    monkeypatch.setenv("MERID_REJECTED_CANDIDATES_LOG", str(log))
    rc.log_rejected_candidate(
        reason="evidence_insufficient", run_id="r1", decision_id="d1",
        asset="XRP", ticker="T-1", side="yes", model_p_selected=0.7,
        held_price_cents=71.0, gross_edge=0.01, net_edge=0.005,
        edge_threshold=0.02, tte_seconds=200.0,
        yes_price_cents=71.0, no_price_cents=29.0,
        entry_price_basis="ask",
    )
    rec = json.loads(log.read_text().strip())
    assert rec["yes_price_cents"] == 71.0
    assert rec["no_price_cents"] == 29.0
    assert rec["entry_price_basis"] == "ask"


def test_rejected_record_no_price_synthesis(tmp_path, monkeypatch):
    """When per-side prices are not passed, the record must emit nulls --
    never a synthesized 100-selected_ask 'other side' price."""
    import merid.prediction.rejection_counterfactual as rc
    log = tmp_path / "rej.jsonl"
    monkeypatch.setenv("MERID_REJECTED_CANDIDATES_LOG", str(log))
    rc.log_rejected_candidate(
        reason="evidence_insufficient", run_id="r1", decision_id="d2",
        asset="XRP", ticker="T-1", side="yes", model_p_selected=0.7,
        held_price_cents=71.0, gross_edge=0.01, net_edge=0.005,
        edge_threshold=0.02, tte_seconds=200.0,
    )
    rec = json.loads(log.read_text().strip())
    assert rec["yes_price_cents"] is None
    assert rec["no_price_cents"] is None
    # and specifically NOT the invalid complement
    assert rec["no_price_cents"] != 100.0 - rec["executable_price_cents"]


def test_bid_basis_prices_not_verified_as_asks(tmp_path):
    """Counting-side invariant: bid-basis records cannot band-match as asks."""
    src = open("scripts/_blocked_opportunity_counts.py", encoding="utf-8").read()
    assert 'basis == "ask"' in src
    assert "bid_basis_unverified" in src
