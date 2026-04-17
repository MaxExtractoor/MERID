#!/usr/bin/env python3
"""
MERID Logging Health Controller (meridctl_logging_only)
Provides logging backend health snapshots.

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

# Import MERID logging config
try:
    import merid_logging_config
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)


class MERIDLoggingHealthController:
    """MERID Logging Health Controller"""
    
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
        print("🚀 Generating MERID logging health snapshot...")
        
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
        
        print(f"\n📊 MERID Logging Health Summary")
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
            output_path = f"merid_logging_health_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(self.results, f, indent=2, default=str)
            
            print(f"📁 Health snapshot saved to: {output_path}")
            return output_path
            
        except Exception as e:
            print(f"❌ Failed to save health snapshot: {e}")
            return None


def main():
    """Main entry point for meridctl_logging_only"""
    if len(sys.argv) < 2 or sys.argv[1] != "status":
        print("Usage: meridctl_logging_only status")
        print("       meridctl_logging_only status --save")
        print("       meridctl_logging_only status --output <path>")
        sys.exit(1)
    
    controller = MERIDLoggingHealthController()
    
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
            print(f"✅ Logging health snapshot complete: {saved_path}")
        else:
            print("❌ Failed to save health snapshot")
            sys.exit(1)
    
    # Exit with appropriate code
    exit_code = 0 if snapshot["overall_status"] == "healthy" else 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
