"""Tests for core/copy_trading.py."""
import pytest
from decimal import Decimal
from datetime import datetime
from core.copy_trading import (
    TraderTier, TraderProfile, CopyTrade, WhaleWatcher, CopyTradingEngine,
    whale_watcher, copy_engine
)


class TestTraderTier:
    """Test TraderTier enum."""

    def test_tier_values(self):
        """Test TraderTier enum values."""
        assert TraderTier.WHALE == "whale"
        assert TraderTier.PRO == "pro"
        assert TraderTier.PROFITABLE == "profitable"
        assert TraderTier.EXPERIMENTAL == "experimental"


class TestTraderProfile:
    """Test TraderProfile dataclass."""

    def test_creation(self):
        """Test TraderProfile creation."""
        profile = TraderProfile(
            wallet_address="0x123abc",
            tier=TraderTier.WHALE,
            win_rate=0.75,
            profit_factor=Decimal("2.5"),
            avg_trade_size=Decimal("10000"),
            total_pnl=Decimal("50000"),
            followers=100,
            trades_30d=50,
            sharpe_ratio=1.5
        )
        assert profile.wallet_address == "0x123abc"
        assert profile.tier == TraderTier.WHALE
        assert profile.win_rate == 0.75


class TestCopyTrade:
    """Test CopyTrade dataclass."""

    def test_creation(self):
        """Test CopyTrade creation."""
        trade = CopyTrade(
            original_trader="0x123abc",
            symbol="SOL",
            side="buy",
            size=Decimal("100"),
            entry_price=Decimal("20.00"),
            copied_at=datetime.now(),
            status="pending"
        )
        assert trade.original_trader == "0x123abc"
        assert trade.symbol == "SOL"
        assert trade.side == "buy"
        assert trade.status == "pending"


class TestWhaleWatcher:
    """Test WhaleWatcher class."""

    @pytest.mark.asyncio
    async def test_add_whale(self):
        """Test adding whale to monitor."""
        watcher = WhaleWatcher()
        await watcher.add_whale("0x123abc", TraderTier.WHALE)
        assert "0x123abc" in watcher.monitored_whales
        assert watcher.monitored_whales["0x123abc"].tier == TraderTier.WHALE

    @pytest.mark.asyncio
    async def test_scan_whale_transactions(self):
        """Test scanning whale transactions."""
        watcher = WhaleWatcher()
        await watcher.add_whale("0x123abc")
        signals = await watcher.scan_whale_transactions()
        assert len(signals) == 1
        assert signals[0]["wallet"] == "0x123abc"[:8]
        assert signals[0]["action"] == "buy"


class TestCopyTradingEngine:
    """Test CopyTradingEngine class."""

    def test_initialization(self):
        """Test engine initialization."""
        engine = CopyTradingEngine()
        assert engine.max_position == Decimal("5000")
        assert engine.copy_ratio == Decimal("0.1")

    def test_initialization_with_watcher(self):
        """Test engine initialization with custom watcher."""
        watcher = WhaleWatcher()
        engine = CopyTradingEngine(watcher)
        assert engine.whale_watcher is watcher

    @pytest.mark.asyncio
    async def test_mirror_trade(self):
        """Test mirroring a trade."""
        engine = CopyTradingEngine()
        result = await engine.mirror_trade(
            whale_wallet="0x123abc",
            symbol="SOL",
            side="buy",
            whale_size=Decimal("10000"),
            price=Decimal("20.00")
        )
        assert result["status"] == "executed"
        assert result["symbol"] == "SOL"
        assert result["side"] == "buy"
        # Should copy 10% of whale size or max position limit
        assert "size" in result
        assert len(engine.copied_trades) == 1

    @pytest.mark.asyncio
    async def test_mirror_trade_respects_max_position(self):
        """Test mirror trade respects max position limit."""
        engine = CopyTradingEngine()
        # Whale size would suggest 1000, but max is 5000/200 = 25
        result = await engine.mirror_trade(
            whale_wallet="0x123abc",
            symbol="BTC",
            side="buy",
            whale_size=Decimal("100000"),
            price=Decimal("200.00")
        )
        # Copy size should be limited
        copy_size = Decimal(result["size"])
        assert copy_size <= Decimal("25")


class TestGlobalInstances:
    """Test global instances."""

    def test_whales_watcher_exists(self):
        """Test global whale_watcher exists."""
        assert whale_watcher is not None
        assert isinstance(whale_watcher, WhaleWatcher)

    def test_copy_engine_exists(self):
        """Test global copy_engine exists."""
        assert copy_engine is not None
        assert isinstance(copy_engine, CopyTradingEngine)
