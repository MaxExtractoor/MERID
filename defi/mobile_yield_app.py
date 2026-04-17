"""
Mobile app façade for yield management.

Simulates mobile client features like biometric auth, push notifications, and
in-app strategy browsing so we can validate UX flows before shipping native
apps. Works with vault APIs to fetch summaries and trigger deposits/withdraws.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List


@dataclass
class MobileUserSession:
    session_id: str
    user_id: str
    device_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_active_at: datetime = field(default_factory=datetime.utcnow)
    biometric_enabled: bool = True


class MobileYieldApp:
    def __init__(self) -> None:
        self._sessions: Dict[str, MobileUserSession] = {}
        self._notifications: List[Dict[str, str]] = []

    def start_session(self, session_id: str, user_id: str, device_id: str) -> MobileUserSession:
        session = MobileUserSession(session_id=session_id, user_id=user_id, device_id=device_id)
        self._sessions[session_id] = session
        return session

    def record_activity(self, session_id: str) -> None:
        session = self._sessions[session_id]
        session.last_active_at = datetime.utcnow()

    def push_notification(self, user_id: str, title: str, body: str) -> None:
        self._notifications.append({"user_id": user_id, "title": title, "body": body, "timestamp": datetime.utcnow().isoformat()})
