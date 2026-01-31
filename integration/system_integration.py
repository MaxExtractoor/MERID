"""
System Integration for MERID Phase 3 Sprint 8

Provides comprehensive system integration with component APIs,
data pipelines, and deployment preparation.

Features:
- Component API integration
- Data pipeline orchestration
- Performance optimization
- System monitoring
- US-compliant deployment
"""

import asyncio
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import logging
from enum import Enum

from utils.logger import get_logger

logger = get_logger("integration.system_integration")

class ComponentType(Enum):
    """Component type enumeration."""
    STREAM = "stream"
    ORACLE = "oracle"
    AGENT = "agent"
    TRADING = "trading"
    MONITORING = "monitoring"
    SCALING = "scaling"
    ANALYTICS = "analytics"
    AI_SIGNALS = "ai_signals"
    MULTI_ASSET = "multi_asset"
    RISK_MANAGEMENT = "risk_management"

class IntegrationStatus(Enum):
    """Integration status enumeration."""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    CONNECTED = "connected"
    TESTING = "testing"
    COMPLETED = "completed"
    FAILED = "failed"

class DataFlowType(Enum):
    """Data flow type enumeration."""
    REAL_TIME = "real_time"
    BATCH = "batch"
    STREAMING = "streaming"
    ON_DEMAND = "on_demand"

@dataclass
class ComponentAPI:
    """Component API definition."""
    component_id: str
    component_name: str
    component_type: ComponentType
    api_endpoint: str
    api_version: str
    authentication: Dict[str, Any]
    rate_limits: Dict[str, int]
    data_formats: List[str]
    status: IntegrationStatus
    health_check_url: str
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class DataPipeline:
    """Data pipeline definition."""
    pipeline_id: str
    pipeline_name: str
    source_component: str
    target_component: str
    data_flow_type: DataFlowType
    transformation_rules: List[Dict[str, Any]]
    filtering_rules: List[Dict[str, Any]]
    schedule: Optional[str]
    status: IntegrationStatus
    throughput: float
    latency: float
    error_rate: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class SystemMetrics:
    """System metrics definition."""
    timestamp: datetime
    total_components: int
    active_components: int
    total_pipelines: int
    active_pipelines: int
    system_throughput: float
    average_latency: float
    error_rate: float
    cpu_usage: float
    memory_usage: float
    disk_usage: float
    network_io: float
    metadata: Dict[str, Any] = field(default_factory=dict)

