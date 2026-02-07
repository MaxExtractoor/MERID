#!/usr/bin/env python3
"""
Monitor Canary Deployment for MERID Production Pipeline.

Monitors canary deployment metrics and determines if promotion is safe.
"""

import argparse
import json
import time
import requests
import sys
from typing import Dict, Any, List
from datetime import datetime, timedelta

class CanaryMonitor:
    """Monitors canary deployment metrics and health."""
    
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics from production."""
        try:
            response = requests.get(
                f"{self.base_url}/metrics",
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            return self._parse_metrics(response.text)
        except Exception as e:
            print(f"Error getting metrics: {e}")
            return {}
    
    def _parse_metrics(self, metrics_text: str) -> Dict[str, Any]:
        """Parse Prometheus metrics text into structured data."""
        metrics = {}
        
        for line in metrics_text.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                parts = line.split()
                if len(parts) >= 2:
                    metric_name = parts[0]
                    value = float(parts[1])
                    
                    # Extract key metrics
                    if 'reality_valid_assertions' in metric_name:
                        domain = metric_name.split('{')[1].split('}')[0].split('=')[1].strip('"')
                        if 'valid_assertions' not in metrics:
                            metrics['valid_assertions'] = {}
                        metrics['valid_assertions'][domain] = value
                    
                    elif 'reality_mode' in metric_name:
                        metrics['current_mode'] = int(value)
                    
                    elif 'reality_mode_transitions_total' in metric_name:
                        if 'mode_transitions' not in metrics:
                            metrics['mode_transitions'] = 0
                        metrics['mode_transitions'] += value
                    
                    elif 'reality_mode_rollbacks_total' in metric_name:
                        if 'rollbacks' not in metrics:
                            metrics['rollbacks'] = 0
                        metrics['rollbacks'] += value
                    
                    elif 'reality_priority_violations_total' in metric_name:
                        if 'priority_violations' not in metrics:
                            metrics['priority_violations'] = 0
                        metrics['priority_violations'] += value
                    
                    elif 'reality_assertion_eval_latency_ms' in metric_name:
                        if 'assertion_latency' not in metrics:
                            metrics['assertion_latency'] = []
                        metrics['assertion_latency'].append(value)
                    
                    elif 'reality_priority_decision_latency_ms' in metric_name:
                        if 'priority_latency' not in metrics:
                            metrics['priority_latency'] = []
                        metrics['priority_latency'].append(value)
        
        return metrics
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get health status from production."""
        try:
            response = requests.get(
                f"{self.base_url}/health",
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error getting health status: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_system_state(self) -> Dict[str, Any]:
        """Get current system state."""
        try:
            response = requests.get(
                f"{self.base_url}/api/v1/reality/status",
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error getting system state: {e}")
            return {"status": "error", "error": str(e)}
    
    def check_thresholds(self, metrics: Dict[str, Any], thresholds: Dict[str, float]) -> Dict[str, bool]:
        """Check if metrics are within thresholds."""
        results = {}
        
        # Check assertion validity
        if 'valid_assertions' in metrics:
            for domain, count in metrics['valid_assertions'].items():
                threshold_key = f"valid_assertions_{domain}"
                if threshold_key in thresholds:
                    results[threshold_key] = count >= thresholds[threshold_key]
        
        # Check mode transitions
        if 'mode_transitions' in metrics and 'mode_transitions' in thresholds:
            results['mode_transitions'] = metrics['mode_transitions'] <= thresholds['mode_transitions']
        
        # Check rollbacks
        if 'rollbacks' in metrics and 'rollbacks' in thresholds:
            results['rollbacks'] = metrics['rollbacks'] <= thresholds['rollbacks']
        
        # Check priority violations
        if 'priority_violations' in metrics and 'priority_violations' in thresholds:
            results['priority_violations'] = metrics['priority_violations'] <= thresholds['priority_violations']
        
        # Check latency (P95)
        if 'assertion_latency' in metrics and 'assertion_latency_p95' in thresholds:
            latency_p95 = sorted(metrics['assertion_latency'])[int(len(metrics['assertion_latency']) * 0.95)]
            results['assertion_latency_p95'] = latency_p95 <= thresholds['assertion_latency_p95']
        
        if 'priority_latency' in metrics and 'priority_latency_p95' in thresholds:
            latency_p95 = sorted(metrics['priority_latency'])[int(len(metrics['priority_latency']) * 0.95)]
            results['priority_latency_p95'] = latency_p95 <= thresholds['priority_latency_p95']
        
        return results
    
    def monitor_canary(self, duration: int, thresholds: Dict[str, float]) -> bool:
        """Monitor canary deployment for specified duration."""
        print(f"Starting canary monitoring for {duration} seconds...")
        print(f"Thresholds: {json.dumps(thresholds, indent=2)}")
        
        start_time = time.time()
        end_time = start_time + duration
        
        # Collect metrics over time
        metrics_history = []
        health_history = []
        threshold_violations = []
        
        while time.time() < end_time:
            current_time = time.time()
            
            # Get current metrics
            metrics = self.get_metrics()
            health = self.get_health_status()
            system_state = self.get_system_state()
            
            # Check thresholds
            threshold_results = self.check_thresholds(metrics, thresholds)
            
            # Record data
            metrics_history.append({
                'timestamp': current_time,
                'metrics': metrics,
                'health': health,
                'system_state': system_state,
                'threshold_results': threshold_results
            })
            
            # Check for threshold violations
            violations = [k for k, v in threshold_results.items() if not v]
            if violations:
                threshold_violations.append({
                    'timestamp': current_time,
                    'violations': violations,
                    'metrics': metrics
                })
                
                # Log violations
                print(f"[{datetime.fromtimestamp(current_time)}] Threshold violations: {violations}")
                
                # If critical violations, fail immediately
                critical_violations = [v for v in violations if 'rollbacks' in v or 'valid_assertions' in v]
                if critical_violations:
                    print(f"CRITICAL VIOLATIONS DETECTED: {critical_violations}")
                    return False
            
            # Log current status
            print(f"[{datetime.fromtimestamp(current_time)}] "
                  f"Mode: {system_state.get('system_state', {}).get('mode', 'unknown')}, "
                  f"Valid Assertions: {metrics.get('valid_assertions', {})}, "
                  f"Violations: {metrics.get('priority_violations', 0)}")
            
            # Wait for next check
            time.sleep(30)  # Check every 30 seconds
        
        # Analyze results
        return self._analyze_results(metrics_history, health_history, threshold_violations, thresholds)
    
    def _analyze_results(self, metrics_history: List[Dict], health_history: List[Dict], 
                        threshold_violations: List[Dict], thresholds: Dict[str, float]) -> bool:
        """Analyze monitoring results and determine if canary is healthy."""
        
        print(f"\n=== Canary Monitoring Results ===")
        print(f"Monitoring duration: {len(metrics_history)} checks over {metrics_history[-1]['timestamp'] - metrics_history[0]['timestamp']:.0f} seconds")
        print(f"Threshold violations: {len(threshold_violations)}")
        
        # Check for any critical violations
        critical_violations = []
        for violation in threshold_violations:
            critical = [v for v in violation['violations'] if 'rollbacks' in v or 'valid_assertions' in v]
            if critical:
                critical_violations.extend(critical)
        
        if critical_violations:
            print(f"❌ CRITICAL VIOLATIONS: {critical_violations}")
            return False
        
        # Check violation rate
        violation_rate = len(threshold_violations) / len(metrics_history)
        if violation_rate > 0.1:  # More than 10% violations
            print(f"❌ HIGH VIOLATION RATE: {violation_rate:.2%}")
            return False
        
        # Check system stability
        mode_changes = []
        current_mode = None
        for entry in metrics_history:
            mode = entry['system_state'].get('system_state', {}).get('mode', 'unknown')
            if current_mode and mode != current_mode:
                mode_changes.append(mode)
            current_mode = mode
        
        if len(mode_changes) > 2:  # More than 2 mode changes
            print(f"❌ UNSTABLE MODE CHANGES: {mode_changes}")
            return False
        
        # Check health status
        health_issues = []
        for entry in health_history:
            if entry.get('status') != 'healthy':
                health_issues.append(entry.get('timestamp'))
        
        if len(health_issues) > len(health_history) * 0.05:  # More than 5% health issues
            print(f"❌ HEALTH ISSUES: {len(health_issues)} out of {len(health_history)} checks")
            return False
        
        # Check final metrics
        final_metrics = metrics_history[-1]['metrics']
        final_threshold_results = metrics_history[-1]['threshold_results']
        
        print(f"Final metrics: {final_metrics}")
        print(f"Final threshold results: {final_threshold_results}")
        
        # All threshold checks must pass
        if not all(final_threshold_results.values()):
            failed_checks = [k for k, v in final_threshold_results.items() if not v]
            print(f"❌ FINAL THRESHOLD FAILURES: {failed_checks}")
            return False
        
        print(f"✅ Canary monitoring PASSED")
        return True


def main():
    """Main entry point for canary monitoring."""
    parser = argparse.ArgumentParser(description='Monitor MERID canary deployment')
    parser.add_argument('--duration', type=int, default=1800, help='Monitoring duration in seconds')
    parser.add_argument('--threshold-error-rate', type=float, default=0.01, help='Error rate threshold')
    parser.add_argument('--threshold-latency-p95', type=float, default=500, help='P95 latency threshold in ms')
    parser.add_argument('--threshold-violations', type=int, default=10, help='Priority violations threshold')
    parser.add_argument('--threshold-rollbacks', type=int, default=0, help='Rollbacks threshold')
    parser.add_argument('--threshold-mode-transitions', type=int, default=5, help='Mode transitions threshold')
    parser.add_argument('--base-url', default='https://api.merid.com', help='Base URL for MERID API')
    parser.add_argument('--api-key', required=True, help='API key for authentication')
    
    args = parser.parse_args()
    
    # Set up thresholds
    thresholds = {
        'valid_assertions_market': 5,
        'valid_assertions_onchain': 5,
        'valid_assertions_simulation': 5,
        'valid_assertions_agent': 5,
        'priority_violations': args.threshold_violations,
        'rollbacks': args.threshold_rollbacks,
        'mode_transitions': args.threshold_mode_transitions,
        'assertion_latency_p95': args.threshold_latency_p95,
        'priority_latency_p95': args.threshold_latency_p95
    }
    
    # Create monitor and run
    monitor = CanaryMonitor(args.base_url, args.api_key)
    
    try:
        success = monitor.monitor_canary(args.duration, thresholds)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nMonitoring interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Monitoring failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
