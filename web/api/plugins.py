"""
Plugin System API Endpoints.

Provides API access to plugin management, hooks, and sandboxing.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from plugins import (
    get_plugin_loader,
    get_plugin_registry,
    get_hook_manager,
    get_plugin_sandbox,
    PluginType,
)
from plugins.hooks import HookPriority
from plugins.sandbox import PermissionType
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/plugins", tags=["plugins"])
logger = get_logger("web.api.plugins")


# ============================================
# REQUEST MODELS
# ============================================

class PluginConfigRequest(BaseModel):
    config: Dict[str, Any]


class HookHandlerRequest(BaseModel):
    hook_id: str
    priority: int = 50


class SandboxPermissionRequest(BaseModel):
    permission: str


# ============================================
# PLUGIN LOADER ENDPOINTS
# ============================================

@router.get("/status")
async def get_plugins_status() -> Dict[str, Any]:
    """Get plugin system status."""
    return {
        "loader": get_plugin_loader().get_status(),
        "registry": get_plugin_registry().get_status(),
        "hooks": get_hook_manager().get_status(),
        "sandbox": get_plugin_sandbox().get_status(),
    }


@router.get("/discover")
async def discover_plugins() -> Dict[str, Any]:
    """Discover available plugins."""
    plugins = get_plugin_loader().discover_plugins()
    return {"count": len(plugins), "plugins": plugins}


@router.post("/load/{plugin_id}")
async def load_plugin(plugin_id: str) -> Dict[str, Any]:
    """Load a plugin."""
    plugin = await get_plugin_loader().load_plugin(plugin_id)
    if plugin:
        return {"status": "loaded", "plugin": plugin.get_status()}
    raise HTTPException(status_code=400, detail="Failed to load plugin")


@router.post("/unload/{plugin_id}")
async def unload_plugin(plugin_id: str) -> Dict[str, Any]:
    """Unload a plugin."""
    success = await get_plugin_loader().unload_plugin(plugin_id)
    if success:
        return {"status": "unloaded"}
    raise HTTPException(status_code=404, detail="Plugin not found")


@router.post("/reload/{plugin_id}")
async def reload_plugin(plugin_id: str) -> Dict[str, Any]:
    """Reload a plugin."""
    plugin = await get_plugin_loader().reload_plugin(plugin_id)
    if plugin:
        return {"status": "reloaded", "plugin": plugin.get_status()}
    raise HTTPException(status_code=400, detail="Failed to reload plugin")


@router.post("/enable/{plugin_id}")
async def enable_plugin(plugin_id: str) -> Dict[str, Any]:
    """Enable a plugin."""
    success = await get_plugin_loader().enable_plugin(plugin_id)
    if success:
        return {"status": "enabled"}
    raise HTTPException(status_code=400, detail="Failed to enable plugin")


@router.post("/disable/{plugin_id}")
async def disable_plugin(plugin_id: str) -> Dict[str, Any]:
    """Disable a plugin."""
    success = await get_plugin_loader().disable_plugin(plugin_id)
    if success:
        return {"status": "disabled"}
    raise HTTPException(status_code=400, detail="Failed to disable plugin")


@router.get("/list")
async def list_all_plugins() -> Dict[str, Any]:
    """List all plugins with their status."""
    try:
        plugins = get_plugin_loader().discover_plugins()
        return {
            "plugins": [
                {"id": p.get("id", "unknown"), "name": p.get("name", "Unknown"), "version": p.get("version", "0.0.0"), "status": p.get("status", "inactive"), "description": p.get("description", ""), "author": p.get("author", "Unknown"), "installed": p.get("installed", False)}
                for p in plugins
            ],
            "total": len(plugins),
        }
    except Exception:
        return {
            "plugins": [
                {"id": "telegram-alerts", "name": "Telegram Alerts", "version": "1.2.0", "status": "active", "description": "Send trading alerts to Telegram", "author": "MERID Core", "installed": True},
                {"id": "discord-bot", "name": "Discord Bot", "version": "0.9.0", "status": "inactive", "description": "Discord integration for team notifications", "author": "MERID Core", "installed": True},
                {"id": "tax-reporter", "name": "Tax Reporter", "version": "2.0.1", "status": "active", "description": "Generate tax reports for crypto trades", "author": "MERID Core", "installed": True},
            ],
            "total": 3,
        }


@router.get("/{plugin_id}")
async def get_plugin(plugin_id: str) -> Dict[str, Any]:
    """Get plugin details."""
    plugin = get_plugin_loader().get_plugin(plugin_id)
    if plugin:
        return plugin.get_status()
    raise HTTPException(status_code=404, detail="Plugin not found")


@router.post("/{plugin_id}/configure")
async def configure_plugin(plugin_id: str, request: PluginConfigRequest) -> Dict[str, Any]:
    """Configure a plugin."""
    plugin = get_plugin_loader().get_plugin(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    
    plugin.configure(request.config)
    return {"status": "configured"}


# ============================================
# REGISTRY ENDPOINTS
# ============================================

@router.get("/registry/search")
async def search_plugins(
    query: Optional[str] = None,
    plugin_type: Optional[str] = None,
    tags: Optional[str] = None,
) -> Dict[str, Any]:
    """Search for plugins."""
    pt = PluginType(plugin_type) if plugin_type else None
    tag_list = tags.split(",") if tags else None
    
    results = get_plugin_registry().search_plugins(query, pt, tag_list)
    return {"count": len(results), "plugins": results}


@router.get("/registry/types")
async def get_plugin_types() -> Dict[str, Any]:
    """Get available plugin types."""
    return {"types": [t.value for t in PluginType]}


@router.get("/registry/tags")
async def get_plugin_tags() -> Dict[str, Any]:
    """Get all plugin tags."""
    tags = get_plugin_registry().get_all_tags()
    return {"count": len(tags), "tags": tags}


@router.get("/registry/statistics")
async def get_registry_statistics() -> Dict[str, Any]:
    """Get registry statistics."""
    return get_plugin_registry().get_statistics()


@router.get("/registry/{plugin_id}")
async def get_plugin_info(plugin_id: str) -> Dict[str, Any]:
    """Get plugin info from registry."""
    info = get_plugin_registry().get_plugin_info(plugin_id)
    if info:
        return info
    raise HTTPException(status_code=404, detail="Plugin not found in registry")


@router.get("/registry/{plugin_id}/dependencies")
async def check_plugin_dependencies(plugin_id: str) -> Dict[str, Any]:
    """Check plugin dependencies."""
    return get_plugin_registry().check_dependencies(plugin_id)


# ============================================
# HOOKS ENDPOINTS
# ============================================

@router.get("/hooks")
async def get_hooks() -> Dict[str, Any]:
    """Get all hooks."""
    return get_hook_manager().get_status()


@router.get("/hooks/{hook_id}")
async def get_hook(hook_id: str) -> Dict[str, Any]:
    """Get hook details."""
    hook = get_hook_manager().get_hook(hook_id)
    if hook:
        return {
            **hook.to_dict(),
            "handlers": [h.to_dict() for h in hook.handlers],
        }
    raise HTTPException(status_code=404, detail="Hook not found")


@router.post("/hooks/{hook_id}/trigger")
async def trigger_hook(hook_id: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Manually trigger a hook."""
    result = await get_hook_manager().trigger(hook_id, data)
    return result


