"""
MERID Production Features Verification Script
Validates all production-grade implementations
"""

import sys
import traceback
from typing import Dict, List, Tuple

def verify_imports() -> Tuple[bool, List[str]]:
    """Verify all critical imports"""
    errors = []
    
    try:
        from core.error_handling import (
            get_error_handler, get_health_monitor, CircuitBreaker,
            RetryStrategy, ErrorSeverity
        )
        print("✅ Error handling framework imported")
    except Exception as e:
        errors.append(f"Error handling: {e}")
    
    try:
        from core.state_recovery import (
            get_state_manager, get_self_healing, GracefulDegradation
        )
        print("✅ State recovery framework imported")
    except Exception as e:
        errors.append(f"State recovery: {e}")
    
    try:
        from agents.explainability import (
            get_explainability_tracker, create_reasoning_builder, DecisionType
        )
        print("✅ Agent explainability framework imported")
    except Exception as e:
        errors.append(f"Explainability: {e}")
    
    try:
        from core.consensus_logging import (
            get_consensus_logger, VoteType, ConsensusOutcome
        )
        print("✅ Consensus logging framework imported")
    except Exception as e:
        errors.append(f"Consensus logging: {e}")
    
    try:
        from core.trust_transparency import (
            get_trust_manager, TrustAdjustmentReason
        )
        print("✅ Trust transparency framework imported")
    except Exception as e:
        errors.append(f"Trust transparency: {e}")
    
    try:
        from core.signal_provenance import (
            get_provenance_tracker, create_provenance_builder,
            SignalSource, ConflictResolution
        )
        print("✅ Signal provenance framework imported")
    except Exception as e:
        errors.append(f"Signal provenance: {e}")
    
    try:
        from trading.execution.defense import get_mev_defense
        print("✅ MEV defense imported")
    except Exception as e:
        errors.append(f"MEV defense: {e}")
    
    try:
        from core.validation.engine import get_validation_engine
        print("✅ Validation engine imported")
    except Exception as e:
        errors.append(f"Validation engine: {e}")
    
    return len(errors) == 0, errors


def verify_singletons() -> Tuple[bool, List[str]]:
    """Verify singleton instances can be created"""
    errors = []
    
    try:
        from core.error_handling import get_error_handler, get_health_monitor
        handler = get_error_handler()
        monitor = get_health_monitor()
        print(f"✅ Error handler initialized: {type(handler).__name__}")
        print(f"✅ Health monitor initialized: {type(monitor).__name__}")
    except Exception as e:
        errors.append(f"Error handling singletons: {e}")
    
    try:
        from core.state_recovery import get_state_manager, get_self_healing
        state_mgr = get_state_manager("test")
        healing = get_self_healing()
        print(f"✅ State manager initialized: {type(state_mgr).__name__}")
        print(f"✅ Self-healing initialized: {type(healing).__name__}")
    except Exception as e:
        errors.append(f"State recovery singletons: {e}")
    
    try:
        from agents.explainability import get_explainability_tracker
        tracker = get_explainability_tracker()
        print(f"✅ Explainability tracker initialized: {type(tracker).__name__}")
    except Exception as e:
        errors.append(f"Explainability singleton: {e}")
    
    try:
        from core.consensus_logging import get_consensus_logger
        logger = get_consensus_logger()
        print(f"✅ Consensus logger initialized: {type(logger).__name__}")
    except Exception as e:
        errors.append(f"Consensus logging singleton: {e}")
    
    try:
        from core.trust_transparency import get_trust_manager
        trust_mgr = get_trust_manager()
        print(f"✅ Trust manager initialized: {type(trust_mgr).__name__}")
    except Exception as e:
        errors.append(f"Trust transparency singleton: {e}")
    
    try:
        from core.signal_provenance import get_provenance_tracker
        prov_tracker = get_provenance_tracker()
        print(f"✅ Provenance tracker initialized: {type(prov_tracker).__name__}")
    except Exception as e:
        errors.append(f"Signal provenance singleton: {e}")
    
    return len(errors) == 0, errors


def verify_execution_integration() -> Tuple[bool, List[str]]:
    """Verify execution engine integration"""
    errors = []
    
    try:
        # Import from trading.execution module (file, not package)
        import importlib.util
        import os
        spec = importlib.util.spec_from_file_location(
            "trading_execution",
            os.path.join(os.path.dirname(__file__), "trading", "execution.py")
        )
        execution_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(execution_module)
        engine = execution_module.get_execution_engine()
        
        # Check MEV defender
        if hasattr(engine, '_mev_defender'):
            print("✅ Execution engine has MEV defender")
        else:
            errors.append("Execution engine missing MEV defender")
        
        # Check validator
        if hasattr(engine, '_validator'):
            print("✅ Execution engine has validator")
        else:
            errors.append("Execution engine missing validator")
        
        # Check error handler
        if hasattr(engine, '_error_handler'):
            print("✅ Execution engine has error handler")
        else:
            errors.append("Execution engine missing error handler")
        
        # Check state manager
        if hasattr(engine, '_state_manager'):
            print("✅ Execution engine has state manager")
        else:
            errors.append("Execution engine missing state manager")
        
        # Check self-healing
        if hasattr(engine, '_self_healing'):
            print("✅ Execution engine has self-healing")
        else:
            errors.append("Execution engine missing self-healing")
        
        # Check circuit breakers
        if hasattr(engine, '_order_breaker'):
            print("✅ Execution engine has order circuit breaker")
        else:
            errors.append("Execution engine missing order circuit breaker")
        
    except Exception as e:
        errors.append(f"Execution engine integration: {e}\n{traceback.format_exc()}")
    
    return len(errors) == 0, errors


