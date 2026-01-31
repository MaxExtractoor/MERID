from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from fastapi import APIRouter, Depends, HTTPException, Request, status

from core.agent_orchestrator import get_agent_orchestrator
from core.cross_domain_portfolio import get_portfolio_engine
from core.automated_risk_controls import get_risk_coordinator
from core.env import capabilities
from core.event_bus import event_stream
from core.social_sentiment import (
    MessageNormalizer,
    MessageSource,
    SentimentAnalyzer,
    SocialMessage,
)
from security.breach_detection import (
    PermissionLevel,
    ThreatCategory,
    ThreatLevel,
    get_breach_detection_system,
)
from social.social_aware_quant import (
    BotCommand,
    BotCommandType,
    get_social_bot_health_monitor,
)
from social.x_bot_commands import XBotRole, CommandDefinition, get_default_commands
from utils.logger import get_logger


logger = get_logger("social.x_bot")


@dataclass
class XBotUserProfile:
    """X user mapped to MERID permissions."""

    user_id: str
    handle: str
    role: XBotRole = XBotRole.PUBLIC
    max_commands_per_hour: int = 30
    dm_only: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


class SocialIntelClassifier:
    """Heuristic classifier that tags social mentions before surfacing them."""

    def __init__(self) -> None:
        self._normalizer = MessageNormalizer()
        self._analyzer = SentimentAnalyzer()

    def classify(self, message: SocialMessage) -> Dict[str, Any]:
        normalized = self._normalizer.normalize([message])
        if not normalized:
            message.asset_tags = []
        else:
            message = normalized[0]
        self._analyzer.analyze_batch([message])

        category = self._categorize(message)
        authenticity = self._score_authenticity(message)
        risk = self._score_risk(message, category, authenticity)

        return {
            "message_id": message.message_id,
            "source": message.source.value,
            "author": message.author,
            "content": message.content,
            "asset_tags": message.asset_tags,
            "sentiment": message.sentiment.name if message.sentiment else "UNKNOWN",
            "category": category,
            "authenticity_score": authenticity,
            "risk_score": risk,
            "timestamp": message.timestamp,
        }

    def _categorize(self, message: SocialMessage) -> str:
        text = message.content.lower()
        if any(token in text for token in ["exploit", "hack", "rug", "down", "stuck"]):
            return "incident"
        if any(token in text for token in ["scam", "airdrop", "phishing", "impersonation"]):
            return "phishing"
        if any(token in text for token in ["merid", "@merid", "what is merid"]):
            return "mention"
        if message.sentiment and message.sentiment.value >= 1:
            return "praise"
        if message.sentiment and message.sentiment.value <= -1:
            return "complaint"
        return "signal"

    def _score_authenticity(self, message: SocialMessage) -> float:
        base = 0.5
        if message.is_influencer:
            base += 0.2
        if message.is_whale:
            base += 0.1
        if message.engagement.get("likes", 0) + message.engagement.get("retweets", 0) > 100:
            base += 0.1
        if any(keyword in message.content.lower() for keyword in ["giveaway", "bonus", "airdrop"]):
            base -= 0.3
        return max(0.0, min(1.0, base))

    def _score_risk(self, message: SocialMessage, category: str, authenticity: float) -> float:
        base = 0.1
        if category == "incident":
            base = 0.8
        elif category == "phishing":
            base = 0.7
        elif category == "complaint":
            base = 0.4
        elif category == "signal":
            base = 0.3
        if authenticity < 0.3:
            base *= 0.5
        return max(0.0, min(1.0, base))


class XBotAuthManager:
    """Maintains user mappings and command permissions."""

    def __init__(self) -> None:
        self._users: Dict[str, XBotUserProfile] = {}

    def register_user(self, profile: XBotUserProfile) -> None:
        self._users[profile.user_id] = profile
        logger.info("Registered X user %s as %s", profile.handle, profile.role.value)

    def get_profile(self, user_id: str, handle: str) -> XBotUserProfile:
        if user_id not in self._users:
            profile = XBotUserProfile(user_id=user_id, handle=handle)
            self._users[user_id] = profile
            return profile
        return self._users[user_id]

    def is_authorized(self, profile: XBotUserProfile, command: CommandDefinition) -> bool:
        role_order = {
            XBotRole.PUBLIC: 0,
            XBotRole.USER: 1,
            XBotRole.OPS: 2,
            XBotRole.ADMIN: 3,
        }
        return role_order[profile.role] >= role_order[command.required_role]


