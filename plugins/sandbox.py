"""
Plugin Sandbox.

Provides sandboxed execution environment for plugins with
resource limits and security restrictions.

Version: 1.0.0
"""

from __future__ import annotations

import time
import asyncio
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

from utils.logger import get_logger

logger = get_logger("plugins.sandbox")


class PermissionType(Enum):
    """Types of permissions."""
    NETWORK = "network"
    FILESYSTEM = "filesystem"
    TRADING = "trading"
    WALLET = "wallet"
    SYSTEM = "system"
    DATA_READ = "data_read"
    DATA_WRITE = "data_write"
    NOTIFICATIONS = "notifications"


@dataclass
class ResourceLimits:
    """Resource limits for sandboxed execution."""
    max_memory_mb: int = 256
    max_cpu_percent: float = 25.0
    max_execution_time_seconds: float = 30.0
    max_network_requests_per_minute: int = 60
    max_file_operations_per_minute: int = 100
    max_concurrent_tasks: int = 10


@dataclass
class SandboxContext:
    """Context for sandboxed execution."""
    plugin_id: str
    permissions: List[PermissionType] = field(default_factory=list)
    limits: ResourceLimits = field(default_factory=ResourceLimits)
    
    # Runtime tracking
    start_time: float = field(default_factory=time.time)
    network_requests: int = 0
    file_operations: int = 0
    active_tasks: int = 0
    
    # Violations
    violations: List[Dict[str, Any]] = field(default_factory=list)
    
    def has_permission(self, permission: PermissionType) -> bool:
        return permission in self.permissions
    
    def record_violation(self, violation_type: str, details: str) -> None:
        self.violations.append({
            "type": violation_type,
            "details": details,
            "timestamp": time.time(),
        })
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "permissions": [p.value for p in self.permissions],
            "limits": {
                "max_memory_mb": self.limits.max_memory_mb,
                "max_cpu_percent": self.limits.max_cpu_percent,
                "max_execution_time_seconds": self.limits.max_execution_time_seconds,
            },
            "network_requests": self.network_requests,
            "file_operations": self.file_operations,
            "active_tasks": self.active_tasks,
            "violations": self.violations,
        }


class SandboxedFunction:
    """Wrapper for sandboxed function execution."""
    
    def __init__(self, func: Callable, context: SandboxContext):
        self.func = func
        self.context = context
        self.logger = get_logger(f"plugins.sandbox.{context.plugin_id}")
    
    async def __call__(self, *args, **kwargs) -> Any:
        """Execute function with sandbox restrictions."""
        # Check execution time limit
        elapsed = time.time() - self.context.start_time
        if elapsed > self.context.limits.max_execution_time_seconds:
            self.context.record_violation("timeout", f"Exceeded {self.context.limits.max_execution_time_seconds}s")
            raise TimeoutError("Sandbox execution time exceeded")
        
        # Check concurrent tasks
        if self.context.active_tasks >= self.context.limits.max_concurrent_tasks:
            self.context.record_violation("task_limit", "Too many concurrent tasks")
            raise RuntimeError("Too many concurrent tasks")
        
        self.context.active_tasks += 1
        
        try:
            # Execute with timeout
            result = await asyncio.wait_for(
                self._execute(args, kwargs),
                timeout=self.context.limits.max_execution_time_seconds - elapsed
            )
            return result
        except asyncio.TimeoutError:
            self.context.record_violation("timeout", "Function execution timed out")
            raise
        finally:
            self.context.active_tasks -= 1
    
    async def _execute(self, args, kwargs) -> Any:
        """Execute the wrapped function."""
        if asyncio.iscoroutinefunction(self.func):
            return await self.func(*args, **kwargs)
        else:
            return self.func(*args, **kwargs)


