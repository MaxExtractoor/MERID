"""Tests for services/quest_campaigns.py."""
import pytest
from datetime import datetime
from services.quest_campaigns import (
    Quest, QuestProgress, QuestCampaignService
)


class TestQuest:
    """Test Quest dataclass."""

    def test_creation(self):
        """Test Quest creation."""
        quest = Quest(
            quest_id="quest_123",
            title="First Trade",
            description="Complete your first trade",
            season=1,
            reward_points=100,
            requirements={"min_volume": "1000"}
        )
        assert quest.quest_id == "quest_123"
        assert quest.title == "First Trade"
        assert quest.season == 1
        assert quest.reward_points == 100


class TestQuestProgress:
    """Test QuestProgress dataclass."""

    def test_creation(self):
        """Test QuestProgress creation."""
        progress = QuestProgress(
            quest_id="quest_123",
            user_id="user_456",
            completed=False
        )
        assert progress.quest_id == "quest_123"
        assert progress.user_id == "user_456"
        assert progress.completed is False
        assert progress.completion_timestamp is None


class TestQuestCampaignService:
    """Test QuestCampaignService class."""

    def test_initialization(self):
        """Test service initialization."""
        service = QuestCampaignService()
        assert service._quests == {}
        assert service._progress == {}

    def test_register_quest(self):
        """Test registering a quest."""
        service = QuestCampaignService()
        quest = Quest(
            quest_id="quest_1",
            title="Test Quest",
            description="A test quest",
            season=1,
            reward_points=100,
            requirements={}
        )
        service.register_quest(quest)
        
        assert "quest_1" in service._quests
        assert service._quests["quest_1"].title == "Test Quest"

    def test_record_progress_new(self):
        """Test recording progress for new user."""
        service = QuestCampaignService()
        quest = Quest(
            quest_id="quest_1",
            title="Test Quest",
            description="A test quest",
            season=1,
            reward_points=100,
            requirements={}
        )
        service.register_quest(quest)
        
        progress = service.record_progress("quest_1", "user_1", completed=True)
        
        assert progress.completed is True
        assert progress.completion_timestamp is not None
        assert "quest_1:user_1" in service._progress

    def test_record_progress_update(self):
        """Test updating existing progress."""
        service = QuestCampaignService()
        quest = Quest(
            quest_id="quest_1",
            title="Test Quest",
            description="A test quest",
            season=1,
            reward_points=100,
            requirements={}
        )
        service.register_quest(quest)
        
        # First record as not completed
        service.record_progress("quest_1", "user_1", completed=False)
        
        # Then update to completed
        progress = service.record_progress("quest_1", "user_1", completed=True)
        
        assert progress.completed is True
        assert progress.completion_timestamp is not None

    def test_season_leaderboard_empty(self):
        """Test empty season leaderboard."""
        service = QuestCampaignService()
        
        leaderboard = service.season_leaderboard(1)
        
        assert leaderboard == []

    def test_season_leaderboard(self):
        """Test season leaderboard with data."""
        service = QuestCampaignService()
        
        # Register quests
        quest1 = Quest("quest_1", "Quest 1", "Desc", 1, 100, {})
        quest2 = Quest("quest_2", "Quest 2", "Desc", 1, 200, {})
        service.register_quest(quest1)
        service.register_quest(quest2)
        
        # Record progress
        service.record_progress("quest_1", "user_1", completed=True)
        service.record_progress("quest_2", "user_1", completed=True)
        service.record_progress("quest_1", "user_2", completed=True)
        
        leaderboard = service.season_leaderboard(1)
        
        assert len(leaderboard) == 2
        # user_1 has 300 points, user_2 has 100
        assert leaderboard[0]["user_id"] == "user_1"
        assert leaderboard[0]["points"] == 300
        assert leaderboard[1]["user_id"] == "user_2"
        assert leaderboard[1]["points"] == 100

    def test_season_leaderboard_different_seasons(self):
        """Test leaderboard filters by season."""
        service = QuestCampaignService()
        
        # Register quests for different seasons
        quest1 = Quest("quest_1", "Quest 1", "Desc", 1, 100, {})
        quest2 = Quest("quest_2", "Quest 2", "Desc", 2, 200, {})
        service.register_quest(quest1)
        service.register_quest(quest2)
        
        # Record progress for both seasons
        service.record_progress("quest_1", "user_1", completed=True)
        service.record_progress("quest_2", "user_1", completed=True)
        
        # Get season 1 leaderboard only
        leaderboard = service.season_leaderboard(1)
        
        assert len(leaderboard) == 1
        assert leaderboard[0]["points"] == 100

    def test_season_leaderboard_incomplete_quests(self):
        """Test that incomplete quests don't count."""
        service = QuestCampaignService()
        
        quest = Quest("quest_1", "Quest 1", "Desc", 1, 100, {})
        service.register_quest(quest)
        
        # Record incomplete progress
        service.record_progress("quest_1", "user_1", completed=False)
        
        leaderboard = service.season_leaderboard(1)
        
        assert leaderboard == []
