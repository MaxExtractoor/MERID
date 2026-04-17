"""
Plugin Base Classes.

Defines the base plugin interface and metadata structures.

Version: 1.0.0
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod

from utils.logger import get_logger

logger = get_logger("plugins.base")


class PluginType(Enum):
    """Types of plugins."""
    STRATEGY = "strategy"
    DATA_SOURCE = "data_source"
    INDICATOR = "indicator"
    EXECUTION = "execution"
    NOTIFICATION = "notification"
    ANALYSIS = "analysis"
    INTEGRATION = "integration"
    UI_WIDGET = "ui_widget"


class PluginState(Enum):
    """Plugin lifecycle states."""
    UNLOADED = "unloaded"
    LOADED = "loaded"
    INITIALIZED = "initialized"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class PluginMetadata:
    """Metadata for a plugin."""
    plugin_id: str
    name: str
    version: str
    plugin_type: PluginType
    
    # Author info
    author: str = ""
    author_email: str = ""
    homepage: str = ""
    
    # Description
    description: str = ""
    long_description: str = ""
    
    # Requirements
    min_merid_version: str = "1.0.0"
    dependencies: List[str] = field(default_factory=list)
    python_dependencies: List[str] = field(default_factory=list)
    
    # Permissions
    required_permissions: List[str] = field(default_factory=list)
    
    # Configuration
    config_schema: Dict[str, Any] = field(default_factory=dict)
    default_config: Dict[str, Any] = field(default_factory=dict)
    
    # Tags
    tags: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "version": self.version,
            "plugin_type": self.plugin_type.value,
            "author": self.author,
            "description": self.description,
            "min_merid_version": self.min_merid_version,
            "dependencies": self.dependencies,
            "required_permissions": self.required_permissions,
            "tags": self.tags,
        }


class Plugin(ABC):
    """
    Base class for all plugins.
    
    Plugins must implement:
    - on_load(): Called when plugin is loaded
    - on_unload(): Called when plugin is unloaded
    - on_enable(): Called when plugin is enabled
    - on_disable(): Called when plugin is disabled
    """
    
    def __init__(self, metadata: PluginMetadata):
        self.metadata = metadata
        self.state = PluginState.UNLOADED
        self.config: Dict[str, Any] = metadata.default_config.copy()
        self.logger = get_logger(f"plugins.{metadata.plugin_id}")
        
        # Runtime info
        self.loaded_at: Optional[float] = None
        self.enabled_at: Optional[float] = None
        self.error_message: str = ""
        
        # Statistics
        self.invocation_count: int = 0
        self.error_count: int = 0
        self.last_invocation: Optional[float] = None
    
    @abstractmethod
    async def on_load(self) -> bool:
        """Called when plugin is loaded. Return True if successful."""
        pass
    
    @abstractmethod
    async def on_unload(self) -> None:
        """Called when plugin is unloaded."""
        pass
    
    @abstractmethod
    async def on_enable(self) -> bool:
        """Called when plugin is enabled. Return True if successful."""
        pass
    
    @abstractmethod
    async def on_disable(self) -> None:
        """Called when plugin is disabled."""
        pass
    
    def configure(self, config: Dict[str, Any]) -> None:
        """Update plugin configuration."""
        self.config.update(config)
        self.logger.info(f"Configuration updated: {list(config.keys())}")
    
    def get_config(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self.config.get(key, default)
    
    def record_invocation(self) -> None:
        """Record a plugin invocation."""
        self.invocation_count += 1
        self.last_invocation = time.time()
    
    def record_error(self, error: str) -> None:
        """Record a plugin error."""
        self.error_count += 1
        self.error_message = error
        self.logger.error(f"Plugin error: {error}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get plugin status."""
        return {
            "plugin_id": self.metadata.plugin_id,
            "name": self.metadata.name,
            "version": self.metadata.version,
            "type": self.metadata.plugin_type.value,
            "state": self.state.value,
            "loaded_at": self.loaded_at,
            "enabled_at": self.enabled_at,
            "invocation_count": self.invocation_count,
            "error_count": self.error_count,
            "last_invocation": self.last_invocation,
            "error_message": self.error_message,
        }


class StrategyPlugin(Plugin):
    """Base class for strategy plugins."""
    
    def __init__(self, metadata: PluginMetadata):
        metadata.plugin_type = PluginType.STRATEGY
        super().__init__(metadata)
    
    @abstractmethod
    async def generate_signals(self, market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate trading signals from market data."""
        pass
    
    @abstractmethod
    async def evaluate_position(self, position: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluate an existing position."""
        pass


class DataSourcePlugin(Plugin):
    """Base class for data source plugins."""
    
    def __init__(self, metadata: PluginMetadata):
        metadata.plugin_type = PluginType.DATA_SOURCE
        super().__init__(metadata)
    
    @abstractmethod
    async def fetch_data(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Fetch data from the source."""
        pass
    
    @abstractmethod
    async def subscribe(self, symbols: List[str], callback: callable) -> str:
        """Subscribe to real-time data."""
        pass
    
    @abstractmethod
    async def unsubscribe(self, subscription_id: str) -> None:
        """Unsubscribe from real-time data."""
        pass


class IndicatorPlugin(Plugin):
    """Base class for indicator plugins."""
    
    def __init__(self, metadata: PluginMetadata):
        metadata.plugin_type = PluginType.INDICATOR
        super().__init__(metadata)
    
    @abstractmethod
    async def calculate(self, data: List[float], **params) -> List[float]:
        """Calculate indicator values."""
        pass
    
    @abstractmethod
    def get_parameters(self) -> Dict[str, Any]:
        """Get indicator parameters."""
        pass


class IntegrationPlugin(Plugin):
    """Base class for integration plugins."""
    
    def __init__(self, metadata: PluginMetadata):
        metadata.plugin_type = PluginType.INTEGRATION
        super().__init__(metadata)
    
    @abstractmethod
    async def connect(self) -> bool:
        """Connect to the external service."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the external service."""
        pass
    
    @abstractmethod
    async def execute(self, action: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute an action on the external service."""
        pass
