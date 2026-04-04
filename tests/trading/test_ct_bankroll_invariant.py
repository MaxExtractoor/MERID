"""Tests for CT bankroll invariant: record_trade_result + check_bankroll_invariant.

Covers:
  - record_trade_result accumulation (single, multi, mixed sign)
  - check_bankroll_invariant returns OK when delta ≤ epsilon
  - check_bankroll_invariant returns WARN when delta > epsilon
  - Session start balance is captured on first invariant call
  - status() exposes bankroll state correctly
  - Settlement-like scenario: buy YES at 50¢, market settles YES, delta ≈ 0
  - Mixed YES/NO fills on the same market
  - Partial fills (multiple fills for one market)
  - "Agent D" scenario: settled fill does not trip invariant on normal settlement
"""

from __future__ import annotations

import pytest

from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader
from unittest.mock import MagicMock, patch


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def ct() -> KalshiContinuousTrader:
    """Fresh CT instance with mocked catalog (no real I/O)."""
    mock_catalog = MagicMock()
    mock_catalog.get_markets_by_asset.return_value = []
    with patch(
        "merid.trading.kalshi_continuous_trader.get_market_catalog",
        return_value=mock_catalog,
    ):
        trader = KalshiContinuousTrader(dry_run=True, catalog=mock_catalog)
    return trader


# ── record_trade_result ───────────────────────────────────────────────────

class TestRecordTradeResult:
    def test_initial_pnl_is_zero(self, ct: KalshiContinuousTrader) -> None:
        assert ct._total_pnl_cents == 0

    def test_single_winning_trade(self, ct: KalshiContinuousTrader) -> None:
        ct.record_trade_result(500)
        assert ct._total_pnl_cents == 500

    def test_single_losing_trade(self, ct: KalshiContinuousTrader) -> None:
        ct.record_trade_result(-300)
        assert ct._total_pnl_cents == -300

    def test_accumulates_across_multiple_settlements(self, ct: KalshiContinuousTrader) -> None:
        ct.record_trade_result(200)
        ct.record_trade_result(-100)
        ct.record_trade_result(450)
        assert ct._total_pnl_cents == 550

    def test_zero_pnl_trade(self, ct: KalshiContinuousTrader) -> None:
        ct.record_trade_result(0)
        assert ct._total_pnl_cents == 0

    def test_large_loss_tracked_correctly(self, ct: KalshiContinuousTrader) -> None:
        ct.record_trade_result(-10_000)
        assert ct._total_pnl_cents == -10_000


# ── check_bankroll_invariant ──────────────────────────────────────────────

class TestBankrollInvariant:
    def test_first_call_captures_session_start_balance(self, ct: KalshiContinuousTrader) -> None:
        assert ct._session_start_balance_cents is None
        ct.check_bankroll_invariant(balance_cents=57_400, portfolio_cents=0)
        assert ct._session_start_balance_cents == 57_400
        assert ct._session_start_bankroll_cents == 57_400

    def test_second_call_does_not_overwrite_session_start(self, ct: KalshiContinuousTrader) -> None:
        ct.check_bankroll_invariant(balance_cents=57_400, portfolio_cents=0)
        ct.check_bankroll_invariant(balance_cents=58_000, portfolio_cents=0)
        assert ct._session_start_balance_cents == 57_400
        assert ct._session_start_bankroll_cents == 57_400

    def test_first_call_uses_mark_to_market_bankroll_baseline(self, ct: KalshiContinuousTrader) -> None:
        ct.check_bankroll_invariant(balance_cents=2_109, portfolio_cents=184, fee_cents=2)
        assert ct._session_start_balance_cents == 2_109
        assert ct._session_start_bankroll_cents == 2_291

    def test_ok_when_no_activity(self, ct: KalshiContinuousTrader) -> None:
        result = ct.check_bankroll_invariant(balance_cents=10_000, portfolio_cents=0)
        assert result["status"] == "ok"
        assert result["delta_cents"] == 0

    def test_ok_within_epsilon(self, ct: KalshiContinuousTrader) -> None:
        # Start balance 10000¢. No settlements. Portfolio has 300¢ open MtM.
        # actual_bankroll = 10000 + 300 = 10300
        # expected_bankroll = 10000 + 0 = 10000
        # delta = 300 → within default epsilon 500¢
        ct.check_bankroll_invariant(balance_cents=10_000, portfolio_cents=0)  # sets start
        result = ct.check_bankroll_invariant(balance_cents=10_000, portfolio_cents=300)
        assert result["status"] == "ok"
        assert result["delta_cents"] == 300

    def test_warn_when_delta_exceeds_epsilon(self, ct: KalshiContinuousTrader) -> None:
        # Start at 10000¢. Balance rose by 600¢ with no settlement recorded.
        ct.check_bankroll_invariant(balance_cents=10_000, portfolio_cents=0)
        result = ct.check_bankroll_invariant(balance_cents=10_600, portfolio_cents=0)
        assert result["status"] == "warn"
        assert result["delta_cents"] == 600
        assert "actual_bankroll_cents" in result
        assert "expected_bankroll_cents" in result

    def test_custom_epsilon(self, ct: KalshiContinuousTrader) -> None:
        ct.check_bankroll_invariant(balance_cents=10_000, portfolio_cents=0)
        # delta 400¢ — ok with epsilon=500, warn with epsilon=300
        result_ok = ct.check_bankroll_invariant(
            balance_cents=10_400, portfolio_cents=0, epsilon_cents=500
        )
        assert result_ok["status"] == "ok"

        result_warn = ct.check_bankroll_invariant(
            balance_cents=10_400, portfolio_cents=0, epsilon_cents=300
        )
        assert result_warn["status"] == "warn"

    def test_last_invariant_status_stored(self, ct: KalshiContinuousTrader) -> None:
        assert ct._last_invariant_status == {}
        ct.check_bankroll_invariant(balance_cents=5_000, portfolio_cents=0)
        assert ct._last_invariant_status["status"] == "ok"

    def test_fee_adjustment_uses_same_bankroll_definition_on_both_sides(self, ct: KalshiContinuousTrader) -> None:
        ct.check_bankroll_invariant(balance_cents=2_109, portfolio_cents=184, fee_cents=2)
        result = ct.check_bankroll_invariant(balance_cents=2_109, portfolio_cents=184, fee_cents=2)
        assert result["status"] == "ok"
        assert result["actual_bankroll_cents"] == 2_291
        assert result["expected_bankroll_cents"] == 2_291
        assert result["delta_cents"] == 0


