#!/usr/bin/env python3
"""
Post-deployment validation script for debate system.
Validates debate-aware behaviors after deployment using health check APIs.
"""

import sys
import os
import time
import json
import asyncio
from datetime import datetime

# Add the web directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'web'))

async def run_post_deploy_validation():
    """Run comprehensive post-deployment validation for debate system."""
    print("🚀 Running Post-Deployment Debate Validation...")
    print("=" * 60)
    
    validation_results = {
        "timestamp": datetime.utcnow().isoformat(),
        "overall_status": "pass",
        "checks": {},
        "failures": [],
        "recommendations": []
    }
    
    try:
        # Import and test health check API
        from web.api.debate_health_api import debate_sla_health_check, post_deploy_validation
        
        print("\n📊 1. SLA Health Check...")
        try:
            sla_results = await debate_sla_health_check()
            validation_results["checks"]["sla_health"] = sla_results
            
            print(f"   Status: {sla_results['status'].upper()}")
            print(f"   Overall Score: {sla_results['overall_score']:.2f}")
            
            if sla_results["violations"]:
                print("   Violations:")
                for violation in sla_results["violations"]:
                    print(f"     ❌ {violation}")
                    validation_results["failures"].append(f"SLA: {violation}")
            
            print("   Individual Checks:")
            for check_name, check_result in sla_results["checks"].items():
                status_icon = "✅" if check_result["status"] == "pass" else "❌"
                print(f"     {status_icon} {check_name}: {check_result['status']}")
            
            if sla_results["status"] == "critical":
                validation_results["overall_status"] = "fail"
            elif sla_results["status"] == "degraded" and validation_results["overall_status"] == "pass":
                validation_results["overall_status"] = "degraded"
                
        except Exception as e:
            error_msg = f"SLA health check failed: {str(e)}"
            print(f"   ❌ {error_msg}")
            validation_results["failures"].append(error_msg)
            validation_results["overall_status"] = "fail"
        
        print("\n🔍 2. Post-Deploy Validation...")
        try:
            deploy_results = await post_deploy_validation()
            validation_results["checks"]["post_deploy"] = deploy_results
            
            print(f"   Status: {deploy_results['status'].upper()}")
            
            if deploy_results["failures"]:
                print("   Failures:")
                for failure in deploy_results["failures"]:
                    print(f"     ❌ {failure}")
                    validation_results["failures"].append(f"Deploy: {failure}")
            
            print("   Validations:")
            for validation_name, validation_result in deploy_results["validations"].items():
                status_icon = "✅" if validation_result["status"] == "pass" else "❌"
                print(f"     {status_icon} {validation_name}: {validation_result['status']}")
            
            if deploy_results["status"] == "critical":
                validation_results["overall_status"] = "fail"
            elif deploy_results["status"] == "fail" and validation_results["overall_status"] == "pass":
                validation_results["overall_status"] = "fail"
                
        except Exception as e:
            error_msg = f"Post-deploy validation failed: {str(e)}"
            print(f"   ❌ {error_msg}")
            validation_results["failures"].append(error_msg)
            validation_results["overall_status"] = "fail"
        
        print("\n🧪 3. Behavioral Smoke Tests...")
        try:
            # Test behavioral enhancements
            from test_behavioral_enhancements import main as behavioral_test_main
            
            # Capture behavioral test results
            print("   Running behavioral smoke tests...")
            behavioral_success = behavioral_test_main()
            
            validation_results["checks"]["behavioral_smoke"] = {
                "status": "pass" if behavioral_success else "fail",
                "success": behavioral_success
            }
            
            status_icon = "✅" if behavioral_success else "❌"
            print(f"   {status_icon} Behavioral smoke tests: {'PASS' if behavioral_success else 'FAIL'}")
            
            if not behavioral_success:
                validation_results["failures"].append("Behavioral smoke tests failed")
                validation_results["overall_status"] = "fail"
                
        except Exception as e:
            error_msg = f"Behavioral smoke tests failed: {str(e)}"
            print(f"   ❌ {error_msg}")
            validation_results["failures"].append(error_msg)
            if validation_results["overall_status"] == "pass":
                validation_results["overall_status"] = "fail"
        
        print("\n⚡ 4. Risk Integration Tests...")
        try:
            # Test risk-side integration
            from test_risk_debate_integration import main as risk_test_main
            
            print("   Running risk-side integration tests...")
            risk_success = risk_test_main()
            
            validation_results["checks"]["risk_integration"] = {
                "status": "pass" if risk_success else "fail",
                "success": risk_success
            }
            
            status_icon = "✅" if risk_success else "❌"
            print(f"   {status_icon} Risk integration tests: {'PASS' if risk_success else 'FAIL'}")
            
            if not risk_success:
                validation_results["failures"].append("Risk integration tests failed")
                validation_results["overall_status"] = "fail"
                
        except Exception as e:
            error_msg = f"Risk integration tests failed: {str(e)}"
            print(f"   ❌ {error_msg}")
            validation_results["failures"].append(error_msg)
            if validation_results["overall_status"] == "pass":
                validation_results["overall_status"] = "fail"
        
        # Generate recommendations
        if validation_results["overall_status"] == "fail":
            validation_results["recommendations"].extend([
                "🚨 CRITICAL: Debate system validation failed - investigate immediately",
                "📋 Check system logs for detailed error information",
                "🔧 Verify all debate services are running and accessible",
                "⚠️ Consider rolling back if critical functionality is broken"
            ])
        elif validation_results["overall_status"] == "degraded":
            validation_results["recommendations"].extend([
                "⚠️ DEGRADED: Debate system partially functional - monitor closely",
                "📊 Review SLA violations and address performance issues",
                "🔍 Check specific failing components for optimization opportunities"
            ])
        else:
            validation_results["recommendations"].extend([
                "✅ SUCCESS: All debate-aware behaviors validated successfully",
                "🚀 System ready for production traffic",
                "📈 Monitor debate metrics for ongoing health"
            ])
        
    except Exception as e:
        critical_error = f"Post-deploy validation system error: {str(e)}"
        print(f"\n🚨 CRITICAL ERROR: {critical_error}")
        validation_results["overall_status"] = "critical"
        validation_results["failures"].append(critical_error)
        validation_results["recommendations"].append("🚨 System-level validation failure - immediate investigation required")
    
    return validation_results

