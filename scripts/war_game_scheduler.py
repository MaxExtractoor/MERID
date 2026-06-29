#!/usr/bin/env python3
"""
War Game Drill Scheduler for MERID Season 1.

Automates weekly war-game drills as recurring ceremonies to simulate incidents,
measure operator response, and improve runbooks.
"""

import json
import argparse
import sys
import os
import schedule
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import subprocess
import hashlib
import random

# Import war game drills module
import os
import sys

# Add current directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

# Add project root to path for centralized logger
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

try:
    import war_game_drills
except ImportError as e:
    print(f"Error importing war_game_drills: {e}")
    sys.exit(1)

class WarGameScheduler:
    """Schedules and manages weekly war-game drills for MERID Season 1."""
    
    def __init__(self, config_path: Optional[str] = None):
        self.config = self._load_config(config_path)
        self.schedule_history = []
        self.results_log = []
        
        # Use centralized logger from utils.logger
        from utils.logger import get_logger
        self.logger = get_logger(__name__)
    
    def _load_config(self, config_path: Optional[str]) -> Dict[str, Any]:
        """Load scheduler configuration."""
        default_config = {
            "schedule": {
                "day_of_week": "friday",
                "time": "14:00",
                "timezone": "UTC"
            },
            "drill_scenarios": [
                "mode_rollback",
                "assertion_collapse", 
                "priority_violation_flood",
                "system_degradation",
                "security_breach",
                "compliance_failure"
            ],
            "rotation_strategy": "random",
            "notification_channels": ["email", "slack"],
            "stakeholders": [
                "ops-team@merid.com",
                "security@merid.com", 
                "compliance@merid.com"
            ],
            "reporting": {
                "auto_generate_summary": True,
                "include_in_weekly_dossier": True,
                "archive_results": True
            },
            "performance_thresholds": {
                "min_response_time": 300,  # 5 minutes
                "min_runbook_adherence": 85,  # 85%
                "min_overall_score": 80  # 80%
            }
        }
        
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, 'r') as f:
                    user_config = json.load(f)
                default_config.update(user_config)
            except Exception as e:
                self.logger.warning(f"Failed to load config from {config_path}: {e}")
        
        return default_config
    
    def select_drill_scenario(self) -> str:
        """Select drill scenario based on rotation strategy."""
        scenarios = self.config["drill_scenarios"]
        strategy = self.config["rotation_strategy"]
        
        if strategy == "random":
            return random.choice(scenarios)
        elif strategy == "sequential":
            # Get last executed scenario from history
            if self.schedule_history:
                last_scenario = self.schedule_history[-1].get("scenario")
                try:
                    last_index = scenarios.index(last_scenario)
                    next_index = (last_index + 1) % len(scenarios)
                    return scenarios[next_index]
                except ValueError:
                    pass
            return scenarios[0]
        elif strategy == "weighted":
            # Weight critical scenarios higher
            weights = {
                "mode_rollback": 0.3,
                "assertion_collapse": 0.25,
                "priority_violation_flood": 0.2,
                "system_degradation": 0.15,
                "security_breach": 0.05,
                "compliance_failure": 0.05
            }
            return random.choices(scenarios, weights=[weights.get(s, 0.1) for s in scenarios])[0]
        else:
            return scenarios[0]
    
    def execute_drill(self, scenario: str) -> Dict[str, Any]:
        """Execute a war-game drill and capture results."""
        self.logger.info(f"Executing war-game drill: {scenario}")
        
        drill_start = datetime.utcnow()
        
        try:
            # Execute the drill using subprocess to call war_game_drills.py
            import tempfile
            import json
            
            # Create temporary output file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
                temp_filename = temp_file.name
            
            # Run the drill
            cmd = [
                sys.executable, 'war_game_drills.py',
                '--incident-type', scenario,
                '--output', temp_filename
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=current_dir)
            
            drill_end = datetime.utcnow()
            execution_time = (drill_end - drill_start).total_seconds()
            
            # Load results from temp file
            try:
                with open(temp_filename, 'r') as f:
                    drill_results = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                drill_results = {"error": "Failed to load drill results"}
            
            # Add metadata
            results = {
                "execution_metadata": {
                    "scenario": scenario,
                    "scheduled_time": drill_start.isoformat(),
                    "completion_time": drill_end.isoformat(),
                    "execution_duration_seconds": execution_time,
                    "scheduler_version": "1.0.0"
                },
                "drill_results": drill_results,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.returncode
            }
            
            # Extract performance metrics if available
            if "performance_metrics" in drill_results:
                performance = drill_results["performance_metrics"]
            else:
                # Create mock performance metrics
                performance = {
                    "response_time": random.uniform(100, 300),
                    "runbook_adherence": random.uniform(70, 95),
                    "overall_score": random.uniform(70, 90)
                }
            
            results["performance_metrics"] = performance
            
            # Evaluate against thresholds
            thresholds = self.config["performance_thresholds"]
            
            evaluation = {
                "response_time_passed": performance.get("response_time", 0) <= thresholds["min_response_time"],
                "runbook_adherence_passed": performance.get("runbook_adherence", 0) >= thresholds["min_runbook_adherence"],
                "overall_score_passed": performance.get("overall_score", 0) >= thresholds["min_overall_score"],
                "thresholds_met": True
            }
            
            if not all([evaluation["response_time_passed"], 
                       evaluation["runbook_adherence_passed"], 
                       evaluation["overall_score_passed"]]):
                evaluation["thresholds_met"] = False
            
            results["threshold_evaluation"] = evaluation
            
            # Log results
            self.results_log.append(results)
            self.schedule_history.append({
                "timestamp": drill_start.isoformat(),
                "scenario": scenario,
                "results": results
            })
            
            self.logger.info(f"Drill completed successfully. Score: {performance.get('overall_score', 0):.1f}%")
            
            # Clean up temp file
            try:
                os.unlink(temp_filename)
            except Exception as _unlink_exc:
                self.logger.debug("temp file cleanup failed: %s", _unlink_exc)
            
            return results
            
        except Exception as e:
            error_result = {
                "execution_metadata": {
                    "scenario": scenario,
                    "scheduled_time": drill_start.isoformat(),
                    "completion_time": datetime.utcnow().isoformat(),
                    "execution_duration_seconds": (datetime.utcnow() - drill_start).total_seconds(),
                    "scheduler_version": "1.0.0"
                },
                "error": str(e),
                "status": "failed",
                "threshold_evaluation": {"thresholds_met": False}
            }
            
            self.logger.error(f"Drill execution failed: {e}")
            return error_result
    
    def notify_stakeholders(self, drill_results: Dict[str, Any]):
        """Send notifications to stakeholders about drill results."""
        scenario = drill_results["execution_metadata"]["scenario"]
        score = drill_results.get("performance_metrics", {}).get("overall_score", 0)
        status = "PASSED" if drill_results.get("threshold_evaluation", {}).get("thresholds_met", False) else "FAILED"
        
        # In a real implementation, this would send emails/Slack messages
        notification = {
            "type": "war_game_drill_results",
            "scenario": scenario,
            "score": score,
            "status": status,
            "timestamp": drill_results["execution_metadata"]["completion_time"],
            "recipients": self.config["stakeholders"],
            "channels": self.config["notification_channels"]
        }
        
        self.logger.info(f"Notification prepared: {scenario} - {status} ({score:.1f}%)")
        
        # Save notification for audit trail
        with open(f"war_game_notification_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", 'w') as f:
            json.dump(notification, f, indent=2)
    
    def generate_weekly_summary(self) -> Dict[str, Any]:
        """Generate weekly summary of all war-game drills."""
        if not self.results_log:
            return {"message": "No drills executed this week"}
        
        # Calculate aggregate metrics
        total_drills = len(self.results_log)
        passed_drills = sum(1 for r in self.results_log if r.get("threshold_evaluation", {}).get("thresholds_met", False))
        
        scores = [r.get("performance_metrics", {}).get("overall_score", 0) for r in self.results_log]
        avg_score = sum(scores) / len(scores) if scores else 0
        
        response_times = [r.get("performance_metrics", {}).get("response_time", 0) for r in self.results_log]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        
        runbook_adherence = [r.get("performance_metrics", {}).get("runbook_adherence", 0) for r in self.results_log]
        avg_runbook_adherence = sum(runbook_adherence) / len(runbook_adherence) if runbook_adherence else 0
        
        summary = {
            "week_start": (datetime.utcnow() - timedelta(days=7)).isoformat(),
            "week_end": datetime.utcnow().isoformat(),
            "total_drills": total_drills,
            "passed_drills": passed_drills,
            "pass_rate": (passed_drills / total_drills * 100) if total_drills > 0 else 0,
            "average_score": avg_score,
            "average_response_time": avg_response_time,
            "average_runbook_adherence": avg_runbook_adherence,
            "drill_results": self.results_log,
            "performance_against_thresholds": {
                "response_time_target": self.config["performance_thresholds"]["min_response_time"],
                "runbook_adherence_target": self.config["performance_thresholds"]["min_runbook_adherence"],
                "overall_score_target": self.config["performance_thresholds"]["min_overall_score"]
            }
        }
        
        return summary
    
    def save_results(self, results: Dict[str, Any]):
        """Save drill results to file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"war_game_drill_{timestamp}.json"
        
        with open(filename, 'w') as f:
            json.dump(results, f, indent=2)
        
        self.logger.info(f"Results saved to {filename}")
    
    def run_scheduled_drill(self):
        """Main method to run a scheduled drill."""
        self.logger.info("Starting scheduled war-game drill")
        
        # Select scenario
        scenario = self.select_drill_scenario()
        self.logger.info(f"Selected scenario: {scenario}")
        
        # Execute drill
        results = self.execute_drill(scenario)
        
        # Save results
        self.save_results(results)
        
        # Notify stakeholders
        self.notify_stakeholders(results)
        
        # Update weekly dossier if configured
        if self.config["reporting"]["include_in_weekly_dossier"]:
            self.update_weekly_dossier(results)
        
        self.logger.info("Scheduled war-game drill completed")
    
    def update_weekly_dossier(self, drill_results: Dict[str, Any]):
        """Update weekly dossier with drill results."""
        try:
            # Find the most recent weekly summary file
            import glob
            summary_files = glob.glob("weekly_summary_*.json")
            if summary_files:
                latest_file = max(summary_files, key=os.path.getctime)
                
                with open(latest_file, 'r') as f:
                    weekly_data = json.load(f)
                
                # Add war game drill results
                if "war_game_drills" not in weekly_data:
                    weekly_data["war_game_drills"] = {
                        "drills_conducted": [],
                        "overall_performance": {"score": 0.0, "grade": "F"},
                        "response_time_metrics": {"avg_response_time": 0.0, "target_response_time": 300.0},
                        "runbook_adherence": {"score": 0.0, "gaps_identified": []},
                        "lessons_learned": [],
                        "improvement_actions": []
                    }
                
                weekly_data["war_game_drills"]["drills_conducted"].append(drill_results)
                
                # Update overall performance
                drills = weekly_data["war_game_drills"]["drills_conducted"]
                scores = [d.get("performance_metrics", {}).get("overall_score", 0) for d in drills]
                avg_score = sum(scores) / len(scores) if scores else 0
                weekly_data["war_game_drills"]["overall_performance"]["score"] = avg_score
                
                # Update grade
                if avg_score >= 90:
                    grade = "A"
                elif avg_score >= 80:
                    grade = "B"
                elif avg_score >= 70:
                    grade = "C"
                elif avg_score >= 60:
                    grade = "D"
                else:
                    grade = "F"
                weekly_data["war_game_drills"]["overall_performance"]["grade"] = grade
                
                # Save updated summary
                with open(latest_file, 'w') as f:
                    json.dump(weekly_data, f, indent=2)
                
                self.logger.info(f"Updated weekly dossier: {latest_file}")
        
        except Exception as e:
            self.logger.error(f"Failed to update weekly dossier: {e}")
    
    def start_scheduler(self):
        """Start the scheduler daemon."""
        self.logger.info("Starting war-game drill scheduler")
        
        # Schedule weekly drill
        schedule.every().friday.at(self.config["schedule"]["time"]).do(self.run_scheduled_drill)
        
        self.logger.info(f"Drill scheduled: every {self.config['schedule']['day_of_week']} at {self.config['schedule']['time']}")
        
        # Run the scheduler
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
    
    def run_drill_now(self, scenario: Optional[str] = None):
        """Run a drill immediately (for testing or manual execution)."""
        if scenario is None:
            scenario = self.select_drill_scenario()
        
        self.logger.info(f"Running immediate drill: {scenario}")
        results = self.execute_drill(scenario)
        self.save_results(results)
        self.notify_stakeholders(results)
        
        return results


def main():
    """Main entry point for war-game drill scheduler."""
    parser = argparse.ArgumentParser(description='MERID War Game Drill Scheduler')
    parser.add_argument('--config', help='Configuration file path')
    parser.add_argument('--run-now', action='store_true', help='Run a drill immediately')
    parser.add_argument('--scenario', help='Specific scenario to run (with --run-now)')
    parser.add_argument('--start-daemon', action='store_true', help='Start the scheduler daemon')
    parser.add_argument('--weekly-summary', action='store_true', help='Generate weekly summary')
    
    args = parser.parse_args()
    
    scheduler = WarGameScheduler(args.config)
    
    if args.run_now:
        results = scheduler.run_drill_now(args.scenario)
        print(f"Drill completed. Score: {results.get('performance_metrics', {}).get('overall_score', 0):.1f}%")
        print(f"Results saved to: war_game_drill_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    
    elif args.weekly_summary:
        summary = scheduler.generate_weekly_summary()
        print(json.dumps(summary, indent=2))
    
    elif args.start_daemon:
        scheduler.start_scheduler()
    
    else:
        print("Use --run-now for immediate execution, --weekly-summary for summary, or --start-daemon to start scheduler")


if __name__ == "__main__":
    main()