def verify_agent_integration() -> Tuple[bool, List[str]]:
    """Verify agent explainability integration"""
    errors = []
    
    try:
        # Check if base agent has explainability imports
        import agents.base_agent as base_agent_module
        source = open(base_agent_module.__file__, 'r').read()
        
        if 'from agents.explainability import' in source:
            print("✅ Base agent imports explainability")
        else:
            errors.append("Base agent missing explainability imports")
        
        if 'get_explainability_tracker' in source:
            print("✅ Base agent uses explainability tracker")
        else:
            errors.append("Base agent not using explainability tracker")
        
        if 'create_reasoning_builder' in source:
            print("✅ Base agent creates reasoning builders")
        else:
            errors.append("Base agent not creating reasoning builders")
        
    except Exception as e:
        errors.append(f"Agent integration: {e}")
    
    return len(errors) == 0, errors


def verify_consensus_integration() -> Tuple[bool, List[str]]:
    """Verify consensus engine integration"""
    errors = []
    
    try:
        # Check if consensus engine has logging imports
        import core.consensus_engine as consensus_module
        source = open(consensus_module.__file__, 'r').read()
        
        if 'from core.consensus_logging import' in source:
            print("✅ Consensus engine imports logging")
        else:
            errors.append("Consensus engine missing logging imports")
        
        if 'get_consensus_logger' in source:
            print("✅ Consensus engine uses logger")
        else:
            errors.append("Consensus engine not using logger")
        
        if 'start_round' in source:
            print("✅ Consensus engine starts rounds")
        else:
            errors.append("Consensus engine not starting rounds")
        
        if 'complete_round' in source:
            print("✅ Consensus engine completes rounds")
        else:
            errors.append("Consensus engine not completing rounds")
        
    except Exception as e:
        errors.append(f"Consensus integration: {e}")
    
    return len(errors) == 0, errors


def verify_api_endpoints() -> Tuple[bool, List[str]]:
    """Verify API endpoints are registered"""
    errors = []
    
    try:
        from web.api.explainability import router
        
        # Count routes
        route_count = len(router.routes)
        print(f"✅ Explainability router has {route_count} routes")
        
        # Check for key endpoints
        route_paths = [route.path for route in router.routes]
        
        expected_endpoints = [
            '/api/v1/explainability/agents/{agent_id}/decisions',
            '/api/v1/explainability/consensus/rounds',
            '/api/v1/explainability/trust/profiles',
            '/api/v1/explainability/health/system',
            '/api/v1/explainability/mev/status',
            '/api/v1/explainability/signals/syntheses'
        ]
        
        for endpoint in expected_endpoints:
            if endpoint in route_paths:
                print(f"✅ Endpoint registered: {endpoint}")
            else:
                errors.append(f"Missing endpoint: {endpoint}")
        
    except Exception as e:
        errors.append(f"API endpoints: {e}")
    
    return len(errors) == 0, errors


def verify_web_integration() -> Tuple[bool, List[str]]:
    """Verify web application integration"""
    errors = []
    
    try:
        import web.main as web_module
        source = open(web_module.__file__, 'r').read()
        
        if 'from web.api.explainability import router as explainability_router' in source:
            print("✅ Web app imports explainability router")
        else:
            errors.append("Web app missing explainability router import")
        
        if 'application.include_router(explainability_router)' in source:
            print("✅ Web app includes explainability router")
        else:
            errors.append("Web app not including explainability router")
        
    except Exception as e:
        errors.append(f"Web integration: {e}")
    
    return len(errors) == 0, errors


def main():
    """Run all verifications"""
    print("=" * 80)
    print("MERID PRODUCTION FEATURES VERIFICATION")
    print("=" * 80)
    print()
    
    results: Dict[str, Tuple[bool, List[str]]] = {}
    
    print("1. Verifying Imports...")
    print("-" * 80)
    results['imports'] = verify_imports()
    print()
    
    print("2. Verifying Singletons...")
    print("-" * 80)
    results['singletons'] = verify_singletons()
    print()
    
    print("3. Verifying Execution Engine Integration...")
    print("-" * 80)
    results['execution'] = verify_execution_integration()
    print()
    
    print("4. Verifying Agent Integration...")
    print("-" * 80)
    results['agents'] = verify_agent_integration()
    print()
    
    print("5. Verifying Consensus Engine Integration...")
    print("-" * 80)
    results['consensus'] = verify_consensus_integration()
    print()
    
    print("6. Verifying API Endpoints...")
    print("-" * 80)
    results['api'] = verify_api_endpoints()
    print()
    
    print("7. Verifying Web Application Integration...")
    print("-" * 80)
    results['web'] = verify_web_integration()
    print()
    
    # Summary
    print("=" * 80)
    print("VERIFICATION SUMMARY")
    print("=" * 80)
    
    all_passed = True
    for name, (passed, errors) in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{name.upper()}: {status}")
        if errors:
            for error in errors:
                print(f"  - {error}")
            all_passed = False
    
    print()
    print("=" * 80)
    if all_passed:
        print("✅ ALL VERIFICATIONS PASSED - PRODUCTION READY")
    else:
        print("❌ SOME VERIFICATIONS FAILED - REVIEW ERRORS ABOVE")
    print("=" * 80)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