def print_summary(results):
    """Print validation summary and recommendations."""
    print("\n" + "=" * 60)
    print("📋 POST-DEPLOY VALIDATION SUMMARY")
    print("=" * 60)
    
    status_emoji = {
        "pass": "✅",
        "degraded": "⚠️", 
        "fail": "❌",
        "critical": "🚨"
    }
    
    overall_emoji = status_emoji.get(results["overall_status"], "❓")
    print(f"Overall Status: {overall_emoji} {results['overall_status'].upper()}")
    print(f"Timestamp: {results['timestamp']}")
    
    if results["failures"]:
        print(f"\n❌ Failures ({len(results['failures'])}):")
        for i, failure in enumerate(results["failures"], 1):
            print(f"   {i}. {failure}")
    
    if results["recommendations"]:
        print(f"\n💡 Recommendations:")
        for i, recommendation in enumerate(results["recommendations"], 1):
            print(f"   {i}. {recommendation}")
    
    # Print detailed check results
    print(f"\n📊 Detailed Results:")
    for check_name, check_result in results["checks"].items():
        print(f"\n{check_name.upper()}:")
        if isinstance(check_result, dict):
            if "status" in check_result:
                status = check_result["status"]
                emoji = status_emoji.get(status, "❓")
                print(f"   Status: {emoji} {status.upper()}")
            
            if "violations" in check_result and check_result["violations"]:
                print("   Violations:")
                for violation in check_result["violations"]:
                    print(f"     ❌ {violation}")
            
            if "failures" in check_result and check_result["failures"]:
                print("   Failures:")
                for failure in check_result["failures"]:
                    print(f"     ❌ {failure}")
            
            if "success" in check_result:
                print(f"   Success: {check_result['success']}")
        else:
            print(f"   Result: {check_result}")

async def main():
    """Main entry point for post-deployment validation."""
    print("🎯 Debate System Post-Deployment Validation")
    print("Validating debate-aware behaviors after deployment...")
    
    start_time = time.time()
    
    try:
        results = await run_post_deploy_validation()
        print_summary(results)
        
        # Exit with appropriate code
        exit_code = 0 if results["overall_status"] == "pass" else 1
        
        duration = time.time() - start_time
        print(f"\n⏱️  Validation completed in {duration:.2f} seconds")
        
        if exit_code == 0:
            print("🎉 Post-deployment validation PASSED")
        else:
            print("❌ Post-deployment validation FAILED")
        
        return exit_code
        
    except KeyboardInterrupt:
        print("\n⚠️ Validation interrupted by user")
        return 130
    except Exception as e:
        print(f"\n🚨 Unexpected error during validation: {str(e)}")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
