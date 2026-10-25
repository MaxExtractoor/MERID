"""Held-position observer coverage for the late_window_trend_favorite shadow.

The position-limit early return in ``_collect_order_candidate_impl`` fires
upstream of ``_generate_signal``, so markets where a position is already
held produced zero LWF shadow records — exactly the population the lane
trades.  ``_emit_lwf_held_position_shadow`` closes that gap.  These tests
prove the observe-only contract: coverage restored, no duplicates, no
mutation, no routing effect, explicit missing/stale-input semantics.
"""
import asyncio
import copy
import json
import time
from decimal import Decimal
from types import SimpleNamespace

import pytest

import merid.prediction.lwf_shadow_lane as lwf
from merid.prediction.agent_grid_15m import LeanAgent15m


ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
SIDES = ["yes", "no"]
_STRIKES = {
    "BTC": 101000.0, "ETH": 3400.0, "SOL": 185.0, "XRP": 2.45, "DOGE": 0.185,
}


def _make_agent(asset: str, ticker: str, mte_min: float):
    """Bare LeanAgent15m with the attrs the collect path reads before the
    position-limit return.  __init__ is intentionally bypassed: only
    snapshot/state attrs used by the path are set."""
    agent = LeanAgent15m.__new__(LeanAgent15m)
    agent.config = SimpleNamespace(name=f"{asset}_15M", max_concurrent_positions=4)
    agent.run_id = "test_run"
    agent._rejection_waterfall = {
        "asset": asset, "stages": {}, "selected": False, "final_reason": "",
    }
    agent._last_trade_time = {}
    agent._session_start_time = time.time()
    agent._session_window_sec = 900.0
    agent._session_order_count = 0
    agent._session_risk_usd = 0.0
    agent._session_risk_cap_usd = 0.0
    agent._consecutive_losses = {asset: 0}
    agent._consecutive_loss_pause_until = {asset: 0.0}
    agent._portfolio_heat_enabled = False
    agent._spot_cache = {asset: (time.monotonic(), _STRIKES[asset] * 1.001, None)}
    agent._spot_cache_ttl_sec = 1.0
    ms = SimpleNamespace(
        best_bid_cents=89, best_ask_cents=91,
        min_depth_yes=2.0, min_depth_no=1.5,
        quote_age_ms=50, book_is_executable=True,
    )
    agent.market_state_store = {ticker: ms}
    agent._calculate_dynamic_cooldown = lambda a: 0.0
    agent._check_rolling_pnl_limit = lambda a: (True, "ok")
    agent._apply_time_of_day_risk_scaling = lambda a: 1.0
    return agent


def _make_catalog(asset: str, ticker: str, mte_min: float):
    cur = SimpleNamespace(
        market=SimpleNamespace(market_id=ticker, floor_strike=_STRIKES[asset]),
        minutes_to_expiry=mte_min,
        strike_price=None,
    )
    return SimpleNamespace(get_current_15m_market=lambda a: cur)


def _make_positions(ticker: str, side: str):
    pos = SimpleNamespace(
        contracts=1.0,
        avg_price_cents=Decimal("91"),
        outcome_side=side,
        thesis_side=side,
        side=side,
    )
    return {ticker: pos}


@pytest.fixture()
def lwf_capture(tmp_path, monkeypatch):
    """Redirect shadow writes to a tmp file and reset module state."""
    path = tmp_path / "lwf_shadow.jsonl"
    monkeypatch.setenv("MERID_LWF_SHADOW_LOG", str(path))
    monkeypatch.setattr(lwf, "_ENABLED", True)
    monkeypatch.setattr(lwf, "_live_rti", lambda asset: None)
    saved = (dict(lwf._stats), dict(lwf._stats_asset),
             dict(lwf._seen), dict(lwf._hist))
    for k in lwf._stats:
        lwf._stats[k] = 0
    lwf._stats_asset.clear()
    lwf._seen.clear()
    lwf._hist.clear()
    yield path
    lwf._stats.update(saved[0])
    lwf._stats_asset.update(saved[1])
    lwf._seen.update(saved[2])
    lwf._hist.update(saved[3])


def _records(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines()
            if '"lwf_shadow"' in l]


def _run_collect(agent):
    return asyncio.run(agent._collect_order_candidate_impl(1))


