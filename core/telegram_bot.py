"""MERID Telegram Bot for Trading Alerts and Notifications.

Real-time alerts for trading signals, risk breaches, and swarm agent notifications.
Supports both python-telegram-bot and aiogram for async operations.
"""

from typing import List, Optional, Dict, Any, Callable
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime
import asyncio
import structlog
import os

logger = structlog.get_logger(__name__)


@dataclass
class TelegramAlert:
    """Trading alert/notification message."""
    alert_type: str  # signal, risk, error, info
    ticker: Optional[str]
    message: str
    severity: str  # low, medium, high, critical
    timestamp: datetime
    data: Dict[str, Any]
    
    def format_message(self) -> str:
        """Format alert for Telegram."""
        emoji_map = {
            "signal": "📊",
            "risk": "⚠️",
            "error": "❌",
            "info": "ℹ️",
            "success": "✅"
        }
        
        severity_emoji = {
            "low": "🟢",
            "medium": "🟡",
            "high": "🟠",
            "critical": "🔴"
        }
        
        emoji = emoji_map.get(self.alert_type, "📢")
        sev = severity_emoji.get(self.severity, "⚪")
        
        ticker_str = f" #{self.ticker}" if self.ticker else ""
        
        lines = [
            f"{emoji}{sev} *MERID Alert*{ticker_str}",
            f"",
            f"{self.message}",
            f"",
            f"🕐 {self.timestamp.strftime('%H:%M:%S')}"
        ]
        
        # Add extra data if present
        if self.data:
            lines.append("")
            for key, value in self.data.items():
                lines.append(f"• {key}: {value}")
        
        return "\n".join(lines)


class TelegramNotifier:
    """Telegram notification bot using python-telegram-bot."""
    
    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None
    ):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.application = None
        self.logger = logger.bind(component="TelegramNotifier")
        
        self._init_bot()
    
    def _init_bot(self):
        """Initialize Telegram bot."""
        if not self.bot_token:
            self.logger.warning("telegram_bot_token_missing")
            return
        
        try:
            from telegram import Bot
            from telegram.ext import Application
            
            self.application = Application.builder().token(self.bot_token).build()
            self.logger.info("telegram_bot_initialized")
            
        except ImportError:
            self.logger.warning("python_telegram_bot_not_installed — Telegram notifications disabled")
        except Exception as e:
            self.logger.error("telegram_init_error", error=str(e))
    
    async def send_alert(self, alert: TelegramAlert) -> bool:
        """Send an alert message."""
        if not self.application or not self.chat_id:
            self.logger.debug("telegram_not_configured")
            return False
        
        try:
            message = alert.format_message()
            
            await self.application.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="Markdown"
            )
            
            self.logger.info(
                "telegram_alert_sent",
                type=alert.alert_type,
                ticker=alert.ticker
            )
            
            return True
            
        except Exception as e:
            self.logger.error("telegram_send_error", error=str(e))
            return False
    
    async def send_signal(
        self,
        ticker: str,
        signal: str,
        price: Decimal,
        confidence: float
    ) -> bool:
        """Send trading signal alert."""
        alert = TelegramAlert(
            alert_type="signal",
            ticker=ticker,
            message=f"Trading Signal: {signal}",
            severity="medium",
            timestamp=datetime.now(),
            data={
                "Price": f"${float(price):.2f}",
                "Confidence": f"{confidence:.1%}",
                "Action": signal
            }
        )
        
        return await self.send_alert(alert)
    
    async def send_risk_alert(
        self,
        ticker: str,
        risk_type: str,
        current_value: Decimal,
        threshold: Decimal
    ) -> bool:
        """Send risk breach alert."""
        alert = TelegramAlert(
            alert_type="risk",
            ticker=ticker,
            message=f"Risk Alert: {risk_type}",
            severity="high",
            timestamp=datetime.now(),
            data={
                "Current": f"{float(current_value):.2f}",
                "Threshold": f"{float(threshold):.2f}",
                "Breach": risk_type
            }
        )
        
        return await self.send_alert(alert)
    
    async def send_error(self, error_message: str, context: str = "") -> bool:
        """Send error notification."""
        alert = TelegramAlert(
            alert_type="error",
            ticker=None,
            message=f"Error: {error_message}",
            severity="critical",
            timestamp=datetime.now(),
            data={"Context": context} if context else {}
        )
        
        return await self.send_alert(alert)
    
    async def send_summary(
        self,
        title: str,
        metrics: Dict[str, Any]
    ) -> bool:
        """Send summary/periodic report."""
        lines = [f"📊 *{title}*", ""]
        
        for key, value in metrics.items():
            lines.append(f"• {key}: {value}")
        
        if not self.application or not self.chat_id:
            return False
        
        try:
            await self.application.bot.send_message(
                chat_id=self.chat_id,
                text="\n".join(lines),
                parse_mode="Markdown"
            )
            return True
        except Exception as e:
            self.logger.error("summary_send_error", error=str(e))
            return False


class AiogramNotifier:
    """Alternative Telegram notifier using aiogram (async-first)."""
    
    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None
    ):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.bot = None
        self.logger = logger.bind(component="AiogramNotifier")
        
        self._init_bot()
    
    def _init_bot(self):
        """Initialize aiogram bot."""
        if not self.bot_token:
            self.logger.warning("aiogram_token_missing")
            return
        
        try:
            from aiogram import Bot
            
            self.bot = Bot(token=self.bot_token)
            self.logger.info("aiogram_bot_initialized")
            
        except ImportError:
            self.logger.error("aiogram_not_installed")
        except Exception as e:
            self.logger.error("aiogram_init_error", error=str(e))
    
    async def send_alert(self, alert: TelegramAlert) -> bool:
        """Send alert using aiogram."""
        if not self.bot or not self.chat_id:
            return False
        
        try:
            from aiogram.enums import ParseMode
            
            message = alert.format_message()
            
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
            
            self.logger.info("aiogram_alert_sent", type=alert.alert_type)
            return True
            
        except Exception as e:
            self.logger.error("aiogram_send_error", error=str(e))
            return False
    
    async def close(self):
        """Close bot session."""
        if self.bot:
            await self.bot.session.close()


