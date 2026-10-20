"""Regression tests for the shared entry-trap gate (2026-10-20 audit).

The gate generalizes the quota-lane book-drop veto to every emitted lane
and adds the sticky-calibration veto, flat/trap mid-regime veto, and the
same-direction basket cap.  All functions under test are pure; the basket
registry is process-local and reset per test.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.prediction import entry_trap_guard as etg
from merid.prediction import window_quota as wq


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Pin all guard knobs so repo .env values cannot leak in."""
    monkeypatch.setenv("MERID_ENTRY_TRAP_VETO_ENABLED", "1")
    monkeypatch.setenv("MERID_ENTRY_TRAP_LOOKBACK_S", "45")
    monkeypatch.setenv("MERID_ENTRY_TRAP_DROP_C", "5.0")
    monkeypatch.setenv("MERID_ENTRY_TRAP_STICKY_P_DROP_C", "3.0")
    monkeypatch.setenv("MERID_ENTRY_TRAP_STICKY_P_MAX_DP", "0.02")
    monkeypatch.setenv("MERID_ENTRY_TRAP_EXEMPT_LANES", "settlement_convergence")
    monkeypatch.setenv("MERID_ENTRY_FLAT_TRAP_ENABLED", "1")
    monkeypatch.setenv("MERID_BASKET_SAME_SIDE_MAX", "2")
    etg._reset_registry_for_tests()
    yield
    etg._reset_registry_for_tests()


def _hist(rows):
    return {"T": rows}


def _s(ts, yb, ya, nb, na, py=None, pn=None):
    return (ts, yb, ya, nb, na, py, pn)


class TestSampleAccessors:
    def test_seven_tuple_layout(self):
        s = _s(100.0, 49, 50, 49, 51, 0.60, 0.40)
        assert etg.side_ask(s, "yes") == 50.0
        assert etg.side_ask(s, "no") == 51.0
        assert etg.side_bid(s, "yes") == 49.0
        assert etg.side_bid(s, "no") == 49.0
        assert etg.side_p(s, "yes") == 0.60
        assert etg.side_p(s, "no") == 0.40
        assert etg.side_mid_cents(s, "yes") == 49.5

    def test_legacy_three_tuple_layout(self):
        s = (100.0, 50.0, 51.0)
        assert etg.side_ask(s, "yes") == 50.0
        assert etg.side_ask(s, "no") == 51.0
        assert etg.side_bid(s, "yes") is None
        assert etg.side_p(s, "yes") is None

    def test_record_sample_bounds_deque(self):
        hist = {}
        for i in range(300):
            etg.record_sample(hist, "K", float(i), 49, 50, 49, 51)
        assert len(hist["K"]) == 240


class TestFallingBookVeto:
    def test_vetoes_falling_own_side_ask(self):
        now = 1000.0
        rows = [
            _s(now - 40, 64, 66, 33, 35, 0.60, 0.40),
            _s(now - 20, 60, 62, 37, 39, 0.60, 0.40),
            _s(now - 5, 57, 59, 40, 42, 0.60, 0.40),
        ]
        reason = etg.entry_book_veto(
            _hist(rows)["T"], "yes", lane="window_quota", now=now
        )
        assert reason is not None
        assert reason.startswith("own_side_ask_falling")

    def test_no_veto_on_rising_ask(self):
        now = 1000.0
        rows = [
            _s(now - 40, 50, 52, 47, 49, 0.60, 0.40),
            _s(now - 20, 54, 56, 43, 45, 0.60, 0.40),
            _s(now - 5, 57, 59, 40, 42, 0.60, 0.40),
        ]
        assert (
            etg.entry_book_veto(_hist(rows)["T"], "yes", now=now) is None
        )

    def test_no_veto_on_stable_book(self):
        now = 1000.0
        rows = [
            _s(now - 40, 49, 51, 48, 50, 0.60, 0.40),
            _s(now - 20, 50, 52, 47, 49, 0.60, 0.40),
            _s(now - 5, 49, 51, 48, 50, 0.60, 0.40),
        ]
        assert (
            etg.entry_book_veto(_hist(rows)["T"], "yes", now=now) is None
        )

    def test_requires_three_samples(self):
        now = 1000.0
        rows = [
            _s(now - 20, 64, 66, 33, 35, 0.60, 0.40),
            _s(now - 5, 57, 59, 40, 42, 0.60, 0.40),
        ]
        assert (
            etg.entry_book_veto(_hist(rows)["T"], "yes", now=now) is None
        )

    def test_stale_samples_outside_lookback_ignored(self):
        now = 1000.0
        rows = [
            _s(now - 400, 64, 66, 33, 35, 0.60, 0.40),
            _s(now - 300, 60, 62, 37, 39, 0.60, 0.40),
            _s(now - 200, 57, 59, 40, 42, 0.60, 0.40),
        ]
        assert (
            etg.entry_book_veto(_hist(rows)["T"], "yes", now=now) is None
        )