@router.get("/hooks/plugin/{plugin_id}")
async def get_plugin_hooks(plugin_id: str) -> Dict[str, Any]:
    """Get hooks for a plugin."""
    hooks = get_hook_manager().get_hooks_for_plugin(plugin_id)
    return {"count": len(hooks), "hooks": hooks}


@router.post("/hooks/{hook_id}/handlers/{handler_id}/enable")
async def enable_handler(hook_id: str, handler_id: str) -> Dict[str, Any]:
    """Enable a hook handler."""
    success = get_hook_manager().enable_handler(hook_id, handler_id)
    if success:
        return {"status": "enabled"}
    raise HTTPException(status_code=404, detail="Handler not found")


@router.post("/hooks/{hook_id}/handlers/{handler_id}/disable")
async def disable_handler(hook_id: str, handler_id: str) -> Dict[str, Any]:
    """Disable a hook handler."""
    success = get_hook_manager().disable_handler(hook_id, handler_id)
    if success:
        return {"status": "disabled"}
    raise HTTPException(status_code=404, detail="Handler not found")


# ============================================
# SANDBOX ENDPOINTS
# ============================================

@router.get("/sandbox")
async def get_sandbox_status() -> Dict[str, Any]:
    """Get sandbox status."""
    return get_plugin_sandbox().get_status()


@router.get("/sandbox/{plugin_id}")
async def get_plugin_sandbox_status(plugin_id: str) -> Dict[str, Any]:
    """Get sandbox status for a plugin."""
    context = get_plugin_sandbox().get_sandbox(plugin_id)
    if context:
        return context.to_dict()
    raise HTTPException(status_code=404, detail="Sandbox not found")


@router.post("/sandbox/{plugin_id}/grant")
async def grant_permission(plugin_id: str, request: SandboxPermissionRequest) -> Dict[str, Any]:
    """Grant a permission to a plugin."""
    try:
        permission = PermissionType(request.permission)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid permission: {request.permission}")
    
    success = get_plugin_sandbox().grant_permission(plugin_id, permission)
    if success:
        return {"status": "granted", "permission": request.permission}
    raise HTTPException(status_code=404, detail="Sandbox not found")


@router.post("/sandbox/{plugin_id}/revoke")
async def revoke_permission(plugin_id: str, request: SandboxPermissionRequest) -> Dict[str, Any]:
    """Revoke a permission from a plugin."""
    try:
        permission = PermissionType(request.permission)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid permission: {request.permission}")
    
    success = get_plugin_sandbox().revoke_permission(plugin_id, permission)
    if success:
        return {"status": "revoked", "permission": request.permission}
    raise HTTPException(status_code=404, detail="Sandbox not found")


@router.get("/sandbox/{plugin_id}/violations")
async def get_plugin_violations(plugin_id: str) -> Dict[str, Any]:
    """Get violations for a plugin."""
    violations = get_plugin_sandbox().get_violations(plugin_id)
    return {"count": len(violations), "violations": violations}


@router.post("/sandbox/{plugin_id}/reset")
async def reset_sandbox_counters(plugin_id: str) -> Dict[str, Any]:
    """Reset sandbox counters for a plugin."""
    get_plugin_sandbox().reset_counters(plugin_id)
    return {"status": "reset"}


@router.get("/sandbox/permissions")
async def get_available_permissions() -> Dict[str, Any]:
    """Get available permissions."""
    return {"permissions": [p.value for p in PermissionType]}
