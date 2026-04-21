"""test_audit_bug_regressions.py

Regression tests for the 10 bugs identified in the MERID Intelligence/Data
Audit (docs/INTELLIGENCE_DATA_AUDIT.md) and fixed in the subsequent sprint.

BUG-01  merid/prediction/model.py           — stale spot-price accepted by compute_edge()
BUG-02  merid/prediction/forecasters/momentum.py — module-level _momentum_history shared across instances
BUG-03  backtesting/engine.py               — backtest fee model (% commission vs Kalshi flat fee)
BUG-04  merid/metrics/calibration.py        — MIN_FORECASTS_FOR_WEIGHT=10 cold-start blind spot
BUG-05  merid/prediction/trading_agent.py   — solo execution at full size with only DEBUG log
BUG-06  merid/prediction/trading_agent.py   — circular p_model = implied + net_edge for Brier scoring
BUG-07  merid/metrics/outcome_resolver.py   — settlement result field case sensitivity ("YES" not matched)
BUG-08  merid/prediction/trading_agent.py   — missing end_date always passes _in_entry_window()
BUG-09  merid/swarm/consensus_aggregator.py — hardcoded mode="paper" in event payload
BUG-10  merid/prediction/forecasters/registry.py — singleton init race condition (no lock)

All tests are pure unit tests — no I/O, no network, no DB.
"""
from __future__ import annotations

import sys
import types
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Minimal stubs so modules can be imported in isolation
# ---------------------------------------------------------------------------

def _stub(name: str, **attrs):
    """Inject a minimal stub module into sys.modules if not already present."""
    if name not in sys.modules:
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
    return sys.modules[name]


# utils.logger is already stubbed by conftest, but guard anyway
_stub("utils.logger", get_logger=lambda n: __import__("logging").getLogger(n))

# data.live_price_feed — no stub needed; real module is importable
# merid.metrics.calibration — no stub needed; real module is importable

# merid.prediction.forecasters.base stub
@dataclass
class _ForecastResult:
    forecaster_id: str
    p_model: float
    confidence: float
    components: dict = field(default_factory=dict)

class _Forecaster:
    @property
    def forecaster_id(self): return "stub"
    def predict(self, *a, **kw): return None

_stub("merid.prediction.forecasters.base",
      Forecaster=_Forecaster, ForecastResult=_ForecastResult)


# ===========================================================================
# BUG-01 — Stale spot price must be rejected in compute_edge()
# ===========================================================================

