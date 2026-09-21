"""
Incident regression tests for the exit price guard (2026-08-19).

These tests cover the BTC 40c stale-data loss incident: an automated
discretionary exit must be rejected unless it is based on a fresh quote,
attributable to an allowed reason, and bounded by the configured max loss /
slippage.  Emergency / near-expiry liquidation is preserved.
"""

import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest


@pytest.fixture(autouse=True)
def _disable_persistence_and_fees(monkeypatch):
    """Keep tests hermetic: do not write to logs/order_decisions.jsonl.

    Fees are mocked to a predictable round-trip 4c so assertions are stable
    across fee-schedule environment differences.
    """
    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_intent_contract.persist_order_decision",
        lambda record: None,
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.parabolic_fees.kalshi_taker_fee_cents_parabolic",
        lambda *_a, **_k: 2,
    )


@pytest.fixture(autouse=True)
def _reset_ev_gate_state(monkeypatch):
    """Keep the EV exit gate hermetic: no file persistence, no env enable,
    and no live RTI fetch (the default provider must not hit the network)."""
    monkeypatch.setenv("MERID_EV_EXIT_DISABLE_PERSIST", "1")
    monkeypatch.delenv("MERID_ENABLE_EV_EXIT_GATE", raising=False)
    monkeypatch.delenv("MERID_EV_EXIT_GATE_KILL", raising=False)
    import merid.event_venues.kalshi.settlement_aligned_exit as sae

    monkeypatch.setattr(sae, "_default_rti_provider", lambda _asset: None)
    sae._evaluator = None
    sae._registry = None
    sae._resolver = None
    yield
    sae._evaluator = None
    sae._registry = None
    sae._resolver = None


@pytest.fixture(autouse=True)
def _seed_canonical_position_cache():
    """Seed the canonical cache with an open position for the test market.

    The exit guard now rejects exits when the canonical position cache reports
    a flat or missing position. These tests call the guard directly with a
    monitor-side Position snapshot, so the canonical cache must be seeded to
    satisfy the new safety contract.
    """
    from merid.event_venues.kalshi.position_cache import CachedPosition, get_position_cache

    market_id = "KXBTC15M-26AUG100000-00"
    cache = get_position_cache()
    cache._positions[market_id] = CachedPosition(
        market_id=market_id,
        agent_id="test",
        contracts=1,
        side="no",
        thesis_side="no",
        avg_price_cents=74,
    )
    yield
    cache._positions.pop(market_id, None)


def _make_state(*, no_bid=None, no_ask=None, yes_bid=None, yes_ask=None,
                age_ms=1000, seconds_to_expiry=300.0, source="ws"):
    """Build a minimal market state for the exit guard."""
    state = Mock()
    state.book_updated_ts = time.monotonic() - (age_ms / 1000.0)
    state.seconds_to_expiry = seconds_to_expiry
    state.book_source = source
    state.no_bid_cents = no_bid
    state.no_ask_cents = no_ask
    state.best_bid_cents = yes_bid
    state.best_ask_cents = yes_ask
    state.book = None
    return state


