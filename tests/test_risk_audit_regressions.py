"""Regression tests for the 8 bugs identified in the prediction market risk audit.

LEGACY: This module tests PaperSession, which is not used by kalshi_crypto_15m_v2 profile.
The lean 15m stack uses live bankroll service (merid.event_venues.kalshi.bankroll_service_v2).

BUG-01: winning_trades double-incremented in record_settlement
BUG-02: get_portfolio_stats mixes realized+unrealized under total_pnl
BUG-03: fees excluded from balance identity invariant
BUG-04: category notional/contract counters never updated in record_fill/record_close
BUG-05: drawdown_pct returns 0 for cells starting with losses (HWM starts at 0)
BUG-06: two competing singleton factories race on paper engine init
BUG-07: stale price silently zeros unrealized PnL and reconciliation masks it
BUG-08: record_settlement must not double-count PnL; sell-closes use early_close PnL (Bug 6)
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.legacy

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _fresh_session(risk_limits=None, **kw):
    """Return a PaperSession with relaxed risk limits and no persistence."""
    from merid.prediction.paper_session import (
        PaperSession, SessionRiskLimits,
    )
    if risk_limits is None:
        risk_limits = SessionRiskLimits(
            max_daily_loss_cents=999_999.0,
            max_weekly_loss_cents=999_999.0,
            max_cluster_daily_loss_cents=999_999.0,
            drawdown_warning_pct=999.0,
            drawdown_downsize_pct=999.0,
            drawdown_halt_pct=999.0,
        )
    with patch("merid.prediction.paper_session._PERSIST_FILE") as pf:
        pf.exists.return_value = False
        sess = PaperSession(risk_limits=risk_limits, **kw)
    sess._save_state = lambda: None  # disable disk writes
    return sess


def _register_and_settle(sess, agent: str, market_id: str, side: str,
                          contracts: int, price_cents: float, outcome: int):
    """register_open_trade + record_fill + record_settlement in one call."""
    sess.record_fill(agent, pnl_cents=0.0, fees_cents=0.0)
    sess.register_open_trade(agent, market_id, side, "buy", contracts, price_cents)
    return sess.record_settlement(market_id, outcome)


# ── BUG-01 & BUG-08: no double PnL / no double win-count ────────────────────



# ── BUG-02: get_portfolio_stats PnL keys ────────────────────────────────────

class TestBug02PortfolioStatsPnLKeys:
    """total_realized_pnl and total_pnl must be distinct and correct."""

    def _engine_with_closed_position(self):
        from trading.paper_trading import PaperTradingEngine
        eng = PaperTradingEngine(starting_balance=10_000.0)
        uid = "test_user"
        portfolio = eng.get_portfolio(uid)
        portfolio.total_pnl = 250.0   # realized from a closed position
        portfolio.current_balance = 9_750.0  # 10000 - 500 margin + 250 realized - 0 fee
        # Open position with unrealized PnL of $100
        from trading.paper_trading import PaperPosition
        pos = PaperPosition(
            position_id="p1", user_id=uid, asset="BTC", side="long",
            size_usd=500.0, entry_price=40000.0, current_price=40000.0,
            leverage=1, market_type="perp", market_id="", venue="test",
        )
        portfolio.positions["BTC_long_perp_test"] = pos
        # Inject current price so _calculate_position_pnl returns $100
        eng.current_prices["BTC"] = 40000.0 * 1.20  # 20% up = $100 on $500 position
        return eng, uid

    def test_total_realized_pnl_is_closed_only(self):
        eng, uid = self._engine_with_closed_position()
        stats = eng.get_portfolio_stats(uid)
        assert "total_realized_pnl" in stats, "total_realized_pnl key missing"
        assert stats["total_realized_pnl"] == pytest.approx(250.0)

    def test_total_pnl_includes_unrealized(self):
        eng, uid = self._engine_with_closed_position()
        stats = eng.get_portfolio_stats(uid)
        # total_pnl must be realized + unrealized
        assert stats["total_pnl"] > stats["total_realized_pnl"], (
            "total_pnl should exceed total_realized_pnl when positions are open"
        )

    def test_total_pnl_not_equal_to_realized(self):
        eng, uid = self._engine_with_closed_position()
        stats = eng.get_portfolio_stats(uid)
        assert stats["total_pnl"] != stats["total_realized_pnl"], (
            "total_pnl == total_realized_pnl with open positions — unrealized not included"
        )


# ── BUG-03: fees in balance identity ────────────────────────────────────────

class TestBug03FeesInBalanceIdentity:
    """cash + margin_locked + total_fees == starting_balance + realized_pnl."""

    @pytest.mark.skip(reason="legacy trading.reconciliation removed; balance_identity checks were paper-only")
    def test_reconciliation_balance_identity_includes_fees(self):
        from trading.paper_trading import PaperTradingEngine, PaperPosition
        from trading.reconciliation import run_reconciliation, CheckStatus
        import trading.paper_trading as _pt

        eng = PaperTradingEngine(starting_balance=10_000.0)
        uid = "fee_user"
        portfolio = eng.get_portfolio(uid)

        # Simulate: one open position, no closed trades, $50 in fees paid
        portfolio.total_fees = 50.0
        portfolio.total_pnl = 0.0
        portfolio.current_balance = 9_450.0   # 10000 - 500 margin - 50 fees

        pos = PaperPosition(
            position_id="p1", user_id=uid, asset="ETH", side="long",
            size_usd=500.0, entry_price=2000.0, current_price=2000.0,
            leverage=1, market_type="perp", market_id="", venue="test",
        )
        portfolio.positions["ETH_long_perp_test"] = pos

        # get_paper_engine is a lazy local import inside run_reconciliation —
        # patch it at the source module so the local import picks up the mock.
        with patch.object(_pt, "_paper_engine", eng):
            with patch("trading.paper_trading.get_paper_engine", return_value=eng):
                with patch("core.execution_gate.check_pnl_consistency",
                           return_value={"consistent": True, "max_divergence_usd": 0.0,
                                         "sources": {}}, create=True):
                    report = run_reconciliation()

        balance_check = next(
            (c for c in report.checks if "balance_identity" in c.name), None
        )
        assert balance_check is not None, "balance_identity check not found"
        assert balance_check.status == CheckStatus.OK, (
            f"Balance identity DELTA with fees included: {balance_check.detail} "
            f"(expected={balance_check.expected}, actual={balance_check.actual})"
        )

    def test_post_load_repair_subtracts_fees(self):
        from trading.paper_trading import PaperTradingEngine, _load_paper_state
        import json, tempfile
        from pathlib import Path

        eng = PaperTradingEngine(starting_balance=10_000.0)
        uid = "repair_user"
        portfolio = eng.get_portfolio(uid)

        state = {
            "portfolios": {
                uid: {
                    "starting_balance": 10_000.0,
                    "current_balance": 9_450.0,  # correct: 10000 - 500 margin - 50 fees
                    "total_pnl": 0.0,
                    "total_fees": 50.0,
                    "total_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "positions": {
                        "ETH_long_perp_test": {
                            "position_id": "p1", "user_id": uid,
                            "asset": "ETH", "side": "long",
                            "size_usd": 500.0, "entry_price": 2000.0,
                            "current_price": 2000.0, "leverage": 1,
                            "market_type": "perp", "market_id": "", "venue": "test",
                            "unrealized_pnl": 0.0, "realized_pnl": 0.0,
                            "opened_at": 0.0, "closed_at": None,
                        }
                    },
                    "closed_positions": [],
                    "trade_history": [],
                    "orders": {},
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                         delete=False) as f:
            json.dump(state, f)
            fpath = Path(f.name)

        try:
            with patch("trading.paper_trading._PERSIST_FILE", fpath):
                _load_paper_state(eng)

            p = eng.portfolios[uid]
            # After repair, balance should NOT be inflated by ignoring fees
            expected = 10_000.0 + 0.0 - 500.0 - 50.0  # = 9450
            assert abs(p.current_balance - expected) < 0.02, (
                f"Post-load repair overcorrected balance: "
                f"got {p.current_balance}, expected {expected}"
            )
        finally:
            fpath.unlink(missing_ok=True)


# ── BUG-04: category counters updated in record_fill / record_close ──────────

class TestBug04CategoryCounters:
    """_category_notional and _category_contracts must be maintained."""

    def _risk(self):
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
        cfg = PredictionRiskConfig()
        return PredictionMarketRisk(config=cfg)

    def test_record_fill_increments_category_notional(self):
        risk = self._risk()
        risk.record_fill(
            market_id="KXBTC-MKT",
            event_id="KXBTC",
            side="yes",
            contracts=10,
            price_cents=Decimal("50"),
            category="crypto",
        )
        assert "crypto" in risk._category_notional
        assert risk._category_notional["crypto"] == pytest.approx(Decimal("5.00"))
        assert risk._category_contracts["crypto"] == 10

    def test_record_fill_without_category_leaves_counters_empty(self):
        risk = self._risk()
        risk.record_fill(
            market_id="KXBTC-MKT2",
            event_id="KXBTC",
            side="yes",
            contracts=5,
            price_cents=Decimal("60"),
        )
        assert "crypto" not in risk._category_notional

    def test_record_close_decrements_category_notional(self):
        risk = self._risk()
        risk.record_fill(
            market_id="KXBTC-MKT3",
            event_id="KXBTC",
            side="yes",
            contracts=20,
            price_cents=Decimal("50"),
            category="crypto",
        )
        risk.record_close(
            market_id="KXBTC-MKT3",
            contracts=10,
            exit_price_cents=Decimal("70"),
            category="crypto",
        )
        # Should have reduced by half
        assert risk._category_contracts["crypto"] == 10
        assert risk._category_notional["crypto"] >= Decimal("0")

    def test_category_cap_now_fires(self):
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig, CategoryLimit
        # Cap set very low: 5 USD notional
        cfg = PredictionRiskConfig(
            category_limits={"crypto": CategoryLimit("crypto",
                                                      max_notional_usd=Decimal("5.00"),
                                                      max_contracts=100)}
        )
        risk = PredictionMarketRisk(config=cfg)
        # Fill up to exactly the cap: 10 contracts * 50c / 100 = $5.00
        risk.record_fill("MKT-A", "EVT-A", "yes", 10, Decimal("50"), category="crypto")
        # Next order should be blocked by category cap
        result = risk.check_order(
            market_id="MKT-B",
            event_id="EVT-B",
            side="yes",
            contracts=1,
            price_cents=Decimal("50"),
            category="crypto",
        )
        assert not result.allowed, (
            "Category cap should block order but allowed=True — counters still zero"
        )


# ── BUG-05: drawdown fires for cells starting with losses ───────────────────



# ── BUG-06: singleton factory race ──────────────────────────────────────────

class TestBug06SingletonRace:
    """get_paper_trading_engine must delegate to get_paper_engine, not race."""

    def test_get_paper_trading_engine_delegates_to_get_paper_engine(self):
        import trading.paper_trading as pt

        sentinel = MagicMock()
        with patch.object(pt, "get_paper_engine", return_value=sentinel) as mock_gpe:
            with patch("trading.paper_trading._paper_engine", None):
                try:
                    from merid.settings import settings as _s
                    kalshi_only = _s.KALSHI_ONLY
                except Exception:
                    kalshi_only = False

                if not kalshi_only:
                    result = pt.get_paper_trading_engine()
                    mock_gpe.assert_called_once(), (
                        "get_paper_trading_engine did not delegate to get_paper_engine"
                    )
                    assert result is sentinel

    def test_no_bare_engine_created_on_second_factory_call(self):
        import trading.paper_trading as pt

        real_engine = MagicMock()
        real_engine.starting_balance = 10_000.0

        called_engines = []

        def track_init(starting_balance=None, **kw):
            e = MagicMock()
            e.starting_balance = starting_balance
            called_engines.append(starting_balance)
            return e

        with patch.object(pt, "_paper_engine", None):
            with patch("trading.paper_trading.PaperTradingEngine", side_effect=track_init):
                with patch("trading.paper_trading._load_paper_state"):
                    with patch("core.fresh_start.is_fresh_start", return_value=False):
                        # Call get_paper_engine first (canonical)
                        pt.get_paper_engine()
                        # Call the second factory — should NOT create another engine
                        try:
                            from merid.settings import settings as _s
                            if _s.KALSHI_ONLY:
                                return
                        except Exception:
                            pass
                        pt.get_paper_trading_engine()

        # PaperTradingEngine() should only have been constructed once
        assert len(called_engines) <= 1, (
            f"PaperTradingEngine constructed {len(called_engines)} times — singleton race"
        )


# ── BUG-07: stale price handling ─────────────────────────────────────────────

class TestBug07StalePriceHandling:
    """Stale price must not silently zero unrealized PnL."""

    def test_missing_price_preserves_last_unrealized_pnl(self):
        from trading.paper_trading import PaperTradingEngine, PaperPosition

        eng = PaperTradingEngine(starting_balance=10_000.0)
        # No current_prices populated
        pos = PaperPosition(
            position_id="p1", user_id="u1", asset="BTC", side="long",
            size_usd=1000.0, entry_price=40_000.0, current_price=41_000.0,
            leverage=1, market_type="perp", market_id="", venue="test",
        )
        pos.unrealized_pnl = 25.0  # last known value

        result = eng._calculate_position_pnl(pos)

        assert result == pytest.approx(25.0), (
            f"Expected last known unrealized_pnl=25.0, got {result} — "
            "stale price fallback zeroed PnL"
        )
        assert getattr(pos, "price_stale", False) is True, (
            "price_stale flag not set when price feed missing"
        )

    def test_stale_price_not_equal_to_entry_price_when_no_feed(self):
        from trading.paper_trading import PaperTradingEngine, PaperPosition

        eng = PaperTradingEngine(starting_balance=10_000.0)
        pos = PaperPosition(
            position_id="p2", user_id="u1", asset="ETH", side="long",
            size_usd=500.0, entry_price=2_000.0, current_price=2_200.0,
            leverage=1, market_type="perp", market_id="", venue="test",
        )
        pos.unrealized_pnl = 50.0

        eng._calculate_position_pnl(pos)

        # current_price must NOT have been overwritten with entry_price
        assert pos.current_price != pos.entry_price or pos.price_stale, (
            "current_price was reset to entry_price (stale fallback path)"
        )

    @pytest.mark.skip(reason="legacy trading.reconciliation removed; stale-price masking was paper-only")
    def test_reconciliation_flags_stale_price_position(self):
        from trading.paper_trading import PaperTradingEngine, PaperPosition
        from trading.reconciliation import run_reconciliation, CheckStatus
        import trading.paper_trading as _pt

        eng = PaperTradingEngine(starting_balance=10_000.0)
        uid = "stale_user"
        portfolio = eng.get_portfolio(uid)
        pos = PaperPosition(
            position_id="p3", user_id=uid, asset="BTC", side="long",
            size_usd=500.0, entry_price=40_000.0, current_price=41_000.0,
            leverage=1, market_type="perp", market_id="", venue="test",
        )
        pos.unrealized_pnl = 25.0
        pos.price_stale = True  # simulate stale feed
        portfolio.positions["BTC_long_perp_test"] = pos

        with patch.object(_pt, "_paper_engine", eng):
            with patch("trading.paper_trading.get_paper_engine", return_value=eng):
                with patch("core.execution_gate.check_pnl_consistency",
                           return_value={"consistent": True, "max_divergence_usd": 0.0,
                                         "sources": {}}, create=True):
                    report = run_reconciliation()

        stale_check = next(
            (c for c in report.checks
             if "position" in c.name and "pnl" in c.name
             and c.status != CheckStatus.OK), None
        )
        assert stale_check is not None, (
            "Reconciliation did not flag the stale-price position — "
            "BUG-07 masking is still present"
        )
        assert "stale" in stale_check.detail.lower()


# ── BUG-08 / Bug 6: sell-close early PnL (no double-count with hold-to-expiry) ─

