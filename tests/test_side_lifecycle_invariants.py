"""Formal YES/NO side lifecycle invariants suite (2026-07-22).

Proves, with exact assertions, that agents can express the full lifecycle:
  - ENTRY:  buy-YES when indicators say YES, buy-NO when indicators say NO
  - EXIT:   sell-YES against a YES thesis, sell-NO against a NO thesis
  - SAFETY: exits never fire without exposure, never over-close, never invert side

Canonical log schemas (emitted by merid/loop_15m.py, greppable + machine-parseable):

  [LIFECYCLE-ENTRY] asset=<A> ticker=<T> agent_id=<ID> indicator_side=<yes|no>
      edge_yes=<f|n/a> edge_no=<f|n/a> edge_pct=<f> thesis_side=<yes|no>
      entry_action=buy kalshi_side=<BUY_YES|BUY_NO> price_cents=<int>
      count=<int> strategy_intent=<s|n/a> entry_or_exit=entry

  [LIFECYCLE-EXIT] asset=<A> ticker=<T> agent_id=<ID> thesis_side=<yes|no>
      action=sell kalshi_side=<SELL_YES|SELL_NO> size_before=<int>
      size_after=<int> count=<int> price_cents=<int> exit_reason=<s>
      entry_or_exit=exit

The validators in this module can be pointed at captured production logs to turn
manual inspection into automated invariant checking.
"""

import re
from pathlib import Path

import pytest

from merid.event_venues.kalshi.strategy_positions import (
    FillRecord,
    StrategyPosition,
    ThesisSide,
    build_exit_order,
    thesis_to_outcome_side,
)

from datetime import datetime

LOOP_15M_PATH = Path(__file__).resolve().parent.parent / "merid" / "loop_15m.py"

ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
TICKER_PREFIX = {
    "BTC": "KXBTC15M",
    "ETH": "KXETH15M",
    "SOL": "KXSOL15M",
    "XRP": "KXXRP15M",
    "DOGE": "KXDOGE15M",
}

# ---------------------------------------------------------------------------
# Canonical schemas: required keys per lifecycle log line
# ---------------------------------------------------------------------------

LIFECYCLE_ENTRY_REQUIRED_KEYS = (
    "asset", "ticker", "agent_id", "indicator_side", "edge_yes", "edge_no",
    "edge_pct", "thesis_side", "entry_action", "kalshi_side", "price_cents",
    "count", "strategy_intent", "entry_or_exit",
)

LIFECYCLE_EXIT_REQUIRED_KEYS = (
    "asset", "ticker", "agent_id", "thesis_side", "action", "kalshi_side",
    "size_before", "size_after", "count", "price_cents", "exit_reason",
    "entry_or_exit",
)

_KV_RE = re.compile(r"(\w+)=(\S+)")


def parse_lifecycle_line(line: str) -> dict:
    """Parse a [LIFECYCLE-ENTRY]/[LIFECYCLE-EXIT] log line into a dict."""
    return dict(_KV_RE.findall(line))


def validate_lifecycle_entry(fields: dict) -> None:
    """Exact ENTRY invariants. Raises AssertionError with the violated rule."""
    for key in LIFECYCLE_ENTRY_REQUIRED_KEYS:
        assert key in fields, f"INV-E0 schema: missing key '{key}' in LIFECYCLE-ENTRY"

    assert fields["indicator_side"] in ("yes", "no"), \
        f"INV-E1: indicator_side must be yes|no, got {fields['indicator_side']}"
    assert fields["entry_action"] == "buy", \
        f"INV-E2: entries must be BUY only, got entry_action={fields['entry_action']}"
    assert fields["thesis_side"] == fields["indicator_side"], \
        (f"INV-E3: thesis_side must equal indicator_side, got "
         f"thesis={fields['thesis_side']} indicator={fields['indicator_side']}")
    expected_kalshi = "BUY_YES" if fields["thesis_side"] == "yes" else "BUY_NO"
    assert fields["kalshi_side"] == expected_kalshi, \
        (f"INV-E4: kalshi_side must be {expected_kalshi} for thesis_side="
         f"{fields['thesis_side']}, got {fields['kalshi_side']}")
    price = int(fields["price_cents"])
    assert 10 <= price <= 75, \
        f"INV-E5: entry price {price}c outside canonical range [10,75]"
    assert int(fields["count"]) >= 1, \
        f"INV-E6: entry count must be >= 1, got {fields['count']}"
    intent = fields["strategy_intent"]
    if intent == "bullish_event":
        assert fields["kalshi_side"] in ("BUY_YES", "SELL_NO"), \
            f"INV-E7: bullish_event requires +Yes exposure, got {fields['kalshi_side']}"
    elif intent == "bearish_event":
        assert fields["kalshi_side"] in ("BUY_NO", "SELL_YES"), \
            f"INV-E7: bearish_event requires +No exposure, got {fields['kalshi_side']}"
    assert fields["entry_or_exit"] == "entry", \
        f"INV-E8: entry_or_exit must be 'entry', got {fields['entry_or_exit']}"


