"""
Notification Configuration Management
Manages routing preferences and channel settings for debate alerts.
"""

import os
import yaml
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum

logger = logging.getLogger(__name__)

class NotificationChannel(Enum):
    """Available notification channels."""
    TELEGRAM = "telegram"
    X_TWITTER = "x_twitter"

@dataclass
class ChannelConfig:
    """Configuration for a notification channel."""
    enabled: bool = True
    rate_limit_messages_per_hour: int = 50
    rate_limit_tweets_per_day: int = 20
    critical_alerts: bool = True
    warning_alerts: bool = True
    daily_summary: bool = True

@dataclass
class RoutingConfig:
    """Configuration for alert routing rules."""
    critical_to_telegram: bool = True
    critical_to_x: bool = True
    warnings_to_telegram: bool = True
    warnings_to_x: bool = False
    high_utilization_only: bool = False  # Only send warnings for >90% utilization
    aggregate_similar: bool = True  # Aggregate similar alerts to reduce spam

@dataclass
class NotificationConfig:
    """Complete notification configuration."""
    channels: Dict[str, ChannelConfig]
    routing: RoutingConfig
    poll_interval_minutes: int = 5
    daily_summary_time_utc: int = 9  # 9 AM UTC

class NotificationConfigManager:
    """Manages notification configuration from files and environment variables."""
    
    def __init__(self, config_file: Optional[str] = None):
        """
        Initialize config manager.
        
        Args:
            config_file: Path to YAML config file (defaults to notification_config.yaml)
        """
        self.config_file = config_file or "notification_config.yaml"
        self.config: Optional[NotificationConfig] = None
        self.load_config()
    
    def load_config(self):
        """Load configuration from file and environment variables."""
        # Start with defaults
        self.config = NotificationConfig(
            channels={
                "telegram": ChannelConfig(
                    enabled=os.getenv("TELEGRAM_ENABLED", "true").lower() == "true",
                    critical_alerts=os.getenv("TELEGRAM_CRITICAL_ALERTS", "true").lower() == "true",
                    warning_alerts=os.getenv("TELEGRAM_WARNING_ALERTS", "true").lower() == "true",
                    daily_summary=os.getenv("TELEGRAM_DAILY_SUMMARY", "true").lower() == "true"
                ),
                "x_twitter": ChannelConfig(
                    enabled=os.getenv("X_ENABLED", "false").lower() == "true",
                    critical_alerts=os.getenv("X_CRITICAL_ALERTS", "false").lower() == "true",
                    warning_alerts=os.getenv("X_WARNING_ALERTS", "false").lower() == "true",
                    daily_summary=os.getenv("X_DAILY_SUMMARY", "false").lower() == "true"
                )
            },
            routing=RoutingConfig(
                critical_to_telegram=os.getenv("CRITICAL_TO_TELEGRAM", "true").lower() == "true",
                critical_to_x=os.getenv("CRITICAL_TO_X", "false").lower() == "true",
                warnings_to_telegram=os.getenv("WARNINGS_TO_TELEGRAM", "true").lower() == "true",
                warnings_to_x=os.getenv("WARNINGS_TO_X", "false").lower() == "true",
                high_utilization_only=os.getenv("HIGH_UTILIZATION_ONLY", "false").lower() == "true",
                aggregate_similar=os.getenv("AGGREGATE_SIMILAR", "true").lower() == "true"
            ),
            poll_interval_minutes=int(os.getenv("NOTIFICATION_POLL_MINUTES", "5")),
            daily_summary_time_utc=int(os.getenv("DAILY_SUMMARY_TIME_UTC", "9"))
        )
        
        # Load from file if it exists
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    file_config = yaml.safe_load(f)
                
                # Merge file config with defaults
                self._merge_config(file_config)
                logger.info(f"Loaded notification config from {self.config_file}")
                
            except Exception as e:
                logger.error(f"Error loading config file {self.config_file}: {e}")
                logger.info("Using default configuration")
        else:
            # Create default config file
            self.save_config()
            logger.info(f"Created default config file: {self.config_file}")
    
    def _merge_config(self, file_config: Dict[str, Any]):
        """Merge file configuration with defaults."""
        if "channels" in file_config:
            for channel_name, channel_config in file_config["channels"].items():
                if channel_name in self.config.channels:
                    # Update existing channel config
                    current = asdict(self.config.channels[channel_name])
                    current.update(channel_config)
                    self.config.channels[channel_name] = ChannelConfig(**current)
                else:
                    # Add new channel config
                    self.config.channels[channel_name] = ChannelConfig(**channel_config)
        
        if "routing" in file_config:
            current_routing = asdict(self.config.routing)
            current_routing.update(file_config["routing"])
            self.config.routing = RoutingConfig(**current_routing)
        
        # Update other top-level fields
        for key in ["poll_interval_minutes", "daily_summary_time_utc"]:
            if key in file_config:
                setattr(self.config, key, file_config[key])
    
    def save_config(self):
        """Save current configuration to file."""
        try:
            config_dict = {
                "channels": {
                    name: asdict(channel) 
                    for name, channel in self.config.channels.items()
                },
                "routing": asdict(self.config.routing),
                "poll_interval_minutes": self.config.poll_interval_minutes,
                "daily_summary_time_utc": self.config.daily_summary_time_utc
            }
            
            with open(self.config_file, 'w') as f:
                yaml.dump(config_dict, f, default_flow_style=False, indent=2)
            
            logger.info(f"Saved notification config to {self.config_file}")
            
        except Exception as e:
            logger.error(f"Error saving config file: {e}")
    
    def get_channel_config(self, channel: NotificationChannel) -> ChannelConfig:
        """Get configuration for a specific channel."""
        return self.config.channels.get(channel.value, ChannelConfig())
    
    def is_channel_enabled(self, channel: NotificationChannel) -> bool:
        """Check if a channel is enabled."""
        channel_config = self.get_channel_config(channel)
        return channel_config.enabled
    
    def should_send_alert(self, severity: str, channel: NotificationChannel) -> bool:
        """Check if an alert of given severity should be sent to a channel."""
        channel_config = self.get_channel_config(channel)
        
        if not channel_config.enabled:
            return False
        
        if severity == "critical":
            return channel_config.critical_alerts
        elif severity == "warning":
            return channel_config.warning_alerts
        
        return False
    
    def should_send_daily_summary(self, channel: NotificationChannel) -> bool:
        """Check if daily summary should be sent to a channel."""
        channel_config = self.get_channel_config(channel)
        return channel_config.enabled and channel_config.daily_summary
    
    def get_routing_rules(self) -> RoutingConfig:
        """Get routing configuration."""
        return self.config.routing
    
    def update_channel_config(self, channel: NotificationChannel, updates: Dict[str, Any]):
        """Update configuration for a specific channel."""
        if channel.value not in self.config.channels:
            self.config.channels[channel.value] = ChannelConfig()
        
        current = asdict(self.config.channels[channel.value])
        current.update(updates)
        self.config.channels[channel.value] = ChannelConfig(**current)
        
        self.save_config()
        logger.info(f"Updated {channel.value} channel config")
    
    def update_routing_config(self, updates: Dict[str, Any]):
        """Update routing configuration."""
        current = asdict(self.config.routing)
        current.update(updates)
        self.config.routing = RoutingConfig(**current)
        
        self.save_config()
        logger.info("Updated routing config")

# Global config manager instance
_config_manager: Optional[NotificationConfigManager] = None

def get_notification_config() -> NotificationConfigManager:
    """Get or create the global notification config manager."""
    global _config_manager
    if _config_manager is None:
        _config_manager = NotificationConfigManager()
    return _config_manager
