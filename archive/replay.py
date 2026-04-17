"""
MERID Archive - Replay Engine

Enables simulation rewind and replay of historical decisions.
Supports counterfactual analysis and strategy backtesting.

Part of MERID-ARCHIVE (Layer 7 - Memory & Forensics)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("archive.replay")


class ReplayMode(Enum):
    """Replay execution modes."""
    STEP_BY_STEP = "step_by_step"
    CONTINUOUS = "continuous"
    FAST_FORWARD = "fast_forward"


class ReplayState(Enum):
    """State of replay session."""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class ReplayEvent:
    """An event to replay."""
    event_id: str
    timestamp: float
    event_type: str
    data: Dict[str, Any]
    
    # Replay metadata
    replayed: bool = False
    replay_timestamp: Optional[float] = None
    replay_result: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "data": self.data,
            "replayed": self.replayed,
            "replay_timestamp": self.replay_timestamp,
            "replay_result": self.replay_result,
        }


@dataclass
class ReplaySession:
    """A replay session."""
    session_id: str
    created_at: float
    
    # Events to replay
    events: List[ReplayEvent] = field(default_factory=list)
    current_index: int = 0
    
    # State
    state: ReplayState = ReplayState.IDLE
    mode: ReplayMode = ReplayMode.STEP_BY_STEP
    
    # Time control
    start_timestamp: Optional[float] = None
    end_timestamp: Optional[float] = None
    speed_multiplier: float = 1.0
    
    # Results
    results: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    def get_progress(self) -> float:
        """Get replay progress (0.0 to 1.0)."""
        if not self.events:
            return 1.0
        return self.current_index / len(self.events)
    
    def get_current_event(self) -> Optional[ReplayEvent]:
        """Get current event to replay."""
        if 0 <= self.current_index < len(self.events):
            return self.events[self.current_index]
        return None
    
    def advance(self) -> bool:
        """Advance to next event. Returns True if more events remain."""
        self.current_index += 1
        return self.current_index < len(self.events)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "event_count": len(self.events),
            "current_index": self.current_index,
            "state": self.state.value,
            "mode": self.mode.value,
            "progress": round(self.get_progress(), 4),
            "speed_multiplier": self.speed_multiplier,
            "error_count": len(self.errors),
        }


class ReplayEngine:
    """
    Replay engine for historical simulation.
    
    Features:
    - Event-by-event replay
    - Counterfactual analysis
    - Speed control
    - State snapshots
    - Result comparison
    """
    
    def __init__(self):
        self._sessions: Dict[str, ReplaySession] = {}
        self._event_handlers: Dict[str, Callable] = {}
        
        logger.info("Replay engine initialized")
    
    def register_handler(
        self,
        event_type: str,
        handler: Callable[[ReplayEvent], Dict[str, Any]],
    ) -> None:
        """Register a handler for an event type."""
        self._event_handlers[event_type] = handler
        logger.debug("Registered handler for event type: %s", event_type)
    
    def create_session(
        self,
        events: List[Dict[str, Any]],
        mode: ReplayMode = ReplayMode.STEP_BY_STEP,
        speed_multiplier: float = 1.0,
    ) -> ReplaySession:
        """Create a new replay session."""
        import uuid
        
        session_id = str(uuid.uuid4())
        
        # Convert events
        replay_events = []
        for i, event_data in enumerate(events):
            replay_event = ReplayEvent(
                event_id=event_data.get("event_id", f"event_{i}"),
                timestamp=event_data.get("timestamp", time.time()),
                event_type=event_data.get("event_type", "unknown"),
                data=event_data.get("data", event_data),
            )
            replay_events.append(replay_event)
        
        # Sort by timestamp
        replay_events.sort(key=lambda e: e.timestamp)
        
        session = ReplaySession(
            session_id=session_id,
            created_at=time.time(),
            events=replay_events,
            mode=mode,
            speed_multiplier=speed_multiplier,
        )
        
        if replay_events:
            session.start_timestamp = replay_events[0].timestamp
            session.end_timestamp = replay_events[-1].timestamp
        
        self._sessions[session_id] = session
        
        logger.info(
            "Created replay session %s: %d events",
            session_id[:8], len(replay_events)
        )
        
        return session
    
    def start_session(self, session_id: str) -> bool:
        """Start a replay session."""
        session = self._sessions.get(session_id)
        if not session:
            logger.warning("Session not found: %s", session_id)
            return False
        
        if session.state == ReplayState.RUNNING:
            logger.warning("Session already running: %s", session_id)
            return False
        
        session.state = ReplayState.RUNNING
        logger.info("Started replay session: %s", session_id[:8])
        return True
    
    def pause_session(self, session_id: str) -> bool:
        """Pause a replay session."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        if session.state == ReplayState.RUNNING:
            session.state = ReplayState.PAUSED
            logger.info("Paused replay session: %s", session_id[:8])
            return True
        return False
    
    def resume_session(self, session_id: str) -> bool:
        """Resume a paused session."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        if session.state == ReplayState.PAUSED:
            session.state = ReplayState.RUNNING
            logger.info("Resumed replay session: %s", session_id[:8])
            return True
        return False
    
    def step(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Execute one replay step."""
        session = self._sessions.get(session_id)
        if not session:
            return None
        
        if session.state not in [ReplayState.RUNNING, ReplayState.PAUSED]:
            return None
        
        event = session.get_current_event()
        if not event:
            session.state = ReplayState.COMPLETED
            return {"status": "completed", "session_id": session_id}
        
        # Execute handler
        result = self._execute_event(event)
        
        # Record result
        event.replayed = True
        event.replay_timestamp = time.time()
        event.replay_result = result
        session.results.append(result)
        
        # Advance
        if not session.advance():
            session.state = ReplayState.COMPLETED
        
        return result
    
    def run_to_completion(
        self,
        session_id: str,
        callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> List[Dict[str, Any]]:
        """Run session to completion."""
        session = self._sessions.get(session_id)
        if not session:
            return []
        
        self.start_session(session_id)
        results = []
        
        while session.state == ReplayState.RUNNING:
            result = self.step(session_id)
            if result:
                results.append(result)
                if callback:
                    callback(result)
        
        return results
    
    def _execute_event(self, event: ReplayEvent) -> Dict[str, Any]:
        """Execute a single event."""
        handler = self._event_handlers.get(event.event_type)
        
        if handler:
            try:
                result = handler(event)
                return {
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "success": True,
                    "result": result,
                }
            except Exception as e:
                logger.error("Handler error for %s: %s", event.event_type, e)
                return {
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "success": False,
                    "error": str(e),
                }
        else:
            # No handler, just record the event
            return {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "success": True,
                "result": {"passthrough": True, "data": event.data},
            }
    
    def get_session(self, session_id: str) -> Optional[ReplaySession]:
        """Get session by ID."""
        return self._sessions.get(session_id)
    
    def get_session_results(self, session_id: str) -> List[Dict[str, Any]]:
        """Get results from a session."""
        session = self._sessions.get(session_id)
        if session:
            return session.results
        return []
    
    def compare_results(
        self,
        original_outcomes: List[Dict[str, Any]],
        replay_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Compare original outcomes with replay results."""
        if len(original_outcomes) != len(replay_results):
            return {
                "comparable": False,
                "reason": "Length mismatch",
                "original_count": len(original_outcomes),
                "replay_count": len(replay_results),
            }
        
        matches = 0
        differences = []
        
        for i, (orig, replay) in enumerate(zip(original_outcomes, replay_results)):
            if orig == replay.get("result"):
                matches += 1
            else:
                differences.append({
                    "index": i,
                    "original": orig,
                    "replay": replay.get("result"),
                })
        
        return {
            "comparable": True,
            "total_events": len(original_outcomes),
            "matches": matches,
            "match_rate": round(matches / len(original_outcomes), 4) if original_outcomes else 0,
            "differences": differences[:10],  # Limit to first 10
        }
    
    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info("Deleted replay session: %s", session_id[:8])
            return True
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics."""
        state_counts = {}
        for session in self._sessions.values():
            state = session.state.value
            state_counts[state] = state_counts.get(state, 0) + 1
        
        return {
            "total_sessions": len(self._sessions),
            "registered_handlers": list(self._event_handlers.keys()),
            "state_counts": state_counts,
        }


# Singleton instance
_replay_engine: Optional[ReplayEngine] = None


def get_replay_engine() -> ReplayEngine:
    """Get the singleton replay engine."""
    global _replay_engine
    if _replay_engine is None:
        _replay_engine = ReplayEngine()
    return _replay_engine