class PluginSandbox:
    """
    Sandboxed execution environment for plugins.
    
    Features:
    - Permission-based access control
    - Resource limits
    - Execution monitoring
    - Violation tracking
    """
    
    def __init__(self):
        self.logger = get_logger("plugins.sandbox")
        
        # Active sandboxes
        self._sandboxes: Dict[str, SandboxContext] = {}
        
        # Default limits
        self._default_limits = ResourceLimits()
        
        # Permission presets
        self._permission_presets: Dict[str, List[PermissionType]] = {
            "minimal": [PermissionType.DATA_READ],
            "standard": [
                PermissionType.DATA_READ,
                PermissionType.DATA_WRITE,
                PermissionType.NOTIFICATIONS,
            ],
            "trading": [
                PermissionType.DATA_READ,
                PermissionType.DATA_WRITE,
                PermissionType.TRADING,
                PermissionType.NOTIFICATIONS,
            ],
            "full": list(PermissionType),
        }
        
        # Blocked operations
        self._blocked_modules = [
            "os.system",
            "subprocess",
            "eval",
            "exec",
            "__import__",
        ]
    
    def create_sandbox(
        self,
        plugin_id: str,
        permissions: Optional[List[PermissionType]] = None,
        limits: Optional[ResourceLimits] = None,
        preset: str = "standard",
    ) -> SandboxContext:
        """Create a sandbox for a plugin."""
        if permissions is None:
            permissions = self._permission_presets.get(preset, [])
        
        context = SandboxContext(
            plugin_id=plugin_id,
            permissions=permissions,
            limits=limits or ResourceLimits(),
        )
        
        self._sandboxes[plugin_id] = context
        self.logger.info(f"Created sandbox for plugin: {plugin_id}")
        
        return context
    
    def get_sandbox(self, plugin_id: str) -> Optional[SandboxContext]:
        """Get sandbox for a plugin."""
        return self._sandboxes.get(plugin_id)
    
    def destroy_sandbox(self, plugin_id: str) -> bool:
        """Destroy a plugin sandbox."""
        if plugin_id in self._sandboxes:
            del self._sandboxes[plugin_id]
            self.logger.info(f"Destroyed sandbox for plugin: {plugin_id}")
            return True
        return False
    
    def check_permission(
        self,
        plugin_id: str,
        permission: PermissionType,
    ) -> bool:
        """Check if plugin has a permission."""
        context = self._sandboxes.get(plugin_id)
        if not context:
            return False
        return context.has_permission(permission)
    
    def grant_permission(
        self,
        plugin_id: str,
        permission: PermissionType,
    ) -> bool:
        """Grant a permission to a plugin."""
        context = self._sandboxes.get(plugin_id)
        if not context:
            return False
        
        if permission not in context.permissions:
            context.permissions.append(permission)
            self.logger.warning(f"Granted {permission.value} to {plugin_id}")
        
        return True
    
    def revoke_permission(
        self,
        plugin_id: str,
        permission: PermissionType,
    ) -> bool:
        """Revoke a permission from a plugin."""
        context = self._sandboxes.get(plugin_id)
        if not context:
            return False
        
        if permission in context.permissions:
            context.permissions.remove(permission)
            self.logger.warning(f"Revoked {permission.value} from {plugin_id}")
        
        return True
    
    def wrap_function(
        self,
        plugin_id: str,
        func: Callable,
    ) -> SandboxedFunction:
        """Wrap a function for sandboxed execution."""
        context = self._sandboxes.get(plugin_id)
        if not context:
            context = self.create_sandbox(plugin_id)
        
        return SandboxedFunction(func, context)
    
    async def execute(
        self,
        plugin_id: str,
        func: Callable,
        *args,
        **kwargs,
    ) -> Any:
        """Execute a function in sandbox."""
        wrapped = self.wrap_function(plugin_id, func)
        return await wrapped(*args, **kwargs)
    
    def record_network_request(self, plugin_id: str) -> bool:
        """Record a network request and check limits."""
        context = self._sandboxes.get(plugin_id)
        if not context:
            return False
        
        if not context.has_permission(PermissionType.NETWORK):
            context.record_violation("permission", "Network access denied")
            return False
        
        context.network_requests += 1
        
        if context.network_requests > context.limits.max_network_requests_per_minute:
            context.record_violation("rate_limit", "Network request limit exceeded")
            return False
        
        return True
    
    def record_file_operation(self, plugin_id: str) -> bool:
        """Record a file operation and check limits."""
        context = self._sandboxes.get(plugin_id)
        if not context:
            return False
        
        if not context.has_permission(PermissionType.FILESYSTEM):
            context.record_violation("permission", "Filesystem access denied")
            return False
        
        context.file_operations += 1
        
        if context.file_operations > context.limits.max_file_operations_per_minute:
            context.record_violation("rate_limit", "File operation limit exceeded")
            return False
        
        return True
    
    def get_violations(self, plugin_id: str) -> List[Dict[str, Any]]:
        """Get violations for a plugin."""
        context = self._sandboxes.get(plugin_id)
        if not context:
            return []
        return context.violations
    
    def clear_violations(self, plugin_id: str) -> None:
        """Clear violations for a plugin."""
        context = self._sandboxes.get(plugin_id)
        if context:
            context.violations.clear()
    
    def reset_counters(self, plugin_id: str) -> None:
        """Reset rate limit counters for a plugin."""
        context = self._sandboxes.get(plugin_id)
        if context:
            context.network_requests = 0
            context.file_operations = 0
            context.start_time = time.time()
    
    def get_status(self) -> Dict[str, Any]:
        """Get sandbox manager status."""
        return {
            "active_sandboxes": len(self._sandboxes),
            "permission_presets": list(self._permission_presets.keys()),
            "sandboxes": {k: v.to_dict() for k, v in self._sandboxes.items()},
        }


# Singleton
_plugin_sandbox: Optional[PluginSandbox] = None


def get_plugin_sandbox() -> PluginSandbox:
    """Get or create the Plugin Sandbox singleton."""
    global _plugin_sandbox
    if _plugin_sandbox is None:
        _plugin_sandbox = PluginSandbox()
    return _plugin_sandbox
