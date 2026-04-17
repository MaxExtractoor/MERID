"""
Debate Orchestrator Tests
Tests for strategic debate protocol orchestration and management.
"""

import pytest
import asyncio
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, Mock, patch

from merid.prediction.debate_orchestrator import (
    DebateOrchestrator, DebateConfig, DebateInvitation, DebateMetrics,
    get_debate_orchestrator, initialize_debate_orchestrator
)
from merid.prediction.debate import DebateStore, DebateSession, DebateArgument


class TestDebateOrchestrator:
    """Test debate orchestrator functionality."""
    
    def setup_method(self):
        """Setup fresh orchestrator for each test."""
        self.mock_store = Mock(spec=DebateStore)
        self.config = DebateConfig(
            max_rounds=2,
            round_duration_minutes=1,  # Short for testing
            min_participants=2,
            max_participants=3
        )
        self.orchestrator = DebateOrchestrator(self.mock_store, self.config)
    
    @pytest.mark.asyncio
    async def test_orchestrator_lifecycle(self):
        """Test orchestrator start/stop lifecycle."""
        assert not self.orchestrator._running
        assert self.orchestrator._orchestration_task is None
        
        await self.orchestrator.start()
        assert self.orchestrator._running
        assert self.orchestrator._orchestration_task is not None
        
        await self.orchestrator.stop()
        assert not self.orchestrator._running
    
    @pytest.mark.asyncio
    async def test_create_debate_session(self):
        """Test creating a new debate session."""
        symbol = "KXBTCD-25JUN-T100000"
        
        # Mock store methods
        self.mock_store.list_debates.return_value = []  # No existing debates
        self.mock_store.create_debate = Mock()
        
        debate_id = await self.orchestrator._create_debate_session(symbol)
        
        assert debate_id is not None
        assert debate_id.startswith("debate-")
        assert symbol in debate_id
        
        # Verify debate was created in store
        self.mock_store.create_debate.assert_called_once()
        created_debate = self.mock_store.create_debate.call_args[0][0]
        assert created_debate.symbol == symbol
        assert created_debate.status == "open"
        
        # Verify debate is tracked in active sessions
        assert debate_id in self.orchestrator.active_sessions
    
    @pytest.mark.asyncio
    async def test_create_debate_session_already_exists(self):
        """Test not creating debate if one already exists."""
        symbol = "KXBTCD-25JUN-T100000"
        existing_debate = Mock(id="existing-debate")
        
        # Mock store to return existing debate
        self.mock_store.list_debates.return_value = [existing_debate]
        
        debate_id = await self.orchestrator._create_debate_session(symbol)
        
        assert debate_id is None
        self.mock_store.create_debate.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_invite_participants(self):
        """Test inviting qualified participants to debate."""
        debate_id = "test-debate-123"
        symbol = "KXBTCD-25JUN-T100000"
        
        # Mock consensus coordinator opinions
        mock_opinions = [
            Mock(agent_id="agent1", score=0.5, confidence=0.8),
            Mock(agent_id="agent2", score=-0.3, confidence=0.6),
            Mock(agent_id="agent3", score=0.2, confidence=0.7),
        ]
        
        # Mock agent data collection
        agent_data = {
            "agent1": {
                "recent_predictions": [
                    {"predicted_prob": 0.8, "actual_outcome": 1},
                    {"predicted_prob": 0.3, "actual_outcome": 0},
                ] * 5,  # 10 predictions
                "recent_arguments": [
                    {"content": "Good arg", "quality_score": 0.8, "evidence_citations": ["src1"]}
                ],
                "debate_history": [{"debate_lift": 0.05}],
                "current_team": {}
            },
            "agent2": {
                "recent_predictions": [
                    {"predicted_prob": 0.7, "actual_outcome": 1},
                    {"predicted_prob": 0.4, "actual_outcome": 0},
                ] * 5,
                "recent_arguments": [
                    {"content": "Another arg", "quality_score": 0.7, "evidence_citations": ["src2"]}
                ],
                "debate_history": [{"debate_lift": 0.03}],
                "current_team": {}
            },
            "agent3": {
                "recent_predictions": [
                    {"predicted_prob": 0.6, "actual_outcome": 1},
                    {"predicted_prob": 0.5, "actual_outcome": 0},
                ] * 5,
                "recent_arguments": [
                    {"content": "Third arg", "quality_score": 0.6, "evidence_citations": ["src3"]}
                ],
                "debate_history": [{"debate_lift": 0.02}],
                "current_team": {}
            }
        }
        
        with patch('merid.prediction.debate_orchestrator.get_consensus_coordinator') as mock_coordinator:
            mock_coordinator.return_value._opinions = {symbol: mock_opinions}
            
            with patch.object(self.orchestrator, '_collect_agent_data') as mock_collect:
                mock_collect.side_effect = lambda aid: agent_data.get(aid)
                
                await self.orchestrator._invite_participants(debate_id, symbol)
        
        # Verify invitations were created
        assert debate_id in self.orchestrator.pending_invitations
        invitations = self.orchestrator.pending_invitations[debate_id]
        
        # Should have invited qualified participants (up to max_participants)
        assert len(invitations) <= self.config.max_participants
        assert all(inv.debate_id == debate_id for inv in invitations)
        assert all(inv.gate_summary is not None for inv in invitations)
    
    @pytest.mark.asyncio
    async def test_collect_agent_data(self):
        """Test collecting comprehensive agent data."""
        agent_id = "test-agent"
        
        # Mock consensus coordinator
        mock_opinions = [
            Mock(agent_id=agent_id, score=0.5, confidence=0.8, timestamp=datetime.now(timezone.utc))
        ]
        
        # Mock debate store methods
        mock_debates = [Mock(id="debate1", debate_lift=0.05, created_at=time.time())]
        mock_arguments = [Mock(content="test", evidence=["src1"], created_at=time.time())]
        
        with patch('merid.prediction.debate_orchestrator.get_consensus_coordinator') as mock_coordinator:
            mock_coordinator.return_value._opinions = {"KXBTCD": mock_opinions}
            
            self.mock_store.list_agent_debates.return_value = mock_debates
            self.mock_store.list_agent_arguments.return_value = mock_arguments
            
            agent_data = await self.orchestrator._collect_agent_data(agent_id)
        
        assert agent_data is not None
        assert agent_data["agent_id"] == agent_id
        assert len(agent_data["recent_predictions"]) == 1
        assert len(agent_data["debate_history"]) == 1
        assert len(agent_data["recent_arguments"]) == 1
        assert "current_team" in agent_data
    
    @pytest.mark.asyncio
    async def test_select_diverse_participants(self):
        """Test selecting diverse participants from candidates."""
        candidates = [
            ("agent1", Mock(total_score=0.9, overall_passed=True)),
            ("agent2", Mock(total_score=0.8, overall_passed=True)),
            ("agent3", Mock(total_score=0.7, overall_passed=True)),
            ("agent4", Mock(total_score=0.6, overall_passed=True)),
            ("agent5", Mock(total_score=0.5, overall_passed=True)),
        ]
        
        selected = self.orchestrator._select_diverse_participants(candidates, 3)
        
        assert len(selected) == 3
        # Should select highest scoring candidates
        selected_ids = [agent_id for agent_id, _ in selected]
        assert "agent1" in selected_ids  # Highest score
        assert "agent2" in selected_ids  # Second highest
        assert "agent3" in selected_ids  # Third highest
    
    @pytest.mark.asyncio
    async def test_process_invitations(self):
        """Test processing pending debate invitations."""
        debate_id = "test-debate-123"
        
        # Create invitations with gate summaries
        gate_summary = Mock(overall_passed=True)
        invitations = [
            DebateInvitation(
                debate_id=debate_id,
                agent_id="agent1",
                invited_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
                gate_summary=gate_summary
            ),
            DebateInvitation(
                debate_id=debate_id,
                agent_id="agent2",
                invited_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
                gate_summary=gate_summary
            )
        ]
        
        self.orchestrator.pending_invitations[debate_id] = invitations
        
        # Mock debate session
        mock_debate = Mock(participant_ids=[])
        self.orchestrator.active_sessions[debate_id] = mock_debate
        self.mock_store.update_debate = Mock()
        
        await self.orchestrator._process_invitations()
        
        # Should have added participants and started debate
        assert len(mock_debate.participant_ids) >= self.config.min_participants
        self.mock_store.update_debate.assert_called()
    
    @pytest.mark.asyncio
    async def test_start_debate_session(self):
        """Test starting a debate session."""
        debate_id = "test-debate-123"
        symbol = "KXBTCD-25JUN-T100000"
        
        # Create debate session
        debate = DebateSession(
            id=debate_id,
            symbol=symbol,
            status="open",
            created_at=time.time()
        )
        
        self.orchestrator.active_sessions[debate_id] = debate
        self.mock_store.update_debate = Mock()
        
        with patch.object(self.orchestrator, '_manage_debate_rounds') as mock_manage:
            mock_manage.return_value = asyncio.create_task(asyncio.sleep(0))
            
            await self.orchestrator._start_debate_session(debate_id)
        
        assert debate.status == "active"
        assert debate.started_at is not None
        self.mock_store.update_debate.assert_called_with(debate)
    
    @pytest.mark.asyncio
    async def test_end_debate_session(self):
        """Test ending a debate session."""
        debate_id = "test-debate-123"
        
        # Create active debate
        debate = DebateSession(
            id=debate_id,
            symbol="KXBTCD",
            status="active",
            participant_ids=["agent1", "agent2"],
            created_at=time.time(),
            started_at=time.time()
        )
        
        self.orchestrator.active_sessions[debate_id] = debate
        self.mock_store.update_debate = Mock()
        
        with patch.object(self.orchestrator, '_calculate_debate_metrics') as mock_metrics:
            mock_metrics.return_value = DebateMetrics(
                debate_id=debate_id,
                created_at=datetime.now(timezone.utc),
                participants=["agent1", "agent2"],
                rounds_completed=2,
                arguments_count=5,
                avg_argument_quality=0.7,
                debate_lift=0.05,
                consensus_improvement=0.1,
                time_to_complete_minutes=15.0
            )
            
            await self.orchestrator._end_debate_session(debate_id)
        
        assert debate.status == "closed"
        assert debate.closed_at is not None
        assert debate_id not in self.orchestrator.active_sessions
        self.mock_store.update_debate.assert_called_with(debate)
    
    @pytest.mark.asyncio
    async def test_calculate_debate_metrics(self):
        """Test calculating comprehensive debate metrics."""
        debate_id = "test-debate-123"
        
        # Create debate in store
        debate = DebateSession(
            id=debate_id,
            symbol="KXBTCD",
            status="closed",
            participant_ids=["agent1", "agent2"],
            created_at=time.time() - 3600,  # 1 hour ago
            debate_lift=0.05
        )
        
        self.mock_store.get_debate.return_value = debate
        self.mock_store.list_debate_arguments.return_value = [
            Mock(content="arg1"), Mock(content="arg2"), Mock(content="arg3")
        ]
        
        metrics = await self.orchestrator._calculate_debate_metrics(debate_id)
        
        assert isinstance(metrics, DebateMetrics)
        assert metrics.debate_id == debate_id
        assert metrics.participants == ["agent1", "agent2"]
        assert metrics.arguments_count == 3
        assert metrics.debate_lift == 0.05
    
    @pytest.mark.asyncio
    async def test_calculate_debate_rewards(self):
        """Test calculating and distributing debate rewards."""
        debate_id = "test-debate-123"
        
        # Create debate with participants
        debate = DebateSession(
            id=debate_id,
            symbol="KXBTCD",
            status="closed",
            participant_ids=["agent1", "agent2"],
            debate_lift=0.05
        )
        
        self.mock_store.get_debate.return_value = debate
        self.mock_store.add_reward = Mock()
        
        await self.orchestrator._calculate_debate_rewards(debate_id)
        
        # Should have called add_reward for each participant
        assert self.mock_store.add_reward.call_count == 2
        
        # Check reward calls
        for call in self.mock_store.add_reward.call_args_list:
            args, kwargs = call
            assert kwargs["agent_id"] in ["agent1", "agent2"]
            assert kwargs["reward_type"] == "debate_participation"
            assert kwargs["points"] > 10.0  # Base reward + lift bonus
            assert debate_id in kwargs["detail"]
    
    @pytest.mark.asyncio
    async def test_scan_debate_opportunities(self):
        """Test scanning for new debate opportunities."""
        # Mock consensus coordinator with high disagreement
        mock_opinions = [
            Mock(agent_id="agent1", score=0.8),
            Mock(agent_id="agent2", score=-0.6),
            Mock(agent_id="agent3", score=0.3),
        ]
        
        with patch('merid.prediction.debate_orchestrator.get_consensus_coordinator') as mock_coordinator:
            mock_coordinator.return_value._opinions = {
                "KXBTCD": mock_opinions,
                "KETH": mock_opinions[:2]  # Only 2 opinions, below threshold
            }
            
            with patch.object(self.orchestrator, '_create_debate_session') as mock_create:
                mock_create.return_value = "debate-123"
                
                await self.orchestrator._scan_debate_opportunities()
        
        # Should have created debate for high-disagreement symbol
        mock_create.assert_called_once_with("KXBTCD")
    
    @pytest.mark.asyncio
    async def test_cleanup_expired_sessions(self):
        """Test cleanup of expired sessions and invitations."""
        # Create expired invitation
        expired_invitation = DebateInvitation(
            debate_id="debate-123",
            agent_id="agent1",
            invited_at=datetime.now(timezone.utc) - timedelta(hours=2),
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1)
        )
        
        # Create valid invitation
        valid_invitation = DebateInvitation(
            debate_id="debate-456",
            agent_id="agent2",
            invited_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
        )
        
        self.orchestrator.pending_invitations["debate-123"] = [expired_invitation]
        self.orchestrator.pending_invitations["debate-456"] = [valid_invitation]
        
        # Create very old active session
        old_debate = DebateSession(
            id="old-debate",
            symbol="OLD",
            status="active",
            created_at=time.time() - (25 * 3600)  # 25 hours ago
        )
        self.orchestrator.active_sessions["old-debate"] = old_debate
        
        with patch.object(self.orchestrator, '_end_debate_session') as mock_end:
            mock_end.return_value = asyncio.create_task(asyncio.sleep(0))
            
            await self.orchestrator._cleanup_expired_sessions()
        
        # Expired invitation should be removed
        assert "debate-123" not in self.orchestrator.pending_invitations
        assert "debate-456" in self.orchestrator.pending_invitations
        
        # Old session should be cleaned up
        mock_end.assert_called_once_with("old-debate")


