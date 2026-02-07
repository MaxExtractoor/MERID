"""
Plugin Registry.

Central registry for plugin discovery, metadata, and marketplace.

Version: 1.0.0
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

from plugins.plugin_base import Plugin, PluginMetadata, PluginType, PluginState
from plugins.plugin_loader import PluginLoader, get_plugin_loader
from utils.logger import get_logger

logger = get_logger("plugins.registry")


class PluginRegistry:
    """
    Central registry for plugins.
    
    Features:
    - Plugin discovery and listing
    - Metadata management
    - Version tracking
    - Dependency resolution
    """
    
    def __init__(self):
        self.logger = get_logger("plugins.registry")
        self._loader = get_plugin_loader()
        
        # Registry data
        self._registry: Dict[str, Dict[str, Any]] = {}
        
        # Categories
        self._categories: Dict[str, List[str]] = {}
        
        # Tags index
        self._tags_index: Dict[str, List[str]] = {}
    
    def register_plugin(self, metadata: PluginMetadata) -> None:
        """Register a plugin in the registry."""
        self._registry[metadata.plugin_id] = {
            "metadata": metadata.to_dict(),
            "registered_at": time.time(),
            "downloads": 0,
            "rating": 0.0,
            "reviews": [],
        }
        
        # Index by type
        type_key = metadata.plugin_type.value
        if type_key not in self._categories:
            self._categories[type_key] = []
        if metadata.plugin_id not in self._categories[type_key]:
            self._categories[type_key].append(metadata.plugin_id)
        
        # Index by tags
        for tag in metadata.tags:
            if tag not in self._tags_index:
                self._tags_index[tag] = []
            if metadata.plugin_id not in self._tags_index[tag]:
                self._tags_index[tag].append(metadata.plugin_id)
        
        self.logger.info(f"Registered plugin: {metadata.plugin_id}")
    
    def unregister_plugin(self, plugin_id: str) -> bool:
        """Unregister a plugin from the registry."""
        if plugin_id not in self._registry:
            return False
        
        entry = self._registry[plugin_id]
        metadata = entry.get("metadata", {})
        
        # Remove from categories
        type_key = metadata.get("plugin_type", "")
        if type_key in self._categories:
            if plugin_id in self._categories[type_key]:
                self._categories[type_key].remove(plugin_id)
        
        # Remove from tags
        for tag in metadata.get("tags", []):
            if tag in self._tags_index:
                if plugin_id in self._tags_index[tag]:
                    self._tags_index[tag].remove(plugin_id)
        
        del self._registry[plugin_id]
        self.logger.info(f"Unregistered plugin: {plugin_id}")
        return True
    
    def get_plugin_info(self, plugin_id: str) -> Optional[Dict[str, Any]]:
        """Get plugin information from registry."""
        entry = self._registry.get(plugin_id)
        if not entry:
            return None
        
        # Add runtime status
        plugin = self._loader.get_plugin(plugin_id)
        if plugin:
            entry["status"] = plugin.get_status()
        else:
            entry["status"] = {"state": "not_loaded"}
        
        return entry
    
    def search_plugins(
        self,
        query: Optional[str] = None,
        plugin_type: Optional[PluginType] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Search for plugins."""
        results = []
        
        for plugin_id, entry in self._registry.items():
            metadata = entry.get("metadata", {})
            
            # Filter by type
            if plugin_type and metadata.get("plugin_type") != plugin_type.value:
                continue
            
            # Filter by tags
            if tags:
                plugin_tags = metadata.get("tags", [])
                if not any(t in plugin_tags for t in tags):
                    continue
            
            # Filter by query
            if query:
                query_lower = query.lower()
                name = metadata.get("name", "").lower()
                desc = metadata.get("description", "").lower()
                if query_lower not in name and query_lower not in desc:
                    continue
            
            results.append({
                "plugin_id": plugin_id,
                **entry,
            })
        
        return results
    
    def get_plugins_by_type(self, plugin_type: PluginType) -> List[Dict[str, Any]]:
        """Get plugins by type."""
        plugin_ids = self._categories.get(plugin_type.value, [])
        return [self.get_plugin_info(pid) for pid in plugin_ids if self.get_plugin_info(pid)]
    
    def get_plugins_by_tag(self, tag: str) -> List[Dict[str, Any]]:
        """Get plugins by tag."""
        plugin_ids = self._tags_index.get(tag, [])
        return [self.get_plugin_info(pid) for pid in plugin_ids if self.get_plugin_info(pid)]
    
    def check_dependencies(self, plugin_id: str) -> Dict[str, Any]:
        """Check if plugin dependencies are satisfied."""
        entry = self._registry.get(plugin_id)
        if not entry:
            return {"satisfied": False, "error": "Plugin not found"}
        
        metadata = entry.get("metadata", {})
        dependencies = metadata.get("dependencies", [])
        
        missing = []
        for dep in dependencies:
            if dep not in self._registry:
                missing.append(dep)
            else:
                # Check if dependency is loaded
                plugin = self._loader.get_plugin(dep)
                if not plugin or plugin.state != PluginState.RUNNING:
                    missing.append(f"{dep} (not running)")
        
        return {
            "satisfied": len(missing) == 0,
            "dependencies": dependencies,
            "missing": missing,
        }
    
    def get_dependency_tree(self, plugin_id: str) -> Dict[str, Any]:
        """Get dependency tree for a plugin."""
        def build_tree(pid: str, visited: set) -> Dict[str, Any]:
            if pid in visited:
                return {"plugin_id": pid, "circular": True}
            
            visited.add(pid)
            
            entry = self._registry.get(pid)
            if not entry:
                return {"plugin_id": pid, "not_found": True}
            
            metadata = entry.get("metadata", {})
            dependencies = metadata.get("dependencies", [])
            
            return {
                "plugin_id": pid,
                "version": metadata.get("version", ""),
                "dependencies": [build_tree(dep, visited.copy()) for dep in dependencies],
            }
        
        return build_tree(plugin_id, set())
    
    def get_all_tags(self) -> List[str]:
        """Get all available tags."""
        return list(self._tags_index.keys())
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get registry statistics."""
        type_counts = {t: len(ids) for t, ids in self._categories.items()}
        
        return {
            "total_plugins": len(self._registry),
            "by_type": type_counts,
            "total_tags": len(self._tags_index),
            "popular_tags": sorted(
                self._tags_index.items(),
                key=lambda x: len(x[1]),
                reverse=True
            )[:10],
        }
    
    def export_registry(self, file_path: str) -> None:
        """Export registry to file."""
        with open(file_path, "w") as f:
            json.dump({
                "registry": self._registry,
                "categories": self._categories,
                "tags_index": self._tags_index,
                "exported_at": time.time(),
            }, f, indent=2)
    
    def import_registry(self, file_path: str) -> None:
        """Import registry from file."""
        with open(file_path, "r") as f:
            data = json.load(f)
        
        self._registry = data.get("registry", {})
        self._categories = data.get("categories", {})
        self._tags_index = data.get("tags_index", {})
    
    def get_status(self) -> Dict[str, Any]:
        """Get registry status."""
        return {
            "total_registered": len(self._registry),
            "categories": list(self._categories.keys()),
            "statistics": self.get_statistics(),
        }


# Singleton
_plugin_registry: Optional[PluginRegistry] = None


def get_plugin_registry() -> PluginRegistry:
    """Get or create the Plugin Registry singleton."""
    global _plugin_registry
    if _plugin_registry is None:
        _plugin_registry = PluginRegistry()
    return _plugin_registry
