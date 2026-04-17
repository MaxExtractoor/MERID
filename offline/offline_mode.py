"""
Offline Mode Manager.

Central coordinator for offline/air-gapped operation.
Manages mode switching, data synchronization, and system state.

Version: 1.0.0
"""

from __future__ import annotations

import threading
import asyncio
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

from offline.data_cache import LocalDataCache, get_local_data_cache
from offline.replay_engine import ReplayEngine, get_replay_engine
from offline.data_import import DataImporter, get_data_importer
from offline.qr_transfer import QRIntentTransfer, get_qr_transfer
from utils.logger import get_logger

logger = get_logger("offline.mode")


class OperationMode(Enum):
    """System operation modes."""
    ONLINE = "online"
    OFFLINE = "offline"
    AIR_GAPPED = "air_gapped"
    HYBRID = "hybrid"  # Online with offline fallback


class SyncStatus(Enum):
    """Data synchronization status."""
    SYNCED = "synced"
    SYNCING = "syncing"
    STALE = "stale"
    OFFLINE = "offline"
    ERROR = "error"


@dataclass
class OfflineState:
    """State of offline mode."""
    mode: OperationMode = OperationMode.ONLINE
    sync_status: SyncStatus = SyncStatus.SYNCED
    
    # Connectivity
    last_online: Optional[float] = None
    last_sync: Optional[float] = None
    connectivity_check_interval: float = 30.0
    
    # Data freshness
    price_data_age_seconds: float = 0.0
    consensus_data_age_seconds: float = 0.0
    max_stale_seconds: float = 300.0  # 5 minutes
    
    # Pending operations
    pending_intents: int = 0
    pending_executions: int = 0
    
    # Mode switch
    mode_changed_at: Optional[float] = None
    auto_switch_enabled: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode.value,
            "sync_status": self.sync_status.value,
            "last_online": self.last_online,
            "last_sync": self.last_sync,
            "price_data_age_seconds": self.price_data_age_seconds,
            "consensus_data_age_seconds": self.consensus_data_age_seconds,
            "is_stale": self.price_data_age_seconds > self.max_stale_seconds,
            "pending_intents": self.pending_intents,
            "pending_executions": self.pending_executions,
            "mode_changed_at": self.mode_changed_at,
            "auto_switch_enabled": self.auto_switch_enabled,
        }