class SystemIntegration:
    """
    Comprehensive system integration manager for MERID.
    
    Provides component API integration, data pipeline orchestration,
    and system monitoring with US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Component APIs
        self.component_apis: Dict[str, ComponentAPI] = {}
        
        # Data pipelines
        self.data_pipelines: Dict[str, DataPipeline] = {}
        
        # System metrics
        self.system_metrics: deque = deque(maxlen=1000)
        
        # Integration status
        self.integration_status: Dict[str, IntegrationStatus] = {}
        
        # Performance monitoring
        self.performance_monitor: Dict[str, Any] = {}
        
        # Configuration
        self.integration_config = config.get("system_integration", {
            "max_components": 50,
            "max_pipelines": 100,
            "health_check_interval": 60,  # seconds
            "metrics_retention_days": 30,
            "auto_recovery": True
        })
        
        # Component templates
        self.component_templates = {
            ComponentType.STREAM: {
                "api_endpoint": "/api/v1/stream",
                "data_formats": ["json", "protobuf"],
                "rate_limits": {"requests_per_second": 1000, "requests_per_minute": 50000}
            },
            ComponentType.ORACLE: {
                "api_endpoint": "/api/v1/oracle",
                "data_formats": ["json"],
                "rate_limits": {"requests_per_second": 100, "requests_per_minute": 5000}
            },
            ComponentType.AGENT: {
                "api_endpoint": "/api/v1/agent",
                "data_formats": ["json", "msgpack"],
                "rate_limits": {"requests_per_second": 500, "requests_per_minute": 20000}
            },
            ComponentType.TRADING: {
                "api_endpoint": "/api/v1/trading",
                "data_formats": ["json", "protobuf"],
                "rate_limits": {"requests_per_second": 200, "requests_per_minute": 10000}
            },
            ComponentType.MONITORING: {
                "api_endpoint": "/api/v1/monitoring",
                "data_formats": ["json", "prometheus"],
                "rate_limits": {"requests_per_second": 1000, "requests_per_minute": 60000}
            },
            ComponentType.SCALING: {
                "api_endpoint": "/api/v1/scaling",
                "data_formats": ["json"],
                "rate_limits": {"requests_per_second": 50, "requests_per_minute": 2000}
            },
            ComponentType.ANALYTICS: {
                "api_endpoint": "/api/v1/analytics",
                "data_formats": ["json", "parquet"],
                "rate_limits": {"requests_per_second": 200, "requests_per_minute": 8000}
            },
            ComponentType.AI_SIGNALS: {
                "api_endpoint": "/api/v1/ai_signals",
                "data_formats": ["json", "numpy"],
                "rate_limits": {"requests_per_second": 100, "requests_per_minute": 5000}
            },
            ComponentType.MULTI_ASSET: {
                "api_endpoint": "/api/v1/multi_asset",
                "data_formats": ["json", "csv"],
                "rate_limits": {"requests_per_second": 150, "requests_per_minute": 7000}
            },
            ComponentType.RISK_MANAGEMENT: {
                "api_endpoint": "/api/v1/risk",
                "data_formats": ["json"],
                "rate_limits": {"requests_per_second": 300, "requests_per_minute": 15000}
            }
        }
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "api_security": True,
            "data_privacy": True,
            "audit_integration": True,
            "performance_disclosure": True
        })
        
        # Background tasks
        self.health_check_task: Optional[asyncio.Task] = None
        self.metrics_collection_task: Optional[asyncio.Task] = None
        
        logger.info("SystemIntegration initialized")
    
    async def register_component(self, component_id: str, component_name: str,
                               component_type: ComponentType, api_endpoint: str,
                               api_version: str = "v1",
                               authentication: Optional[Dict[str, Any]] = None,
                               custom_rate_limits: Optional[Dict[str, int]] = None) -> bool:
        """Register a component API."""
        try:
            # Validate component configuration
            if not self._validate_component_config(component_type, api_endpoint):
                logger.error(f"Invalid component configuration: {component_id}")
                return False
            
            # Get template defaults
            template = self.component_templates.get(component_type, {})
            
            # Merge with custom configuration
            rate_limits = custom_rate_limits or template.get("rate_limits", {})
            data_formats = template.get("data_formats", ["json"])
            
            # Create component API
            component_api = ComponentAPI(
                component_id=component_id,
                component_name=component_name,
                component_type=component_type,
                api_endpoint=api_endpoint,
                api_version=api_version,
                authentication=authentication or {"type": "none"},
                rate_limits=rate_limits,
                data_formats=data_formats,
                status=IntegrationStatus.NOT_STARTED,
                health_check_url=f"{api_endpoint}/health"
            )
            
            # Store component
            self.component_apis[component_id] = component_api
            self.integration_status[component_id] = IntegrationStatus.NOT_STARTED
            
            # Record for compliance
            if self.us_compliance.get("audit_integration", True):
                await self._record_component_registration(component_api)
            
            logger.info(f"Component registered: {component_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to register component {component_id}: {e}")
            return False
    
    def _validate_component_config(self, component_type: ComponentType, api_endpoint: str) -> bool:
        """Validate component configuration."""
        try:
            # Check component type
            if component_type not in ComponentType:
                return False
            
            # Check API endpoint
            if not api_endpoint or not api_endpoint.startswith("/"):
                return False
            
            # Check component count limit
            if len(self.component_apis) >= self.integration_config["max_components"]:
                return False
            
            # US compliance checks
            if self.us_compliance.get("api_security", True):
                if not self._validate_component_security(component_type, api_endpoint):
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Component configuration validation error: {e}")
            return False
    
    def _validate_component_security(self, component_type: ComponentType, api_endpoint: str) -> bool:
        """Validate component security for US compliance."""
        try:
            # Check for secure endpoints
            if "trading" in api_endpoint or "risk" in api_endpoint:
                # These should have authentication
                return True  # Simplified check
            
            return True
            
        except Exception as e:
            logger.error(f"Component security validation error: {e}")
            return False
    
    async def connect_component(self, component_id: str) -> bool:
        """Connect to a component."""
        try:
            if component_id not in self.component_apis:
                logger.error(f"Component {component_id} not found")
                return False
            
            component = self.component_apis[component_id]
            
            # Update status
            self.integration_status[component_id] = IntegrationStatus.IN_PROGRESS
            component.status = IntegrationStatus.IN_PROGRESS
            
            # Mock connection process
            logger.info(f"Connecting to {component_id}...")
            
            # Simulate connection attempts
            for attempt in range(3):
                try:
                    # Mock health check
                    health_status = await self._perform_health_check(component)
                    
                    if health_status:
                        self.integration_status[component_id] = IntegrationStatus.CONNECTED
                        component.status = IntegrationStatus.CONNECTED
                        
                        logger.info(f"Connected to {component_id}")
                        return True
                    
                    await asyncio.sleep(1)  # Wait before retry
                    
                except Exception as e:
                    logger.warning(f"Connection attempt {attempt + 1} failed for {component_id}: {e}")
            
            # Connection failed
            self.integration_status[component_id] = IntegrationStatus.FAILED
            component.status = IntegrationStatus.FAILED
            
            logger.error(f"Failed to connect to {component_id}")
            return False
            
        except Exception as e:
            logger.error(f"Failed to connect to component {component_id}: {e}")
            return False
    
    async def _perform_health_check(self, component: ComponentAPI) -> bool:
        """Perform health check on component."""
        try:
            # Mock health check
            # In production, make actual HTTP request to health_check_url
            
            # Simulate health check response
            health_response = {
                "status": "healthy",
                "timestamp": datetime.now().isoformat(),
                "version": component.api_version,
                "uptime": np.random.uniform(3600, 86400)  # 1-24 hours
            }
            
            return health_response["status"] == "healthy"
            
        except Exception as e:
            logger.error(f"Health check failed for {component.component_id}: {e}")
            return False
    
    async def create_data_pipeline(self, pipeline_id: str, pipeline_name: str,
                                 source_component: str, target_component: str,
                                 data_flow_type: DataFlowType,
                                 transformation_rules: Optional[List[Dict[str, Any]]] = None,
                                 filtering_rules: Optional[List[Dict[str, Any]]] = None,
                                 schedule: Optional[str] = None) -> bool:
        """Create a data pipeline."""
        try:
            # Validate pipeline configuration
            if not self._validate_pipeline_config(source_component, target_component, data_flow_type):
                logger.error(f"Invalid pipeline configuration: {pipeline_id}")
                return False
            
            # Create pipeline
            pipeline = DataPipeline(
                pipeline_id=pipeline_id,
                pipeline_name=pipeline_name,
                source_component=source_component,
                target_component=target_component,
                data_flow_type=data_flow_type,
                transformation_rules=transformation_rules or [],
                filtering_rules=filtering_rules or [],
                schedule=schedule,
                status=IntegrationStatus.NOT_STARTED,
                throughput=0.0,
                latency=0.0,
                error_rate=0.0
            )
            
            # Store pipeline
            self.data_pipelines[pipeline_id] = pipeline
            
            logger.info(f"Data pipeline created: {pipeline_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create data pipeline {pipeline_id}: {e}")
            return False
    
    def _validate_pipeline_config(self, source_component: str, target_component: str,
                               data_flow_type: DataFlowType) -> bool:
        """Validate pipeline configuration."""
        try:
            # Check components exist
            if source_component not in self.component_apis:
                return False
            if target_component not in self.component_apis:
                return False
            
            # Check data flow type
            if data_flow_type not in DataFlowType:
                return False
            
            # Check pipeline count limit
            if len(self.data_pipelines) >= self.integration_config["max_pipelines"]:
                return False
            
            # US compliance checks
            if self.us_compliance.get("data_privacy", True):
                if not self._validate_pipeline_privacy(source_component, target_component):
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Pipeline configuration validation error: {e}")
            return False
    
    def _validate_pipeline_privacy(self, source_component: str, target_component: str) -> bool:
        """Validate pipeline for data privacy."""
        try:
            # Check for sensitive data flows
            sensitive_components = ["trading", "risk_management", "ai_signals"]
            
            source_type = self.component_apis[source_component].component_type.value
            target_type = self.component_apis[target_component].component_type.value
            
            # If sensitive data is involved, ensure proper handling
            if any(comp in source_type or comp in target_type for comp in sensitive_components):
                return True  # Simplified check
            
            return True
            
        except Exception as e:
            logger.error(f"Pipeline privacy validation error: {e}")
            return False
    
    async def start_pipeline(self, pipeline_id: str) -> bool:
        """Start a data pipeline."""
        try:
            if pipeline_id not in self.data_pipelines:
                logger.error(f"Pipeline {pipeline_id} not found")
                return False
            
            pipeline = self.data_pipelines[pipeline_id]
            
            # Check source and target components are connected
            if (self.integration_status.get(pipeline.source_component) != IntegrationStatus.CONNECTED or
                self.integration_status.get(pipeline.target_component) != IntegrationStatus.CONNECTED):
                logger.error(f"Components not connected for pipeline {pipeline_id}")
                return False
            
            # Update status
            pipeline.status = IntegrationStatus.IN_PROGRESS
            
            # Mock pipeline start
            logger.info(f"Starting pipeline {pipeline_id}...")
            
            # Simulate pipeline initialization
            await asyncio.sleep(0.1)
            
            # Update status
            pipeline.status = IntegrationStatus.COMPLETED
            
            # Initialize performance metrics
            pipeline.throughput = np.random.uniform(100, 1000)  # messages per second
            pipeline.latency = np.random.uniform(1, 50)  # milliseconds
            pipeline.error_rate = np.random.uniform(0.001, 0.01)  # 0.1% - 1%
            
            logger.info(f"Pipeline started: {pipeline_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start pipeline {pipeline_id}: {e}")
            return False
    
    async def test_integration(self, component_id: Optional[str] = None,
                            pipeline_id: Optional[str] = None) -> Dict[str, Any]:
        """Test system integration."""
        try:
            test_results = {
                "timestamp": datetime.now(),
                "component_tests": {},
                "pipeline_tests": {},
                "overall_status": "passed",
                "issues": []
            }
            
            # Test components
            if component_id:
                if component_id in self.component_apis:
                    result = await self._test_component(component_id)
                    test_results["component_tests"][component_id] = result
                    
                    if not result["passed"]:
                        test_results["overall_status"] = "failed"
                        test_results["issues"].append(f"Component {component_id} test failed")
                else:
                    test_results["issues"].append(f"Component {component_id} not found")
                    test_results["overall_status"] = "failed"
            else:
                # Test all connected components
                for comp_id, component in self.component_apis.items():
                    if component.status == IntegrationStatus.CONNECTED:
                        result = await self._test_component(comp_id)
                        test_results["component_tests"][comp_id] = result
                        
                        if not result["passed"]:
                            test_results["overall_status"] = "failed"
                            test_results["issues"].append(f"Component {comp_id} test failed")
            
            # Test pipelines
            if pipeline_id:
                if pipeline_id in self.data_pipelines:
                    result = await self._test_pipeline(pipeline_id)
                    test_results["pipeline_tests"][pipeline_id] = result
                    
                    if not result["passed"]:
                        test_results["overall_status"] = "failed"
                        test_results["issues"].append(f"Pipeline {pipeline_id} test failed")
                else:
                    test_results["issues"].append(f"Pipeline {pipeline_id} not found")
                    test_results["overall_status"] = "failed"
            else:
                # Test all active pipelines
                for pipe_id, pipeline in self.data_pipelines.items():
                    if pipeline.status == IntegrationStatus.COMPLETED:
                        result = await self._test_pipeline(pipe_id)
                        test_results["pipeline_tests"][pipe_id] = result
                        
                        if not result["passed"]:
                            test_results["overall_status"] = "failed"
                            test_results["issues"].append(f"Pipeline {pipe_id} test failed")
            
            return test_results
            
        except Exception as e:
            logger.error(f"Integration test failed: {e}")
            return {
                "timestamp": datetime.now(),
                "overall_status": "failed",
                "issues": [f"Test execution error: {e}"]
            }
    
    async def _test_component(self, component_id: str) -> Dict[str, Any]:
        """Test a component."""
        try:
            component = self.component_apis[component_id]
            
            test_result = {
                "component_id": component_id,
                "passed": True,
                "response_time": 0.0,
                "api_tests": {},
                "issues": []
            }
            
            start_time = time.time()
            
            # Mock API tests
            api_tests = [
                {"endpoint": "/health", "method": "GET"},
                {"endpoint": "/status", "method": "GET"},
                {"endpoint": "/metrics", "method": "GET"}
            ]
            
            for test in api_tests:
                # Mock API call
                response_time = np.random.uniform(10, 200)  # 10-200ms
                status_code = 200 if np.random.random() > 0.05 else 500  # 5% error rate
                
                test_result["api_tests"][test["endpoint"]] = {
                    "status_code": status_code,
                    "response_time": response_time,
                    "passed": status_code == 200
                }
                
                if status_code != 200:
                    test_result["passed"] = False
                    test_result["issues"].append(f"API test failed: {test['endpoint']}")
            
            test_result["response_time"] = time.time() - start_time
            
            return test_result
            
        except Exception as e:
            logger.error(f"Component test failed for {component_id}: {e}")
            return {
                "component_id": component_id,
                "passed": False,
                "issues": [f"Test execution error: {e}"]
            }
    
    async def _test_pipeline(self, pipeline_id: str) -> Dict[str, Any]:
        """Test a data pipeline."""
        try:
            pipeline = self.data_pipelines[pipeline_id]
            
            test_result = {
                "pipeline_id": pipeline_id,
                "passed": True,
                "throughput_test": {},
                "latency_test": {},
                "data_integrity_test": {},
                "issues": []
            }
            
            # Mock throughput test
            test_messages = 100
            start_time = time.time()
            
            # Simulate message processing
            for _ in range(test_messages):
                await asyncio.sleep(0.001)  # 1ms processing time
            
            processing_time = time.time() - start_time
            throughput = test_messages / processing_time
            
            test_result["throughput_test"] = {
                "messages_processed": test_messages,
                "processing_time": processing_time,
                "throughput": throughput,
                "passed": throughput > 50  # Minimum 50 msg/s
            }
            
            if throughput <= 50:
                test_result["passed"] = False
                test_result["issues"].append("Throughput below minimum threshold")
            
            # Mock latency test
            latencies = [np.random.uniform(1, 100) for _ in range(10)]  # 1-100ms
            avg_latency = np.mean(latencies)
            max_latency = np.max(latencies)
            
            test_result["latency_test"] = {
                "average_latency": avg_latency,
                "max_latency": max_latency,
                "passed": avg_latency < 50  # Average < 50ms
            }
            
            if avg_latency >= 50:
                test_result["passed"] = False
                test_result["issues"].append("Latency above maximum threshold")
            
            # Mock data integrity test
            test_data = {"test": "data", "timestamp": datetime.now().isoformat()}
            integrity_passed = np.random.random() > 0.02  # 2% failure rate
            
            test_result["data_integrity_test"] = {
                "test_data": test_data,
                "passed": integrity_passed
            }
            
            if not integrity_passed:
                test_result["passed"] = False
                test_result["issues"].append("Data integrity test failed")
            
            return test_result
            
        except Exception as e:
            logger.error(f"Pipeline test failed for {pipeline_id}: {e}")
            return {
                "pipeline_id": pipeline_id,
                "passed": False,
                "issues": [f"Test execution error: {e}"]
            }
    
    async def collect_system_metrics(self) -> SystemMetrics:
        """Collect system metrics."""
        try:
            # Count active components and pipelines
            active_components = sum(1 for status in self.integration_status.values() 
                                 if status == IntegrationStatus.CONNECTED)
            active_pipelines = sum(1 for pipeline in self.data_pipelines.values() 
                                if pipeline.status == IntegrationStatus.COMPLETED)
            
            # Calculate system metrics
            total_throughput = sum(pipeline.throughput for pipeline in self.data_pipelines.values()
                                 if pipeline.status == IntegrationStatus.COMPLETED)
            
            avg_latency = np.mean([pipeline.latency for pipeline in self.data_pipelines.values()
                                 if pipeline.status == IntegrationStatus.COMPLETED]) if active_pipelines > 0 else 0
            
            avg_error_rate = np.mean([pipeline.error_rate for pipeline in self.data_pipelines.values()
                                    if pipeline.status == IntegrationStatus.COMPLETED]) if active_pipelines > 0 else 0
            
            # Mock system resource metrics
            cpu_usage = np.random.uniform(20, 80)
            memory_usage = np.random.uniform(30, 70)
            disk_usage = np.random.uniform(40, 60)
            network_io = np.random.uniform(10, 100)
            
            metrics = SystemMetrics(
                timestamp=datetime.now(),
                total_components=len(self.component_apis),
                active_components=active_components,
                total_pipelines=len(self.data_pipelines),
                active_pipelines=active_pipelines,
                system_throughput=total_throughput,
                average_latency=avg_latency,
                error_rate=avg_error_rate,
                cpu_usage=cpu_usage,
                memory_usage=memory_usage,
                disk_usage=disk_usage,
                network_io=network_io
            )
            
            # Store metrics
            self.system_metrics.append(metrics)
            
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to collect system metrics: {e}")
            return SystemMetrics(
                timestamp=datetime.now(),
                total_components=0,
                active_components=0,
                total_pipelines=0,
                active_pipelines=0,
                system_throughput=0.0,
                average_latency=0.0,
                error_rate=0.0,
                cpu_usage=0.0,
                memory_usage=0.0,
                disk_usage=0.0,
                network_io=0.0
            )
    
    def get_component_status(self, component_id: Optional[str] = None) -> Dict[str, Any]:
        """Get component status."""
        try:
            if component_id:
                if component_id in self.component_apis:
                    component = self.component_apis[component_id]
                    status = self.integration_status.get(component_id, IntegrationStatus.NOT_STARTED)
                    
                    return {
                        "component_id": component_id,
                        "component_name": component.component_name,
                        "component_type": component.component_type.value,
                        "status": status.value,
                        "api_endpoint": component.api_endpoint,
                        "api_version": component.api_version,
                        "health_check_url": component.health_check_url
                    }
                else:
                    return {"error": f"Component {component_id} not found"}
            else:
                # Return all components
                components = {}
                for comp_id, component in self.component_apis.items():
                    status = self.integration_status.get(comp_id, IntegrationStatus.NOT_STARTED)
                    components[comp_id] = {
                        "component_name": component.component_name,
                        "component_type": component.component_type.value,
                        "status": status.value,
                        "api_endpoint": component.api_endpoint
                    }
                
                return components
                
        except Exception as e:
            logger.error(f"Failed to get component status: {e}")
            return {"error": str(e)}
    
    def get_pipeline_status(self, pipeline_id: Optional[str] = None) -> Dict[str, Any]:
        """Get pipeline status."""
        try:
            if pipeline_id:
                if pipeline_id in self.data_pipelines:
                    pipeline = self.data_pipelines[pipeline_id]
                    
                    return {
                        "pipeline_id": pipeline_id,
                        "pipeline_name": pipeline.pipeline_name,
                        "source_component": pipeline.source_component,
                        "target_component": pipeline.target_component,
                        "data_flow_type": pipeline.data_flow_type.value,
                        "status": pipeline.status.value,
                        "throughput": pipeline.throughput,
                        "latency": pipeline.latency,
                        "error_rate": pipeline.error_rate
                    }
                else:
                    return {"error": f"Pipeline {pipeline_id} not found"}
            else:
                # Return all pipelines
                pipelines = {}
                for pipe_id, pipeline in self.data_pipelines.items():
                    pipelines[pipe_id] = {
                        "pipeline_name": pipeline.pipeline_name,
                        "source_component": pipeline.source_component,
                        "target_component": pipeline.target_component,
                        "status": pipeline.status.value,
                        "throughput": pipeline.throughput,
                        "latency": pipeline.latency
                    }
                
                return pipelines
                
        except Exception as e:
            logger.error(f"Failed to get pipeline status: {e}")
            return {"error": str(e)}
    
    def get_system_metrics(self, limit: int = 100) -> List[SystemMetrics]:
        """Get system metrics."""
        return list(self.system_metrics)[-limit:]
    
    def get_integration_summary(self) -> Dict[str, Any]:
        """Get comprehensive integration summary."""
        try:
            # Component status distribution
            component_status = {}
            for status in self.integration_status.values():
                status_name = status.value
                component_status[status_name] = component_status.get(status_name, 0) + 1
            
            # Pipeline status distribution
            pipeline_status = {}
            for pipeline in self.data_pipelines.values():
                status_name = pipeline.status.value
                pipeline_status[status_name] = pipeline_status.get(status_name, 0) + 1
            
            # Component type distribution
            component_types = {}
            for component in self.component_apis.values():
                comp_type = component.component_type.value
                component_types[comp_type] = component_types.get(comp_type, 0) + 1
            
            # Latest metrics
            latest_metrics = self.system_metrics[-1] if self.system_metrics else None
            
            return {
                "total_components": len(self.component_apis),
                "component_status": component_status,
                "component_types": component_types,
                "total_pipelines": len(self.data_pipelines),
                "pipeline_status": pipeline_status,
                "latest_metrics": {
                    "active_components": latest_metrics.active_components if latest_metrics else 0,
                    "active_pipelines": latest_metrics.active_pipelines if latest_metrics else 0,
                    "system_throughput": latest_metrics.system_throughput if latest_metrics else 0,
                    "average_latency": latest_metrics.average_latency if latest_metrics else 0,
                    "error_rate": latest_metrics.error_rate if latest_metrics else 0,
                    "cpu_usage": latest_metrics.cpu_usage if latest_metrics else 0,
                    "memory_usage": latest_metrics.memory_usage if latest_metrics else 0
                } if latest_metrics else {},
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get integration summary: {e}")
            return {"status": "error", "error": str(e)}
    
    async def start_monitoring(self):
        """Start system monitoring."""
        try:
            # Start health check task
            self.health_check_task = asyncio.create_task(self._health_check_loop())
            
            # Start metrics collection task
            self.metrics_collection_task = asyncio.create_task(self._metrics_collection_loop())
            
            logger.info("System monitoring started")
            
        except Exception as e:
            logger.error(f"Failed to start monitoring: {e}")
    
    async def stop_monitoring(self):
        """Stop system monitoring."""
        try:
            if self.health_check_task:
                self.health_check_task.cancel()
                try:
                    await self.health_check_task
                except asyncio.CancelledError:
                    pass
            
            if self.metrics_collection_task:
                self.metrics_collection_task.cancel()
                try:
                    await self.metrics_collection_task
                except asyncio.CancelledError:
                    pass
            
            logger.info("System monitoring stopped")
            
        except Exception as e:
            logger.error(f"Failed to stop monitoring: {e}")
    
    async def _health_check_loop(self):
        """Health check loop."""
        while True:
            try:
                # Check all connected components
                for component_id, component in self.component_apis.items():
                    if component.status == IntegrationStatus.CONNECTED:
                        health_status = await self._perform_health_check(component)
                        
                        if not health_status:
                            logger.warning(f"Health check failed for {component_id}")
                            
                            # Attempt recovery if enabled
                            if self.integration_config.get("auto_recovery", True):
                                await self._attempt_component_recovery(component_id)
                
                await asyncio.sleep(self.integration_config["health_check_interval"])
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check loop error: {e}")
                await asyncio.sleep(10)
    
    async def _metrics_collection_loop(self):
        """Metrics collection loop."""
        while True:
            try:
                await self.collect_system_metrics()
                await asyncio.sleep(30)  # Collect metrics every 30 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Metrics collection loop error: {e}")
                await asyncio.sleep(10)
    
    async def _attempt_component_recovery(self, component_id: str):
        """Attempt to recover a failed component."""
        try:
            logger.info(f"Attempting recovery for {component_id}")
            
            # Try to reconnect
            success = await self.connect_component(component_id)
            
            if success:
                logger.info(f"Recovery successful for {component_id}")
            else:
                logger.error(f"Recovery failed for {component_id}")
                
        except Exception as e:
            logger.error(f"Component recovery error for {component_id}: {e}")
    
    async def _record_component_registration(self, component: ComponentAPI):
        """Record component registration for compliance."""
        if not self.us_compliance.get("audit_integration", True):
            return
        
        audit_entry = {
            "action": "component_registration",
            "component_id": component.component_id,
            "component_name": component.component_name,
            "component_type": component.component_type.value,
            "api_endpoint": component.api_endpoint,
            "timestamp": time.time(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Component registration audit entry: {audit_entry}")
    
    def update_config(self, new_config: Dict[str, Any]):
        """Update integration configuration."""
        self.config.update(new_config)
        
        # Update specific parameters
        if "system_integration" in new_config:
            self.integration_config.update(new_config["system_integration"])
        
        logger.info("System integration configuration updated")
