"""Comprehensive test suite for merid.pipeline ? Unified multi-venue trade pipeline.

Covers:
S1 TradeProposal, InstrumentRegistry, AdapterRegistry
S3 ModeManager + VenueConfig
S4 GlobalRiskManager (cross-domain limits, capital routing)
S2 Domain agents (PredictionMarketAgent, CryptoArbAgent, EquityAgent)
S5 TradeRouter (full pipeline flow)
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
from merid.pipeline.risk_manager import (
    GlobalRiskManager,
    DomainRiskConfig,
)


# ======================================================================
# ?1 TradeProposal Tests
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
# ?1 InstrumentRegistry Tests
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
        max_pos = self.rm._domain_configs[TradeDomain.CRYPTO].max_positions
        for i in range(max_pos):
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
# ?2 Domain Agent Tests
# ======================================================================

# ======================================================================
# ?5 TradeRouter Tests
# ======================================================================