class TestStickyModelVeto:
    def test_static_p_plus_falling_book_vetoes_below_drop_threshold(self):
        """3-5c ask drop + static p: under the drop veto but still phantom."""
        now = 1000.0
        rows = [
            _s(now - 40, 62, 64, 35, 37, 0.64, 0.36),
            _s(now - 20, 61, 62, 37, 39, 0.64, 0.36),
            _s(now - 5, 59, 61, 38, 40, 0.645, 0.355),
        ]
        # yes_ask fell 64 -> 61 (3c < 5c drop threshold); p moved 0.005.
        reason = etg.entry_book_veto(
            _hist(rows)["T"], "yes", lane="current_build_provisional",
            now=now,
        )
        assert reason is not None
        assert reason.startswith("stale_model_divergence")

    def test_moving_p_defeats_sticky_veto(self):
        """Model tracking the book (p fell with the ask) is real repricing."""
        now = 1000.0
        rows = [
            _s(now - 40, 62, 64, 35, 37, 0.64, 0.36),
            _s(now - 20, 61, 62, 37, 39, 0.60, 0.40),
            _s(now - 5, 59, 61, 38, 40, 0.57, 0.43),
        ]
        assert (
            etg.entry_book_veto(_hist(rows)["T"], "yes", now=now) is None
        )

    def test_exempt_lane_skips_sticky_veto(self):
        """settlement_convergence: banked-sample p is legitimately static."""
        now = 1000.0
        rows = [
            _s(now - 40, 96, 98, 1, 3, 0.995, 0.005),
            _s(now - 20, 95, 97, 2, 4, 0.995, 0.005),
            _s(now - 5, 95, 97, 2, 4, 0.995, 0.005),
        ]
        assert (
            etg.entry_book_veto(
                _hist(rows)["T"], "yes",
                lane="settlement_convergence", now=now,
            )
            is None
        )

    def test_exempt_lane_still_gets_drop_veto(self, monkeypatch):
        """Exemption covers only the sticky-p check, not a collapsing book."""
        now = 1000.0
        rows = [
            _s(now - 40, 96, 98, 1, 3, 0.995, 0.005),
            _s(now - 20, 93, 95, 4, 6, 0.995, 0.005),
            _s(now - 5, 90, 92, 7, 9, 0.995, 0.005),
        ]
        reason = etg.entry_book_veto(
            _hist(rows)["T"], "yes",
            lane="settlement_convergence", now=now,
        )
        assert reason is not None
        assert reason.startswith("own_side_ask_falling")


class TestFlatTrapVeto:
    def test_whipsaw_mid_vetoes(self):
        now = 1000.0
        rows = [
            _s(now - d, 49 + (i % 2) * 4, 51 + (i % 2) * 4,
               48 - (i % 2) * 4, 50 - (i % 2) * 4)
            for i, d in enumerate((35, 30, 25, 20, 15, 10, 5))
        ]
        reason = etg.entry_book_veto(
            _hist(rows)["T"], "yes", lane="core", now=now
        )
        assert reason == "mid_whipsaw_trap"

    def test_flat_book_vetoes_taker_only(self):
        now = 1000.0
        rows = [
            _s(now - d, 49, 51, 48, 50) for d in (35, 30, 25, 20, 15, 10, 5)
        ]
        assert (
            etg.entry_book_veto(
                _hist(rows)["T"], "yes", lane="core",
                crosses_spread=True, now=now,
            )
            == "flat_book_taker_cross"
        )
        # A resting maker bid in a flat book is the validated edge.
        assert (
            etg.entry_book_veto(
                _hist(rows)["T"], "yes", lane="maker_bid",
                crosses_spread=False, now=now,
            )
            is None
        )


