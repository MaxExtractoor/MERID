#!/usr/bin/env python3
"""
Risk Shadow Mode Report Generator

Automatically generates the Risk Shadow Mini-Report by collecting
data from shadow mode logs, metrics, and analysis results.

Usage:
    python generate_risk_shadow_report.py --start-date 2026-02-08 --end-date 2026-02-21
    python generate_risk_shadow_report.py --days 10
    python generate_risk_shadow_report.py --latest

Output:
    risk_shadow_mini_report_[TIMESTAMP].md
"""

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class RiskShadowReportGenerator:
    """Generates Risk Shadow Mode Mini-Report from collected data."""
    
    def __init__(self, db_path: str = "data/risk_shadow.db"):
        self.db_path = db_path
        self.template_path = "risk_shadow_mini_report_template.md"
        
    def generate_report(self, start_date: datetime, end_date: datetime) -> str:
        """Generate complete Risk Shadow Mini-Report."""
        logger.info(f"Generating report for {start_date.date()} to {end_date.date()}")
        
        # Collect all metrics
        metrics = self._collect_metrics(start_date, end_date)
        
        # Load template
        template = self._load_template()
        
        # Fill template with data
        report = self._fill_template(template, metrics, start_date, end_date)
        
        return report
    
    def _collect_metrics(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Collect all metrics for the report period."""
        metrics = {}
        
        # Core metrics
        metrics.update(self._get_core_metrics(start_date, end_date))
        
        # Daily performance
        metrics.update(self._get_daily_performance(start_date, end_date))
        
        # Decision alignment
        metrics.update(self._get_decision_alignment(start_date, end_date))
        
        # Guardrail analysis
        metrics.update(self._get_guardrail_analysis(start_date, end_date))
        
        # Impact assessment
        metrics.update(self._get_impact_assessment(start_date, end_date))
        
        # Outlier analysis
        metrics.update(self._get_outlier_analysis(start_date, end_date))
        
        # Stress experiments
        metrics.update(self._get_stress_experiments(start_date, end_date))
        
        # System performance
        metrics.update(self._get_system_performance(start_date, end_date))
        
        return metrics
    
    def _get_core_metrics(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Get core shadow mode metrics."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Days active
        cursor.execute("""
            SELECT COUNT(DISTINCT DATE(timestamp)) as days_active
            FROM shadow_decisions
            WHERE timestamp BETWEEN ? AND ?
        """, (start_date.isoformat(), end_date.isoformat()))
        days_active = cursor.fetchone()[0]
        
        # Decision alignment
        cursor.execute("""
            SELECT 
                COUNT(*) as total_decisions,
                SUM(CASE WHEN shadow_action = actual_action THEN 1 ELSE 0 END) as aligned_decisions
            FROM shadow_decisions
            WHERE timestamp BETWEEN ? AND ?
        """, (start_date.isoformat(), end_date.isoformat()))
        total, aligned = cursor.fetchone()
        alignment_pct = (aligned / total * 100) if total > 0 else 0
        
        # Guardrail latency p95
        cursor.execute("""
            SELECT 
                AVG(calculation_latency) as avg_calc,
                AVG(decision_latency) as avg_decision,
                AVG(contract_latency) as avg_contract,
                (SELECT calculation_latency FROM shadow_metrics 
                 WHERE timestamp BETWEEN ? AND ? 
                 ORDER BY calculation_latency DESC 
                 LIMIT (SELECT COUNT(*) FROM shadow_metrics WHERE timestamp BETWEEN ? AND ?) * 0.95) as p95_calc
            FROM shadow_metrics
            WHERE timestamp BETWEEN ? AND ?
        """, (start_date.isoformat(), end_date.isoformat(), 
              start_date.isoformat(), end_date.isoformat(),
              start_date.isoformat(), end_date.isoformat()))
        avg_calc, avg_decision, avg_contract, p95_calc = cursor.fetchone()
        
        # System impact
        cursor.execute("""
            SELECT 
                AVG(pnl_impact_pct) as avg_impact,
                AVG(risk_impact_pct) as avg_risk_impact
            FROM shadow_impact
            WHERE timestamp BETWEEN ? AND ?
        """, (start_date.isoformat(), end_date.isoformat()))
        result = cursor.fetchone()
        avg_impact = result[0] if result[0] is not None else 0
        avg_risk_impact = result[1] if result[1] is not None else 0
        
        # Data quality
        cursor.execute("""
            SELECT AVG(data_quality_score) as avg_quality
            FROM shadow_data_quality
            WHERE timestamp BETWEEN ? AND ?
        """, (start_date.isoformat(), end_date.isoformat()))
        avg_quality = cursor.fetchone()[0] or 0
        
        # Incidents
        cursor.execute("""
            SELECT COUNT(*) as incidents
            FROM incidents
            WHERE severity IN ('Sev-0', 'Sev-1')
            AND timestamp BETWEEN ? AND ?
            AND component = 'Risk Shadow'
        """, (start_date.isoformat(), end_date.isoformat()))
        incidents = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            'days_active': days_active,
            'total_decisions': total,
            'aligned_decisions': aligned,
            'alignment_pct': round(alignment_pct, 1),
            'avg_calc_latency': round(avg_calc, 1),
            'avg_decision_latency': round(avg_decision, 1),
            'avg_contract_latency': round(avg_contract, 1),
            'p95_calc_latency': round(p95_calc, 1),
            'avg_pnl_impact': round(avg_impact, 2),
            'avg_risk_impact': round(avg_risk_impact, 2),
            'avg_data_quality': round(avg_quality, 1),
            'incidents': incidents
        }
    
    def _get_daily_performance(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Get daily performance summary."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                DATE(s.timestamp) as date,
                COUNT(*) as decisions,
                AVG(CASE WHEN s.shadow_action = s.actual_action THEN 100.0 ELSE 0.0 END) as alignment,
                (SELECT calculation_latency FROM shadow_metrics m 
                 WHERE DATE(m.timestamp) = DATE(s.timestamp) 
                 ORDER BY calculation_latency DESC 
                 LIMIT (SELECT COUNT(*) FROM shadow_metrics m2 WHERE DATE(m2.timestamp) = DATE(s.timestamp)) * 0.95) as p95_latency,
                AVG(i.pnl_impact_pct) as impact,
                AVG(dq.data_quality_score) as quality
            FROM shadow_decisions s
            LEFT JOIN shadow_metrics m ON DATE(s.timestamp) = DATE(m.timestamp)
            LEFT JOIN shadow_impact i ON DATE(s.timestamp) = DATE(i.timestamp)
            LEFT JOIN shadow_data_quality dq ON DATE(s.timestamp) = DATE(dq.timestamp)
            WHERE s.timestamp BETWEEN ? AND ?
            GROUP BY DATE(s.timestamp)
            ORDER BY date
        """, (start_date.isoformat(), end_date.isoformat()))
        
        daily_data = cursor.fetchall()
        conn.close()
        
        return {
            'daily_performance': [
                {
                    'date': row[0],
                    'decisions': row[1],
                    'alignment': round(row[2], 1),
                    'p95_latency': round(row[3] or 0, 1),
                    'impact': round(row[4] or 0, 2),
                    'quality': round(row[5] or 0, 1)
                }
                for row in daily_data
            ]
        }
    
    def _get_decision_alignment(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Get decision alignment breakdown."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                decision_type,
                COUNT(*) as total,
                SUM(CASE WHEN shadow_action = actual_action THEN 1 ELSE 0 END) as aligned
            FROM shadow_decisions
            WHERE timestamp BETWEEN ? AND ?
            GROUP BY decision_type
        """, (start_date.isoformat(), end_date.isoformat()))
        
        alignment_data = cursor.fetchall()
        conn.close()
        
        return {
            'decision_alignment': [
                {
                    'type': row[0],
                    'total': row[1],
                    'aligned': row[2],
                    'alignment_rate': round(row[2] / row[1] * 100, 1) if row[1] > 0 else 0
                }
                for row in alignment_data
            ]
        }
    
    def _get_guardrail_analysis(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Get guardrail trigger analysis."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                guardrail_type,
                COUNT(*) as triggers,
                SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct,
                SUM(CASE WHEN is_correct = 0 THEN 1 ELSE 0 END) as false_positive
            FROM guardrail_triggers
            WHERE timestamp BETWEEN ? AND ?
            GROUP BY guardrail_type
        """, (start_date.isoformat(), end_date.isoformat()))
        
        guardrail_data = cursor.fetchall()
        conn.close()
        
        return {
            'guardrail_triggers': [
                {
                    'type': row[0],
                    'triggers': row[1],
                    'correct': row[2],
                    'false_positive': row[3],
                    'accuracy': round(row[2] / row[1] * 100, 1) if row[1] > 0 else 0
                }
                for row in guardrail_data
            ]
        }
    
    def _get_impact_assessment(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Get P&L and risk impact assessment."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                SUM(CASE WHEN actual_pnl IS NOT NULL THEN actual_pnl ELSE 0 END) as actual_pnl,
                SUM(CASE WHEN shadow_pnl IS NOT NULL THEN shadow_pnl ELSE 0 END) as shadow_pnl,
                AVG(CASE WHEN actual_var IS NOT NULL THEN actual_var ELSE 0 END) as actual_var,
                AVG(CASE WHEN shadow_var IS NOT NULL THEN shadow_var ELSE 0 END) as shadow_var,
                AVG(CASE WHEN actual_drawdown IS NOT NULL THEN actual_drawdown ELSE 0 END) as actual_dd,
                AVG(CASE WHEN shadow_drawdown IS NOT NULL THEN shadow_drawdown ELSE 0 END) as shadow_dd,
                AVG(CASE WHEN actual_concentration IS NOT NULL THEN actual_concentration ELSE 0 END) as actual_conc,
                AVG(CASE WHEN shadow_concentration IS NOT NULL THEN shadow_concentration ELSE 0 END) as shadow_conc
            FROM shadow_impact
            WHERE timestamp BETWEEN ? AND ?
        """, (start_date.isoformat(), end_date.isoformat()))
        
        actual_pnl, shadow_pnl, actual_var, shadow_var, actual_dd, shadow_dd, actual_conc, shadow_conc = cursor.fetchone()
        
        pnl_diff = shadow_pnl - actual_pnl
        pnl_impact_pct = (pnl_diff / actual_pnl * 100) if actual_pnl != 0 else 0
        
        conn.close()
        
        return {
            'actual_pnl': round(actual_pnl, 2),
            'shadow_pnl': round(shadow_pnl, 2),
            'pnl_difference': round(pnl_diff, 2),
            'pnl_impact_pct': round(pnl_impact_pct, 2),
            'actual_var': round(actual_var, 2),
            'shadow_var': round(shadow_var, 2),
            'actual_drawdown': round(actual_dd, 2),
            'shadow_drawdown': round(shadow_dd, 2),
            'actual_concentration': round(actual_conc, 2),
            'shadow_concentration': round(shadow_conc, 2)
        }
    
    def _get_outlier_analysis(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Get outlier analysis results."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                outlier_id,
                DATE(timestamp) as date,
                decision_type,
                shadow_action,
                actual_action,
                classification,
                rationale
            FROM outlier_analysis
            WHERE timestamp BETWEEN ? AND ?
            ORDER BY date
        """, (start_date.isoformat(), end_date.isoformat()))
        
        outlier_data = cursor.fetchall()
        
        # Classification summary
        cursor.execute("""
            SELECT 
                classification,
                COUNT(*) as count
            FROM outlier_analysis
            WHERE timestamp BETWEEN ? AND ?
            GROUP BY classification
        """, (start_date.isoformat(), end_date.isoformat()))
        
        classification_data = cursor.fetchall()
        total_outliers = sum(count for _, count in classification_data)
        
        conn.close()
        
        return {
            'outliers': [
                {
                    'id': row[0],
                    'date': row[1],
                    'type': row[2],
                    'shadow_action': row[3],
                    'actual_action': row[4],
                    'classification': row[5],
                    'rationale': row[6]
                }
                for row in outlier_data
            ],
            'classification_summary': [
                {
                    'classification': row[0],
                    'count': row[1],
                    'percentage': round(row[1] / total_outliers * 100, 1) if total_outliers > 0 else 0
                }
                for row in classification_data
            ]
        }
    
    def _get_stress_experiments(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Get stress experiment results."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                experiment_name,
                experiment_date,
                duration_hours,
                conditions,
                normal_triggers,
                stress_triggers,
                normal_alignment,
                stress_alignment,
                normal_impact,
                stress_impact,
                normal_latency,
                stress_latency,
                findings,
                conclusions
            FROM stress_experiments
            WHERE experiment_date BETWEEN ? AND ?
            ORDER BY experiment_date
        """, (start_date.isoformat(), end_date.isoformat()))
        
        experiment_data = cursor.fetchone()
        conn.close()
        
        if not experiment_data:
            return {
                'has_experiments': False,
                'experiments': []
            }
        
        return {
            'has_experiments': True,
            'experiments': [{
                'name': experiment_data[0],
                'date': experiment_data[1],
                'duration': experiment_data[2],
                'conditions': experiment_data[3],
                'normal_triggers': experiment_data[4],
                'stress_triggers': experiment_data[5],
                'normal_alignment': experiment_data[6],
                'stress_alignment': experiment_data[7],
                'normal_impact': experiment_data[8],
                'stress_impact': experiment_data[9],
                'normal_latency': experiment_data[10],
                'stress_latency': experiment_data[11],
                'findings': experiment_data[12],
                'conclusions': experiment_data[13]
            }]
        }
    
    def _get_system_performance(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        """Get system performance metrics."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                AVG(cpu_usage) as avg_cpu,
                MAX(cpu_usage) as peak_cpu,
                AVG(memory_usage) as avg_memory,
                MAX(memory_usage) as peak_memory,
                AVG(network_usage) as avg_network,
                MAX(network_usage) as peak_network,
                AVG(storage_usage) as avg_storage,
                MAX(storage_usage) as peak_storage
            FROM system_metrics
            WHERE timestamp BETWEEN ? AND ?
        """, (start_date.isoformat(), end_date.isoformat()))
        
        perf_data = cursor.fetchone()
        
        # Reliability metrics
        cursor.execute("""
            SELECT 
                AVG(uptime_pct) as avg_uptime,
                AVG(error_rate) as avg_error_rate,
                AVG(recovery_time_min) as avg_recovery,
                AVG(data_quality_score) as avg_data_quality
            FROM reliability_metrics
            WHERE timestamp BETWEEN ? AND ?
        """, (start_date.isoformat(), end_date.isoformat()))
        
        reliability_data = cursor.fetchone()
        conn.close()
        
        return {
            'avg_cpu': round(perf_data[0], 1),
            'peak_cpu': round(perf_data[1], 1),
            'avg_memory': round(perf_data[2], 1),
            'peak_memory': round(perf_data[3], 1),
            'avg_network': round(perf_data[4], 1),
            'peak_network': round(perf_data[5], 1),
            'avg_storage': round(perf_data[6], 2),
            'peak_storage': round(perf_data[7], 2),
            'avg_uptime': round(reliability_data[0], 1),
            'avg_error_rate': round(reliability_data[1], 2),
            'avg_recovery': round(reliability_data[2], 1),
            'avg_data_quality': round(reliability_data[3], 1)
        }
    
    def _load_template(self) -> str:
        """Load the report template."""
        try:
            with open(self.template_path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            logger.error(f"Template file not found: {self.template_path}")
            sys.exit(1)
    
    def _fill_template(self, template: str, metrics: Dict[str, Any], 
                      start_date: datetime, end_date: datetime) -> str:
        """Fill template with collected metrics."""
        
        # Core metrics
        template = template.replace("[X]", str(metrics.get('days_active', 0)))
        template = template.replace("[X.X]%", str(metrics.get('alignment_pct', 0)))
        template = template.replace("[X]ms", str(metrics.get('p95_calc_latency', 0)))
        template = template.replace("[X.X]%", str(metrics.get('avg_pnl_impact', 0)))
        template = template.replace("[X.X]%", str(metrics.get('avg_data_quality', 0)))
        template = template.replace("[X]", str(metrics.get('incidents', 0)))
        
        # Decision counts
        template = template.replace("[X]", str(metrics.get('total_decisions', 0)))
        template = template.replace("[X]", str(metrics.get('aligned_decisions', 0)))
        
        # Latency metrics
        template = template.replace("[X]ms", str(metrics.get('avg_calc_latency', 0)))
        template = template.replace("[X]ms", str(metrics.get('avg_decision_latency', 0)))
        template = template.replace("[X]ms", str(metrics.get('avg_contract_latency', 0)))
        
        # P&L impact
        template = template.replace("$[X]", f"${abs(metrics.get('actual_pnl', 0)):.2f}")
        template = template.replace("$[X]", f"${abs(metrics.get('shadow_pnl', 0)):.2f}")
        template = template.replace("$[X]", f"${abs(metrics.get('pnl_difference', 0)):.2f}")
        
        # Risk metrics
        template = template.replace("[X]", str(metrics.get('actual_var', 0)))
        template = template.replace("[X]", str(metrics.get('shadow_var', 0)))
        template = template.replace("[X]%", str(metrics.get('actual_drawdown', 0)))
        template = template.replace("[X]%", str(metrics.get('shadow_drawdown', 0)))
        template = template.replace("[X]%", str(metrics.get('actual_concentration', 0)))
        template = template.replace("[X]%", str(metrics.get('shadow_concentration', 0)))
        
        # System performance
        template = template.replace("[X.X]%", str(metrics.get('avg_cpu', 0)))
        template = template.replace("[X.X]%", str(metrics.get('peak_cpu', 0)))
        template = template.replace("[X]MB", str(metrics.get('avg_memory', 0)))
        template = template.replace("[X]MB", str(metrics.get('peak_memory', 0)))
        template = template.replace("[X]Mbps", str(metrics.get('avg_network', 0)))
        template = template.replace("[X]Mbps", str(metrics.get('peak_network', 0)))
        template = template.replace("[X]GB/day", str(metrics.get('avg_storage', 0)))
        template = template.replace("[X]GB/day", str(metrics.get('peak_storage', 0)))
        
        template = template.replace("[X.X]%", str(metrics.get('avg_uptime', 0)))
        template = template.replace("[X.X]%", str(metrics.get('avg_error_rate', 0)))
        template = template.replace("[X]min", str(metrics.get('avg_recovery', 0)))
        template = template.replace("[X.X]%", str(metrics.get('avg_data_quality', 0)))
        
        # Dates
        template = template.replace("[DATE]", datetime.now().strftime("%Y-%m-%d"))
        template = template.replace("[START_DATE]", start_date.strftime("%Y-%m-%d"))
        template = template.replace("[END_DATE]", end_date.strftime("%Y-%m-%d"))
        template = template.replace("[TIMESTAMP]", datetime.now().strftime("%Y%m%d_%H%M%S"))
        template = template.replace("[REVIEW DATE]", (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d"))
        
        # Daily performance table
        daily_table = ""
        for day in metrics.get('daily_performance', []):
            daily_table += f"| {day['date']} | {day['decisions']} | {day['alignment']}% | {day['p95_latency']}ms | {day['impact']}% | {day['quality']}% |\n"
        
        # Find the daily performance table section and replace it
        start_marker = "| [DATE] | [X] | [X.X]% | [X]ms | [X.X]% | [X.X]% |"
        end_marker = "| **Average** | **[X]** | **[X.X]%** | **[X]ms** | **[X.X]%** | **[X.X]%** |"
        
        if start_marker in template and end_marker in template:
            start_idx = template.find(start_marker)
            end_idx = template.find(end_marker) + len(end_marker)
            template = template[:start_idx] + daily_table + template[end_idx:]
        
        # Decision alignment table
        alignment_table = ""
        for alignment in metrics.get('decision_alignment', []):
            alignment_table += f"| {alignment['type']} | {alignment['total']} | {alignment['aligned']} | {alignment['alignment_rate']}% |\n"
        
        # Find and replace decision alignment table
        start_marker = "| [TYPE] | [X] | [X] | [X.X]% |"
        end_marker = "| **Total** | **[X]** | **[X]** | **[X.X]%** |"
        
        if start_marker in template and end_marker in template:
            start_idx = template.find(start_marker)
            end_idx = template.find(end_marker) + len(end_marker)
            template = template[:start_idx] + alignment_table + template[end_idx:]
        
        # Guardrail triggers table
        guardrail_table = ""
        for guardrail in metrics.get('guardrail_triggers', []):
            guardrail_table += f"| {guardrail['type']} | {guardrail['triggers']} | {guardrail['correct']} | {guardrail['false_positive']} | {guardrail['accuracy']}% |\n"
        
        # Find and replace guardrail triggers table
        start_marker = "| [TYPE] | [X] | [X] | [X] | [X.X]% |"
        end_marker = "| **Total** | **[X]** | **[X]** | **[X]** | **[X.X]%** |"
        
        if start_marker in template and end_marker in template:
            start_idx = template.find(start_marker)
            end_idx = template.find(end_marker) + len(end_marker)
            template = template[:start_idx] + guardrail_table + template[end_idx:]
        
        # Outlier table
        outlier_table = ""
        for outlier in metrics.get('outliers', []):
            outlier_table += f"| {outlier['id']} | {outlier['date']} | {outlier['type']} | {outlier['shadow_action']} | {outlier['actual_action']} | {outlier['classification']} | {outlier['rationale']} |\n"
        
        # Find and replace outlier table
        start_marker = "| [OUT-001] | [DATE] | [TYPE] | [SHADOW] | [ACTUAL] | [CORRECT/CONSERVATIVE/LAX] | [RATIONALE] |"
        end_marker = "| **Total** | **[X]** | **100%** | **[DESCRIPTION]** |"
        
        if start_marker in template and end_marker in template:
            start_idx = template.find(start_marker)
            end_idx = template.find(end_marker) + len(end_marker)
            template = template[:start_idx] + outlier_table + template[end_idx:]
        
        # Classification summary
        class_table = ""
        for classification in metrics.get('classification_summary', []):
            class_table += f"| {classification['classification']} | {classification['count']} | {classification['percentage']}% | [DESCRIPTION] |\n"
        
        # Find and replace classification table
        start_marker = "| [CORRECT/CONSERVATIVE/LAX] | [X] | [X.X]% | [DESCRIPTION] |"
        end_marker = "| **Total** | **[X]** | **100%** | **[DESCRIPTION]** |"
        
        if start_marker in template and end_marker in template:
            start_idx = template.find(start_marker)
            end_idx = template.find(end_marker) + len(end_marker)
            template = template[:start_idx] + class_table + template[end_idx:]
        
        # Enforcement gate status
        gate_status = "PASS" if (
            metrics.get('days_active', 0) >= 10 and
            metrics.get('alignment_pct', 0) >= 90 and
            metrics.get('p95_calc_latency', 999) <= 100 and
            metrics.get('avg_data_quality', 0) >= 99.9 and
            metrics.get('incidents', 0) == 0
        ) else "FAIL"
        
        recommendation = "PROCEED" if gate_status == "PASS" else "DEFER"
        
        template = template.replace("[PASS/FAIL]", gate_status)
        template = template.replace("[PROCEED/DEFER]", recommendation)
        
        return template

def main():
    """Main function to generate the report."""
    parser = argparse.ArgumentParser(description="Generate Risk Shadow Mode Mini-Report")
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, help="Number of days to analyze")
    parser.add_argument("--latest", action="store_true", help="Use latest available data")
    parser.add_argument("--output", help="Output file path")
    
    args = parser.parse_args()
    
    # Determine date range
    if args.latest:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=10)
    elif args.days:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=args.days)
    elif args.start_date and args.end_date:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
    else:
        # Default to last 10 days
        end_date = datetime.now()
        start_date = end_date - timedelta(days=10)
    
    # Generate report
    generator = RiskShadowReportGenerator()
    report = generator.generate_report(start_date, end_date)
    
    # Save report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_filename = f"risk_shadow_mini_report_{timestamp}.md"
    output_path = args.output or default_filename
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"Report generated: {output_path}")
    print(f"Period: {start_date.date()} to {end_date.date()}")
    print(f"Days analyzed: {(end_date - start_date).days}")

if __name__ == "__main__":
    main()
