"""
Production Deployment System for MERID Phase 4 Sprint 10

Provides comprehensive production deployment capabilities with
automated deployment pipeline, environment management, and rollback procedures.

Features:
- Production environment setup
- Automated deployment pipeline
- Health monitoring and validation
- Rollback procedures
- US-compliant deployment
"""

import asyncio
import time
import os
import json
import subprocess
import shutil
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
from enum import Enum

from utils.logger import get_logger

logger = get_logger("deployment.production_deployment")

class EnvironmentType(Enum):
    """Environment type enumeration."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    DR = "disaster_recovery"

class DeploymentStatus(Enum):
    """Deployment status enumeration."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    TESTING = "testing"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    CANCELLED = "cancelled"

class DeploymentType(Enum):
    """Deployment type enumeration."""
    FULL = "full"
    INCREMENTAL = "incremental"
    ROLLBACK = "rollback"
    HOTFIX = "hotfix"
    BLUE_GREEN = "blue_green"

@dataclass
class Environment:
    """Environment definition."""
    env_id: str
    env_name: str
    env_type: EnvironmentType
    config: Dict[str, Any]
    servers: List[str]
    database_config: Dict[str, Any]
    security_config: Dict[str, Any]
    monitoring_config: Dict[str, Any]
    status: str
    last_deployment: Optional[datetime]
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class DeploymentConfig:
    """Deployment configuration."""
    deployment_id: str
    deployment_name: str
    deployment_type: DeploymentType
    source_env: str
    target_env: str
    components: List[str]
    version: str
    rollback_enabled: bool
    health_check_enabled: bool
    monitoring_enabled: bool
    security_scan_enabled: bool
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class DeploymentStep:
    """Deployment step definition."""
    step_id: str
    step_name: str
    step_type: str
    command: str
    timeout_seconds: int
    retry_count: int
    dependencies: List[str]
    validation_rules: List[str]
    rollback_command: Optional[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class DeploymentResult:
    """Deployment result definition."""
    deployment_id: str
    deployment_name: str
    status: DeploymentStatus
    start_time: datetime
    end_time: Optional[datetime]
    duration_seconds: float
    success: bool
    deployed_components: List[str]
    failed_components: List[str]
    rollback_performed: bool
    health_check_results: Dict[str, bool]
    security_scan_results: Dict[str, Any]
    error_message: Optional[str]
    warnings: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

class ProductionDeployment:
    """
    Comprehensive production deployment system for MERID.
    
    Provides automated deployment pipeline, environment management,
    and rollback procedures with US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Environments
        self.environments: Dict[str, Environment] = {}
        
        # Deployment configurations
        self.deployment_configs: Dict[str, DeploymentConfig] = {}
        
        # Deployment steps
        self.deployment_steps: Dict[str, List[DeploymentStep]] = {}
        
        # Deployment results
        self.deployment_results: deque = deque(maxlen=1000)
        
        # Deployment state
        self.deployment_state: Dict[str, DeploymentStatus] = {}
        
        # Configuration
        self.deployment_config = config.get("production_deployment", {
            "max_concurrent_deployments": 3,
            "default_timeout": 1800,  # 30 minutes
            "health_check_interval": 60,
            "rollback_timeout": 600,  # 10 minutes
            "security_scan_timeout": 300,  # 5 minutes
            "backup_enabled": True,
            "monitoring_enabled": True
        })
        
        # Environment templates
        self.environment_templates = {
            EnvironmentType.DEVELOPMENT: {
                "servers": ["dev-server-1", "dev-server-2"],
                "database_config": {
                    "host": "localhost",
                    "port": 5432,
                    "name": "merid_dev"
                },
                "security_config": {
                    "ssl_enabled": False,
                    "firewall_enabled": False,
                    "access_control": "basic"
                },
                "monitoring_config": {
                    "metrics_enabled": True,
                    "logging_level": "DEBUG",
                    "alerting_enabled": False
                }
            },
            EnvironmentType.STAGING: {
                "servers": ["staging-server-1", "staging-server-2"],
                "database_config": {
                    "host": "staging-db.internal",
                    "port": 5432,
                    "name": "merid_staging"
                },
                "security_config": {
                    "ssl_enabled": True,
                    "firewall_enabled": True,
                    "access_control": "oauth"
                },
                "monitoring_config": {
                    "metrics_enabled": True,
                    "logging_level": "INFO",
                    "alerting_enabled": True
                }
            },
            EnvironmentType.PRODUCTION: {
                "servers": ["prod-server-1", "prod-server-2", "prod-server-3"],
                "database_config": {
                    "host": "prod-db.internal",
                    "port": 5432,
                    "name": "merid_prod",
                    "replicas": 3
                },
                "security_config": {
                    "ssl_enabled": True,
                    "firewall_enabled": True,
                    "access_control": "sso",
                    "encryption_enabled": True
                },
                "monitoring_config": {
                    "metrics_enabled": True,
                    "logging_level": "WARN",
                    "alerting_enabled": True,
                    "performance_monitoring": True
                }
            }
        }
        
        # Deployment step templates
        self.step_templates = {
            "pre_deployment": [
                {
                    "step_id": "backup_database",
                    "step_name": "Backup Database",
                    "step_type": "backup",
                    "command": "backup_database.sh",
                    "timeout_seconds": 300,
                    "retry_count": 2,
                    "dependencies": [],
                    "validation_rules": ["backup_success"],
                    "rollback_command": None
                },
                {
                    "step_id": "health_check",
                    "step_name": "Pre-Deployment Health Check",
                    "step_type": "health_check",
                    "command": "health_check.sh",
                    "timeout_seconds": 120,
                    "retry_count": 1,
                    "dependencies": [],
                    "validation_rules": ["all_healthy"],
                    "rollback_command": None
                }
            ],
            "deployment": [
                {
                    "step_id": "stop_services",
                    "step_name": "Stop Services",
                    "step_type": "service_management",
                    "command": "stop_services.sh",
                    "timeout_seconds": 60,
                    "retry_count": 2,
                    "dependencies": ["health_check"],
                    "validation_rules": ["services_stopped"],
                    "rollback_command": "start_services.sh"
                },
                {
                    "step_id": "deploy_code",
                    "step_name": "Deploy Code",
                    "step_type": "code_deployment",
                    "command": "deploy_code.sh",
                    "timeout_seconds": 300,
                    "retry_count": 1,
                    "dependencies": ["stop_services"],
                    "validation_rules": ["deployment_success"],
                    "rollback_command": "rollback_code.sh"
                },
                {
                    "step_id": "database_migrations",
                    "step_name": "Database Migrations",
                    "step_type": "database_migration",
                    "command": "run_migrations.sh",
                    "timeout_seconds": 600,
                    "retry_count": 1,
                    "dependencies": ["deploy_code"],
                    "validation_rules": ["migrations_success"],
                    "rollback_command": "rollback_migrations.sh"
                },
                {
                    "step_id": "start_services",
                    "step_name": "Start Services",
                    "step_type": "service_management",
                    "command": "start_services.sh",
                    "timeout_seconds": 60,
                    "retry_count": 2,
                    "dependencies": ["database_migrations"],
                    "validation_rules": ["services_started"],
                    "rollback_command": "stop_services.sh"
                }
            ],
            "post_deployment": [
                {
                    "step_id": "health_check",
                    "step_name": "Post-Deployment Health Check",
                    "step_type": "health_check",
                    "command": "health_check.sh",
                    "timeout_seconds": 120,
                    "retry_count": 3,
                    "dependencies": ["start_services"],
                    "validation_rules": ["all_healthy"],
                    "rollback_command": None
                },
                {
                    "step_id": "security_scan",
                    "step_name": "Security Scan",
                    "step_type": "security_validation",
                    "command": "security_scan.sh",
                    "timeout_seconds": 300,
                    "retry_count": 1,
                    "dependencies": ["health_check"],
                    "validation_rules": ["security_passed"],
                    "rollback_command": None
                },
                {
                    "step_id": "performance_test",
                    "step_name": "Performance Test",
                    "step_type": "performance_validation",
                    "command": "performance_test.sh",
                    "timeout_seconds": 600,
                    "retry_count": 1,
                    "dependencies": ["health_check"],
                    "validation_rules": ["performance_passed"],
                    "rollback_command": None
                }
            ]
        }
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "deployment_security": True,
            "audit_deployment": True,
            "data_protection": True,
            "access_control": True
        })
        
        logger.info("ProductionDeployment initialized")
    
    async def create_environment(self, env_id: str, env_name: str, env_type: EnvironmentType,
                              custom_config: Optional[Dict[str, Any]] = None) -> bool:
        """Create an environment."""
        try:
            # Validate environment configuration
            if not self._validate_environment_config(env_type, custom_config):
                logger.error(f"Invalid environment configuration: {env_id}")
                return False
            
            # Get template defaults
            template = self.environment_templates.get(env_type, {})
            
            # Merge with custom configuration
            config = template.copy()
            if custom_config:
                config.update(custom_config)
            
            # Create environment
            environment = Environment(
                env_id=env_id,
                env_name=env_name,
                env_type=env_type,
                config=config,
                servers=config.get("servers", []),
                database_config=config.get("database_config", {}),
                security_config=config.get("security_config", {}),
                monitoring_config=config.get("monitoring_config", {}),
                status="created",
                last_deployment=None
            )
            
            # Store environment
            self.environments[env_id] = environment
            
            logger.info(f"Environment created: {env_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create environment {env_id}: {e}")
            return False
    
    def _validate_environment_config(self, env_type: EnvironmentType, custom_config: Optional[Dict[str, Any]]) -> bool:
        """Validate environment configuration."""
        try:
            # Check environment type
            if env_type not in EnvironmentType:
                return False
            
            # US compliance checks
            if self.us_compliance.get("deployment_security", True):
                if not self._validate_environment_security(env_type, custom_config):
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Environment configuration validation error: {e}")
            return False
    
    def _validate_environment_security(self, env_type: EnvironmentType, custom_config: Optional[Dict[str, Any]]) -> bool:
        """Validate environment security configuration."""
        try:
            # Check security requirements for production
            if env_type == EnvironmentType.PRODUCTION:
                if custom_config:
                    security_config = custom_config.get("security_config", {})
                    
                    # Production must have SSL enabled
                    if not security_config.get("ssl_enabled", True):
                        return False
                    
                    # Production must have firewall enabled
                    if not security_config.get("firewall_enabled", True):
                        return False
                    
                    # Production must have proper access control
                    if security_config.get("access_control") not in ["sso", "oauth", "ldap"]:
                        return False
            
            return True
            
        except Exception as e:
            logger.error(f"Environment security validation error: {e}")
            return False
    
    async def create_deployment_config(self, deployment_id: str, deployment_name: str,
                                      deployment_type: DeploymentType,
                                      source_env: str, target_env: str,
                                      components: List[str], version: str,
                                      rollback_enabled: bool = True,
                                      health_check_enabled: bool = True,
                                      monitoring_enabled: bool = True,
                                      security_scan_enabled: bool = True) -> bool:
        """Create a deployment configuration."""
        try:
            # Validate deployment configuration
            if not self._validate_deployment_config(deployment_type, source_env, target_env, components):
                logger.error(f"Invalid deployment configuration: {deployment_id}")
                return False
            
            # Create deployment configuration
            deployment_config = DeploymentConfig(
                deployment_id=deployment_id,
                deployment_name=deployment_name,
                deployment_type=deployment_type,
                source_env=source_env,
                target_env=target_env,
                components=components,
                version=version,
                rollback_enabled=rollback_enabled,
                health_check_enabled=health_check_enabled,
                monitoring_enabled=monitoring_enabled,
                security_scan_enabled=security_scan_enabled
            )
            
            # Store deployment configuration
            self.deployment_configs[deployment_id] = deployment_config
            self.deployment_state[deployment_id] = DeploymentStatus.PENDING
            
            logger.info(f"Deployment configuration created: {deployment_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create deployment configuration {deployment_id}: {e}")
            return False
    
    def _validate_deployment_config(self, deployment_type: DeploymentType,
                                    source_env: str, target_env: str,
                                    components: List[str]) -> bool:
        """Validate deployment configuration."""
        try:
            # Check deployment type
            if deployment_type not in DeploymentType:
                return False
            
            # Check environments exist
            if source_env not in self.environments:
                return False
            if target_env not in self.environments:
                return False
            
            # Check components
            if not components:
                return False
            
            # US compliance checks
            if self.us_compliance.get("deployment_security", True):
                if not self._validate_deployment_security(deployment_type, source_env, target_env):
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Deployment configuration validation error: {e}")
            return False
    
    def _validate_deployment_security(self, deployment_type: DeploymentType,
                                   source_env: str, target_env: str) -> bool:
        """Validate deployment security configuration."""
        try:
            # Check production deployment security requirements
            if deployment_type == DeploymentType.FULL:
                target_environment = self.environments[target_env]
                
                if target_environment.env_type == EnvironmentType.PRODUCTION:
                    security_config = target_environment.security_config
                    
                    # Production deployment must have security scan enabled
                    if not security_config.get("encryption_enabled", False):
                        return False
                    
                    # Production deployment must have proper access control
                    if security_config.get("access_control") not in ["sso", "oauth", "ldap"]:
                        return False
            
            return True
            
        except Exception as e:
            logger.error(f"Deployment security validation error: {e}")
            return False
    
    async def execute_deployment(self, deployment_id: str) -> DeploymentResult:
        """Execute a deployment."""
        try:
            if deployment_id not in self.deployment_configs:
                raise ValueError(f"Deployment configuration {deployment_id} not found")
            
            deployment_config = self.deployment_configs[deployment_id]
            
            # Update status
            self.deployment_state[deployment_id] = DeploymentStatus.IN_PROGRESS
            
            # Create deployment result
            result = DeploymentResult(
                deployment_id=deployment_id,
                deployment_name=deployment_config.deployment_name,
                status=DeploymentStatus.IN_PROGRESS,
                start_time=datetime.now(),
                end_time=None,
                duration_seconds=0.0,
                success=False,
                deployed_components=[],
                failed_components=[],
                rollback_performed=False,
                health_check_results={},
                security_scan_results={},
                error_message=None,
                warnings=[],
                metadata={}
            )
            
            logger.info(f"Starting deployment: {deployment_id}")
            
            try:
                # Execute deployment steps
                if deployment_config.deployment_type == DeploymentType.ROLLBACK:
                    success = await self._execute_rollback(deployment_config, result)
                else:
                    success = await self._execute_deployment_pipeline(deployment_config, result)
                
                if success:
                    result.status = DeploymentStatus.COMPLETED
                    result.success = True
                    self.deployment_state[deployment_id] = DeploymentStatus.COMPLETED
                    logger.info(f"Deployment completed successfully: {deployment_id}")
                else:
                    result.status = DeploymentStatus.FAILED
                    self.deployment_state[deployment_id] = DeploymentStatus.FAILED
                    logger.error(f"Deployment failed: {deployment_id}")
                
            except Exception as e:
                result.status = DeploymentStatus.FAILED
                result.error_message = str(e)
                self.deployment_state[deployment_id] = DeploymentStatus.FAILED
                logger.error(f"Deployment error: {deployment_id} - {e}")
                
                # Attempt rollback if enabled
                if deployment_config.rollback_enabled:
                    logger.info(f"Attempting rollback for {deployment_id}")
                    await self._execute_rollback(deployment_config, result)
                    result.rollback_performed = True
                    result.status = DeploymentStatus.ROLLED_BACKED
                    self.deployment_state[deployment_id] = DeploymentStatus.ROLLED_BACKED
            
            # Finalize result
            result.end_time = datetime.now()
            result.duration_seconds = (result.end_time - result.start_time).total_seconds()
            
            # Store result
            self.deployment_results.append(result)
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to execute deployment {deployment_id}: {e}")
            
            # Create failed result
            failed_result = DeploymentResult(
                deployment_id=deployment_id,
                deployment_name="Unknown",
                status=DeploymentStatus.FAILED,
                start_time=datetime.now(),
                end_time=datetime.now(),
                duration_seconds=0.0,
                success=False,
                deployed_components=[],
                failed_components=[],
                rollback_performed=False,
                health_check_results={},
                security_scan_results={},
                error_message=str(e),
                warnings=[],
                metadata={}
            )
            
            self.deployment_results.append(failed_result)
            return failed_result
    
    async def _execute_deployment_pipeline(self, deployment_config: DeploymentConfig, result: DeploymentResult) -> bool:
        """Execute deployment pipeline."""
        try:
            # Get deployment steps
            steps = []
            
            # Add pre-deployment steps
            steps.extend(self.step_templates.get("pre_deployment", []))
            
            # Add deployment steps
            steps.extend(self.step_templates.get("deployment", []))
            
            # Add post-deployment steps
            steps.extend(self.step_templates.get("post_deployment", []))
            
            # Execute steps
            for step in steps:
                logger.info(f"Executing step: {step.step_name}")
                
                # Check dependencies
                if step.dependencies:
                    dependencies_met = all(
                        dep in result.deployed_components 
                        for dep in step.dependencies
                    )
                    if not dependencies_met:
                        logger.warning(f"Dependencies not met for step {step.step_id}")
                        continue
                
                # Execute step
                step_success = await self._execute_step(step, deployment_config, result)
                
                if not step_success:
                    logger.error(f"Step {step.step_id} failed")
                    result.failed_components.append(step.step_id)
                    return False
                else:
                    result.deployed_components.append(step.step_id)
                
                # Validate step
                if step.validation_rules:
                    validation_success = await self._validate_step(step, deployment_config, result)
                    if not validation_success:
                        logger.error(f"Step {step_id} validation failed")
                        result.failed_components.append(step.step_id)
                        return False
            
            return True
            
        except Exception as e:
            logger.error(f"Deployment pipeline error: {e}")
            return False
    
    async def _execute_step(self, step: DeploymentStep, deployment_config: DeploymentConfig, result: DeploymentResult) -> bool:
        """Execute a deployment step."""
        try:
            for attempt in range(step.retry_count + 1):
                try:
                    # Execute step command
                    success = await self._execute_command(step.command, step.timeout_seconds)
                    
                    if success:
                        logger.info(f"Step {step.step_id} completed successfully")
                        return True
                    else:
                        if attempt < step.retry_count:
                            logger.warning(f"Step {step.step_id} failed, retrying... (attempt {attempt + 1})")
                            await asyncio.sleep(5)  # Wait before retry
                        else:
                            logger.error(f"Step {step.step_id} failed after {step.retry_count + 1} attempts")
                            return False
                
                except asyncio.TimeoutError:
                    logger.error(f"Step {step.step_id} timed out after {step.timeout_seconds} seconds")
                    return False
                
                except Exception as e:
                    logger.error(f"Step {step.step_id} error: {e}")
                    if attempt < step.retry_count:
                        await asyncio.sleep(5)
                    else:
                        return False
            
            return False
            
        except Exception as e:
            logger.error(f"Step execution error: {e}")
            return False
    
    async def _execute_command(self, command: str, timeout_seconds: int) -> bool:
        """Execute a command."""
        try:
            # Mock command execution
            # In production, execute actual deployment commands
            
            logger.info(f"Executing command: {command}")
            
            # Simulate command execution
            await asyncio.sleep(1)  # Simulate command execution time
            
            # Mock success for demonstration
            if "backup" in command or "health_check" in command or "deploy" in command:
                return True
            elif "stop" in command or "start" in command:
                return True
            elif "migrations" in command:
                return True
            else:
                return True  # Assume success for demonstration
            
        except Exception as e:
            logger.error(f"Command execution error: {e}")
            return False
    
    async def _validate_step(self, step: DeploymentStep, deployment_config: DeploymentConfig, result: DeploymentResult) -> bool:
        """Validate a deployment step."""
        try:
            # Mock validation
            # In production, perform actual validation
            
            for rule in step.validation_rules:
                if rule == "backup_success":
                    # Mock backup validation
                    success = True
                elif rule == "all_healthy":
                    # Mock health check validation
                    success = True
                elif rule == "services_stopped":
                    # Mock service validation
                    success = True
                elif rule == "deployment_success":
                    # Mock deployment validation
                    success = True
                elif rule == "migrations_success":
                    # Mock migration validation
                    success = True
                elif rule == "services_started":
                    # Mock service validation
                    success = True
                elif rule == "security_passed":
                    # Mock security validation
                    success = True
                elif rule == "performance_passed":
                    # Mock performance validation
                    success = True
                else:
                    success = True  # Assume success for demonstration
                
                if not success:
                    logger.error(f"Validation rule {rule} failed")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Step validation error: {e}")
            return False
    
    async def _execute_rollback(self, deployment_config: DeploymentConfig, result: DeploymentResult) -> bool:
        """Execute rollback procedures."""
        try:
            logger.info(f"Executing rollback for {deployment_config.deployment_id}")
            
            # Get rollback steps (reverse of deployment steps)
            rollback_steps = []
            
            # Add rollback steps in reverse order
            deployment_steps = self.step_templates.get("deployment", [])
            for step in reversed(deployment_steps):
                if step.rollback_command:
                    rollback_step = DeploymentStep(
                        step_id=f"rollback_{step.step_id}",
                        step_name=f"Rollback {step.step_name}",
                        step_type="rollback",
                        command=step.rollback_command,
                        timeout_seconds=step.timeout_seconds,
                        retry_count=step.retry_count,
                        dependencies=[],
                        validation_rules=[],
                        rollback_command=None
                    )
                    rollback_steps.append(rollback_step)
            
            # Execute rollback steps
            for step in rollback_steps:
                logger.info(f"Executing rollback step: {step.step_name}")
                
                success = await self._execute_step(step, deployment_config, result)
                
                if not success:
                    logger.error(f"Rollback step {step.step_id} failed")
                    return False
                
                result.deployed_components.remove(step.step_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Rollback execution error: {e}")
            return False
    
    async def health_check(self, env_id: str) -> Dict[str, Any]:
        """Perform health check on environment."""
        try:
            if env_id not in self.environments:
                return {"status": "error", "message": f"Environment {env_id} not found"}
            
            environment = self.environments[env_id]
            
            # Mock health check
            health_status = {
                "status": "healthy",
                "timestamp": datetime.now().isoformat(),
                "servers": {},
                "database": "connected",
                "services": "running",
                "security": "compliant",
                "performance": "optimal"
            }
            
            # Check server health
            for server in environment.servers:
                health_status["servers"][server] = {
                    "status": "healthy",
                    "cpu_usage": np.random.uniform(20, 80),
                    "memory_usage": np.random.uniform(30, 70),
                    "disk_usage": np.random.uniform(10, 50)
                }
            
            logger.info(f"Health check completed for {env_id}")
            return health_status
            
        except Exception as e:
            logger.error(f"Health check error for {env_id}: {e}")
            return {"status": "error", "message": str(e)}
    
    def get_deployment_status(self, deployment_id: Optional[str] = None) -> Dict[str, Any]:
        """Get deployment status."""
        try:
            if deployment_id:
                if deployment_id in self.deployment_state:
                    return {
                        "deployment_id": deployment_id,
                        "status": self.deployment_state[deployment_id].value
                    }
                else:
                    return {"status": "error", "message": f"Deployment {deployment_id} not found"}
            else:
                # Return all deployment statuses
                return {
                    dep_id: status.value for dep_id, status in self.deployment_state.items()
                }
                
        except Exception as e:
            logger.error(f"Failed to get deployment status: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_deployment_history(self, limit: int = 100) -> List[DeploymentResult]:
        """Get deployment history."""
        return list(self.deployment_results)[-limit:]
    
    def get_environment_status(self, env_id: Optional[str] = None) -> Dict[str, Any]:
        """Get environment status."""
        try:
            if env_id:
                if env_id in self.environments:
                    environment = self.environments[env_id]
                    return {
                        "env_id": env_id,
                        "env_name": environment.env_name,
                        "env_type": environment.env_type.value,
                        "status": environment.status,
                        "servers": environment.servers,
                        "last_deployment": environment.last_deployment.isoformat() if environment.last_deployment else None
                    }
                else:
                    return {"status": "error", "message": f"Environment {env_id} not found"}
            else:
                # Return all environment statuses
                return {
                    env_id: {
                        "env_name": env.env_name,
                        "env_type": env.env_type.value,
                        "status": env.status,
                        "servers": env.servers
                    }
                    for env_id, env in self.environments.items()
                }
                
        except Exception as e:
            logger.error(f"Failed to get environment status: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_deployment_summary(self) -> Dict[str, Any]:
        """Get deployment summary."""
        try:
            # Deployment status distribution
            deployment_statuses = {}
            for status in self.deployment_state.values():
                status_name = status.value
                deployment_statuses[status_name] = deployment_statuses.get(status_name, 0) + 1
            
            # Environment status distribution
            environment_statuses = {}
            for environment in self.environments.values():
                status_name = environment.status
                environment_statuses[status_name] = environment_statuses.get(status_name, 0) + 1
            
            # Recent deployments
            recent_deployments = list(self.deployment_results)[-10:]
            
            return {
                "total_deployments": len(self.deployment_results),
                "deployment_statuses": deployment_statuses,
                "environment_statuses": environment_statuses,
                "recent_deployments": len(recent_deployments),
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get deployment summary: {e}")
            return {"status": "error", "error": str(e)}
    
    def update_config(self, new_config: Dict[str, Any]):
        """Update deployment configuration."""
        self.config.update(new_config)
        
        # Update specific parameters
        if "production_deployment" in new_config:
            self.deployment_config.update(new_config["production_deployment"])
        
        logger.info("Production deployment configuration updated")
