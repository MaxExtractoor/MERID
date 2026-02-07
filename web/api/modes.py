"""
Mode Management API Endpoints
REST API for managing trading modes, feature gates, and debug configuration
"""

from fastapi import APIRouter, HTTPException, Depends, Query, Body
from typing import Dict, Any, List, Set, Optional
from pydantic import BaseModel, Field
import logging

from core.mode_manager import get_mode_manager, TradingMode, FeatureCategory, DebugMode, FeatureGate, ModeConfig

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/modes", tags=["modes"])

# Pydantic models for API requests/responses
class ModeChangeRequest(BaseModel):
    mode: str
    reason: Optional[str] = None

class FeatureGateRequest(BaseModel):
    name: str
    category: str
    enabled: bool = True
    required_modes: List[str] = []
    blocked_modes: List[str] = []
    required_permissions: List[str] = []
    metadata: Dict[str, Any] = {}

class FeatureGateUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    required_modes: Optional[List[str]] = None
    blocked_modes: Optional[List[str]] = None
    required_permissions: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None

class DebugModeRequest(BaseModel):
    debug_mode: str

def get_current_user_permissions() -> Set[str]:
    """Get current user permissions (mock implementation)"""
    # In a real implementation, this would extract from JWT/auth token
    return {"user"}  # Default permissions

@router.get("/status")
async def get_mode_status():
    """Get current system mode status"""
    try:
        mode_manager = get_mode_manager()
        status = mode_manager.get_mode_status()
        return {
            "status": "success",
            "data": status
        }
    except Exception as e:
        logger.error(f"Failed to get mode status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get mode status")

@router.get("/current")
async def get_current_mode():
    """Get current system mode"""
    try:
        mode_manager = get_mode_manager()
        return {
            "status": "success",
            "data": {
                "current_mode": mode_manager.system_mode.current_mode.value,
                "description": mode_manager.mode_configs[mode_manager.system_mode.current_mode].description,
                "debug_mode": mode_manager.debug_mode.value,
                "is_spectator": mode_manager.is_spectator_mode(),
                "is_maintenance": mode_manager.is_maintenance_mode(),
                "can_trade": mode_manager.can_execute_trading(),
                "can_paper_trade": mode_manager.can_execute_paper_trading()
            }
        }
    except Exception as e:
        logger.error(f"Failed to get current mode: {e}")
        raise HTTPException(status_code=500, detail="Failed to get current mode")