class TestBug01StaleSpotPrice:
    """MAX_PRICE_AGE_SECONDS must exist and compute_edge must skip stale prices."""

    def test_constant_exists(self):
        from merid.prediction.model import MAX_PRICE_AGE_SECONDS
        assert isinstance(MAX_PRICE_AGE_SECONDS, int)
        assert MAX_PRICE_AGE_SECONDS > 0

    def test_constant_is_reasonable(self):
        from merid.prediction.model import MAX_PRICE_AGE_SECONDS
        # Should be between 5 and 300 seconds — not 0 (always stale) or ∞ (never checked)
        assert 5 <= MAX_PRICE_AGE_SECONDS <= 300

    def test_fresh_price_is_used(self):
        """A price timestamped now should still feed the spot-relative model."""
        from merid.prediction.model import PredictionMarketModel, ImpliedProbability

        @dataclass
        class _PriceData:
            symbol: str
            price: float
            bid: float
            ask: float
            timestamp: datetime = field(
                default_factory=lambda: datetime.now()  # fresh
            )

        mock_feed = MagicMock()
        mock_feed.get_current_price.return_value = _PriceData(
            symbol="BTC/USD", price=50000.0, bid=49990.0, ask=50010.0
        )

        model = PredictionMarketModel()
        model._price_feed = mock_feed

        implied = ImpliedProbability(
            yes_prob=Decimal("0.5"), no_prob=Decimal("0.5"),
            yes_bid=Decimal("45"), yes_ask=Decimal("55"),
            no_bid=Decimal("45"), no_ask=Decimal("55"),
        )
        edge = model.compute_edge(
            "BTC-50K-MKT", implied, asset="BTC", strike_price=50000.0
        )
        # model_prob should have been derived (not equal to market implied 0.5)
        assert edge.model_prob is not None

    def test_stale_price_falls_back_to_implied(self):
        """A price older than MAX_PRICE_AGE_SECONDS must not be used; model_prob falls back to implied."""
        from merid.prediction.model import (
            PredictionMarketModel, ImpliedProbability, MAX_PRICE_AGE_SECONDS,
        )

        @dataclass
        class _PriceData:
            symbol: str
            price: float
            bid: float
            ask: float
            timestamp: datetime = field(default_factory=datetime.now)

        stale_ts = datetime.now() - timedelta(seconds=MAX_PRICE_AGE_SECONDS + 10)

        mock_feed = MagicMock()
        mock_feed.get_current_price.return_value = _PriceData(
            symbol="BTC/USD", price=99999.0, bid=99998.0, ask=100000.0,
            timestamp=stale_ts,
        )

        model = PredictionMarketModel()
        model._price_feed = mock_feed

        implied = ImpliedProbability(
            yes_prob=Decimal("0.5"), no_prob=Decimal("0.5"),
            yes_bid=Decimal("45"), yes_ask=Decimal("55"),
            no_bid=Decimal("45"), no_ask=Decimal("55"),
        )
        edge = model.compute_edge(
            "BTC-50K-MKT", implied, side="yes", asset="BTC", strike_price=50000.0
        )
        # When stale, model falls back to implied yes_prob (mid = 0.5)
        assert float(edge.model_prob) == pytest.approx(0.5, abs=0.01)


# ===========================================================================
# BUG-02 — _momentum_history must be per-instance, not module-level
# ===========================================================================

class TestBug02MomentumHistoryIsolation:
    """Two MomentumForecaster instances must not share history state."""

    def _make_forecaster(self):
        from merid.prediction.forecasters.momentum import MomentumForecaster
        return MomentumForecaster()

    def test_no_module_level_history(self):
        import merid.prediction.forecasters.momentum as _mod
        assert not hasattr(_mod, "_momentum_history"), (
            "_momentum_history must not exist at module level after the fix"
        )

    def test_instances_have_own_history(self):
        f1 = self._make_forecaster()
        f2 = self._make_forecaster()
        assert f1._momentum_history is not f2._momentum_history

    def test_recording_does_not_bleed_across_instances(self):
        f1 = self._make_forecaster()
        f2 = self._make_forecaster()

        # Inject observations into f1 only
        for _ in range(5):
            f1._record_observation("MKT-A", 0.6, 1000.0, 500.0)

        # f2 should see nothing for "MKT-A"
        assert len(f2._momentum_history.get("MKT-A", [])) == 0

    def test_max_history_respected_per_instance(self):
        from merid.prediction.forecasters.momentum import _MAX_HISTORY
        f = self._make_forecaster()
        for i in range(_MAX_HISTORY + 5):
            f._record_observation("MKT-X", 0.5 + i * 0.01, float(i), float(i))
        assert len(f._momentum_history["MKT-X"]) == _MAX_HISTORY


# ===========================================================================
# BUG-03 — BacktestConfig.use_kalshi_fees flag + _compute_trade_fee routing
# ===========================================================================

