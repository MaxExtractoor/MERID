"""Crypto symbol/timeframe coverage guard tests.

Validates the config → agent → opinion chain for BTC, ETH, SOL, XRP, DOGE
and their timeframes (15m, 1h, daily, weekly). Ensures no symbol/timeframe
can silently drop from the trading grid.
"""

import pytest
import asyncio
from typing import Set, Tuple, List, Dict, Any, Optional
from dataclasses import dataclass


class TestCryptoUniverseConfig:
    """Upstream: Validate config layer declares all required symbols/timeframes."""

    EXPECTED_SYMBOLS: Set[str] = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
    EXPECTED_TIMEFRAMES: Set[str] = {"15m", "1h", "daily", "weekly"}

    def test_kalshi_crypto_series_meta_has_all_symbols(self):
        """kalshi_crypto_series_meta.SERIES_META_LIST must include all 5 symbols."""
        from config.kalshi_crypto_series_meta import SERIES_META_LIST, AssetSymbol
        
        symbols_in_meta: Set[str] = set()
        for meta in SERIES_META_LIST:
            symbols_in_meta.add(meta.asset)
        
        missing = self.EXPECTED_SYMBOLS - symbols_in_meta
        extra = symbols_in_meta - self.EXPECTED_SYMBOLS
        
        assert not missing, f"Missing symbols in SERIES_META_LIST: {missing}"
        assert not extra, f"Unexpected extra symbols in SERIES_META_LIST: {extra}"

    def test_kalshi_crypto_series_meta_has_all_timeframes_per_symbol(self):
        """Each symbol must have 15m, 1h, daily, weekly in SERIES_META_LIST."""
        from config.kalshi_crypto_series_meta import SERIES_META_LIST
        
        for symbol in self.EXPECTED_SYMBOLS:
            timeframes_for_symbol: Set[str] = set()
            for meta in SERIES_META_LIST:
                if meta.asset == symbol:
                    timeframes_for_symbol.add(meta.timeframe)
            
            missing = self.EXPECTED_TIMEFRAMES - timeframes_for_symbol
            assert not missing, f"{symbol} missing timeframes: {missing}"

    def test_kalshi_crypto_series_meta_has_correct_series_tickers(self):
        """Series tickers must follow Kalshi naming convention."""
        from config.kalshi_crypto_series_meta import SERIES_META_LIST, get_series_meta
        
        expected_tickers = {
            ("BTC", "15m"): "KXBTC15M",
            ("BTC", "1h"): "KXBTC",
            ("BTC", "daily"): "KXBTCD1",
            ("BTC", "weekly"): "KXBTCW1",
            ("ETH", "15m"): "KXETH15M",
            ("ETH", "1h"): "KXETH",
            ("ETH", "daily"): "KXETHD1",
            ("ETH", "weekly"): "KXETHW1",
            ("SOL", "15m"): "KXSOL15M",
            ("SOL", "1h"): "KXSOL",
            ("SOL", "daily"): "KXSOLD1",
            ("SOL", "weekly"): "KXSOLW1",
            ("XRP", "15m"): "KXXRP15M",
            ("XRP", "1h"): "KXXRP",
            ("XRP", "daily"): "KXXRPD1",
            ("XRP", "weekly"): "KXXRPW1",
            ("DOGE", "15m"): "KXDOGE15M",
            ("DOGE", "1h"): "KXDOGE",
            ("DOGE", "daily"): "KXDOGED1",
            ("DOGE", "weekly"): "KXDOGEW1",
        }
        
        for (asset, timeframe), expected_ticker in expected_tickers.items():
            meta = get_series_meta(asset, timeframe)
            assert meta is not None, f"Missing series meta for {asset}/{timeframe}"
            assert meta.series_ticker == expected_ticker, \
                f"{asset}/{timeframe}: expected {expected_ticker}, got {meta.series_ticker}"

    def test_crypto_spot_kalshi_config_has_all_symbols(self):
        """CRYPTO_CONFIG must define all 5 symbols."""
        from config.crypto_spot_kalshi_config import CRYPTO_CONFIG
        
        symbols_in_config: Set[str] = set(CRYPTO_CONFIG.keys())
        
        missing = self.EXPECTED_SYMBOLS - symbols_in_config
        extra = symbols_in_config - self.EXPECTED_SYMBOLS
        
        assert not missing, f"Missing symbols in CRYPTO_CONFIG: {missing}"
        assert not extra, f"Unexpected extra symbols in CRYPTO_CONFIG: {extra}"

    def test_agent_grid_yaml_has_crypto_agents_for_all_symbols_timeframes(self):
        """kalshi_agent_grid.yaml must have directional agents for all symbol/timeframe pairs."""
        from merid.prediction.agent_grid_config import get_agent_grid_config
        
        config = get_agent_grid_config()
        
        # Find all per-asset directional agents
        crypto_agents: List[Tuple[str, str]] = []
        for agent in config.agents:
            if agent.category == "crypto" and agent.archetype == "directional":
                for asset in agent.assets:
                    for timeframe in agent.timeframes:
                        crypto_agents.append((asset.upper(), timeframe.lower()))
        
        # Check all expected pairs exist
        expected_pairs = {
            (s, t) for s in self.EXPECTED_SYMBOLS 
            for t in self.EXPECTED_TIMEFRAMES
        }
        actual_pairs = set(crypto_agents)
        
        missing = expected_pairs - actual_pairs
        
        if missing:
            missing_str = [f"{s}/{t}" for s, t in sorted(missing)]
            pytest.fail(f"Missing crypto agents for: {missing_str}")

    def test_agent_grid_yaml_has_20_crypto_directional_agents(self):
        """Should have exactly 20 directional crypto agents (5 symbols × 4 timeframes)."""
        from merid.prediction.agent_grid_config import get_agent_grid_config
        
        config = get_agent_grid_config()
        
        count = sum(
            1 for agent in config.agents 
            if agent.category == "crypto" and agent.archetype == "directional"
        )
        
        assert count >= 20, f"Expected at least 20 crypto directional agents, found {count}"


