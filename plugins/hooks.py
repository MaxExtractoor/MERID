"""
Hook System.

Provides extensibility hooks for plugins to integrate with core functionality.

Version: 1.0.0
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Any, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum

from utils.logger import get_logger

logger = get_logger("plugins.hooks")


class HookPriority(Enum):
    """Priority levels for hook handlers."""
    LOWEST = 0
    LOW = 25
    NORMAL = 50
    HIGH = 75
    HIGHEST = 100


@dataclass
class HookHandler:
    """A registered hook handler."""
    handler_id: str
    plugin_id: str
    callback: Callable[..., Awaitable[Any]]
    priority: HookPriority = HookPriority.NORMAL
    enabled: bool = True
    
    # Statistics
    invocation_count: int = 0
    error_count: int = 0
    total_time_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "handler_id": self.handler_id,
            "plugin_id": self.plugin_id,
            "priority": self.priority.value,
            "enabled": self.enabled,
            "invocation_count": self.invocation_count,
            "error_count": self.error_count,
            "avg_time_ms": self.total_time_ms / max(self.invocation_count, 1),
        }


@dataclass
class Hook:
    """A hook definition."""
    hook_id: str
    name: str
    description: str = ""
    
    # Handlers
    handlers: List[HookHandler] = field(default_factory=list)
    
    # Configuration
    allow_modification: bool = True  # Can handlers modify data
    stop_on_error: bool = False  # Stop execution on handler error
    
    # Statistics
    trigger_count: int = 0
    last_triggered: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "hook_id": self.hook_id,
            "name": self.name,
            "description": self.description,
            "handler_count": len(self.handlers),
            "allow_modification": self.allow_modification,
            "trigger_count": self.trigger_count,
            "last_triggered": self.last_triggered,
        }


class HookManager:
    """
    Manages hooks for plugin extensibility.
    
    Features:
    - Hook registration and discovery
    - Priority-based handler execution
    - Data modification support
    - Error handling
    """
    
    def __init__(self):
        self.logger = get_logger("plugins.hooks")
        
        # Registered hooks
        self._hooks: Dict[str, Hook] = {}
        
        # Initialize core hooks
        self._init_core_hooks()
    
    def _init_core_hooks(self) -> None:
        """Initialize core system hooks."""
        core_hooks = [
            # Trading hooks
            Hook("pre_order", "Pre-Order", "Called before an order is placed"),
            Hook("post_order", "Post-Order", "Called after an order is placed"),
            Hook("pre_execution", "Pre-Execution", "Called before trade execution"),
            Hook("post_execution", "Post-Execution", "Called after trade execution"),
            
            # Data hooks
            Hook("price_update", "Price Update", "Called when prices are updated"),
            Hook("market_data", "Market Data", "Called when market data is received"),
            
            # Agent hooks
            Hook("agent_decision", "Agent Decision", "Called when an agent makes a decision"),
            Hook("consensus_vote", "Consensus Vote", "Called during consensus voting"),
            
            # System hooks
            Hook("system_startup", "System Startup", "Called when system starts"),
            Hook("system_shutdown", "System Shutdown", "Called when system shuts down"),
            Hook("config_change", "Config Change", "Called when configuration changes"),
            
            # Risk hooks
            Hook("risk_check", "Risk Check", "Called during risk evaluation"),
            Hook("position_update", "Position Update", "Called when positions change"),
            
            # Notification hooks
            Hook("notification_send", "Notification Send", "Called before sending notification"),
            Hook("alert_trigger", "Alert Trigger", "Called when an alert triggers"),
        ]
        
        for hook in core_hooks:
            self._hooks[hook.hook_id] = hook
    
    def register_hook(
        self,
        hook_id: str,
        name: str,
        description: str = "",
        allow_modification: bool = True,
    ) -> Hook:
        """Register a new hook."""
        if hook_id in self._hooks:
            return self._hooks[hook_id]
        
        hook = Hook(
            hook_id=hook_id,
            name=name,
            description=description,
            allow_modification=allow_modification,
        )
        
        self._hooks[hook_id] = hook
        self.logger.info(f"Registered hook: {hook_id}")
        
        return hook
    
    def add_handler(
        self,
        hook_id: str,
        plugin_id: str,
        callback: Callable[..., Awaitable[Any]],
        priority: HookPriority = HookPriority.NORMAL,
    ) -> Optional[str]:
        """Add a handler to a hook."""
        hook = self._hooks.get(hook_id)
        if not hook:
            self.logger.error(f"Hook not found: {hook_id}")
            return None
        
        import uuid
        handler_id = f"handler_{uuid.uuid4().hex[:8]}"
        
        handler = HookHandler(
            handler_id=handler_id,
            plugin_id=plugin_id,
            callback=callback,
            priority=priority,
        )
        
        # Insert in priority order
        hook.handlers.append(handler)
        hook.handlers.sort(key=lambda h: h.priority.value, reverse=True)
        
        self.logger.info(f"Added handler {handler_id} to hook {hook_id}")
        return handler_id
    
    def remove_handler(self, hook_id: str, handler_id: str) -> bool:
        """Remove a handler from a hook."""
        hook = self._hooks.get(hook_id)
        if not hook:
            return False
        
        for i, handler in enumerate(hook.handlers):
            if handler.handler_id == handler_id:
                hook.handlers.pop(i)
                self.logger.info(f"Removed handler {handler_id} from hook {hook_id}")
                return True
        
        return False
    
    def remove_plugin_handlers(self, plugin_id: str) -> int:
        """Remove all handlers for a plugin."""
        removed = 0
        
        for hook in self._hooks.values():
            hook.handlers = [h for h in hook.handlers if h.plugin_id != plugin_id]
            removed += 1
        
        return removed
    
    async def trigger(
        self,
        hook_id: str,
        data: Any = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Trigger a hook and execute all handlers."""
        hook = self._hooks.get(hook_id)
        if not hook:
            return {"success": False, "error": "Hook not found"}
        
        hook.trigger_count += 1
        hook.last_triggered = time.time()
        
        results = []
        modified_data = data
        
        for handler in hook.handlers:
            if not handler.enabled:
                continue
            
            start_time = time.time()
            
            try:
                result = await handler.callback(
                    modified_data,
                    context or {},
                    hook_id,
                )
                
                handler.invocation_count += 1
                handler.total_time_ms += (time.time() - start_time) * 1000
                
                # Allow data modification
                if hook.allow_modification and result is not None:
                    modified_data = result
                
                results.append({
                    "handler_id": handler.handler_id,
                    "plugin_id": handler.plugin_id,
                    "success": True,
                    "result": result,
                })
                
            except Exception as e:
                handler.error_count += 1
                handler.total_time_ms += (time.time() - start_time) * 1000
                
                self.logger.error(f"Handler error in {hook_id}: {e}")
                
                results.append({
                    "handler_id": handler.handler_id,
                    "plugin_id": handler.plugin_id,
                    "success": False,
                    "error": str(e),
                })
                
                if hook.stop_on_error:
                    break
        
        return {
            "success": True,
            "hook_id": hook_id,
            "handlers_executed": len(results),
            "data": modified_data,
            "results": results,
        }
    
    def get_hook(self, hook_id: str) -> Optional[Hook]:
        """Get a hook by ID."""
        return self._hooks.get(hook_id)
    
    def get_hooks_for_plugin(self, plugin_id: str) -> List[Dict[str, Any]]:
        """Get all hooks a plugin has handlers for."""
        hooks = []
        
        for hook in self._hooks.values():
            plugin_handlers = [h for h in hook.handlers if h.plugin_id == plugin_id]
            if plugin_handlers:
                hooks.append({
                    "hook_id": hook.hook_id,
                    "name": hook.name,
                    "handlers": [h.to_dict() for h in plugin_handlers],
                })
        
        return hooks
    
    def enable_handler(self, hook_id: str, handler_id: str) -> bool:
        """Enable a handler."""
        hook = self._hooks.get(hook_id)
        if not hook:
            return False
        
        for handler in hook.handlers:
            if handler.handler_id == handler_id:
                handler.enabled = True
                return True
        
        return False
    
    def disable_handler(self, hook_id: str, handler_id: str) -> bool:
        """Disable a handler."""
        hook = self._hooks.get(hook_id)
        if not hook:
            return False
        
        for handler in hook.handlers:
            if handler.handler_id == handler_id:
                handler.enabled = False
                return True
        
        return False
    
    def get_status(self) -> Dict[str, Any]:
        """Get hook manager status."""
        total_handlers = sum(len(h.handlers) for h in self._hooks.values())
        
        return {
            "total_hooks": len(self._hooks),
            "total_handlers": total_handlers,
            "hooks": {k: v.to_dict() for k, v in self._hooks.items()},
        }


# Singleton
_hook_manager: Optional[HookManager] = None


def get_hook_manager() -> HookManager:
    """Get or create the Hook Manager singleton."""
    global _hook_manager
    if _hook_manager is None:
        _hook_manager = HookManager()
    return _hook_manager
