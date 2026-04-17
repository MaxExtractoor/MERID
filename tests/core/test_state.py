"""Tests for core/state.py."""
import pytest
from core.state import TopPick, MeridState, state


class TestTopPick:
    """Test TopPick dataclass."""

    def test_creation(self):
        """Test TopPick creation."""
        pick = TopPick(
            energy_id="e1",
            payload="Test payload",
            consensus=0.85,
            approved_at="2024-01-01T00:00:00Z",
            source="test",
            curator=["user1"]
        )
        assert pick.energy_id == "e1"
        assert pick.payload == "Test payload"
        assert pick.consensus == 0.85
        assert pick.curator == ["user1"]


class TestMeridState:
    """Test MeridState class."""

    def test_initialization(self):
        """Test state initialization."""
        state_obj = MeridState()
        assert len(state_obj._top_picks) == 0
        assert len(state_obj._connections) == 0
        assert len(state_obj._user_filters) == 0

    @pytest.mark.asyncio
    async def test_record_and_get_top_picks(self):
        """Test recording and retrieving top picks."""
        state_obj = MeridState()
        await state_obj.record_top_pick(
            energy_id="e1",
            payload="Test",
            consensus=0.9,
            source="source1"
        )
        picks = await state_obj.get_top_picks()
        assert len(picks) == 1
        assert picks[0]["energy_id"] == "e1"
        assert picks[0]["consensus"] == "90.0%"

    @pytest.mark.asyncio
    async def test_record_validation(self):
        """Test recording validation."""
        state_obj = MeridState()
        await state_obj.record_validation(
            energy={"energy_id": "e1", "payload": "Test"},
            verdict={"result": "approved"},
            vote_result={"yes": 5, "no": 2}
        )
        validation = await state_obj.get_validation("e1")
        assert validation["energy_id"] == "e1"
        assert validation["verdict"]["result"] == "approved"

    @pytest.mark.asyncio
    async def test_list_validations(self):
        """Test listing validations."""
        state_obj = MeridState()
        await state_obj.record_validation(
            energy={"energy_id": "e1", "payload": "Test1"},
            verdict={"result": "approved"},
            vote_result={}
        )
        await state_obj.record_validation(
            energy={"energy_id": "e2", "payload": "Test2"},
            verdict={"result": "rejected"},
            vote_result={}
        )
        validations = await state_obj.list_validations(limit=2)
        assert len(validations) == 2

    @pytest.mark.asyncio
    async def test_record_and_list_audits(self):
        """Test recording and listing audits."""
        state_obj = MeridState()
        await state_obj.record_audit({"action": "test"})
        audits = await state_obj.list_audits()
        assert len(audits) == 1
        assert audits[0]["report"]["action"] == "test"

    @pytest.mark.asyncio
    async def test_record_and_list_automation_events(self):
        """Test recording and listing automation events."""
        state_obj = MeridState()
        await state_obj.record_automation_event(
            channel="test_channel",
            status="success",
            message="Test message"
        )
        events = await state_obj.list_automation_events()
        assert len(events) == 1
        assert events[0]["channel"] == "test_channel"

    @pytest.mark.asyncio
    async def test_register_and_get_connections(self):
        """Test registering and getting connections."""
        state_obj = MeridState()
        await state_obj.register_connection(
            user_handle="user1",
            x_handle="@user1",
            wallet_address="0x123"
        )
        connections = await state_obj.get_connections("user1")
        assert "user1" in connections
        assert connections["user1"]["x_handle"] == "@user1"

    @pytest.mark.asyncio
    async def test_set_and_get_filters(self):
        """Test setting and getting filters."""
        state_obj = MeridState()
        await state_obj.set_filters("user1", {"source": "twitter"})
        filters = await state_obj.get_filters("user1")
        assert filters["source"] == "twitter"

    def test_help_sections(self):
        """Test help sections."""
        state_obj = MeridState()
        sections = state_obj.help_sections()
        assert len(sections) == 3
        assert sections[0]["title"] == "Getting Started"

    def test_legal_notice(self):
        """Test legal notice."""
        state_obj = MeridState()
        notice = state_obj.legal_notice()
        assert "MERID" in notice
        assert "All Rights Reserved" in notice


class TestGlobalState:
    """Test global state instance."""

    def test_state_exists(self):
        """Test global state exists."""
        assert state is not None
        assert isinstance(state, MeridState)