class TestDebateConfig:
    """Test debate configuration."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = DebateConfig()
        
        assert config.max_rounds == 3
        assert config.round_duration_minutes == 10
        assert config.min_participants == 2
        assert config.max_participants == 5
        assert config.min_debate_lift == 0.02
        assert config.enable_quantitative_gates is True
    
    def test_custom_config(self):
        """Test custom configuration values."""
        config = DebateConfig(
            max_rounds=5,
            round_duration_minutes=15,
            min_participants=3,
            max_participants=8
        )
        
        assert config.max_rounds == 5
        assert config.round_duration_minutes == 15
        assert config.min_participants == 3
        assert config.max_participants == 8
        # Other values should be defaults
        assert config.min_debate_lift == 0.02


class TestGlobalOrchestrator:
    """Test global orchestrator instance management."""
    
    def test_get_debate_orchestrator(self):
        """Test getting global orchestrator instance."""
        orchestrator = get_debate_orchestrator()
        assert orchestrator is None  # Not initialized yet
    
    def test_initialize_debate_orchestrator(self):
        """Test initializing global orchestrator."""
        mock_store = Mock(spec=DebateStore)
        config = DebateConfig()
        
        orchestrator = initialize_debate_orchestrator(mock_store, config)
        
        assert isinstance(orchestrator, DebateOrchestrator)
        assert orchestrator.store is mock_store
        assert orchestrator.config is config
        
        # Should be available globally
        global_orchestrator = get_debate_orchestrator()
        assert global_orchestrator is orchestrator


class TestDebateInvitation:
    """Test debate invitation data structure."""
    
    def test_invitation_creation(self):
        """Test creating a debate invitation."""
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=1)
        
        invitation = DebateInvitation(
            debate_id="debate-123",
            agent_id="agent1",
            invited_at=now,
            expires_at=expires,
            role="proposer"
        )
        
        assert invitation.debate_id == "debate-123"
        assert invitation.agent_id == "agent1"
        assert invitation.invited_at == now
        assert invitation.expires_at == expires
        assert invitation.role == "proposer"
        assert invitation.gate_summary is None


if __name__ == "__main__":
    pytest.main([__file__])