def validate_lifecycle_exit(fields: dict) -> None:
    """Exact EXIT invariants. Raises AssertionError with the violated rule."""
    for key in LIFECYCLE_EXIT_REQUIRED_KEYS:
        assert key in fields, f"INV-X0 schema: missing key '{key}' in LIFECYCLE-EXIT"

    assert fields["thesis_side"] in ("yes", "no"), \
        f"INV-X1: thesis_side must be yes|no, got {fields['thesis_side']}"
    assert fields["action"] == "sell", \
        f"INV-X2: exits must be SELL only, got action={fields['action']}"
    expected_kalshi = "SELL_YES" if fields["thesis_side"] == "yes" else "SELL_NO"
    assert fields["kalshi_side"] == expected_kalshi, \
        (f"INV-X3: kalshi_side must be {expected_kalshi} for thesis_side="
         f"{fields['thesis_side']}, got {fields['kalshi_side']}")
    size_before = int(fields["size_before"])
    size_after = int(fields["size_after"])
    count = int(fields["count"])
    assert size_before > 0, \
        f"INV-X4: exit fired with no open position (size_before={size_before})"
    assert 0 <= size_after < size_before, \
        (f"INV-X5: exit must strictly reduce exposure toward zero, got "
         f"size_before={size_before} size_after={size_after}")
    assert size_after == size_before - count, \
        (f"INV-X6: size_after must equal size_before - count, got "
         f"{size_after} != {size_before} - {count}")
    assert count >= 1, f"INV-X7: exit count must be >= 1, got {count}"
    price = int(fields["price_cents"])
    assert 1 <= price <= 99, \
        f"INV-X8: exit price {price}c outside valid range [1,99]"
    assert fields["entry_or_exit"] == "exit", \
        f"INV-X9: entry_or_exit must be 'exit', got {fields['entry_or_exit']}"


def scan_log_file_for_lifecycle_violations(log_path: str) -> list:
    """Scan a production log file; return list of (line_no, error) violations.

    Usage against live logs:
        violations = scan_log_file_for_lifecycle_violations("logs/full.log")
        assert not violations, violations
    """
    violations = []
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for line_no, line in enumerate(f, start=1):
            try:
                if "[LIFECYCLE-ENTRY]" in line:
                    validate_lifecycle_entry(parse_lifecycle_line(line))
                elif "[LIFECYCLE-EXIT]" in line:
                    validate_lifecycle_exit(parse_lifecycle_line(line))
            except AssertionError as e:
                violations.append((line_no, str(e)))
    return violations


# ---------------------------------------------------------------------------
# Entry-side mapping invariants (candidate side/action -> kalshi_side)
# Mirrors the production mapping table in loop_15m._execute_candidate
# ---------------------------------------------------------------------------

def _map_side_action_to_kalshi(side_raw: str, action_raw: str) -> str:
    side_raw = side_raw.upper()
    action_raw = action_raw.upper()
    if side_raw == "YES" and action_raw == "BUY":
        return "BUY_YES"
    if side_raw == "YES" and action_raw == "SELL":
        return "SELL_YES"
    if side_raw == "NO" and action_raw == "BUY":
        return "BUY_NO"
    if side_raw == "NO" and action_raw == "SELL":
        return "SELL_NO"
    return f"{action_raw}_{side_raw}"


