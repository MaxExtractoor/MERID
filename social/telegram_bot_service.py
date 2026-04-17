from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
import asyncio
from typing import Any, Dict, List, Optional

from fastapi.encoders import jsonable_encoder

from core.event_bus import event_stream
from security.breach_detection import PermissionLevel, get_breach_detection_system
from social.social_aware_quant import BotCommand, BotCommandType
from social.x_bot_interface import BackendClient
from utils.logger import get_logger
from social.social_aware_quant import get_social_bot_health_monitor


logger = get_logger("social.telegram_bot")


class TelegramBotRole(Enum):
    VIEWER = "viewer"
    USER = "user"
    OPERATOR = "operator"
    ADMIN = "admin"


@dataclass
class TelegramCommandDefinition:
    name: str
    command_type: BotCommandType
    required_role: TelegramBotRole
    description: str
    method: str = "GET"
    endpoint: Optional[str] = None
    requires_confirmation: bool = False


@dataclass
class TelegramUserProfile:
    user_id: str
    handle: str
    role: TelegramBotRole
    auth_token: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TelegramSession:
    session_id: str
    user_id: str
    started_at: float
    expires_at: float


class TelegramRateLimiter:
    def __init__(self) -> None:
        self._history: Dict[str, List[float]] = {}

    def check_and_record(self, user_id: str, limit_per_hour: int) -> bool:
        now = time.time()
        window = 3600
        history = self._history.setdefault(user_id, [])
        history[:] = [ts for ts in history if now - ts < window]
        if len(history) >= limit_per_hour:
            return False
        history.append(now)
        return True


