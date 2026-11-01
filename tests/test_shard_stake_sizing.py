from decimal import Decimal
from types import SimpleNamespace

import pytest

from merid.event_venues.kalshi import shard_funding as sf
from merid.event_venues.kalshi.parabolic_fees import kalshi_fee_cents_exact
from merid.prediction import unified_sizing as sizing


@pytest.fixture
def isolated_sizing(monkeypatch):
    from merid.config import live_config
    from merid.risk import global_slot_allocator

    allocator = SimpleNamespace(
        sync_with_position_cache=lambda: 0,
        get_total_exposure=lambda: 0,
    )
    config = SimpleNamespace(
        resolved=True, fixed_exposure_cap_usd=Decimal("6"),
        max_contracts_per_order=6,
    )
    monkeypatch.setattr(global_slot_allocator, "get_global_slot_allocator", lambda: allocator)
    monkeypatch.setattr(live_config, "get_resolved_live_config", lambda **kw: config)
    monkeypatch.setattr(sizing, "_get_max_contracts_per_asset", lambda asset: 6)
    monkeypatch.setattr(sizing, "_is_dynamic_sizing_enabled", lambda: False)
    monkeypatch.setattr(sf, "_last_result", None)
    monkeypatch.setenv("MERID_DISABLE_LOSS_CAP", "1")


@pytest.mark.parametrize("price", [50, 94, 95, 98])
def test_stake_cap_sizes_down_on_centi_contract_grid(isolated_sizing, price):
    cash = Decimal("13.5694")
    cap = sizing.shard_stake_cap_usd(cash, Decimal("0.35"))
    count, notional, metadata = sizing.compute_order_size(
        bankroll_usd=cash, price_cents=price, asset="BTC", stake_cap_usd=cap
    )
    q = Decimal(str(count))
    assert q == q.quantize(Decimal("0.01"))
    assert notional == q * Decimal(price) / 100
    assert notional <= cap
    assert notional + kalshi_fee_cents_exact(price / 100, q, "taker") / 100 <= cash
    if price == 98:
        assert q == Decimal("4.84")
        assert metadata["stake_cap_applied"]


def test_cap_disabled_and_invalid_inputs():
    assert sizing.shard_stake_cap_usd(Decimal("10"), Decimal("0")) is None
    with pytest.raises(ValueError):
        sizing.shard_stake_cap_usd(Decimal("NaN"), Decimal("0.35"))
    with pytest.raises(ValueError):
        sizing.shard_stake_cap_usd(Decimal("-1"), Decimal("0.35"))


def test_exact_shard_cash_must_be_fresh(monkeypatch):
    monkeypatch.setattr(sf.time, "time", lambda: 100.0)
    monkeypatch.setattr(sf, "_bal_cache", {2: Decimal("13.5694")})
    monkeypatch.setattr(sf, "_bal_cache_ts", 95.0)
    monkeypatch.setattr(sf, "_last_result", None)
    assert sf.fresh_cached_shard_cash(2) == Decimal("13.5694")
    assert sf.fresh_cached_shard_cash(0) is None
    monkeypatch.setattr(sf, "_bal_cache_ts", 84.0)
    assert sf.fresh_cached_shard_cash(2) is None
    monkeypatch.setattr(sf, "_bal_cache_ts", 101.0)
    assert sf.fresh_cached_shard_cash(2) is None


def test_funding_snapshot_fallback_requires_same_shard_and_freshness(monkeypatch):
    monkeypatch.setattr(sf.time, "time", lambda: 100.0)
    monkeypatch.setattr(sf, "_bal_cache", {})
    monkeypatch.setattr(sf, "_last_check_ts", 92.0)
    snapshot = sf.ShardFundingResult(
        2, {2: Decimal("13.5694")}, Decimal("13.5694"), Decimal("6")
    )
    monkeypatch.setattr(sf, "_last_result", snapshot)
    assert sf.fresh_cached_shard_cash(2) == Decimal("13.5694")
    assert sf.fresh_cached_shard_cash(1) is None
    monkeypatch.setattr(sf, "_last_check_ts", 84.0)
    assert sf.fresh_cached_shard_cash(2) is None


@pytest.mark.parametrize("ev", [None, "-5", "0", "NaN"])
def test_stake_resize_does_not_release_nonpositive_evidence(ev):
    decision = SimpleNamespace(
        selected_outcome="yes", p_selected=Decimal("0.98"),
        indicators={"yes_ev_net_cents": ev},
    )
    assert not sizing.stake_sizing_evidence_is_positive(decision, "yes")


def test_stake_resize_requires_matching_selected_side_and_positive_ev():
    decision = SimpleNamespace(
        selected_outcome="no", p_selected=Decimal("0.98"),
        indicators={"no_ev_net_cents": Decimal("1")},
    )
    assert sizing.stake_sizing_evidence_is_positive(decision, "no")
    assert not sizing.stake_sizing_evidence_is_positive(decision, "yes")
    assert not sizing.stake_sizing_evidence_is_positive(None, "yes")


def test_permissive_lane_floor_cannot_release_negative_resized_order(monkeypatch):
    from merid.config import live_config
    from merid.risk.executable_cost_ev_gate import EVInput, evaluate_executable_cost_ev

    monkeypatch.setattr(live_config, "get_resolved_live_config", lambda **kw: None)
    result = evaluate_executable_cost_ev(EVInput(
        p_model=Decimal("0.97"), p_exec=Decimal("0.98"), qty_cc=484,
        entry_fee_per_contract=Decimal("0.001"),
        min_dollar_ev=Decimal("-1"), min_ev_to_tail_ratio=Decimal("-10"),
    ))
    assert result.allowed
    assert not sizing.stake_sizing_final_ev_is_positive(result)

    positive = evaluate_executable_cost_ev(EVInput(
        p_model=Decimal("0.99"), p_exec=Decimal("0.98"), qty_cc=484,
        entry_fee_per_contract=Decimal("0.001"),
        min_dollar_ev=Decimal("0"), min_ev_to_tail_ratio=Decimal("0"),
    ))
    assert positive.allowed
    assert sizing.stake_sizing_final_ev_is_positive(positive)
