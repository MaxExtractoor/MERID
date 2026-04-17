"""
Deterministic Replay Engine.

Enables replay of historical market data and consensus decisions
for backtesting, debugging, and offline analysis.

Version: 1.0.0
"""

from __future__ import annotations

import threading
import asyncio
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

from offline.data_cache import LocalDataCache, get_local_data_cache, CacheType
from utils.logger import get_logger

logger = get_logger("offline.replay")


class ReplaySpeed(Enum):
    """Replay speed options."""
    REALTIME = 1.0
    FAST_2X = 2.0
    FAST_5X = 5.0
    FAST_10X = 10.0
    FAST_100X = 100.0
    INSTANT = float("inf")


class ReplayStatus(Enum):
    """Status of replay."""
    IDLE = "idle"
    LOADING = "loading"
    PLAYING = "playing"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class ReplayEvent:
    """A single event in the replay timeline."""
    event_id: str
    event_type: str
    timestamp: float
    data: Dict[str, Any]
    processed: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "data": self.data,
            "processed": self.processed,
        }


@dataclass
class ReplaySession:
    """A replay session."""
    session_id: str
    status: ReplayStatus = ReplayStatus.IDLE
    
    # Time range
    start_time: float = 0.0
    end_time: float = 0.0
    current_time: float = 0.0
    
    # Events
    events: List[ReplayEvent] = field(default_factory=list)
    current_index: int = 0
    
    # Speed
    speed: ReplaySpeed = ReplaySpeed.REALTIME
    
    # Stats
    events_processed: int = 0
    events_total: int = 0
    
    # Timing
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    
    def progress_pct(self) -> float:
        if self.events_total == 0:
            return 0.0
        return (self.events_processed / self.events_total) * 100
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "current_time": self.current_time,
            "current_index": self.current_index,
            "speed": self.speed.value,
            "events_processed": self.events_processed,
            "events_total": self.events_total,
            "progress_pct": self.progress_pct(),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class ReplayEngine:
    """
    Deterministic replay engine for offline analysis.
    
    Features:
    - Load historical data from cache
    - Replay at various speeds
    - Pause/resume/seek
    - Event callbacks for integration
    - Deterministic execution
    """
    
    def __init__(self):
        self.logger = get_logger("offline.replay")
        self._cache = get_local_data_cache()
        
        # Sessions
        self._sessions: Dict[str, ReplaySession] = {}
        self._active_session: Optional[str] = None
        
        # Callbacks
        self._event_callbacks: Dict[str, List[Callable[[ReplayEvent], None]]] = {}
        
        # Running state
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
    
    def create_session(
        self,
        start_time: float,
        end_time: float,
        speed: ReplaySpeed = ReplaySpeed.REALTIME,
    ) -> ReplaySession:
        """Create a new replay session."""
        import uuid
        
        session_id = f"replay_{uuid.uuid4().hex[:8]}"
        
        session = ReplaySession(
            session_id=session_id,
            start_time=start_time,
            end_time=end_time,
            current_time=start_time,
            speed=speed,
        )
        
        self._sessions[session_id] = session
        self.logger.info(f"Created replay session: {session_id}")
        
        return session
    
    async def load_session(self, session_id: str) -> bool:
        """Load events for a replay session."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        session.status = ReplayStatus.LOADING
        
        try:
            events = []
            
            # Load price data
            price_events = self._load_price_events(session.start_time, session.end_time)
            events.extend(price_events)
            
            # Load consensus events
            consensus_events = self._load_consensus_events(session.start_time, session.end_time)
            events.extend(consensus_events)
            
            # Sort by timestamp
            events.sort(key=lambda e: e.timestamp)
            
            session.events = events
            session.events_total = len(events)
            session.status = ReplayStatus.IDLE
            
            self.logger.info(f"Loaded {len(events)} events for session {session_id}")
            return True
            
        except Exception as e:
            session.status = ReplayStatus.ERROR
            self.logger.error(f"Failed to load session: {e}")
            return False
    
    def _load_price_events(self, start_time: float, end_time: float) -> List[ReplayEvent]:
        """Load price events from cache."""
        events = []
        
        # Get all cached prices
        type_dir = self._cache.cache_dir / CacheType.PRICE_DATA.value
        if not type_dir.exists():
            return events
        
        import json
        
        for cache_file in type_dir.glob("*.json"):
            try:
                with open(cache_file, "r") as f:
                    entry = json.load(f)
                    data = entry.get("data", {})
                    ts = data.get("timestamp", 0)
                    
                    if start_time <= ts <= end_time:
                        events.append(ReplayEvent(
                            event_id=f"price_{int(ts)}",
                            event_type="price_update",
                            timestamp=ts,
                            data=data,
                        ))
            except Exception as _pf_exc:
                logger.debug("Price cache file read failed for %s: %s", cache_file, _pf_exc)
        
        return events
    
    def _load_consensus_events(self, start_time: float, end_time: float) -> List[ReplayEvent]:
        """Load consensus events from cache."""
        events = []
        
        type_dir = self._cache.cache_dir / CacheType.CONSENSUS.value
        if not type_dir.exists():
            return events
        
        import json
        
        for cache_file in type_dir.glob("*.json"):
            try:
                with open(cache_file, "r") as f:
                    entry = json.load(f)
                    data = entry.get("data", {})
                    ts = data.get("timestamp", entry.get("timestamp", 0))
                    
                    if start_time <= ts <= end_time:
                        events.append(ReplayEvent(
                            event_id=data.get("block_id", f"consensus_{int(ts)}"),
                            event_type="consensus_block",
                            timestamp=ts,
                            data=data,
                        ))
            except Exception as _cf_exc:
                logger.debug("Consensus cache file read failed for %s: %s", cache_file, _cf_exc)
        
        return events
    
    async def start(self, session_id: str) -> bool:
        """Start replay for a session."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        if session.status == ReplayStatus.PLAYING:
            return True
        
        if session.events_total == 0:
            await self.load_session(session_id)
        
        session.status = ReplayStatus.PLAYING
        session.started_at = time.time()
        self._active_session = session_id
        self._running = True
        
        self._task = asyncio.create_task(self._replay_loop(session))
        
        self.logger.info(f"Started replay: {session_id}")
        return True
    
    async def _replay_loop(self, session: ReplaySession) -> None:
        """Main replay loop."""
        last_real_time = time.time()
        
        while self._running and session.current_index < len(session.events):
            if session.status == ReplayStatus.PAUSED:
                await asyncio.sleep(0.1)
                last_real_time = time.time()
                continue
            
            event = session.events[session.current_index]
            
            # Calculate wait time based on speed
            if session.speed != ReplaySpeed.INSTANT:
                time_diff = event.timestamp - session.current_time
                wait_time = time_diff / session.speed.value
                
                if wait_time > 0:
                    await asyncio.sleep(min(wait_time, 1.0))
            
            # Process event
            await self._process_event(event)
            
            event.processed = True
            session.current_time = event.timestamp
            session.current_index += 1
            session.events_processed += 1
            
            last_real_time = time.time()
        
        # Completed
        session.status = ReplayStatus.COMPLETED
        session.completed_at = time.time()
        self._running = False
        
        self.logger.info(f"Replay completed: {session.session_id}")
    
    async def _process_event(self, event: ReplayEvent) -> None:
        """Process a replay event."""
        # Call registered callbacks
        callbacks = self._event_callbacks.get(event.event_type, [])
        callbacks.extend(self._event_callbacks.get("*", []))  # Wildcard
        
        for callback in callbacks:
            try:
                callback(event)
            except Exception as e:
                self.logger.error(f"Event callback error: {e}")
    
    def pause(self, session_id: str) -> bool:
        """Pause replay."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        session.status = ReplayStatus.PAUSED
        self.logger.info(f"Replay paused: {session_id}")
        return True
    
    def resume(self, session_id: str) -> bool:
        """Resume replay."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        if session.status == ReplayStatus.PAUSED:
            session.status = ReplayStatus.PLAYING
            self.logger.info(f"Replay resumed: {session_id}")
        return True
    
    async def stop(self, session_id: str) -> bool:
        """Stop replay."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        session.status = ReplayStatus.IDLE
        self.logger.info(f"Replay stopped: {session_id}")
        return True
    
    def seek(self, session_id: str, timestamp: float) -> bool:
        """Seek to a specific timestamp."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        # Find event index for timestamp
        for i, event in enumerate(session.events):
            if event.timestamp >= timestamp:
                session.current_index = i
                session.current_time = timestamp
                break
        
        self.logger.info(f"Seeked to {timestamp} in {session_id}")
        return True
    
    def set_speed(self, session_id: str, speed: ReplaySpeed) -> bool:
        """Set replay speed."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        session.speed = speed
        self.logger.info(f"Set speed to {speed.value}x for {session_id}")
        return True
    
    def on_event(self, event_type: str, callback: Callable[[ReplayEvent], None]) -> None:
        """Register callback for event type."""
        if event_type not in self._event_callbacks:
            self._event_callbacks[event_type] = []
        self._event_callbacks[event_type].append(callback)
    
    def get_session(self, session_id: str) -> Optional[ReplaySession]:
        """Get a replay session."""
        return self._sessions.get(session_id)
    
    def get_status(self) -> Dict[str, Any]:
        """Get replay engine status."""
        return {
            "active_session": self._active_session,
            "running": self._running,
            "sessions": {k: v.to_dict() for k, v in self._sessions.items()},
            "registered_callbacks": list(self._event_callbacks.keys()),
        }


# Singleton
_replay_engine: Optional[ReplayEngine] = None
_replay_engine_lock = threading.Lock()


def get_replay_engine() -> ReplayEngine:
    """Get or create the Replay Engine singleton."""
    global _replay_engine
    if _replay_engine is None:
        with _replay_engine_lock:
            if _replay_engine is None:
                _replay_engine = ReplayEngine()
    return _replay_engine