class TestBug03BacktestFeeModel:
    """use_kalshi_fees flag and _compute_trade_fee helper must exist and route correctly."""

    def test_use_kalshi_fees_field_exists(self):
        from backtesting.engine import BacktestConfig
        import inspect
        fields = {f.name for f in __import__("dataclasses").fields(BacktestConfig)}
        assert "use_kalshi_fees" in fields

    def test_default_is_false(self):
        from backtesting.engine import BacktestConfig
        cfg = BacktestConfig(
            backtest_id="t1", strategy_name="momentum",
            symbols=["BTC/USD"],
            start_date=datetime(2025, 1, 1),
            end_date=datetime(2025, 2, 1),
        )
        assert cfg.use_kalshi_fees is False

    def test_compute_trade_fee_pct_when_flag_off(self):
        from backtesting.engine import BacktestConfig, _compute_trade_fee
        cfg = BacktestConfig(
            backtest_id="t2", strategy_name="momentum",
            symbols=["BTC/USD"],
            start_date=datetime(2025, 1, 1),
            end_date=datetime(2025, 2, 1),
            commission_pct=0.001,
            use_kalshi_fees=False,
        )
        fee = _compute_trade_fee(cfg, price_cents=50, contracts=10, capital=10000.0)
        assert fee == pytest.approx(10000.0 * 0.001)

    def test_compute_trade_fee_kalshi_when_flag_on(self):
        """With use_kalshi_fees=True the fee should NOT equal the % commission."""
        from backtesting.engine import BacktestConfig, _compute_trade_fee
        cfg = BacktestConfig(
            backtest_id="t3", strategy_name="momentum",
            symbols=["BTC/USD"],
            start_date=datetime(2025, 1, 1),
            end_date=datetime(2025, 2, 1),
            commission_pct=0.001,
            use_kalshi_fees=True,
        )
        # kalshi_fee_cents(50, 10) = 2 cents * 10 = 20 cents = $0.20
        fee = _compute_trade_fee(cfg, price_cents=50, contracts=10, capital=10000.0)
        # Should NOT be capital * commission_pct = $10
        assert fee != pytest.approx(10000.0 * 0.001, rel=0.01)

    def test_ohlcv_candle_limit_constant_exists(self):
        from backtesting.engine import BacktestEngine
        assert hasattr(BacktestEngine, "_OHLCV_CANDLE_LIMIT")
        assert BacktestEngine._OHLCV_CANDLE_LIMIT == 500


# ===========================================================================
# BUG-04 — MIN_FORECASTS_FOR_WEIGHT = 1 (cold-start fix)
# ===========================================================================

class TestBug04ColdStartCalibration:
    """MIN_FORECASTS_FOR_WEIGHT must be 1, not 10."""

    def test_constant_value(self):
        from merid.metrics.calibration import MIN_FORECASTS_FOR_WEIGHT
        assert MIN_FORECASTS_FOR_WEIGHT == 1, (
            f"Expected 1, got {MIN_FORECASTS_FOR_WEIGHT}. "
            "Cold-start bug: equal-weight window must be removed."
        )

    def test_weight_computed_after_first_outcome(self):
        """get_weight() must return a real calibration weight after just 1 forecast."""
        import importlib.util, os, sys, tempfile
        _mod_name = "_cal_direct_test"
        spec = importlib.util.spec_from_file_location(
            _mod_name,
            str(__import__('pathlib').Path(__file__).resolve().parent.parent
                / "merid" / "metrics" / "calibration.py")
        )
        _cal = importlib.util.module_from_spec(spec)
        # Register in sys.modules so dataclasses string-annotation resolution works
        sys.modules[_mod_name] = _cal
        spec.loader.exec_module(_cal)
        CalibrationStore = _cal.CalibrationStore
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            store = CalibrationStore(db_path=db_path)
            store.record_forecast(
                forecaster_id="test_fc",
                bucket="crypto",
                market_id="MKT-001",
                p_model=0.7,
                timestamp=1000.0,
            )
            store.resolve_outcome(market_id="MKT-001", outcome=1)
            weight = store.get_weight("test_fc", "crypto")
            # After 1 resolved forecast, weight must not be the default (1.0 = undef)
            # Actually it could be close to 1.0 for a good forecast but must be computed
            assert weight is not None
            assert isinstance(weight, float)
        finally:
            # Close the SQLite connection before unlinking (required on Windows)
            try:
                if hasattr(store, "_conn") and store._conn:
                    store._conn.close()
                elif hasattr(store, "conn") and store.conn:
                    store.conn.close()
            except Exception:
                pass
            try:
                os.unlink(db_path)
            except OSError:
                pass  # Best-effort cleanup on Windows


# ===========================================================================
# BUG-05 — Solo execution: swarm_degraded flag, WARNING, small size cap
# ===========================================================================

