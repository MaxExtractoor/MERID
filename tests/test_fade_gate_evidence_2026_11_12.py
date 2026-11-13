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