class SwarmTelegramBridge:
    """Bridge between swarm agents and Telegram notifications."""
    
    def __init__(self, notifier: Optional[TelegramNotifier] = None):
        self.notifier = notifier or TelegramNotifier()
        self.logger = logger.bind(component="SwarmTelegramBridge")
        self.subscribers: Dict[str, List[str]] = {}  # ticker -> chat_ids
    
    async def notify_trade_signal(
        self,
        ticker: str,
        signal: str,
        price: Decimal,
        confidence: float,
        agent: str
    ):
        """Notify about trade signal from swarm agent."""
        self.logger.info(
            "swarm_signal_notify",
            ticker=ticker,
            signal=signal,
            agent=agent
        )
        
        await self.notifier.send_signal(ticker, signal, price, confidence)
    
    async def notify_risk_breach(
        self,
        ticker: str,
        risk_type: str,
        current: Decimal,
        threshold: Decimal,
        agent: str
    ):
        """Notify about risk breach from risk agent."""
        self.logger.warning(
            "swarm_risk_notify",
            ticker=ticker,
            risk=risk_type,
            agent=agent
        )
        
        await self.notifier.send_risk_alert(ticker, risk_type, current, threshold)
    
    async def notify_sentiment_spike(
        self,
        ticker: str,
        sentiment_score: float,
        source: str,
        mention_count: int
    ):
        """Notify about significant sentiment change."""
        severity = "high" if abs(sentiment_score) > 0.7 else "medium"
        
        alert = TelegramAlert(
            alert_type="info",
            ticker=ticker,
            message=f"Sentiment Alert from {source}",
            severity=severity,
            timestamp=datetime.now(),
            data={
                "Score": f"{sentiment_score:.2f}",
                "Mentions": mention_count,
                "Source": source
            }
        )
        
        await self.notifier.send_alert(alert)
    
    async def send_daily_summary(self, portfolio_data: Dict[str, Any]):
        """Send daily portfolio summary."""
        metrics = {
            "Portfolio Value": f"${portfolio_data.get('value', 0):,.2f}",
            "Daily P&L": f"${portfolio_data.get('pnl', 0):,.2f}",
            "Active Positions": portfolio_data.get('positions', 0),
            "Open Orders": portfolio_data.get('orders', 0),
            "Swarm Status": portfolio_data.get('swarm_status', 'Unknown')
        }
        
        await self.notifier.send_summary("Daily Portfolio Summary", metrics)
    
    def subscribe_to_ticker(self, ticker: str, chat_id: str):
        """Subscribe a chat to ticker alerts."""
        ticker = ticker.upper()
        if ticker not in self.subscribers:
            self.subscribers[ticker] = []
        
        if chat_id not in self.subscribers[ticker]:
            self.subscribers[ticker].append(chat_id)
            self.logger.info("ticker_subscribed", ticker=ticker, chat_id=chat_id[:8])
    
    def unsubscribe_from_ticker(self, ticker: str, chat_id: str):
        """Unsubscribe a chat from ticker alerts."""
        ticker = ticker.upper()
        if ticker in self.subscribers and chat_id in self.subscribers[ticker]:
            self.subscribers[ticker].remove(chat_id)
            self.logger.info("ticker_unsubscribed", ticker=ticker)


class AlertScheduler:
    """Schedule and manage recurring alerts."""
    
    def __init__(self, notifier: TelegramNotifier):
        self.notifier = notifier
        self.logger = logger.bind(component="AlertScheduler")
        self.scheduled_tasks: Dict[str, asyncio.Task] = {}
    
    async def schedule_price_alert(
        self,
        ticker: str,
        target_price: Decimal,
        condition: str,  # above, below
        interval: int = 60
    ):
        """Schedule a price-based alert."""
        task_id = f"price_{ticker}_{condition}_{target_price}"
        
        async def check_price():
            # Placeholder - would fetch actual price
            while True:
                await asyncio.sleep(interval)
        
        task = asyncio.create_task(check_price())
        self.scheduled_tasks[task_id] = task
        
        self.logger.info(
            "price_alert_scheduled",
            ticker=ticker,
            target=str(target_price),
            condition=condition
        )
    
    async def schedule_sentiment_digest(
        self,
        tickers: List[str],
        interval_hours: int = 4
    ):
        """Schedule periodic sentiment digest."""
        task_id = f"sentiment_digest_{'_'.join(tickers)}"
        
        async def send_digest():
            while True:
                await asyncio.sleep(interval_hours * 3600)
                # Fetch and send sentiment summary
                # await self.send_sentiment_summary(tickers)
        
        task = asyncio.create_task(send_digest())
        self.scheduled_tasks[task_id] = task
    
    def cancel_alert(self, task_id: str):
        """Cancel a scheduled alert."""
        if task_id in self.scheduled_tasks:
            self.scheduled_tasks[task_id].cancel()
            del self.scheduled_tasks[task_id]
            self.logger.info("alert_cancelled", task_id=task_id)


# Singleton instances
telegram_notifier = TelegramNotifier()
swarm_telegram_bridge = SwarmTelegramBridge()
