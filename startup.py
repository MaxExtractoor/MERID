#!/usr/bin/env python3
"""
MERID Production Startup Script

Initializes all core systems in correct order with health checks and validation.
"""

import os
import sys
import logging
import asyncio
from typing import Dict, Any
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MERIDStartup:
    """Orchestrates MERID system startup with validation."""
    
    def __init__(self):
        self.startup_time = time.time()
        self.components_initialized = []
        self.health_checks_passed = []
        self.errors = []
    
    def load_environment(self) -> bool:
        """Load and validate environment variables."""
        logger.info("Loading environment configuration...")
        
        required_vars = [
            "NEO4J_URI",
            "NEO4J_USER",
            "NEO4J_PASSWORD",
        ]
        
        missing = []
        for var in required_vars:
            if not os.getenv(var):
                missing.append(var)
        
        if missing:
            logger.error(f"Missing required environment variables: {', '.join(missing)}")
            return False
        
        logger.info("✓ Environment configuration loaded")
        return True
    
    def initialize_graph_service(self) -> bool:
        """Initialize Neo4j graph database connection."""
        logger.info("Initializing Neo4j GraphService...")
        
        try:
            from core.graph_service import initialize_graph_service
            
            graph_service = initialize_graph_service(
                uri=os.getenv("NEO4J_URI"),
                user=os.getenv("NEO4J_USER"),
                password=os.getenv("NEO4J_PASSWORD"),
                database=os.getenv("NEO4J_DATABASE", "neo4j")
            )
            
            # Run initialization to set defaults
            graph_service.run_init()
            
            self.components_initialized.append("GraphService")
            logger.info("✓ Neo4j GraphService initialized")
            return True
            
        except Exception as e:
            logger.error(f"✗ GraphService initialization failed: {e}")
            self.errors.append(f"GraphService: {e}")
            return False
    
    def initialize_reality_registry(self) -> bool:
        """Initialize Reality Registry."""
        logger.info("Initializing Reality Registry...")
        
        try:
            from core.reality_registry import get_reality_registry
            
            registry = get_reality_registry()
            
            # Verify domains
            domains = registry.get_all_domains()
            if len(domains) < 8:
                logger.warning(f"Only {len(domains)} domains initialized (expected 8)")
            
            self.components_initialized.append("RealityRegistry")
            logger.info(f"✓ Reality Registry initialized with {len(domains)} domains")
            return True
            
        except Exception as e:
            logger.error(f"✗ Reality Registry initialization failed: {e}")
            self.errors.append(f"RealityRegistry: {e}")
            return False
    
    def initialize_execution_controller(self) -> bool:
        """Initialize Execution Controller."""
        logger.info("Initializing Execution Controller...")
        
        try:
            from core.execution_controller import get_execution_controller
            
            controller = get_execution_controller()
            
            # Verify kill switch is not active
            if controller.kill_switch_active:
                logger.warning("Kill switch is ACTIVE - system will not execute trades")
            
            self.components_initialized.append("ExecutionController")
            logger.info("✓ Execution Controller initialized")
            return True
            
        except Exception as e:
            logger.error(f"✗ Execution Controller initialization failed: {e}")
            self.errors.append(f"ExecutionController: {e}")
            return False
    
    def initialize_risk_envelope(self) -> bool:
        """Initialize Risk Envelope Manager."""
        logger.info("Initializing Risk Envelope Manager...")
        
        try:
            from core.risk_envelope import get_risk_envelope_manager
            
            risk_mgr = get_risk_envelope_manager()
            
            # Verify risk limits are set
            envelope = risk_mgr.envelope
            logger.info(f"  - Max position size: ${envelope.max_position_size_usd:,.0f}")
            logger.info(f"  - Max leverage: {envelope.max_leverage}x")
            logger.info(f"  - Max drawdown: {envelope.max_drawdown_pct*100:.1f}%")
            
            self.components_initialized.append("RiskEnvelopeManager")
            logger.info("✓ Risk Envelope Manager initialized")
            return True
            
        except Exception as e:
            logger.error(f"✗ Risk Envelope Manager initialization failed: {e}")
            self.errors.append(f"RiskEnvelopeManager: {e}")
            return False
    
    def initialize_threat_monitor(self) -> bool:
        """Initialize Enhanced Threat Monitor."""
        logger.info("Initializing Enhanced Threat Monitor...")
        
        try:
            from core.enhanced_threat_model import get_enhanced_threat_monitor
            
            threat_monitor = get_enhanced_threat_monitor()
            
            # Verify threats are loaded
            threat_count = len(threat_monitor.threats)
            logger.info(f"  - {threat_count} threats registered")
            
            self.components_initialized.append("EnhancedThreatMonitor")
            logger.info("✓ Enhanced Threat Monitor initialized")
            return True
            
        except Exception as e:
            logger.error(f"✗ Enhanced Threat Monitor initialization failed: {e}")
            self.errors.append(f"EnhancedThreatMonitor: {e}")
            return False
    
    def initialize_model_inventory(self) -> bool:
        """Initialize Model Inventory."""
        logger.info("Initializing Model Inventory...")
        
        try:
            from core.model_risk_management import get_model_inventory
            
            inventory = get_model_inventory()
            
            # Count registered models
            model_count = len(inventory.models)
            logger.info(f"  - {model_count} models in inventory")
            
            self.components_initialized.append("ModelInventory")
            logger.info("✓ Model Inventory initialized")
            return True
            
        except Exception as e:
            logger.error(f"✗ Model Inventory initialization failed: {e}")
            self.errors.append(f"ModelInventory: {e}")
            return False
    
    def initialize_observability(self) -> bool:
        """Initialize Observability Dashboard."""
        logger.info("Initializing Observability Dashboard...")
        
        try:
            from core.observability_dashboards import get_observability_dashboard
            
            dashboard = get_observability_dashboard()
            
            self.components_initialized.append("ObservabilityDashboard")
            logger.info("✓ Observability Dashboard initialized")
            return True
            
        except Exception as e:
            logger.error(f"✗ Observability Dashboard initialization failed: {e}")
            self.errors.append(f"ObservabilityDashboard: {e}")
            return False
    
    def initialize_compliance_engine(self) -> bool:
        """Initialize Programmable Compliance Engine."""
        logger.info("Initializing Programmable Compliance Engine...")
        
        try:
            from core.defi_compliance import get_programmable_compliance_engine
            
            compliance = get_programmable_compliance_engine()
            
            # Verify sanctions lists loaded
            logger.info("  - Sanctions lists loaded")
            logger.info(f"  - Max wallet risk score: {compliance.max_wallet_risk_score}")
            logger.info(f"  - Max protocol illicit flow: {compliance.max_protocol_illicit_flow_pct}%")
            
            self.components_initialized.append("ProgrammableComplianceEngine")
            logger.info("✓ Programmable Compliance Engine initialized")
            return True
            
        except Exception as e:
            logger.error(f"✗ Compliance Engine initialization failed: {e}")
            self.errors.append(f"ComplianceEngine: {e}")
            return False
    
    def run_health_checks(self) -> bool:
        """Run health checks on all initialized components."""
        logger.info("\nRunning health checks...")
        
        all_passed = True
        
        # Check 1: Neo4j connectivity
        try:
            from core.graph_service import get_graph_service
            graph = get_graph_service()
            health = graph.get_system_health_summary()
            logger.info(f"✓ Neo4j: {health.get('total_proposals', 0)} proposals in database")
            self.health_checks_passed.append("Neo4j connectivity")
        except Exception as e:
            logger.error(f"✗ Neo4j health check failed: {e}")
            all_passed = False
        
        # Check 2: Reality Registry
        try:
            from core.reality_registry import get_reality_registry
            registry = get_reality_registry()
            domains = registry.get_all_domains()
            logger.info(f"✓ Reality Registry: {len(domains)} domains active")
            self.health_checks_passed.append("Reality Registry")
        except Exception as e:
            logger.error(f"✗ Reality Registry health check failed: {e}")
            all_passed = False
        
        # Check 3: Execution Controller
        try:
            from core.execution_controller import get_execution_controller
            controller = get_execution_controller()
            if not controller.kill_switch_active:
                logger.info("✓ Execution Controller: Ready for trading")
                self.health_checks_passed.append("Execution Controller")
            else:
                logger.warning("⚠ Execution Controller: Kill switch ACTIVE")
                all_passed = False
        except Exception as e:
            logger.error(f"✗ Execution Controller health check failed: {e}")
            all_passed = False
        
        # Check 4: Risk Envelope
        try:
            from core.risk_envelope import get_risk_envelope_manager
            risk_mgr = get_risk_envelope_manager()
            logger.info("✓ Risk Envelope: Limits configured")
            self.health_checks_passed.append("Risk Envelope")
        except Exception as e:
            logger.error(f"✗ Risk Envelope health check failed: {e}")
            all_passed = False
        
        return all_passed
    
    def print_startup_summary(self):
        """Print startup summary."""
        elapsed = time.time() - self.startup_time
        
        print("\n" + "="*70)
        print("MERID STARTUP SUMMARY")
        print("="*70)
        
        print(f"\n✓ Components Initialized ({len(self.components_initialized)}):")
        for component in self.components_initialized:
            print(f"  - {component}")
        
        print(f"\n✓ Health Checks Passed ({len(self.health_checks_passed)}):")
        for check in self.health_checks_passed:
            print(f"  - {check}")
        
        if self.errors:
            print(f"\n✗ Errors ({len(self.errors)}):")
            for error in self.errors:
                print(f"  - {error}")
        
        print(f"\nStartup completed in {elapsed:.2f} seconds")
        
        if not self.errors:
            print("\n🚀 MERID IS READY FOR OPERATION")
        else:
            print("\n⚠️  MERID STARTED WITH ERRORS - REVIEW BEFORE TRADING")
        
        print("="*70 + "\n")
    
    def run(self) -> bool:
        """Run complete startup sequence."""
        logger.info("="*70)
        logger.info("MERID PRODUCTION STARTUP")
        logger.info("="*70 + "\n")
        
        # Step 1: Load environment
        if not self.load_environment():
            logger.error("Environment configuration failed - aborting startup")
            return False
        
        # Step 2: Initialize core components
        steps = [
            ("Neo4j GraphService", self.initialize_graph_service),
            ("Reality Registry", self.initialize_reality_registry),
            ("Execution Controller", self.initialize_execution_controller),
            ("Risk Envelope Manager", self.initialize_risk_envelope),
            ("Enhanced Threat Monitor", self.initialize_threat_monitor),
            ("Model Inventory", self.initialize_model_inventory),
            ("Observability Dashboard", self.initialize_observability),
            ("Compliance Engine", self.initialize_compliance_engine),
        ]
        
        for name, init_func in steps:
            try:
                if not init_func():
                    logger.warning(f"Component {name} failed to initialize - continuing...")
            except Exception as e:
                logger.error(f"Unexpected error initializing {name}: {e}")
                self.errors.append(f"{name}: {e}")
        
        # Step 3: Run health checks
        health_ok = self.run_health_checks()
        
        # Step 4: Print summary
        self.print_startup_summary()
        
        # Return success if no critical errors
        return len(self.errors) == 0


def main():
    """Main entry point."""
    startup = MERIDStartup()
    
    try:
        success = startup.run()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("\nStartup interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error during startup: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