# ── Scenario: simple YES buy → settle YES ────────────────────────────────

class TestSettlementScenario:
    def test_single_yes_buy_settles_yes(self, ct: KalshiContinuousTrader) -> None:
        """Buy 10 YES contracts at 50¢. Market settles YES (100¢ payout).
        PnL = 10 × (100 - 50) = 500¢.
        After settlement: balance rises by 1000¢ (10 × 100¢ payout),
        portfolio drops to 0.  Invariant delta should be ≈ 0.
        """
        start_balance = 57_400
        cost_cents = 10 * 50  # 500¢ spent
        payout_cents = 10 * 100  # 1000¢ received at settlement

        # Set session start
        ct.check_bankroll_invariant(balance_cents=start_balance, portfolio_cents=0)

        # Simulate open position: balance reduced by cost, portfolio shows MtM
        # (At 50¢ ask, MtM ≈ 500¢ for 10 YES contracts at mid price 50¢)
        ct.check_bankroll_invariant(
            balance_cents=start_balance - cost_cents,
            portfolio_cents=500,
        )

        # Settlement: record trade result (pnl = payout - cost = 1000 - 500 = 500¢)
        ct.record_trade_result(500)

        # After settlement Kalshi pays out 1000¢ into balance, portfolio → 0
        result = ct.check_bankroll_invariant(
            balance_cents=start_balance - cost_cents + payout_cents,
            portfolio_cents=0,
        )
        # actual_bankroll = (start - cost + payout) + 0 = 57900
        # expected_bankroll = start + 500 = 57900
        # delta = 0 → OK
        assert result["status"] == "ok"
        assert result["delta_cents"] == 0

    def test_single_yes_buy_settles_no(self, ct: KalshiContinuousTrader) -> None:
        """Buy 10 YES contracts at 50¢. Market settles NO (0¢ payout).
        PnL = 10 × (0 - 50) = -500¢.
        After settlement: balance unchanged (no payout), portfolio → 0.
        """
        start_balance = 57_400
        cost_cents = 500  # 10 × 50¢

        ct.check_bankroll_invariant(balance_cents=start_balance, portfolio_cents=0)
        ct.record_trade_result(-500)

        # Balance not increased (payout=0), portfolio cleared
        result = ct.check_bankroll_invariant(
            balance_cents=start_balance - cost_cents,
            portfolio_cents=0,
        )
        # actual_bankroll = (start_balance - cost) + 0 = 56900
        # expected_bankroll = start_balance + (-500) = 56900
        # delta = 0
        assert result["status"] == "ok"
        assert result["delta_cents"] == 0

    def test_multi_fill_same_market(self, ct: KalshiContinuousTrader) -> None:
        """Two partial fills on the same market, both YES buys.
        Fill 1: 5 contracts @ 48¢ → cost 240¢
        Fill 2: 5 contracts @ 52¢ → cost 260¢
        Total cost: 500¢, avg price 50¢.
        Settles YES → payout 1000¢, pnl = 500¢.
        """
        start_balance = 10_000
        ct.check_bankroll_invariant(balance_cents=start_balance, portfolio_cents=0)

        # Simulate accumulated pnl from both partial fills at settlement
        fill1_pnl = 5 * (100 - 48)  # 260¢
        fill2_pnl = 5 * (100 - 52)  # 240¢
        ct.record_trade_result(fill1_pnl + fill2_pnl)  # 500¢

        result = ct.check_bankroll_invariant(
            balance_cents=start_balance - 500 + 1000,  # -cost + payout
            portfolio_cents=0,
        )
        assert result["status"] == "ok"
        assert result["delta_cents"] == 0

    def test_mixed_yes_no_fills_same_market(self, ct: KalshiContinuousTrader) -> None:
        """YES buy and NO buy on the same market (hedged).
        YES buy: 10 @ 50¢ → cost 500¢
        NO buy:  10 @ 50¢ → cost 500¢
        Settles YES:
          YES pnl = 10 × (100-50) = +500¢
          NO pnl  = 10 × (0-50)   = -500¢
          Net pnl = 0¢
        """
        start_balance = 20_000
        ct.check_bankroll_invariant(balance_cents=start_balance, portfolio_cents=0)

        yes_pnl = 10 * (100 - 50)   # +500¢
        no_pnl = 10 * (0 - 50)      # -500¢  (win_cents for NO when settled YES = 0)
        ct.record_trade_result(yes_pnl + no_pnl)  # 0¢

        total_cost = 500 + 500  # 1000¢
        yes_payout = 1000  # 10 × 100¢
        no_payout = 0

        result = ct.check_bankroll_invariant(
            balance_cents=start_balance - total_cost + yes_payout + no_payout,
            portfolio_cents=0,
        )
        assert result["status"] == "ok"
        assert result["delta_cents"] == 0


