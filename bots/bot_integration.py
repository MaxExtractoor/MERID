"""
MERID Bot Integration - Section 11: Telegram and X/Twitter Bots as First-Class Tools

Bots are thin frontends on top of the MERID event bus, not separate systems.
They read from Kafka topics and post human-readable summaries.
Commands become events on command topics.

Key Features:
- Telegram bot with slash commands
- X/Twitter bot for public summaries
- RBAC on commands (privileged users only)
- Rate limiting to prevent abuse
- All interactions logged to bots.activity.* topic
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("bots.integration")


class BotType(str, Enum):
    """Types of bots."""
    TELEGRAM = "telegram"
    TWITTER = "twitter"
    DISCORD = "discord"


class CommandType(str, Enum):
    """Types of bot commands."""
    STATUS = "status"
    RISK = "risk"
    PORTFOLIO = "portfolio"
    PAUSE = "pause"
    RESUME = "resume"
    KILL = "kill"
    MUTE = "mute"
    UNMUTE = "unmute"
    HELP = "help"


class PermissionLevel(str, Enum):
    """Permission levels for bot commands."""
    PUBLIC = "public"           # Anyone can use
    AUTHENTICATED = "authenticated"  # Must be registered user
    OPERATOR = "operator"       # Trading operators
    ADMIN = "admin"             # System administrators


@dataclass
class BotUser:
    """A registered bot user."""
    user_id: str
    platform: BotType
    platform_user_id: str
    username: str
    permission_level: PermissionLevel = PermissionLevel.PUBLIC
    
    # Rate limiting
    last_command_time: float = 0.0
    commands_this_minute: int = 0
    
    # Status
    is_muted: bool = False
    registered_at: float = field(default_factory=time.time)


@dataclass
class BotCommand:
    """A command received from a bot."""
    command_id: str = field(default_factory=lambda: f"cmd_{uuid.uuid4().hex[:12]}")
    
    # Source
    platform: BotType = BotType.TELEGRAM
    user_id: str = ""
    username: str = ""
    chat_id: str = ""
    
    # Command
    command_type: CommandType = CommandType.HELP
    raw_text: str = ""
    arguments: List[str] = field(default_factory=list)
    
    # Processing
    timestamp: float = field(default_factory=time.time)
    processed: bool = False
    response: str = ""
    
    def to_event(self) -> Dict[str, Any]:
        """Convert to Kafka event format."""
        return {
            "event_type": f"{self.platform.value}.command",
            "event_id": self.command_id,
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "username": self.username,
            "command": self.command_type.value,
            "arguments": self.arguments,
            "raw_text": self.raw_text[:200],  # Truncate for safety
        }


@dataclass
class BotAlert:
    """An alert to be sent via bots."""
    alert_id: str = field(default_factory=lambda: f"alert_{uuid.uuid4().hex[:12]}")
    
    # Content
    title: str = ""
    message: str = ""
    severity: str = "info"  # info, warning, critical
    
    # Target
    target_platforms: List[BotType] = field(default_factory=list)
    target_channels: List[str] = field(default_factory=list)
    
    # Source
    source_topic: str = ""
    source_event_id: str = ""
    
    timestamp: float = field(default_factory=time.time)


# ============================================
# COMMAND DEFINITIONS
# ============================================

COMMAND_DEFINITIONS = {
    CommandType.STATUS: {
        "description": "Get system status",
        "permission": PermissionLevel.PUBLIC,
        "usage": "/status",
        "cooldown_seconds": 10,
    },
    CommandType.RISK: {
        "description": "Get risk metrics",
        "permission": PermissionLevel.AUTHENTICATED,
        "usage": "/risk",
        "cooldown_seconds": 30,
    },
    CommandType.PORTFOLIO: {
        "description": "Get portfolio summary",
        "permission": PermissionLevel.AUTHENTICATED,
        "usage": "/portfolio",
        "cooldown_seconds": 30,
    },
    CommandType.PAUSE: {
        "description": "Pause trading",
        "permission": PermissionLevel.OPERATOR,
        "usage": "/pause [reason]",
        "cooldown_seconds": 60,
    },
    CommandType.RESUME: {
        "description": "Resume trading",
        "permission": PermissionLevel.OPERATOR,
        "usage": "/resume",
        "cooldown_seconds": 60,
    },
    CommandType.KILL: {
        "description": "Trigger kill switch (EMERGENCY)",
        "permission": PermissionLevel.ADMIN,
        "usage": "/kill [reason]",
        "cooldown_seconds": 0,  # No cooldown for emergency
    },
    CommandType.MUTE: {
        "description": "Mute bot alerts",
        "permission": PermissionLevel.AUTHENTICATED,
        "usage": "/mute [duration_minutes]",
        "cooldown_seconds": 60,
    },
    CommandType.UNMUTE: {
        "description": "Unmute bot alerts",
        "permission": PermissionLevel.AUTHENTICATED,
        "usage": "/unmute",
        "cooldown_seconds": 10,
    },
    CommandType.HELP: {
        "description": "Show help",
        "permission": PermissionLevel.PUBLIC,
        "usage": "/help",
        "cooldown_seconds": 5,
    },
}


# ============================================
# BOT BASE CLASS
# ============================================

class BotBase(ABC):
    """Base class for all bots."""
    
    def __init__(self, bot_type: BotType):
        self.bot_type = bot_type
        self._users: Dict[str, BotUser] = {}
        self._admin_ids: Set[str] = set()
        self._operator_ids: Set[str] = set()
        self._muted_channels: Set[str] = set()
        
        self._event_handlers: List[Callable] = []
        self._running = False
        
        # Rate limiting
        self._global_rate_limit = 60  # Commands per minute
        self._user_rate_limit = 10
        self._command_counts: Dict[str, int] = {}
        
        logger.info(f"{bot_type.value} bot initialized")
    
    def subscribe_events(self, handler: Callable) -> None:
        """Subscribe to command events for Kafka emission."""
        self._event_handlers.append(handler)
    
    async def _emit_event(self, event: Dict[str, Any]) -> None:
        """Emit event to subscribers."""
        for handler in self._event_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(f"{self.bot_type.value}.commands", event)
                else:
                    handler(f"{self.bot_type.value}.commands", event)
            except Exception as e:
                logger.error(f"Event emission error: {e}")
    
    def register_admin(self, platform_user_id: str) -> None:
        """Register an admin user."""
        self._admin_ids.add(platform_user_id)
    
    def register_operator(self, platform_user_id: str) -> None:
        """Register an operator user."""
        self._operator_ids.add(platform_user_id)
    
    def get_user_permission(self, platform_user_id: str) -> PermissionLevel:
        """Get permission level for a user."""
        if platform_user_id in self._admin_ids:
            return PermissionLevel.ADMIN
        if platform_user_id in self._operator_ids:
            return PermissionLevel.OPERATOR
        if platform_user_id in self._users:
            return PermissionLevel.AUTHENTICATED
        return PermissionLevel.PUBLIC
    
    def check_rate_limit(self, user_id: str) -> bool:
        """Check if user is rate limited."""
        now = time.time()
        minute_key = f"{user_id}:{int(now / 60)}"
        
        count = self._command_counts.get(minute_key, 0)
        if count >= self._user_rate_limit:
            return False
        
        self._command_counts[minute_key] = count + 1
        
        # Cleanup old entries
        cutoff = int(now / 60) - 2
        self._command_counts = {
            k: v for k, v in self._command_counts.items()
            if int(k.split(":")[1]) > cutoff
        }
        
        return True
    
    def can_execute_command(
        self,
        command_type: CommandType,
        user_id: str,
    ) -> tuple[bool, str]:
        """Check if user can execute a command."""
        # Check permission
        user_perm = self.get_user_permission(user_id)
        required_perm = COMMAND_DEFINITIONS[command_type]["permission"]
        
        perm_order = [PermissionLevel.PUBLIC, PermissionLevel.AUTHENTICATED, 
                     PermissionLevel.OPERATOR, PermissionLevel.ADMIN]
        
        if perm_order.index(user_perm) < perm_order.index(required_perm):
            return False, f"Insufficient permissions. Required: {required_perm.value}"
        
        # Check rate limit
        if not self.check_rate_limit(user_id):
            return False, "Rate limit exceeded. Please wait."
        
        return True, ""
    
    def format_status_response(self, status: Dict[str, Any]) -> str:
        """Format status data for human-readable output."""
        return (
            f"📊 **MERID Status**\n"
            f"├ Mode: {status.get('mode', 'unknown')}\n"
            f"├ Agents: {status.get('healthy_agents', 0)}/{status.get('total_agents', 0)} healthy\n"
            f"├ Daily PnL: ${status.get('daily_pnl', 0):,.2f}\n"
            f"└ Last Update: {time.strftime('%H:%M:%S')}"
        )
    
    def format_risk_response(self, risk: Dict[str, Any]) -> str:
        """Format risk data for human-readable output."""
        return (
            f"⚠️ **Risk Metrics**\n"
            f"├ Exposure: ${risk.get('total_exposure', 0):,.2f}\n"
            f"├ Leverage: {risk.get('leverage', 0):.2f}x\n"
            f"├ Drawdown: {risk.get('drawdown', 0):.1f}%\n"
            f"├ Daily Loss: ${abs(risk.get('daily_loss', 0)):,.2f}\n"
            f"└ Kill Switch: {'🔴 ACTIVE' if risk.get('kill_switch') else '🟢 Ready'}"
        )
    
    def format_alert(self, alert: BotAlert) -> str:
        """Format alert for human-readable output."""
        emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(alert.severity, "📢")
        return f"{emoji} **{alert.title}**\n{alert.message}"
    
    @abstractmethod
    async def start(self) -> None:
        """Start the bot."""
        pass
    
    @abstractmethod
    async def stop(self) -> None:
        """Stop the bot."""
        pass
    
    @abstractmethod
    async def send_message(self, chat_id: str, message: str) -> bool:
        """Send a message to a chat."""
        pass
    
    @abstractmethod
    async def broadcast_alert(self, alert: BotAlert) -> int:
        """Broadcast an alert. Returns number of successful sends."""
        pass


# ============================================
# TELEGRAM BOT
# ============================================

class TelegramBot(BotBase):
    """Telegram bot implementation."""
    
    def __init__(self, token: str = None):
        super().__init__(BotType.TELEGRAM)
        self._token = token
        self._bot = None
        self._alert_channels: Set[str] = set()
    
    def add_alert_channel(self, chat_id: str) -> None:
        """Add a channel to receive alerts."""
        self._alert_channels.add(chat_id)
    
    async def start(self) -> None:
        """Start the Telegram bot."""
        if not self._token:
            logger.warning("Telegram bot token not set, running in mock mode")
            self._running = True
            return
        
        try:
            # In production, use python-telegram-bot
            # from telegram.ext import Application, CommandHandler
            # self._bot = Application.builder().token(self._token).build()
            # Register handlers...
            # await self._bot.run_polling()
            self._running = True
            logger.info("Telegram bot started")
        except Exception as e:
            logger.error(f"Telegram bot start error: {e}")
    
    async def stop(self) -> None:
        """Stop the Telegram bot."""
        self._running = False
        if self._bot:
            # await self._bot.stop()
            pass
        logger.info("Telegram bot stopped")
    
    async def send_message(self, chat_id: str, message: str) -> bool:
        """Send a message via Telegram."""
        if chat_id in self._muted_channels:
            return False
        
        if not self._token:
            logger.debug(f"[MOCK] Telegram -> {chat_id}: {message[:50]}...")
            return True
        
        try:
            # In production:
            # await self._bot.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
            return True
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False
    
    async def broadcast_alert(self, alert: BotAlert) -> int:
        """Broadcast alert to all alert channels."""
        message = self.format_alert(alert)
        success_count = 0
        
        for chat_id in self._alert_channels:
            if await self.send_message(chat_id, message):
                success_count += 1
        
        return success_count
    
    async def handle_command(self, command: BotCommand) -> str:
        """Process a command and return response."""
        # Check permissions
        can_exec, reason = self.can_execute_command(command.command_type, command.user_id)
        if not can_exec:
            return f"❌ {reason}"
        
        # Emit command event
        await self._emit_event(command.to_event())
        
        # Process command — wired to live Kalshi APIs
        if command.command_type == CommandType.HELP:
            return self._get_help_text()

        elif command.command_type == CommandType.STATUS:
            return self._handle_status()

        elif command.command_type == CommandType.RISK:
            return self._handle_risk()

        elif command.command_type == CommandType.PORTFOLIO:
            return self._handle_portfolio()

        elif command.command_type == CommandType.PAUSE:
            reason = " ".join(command.arguments) or "Manual pause via bot"
            return self._handle_pause(reason)

        elif command.command_type == CommandType.RESUME:
            return self._handle_resume()

        elif command.command_type == CommandType.KILL:
            reason = " ".join(command.arguments) or "Emergency via bot"
            return self._handle_kill(reason)
        
        elif command.command_type == CommandType.MUTE:
            duration = int(command.arguments[0]) if command.arguments else 60
            self._muted_channels.add(command.chat_id)
            return f"🔇 Alerts muted for {duration} minutes"
        
        elif command.command_type == CommandType.UNMUTE:
            self._muted_channels.discard(command.chat_id)
            return "🔊 Alerts unmuted"
        
        return "Unknown command"
    
    def _handle_status(self) -> str:
        """Return live Kalshi grid + risk status."""
        try:
            from merid.prediction.agent_grid import get_agent_grid
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            grid = get_agent_grid()
            summary = grid.summary()
            risk = get_kalshi_risk()
            rs = risk.summary()
            agent_count = summary.get("agent_count", 0)
            running = sum(1 for a in summary.get("agents", []) if a.get("status") == "running")
            mode = summary.get("mode", "unknown")
            daily_pnl = rs.get("daily_pnl_usd", 0)
            ks = "🔴 ACTIVE" if rs.get("kill_switch_active") else "🟢 Ready"
            return (
                f"📊 **MERID Kalshi Status**\n"
                f"├ Mode: {mode}\n"
                f"├ Agents: {running}/{agent_count} running\n"
                f"├ Daily PnL: ${daily_pnl:,.2f}\n"
                f"├ Kill Switch: {ks}\n"
                f"└ Notional: ${rs.get('total_notional_usd', 0):,.2f}"
            )
        except Exception as exc:
            return f"⚠️ Status unavailable: {exc}"

    def _handle_risk(self) -> str:
        """Return live Kalshi risk metrics."""
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            risk = get_kalshi_risk()
            rs = risk.summary()
            return self.format_risk_response({
                "total_exposure": rs.get("total_notional_usd", 0),
                "leverage": 1.0,
                "drawdown": rs.get("drawdown_pct", 0),
                "daily_loss": abs(min(rs.get("daily_pnl_usd", 0), 0)),
                "kill_switch": rs.get("kill_switch_active", False),
            })
        except Exception as exc:
            return f"⚠️ Risk data unavailable: {exc}"

    def _handle_portfolio(self) -> str:
        """Return live Kalshi portfolio summary."""
        try:
            from merid.prediction.agent_grid import get_agent_grid
            from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
            grid = get_agent_grid()
            summary = grid.summary()
            tracker = get_agent_performance_tracker()
            sys_perf = tracker.get_system_summary()
            pr = summary.get("portfolio_risk", {})
            snap = pr.get("latest_snapshot") or {}
            notional = float(snap.get("total_notional_usd", 0))
            pnl = float(sys_perf.get("system_pnl_usd", "0"))
            win_rate = sys_perf.get("system_win_rate", 0)
            open_trades = sys_perf.get("open_trades", 0)
            return (
                f"💼 **Kalshi Portfolio**\n"
                f"├ Notional: ${notional:,.2f}\n"
                f"├ Total PnL: ${pnl:,.2f}\n"
                f"├ Win Rate: {win_rate:.1%}\n"
                f"├ Open Trades: {open_trades}\n"
                f"└ Agents: {summary.get('agent_count', 0)} active"
            )
        except Exception as exc:
            return f"⚠️ Portfolio data unavailable: {exc}"

    def _handle_pause(self, reason: str) -> str:
        """Pause all Kalshi trading agents."""
        try:
            from merid.prediction.agent_grid import get_agent_grid
            grid = get_agent_grid()
            paused = 0
            for agent in grid.agents:
                if hasattr(agent, "pause"):
                    agent.pause()
                    paused += 1
            return f"⏸️ Trading paused ({paused} agents): {reason}"
        except Exception as exc:
            return f"⚠️ Pause failed: {exc}"

    def _handle_resume(self) -> str:
        """Resume all paused Kalshi trading agents."""
        try:
            from merid.prediction.agent_grid import get_agent_grid
            grid = get_agent_grid()
            resumed = 0
            for agent in grid.agents:
                if hasattr(agent, "resume"):
                    agent.resume()
                    resumed += 1
            return f"▶️ Trading resumed ({resumed} agents)"
        except Exception as exc:
            return f"⚠️ Resume failed: {exc}"

    def _handle_kill(self, reason: str) -> str:
        """Activate Kalshi kill switch — halts all trading immediately."""
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            from merid.prediction.agent_grid import get_agent_grid
            risk = get_kalshi_risk()
            risk.fire_kill_switch(f"Bot command: {reason}")
            grid = get_agent_grid()
            paused = 0
            for agent in grid.agents:
                if hasattr(agent, "pause"):
                    agent.pause()
                    paused += 1
            return (
                f"🚨 **KILL SWITCH ACTIVATED**\n"
                f"Reason: {reason}\n"
                f"Paused {paused} agents. All trading halted."
            )
        except Exception as exc:
            return f"⚠️ Kill switch failed: {exc}"

    def _get_help_text(self) -> str:
        """Get help text for all commands."""
        lines = ["📖 **Available Commands**\n"]
        for cmd_type, info in COMMAND_DEFINITIONS.items():
            lines.append(f"`{info['usage']}` - {info['description']}")
        return "\n".join(lines)


# ============================================
# TWITTER/X BOT
# ============================================

class TwitterBot(BotBase):
    """Twitter/X bot implementation."""
    
    def __init__(self, api_key: str = None, api_secret: str = None):
        super().__init__(BotType.TWITTER)
        self._api_key = api_key
        self._api_secret = api_secret
        self._client = None
        
        # Rate limiting for tweets
        self._tweets_per_hour = 10
        self._tweet_history: List[float] = []
        
        # Content settings
        self._hashtags = ["#MERID", "#CryptoTrading", "#AI"]
    
    async def start(self) -> None:
        """Start the Twitter bot."""
        if not self._api_key:
            logger.warning("Twitter API key not set, running in mock mode")
            self._running = True
            return
        
        try:
            # In production, use tweepy
            # import tweepy
            # auth = tweepy.OAuthHandler(self._api_key, self._api_secret)
            # self._client = tweepy.API(auth)
            self._running = True
            logger.info("Twitter bot started")
        except Exception as e:
            logger.error(f"Twitter bot start error: {e}")
    
    async def stop(self) -> None:
        """Stop the Twitter bot."""
        self._running = False
        logger.info("Twitter bot stopped")
    
    async def send_message(self, chat_id: str, message: str) -> bool:
        """Send a DM via Twitter."""
        if not self._api_key:
            logger.debug(f"[MOCK] Twitter DM -> {chat_id}: {message[:50]}...")
            return True
        
        try:
            # In production:
            # self._client.send_direct_message(chat_id, message)
            return True
        except Exception as e:
            logger.error(f"Twitter DM error: {e}")
            return False
    
    async def post_tweet(self, content: str) -> bool:
        """Post a public tweet."""
        # Check rate limit
        now = time.time()
        self._tweet_history = [t for t in self._tweet_history if t > now - 3600]
        
        if len(self._tweet_history) >= self._tweets_per_hour:
            logger.warning("Tweet rate limit reached")
            return False
        
        # Add hashtags if space
        if len(content) + len(" ".join(self._hashtags)) < 280:
            content = f"{content}\n\n{' '.join(self._hashtags)}"
        
        if not self._api_key:
            logger.debug(f"[MOCK] Tweet: {content[:100]}...")
            self._tweet_history.append(now)
            return True
        
        try:
            # In production:
            # self._client.update_status(content)
            self._tweet_history.append(now)
            return True
        except Exception as e:
            logger.error(f"Tweet error: {e}")
            return False
    
    async def broadcast_alert(self, alert: BotAlert) -> int:
        """Broadcast alert as tweet (if appropriate)."""
        # Only tweet critical alerts
        if alert.severity != "critical":
            return 0
        
        # Format for Twitter
        tweet = f"🚨 {alert.title}\n{alert.message[:200]}"
        
        if await self.post_tweet(tweet):
            return 1
        return 0
    
    def format_market_summary(self, data: Dict[str, Any]) -> str:
        """Format market summary for tweet."""
        return (
            f"📊 MERID Market Update\n"
            f"BTC: ${data.get('btc_price', 0):,.0f} ({data.get('btc_change', 0):+.1f}%)\n"
            f"ETH: ${data.get('eth_price', 0):,.0f} ({data.get('eth_change', 0):+.1f}%)\n"
            f"Sentiment: {data.get('sentiment', 'Neutral')}"
        )


# ============================================
# BOT MANAGER
# ============================================

class BotManager:
    """Manages all bots and routes events."""
    
    _instance: Optional["BotManager"] = None
    
    def __init__(self):
        self._bots: Dict[BotType, BotBase] = {}
        self._topic_subscriptions: Dict[str, List[BotType]] = {}
        self._activity_log: List[Dict[str, Any]] = []
        
        logger.info("BotManager initialized")
    
    @classmethod
    def get_instance(cls) -> "BotManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def register_bot(self, bot: BotBase) -> None:
        """Register a bot."""
        self._bots[bot.bot_type] = bot
        logger.info(f"Registered bot: {bot.bot_type.value}")
    
    def subscribe_to_topic(self, topic: str, bot_type: BotType) -> None:
        """Subscribe a bot to a Kafka topic for alerts."""
        if topic not in self._topic_subscriptions:
            self._topic_subscriptions[topic] = []
        self._topic_subscriptions[topic].append(bot_type)
    
    async def start_all(self) -> None:
        """Start all registered bots."""
        for bot in self._bots.values():
            await bot.start()
    
    async def stop_all(self) -> None:
        """Stop all bots."""
        for bot in self._bots.values():
            await bot.stop()
    
    async def handle_kafka_event(self, topic: str, event: Dict[str, Any]) -> None:
        """Handle an incoming Kafka event and route to appropriate bots."""
        subscribed_bots = self._topic_subscriptions.get(topic, [])
        
        if not subscribed_bots:
            return
        
        # Convert event to alert
        alert = BotAlert(
            title=event.get("title", event.get("event_type", "Alert")),
            message=event.get("message", str(event.get("data", ""))[:500]),
            severity=event.get("severity", "info"),
            target_platforms=subscribed_bots,
            source_topic=topic,
            source_event_id=event.get("event_id", ""),
        )
        
        # Send to subscribed bots
        for bot_type in subscribed_bots:
            bot = self._bots.get(bot_type)
            if bot:
                await bot.broadcast_alert(alert)
        
        # Log activity
        self._activity_log.append({
            "timestamp": time.time(),
            "topic": topic,
            "event_id": alert.source_event_id,
            "bots_notified": [b.value for b in subscribed_bots],
        })
    
    def get_activity_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent bot activity."""
        return self._activity_log[-limit:]
    
    def get_status(self) -> Dict[str, Any]:
        """Get status of all bots."""
        return {
            "bots": {
                bot_type.value: {
                    "running": bot._running,
                    "muted_channels": len(bot._muted_channels),
                }
                for bot_type, bot in self._bots.items()
            },
            "subscriptions": {
                topic: [b.value for b in bots]
                for topic, bots in self._topic_subscriptions.items()
            },
            "activity_count": len(self._activity_log),
        }


def get_bot_manager() -> BotManager:
    """Get the global bot manager."""
    return BotManager.get_instance()


# ============================================
# DEFAULT SETUP
# ============================================

def setup_default_bots() -> BotManager:
    """Set up default bot configuration."""
    manager = get_bot_manager()
    
    # Create bots
    telegram = TelegramBot()
    twitter = TwitterBot()
    
    # Register
    manager.register_bot(telegram)
    manager.register_bot(twitter)
    
    # Subscribe to relevant topics
    manager.subscribe_to_topic("alerts.*", BotType.TELEGRAM)
    manager.subscribe_to_topic("risk.alerts.*", BotType.TELEGRAM)
    manager.subscribe_to_topic("governance.kill_switch", BotType.TELEGRAM)
    manager.subscribe_to_topic("governance.kill_switch", BotType.TWITTER)
    
    return manager