class TelegramBotService:
    def __init__(
        self,
        command_definitions: Optional[Dict[str, TelegramCommandDefinition]] = None,
        backend_client: Optional[BackendClient] = None,
        session_ttl_seconds: int = 4 * 3600,
    ) -> None:
        self._commands = command_definitions or self._default_commands()
        self._backend = backend_client or BackendClient()
        self._session_ttl = session_ttl_seconds

        self._users: Dict[str, TelegramUserProfile] = {}
        self._sessions: Dict[str, TelegramSession] = {}
        self._rate_limiter = TelegramRateLimiter()
        self._pending_approvals: Dict[str, BotCommand] = {}
        self._breach_system = get_breach_detection_system()
        self._lock = asyncio.Lock()
        self._health = get_social_bot_health_monitor()
        self._component_name = "telegram_bot_service"
        self._health.register_component(
            self._component_name,
            component_type="bot",
            auto_recover=True,
            heartbeat_interval=120.0,
        )
        self._health.update_heartbeat(self._component_name, status="initialized")

    # ------------------------------------------------------------------
    # User/session management
    # ------------------------------------------------------------------
    def register_user(
        self,
        user_id: str,
        handle: str,
        role: TelegramBotRole,
        auth_token: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._users[user_id] = TelegramUserProfile(user_id, handle, role, auth_token, metadata or {})
        logger.info("Registered Telegram user %s with role %s", handle, role.value)

    def has_user(self, user_id: str) -> bool:
        return user_id in self._users

    def list_users(self) -> List[TelegramUserProfile]:
        return list(self._users.values())

    def start_session(self, user_id: str, auth_token: str) -> Optional[TelegramSession]:
        profile = self._users.get(user_id)
        if not profile or profile.auth_token != auth_token:
            logger.warning("Telegram auth failed for %s", user_id)
            self._breach_system.detect_auth_failure(user_id, "telegram", "invalid_token")
            return None

        now = time.time()
        session = TelegramSession(
            session_id=str(uuid.uuid4()),
            user_id=user_id,
            started_at=now,
            expires_at=now + self._session_ttl,
        )
        self._sessions[user_id] = session
        logger.info("Telegram session started for %s", profile.handle)
        self._health.update_heartbeat(
            self._component_name,
            metadata={"event": "session_start", "user_id": user_id, "handle": profile.handle},
        )
        return session

    def end_session(self, user_id: str, session_id: Optional[str] = None) -> bool:
        session = self._sessions.get(user_id)
        if not session:
            return False
        if session_id and session.session_id != session_id:
            return False
        self._sessions.pop(user_id, None)
        logger.info("Telegram session ended for %s", user_id)
        self._health.update_heartbeat(
            self._component_name,
            metadata={"event": "session_end", "user_id": user_id},
        )
        return True

    def get_session(self, user_id: str) -> Optional[TelegramSession]:
        return self._sessions.get(user_id)

    def _session_active(self, user_id: str) -> bool:
        session = self._sessions.get(user_id)
        if not session:
            return False
        if session.expires_at < time.time():
            self._sessions.pop(user_id, None)
            return False
        return True

    def _session_matches(self, user_id: str, session_id: Optional[str]) -> bool:
        if not session_id:
            return True
        session = self._sessions.get(user_id)
        return bool(session and session.session_id == session_id)

    # ------------------------------------------------------------------
    # Command handling
    # ------------------------------------------------------------------
    async def process_message(
        self,
        user_id: str,
        text: str,
        message_id: str,
        session_id: Optional[str] = None,
    ) -> str:
        profile = self._users.get(user_id)
        if not profile:
            return "Access denied. Contact MERID ops."

        if not self._session_active(user_id):
            return "Session expired or missing. Run /login first."

        if not self._session_matches(user_id, session_id):
            return "Session mismatch. Please re-authenticate."

        text = text.strip()
        if not text:
            return ""

        if text.startswith("/confirm"):
            self._health.update_heartbeat(
                self._component_name,
                metadata={"event": "confirm_request", "user": profile.handle},
            )
            return await self._handle_confirmation(profile, text, message_id)

        command_name, args = self._parse_command(text)
        if not command_name:
            return "Unknown command. Use /help."

        definition = self._commands.get(command_name)
        if not definition:
            return "Command not available."

        if not self._is_role_authorized(profile.role, definition.required_role):
            self._breach_system.detect_auth_failure(user_id, "telegram", "unauthorized_command")
            return "You do not have permission for this command."

        rate_limit = 60 if definition.command_type == BotCommandType.READ_ONLY else 10
        if not self._rate_limiter.check_and_record(user_id, rate_limit):
            return "Rate limit exceeded. Try again later."

        permission = PermissionLevel.READ if definition.command_type == BotCommandType.READ_ONLY else PermissionLevel.EXECUTE
        allowed = self._breach_system.check_permission(
            actor_id=user_id,
            role_id=profile.role.value,
            resource=f"telegram.{command_name}",
            required_permission=permission,
            details={"args": args, "risk": definition.command_type.value},
        )
        if not allowed:
            return "Command blocked by breach detection."

        bot_command = BotCommand(
            command_id=f"tg_{message_id}",
            command_type=definition.command_type,
            command=command_name,
            args=args,
            source="telegram",
            user_id=user_id,
            requires_auth=True,
            requires_approval=definition.requires_confirmation,
        )

        if definition.requires_confirmation:
            approval_id = await self._queue_approval(bot_command, profile)
            return f"Command `{command_name}` queued. Confirm with `/confirm {approval_id}`."

        return await self._execute_command(bot_command, definition, profile)

    def _parse_command(self, text: str) -> tuple[Optional[str], List[str]]:
        if not text.startswith("/"):
            return None, []
        parts = text[1:].split()
        if not parts:
            return None, []
        return parts[0].lower(), parts[1:]

    def _is_role_authorized(self, role: TelegramBotRole, required: TelegramBotRole) -> bool:
        hierarchy = {
            TelegramBotRole.VIEWER: 0,
            TelegramBotRole.USER: 1,
            TelegramBotRole.OPERATOR: 2,
            TelegramBotRole.ADMIN: 3,
        }
        return hierarchy[role] >= hierarchy[required]

    async def _queue_approval(self, command: BotCommand, profile: TelegramUserProfile) -> str:
        approval_id = str(uuid.uuid4())
        async with self._lock:
            self._pending_approvals[approval_id] = command
        await event_stream.publish(
            "telegram_command",
            {
                "command": command.command,
                "user": profile.handle,
                "pending": True,
                "approval_id": approval_id,
            },
        )
        return approval_id

    async def _handle_confirmation(self, profile: TelegramUserProfile, text: str, message_id: str) -> str:
        parts = text.split()
        if len(parts) < 2:
            return "Usage: /confirm <id>"
        approval_id = parts[1]
        async with self._lock:
            command = self._pending_approvals.pop(approval_id, None)
        if not command:
            return "No pending command with that ID."

        definition = self._commands.get(command.command)
        if not definition:
            return "Command definition missing."

        return await self._execute_command(command, definition, profile)

    async def _execute_command(
        self,
        command: BotCommand,
        definition: TelegramCommandDefinition,
        profile: TelegramUserProfile,
    ) -> str:
        backend_latency_ms = 0.0
        status_code = None
        result_text = ""

        if definition.endpoint:
            start = time.perf_counter()
            try:
                response, status_code = await self._backend.request(definition.method, definition.endpoint)
                backend_latency_ms = (time.perf_counter() - start) * 1000
                result_text = self._format_response(command.command, response)
                command.result = result_text
                command.executed = True
            except Exception as exc:  # pragma: no cover
                backend_latency_ms = (time.perf_counter() - start) * 1000
                command.error = str(exc)
                result_text = f"Backend error: {exc}"
                self._health.record_failure(self._component_name, f"backend_error:{exc}", recoverable=True)
        else:
            result_text = "Command acknowledged. Backend endpoint not yet available."
            command.result = result_text
            command.executed = True

        await event_stream.publish(
            "telegram_command",
            {
                "command": command.command,
                "user": profile.handle,
                "success": command.error == "",
                "latency_ms": backend_latency_ms,
                "status_code": status_code,
                "pending": False,
                "result": result_text,
            },
        )
        self._health.update_heartbeat(
            self._component_name,
            metadata={
                "event": "command",
                "command": command.command,
                "success": command.error == "",
                "latency_ms": backend_latency_ms,
            },
        )
        return result_text

    def _format_response(self, command: str, payload: Dict[str, Any]) -> str:
        if command == "status":
            incidents = payload.get("health", {}).get("incidents", {}).get("active", 0)
            return f"MERID online. Active incidents: {incidents}."
        if command == "portfolio":
            value = payload.get("portfolio_value") or payload.get("portfolio", {}).get("value")
            return f"Portfolio value: ${value:,.2f}" if value else jsonable_encoder(payload)
        if command == "risk":
            kill_switch = payload.get("social_kill_switch", {}).get("kill_switch_active")
            return f"Social kill switch active: {bool(kill_switch)}."
        if command == "incidents":
            total = payload.get("total", 0)
            return f"Incidents in queue: {total}."
        if command == "intel":
            return payload.get("summary", "No intel available.")
        return jsonable_encoder(payload)

    # ------------------------------------------------------------------
    # Command definitions
    # ------------------------------------------------------------------
    def _default_commands(self) -> Dict[str, TelegramCommandDefinition]:
        return {
            "help": TelegramCommandDefinition(
                name="help",
                command_type=BotCommandType.READ_ONLY,
                required_role=TelegramBotRole.VIEWER,
                description="List available commands",
            ),
            "status": TelegramCommandDefinition(
                name="status",
                command_type=BotCommandType.READ_ONLY,
                required_role=TelegramBotRole.VIEWER,
                description="System status",
                endpoint="/x/status",
            ),
            "portfolio": TelegramCommandDefinition(
                name="portfolio",
                command_type=BotCommandType.READ_ONLY,
                required_role=TelegramBotRole.USER,
                description="Portfolio summary",
                endpoint="/x/portfolio",
            ),
            "risk": TelegramCommandDefinition(
                name="risk",
                command_type=BotCommandType.READ_ONLY,
                required_role=TelegramBotRole.USER,
                description="Risk and kill switch state",
                endpoint="/x/risk",
            ),
            "incidents": TelegramCommandDefinition(
                name="incidents",
                command_type=BotCommandType.READ_ONLY,
                required_role=TelegramBotRole.OPERATOR,
                description="Incident summaries",
                endpoint="/x/incidents",
            ),
            "intel": TelegramCommandDefinition(
                name="intel",
                command_type=BotCommandType.READ_ONLY,
                required_role=TelegramBotRole.USER,
                description="Social intel summary",
                endpoint="/x/social-intel",
            ),
            "pause": TelegramCommandDefinition(
                name="pause",
                command_type=BotCommandType.LIMITED_CONTROL,
                required_role=TelegramBotRole.OPERATOR,
                description="Pause trading",
                requires_confirmation=True,
            ),
            "resume": TelegramCommandDefinition(
                name="resume",
                command_type=BotCommandType.LIMITED_CONTROL,
                required_role=TelegramBotRole.OPERATOR,
                description="Resume trading",
                requires_confirmation=True,
            ),
            "reduce_risk": TelegramCommandDefinition(
                name="reduce_risk",
                command_type=BotCommandType.LIMITED_CONTROL,
                required_role=TelegramBotRole.OPERATOR,
                description="Temporarily reduce exposure",
                requires_confirmation=True,
            ),
            "emergency_stop": TelegramCommandDefinition(
                name="emergency_stop",
                command_type=BotCommandType.ADMIN,
                required_role=TelegramBotRole.ADMIN,
                description="Emergency kill switch",
                requires_confirmation=True,
            ),
        }


_telegram_bot_service: Optional[TelegramBotService] = None
_telegram_bot_service_lock = threading.Lock()


def get_telegram_bot_service() -> TelegramBotService:
    global _telegram_bot_service
    if _telegram_bot_service is None:
        with _telegram_bot_service_lock:
            if _telegram_bot_service is None:
                _telegram_bot_service = TelegramBotService()
    return _telegram_bot_service


