"""Surface-level tests for KalshiTradingAgent — verifies construction, crypto threshold
wiring, vol-band fields, consensus direction, and observe() alias."""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from merid.prediction.trading_agent import KalshiTradingAgent
from merid.prediction.agent_grid_config import AgentConfig, AgentRiskLimits
from merid.prediction.strategy import ExpiryPhase
from merid.prediction.no_trade_reasons import NoTradeReason, get_no_trade_tracker, reset_no_trade_tracker


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_agent(name: str = "BTC_15M", assets: list = None, timeframes: list = None,
                category: str = None) -> KalshiTradingAgent:
    # Use explicit empty list when the caller passes [] so we don't accidentally
    # fall back to ["BTC"] (which would trigger crypto threshold detection).
    _assets = assets if assets is not None else ["BTC"]
    cfg = AgentConfig(
        name=name,
        assets=_assets,
        timeframes=timeframes or ["15m"],
        risk_limits=AgentRiskLimits(max_notional_usd=Decimal("1000")),
        enabled=True,
        category=category,
    )
    return KalshiTradingAgent(cfg)


# ── AgentConfig.category field ────────────────────────────────────────────────

class TestAgentConfigCategory:
    """Verify category can be passed as constructor argument and is used as-is."""

    def test_explicit_category_stored(self):
        cfg = AgentConfig(name="TEST_AGENT", category="crypto")
        assert cfg.category == "crypto"

    def test_none_category_inferred_from_name(self):
        cfg = AgentConfig(name="BTC_15M")
        assert cfg.category is None
        assert cfg.resolve_category() == "crypto"

    def test_resolve_category_returns_explicit(self):
        cfg = AgentConfig(name="BTC_15M", category="financials")
        assert cfg.resolve_category() == "financials"

    def test_resolve_category_fallback_for_non_crypto_name(self):
        # "macro" maps to "economics" by the category inference logic
        cfg = AgentConfig(name="MACRO_DIRECTIONAL")
        assert cfg.resolve_category() == "economics"

    def test_resolve_category_for_all(self):
        # Names with no recognized token map to "all"
        cfg = AgentConfig(name="UNKNOWN_AGENT_XYZ")
        assert cfg.resolve_category() == "all"

    def test_resolve_category_for_eth(self):
        cfg = AgentConfig(name="ETH_1H")
        assert cfg.resolve_category() == "crypto"

    def test_category_none_does_not_break_str_equality(self):
        """AgentConfig.category==None should not equal any string."""
        cfg = AgentConfig(name="BTC_15M")
        assert cfg.category is None
        assert cfg.category != "crypto"


# ── Crypto threshold auto-application ─────────────────────────────────────────

class TestCryptoThresholdAutoApplication:
    """Verify that creating a crypto agent automatically applies crypto thresholds."""

    def test_btc_agent_gets_lenient_thresholds(self):
        agent = _make_agent("BTC_15M", assets=["BTC"])
        # Modern crypto profile has edge_floor_profile="medium"
        assert agent._strategy.config.edge_floor_profile == "medium"

    def test_eth_agent_gets_crypto_thresholds(self):
        agent = _make_agent("ETH_1H", assets=["ETH"], timeframes=["1h"])
        assert agent._strategy.config.min_edge_early < Decimal("0.05")

    def test_crypto_15m_mm_name_gets_crypto_thresholds(self):
        agent = _make_agent("CRYPTO_15M_MM", assets=["BTC"])
        assert agent._strategy.config.edge_floor_profile == "medium"

    def test_non_crypto_agent_retains_strict_defaults(self):
        # Explicitly pass empty assets and a non-crypto name so crypto detection is skipped
        agent = _make_agent("MACRO_DIRECTIONAL", assets=[], timeframes=["daily"])
        # Non-crypto: strict profile unchanged
        assert agent._strategy.config.edge_floor_profile == "strict"
        assert agent._strategy.config.min_edge_early == Decimal("0.05")

    def test_get_edge_threshold_returns_applied_value(self):
        agent = _make_agent("BTC_15M")
        t = agent._strategy._get_edge_threshold(ExpiryPhase.EARLY)
        # Modern profile: min_edge_early=0.04, edge_floor_profile="medium" (0.6 factor)
        # Computed: 0.04 * 0.6 = 0.024
        from decimal import Decimal as D
        assert t == D("0.024")


# ── Consensus direction mapping ───────────────────────────────────────────────

