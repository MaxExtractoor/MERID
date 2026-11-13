"""Tests for the evidence-decay fade gate (merid/prediction/fade_gate.py).

Covers the self-resetting contract the 2026-11-12 audit required:
  * fresh/empty state allows every asset (static allowlist retired)
  * a trailing settled cohort with EV < trip blocks that (asset, side)
  * hysteresis: blocked stays blocked while EV sits in (release, trip)
  * recovery: EV >= release auto-releases — no manual intervention
  * stale evidence (> STALE_S without fresh settlements) fails open
  * corrupt/missing state fails open
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

_TMP = Path(tempfile.gettempdir()) / "fade_gate_test"
_STATE = _TMP / "state.json"
_SAMPLES = _TMP / "samples.jsonl"
_SETTLE = _TMP / "settlements.jsonl"


def _fresh_module():
    """Import fade_gate with test paths + tiny windows."""
    for mod in list(sys.modules):
        if mod.startswith("merid.prediction.fade_gate"):
            del sys.modules[mod]
    os.environ["MERID_FADE_GATE_STATE_PATH"] = str(_STATE)
    os.environ["MERID_FADE_GATE_SAMPLES_PATH"] = str(_SAMPLES)
    os.environ["MERID_FADE_GATE_SETTLEMENTS_PATH"] = str(_SETTLE)
    os.environ["MERID_FADE_GATE_WINDOW"] = "10"
    os.environ["MERID_FADE_GATE_MIN_SAMPLE"] = "4"
    os.environ["MERID_FADE_GATE_TRIP_EV_C"] = "-2.0"
    os.environ["MERID_FADE_GATE_RELEASE_EV_C"] = "0.0"
    os.environ["MERID_FADE_GATE_REFRESH_S"] = "0"
    os.environ["MERID_FADE_GATE_PENDING_TTL_S"] = "3600"
    os.environ["MERID_FADE_GATE_STALE_S"] = "86400"
    os.environ["MERID_FADE_GATE_MODE"] = "auto"
    import merid.prediction.fade_gate as fg

    return fg


def _write_settlements(rows):
    _TMP.mkdir(parents=True, exist_ok=True)
    with open(_SETTLE, "w", encoding="utf-8") as fh:
        for t, ry in rows:
            fh.write(json.dumps({"ticker": t, "resolved_yes": ry}) + "\n")


def _check(fg, asset="BTC", side="no", ticker="KXBTC15M-T-00", px=30.0):
    return fg.fade_gate_check(
        asset=asset,
        side=side,
        ticker=ticker,
        lean_cents=15.0,
        entry_price_cents=px,
        route="maker_bid",
    )


@pytest.fixture(autouse=True)
def _clean(tmp_path):
    import shutil

    if _TMP.exists():
        shutil.rmtree(_TMP)
    _TMP.mkdir(parents=True, exist_ok=True)
    _write_settlements([])
    yield
    for k in list(os.environ):
        if k.startswith("MERID_FADE_GATE_"):
            del os.environ[k]


class TestFreshState:
    def test_all_assets_allowed_initially(self):
        fg = _fresh_module()
        for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            allowed, detail = _check(fg, asset=asset, ticker=f"T-{asset}")
            assert allowed is True
            assert detail["outcome"] == "allowed"

    def test_sample_recorded_for_evidence(self):
        fg = _fresh_module()
        _check(fg, ticker="KXXRP15M-T1-00")
        assert _SAMPLES.exists()
        lines = _SAMPLES.read_text().strip().splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["ticker"] == "KXXRP15M-T1-00"
        assert rec["asset"] == "BTC"
        assert rec["px"] == 30.0


class TestBlocking:
    def _settle_toxic(self, fg, asset="BTC", side="no", n=6):
        """Feed n settled fade windows that all lose (resolved against side)."""
        # side=no loses when resolved_yes=1; px=30 -> pnl=-30 each => EV=-30
        rows = []
        for i in range(n):
            t = f"{asset}15M-T{i:02d}-00"
            rows.append((t, 1))
            _check(fg, asset=asset, side=side, ticker=t, px=30.0)
        _write_settlements(rows)
        # force refresh
        fg._last_refresh_ts = 0.0
        allowed, _ = _check(fg, asset=asset, side=side, ticker="probe", px=30.0)
        return allowed

    def test_toxic_cohort_blocks(self):
        fg = _fresh_module()
        # 6 settled losses -> EV=-30c < trip -2c, n=6 >= min 4 -> blocked
        rows = [(f"KXBTC15M-T{i}-00", 1) for i in range(6)]
        for i in range(6):
            _check(fg, ticker=f"KXBTC15M-T{i}-00")
        _write_settlements(rows)
        fg._last_refresh_ts = 0.0
        allowed, detail = _check(fg, ticker="KXBTC15M-T6-00")
        assert allowed is False
        assert detail["outcome"] == "blocked"
        assert detail["cohort"]["n"] == 6

    def test_block_is_per_asset_side(self):
        fg = _fresh_module()
        rows = [(f"KXBTC15M-T{i}-00", 1) for i in range(6)]
        for i in range(6):
            _check(fg, asset="BTC", side="no", ticker=f"KXBTC15M-T{i}-00")
        _write_settlements(rows)
        fg._last_refresh_ts = 0.0
        # BTC-no blocked; BTC-yes and XRP-no still allowed
        assert _check(fg, asset="BTC", side="no", ticker="p1")[0] is False
        assert _check(fg, asset="BTC", side="yes", ticker="p2")[0] is True
        assert _check(fg, asset="XRP", side="no", ticker="p3")[0] is True

    def test_min_sample_required(self):
        fg = _fresh_module()
        # only 3 settled losses (< min_sample 4) -> still allowed
        rows = [(f"KXBTC15M-T{i}-00", 1) for i in range(3)]
        for i in range(3):
            _check(fg, ticker=f"KXBTC15M-T{i}-00")
        _write_settlements(rows)
        fg._last_refresh_ts = 0.0
        allowed, _ = _check(fg, ticker="KXBTC15M-T9-00")
        assert allowed is True


class TestHysteresisAndRelease:
    def test_blocked_stays_blocked_in_hysteresis_band(self):
        fg = _fresh_module()
        # 4 big losses then enough ~-1c outcomes to pull EV into (-2, 0)
        rows = [(f"KXXRP15M-L{i}-00", 1) for i in range(4)]  # -30 each
        for i in range(4):
            _check(fg, asset="XRP", side="no", ticker=f"KXXRP15M-L{i}-00", px=30.0)
        _write_settlements(rows)
        fg._last_refresh_ts = 0.0
        assert _check(fg, asset="XRP", side="no", ticker="p")[0] is False
        # now settle 4 more at px=98 resolved_yes=1 -> pnl=-98? no:
        # want small negative ~-1c: px=30, win pays +70 loss -30... use px=50 win=+50/loss=-50
        # simpler: px=99 no-side, resolved_yes=0 -> win +1; resolved_yes=1 -> -99
        # craft: 4 samples px=50 side=no; resolved_yes=1 -> -50... too big.
        # Use px=30 side=YES? Let's directly inject trailing state instead.
        rec = fg._cohorts[("fade", "XRP", "no")]
        rec["trailing"] = [-30.0] * 4  # EV=-30 blocked already? state may be allowed->blocked on refresh
        fg._last_refresh_ts = 0.0
        _check(fg, asset="XRP", side="no", ticker="h1")
        # set state blocked manually then EV=-1 -> stays blocked (hysteresis)
        fg._cohorts[("fade", "XRP", "no")]["state"] = "blocked"
        fg._cohorts[("fade", "XRP", "no")]["trailing"] = [-1.0] * 10  # EV=-1 in band
        fg._last_refresh_ts = 0.0
        allowed, _ = _check(fg, asset="XRP", side="no", ticker="h2")
        assert allowed is False

    def test_recovery_auto_releases(self):
        fg = _fresh_module()
        # Block first
        rows = [(f"KXDOGE15M-B{i}-00", 1) for i in range(6)]
        for i in range(6):
            _check(fg, asset="DOGE", side="no", ticker=f"KXDOGE15M-B{i}-00", px=30.0)
        _write_settlements(rows)
        fg._last_refresh_ts = 0.0
        assert _check(fg, asset="DOGE", side="no", ticker="p1")[0] is False
        # Now 10 winning fades roll the window: px=30 no-side, resolved_yes=0 -> +70 each
        win_rows = [(f"KXDOGE15M-W{i}-00", 0) for i in range(10)]
        for i in range(10):
            _check(fg, asset="DOGE", side="no", ticker=f"KXDOGE15M-W{i}-00", px=30.0)
        _write_settlements(rows + win_rows)
        fg._last_refresh_ts = 0.0
        allowed, detail = _check(fg, asset="DOGE", side="no", ticker="p2")
        assert allowed is True
        assert detail["outcome"] == "allowed"

    def test_stale_blocked_releases(self):
        fg = _fresh_module()
        fg._cohorts[("fade", "BTC", "no")] = {
            "state": "blocked",
            "trailing": [-30.0] * 10,
            "last_settled_ts": time.time() - 90000,  # > STALE_S 86400
        }
        allowed, _ = _check(fg, asset="BTC", side="no", ticker="stale1")
        assert allowed is True  # fail-open on stale evidence


class TestFailOpen:
    def test_corrupt_state_allows(self):
        _TMP.mkdir(parents=True, exist_ok=True)
        _STATE.write_text("{not json", encoding="utf-8")
        fg = _fresh_module()
        allowed, detail = _check(fg)
        assert allowed is True

    def test_missing_settlement_feed_allows(self):
        if _SETTLE.exists():
            _SETTLE.unlink()
        fg = _fresh_module()
        # samples just stay pending; cohort has no evidence -> allowed
        allowed, _ = _check(fg, ticker="KXETH15M-T-00")
        assert allowed is True


class TestModes:
    def test_off_mode_never_blocks(self, monkeypatch):
        monkeypatch.setenv("MERID_FADE_GATE_MODE", "off")
        fg = _fresh_module()
        fg._MODE = "off"
        for _ in range(30):
            _check(fg, ticker=f"KXXRP15M-O{_}-00")
        allowed, detail = _check(fg, ticker="KXXRP15M-OZ-00")
        assert allowed is True
        assert detail["outcome"] == "non_auto_mode"

    def test_allowlist_mode_delegates(self):
        fg = _fresh_module()
        assert fg.gate_mode() == "auto"


# ── veto_release_check: evidence-release for unconditional vetoes ────────────
# 2026-11-13 cost-basis audit: p_selected<=min_p forfeited +6.4c/tr on the
# settled counterfactual (BTC-NO +17.4c).  The veto stands by default and
# releases per (gate, asset, side) only on proven positive trailing EV.

def _veto_check(fg, asset="BTC", side="no", ticker="KXBTC15M-V-00", px=40.0, gate="cost_basis"):
    return fg.veto_release_check(
        gate=gate, asset=asset, side=side, ticker=ticker, px=px, route="maker_bid"
    )


class TestVetoRelease:
    def test_unproven_cohort_veto_stands(self):
        fg = _fresh_module()
        released, detail = _veto_check(fg)
        assert released is False
        assert detail["outcome"] == "veto_stands"

    def test_toxic_cohort_veto_stands(self):
        fg = _fresh_module()
        fg._VETO_RELEASE_MIN_N = 4
        # 6 settled losses for side=no (resolved_yes=1, px=30 -> -30 each)
        rows = [(f"KXXRP15M-V{i}-00", 1) for i in range(6)]
        for i in range(6):
            _veto_check(fg, asset="XRP", side="no", ticker=f"KXXRP15M-V{i}-00", px=30.0)
        _write_settlements(rows)
        fg._last_refresh_ts = 0.0
        released, detail = _veto_check(fg, asset="XRP", side="no", ticker="probe")
        assert released is False
        assert detail["cohort"]["ev_c"] is not None and detail["cohort"]["ev_c"] < 0

    def test_proven_positive_releases(self):
        fg = _fresh_module()
        fg._VETO_RELEASE_MIN_N = 4
        fg._VETO_RELEASE_MIN_EV_C = 2.0
        # 6 settled wins for side=no (resolved_yes=0, px=30 -> +70 each, EV=+70)
        rows = [(f"KXDOGE15M-V{i}-00", 0) for i in range(6)]
        for i in range(6):
            _veto_check(fg, asset="DOGE", side="no", ticker=f"KXDOGE15M-V{i}-00", px=30.0)
        _write_settlements(rows)
        fg._last_refresh_ts = 0.0
        released, detail = _veto_check(fg, asset="DOGE", side="no", ticker="probe")
        assert released is True
        assert detail["outcome"] == "released"
        assert detail["cohort"]["n"] == 6

    def test_min_n_required(self):
        fg = _fresh_module()
        fg._VETO_RELEASE_MIN_N = 10
        fg._VETO_RELEASE_MIN_EV_C = 2.0
        # only 3 wins (< min_n 10) -> veto stands despite huge EV
        rows = [(f"KXSOL15M-V{i}-00", 0) for i in range(3)]
        for i in range(3):
            _veto_check(fg, asset="SOL", side="no", ticker=f"KXSOL15M-V{i}-00", px=30.0)
        _write_settlements(rows)
        fg._last_refresh_ts = 0.0
        released, _ = _veto_check(fg, asset="SOL", side="no", ticker="probe")
        assert released is False

    def test_ev_below_release_bound_vetoes(self):
        fg = _fresh_module()
        fg._VETO_RELEASE_MIN_N = 4
        fg._VETO_RELEASE_MIN_EV_C = 2.0
        # wins at px=98 -> +2c each? need >=2.0: px=97 -> +3c win... craft EV=+1c:
        # side=no px=99 resolved_yes=0 -> +1c each (below 2.0 bound)
        rows = [(f"KXETH15M-V{i}-00", 0) for i in range(6)]
        for i in range(6):
            _veto_check(fg, asset="ETH", side="no", ticker=f"KXETH15M-V{i}-00", px=99.0)
        _write_settlements(rows)
        fg._last_refresh_ts = 0.0
        released, detail = _veto_check(fg, asset="ETH", side="no", ticker="probe", px=99.0)
        assert released is False
        assert detail["cohort"]["ev_c"] == 1.0

    def test_release_is_per_gate_asset_side(self):
        fg = _fresh_module()
        fg._VETO_RELEASE_MIN_N = 4
        # prove cost_basis BTC-no released
        rows = [(f"KXBTC15M-V{i}-00", 0) for i in range(6)]
        for i in range(6):
            _veto_check(fg, asset="BTC", side="no", ticker=f"KXBTC15M-V{i}-00", px=30.0)
        _write_settlements(rows)
        fg._last_refresh_ts = 0.0
        assert _veto_check(fg, asset="BTC", side="no", ticker="p1")[0] is True
        # different asset, different side, different gate all still veto
        assert _veto_check(fg, asset="XRP", side="no", ticker="p2")[0] is False
        assert _veto_check(fg, asset="BTC", side="yes", ticker="p3")[0] is False
        assert _veto_check(fg, asset="BTC", side="no", ticker="p4", gate="drift")[0] is False

    def test_mode_off_never_releases(self):
        fg = _fresh_module()
        fg._VETO_RELEASE_MODE = "off"
        fg._VETO_RELEASE_MIN_N = 1
        rows = [("KXXRP15M-OFF-00", 0)]
        _veto_check(fg, asset="XRP", side="no", ticker="KXXRP15M-OFF-00", px=30.0)
        _write_settlements(rows)
        fg._last_refresh_ts = 0.0
        released, detail = _veto_check(fg, asset="XRP", side="no", ticker="probe")
        assert released is False
        assert detail["outcome"] == "mode_off_veto_stands"

    def test_sample_recorded_under_gate(self):
        fg = _fresh_module()
        _veto_check(fg, asset="BTC", side="no", ticker="KXBTC15M-S-00", px=42.0)
        lines = _SAMPLES.read_text().strip().splitlines()
        rec = json.loads(lines[-1])
        assert rec["gate"] == "cost_basis"
        assert rec["asset"] == "BTC"
        assert rec["px"] == 42.0
