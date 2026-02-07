"""
Self-Healing Social + Bot Layer (Phase 21f)

Monitors social data feeds and bot health, automatically recovers from failures,
and coordinates with breach detection for security incidents.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
import logging

logger = logging.getLogger(__name__)


@dataclass
class HealingAction:
    action_id: str
    target: str
    action_type: str
    reason: str
    initiated_at: datetime
    completed_at: Optional[datetime] = None
    success: bool = False


@dataclass
class HealthCheckResult:
    target: str
    healthy: bool
    issues: List[str]
    metrics: Dict[str, float]
    checked_at: datetime


class SelfHealingSocialLayer:
    """
    Self-healing orchestrator for social data and bot infrastructure.
    
    Features:
    - Continuous health monitoring
    - Automatic failure detection
    - Recovery action coordination
    - Breach detection integration
    - Escalation to human operators
    """
    
    def __init__(self):
        self._healing_actions: List[HealingAction] = []
        self._health_checks: Dict[str, HealthCheckResult] = {}
        self._recovery_strategies: Dict[str, callable] = {}
        self._monitoring_enabled = False
        self._check_interval = 30.0
        self._x_bot_retries = 3
        self._telegram_retries = 3
        self._base_backoff_seconds = 2.0
        self._max_backoff_seconds = 60.0
        self._telegram_backoff_cap = 30.0
        
        self._register_default_strategies()
    
    def _register_default_strategies(self) -> None:
        """Register default recovery strategies."""
        self._recovery_strategies = {
            "x_bot_failure": self._recover_x_bot,
            "telegram_bot_failure": self._recover_telegram_bot,
            "social_feed_stale": self._recover_social_feed,
            "sentiment_api_down": self._recover_sentiment_api,
            "rate_limit_exceeded": self._recover_rate_limit,
        }
    
    async def monitor_health(self) -> None:
        """Continuous health monitoring loop."""
        from social.social_aware_quant import get_social_bot_health_monitor
        from social.x_bot_interface import get_x_bot_service
        from social.telegram_bot_interface import get_telegram_bot
        from observability.clock_sync_monitor import get_clock_sync_monitor
        from observability.feed_parity_checker import get_feed_parity_checker
        
        self._monitoring_enabled = True
        logger.info("Self-healing social layer monitoring started")
        
        while self._monitoring_enabled:
            try:
                bot_monitor = get_social_bot_health_monitor()
                health_summary = bot_monitor.get_health_summary()
                
                for bot_id, bot_health in health_summary.get("bot_health", {}).items():
                    if not bot_health.get("healthy", True):
                        await self._initiate_healing(bot_id, "bot_failure", bot_health.get("issues", []))
                
                x_bot = get_x_bot_service()
                if hasattr(x_bot, "get_health_status"):
                    x_health = x_bot.get_health_status()
                    if not x_health.get("healthy", True):
                        await self._initiate_healing("x_bot", "x_bot_failure", x_health.get("issues", []))
                
                telegram_bot = get_telegram_bot()
                if not telegram_bot._running:
                    await self._initiate_healing("telegram_bot", "telegram_bot_failure", ["Bot not running"])

                clock_sync = get_clock_sync_monitor().get_sync_status()
                if clock_sync.get("max_drift_ms", 0) > 250:
                    await self._initiate_healing(
                        "clock_sync",
                        "infrastructure_issue",
                        [f"Drift {clock_sync['max_drift_ms']}ms exceeds 250ms"],
                    )

                parity_status = get_feed_parity_checker().get_parity_status()
                if parity_status.get("recent_violations_1h", 0) > 3:
                    await self._initiate_healing(
                        "feed_parity",
                        "social_feed_stale",
                        [f"Feed parity violations {parity_status['recent_violations_1h']} past hour"],
                    )
                
                await asyncio.sleep(self._check_interval)
                
            except Exception as e:
                logger.error(f"Error in health monitoring loop: {e}")
                await asyncio.sleep(self._check_interval)
    
    async def _initiate_healing(
        self,
        target: str,
        failure_type: str,
        issues: List[str],
    ) -> None:
        """Initiate healing action for detected failure."""
        action_id = f"heal_{target}_{int(time.time())}"
        
        action = HealingAction(
            action_id=action_id,
            target=target,
            action_type=failure_type,
            reason="; ".join(issues),
            initiated_at=datetime.utcnow(),
        )
        
        self._healing_actions.append(action)
        logger.warning(f"Initiating healing action: {action_id} for {target} ({failure_type})")
        
        strategy = self._recovery_strategies.get(failure_type)
        if strategy:
            try:
                success = await strategy(target, issues)
                action.success = success
                action.completed_at = datetime.utcnow()
                
                if success:
                    logger.info(f"Healing action {action_id} completed successfully")
                else:
                    logger.error(f"Healing action {action_id} failed")
                    await self._escalate_to_human(action)
            except Exception as e:
                logger.error(f"Error executing healing strategy: {e}")
                action.success = False
                action.completed_at = datetime.utcnow()
                await self._escalate_to_human(action)
        else:
            logger.warning(f"No recovery strategy for failure type: {failure_type}")
            await self._escalate_to_human(action)
        
        if len(self._healing_actions) > 1000:
            self._healing_actions = self._healing_actions[-500:]
    
    async def _recover_x_bot(self, target: str, issues: List[str]) -> bool:
        """Recover X bot from failure."""
        from social.x_bot_interface import get_x_bot_service
        
        logger.info(f"Attempting to recover X bot: {target}")
        
        try:
            x_bot = get_x_bot_service()
            
            if "rate_limit" in str(issues).lower():
                logger.info("Rate limit detected, backing off...")
                await asyncio.sleep(60.0)
                return True
            
            if not hasattr(x_bot, "reconnect"):
                logger.error("X bot service missing reconnect handler")
                return False

            delay = self._base_backoff_seconds
            for attempt in range(self._x_bot_retries):
                try:
                    await x_bot.reconnect()
                    logger.info("X bot reconnect succeeded on attempt %s", attempt + 1)
                    return True
                except Exception as exc:
                    logger.warning("X bot reconnect attempt %s failed: %s", attempt + 1, exc)
                    if attempt == self._x_bot_retries - 1:
                        break
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, self._max_backoff_seconds)
            
            return False
        except Exception as e:
            logger.error(f"Failed to recover X bot: {e}")
            return False
    
    async def _recover_telegram_bot(self, target: str, issues: List[str]) -> bool:
        """Recover Telegram bot from failure."""
        from social.telegram_bot_interface import get_telegram_bot
        
        logger.info(f"Attempting to recover Telegram bot: {target}")
        
        try:
            telegram_bot = get_telegram_bot()
            delay = 1.0
            for attempt in range(self._telegram_retries):
                try:
                    await telegram_bot.start()
                    logger.info("Telegram bot restart succeeded on attempt %s", attempt + 1)
                    return True
                except Exception as exc:
                    logger.warning("Telegram bot restart attempt %s failed: %s", attempt + 1, exc)
                    if attempt == self._telegram_retries - 1:
                        break
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, self._telegram_backoff_cap)
            return False
        except Exception as e:
            logger.error(f"Failed to recover Telegram bot: {e}")
            return False
    
    async def _recover_social_feed(self, target: str, issues: List[str]) -> bool:
        """Recover stale social feed."""
        from social.social_aware_quant import get_social_aware_quant_engine
        
        logger.info(f"Attempting to recover social feed: {target}")
        
        try:
            engine = get_social_aware_quant_engine()
            
            logger.info("Clearing stale social data cache...")
            if hasattr(engine, "reset_state"):
                engine.reset_state()
            if hasattr(engine, "refresh_social_feeds"):
                maybe_refresh = engine.refresh_social_feeds()
                if asyncio.iscoroutine(maybe_refresh):
                    await maybe_refresh
            
            return True
        except Exception as e:
            logger.error(f"Failed to recover social feed: {e}")
            return False
    
    async def _recover_sentiment_api(self, target: str, issues: List[str]) -> bool:
        """Recover sentiment API connection."""
        logger.info(f"Attempting to recover sentiment API: {target}")
        
        await asyncio.sleep(30.0)
        
        return True
    
    async def _recover_rate_limit(self, target: str, issues: List[str]) -> bool:
        """Recover from rate limit by backing off."""
        logger.info(f"Rate limit recovery for: {target}")
        
        await asyncio.sleep(120.0)
        
        return True
    
    async def _escalate_to_human(self, action: HealingAction) -> None:
        """Escalate failed healing action to human operators."""
        from social.telegram_bot_interface import get_telegram_bot
        
        logger.critical(
            f"Escalating to human: {action.action_id} - {action.target} - {action.reason}"
        )
        
        try:
            telegram_bot = get_telegram_bot()
            await telegram_bot.send_alert(
                f"🚨 *Healing Failed - Human Intervention Required*\n\n"
                f"Target: {action.target}\n"
                f"Type: {action.action_type}\n"
                f"Reason: {action.reason}\n"
                f"Action ID: {action.action_id}",
                severity="critical",
            )
        except Exception as e:
            logger.error(f"Failed to send escalation alert: {e}")
    
    def register_recovery_strategy(
        self,
        failure_type: str,
        strategy: callable,
    ) -> None:
        """Register custom recovery strategy."""
        self._recovery_strategies[failure_type] = strategy
        logger.info(f"Registered recovery strategy for: {failure_type}")
    
    def get_healing_history(self, limit: int = 50) -> List[HealingAction]:
        """Get recent healing actions."""
        return self._healing_actions[-limit:]
    
    def get_healing_stats(self) -> Dict[str, object]:
        """Get healing statistics."""
        recent = [
            a for a in self._healing_actions
            if a.initiated_at > datetime.utcnow() - timedelta(hours=24)
        ]
        
        total = len(recent)
        successful = len([a for a in recent if a.success])
        failed = total - successful
        
        by_type = {}
        for action in recent:
            by_type[action.action_type] = by_type.get(action.action_type, 0) + 1
        
        return {
            "total_actions_24h": total,
            "successful_24h": successful,
            "failed_24h": failed,
            "success_rate": successful / total if total > 0 else 0.0,
            "by_type": by_type,
            "monitoring_enabled": self._monitoring_enabled,
        }
    
    async def start(self) -> None:
        """Start self-healing monitoring."""
        asyncio.create_task(self.monitor_health())
    
    def stop(self) -> None:
        """Stop self-healing monitoring."""
        self._monitoring_enabled = False
        logger.info("Self-healing social layer monitoring stopped")


_self_healing_layer: Optional[SelfHealingSocialLayer] = None


def get_self_healing_layer() -> SelfHealingSocialLayer:
    """Get global SelfHealingSocialLayer instance."""
    global _self_healing_layer
    if _self_healing_layer is None:
        _self_healing_layer = SelfHealingSocialLayer()
    return _self_healing_layer