class TestBasketSameSideCap:
    W = "26OCT200515"

    def _tick(self, series):
        return f"KX{series}15M-{self.W}-15"

    def test_allows_up_to_cap(self):
        etg.record_window_emission(self._tick("BTC"), "yes")
        assert etg.basket_same_side_veto(self._tick("ETH"), "yes") is None
        etg.record_window_emission(self._tick("ETH"), "yes")
        reason = etg.basket_same_side_veto(self._tick("SOL"), "yes")
        assert reason is not None
        assert reason.startswith("basket_same_side_cap")

    def test_opposite_side_not_capped(self):
        etg.record_window_emission(self._tick("BTC"), "yes")
        etg.record_window_emission(self._tick("ETH"), "yes")
        assert etg.basket_same_side_veto(self._tick("SOL"), "no") is None

    def test_other_window_isolated(self):
        etg.record_window_emission(self._tick("BTC"), "yes")
        etg.record_window_emission(self._tick("ETH"), "yes")
        nxt = "KXXRP15M-26OCT200530-30"
        assert etg.basket_same_side_veto(nxt, "yes") is None

    def test_cap_zero_disables(self, monkeypatch):
        monkeypatch.setenv("MERID_BASKET_SAME_SIDE_MAX", "0")
        etg.record_window_emission(self._tick("BTC"), "yes")
        etg.record_window_emission(self._tick("ETH"), "yes")
        etg.record_window_emission(self._tick("SOL"), "yes")
        assert etg.basket_same_side_veto(self._tick("DOGE"), "yes") is None

    def test_own_series_resubmission_not_capped(self):
        """A retry on the same series is not a *new* correlated bet."""
        etg.record_window_emission(self._tick("BTC"), "yes")
        etg.record_window_emission(self._tick("ETH"), "yes")
        assert etg.basket_same_side_veto(self._tick("BTC"), "yes") is None


class TestMasterSwitch:
    def test_disabled_gate_returns_none(self, monkeypatch):
        monkeypatch.setenv("MERID_ENTRY_TRAP_VETO_ENABLED", "0")
        now = 1000.0
        rows = [
            _s(now - 40, 64, 66, 33, 35, 0.60, 0.40),
            _s(now - 20, 60, 62, 37, 39, 0.60, 0.40),
            _s(now - 5, 57, 59, 40, 42, 0.60, 0.40),
        ]
        assert (
            etg.entry_book_veto(_hist(rows)["T"], "yes", now=now) is None
        )


