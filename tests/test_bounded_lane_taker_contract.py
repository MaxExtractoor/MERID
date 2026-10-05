"""Bounded-lane taker-posture contract tests (2026-10-03).

Regression coverage for the audit findings in
AUDIT_2026_10_03_EXECUTION_THROUGHPUT.md:

  * a bounded-lane intent emitted with taker posture
    (MERID_BOUNDED_TAKER_CROSS) must be stamped with the taker execution
    contract — stamping maker-only self-rejected ~21 intents pre-wire on
    2026-10-03 (PRE_WIRE_POST_ONLY_UNAVAILABLE),
  * a maker-posture bounded intent keeps the immutable post-only contract,
  * a side-level catastrophe parks only the offending ``{asset}:{side}``
    lane (6h TTL) instead of the whole side indefinitely,
  * strip concentration allows bounded concurrent same-side entries under
    the EV ladder,
  * the provisional NO mid-band (50-89c) cell relief lowers the cell
    threshold without touching YES or the low tails.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.event_venues.kalshi.order_router import (
    ExecutionPolicy,
    OrderIntent,
    _intent_requires_post_only,
    resolve_bounded_lane_execution_policy,
)
from merid.prediction import directional_regime as dr
from merid.prediction import current_build_provisional as cbp


# ---------------------------------------------------------------------------
# 1. Posture-aware ExecutionPolicy resolution
# ---------------------------------------------------------------------------

def _intent(lane: str, post_only: bool, policy=None):
    return OrderIntent(
        ticker="KXBTC15M-TESTBTC",
        price_cents=70,
        count=1.0,
        side="no",
        action="buy",
        post_only=post_only,
        aggressiveness=0.0 if post_only else 1.0,
        decision_lane=lane,
        entry_or_exit="entry",
        execution_policy=policy,
    )


@pytest.mark.parametrize("lane", ["threshold_cell", "current_build_provisional"])
def test_taker_posture_gets_taker_contract(lane):
    """The 2026-10-03 bug: taker-evaluated bounded intents were stamped
    required_post_only=True and died pre-wire.  The contract must mirror
    the emitted posture."""
    pol = resolve_bounded_lane_execution_policy(lane, post_only=False)

    assert pol is not None
    assert pol.required_post_only is False
    assert pol.required_liquidity_role == "taker"
    assert pol.allow_taker_fallback is False


@pytest.mark.parametrize("lane", ["threshold_cell", "current_build_provisional"])
def test_maker_posture_keeps_post_only_contract(lane):
    pol = resolve_bounded_lane_execution_policy(lane, post_only=True)

    assert pol is not None
    assert pol.required_post_only is True
    assert pol.required_liquidity_role == "maker"
    assert pol.allow_taker_fallback is False


@pytest.mark.parametrize("lane", ["threshold_cell", "current_build_provisional"])
def test_taker_contract_survives_maker_taker_policy(lane):
    """End-to-end: a taker-stamped intent must NOT be flagged for pre-wire
    rejection and must keep its marketable posture through policy."""
    from merid.event_venues.kalshi.maker_taker_integration import (
        apply_maker_taker_policy,
    )

    intent = _intent(
        lane,
        post_only=False,
        policy=resolve_bounded_lane_execution_policy(lane, post_only=False),
    )
    apply_maker_taker_policy(intent)

    assert getattr(intent, "_execution_policy_violation", None) is None
    assert _intent_requires_post_only(intent) is False
    assert intent.post_only is False


def test_maker_contract_still_flags_marketable_posture():
    """The protection still works: an intent whose posture contradicts a
    maker-only contract is flagged pre-wire (never silently downgraded)."""
    from merid.event_venues.kalshi.maker_taker_integration import (
        apply_maker_taker_policy,
    )

    intent = _intent(
        "current_build_provisional",
        post_only=False,
        policy=resolve_bounded_lane_execution_policy(
            "current_build_provisional", post_only=True
        ),
    )
    apply_maker_taker_policy(intent)

    assert getattr(intent, "_execution_policy_violation", None) == (
        "PRE_WIRE_POST_ONLY_UNAVAILABLE"
    )
    assert intent.post_only is True


def test_formula_lane_unstamped():
    assert resolve_bounded_lane_execution_policy("formula", False) is None
    assert resolve_bounded_lane_execution_policy(None, False) is None


# ---------------------------------------------------------------------------
# 2. Asset-scoped catastrophe suspension
# ---------------------------------------------------------------------------

@pytest.fixture
def throttle_path(tmp_path, monkeypatch):
    p = tmp_path / "throttle.json"
    monkeypatch.setenv("MERID_DIRECTIONAL_THROTTLE_PATH", str(p))
    monkeypatch.delenv("MERID_SIDE_CATASTROPHE_SCOPE", raising=False)
    monkeypatch.delenv("MERID_SIDE_CATASTROPHE_TTL_S", raising=False)
    dr._throttle_cache = (0.0, {})
    yield str(p)
    dr._throttle_cache = (0.0, {})


def test_catastrophe_scoped_to_asset_side(throttle_path):
    """A SOL-YES breach parks sol:yes only — every other asset's YES lane
    and the whole-NO side stay open (the 19h all-YES outage regression)."""
    dr.record_side_catastrophe("yes", "cbp_sol_yes_30_40:markout=-7.5c",
                               ts=1_000_000.0, asset="sol")

    assert dr.side_throttle_block("yes", now=1_000_001.0, asset="sol") is not None
    assert dr.side_throttle_block("yes", now=1_000_001.0, asset="btc") is None
    assert dr.side_throttle_block("yes", now=1_000_001.0, asset="eth") is None
    assert dr.side_throttle_block("yes", now=1_000_001.0) is None
    assert dr.side_throttle_block("no", now=1_000_001.0, asset="sol") is None
    assert dr.side_lane_state("yes", now=1_000_001.0, asset="sol") == "SUSPENDED"
    assert dr.side_lane_state("yes", now=1_000_001.0, asset="btc") == "OPEN"


def test_scoped_catastrophe_auto_releases(throttle_path, monkeypatch):
    """Asset-scoped stops carry a bounded TTL — they cool down, not lock."""
    monkeypatch.setenv("MERID_SIDE_CATASTROPHE_TTL_S", "3600")
    dr.record_side_catastrophe("no", "cbp_btc_no_60_70:fill_ev=-2c",
                               ts=1_000_000.0, asset="btc")
    assert dr.side_throttle_block("no", now=1_000_001.0, asset="btc") is not None
    assert dr.side_throttle_block("no", now=1_003_601.0, asset="btc") is None


def test_side_scope_keeps_manual_review(throttle_path, monkeypatch):
    """Unattributed or explicitly side-scoped breaches stay until-release —
    an unknown structural break must not auto-heal."""
    monkeypatch.setenv("MERID_SIDE_CATASTROPHE_SCOPE", "side")
    dr.record_side_catastrophe("yes", "unknown_breach", ts=1_000_000.0,
                               asset="sol")
    blk = dr.side_throttle_block("yes", now=1_000_001.0)
    assert blk and "manual_review" in blk
    # And no-asset callers also get the whole-side manual review.
    dr.release_side("yes", ts=1_000_002.0)
    dr.record_side_catastrophe("no", "cbp_x_no:breach", ts=1_000_003.0)
    blk = dr.side_throttle_block("no", now=1_000_004.0)
    assert blk and "manual_review" in blk


def test_release_side_clears_scoped_suspensions(throttle_path):
    dr.record_side_catastrophe("yes", "cbp_sol_yes:breach",
                               ts=1_000_000.0, asset="sol")
    dr.release_side("yes", ts=1_000_100.0)
    assert dr.side_throttle_block("yes", now=1_000_101.0, asset="sol") is None


# ---------------------------------------------------------------------------
# 3. Strip concentration — bounded concurrent same-side entries
# ---------------------------------------------------------------------------

def test_strip_default_serializes(throttle_path, monkeypatch):
    """Default (1): one open same-side entry blocks the next — legacy."""
    monkeypatch.delenv("MERID_STRIP_CONC_MAX_OPEN_SAME_SIDE", raising=False)
    now = 1_700_000_000.0
    dr.record_strip_entry("no", 5.0, ts=now, decision_id="a")
    assert dr.strip_concentration_block("no", 9.0, ts=now + 60) == (
        "strip_same_side_open:no"
    )


def test_strip_max_open_allows_second_concurrent(throttle_path, monkeypatch):
    """2026-10-05 relax: max_open=2 — while a same-side slot remains, any
    positive-EV entry may stack (no EV ladder); the cap binds at 2 open.
    The ladder only gates re-entry after every prior has closed."""
    monkeypatch.setenv("MERID_STRIP_CONC_MAX_OPEN_SAME_SIDE", "2")
    monkeypatch.setenv("MERID_STRIP_CONC_EV_MARGIN_CENTS", "3.0")
    now = 1_699_999_800.0  # mid-strip: +120s stays inside the same 900s strip
    dr.record_strip_entry("no", 5.0, ts=now, decision_id="a")
    # Open slot remains: a weaker 7c entry stacks beside the 5c open prior.
    assert dr.strip_concentration_block("no", 7.0, ts=now + 60) is None

    dr.record_strip_entry("no", 9.0, ts=now + 60, decision_id="b")
    # Two open now -> third blocked regardless of EV.
    assert dr.strip_concentration_block("no", 20.0, ts=now + 120) == (
        "strip_same_side_open:no"
    )


# ---------------------------------------------------------------------------
# 4. Provisional NO mid-band relief
# ---------------------------------------------------------------------------

def _cell(cell_id: str):
    cell = cbp.provisional_cell_for_id(cell_id)
    assert cell is not None, cell_id
    return cell


def test_no_mid_band_relief_narrows_no_cells_only(monkeypatch):
    monkeypatch.setenv("MERID_CBP_MID_BAND_RELIEF_NO_CENTS", "1.0")
    monkeypatch.delenv("MERID_PROVISIONAL_MIN_EV_FLOOR_C", raising=False)
    monkeypatch.delenv("MERID_PROVISIONAL_MIN_EV_C_BTC_NO", raising=False)

    no_mid = _cell("cbp_btc_no_50_60_t120_300")
    no_low = _cell("cbp_btc_no_30_40_t120_300")
    yes_mid = _cell("cbp_btc_yes_50_60_t120_300")

    # BTC NO default min-EV is 2.0c; relief brings the 50-60c cell to 1.0c.
    assert cbp.cell_min_ev_cents(no_mid) == pytest.approx(1.0)
    # <50c NO bands are untouched.
    assert cbp.cell_min_ev_cents(no_low) == pytest.approx(2.0)
    # YES is never relieved.
    assert cbp.cell_min_ev_cents(yes_mid) == pytest.approx(2.5)


def test_no_mid_band_relief_off_by_default(monkeypatch):
    monkeypatch.delenv("MERID_CBP_MID_BAND_RELIEF_NO_CENTS", raising=False)
    monkeypatch.delenv("MERID_PROVISIONAL_MIN_EV_FLOOR_C", raising=False)
    monkeypatch.delenv("MERID_PROVISIONAL_MIN_EV_C_BTC_NO", raising=False)
    no_mid = _cell("cbp_btc_no_50_60_t120_300")
    assert cbp.cell_min_ev_cents(no_mid) == pytest.approx(2.0)