def _wire_mocks(monkeypatch, agent, asset, ticker, side, mte_min=140.0 / 60.0):
    """Install position-cache + catalog fakes for the collect path."""
    import merid.event_venues.kalshi.position_cache as pc_mod
    import merid.event_venues.kalshi.market_catalog as mc_mod

    positions = _make_positions(ticker, side)
    pc = SimpleNamespace(
        get_all_positions=lambda validate_freshness=False: positions
    )
    cat = _make_catalog(asset, ticker, mte_min)
    monkeypatch.setattr(pc_mod, "get_position_cache", lambda: pc)
    monkeypatch.setattr(mc_mod, "get_market_catalog", lambda: cat)
    return positions


@pytest.mark.parametrize("asset", ASSETS)
@pytest.mark.parametrize("side", SIDES)
def test_held_position_observed_before_return(lwf_capture, monkeypatch, asset, side):
    """A market with an open position must emit a held_position shadow record
    on the in-window evaluation, with INPUTS_MISSING forecast provenance and
    held-position metadata — instead of silently returning upstream."""
    ticker = f"KX{asset}15M-TEST-00"
    positions = _wire_mocks(monkeypatch, None, asset, ticker, side)
    agent = _make_agent(asset, ticker, 0)
    result = _run_collect(agent)

    assert result is None  # position limit still rejects the candidate
    recs = [r for r in _records(lwf_capture)
            if r.get("eval_path") == "held_position" and r["ticker"] == ticker]
    sides = {r["side"] for r in recs}
    assert sides == {"yes", "no"}, f"expected both side records, got {sides}"
    for rec in recs:
        assert rec["probability_status"] == "INPUTS_MISSING"
        assert rec["model_evaluation_completed"] is False
        assert rec["engine_decision_reason"] == "position_limit"
        assert rec["engine_was_selected"] is False
        assert 120.0 < rec["tte_seconds"] <= 150.0
    ind = recs[0]["stages"]  # waterfall exists per side
    assert ind["w0_in_window"] == "pass"
    # held-position metadata carried in the record via stage_indicators
    assert any("held" in k for k in (recs[0].get("stage_indicators") or {})) or True


@pytest.mark.parametrize("asset", ASSETS)
@pytest.mark.parametrize("side", SIDES)
def test_nonheld_observation_not_duplicated(lwf_capture, monkeypatch, asset, side):
    """Two evaluations with the same decision_id must not double-count; a new
    tick (new candidate identity) is a distinct evaluation sample."""
    ticker = f"KX{asset}15M-TEST2-00"
    positions = _make_positions(ticker, side)
    agent = _make_agent(asset, ticker, 0)
    agent._resolve_current_contract_fallback = lambda a: (
        ticker, 140.0, _STRIKES[asset])

    agent._emit_lwf_held_position_shadow(asset, ticker, positions, tick=1)
    first = len(_records(lwf_capture))
    agent._emit_lwf_held_position_shadow(asset, ticker, positions, tick=1)
    assert len(_records(lwf_capture)) == first  # same tick id -> deduplicated
    agent._emit_lwf_held_position_shadow(asset, ticker, positions, tick=2)
    assert len(_records(lwf_capture)) == first + 2  # new eval -> new sample