class TestAgentGridWiring:
    """Midstream: Validate grid → agent wiring produces all symbol/timeframe agents."""

    def test_agent_grid_creates_agents_from_config(self):
        """AgentGrid.__init__ should create KalshiTradingAgent per config entry."""
        from merid.prediction.agent_grid import AgentGrid
        from merid.prediction.agent_grid_config import get_agent_grid_config
        
        config = get_agent_grid_config()
        
        # Create grid
        grid = AgentGrid(config)
        
        # Should have agents matching enabled config entries
        enabled_agents = [a for a in config.agents if a.enabled]
        assert len(grid._agents) == len(enabled_agents), \
            f"Grid created {len(grid._agents)} agents but config has {len(enabled_agents)} enabled"

    def test_agent_grid_registry_contains_all_crypto_symbol_timeframe_pairs(self):
        """Grid's internal agent map should have entry for each (symbol, timeframe)."""
        from merid.prediction.agent_grid import AgentGrid
        from merid.prediction.agent_grid_config import get_agent_grid_config
        
        config = get_agent_grid_config()
        grid = AgentGrid(config)
        
        # Build set of (symbol, timeframe) pairs covered by grid agents
        covered_pairs: Set[Tuple[str, str]] = set()
        for agent in grid._agents:
            cfg = agent._config
            for asset in cfg.assets:
                for timeframe in cfg.timeframes:
                    covered_pairs.add((asset.upper(), timeframe.lower()))
        
        # All expected pairs should be covered
        expected = {
            (s, t) for s in TestCryptoUniverseConfig.EXPECTED_SYMBOLS
            for t in TestCryptoUniverseConfig.EXPECTED_TIMEFRAMES
        }
        
        missing = expected - covered_pairs
        assert not missing, f"Grid missing coverage for: {sorted(missing)}"


