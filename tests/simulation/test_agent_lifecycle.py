import time

import pytest

from simulation.engine import (
    MeridSimulationChain,
    SimulationFeatureConfig,
    SimulationOutcome,
    SimulationResult,
)


class _DummyTradingClient:
    def __init__(self, *_, **__):
        pass

    def fetch_markets(self, limit: int = 25):
        return []

    def find_negative_risk_opportunities(self, markets):
        return [
            {
                "slug": "unit-market",
                "platform": "polymarket",
                "yes_price": 0.55,
                "no_price": 0.45,
                "volume": 10_000,
            }
        ]


class _NoopAdapter:
    def __init__(self, *_, **__):
        pass

    def fetch_markets(self, limit: int = 10):
        return []

    def fetch_funding_rates(self):
        return []

    def fetch_whale_signals(self, limit: int = 5):
        return []


class _NoopOracle:
    def __init__(self, *_, **__):
        pass

    def fetch_feeds(self):
        return {}


class _NoopMonitor:
    def __init__(self, *_, **__):
        pass

    def fetch_signals(self, limit: int = 10):
        return []


class _NoopNews:
    def __init__(self, *_, **__):
        pass

    def fetch_headlines(self, limit: int = 5):
        return []


class _NoopOnchain:
    def __init__(self, *_, **__):
        pass

    def fetch_snapshot(self):
        return None


class _NoopCoinGlass:
    def __init__(self, *_, **__):
        pass

    def fetch_heatmap(self):
        return []


class _NoopTelegram:
    def __init__(self, *_, **__):
        pass

    def send_alert(self, *_args, **_kwargs):
        return None


@pytest.fixture
def chain(monkeypatch):
    import simulation.engine as engine_mod

    monkeypatch.setattr(engine_mod, "PolymarketClient", _DummyTradingClient)
    monkeypatch.setattr(engine_mod, "AugurTradingLayer", lambda *_, **__: _DummyTradingClient())
    monkeypatch.setattr(engine_mod, "ChainlinkOracle", _NoopOracle)
    monkeypatch.setattr(engine_mod, "WhaleIntelMonitor", _NoopMonitor)
    monkeypatch.setattr(engine_mod, "CoinGlassLiquidationMonitor", _NoopCoinGlass)
    monkeypatch.setattr(engine_mod, "NewsSentinel", _NoopNews)
    monkeypatch.setattr(engine_mod, "OnchainAnalyticsMonitor", _NoopOnchain)
    monkeypatch.setattr(engine_mod, "TelegramAlertClient", _NoopTelegram)

    # Disable perp adapters entirely by forcing builder to return empty list.
    monkeypatch.setattr(MeridSimulationChain, "_build_perp_adapters", lambda self: [])

    features = SimulationFeatureConfig(
        enable_augur=False,
        enable_chainlink=False,
        enable_news=False,
        enable_liquidations=False,
        enable_whales=False,
        enable_perp_bundle=False,
        enable_onchain_analytics=False,
    )

    return MeridSimulationChain(trading_client=_DummyTradingClient(), features=features, enable_mock=True)


def test_agent_decay_deactivates_inactive(chain: MeridSimulationChain):
    agent = next(iter(chain.agents.values()))
    agent.last_active = time.time() - 3600 * 600  # 600 hours ago
    agent.current_score = 1.0

    chain._apply_agent_decay()

    assert agent.current_score < 0.1
    assert agent.active is False


def test_spawn_rules_create_agent_when_conditions_met(chain: MeridSimulationChain):
    initial = len(chain.agents)
    result = SimulationResult(
        sim_id="spawn-test",
        model="unit",
        outcomes=[SimulationOutcome("YES", "", 1.0, 4, 0.6, "")],
        confidence=0.85,
        data={
            "arbitrage_gap": 0.08,
            "oracle_gap": 0.01,
            "funding_rate": 0.0005,
            "liquidation_bundle": {"liquidations": []},
            "news_bundle": [],
            "hybrid": False,
        },
    )

    chain._evaluate_spawn_rules(result)

    assert len(chain.agents) == initial + 1


def test_population_cap_retains_genesis_agents(chain: MeridSimulationChain):
    genesis_ids = {agent.instance_id for agent in chain.agents.values() if agent.parent_id is None}
    chain._max_agents = len(chain.agents) + 2

    parent_id = next(iter(genesis_ids))
    for _ in range(5):
        chain.spawn_agent("arbitrage_hunter", parent_id=parent_id)

    assert len(chain.agents) <= chain._max_agents
    assert genesis_ids.issubset(set(chain.agents.keys()))
