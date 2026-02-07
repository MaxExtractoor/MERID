"""
Phase 21c-f: Social-Aware Quant, Risk, and Bot Interfaces

Implements:
- Social-aware quant models with sentiment integration
- Market data confirmation requirements
- Risk rules for social-driven strategies
- X (Twitter) bot interface
- Telegram bot console
- Self-healing social + bot layer
"""

import logging
from typing import Dict, List, Optional, Any, Callable, Set, Awaitable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import re
import asyncio
import time
from collections import defaultdict

from core.event_bus import event_stream
from observability.observability_stack import get_observability_stack

logger = logging.getLogger(__name__)


class SocialSource(Enum):
    """Social data sources."""
    TWITTER = "twitter"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    REDDIT = "reddit"
    NEWS = "news"


class SentimentLevel(Enum):
    """Sentiment classification levels."""
    VERY_BEARISH = "very_bearish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    BULLISH = "bullish"
    VERY_BULLISH = "very_bullish"


class MarketRegime(Enum):
    """Market regime classification."""
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"


class BotCommandType(Enum):
    """Types of bot commands."""
    READ_ONLY = "read_only"
    LIMITED_CONTROL = "limited_control"
    ADMIN = "admin"


@dataclass
class SocialSignal:
    """A social sentiment signal."""
    signal_id: str
    source: SocialSource
    asset: str
    
    sentiment: SentimentLevel
    sentiment_score: float
    
    volume: int = 0
    velocity: float = 0.0
    
    influencer_mentions: int = 0
    whale_mentions: int = 0
    
    keywords: List[str] = field(default_factory=list)
    hashtags: List[str] = field(default_factory=list)
    
    raw_count: int = 0
    filtered_count: int = 0
    
    timestamp: datetime = field(default_factory=datetime.utcnow)
    decay_factor: float = 1.0


@dataclass
class MarketConfirmation:
    """Market data confirmation for social signals."""
    asset: str
    
    price_aligned: bool = False
    volume_confirmed: bool = False
    liquidity_sufficient: bool = False
    spread_acceptable: bool = False
    volatility_within_bounds: bool = False
    
    price_change_1h: float = 0.0
    price_change_24h: float = 0.0
    volume_24h: float = 0.0
    liquidity_depth: float = 0.0
    spread_bps: float = 0.0
    volatility_24h: float = 0.0
    
    confirmation_score: float = 0.0
    
    checked_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SocialRiskLimits:
    """Risk limits for social-driven strategies."""
    max_social_exposure_pct: float = 10.0
    max_single_asset_pct: float = 2.0
    max_sentiment_driven_size_usd: float = 10000.0
    
    min_liquidity_usd: float = 100000.0
    max_spread_bps: float = 50.0
    max_volatility_24h: float = 0.5
    
    sentiment_decay_hours: float = 4.0
    min_confirmation_score: float = 0.6
    
    max_correlated_positions: int = 3
    correlation_threshold: float = 0.7
    
    drawdown_kill_switch_pct: float = 5.0


@dataclass
class BotCommand:
    """A bot command."""
    command_id: str
    command_type: BotCommandType
    
    command: str
    args: List[str] = field(default_factory=list)
    
    source: str = ""
    user_id: str = ""
    
    requires_auth: bool = True
    requires_approval: bool = False
    
    executed: bool = False
    result: str = ""
    error: str = ""
    
    received_at: datetime = field(default_factory=datetime.utcnow)
    executed_at: Optional[datetime] = None