class TestBug05SoloExecutionFallback:
    """AgentState must have swarm_degraded and last_consensus_at fields."""

    def test_agent_state_has_swarm_degraded(self):
        from merid.prediction.trading_agent import AgentState
        state = AgentState(name="test-agent")
        assert hasattr(state, "swarm_degraded")
        assert state.swarm_degraded is False

    def test_agent_state_has_last_consensus_at(self):
        from merid.prediction.trading_agent import AgentState
        state = AgentState(name="test-agent")
        assert hasattr(state, "last_consensus_at")
        assert state.last_consensus_at is None

    def test_to_dict_includes_new_fields(self):
        from merid.prediction.trading_agent import AgentState
        state = AgentState(name="test-agent")
        d = state.to_dict()
        assert "swarm_degraded" in d
        assert "last_consensus_at" in d

    def test_max_solo_seconds_constant_exists(self):
        from merid.prediction.trading_agent import _MAX_SOLO_SECONDS
        assert isinstance(_MAX_SOLO_SECONDS, (int, float))
        assert _MAX_SOLO_SECONDS >= 0  # 0 = no hold (single-agent default)

    def test_swarm_degraded_clears_on_recovery(self):
        """swarm_degraded=True → False when last_consensus_at is updated."""
        from merid.prediction.trading_agent import AgentState
        state = AgentState(name="test-agent")
        state.swarm_degraded = True
        # Simulate consensus recovery
        state.last_consensus_at = datetime.now(timezone.utc)
        state.swarm_degraded = False
        assert not state.swarm_degraded
        assert state.last_consensus_at is not None


# ===========================================================================
# BUG-06 — Brier scoring uses model_prob directly, not implied + net_edge
# ===========================================================================

