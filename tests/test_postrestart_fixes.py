"""Regression tests for the 2026-10-24 post-restart fix batch.

Covers:
  * pinned_fav lane honoring per-asset moneyness caps (the lane's maker
    band 76-91 deliberately overlaps audited-toxic pockets; the caps are
    the load-bearing protection).
  * Exit post-only-cross marketable conversion pricing (sell exits fill
    at bid >= limit; buy-to-close at ask <= limit).
  * Tail-loss drop-trigger persistence (single noisy bid print must not
    crystallize a loss on a contract that later settles favorably).
  * Watchdog decision logic (miss threshold, cooldown, hourly budget,
    observe-only mode).
"""

import os
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import merid.prediction.directional_regime as dr
from merid.event_venues.kalshi.order_router import _exit_conversion_price_cents
from merid.position_management.position_monitor import _tail_drop_min_obs
import watchdog_15m as wd


@pytest.fixture
def _pf_env(monkeypatch):
    """Pinned-fav lane armed in maker mode with a clean daily budget."""
    monkeypatch.setenv("MERID_PINNED_FAV_ENABLED", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MODE", "1")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_LO", "76")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_HI", "91")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MIN_TTE_S", "90")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MAX_TTE_S", "840")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MIN_EV_CENTS", "-12.0")
    monkeypatch.setenv("MERID_PINNED_FAV_MAKER_MIN_P", "0.85")
    monkeypatch.setenv("MERID_PINNED_FAV_DAILY_MAX", "480")
    monkeypatch.delenv("MERID_PRICE_CAP_EXCEPT_BTC_NO", raising=False)
    monkeypatch.setattr(dr, "pinned_fav_cap_remaining", lambda *a, **k: 5)
    return monkeypatch


