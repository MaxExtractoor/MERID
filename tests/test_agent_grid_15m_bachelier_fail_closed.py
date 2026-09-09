"""Fail-closed regressions for the Bachelier/settlement input path.

Covers:
- ``_get_bachelier_spot_price`` must not silently reuse the lagged 60-second
  CF RTI average when the live observation is missing a valid latest tick.
- ``_generate_trade_decision_signal`` must refuse new entries when
  ``MERID_SETTLEMENT_DISTRIBUTION_V2`` is enabled but the settlement-aware
  distribution cannot be built, instead of silently falling back to the
  point-Bachelier path.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest


def _obs(value=None, execution_eligible=True):
    try:
        value_decimal = Decimal(str(value)) if value is not None else None
    except Exception:
        value_decimal = None
    obs = SimpleNamespace(
        value=value,
        value_decimal=value_decimal,
        execution_eligible=execution_eligible,
        source_ts_ms=1_700_000_000_000,
        timestamp_quality="good",
    )
    return obs


class TestBachelierSpot:
    def test_returns_latest_tick_when_eligible(self):
        from merid.prediction.agent_grid_15m import _get_bachelier_spot_price

        obs = _obs(value=65000.25)
        assert _get_bachelier_spot_price(obs, 64999.0) == pytest.approx(65000.25)

    def test_live_obs_without_latest_tick_returns_none(self):
        """A live (execution-eligible) RTI observation whose latest tick is
        missing or invalid must not fall back to the 60-second average."""
        from merid.prediction.agent_grid_15m import _get_bachelier_spot_price

        for bad in (None, 0.0, -1.0, float("nan"), float("inf"), "bad"):
            obs = _obs(value=bad)
            assert _get_bachelier_spot_price(obs, 64999.0) is None, f"value={bad!r}"

    def test_unavailable_rti_rejects_bachelier_spot(self):
        """When RTI is missing or ineligible, _get_bachelier_spot_price fails
        closed; the public spot is intentionally not used as the Bachelier spot."""
        from merid.prediction.agent_grid_15m import _get_bachelier_spot_price

        assert _get_bachelier_spot_price(None, 64000.0) is None
        assert _get_bachelier_spot_price(_obs(value=65000.0, execution_eligible=False), 64000.0) is None


def _make_agent():
    rejections = []

    agent = SimpleNamespace()
    agent.market_state_store = None
    agent.run_id = "test_run"
    agent.config = SimpleNamespace(name="test", min_net_edge=None)
    agent.risk_config = SimpleNamespace(model_uncertainty=None, strategy_policy_min_edge=None)
    agent._last_signal_vol_context = {}
    agent._last_velocity_value = None
    agent._last_velocity_source = None
    agent._last_velocity_age_ms = None
    agent._last_velocity_signal_type = None
    agent._last_velocity_threshold = None
    agent._last_spot_data = {}
    agent._record_signal_rejection = lambda reason, **ctx: rejections.append((reason, ctx))
    agent._build_trade_decision_rejection_context = lambda *a, **k: dict(k.get("extra") or {})
    agent._classify_regime = lambda ticker: "normal"
    agent._resolve_runtime_signal_mode = lambda: "bachelier"
    agent._get_candles_available = lambda asset: 0
    return agent, rejections


def _make_market():
    expiry = datetime.now(timezone.utc) + timedelta(seconds=600)
    market = SimpleNamespace(
        market=SimpleNamespace(market_id="KXBTC15M-TEST", end_date=expiry),
        expires_at=expiry,
        settlement_digits=2,
        seconds_to_expiry=600.0,
        best_bid_cents=50.0,
        best_ask_cents=52.0,
        best_no_bid_cents=48.0,
        best_no_ask_cents=50.0,
        min_depth_yes=5.0,
        min_depth_no=5.0,
        data_quality="good",
        book_initialized=True,
        regime="normal",
    )
    return market


def _patch_strike_and_rti(monkeypatch, ag, obs, settlement_price=65000.5):
    monkeypatch.delenv("MERID_PAUSED_ASSETS", raising=False)
    monkeypatch.setattr(
        ag, "_resolve_trade_decision_strike",
        lambda asset, market_state, market, spot: (65050.0, "floor_strike", {}),
    )
    monkeypatch.setattr(
        ag, "_get_settlement_input_price",
        lambda asset, spot_price, settlement_digits=None: (
            settlement_price, 0.5, "cfb_rti_live", obs
        ),
    )
    # Tests target the settlement-distribution gate, not the snapshot-freshness
    # gate. Provide a valid snapshot so the decision flow reaches distribution.
    monkeypatch.setattr(
        ag, "validate_trade_snapshot",
        lambda **kwargs: [],
    )


def test_signal_rejects_entry_when_latest_rti_tick_missing(monkeypatch):
    import merid.prediction.agent_grid_15m as ag

    agent, rejections = _make_agent()
    _patch_strike_and_rti(monkeypatch, ag, _obs(value=None))

    result = ag.LeanAgent15m._generate_trade_decision_signal(
        agent, "BTC", 65000.0, _make_market(), 10.0, tick=0
    )

    assert result is None
    assert rejections and rejections[-1][0] == "cf_rti_latest_tick_invalid"


def test_settlement_v2_build_failure_blocks_entry(monkeypatch):
    """With V2 enabled, a distribution build failure must reject the entry
    rather than silently falling back to the point-Bachelier model."""
    import merid.prediction.agent_grid_15m as ag

    agent, rejections = _make_agent()
    _patch_strike_and_rti(monkeypatch, ag, _obs(value=65000.25))
    monkeypatch.setattr(ag, "MERID_SETTLEMENT_DISTRIBUTION_V2", True)
    monkeypatch.setattr(ag, "_SETTLEMENT_DISTRIBUTION_AVAILABLE", True)

    def _raise(*args, **kwargs):
        raise ValueError("Incomplete or inconsistent elapsed settlement samples")

    monkeypatch.setattr(ag, "compute_settlement_distribution", _raise)
    monkeypatch.setattr(ag, "build_settlement_state", lambda **kwargs: object())
    monkeypatch.setattr(
        ag, "_resolve_annualized_vol",
        lambda **kwargs: (kwargs["requested_vol"], "default", 0.05, 5.0, None),
    )
    import merid.data.cf_rti_adapter as cf
    monkeypatch.setattr(cf, "get_rti_history", lambda *a, **k: [])

    result = ag.LeanAgent15m._generate_trade_decision_signal(
        agent, "BTC", 65000.0, _make_market(), 10.0, tick=0
    )

    assert result is None
    assert rejections and rejections[-1][0] == "settlement_distribution_unavailable"


def test_settlement_v2_module_unavailable_blocks_entry(monkeypatch):
    """With V2 enabled but the module import missing, entries must be refused."""
    import merid.prediction.agent_grid_15m as ag

    agent, rejections = _make_agent()
    _patch_strike_and_rti(monkeypatch, ag, _obs(value=65000.25))
    monkeypatch.setattr(ag, "MERID_SETTLEMENT_DISTRIBUTION_V2", True)
    monkeypatch.setattr(ag, "_SETTLEMENT_DISTRIBUTION_AVAILABLE", False)

    result = ag.LeanAgent15m._generate_trade_decision_signal(
        agent, "BTC", 65000.0, _make_market(), 10.0, tick=0
    )

    assert result is None
    assert rejections and rejections[-1][0] == "settlement_distribution_unavailable"


def test_settlement_v2_off_skips_distribution(monkeypatch):
    """With V2 off (the live default), the distribution is never built and the
    legacy point-Bachelier path proceeds to the decision engine."""
    import merid.prediction.agent_grid_15m as ag

    agent, rejections = _make_agent()
    _patch_strike_and_rti(monkeypatch, ag, _obs(value=65000.25))
    monkeypatch.setattr(ag, "MERID_SETTLEMENT_DISTRIBUTION_V2", False)
    monkeypatch.setattr(ag, "_SETTLEMENT_DISTRIBUTION_AVAILABLE", False)

    calls = []
    monkeypatch.setattr(
        ag, "build_settlement_state",
        lambda **kwargs: calls.append(kwargs) or object(),
    )
    # Short-circuit at the real decision engine to prove the flow reached past
    # the distribution block without running the full pipeline.
    def _sentinel(**kwargs):
        raise RuntimeError("reached_trade_decision")
    monkeypatch.setattr(ag, "compute_trade_decision", _sentinel)
    agent._compute_hybrid_p_yes = lambda **kwargs: None

    with pytest.raises(RuntimeError, match="reached_trade_decision"):
        ag.LeanAgent15m._generate_trade_decision_signal(
            agent, "BTC", 65000.0, _make_market(), 10.0, tick=0
        )

    assert calls == []
    assert all(r[0] != "settlement_distribution_unavailable" for r in rejections)
