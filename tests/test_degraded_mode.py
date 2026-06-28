"""
Table-driven tests for the 15m loop state machine (HALT / WAITING / IDLE / ACTIVE).

Exercises the cadence-aware execution gating in merid/loop_15m.py via the pure
compute_loop_state() decision function, ensuring:
- infra failure                       -> HALT (the only true "system broken" state)
- markets absent but expected         -> WAITING (transient venue/posting gap, NOT a fault)
- markets absent and not expected     -> IDLE (maintenance / off hours, NOT a fault)
- markets present                     -> ACTIVE; execution_mode from per-asset readiness
- "0 ready assets"                    -> ACTIVE-HALT ONLY when markets present (else WAITING/IDLE)
- execution_ready (the trading gate)  -> True only when ACTIVE and >=1 asset ready
"""

import pytest

from merid.loop_15m import (
    compute_loop_state,
    markets_expected_now,
    is_within_kalshi_maintenance,
)


def decide(
    infra_ready: bool = True,
    markets_expected: bool = True,
    markets_present: bool = True,
    ready_assets_count: int = 5,
    min_ready_for_normal: int = 2,
):
    """Declarative wrapper around the production decision function."""
    return compute_loop_state(
        infra_ready=infra_ready,
        markets_expected=markets_expected,
        markets_present=markets_present,
        ready_assets_count=ready_assets_count,
        min_ready_for_normal=min_ready_for_normal,
    )


class TestLoopStateSelection:
    """loop_state is chosen from infra health + market presence/expectation."""

    @pytest.mark.parametrize(
        "infra_ready,markets_expected,markets_present,expected_state",
        [
            # Infra broken -> HALT regardless of markets
            (False, True, True, "HALT"),
            (False, True, False, "HALT"),
            (False, False, False, "HALT"),
            # Infra OK + strips present -> ACTIVE (present beats "not expected")
            (True, True, True, "ACTIVE"),
            (True, False, True, "ACTIVE"),
            # Infra OK, no strips, but expected -> WAITING (transient posting gap)
            (True, True, False, "WAITING"),
            # Infra OK, no strips, not expected -> IDLE (maintenance / off hours)
            (True, False, False, "IDLE"),
        ],
    )
    def test_loop_state_selection(self, infra_ready, markets_expected, markets_present, expected_state):
        # ready_assets_count must NOT influence loop_state selection
        loop_state, _, _ = decide(
            infra_ready=infra_ready,
            markets_expected=markets_expected,
            markets_present=markets_present,
            ready_assets_count=0,
        )
        assert loop_state == expected_state


class TestExecutionModeWithinActive:
    """Within ACTIVE, execution_mode is driven purely by ready_assets_count."""

    @pytest.mark.parametrize(
        "ready_count,expected_mode,expected_ready",
        [
            (5, "NORMAL", True),
            (3, "NORMAL", True),
            (2, "NORMAL", True),          # threshold: >=2 -> NORMAL
            (1, "DEGRADED", True),        # exactly 1 ready -> still trade it
            (0, "ACTIVE-HALT", False),    # strips present but nothing tradable -> red flag
        ],
    )
    def test_active_modes(self, ready_count, expected_mode, expected_ready):
        loop_state, mode, ready = decide(markets_present=True, ready_assets_count=ready_count)
        assert loop_state == "ACTIVE"
        assert mode == expected_mode
        assert ready == expected_ready

    def test_degraded_still_trades(self):
        """DEGRADED (1 ready asset) is NOT a kill-switch: execution_ready stays True."""
        _, mode, ready = decide(markets_present=True, ready_assets_count=1)
        assert mode == "DEGRADED"
        assert ready is True

    def test_custom_normal_threshold(self):
        """min_ready_for_normal is parameterizable (e.g. require 3 for NORMAL)."""
        _, mode, _ = decide(markets_present=True, ready_assets_count=2, min_ready_for_normal=3)
        assert mode == "DEGRADED"
        _, mode, _ = decide(markets_present=True, ready_assets_count=3, min_ready_for_normal=3)
        assert mode == "NORMAL"


class TestZeroReadyIsNotAlwaysHalt:
    """Core fix: 0 ready assets is only a fault when markets are PRESENT."""

    def test_zero_ready_no_markets_is_waiting(self):
        loop_state, mode, ready = decide(
            markets_present=False, markets_expected=True, ready_assets_count=0
        )
        assert loop_state == "WAITING"
        assert mode == "NONE"
        assert ready is False  # no trading, but NOT a fault

    def test_zero_ready_off_hours_is_idle(self):
        loop_state, mode, ready = decide(
            markets_present=False, markets_expected=False, ready_assets_count=0
        )
        assert loop_state == "IDLE"
        assert mode == "NONE"
        assert ready is False

    def test_zero_ready_with_markets_is_active_halt(self):
        loop_state, mode, ready = decide(markets_present=True, ready_assets_count=0)
        assert loop_state == "ACTIVE"
        assert mode == "ACTIVE-HALT"   # red flag: strips exist but nothing tradable
        assert ready is False

    def test_infra_down_is_halt_even_with_markets(self):
        loop_state, mode, ready = decide(
            infra_ready=False, markets_present=True, ready_assets_count=5
        )
        assert loop_state == "HALT"
        assert mode == "NONE"
        assert ready is False


class TestExecutionModeOnlyMeaningfulWhenActive:
    """Outside ACTIVE, execution_mode is NONE regardless of ready_assets_count."""

    @pytest.mark.parametrize(
        "infra_ready,markets_expected,markets_present",
        [
            (False, True, True),    # HALT
            (True, True, False),    # WAITING
            (True, False, False),   # IDLE
        ],
    )
    def test_mode_is_none_outside_active(self, infra_ready, markets_expected, markets_present):
        _, mode, ready = decide(
            infra_ready=infra_ready,
            markets_expected=markets_expected,
            markets_present=markets_present,
            ready_assets_count=5,  # even with all assets "ready"
        )
        assert mode == "NONE"
        assert ready is False


class TestMarketsExpectedCadence:
    """markets_expected_now() encodes the venue schedule (maintenance window)."""

    def test_markets_expected_is_inverse_of_maintenance(self):
        # Whatever the current wall-clock, expected == not in maintenance.
        assert markets_expected_now() == (not is_within_kalshi_maintenance())


class TestPerMarketEligibility:
    """Per-market depth eligibility is independent of the global loop_state."""

    def test_per_market_depth_check(self):
        # Each market has its own depth check:
        # depth_ok(market) = (min_depth_yes >= 25 AND min_depth_no >= 25)
        markets = {
            "KXBTC15M-26JUN071700-00": {"min_depth_yes": 30, "min_depth_no": 30},   # OK
            "KXETH15M-26JUN071700-00": {"min_depth_yes": 30, "min_depth_no": 30},   # OK
            "KXSOL15M-26JUN071700-00": {"min_depth_yes": 30, "min_depth_no": 30},   # OK
            "KXXRP15M-26JUN071700-00": {"min_depth_yes": 10, "min_depth_no": 10},   # Not OK
            "KXDOGE15M-26JUN071700-00": {"min_depth_yes": 10, "min_depth_no": 10},  # Not OK
        }
        eligible_markets = [
            ticker
            for ticker, depth in markets.items()
            if depth["min_depth_yes"] >= 25 and depth["min_depth_no"] >= 25
        ]
        assert len(eligible_markets) == 3
        assert "KXBTC15M-26JUN071700-00" in eligible_markets
        assert "KXXRP15M-26JUN071700-00" not in eligible_markets
        assert "KXDOGE15M-26JUN071700-00" not in eligible_markets


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