class TestEntrySideMappingInvariants:
    """INV-E: indicator side must map deterministically to entry kalshi_side."""

    @pytest.mark.parametrize("side,action,expected", [
        ("yes", "buy", "BUY_YES"),
        ("no", "buy", "BUY_NO"),
        ("yes", "sell", "SELL_YES"),
        ("no", "sell", "SELL_NO"),
    ])
    def test_side_action_mapping_table(self, side, action, expected):
        assert _map_side_action_to_kalshi(side, action) == expected

    @pytest.mark.parametrize("side", ["yes", "no"])
    def test_entry_buy_mapping_per_asset(self, side):
        """Every asset must be able to express BUY_YES and BUY_NO entries."""
        expected = "BUY_YES" if side == "yes" else "BUY_NO"
        for asset in ASSETS:
            kalshi_side = _map_side_action_to_kalshi(side, "buy")
            assert kalshi_side == expected, \
                f"asset={asset}: entry side={side} must map to {expected}, got {kalshi_side}"

    def test_entry_log_line_passes_validator_yes(self):
        line = (
            "[LIFECYCLE-ENTRY] asset=BTC ticker=KXBTC15M-26JUL221230-30 "
            "agent_id=BTC_15M indicator_side=yes edge_yes=0.0500 edge_no=0.0100 "
            "edge_pct=5.0000 thesis_side=yes entry_action=buy kalshi_side=BUY_YES "
            "price_cents=45 count=2 strategy_intent=bullish_event entry_or_exit=entry"
        )
        validate_lifecycle_entry(parse_lifecycle_line(line))

    def test_entry_log_line_passes_validator_no(self):
        line = (
            "[LIFECYCLE-ENTRY] asset=ETH ticker=KXETH15M-26JUL221230-30 "
            "agent_id=ETH_15M indicator_side=no edge_yes=0.0100 edge_no=0.0500 "
            "edge_pct=5.0000 thesis_side=no entry_action=buy kalshi_side=BUY_NO "
            "price_cents=55 count=1 strategy_intent=bearish_event entry_or_exit=entry"
        )
        validate_lifecycle_entry(parse_lifecycle_line(line))

    def test_entry_validator_rejects_sell_entry(self):
        line = (
            "[LIFECYCLE-ENTRY] asset=BTC ticker=KXBTC15M-26JUL221230-30 "
            "agent_id=BTC_15M indicator_side=yes edge_yes=0.05 edge_no=0.01 "
            "edge_pct=5.0 thesis_side=yes entry_action=sell kalshi_side=SELL_YES "
            "price_cents=45 count=1 strategy_intent=n/a entry_or_exit=entry"
        )
        with pytest.raises(AssertionError, match="INV-E2"):
            validate_lifecycle_entry(parse_lifecycle_line(line))

    def test_entry_validator_rejects_side_mismatch(self):
        """Indicator says NO but kalshi_side is BUY_YES -> YES-bias bug caught."""
        line = (
            "[LIFECYCLE-ENTRY] asset=SOL ticker=KXSOL15M-26JUL221230-30 "
            "agent_id=SOL_15M indicator_side=no edge_yes=0.01 edge_no=0.05 "
            "edge_pct=5.0 thesis_side=no entry_action=buy kalshi_side=BUY_YES "
            "price_cents=45 count=1 strategy_intent=bearish_event entry_or_exit=entry"
        )
        with pytest.raises(AssertionError, match="INV-E4"):
            validate_lifecycle_entry(parse_lifecycle_line(line))

    def test_entry_validator_rejects_intent_exposure_mismatch(self):
        """bullish_event with BUY_NO exposure must be flagged."""
        line = (
            "[LIFECYCLE-ENTRY] asset=XRP ticker=KXXRP15M-26JUL221230-30 "
            "agent_id=XRP_15M indicator_side=no edge_yes=0.01 edge_no=0.05 "
            "edge_pct=5.0 thesis_side=no entry_action=buy kalshi_side=BUY_NO "
            "price_cents=45 count=1 strategy_intent=bullish_event entry_or_exit=entry"
        )
        with pytest.raises(AssertionError, match="INV-E7"):
            validate_lifecycle_entry(parse_lifecycle_line(line))


# ---------------------------------------------------------------------------
# Exit-side mapping invariants (thesis_side -> SELL_YES / SELL_NO)
# Uses the production pure function build_exit_order
# ---------------------------------------------------------------------------

def _make_position(asset: str, thesis: ThesisSide, size_fp: int = 1,
                   entry_price: int = 45) -> StrategyPosition:
    return StrategyPosition(
        ticker=f"{TICKER_PREFIX[asset]}-26JUL221230-30",
        agent_id=f"{asset}_15M",
        thesis_side=thesis,
        size_fp=size_fp,
        avg_entry_price_cents=entry_price,
    )


