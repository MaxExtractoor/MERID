"""
MERID Plugin / Extension System.

Provides a modular plugin architecture for extending MERID functionality
with custom strategies, data sources, and integrations.

Version: 1.0.0
"""

from plugins.plugin_base import Plugin, PluginType, PluginMetadata
from plugins.plugin_loader import PluginLoader, get_plugin_loader
from plugins.plugin_registry import PluginRegistry, get_plugin_registry
from plugins.hooks import HookManager, Hook, get_hook_manager
from plugins.sandbox import PluginSandbox, get_plugin_sandbox

__all__ = [
    "Plugin",
    "PluginType",
    "PluginMetadata",
    "PluginLoader",
    "get_plugin_loader",
    "PluginRegistry",
    "get_plugin_registry",
    "HookManager",
    "Hook",
    "get_hook_manager",
    "PluginSandbox",
    "get_plugin_sandbox",
]

# Plugin settings
PLUGINS_ENABLED = True
SANDBOX_ENABLED = True