@router.post("/change")
async def change_mode(request: ModeChangeRequest, permissions: Set[str] = Depends(get_current_user_permissions)):
    """Change system mode"""
    try:
        mode_manager = get_mode_manager()
        
        # Validate mode
        try:
            new_mode = TradingMode(request.mode)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid mode: {request.mode}")
        
        # Get user identifier (mock implementation)
        user_id = "user"  # In real implementation, extract from auth token
        
        # Change mode
        success = mode_manager.change_mode(new_mode, user_id, request.reason)
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to change mode")
        
        return {
            "status": "success",
            "message": f"Mode changed to {request.mode}",
            "data": {
                "previous_mode": mode_manager.system_mode.previous_mode.value if mode_manager.system_mode.previous_mode else None,
                "current_mode": mode_manager.system_mode.current_mode.value,
                "changed_at": mode_manager.system_mode.mode_changed_at.isoformat(),
                "changed_by": mode_manager.system_mode.mode_changed_by,
                "reason": mode_manager.system_mode.mode_change_reason
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to change mode: {e}")
        raise HTTPException(status_code=500, detail="Failed to change mode")

@router.get("/available")
async def get_available_modes():
    """Get list of available modes with descriptions"""
    try:
        mode_manager = get_mode_manager()
        
        modes = []
        for mode, config in mode_manager.mode_configs.items():
            modes.append({
                "mode": mode.value,
                "description": config.description,
                "permissions": list(config.permissions),
                "enabled_features": list(config.enabled_features),
                "disabled_features": list(config.disabled_features),
                "limits": config.limits
            })
        
        return {
            "status": "success",
            "data": {
                "modes": modes,
                "current_mode": mode_manager.system_mode.current_mode.value
            }
        }
    except Exception as e:
        logger.error(f"Failed to get available modes: {e}")
        raise HTTPException(status_code=500, detail="Failed to get available modes")

@router.get("/features")
async def get_features(permissions: Set[str] = Depends(get_current_user_permissions)):
    """Get all features and their status"""
    try:
        mode_manager = get_mode_manager()
        
        features = []
        for name, gate in mode_manager.feature_gates.items():
            features.append({
                "name": name,
                "category": gate.category.value,
                "enabled": gate.enabled,
                "is_available": mode_manager.is_feature_enabled(name, permissions),
                "required_modes": [mode.value for mode in gate.required_modes],
                "blocked_modes": [mode.value for mode in gate.blocked_modes],
                "required_permissions": list(gate.required_permissions),
                "metadata": gate.metadata,
                "last_modified": gate.last_modified.isoformat()
            })
        
        return {
            "status": "success",
            "data": {
                "features": features,
                "enabled_features": list(mode_manager.get_enabled_features(permissions)),
                "current_mode": mode_manager.system_mode.current_mode.value
            }
        }
    except Exception as e:
        logger.error(f"Failed to get features: {e}")
        raise HTTPException(status_code=500, detail="Failed to get features")

@router.get("/features/{feature_name}")
async def get_feature_status(feature_name: str, permissions: Set[str] = Depends(get_current_user_permissions)):
    """Get status of a specific feature"""
    try:
        mode_manager = get_mode_manager()
        
        if feature_name not in mode_manager.feature_gates:
            raise HTTPException(status_code=404, detail=f"Feature '{feature_name}' not found")
        
        gate = mode_manager.feature_gates[feature_name]
        
        return {
            "status": "success",
            "data": {
                "name": gate.name,
                "category": gate.category.value,
                "enabled": gate.enabled,
                "is_available": mode_manager.is_feature_enabled(feature_name, permissions),
                "required_modes": [mode.value for mode in gate.required_modes],
                "blocked_modes": [mode.value for mode in gate.blocked_modes],
                "required_permissions": list(gate.required_permissions),
                "metadata": gate.metadata,
                "last_modified": gate.last_modified.isoformat()
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get feature status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get feature status")

@router.post("/features")
async def create_feature_gate(request: FeatureGateRequest, permissions: Set[str] = Depends(get_current_user_permissions)):
    """Create a new feature gate"""
    try:
        mode_manager = get_mode_manager()
        
        # Check permissions
        if "admin" not in permissions:
            raise HTTPException(status_code=403, detail="Admin permissions required")
        
        # Validate category
        try:
            category = FeatureCategory(request.category)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid category: {request.category}")
        
        # Validate modes
        required_modes = set()
        for mode_str in request.required_modes:
            try:
                required_modes.add(TradingMode(mode_str))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid required mode: {mode_str}")
        
        blocked_modes = set()
        for mode_str in request.blocked_modes:
            try:
                blocked_modes.add(TradingMode(mode_str))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid blocked mode: {mode_str}")
        
        # Create feature gate
        feature = FeatureGate(
            name=request.name,
            category=category,
            enabled=request.enabled,
            required_modes=required_modes,
            blocked_modes=blocked_modes,
            required_permissions=set(request.required_permissions),
            metadata=request.metadata
        )
        
        success = mode_manager.add_feature_gate(feature)
        
        if not success:
            raise HTTPException(status_code=400, detail="Feature gate already exists")
        
        return {
            "status": "success",
            "message": f"Feature gate '{request.name}' created successfully",
            "data": {
                "name": feature.name,
                "category": feature.category.value,
                "enabled": feature.enabled,
                "required_modes": [mode.value for mode in feature.required_modes],
                "blocked_modes": [mode.value for mode in feature.blocked_modes],
                "required_permissions": list(feature.required_permissions),
                "metadata": feature.metadata
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create feature gate: {e}")
        raise HTTPException(status_code=500, detail="Failed to create feature gate")

@router.put("/features/{feature_name}")
async def update_feature_gate(
    feature_name: str, 
    request: FeatureGateUpdateRequest,
    permissions: Set[str] = Depends(get_current_user_permissions)
):
    """Update an existing feature gate"""
    try:
        mode_manager = get_mode_manager()
        
        # Check permissions
        if "admin" not in permissions:
            raise HTTPException(status_code=403, detail="Admin permissions required")
        
        # Build update kwargs
        update_kwargs = {}
        
        if request.enabled is not None:
            update_kwargs["enabled"] = request.enabled
        
        if request.required_modes is not None:
            required_modes = set()
            for mode_str in request.required_modes:
                try:
                    required_modes.add(TradingMode(mode_str))
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"Invalid required mode: {mode_str}")
            update_kwargs["required_modes"] = required_modes
        
        if request.blocked_modes is not None:
            blocked_modes = set()
            for mode_str in request.blocked_modes:
                try:
                    blocked_modes.add(TradingMode(mode_str))
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"Invalid blocked mode: {mode_str}")
            update_kwargs["blocked_modes"] = blocked_modes
        
        if request.required_permissions is not None:
            update_kwargs["required_permissions"] = set(request.required_permissions)
        
        if request.metadata is not None:
            update_kwargs["metadata"] = request.metadata
        
        # Update feature gate
        success = mode_manager.update_feature_gate(feature_name, **update_kwargs)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Feature '{feature_name}' not found")
        
        return {
            "status": "success",
            "message": f"Feature gate '{feature_name}' updated successfully",
            "data": {
                "name": feature_name,
                "updated_fields": list(update_kwargs.keys())
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update feature gate: {e}")
        raise HTTPException(status_code=500, detail="Failed to update feature gate")

@router.delete("/features/{feature_name}")
async def delete_feature_gate(feature_name: str, permissions: Set[str] = Depends(get_current_user_permissions)):
    """Delete a feature gate"""
    try:
        mode_manager = get_mode_manager()
        
        # Check permissions
        if "admin" not in permissions:
            raise HTTPException(status_code=403, detail="Admin permissions required")
        
        success = mode_manager.remove_feature_gate(feature_name)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Feature '{feature_name}' not found")
        
        return {
            "status": "success",
            "message": f"Feature gate '{feature_name}' deleted successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete feature gate: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete feature gate")

@router.get("/limits")
async def get_mode_limits():
    """Get current mode limits"""
    try:
        mode_manager = get_mode_manager()
        
        limits = mode_manager.get_mode_limits()
        
        return {
            "status": "success",
            "data": {
                "current_mode": mode_manager.system_mode.current_mode.value,
                "limits": limits
            }
        }
    except Exception as e:
        logger.error(f"Failed to get mode limits: {e}")
        raise HTTPException(status_code=500, detail="Failed to get mode limits")

@router.get("/debug")
async def get_debug_mode():
    """Get current debug mode"""
    try:
        mode_manager = get_mode_manager()
        
        return {
            "status": "success",
            "data": {
                "debug_mode": mode_manager.debug_mode.value,
                "available_modes": [mode.value for mode in DebugMode]
            }
        }
    except Exception as e:
        logger.error(f"Failed to get debug mode: {e}")
        raise HTTPException(status_code=500, detail="Failed to get debug mode")

@router.post("/debug")
async def set_debug_mode(request: DebugModeRequest, permissions: Set[str] = Depends(get_current_user_permissions)):
    """Set debug mode"""
    try:
        mode_manager = get_mode_manager()
        
        # Check permissions
        if "admin" not in permissions and "debug" not in permissions:
            raise HTTPException(status_code=403, detail="Admin or debug permissions required")
        
        # Validate debug mode
        try:
            debug_mode = DebugMode(request.debug_mode)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid debug mode: {request.debug_mode}")
        
        success = mode_manager.set_debug_mode(debug_mode)
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to set debug mode")
        
        return {
            "status": "success",
            "message": f"Debug mode set to {request.debug_mode}",
            "data": {
                "debug_mode": mode_manager.debug_mode.value
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set debug mode: {e}")
        raise HTTPException(status_code=500, detail="Failed to set debug mode")

@router.get("/configuration")
async def export_configuration(permissions: Set[str] = Depends(get_current_user_permissions)):
    """Export current configuration"""
    try:
        mode_manager = get_mode_manager()
        
        # Check permissions
        if "admin" not in permissions:
            raise HTTPException(status_code=403, detail="Admin permissions required")
        
        config = mode_manager.export_configuration()
        
        return {
            "status": "success",
            "data": config
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to export configuration: {e}")
        raise HTTPException(status_code=500, detail="Failed to export configuration")

@router.post("/configuration")
async def import_configuration(
    config: Dict[str, Any],
    permissions: Set[str] = Depends(get_current_user_permissions)
):
    """Import configuration"""
    try:
        mode_manager = get_mode_manager()
        
        # Check permissions
        if "admin" not in permissions:
            raise HTTPException(status_code=403, detail="Admin permissions required")
        
        success = mode_manager.import_configuration(config)
        
        if not success:
            raise HTTPException(status_code=400, detail="Failed to import configuration")
        
        return {
            "status": "success",
            "message": "Configuration imported successfully",
            "data": {
                "current_mode": mode_manager.system_mode.current_mode.value,
                "debug_mode": mode_manager.debug_mode.value,
                "feature_gates_count": len(mode_manager.feature_gates),
                "mode_configs_count": len(mode_manager.mode_configs)
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to import configuration: {e}")
        raise HTTPException(status_code=500, detail="Failed to import configuration")

@router.get("/check-feature/{feature_name}")
async def check_feature_availability(feature_name: str, permissions: Set[str] = Depends(get_current_user_permissions)):
    """Check if a feature is available for the current mode and user"""
    try:
        mode_manager = get_mode_manager()
        
        is_available = mode_manager.is_feature_enabled(feature_name, permissions)
        
        if feature_name not in mode_manager.feature_gates:
            return {
                "status": "warning",
                "message": f"Feature '{feature_name}' not found in feature gates",
                "data": {
                    "feature_name": feature_name,
                    "available": False,
                    "reason": "Feature not defined"
                }
            }
        
        gate = mode_manager.feature_gates[feature_name]
        
        return {
            "status": "success",
            "data": {
                "feature_name": feature_name,
                "available": is_available,
                "current_mode": mode_manager.system_mode.current_mode.value,
                "user_permissions": list(permissions),
                "feature_enabled": gate.enabled,
                "required_modes": [mode.value for mode in gate.required_modes],
                "blocked_modes": [mode.value for mode in gate.blocked_modes],
                "required_permissions": list(gate.required_permissions),
                "reason": _get_feature_unavailability_reason(mode_manager, feature_name, permissions) if not is_available else "Available"
            }
        }
    except Exception as e:
        logger.error(f"Failed to check feature availability: {e}")
        raise HTTPException(status_code=500, detail="Failed to check feature availability")

def _get_feature_unavailability_reason(mode_manager, feature_name: str, permissions: Set[str]) -> str:
    """Get reason why feature is not available"""
    gate = mode_manager.feature_gates[feature_name]
    current_mode = mode_manager.system_mode.current_mode
    
    # Check if feature is enabled
    if not gate.enabled:
        return "Feature is disabled"
    
    # Check mode requirements
    if gate.required_modes and current_mode not in gate.required_modes:
        return f"Requires mode: {', '.join([mode.value for mode in gate.required_modes])}"
    
    # Check mode blocks
    if gate.blocked_modes and current_mode in gate.blocked_modes:
        return f"Blocked in mode: {current_mode.value}"
    
    # Check permissions
    if gate.required_permissions and not gate.required_permissions.intersection(permissions):
        return f"Requires permissions: {', '.join(gate.required_permissions)}"
    
    # Check mode-specific configuration
    mode_config = mode_manager.mode_configs.get(current_mode)
    if mode_config:
        if feature_name in mode_config.disabled_features:
            return "Disabled in current mode configuration"
        if feature_name not in mode_config.enabled_features and mode_config.enabled_features:
            return "Not enabled in current mode configuration"
    
    return "Unknown reason"