# ── Agent D scenario: settled fill should not trip invariant ─────────────

class TestAgentDScenario:
    """Reproduces the 'Agent D settled fill triggers kill switch' case.

    The original bug: a market settles while CT's balance and portfolio are
    read at slightly different times (race window), creating a transient delta.
    The invariant should only WARN on real wiring mismatches, not on normal
    settlement-induced temporary divergence within epsilon.
    """

    def test_settlement_race_window_within_epsilon(self, ct: KalshiContinuousTrader) -> None:
        """During settlement, Kalshi may update balance before removing portfolio.
        This creates a transient state where both balance and portfolio are elevated.
        The delta in that window should be within epsilon (500¢) for small positions.
        """
        start_balance = 10_000

        # Pre-settlement state: open position worth 300¢ MtM
        ct.check_bankroll_invariant(balance_cents=start_balance, portfolio_cents=0)
        ct.record_trade_result(300)  # settlement fires

        # Race window: Kalshi updated balance (payout arrived) but portfolio
        # entry not yet removed — both balance_cents and portfolio_cents are non-zero
        # actual_bankroll = 10300 + 300 = 10600
        # expected_bankroll = 10000 + 300 = 10300
        # delta = 300 — within epsilon 500¢
        race_result = ct.check_bankroll_invariant(
            balance_cents=start_balance + 300,  # payout arrived
            portfolio_cents=300,                # position not yet cleared
            epsilon_cents=500,
        )
        # Should be OK (not WARN) within epsilon — no false kill switch
        assert race_result["status"] == "ok"

    def test_large_real_mismatch_triggers_warn_not_ok(self, ct: KalshiContinuousTrader) -> None:
        """A genuine wiring failure (e.g. missed settlement) should WARN."""
        start_balance = 10_000
        ct.check_bankroll_invariant(balance_cents=start_balance, portfolio_cents=0)
        # Balance rose by 1000¢ but record_trade_result was never called
        result = ct.check_bankroll_invariant(
            balance_cents=start_balance + 1_000,
            portfolio_cents=0,
        )
        assert result["status"] == "warn"
        assert abs(result["delta_cents"]) > 500


# ── status() exposes bankroll ─────────────────────────────────────────────

class TestStatusExposure:
    def test_status_includes_bankroll_section(self, ct: KalshiContinuousTrader) -> None:
        s = ct.status()
        assert "bankroll" in s

    def test_bankroll_initial_state(self, ct: KalshiContinuousTrader) -> None:
        b = ct.status()["bankroll"]
        assert b["total_pnl_cents"] == 0
        assert b["total_pnl_usd"] == 0.0
        assert b["session_start_balance_cents"] is None
        assert b["session_start_bankroll_cents"] is None
        assert b["last_invariant"] == {}

    def test_bankroll_after_settlement(self, ct: KalshiContinuousTrader) -> None:
        ct.record_trade_result(1_234)
        ct.check_bankroll_invariant(balance_cents=50_000, portfolio_cents=0)
        b = ct.status()["bankroll"]
        assert b["total_pnl_cents"] == 1_234
        assert b["total_pnl_usd"] == pytest.approx(12.34, abs=0.001)
        assert b["session_start_balance_cents"] == 50_000
        assert b["session_start_bankroll_cents"] == 50_000
        assert b["last_invariant"]["status"] in ("ok", "warn")