def _make_position(**kwargs):
    defaults = dict(
        position_id="pos-12345678",
        market_id="KXBTC15M-26AUG100000-00",
        size=1,
        avg_entry_price_cents=74,
        outcome_side="no",
        thesis_side="no",
        stop_loss_price_cents=None,
        hard_stop_price_cents=None,
        entry_fill_id="fill-abc",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _patched_get_market_state(state=None):
    def _get_market_state(_ticker):
        return (state, None)
    return _get_market_state


def _run_guard(position, exit_reason, exit_price_cents=36, count=1, state=None):
    from merid.loop_15m import _run_exit_price_guard
    with patch(
        "merid.event_venues.kalshi.stop_candidate._get_market_state",
        _patched_get_market_state(state),
    ):
        return _run_exit_price_guard(position, exit_reason, exit_price_cents, count)


def test_stale_data_loss_exit_rejected_on_stale_quote():
    """Incident: a stale-data trigger with a stale quote must be rejected."""
    position = _make_position()
    state = _make_state(no_bid=42, no_ask=44, age_ms=12_264)

    approved, _price, record, _did = _run_guard(
        position, "stale_data", exit_price_cents=36, state=state
    )

    assert approved is False
    assert record["exit_reason_canonical"] == "reconciliation"
    assert record["reject_reason"] == "stale_quote"
    assert record["best_bid_cents"] == 42


def test_fresh_quote_loss_exit_rejected_on_profit_floor():
    """A fresh quote does not make a 32c gross loss exit acceptable."""
    position = _make_position()
    state = _make_state(no_bid=42, no_ask=44, age_ms=100)

    approved, _price, record, _did = _run_guard(
        position, "stale_data", exit_price_cents=36, state=state
    )

    assert approved is False
    assert record["exit_reason_canonical"] == "reconciliation"
    assert record["reject_reason"] == "profit_exit_not_profitable"
    assert record["projected_net_pnl_cents"] < -3
    assert record["best_bid_cents"] == 42


def test_emergency_expiry_liquidation_approved():
    """Near-expiry emergency liquidation with a bounded loss is preserved."""
    position = _make_position()
    state = _make_state(no_bid=70, no_ask=72, seconds_to_expiry=30.0)

    approved, price, record, _did = _run_guard(
        position, "auto_exit_99c", exit_price_cents=99, state=state
    )

    assert approved is True
    assert record["exit_reason_canonical"] == "expiry_liquidation"
    assert record["is_emergency"] is True
    assert record["limit_cents"] == 68  # 70c bid - 2c slippage
    assert record["projected_net_pnl_cents"] < 0
    assert record["projected_net_pnl_cents"] >= -15
    assert price == 68


def test_stop_loss_vetoed_observe_only_when_gate_disabled():
    """Discretionary stop-loss is observe-only while the EV gate is disabled.

    The legacy checks still compute the would-be limit price so the record is
    replayable, but the order is vetoed at the approval point.
    """
    position = _make_position(stop_loss_price_cents=70)
    state = _make_state(no_bid=70, no_ask=72)

    approved, price, record, _did = _run_guard(
        position, "stop_loss", exit_price_cents=70, state=state
    )

    assert approved is False
    assert record["exit_reason_canonical"] == "stop_loss"
    assert record["exit_class"] == "discretionary"
    assert record["reject_reason"] == "discretionary_exit_observe_only"
    assert record["legacy_would_approve"] is True
    assert record["limit_cents"] == 68  # stop 70 - 2c slippage (recorded for replay)
    assert record["projected_net_pnl_cents"] < 0  # bounded loss, recorded for replay
    assert "ev_evaluation" in record


def test_stop_loss_rejected_when_market_gapped_through_slippage():
    """If the best bid is worse than stop - slippage, do not chase the market."""
    position = _make_position(stop_loss_price_cents=70)
    # Market has already fallen to 67; stop - 2 = 68, so the bid is worse.
    state = _make_state(no_bid=67, no_ask=69)

    approved, _price, record, _did = _run_guard(
        position, "stop_loss", exit_price_cents=70, state=state
    )

    assert approved is False
    assert record["reject_reason"] == "stop_beyond_slippage"


def test_take_profit_vetoed_observe_only_when_gate_disabled():
    """Take-profit is discretionary: observe-only until the EV gate is enabled."""
    position = _make_position()
    state = _make_state(no_bid=84, no_ask=86)

    approved, _price, record, _did = _run_guard(
        position, "take_profit", exit_price_cents=84, state=state
    )

    assert approved is False
    assert record["exit_reason_canonical"] == "take_profit"
    assert record["exit_class"] == "discretionary"
    assert record["reject_reason"] == "discretionary_exit_observe_only"
    assert record["legacy_would_approve"] is True
    assert record["limit_cents"] == 84  # recorded for replay


def test_take_profit_rejected_when_not_profitable():
    """A take-profit priced at a loss is rejected."""
    position = _make_position()
    state = _make_state(no_bid=70, no_ask=72)

    approved, _price, record, _did = _run_guard(
        position, "take_profit", exit_price_cents=70, state=state
    )

    assert approved is False
    assert record["reject_reason"] == "profit_exit_not_profitable"


def test_unknown_exit_reason_rejected():
    """Only explicitly allowed exit reasons may be submitted."""
    position = _make_position()
    state = _make_state(no_bid=50, no_ask=52)

    approved, _price, record, _did = _run_guard(
        position, "foobar", exit_price_cents=50, state=state
    )

    assert approved is False
    assert record["reject_reason"] == "exit_reason_not_allowed"


def test_time_exit_with_small_loss_vetoed_observe_only():
    """Non-mechanical time exits are discretionary: observe-only by default."""
    position = _make_position()
    # 1c gross loss -> net -7 with mocked 4c round-trip fee; forced exit still approves.
    state = _make_state(no_bid=73, no_ask=75)

    approved, _price, record, _did = _run_guard(
        position, "time_stop", exit_price_cents=73, state=state
    )

    assert approved is False
    assert record["exit_reason_canonical"] == "time_exit"
    assert record["exit_class"] == "discretionary"
    assert record["reject_reason"] == "discretionary_exit_observe_only"
    assert record["projected_net_pnl_cents"] < 0


def test_time_exit_break_even_vetoed_observe_only():
    """Break-even time exit is discretionary too; recorded but not submitted."""
    position = _make_position()
    state = _make_state(no_bid=74, no_ask=76)

    approved, _price, record, _did = _run_guard(
        position, "time_stop", exit_price_cents=74, state=state
    )

    assert approved is False
    assert record["exit_reason_canonical"] == "time_exit"
    assert record["reject_reason"] == "discretionary_exit_observe_only"
    assert record["projected_net_pnl_cents"] < 0  # gross -2 minus round-trip fees


def test_quote_freshness_uses_age_threshold():
    """Quote just under the freshness threshold reaches the gate; just over is rejected."""
    position = _make_position()
    from merid.loop_15m import MERID_EXIT_MAX_QUOTE_AGE_MS

    # Just under the 10,000 ms default: the quote passes freshness but the
    # discretionary exit is still vetoed observe-only (gate disabled).
    state = _make_state(no_bid=84, no_ask=86, age_ms=MERID_EXIT_MAX_QUOTE_AGE_MS - 1)
    approved, _price, record, _did = _run_guard(
        position, "take_profit", exit_price_cents=84, state=state
    )
    assert approved is False
    assert record["reject_reason"] == "discretionary_exit_observe_only"

    # Just over the threshold: a profitable exit is rejected for stale quote.
    state = _make_state(no_bid=84, no_ask=86, age_ms=MERID_EXIT_MAX_QUOTE_AGE_MS + 100)
    approved, _price, record, _did = _run_guard(
        position, "take_profit", exit_price_cents=84, state=state
    )
    assert approved is False
    assert record["reject_reason"] == "stale_quote"


def test_current_edge_reversal_vetoed_observe_only():
    """current_edge_reversal canonicalizes to signal_reversal (discretionary, vetoed)."""
    position = _make_position()
    state = _make_state(no_bid=84, no_ask=86)
    state.book_updated_ts = time.monotonic()  # avoid stale quote after slow module import

    approved, _price, record, _did = _run_guard(
        position, "current_edge_reversal", exit_price_cents=84, state=state
    )

    assert approved is False
    assert record["exit_reason_canonical"] == "signal_reversal"
    assert record["exit_reason_original"] == "current_edge_reversal"
    assert record["exit_class"] == "discretionary"
    assert record["reject_reason"] == "discretionary_exit_observe_only"
    assert record["limit_cents"] == 82  # recorded for replay
    assert record["projected_net_pnl_cents"] > 0  # worst-case (82-74) minus fees