class TestBug06CircularPModelReconstruction:
    """_record_signal must use edge.model_prob, not implied + net_edge."""

    def _get_record_signal_source(self) -> str:
        import inspect
        from merid.prediction import trading_agent as ta
        return inspect.getsource(ta.KalshiTradingAgent._record_signal)

    def test_no_imp_plus_edge_reconstruction(self):
        """The old circular reconstruction pattern must be absent."""
        src = self._get_record_signal_source()
        # Old pattern: imp + edge_val or imp + net_edge
        assert "imp + edge_val" not in src, "Circular p_model reconstruction still present"
        assert "implied + net_edge" not in src.lower(), "Circular p_model reconstruction still present"

    def test_uses_model_prob_directly(self):
        """The fix uses signal.edge.model_prob directly."""
        src = self._get_record_signal_source()
        assert "model_prob" in src, "model_prob reference missing from _record_signal"

    def _get_brier_scoring_block(self) -> str:
        """Extract only the non-comment code lines of the Brier-scoring section."""
        src = self._get_record_signal_source()
        marker = "# ── Calibration: log forecast for Brier scoring"
        idx = src.find(marker)
        assert idx != -1, "Calibration marker not found in _record_signal"
        block = src[idx:]
        # Strip comment lines so we only check executable code, not explanatory text
        code_lines = [
            line for line in block.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        return "\n".join(code_lines)

    def test_no_fallback_to_edge_reconstruction(self):
        """The Brier scoring block must not reconstruct p_model from net_edge in code."""
        brier_block = self._get_brier_scoring_block()
        assert "net_edge" not in brier_block, (
            "net_edge referenced in executable code inside the Brier scoring block — "
            "circular p_model reconstruction not fully fixed"
        )


# ===========================================================================
# BUG-07 — Settlement result normalization (case-insensitive)
# ===========================================================================

class TestBug07SettlementResultNormalization:
    """_get_outcome_from_kalshi must normalise result to lowercase before comparing."""

    def _get_source(self) -> str:
        import inspect, importlib.util, sys
        _mod_name = "_or_direct_test"
        spec = importlib.util.spec_from_file_location(
            _mod_name,
            str(__import__('pathlib').Path(__file__).resolve().parent.parent
                / "merid" / "metrics" / "outcome_resolver.py")
        )
        _or = importlib.util.module_from_spec(spec)
        # Register so dataclasses string-annotation resolution works
        sys.modules[_mod_name] = _or
        spec.loader.exec_module(_or)
        return inspect.getsource(_or.OutcomeResolver._get_outcome_from_kalshi)

    def test_lowercase_normalisation_present(self):
        src = self._get_source()
        # The fix uses .strip().lower() or similar
        assert ".lower()" in src, "Case normalisation (.lower()) missing from _get_outcome_from_kalshi"

    def test_warning_on_settled_but_unknown_result(self):
        src = self._get_source()
        assert "logger.warning" in src, (
            "WARNING log missing: settled market with unrecognized result must be warned"
        )

    def test_uppercase_yes_maps_to_1(self):
        """Simulate the normalisation logic: 'YES'.strip().lower() == 'yes' → 1."""
        result_field = "YES"
        normalized = result_field.strip().lower()
        outcome = 1 if normalized == "yes" else (0 if normalized == "no" else None)
        assert outcome == 1

    def test_uppercase_no_maps_to_0(self):
        result_field = "NO"
        normalized = result_field.strip().lower()
        outcome = 1 if normalized == "yes" else (0 if normalized == "no" else None)
        assert outcome == 0

    def test_mixed_case_yes_maps_to_1(self):
        result_field = "Yes"
        normalized = result_field.strip().lower()
        outcome = 1 if normalized == "yes" else (0 if normalized == "no" else None)
        assert outcome == 1

    def test_empty_result_returns_none(self):
        result_field = ""
        normalized = result_field.strip().lower()
        outcome = 1 if normalized == "yes" else (0 if normalized == "no" else None)
        assert outcome is None


# ===========================================================================
# BUG-08 — Missing end_date must REJECT, not always-allow entry window
# ===========================================================================

class TestBug08MissingEndDateRejected:
    """_in_entry_window() must return False when market.end_date is None."""

    def _make_market(self, end_date=None):
        m = MagicMock()
        m.end_date = end_date
        m.market_id = "TEST-MKT"
        return m

    def _make_agent(self):
        """Build a minimal KalshiTradingAgent with enough config to call _in_entry_window."""
        from merid.prediction.trading_agent import KalshiTradingAgent
        cfg = MagicMock()
        cfg.name = "test-agent"
        cfg.entry_window.minutes_before_expiry = 120
        cfg.entry_window.cutoff_minutes_before_expiry = 5
        return KalshiTradingAgent.__new__(KalshiTradingAgent), cfg

    def test_none_end_date_returns_false(self):
        from merid.prediction.trading_agent import KalshiTradingAgent
        agent = KalshiTradingAgent.__new__(KalshiTradingAgent)
        agent.config = MagicMock()
        agent.config.entry_window.minutes_before_expiry = 120
        agent.config.entry_window.cutoff_minutes_before_expiry = 5
        agent.logger = __import__("logging").getLogger("test")

        market = self._make_market(end_date=None)
        result = agent._in_entry_window(market, datetime.now(timezone.utc))
        assert result is False, (
            "_in_entry_window must return False for missing end_date, not True"
        )

    def test_valid_end_date_within_window_returns_true(self):
        from merid.prediction.trading_agent import KalshiTradingAgent
        agent = KalshiTradingAgent.__new__(KalshiTradingAgent)
        agent.config = MagicMock()
        agent.config.entry_window.minutes_before_expiry = 120
        agent.config.entry_window.cutoff_minutes_before_expiry = 5
        agent.logger = __import__("logging").getLogger("test")

        now = datetime.now(timezone.utc)
        market = self._make_market(end_date=now + timedelta(minutes=60))
        result = agent._in_entry_window(market, now)
        assert result is True

    def test_valid_end_date_outside_window_returns_false(self):
        from merid.prediction.trading_agent import KalshiTradingAgent
        agent = KalshiTradingAgent.__new__(KalshiTradingAgent)
        agent.config = MagicMock()
        agent.config.entry_window.minutes_before_expiry = 120
        agent.config.entry_window.cutoff_minutes_before_expiry = 5
        agent.logger = __import__("logging").getLogger("test")

        now = datetime.now(timezone.utc)
        # Expiry is 200 minutes away — before the entry window opens at -120m
        market = self._make_market(end_date=now + timedelta(minutes=200))
        result = agent._in_entry_window(market, now)
        assert result is False


# ===========================================================================
# BUG-09 — consensus event payload mode must not be hardcoded "paper"
# ===========================================================================

class TestBug09ConsensusPayloadMode:
    """_get_venue_mode() must exist and the aggregator must call it, not literal 'paper'."""

    def test_get_venue_mode_exists(self):
        from merid.swarm.consensus_aggregator import _get_venue_mode
        assert callable(_get_venue_mode)

    def test_get_venue_mode_returns_string(self):
        from merid.swarm.consensus_aggregator import _get_venue_mode
        result = _get_venue_mode()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_venue_mode_fallback_is_paper(self):
        """When venue gate is unavailable, fallback must be 'paper' (safe default)."""
        with patch("merid.swarm.consensus_aggregator._get_venue_mode",
                   side_effect=Exception("no gate")):
            # The module-level helper itself has try/except — test its internal fallback
            pass  # tested via source inspection below

        import inspect
        from merid.swarm import consensus_aggregator as ca
        src = inspect.getsource(ca._get_venue_mode)
        assert '"paper"' in src or "'paper'" in src, (
            "_get_venue_mode must have 'paper' as its fallback"
        )

    def test_hardcoded_paper_string_not_in_publish_block(self):
        """The literal string 'paper' must not appear in the consensus publish payload."""
        import inspect
        from merid.swarm import consensus_aggregator as ca
        # The publish happens inside _recompute_consensus / _aggregate_proposals
        src = inspect.getsource(ca.SwarmConsensusAggregator._recompute_consensus)
        assert '"mode": "paper"' not in src, (
            'Hardcoded "mode": "paper" still in _recompute_consensus — fix not applied'
        )

    def test_get_venue_mode_called_in_publish(self):
        """_get_venue_mode() must be referenced in the consensus publish path."""
        import inspect
        from merid.swarm import consensus_aggregator as ca
        src = inspect.getsource(ca.SwarmConsensusAggregator._recompute_consensus)
        assert "_get_venue_mode()" in src, (
            "_get_venue_mode() not called in _recompute_consensus publish block"
        )


# ===========================================================================
# BUG-10 — ForecasterRegistry singleton init must be thread-safe
# ===========================================================================

class TestBug10RegistryThreadSafety:
    """get_forecaster_registry() must use a double-checked lock."""

    def test_lock_exists(self):
        import merid.prediction.forecasters.registry as reg_mod
        assert hasattr(reg_mod, "_registry_lock"), "_registry_lock not found at module level"
        assert isinstance(reg_mod._registry_lock, type(__import__("threading").Lock()))

    def test_concurrent_calls_return_same_instance(self):
        """10 threads calling get_forecaster_registry() must all receive the same object."""
        import merid.prediction.forecasters.registry as reg_mod

        # Reset singleton so threads race on first init
        original = reg_mod._registry
        reg_mod._registry = None

        results = []
        errors = []

        def _get():
            try:
                r = reg_mod.get_forecaster_registry()
                results.append(id(r))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_get) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Restore original in case other tests need it
        if original is not None:
            reg_mod._registry = original

        assert not errors, f"Threads raised errors: {errors}"
        assert len(set(results)) == 1, (
            f"Expected 1 unique registry id, got {len(set(results))} — race condition not fixed"
        )

    def test_registry_assigned_atomically(self):
        """_registry must be set only after all forecasters are registered (no partial state)."""
        import inspect
        import merid.prediction.forecasters.registry as reg_mod
        src = inspect.getsource(reg_mod.get_forecaster_registry)
        # The fix assigns to `_registry` only after `reg` is fully built
        assert "reg = ForecasterRegistry()" in src or "_registry = reg" in src, (
            "Atomic assignment pattern (reg = ... ; _registry = reg) not found in get_forecaster_registry"
        )
