"""CRYPTO MM QUOTE wiring: mid price for intent_risk and threshold matrix prep."""

from decimal import Decimal

import pytest

from merid.prediction.model import ContractState, ImpliedProbability, MarketSnapshot
from merid.prediction.strategy import KalshiStrategy, SignalAction, StrategyConfig


def _snapshot_mm_ok() -> MarketSnapshot:
    """Tight book: 48/52 bid/ask, 4c spread (under default mm_max_spread_cents=10)."""
    imp = ImpliedProbability(
        yes_prob=Decimal("0.50"),
        no_prob=Decimal("0.50"),
        yes_bid=Decimal("0.48"),
        yes_ask=Decimal("0.52"),
        spread_cents=Decimal("4"),
    )
    return MarketSnapshot(
        market_id="KXETH15M-26APR081845-45",
        event_id="evt",
        title="t",
        state=ContractState.TRADING,
        implied=imp,
        volume=Decimal("1000"),
        open_interest=Decimal("100"),
    )


def test_evaluate_mm_sets_limit_price_cents_to_mid():
    """QUOTE signals carry limit_price_cents = floor((bid+ask)/2) for downstream intent_risk."""
    strat = KalshiStrategy(StrategyConfig(), agent_name="CRYPTO_15M_MM")
    snap = _snapshot_mm_ok()
    sig = strat._evaluate_mm(snap, strat._expiry_phase(Decimal("0.5")))
    assert sig.action == SignalAction.QUOTE
    assert sig.bid_price_cents is not None and sig.ask_price_cents is not None
    assert sig.limit_price_cents is not None
    expected_mid = max(1, min(99, (sig.bid_price_cents + sig.ask_price_cents) // 2))
    assert sig.limit_price_cents == expected_mid
    assert sig.limit_price_cents > 0


def test_quote_intent_risk_nonzero_math():
    """Contracts × mid-cents / 100 must be > 0 when limit_price_cents is set."""
    strat = KalshiStrategy(StrategyConfig(), agent_name="CRYPTO_15M_MM")
    snap = _snapshot_mm_ok()
    sig = strat._evaluate_mm(snap, strat._expiry_phase(Decimal("0.5")))
    size = sig.contracts
    pc = sig.limit_price_cents or 0
    intent_risk = float(size) * (pc / 100.0)
    assert intent_risk > 0.0


def test_kalshi_tools_order_intent_includes_agent_id():
    """OrderIntent from kalshi_tools passes agent_name through as agent_id."""
    from merid.event_venues.kalshi.order_router import OrderIntent
    from merid.prediction.venue_gate import TradingMode

    intent = OrderIntent(
        ticker="KXBTC15M-X",
        side="yes",
        action="buy",
        price_cents=50,
        count=2,
        mode=TradingMode.LIVE,
        source="kalshi_tools",
        agent_id="kalshi-crypto_15m_mm_deadbeef",
    )
    assert intent.agent_id == "kalshi-crypto_15m_mm_deadbeef"
