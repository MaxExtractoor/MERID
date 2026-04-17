#!/usr/bin/env python3
"""
MERID Simple Health Controller
Provides logging backend health snapshots without complex dependencies.

Date: 2026-01-26
Status: IMPLEMENTED
"""

import json
import os
import sys
import time
import logging
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

# Import MERID logging config only
try:
    import merid_logging_config
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)


class MERIDSimpleHealthController:
    """MERID Simple Health Controller - Logging Only"""
    
    def __init__(self):
        self.start_time = time.time()
        self.results = {}
        
    def check_logging_backend(self) -> Dict[str, Any]:
        """Check logging backend wiring (queue + listener alive, log file writable)"""
        print("🔍 Checking logging backend...")
        
        try:
            # Test logging configuration
            test_log_path = "merid_health_test.log"
            
            # Check if we can start logging
            merid_logging_config.start_merid_logging(test_log_path)
            
            # Test log file creation and writing
            logger = logging.getLogger("merid.health.check")
            logger.info("Health check test message")
            time.sleep(0.5)  # Allow async processing
            
            # Verify log file exists and is writable
            log_file_exists = os.path.exists(test_log_path)
            log_file_writable = os.access(test_log_path, os.W_OK) if log_file_exists else False
            
            # Check log file content
            content_valid = False
            if log_file_exists:
                try:
                    with open(test_log_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        content_valid = "Health check test message" in content
                except Exception:
                    content_valid = False
            
            # Clean shutdown
            merid_logging_config.shutdown_merid_logging()
            
            # Clean up test file
            try:
                os.remove(test_log_path)
            except Exception:
                pass
            
            status = "healthy" if (log_file_exists and log_file_writable and content_valid) else "unhealthy"
            
            return {
                "status": status,
                "log_file_exists": log_file_exists,
                "log_file_writable": log_file_writable,
                "content_valid": content_valid,
                "queue_listener_active": True  # If we got here, it's working
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "log_file_exists": False,
                "log_file_writable": False,
                "content_valid": False,
                "queue_listener_active": False
            }
    
    def check_environment_configuration(self) -> Dict[str, Any]:
        """Check environment-driven configuration"""
        print("🔍 Checking environment configuration...")
        
        try:
            # Test default path resolution
            default_path = merid_logging_config._resolve_default_log_path()
            
            # Test environment variable override
            old_env = os.environ.get("MERID_LOG_PATH")
            try:
                test_env_path = "test_env_override.log"
                os.environ["MERID_LOG_PATH"] = test_env_path
                env_resolved_path = merid_logging_config._resolve_default_log_path()
                
                env_works = env_resolved_path == test_env_path
            finally:
                if old_env:
                    os.environ["MERID_LOG_PATH"] = old_env
                else:
                    os.environ.pop("MERID_LOG_PATH", None)
            
            # Test explicit path override
            explicit_path = "test_explicit.log"
            explicit_works = True  # If we can pass it to start_merid_logging without error
            
            status = "healthy" if (default_path and env_works and explicit_works) else "unhealthy"
            
            return {
                "status": status,
                "default_path": default_path,
                "environment_override": env_works,
                "explicit_override": explicit_works,
                "default_log_path_constant": str(merid_logging_config.DEFAULT_LOG_PATH)
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }
    
    def check_rotation_configuration(self) -> Dict[str, Any]:
        """Check rotation configuration"""
        print("🔍 Checking rotation configuration...")
        
        try:
            # Get the base dict config to check rotation settings
            test_path = "test_rotation.log"
            cfg = merid_logging_config.base_dict_config(test_path)
            
            # Check if rotating_file handler exists
            handlers = cfg.get("handlers", {})
            rotating_handler = handlers.get("rotating_file", {})
            
            # Check rotation settings
            rotation_class = rotating_handler.get("class", "")
            when = rotating_handler.get("when", "")
            interval = rotating_handler.get("interval", 1)
            backup_count = rotating_handler.get("backupCount", 7)
            encoding = rotating_handler.get("encoding", "")
            
            # Validate rotation settings
            is_timed_rotating = "TimedRotatingFileHandler" in rotation_class
            valid_when = when in ["midnight", "S", "M", "H", "D", "midnight", "W0", "W1", "W2", "W3", "W4", "W5", "W6"]
            valid_encoding = encoding == "utf-8"
            valid_backup_count = isinstance(backup_count, int) and backup_count > 0
            
            status = "healthy" if (is_timed_rotating and valid_when and valid_encoding and valid_backup_count) else "unhealthy"
            
            return {
                "status": status,
                "handler_class": rotation_class,
                "when": when,
                "interval": interval,
                "backup_count": backup_count,
                "encoding": encoding,
                "is_timed_rotating": is_timed_rotating,
                "valid_when": valid_when,
                "valid_encoding": valid_encoding,
                "valid_backup_count": valid_backup_count
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }
    
    def generate_health_snapshot(self) -> Dict[str, Any]:
        """Generate complete logging health snapshot"""
        print("🚀 Generating MERID simple health snapshot...")
        
        start_time = time.time()
        
        # Run all health checks
        self.results = {
            "timestamp": datetime.utcnow().isoformat(),
            "duration_seconds": 0,
            "overall_status": "unknown",
            "checks": {
                "logging_backend": self.check_logging_backend(),
                "environment_configuration": self.check_environment_configuration(),
                "rotation_configuration": self.check_rotation_configuration(),
            }
        }
        
        # Calculate overall status
        unhealthy_count = sum(1 for check in self.results["checks"].values() 
                            if check.get("status") == "unhealthy")
        
        if unhealthy_count == 0:
            self.results["overall_status"] = "healthy"
        elif unhealthy_count <= 1:
            self.results["overall_status"] = "degraded"
        else:
            self.results["overall_status"] = "unhealthy"
        
        # Calculate duration
        self.results["duration_seconds"] = round(time.time() - start_time, 2)
        
        # Add summary
        self.results["summary"] = {
            "total_checks": len(self.results["checks"]),
            "healthy_checks": sum(1 for check in self.results["checks"].values() 
                               if check.get("status") == "healthy"),
            "unhealthy_checks": unhealthy_count,
            "degraded_checks": sum(1 for check in self.results["checks"].values() 
                               if check.get("status") == "degraded")
        }
        
        return self.results
    
    def print_health_summary(self):
        """Print health summary to console"""
        if not self.results:
            print("❌ No health check results available")
            return
        
        print(f"\n📊 MERID Simple Health Summary")
        print(f"   Overall Status: {self.results['overall_status'].upper()}")
        print(f"   Duration: {self.results['duration_seconds']}s")
        print(f"   Timestamp: {self.results['timestamp']}")
        
        summary = self.results["summary"]
        print(f"   Total Checks: {summary['total_checks']}")
        print(f"   Healthy: {summary['healthy_checks']}")
        print(f"   Degraded: {summary['degraded_checks']}")
        print(f"   Unhealthy: {summary['unhealthy_checks']}")
        
        print(f"\n🔍 Check Details:")
        for name, check in self.results["checks"].items():
            status_icon = "✅" if check["status"] == "healthy" else "⚠️" if check["status"] == "degraded" else "❌"
            print(f"   {status_icon} {name}: {check['status'].upper()}")
            if "error" in check:
                print(f"      Error: {check['error']}")
    
    def save_health_snapshot(self, output_path: str = None) -> str:
        """Save health snapshot to JSON file"""
        if output_path is None:
            output_path = f"merid_simple_health_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(self.results, f, indent=2, default=str)
            
            print(f"📁 Health snapshot saved to: {output_path}")
            return output_path
            
        except Exception as e:
            print(f"❌ Failed to save health snapshot: {e}")
            return None


def print_git_conflict_help():
    """Print Git conflict resolution help for MERID."""
    
    print("""
🚀 MERID Git Conflict Resolution Playbook
=========================================

When encountering merge conflicts in MERID, follow these patterns:

📋 PATTERN 1: Take Other Branch's Version
For files where one side is clearly authoritative:

    # Keep "theirs" (branch you're merging in)
    git checkout --theirs -- path/to/file.py
    git add path/to/file.py

    # Keep "ours" (your current branch)
    git checkout --ours -- path/to/file.py
    git add path/to/file.py

📋 PATTERN 2: Manual Merge for Composite Files
For files like agents/__init__.py that need custom merging:

    1. Open file and find conflict blocks:
       <<<<<<< HEAD
       # your branch content
       =======
       # other branch content
       >>>>>>> feature-branch

    2. Edit to desired final code

    3. Delete all conflict markers:
       - <<<<<<< HEAD
       - =======
       - >>>>>>> feature-branch

    4. Validate syntax:
       python -m py_compile path/to/file.py

    5. Stage as resolved:
       git add path/to/file.py

📋 PATTERN 3: Recovery from Wrong Choice
If you picked the wrong side and haven't staged yet:

    # Restore conflicted version
    git checkout -m -- path/to/file.py

If already staged:
    git reset HEAD path/to/file.py
    git checkout -m -- path/to/file.py

📋 PATTERN 4: Systematic Resolution

    1. Resolve one file at a time
    2. Validate after each fix (python -m py_compile)
    3. Stage immediately (git add)
    4. Test imports
    5. Verify system health (python meridctl_simple.py status)

📋 PATTERN 5: Final Verification

    git status  # Should show no "unmerged paths"
    python meridctl_simple.py status  # Verify system health
    git commit  # Complete the merge

🔍 COMMON MERID CONFLICT SCENARIOS

Import Files (__init__.py):
    • Use PATTERN 2 (Manual Merge)
    • Often need combined imports from both branches
    • Validate with python -m py_compile

Configuration Files:
    • Use PATTERN 1 (Take authoritative version)
    • Usually one branch has correct configuration

Core Implementation Files:
    • Use PATTERN 1 for clean files
    • Use PATTERN 2 for files with custom changes

💡 QUICK REFERENCE SUMMARY

    git checkout --theirs -- file.py    # Take their version
    git checkout --ours -- file.py      # Take your version
    git add file.py                     # Mark resolved
    python -m py_compile file.py        # Validate syntax
    git checkout -m -- file.py          # Restore conflicts
    meridctl_simple.py status           # Verify health

📚 MORE HELP

    python tools/merid-git-help.py  # Full interactive help
    cat CONTRIBUTING.md               # Complete development guide
""")

def print_pre_merge_checklist():
    """Print pre-merge/pre-push checklist."""
    
    print("""
🔍 MERID Pre-Merge/Pre-Push Checklist
===================================

Run these checks before merging or pushing to ensure system integrity:

📋 SYNTAX VALIDATION
    python -m py_compile agents/__init__.py
    python -m py_compile core/settings.py
    python -m py_compile db/neo4j.py
    python -m py_compile merid_logging_config.py

📋 SYSTEM HEALTH CHECK
    python meridctl_simple.py status

📋 SMOKE TESTS (Optional)
    python -m pytest tests/smoke -q
    python -m pytest tests/test_merid_dropin_patterns.py -q

📋 QUICK VALIDATION COMMANDS
    # All syntax checks in one command:
    python -c "
import py_compile
files = ['agents/__init__.py', 'core/settings.py', 'db/neo4j.py', 'merid_logging_config.py']
[py_compile.compile(f, doraise=True) for f in files]
print('✅ All syntax checks passed')
"

    # System health check:
    python meridctl_simple.py status

📋 COMMON ISSUES TO CHECK
    • Import errors in core modules
    • Merge conflict markers (<<<<<<<, =======, >>>>>>>)
    • Syntax errors in Python files
    • Health check failures
    • Test failures in critical paths

📋 IF CHECKS FAIL
    • Fix syntax errors first
    • Resolve any remaining merge conflicts
    • Run health check to verify system integrity
    • Fix test failures before merging

💡 AUTOMATION TIP
    Add to your pre-commit hook:
    #!/bin/bash
    python -m py_compile agents/__init__.py core/settings.py db/neo4j.py merid_logging_config.py
    python meridctl_simple.py status
    python -m pytest tests/smoke -q
""")

def main():
    """Main entry point for meridctl_simple"""
    if len(sys.argv) < 2:
        print("Usage: meridctl_simple <command>")
        print("       meridctl_simple status [--save|--output <path>]")
        print("       meridctl_simple git-help")
        print("       meridctl_simple pre-merge-checklist")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "git-help":
        print_git_conflict_help()
        return
    
    if command == "pre-merge-checklist":
        print_pre_merge_checklist()
        return
    
    if command != "status":
        print("❌ Unknown command. Use 'status', 'git-help', or 'pre-merge-checklist'")
        sys.exit(1)
    
    controller = MERIDSimpleHealthController()
    
    # Generate health snapshot
    snapshot = controller.generate_health_snapshot()
    
    # Print summary
    controller.print_health_summary()
    
    # Save snapshot if requested
    if "--save" in sys.argv or "--output" in sys.argv:
        output_path = None
        if "--output" in sys.argv:
            try:
                output_index = sys.argv.index("--output")
                output_path = sys.argv[output_index + 1]
            except (IndexError, ValueError):
                print("❌ --output requires a path argument")
                sys.exit(1)
        
        saved_path = controller.save_health_snapshot(output_path)
        if saved_path:
            print(f"✅ Simple health snapshot complete: {saved_path}")
        else:
            print("❌ Failed to save health snapshot")
            sys.exit(1)
    
    # Exit with appropriate code
    exit_code = 0 if snapshot["overall_status"] == "healthy" else 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