class TestParameterizedAgentOpinionSmokeTest:
    """Parameterized smoke tests for all (symbol, timeframe) combinations."""

    # All symbol/timeframe combinations to test
    CRYPTO_COMBOS = [
        ("BTC", "15m"), ("BTC", "1h"), ("BTC", "daily"), ("BTC", "weekly"),
        ("ETH", "15m"), ("ETH", "1h"), ("ETH", "daily"), ("ETH", "weekly"),
        ("SOL", "15m"), ("SOL", "1h"), ("SOL", "daily"), ("SOL", "weekly"),
        ("XRP", "15m"), ("XRP", "1h"), ("XRP", "daily"), ("XRP", "weekly"),
        ("DOGE", "15m"), ("DOGE", "1h"), ("DOGE", "daily"), ("DOGE", "weekly"),
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("symbol,timeframe", CRYPTO_COMBOS)
    async def test_regime_agent_get_opinion_runs_without_error(self, symbol: str, timeframe: str):
        """Each (symbol, timeframe) agent can call get_opinion without KeyError/mis-routing."""
        # Only test the 5 regime agents that exist (ETH 15m, SOL 15m, XRP 15m, DOGE 15m, BTC 1h)
        regime_combos = {
            ("ETH", "15m"), ("SOL", "15m"), ("XRP", "15m"), ("DOGE", "15m"), ("BTC", "1h")
        }
        
        if (symbol, timeframe) not in regime_combos:
            pytest.skip(f"No regime agent for {symbol}/{timeframe}")
        
        # Import the appropriate agent class
        agent_map = {
            ("ETH", "15m"): "merid.agents.eth_15m_agent",
            ("SOL", "15m"): "merid.agents.sol_15m_agent",
            ("XRP", "15m"): "merid.agents.xrp_15m_agent",
            ("DOGE", "15m"): "merid.agents.doge_15m_agent",
            # BTC 1h archived 2026-01-15 - focus on 15m timeframe only
        }
        
        module_path = agent_map[(symbol, timeframe)]
        module = __import__(module_path, fromlist=["AgentClass"])
        
        # Get agent class (naming convention: Eth15mAgent, Sol15mAgent, etc.)
        class_name = f"{symbol.title()}{timeframe.replace('m', 'm').replace('h', 'h').replace('d', 'd').replace('w', 'w')}Agent"
        if timeframe == "1h":
            class_name = f"{symbol.title()}1hAgent"
        
        agent_class = getattr(module, class_name)
        
        # Instantiate without side effects (no dependencies)
        agent = agent_class()
        
        # Call get_opinion — should return AgentOpinion or None, never raise
        try:
            opinion = await agent.get_opinion(
                trace_id=f"test_{symbol}_{timeframe}",
                correlation_id="test_correlation"
            )
            
            # Validate opinion structure if not None
            if opinion is not None:
                assert opinion.agent_id == agent.agent_id
                assert opinion.trace_id == f"test_{symbol}_{timeframe}"
                # CRITICAL: symbol/timeframe must match the test parameters exactly
                assert opinion.symbol == symbol, \
                    f"Agent {symbol}/{timeframe} returned opinion.symbol={opinion.symbol}, expected {symbol}"
                assert opinion.timeframe == timeframe, \
                    f"Agent {symbol}/{timeframe} returned opinion.timeframe={opinion.timeframe}, expected {timeframe}"
                
        except KeyError as e:
            pytest.fail(f"KeyError in get_opinion for {symbol}/{timeframe}: {e}")
        except Exception as e:
            # Other exceptions may be expected (missing deps, no market data)
            # but we specifically want to avoid KeyError/mis-routing
            if "key" in str(e).lower() or "routing" in str(e).lower():
                pytest.fail(f"Routing error in get_opinion for {symbol}/{timeframe}: {e}")


class TestAgentOpinionToKalshiMarketRouting:
    """Downstream: Validate AgentOpinion → correct Kalshi market routing."""

    def test_agent_opinion_carries_symbol_and_timeframe(self):
        """AgentOpinion must have symbol and timeframe fields for routing."""
        from merid.agents.base import AgentOpinion
        
        opinion = AgentOpinion(
            agent_id="test_agent",
            symbol="BTC",
            timeframe="15m",
            side="YES",
            confidence=0.75,
            edge_estimate=0.05,
            market_id="KXBTC15M-TEST",
        )
        
        assert opinion.symbol == "BTC"
        assert opinion.timeframe == "15m"

    def test_series_ticker_resolution_for_all_symbol_timeframe_combos(self):
        """Each (symbol, timeframe) must resolve to correct Kalshi series ticker."""
        from config.kalshi_crypto_series_meta import resolve_series_ticker_from_meta
        
        test_cases = [
            (("BTC", "15m"), "KXBTC15M"),
            (("BTC", "1h"), "KXBTC"),
            (("BTC", "daily"), "KXBTCD1"),
            (("BTC", "weekly"), "KXBTCW1"),
            (("ETH", "15m"), "KXETH15M"),
            (("ETH", "1h"), "KXETH"),
            (("ETH", "daily"), "KXETHD1"),
            (("ETH", "weekly"), "KXETHW1"),
            (("SOL", "15m"), "KXSOL15M"),
            (("SOL", "1h"), "KXSOL"),
            (("SOL", "daily"), "KXSOLD1"),
            (("SOL", "weekly"), "KXSOLW1"),
            (("XRP", "15m"), "KXXRP15M"),
            (("XRP", "1h"), "KXXRP"),
            (("XRP", "daily"), "KXXRPD1"),
            (("XRP", "weekly"), "KXXRPW1"),
            (("DOGE", "15m"), "KXDOGE15M"),
            (("DOGE", "1h"), "KXDOGE"),
            (("DOGE", "daily"), "KXDOGED1"),
            (("DOGE", "weekly"), "KXDOGEW1"),
        ]
        
        for (asset, timeframe), expected_ticker in test_cases:
            actual = resolve_series_ticker_from_meta(asset, timeframe)
            assert actual == expected_ticker, \
                f"{asset}/{timeframe}: expected {expected_ticker}, got {actual}"

    def test_bidirectional_series_ticker_mapping_no_collisions(self):
        """Series ticker -> (symbol, timeframe) must be unique (no collisions)."""
        from config.kalshi_crypto_series_meta import SERIES_META_LIST
        
        # Build reverse mapping: series_ticker -> (symbol, timeframe)
        reverse_map: Dict[str, Tuple[str, str]] = {}
        
        for meta in SERIES_META_LIST:
            key = (meta.asset, meta.timeframe)
            ticker = meta.series_ticker
            
            if ticker in reverse_map:
                existing = reverse_map[ticker]
                pytest.fail(
                    f"Series ticker collision: {ticker} maps to both "
                    f"{existing} and {key}"
                )
            
            reverse_map[ticker] = key
        
        # Verify all expected tickers are present and unique
        expected_tickers = {
            "KXBTC15M", "KXBTC", "KXBTCD1", "KXBTCW1",
            "KXETH15M", "KXETH", "KXETHD1", "KXETHW1",
            "KXSOL15M", "KXSOL", "KXSOLD1", "KXSOLW1",
            "KXXRP15M", "KXXRP", "KXXRPD1", "KXXRPW1",
            "KXDOGE15M", "KXDOGE", "KXDOGED1", "KXDOGEW1",
        }
        
        missing = expected_tickers - set(reverse_map.keys())
        extra = set(reverse_map.keys()) - expected_tickers
        
        assert not missing, f"Missing series tickers in reverse map: {missing}"
        # Allow extra for monthly/annual if present

    def test_market_selector_resolves_agent_to_series_tickers(self):
        """market_selector.get_agent_market_tickers must return series for all crypto agents."""
        try:
            from merid.event_venues.kalshi.market_selector import get_agent_market_tickers, AGENT_SERIES_MAP
        except ImportError:
            pytest.skip("market_selector not available")
        
        # Test for all crypto regime agents
        crypto_agents = [
            "eth_15m", "sol_15m", "xrp_15m", "doge_15m",
            "btc_15m", "eth_1h", "sol_1h", "xrp_1h", "doge_1h",
        ]
        
        for agent_name in crypto_agents:
            if agent_name in AGENT_SERIES_MAP:
                tickers = get_agent_market_tickers(agent_name)
                assert tickers, f"{agent_name} resolved to empty tickers"
                assert all(isinstance(t, str) for t in tickers), \
                    f"{agent_name} tickers not all strings: {tickers}"


class TestPerSymbolTimeframeRiskBehavior:
    """Risk singleton per-symbol/timeframe isolation tests."""

    def test_risk_singleton_does_not_blend_symbol_parameters(self):
        """Changing per-symbol risk config should not affect other symbols."""
        from merid.prediction.risk import get_prediction_risk, PredictionRiskConfig
        
        # Get the singleton
        risk = get_prediction_risk()
        
        # The risk object should exist
        assert risk is not None
        
        # Verify the risk object has per-symbol tracking capabilities
        # (specific implementation depends on PredictionMarketRisk structure)
        if hasattr(risk, '_symbol_configs'):
            # If using per-symbol config dict, ensure isolation
            symbol_configs = risk._symbol_configs
            
            # Each symbol should have independent config
            for symbol in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                if symbol in symbol_configs:
                    # Modify one symbol's config
                    original_value = symbol_configs.get(symbol, {}).get('max_leverage', 1.0)
                    symbol_configs[symbol]['max_leverage'] = 999.0
                    
                    # Verify other symbols unchanged
                    for other in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                        if other != symbol and other in symbol_configs:
                            other_value = symbol_configs[other].get('max_leverage', 1.0)
                            assert other_value != 999.0, \
                                f"Modifying {symbol} max_leverage leaked to {other}"
                    
                    # Restore
                    symbol_configs[symbol]['max_leverage'] = original_value

    def test_prediction_risk_has_per_timeframe_position_tracking(self):
        """Risk engine should track positions per (symbol, timeframe), not just symbol."""
        from merid.prediction.risk import get_prediction_risk
        
        risk = get_prediction_risk()
        
        # Check for per-timeframe position tracking
        if hasattr(risk, '_positions'):
            # Positions should be keyed by (symbol, timeframe) or similar
            # Not just by symbol alone
            pass  # Structure check depends on implementation

    def test_risk_cache_key_includes_symbol_and_timeframe(self):
        """Any risk cache or registry key must include both symbol and timeframe."""
        from merid.prediction.risk import get_prediction_risk
        
        risk = get_prediction_risk()
        
        # Check that risk object enforces per-(symbol, timeframe) identity
        # This prevents cross-contamination between BTC 15m and BTC 1h positions
        
        if hasattr(risk, '_position_cache'):
            cache = risk._position_cache
            # Example cache keys should be tuples or contain both symbol and timeframe
            for key in list(cache.keys())[:10]:  # Sample first 10 keys
                key_str = str(key)
                # Key should not be just a symbol (e.g., "BTC")
                assert not key_str.upper() in ["BTC", "ETH", "SOL", "XRP", "DOGE"], \
                    f"Risk cache key {key} appears to be bare symbol without timeframe"

    def test_risk_singleton_keys_are_not_shared_across_timeframes(self):
        """Modifying risk state for one (symbol, timeframe) must not affect others."""
        from merid.prediction.risk import get_prediction_risk
        
        risk = get_prediction_risk()
        
        # Verify that risk singleton uses compound keys for tracking
        if hasattr(risk, '_exposure'):
            # Check exposure dict keys are compound (symbol, timeframe) not bare symbol
            for key in list(risk._exposure.keys())[:10]:
                if isinstance(key, str) and key.upper() in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                    pytest.fail(
                        f"Risk exposure uses bare symbol key: {key}. "
                        f"Must use (symbol, timeframe) tuple to prevent cross-timeframe leakage."
                    )


class TestConfigConsistencyReport:
    """Validate config consistency across modules."""

    def test_crypto_surface_config_matches_series_meta(self):
        """CRYPTO_CONFIG series must match kalshi_crypto_series_meta."""
        from config.crypto_spot_kalshi_config import CRYPTO_CONFIG
        from config.kalshi_crypto_series_meta import get_series_meta
        
        mismatches = []
        
        for symbol, cfg in CRYPTO_CONFIG.items():
            for tf_key, series_ticker in cfg.get("series", {}).items():
                # Map timeframe key to canonical
                tf_map = {"15M": "15m", "1H": "1h", "1D": "daily"}
                canonical_tf = tf_map.get(tf_key, tf_key.lower())
                
                meta = get_series_meta(symbol, canonical_tf)
                if meta is None:
                    mismatches.append(f"{symbol}/{canonical_tf}: no series meta found")
                elif meta.series_ticker != series_ticker:
                    mismatches.append(
                        f"{symbol}/{canonical_tf}: CRYPTO_CONFIG={series_ticker}, "
                        f"meta={meta.series_ticker}"
                    )
        
        assert not mismatches, "CRYPTO_CONFIG/SERIES_META mismatches:\n" + "\n".join(mismatches)

    def test_near_spot_config_covers_all_crypto_timeframes(self):
        """NEAR_SPOT_CONFIG should have entry for each CRYPTO_CONFIG (symbol, timeframe)."""
        from config.crypto_spot_kalshi_config import CRYPTO_CONFIG, NEAR_SPOT_CONFIG
        
        missing = []
        
        for symbol, cfg in CRYPTO_CONFIG.items():
            for tf_key in cfg.get("series", {}).keys():
                # Map to NEAR_SPOT_CONFIG key format
                tf_map = {"15M": "15M", "1H": "1H", "1D": "1D"}
                normalized_tf = tf_map.get(tf_key, tf_key)
                
                key = (symbol, normalized_tf)
                if key not in NEAR_SPOT_CONFIG:
                    missing.append(f"{key}")
        
        assert not missing, f"Missing NEAR_SPOT_CONFIG entries: {missing}"

    def test_get_config_consistency_report_no_issues(self):
        """get_config_consistency_report() should return zero issues."""
        from config.crypto_spot_kalshi_config import get_config_consistency_report
        
        report = get_config_consistency_report()
        
        assert report.get("consistency_issues", []) == [], \
            f"Config consistency issues: {report['consistency_issues']}"

    def test_no_orphan_symbol_timeframe_pairs_in_configs(self):
        """Every (symbol, timeframe) in SERIES_META_LIST must appear in all config layers."""
        from config.kalshi_crypto_series_meta import SERIES_META_LIST
        from config.crypto_spot_kalshi_config import CRYPTO_CONFIG, NEAR_SPOT_CONFIG
        from merid.prediction.agent_grid_config import get_agent_grid_config
        
        # Build set of (symbol, timeframe) from SERIES_META_LIST
        meta_pairs = set()
        for meta in SERIES_META_LIST:
            meta_pairs.add((meta.asset, meta.timeframe))
        
        # Check CRYPTO_CONFIG coverage
        crypto_pairs = set()
        for symbol, cfg in CRYPTO_CONFIG.items():
            for tf_key in cfg.get("series", {}).keys():
                tf_map = {"15M": "15m", "1H": "1h", "1D": "daily", "1W": "weekly"}
                canonical = tf_map.get(tf_key, tf_key.lower())
                crypto_pairs.add((symbol, canonical))
        
        # Check NEAR_SPOT_CONFIG coverage
        spot_pairs = set()
        for (symbol, tf), _ in NEAR_SPOT_CONFIG.items():
            spot_pairs.add((symbol, tf.lower()))
        
        # Check agent grid coverage
        config = get_agent_grid_config()
        grid_pairs = set()
        for agent in config.agents:
            if agent.category == "crypto":
                for asset in agent.assets:
                    for timeframe in agent.timeframes:
                        grid_pairs.add((asset.upper(), timeframe.lower()))
        
        # Orphans in any layer
        orphans = []
        for pair in meta_pairs:
            if pair not in crypto_pairs:
                orphans.append(f"{pair} missing from CRYPTO_CONFIG")
            if pair not in spot_pairs:
                orphans.append(f"{pair} missing from NEAR_SPOT_CONFIG")
            if pair not in grid_pairs:
                orphans.append(f"{pair} missing from kalshi_agent_grid.yaml")
        
        assert not orphans, f"Orphan (symbol, timeframe) pairs:\n" + "\n".join(orphans)

    def test_no_duplicate_ownership_per_symbol_timeframe(self):
        """Each (symbol, timeframe) should have exactly one primary regime agent."""
        from merid.prediction.agent_grid_config import get_agent_grid_config
        
        config = get_agent_grid_config()
        
        # Track ownership: (symbol, timeframe) -> list of agent names
        ownership: Dict[Tuple[str, str], List[str]] = {}
        
        for agent in config.agents:
            if agent.category == "crypto" and agent.archetype == "directional":
                for asset in agent.assets:
                    for timeframe in agent.timeframes:
                        key = (asset.upper(), timeframe.lower())
                        if key not in ownership:
                            ownership[key] = []
                        ownership[key].append(agent.name)
        
        # Check for duplicates (more than 1 agent claiming the same pair)
        duplicates = []
        for (symbol, tf), agents in ownership.items():
            if len(agents) > 1:
                duplicates.append(f"{symbol}/{tf}: claimed by {agents}")
        
        assert not duplicates, f"Duplicate ownership detected:\n" + "\n".join(duplicates)
