"""
MERID Mode Management System
Single source of truth for trading modes, feature gating, and debug configuration
"""

import os
import json
from typing import Dict, Any, List, Optional, Set
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class TradingMode(Enum):
    """Trading system modes"""
    OFFLINE = "offline"
    SIMULATION = "simulation"
    PAPER = "paper"
    LIVE = "live"
    HYBRID = "hybrid"
    SPECTATOR = "spectator"
    MAINTENANCE = "maintenance"

class FeatureCategory(Enum):
    """Feature categories for gating"""
    TRADING = "trading"
    EXECUTION = "execution"
    RISK = "risk"
    ANALYTICS = "analytics"
    MONITORING = "monitoring"
    DEBUG = "debug"
    ADMIN = "admin"

class DebugMode(Enum):
    """Debug modes for development and troubleshooting"""
    NONE = "none"
    VERBOSE = "verbose"
    TRACE = "trace"
    PERFORMANCE = "performance"
    NETWORK = "network"
    DATABASE = "database"
    AGENTS = "agents"
    REALITY = "reality"

@dataclass
class FeatureGate:
    """Individual feature gate configuration"""
    name: str
    category: FeatureCategory
    enabled: bool = True
    required_modes: Set[TradingMode] = field(default_factory=set)
    blocked_modes: Set[TradingMode] = field(default_factory=set)
    required_permissions: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)
    last_modified: datetime = field(default_factory=datetime.now)

@dataclass
class ModeConfig:
    """Mode-specific configuration"""
    mode: TradingMode
    description: str
    enabled_features: Set[str] = field(default_factory=set)
    disabled_features: Set[str] = field(default_factory=set)
    permissions: Set[str] = field(default_factory=set)
    limits: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class SystemMode:
    """Current system mode state"""
    current_mode: TradingMode
    previous_mode: Optional[TradingMode] = None
    mode_changed_at: datetime = field(default_factory=datetime.now)
    mode_changed_by: Optional[str] = None
    mode_change_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

