"""Comprehensive test suite for merid.pipeline — Unified multi-venue trade pipeline.

Covers:
§1 TradeProposal, InstrumentRegistry, AdapterRegistry
§3 ModeManager + VenueConfig
§4 GlobalRiskManager (cross-domain limits, capital routing)
§2 Domain agents (PredictionMarketAgent, CryptoArbAgent, EquityAgent)
§5 TradeRouter (full pipeline flow)
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from merid.pipeline.proposal import (
    TradeDomain,
    TradeProposal,
    ProposalStatus,
    ExecutionResult,
    OrderSide,
    OrderType,
)
from merid.pipeline.adapter import AdapterRegistry, UnifiedVenueAdapter
from merid.pipeline.instruments import (
    Instrument,
    InstrumentRegistry,
    build_default_registry,
)
from merid.pipeline.mode_manager import (
    ModeManager,
    VenueConfig,
    TradingMode,
)
from merid.pipeline.risk_manager import (
    GlobalRiskManager,
    DomainRiskConfig,
)
from merid.pipeline.router import TradeRouter
from merid.pipeline.domain_agents import (
    PredictionMarketAgent,
    CryptoArbAgent,
    FundingArbAgent,
    EquityAgent,
)


# ======================================================================
# §1 TradeProposal Tests
# ======================================================================

class TestTradeProposal:

    def test_default_proposal(self):
        p = TradeProposal()
        assert p.status == ProposalStatus.PENDING
        assert p.domain == TradeDomain.CRYPTO
        assert p.proposal_id  # auto-generated

    def test_proposal_approve(self):
        p = TradeProposal()
        p.approve()
        assert p.status == ProposalStatus.RISK_APPROVED
        assert p.updated_at is not None

    def test_proposal_reject(self):
        p = TradeProposal()
        p.reject("Too risky")
        assert p.status == ProposalStatus.RISK_REJECTED
        assert p.risk_check_result["reason"] == "Too risky"

    def test_proposal_to_dict(self):
        p = TradeProposal(
            venue="binance", instrument_id="BTC-USD",
            side=OrderSide.BUY, qty=Decimal("0.1"),
            price=Decimal("50000"),
        )
        d = p.to_dict()
        assert d["venue"] == "binance"
        assert d["side"] == "buy"
        assert d["qty"] == "0.1"

    def test_execution_result_to_dict(self):
        r = ExecutionResult(
            proposal_id="abc", venue="binance",
            venue_order_id="ORD-123", status="filled",
            filled_qty=Decimal("0.1"), avg_price=Decimal("50000"),
        )
        d = r.to_dict()
        assert d["status"] == "filled"
        assert d["venue_order_id"] == "ORD-123"

    def test_trade_domains(self):
        assert TradeDomain.PREDICTION.value == "prediction"
        assert TradeDomain.CRYPTO.value == "crypto"
        assert TradeDomain.EQUITY.value == "equity"
        assert TradeDomain.MACRO.value == "macro"


# ======================================================================
# §1 InstrumentRegistry Tests
# ======================================================================

class TestInstrumentRegistry:

    def test_register_and_resolve(self):
        reg = InstrumentRegistry()
        reg.register(Instrument(
            merid_symbol="BTC-USD", domain="crypto",
            venue_symbols={"binance": "BTCUSDT", "coinbase": "BTC-USD"},
        ))
        assert reg.resolve("BTC-USD", "binance") == "BTCUSDT"
        assert reg.resolve("BTC-USD", "coinbase") == "BTC-USD"
        assert reg.resolve("BTC-USD", "kraken") is None

    def test_reverse_lookup(self):
        reg = InstrumentRegistry()
        reg.register(Instrument(
            merid_symbol="ETH-USD", domain="crypto",
            venue_symbols={"binance": "ETHUSDT"},
        ))
        assert reg.reverse_lookup("binance", "ETHUSDT") == "ETH-USD"
        assert reg.reverse_lookup("binance", "UNKNOWN") is None

    def test_by_domain(self):
        reg = InstrumentRegistry()
        reg.register(Instrument(merid_symbol="BTC-USD", domain="crypto", venue_symbols={"binance": "BTCUSDT"}))
        reg.register(Instrument(merid_symbol="AAPL", domain="equity", venue_symbols={"alpaca": "AAPL"}))
        assert len(reg.by_domain("crypto")) == 1
        assert len(reg.by_domain("equity")) == 1

    def test_by_venue(self):
        reg = InstrumentRegistry()
        reg.register(Instrument(merid_symbol="BTC-USD", domain="crypto", venue_symbols={"binance": "BTCUSDT"}))
        reg.register(Instrument(merid_symbol="ETH-USD", domain="crypto", venue_symbols={"binance": "ETHUSDT", "coinbase": "ETH-USD"}))
        assert len(reg.by_venue("binance")) == 2
        assert len(reg.by_venue("coinbase")) == 1

    def test_compliance_check(self):
        reg = InstrumentRegistry()
        reg.register(Instrument(
            merid_symbol="PM:FED", domain="prediction",
            venue_symbols={"kalshi": "FED"},
            compliance_flags={"polymarket": False},
        ))
        assert reg.check_compliance("PM:FED", "kalshi") is True
        assert reg.check_compliance("PM:FED", "polymarket") is False

    def test_all_symbols(self):
        reg = InstrumentRegistry()
        reg.register(Instrument(merid_symbol="A", domain="crypto", venue_symbols={}))
        reg.register(Instrument(merid_symbol="B", domain="equity", venue_symbols={}))
        assert sorted(reg.all_symbols()) == ["A", "B"]

    def test_venues_for(self):
        reg = InstrumentRegistry()
        reg.register(Instrument(
            merid_symbol="BTC-USD", domain="crypto",
            venue_symbols={"binance": "BTCUSDT", "kraken": "XXBTZUSD"},
        ))
        assert sorted(reg.venues_for("BTC-USD")) == ["binance", "kraken"]
        assert reg.venues_for("UNKNOWN") == []

    def test_summary(self):
        reg = build_default_registry()
        s = reg.summary()
        assert s["total_instruments"] > 0
        assert "crypto" in s["domains"]
        assert "equity" in s["domains"]

    def test_default_registry_has_crypto(self):
        reg = build_default_registry()
        assert reg.resolve("BTC-USD", "binance") == "BTCUSDT"

    def test_default_registry_has_equities(self):
        reg = build_default_registry()
        assert reg.resolve("AAPL", "alpaca") == "AAPL"


# ======================================================================
# §1 AdapterRegistry Tests
# ======================================================================

class TestAdapterRegistry:

    def _mock_adapter(self, name="test", domain="crypto"):
        adapter = MagicMock(spec=UnifiedVenueAdapter)
        adapter.venue_name = name
        adapter.domain = domain
        adapter.supports_trading = True
        return adapter

    def test_register_and_get(self):
        reg = AdapterRegistry()
        adapter = self._mock_adapter("binance")
        reg.register(adapter)
        assert reg.get("binance") is adapter
        assert reg.get("unknown") is None

    def test_list_venues(self):
        reg = AdapterRegistry()
        reg.register(self._mock_adapter("binance"))
        reg.register(self._mock_adapter("coinbase"))
        venues = sorted(reg.list_venues())
        assert "binance" in venues
        assert "coinbase" in venues

    def test_by_domain(self):
        reg = AdapterRegistry()
        reg.register(self._mock_adapter("binance", "crypto"))
        reg.register(self._mock_adapter("alpaca", "equity"))
        assert len(reg.by_domain("crypto")) == 1
        assert len(reg.by_domain("equity")) == 1

    def test_summary(self):
        reg = AdapterRegistry()
        reg.register(self._mock_adapter("binance"))
        s = reg.summary()
        assert len(s) >= 1
        venues = [item["venue"] for item in s]
        assert "binance" in venues


# ======================================================================
# §3 ModeManager Tests
# ======================================================================

class TestModeManager:

    def test_default_venues(self):
        mm = ModeManager()
        venues = mm.list_venues()
        assert "kalshi" in venues
        assert "binance" in venues
        assert "alpaca" in venues

    def test_get_config(self):
        mm = ModeManager()
        cfg = mm.get_config("kalshi")
        assert cfg is not None
        assert cfg.domain == "prediction"

    def test_set_venue_mode(self):
        mm = ModeManager()
        mm.set_venue_mode("binance", TradingMode.PAPER)
        cfg = mm.get_config("binance")
        assert cfg.mode == TradingMode.PAPER

    def test_set_venue_mode_unknown(self):
        mm = ModeManager()
        with pytest.raises(ValueError, match="Unknown venue"):
            mm.set_venue_mode("unknown_venue", TradingMode.PAPER)

    def test_check_can_trade_sim_blocked(self):
        cfg = [VenueConfig(venue="testv", domain="crypto", mode=TradingMode.SIM, enabled=True)]
        mm = ModeManager(configs=cfg)
        with pytest.raises(ModeManager.ModeBlockedError, match="SIM"):
            mm.check_can_trade("testv")

    def test_check_can_trade_paper_ok(self):
        mm = ModeManager()
        mm.set_venue_mode("binance", TradingMode.PAPER)
        mm.check_can_trade("binance")  # should not raise

    def test_disable_venue(self):
        mm = ModeManager()
        mm.disable_venue("binance")
        with pytest.raises(ModeManager.VenueDisabledError, match="disabled"):
            mm.check_can_trade("binance")

    def test_enable_venue(self):
        mm = ModeManager()
        mm.disable_venue("binance")
        mm.enable_venue("binance")
        mm.set_venue_mode("binance", TradingMode.PAPER)
        mm.check_can_trade("binance")  # should not raise

    def test_disable_domain(self):
        mm = ModeManager()
        mm.set_venue_mode("binance", TradingMode.PAPER)
        mm.disable_domain("crypto")
        with pytest.raises(ModeManager.VenueDisabledError, match="Domain"):
            mm.check_can_trade("binance")

    def test_enable_domain(self):
        mm = ModeManager()
        mm.disable_domain("crypto")
        mm.enable_domain("crypto")
        assert mm.is_domain_enabled("crypto") is True

    def test_should_simulate_sim(self):
        mm = ModeManager()
        assert mm.should_simulate("binance") is True  # default SIM

    def test_should_simulate_paper(self):
        mm = ModeManager()
        mm.set_venue_mode("binance", TradingMode.PAPER)
        assert mm.should_simulate("binance") is True

    def test_should_simulate_live(self):
        mm = ModeManager()
        mm.set_venue_mode("binance", TradingMode.LIVE)
        assert mm.should_simulate("binance") is False

    def test_should_simulate_unknown(self):
        mm = ModeManager()
        assert mm.should_simulate("unknown") is True

    def test_venues_by_domain(self):
        mm = ModeManager()
        crypto = mm.venues_by_domain("crypto")
        assert len(crypto) >= 3  # binance, coinbase, kraken, okx

    def test_venue_config_has_credentials(self):
        cfg = VenueConfig(venue="test", domain="crypto", api_key_env="NONEXISTENT_KEY_12345")
        assert cfg.has_credentials() is False

    def test_venue_config_to_dict(self):
        cfg = VenueConfig(venue="test", domain="crypto")
        d = cfg.to_dict()
        assert d["venue"] == "test"
        assert d["domain"] == "crypto"

    def test_summary(self):
        mm = ModeManager()
        s = mm.summary()
        assert "venues" in s
        assert "disabled_domains" in s


# ======================================================================
# §4 GlobalRiskManager Tests
# ======================================================================

class TestGlobalRiskManager:

    def setup_method(self):
        self.rm = GlobalRiskManager(
            total_capital_usd=Decimal("50000"),
            max_portfolio_notional_usd=Decimal("50000"),
        )

    def test_proposal_approved(self):
        p = TradeProposal(
            domain=TradeDomain.CRYPTO, venue="binance",
            qty=Decimal("0.1"), price=Decimal("50000"),
            notional_usd=Decimal("5000"),
        )
        result = self.rm.check_proposal(p)
        assert result.approved is True

    def test_single_order_too_large(self):
        p = TradeProposal(
            domain=TradeDomain.CRYPTO, venue="binance",
            notional_usd=Decimal("10000"),  # > max_single_order_usd for crypto (5000)
        )
        result = self.rm.check_proposal(p)
        assert result.approved is False
        assert "exceeds domain max" in result.reason

    def test_domain_notional_limit(self):
        # Fill up crypto domain
        self.rm.record_fill("binance", "crypto", Decimal("24000"))
        p = TradeProposal(
            domain=TradeDomain.CRYPTO, venue="coinbase",
            notional_usd=Decimal("2000"),
        )
        result = self.rm.check_proposal(p)
        assert result.approved is False
        assert "would exceed max" in result.reason

    def test_domain_daily_loss_limit(self):
        self.rm.record_close("binance", "crypto", Decimal("5000"), Decimal("-1100"))
        p = TradeProposal(
            domain=TradeDomain.CRYPTO, venue="binance",
            notional_usd=Decimal("100"),
        )
        result = self.rm.check_proposal(p)
        assert result.approved is False
        assert "daily loss" in result.reason

    def test_domain_position_limit(self):
        for i in range(30):
            self.rm.record_fill(f"venue-{i}", "crypto", Decimal("10"))
        p = TradeProposal(
            domain=TradeDomain.CRYPTO, venue="binance",
            notional_usd=Decimal("100"),
        )
        result = self.rm.check_proposal(p)
        assert result.approved is False
        assert "positions" in result.reason

    def test_portfolio_notional_limit(self):
        self.rm.record_fill("binance", "crypto", Decimal("25000"))
        self.rm.record_fill("alpaca", "equity", Decimal("19000"))
        p = TradeProposal(
            domain=TradeDomain.EQUITY, venue="alpaca",
            notional_usd=Decimal("2000"),  # within single-order limit
        )
        # Portfolio = 25000 + 19000 + 2000 = 46000; equity domain = 19000 + 2000 = 21000 > 20000
        # Hits domain notional limit first
        result = self.rm.check_proposal(p)
        assert result.approved is False
        assert "would exceed max" in result.reason

    def test_capital_allocation_limit(self):
        # Prediction max is 10% of 50000 = 5000, max_single_order = 500
        self.rm.record_fill("kalshi", "prediction", Decimal("4600"))
        p = TradeProposal(
            domain=TradeDomain.PREDICTION, venue="kalshi",
            notional_usd=Decimal("500"),  # within single-order limit
        )
        # 4600 + 500 = 5100 > 5000 (max notional for prediction)
        result = self.rm.check_proposal(p)
        assert result.approved is False
        assert "would exceed max" in result.reason

    def test_domain_halted(self):
        self.rm.halt_domain("crypto", "Market crash")
        p = TradeProposal(
            domain=TradeDomain.CRYPTO, venue="binance",
            notional_usd=Decimal("100"),
        )
        result = self.rm.check_proposal(p)
        assert result.approved is False
        assert "halted" in result.reason

    def test_domain_resume(self):
        self.rm.halt_domain("crypto", "Test")
        self.rm.resume_domain("crypto")
        assert self.rm.is_domain_halted("crypto") is False

    def test_available_capital(self):
        avail = self.rm.available_capital(TradeDomain.CRYPTO)
        # min(50000 * 0.50, 25000) = 25000
        assert avail == Decimal("25000")

    def test_available_capital_with_exposure(self):
        self.rm.record_fill("binance", "crypto", Decimal("10000"))
        avail = self.rm.available_capital(TradeDomain.CRYPTO)
        assert avail == Decimal("15000")

    def test_record_fill_and_close(self):
        self.rm.record_fill("binance", "crypto", Decimal("5000"))
        assert self.rm.domain_notional("crypto") == Decimal("5000")
        self.rm.record_close("binance", "crypto", Decimal("5000"), Decimal("200"))
        assert self.rm.domain_notional("crypto") == Decimal("0")

    def test_update_unrealized(self):
        self.rm.record_fill("binance", "crypto", Decimal("5000"))
        self.rm.update_unrealized("binance", Decimal("300"))
        exp = self.rm._exposures["binance"]
        assert exp.unrealized_pnl_usd == Decimal("300")

    def test_summary(self):
        self.rm.record_fill("binance", "crypto", Decimal("5000"))
        s = self.rm.summary()
        assert s["total_capital_usd"] == "50000"
        assert "crypto" in s["domains"]
        assert len(s["venue_exposures"]) == 1

    def test_domain_disabled(self):
        cfg = self.rm._domain_configs[TradeDomain.MACRO]
        cfg.enabled = False
        p = TradeProposal(
            domain=TradeDomain.MACRO, venue="alpaca",
            notional_usd=Decimal("100"),
        )
        result = self.rm.check_proposal(p)
        assert result.approved is False
        assert "disabled" in result.reason


# ======================================================================
# §2 Domain Agent Tests
# ======================================================================

class TestDomainAgents:

    def test_prediction_agent_create(self):
        agent = PredictionMarketAgent()
        assert agent.domain == TradeDomain.PREDICTION
        assert agent.is_active is True

    def test_prediction_agent_pause_resume(self):
        agent = PredictionMarketAgent()
        agent.pause()
        assert agent.is_active is False
        agent.resume()
        assert agent.is_active is True

    def test_prediction_agent_watch(self):
        agent = PredictionMarketAgent()
        agent.watch_market("FED-25DEC")
        assert "FED-25DEC" in agent._watched_markets
        agent.unwatch_market("FED-25DEC")
        assert "FED-25DEC" not in agent._watched_markets

    def test_prediction_agent_create_proposal(self):
        agent = PredictionMarketAgent()
        p = agent.create_pm_proposal(
            market_id="FED-25DEC", side="buy_yes",
            contracts=10, price_cents=55,
        )
        assert p.domain == TradeDomain.PREDICTION
        assert p.venue == "kalshi"
        assert p.qty == Decimal("10")
        assert "prediction" in p.risk_tags

    @pytest.mark.asyncio
    async def test_prediction_agent_generate_empty(self):
        agent = PredictionMarketAgent()
        proposals = await agent.generate_proposals()
        assert proposals == []

    @pytest.mark.asyncio
    async def test_prediction_agent_paused_no_proposals(self):
        agent = PredictionMarketAgent()
        agent.pause()
        proposals = await agent.generate_proposals()
        assert proposals == []

    def test_crypto_arb_agent_create(self):
        agent = CryptoArbAgent()
        assert agent.domain == TradeDomain.CRYPTO
        assert "binance" in agent.venues

    def test_crypto_arb_agent_watch_pair(self):
        agent = CryptoArbAgent()
        agent.watch_pair("DOGE-USD")
        assert "DOGE-USD" in agent._watched_pairs

    def test_crypto_arb_create_pair(self):
        agent = CryptoArbAgent()
        pair = agent.create_arb_pair(
            merid_symbol="BTC-USD",
            buy_venue="binance", sell_venue="coinbase",
            buy_price=Decimal("50000"), sell_price=Decimal("50200"),
            qty=Decimal("0.1"),
        )
        assert len(pair) == 2
        assert pair[0].side == OrderSide.BUY
        assert pair[1].side == OrderSide.SELL
        assert pair[0].venue == "binance"
        assert pair[1].venue == "coinbase"

    def test_funding_arb_agent(self):
        agent = FundingArbAgent()
        assert agent.domain == TradeDomain.CRYPTO

    def test_equity_agent_create(self):
        agent = EquityAgent()
        assert agent.domain == TradeDomain.EQUITY
        assert agent.venue == "alpaca"

    def test_equity_agent_watchlist(self):
        agent = EquityAgent()
        agent.set_watchlist(["TSLA", "NVDA"])
        assert agent._watchlist == ["TSLA", "NVDA"]

    def test_equity_agent_create_proposal(self):
        agent = EquityAgent()
        p = agent.create_equity_proposal(
            symbol="AAPL", side="buy",
            qty=Decimal("10"), price=Decimal("180"),
        )
        assert p.domain == TradeDomain.EQUITY
        assert p.venue == "alpaca"
        assert p.instrument_id == "AAPL"

    def test_agent_summary(self):
        agent = PredictionMarketAgent()
        agent.create_pm_proposal("X", "buy", 1, 50)
        s = agent.summary()
        assert s["proposals_generated"] == 1
        assert s["domain"] == "prediction"


# ======================================================================
# §5 TradeRouter Tests
# ======================================================================

class TestTradeRouter:

    def _build_router(self):
        instruments = InstrumentRegistry()
        instruments.register(Instrument(
            merid_symbol="BTC-USD", domain="crypto",
            venue_symbols={"binance": "BTCUSDT"},
        ))
        instruments.register(Instrument(
            merid_symbol="AAPL", domain="equity",
            venue_symbols={"alpaca": "AAPL"},
        ))

        mm = ModeManager()
        mm.set_venue_mode("binance", TradingMode.PAPER)
        mm.set_venue_mode("alpaca", TradingMode.PAPER)

        rm = GlobalRiskManager(total_capital_usd=Decimal("50000"))
        adapters = AdapterRegistry()

        return TradeRouter(
            registry=adapters,
            instruments=instruments,
            mode_manager=mm,
            risk_manager=rm,
        )

    @pytest.mark.asyncio
    async def test_simulated_fill(self):
        router = self._build_router()
        p = TradeProposal(
            domain=TradeDomain.CRYPTO, venue="binance",
            instrument_id="BTC-USD", side=OrderSide.BUY,
            qty=Decimal("0.1"), price=Decimal("50000"),
            notional_usd=Decimal("5000"),
        )
        result = await router.submit(p)
        assert result.status == ProposalStatus.FILLED
        assert result.execution_result is not None
        assert result.execution_result.status == "filled"
        assert result.native_symbol == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_instrument_not_found(self):
        router = self._build_router()
        p = TradeProposal(
            domain=TradeDomain.CRYPTO, venue="binance",
            instrument_id="UNKNOWN-COIN",
        )
        result = await router.submit(p)
        assert result.status == ProposalStatus.RISK_REJECTED
        assert "Cannot resolve" in result.risk_check_result["reason"]

    @pytest.mark.asyncio
    async def test_mode_blocked(self):
        router = self._build_router()
        # kalshi is still SIM by default
        p = TradeProposal(
            domain=TradeDomain.PREDICTION, venue="kalshi",
            native_symbol="FED-25DEC",
            qty=Decimal("10"), price=Decimal("55"),
            notional_usd=Decimal("55"),
        )
        result = await router.submit(p)
        assert result.status == ProposalStatus.RISK_REJECTED
        assert "SIM" in str(result.risk_check_result)

    @pytest.mark.asyncio
    async def test_risk_rejected(self):
        router = self._build_router()
        # Exceed single order limit for crypto ($5000)
        p = TradeProposal(
            domain=TradeDomain.CRYPTO, venue="binance",
            instrument_id="BTC-USD",
            notional_usd=Decimal("10000"),
        )
        result = await router.submit(p)
        assert result.status == ProposalStatus.RISK_REJECTED

    @pytest.mark.asyncio
    async def test_batch_submit(self):
        router = self._build_router()
        proposals = [
            TradeProposal(
                domain=TradeDomain.CRYPTO, venue="binance",
                instrument_id="BTC-USD", qty=Decimal("0.01"),
                price=Decimal("50000"), notional_usd=Decimal("500"),
            ),
            TradeProposal(
                domain=TradeDomain.EQUITY, venue="alpaca",
                instrument_id="AAPL", qty=Decimal("5"),
                price=Decimal("180"), notional_usd=Decimal("900"),
            ),
        ]
        results = await router.submit_batch(proposals)
        assert len(results) == 2
        assert all(r.status == ProposalStatus.FILLED for r in results)

    @pytest.mark.asyncio
    async def test_compliance_blocked(self):
        instruments = InstrumentRegistry()
        instruments.register(Instrument(
            merid_symbol="PM:FED", domain="prediction",
            venue_symbols={"kalshi": "FED", "polymarket": "FED"},
            compliance_flags={"polymarket": False},
        ))
        mm = ModeManager()
        mm.set_venue_mode("kalshi", TradingMode.PAPER)
        rm = GlobalRiskManager()
        router = TradeRouter(
            registry=AdapterRegistry(),
            instruments=instruments,
            mode_manager=mm,
            risk_manager=rm,
        )
        p = TradeProposal(
            domain=TradeDomain.PREDICTION, venue="polymarket",
            instrument_id="PM:FED",
            notional_usd=Decimal("100"),
        )
        result = await router.submit(p)
        assert result.status == ProposalStatus.RISK_REJECTED
        assert "not compliant" in str(result.risk_check_result)

    def test_summary(self):
        router = self._build_router()
        s = router.summary()
        assert "total_proposals" in s
        assert "adapters" in s
        assert "instruments" in s

    def test_recent_proposals(self):
        router = self._build_router()
        assert router.recent_proposals() == []
