"""
MERID State Recovery and Persistence
Self-healing state management with automatic recovery and persistence
"""

import asyncio
import json
import threading

from utils.logger import get_logger
import ormsgpack
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from enum import Enum

logger = get_logger(__name__)


class StateStatus(Enum):
    """State health status"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CORRUPTED = "corrupted"
    RECOVERING = "recovering"


@dataclass
class StateSnapshot:
    """Snapshot of component state"""
    component: str
    timestamp: float
    state_data: Dict[str, Any]
    version: str
    checksum: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RecoveryPoint:
    """Recovery point for state restoration"""
    recovery_id: str
    timestamp: float
    component: str
    state_snapshot: StateSnapshot
    is_valid: bool = True
    recovery_count: int = 0


class StateManager:
    """Manages component state with persistence and recovery"""
    
    def __init__(self, component_name: str, persistence_dir: str = "data/state"):
        self.component_name = component_name
        self.persistence_dir = Path(persistence_dir)
        self.persistence_dir.mkdir(parents=True, exist_ok=True)
        
        self.current_state: Dict[str, Any] = {}
        self.state_history: List[StateSnapshot] = []
        self.recovery_points: List[RecoveryPoint] = []
        self.state_status = StateStatus.HEALTHY
        
        self._lock = asyncio.Lock()
        self._auto_save_task: Optional[asyncio.Task] = None
        self._auto_save_interval = 60.0  # Save every 60 seconds
        self._max_history = 100
        self._max_recovery_points = 10
    
    async def initialize(self):
        """Initialize state manager and attempt recovery"""
        try:
            await self._load_state()
            logger.info(f"State manager initialized for {self.component_name}")
        except Exception as e:
            logger.error(f"Failed to load state for {self.component_name}: {e}")
            await self._attempt_recovery()
    
    async def update_state(self, state_data: Dict[str, Any], create_recovery_point: bool = False):
        """Update component state"""
        async with self._lock:
            self.current_state.update(state_data)
            
            # Create snapshot
            snapshot = StateSnapshot(
                component=self.component_name,
                timestamp=time.time(),
                state_data=self.current_state.copy(),
                version="1.0",
                checksum=self._calculate_checksum(self.current_state)
            )
            
            self.state_history.append(snapshot)
            
            # Trim history
            if len(self.state_history) > self._max_history:
                self.state_history = self.state_history[-self._max_history:]
            
            # Create recovery point if requested
            if create_recovery_point:
                await self._create_recovery_point(snapshot)
            
            # Validate state
            if not await self._validate_state():
                logger.warning(f"State validation failed for {self.component_name}")
                self.state_status = StateStatus.DEGRADED
                await self._attempt_recovery()
    
    async def get_state(self) -> Dict[str, Any]:
        """Get current state"""
        async with self._lock:
            return self.current_state.copy()
    
    async def _create_recovery_point(self, snapshot: StateSnapshot):
        """Create a recovery point"""
        recovery_point = RecoveryPoint(
            recovery_id=f"{self.component_name}_{int(time.time() * 1000)}",
            timestamp=time.time(),
            component=self.component_name,
            state_snapshot=snapshot
        )
        
        self.recovery_points.append(recovery_point)
        
        # Trim recovery points
        if len(self.recovery_points) > self._max_recovery_points:
            self.recovery_points = self.recovery_points[-self._max_recovery_points:]
        
        # Persist recovery point
        await self._save_recovery_point(recovery_point)
    
    async def _attempt_recovery(self):
        """Attempt to recover from corrupted state"""
        logger.info(f"Attempting state recovery for {self.component_name}")
        self.state_status = StateStatus.RECOVERING
        
        # Try recovery points in reverse order (newest first)
        for recovery_point in reversed(self.recovery_points):
            if recovery_point.is_valid:
                try:
                    self.current_state = recovery_point.state_snapshot.state_data.copy()
                    recovery_point.recovery_count += 1
                    
                    if await self._validate_state():
                        self.state_status = StateStatus.HEALTHY
                        logger.info(
                            f"State recovered successfully for {self.component_name} "
                            f"from recovery point {recovery_point.recovery_id}"
                        )
                        return True
                except Exception as e:
                    logger.error(f"Recovery attempt failed: {e}")
                    recovery_point.is_valid = False
        
        # If all recovery points failed, initialize with empty state
        logger.warning(f"All recovery points failed for {self.component_name}, initializing empty state")
        self.current_state = {}
        self.state_status = StateStatus.DEGRADED
        return False
    
    async def _validate_state(self) -> bool:
        """Validate current state integrity"""
        try:
            # Check if state is a dictionary
            if not isinstance(self.current_state, dict):
                return False
            
            # Check checksum if available
            if self.state_history:
                last_snapshot = self.state_history[-1]
                current_checksum = self._calculate_checksum(self.current_state)
                if current_checksum != last_snapshot.checksum:
                    logger.warning(f"State checksum mismatch for {self.component_name}")
            
            return True
        except Exception as e:
            logger.error(f"State validation error: {e}")
            return False
    
    def _calculate_checksum(self, state_data: Dict[str, Any]) -> str:
        """Calculate checksum for state data"""
        import hashlib
        state_json = json.dumps(state_data, sort_keys=True)
        return hashlib.sha256(state_json.encode()).hexdigest()
    
    async def _save_state(self):
        """Persist current state to disk"""
        try:
            state_file = self.persistence_dir / f"{self.component_name}_state.json"
            
            async with self._lock:
                state_data = {
                    "component": self.component_name,
                    "timestamp": time.time(),
                    "state": self.current_state,
                    "status": self.state_status.value
                }
            
            with open(state_file, 'w') as f:
                json.dump(state_data, f, indent=2)
            
            logger.debug(f"State saved for {self.component_name}")
        except Exception as e:
            logger.error(f"Failed to save state for {self.component_name}: {e}")
    
    async def _load_state(self):
        """Load persisted state from disk"""
        try:
            state_file = self.persistence_dir / f"{self.component_name}_state.json"
            
            if not state_file.exists():
                logger.info(f"No persisted state found for {self.component_name}")
                return
            
            with open(state_file, 'r') as f:
                state_data = json.load(f)
            
            async with self._lock:
                self.current_state = state_data.get("state", {})
                self.state_status = StateStatus(state_data.get("status", "healthy"))
            
            logger.info(f"State loaded for {self.component_name}")
        except Exception as e:
            logger.error(f"Failed to load state for {self.component_name}: {e}")
            raise
    
    async def _save_recovery_point(self, recovery_point: RecoveryPoint):
        """Persist recovery point to disk"""
        try:
            recovery_file = self.persistence_dir / f"{recovery_point.recovery_id}.recovery"
            
            with open(recovery_file, 'wb') as f:
                f.write(ormsgpack.packb(recovery_point))
            
            logger.debug(f"Recovery point saved: {recovery_point.recovery_id}")
        except Exception as e:
            logger.error(f"Failed to save recovery point: {e}")
    
    async def start_auto_save(self, interval: float = 60.0):
        """Start automatic state persistence"""
        self._auto_save_interval = interval
        
        async def auto_save_loop():
            while True:
                await asyncio.sleep(self._auto_save_interval)
                await self._save_state()
        
        self._auto_save_task = asyncio.create_task(auto_save_loop())
        logger.info(f"Auto-save started for {self.component_name} (interval: {interval}s)")
    
    async def stop_auto_save(self):
        """Stop automatic state persistence"""
        if self._auto_save_task:
            self._auto_save_task.cancel()
            try:
                await self._auto_save_task
            except asyncio.CancelledError:
                pass
            
            # Final save
            await self._save_state()
            logger.info(f"Auto-save stopped for {self.component_name}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get state manager status"""
        return {
            "component": self.component_name,
            "status": self.state_status.value,
            "state_size": len(json.dumps(self.current_state)),
            "history_count": len(self.state_history),
            "recovery_points": len(self.recovery_points),
            "last_update": self.state_history[-1].timestamp if self.state_history else None
        }