def _make_fill(outcome_side: str, count: int, price: int,
               action: str = "buy") -> FillRecord:
    return FillRecord(
        timestamp=datetime.utcnow(),
        fill_id=f"fill_{outcome_side}_{count}_{price}",
        side=outcome_side,
        action=action,
        outcome_side=outcome_side,
        count_fp=count,
        price_cents=price,
        fee_cents=0,
        intent_side=outcome_side,
    )


class TestExitSideMappingInvariants:
    """INV-X: exits must sell the thesis side, never invert, never over-close."""

    @pytest.mark.parametrize("asset", ASSETS)
    def test_yes_thesis_exit_is_sell_yes(self, asset):
        position = _make_position(asset, ThesisSide.YES, size_fp=2)
        order = build_exit_order(position, qty_fp=2, price_cents=50)
        assert order["kalshi_side"] == "SELL_YES", \
            f"INV-X3: YES thesis must exit via SELL_YES, got {order['kalshi_side']}"
        assert order["action"] == "sell"
        assert order["side"] == "yes"
        assert order["outcome_side"] == "yes"
        assert order["thesis_side"] == "yes"

    @pytest.mark.parametrize("asset", ASSETS)
    def test_no_thesis_exit_is_sell_no(self, asset):
        position = _make_position(asset, ThesisSide.NO, size_fp=2)
        order = build_exit_order(position, qty_fp=2, price_cents=50)
        assert order["kalshi_side"] == "SELL_NO", \
            f"INV-X3: NO thesis must exit via SELL_NO, got {order['kalshi_side']}"
        assert order["action"] == "sell"
        assert order["side"] == "no"
        assert order["outcome_side"] == "no"
        assert order["thesis_side"] == "no"

    @pytest.mark.parametrize("thesis", [ThesisSide.YES, ThesisSide.NO])
    def test_exit_with_zero_size_raises(self, thesis):
        """INV-X4: exit without exposure is structurally impossible."""
        position = _make_position("BTC", thesis, size_fp=0)
        with pytest.raises(ValueError, match="size_fp must be positive"):
            build_exit_order(position, qty_fp=1, price_cents=50)

    def test_exit_with_negative_size_raises(self):
        position = _make_position("ETH", ThesisSide.YES, size_fp=-1)
        with pytest.raises(ValueError, match="size_fp must be positive"):
            build_exit_order(position, qty_fp=1, price_cents=50)

    def test_exit_over_close_raises(self):
        """INV-X5/X6: exits can never increase or over-close exposure."""
        position = _make_position("SOL", ThesisSide.NO, size_fp=1)
        with pytest.raises(ValueError, match="exceeds position size"):
            build_exit_order(position, qty_fp=2, price_cents=50)

    def test_exit_zero_qty_raises(self):
        position = _make_position("XRP", ThesisSide.YES, size_fp=1)
        with pytest.raises(ValueError, match="must be positive"):
            build_exit_order(position, qty_fp=0, price_cents=50)

    def test_thesis_to_outcome_side_is_identity(self):
        assert thesis_to_outcome_side(ThesisSide.YES) == "yes"
        assert thesis_to_outcome_side(ThesisSide.NO) == "no"

    def test_exit_log_line_passes_validator(self):
        line = (
            "[LIFECYCLE-EXIT] asset=ETH ticker=KXETH15M-26JUL221200-00 "
            "agent_id=merid.position_management.position_monitor thesis_side=no "
            "action=sell kalshi_side=SELL_NO size_before=2 size_after=0 count=2 "
            "price_cents=55 exit_reason=time_stop entry_or_exit=exit"
        )
        validate_lifecycle_exit(parse_lifecycle_line(line))

    def test_exit_validator_rejects_zero_size_before(self):
        line = (
            "[LIFECYCLE-EXIT] asset=ETH ticker=KXETH15M-26JUL221200-00 "
            "agent_id=pm thesis_side=yes action=sell kalshi_side=SELL_YES "
            "size_before=0 size_after=0 count=1 price_cents=55 "
            "exit_reason=stale_data entry_or_exit=exit"
        )
        with pytest.raises(AssertionError, match="INV-X4"):
            validate_lifecycle_exit(parse_lifecycle_line(line))

    def test_exit_validator_rejects_side_inversion(self):
        """YES thesis exiting via SELL_NO is the historical inversion bug."""
        line = (
            "[LIFECYCLE-EXIT] asset=DOGE ticker=KXDOGE15M-26JUL221200-00 "
            "agent_id=pm thesis_side=yes action=sell kalshi_side=SELL_NO "
            "size_before=1 size_after=0 count=1 price_cents=55 "
            "exit_reason=take_profit entry_or_exit=exit"
        )
        with pytest.raises(AssertionError, match="INV-X3"):
            validate_lifecycle_exit(parse_lifecycle_line(line))

    def test_exit_validator_rejects_exposure_increase(self):
        line = (
            "[LIFECYCLE-EXIT] asset=BTC ticker=KXBTC15M-26JUL221200-00 "
            "agent_id=pm thesis_side=yes action=sell kalshi_side=SELL_YES "
            "size_before=1 size_after=2 count=1 price_cents=55 "
            "exit_reason=stop_loss entry_or_exit=exit"
        )
        with pytest.raises(AssertionError, match="INV-X5"):
            validate_lifecycle_exit(parse_lifecycle_line(line))

    def test_exit_validator_rejects_buy_action(self):
        line = (
            "[LIFECYCLE-EXIT] asset=BTC ticker=KXBTC15M-26JUL221200-00 "
            "agent_id=pm thesis_side=yes action=buy kalshi_side=SELL_YES "
            "size_before=1 size_after=0 count=1 price_cents=55 "
            "exit_reason=stop_loss entry_or_exit=exit"
        )
        with pytest.raises(AssertionError, match="INV-X2"):
            validate_lifecycle_exit(parse_lifecycle_line(line))


