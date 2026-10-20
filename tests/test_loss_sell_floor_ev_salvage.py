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
    """2026-10-20: HARD_STOP/LOSS_CAP are capital protection ONLY while
    MERID_LOSS_EXITS_ENABLED=1; the operator directive disables
    price-depth loss exits by default (stopped dips recover ~70%)."""

    @pytest.mark.parametrize("trigger", ["HARD_STOP", "LOSS_CAP", "hard_stop", "loss_cap"])
    def test_hard_risk_triggers_not_floored(self, trigger, monkeypatch):
        monkeypatch.setenv("MERID_LOSS_EXITS_ENABLED", "1")
        assert loss_sell_blocked(trigger, 30, 68) is False

    @pytest.mark.parametrize("trigger", ["HARD_STOP", "LOSS_CAP", "hard_stop", "loss_cap"])
    def test_hard_risk_triggers_floored_when_disabled(self, trigger):
        assert loss_sell_blocked(trigger, 30, 68) is True

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


class TestNoEdgeProbeFloor:
    """2026-10-19: a non-positive *stamped admission edge* marks a
    bounded-lane/telemetry entry — there is no model thesis to hold for,
    so the floor drops to ``hold - MERID_LOSS_SELL_PROBE_MARGIN_CENTS``
    instead of forcing a binary ride.  XRP-0130: a -5c quota entry
    peaked at 68c then watched ~60 trail sells suppressed by the
    ratcheted 56c floor down to settlement at zero."""

    def test_no_edge_entry_salvages_at_hold(self):
        # entry 51, peak 68 (ratchet floor would be 56), hold 42, bid 42:
        # probe floor = min(51, 40) = 40 -> sell at fair is allowed.
        assert loss_sell_blocked(
            "TRAILING_STOP", 42, 51, hold_value_cents=42,
            peak_price_cents=68, entry_edge=-0.05,
        ) is False

    def test_no_edge_entry_blocked_below_probe_floor(self):
        # bid 38 < hold 42 - margin 2 -> below fair; still suppressed.
        assert loss_sell_blocked(
            "TRAILING_STOP", 38, 51, hold_value_cents=42,
            peak_price_cents=68, entry_edge=-0.05,
        ) is True

    def test_no_edge_entry_capped_at_entry_when_model_bullish(self):
        # hold 80 >> bid 40: floor = min(51, 78) = 51 -> the model still
        # claims hold > entry, so the ride stays protected.
        assert loss_sell_blocked(
            "TRAILING_STOP", 40, 51, hold_value_cents=80,
            peak_price_cents=68, entry_edge=-0.05,
        ) is True

    def test_positive_edge_entry_ratchet_unchanged(self):
        # +5c stamped edge -> ratchet floor 56 stands, bid 42 blocked.
        assert loss_sell_blocked(
            "TRAILING_STOP", 42, 51, hold_value_cents=42,
            peak_price_cents=68, entry_edge=0.05,
        ) is True

    def test_missing_edge_entry_ratchet_unchanged(self):
        assert loss_sell_blocked(
            "TRAILING_STOP", 42, 51, hold_value_cents=42,
            peak_price_cents=68, entry_edge=None,
        ) is True

    def test_no_edge_missing_hold_fails_closed(self):
        # No hold value -> keep the entry/ratchet anchor (fail closed).
        assert loss_sell_blocked(
            "TRAILING_STOP", 42, 51, hold_value_cents=None,
            peak_price_cents=68, entry_edge=-0.05,
        ) is True

    def test_no_edge_exempt_trigger_still_exempt(self, monkeypatch):
        # Exemption survives only under the re-enable flag (2026-10-20).
        monkeypatch.setenv("MERID_LOSS_EXITS_ENABLED", "1")
        assert loss_sell_blocked(
            "HARD_STOP", 30, 51, hold_value_cents=42,
            peak_price_cents=68, entry_edge=-0.05,
        ) is False

    def test_no_edge_hard_stop_uses_probe_floor_when_disabled(self):
        # flag off + no-edge entry: floor = hold 42 - probe 2 = 40;
        # bid 30 < 40 -> suppressed; bid 42 would pass (+EV vs hold).
        assert loss_sell_blocked(
            "HARD_STOP", 30, 51, hold_value_cents=42,
            peak_price_cents=68, entry_edge=-0.05,
        ) is True
        assert loss_sell_blocked(
            "LOSS_CAP", 42, 51, hold_value_cents=42,
            peak_price_cents=68, entry_edge=-0.05,
        ) is False

    def test_no_edge_floor_never_below_one(self):
        # hold collapsed to 1c -> floor = max(1, min(51, -1)) = 1.
        assert loss_sell_blocked(
            "TRAILING_STOP", 2, 51, hold_value_cents=1,
            peak_price_cents=68, entry_edge=-0.05,
        ) is False
        assert loss_sell_blocked(
            "TRAILING_STOP", 1, 51, hold_value_cents=1,
            peak_price_cents=68, entry_edge=-0.05,
        ) is False

    def test_probe_margin_env_override(self, monkeypatch):
        monkeypatch.setenv("MERID_LOSS_SELL_PROBE_MARGIN_CENTS", "10")
        # floor = hold 42 - 10 = 32 -> bid 38 still sells (>= 32).
        assert loss_sell_blocked(
            "TRAILING_STOP", 38, 51, hold_value_cents=42,
            peak_price_cents=68, entry_edge=-0.05,
        ) is False
        assert loss_sell_blocked(
            "TRAILING_STOP", 30, 51, hold_value_cents=42,
            peak_price_cents=68, entry_edge=-0.05,
        ) is True