class TestQuotaBookFellLayoutCompat:
    """window_quota.quota_side_book_fell must read both the legacy 3-tuple
    and the new 7-tuple history layouts."""

    def test_seven_tuple_falling_yes(self, monkeypatch):
        monkeypatch.setenv("MERID_WINDOW_QUOTA_BOOK_LOOKBACK_S", "45")
        monkeypatch.setenv("MERID_WINDOW_QUOTA_BOOK_DROP_VETO_C", "6")
        now = 1000.0
        hist = [
            _s(now - 40, 42, 43, 56, 58),
            _s(now - 20, 38, 39, 60, 62),
            _s(now - 5, 33, 34, 65, 67),
        ]
        assert wq.quota_side_book_fell(hist, "yes", 34.0, now=now)

    def test_seven_tuple_falling_no(self, monkeypatch):
        monkeypatch.setenv("MERID_WINDOW_QUOTA_BOOK_LOOKBACK_S", "45")
        monkeypatch.setenv("MERID_WINDOW_QUOTA_BOOK_DROP_VETO_C", "6")
        now = 1000.0
        hist = [
            _s(now - 40, 30, 32, 67, 69),
            _s(now - 20, 33, 35, 64, 66),
            _s(now - 5, 37, 39, 60, 62),
        ]
        assert wq.quota_side_book_fell(hist, "no", 62.0, now=now)

    def test_legacy_three_tuple_still_works(self, monkeypatch):
        monkeypatch.setenv("MERID_WINDOW_QUOTA_BOOK_LOOKBACK_S", "45")
        monkeypatch.setenv("MERID_WINDOW_QUOTA_BOOK_DROP_VETO_C", "6")
        now = 1000.0
        hist = [
            (now - 40, 43.0, 58.0),
            (now - 20, 39.0, 62.0),
            (now - 5, 34.0, 67.0),
        ]
        assert wq.quota_side_book_fell(hist, "yes", 34.0, now=now)

    def test_stable_book_no_veto(self, monkeypatch):
        monkeypatch.setenv("MERID_WINDOW_QUOTA_BOOK_LOOKBACK_S", "45")
        monkeypatch.setenv("MERID_WINDOW_QUOTA_BOOK_DROP_VETO_C", "6")
        now = 1000.0
        hist = [
            _s(now - 40, 49, 51, 48, 50),
            _s(now - 20, 50, 52, 47, 49),
            _s(now - 5, 49, 51, 48, 50),
        ]
        assert not wq.quota_side_book_fell(hist, "yes", 51.0, now=now)


class TestToxicityKillSwitchFailClosed:
    """2026-10-20: entry orders must fail closed when the entropy kill
    switch check itself errors — a broken check silently admitting entries
    was the gap behind toxic-mid fills landing before the cancel ran."""

    def _intent(self):
        class _I:
            ticker = "KXBTC15M-TEST-15"
            action = "buy"
            side = "yes"
        return _I()

    def test_check_failure_rejects_entry(self, monkeypatch):
        monkeypatch.delenv("MERID_TOXICITY_CHECK_FAIL_OPEN", raising=False)
        from merid.event_venues.kalshi import order_router as or_

        monkeypatch.setattr(or_, "_is_exit_order", lambda i: False)
        monkeypatch.setattr(
            or_,
            "get_entropy_kill_switch",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        assert or_._check_toxicity_kill_switch(self._intent()) == (
            "kill_switch_check_failed"
        )

    def test_fail_open_override_restores_legacy(self, monkeypatch):
        monkeypatch.setenv("MERID_TOXICITY_CHECK_FAIL_OPEN", "1")
        from merid.event_venues.kalshi import order_router as or_

        monkeypatch.setattr(or_, "_is_exit_order", lambda i: False)
        monkeypatch.setattr(
            or_,
            "get_entropy_kill_switch",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        assert or_._check_toxicity_kill_switch(self._intent()) is None

    def test_exit_order_still_bypasses(self, monkeypatch):
        monkeypatch.delenv("MERID_TOXICITY_CHECK_FAIL_OPEN", raising=False)
        from merid.event_venues.kalshi import order_router as or_

        monkeypatch.setattr(or_, "_is_exit_order", lambda i: True)

        def _boom():
            raise RuntimeError("must not be called for exits")

        monkeypatch.setattr(or_, "get_entropy_kill_switch", _boom)
        assert or_._check_toxicity_kill_switch(self._intent()) is None

    def test_active_switch_rejects(self, monkeypatch):
        monkeypatch.delenv("MERID_TOXICITY_CHECK_FAIL_OPEN", raising=False)
        from merid.event_venues.kalshi import order_router as or_

        monkeypatch.setattr(or_, "_is_exit_order", lambda i: False)

        class _KS:
            def is_trading_allowed(self, ticker):
                return False, "entropy_high"

        monkeypatch.setattr(or_, "get_entropy_kill_switch", lambda: _KS())
        reason = or_._check_toxicity_kill_switch(self._intent())
        assert reason is not None and reason.startswith("kill_switch_active")