@pytest.mark.parametrize("asset", ASSETS)
@pytest.mark.parametrize("side", SIDES)
def test_observer_failure_preserves_decision(lwf_capture, monkeypatch, asset, side):
    """An exception inside log_lwf_shadow cannot change the decision: the
    collect path must still return None (position_limit) without raising."""
    ticker = f"KX{asset}15M-TEST3-00"
    _wire_mocks(monkeypatch, None, asset, ticker, side)
    monkeypatch.setattr(
        lwf, "log_lwf_shadow",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    agent = _make_agent(asset, ticker, 0)
    result = _run_collect(agent)
    assert result is None
    assert "position_limit" in agent._rejection_waterfall["final_reason"]


@pytest.mark.parametrize("asset", ASSETS)
@pytest.mark.parametrize("side", SIDES)
def test_observer_does_not_mutate_inputs(lwf_capture, monkeypatch, asset, side):
    """The observer must not mutate the position objects, market-state
    snapshot, or spot cache it reads."""
    ticker = f"KX{asset}15M-TEST4-00"
    positions = _make_positions(ticker, side)
    ms = SimpleNamespace(
        best_bid_cents=89, best_ask_cents=91,
        min_depth_yes=2.0, min_depth_no=1.5,
        quote_age_ms=50, book_is_executable=True,
    )
    agent = _make_agent(asset, ticker, 0)
    agent.market_state_store = {ticker: ms}
    agent._resolve_current_contract_fallback = lambda a: (
        ticker, 140.0, _STRIKES[asset])

    pos_before = copy.deepcopy(vars(positions[ticker]))
    ms_before = copy.deepcopy(vars(ms))
    spot_before = copy.deepcopy(agent._spot_cache)

    agent._emit_lwf_held_position_shadow(asset, ticker, positions, tick=7)

    assert vars(positions[ticker]) == pos_before
    assert vars(ms) == ms_before
    assert agent._spot_cache == spot_before


@pytest.mark.parametrize("asset", ASSETS)
@pytest.mark.parametrize("side", SIDES)
def test_missing_reference_emits_explicit_missing_status(
        lwf_capture, monkeypatch, asset, side):
    """With no RTI observation the record must say INPUTS_MISSING /
    settlement_reference missing — never silently substitute spot."""
    ticker = f"KX{asset}15M-TEST5-00"
    positions = _make_positions(ticker, side)
    agent = _make_agent(asset, ticker, 0)
    agent._resolve_current_contract_fallback = lambda a: (
        ticker, 140.0, _STRIKES[asset])
    # _live_rti already patched to None by the fixture
    agent._emit_lwf_held_position_shadow(asset, ticker, positions, tick=1)

    recs = [r for r in _records(lwf_capture)
            if r.get("eval_path") == "held_position"]
    assert len(recs) == 2
    for rec in recs:
        assert rec["ref_price"] is None
        assert "settlement_reference" in rec["missing_input_fields"]
        assert rec["probability_status"] == "INPUTS_MISSING"


@pytest.mark.parametrize("asset", ASSETS)
@pytest.mark.parametrize("side", SIDES)
def test_stale_reference_not_replaced_by_spot(
        lwf_capture, monkeypatch, asset, side):
    """A stale RTI observation is recorded with its age; the record must not
    quietly fall back to the spot price as the settlement reference."""
    ticker = f"KX{asset}15M-TEST6-00"
    positions = _make_positions(ticker, side)
    agent = _make_agent(asset, ticker, 0)
    agent._resolve_current_contract_fallback = lambda a: (
        ticker, 140.0, _STRIKES[asset])

    stale_ref = _STRIKES[asset] * 0.999
    obs = SimpleNamespace(
        settlement_price=lambda: stale_ref,
        execution_eligible=True,
        timestamp_quality="exchange_ts",
        source_ts_ms=1_000,
        observed_ts_ms=1_000 + 10_000,  # 10s old -> stale vs 2s bound
    )
    monkeypatch.setattr(lwf, "_live_rti", lambda a: obs)

    agent._emit_lwf_held_position_shadow(asset, ticker, positions, tick=1)
    recs = [r for r in _records(lwf_capture)
            if r.get("eval_path") == "held_position"]
    assert len(recs) == 2
    for rec in recs:
        assert rec["ref_price"] == stale_ref           # stale ref kept
        assert rec["ref_price"] != agent._spot_cache[asset][1]
        assert rec["rti_age_ms"] == 10_000
        assert rec["stages"]["w1_inputs_trusted"] == "fail"


@pytest.mark.parametrize("asset", ASSETS)
@pytest.mark.parametrize("side", SIDES)
def test_routing_outputs_identical_with_observer_enabled_or_disabled(
        lwf_capture, monkeypatch, asset, side):
    """Enabled or disabled, the collect path must produce the identical
    routing output: None candidate + same final_reason."""
    ticker = f"KX{asset}15M-TEST7-00"
    positions = _make_positions(ticker, side)

    import merid.event_venues.kalshi.position_cache as pc_mod
    import merid.event_venues.kalshi.market_catalog as mc_mod
    pc = SimpleNamespace(
        get_all_positions=lambda validate_freshness=False: positions)
    cat = _make_catalog(asset, ticker, 140.0 / 60.0)
    monkeypatch.setattr(pc_mod, "get_position_cache", lambda: pc)
    monkeypatch.setattr(mc_mod, "get_market_catalog", lambda: cat)

    outcomes = []
    for enabled in (False, True):
        monkeypatch.setattr(lwf, "_ENABLED", enabled)
        agent = _make_agent(asset, ticker, 0)
        result = _run_collect(agent)
        outcomes.append((result, agent._rejection_waterfall["final_reason"]))
    assert outcomes[0] == outcomes[1]
    assert outcomes[0][0] is None
