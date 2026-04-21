"""Telegram Execution Notification Tests — 12 tests

Covers send_execute_success, send_execute_failure, send_protect_alert
integration with TelegramAgent.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.telegram_agent import TelegramAgent, TelegramMessage


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def mock_telegram_agent():
    """Create TelegramAgent with mocked bot for testing."""
    agent = TelegramAgent()
    agent.enabled = True
    agent._bot = MagicMock()
    agent._bot.send_message = AsyncMock()
    agent.recent_messages = []
    agent.last_post_time = 0
    return agent


# ═══════════════════════════════════════════════════════════════════════════════
# 1. send_execute_success Tests (4)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSendExecuteSuccess:
    """Test execution success notifications."""

    @pytest.mark.asyncio
    async def test_execute_success_basic(self, mock_telegram_agent):
        """Basic execution success notification."""
        mock_telegram_agent._bot.send_message.return_value = MagicMock(
            message_id=12345, chat_id="123456"
        )
        result = await mock_telegram_agent.send_execute_success(
            episode_id="abc123def456",
            assets=["BTC"],
            summary="LONG BTC/USD $500",
            throttle="80%",
            cqi="0.67",
        )
        assert result is not None
        assert "EXECUTE — SUCCESS ✅" in result.text
        assert "BTC" in result.text
        assert "abc123" in result.text  # Truncated episode ID

    @pytest.mark.asyncio
    async def test_execute_success_multiple_assets(self, mock_telegram_agent):
        """Success with multiple assets."""
        mock_telegram_agent._bot.send_message.return_value = MagicMock(
            message_id=12346, chat_id="123456"
        )
        result = await mock_telegram_agent.send_execute_success(
            episode_id="def789",
            assets=["BTC", "ETH", "SOL"],
            summary="Portfolio rebalance $1500",
            throttle="100%",
            cqi="0.82",
        )
        assert "BTC, ETH, SOL" in result.text

    @pytest.mark.asyncio
    async def test_execute_success_no_assets(self, mock_telegram_agent):
        """Success with no assets (em-dash)."""
        mock_telegram_agent._bot.send_message.return_value = MagicMock(
            message_id=12347, chat_id="123456"
        )
        result = await mock_telegram_agent.send_execute_success(
            episode_id="xyz999",
            assets=[],
            summary="Generic operation",
            throttle="—",
            cqi="—",
        )
        assert "—" in result.text  # Should show em-dash for no assets

    @pytest.mark.asyncio
    async def test_execute_success_returns_none_when_disabled(self, mock_telegram_agent):
        """Returns None when agent is disabled."""
        mock_telegram_agent.enabled = False
        result = await mock_telegram_agent.send_execute_success(
            episode_id="test",
            assets=["BTC"],
            summary="Test",
            throttle="50%",
            cqi="0.5",
        )
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# 2. send_execute_failure Tests (4)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSendExecuteFailure:
    """Test execution failure notifications."""

    @pytest.mark.asyncio
    async def test_execute_failure_basic(self, mock_telegram_agent):
        """Basic execution failure notification."""
        mock_telegram_agent._bot.send_message.return_value = MagicMock(
            message_id=12348, chat_id="123456"
        )
        result = await mock_telegram_agent.send_execute_failure(
            episode_id="fail123",
            assets=["ETH"],
            summary="Order rejected by venue",
            error="Insufficient margin for trade",
        )
        assert result is not None
        assert "EXECUTE — FAILURE ❌" in result.text
        assert "Insufficient margin" in result.text

    @pytest.mark.asyncio
    async def test_execute_failure_error_truncation(self, mock_telegram_agent):
        """Long errors are truncated to 100 chars."""
        mock_telegram_agent._bot.send_message.return_value = MagicMock(
            message_id=12349, chat_id="123456"
        )
        long_error = "x" * 200
        result = await mock_telegram_agent.send_execute_failure(
            episode_id="test",
            assets=["BTC"],
            summary="Test",
            error=long_error,
        )
        assert "x" * 100 in result.text
        assert len(result.text) < 250  # Should be truncated

    @pytest.mark.asyncio
    async def test_execute_failure_uses_force(self, mock_telegram_agent):
        """Failure notifications use force=True to bypass rate limiting."""
        mock_telegram_agent._bot.send_message.return_value = MagicMock(
            message_id=12350, chat_id="123456"
        )
        with patch.object(mock_telegram_agent, 'send_message') as mock_send:
            mock_send.return_value = MagicMock(text="test")
            await mock_telegram_agent.send_execute_failure(
                episode_id="test",
                assets=["BTC"],
                summary="Test",
                error="Test error",
            )
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert call_args.kwargs.get('force') is True

    @pytest.mark.asyncio
    async def test_execute_failure_returns_none_when_disabled(self, mock_telegram_agent):
        """Returns None when agent is disabled."""
        mock_telegram_agent.enabled = False
        result = await mock_telegram_agent.send_execute_failure(
            episode_id="test",
            assets=["BTC"],
            summary="Test",
            error="Test error",
        )
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# 3. send_protect_alert Tests (4)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSendProtectAlert:
    """Test PROTECT phase alert notifications."""

    @pytest.mark.asyncio
    async def test_protect_alert_basic(self, mock_telegram_agent):
        """Basic PROTECT alert."""
        mock_telegram_agent._bot.send_message.return_value = MagicMock(
            message_id=12351, chat_id="123456"
        )
        result = await mock_telegram_agent.send_protect_alert(
            episode_id="system",
            assets=[],
            summary="Global kill switch active — all execution blocked",
            reason="manual operator intervention",
        )
        assert result is not None
        assert "PROTECT — FAILURE ❌" in result.text
        assert "kill switch" in result.text.lower()
        assert "manual operator intervention" in result.text

    @pytest.mark.asyncio
    async def test_protect_alert_bypasses_dedupe(self, mock_telegram_agent):
        """PROTECT alerts bypass deduplication with force=True."""
        mock_telegram_agent._bot.send_message.return_value = MagicMock(
            message_id=12352, chat_id="123456"
        )
        with patch.object(mock_telegram_agent, 'send_message') as mock_send:
            mock_send.return_value = MagicMock(text="test")
            await mock_telegram_agent.send_protect_alert(
                episode_id="system",
                assets=[],
                summary="Critical risk breach",
                reason="drawdown exceeded 10%",
            )
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert call_args.kwargs.get('force') is True

    @pytest.mark.asyncio
    async def test_protect_alert_custom_force(self, mock_telegram_agent):
        """Can override force parameter."""
        mock_telegram_agent._bot.send_message.return_value = MagicMock(
            message_id=12353, chat_id="123456"
        )
        with patch.object(mock_telegram_agent, 'send_message') as mock_send:
            mock_send.return_value = MagicMock(text="test")
            await mock_telegram_agent.send_protect_alert(
                episode_id="system",
                assets=[],
                summary="Test",
                reason="Test",
                force=False,  # Override
            )
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert call_args.kwargs.get('force') is False

    @pytest.mark.asyncio
    async def test_protect_alert_returns_none_when_disabled(self, mock_telegram_agent):
        """Returns None when agent is disabled."""
        mock_telegram_agent.enabled = False
        result = await mock_telegram_agent.send_protect_alert(
            episode_id="system",
            assets=[],
            summary="Test",
            reason="Test",
        )
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Integration Tests (3)
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntegration:
    """Integration with existing TelegramAgent functionality."""

    @pytest.mark.asyncio
    async def test_execution_notifications_use_send_message(self, mock_telegram_agent):
        """All execution methods use underlying send_message."""
        mock_telegram_agent._bot.send_message.return_value = MagicMock(
            message_id=12354, chat_id="123456"
        )
        # Test success
        await mock_telegram_agent.send_execute_success(
            episode_id="test", assets=["BTC"], summary="Test", throttle="50%", cqi="0.5"
        )
        # Test failure
        await mock_telegram_agent.send_execute_failure(
            episode_id="test", assets=["BTC"], summary="Test", error="Test"
        )
        # Test protect
        await mock_telegram_agent.send_protect_alert(
            episode_id="system", assets=[], summary="Test", reason="Test"
        )
        assert mock_telegram_agent._bot.send_message.call_count == 3

    @pytest.mark.asyncio
    async def test_execution_messages_tracked_in_recent(self, mock_telegram_agent):
        """Execution messages appear in recent_messages list."""
        mock_telegram_agent._bot.send_message.return_value = MagicMock(
            message_id=12355, chat_id="123456"
        )
        await mock_telegram_agent.send_execute_success(
            episode_id="test", assets=["BTC"], summary="Test", throttle="50%", cqi="0.5"
        )
        recent = mock_telegram_agent.get_recent_messages(limit=1)
        assert len(recent) == 1
        assert "EXECUTE — SUCCESS" in recent[0].text

    @pytest.mark.asyncio
    async def test_html_formatting_in_messages(self, mock_telegram_agent):
        """Messages use HTML formatting (bold tags)."""
        mock_telegram_agent._bot.send_message.return_value = MagicMock(
            message_id=12356, chat_id="123456"
        )
        result = await mock_telegram_agent.send_execute_success(
            episode_id="test", assets=["BTC"], summary="Test", throttle="50%", cqi="0.5"
        )
        assert "<b>" in result.text  # HTML bold tags present
        assert "</b>" in result.text