class TestPinnedFavMoneynessCaps:
    def test_btc_no_above_cap_vetoes(self, _pf_env):
        """KXBTC15M-...2145 replay: NO@86 maker vs audited BTC cap 79."""
        _pf_env.setenv("MERID_MONEYNESS_MAX_ENTRY_PRICE_CENTS_NO_BTC", "79")
        _pf_env.setenv("MERID_MONEYNESS_MAX_ENTRY_PRICE_CENTS_NO", "50")
        assert (
            dr.pinned_fav_block(
                side_price_cents=86.0,
                net_ev_cents=-4.1,
                tte_seconds=300,
                p_selected=0.90,
                held_side="no",
                asset="BTC",
            )
            == "pinned_fav_moneyness_cap"
        )

    def test_sol_no_above_cap_vetoes(self, _pf_env):
        """KXSOL15M-...1945 replay: NO@83 maker vs audited SOL cap 75."""
        _pf_env.setenv("MERID_MONEYNESS_MAX_ENTRY_PRICE_CENTS_NO_SOL", "75")
        assert (
            dr.pinned_fav_block(
                side_price_cents=83.0,
                net_ev_cents=-1.8,
                tte_seconds=300,
                p_selected=0.90,
                held_side="no",
                asset="SOL",
            )
            == "pinned_fav_moneyness_cap"
        )

    def test_eth_no_under_cap_passes(self, _pf_env):
        """ETH cap is 89 — an 86c NO favorite stays admissible."""
        _pf_env.setenv("MERID_MONEYNESS_MAX_ENTRY_PRICE_CENTS_NO_ETH", "89")
        assert (
            dr.pinned_fav_block(
                side_price_cents=86.0,
                net_ev_cents=-1.8,
                tte_seconds=300,
                p_selected=0.90,
                held_side="no",
                asset="ETH",
            )
            is None
        )

    def test_no_per_asset_cap_leaves_lane_domain(self, _pf_env):
        """Global side caps don't bind in-lane — only audited per-asset ones.

        The lane's domain (76-98c favorites) sits above the generic side
        baselines by design; only per-asset caps carry settled-fill
        evidence.  An unmapped asset proceeds.
        """
        _pf_env.setenv("MERID_MONEYNESS_MAX_ENTRY_PRICE_CENTS_NO", "50")
        assert (
            dr.pinned_fav_block(
                side_price_cents=80.0,
                net_ev_cents=-2.0,
                tte_seconds=300,
                p_selected=0.90,
                held_side="no",
                asset="UNMAPPED",
            )
            is None
        )

    def test_xrp_no_hard_block_binds_in_lane(self, _pf_env):
        """XRP-NO cap=1 is a hard block — the lane must not admit it."""
        _pf_env.setenv("MERID_MONEYNESS_MAX_ENTRY_PRICE_CENTS_NO_XRP", "1")
        assert (
            dr.pinned_fav_block(
                side_price_cents=80.0,
                net_ev_cents=-2.0,
                tte_seconds=300,
                p_selected=0.90,
                held_side="no",
                asset="XRP",
            )
            == "pinned_fav_moneyness_cap"
        )

    def test_honor_flag_off_restores_probe(self, _pf_env):
        _pf_env.setenv("MERID_PINNED_FAV_HONOR_MONEYNESS_CAPS", "0")
        _pf_env.setenv("MERID_MONEYNESS_MAX_ENTRY_PRICE_CENTS_NO_BTC", "79")
        assert (
            dr.pinned_fav_block(
                side_price_cents=86.0,
                net_ev_cents=-4.1,
                tte_seconds=300,
                p_selected=0.90,
                held_side="no",
                asset="BTC",
            )
            is None
        )

    def test_btc_exception_requires_positive_ev(self, _pf_env):
        _pf_env.setenv("MERID_PRICE_CAP_EXCEPT_BTC_NO", "1")
        _pf_env.setenv("MERID_MONEYNESS_MAX_ENTRY_PRICE_CENTS_NO_BTC", "79")
        # Negative-EV probe still vetoed even under the exception flag.
        assert (
            dr.pinned_fav_block(
                side_price_cents=86.0,
                net_ev_cents=-4.1,
                tte_seconds=300,
                p_selected=0.90,
                held_side="no",
                asset="BTC",
            )
            == "pinned_fav_moneyness_cap"
        )
        # A genuinely +EV claim inside the pocket passes the cap check.
        assert (
            dr.pinned_fav_block(
                side_price_cents=86.0,
                net_ev_cents=3.0,
                tte_seconds=300,
                p_selected=0.90,
                held_side="no",
                asset="BTC",
            )
            is None
        )

    def test_missing_side_is_inert(self, _pf_env):
        """No held_side -> cap check skipped (legacy call-site behavior)."""
        _pf_env.setenv("MERID_MONEYNESS_MAX_ENTRY_PRICE_CENTS_NO_BTC", "79")
        assert (
            dr.pinned_fav_block(
                side_price_cents=86.0,
                net_ev_cents=-4.1,
                tte_seconds=300,
                p_selected=0.90,
            )
            is None
        )


class TestExitConversionPricing:
    """Sell exits convert at bid >= limit; buy-to-close at ask <= limit."""

    def test_sell_at_bid_when_crossed(self):
        # Limit 70c sell, book crossed to bid 75 — conversion at 75 is
        # strictly better than the intended price.
        assert _exit_conversion_price_cents("sell", 70, 75, 80) == 75

    def test_sell_at_limit_boundary(self):
        assert _exit_conversion_price_cents("sell", 70, 70, 80) == 70

    def test_sell_declines_when_book_recrossed(self):
        # Moment passed: refetched bid fell below our limit — don't chase.
        assert _exit_conversion_price_cents("sell", 70, 65, 80) is None

    def test_sell_declines_empty_bid(self):
        assert _exit_conversion_price_cents("sell", 70, 0, 80) is None

    def test_buy_to_close_at_ask(self):
        assert _exit_conversion_price_cents("buy", 60, 40, 55) == 55

    def test_buy_to_close_declines_above_limit(self):
        assert _exit_conversion_price_cents("buy", 60, 40, 65) is None

    def test_unknown_action_declines(self):
        assert _exit_conversion_price_cents("hold", 70, 75, 80) is None