class XBotRateLimiter:
    """Simple sliding-window rate limiter per user."""

    def __init__(self) -> None:
        self._history: Dict[str, List[float]] = {}

    def check_and_record(self, profile: XBotUserProfile) -> bool:
        now = time.time()
        window = 3600.0
        history = self._history.setdefault(profile.user_id, [])
        history[:] = [ts for ts in history if now - ts < window]
        if len(history) >= profile.max_commands_per_hour:
            return False
        history.append(now)
        return True


class BackendClient:
    """Thin Async HTTP client for MERID internal endpoints."""

    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None) -> None:
        self._base_url = (base_url or capabilities.merid_api_base_url).rstrip("/")
        self._token = token or capabilities.x_bot_service_token
        self._client = httpx.AsyncClient(timeout=15.0)

    async def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], int]:
        url = f"{self._base_url}{path}"
        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        response = await self._client.request(method, url, params=params, json=json_body, headers=headers)
        response.raise_for_status()
        return response.json(), response.status_code

    async def close(self) -> None:
        await self._client.aclose()


class XBotService:
    """Primary orchestrator for Phase 21d X bot functionality."""

    def __init__(
        self,
        command_definitions: Optional[Dict[str, CommandDefinition]] = None,
        backend_client: Optional[BackendClient] = None,
        incident_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> None:
        self._commands = command_definitions or get_default_commands()
        self._auth = XBotAuthManager()
        self._rate_limiter = XBotRateLimiter()
        self._classifier = SocialIntelClassifier()
        self._backend = backend_client or BackendClient()
        self._incident_callback = incident_callback
        self._breach_system = get_breach_detection_system()
        self._command_history: List[BotCommand] = []
        self._connected = False
        self._stop = False
        self._health = get_social_bot_health_monitor()
        self._component_name = "x_bot_service"
        self._health.register_component(
            self._component_name,
            component_type="bot",
            auto_recover=True,
            heartbeat_interval=60.0,
        )
        self._health.update_heartbeat(self._component_name, status="initialized")

    async def start(self) -> None:
        self._connected = True
        logger.info("XBotService started")
        self._health.update_heartbeat(self._component_name, status="running")

    async def shutdown(self) -> None:
        self._stop = True
        await self._backend.close()
        self._connected = False
        logger.info("XBotService stopped")
        self._health.update_heartbeat(self._component_name, status="stopped")

    async def process_mention(
        self,
        mention_payload: Dict[str, Any],
    ) -> Optional[BotCommand]:
        if not self._connected:
            logger.warning("XBotService not running; dropping mention")
            return None

        message = self._build_social_message(mention_payload)
        intel = self._classifier.classify(message)
        await event_stream.publish("social_intel", intel)
        await self._maybe_trigger_incident(intel)
        self._health.update_heartbeat(
            self._component_name,
            metadata={"event": "mention", "message_id": intel["message_id"], "category": intel["category"]},
        )

        command_name, args = self._parse_command(message.content)
        if not command_name:
            return None

        profile = self._auth.get_profile(message.author, mention_payload.get("handle", message.author))
        return await self._handle_command(command_name, args, profile, mention_payload)

    def register_user(self, profile: XBotUserProfile) -> None:
        self._auth.register_user(profile)

    async def _handle_command(
        self,
        command_name: str,
        args: List[str],
        profile: XBotUserProfile,
        mention_payload: Dict[str, Any],
    ) -> Optional[BotCommand]:
        definition = self._commands.get(command_name)
        if not definition:
            logger.warning("Command %s not recognized", command_name)
            return None

        if not self._auth.is_authorized(profile, definition):
            logger.warning("User %s not authorized for %s", profile.handle, command_name)
            self._breach_system.detect_auth_failure(profile.user_id, mention_payload.get("ip", "x"), "xbot_unauthorized")
            return None

        if not self._rate_limiter.check_and_record(profile):
            logger.warning("User %s exceeded rate limit", profile.handle)
            return None

        permission = PermissionLevel.READ if definition.command_type == BotCommandType.READ_ONLY else PermissionLevel.EXECUTE
        allowed = self._breach_system.check_permission(
            actor_id=profile.user_id,
            role_id=profile.role.value,
            resource=f"xbot.{command_name}",
            required_permission=permission,
            details={
                "args": args,
                "command_type": definition.command_type.value,
                "risk_level": definition.risk_level,
            },
        )
        if not allowed:
            logger.warning("Breach system denied command %s for %s", command_name, profile.handle)
            return None

        bot_command = BotCommand(
            command_id=f"xbot_{int(time.time() * 1000)}",
            command_type=definition.command_type,
            command=command_name,
            args=args,
            source="twitter",
            user_id=profile.user_id,
            requires_auth=True,
            requires_approval=definition.command_type != BotCommandType.READ_ONLY,
        )

        backend_latency_ms = 0.0
        status_code = None
        start_time = time.perf_counter()
        try:
            response = await self._backend.request(definition.method, definition.endpoint, params={"args": ",".join(args)})
            backend_latency_ms = (time.perf_counter() - start_time) * 1000
            bot_command.result = self._format_response(command_name, response)
        except httpx.HTTPStatusError as exc:
            backend_latency_ms = (time.perf_counter() - start_time) * 1000
            status_code = exc.response.status_code
            bot_command.error = f"Backend error {status_code}"
            self._health.record_failure(self._component_name, f"backend_error:{status_code}", recoverable=True)
        except Exception as exc:  # pragma: no cover
            backend_latency_ms = (time.perf_counter() - start_time) * 1000
            bot_command.error = str(exc)
            self._health.record_failure(self._component_name, f"backend_exception:{exc}", recoverable=True)

        bot_command.executed = bot_command.error == ""
        bot_command.executed_at = time.time()
        self._command_history.append(bot_command)
        await event_stream.publish(
            "xbot_command",
            {
                "command": command_name,
                "user": profile.handle,
                "success": bot_command.error == "",
                "latency_ms": backend_latency_ms,
                "status_code": status_code,
                "error": bot_command.error,
            },
        )
        self._health.update_heartbeat(
            self._component_name,
            metadata={
                "event": "command",
                "command": command_name,
                "success": bot_command.error == "",
                "latency_ms": backend_latency_ms,
            },
        )
        return bot_command

    async def _maybe_trigger_incident(self, intel: Dict[str, Any]) -> None:
        if intel["category"] not in {"incident", "phishing"}:
            return
        evidence = {
            "message_id": intel["message_id"],
            "author": intel["author"],
            "content": intel["content"],
            "authenticity": intel["authenticity_score"],
        }
        event = self._breach_system.detect_anomalous_order(
            user_id=intel["author"],
            order_size_usd=0,
            venue="social",
        )
        if event:
            event.category = ThreatCategory.UNAUTHORIZED_ACCESS
            event.threat_level = ThreatLevel.MEDIUM
            event.evidence.update(evidence)
        if self._incident_callback:
            await self._incident_callback({"intel": intel, "breach_event": event})

    def _parse_command(self, content: str) -> Tuple[Optional[str], List[str]]:
        tokens = content.strip().split()
        if not tokens:
            return None, []

        for idx, token in enumerate(tokens):
            if token.startswith("!"):
                command = token[1:].lower()
                return command, tokens[idx + 1 :]
        return None, []

    def _format_response(self, command: str, payload: Dict[str, Any]) -> str:
        if command == "status":
            return f"System running: {payload.get('system_running', False)} | Incidents: {payload.get('incidents', 0)}"
        if command == "risk":
            return f"Risk usage {payload.get('usage_pct', 0):.1f}% | Kill switches: {payload.get('kill_switches', [])}"
        if command == "portfolio":
            return f"PnL: {payload.get('pnl', 0):,.2f} | Exposure: {payload.get('exposure', 0):,.2f}"
        if command == "incidents":
            incidents = payload.get("incidents", [])
            return f"Recent incidents: {len(incidents)}"
        if command == "social-intel":
            return payload.get("summary", "no data")
        return str(payload)

    def _build_social_message(self, payload: Dict[str, Any]) -> SocialMessage:
        return SocialMessage(
            message_id=payload.get("id", f"mention_{int(time.time())}"),
            source=MessageSource.TWITTER,
            author=str(payload.get("user_id", "unknown")),
            content=payload.get("text", ""),
            timestamp=payload.get("timestamp", time.time()),
            asset_tags=payload.get("assets", []),
            sentiment=None,
            engagement=payload.get("engagement", {}),
            is_influencer=payload.get("is_influencer", False),
            is_whale=payload.get("is_whale", False),
        )

    async def run_polling_loop(self, mention_fetcher: Callable[[], Awaitable[List[Dict[str, Any]]]], interval: float = 60.0) -> None:
        """Generic polling loop to ingest mentions while respecting jitter."""
        await self.start()
        while not self._stop:
            try:
                mentions = await mention_fetcher()
                for mention in mentions:
                    try:
                        await self.process_mention(mention)
                    except Exception as exc:  # pragma: no cover
                        logger.error("Failed to process mention: %s", exc)
                sleep_for = interval + random.uniform(-5, 5)
                await asyncio.sleep(max(5.0, sleep_for))
            except Exception as exc:  # pragma: no cover
                logger.error("Mention fetcher failed: %s", exc)
                await asyncio.sleep(interval * 2)

