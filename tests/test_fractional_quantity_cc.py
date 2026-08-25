"""Fractional centi-contract propagation through order intent, router, and wire.

This is the 2026-08-18 acceptance matrix for the ``quantity_cc`` canonical model.
"""

import pytest
import os
from decimal import Decimal

from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    route_order,
    simulate_paper_fill,
)
from merid.event_venues.kalshi.order_intent_contract import (
    normalize_order,
    validate_canonical_intent,
    OrderIntentValidationError,
    CanonicalOrderIntent,
)
from merid.event_venues.kalshi.position_cache import KalshiPositionCache
from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger
from merid.prediction.trading_mode import TradingMode


@pytest.fixture(autouse=True)
def _ensure_testing_env():
    """Keep the test environment explicitly non-production and mock mode."""
    from trading.trade_mode import _reset_for_tests, set_trade_mode
    old_env = os.environ.get("MERID_ENV")
    os.environ["MERID_ENV"] = "testing"
    os.environ["MERID_TRADE_MODE"] = "mock"
    _reset_for_tests()
    set_trade_mode(TradingMode.MOCK, reason="fractional test fixture")
    yield
    os.environ["MERID_ENV"] = old_env if old_env is not None else "testing"


@pytest.fixture
def cache():
    c = KalshiPositionCache()
    c._positions = {}
    c._applied_fill_ids.clear()
    return c


@pytest.fixture
def ledger():
    return KalshiFillsLedger()


def _intent(count_fp: Decimal, side="yes", action="buy", price=50, count=None, **kw):
    return OrderIntent(
        ticker="KXETH15M-FRAC",
        side=side,
        action=action,
        price_cents=price,
        count=int(count) if count is not None else 0,
        count_fp=count_fp,
        mode=TradingMode.MOCK,
        reason="fractional_test",
        agent_id="ETH_15M",
        source="ETH_15M",
        **kw,
    )


class TestNormalizeFractional:
    """order_intent_contract.normalize_order is the boundary to the canonical model."""

    def test_count_fp_zero_point_three_five(self):
        intent = _intent(Decimal("0.35"))
        canonical = normalize_order(intent, exchange_position_cc=0)
        assert isinstance(canonical, CanonicalOrderIntent)
        assert canonical.qty_cc == 35

    def test_count_zero_with_count_fp_is_accepted(self):
        # count is display/floor and may be 0 for fractional sizes.
        intent = _intent(Decimal("0.49"), count=0)
        canonical = normalize_order(intent, exchange_position_cc=0)
        assert canonical.qty_cc == 49

    def test_reject_count_fp_not_aligned_to_centi_contract(self):
        intent = _intent(Decimal("0.355"))
        with pytest.raises(OrderIntentValidationError):
            normalize_order(intent, exchange_position_cc=0)

    def test_reject_negative_count_fp(self):
        intent = _intent(Decimal("-0.35"))
        with pytest.raises(OrderIntentValidationError):
            normalize_order(intent, exchange_position_cc=0)

    def test_reject_count_fp_nan(self):
        intent = _intent(Decimal("NaN"))
        with pytest.raises(OrderIntentValidationError):
            normalize_order(intent, exchange_position_cc=0)

    def test_integer_count_backfills_count_fp(self):
        # If only the legacy ``count`` field is supplied, qty_cc is still exact.
        intent = OrderIntent(
            ticker="KXETH15M-FRAC",
            side="yes",
            action="buy",
            price_cents=50,
            count=2,
            mode=TradingMode.MOCK,
            reason="fractional_test",
        )
        canonical = normalize_order(intent, exchange_position_cc=0)
        assert canonical.qty_cc == 200


class TestPaperFillFractional:
    """simulate_paper_fill must produce and consume fixed-point quantity."""

    def test_simulate_zero_point_three_five(self):
        intent = _intent(Decimal("0.35"))
        fill = simulate_paper_fill(intent)
        assert fill["count_fp"] == "0.35"
        assert fill["quantity_cc"] == 35
        assert fill["count"] == 0
        assert fill["requested_quantity_cc"] == 35
        assert fill["remaining_quantity_cc"] == 0

    def test_simulate_partial_fill_fractional(self):
        # 2.50 contracts -> partial fill of 2 with 0.50 remainder.
        intent = _intent(Decimal("2.50"))
        # Seed deterministic RNG to hit the partial-fill branch.
        import random
        rng = random.Random(42)
        fill = simulate_paper_fill(intent, _rng=rng)
        if fill["partial_fill"]:
            assert fill["quantity_cc"] > 0
            assert fill["quantity_cc"] <= 250
            assert fill["remaining_quantity_cc"] == 250 - fill["quantity_cc"]
            assert fill["remaining_quantity_cc"] >= 0
        else:
            assert fill["quantity_cc"] == 250
            assert fill["remaining_quantity_cc"] == 0