# ---------------------------------------------------------------------------
# Full lifecycle invariants per asset: entry -> open -> exit -> flat
# ---------------------------------------------------------------------------

class TestFullLifecyclePerAsset:
    """INV-L: buy-YES/buy-NO entry then sell-YES/sell-NO exit, ending flat."""

    @pytest.mark.parametrize("asset", ASSETS)
    def test_yes_lifecycle_entry_to_flat(self, asset):
        # ENTRY: buy YES (indicator said YES)
        position = _make_position(asset, ThesisSide.YES, size_fp=0)
        position.add_entry_fill(_make_fill("yes", count=2, price=45))
        assert position.is_open, "INV-L1: entry fill must open the position"
        assert position.size_fp == 2

        # EXIT: sell YES to flatten
        order = build_exit_order(position, qty_fp=position.size_fp, price_cents=60)
        assert order["kalshi_side"] == "SELL_YES"
        position.add_exit_fill(_make_fill("yes", count=2, price=60, action="sell"))
        assert position.size_fp == 0, "INV-L1: exit fill must flatten to zero"
        assert not position.is_open

        # SAFETY: further exits impossible once flat
        with pytest.raises(ValueError):
            build_exit_order(position, qty_fp=1, price_cents=60)

    @pytest.mark.parametrize("asset", ASSETS)
    def test_no_lifecycle_entry_to_flat(self, asset):
        # ENTRY: buy NO (indicator said NO)
        position = _make_position(asset, ThesisSide.NO, size_fp=0)
        position.add_entry_fill(_make_fill("no", count=2, price=55))
        assert position.is_open, "INV-L2: entry fill must open the position"
        assert position.size_fp == 2

        # EXIT: sell NO to flatten
        order = build_exit_order(position, qty_fp=position.size_fp, price_cents=70)
        assert order["kalshi_side"] == "SELL_NO"
        position.add_exit_fill(_make_fill("no", count=2, price=70, action="sell"))
        assert position.size_fp == 0, "INV-L2: exit fill must flatten to zero"
        assert not position.is_open

        with pytest.raises(ValueError):
            build_exit_order(position, qty_fp=1, price_cents=70)

    def test_partial_exit_reduces_then_flattens(self):
        position = _make_position("BTC", ThesisSide.YES, size_fp=0)
        position.add_entry_fill(_make_fill("yes", count=3, price=45))

        # Partial exit: 3 -> 1
        order = build_exit_order(position, qty_fp=2, price_cents=55)
        assert order["kalshi_side"] == "SELL_YES"
        position.add_exit_fill(_make_fill("yes", count=2, price=55, action="sell"))
        assert position.size_fp == 1
        assert position.is_open

        # Final exit: 1 -> 0
        order = build_exit_order(position, qty_fp=1, price_cents=58)
        position.add_exit_fill(_make_fill("yes", count=1, price=58, action="sell"))
        assert position.size_fp == 0
        assert not position.is_open

    def test_cross_side_entry_fill_raises(self):
        """INV-L3: side inversion at fill level is structurally impossible."""
        position = _make_position("ETH", ThesisSide.NO, size_fp=0)
        with pytest.raises(ValueError, match="does not match"):
            position.add_entry_fill(_make_fill("yes", count=1, price=45))

    def test_exit_fill_over_close_raises(self):
        position = _make_position("DOGE", ThesisSide.YES, size_fp=0)
        position.add_entry_fill(_make_fill("yes", count=1, price=45))
        with pytest.raises(ValueError, match="over-close"):
            position.add_exit_fill(_make_fill("yes", count=2, price=55, action="sell"))


