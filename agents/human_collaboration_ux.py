"""
Human-in-the-loop collaboration utilities with mentorship memory.

Provides a light-weight interface layer that lets operators pair with swarm
agents. Each session captures prompts, decisions, and mentorship tags so the
value-learning system can replay the interactions later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
from utils.logger import get_logger
import threading
import uuid


logger = get_logger(__name__)


@dataclass
class MentorshipNote:
    note_id: str
    mentor: str
    mentee_agent: str
    guidance: str
    tags: List[str]
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CollaborationSession:
    session_id: str
    agent_id: str
    operator: str
    started_at: datetime = field(default_factory=datetime.utcnow)
    events: List[Dict[str, str]] = field(default_factory=list)
    mentorship_notes: List[MentorshipNote] = field(default_factory=list)
    closed_at: Optional[datetime] = None

    def log_event(self, event_type: str, message: str) -> None:
        self.events.append(
            {"event_type": event_type, "message": message, "timestamp": datetime.utcnow().isoformat()}
        )

    def close(self) -> None:
        self.closed_at = datetime.utcnow()


class HumanCollaborationUX:
    """Facilitates operator collaboration sessions with mentorship memory."""

    def __init__(self) -> None:
        self._sessions: Dict[str, CollaborationSession] = {}
        self._mentorship_history: List[MentorshipNote] = []

    def start_session(self, agent_id: str, operator: str) -> CollaborationSession:
        session = CollaborationSession(
            session_id=uuid.uuid4().hex[:12],
            agent_id=agent_id,
            operator=operator,
        )
        self._sessions[session.session_id] = session
        logger.info("Started collaboration session %s for agent %s", session.session_id, agent_id)
        return session

    def record_action(self, session_id: str, event_type: str, message: str) -> None:
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(f"Session '{session_id}' not found")
        session.log_event(event_type, message)

    def add_mentorship_note(
        self,
        session_id: str,
        mentor: str,
        guidance: str,
        tags: Optional[List[str]] = None,
    ) -> MentorshipNote:
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(f"Session '{session_id}' not found")
        note = MentorshipNote(
            note_id=uuid.uuid4().hex[:10],
            mentor=mentor,
            mentee_agent=session.agent_id,
            guidance=guidance,
            tags=tags or [],
        )
        session.mentorship_notes.append(note)
        self._mentorship_history.append(note)
        logger.info("Mentorship note %s recorded for agent %s", note.note_id, session.agent_id)
        return note

    def close_session(self, session_id: str) -> CollaborationSession:
        session = self._sessions.get(session_id)
        if not session:
            raise KeyError(f"Session '{session_id}' not found")
        session.close()
        logger.info("Closed collaboration session %s", session_id)
        return session

    def get_active_sessions(self) -> List[CollaborationSession]:
        return [s for s in self._sessions.values() if s.closed_at is None]

    def get_mentorship_history(self, agent_id: Optional[str] = None) -> List[MentorshipNote]:
        if agent_id:
            return [note for note in self._mentorship_history if note.mentee_agent == agent_id]
        return list(self._mentorship_history)


_human_collab_ux: Optional[HumanCollaborationUX] = None
_human_collab_ux_lock = threading.Lock()


def get_human_collaboration_ux() -> HumanCollaborationUX:
    global _human_collab_ux
    if _human_collab_ux is None:
        with _human_collab_ux_lock:
            if _human_collab_ux is None:
                _human_collab_ux = HumanCollaborationUX()
    return _human_collab_ux