class TestExitInvariantsFractional:
    """Over-close and residual exposure use centi-contracts."""

    def test_exit_full_close_zero_point_three_five(self):
        # Long YES 0.35, exit SELL YES 0.35 -> flat.
        canonical = normalize_order(
            _intent(Decimal("0.35"), side="yes", action="sell"),
            exchange_position_cc=35,
        )
        assert canonical.qty_cc == 35
        assert canonical.expected_position_after == 0
        validate_canonical_intent(canonical, exchange_position_cc=35)

    def test_exit_over_close_rejected(self):
        # Long YES 0.35, exit SELL YES 0.36 -> over-close.
        canonical = normalize_order(
            _intent(Decimal("0.36"), side="yes", action="sell"),
            exchange_position_cc=35,
        )
        with pytest.raises(OrderIntentValidationError) as exc:
            validate_canonical_intent(canonical, exchange_position_cc=35)
        assert "over_close" in str(exc.value)

    def test_exit_partial_close_leaves_residual(self):
        # Long YES 0.35, exit SELL YES 0.34 -> residual 0.01.
        canonical = normalize_order(
            _intent(Decimal("0.34"), side="yes", action="sell"),
            exchange_position_cc=35,
        )
        assert canonical.expected_position_after == 1  # 0.01 contracts

    def test_all_four_shapes_long_short_yes_no(self):
        # Long YES -> entry BUY YES, exit SELL YES
        c1 = normalize_order(_intent(Decimal("0.35")), exchange_position_cc=0)
        assert c1.qty_cc == 35 and c1.yes_delta() == 35
        # Short YES (long NO) -> entry BUY NO, exit SELL NO
        c2 = normalize_order(
            _intent(Decimal("0.35"), side="no", action="buy"),
            exchange_position_cc=-35,
        )
        assert c2.qty_cc == 35 and c2.yes_delta() == -35
        # Long NO? same as short YES; use SELL NO to close a short YES (long NO) position.
        c3 = normalize_order(
            _intent(Decimal("0.35"), side="no", action="sell"),
            exchange_position_cc=-35,
        )
        assert c3.qty_cc == 35 and c3.yes_delta() == +35
        # Short NO (long YES) -> entry SELL NO, exit BUY NO
        c4 = normalize_order(
            _intent(Decimal("0.35"), side="no", action="buy"),
            exchange_position_cc=35,
        )
        assert c4.qty_cc == 35 and c4.yes_delta() == -35


class TestRouterFractional:
    """route_order must preserve fractional size through the router."""

    def test_mock_entry_fill_zero_point_three_five(self, cache, ledger, monkeypatch):
        import merid.event_venues.kalshi.order_router as _router
        _router._startup_time = 0.0
        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_router._is_authorized_caller",
            lambda caller: True,
        )
        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_router._apply_risk_based_order_sizing",
            lambda intent, bankroll_usd=None: intent.count_fp or Decimal(intent.count),
        )
        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_router._apply_depth_based_order_sizing",
            lambda intent, state=None: intent.count_fp or Decimal(intent.count),
        )
        # Provide a healthy risk envelope so bankroll checks pass.
        class _MockEnvelope:
            max_total_notional_usd = 1000.0
            def get_depth_thresholds(self, _asset):
                return {"min_depth_yes": 1, "min_depth_no": 1}
        monkeypatch.setattr(
            "merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope",
            lambda *_a, **_k: _MockEnvelope(),
        )
        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_router._get_strategy_policy",
            lambda _intent: {
                "min_edge": 0.0,
                "min_confidence": 0.0,
                "max_md_staleness_sec": 1000,
            },
        )
        intent = _intent(
            Decimal("0.35"), confidence=0.95, edge_pct=0.03, model_prob=0.55,
            effective_equity_usd=1000.0, entry_or_exit="entry",
            exit_policy_id="frac_test_ep", window_resolution_id="frac_test_wr",
            risk_tier="standard", max_hold_seconds=900,
        )
        result = route_order(intent)
        assert result.status == "filled_mock"
        assert result.fill["count_fp"] == "0.35"
        assert result.fill["quantity_cc"] == 35

    def test_mock_exit_over_close_rejected(self, cache, monkeypatch):
        monkeypatch.setattr(
            "merid.event_venues.kalshi.order_router._is_authorized_caller",
            lambda caller: True,
        )
        # Seed a long YES 0.35 position.
        cache._positions["KXETH15M-FRAC"] = cache._positions.get(
            "KXETH15M-FRAC",
            type("P", (), {
                "market_id": "KXETH15M-FRAC",
                "side": "yes",
                "quantity_cc": 35,
                "contracts": 0,
                "avg_price_cents": 50,
                "_yes_exposure": lambda self: 35,
            })(),
        )
        monkeypatch.setattr(
            "merid.event_venues.kalshi.position_cache.get_position_cache",
            lambda: cache,
        )
        intent = _intent(Decimal("0.36"), side="yes", action="sell", entry_or_exit="exit")
        result = route_order(intent)
        assert result.status == "rejected"
        assert "over_close" in result.reason or "exit_invariant" in result.reason
