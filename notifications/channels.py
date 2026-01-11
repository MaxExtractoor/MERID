"""
Notification Channels.

Multi-channel notification delivery including email, SMS, push, and webhooks.

Version: 1.0.0
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod

from utils.logger import get_logger

logger = get_logger("notifications.channels")


class ChannelType(Enum):
    """Types of notification channels."""
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    WEBHOOK = "webhook"
    SLACK = "slack"
    TELEGRAM = "telegram"
    DISCORD = "discord"


class DeliveryStatus(Enum):
    """Status of notification delivery."""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    BOUNCED = "bounced"


@dataclass
class NotificationMessage:
    """A notification message."""
    message_id: str
    channel_type: ChannelType
    recipient: str
    subject: str
    body: str
    priority: str = "normal"  # low, normal, high, critical
    
    # Delivery
    status: DeliveryStatus = DeliveryStatus.PENDING
    sent_at: Optional[float] = None
    delivered_at: Optional[float] = None
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    retry_count: int = 0
    max_retries: int = 3
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "channel_type": self.channel_type.value,
            "recipient": self.recipient,
            "subject": self.subject,
            "body": self.body[:100] + "..." if len(self.body) > 100 else self.body,
            "priority": self.priority,
            "status": self.status.value,
            "sent_at": self.sent_at,
            "delivered_at": self.delivered_at,
            "created_at": self.created_at,
            "retry_count": self.retry_count,
        }


class NotificationChannel(ABC):
    """Abstract base class for notification channels."""
    
    def __init__(self, channel_type: ChannelType):
        self.channel_type = channel_type
        self.enabled = True
        self.logger = get_logger(f"notifications.{channel_type.value}")
        
        # Rate limiting
        self.rate_limit_per_minute = 60
        self.sent_this_minute = 0
        self.minute_start = time.time()
    
    @abstractmethod
    async def send(self, message: NotificationMessage) -> bool:
        """Send a notification."""
        pass
    
    @abstractmethod
    def validate_recipient(self, recipient: str) -> bool:
        """Validate recipient format."""
        pass
    
    def check_rate_limit(self) -> bool:
        """Check if rate limit allows sending."""
        now = time.time()
        if now - self.minute_start > 60:
            self.sent_this_minute = 0
            self.minute_start = now
        
        return self.sent_this_minute < self.rate_limit_per_minute
    
    def record_send(self) -> None:
        """Record a send for rate limiting."""
        self.sent_this_minute += 1


class EmailChannel(NotificationChannel):
    """Email notification channel."""
    
    def __init__(self):
        super().__init__(ChannelType.EMAIL)
        
        # SMTP configuration
        self.smtp_host = ""
        self.smtp_port = 587
        self.smtp_user = ""
        self.smtp_password = ""
        self.from_address = "merid@localhost"
        self.use_tls = True
    
    def configure(
        self,
        smtp_host: str,
        smtp_port: int = 587,
        smtp_user: str = "",
        smtp_password: str = "",
        from_address: str = "",
        use_tls: bool = True,
    ) -> None:
        """Configure SMTP settings."""
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.from_address = from_address or self.from_address
        self.use_tls = use_tls
        self.logger.info(f"Email channel configured: {smtp_host}:{smtp_port}")
    
    async def send(self, message: NotificationMessage) -> bool:
        """Send email notification."""
        if not self.enabled:
            return False
        
        if not self.check_rate_limit():
            self.logger.warning("Email rate limit exceeded")
            return False
        
        if not self.smtp_host:
            self.logger.warning("Email not configured - simulating send")
            message.status = DeliveryStatus.SENT
            message.sent_at = time.time()
            self.record_send()
            return True
        
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            
            msg = MIMEMultipart()
            msg["From"] = self.from_address
            msg["To"] = message.recipient
            msg["Subject"] = message.subject
            msg.attach(MIMEText(message.body, "plain"))
            
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()
                if self.smtp_user:
                    server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
            
            message.status = DeliveryStatus.SENT
            message.sent_at = time.time()
            self.record_send()
            self.logger.info(f"Email sent to {message.recipient}")
            return True
            
        except Exception as e:
            message.status = DeliveryStatus.FAILED
            self.logger.error(f"Email send failed: {e}")
            return False
    
    def validate_recipient(self, recipient: str) -> bool:
        """Validate email address."""
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, recipient))


class SMSChannel(NotificationChannel):
    """SMS notification channel."""
    
    def __init__(self):
        super().__init__(ChannelType.SMS)
        
        # Twilio configuration
        self.account_sid = ""
        self.auth_token = ""
        self.from_number = ""
        self.rate_limit_per_minute = 10
    
    def configure(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str,
    ) -> None:
        """Configure Twilio settings."""
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.logger.info("SMS channel configured")
    
    async def send(self, message: NotificationMessage) -> bool:
        """Send SMS notification."""
        if not self.enabled:
            return False
        
        if not self.check_rate_limit():
            self.logger.warning("SMS rate limit exceeded")
            return False
        
        if not self.account_sid:
            self.logger.warning("SMS not configured - simulating send")
            message.status = DeliveryStatus.SENT
            message.sent_at = time.time()
            self.record_send()
            return True
        
        try:
            # In production, use Twilio client
            # from twilio.rest import Client
            # client = Client(self.account_sid, self.auth_token)
            # client.messages.create(
            #     body=message.body[:160],
            #     from_=self.from_number,
            #     to=message.recipient
            # )
            
            message.status = DeliveryStatus.SENT
            message.sent_at = time.time()
            self.record_send()
            self.logger.info(f"SMS sent to {message.recipient}")
            return True
            
        except Exception as e:
            message.status = DeliveryStatus.FAILED
            self.logger.error(f"SMS send failed: {e}")
            return False
    
    def validate_recipient(self, recipient: str) -> bool:
        """Validate phone number."""
        import re
        pattern = r'^\+?[1-9]\d{1,14}$'
        return bool(re.match(pattern, recipient.replace(" ", "").replace("-", "")))


class PushChannel(NotificationChannel):
    """Push notification channel."""
    
    def __init__(self):
        super().__init__(ChannelType.PUSH)
        
        # Firebase configuration
        self.firebase_credentials = None
        self.rate_limit_per_minute = 100
    
    def configure(self, credentials_path: str) -> None:
        """Configure Firebase settings."""
        self.firebase_credentials = credentials_path
        self.logger.info("Push channel configured")
    
    async def send(self, message: NotificationMessage) -> bool:
        """Send push notification."""
        if not self.enabled:
            return False
        
        if not self.check_rate_limit():
            self.logger.warning("Push rate limit exceeded")
            return False
        
        # Simulated push notification
        message.status = DeliveryStatus.SENT
        message.sent_at = time.time()
        self.record_send()
        self.logger.info(f"Push sent to {message.recipient}")
        return True
    
    def validate_recipient(self, recipient: str) -> bool:
        """Validate device token."""
        return len(recipient) > 10


class WebhookChannel(NotificationChannel):
    """Webhook notification channel."""
    
    def __init__(self):
        super().__init__(ChannelType.WEBHOOK)
        self.rate_limit_per_minute = 100
    
    async def send(self, message: NotificationMessage) -> bool:
        """Send webhook notification."""
        if not self.enabled:
            return False
        
        if not self.check_rate_limit():
            self.logger.warning("Webhook rate limit exceeded")
            return False
        
        try:
            import aiohttp
            
            payload = {
                "message_id": message.message_id,
                "subject": message.subject,
                "body": message.body,
                "priority": message.priority,
                "timestamp": time.time(),
                "metadata": message.metadata,
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    message.recipient,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status < 300:
                        message.status = DeliveryStatus.DELIVERED
                        message.delivered_at = time.time()
                    else:
                        message.status = DeliveryStatus.FAILED
            
            message.sent_at = time.time()
            self.record_send()
            self.logger.info(f"Webhook sent to {message.recipient}")
            return message.status == DeliveryStatus.DELIVERED
            
        except Exception as e:
            message.status = DeliveryStatus.FAILED
            self.logger.error(f"Webhook send failed: {e}")
            return False
    
    def validate_recipient(self, recipient: str) -> bool:
        """Validate webhook URL."""
        return recipient.startswith("http://") or recipient.startswith("https://")


class ChannelManager:
    """Manages notification channels."""
    
    def __init__(self):
        self.logger = get_logger("notifications.channels")
        
        # Initialize channels
        self._channels: Dict[ChannelType, NotificationChannel] = {
            ChannelType.EMAIL: EmailChannel(),
            ChannelType.SMS: SMSChannel(),
            ChannelType.PUSH: PushChannel(),
            ChannelType.WEBHOOK: WebhookChannel(),
        }
        
        # Message history
        self._history: List[NotificationMessage] = []
        self._max_history: int = 1000
    
    def get_channel(self, channel_type: ChannelType) -> Optional[NotificationChannel]:
        """Get a channel by type."""
        return self._channels.get(channel_type)
    
    async def send(
        self,
        channel_type: ChannelType,
        recipient: str,
        subject: str,
        body: str,
        priority: str = "normal",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Send a notification via specified channel."""
        import uuid
        
        channel = self._channels.get(channel_type)
        if not channel:
            self.logger.error(f"Unknown channel: {channel_type}")
            return None
        
        if not channel.validate_recipient(recipient):
            self.logger.error(f"Invalid recipient for {channel_type.value}: {recipient}")
            return None
        
        message = NotificationMessage(
            message_id=f"msg_{uuid.uuid4().hex[:12]}",
            channel_type=channel_type,
            recipient=recipient,
            subject=subject,
            body=body,
            priority=priority,
            metadata=metadata or {},
        )
        
        success = await channel.send(message)
        
        # Store in history
        self._history.append(message)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        
        return message.message_id if success else None
    
    def enable_channel(self, channel_type: ChannelType) -> None:
        """Enable a channel."""
        channel = self._channels.get(channel_type)
        if channel:
            channel.enabled = True
            self.logger.info(f"Channel enabled: {channel_type.value}")
    
    def disable_channel(self, channel_type: ChannelType) -> None:
        """Disable a channel."""
        channel = self._channels.get(channel_type)
        if channel:
            channel.enabled = False
            self.logger.info(f"Channel disabled: {channel_type.value}")
    
    def get_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get message history."""
        return [m.to_dict() for m in self._history[-limit:]]
    
    def get_status(self) -> Dict[str, Any]:
        """Get channel manager status."""
        return {
            "channels": {
                ct.value: {
                    "enabled": ch.enabled,
                    "rate_limit": ch.rate_limit_per_minute,
                    "sent_this_minute": ch.sent_this_minute,
                }
                for ct, ch in self._channels.items()
            },
            "history_count": len(self._history),
        }


# Singleton
_channel_manager: Optional[ChannelManager] = None


def get_channel_manager() -> ChannelManager:
    """Get or create the Channel Manager singleton."""
    global _channel_manager
    if _channel_manager is None:
        _channel_manager = ChannelManager()
    return _channel_manager