class SocialAwareQuantEngine:
    """
    Social-Aware Quantitative Engine.
    
    Extends quant models with social features while maintaining
    strict risk controls and market data confirmation requirements.
    """
    
    def __init__(self, risk_limits: Optional[SocialRiskLimits] = None):
        self._risk_limits = risk_limits or SocialRiskLimits()
        self._signals: Dict[str, List[SocialSignal]] = {}
        self._confirmations: Dict[str, MarketConfirmation] = {}
        self._positions: Dict[str, float] = {}
        self._asset_exposure: Dict[str, float] = {}
        self._tracked_assets: Set[str] = set()
        
        self._total_social_exposure: float = 0.0
        self._social_pnl: float = 0.0
        self._social_drawdown: float = 0.0
        self._high_water_mark: float = 0.0
        
        self._kill_switch_active: bool = False
        self._kill_switch_reason: str = ""
    
    def ingest_social_signal(
        self,
        source: SocialSource,
        asset: str,
        sentiment_score: float,
        volume: int,
        velocity: float,
        influencer_mentions: int = 0,
        whale_mentions: int = 0,
        keywords: Optional[List[str]] = None,
        hashtags: Optional[List[str]] = None,
    ) -> SocialSignal:
        """Ingest a social signal."""
        if sentiment_score > 0.6:
            sentiment = SentimentLevel.VERY_BULLISH
        elif sentiment_score > 0.2:
            sentiment = SentimentLevel.BULLISH
        elif sentiment_score > -0.2:
            sentiment = SentimentLevel.NEUTRAL
        elif sentiment_score > -0.6:
            sentiment = SentimentLevel.BEARISH
        else:
            sentiment = SentimentLevel.VERY_BEARISH
        
        signal = SocialSignal(
            signal_id=f"sig_{asset}_{int(datetime.utcnow().timestamp())}",
            source=source,
            asset=asset,
            sentiment=sentiment,
            sentiment_score=sentiment_score,
            volume=volume,
            velocity=velocity,
            influencer_mentions=influencer_mentions,
            whale_mentions=whale_mentions,
            keywords=keywords or [],
            hashtags=hashtags or [],
        )
        
        if asset not in self._signals:
            self._signals[asset] = []
        self._signals[asset].append(signal)
        self._tracked_assets.add(asset.upper())
        
        if len(self._signals[asset]) > 1000:
            self._signals[asset] = self._signals[asset][-500:]
        
        return signal
    
    def get_aggregated_sentiment(
        self,
        asset: str,
        window_hours: float = 4.0,
    ) -> Optional[Dict[str, Any]]:
        """Get aggregated sentiment for an asset with decay."""
        if asset not in self._signals:
            return None
        
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=window_hours)
        
        recent_signals = [
            s for s in self._signals[asset]
            if s.timestamp > cutoff
        ]
        
        if not recent_signals:
            return None
        
        total_weight = 0.0
        weighted_sentiment = 0.0
        total_volume = 0
        total_influencer = 0
        total_whale = 0
        
        for signal in recent_signals:
            age_hours = (now - signal.timestamp).total_seconds() / 3600
            decay = 2 ** (-age_hours / self._risk_limits.sentiment_decay_hours)
            signal.decay_factor = decay
            
            weight = decay * (1 + signal.influencer_mentions * 0.5 + signal.whale_mentions * 0.3)
            
            weighted_sentiment += signal.sentiment_score * weight
            total_weight += weight
            total_volume += signal.volume
            total_influencer += signal.influencer_mentions
            total_whale += signal.whale_mentions
        
        avg_sentiment = weighted_sentiment / total_weight if total_weight > 0 else 0.0
        
        return {
            "asset": asset,
            "sentiment_score": avg_sentiment,
            "signal_count": len(recent_signals),
            "total_volume": total_volume,
            "influencer_mentions": total_influencer,
            "whale_mentions": total_whale,
            "window_hours": window_hours,
            "calculated_at": now.isoformat(),
        }
    
    def check_market_confirmation(
        self,
        asset: str,
        price_change_1h: float,
        price_change_24h: float,
        volume_24h: float,
        liquidity_depth: float,
        spread_bps: float,
        volatility_24h: float,
        sentiment_direction: float,
    ) -> MarketConfirmation:
        """Check market data confirmation for social signal."""
        price_aligned = (
            (sentiment_direction > 0 and price_change_1h > 0) or
            (sentiment_direction < 0 and price_change_1h < 0) or
            abs(sentiment_direction) < 0.2
        )
        
        volume_confirmed = volume_24h > self._risk_limits.min_liquidity_usd * 0.1
        liquidity_sufficient = liquidity_depth > self._risk_limits.min_liquidity_usd
        spread_acceptable = spread_bps < self._risk_limits.max_spread_bps
        volatility_within_bounds = volatility_24h < self._risk_limits.max_volatility_24h
        
        checks = [
            price_aligned,
            volume_confirmed,
            liquidity_sufficient,
            spread_acceptable,
            volatility_within_bounds,
        ]
        confirmation_score = sum(checks) / len(checks)
        
        confirmation = MarketConfirmation(
            asset=asset,
            price_aligned=price_aligned,
            volume_confirmed=volume_confirmed,
            liquidity_sufficient=liquidity_sufficient,
            spread_acceptable=spread_acceptable,
            volatility_within_bounds=volatility_within_bounds,
            price_change_1h=price_change_1h,
            price_change_24h=price_change_24h,
            volume_24h=volume_24h,
            liquidity_depth=liquidity_depth,
            spread_bps=spread_bps,
            volatility_24h=volatility_24h,
            confirmation_score=confirmation_score,
        )
        
        self._confirmations[asset] = confirmation
        return confirmation
    
    def calculate_social_position_size(
        self,
        asset: str,
        portfolio_value: float,
        sentiment_score: float,
    ) -> Dict[str, Any]:
        """Calculate position size for social-driven trade."""
        if self._kill_switch_active:
            return {
                "allowed": False,
                "reason": f"Kill switch active: {self._kill_switch_reason}",
                "size_usd": 0.0,
            }
        
        confirmation = self._confirmations.get(asset)
        if not confirmation:
            return {
                "allowed": False,
                "reason": "No market confirmation available",
                "size_usd": 0.0,
            }
        
        if confirmation.confirmation_score < self._risk_limits.min_confirmation_score:
            return {
                "allowed": False,
                "reason": f"Confirmation score {confirmation.confirmation_score:.2f} below minimum {self._risk_limits.min_confirmation_score}",
                "size_usd": 0.0,
            }
        
        max_social = portfolio_value * self._risk_limits.max_social_exposure_pct / 100
        remaining_social = max_social - self._total_social_exposure
        
        if remaining_social <= 0:
            return {
                "allowed": False,
                "reason": "Social exposure limit reached",
                "size_usd": 0.0,
            }
        
        max_single = portfolio_value * self._risk_limits.max_single_asset_pct / 100
        
        sentiment_multiplier = min(1.0, abs(sentiment_score))
        base_size = min(
            self._risk_limits.max_sentiment_driven_size_usd * sentiment_multiplier,
            max_single,
            remaining_social,
        )
        
        liquidity_cap = confirmation.liquidity_depth * 0.01
        final_size = min(base_size, liquidity_cap)
        
        return {
            "allowed": True,
            "size_usd": final_size,
            "sentiment_score": sentiment_score,
            "confirmation_score": confirmation.confirmation_score,
            "liquidity_cap": liquidity_cap,
            "remaining_social_budget": remaining_social - final_size,
        }

    def register_position_allocation(self, asset: str, size_usd: float) -> None:
        """Register an approved social-driven allocation for ongoing tracking."""
        self._total_social_exposure += size_usd
        key = asset.upper()
        self._asset_exposure[key] = self._asset_exposure.get(key, 0.0) + size_usd

    def release_position_allocation(self, asset: str, size_usd: float) -> None:
        """Release exposure when position is closed or reduced."""
        self._total_social_exposure = max(0.0, self._total_social_exposure - size_usd)
        key = asset.upper()
        if key in self._asset_exposure:
            new_value = max(0.0, self._asset_exposure[key] - size_usd)
            if new_value == 0.0:
                self._asset_exposure.pop(key, None)
            else:
                self._asset_exposure[key] = new_value

    def get_position_constraints(self, asset: str) -> Dict[str, Any]:
        """Return current constraints/telemetry for the asset."""
        exposure = self._asset_exposure.get(asset, 0.0)
        confirmation = self._confirmations.get(asset)
        constraints = {
            "kill_switch_active": self._kill_switch_active,
            "kill_switch_reason": self._kill_switch_reason,
            "asset_exposure": exposure,
            "total_social_exposure": self._total_social_exposure,
            "max_asset_pct": self._risk_limits.max_single_asset_pct,
            "max_total_pct": self._risk_limits.max_social_exposure_pct,
            "confirmation_score": confirmation.confirmation_score if confirmation else 0.0,
            "confirmation_available": confirmation is not None,
            "data_fresh": self.is_data_fresh(asset),
            "is_social_asset": self.is_social_asset(asset),
        }
        return constraints

    def evaluate_trade_request(
        self,
        asset: str,
        portfolio_value: float,
        sentiment_score: float,
        market_metrics: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Evaluate a potential trade and return size + constraint telemetry."""
        metrics = self._normalize_market_metrics(market_metrics or {})
        confirmation: Optional[MarketConfirmation] = None
        required_metric_keys = {
            "price_change_1h",
            "price_change_24h",
            "volume_24h",
            "liquidity_depth",
            "spread_bps",
            "volatility_24h",
        }
        provided_metric_keys = set((market_metrics or {}).keys())

        if required_metric_keys.issubset(provided_metric_keys):
            confirmation = self.check_market_confirmation(
                asset=asset,
                price_change_1h=metrics["price_change_1h"],
                price_change_24h=metrics["price_change_24h"],
                volume_24h=metrics["volume_24h"],
                liquidity_depth=metrics["liquidity_depth"],
                spread_bps=metrics["spread_bps"],
                volatility_24h=metrics["volatility_24h"],
                sentiment_direction=sentiment_score,
            )
        else:
            # Reuse cached confirmation when callers only refresh a subset of metrics.
            confirmation = self._confirmations.get(asset)

        if confirmation is None:
            confirmation = self.check_market_confirmation(
                asset=asset,
                price_change_1h=metrics["price_change_1h"],
                price_change_24h=metrics["price_change_24h"],
                volume_24h=metrics["volume_24h"],
                liquidity_depth=metrics["liquidity_depth"],
                spread_bps=metrics["spread_bps"],
                volatility_24h=metrics["volatility_24h"],
                sentiment_direction=sentiment_score,
            )

        sizing = self.calculate_social_position_size(
            asset=asset,
            portfolio_value=portfolio_value,
            sentiment_score=sentiment_score,
        )
        sizing["confirmation"] = confirmation
        sizing["constraints"] = self.get_position_constraints(asset)
        return sizing

    def activate_kill_switch(self, reason: str) -> None:
        """Force kill switch (used by governance/risk)."""
        self._kill_switch_active = True
        self._kill_switch_reason = reason

    def reset_kill_switch(self) -> None:
        """Reset kill switch when safe to resume."""
        self._kill_switch_active = False
        self._kill_switch_reason = ""
        self._social_drawdown = 0.0
        self._high_water_mark = max(0.0, self._social_pnl)
        logger.info("Social strategy kill switch reset")

    def is_data_fresh(self, asset: str, max_age_minutes: float = 15.0) -> bool:
        """Check if we have fresh social data for asset."""
        if asset not in self._signals or not self._signals[asset]:
            return False
        latest = max(self._signals[asset], key=lambda s: s.timestamp)
        age_minutes = (datetime.utcnow() - latest.timestamp).total_seconds() / 60
        return age_minutes <= max_age_minutes

    def _normalize_market_metrics(self, metrics: Dict[str, float]) -> Dict[str, float]:
        """Ensure required market metrics exist with safe defaults."""
        safe_defaults = {
            "price_change_1h": 0.0,
            "price_change_24h": 0.0,
            "volume_24h": self._risk_limits.min_liquidity_usd,
            "liquidity_depth": self._risk_limits.min_liquidity_usd,
            "spread_bps": self._risk_limits.max_spread_bps,
            "volatility_24h": self._risk_limits.max_volatility_24h,
        }
        safe_defaults.update({k: float(v) for k, v in metrics.items() if v is not None})
        return safe_defaults

    def register_social_asset(self, asset: str) -> None:
        """Explicitly register asset as social-aware even before signals arrive."""
        self._tracked_assets.add(asset.upper())

    def is_social_asset(self, asset: str) -> bool:
        """Check if asset is tracked for social-aware strategies."""
        return asset.upper() in self._tracked_assets

    def get_risk_limits(self) -> SocialRiskLimits:
        """Expose current risk limits (copy) for external checks."""
        return SocialRiskLimits(**self._risk_limits.__dict__)

    def reset_state(self) -> None:
        """Reset engine state (used in tests)."""
        self._signals.clear()
        self._confirmations.clear()
        self._positions.clear()
        self._asset_exposure.clear()
        self._tracked_assets.clear()
        self._total_social_exposure = 0.0
        self._social_pnl = 0.0
        self._social_drawdown = 0.0
        self._high_water_mark = 0.0
        self._kill_switch_active = False
        self._kill_switch_reason = ""
    
    def get_top_asset_exposure(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Return top-N assets by social exposure."""
        ranked = sorted(
            self._asset_exposure.items(),
            key=lambda kv: kv[1],
            reverse=True,
        )
        return [
            {
                "asset": asset,
                "exposure": exposure,
                "constraints": self.get_position_constraints(asset),
            }
            for asset, exposure in ranked[:limit]
        ]
    
    def update_social_pnl(self, pnl_change: float) -> None:
        """Update social strategy PnL and check kill switch."""
        self._social_pnl += pnl_change
        
        if self._social_pnl > self._high_water_mark:
            self._high_water_mark = self._social_pnl
        
        if self._high_water_mark > 0:
            self._social_drawdown = (self._high_water_mark - self._social_pnl) / self._high_water_mark
        
        if self._social_drawdown * 100 > self._risk_limits.drawdown_kill_switch_pct:
            self._kill_switch_active = True
            self._kill_switch_reason = f"Drawdown {self._social_drawdown:.2%} exceeded limit"
            logger.warning(f"Social strategy kill switch activated: {self._kill_switch_reason}")
    
    def get_social_risk_status(self) -> Dict[str, Any]:
        """Get current social strategy risk status."""
        total_assets = len(self._signals)
        fresh_assets = sum(1 for asset in self._signals if self.is_data_fresh(asset))
        freshness_score = (
            fresh_assets / total_assets if total_assets > 0 else 0.0
        )
        active_positions = sum(1 for qty in self._positions.values() if abs(qty) > 0)
        total_exposure = sum(self._asset_exposure.values())
        top_assets = self.get_top_asset_exposure(limit=5)

        return {
            "kill_switch_active": self._kill_switch_active,
            "kill_switch_reason": self._kill_switch_reason,
            "total_social_exposure": self._total_social_exposure,
            "total_exposure_usd": total_exposure,
            "active_positions": active_positions,
            "social_pnl": self._social_pnl,
            "social_drawdown": self._social_drawdown,
            "high_water_mark": self._high_water_mark,
            "assets_tracked": total_assets,
            "confirmations_cached": len(self._confirmations),
            "data_freshness_score": freshness_score,
            "top_assets": top_assets,
        }


class TwitterBotInterface:
    """
    X (Twitter) Bot Interface.
    
    Provides read-only status and limited control commands
    with proper authentication and approval workflows.
    """
    
    WHITELISTED_COMMANDS = {
        "status": BotCommandType.READ_ONLY,
        "portfolio": BotCommandType.READ_ONLY,
        "pnl": BotCommandType.READ_ONLY,
        "positions": BotCommandType.READ_ONLY,
        "alerts": BotCommandType.READ_ONLY,
        "risk": BotCommandType.READ_ONLY,
        "pause": BotCommandType.LIMITED_CONTROL,
        "resume": BotCommandType.LIMITED_CONTROL,
    }
    
    def __init__(self):
        self._authorized_users: Set[str] = set()
        self._command_history: List[BotCommand] = []
        self._rate_limits: Dict[str, List[datetime]] = {}
        self._max_commands_per_hour = 60
        
        self._command_handlers: Dict[str, Callable] = {}
        self._approval_queue: List[BotCommand] = []
        
        self._connected = False
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
    
    def authorize_user(self, user_id: str) -> None:
        """Authorize a user to send commands."""
        self._authorized_users.add(user_id)
        logger.info(f"Authorized Twitter user: {user_id}")
    
    def register_handler(
        self,
        command: str,
        handler: Callable[[BotCommand], str],
    ) -> None:
        """Register a command handler."""
        self._command_handlers[command] = handler
    
    def _check_rate_limit(self, user_id: str) -> bool:
        """Check if user is within rate limits."""
        now = datetime.utcnow()
        
        if user_id not in self._rate_limits:
            self._rate_limits[user_id] = []
        
        self._rate_limits[user_id] = [
            t for t in self._rate_limits[user_id]
            if now - t < timedelta(hours=1)
        ]
        
        return len(self._rate_limits[user_id]) < self._max_commands_per_hour
    
    def process_mention(
        self,
        user_id: str,
        text: str,
        message_id: str,
    ) -> Optional[BotCommand]:
        """Process a Twitter mention."""
        if user_id not in self._authorized_users:
            logger.warning(f"Unauthorized Twitter user attempted command: {user_id}")
            return None
        
        if not self._check_rate_limit(user_id):
            logger.warning(f"Rate limit exceeded for user: {user_id}")
            return None
        
        parts = text.lower().split()
        if not parts:
            return None
        
        command = parts[0].lstrip("@").lstrip("/")
        args = parts[1:] if len(parts) > 1 else []
        
        if command not in self.WHITELISTED_COMMANDS:
            logger.warning(f"Unknown command from Twitter: {command}")
            return None
        
        command_type = self.WHITELISTED_COMMANDS[command]
        
        bot_command = BotCommand(
            command_id=f"tw_{message_id}",
            command_type=command_type,
            command=command,
            args=args,
            source="twitter",
            user_id=user_id,
            requires_auth=True,
            requires_approval=command_type == BotCommandType.LIMITED_CONTROL,
        )
        
        self._rate_limits[user_id].append(datetime.utcnow())
        self._command_history.append(bot_command)
        
        if bot_command.requires_approval:
            self._approval_queue.append(bot_command)
            bot_command.result = "Command queued for approval"
        else:
            self._execute_command(bot_command)
        
        return bot_command
    
    def _execute_command(self, command: BotCommand) -> None:
        """Execute a bot command."""
        if command.command in self._command_handlers:
            try:
                result = self._command_handlers[command.command](command)
                command.result = result
                command.executed = True
                command.executed_at = datetime.utcnow()
            except Exception as e:
                command.error = str(e)
                logger.error(f"Command execution failed: {e}")
        else:
            command.result = f"No handler for command: {command.command}"
    
    def approve_command(self, command_id: str, approver: str) -> bool:
        """Approve a queued command."""
        for cmd in self._approval_queue:
            if cmd.command_id == command_id:
                self._approval_queue.remove(cmd)
                self._execute_command(cmd)
                logger.info(f"Command {command_id} approved by {approver}")
                return True
        return False
    
    async def reconnect(self) -> bool:
        """Attempt to reconnect to Twitter."""
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            logger.error("Max reconnect attempts reached")
            return False
        
        self._reconnect_attempts += 1
        backoff = 2 ** self._reconnect_attempts
        
        logger.info(f"Reconnecting to Twitter in {backoff}s (attempt {self._reconnect_attempts})")
        await asyncio.sleep(backoff)
        
        self._connected = True
        self._reconnect_attempts = 0
        return True
    
    def get_status(self) -> Dict[str, Any]:
        """Get bot status."""
        return {
            "connected": self._connected,
            "authorized_users": len(self._authorized_users),
            "commands_processed": len(self._command_history),
            "pending_approvals": len(self._approval_queue),
            "reconnect_attempts": self._reconnect_attempts,
        }


class TelegramBotConsole:
    """
    Telegram Bot Console.
    
    Provides ops console and user console with safe controls
    and proper authentication.
    """
    
    WHITELISTED_COMMANDS = {
        "status": BotCommandType.READ_ONLY,
        "portfolio": BotCommandType.READ_ONLY,
        "pnl": BotCommandType.READ_ONLY,
        "positions": BotCommandType.READ_ONLY,
        "alerts": BotCommandType.READ_ONLY,
        "risk": BotCommandType.READ_ONLY,
        "agents": BotCommandType.READ_ONLY,
        "strategies": BotCommandType.READ_ONLY,
        "pause": BotCommandType.LIMITED_CONTROL,
        "resume": BotCommandType.LIMITED_CONTROL,
        "reduce_risk": BotCommandType.LIMITED_CONTROL,
        "emergency_stop": BotCommandType.ADMIN,
    }
    
    def __init__(self):
        self._authorized_users: Dict[str, str] = {}
        self._user_roles: Dict[str, str] = {}
        self._command_history: List[BotCommand] = []
        self._sessions: Dict[str, datetime] = {}
        self._session_timeout = timedelta(hours=4)
        
        self._command_handlers: Dict[str, Callable] = {}
        
        self._connected = False
        self._reconnect_attempts = 0
    
    def authorize_user(
        self,
        user_id: str,
        role: str = "viewer",
        auth_token: str = "",
    ) -> None:
        """Authorize a Telegram user."""
        self._authorized_users[user_id] = auth_token
        self._user_roles[user_id] = role
        logger.info(f"Authorized Telegram user {user_id} with role {role}")
    
    def register_handler(
        self,
        command: str,
        handler: Callable[[BotCommand], str],
    ) -> None:
        """Register a command handler."""
        self._command_handlers[command] = handler
    
    def _check_session(self, user_id: str) -> bool:
        """Check if user has valid session."""
        if user_id not in self._sessions:
            return False
        
        if datetime.utcnow() - self._sessions[user_id] > self._session_timeout:
            del self._sessions[user_id]
            return False
        
        return True
    
    def _check_permission(self, user_id: str, command_type: BotCommandType) -> bool:
        """Check if user has permission for command type."""
        role = self._user_roles.get(user_id, "viewer")
        
        if command_type == BotCommandType.READ_ONLY:
            return True
        elif command_type == BotCommandType.LIMITED_CONTROL:
            return role in ["operator", "admin"]
        elif command_type == BotCommandType.ADMIN:
            return role == "admin"
        
        return False
    
    def start_session(self, user_id: str, auth_token: str) -> bool:
        """Start a session for a user."""
        if user_id not in self._authorized_users:
            return False
        
        if self._authorized_users[user_id] != auth_token:
            return False
        
        self._sessions[user_id] = datetime.utcnow()
        logger.info(f"Session started for Telegram user {user_id}")
        return True
    
    def process_message(
        self,
        user_id: str,
        text: str,
        message_id: str,
    ) -> Optional[BotCommand]:
        """Process a Telegram message."""
        if not self._check_session(user_id):
            logger.warning(f"No valid session for Telegram user: {user_id}")
            return None
        
        parts = text.split()
        if not parts:
            return None
        
        command = parts[0].lstrip("/").lower()
        args = parts[1:] if len(parts) > 1 else []
        
        if command not in self.WHITELISTED_COMMANDS:
            return None
        
        command_type = self.WHITELISTED_COMMANDS[command]
        
        if not self._check_permission(user_id, command_type):
            logger.warning(f"Permission denied for {user_id} on command {command}")
            return None
        
        bot_command = BotCommand(
            command_id=f"tg_{message_id}",
            command_type=command_type,
            command=command,
            args=args,
            source="telegram",
            user_id=user_id,
        )
        
        self._command_history.append(bot_command)
        self._execute_command(bot_command)
        
        return bot_command
    
    def _execute_command(self, command: BotCommand) -> None:
        """Execute a bot command."""
        if command.command in self._command_handlers:
            try:
                result = self._command_handlers[command.command](command)
                command.result = result
                command.executed = True
                command.executed_at = datetime.utcnow()
            except Exception as e:
                command.error = str(e)
                logger.error(f"Command execution failed: {e}")
    
    async def reconnect(self) -> bool:
        """Attempt to reconnect to Telegram."""
        self._reconnect_attempts += 1
        backoff = min(2 ** self._reconnect_attempts, 60)
        
        logger.info(f"Reconnecting to Telegram in {backoff}s")
        await asyncio.sleep(backoff)
        
        self._connected = True
        self._reconnect_attempts = 0
        return True
    
    def get_status(self) -> Dict[str, Any]:
        """Get bot status."""
        active_sessions = sum(
            1 for user_id in self._sessions
            if datetime.utcnow() - self._sessions[user_id] < self._session_timeout
        )
        
        return {
            "connected": self._connected,
            "authorized_users": len(self._authorized_users),
            "active_sessions": active_sessions,
            "commands_processed": len(self._command_history),
            "reconnect_attempts": self._reconnect_attempts,
        }


@dataclass
class ComponentState:
    """Runtime status for a monitored component."""

    name: str
    component_type: str
    auto_recover: bool = True
    heartbeat_interval: float = 60.0
    last_heartbeat: float = 0.0
    status: str = "unknown"
    failures: int = 0
    recoveries: int = 0
    backoff_seconds: float = 5.0
    next_retry_at: float = 0.0
    last_error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class SocialBotHealthMonitor:
    """
    Self-Healing Social + Bot Layer.
    
    Makes social ingestion non-critical and bots self-healing
    with proper failure handling and learning.
    """
    
    def __init__(self):
        self._component_health: Dict[str, Dict[str, Any]] = {}
        self._failure_history: List[Dict[str, Any]] = []
        self._recovery_actions: List[Dict[str, Any]] = []
        self._components: Dict[str, ComponentState] = {}
        self._recovery_handlers: Dict[str, Callable[[], Awaitable[bool]]] = {}
        self._min_backoff = 5.0
        self._max_backoff = 300.0
        self._observability = get_observability_stack()
        self._loop = None
        
        self._twitter_bot: Optional[TwitterBotInterface] = None
        self._telegram_bot: Optional[TelegramBotConsole] = None
        self._social_engine: Optional[SocialAwareQuantEngine] = None
    
    def register_components(
        self,
        twitter_bot: Optional[TwitterBotInterface] = None,
        telegram_bot: Optional[TelegramBotConsole] = None,
        social_engine: Optional[SocialAwareQuantEngine] = None,
    ) -> None:
        """Register components for monitoring."""
        self._twitter_bot = twitter_bot
        self._telegram_bot = telegram_bot
        self._social_engine = social_engine
        if twitter_bot:
            self.register_component(
                "twitter_bot",
                component_type="bot",
                auto_recover=True,
                heartbeat_interval=60.0,
                recovery_handler=twitter_bot.reconnect,
            )
        if telegram_bot:
            self.register_component(
                "telegram_bot",
                component_type="bot",
                auto_recover=True,
                heartbeat_interval=60.0,
                recovery_handler=telegram_bot.reconnect,
            )

    def register_component(
        self,
        name: str,
        component_type: str,
        auto_recover: bool,
        heartbeat_interval: float,
        recovery_handler: Optional[Callable[[], Awaitable[bool]]] = None,
    ) -> None:
        """Register or update a component state."""
        state = self._components.get(name, ComponentState(name=name, component_type=component_type))
        state.component_type = component_type
        state.auto_recover = auto_recover
        state.heartbeat_interval = heartbeat_interval
        self._components[name] = state
        if recovery_handler:
            self._recovery_handlers[name] = recovery_handler
        logger.info("Registered social component %s (%s)", name, component_type)

    def update_heartbeat(
        self,
        name: str,
        status: str = "healthy",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Update heartbeat for a component."""
        state = self._components.get(name)
        if not state:
            return
        now = time.time()
        state.last_heartbeat = now
        previous_status = state.status
        state.status = status
        if metadata:
            state.metadata.update(metadata)
        self._component_health[name] = {
            "status": status,
            "last_heartbeat": datetime.utcnow().isoformat(),
            "metadata": state.metadata,
        }
        if previous_status != status:
            self._emit_event(
                "social_health",
                {
                    "component": name,
                    "status": status,
                    "previous_status": previous_status,
                    "timestamp": datetime.utcnow().isoformat(),
                    "metadata": metadata or {},
                },
            )
        self._observability.telemetry.log_structured(
            stream_name="social",
            level="INFO",
            event_type="heartbeat",
            message=f"Heartbeat received for {name}",
            fields={"status": status, "metadata": metadata or {}},
        )
    
    def record_failure(
        self,
        component: str,
        error: str,
        recoverable: bool = True,
    ) -> None:
        """Record a component failure."""
        now = time.time()
        state = self._components.setdefault(component, ComponentState(name=component, component_type="unknown"))
        state.failures += 1
        state.status = "degraded"
        state.last_error = error
        state.backoff_seconds = min(
            self._max_backoff,
            state.backoff_seconds * 2 if state.backoff_seconds else self._min_backoff,
        )
        state.next_retry_at = now + max(self._min_backoff, state.backoff_seconds)

        failure = {
            "component": component,
            "error": error,
            "recoverable": recoverable,
            "timestamp": datetime.utcnow().isoformat(),
            "backoff_seconds": state.backoff_seconds,
        }
        self._failure_history.append(failure)

        if len(self._failure_history) > 1000:
            self._failure_history = self._failure_history[-500:]

        logger.warning("Component failure: %s - %s", component, error)
        self._observability.telemetry.log_structured(
            stream_name="social",
            level="ERROR",
            event_type="social_component_failure",
            message=f"{component} failure: {error}",
            fields={"component": component, "error": error, "recoverable": recoverable},
        )
        self._observability.telemetry.record_metric(
            "social",
            f"{component}.failures",
            state.failures,
            tags={"component": component},
            unit="count",
        )
        self._emit_event(
            "social_health",
            {
                "component": component,
                "status": "degraded",
                "error": error,
                "recoverable": recoverable,
                "next_retry_at": state.next_retry_at,
            },
        )
    
    async def attempt_recovery(self, component: str) -> bool:
        """Attempt to recover a failed component."""
        state = self._components.get(component)
        if not state:
            return False
        if not state.auto_recover:
            return False
        now = time.time()
        if now < state.next_retry_at:
            return False

        handler = self._recovery_handlers.get(component)
        success = False
        if handler:
            success = await handler()
        elif component == "twitter_bot" and self._twitter_bot:
            success = await self._twitter_bot.reconnect()
        elif component == "telegram_bot" and self._telegram_bot:
            success = await self._telegram_bot.reconnect()

        self._recovery_actions.append(
            {
                "component": component,
                "success": success,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

        if success:
            state.recoveries += 1
            state.status = "healthy"
            state.backoff_seconds = self._min_backoff
            state.next_retry_at = 0.0
            self._observability.telemetry.log_structured(
                stream_name="social",
                level="INFO",
                event_type="social_component_recovered",
                message=f"{component} recovered successfully",
                fields={"component": component},
            )
            self._emit_event(
                "social_health",
                {"component": component, "status": "healthy", "timestamp": datetime.utcnow().isoformat()},
            )
        else:
            state.status = "recovering"
            state.next_retry_at = now + state.backoff_seconds
        return success
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get overall health status."""
        recent_failures = [
            f for f in self._failure_history
            if datetime.fromisoformat(f["timestamp"]) > datetime.utcnow() - timedelta(hours=1)
        ]
        
        components = {}
        if self._twitter_bot:
            components["twitter_bot"] = self._twitter_bot.get_status()
        if self._telegram_bot:
            components["telegram_bot"] = self._telegram_bot.get_status()
        if self._social_engine:
            components["social_engine"] = self._social_engine.get_social_risk_status()

        for name, state in self._components.items():
            components.setdefault(
                name,
                {
                    "status": state.status,
                    "last_heartbeat": datetime.utcfromtimestamp(state.last_heartbeat).isoformat()
                    if state.last_heartbeat
                    else None,
                    "failures": state.failures,
                    "recoveries": state.recoveries,
                    "next_retry_at": datetime.utcfromtimestamp(state.next_retry_at).isoformat()
                    if state.next_retry_at
                    else None,
                },
            )

        return {
            "components": components,
            "failures_1h": len(recent_failures),
            "total_failures": len(self._failure_history),
            "recovery_attempts": len(self._recovery_actions),
        }

    def _emit_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Best-effort async publish to event stream."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(event_stream.publish(event_type, payload))
        except RuntimeError:
            logger.debug("No running event loop to publish %s", event_type)


_social_engine: Optional[SocialAwareQuantEngine] = None
_twitter_bot: Optional[TwitterBotInterface] = None
_telegram_bot: Optional[TelegramBotConsole] = None
_health_monitor: Optional[SocialBotHealthMonitor] = None


def get_social_aware_quant_engine() -> SocialAwareQuantEngine:
    """Get global SocialAwareQuantEngine instance."""
    global _social_engine
    if _social_engine is None:
        _social_engine = SocialAwareQuantEngine()
    return _social_engine


def get_twitter_bot() -> TwitterBotInterface:
    """Get global TwitterBotInterface instance."""
    global _twitter_bot
    if _twitter_bot is None:
        _twitter_bot = TwitterBotInterface()
    return _twitter_bot


def get_telegram_bot() -> TelegramBotConsole:
    """Get global TelegramBotConsole instance."""
    global _telegram_bot
    if _telegram_bot is None:
        _telegram_bot = TelegramBotConsole()
    return _telegram_bot


def get_social_bot_health_monitor() -> SocialBotHealthMonitor:
    """Get global SocialBotHealthMonitor instance."""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = SocialBotHealthMonitor()
    return _health_monitor
