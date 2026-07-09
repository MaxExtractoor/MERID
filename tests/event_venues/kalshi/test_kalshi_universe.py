"""Tests for KalshiUniverse, infer_category, _get_underlying, and universal agent."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ────────────────────────────────────────────────────────────────

@dataclass
class _FakeMarket:
    market_id: str
    volume: int = 100
    open_interest: int = 50
    question: str = ""
    raw_data: Dict[str, Any] = field(default_factory=lambda: {"yes_bid": 40, "yes_ask": 60})


@dataclass
class _FakeCatalogMarket:
    market: _FakeMarket
    category: Optional[str] = None
    asset: Optional[str] = None
    timeframe: Optional[str] = None


def _make_cm(
    ticker: str,
    category: str = "crypto",
    asset: str = "BTC",
    volume: int = 200,
    bid: int = 45,
    ask: int = 55,
) -> _FakeCatalogMarket:
    return _FakeCatalogMarket(
        market=_FakeMarket(
            market_id=ticker,
            volume=volume,
            open_interest=100,
            raw_data={"yes_bid": bid, "yes_ask": ask},
        ),
        category=category,
        asset=asset,
    )


def _make_mock_catalog(markets: list) -> MagicMock:
    catalog = MagicMock()
    catalog.get_all_markets.return_value = markets
    catalog.get_markets_by_category.side_effect = (
        lambda cat, timeframe=None, asset=None: [
            m for m in markets if (m.category or "").lower() == cat.lower()
        ]
    )
    catalog.get_markets_by_asset.side_effect = (
        lambda asset, timeframe=None: [
            m for m in markets if (m.asset or "").upper() == asset.upper()
        ]
    )
    return catalog


# ══════════════════════════════════════════════════════════════════════════
# 1. infer_category
# ══════════════════════════════════════════════════════════════════════════

class TestInferCategory:
    def _fn(self):
        from merid.event_venues.kalshi.category_exposure import infer_category
        return infer_category

    def test_crypto_assets(self):
        fn = self._fn()
        for sym in ("BTC", "ETH", "SOL", "XRP", "DOGE", "AVAX", "ADA", "LTC", "PEPE"):
            assert fn(sym) == "crypto", sym

    def test_case_insensitive(self):
        fn = self._fn()
        assert fn("btc") == "crypto"
        assert fn("Eth") == "crypto"

    def test_economics(self):
        fn = self._fn()
        for sym in ("CPI", "GDP", "JOBS", "RATES"):
            assert fn(sym) == "economics", sym

    def test_financials(self):
        fn = self._fn()
        for sym in ("SPX", "NDX", "DJI", "RUT"):
            assert fn(sym) == "financials", sym

    def test_politics(self):
        fn = self._fn()
        for sym in ("ELECTION", "SENATE", "CONGRESS", "SCOTUS"):
            assert fn(sym) == "politics", sym

    def test_climate(self):
        fn = self._fn()
        for sym in ("WEATHER", "CLIMATE"):
            assert fn(sym) == "climate", sym

    def test_sports(self):
        fn = self._fn()
        for sym in ("NBA", "NFL", "MLB", "NHL", "MMA"):
            assert fn(sym) == "sports", sym

    def test_tech(self):
        fn = self._fn()
        for sym in ("AI", "NVDA", "AAPL", "META", "TECH"):
            assert fn(sym) == "tech", sym

    def test_unknown_returns_other(self):
        fn = self._fn()
        assert fn("ZZZZUNKNOWN") == "other"


# ══════════════════════════════════════════════════════════════════════════
# 2. _get_underlying
# ══════════════════════════════════════════════════════════════════════════

class TestGetUnderlying:
    def _fn(self):
        from merid.event_venues.kalshi.order_router import _get_underlying
        return _get_underlying

    def test_crypto_tickers(self):
        fn = self._fn()
        assert fn("KXBTC-23DEC-T30000") == "BTC"
        assert fn("KXETH-24JAN-T2000") == "ETH"
        assert fn("KXSOL-24MAR") == "SOL"
        assert fn("KXXRP-99") == "XRP"

    def test_macro_tickers(self):
        fn = self._fn()
        assert fn("KXCPI-2024DEC") == "CPI"

    def test_unknown_returns_other(self):
        fn = self._fn()
        assert fn("ZZZNOMATCH") == "OTHER"

    def test_case_insensitive(self):
        fn = self._fn()
        assert fn("kxbtc-99") == "BTC"


# ══════════════════════════════════════════════════════════════════════════
# 3. _DEFAULT_CATEGORY_CAPS — all categories present
# ══════════════════════════════════════════════════════════════════════════

class TestCategoryCaps:
    def test_all_categories_have_caps(self):
        from merid.event_venues.kalshi.category_exposure import _DEFAULT_CATEGORY_CAPS
        required = {
            "crypto", "economics", "macro", "financials", "politics",
            "climate", "sports", "tech", "culture", "science", "other",
        }
        missing = required - set(_DEFAULT_CATEGORY_CAPS.keys())
        assert not missing, f"Missing caps for: {missing}"

    def test_caps_are_positive(self):
        from merid.event_venues.kalshi.category_exposure import _DEFAULT_CATEGORY_CAPS
        for cat, cap in _DEFAULT_CATEGORY_CAPS.items():
            assert cap > 0, f"Cap for {cat} is not positive: {cap}"

    def test_crypto_underlyings_all_crypto(self):
        from merid.event_venues.kalshi.category_exposure import (
            _CRYPTO_UNDERLYINGS,
            _UNDERLYING_CATEGORY_MAP,
        )
        for sym in _CRYPTO_UNDERLYINGS:
            assert _UNDERLYING_CATEGORY_MAP[sym] == "crypto", sym


# ══════════════════════════════════════════════════════════════════════════
# 4. UniverseConfig
# ══════════════════════════════════════════════════════════════════════════

class TestUniverseConfig:
    def test_category_allowed_empty_whitelist(self):
        from merid.event_venues.kalshi.universe import UniverseConfig
        cfg = UniverseConfig()
        cfg.allowed_categories = []
        assert cfg.category_allowed("crypto") is True
        assert cfg.category_allowed("politics") is True

    def test_category_allowed_with_whitelist(self):
        from merid.event_venues.kalshi.universe import UniverseConfig
        cfg = UniverseConfig()
        cfg.allowed_categories = ["crypto", "sports"]
        assert cfg.category_allowed("crypto") is True
        assert cfg.category_allowed("sports") is True
        assert cfg.category_allowed("politics") is False

    def test_category_allowed_case_insensitive(self):
        from merid.event_venues.kalshi.universe import UniverseConfig
        cfg = UniverseConfig()
        cfg.allowed_categories = ["Crypto"]
        assert cfg.category_allowed("CRYPTO") is True


# ══════════════════════════════════════════════════════════════════════════
# 5. _passes_liquidity
# ══════════════════════════════════════════════════════════════════════════

class TestPassesLiquidity:
    def _passes(self, cm, **kwargs):
        from merid.event_venues.kalshi.universe import UniverseConfig, _passes_liquidity
        import os
        
        # Set environment variables for testing (UniverseConfig reads from env vars)
        original_env = {}
        for key, value in kwargs.items():
            env_key = f"MERID_UNIVERSE_{key.upper()}"
            original_env[env_key] = os.environ.get(env_key)
            os.environ[env_key] = str(value)
        
        try:
            cfg = UniverseConfig()
            return _passes_liquidity(cm, cfg)
        finally:
            # Restore original environment
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_passes_with_defaults(self):
        cm = _make_cm("TEST-1")
        assert self._passes(cm) is True

    def test_fails_volume_floor(self):
        cm = _make_cm("TEST-2", volume=5)
        assert self._passes(cm, min_volume=10) is False

    def test_fails_spread(self):
        cm = _make_cm("TEST-3", bid=10, ask=90)
        assert self._passes(cm, max_spread_cents=10) is False

    def test_passes_spread_within_limit(self):
        cm = _make_cm("TEST-4", bid=45, ask=55)
        # spread=10, limit=10 — should pass (not strictly greater)
        assert self._passes(cm, max_spread_cents=10) is True

    def test_no_book_skips_spread_check(self):
        cm = _make_cm("TEST-5", bid=0, ask=0)
        assert self._passes(cm, max_spread_cents=5) is True


# ══════════════════════════════════════════════════════════════════════════
# 6. KalshiUniverse.get_pool
# ══════════════════════════════════════════════════════════════════════════

class TestKalshiUniverseGetPool:

    def test_all_markets_no_filter(self):
        markets = [
            _make_cm("A-1", category="crypto"),
            _make_cm("B-1", category="sports"),
            _make_cm("C-1", category="politics"),
        ]
        from merid.event_venues.kalshi.universe import KalshiUniverse, UniverseConfig
        u = KalshiUniverse(UniverseConfig())
        mock_catalog = _make_mock_catalog(markets)
        with patch("merid.event_venues.kalshi.universe.get_market_catalog", return_value=mock_catalog):
            pool = u.get_pool()
        assert len(pool) == 3

    def test_category_filter(self):
        markets = [
            _make_cm("A-1", category="crypto"),
            _make_cm("B-1", category="sports"),
        ]
        from merid.event_venues.kalshi.universe import KalshiUniverse, UniverseConfig
        u = KalshiUniverse(UniverseConfig())
        mock_catalog = _make_mock_catalog(markets)
        with patch("merid.event_venues.kalshi.universe.get_market_catalog", return_value=mock_catalog):
            pool = u.get_pool(category="crypto")
        assert len(pool) == 1
        assert pool[0].market.market_id == "A-1"

    def test_limit_respected(self):
        markets = [_make_cm(f"X-{i}", category="crypto") for i in range(20)]
        from merid.event_venues.kalshi.universe import KalshiUniverse, UniverseConfig
        u = KalshiUniverse(UniverseConfig(max_per_agent=5))
        mock_catalog = _make_mock_catalog(markets)
        with patch("merid.event_venues.kalshi.universe.get_market_catalog", return_value=mock_catalog):
            pool = u.get_pool()
        assert len(pool) == 5

    def test_allowlist_excludes_blocked_category(self):
        markets = [
            _make_cm("A-1", category="crypto"),
            _make_cm("B-1", category="politics"),
        ]
        from merid.event_venues.kalshi.universe import KalshiUniverse, UniverseConfig
        cfg = UniverseConfig()
        cfg.allowed_categories = ["crypto"]
        u = KalshiUniverse(cfg)
        mock_catalog = _make_mock_catalog(markets)
        with patch("merid.event_venues.kalshi.universe.get_market_catalog", return_value=mock_catalog):
            pool = u.get_pool()
        cats = {m.category for m in pool}
        assert "politics" not in cats

    def test_liquidity_filtered(self):
        markets = [
            _make_cm("PASS-1", volume=500),
            _make_cm("FAIL-1", volume=2),
        ]
        from merid.event_venues.kalshi.universe import KalshiUniverse, UniverseConfig
        u = KalshiUniverse(UniverseConfig(min_volume=10))
        mock_catalog = _make_mock_catalog(markets)
        with patch("merid.event_venues.kalshi.universe.get_market_catalog", return_value=mock_catalog):
            pool = u.get_pool()
        tickers = [m.market.market_id for m in pool]
        assert "PASS-1" in tickers
        assert "FAIL-1" not in tickers

    def test_get_all_open(self):
        markets = [_make_cm(f"M-{i}") for i in range(10)]
        from merid.event_venues.kalshi.universe import KalshiUniverse, UniverseConfig
        u = KalshiUniverse(UniverseConfig(max_per_agent=100))
        mock_catalog = _make_mock_catalog(markets)
        with patch("merid.event_venues.kalshi.universe.get_market_catalog", return_value=mock_catalog):
            pool = u.get_all_open()
        assert len(pool) == 10

    def test_category_not_in_allowlist_returns_empty(self):
        markets = [_make_cm("P-1", category="politics")]
        from merid.event_venues.kalshi.universe import KalshiUniverse, UniverseConfig
        cfg = UniverseConfig()
        cfg.allowed_categories = ["crypto"]
        u = KalshiUniverse(cfg)
        mock_catalog = _make_mock_catalog(markets)
        with patch("merid.event_venues.kalshi.universe.get_market_catalog", return_value=mock_catalog):
            pool = u.get_pool(category="politics")
        assert pool == []


# ══════════════════════════════════════════════════════════════════════════
# 7. iter_categories
# ══════════════════════════════════════════════════════════════════════════

class TestIterCategories:
    def test_yields_non_empty_categories_only(self):
        markets = [
            _make_cm("C-1", category="crypto"),
            _make_cm("C-2", category="crypto"),
            _make_cm("S-1", category="sports"),
        ]
        from merid.event_venues.kalshi.universe import KalshiUniverse, UniverseConfig
        u = KalshiUniverse(UniverseConfig())
        mock_catalog = _make_mock_catalog(markets)
        with patch("merid.event_venues.kalshi.universe.get_market_catalog", return_value=mock_catalog):
            results = list(u.iter_categories())
        cats = [cat for cat, _, _ in results]
        assert "crypto" in cats
        assert "sports" in cats

    def test_yields_valid_mode_strings(self):
        markets = [_make_cm("C-1", category="crypto")]
        from merid.event_venues.kalshi.universe import KalshiUniverse, UniverseConfig
        u = KalshiUniverse(UniverseConfig())
        mock_catalog = _make_mock_catalog(markets)
        with patch("merid.event_venues.kalshi.universe.get_market_catalog", return_value=mock_catalog):
            with patch.dict(os.environ, {"MERID_UNIVERSE_MODE_CRYPTO": "paper"}):
                results = list(u.iter_categories())
        for _, mode, _ in results:
            assert mode in ("paper", "live"), f"Unexpected mode: {mode}"

    def test_yields_pool_list(self):
        markets = [_make_cm("C-1", category="crypto"), _make_cm("C-2", category="crypto")]
        from merid.event_venues.kalshi.universe import KalshiUniverse, UniverseConfig
        u = KalshiUniverse(UniverseConfig())
        mock_catalog = _make_mock_catalog(markets)
        with patch("merid.event_venues.kalshi.universe.get_market_catalog", return_value=mock_catalog):
            results = list(u.iter_categories())
        for cat, _, pool in results:
            if cat == "crypto":
                assert len(pool) == 2


# ══════════════════════════════════════════════════════════════════════════
# 8. coverage_summary
# ══════════════════════════════════════════════════════════════════════════

class TestCoverageSummary:
    def test_summary_counts(self):
        markets = [
            _make_cm("C-1", category="crypto"),
            _make_cm("C-2", category="crypto"),
            _make_cm("P-1", category="politics"),
        ]
        from merid.event_venues.kalshi.universe import KalshiUniverse, UniverseConfig
        u = KalshiUniverse(UniverseConfig())
        mock_catalog = _make_mock_catalog(markets)
        with patch("merid.event_venues.kalshi.universe.get_market_catalog", return_value=mock_catalog):
            summary = u.coverage_summary()
        assert summary["total_active"] == 3
        assert summary["by_category"].get("crypto", 0) == 2
        assert summary["by_category"].get("politics", 0) == 1

    def test_summary_has_required_keys(self):
        from merid.event_venues.kalshi.universe import KalshiUniverse, UniverseConfig
        u = KalshiUniverse(UniverseConfig())
        mock_catalog = _make_mock_catalog([])
        with patch("merid.event_venues.kalshi.universe.get_market_catalog", return_value=mock_catalog):
            summary = u.coverage_summary()
        for key in ("total_active", "total_liquid", "by_category", "category_modes", "max_per_agent"):
            assert key in summary, f"Missing key: {key}"

    def test_summary_category_modes_present(self):
        from merid.event_venues.kalshi.universe import KalshiUniverse, UniverseConfig, KNOWN_CATEGORIES
        u = KalshiUniverse(UniverseConfig())
        mock_catalog = _make_mock_catalog([])
        with patch("merid.event_venues.kalshi.universe.get_market_catalog", return_value=mock_catalog):
            summary = u.coverage_summary()
        modes = summary["category_modes"]
        for cat in KNOWN_CATEGORIES:
            assert cat in modes
            assert modes[cat] in ("paper", "live")


# ══════════════════════════════════════════════════════════════════════════
# 9. get_category_mode / get_all_category_modes
# ══════════════════════════════════════════════════════════════════════════

class TestCategoryModes:
    def test_env_override_live(self):
        from merid.event_venues.kalshi.universe import get_category_mode
        with patch.dict(os.environ, {"MERID_UNIVERSE_MODE_CRYPTO": "live"}):
            assert get_category_mode("crypto") == "live"

    def test_env_override_paper(self):
        from merid.event_venues.kalshi.universe import get_category_mode
        with patch.dict(os.environ, {"MERID_UNIVERSE_MODE_CRYPTO": "paper"}):
            assert get_category_mode("crypto") == "paper"

    def test_invalid_override_falls_back(self):
        from merid.event_venues.kalshi.universe import get_category_mode
        with patch.dict(os.environ, {"MERID_UNIVERSE_MODE_CRYPTO": "bogus"}):
            mode = get_category_mode("crypto")
            assert mode in ("paper", "live")

    def test_all_category_modes_covers_all_known(self):
        from merid.event_venues.kalshi.universe import get_all_category_modes, KNOWN_CATEGORIES
        modes = get_all_category_modes()
        for cat in KNOWN_CATEGORIES:
            assert cat in modes, f"Missing mode for: {cat}"
            assert modes[cat] in ("paper", "live"), f"Invalid mode for {cat}: {modes[cat]}"


# ══════════════════════════════════════════════════════════════════════════
# 10. Singleton
# ══════════════════════════════════════════════════════════════════════════

class TestUniverseSingleton:
    def test_singleton_returns_same_instance(self):
        import merid.event_venues.kalshi.universe as umod
        orig = umod._universe
        umod._universe = None
        try:
            from merid.event_venues.kalshi.universe import get_kalshi_universe
            a = get_kalshi_universe()
            b = get_kalshi_universe()
            assert a is b
        finally:
            umod._universe = orig


# ══════════════════════════════════════════════════════════════════════════
# 11. KalshiUniversalAgent — config, state, registry
# ══════════════════════════════════════════════════════════════════════════

class TestUniversalAgentConfig:
    def test_defaults(self):
        from merid.prediction.universal_agent import UniversalAgentConfig
        cfg = UniversalAgentConfig()
        assert cfg.name == "universal-agent"
        assert cfg.dry_run is False
        assert cfg.max_markets == 50
        assert cfg.cycle_secs == 60.0

    def test_custom_config(self):
        from merid.prediction.universal_agent import UniversalAgentConfig
        cfg = UniversalAgentConfig(
            name="test-agent",
            categories=["crypto", "sports"],
            max_markets=10,
            dry_run=True,
        )
        assert cfg.categories == ["crypto", "sports"]
        assert cfg.max_markets == 10
        assert cfg.dry_run is True


class TestUniversalAgentState:
    def test_initial_state(self):
        from merid.prediction.universal_agent import KalshiUniversalAgent, UniversalAgentConfig
        agent = KalshiUniversalAgent(UniversalAgentConfig(name="test"))
        assert agent.state.running is False
        assert agent.state.cycles_run == 0
        assert agent.state.orders_placed == 0

    def test_to_dict_keys(self):
        from merid.prediction.universal_agent import KalshiUniversalAgent, UniversalAgentConfig
        agent = KalshiUniversalAgent(UniversalAgentConfig(name="test"))
        d = agent.state.to_dict()
        for key in ("name", "running", "enabled", "cycles_run", "orders_placed", "orders_rejected"):
            assert key in d, f"Missing key: {key}"

    def test_pause_resume(self):
        from merid.prediction.universal_agent import KalshiUniversalAgent, UniversalAgentConfig
        agent = KalshiUniversalAgent(UniversalAgentConfig(name="pr-test"))
        agent.pause()
        assert agent.state.enabled is False
        agent.resume()
        assert agent.state.enabled is True


class TestUniversalAgentRegistry:
    def test_register_and_get(self):
        import merid.prediction.universal_agent as amod
        from merid.prediction.universal_agent import (
            KalshiUniversalAgent,
            UniversalAgentConfig,
            get_universal_agent,
            register_universal_agent,
        )
        orig = dict(amod._agents)
        amod._agents.clear()
        try:
            agent = KalshiUniversalAgent(UniversalAgentConfig(name="reg-test"))
            register_universal_agent(agent)
            assert get_universal_agent("reg-test") is agent
            assert get_universal_agent("nonexistent") is None
        finally:
            amod._agents = orig

    def test_get_or_create_idempotent(self):
        import merid.prediction.universal_agent as amod
        from merid.prediction.universal_agent import (
            UniversalAgentConfig,
            get_or_create_universal_agent,
        )
        orig = dict(amod._agents)
        amod._agents.clear()
        try:
            cfg = UniversalAgentConfig(name="idem-agent")
            a1 = get_or_create_universal_agent("idem-agent", cfg)
            a2 = get_or_create_universal_agent("idem-agent")
            assert a1 is a2
        finally:
            amod._agents = orig


# ══════════════════════════════════════════════════════════════════════════
# 12. Dry-run: no route_order_async called, order_log populated
# ══════════════════════════════════════════════════════════════════════════

class TestUniversalAgentDryRun:

    @pytest.mark.asyncio
    async def test_no_signal_no_route(self):
        from merid.prediction.universal_agent import (
            KalshiUniversalAgent,
            UniversalAgentConfig,
        )
        from merid.prediction.strategy import SignalAction

        agent = KalshiUniversalAgent(
            UniversalAgentConfig(name="dry-nosig", dry_run=True, max_markets=5)
        )

        market = _make_cm("DRY-1", category="crypto")
        mock_strategy = MagicMock()

        class _NoAction:
            action = SignalAction.NO_ACTION
            edge = None
            limit_price_cents = 50
            contracts = 1

        mock_strategy.evaluate.return_value = _NoAction()
        agent._strategy = mock_strategy
        agent._init_subsystems = lambda: None

        with patch("merid.event_venues.kalshi.order_router.route_order_async") as mock_route:
            await agent._evaluate_market(market, "paper")
            mock_route.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_logs_buy_signal(self):
        from merid.prediction.universal_agent import (
            KalshiUniversalAgent,
            UniversalAgentConfig,
        )
        from merid.prediction.strategy import SignalAction

        agent = KalshiUniversalAgent(
            UniversalAgentConfig(name="dry-log", dry_run=True, max_markets=5, min_edge=0.0)
        )

        market = _make_cm("BUY-1", category="crypto")
        mock_strategy = MagicMock()

        class _Edge:
            net_edge = 0.15

        class _BuySignal:
            action = SignalAction.BUY_YES
            limit_price_cents = 55
            contracts = 2
            edge = _Edge()

        mock_strategy.evaluate.return_value = _BuySignal()
        agent._strategy = mock_strategy
        agent._risk = None
        agent._init_subsystems = lambda: None

        # Patch _build_snapshot to return a stub so model imports aren't needed
        agent._build_snapshot = lambda cm: MagicMock()

        with patch("merid.event_venues.kalshi.order_router.route_order_async") as mock_route:
            await agent._evaluate_market(market, "paper")
            mock_route.assert_not_called()

        assert len(agent.state.order_log) == 1
        entry = agent.state.order_log[0]
        assert entry["dry_run"] is True
        assert entry["ticker"] == "BUY-1"
        assert entry["side"] == "yes"
        assert entry["action"] == "buy"

    @pytest.mark.asyncio
    async def test_edge_gate_blocks_low_edge(self):
        from merid.prediction.universal_agent import (
            KalshiUniversalAgent,
            UniversalAgentConfig,
        )
        from merid.prediction.strategy import SignalAction

        agent = KalshiUniversalAgent(
            UniversalAgentConfig(name="edge-gate", dry_run=True, min_edge=0.10)
        )

        market = _make_cm("EDGE-1", category="crypto")
        mock_strategy = MagicMock()

        class _Edge:
            net_edge = 0.01  # below min_edge=0.10

        class _WeakSignal:
            action = SignalAction.BUY_YES
            limit_price_cents = 50
            contracts = 1
            edge = _Edge()

        mock_strategy.evaluate.return_value = _WeakSignal()
        agent._strategy = mock_strategy
        agent._risk = None
        agent._init_subsystems = lambda: None
        agent._build_snapshot = lambda cm: MagicMock()

        with patch("merid.event_venues.kalshi.order_router.route_order_async") as mock_route:
            await agent._evaluate_market(market, "paper")
            mock_route.assert_not_called()

        assert len(agent.state.order_log) == 0


# ══════════════════════════════════════════════════════════════════════════
# 13. CategoryExposureTracker — new categories accepted
# ══════════════════════════════════════════════════════════════════════════

class TestCategoryExposureNewCats:
    def _tracker(self):
        from merid.event_venues.kalshi.category_exposure import CategoryExposureTracker
        return CategoryExposureTracker()

    def test_new_categories_accepted_within_cap(self):
        tracker = self._tracker()
        for cat in ("economics", "climate", "tech", "culture", "science"):
            allowed, reason = tracker.check_category_cap(cat, 10.0)
            assert allowed is True, f"{cat}: {reason}"

    def test_category_cap_exceeded(self):
        from merid.event_venues.kalshi.category_exposure import CategoryExposureTracker, _DEFAULT_CATEGORY_CAPS
        tracker = CategoryExposureTracker()
        cat = "sports"
        cap = _DEFAULT_CATEGORY_CAPS.get(cat, 200.0)
        # Record exposure just over the cap
        tracker.record_fill(cat, "NBA", cap + 1.0)
        allowed, reason = tracker.check_category_cap(cat, 1.0)
        assert allowed is False
        assert cat in reason

    def test_unknown_category_has_no_cap(self):
        tracker = self._tracker()
        allowed, reason = tracker.check_category_cap("unknowncategory", 999.0)
        assert allowed is True

    def test_infer_category_used_by_tracker_via_underlying(self):
        from merid.event_venues.kalshi.category_exposure import infer_category
        assert infer_category("SPX") == "financials"
        assert infer_category("NBA") == "sports"
        assert infer_category("CPI") == "economics"
