"""
MERID Telegram Bot Interface (Phase 21e)

Provides a Telegram console for monitoring, control, and alerts.
Integrates with social bot health monitor and breach detection.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Callable
import logging

logger = logging.getLogger(__name__)


@dataclass
class TelegramCommand:
    command: str
    args: List[str]
    user_id: str
    chat_id: str
    timestamp: datetime


@dataclass
class TelegramMessage:
    text: str
    chat_id: str
    parse_mode: str = "Markdown"
    disable_notification: bool = False


class TelegramBotInterface:
    """
    Telegram bot interface for MERID monitoring and control.
    
    Features:
    - Command processing (/status, /positions, /risk, /kill)
    - Real-time alerts and notifications
    - Authentication and authorization
    - Rate limiting per user
    - Self-healing integration
    """
    
    def __init__(
        self,
        bot_token: Optional[str] = None,
        authorized_users: Optional[List[str]] = None,
    ):
        self.bot_token = bot_token
        self.authorized_users = set(authorized_users or [])
        self._command_handlers: Dict[str, Callable] = {}
        self._rate_limits: Dict[str, List[float]] = {}
        self._rate_limit_window = 60.0
        self._rate_limit_max = 20
        self._running = False
        
        self._register_default_handlers()
    
    def _register_default_handlers(self) -> None:
        """Register default command handlers."""
        self._command_handlers = {
            "start": self._handle_start,
            "help": self._handle_help,
            "status": self._handle_status,
            "positions": self._handle_positions,
            "risk": self._handle_risk,
            "social": self._handle_social,
            "kill": self._handle_kill,
            "health": self._handle_health,
        }
    
    def register_command(self, command: str, handler: Callable) -> None:
        """Register custom command handler."""
        self._command_handlers[command] = handler
        logger.info(f"Registered Telegram command: /{command}")
    
    def _check_rate_limit(self, user_id: str) -> bool:
        """Check if user is within rate limits."""
        now = time.time()
        user_requests = self._rate_limits.get(user_id, [])
        
        user_requests = [ts for ts in user_requests if now - ts < self._rate_limit_window]
        
        if len(user_requests) >= self._rate_limit_max:
            return False
        
        user_requests.append(now)
        self._rate_limits[user_id] = user_requests
        return True
    
    def _is_authorized(self, user_id: str) -> bool:
        """Check if user is authorized."""
        if not self.authorized_users:
            return True
        return user_id in self.authorized_users
    
    async def process_command(self, command: TelegramCommand) -> Optional[TelegramMessage]:
        """Process incoming command."""
        if not self._is_authorized(command.user_id):
            return TelegramMessage(
                text="⛔ Unauthorized. Contact administrator.",
                chat_id=command.chat_id,
            )
        
        if not self._check_rate_limit(command.user_id):
            return TelegramMessage(
                text="⏱️ Rate limit exceeded. Please wait.",
                chat_id=command.chat_id,
            )
        
        handler = self._command_handlers.get(command.command)
        if not handler:
            return TelegramMessage(
                text=f"❓ Unknown command: /{command.command}\nUse /help for available commands.",
                chat_id=command.chat_id,
            )
        
        try:
            response = await handler(command)
            return response
        except Exception as e:
            logger.error(f"Error processing command /{command.command}: {e}")
            return TelegramMessage(
                text=f"❌ Error processing command: {str(e)}",
                chat_id=command.chat_id,
            )
    
    async def _handle_start(self, cmd: TelegramCommand) -> TelegramMessage:
        """Handle /start command."""
        return TelegramMessage(
            text=(
                "🤖 *MERID Telegram Console*\n\n"
                "Welcome! Use /help to see available commands."
            ),
            chat_id=cmd.chat_id,
        )
    
    async def _handle_help(self, cmd: TelegramCommand) -> TelegramMessage:
        """Handle /help command."""
        commands = [
            "/status - System status overview",
            "/positions - Active positions",
            "/risk - Risk metrics",
            "/social - Social signal status",
            "/health - Bot health status",
            "/kill - Emergency kill switch",
        ]
        return TelegramMessage(
            text="📋 *Available Commands:*\n\n" + "\n".join(commands),
            chat_id=cmd.chat_id,
        )
    
    async def _handle_status(self, cmd: TelegramCommand) -> TelegramMessage:
        """Handle /status command."""
        from social.social_aware_quant import get_social_aware_quant_engine
        
        engine = get_social_aware_quant_engine()
        status = engine.get_social_risk_status()
        
        text = (
            f"📊 *System Status*\n\n"
            f"Social Kill Switch: {'🔴 ACTIVE' if status['kill_switch_active'] else '🟢 Inactive'}\n"
            f"Exposure: ${status['total_exposure_usd']:,.0f}\n"
            f"Active Positions: {status['active_positions']}\n"
        )
        
        return TelegramMessage(text=text, chat_id=cmd.chat_id)
    
    async def _handle_positions(self, cmd: TelegramCommand) -> TelegramMessage:
        """Handle /positions command."""
        from social.social_aware_quant import get_social_aware_quant_engine
        
        engine = get_social_aware_quant_engine()
        exposures = engine.get_top_asset_exposures(limit=10)
        
        if not exposures:
            return TelegramMessage(
                text="📭 No active positions.",
                chat_id=cmd.chat_id,
            )
        
        lines = ["💼 *Top Positions:*\n"]
        for asset, exposure in exposures:
            lines.append(f"• {asset}: ${exposure:,.0f}")
        
        return TelegramMessage(text="\n".join(lines), chat_id=cmd.chat_id)
    
    async def _handle_risk(self, cmd: TelegramCommand) -> TelegramMessage:
        """Handle /risk command."""
        from governance.multi_agent_risk_controls import get_multi_agent_risk_controls
        
        controls = get_multi_agent_risk_controls()
        status = controls.get_risk_status()
        
        text = (
            f"⚠️ *Risk Status*\n\n"
            f"Global Kill Switch: {'🔴 ACTIVE' if status.get('kill_switch_active') else '🟢 Inactive'}\n"
            f"Active Violations: {len(status.get('violations', []))}\n"
        )
        
        return TelegramMessage(text=text, chat_id=cmd.chat_id)
    
    async def _handle_social(self, cmd: TelegramCommand) -> TelegramMessage:
        """Handle /social command."""
        from social.social_aware_quant import get_social_aware_quant_engine
        
        engine = get_social_aware_quant_engine()
        status = engine.get_social_risk_status()
        
        text = (
            f"📱 *Social Signal Status*\n\n"
            f"Data Freshness: {status.get('data_freshness_score', 0):.1%}\n"
            f"Kill Switch: {'🔴 ACTIVE' if status['kill_switch_active'] else '🟢 Inactive'}\n"
        )
        
        return TelegramMessage(text=text, chat_id=cmd.chat_id)
    
    async def _handle_health(self, cmd: TelegramCommand) -> TelegramMessage:
        """Handle /health command."""
        from social.social_aware_quant import get_social_bot_health_monitor
        
        monitor = get_social_bot_health_monitor()
        health = monitor.get_health_summary()
        
        text = f"🏥 *Bot Health*\n\nBots Tracked: {health['total_bots']}\n"
        
        return TelegramMessage(text=text, chat_id=cmd.chat_id)
    
    async def _handle_kill(self, cmd: TelegramCommand) -> TelegramMessage:
        """Handle /kill command (emergency stop)."""
        from social.social_aware_quant import get_social_aware_quant_engine
        
        engine = get_social_aware_quant_engine()
        engine.activate_kill_switch("telegram_emergency_command")
        await self.send_alert(
            message="Telegram operator issued /kill. All social trading halted.",
            severity="critical",
        )
        
        return TelegramMessage(
            text="🛑 *EMERGENCY KILL SWITCH ACTIVATED*\n\nAll social trading halted.",
            chat_id=cmd.chat_id,
        )
    
    async def send_alert(self, message: str, severity: str = "info") -> None:
        """Send alert to all authorized users."""
        emoji = {"critical": "🚨", "high": "⚠️", "medium": "ℹ️", "info": "📢"}.get(severity, "📢")
        
        text = f"{emoji} *Alert*\n\n{message}"
        
        for user_id in self.authorized_users:
            logger.info(f"Sending alert to Telegram user {user_id}: {message}")
    
    async def start(self) -> None:
        """Start Telegram bot polling."""
        self._running = True
        logger.info("Telegram bot interface started")
    
    async def stop(self) -> None:
        """Stop Telegram bot."""
        self._running = False
        logger.info("Telegram bot interface stopped")


_telegram_bot: Optional[TelegramBotInterface] = None


def get_telegram_bot() -> TelegramBotInterface:
    """Get global TelegramBotInterface instance."""
    global _telegram_bot
    if _telegram_bot is None:
        _telegram_bot = TelegramBotInterface()
    return _telegram_bot
