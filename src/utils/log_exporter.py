#!/usr/bin/env python3
"""
MERID Phase 0 Acceptance Test Log Export
Exports structured logs to central store or files
"""

import json
import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path


class LogExporter:
    """Exports structured logs from acceptance tests"""
    
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
    
    def export_test_logs(self, test_id: str, output_file: str = None) -> str:
        """Export logs for a specific test run"""
        if output_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"{self.log_dir}/phase0_acceptance_{timestamp}.jsonl"
        
        # Collect logs from various sources
        log_entries = []
        
        # Add test metadata
        log_entries.append({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": "INFO",
            "service": "log-exporter",
            "event": "test_log_export_started",
            "test_id": test_id,
            "output_file": output_file
        })
        
        # Export to JSONL file
        with open(output_file, 'w') as f:
            for entry in log_entries:
                f.write(json.dumps(entry) + '\n')
        
        print(f"✅ Logs exported to: {output_file}")
        return output_file
    
    def ship_to_central_store(self, log_file: str, endpoint: str = None):
        """Ship logs to central log store"""
        if endpoint is None:
            print("❌ No central log endpoint configured")
            return False
        
        try:
            # Use curl to ship logs (simple approach)
            cmd = [
                "curl", "-X", "POST",
                endpoint,
                "-H", "Content-Type: application/json",
                "--data-binary", f"@{log_file}"
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"✅ Logs shipped to central store: {endpoint}")
                return True
            else:
                print(f"❌ Failed to ship logs: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ Exception shipping logs: {str(e)}")
            return False
    
    def analyze_logs(self, log_file: str) -> dict:
        """Analyze exported logs for key metrics"""
        metrics = {
            "total_events": 0,
            "error_count": 0,
            "http_requests": 0,
            "sql_queries": 0,
            "test_steps": 0,
            "correlation_ids": set()
        }
        
        try:
            with open(log_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        entry = json.loads(line)
                        metrics["total_events"] += 1
                        
                        # Count errors
                        if entry.get("level") == "ERROR":
                            metrics["error_count"] += 1
                        
                        # Count HTTP requests
                        if entry.get("event", "").startswith("http_"):
                            metrics["http_requests"] += 1
                        
                        # Count SQL queries
                        if "sql" in entry.get("event", "").lower():
                            metrics["sql_queries"] += 1
                        
                        # Count test steps
                        if entry.get("event", "").startswith("step_"):
                            metrics["test_steps"] += 1
                        
                        # Collect correlation IDs
                        if "correlation_id" in entry:
                            metrics["correlation_ids"].add(entry["correlation_id"])
                            
                    except json.JSONDecodeError:
                        continue
            
            # Convert set to count
            metrics["correlation_ids"] = len(metrics["correlation_ids"])
            
            return metrics
            
        except Exception as e:
            print(f"❌ Error analyzing logs: {str(e)}")
            return metrics
    
    def generate_report(self, log_file: str, output_file: str = None) -> str:
        """Generate analysis report from logs"""
        if output_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"{self.log_dir}/phase0_analysis_{timestamp}.md"
        
        metrics = self.analyze_logs(log_file)
        
        report = f"""# Phase 0 Acceptance Test Log Analysis

**Generated**: {datetime.now().isoformat()}
**Log File**: {log_file}
**Test ID**: {log_file.split('_')[-2] if '_' in log_file else 'Unknown'}

## 📊 Log Metrics

- **Total Events**: {metrics['total_events']}
- **Error Count**: {metrics['error_count']}
- **HTTP Requests**: {metrics['http_requests']}
- **SQL Queries**: {metrics['sql_queries']}
- **Test Steps**: {metrics['test_steps']}
- **Correlation IDs**: {metrics['correlation_ids']}

## 🎯 Key Findings

"""
        
        if metrics['error_count'] > 0:
            report += f"- ❌ **{metrics['error_count']} errors detected** - needs investigation\n"
        else:
            report += "- ✅ **No errors detected** - test execution clean\n"
        
        if metrics['http_requests'] > 0:
            report += f"- ✅ **{metrics['http_requests']} HTTP requests** - API communication working\n"
        
        if metrics['sql_queries'] > 0:
            report += f"- ✅ **{metrics['sql_queries']} SQL queries** - database activity captured\n"
        
        if metrics['test_steps'] >= 6:
            report += f"- ✅ **{metrics['test_steps']} test steps** - complete test execution\n"
        else:
            report += f"- ❌ **{metrics['test_steps']} test steps** - incomplete test execution\n"
        
        report += f"""
## 🔍 Recommendations

"""
        
        if metrics['error_count'] > 0:
            report += "- Review error logs for service layer issues\n"
        
        if metrics['sql_queries'] == 0:
            report += "- Check database connectivity and logging configuration\n"
        
        if metrics['test_steps'] < 6:
            report += "- Verify test execution completed all steps\n"
        
        # Write report
        with open(output_file, 'w') as f:
            f.write(report)
        
        print(f"✅ Analysis report generated: {output_file}")
        return output_file


def main():
    """Main entry point"""
    exporter = LogExporter()
    
    # Get latest log file
    log_files = list(Path("logs").glob("phase0_acceptance_*.jsonl"))
    if not log_files:
        print("❌ No acceptance test log files found")
        sys.exit(1)
    
    latest_log = max(log_files, key=os.path.getctime)
    print(f"Processing log file: {latest_log}")
    
    # Generate analysis report
    report_file = exporter.generate_report(str(latest_log))
    
    # Optionally ship to central store (if endpoint configured)
    # endpoint = os.getenv("MERID_LOG_ENDPOINT")
    # if endpoint:
    #     exporter.ship_to_central_store(str(latest_log), endpoint)
    
    print(f"✅ Log analysis complete. Report: {report_file}")


if __name__ == "__main__":
    main()