class TestTailDropPersistence:
    def test_min_obs_default_two(self, monkeypatch):
        monkeypatch.delenv("MERID_TAIL_LOSS_DROP_MIN_OBS", raising=False)
        assert _tail_drop_min_obs() == 2

    def test_min_obs_env_override(self, monkeypatch):
        monkeypatch.setenv("MERID_TAIL_LOSS_DROP_MIN_OBS", "4")
        assert _tail_drop_min_obs() == 4
        monkeypatch.setenv("MERID_TAIL_LOSS_DROP_MIN_OBS", "garbage")
        assert _tail_drop_min_obs() == 2
        monkeypatch.setenv("MERID_TAIL_LOSS_DROP_MIN_OBS", "0")
        assert _tail_drop_min_obs() == 1

    def test_counter_lifecycle(self):
        """Breach counter increments while breached, resets on recovery."""
        pos = types.SimpleNamespace()
        # First breach observation — below threshold.
        obs = int(getattr(pos, "tail_drop_breach_obs", 0) or 0) + 1
        pos.tail_drop_breach_obs = obs
        assert obs < _tail_drop_min_obs()
        # Second consecutive — threshold reached, fire allowed.
        obs = int(getattr(pos, "tail_drop_breach_obs", 0) or 0) + 1
        pos.tail_drop_breach_obs = obs
        assert obs >= _tail_drop_min_obs()
        # Recovery resets.
        pos.tail_drop_breach_obs = 0
        assert pos.tail_drop_breach_obs == 0


class TestWatchdogDecide:
    def test_healthy_resets(self):
        action, times, misses = wd.decide([], 2, [100.0], None, 200.0)
        assert action == "ok" and misses == 0
        assert times == [100.0]  # within the hour — kept

    def test_healthy_prunes_old_restarts(self):
        action, times, _ = wd.decide([], 0, [100.0, 5000.0], None, 5000.0)
        assert action == "ok" and times == [5000.0]

    def test_below_threshold_waits(self):
        action, _, misses = wd.decide(["heartbeat_stale"], 0, [], None, 100.0)
        assert action == "wait" and misses == 1

    def test_restart_at_threshold(self):
        action, _, misses = wd.decide(["port_closed"], 2, [], None, 100.0)
        assert action == "restart" and misses == 3

    def test_cooldown_defers(self):
        action, _, _ = wd.decide(
            ["port_closed"], 2, [50.0], 50.0, 100.0, cooldown_s=60.0
        )
        assert action == "wait"  # 50s since last restart < 60s cooldown

    def test_budget_exhaustion(self):
        times = [100.0, 200.0, 300.0]
        action, _, _ = wd.decide(
            ["port_closed"], 2, times, 300.0, 400.0, max_restarts_per_hour=3
        )
        assert action == "budget_exhausted"

    def test_budget_prunes_after_hour(self):
        times = [100.0, 200.0, 3900.0]
        action, _, _ = wd.decide(
            ["port_closed"], 2, times, 3900.0, 4000.0, max_restarts_per_hour=3
        )
        # Two of three restarts are >1h old — budget available.
        assert action == "restart"

    def test_observe_only(self):
        action, _, _ = wd.decide(
            ["port_closed"], 5, [], None, 100.0, auto_restart=False
        )
        assert action == "observe"

    def test_signals_failed_logic(self):
        status = {
            "port_listening": True,
            "heartbeat_age_s": 10.0,
            "log_age_s": 5.0,
        }
        assert wd.signals_failed(status, 90.0) == []
        status["heartbeat_age_s"] = 200.0
        assert wd.signals_failed(status, 90.0) == ["heartbeat_stale"]
        status["port_listening"] = False
        assert wd.signals_failed(status, 90.0) == [
            "port_closed",
            "heartbeat_stale",
        ]
        # Heartbeat unreadable -> log mtime is the fallback signal.
        status = {
            "port_listening": True,
            "heartbeat_age_s": None,
            "log_age_s": 500.0,
        }
        assert wd.signals_failed(status, 90.0) == ["log_silent"]