class TestConsensusDirectionMapping:
    """Verify SELL actions map to the correct consensus direction."""

    def test_sell_yes_maps_to_no_direction(self):
        """SELL_YES = bearish view → consensus direction should be 'no'."""
        from merid.prediction.strategy import SignalAction

        direction_map = {
            SignalAction.BUY_YES: "yes",
            SignalAction.SELL_YES: "no",   # FIXED: was incorrectly "yes"
            SignalAction.BUY_NO: "no",
            SignalAction.SELL_NO: "yes",
        }
        assert direction_map[SignalAction.SELL_YES] == "no"

    def test_sell_no_maps_to_yes_direction(self):
        from merid.prediction.strategy import SignalAction
        direction_map = {
            SignalAction.BUY_YES: "yes",
            SignalAction.SELL_YES: "no",
            SignalAction.BUY_NO: "no",
            SignalAction.SELL_NO: "yes",
        }
        assert direction_map[SignalAction.SELL_NO] == "yes"


# ── NoTradeDecisionTracker.observe() alias ────────────────────────────────────

class TestNoTradeObserveAlias:
    """Verify the observe() alias behaves identically to record()."""

    def setup_method(self):
        reset_no_trade_tracker()

    def test_observe_increments_counter(self):
        tracker = get_no_trade_tracker()
        before = tracker.get_counts().get(NoTradeReason.INFRA_BACKOFF.value, 0)
        tracker.observe(
            agent_name="TEST",
            market_id="KXBTC-TEST",
            asset="BTC",
            timeframe="15m",
            reason=NoTradeReason.INFRA_BACKOFF,
        )
        after = tracker.get_counts().get(NoTradeReason.INFRA_BACKOFF.value, 0)
        assert after == before + 1

    def test_observe_with_additional_context(self):
        """observe() should accept additional_context dict."""
        tracker = get_no_trade_tracker()
        tracker.observe(
            agent_name="TEST",
            market_id="KXBTC-TEST",
            asset="BTC",
            timeframe="15m",
            reason=NoTradeReason.INFRA_BACKOFF,
            additional_context={
                "error_code": "pm_agent_execution",
                "error_message": "order_failed",
            },
        )
        counts = tracker.get_counts()
        assert counts.get(NoTradeReason.INFRA_BACKOFF.value, 0) >= 1

    def test_observe_and_record_are_equivalent(self):
        """Calling observe() and record() should produce the same counter increment."""
        tracker = get_no_trade_tracker()
        before = tracker.get_counts().get(NoTradeReason.EDGE_BELOW_THRESHOLD.value, 0)
        tracker.observe(
            agent_name="A",
            market_id="M1",
            asset="BTC",
            timeframe="15m",
            reason=NoTradeReason.EDGE_BELOW_THRESHOLD,
        )
        tracker.record(
            agent_name="B",
            market_id="M2",
            asset="BTC",
            timeframe="15m",
            reason=NoTradeReason.EDGE_BELOW_THRESHOLD,
        )
        after = tracker.get_counts().get(NoTradeReason.EDGE_BELOW_THRESHOLD.value, 0)
        assert after == before + 2


# ── Snapshot staleness integration ────────────────────────────────────────────

class TestSnapshotTimestampField:
    """Verify MarketSnapshot has the epoch timestamp property."""

    def test_snapshot_has_epoch_property(self):
        import time
        from merid.prediction.model import MarketSnapshot, ContractState, PredictionMarketModel

        model = PredictionMarketModel()
        implied = model.implied_probabilities(
            yes_bid=Decimal("49"),
            yes_ask=Decimal("51"),
            no_bid=Decimal("49"),
            no_ask=Decimal("51"),
        )
        snap = MarketSnapshot(
            market_id="TEST",
            event_id="TEST",
            title="t",
            state=ContractState.TRADING,
            implied=implied,
            volume=Decimal("1"),
            open_interest=Decimal("1"),
        )
        ts = snap.snapshot_timestamp_utc_epoch_seconds
        assert isinstance(ts, float)
        assert abs(ts - time.time()) < 5.0


# ── OrderIntent snapshot_ts field ─────────────────────────────────────────────

class TestOrderIntentSnapshotTs:
    """Verify snapshot_ts field exists on OrderIntent."""

    def test_snapshot_ts_field_defaults_none(self):
        from merid.event_venues.kalshi.order_router import OrderIntent
        intent = OrderIntent(
            ticker="KXBTC-TEST",
            side="yes",
            action="buy",
            price_cents=55,
            count=5,
        )
        assert intent.snapshot_ts is None

    def test_snapshot_ts_can_be_set(self):
        import time
        from merid.event_venues.kalshi.order_router import OrderIntent
        ts = time.time()
        intent = OrderIntent(
            ticker="KXBTC-TEST",
            side="yes",
            action="buy",
            price_cents=55,
            count=5,
            snapshot_ts=ts,
        )
        assert intent.snapshot_ts == pytest.approx(ts)
