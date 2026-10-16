"""Regression tests for the profit_only_v1 breakeven floor rework.

The pure entry-price anchor converted every below-entry bid into a forced
ride-to-settlement — including HARD_STOP/LOSS_CAP capital-protection exits
and bids that beat the model's own hold value by a wide margin.  The floor
now composes as:

1. Exempt triggers (state-repair, terminal, hard-risk) never blocked.
2. Breakeven ratchet: once the peak bid exceeds entry + ARM, the floor rises
   to ``max(entry, peak - TRAIL)``.
3. EV salvage: a below-floor bid >= ``hold_value + margin`` is +EV vs holding
   and is allowed; missing hold data fails closed to the anchor.
"""

import pytest

from merid.event_venues.kalshi.stop_candidate import loss_sell_blocked


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.setenv("MERID_PROFIT_ONLY_EXITS", "1")
    monkeypatch.delenv("MERID_LOSS_SELL_EV_SALVAGE", raising=False)
    monkeypatch.delenv("MERID_LOSS_SELL_SALVAGE_MARGIN_CENTS", raising=False)
    monkeypatch.delenv("MERID_BREAKEVEN_RATCET_ARM_CENTS", raising=False)
    monkeypatch.delenv("MERID_BREAKEVEN_RATCET_TRAIL_CENTS", raising=False)


class TestHardRiskExemptions:
    """HARD_STOP/LOSS_CAP are capital protection — the floor must not convert
    them into ride-to-zero holds."""

    @pytest.mark.parametrize("trigger", ["HARD_STOP", "LOSS_CAP", "hard_stop", "loss_cap"])
    def test_hard_risk_triggers_not_floored(self, trigger):
        assert loss_sell_blocked(trigger, 30, 68) is False

    def test_discretionary_trigger_still_floored(self):
        assert loss_sell_blocked("EDGE_DECAY", 30, 68) is True
        assert loss_sell_blocked("TAKE_PROFIT", 30, 68) is True

    def test_existing_exemptions_unchanged(self):
        for tr in ("MANUAL", "RECONCILIATION", "MARKET_EXPIRED", "EMERGENCY",
                   "HARD_RISK", "STALE_DATA", "POSITION_MISMATCH"):
            assert loss_sell_blocked(tr, 30, 68) is False


class TestEvSalvage:
    """bid-vs-hold-EV replaces the pure entry anchor when hold data exists."""

    def test_bid_beating_hold_by_margin_allowed_below_entry(self):
        # entry 68, bid 30, calibrated hold 20: taking 30 is +10 vs holding.
        assert loss_sell_blocked(
            "EDGE_DECAY", 30, 68, hold_value_cents=20
        ) is False

    def test_bid_below_hold_plus_margin_still_blocked(self):
        # bid 24 < hold 20 + margin 5 -> keep holding.
        assert loss_sell_blocked(
            "EDGE_DECAY", 24, 68, hold_value_cents=20
        ) is True

    def test_margin_boundary_is_allowed(self):
        # bid exactly at hold + margin clears.
        assert loss_sell_blocked(
            "EDGE_DECAY", 25, 68, hold_value_cents=20
        ) is False

    def test_missing_hold_value_fails_closed_to_anchor(self):
        assert loss_sell_blocked("EDGE_DECAY", 30, 68, hold_value_cents=None) is True
        assert loss_sell_blocked("EDGE_DECAY", 30, 68) is True

    def test_salvage_flag_off_restores_anchor(self, monkeypatch):
        monkeypatch.setenv("MERID_LOSS_SELL_EV_SALVAGE", "0")
        assert loss_sell_blocked(
            "EDGE_DECAY", 30, 68, hold_value_cents=20
        ) is True

    def test_salvage_margin_env_override(self, monkeypatch):
        monkeypatch.setenv("MERID_LOSS_SELL_SALVAGE_MARGIN_CENTS", "15")
        assert loss_sell_blocked(
            "EDGE_DECAY", 30, 68, hold_value_cents=20
        ) is True
        assert loss_sell_blocked(
            "EDGE_DECAY", 36, 68, hold_value_cents=20
        ) is False

    def test_salvage_only_applies_below_floor(self):
        # bid >= entry is a profitable exit; floor never binds.
        assert loss_sell_blocked("EDGE_DECAY", 70, 68, hold_value_cents=90) is False


class TestBreakevenRatchet:
    """Floor rises to max(entry, peak - trail) once the position armed."""

    def test_unarmed_peak_keeps_entry_floor(self):
        # peak 70 < entry 68 + arm 8 -> not armed, floor stays entry.
        assert loss_sell_blocked(
            "TRAILING_STOP", 60, 68, peak_price_cents=70
        ) is True
        assert loss_sell_blocked(
            "TRAILING_STOP", 68, 68, peak_price_cents=70
        ) is False

    def test_armed_ratchet_raises_floor(self):
        # peak 90, trail 12 -> floor = max(68, 78) = 78.
        assert loss_sell_blocked(
            "TRAILING_STOP", 75, 68, peak_price_cents=90
        ) is True
        assert loss_sell_blocked(
            "TRAILING_STOP", 78, 68, peak_price_cents=90
        ) is False

    def test_ratchet_never_lowers_floor_below_entry(self):
        # peak just armed: floor = max(68, 76 - 12) = 68 -> entry.
        assert loss_sell_blocked(
            "TRAILING_STOP", 67, 68, peak_price_cents=76
        ) is True
        assert loss_sell_blocked(
            "TRAILING_STOP", 68, 68, peak_price_cents=76
        ) is False

    def test_ratchet_overridden_by_ev_salvage(self):
        # Armed floor 78, but hold collapsed to 40 and bid 65 >= 45:
        # taking the bid beats the ride even under the armed floor.
        assert loss_sell_blocked(
            "TRAILING_STOP", 65, 68, peak_price_cents=90, hold_value_cents=40
        ) is False
        # Bid below hold+margin under an armed floor still holds.
        assert loss_sell_blocked(
            "TRAILING_STOP", 44, 68, peak_price_cents=90, hold_value_cents=40
        ) is True

    def test_no_peak_unchanged(self):
        assert loss_sell_blocked("TRAILING_STOP", 67, 68) is True
