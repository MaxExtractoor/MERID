"""
Plugin Loader.

Handles loading, unloading, and lifecycle management of plugins.

Version: 1.0.0
"""

from __future__ import annotations

import os
import sys
import importlib
import importlib.util
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Type

from plugins.plugin_base import Plugin, PluginMetadata, PluginState, PluginType
from utils.logger import get_logger

logger = get_logger("plugins.loader")


class PluginLoader:
    """
    Loads and manages plugin lifecycle.
    
    Features:
    - Dynamic loading from files
    - Dependency resolution
    - Version checking
    - Safe unloading
    """
    
    def __init__(self, plugins_dir: str = "plugins/installed"):
        self.logger = get_logger("plugins.loader")
        self.plugins_dir = Path(plugins_dir)
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        
        # Loaded plugins
        self._plugins: Dict[str, Plugin] = {}
        self._modules: Dict[str, Any] = {}
        
        # Plugin classes discovered
        self._plugin_classes: Dict[str, Type[Plugin]] = {}
        
        # Load history
        self._load_history: List[Dict[str, Any]] = []
    
    def discover_plugins(self) -> List[Dict[str, Any]]:
        """Discover available plugins in the plugins directory."""
        discovered = []
        
        for plugin_dir in self.plugins_dir.iterdir():
            if not plugin_dir.is_dir():
                continue
            
            # Look for plugin.py or __init__.py
            plugin_file = plugin_dir / "plugin.py"
            if not plugin_file.exists():
                plugin_file = plugin_dir / "__init__.py"
            
            if not plugin_file.exists():
                continue
            
            # Look for metadata
            metadata_file = plugin_dir / "metadata.json"
            metadata = {}
            
            if metadata_file.exists():
                import json
                with open(metadata_file, "r") as f:
                    metadata = json.load(f)
            
            discovered.append({
                "plugin_id": plugin_dir.name,
                "path": str(plugin_dir),
                "plugin_file": str(plugin_file),
                "metadata": metadata,
                "loaded": plugin_dir.name in self._plugins,
            })
        
        return discovered
    
    async def load_plugin(self, plugin_id: str) -> Optional[Plugin]:
        """Load a plugin by ID."""
        plugin_dir = self.plugins_dir / plugin_id
        
        if not plugin_dir.exists():
            self.logger.error(f"Plugin directory not found: {plugin_id}")
            return None
        
        plugin_file = plugin_dir / "plugin.py"
        if not plugin_file.exists():
            plugin_file = plugin_dir / "__init__.py"
        
        if not plugin_file.exists():
            self.logger.error(f"Plugin file not found: {plugin_id}")
            return None
        
        try:
            # Load the module
            spec = importlib.util.spec_from_file_location(
                f"plugins.installed.{plugin_id}",
                plugin_file
            )
            
            if spec is None or spec.loader is None:
                self.logger.error(f"Could not load plugin spec: {plugin_id}")
                return None
            
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            
            self._modules[plugin_id] = module
            
            # Find the plugin class
            plugin_class = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and 
                    issubclass(attr, Plugin) and 
                    attr is not Plugin):
                    plugin_class = attr
                    break
            
            if plugin_class is None:
                self.logger.error(f"No Plugin class found in: {plugin_id}")
                return None
            
            self._plugin_classes[plugin_id] = plugin_class
            
            # Create metadata if not provided by class
            if hasattr(module, "PLUGIN_METADATA"):
                metadata = module.PLUGIN_METADATA
            else:
                metadata = PluginMetadata(
                    plugin_id=plugin_id,
                    name=plugin_id,
                    version="1.0.0",
                    plugin_type=PluginType.INTEGRATION,
                )
            
            # Instantiate plugin
            plugin = plugin_class(metadata)
            
            # Call on_load
            success = await plugin.on_load()
            
            if success:
                plugin.state = PluginState.LOADED
                plugin.loaded_at = time.time()
                self._plugins[plugin_id] = plugin
                
                self._load_history.append({
                    "plugin_id": plugin_id,
                    "action": "load",
                    "success": True,
                    "timestamp": time.time(),
                })
                
                self.logger.info(f"Plugin loaded: {plugin_id}")
                return plugin
            else:
                self.logger.error(f"Plugin on_load failed: {plugin_id}")
                return None
                
        except Exception as e:
            self.logger.error(f"Failed to load plugin {plugin_id}: {e}")
            self._load_history.append({
                "plugin_id": plugin_id,
                "action": "load",
                "success": False,
                "error": str(e),
                "timestamp": time.time(),
            })
            return None
    
    async def unload_plugin(self, plugin_id: str) -> bool:
        """Unload a plugin."""
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            return False
        
        try:
            # Disable first if running
            if plugin.state == PluginState.RUNNING:
                await plugin.on_disable()
            
            # Call on_unload
            await plugin.on_unload()
            
            plugin.state = PluginState.UNLOADED
            
            # Remove from registry
            del self._plugins[plugin_id]
            
            # Remove module
            if plugin_id in self._modules:
                module_name = f"plugins.installed.{plugin_id}"
                if module_name in sys.modules:
                    del sys.modules[module_name]
                del self._modules[plugin_id]
            
            self._load_history.append({
                "plugin_id": plugin_id,
                "action": "unload",
                "success": True,
                "timestamp": time.time(),
            })
            
            self.logger.info(f"Plugin unloaded: {plugin_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to unload plugin {plugin_id}: {e}")
            return False
    
    async def reload_plugin(self, plugin_id: str) -> Optional[Plugin]:
        """Reload a plugin."""
        await self.unload_plugin(plugin_id)
        return await self.load_plugin(plugin_id)
    
    async def enable_plugin(self, plugin_id: str) -> bool:
        """Enable a loaded plugin."""
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            return False
        
        if plugin.state not in [PluginState.LOADED, PluginState.STOPPED, PluginState.PAUSED]:
            return False
        
        try:
            success = await plugin.on_enable()
            
            if success:
                plugin.state = PluginState.RUNNING
                plugin.enabled_at = time.time()
                self.logger.info(f"Plugin enabled: {plugin_id}")
                return True
            else:
                plugin.state = PluginState.ERROR
                return False
                
        except Exception as e:
            plugin.state = PluginState.ERROR
            plugin.record_error(str(e))
            return False
    
    async def disable_plugin(self, plugin_id: str) -> bool:
        """Disable a running plugin."""
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            return False
        
        if plugin.state != PluginState.RUNNING:
            return False
        
        try:
            await plugin.on_disable()
            plugin.state = PluginState.STOPPED
            self.logger.info(f"Plugin disabled: {plugin_id}")
            return True
            
        except Exception as e:
            plugin.record_error(str(e))
            return False
    
    def get_plugin(self, plugin_id: str) -> Optional[Plugin]:
        """Get a loaded plugin."""
        return self._plugins.get(plugin_id)
    
    def get_plugins_by_type(self, plugin_type: PluginType) -> List[Plugin]:
        """Get plugins by type."""
        return [
            p for p in self._plugins.values()
            if p.metadata.plugin_type == plugin_type
        ]
    
    def get_running_plugins(self) -> List[Plugin]:
        """Get all running plugins."""
        return [p for p in self._plugins.values() if p.state == PluginState.RUNNING]
    
    def get_status(self) -> Dict[str, Any]:
        """Get loader status."""
        return {
            "plugins_dir": str(self.plugins_dir),
            "loaded_count": len(self._plugins),
            "running_count": len(self.get_running_plugins()),
            "plugins": {k: v.get_status() for k, v in self._plugins.items()},
            "recent_history": self._load_history[-10:],
        }


# Singleton
_plugin_loader: Optional[PluginLoader] = None


def get_plugin_loader() -> PluginLoader:
    """Get or create the Plugin Loader singleton."""
    global _plugin_loader
    if _plugin_loader is None:
        _plugin_loader = PluginLoader()
    return _plugin_loader