class GracefulDegradation:
    """Manages graceful degradation of system capabilities"""
    
    def __init__(self):
        self.degradation_levels: Dict[str, int] = {}  # 0=full, 1=degraded, 2=minimal, 3=disabled
        self.fallback_handlers: Dict[str, Callable] = {}
        self._lock = asyncio.Lock()
    
    async def set_degradation_level(self, component: str, level: int):
        """Set degradation level for component"""
        async with self._lock:
            self.degradation_levels[component] = level
            logger.warning(f"Component {component} degradation level set to {level}")
    
    async def get_degradation_level(self, component: str) -> int:
        """Get current degradation level"""
        async with self._lock:
            return self.degradation_levels.get(component, 0)
    
    def register_fallback(self, component: str, handler: Callable):
        """Register fallback handler for component"""
        self.fallback_handlers[component] = handler
    
    async def execute_with_fallback(
        self,
        component: str,
        primary_func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """Execute function with fallback on failure"""
        try:
            # Try primary function
            if asyncio.iscoroutinefunction(primary_func):
                return await primary_func(*args, **kwargs)
            else:
                return primary_func(*args, **kwargs)
        except Exception as e:
            logger.warning(f"Primary function failed for {component}: {e}")
            
            # Try fallback
            fallback = self.fallback_handlers.get(component)
            if fallback:
                try:
                    logger.info(f"Executing fallback for {component}")
                    if asyncio.iscoroutinefunction(fallback):
                        return await fallback(*args, **kwargs)
                    else:
                        return fallback(*args, **kwargs)
                except Exception as fallback_error:
                    logger.error(f"Fallback also failed for {component}: {fallback_error}")
                    raise
            else:
                raise
    
    def get_status(self) -> Dict[str, Any]:
        """Get degradation status"""
        return {
            "degraded_components": {
                comp: level for comp, level in self.degradation_levels.items() if level > 0
            },
            "total_components": len(self.degradation_levels),
            "healthy_components": sum(1 for level in self.degradation_levels.values() if level == 0)
        }


class SelfHealing:
    """Self-healing mechanisms for automatic recovery"""
    
    def __init__(self):
        self.healing_strategies: Dict[str, Callable] = {}
        self.healing_history: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()
    
    def register_healing_strategy(self, component: str, strategy: Callable):
        """Register self-healing strategy for component"""
        self.healing_strategies[component] = strategy
        logger.info(f"Self-healing strategy registered for {component}")
    
    async def attempt_healing(self, component: str, error: Exception) -> bool:
        """Attempt to heal component after error"""
        strategy = self.healing_strategies.get(component)
        if not strategy:
            logger.warning(f"No healing strategy registered for {component}")
            return False
        
        try:
            logger.info(f"Attempting self-healing for {component}")
            
            if asyncio.iscoroutinefunction(strategy):
                result = await strategy(error)
            else:
                result = strategy(error)
            
            healing_record = {
                "component": component,
                "timestamp": time.time(),
                "error": str(error),
                "success": bool(result)
            }
            
            async with self._lock:
                self.healing_history.append(healing_record)
            
            if result:
                logger.info(f"Self-healing successful for {component}")
            else:
                logger.warning(f"Self-healing failed for {component}")
            
            return bool(result)
            
        except Exception as healing_error:
            logger.error(f"Self-healing error for {component}: {healing_error}")
            return False
    
    def get_healing_stats(self) -> Dict[str, Any]:
        """Get self-healing statistics"""
        total_attempts = len(self.healing_history)
        successful = sum(1 for h in self.healing_history if h["success"])
        
        return {
            "total_attempts": total_attempts,
            "successful": successful,
            "success_rate": (successful / total_attempts * 100) if total_attempts > 0 else 0,
            "recent_healings": self.healing_history[-10:]
        }


# Global instances
_state_managers: Dict[str, StateManager] = {}
_graceful_degradation: Optional[GracefulDegradation] = None
_graceful_degradation_lock = threading.Lock()
_self_healing: Optional[SelfHealing] = None
_self_healing_lock = threading.Lock()


def get_state_manager(component_name: str) -> StateManager:
    """Get or create state manager for component"""
    if component_name not in _state_managers:
        _state_managers[component_name] = StateManager(component_name)
    return _state_managers[component_name]


def get_graceful_degradation() -> GracefulDegradation:
    """Get global graceful degradation instance"""
    global _graceful_degradation
    if _graceful_degradation is None:
        with _graceful_degradation_lock:
            if _graceful_degradation is None:
                _graceful_degradation = GracefulDegradation()
    return _graceful_degradation


def get_self_healing() -> SelfHealing:
    """Get global self-healing instance"""
    global _self_healing
    if _self_healing is None:
        with _self_healing_lock:
            if _self_healing is None:
                _self_healing = SelfHealing()
    return _self_healing
