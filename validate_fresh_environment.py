#!/usr/bin/env python3
"""
MERID Fresh Environment Validation Script

Validates complete MERID installation on a clean machine.
Captures golden baseline logs for future comparison.

Run this on a fresh VM/machine after initial setup to verify
all components work without manual intervention.
"""

import os
import sys
import subprocess
import logging
from pathlib import Path
from datetime import datetime
import json

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FreshEnvironmentValidator:
    """Validates MERID installation on fresh environment."""
    
    def __init__(self):
        self.validation_time = datetime.now()
        self.results = {
            "timestamp": self.validation_time.isoformat(),
            "checks": [],
            "passed": 0,
            "failed": 0,
            "warnings": 0
        }
        self.golden_logs_dir = Path("logs/golden_baseline")
        self.golden_logs_dir.mkdir(parents=True, exist_ok=True)
    
    def check_python_version(self) -> bool:
        """Verify Python version is 3.11+."""
        logger.info("Checking Python version...")
        
        version = sys.version_info
        required = (3, 11)
        
        if version >= required:
            logger.info(f"✓ Python {version.major}.{version.minor}.{version.micro}")
            self._record_check("Python Version", True, f"{version.major}.{version.minor}.{version.micro}")
            return True
        else:
            logger.error(f"✗ Python {version.major}.{version.minor} (required: 3.11+)")
            self._record_check("Python Version", False, f"{version.major}.{version.minor}", "Python 3.11+ required")
            return False
    
    def check_virtual_environment(self) -> bool:
        """Verify running in virtual environment."""
        logger.info("Checking virtual environment...")
        
        in_venv = hasattr(sys, 'real_prefix') or (
            hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
        )
        
        if in_venv:
            logger.info(f"✓ Virtual environment active: {sys.prefix}")
            self._record_check("Virtual Environment", True, sys.prefix)
            return True
        else:
            logger.warning("⚠ Not in virtual environment (recommended)")
            self._record_check("Virtual Environment", True, "Not active", "Recommended but not required")
            self.results["warnings"] += 1
            return True
    
    def check_required_packages(self) -> bool:
        """Verify required packages are installed."""
        logger.info("Checking required packages...")
        
        required = [
            "neo4j",
            "fastapi",
            "uvicorn",
            "pydantic",
            "aiohttp",
        ]
        
        missing = []
        for package in required:
            try:
                __import__(package)
                logger.info(f"  ✓ {package}")
            except ImportError:
                logger.error(f"  ✗ {package} not found")
                missing.append(package)
        
        if not missing:
            self._record_check("Required Packages", True, f"{len(required)} packages installed")
            return True
        else:
            self._record_check("Required Packages", False, f"{len(missing)} missing", f"Missing: {', '.join(missing)}")
            return False
    
    def check_environment_variables(self) -> bool:
        """Verify required environment variables are set."""
        logger.info("Checking environment variables...")
        
        required = [
            "NEO4J_URI",
            "NEO4J_USER",
            "NEO4J_PASSWORD",
        ]
        
        missing = []
        for var in required:
            if os.getenv(var):
                logger.info(f"  ✓ {var}")
            else:
                logger.error(f"  ✗ {var} not set")
                missing.append(var)
        
        if not missing:
            self._record_check("Environment Variables", True, f"{len(required)} variables set")
            return True
        else:
            self._record_check("Environment Variables", False, f"{len(missing)} missing", f"Missing: {', '.join(missing)}")
            return False
    
    def check_directory_structure(self) -> bool:
        """Verify required directories exist."""
        logger.info("Checking directory structure...")
        
        required_dirs = [
            "core",
            "agents",
            "trading",
            "web",
            "logs",
            "tests",
        ]
        
        missing = []
        for dir_name in required_dirs:
            if Path(dir_name).exists():
                logger.info(f"  ✓ {dir_name}/")
            else:
                logger.error(f"  ✗ {dir_name}/ not found")
                missing.append(dir_name)
        
        if not missing:
            self._record_check("Directory Structure", True, f"{len(required_dirs)} directories present")
            return True
        else:
            self._record_check("Directory Structure", False, f"{len(missing)} missing", f"Missing: {', '.join(missing)}")
            return False
    
    def run_startup_script(self) -> bool:
        """Run startup.py and capture output."""
        logger.info("Running startup.py...")
        
        try:
            result = subprocess.run(
                [sys.executable, "startup.py"],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            # Save golden startup log
            golden_startup = self.golden_logs_dir / f"golden_startup_{self.validation_time.strftime('%Y%m%d_%H%M%S')}.log"
            with open(golden_startup, 'w') as f:
                f.write(result.stdout)
                if result.stderr:
                    f.write("\n=== STDERR ===\n")
                    f.write(result.stderr)
            
            logger.info(f"  Saved golden startup log: {golden_startup}")
            
            # Check for success indicators
            success_indicators = [
                "Components Initialized",
                "Health Checks Passed",
                "MERID IS READY FOR OPERATION"
            ]
            
            all_present = all(indicator in result.stdout for indicator in success_indicators)
            
            if result.returncode == 0 and all_present:
                logger.info("✓ startup.py completed successfully")
                self._record_check("Startup Script", True, "All components initialized", golden_startup.name)
                return True
            else:
                logger.error(f"✗ startup.py failed (exit code: {result.returncode})")
                self._record_check("Startup Script", False, f"Exit code: {result.returncode}", result.stderr[:200] if result.stderr else "Check log")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("✗ startup.py timed out (>60s)")
            self._record_check("Startup Script", False, "Timeout", "Exceeded 60 seconds")
            return False
        except Exception as e:
            logger.error(f"✗ startup.py error: {e}")
            self._record_check("Startup Script", False, "Exception", str(e))
            return False
    
    def run_test_script(self) -> bool:
        """Run run_tests.py and capture output."""
        logger.info("Running run_tests.py...")
        
        try:
            result = subprocess.run(
                [sys.executable, "run_tests.py"],
                capture_output=True,
                text=True,
                timeout=120
            )
            
            # Save golden test log
            golden_tests = self.golden_logs_dir / f"golden_tests_{self.validation_time.strftime('%Y%m%d_%H%M%S')}.log"
            with open(golden_tests, 'w') as f:
                f.write(result.stdout)
                if result.stderr:
                    f.write("\n=== STDERR ===\n")
                    f.write(result.stderr)
            
            logger.info(f"  Saved golden test log: {golden_tests}")
            
            # Check for success indicators
            success_indicators = [
                "7/7 tests passed",
                "ALL TESTS PASSED"
            ]
            
            all_present = all(indicator in result.stdout for indicator in success_indicators)
            
            if result.returncode == 0 and all_present:
                logger.info("✓ run_tests.py completed successfully")
                self._record_check("Test Script", True, "7/7 tests passed", golden_tests.name)
                return True
            else:
                logger.error(f"✗ run_tests.py failed (exit code: {result.returncode})")
                self._record_check("Test Script", False, f"Exit code: {result.returncode}", result.stderr[:200] if result.stderr else "Check log")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("✗ run_tests.py timed out (>120s)")
            self._record_check("Test Script", False, "Timeout", "Exceeded 120 seconds")
            return False
        except Exception as e:
            logger.error(f"✗ run_tests.py error: {e}")
            self._record_check("Test Script", False, "Exception", str(e))
            return False
    
    def _record_check(
        self,
        check_name: str,
        passed: bool,
        details: str,
        notes: str = ""
    ):
        """Record check result."""
        self.results["checks"].append({
            "name": check_name,
            "passed": passed,
            "details": details,
            "notes": notes
        })
        
        if passed:
            self.results["passed"] += 1
        else:
            self.results["failed"] += 1
    
    def save_validation_report(self):
        """Save validation report to JSON."""
        report_path = self.golden_logs_dir / f"validation_report_{self.validation_time.strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(report_path, 'w') as f:
            json.dump(self.results, f, indent=2)
        
        logger.info(f"Validation report saved: {report_path}")
    
    def print_summary(self):
        """Print validation summary."""
        print("\n" + "="*70)
        print("FRESH ENVIRONMENT VALIDATION SUMMARY")
        print("="*70)
        
        print(f"\nTimestamp: {self.results['timestamp']}")
        print(f"Total Checks: {len(self.results['checks'])}")
        print(f"Passed: {self.results['passed']}")
        print(f"Failed: {self.results['failed']}")
        print(f"Warnings: {self.results['warnings']}")
        
        if self.results['failed'] > 0:
            print("\n❌ FAILED CHECKS:")
            for check in self.results['checks']:
                if not check['passed']:
                    print(f"  - {check['name']}: {check['notes']}")
        
        if self.results['warnings'] > 0:
            print("\n⚠️  WARNINGS:")
            for check in self.results['checks']:
                if check.get('notes') and 'Recommended' in check['notes']:
                    print(f"  - {check['name']}: {check['notes']}")
        
        print(f"\nGolden Logs Directory: {self.golden_logs_dir}")
        
        if self.results['failed'] == 0:
            print("\n✅ FRESH ENVIRONMENT VALIDATION PASSED")
            print("   System is ready for deployment")
        else:
            print("\n❌ FRESH ENVIRONMENT VALIDATION FAILED")
            print("   Fix issues before proceeding")
        
        print("="*70 + "\n")
    
    def run_all_checks(self) -> bool:
        """Run all validation checks."""
        logger.info("="*70)
        logger.info("MERID FRESH ENVIRONMENT VALIDATION")
        logger.info("="*70 + "\n")
        
        checks = [
            ("Python Version", self.check_python_version),
            ("Virtual Environment", self.check_virtual_environment),
            ("Required Packages", self.check_required_packages),
            ("Environment Variables", self.check_environment_variables),
            ("Directory Structure", self.check_directory_structure),
            ("Startup Script", self.run_startup_script),
            ("Test Script", self.run_test_script),
        ]
        
        for name, check_func in checks:
            try:
                check_func()
            except Exception as e:
                logger.error(f"Unexpected error in {name}: {e}")
                self._record_check(name, False, "Exception", str(e))
            
            print()  # Blank line between checks
        
        # Save results
        self.save_validation_report()
        
        # Print summary
        self.print_summary()
        
        # Return overall success
        return self.results['failed'] == 0


def main():
    """Main entry point."""
    validator = FreshEnvironmentValidator()
    
    try:
        success = validator.run_all_checks()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("\nValidation interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error during validation: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