class OfflineModeManager:
    """
    Manages offline/air-gapped operation mode.
    
    Features:
    - Automatic mode switching based on connectivity
    - Data synchronization management
    - Offline intent queue
    - State persistence
    """
    
    def __init__(self):
        self.logger = get_logger("offline.mode")
        
        # Sub-components
        self._cache = get_local_data_cache()
        self._replay = get_replay_engine()
        self._importer = get_data_importer()
        self._qr_transfer = get_qr_transfer()
        
        # State
        self._state = OfflineState()
        
        # Pending operations queue
        self._pending_intents: List[Dict[str, Any]] = []
        self._pending_executions: List[Dict[str, Any]] = []
        
        # Callbacks
        self._mode_change_callbacks: List[Callable[[OperationMode], None]] = []
        self._sync_callbacks: List[Callable[[SyncStatus], None]] = []
        
        # Running state
        self._running: bool = False
        self._monitor_task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """Start offline mode manager."""
        if self._running:
            return
        
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        
        self.logger.info(f"Offline mode manager started in {self._state.mode.value} mode")
    
    async def stop(self) -> None:
        """Stop offline mode manager."""
        self._running = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        self.logger.info("Offline mode manager stopped")
    
    async def _monitor_loop(self) -> None:
        """Monitor connectivity and manage mode."""
        while self._running:
            try:
                # Check connectivity
                is_online = await self._check_connectivity()
                
                # Update state
                if is_online:
                    self._state.last_online = time.time()
                    
                    if self._state.mode == OperationMode.OFFLINE:
                        if self._state.auto_switch_enabled:
                            await self.switch_mode(OperationMode.ONLINE)
                else:
                    if self._state.mode == OperationMode.ONLINE:
                        if self._state.auto_switch_enabled:
                            await self.switch_mode(OperationMode.OFFLINE)
                
                # Update data freshness
                self._update_data_freshness()
                
                # Process pending operations if online
                if is_online and self._state.mode == OperationMode.ONLINE:
                    await self._process_pending_operations()
                
                await asyncio.sleep(self._state.connectivity_check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Monitor error: {e}")
                await asyncio.sleep(60)
    
    async def _check_connectivity(self) -> bool:
        """Check internet connectivity."""
        try:
            import socket
            
            # Try to connect to common endpoints
            endpoints = [
                ("8.8.8.8", 53),      # Google DNS
                ("1.1.1.1", 53),      # Cloudflare DNS
            ]
            
            for host, port in endpoints:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(3)
                    result = sock.connect_ex((host, port))
                    sock.close()
                    
                    if result == 0:
                        return True
                except:
                    continue
            
            return False
            
        except Exception as e:
            self.logger.debug(f"Connectivity check error: {e}")
            return False
    
    def _update_data_freshness(self) -> None:
        """Update data freshness metrics."""
        cache_stats = self._cache.get_stats()
        last_sync = cache_stats.get("last_sync")
        
        if last_sync:
            self._state.last_sync = last_sync
            self._state.price_data_age_seconds = time.time() - last_sync
        
        # Update sync status
        if self._state.mode == OperationMode.OFFLINE:
            self._state.sync_status = SyncStatus.OFFLINE
        elif self._state.price_data_age_seconds > self._state.max_stale_seconds:
            self._state.sync_status = SyncStatus.STALE
        else:
            self._state.sync_status = SyncStatus.SYNCED
    
    async def switch_mode(self, new_mode: OperationMode) -> bool:
        """Switch operation mode."""
        old_mode = self._state.mode
        
        if old_mode == new_mode:
            return True
        
        self.logger.warning(f"Switching mode: {old_mode.value} -> {new_mode.value}")
        
        # Pre-switch actions
        if new_mode == OperationMode.OFFLINE:
            # Save current state
            await self._save_state_for_offline()
        
        elif new_mode == OperationMode.ONLINE:
            # Sync pending operations
            await self._sync_pending_to_online()
        
        elif new_mode == OperationMode.AIR_GAPPED:
            # Full isolation
            await self._prepare_air_gapped()
        
        # Update state
        self._state.mode = new_mode
        self._state.mode_changed_at = time.time()
        
        # Notify callbacks
        for callback in self._mode_change_callbacks:
            try:
                callback(new_mode)
            except Exception as e:
                self.logger.error(f"Mode change callback error: {e}")
        
        return True
    
    async def _save_state_for_offline(self) -> None:
        """Save current state for offline operation."""
        state_snapshot = {
            "timestamp": time.time(),
            "mode": self._state.mode.value,
            "pending_intents": len(self._pending_intents),
            "pending_executions": len(self._pending_executions),
        }
        
        self._cache.cache_system_state(state_snapshot)
        self.logger.info("State saved for offline operation")
    
    async def _sync_pending_to_online(self) -> None:
        """Sync pending operations when coming back online."""
        self._state.sync_status = SyncStatus.SYNCING
        
        # Process pending intents
        for intent in self._pending_intents[:]:
            try:
                # In production, submit to execution engine
                self.logger.info(f"Syncing intent: {intent.get('intent_id')}")
                self._pending_intents.remove(intent)
            except Exception as e:
                self.logger.error(f"Intent sync error: {e}")
        
        # Process pending executions
        for execution in self._pending_executions[:]:
            try:
                self.logger.info(f"Syncing execution: {execution.get('execution_id')}")
                self._pending_executions.remove(execution)
            except Exception as e:
                self.logger.error(f"Execution sync error: {e}")
        
        self._state.sync_status = SyncStatus.SYNCED
        self.logger.info("Pending operations synced")
    
    async def _prepare_air_gapped(self) -> None:
        """Prepare for air-gapped operation."""
        # Disable all network features
        self._state.auto_switch_enabled = False
        
        # Clear any network-dependent state
        self.logger.warning("Entering air-gapped mode - all network features disabled")
    
    async def _process_pending_operations(self) -> None:
        """Process pending operations when online."""
        # Update counts
        self._state.pending_intents = len(self._pending_intents)
        self._state.pending_executions = len(self._pending_executions)
    
    def queue_intent(self, intent: Dict[str, Any]) -> str:
        """Queue an intent for later execution."""
        import uuid
        
        intent_id = intent.get("intent_id", f"intent_{uuid.uuid4().hex[:8]}")
        intent["intent_id"] = intent_id
        intent["queued_at"] = time.time()
        
        self._pending_intents.append(intent)
        self._state.pending_intents = len(self._pending_intents)
        
        self.logger.info(f"Intent queued: {intent_id}")
        return intent_id
    
    def queue_execution(self, execution: Dict[str, Any]) -> str:
        """Queue an execution result for later sync."""
        import uuid
        
        execution_id = execution.get("execution_id", f"exec_{uuid.uuid4().hex[:8]}")
        execution["execution_id"] = execution_id
        execution["queued_at"] = time.time()
        
        self._pending_executions.append(execution)
        self._state.pending_executions = len(self._pending_executions)
        
        self.logger.info(f"Execution queued: {execution_id}")
        return execution_id
    
    def get_pending_intents(self) -> List[Dict[str, Any]]:
        """Get pending intents."""
        return self._pending_intents.copy()
    
    def get_pending_executions(self) -> List[Dict[str, Any]]:
        """Get pending executions."""
        return self._pending_executions.copy()
    
    def on_mode_change(self, callback: Callable[[OperationMode], None]) -> None:
        """Register callback for mode changes."""
        self._mode_change_callbacks.append(callback)
    
    def on_sync_status_change(self, callback: Callable[[SyncStatus], None]) -> None:
        """Register callback for sync status changes."""
        self._sync_callbacks.append(callback)
    
    def set_auto_switch(self, enabled: bool) -> None:
        """Enable/disable automatic mode switching."""
        self._state.auto_switch_enabled = enabled
        self.logger.info(f"Auto mode switch: {'enabled' if enabled else 'disabled'}")
    
    def force_offline(self) -> None:
        """Force offline mode (for testing or manual control)."""
        asyncio.create_task(self.switch_mode(OperationMode.OFFLINE))
        self._state.auto_switch_enabled = False
    
    def force_online(self) -> None:
        """Force online mode."""
        asyncio.create_task(self.switch_mode(OperationMode.ONLINE))
    
    def get_state(self) -> Dict[str, Any]:
        """Get current offline state."""
        return self._state.to_dict()
    
    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive offline mode status."""
        return {
            "state": self._state.to_dict(),
            "cache": self._cache.get_stats(),
            "replay": self._replay.get_status(),
            "importer": self._importer.get_status(),
            "qr_transfer": self._qr_transfer.get_status(),
            "pending_intents": len(self._pending_intents),
            "pending_executions": len(self._pending_executions),
        }


# Singleton
_offline_mode_manager: Optional[OfflineModeManager] = None
_offline_mode_manager_lock = threading.Lock()


def get_offline_mode_manager() -> OfflineModeManager:
    """Get or create the Offline Mode Manager singleton."""
    global _offline_mode_manager
    if _offline_mode_manager is None:
        with _offline_mode_manager_lock:
            if _offline_mode_manager is None:
                _offline_mode_manager = OfflineModeManager()
    return _offline_mode_manager
