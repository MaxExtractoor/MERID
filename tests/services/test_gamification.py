"""Tests for services/gamification.py."""
import pytest
import time
from unittest.mock import Mock, patch
from services.gamification import (
    XpEvent, GamificationEngine
)


class TestXpEvent:
    """Test XpEvent dataclass."""

    def test_creation(self):
        """Test XpEvent creation."""
        event = XpEvent(
            user="test_user",
            xp=100,
            reason="completed_trade",
            timestamp=1234567890.0,
            metadata={"symbol": "BTC/USD"}
        )
        assert event.user == "test_user"
        assert event.xp == 100
        assert event.reason == "completed_trade"
        assert event.metadata["symbol"] == "BTC/USD"


class TestGamificationEngineInitialization:
    """Test GamificationEngine initialization."""

    def test_default_initialization(self):
        """Test default initialization."""
        engine = GamificationEngine()
        assert engine.base_xp == 50
        assert engine._xp == {}
        assert engine._events == []

    def test_custom_base_xp(self):
        """Test initialization with custom base XP."""
        engine = GamificationEngine(base_xp=100)
        assert engine.base_xp == 100


class TestGamificationEngineAwardXp:
    """Test award_xp method."""

    def test_award_xp_basic(self):
        """Test basic XP award."""
        engine = GamificationEngine(base_xp=50)
        xp_gain = engine.award_xp("user1", 1.0, "first_trade")
        
        assert xp_gain == 50
        assert engine._xp["user1"] == 50
        assert len(engine._events) == 1

    def test_award_xp_with_multiplier(self):
        """Test XP award with multiplier."""
        engine = GamificationEngine(base_xp=50)
        xp_gain = engine.award_xp("user1", 2.0, "streak_bonus")
        
        assert xp_gain == 100
        assert engine._xp["user1"] == 100

    def test_award_xp_with_metadata(self):
        """Test XP award with metadata."""
        engine = GamificationEngine(base_xp=50)
        xp_gain = engine.award_xp(
            "user1", 
            1.5, 
            "profitable_trade",
            metadata={"profit": "100", "symbol": "BTC/USD"}
        )
        
        assert xp_gain == 75
        assert engine._events[0].metadata["profit"] == "100"

    def test_award_xp_accumulation(self):
        """Test XP accumulation for same user."""
        engine = GamificationEngine(base_xp=50)
        engine.award_xp("user1", 1.0, "first_trade")
        engine.award_xp("user1", 1.0, "second_trade")
        
        assert engine._xp["user1"] == 100
        assert len(engine._events) == 2

    def test_award_xp_minimum(self):
        """Test XP award minimum of 1."""
        engine = GamificationEngine(base_xp=50)
        xp_gain = engine.award_xp("user1", 0.01, "tiny_action")
        
        assert xp_gain == 1


class TestGamificationEngineLeaderboard:
    """Test leaderboard method."""

    def test_empty_leaderboard(self):
        """Test leaderboard with no users."""
        engine = GamificationEngine()
        board = engine.leaderboard()
        
        assert board == []

    def test_leaderboard_sorted(self):
        """Test leaderboard is sorted by XP."""
        engine = GamificationEngine(base_xp=50)
        engine.award_xp("user1", 1.0, "trade")  # 50 XP
        engine.award_xp("user2", 3.0, "trade")  # 150 XP
        engine.award_xp("user3", 2.0, "trade")  # 100 XP
        
        board = engine.leaderboard()
        
        assert len(board) == 3
        assert board[0]["user"] == "user2"
        assert board[0]["xp"] == 150
        assert board[1]["user"] == "user3"
        assert board[2]["user"] == "user1"

    def test_leaderboard_limit(self):
        """Test leaderboard with limit."""
        engine = GamificationEngine(base_xp=50)
        for i in range(25):
            engine.award_xp(f"user{i}", 1.0, "trade")
        
        board = engine.leaderboard(limit=10)
        
        assert len(board) == 10


class TestGamificationEngineXpFor:
    """Test xp_for method."""

    def test_xp_for_existing_user(self):
        """Test getting XP for existing user."""
        engine = GamificationEngine(base_xp=50)
        engine.award_xp("user1", 2.0, "trade")
        
        xp = engine.xp_for("user1")
        assert xp == 100

    def test_xp_for_new_user(self):
        """Test getting XP for new user."""
        engine = GamificationEngine()
        
        xp = engine.xp_for("new_user")
        assert xp == 0


class TestGamificationEngineEvents:
    """Test events methods."""

    def test_events_all(self):
        """Test getting all events."""
        engine = GamificationEngine(base_xp=50)
        engine.award_xp("user1", 1.0, "trade1")
        engine.award_xp("user2", 1.0, "trade2")
        
        events = engine.events()
        
        assert len(events) == 2

    def test_events_limit(self):
        """Test events with limit."""
        engine = GamificationEngine(base_xp=50)
        for i in range(60):
            engine.award_xp("user1", 1.0, f"trade{i}")
        
        events = engine.events(limit=10)
        
        assert len(events) == 10

    def test_events_for_user(self):
        """Test getting events for specific user."""
        engine = GamificationEngine(base_xp=50)
        engine.award_xp("user1", 1.0, "trade1")
        engine.award_xp("user2", 1.0, "trade2")
        engine.award_xp("user1", 1.0, "trade3")
        
        events = engine.events_for("user1")
        
        assert len(events) == 2
        assert all(e["user"] == "user1" for e in events)

    def test_events_for_user_limit(self):
        """Test events_for with limit."""
        engine = GamificationEngine(base_xp=50)
        for i in range(60):
            engine.award_xp("user1", 1.0, f"trade{i}")
        
        events = engine.events_for("user1", limit=10)
        
        assert len(events) == 10

    def test_events_returns_dicts(self):
        """Test that events returns list of dicts."""
        engine = GamificationEngine(base_xp=50)
        engine.award_xp("user1", 1.0, "trade", metadata={"key": "value"})
        
        events = engine.events()
        
        assert isinstance(events[0], dict)
        assert "user" in events[0]
        assert "xp" in events[0]
        assert "reason" in events[0]
        assert "timestamp" in events[0]
        assert "metadata" in events[0]
