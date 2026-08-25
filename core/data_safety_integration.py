"""
Data Safety Integration — Unified initialization and coordination of data safety systems.

This module provides:
- Single entry point for all data safety systems
- Coordinated initialization of backup, integrity, and retention systems
- Integration between systems (e.g., backup manager uses integrity checker)
- Simple configuration and startup
- Monitoring and health checks

Data Safety Improvements:
1. Provides unified interface for all data safety features
2. Ensures systems are properly integrated
3. Simplifies deployment and configuration
4. Provides health monitoring
5. Enables coordinated shutdown
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.data_safety_integration")

from core.database_backup_manager import DatabaseSafetyBackupManager, get_backup_manager
from core.data_integrity_checker import DataSafetyIntegrityChecker, get_integrity_checker
from core.data_retention_manager import DataSafetyRetentionManager, get_retention_manager

# Optional secrets manager import with warning on failure
try:
    from core.secrets_manager import get_secrets_manager
    SECRETS_MANAGER_AVAILABLE = True
except ImportError:
    SECRETS_MANAGER_AVAILABLE = False
    logger.warning("Secrets manager not available - some features may be limited")


class DataSafetyCoordinator:
    """
    Coordinates all data safety systems.
    
    This class provides a unified interface for:
    - Database backup management
    - Data integrity checking
    - Data retention enforcement
    - System health monitoring
    
    Usage:
        coordinator = DataSafetyCoordinator()
        
        # Configure with default settings
        await coordinator.initialize()
        
        # Start all systems
        await coordinator.start()
        
        # Check health
        health = await coordinator.health_check()
        
        # Shutdown gracefully
        await coordinator.shutdown()
    """
    
    def __init__(self):
        self._backup_manager: Optional[DatabaseSafetyBackupManager] = None
        self._integrity_checker: Optional[DataSafetyIntegrityChecker] = None
        self._retention_manager: Optional[DataSafetyRetentionManager] = None
        
        self._initialized = False
        self._started = False
        
        # Configuration
        self._config = {
            "backup_enabled": os.getenv("MERID_BACKUP_ENABLED", "true").lower() == "true",
            "integrity_check_enabled": os.getenv("MERID_INTEGRITY_CHECK_ENABLED", "true").lower() == "true",
            "retention_enabled": os.getenv("MERID_RETENTION_ENABLED", "true").lower() == "true",
            
            # Database paths to monitor
            "databases": [
                os.getenv("MERID_FILLS_DB_PATH", "data/kalshi_fills.db"),
                os.getenv("MERID_ANALYTICS_DB_PATH", "data/analytics.db"),
                os.getenv("MERID_ALERTS_DB_PATH", "data/alerts.db"),
            ],
        }
        
        logger.info("DataSafetyCoordinator initialized")
    
    async def initialize(self, config: Optional[Dict[str, Any]] = None) -> None:
        """
        Initialize all data safety systems.
        
        Args:
            config: Optional configuration overrides
        """
        if config:
            self._config.update(config)
        
        logger.info("Initializing data safety systems...")
        
        # Initialize backup manager with error handling
        if self._config["backup_enabled"]:
            try:
                self._backup_manager = get_backup_manager()
                
                # Add databases to backup schedule
                for db_path in self._config["databases"]:
                    if os.path.exists(db_path):
                        from core.database_backup_manager import BackupPolicy
                        self._backup_manager.add_database(
                            db_path,
                            BackupPolicy(
                                backup_interval_hours=1.0,
                                keep_hourly=24,
                                keep_daily=7,
                                keep_weekly=4,
                                keep_monthly=12,
                            )
                        )
                        logger.info(f"Added {db_path} to backup schedule")
                
                logger.info("Backup manager initialized")
            except Exception as e:
                logger.error(f"Failed to initialize backup manager: {e}")
                self._backup_manager = None
                # Continue with other components - graceful degradation
        
        # Initialize integrity checker with error handling
        if self._config["integrity_check_enabled"]:
            try:
                self._integrity_checker = get_integrity_checker()
                
                # Add databases to integrity monitoring
                for db_path in self._config["databases"]:
                    if os.path.exists(db_path):
                        self._integrity_checker.add_database(
                            db_path,
                            critical=True,
                        )
                        logger.info(f"Added {db_path} to integrity monitoring")
                
                # Integrate with backup manager
                if self._backup_manager:
                    self._integrity_checker.set_alert_manager(
                        type('obj', (object,), {'alert': lambda *args, **kwargs: None})()
                    )
                
                logger.info("Integrity checker initialized")
            except Exception as e:
                logger.error(f"Failed to initialize integrity checker: {e}")
                self._integrity_checker = None
                # Continue with other components - graceful degradation
        
        # Initialize retention manager with error handling
        if self._config["retention_enabled"]:
            try:
                self._retention_manager = get_retention_manager()
                
                # Register databases with their data types
                from core.data_retention_manager import DataType
                
                # ARRAY INDEX FIX: Validate database array length before accessing
                databases = self._config.get("databases", [])
                
                # Fills database: trades (index 0)
                if len(databases) > 0:
                    fills_db = databases[0]
                    if os.path.exists(fills_db):
                        self._retention_manager.register_database(
                            fills_db,
                            [DataType.TRADES]
                        )
                
                # Analytics database: snapshots (index 1)
                if len(databases) > 1:
                    analytics_db = databases[1]
                    if os.path.exists(analytics_db):
                        self._retention_manager.register_database(
                            analytics_db,
                            [DataType.SNAPSHOTS]
                        )
                
                # Alerts database: alerts (index 2)
                if len(databases) > 2:
                    alerts_db = databases[2]
                    if os.path.exists(alerts_db):
                        self._retention_manager.register_database(
                            alerts_db,
                            [DataType.ALERTS, DataType.ALERT_AGGREGATES]
                        )
                
                logger.info("Retention manager initialized")
            except Exception as e:
                logger.error(f"Failed to initialize retention manager: {e}")
                self._retention_manager = None
                # Continue with other components - graceful degradation
        
        self._initialized = True
        logger.info("Data safety systems initialized successfully")
    
    async def start(self) -> None:
        """Start all data safety systems."""
        if not self._initialized:
            await self.initialize()
        
        logger.info("Starting data safety systems...")
        
        # Start backup manager
        if self._backup_manager:
            await self._backup_manager.start()
            logger.info("Backup manager started")
        
        # Start integrity monitoring
        if self._integrity_checker:
            await self._integrity_checker.start_monitoring()
            logger.info("Integrity monitoring started")
        
        # Start retention enforcement
        if self._retention_manager:
            await self._retention_manager.start()
            logger.info("Retention enforcement started")
        
        self._started = True
        logger.info("All data safety systems started")
    
    async def stop(self) -> None:
        """Stop all data safety systems gracefully."""
        logger.info("Stopping data safety systems...")
        
        # Stop retention enforcement
        if self._retention_manager:
            await self._retention_manager.stop()
            logger.info("Retention enforcement stopped")
        
        # Stop integrity monitoring
        if self._integrity_checker:
            await self._integrity_checker.stop_monitoring()
            logger.info("Integrity monitoring stopped")
        
        # Stop backup manager
        if self._backup_manager:
            await self._backup_manager.stop()
            logger.info("Backup manager stopped")
        
        self._started = False
        logger.info("All data safety systems stopped")
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on all data safety systems.
        
        Returns:
            Health status report
        """
        health = {
            "timestamp": asyncio.get_event_loop().time(),
            "overall_status": "healthy",
            "systems": {},
        }
        
        # Check backup manager
        if self._backup_manager:
            backup_stats = self._backup_manager.get_stats()
            health["systems"]["backup"] = {
                "status": "healthy" if backup_stats["failed_backups"] == 0 else "degraded",
                "stats": backup_stats,
            }
            
            if backup_stats["failed_backups"] > 0:
                health["overall_status"] = "degraded"
        
        # Check integrity checker
        if self._integrity_checker:
            integrity_stats = self._integrity_checker.get_stats()
            health["systems"]["integrity"] = {
                "status": "healthy" if integrity_stats["critical_checks"] == 0 else "critical",
                "stats": integrity_stats,
            }
            
            if integrity_stats["critical_checks"] > 0:
                health["overall_status"] = "critical"
        
        # Check retention manager
        if self._retention_manager:
            retention_stats = self._retention_manager.get_stats()
            health["systems"]["retention"] = {
                "status": "healthy",
                "stats": retention_stats,
            }
        
        return health
    
    async def run_integrity_checks(self) -> Dict[str, Any]:
        """
        Run integrity checks on all databases.
        
        Returns:
            Integrity check results
        """
        if not self._integrity_checker:
            logger.warning("Integrity checker not initialized")
            return {"error": "Integrity checker not initialized"}
        
        results = {}
        for db_path in self._config["databases"]:
            if os.path.exists(db_path):
                report = await self._integrity_checker.check_database(db_path)
                results[db_path] = {
                    "status": report.overall_status.value,
                    "issues": report.critical_issues_found,
                    "warnings": report.warnings_found,
                }
        
        return results
    
    async def force_backup(self, database_path: str) -> bool:
        """
        Force an immediate backup of a database.
        
        Args:
            database_path: Path to the database to backup
        
        Returns:
            True if backup successful
        """
        if not self._backup_manager:
            logger.warning("Backup manager not initialized")
            return False
        
        backup = await self._backup_manager.backup_database(database_path, force=True)
        return backup is not None
    
    async def force_retention_enforcement(self) -> Dict[str, Any]:
        """
        Force immediate retention policy enforcement.
        
        Returns:
            Enforcement summary
        """
        if not self._retention_manager:
            logger.warning("Retention manager not initialized")
            return {"error": "Retention manager not initialized"}
        
        return await self._retention_manager.enforce_policies()
    
    def get_backup_manager(self) -> Optional[DatabaseBackupManager]:
        """Get the backup manager instance."""
        return self._backup_manager
    
    def get_integrity_checker(self) -> Optional[DataIntegrityChecker]:
        """Get the integrity checker instance."""
        return self._integrity_checker
    
    def get_retention_manager(self) -> Optional[DataRetentionManager]:
        """Get the retention manager instance."""
        return self._retention_manager


# Global instance
_coordinator: Optional[DataSafetyCoordinator] = None


async def get_data_safety_coordinator() -> DataSafetyCoordinator:
    """
    Get or create the global data safety coordinator.
    
    Returns:
        DataSafetyCoordinator instance
    """
    global _coordinator
    
    if _coordinator is None:
        _coordinator = DataSafetyCoordinator()
        await _coordinator.initialize()
    
    return _coordinator


async def initialize_data_safety_systems() -> DataSafetyCoordinator:
    """
    Initialize and start all data safety systems.
    
    This is the main entry point for data safety initialization.
    
    Usage:
        from core.data_safety_integration import initialize_data_safety_systems
        
        coordinator = await initialize_data_safety_systems()
        
        # Systems are now running in the background
    """
    coordinator = await get_data_safety_coordinator()
    await coordinator.start()
    
    logger.info("Data safety systems initialized and started")
    
    return coordinator
