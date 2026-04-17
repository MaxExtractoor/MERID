# tests/test_telegram_market_batch.py
import html
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.alerts.crypto_alert_router import MarketSelectionItem, MarketTag


@pytest.fixture
def agent():
    with patch("agents.telegram_agent.Bot"):
        from agents.telegram_agent import TelegramAgent
        ag = TelegramAgent.__new__(TelegramAgent)
        ag._bot = AsyncMock()
        ag._bot.send_message = AsyncMock()
        ag.last_post_time = 0.0
        ag.recent_messages = []
        return ag


class TestSendMarketSelectionBatch:
    @pytest.mark.asyncio
    async def test_sends_one_message(self, agent):
        items = [
            MarketSelectionItem("KXBTCD-26MAR22", "Will BTC close above $87k?",
                                "daily", 5000, 0.52, {MarketTag.TRENDING}),
        ]
        await agent.send_market_selection_batch("BTC", MarketTag.TRENDING, items)
        agent._bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_html_escapes_title(self, agent):
        items = [
            MarketSelectionItem("KXBTCD-26MAR22", "<b>Tricky & title</b>",
                                "daily", 5000, 0.50, {MarketTag.TRENDING}),
        ]
        await agent.send_market_selection_batch("BTC", MarketTag.TRENDING, items)
        call_args = agent._bot.send_message.call_args
        text = call_args[1].get("text") or call_args[0][1]
        assert "&lt;b&gt;" in text or "Tricky &amp; title" in text

    @pytest.mark.asyncio
    async def test_message_under_4096_chars(self, agent):
        items = [
            MarketSelectionItem(f"KXBTCD-26MAR{i:02d}", f"Title {i}", "daily", 1000, 0.50, set())
            for i in range(5)
        ]
        await agent.send_market_selection_batch("BTC", MarketTag.TRENDING, items)
        call_args = agent._bot.send_message.call_args
        text = call_args[1].get("text") or call_args[0][1]
        assert len(text) < 4096

    @pytest.mark.asyncio
    async def test_send_risk_alert_accepts_new_kwargs(self, agent):
        """New optional kwargs must not break existing call sites."""
        await agent.send_risk_alert("risk_limit", "Test message", "warning",
                                    symbol="BTC", episode_id="KXBTCD",
                                    frequency="daily", total_risk=480.0, risk_limit=500.0)
        agent._bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_risk_alert_old_signature_still_works(self, agent):
        """Existing call sites with 3 args must not break."""
        await agent.send_risk_alert("risk_limit", "Test message", "warning")
        agent._bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_risk_alert_escapes_plain_message(self, agent):
        """The new send_risk_alert escapes the message param."""
        await agent.send_risk_alert("risk_limit", "Balance <b>breached</b>", "critical")
        call_args = agent._bot.send_message.call_args
        text = call_args[1].get("text") or call_args[0][1]
        assert "<b>" not in text
        assert "&lt;b&gt;" in text or "breached" in text