class ModeManager:
    """Central mode management system"""
    
    def __init__(self):
        self.feature_gates: Dict[str, FeatureGate] = {}
        self.mode_configs: Dict[TradingMode, ModeConfig] = {}
        self.system_mode: SystemMode = SystemMode(current_mode=TradingMode.OFFLINE)
        self.debug_mode: DebugMode = DebugMode.NONE
        self._load_default_configuration()
        
    def _load_default_configuration(self):
        """Load default mode and feature configuration"""
        logger.info("Loading default mode configuration...")
        
        # Default feature gates
        default_features = [
            FeatureGate(
                name="trading_execution",
                category=FeatureCategory.TRADING,
                required_modes={TradingMode.LIVE, TradingMode.HYBRID},
                blocked_modes={TradingMode.OFFLINE, TradingMode.MAINTENANCE}
            ),
            FeatureGate(
                name="paper_trading",
                category=FeatureCategory.TRADING,
                required_modes={TradingMode.PAPER, TradingMode.SIMULATION},
                blocked_modes={TradingMode.OFFLINE, TradingMode.MAINTENANCE}
            ),
            FeatureGate(
                name="risk_monitoring",
                category=FeatureCategory.RISK,
                enabled=True,
                blocked_modes={TradingMode.OFFLINE}
            ),
            FeatureGate(
                name="analytics_dashboard",
                category=FeatureCategory.ANALYTICS,
                enabled=True,
                blocked_modes=set()
            ),
            FeatureGate(
                name="debug_console",
                category=FeatureCategory.DEBUG,
                enabled=False,
                required_permissions={"admin", "debug"}
            ),
            FeatureGate(
                name="agent_control",
                category=FeatureCategory.ADMIN,
                required_permissions={"admin"},
                blocked_modes={TradingMode.LIVE}
            ),
            FeatureGate(
                name="execution_engine",
                category=FeatureCategory.EXECUTION,
                required_modes={TradingMode.LIVE, TradingMode.HYBRID, TradingMode.PAPER},
                blocked_modes={TradingMode.OFFLINE, TradingMode.MAINTENANCE}
            ),
            FeatureGate(
                name="monitoring_alerts",
                category=FeatureCategory.MONITORING,
                enabled=True,
                blocked_modes=set()
            ),
            FeatureGate(
                name="spectator_mode",
                category=FeatureCategory.MONITORING,
                enabled=True,
                required_modes={TradingMode.SPECTATOR}
            ),
            FeatureGate(
                name="reality_enforcement",
                category=FeatureCategory.RISK,
                enabled=True,
                blocked_modes={TradingMode.OFFLINE}
            )
        ]
        
        for feature in default_features:
            self.feature_gates[feature.name] = feature
        
        # Default mode configurations
        mode_configs = {
            TradingMode.OFFLINE: ModeConfig(
                mode=TradingMode.OFFLINE,
                description="System offline - no trading or data processing",
                disabled_features={"trading_execution", "paper_trading", "execution_engine"},
                limits={"max_api_calls_per_minute": 10}
            ),
            TradingMode.SIMULATION: ModeConfig(
                mode=TradingMode.SIMULATION,
                description="Simulation mode - mock data and simulated trading",
                enabled_features={"paper_trading", "analytics_dashboard", "risk_monitoring"},
                limits={"max_api_calls_per_minute": 100}
            ),
            TradingMode.PAPER: ModeConfig(
                mode=TradingMode.PAPER,
                description="Paper trading mode - real data, simulated execution",
                enabled_features={"paper_trading", "execution_engine", "risk_monitoring", "analytics_dashboard"},
                limits={"max_position_size": 10000, "max_daily_volume": 100000}
            ),
            TradingMode.LIVE: ModeConfig(
                mode=TradingMode.LIVE,
                description="Live trading mode - real execution with real money",
                enabled_features={"trading_execution", "execution_engine", "risk_monitoring", "analytics_dashboard"},
                permissions={"trader", "risk_manager"},
                limits={"max_position_size": 100000, "max_daily_volume": 1000000}
            ),
            TradingMode.HYBRID: ModeConfig(
                mode=TradingMode.HYBRID,
                description="Hybrid mode - mix of paper and live trading",
                enabled_features={"trading_execution", "paper_trading", "execution_engine", "risk_monitoring"},
                permissions={"trader", "risk_manager"},
                limits={"max_live_position_size": 50000, "max_paper_position_size": 20000}
            ),
            TradingMode.SPECTATOR: ModeConfig(
                mode=TradingMode.SPECTATOR,
                description="Spectator mode - read-only access to all data",
                enabled_features={"analytics_dashboard", "risk_monitoring", "monitoring_alerts", "spectator_mode"},
                limits={"max_api_calls_per_minute": 50}
            ),
            TradingMode.MAINTENANCE: ModeConfig(
                mode=TradingMode.MAINTENANCE,
                description="Maintenance mode - system under maintenance",
                disabled_features={"trading_execution", "paper_trading", "execution_engine"},
                permissions={"admin"}
            )
        }
        
        for mode, config in mode_configs.items():
            self.mode_configs[mode] = config
        
        logger.info(f"Loaded {len(self.feature_gates)} feature gates and {len(self.mode_configs)} mode configurations")
    
    def is_feature_enabled(self, feature_name: str, user_permissions: Set[str] = None) -> bool:
        """Check if a feature is enabled for the current mode"""
        if feature_name not in self.feature_gates:
            logger.warning(f"Feature '{feature_name}' not found in feature gates")
            return False
        
        feature = self.feature_gates[feature_name]
        current_mode = self.system_mode.current_mode
        
        # Check if feature is explicitly enabled
        if not feature.enabled:
            return False
        
        # Check mode requirements
        if feature.required_modes and current_mode not in feature.required_modes:
            return False
        
        # Check mode blocks
        if feature.blocked_modes and current_mode in feature.blocked_modes:
            return False
        
        # Check permissions
        if feature.required_permissions and user_permissions:
            if not feature.required_permissions.intersection(user_permissions):
                return False
        
        # Check mode-specific configuration
        mode_config = self.mode_configs.get(current_mode)
        if mode_config:
            if feature_name in mode_config.disabled_features:
                return False
            if feature_name not in mode_config.enabled_features and mode_config.enabled_features:
                return False
        
        return True
    
    def get_enabled_features(self, user_permissions: Set[str] = None) -> Set[str]:
        """Get all enabled features for the current mode"""
        enabled_features = set()
        
        for feature_name in self.feature_gates:
            if self.is_feature_enabled(feature_name, user_permissions):
                enabled_features.add(feature_name)
        
        return enabled_features
    
    def get_mode_limits(self) -> Dict[str, Any]:
        """Get limits for the current mode"""
        mode_config = self.mode_configs.get(self.system_mode.current_mode)
        return mode_config.limits if mode_config else {}
    
    def can_execute_trading(self, user_permissions: Set[str] = None) -> bool:
        """Check if trading execution is allowed"""
        return self.is_feature_enabled("trading_execution", user_permissions)
    
    def can_execute_paper_trading(self, user_permissions: Set[str] = None) -> bool:
        """Check if paper trading is allowed"""
        return self.is_feature_enabled("paper_trading", user_permissions)
    
    def is_spectator_mode(self) -> bool:
        """Check if system is in spectator mode"""
        return self.system_mode.current_mode == TradingMode.SPECTATOR
    
    def is_maintenance_mode(self) -> bool:
        """Check if system is in maintenance mode"""
        return self.system_mode.current_mode == TradingMode.MAINTENANCE
    
    def change_mode(self, new_mode: TradingMode, changed_by: str = None, reason: str = None) -> bool:
        """Change the system mode"""
        if new_mode not in self.mode_configs:
            logger.error(f"Invalid mode: {new_mode}")
            return False
        
        old_mode = self.system_mode.current_mode
        
        # Validate mode change
        if not self._validate_mode_change(old_mode, new_mode, changed_by):
            return False
        
        # Update system mode
        self.system_mode.previous_mode = old_mode
        self.system_mode.current_mode = new_mode
        self.system_mode.mode_changed_at = datetime.now()
        self.system_mode.mode_changed_by = changed_by
        self.system_mode.mode_change_reason = reason
        
        logger.info(f"Mode changed from {old_mode} to {new_mode} by {changed_by}: {reason}")
        
        # Trigger mode change events
        self._on_mode_changed(old_mode, new_mode)
        
        return True
    
    def _validate_mode_change(self, old_mode: TradingMode, new_mode: TradingMode, changed_by: str = None) -> bool:
        """Validate if mode change is allowed"""
        # Check permissions
        if changed_by and "admin" not in changed_by:
            # Non-admin users can only switch to less privileged modes
            privileged_modes = {TradingMode.LIVE, TradingMode.HYBRID}
            if new_mode in privileged_modes:
                logger.warning(f"User {changed_by} not authorized to switch to privileged mode {new_mode}")
                return False
        
        # Check if system is in maintenance
        if old_mode == TradingMode.MAINTENANCE and new_mode != TradingMode.OFFLINE:
            if changed_by and "admin" not in changed_by:
                logger.warning("Only admin can exit maintenance mode")
                return False
        
        return True
    
    def _on_mode_changed(self, old_mode: TradingMode, new_mode: TradingMode):
        """Handle mode change events"""
        # Log mode change
        logger.info(f"Mode transition: {old_mode} -> {new_mode}")
        
        # Update debug mode if needed
        if new_mode == TradingMode.OFFLINE:
            self.set_debug_mode(DebugMode.VERBOSE)
        elif new_mode == TradingMode.LIVE:
            self.set_debug_mode(DebugMode.NONE)
        
        # Trigger mode-specific actions
        if new_mode == TradingMode.MAINTENANCE:
            logger.info("Entering maintenance mode - disabling trading features")
        elif old_mode == TradingMode.MAINTENANCE:
            logger.info("Exiting maintenance mode - re-enabling features")
    
    def set_debug_mode(self, debug_mode: DebugMode) -> bool:
        """Set debug mode"""
        old_debug_mode = self.debug_mode
        self.debug_mode = debug_mode
        
        logger.info(f"Debug mode changed from {old_debug_mode} to {debug_mode}")
        
        # Update logging levels based on debug mode
        self._update_logging_level(debug_mode)
        
        return True
    
    def _update_logging_level(self, debug_mode: DebugMode):
        """Update logging levels based on debug mode"""
        if debug_mode == DebugMode.VERBOSE:
            logging.getLogger().setLevel(logging.INFO)
        elif debug_mode == DebugMode.TRACE:
            logging.getLogger().setLevel(logging.DEBUG)
        elif debug_mode == DebugMode.NONE:
            logging.getLogger().setLevel(logging.WARNING)
        else:
            logging.getLogger().setLevel(logging.INFO)
    
    def get_mode_status(self) -> Dict[str, Any]:
        """Get current mode status"""
        return {
            "current_mode": self.system_mode.current_mode.value,
            "previous_mode": self.system_mode.previous_mode.value if self.system_mode.previous_mode else None,
            "mode_changed_at": self.system_mode.mode_changed_at.isoformat(),
            "mode_changed_by": self.system_mode.mode_changed_by,
            "mode_change_reason": self.system_mode.mode_change_reason,
            "debug_mode": self.debug_mode.value,
            "enabled_features": list(self.get_enabled_features()),
            "mode_limits": self.get_mode_limits(),
            "mode_config": {
                "description": self.mode_configs[self.system_mode.current_mode].description,
                "permissions": list(self.mode_configs[self.system_mode.current_mode].permissions)
            }
        }
    
    def add_feature_gate(self, feature: FeatureGate) -> bool:
        """Add a new feature gate"""
        if feature.name in self.feature_gates:
            logger.warning(f"Feature gate '{feature.name}' already exists")
            return False
        
        self.feature_gates[feature.name] = feature
        logger.info(f"Added feature gate: {feature.name}")
        return True
    
    def update_feature_gate(self, feature_name: str, **kwargs) -> bool:
        """Update an existing feature gate"""
        if feature_name not in self.feature_gates:
            logger.error(f"Feature gate '{feature_name}' not found")
            return False
        
        feature = self.feature_gates[feature_name]
        
        for key, value in kwargs.items():
            if hasattr(feature, key):
                setattr(feature, key, value)
                feature.last_modified = datetime.now()
        
        logger.info(f"Updated feature gate: {feature_name}")
        return True
    
    def remove_feature_gate(self, feature_name: str) -> bool:
        """Remove a feature gate"""
        if feature_name not in self.feature_gates:
            logger.error(f"Feature gate '{feature_name}' not found")
            return False
        
        del self.feature_gates[feature_name]
        logger.info(f"Removed feature gate: {feature_name}")
        return True
    
    def export_configuration(self) -> Dict[str, Any]:
        """Export current configuration"""
        return {
            "feature_gates": {
                name: {
                    "category": gate.category.value,
                    "enabled": gate.enabled,
                    "required_modes": [mode.value for mode in gate.required_modes],
                    "blocked_modes": [mode.value for mode in gate.blocked_modes],
                    "required_permissions": list(gate.required_permissions),
                    "metadata": gate.metadata,
                    "last_modified": gate.last_modified.isoformat()
                }
                for name, gate in self.feature_gates.items()
            },
            "mode_configs": {
                mode.value: {
                    "description": config.description,
                    "enabled_features": list(config.enabled_features),
                    "disabled_features": list(config.disabled_features),
                    "permissions": list(config.permissions),
                    "limits": config.limits,
                    "metadata": config.metadata
                }
                for mode, config in self.mode_configs.items()
            },
            "system_mode": {
                "current_mode": self.system_mode.current_mode.value,
                "previous_mode": self.system_mode.previous_mode.value if self.system_mode.previous_mode else None,
                "mode_changed_at": self.system_mode.mode_changed_at.isoformat(),
                "mode_changed_by": self.system_mode.mode_changed_by,
                "mode_change_reason": self.system_mode.mode_change_reason,
                "metadata": self.system_mode.metadata
            },
            "debug_mode": self.debug_mode.value
        }
    
    def import_configuration(self, config: Dict[str, Any]) -> bool:
        """Import configuration from dictionary"""
        try:
            # Import feature gates
            if "feature_gates" in config:
                for name, gate_config in config["feature_gates"].items():
                    feature = FeatureGate(
                        name=name,
                        category=FeatureCategory(gate_config["category"]),
                        enabled=gate_config["enabled"],
                        required_modes={TradingMode(mode) for mode in gate_config["required_modes"]},
                        blocked_modes={TradingMode(mode) for mode in gate_config["blocked_modes"]},
                        required_permissions=set(gate_config["required_permissions"]),
                        metadata=gate_config["metadata"]
                    )
                    self.feature_gates[name] = feature
            
            # Import mode configs
            if "mode_configs" in config:
                for mode_value, mode_config in config["mode_configs"].items():
                    mode = TradingMode(mode_value)
                    config_obj = ModeConfig(
                        mode=mode,
                        description=mode_config["description"],
                        enabled_features=set(mode_config["enabled_features"]),
                        disabled_features=set(mode_config["disabled_features"]),
                        permissions=set(mode_config["permissions"]),
                        limits=mode_config["limits"],
                        metadata=mode_config["metadata"]
                    )
                    self.mode_configs[mode] = config_obj
            
            # Import system mode
            if "system_mode" in config:
                system_config = config["system_mode"]
                self.system_mode = SystemMode(
                    current_mode=TradingMode(system_config["current_mode"]),
                    previous_mode=TradingMode(system_config["previous_mode"]) if system_config["previous_mode"] else None,
                    mode_changed_at=datetime.fromisoformat(system_config["mode_changed_at"]),
                    mode_changed_by=system_config["mode_changed_by"],
                    mode_change_reason=system_config["mode_change_reason"],
                    metadata=system_config["metadata"]
                )
            
            # Import debug mode
            if "debug_mode" in config:
                self.debug_mode = DebugMode(config["debug_mode"])
            
            logger.info("Configuration imported successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to import configuration: {e}")
            return False

# Global mode manager instance
_mode_manager: Optional[ModeManager] = None

def get_mode_manager() -> ModeManager:
    """Get the global mode manager instance"""
    global _mode_manager
    if _mode_manager is None:
        _mode_manager = ModeManager()
    return _mode_manager

def initialize_mode_manager(config_file: str = None) -> ModeManager:
    """Initialize mode manager with optional configuration file"""
    global _mode_manager
    _mode_manager = ModeManager()
    
    if config_file and os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
            _mode_manager.import_configuration(config)
            logger.info(f"Loaded mode configuration from {config_file}")
        except Exception as e:
            logger.error(f"Failed to load configuration from {config_file}: {e}")
    
    return _mode_manager