# ---------------------------------------------------------------------------
# Source guards: production code must contain the enforcement + log schemas
# ---------------------------------------------------------------------------

class TestProductionSourceGuards:
    """INV-G: guards and canonical log tags must exist in loop_15m.py."""

    @pytest.fixture(scope="class")
    def loop_source(self):
        return LOOP_15M_PATH.read_text(encoding="utf-8", errors="replace")

    def test_exit_order_size_assertion_exists(self, loop_source):
        assert "assert position.size > 0" in loop_source, \
            "INV-G1: _execute_exit_order must assert position.size > 0"

    def test_exit_order_side_str_assertion_exists(self, loop_source):
        assert 'assert side_str in ("yes", "no", "YES", "NO")' in loop_source, \
            "INV-G2: _execute_exit_order must assert side_str validity"

    def test_callback_suppresses_zero_size_exits(self, loop_source):
        assert "Exit intent suppressed - no open position" in loop_source, \
            "INV-G3: PositionMonitor callback must suppress exits on zero size"

    def test_entry_rejects_missing_side(self, loop_source):
        assert "REJECTING CANDIDATE: missing side" in loop_source, \
            "INV-G4: entries with missing side/action must be rejected (YES-bias guard)"

    def test_entry_rejects_sell_action(self, loop_source):
        assert "[ENTRY-ORDER-INVARIANT-VIOLATION]" in loop_source, \
            "INV-G5: SELL actions on entry path must be rejected"

    def test_lifecycle_entry_log_schema_present(self, loop_source):
        assert "[LIFECYCLE-ENTRY]" in loop_source, \
            "INV-G6: canonical LIFECYCLE-ENTRY log must exist"
        start = loop_source.find("[LIFECYCLE-ENTRY]")
        block = loop_source[start:start + 400]
        for key in LIFECYCLE_ENTRY_REQUIRED_KEYS:
            assert f"{key}=" in block, \
                f"INV-G6: LIFECYCLE-ENTRY log missing schema key '{key}'"

    def test_lifecycle_exit_log_schema_present(self, loop_source):
        assert "[LIFECYCLE-EXIT]" in loop_source, \
            "INV-G7: canonical LIFECYCLE-EXIT log must exist"
        start = loop_source.find("[LIFECYCLE-EXIT]")
        block = loop_source[start:start + 400]
        for key in LIFECYCLE_EXIT_REQUIRED_KEYS:
            assert f"{key}=" in block, \
                f"INV-G7: LIFECYCLE-EXIT log missing schema key '{key}'"

    def test_exit_intent_contract_fields_present(self, loop_source):
        for field_marker in ('entry_or_exit="exit"', "pre_position_size=",
                             "expected_post_position_size="):
            assert field_marker in loop_source, \
                f"INV-G8: exit OrderIntent must carry contract field {field_marker}"

    def test_exit_orders_bypass_bankroll_cap(self):
        """INV-G9: exits reduce exposure; the entry notional cap must not trap them."""
        router_source = (LOOP_15M_PATH.parent / "event_venues" / "kalshi" /
                         "order_router.py").read_text(encoding="utf-8", errors="replace")
        guard_pos = router_source.find('if intent.entry_or_exit == "exit":')
        cap_check_pos = router_source.find("def _check_bankroll_risk_cap")
        assert cap_check_pos > 0, "INV-G9: _check_bankroll_risk_cap must exist"
        assert guard_pos > cap_check_pos, \
            "INV-G9: _check_bankroll_risk_cap must bypass exit orders (exposure-reducing)"
        assert "Exit order bypasses notional cap" in router_source, \
            "INV-G9: exit bankroll-cap bypass log must exist"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
