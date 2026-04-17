#!/usr/bin/env python3
"""
Create remaining Grafana dashboards for MERID monitoring
Week 2: Production Operations Gate - Evidence Artifact
Date: 2026-01-26
"""

import json
from pathlib import Path

def create_governance_gates_dashboard():
    """Create governance gates dashboard JSON"""
    dashboard = {
        "dashboard": {
            "id": None,
            "title": "MERID Governance Gates",
            "tags": ["merid", "governance", "gates"],
            "timezone": "browser",
            "panels": [
                {
                    "id": 1,
                    "title": "Technical Readiness Gate",
                    "type": "stat",
                    "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
                    "targets": [
                        {"expr": "merid_technical_readiness_gate_status", "legendFormat": "Technical Gate"}
                    ],
                    "fieldConfig": {
                        "defaults": {
                            "mappings": [
                                {"options": {"0": {"color": "red", "text": "FAIL"}}, "type": "value"},
                                {"options": {"1": {"color": "green", "text": "PASS"}}, "type": "value"}
                            ]
                        }
                    }
                },
                {
                    "id": 2,
                    "title": "Operational Readiness Gate",
                    "type": "stat",
                    "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
                    "targets": [
                        {"expr": "merid_operational_readiness_gate_status", "legendFormat": "Ops Gate"}
                    ],
                    "fieldConfig": {
                        "defaults": {
                            "mappings": [
                                {"options": {"0": {"color": "red", "text": "FAIL"}}, "type": "value"},
                                {"options": {"1": {"color": "green", "text": "PASS"}}, "type": "value"}
                            ]
                        }
                    }
                },
                {
                    "id": 3,
                    "title": "Cohort Governance Gate",
                    "type": "stat",
                    "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
                    "targets": [
                        {"expr": "merid_cohort_gate_status", "legendFormat": "Cohort Gate"}
                    ],
                    "fieldConfig": {
                        "defaults": {
                            "mappings": [
                                {"options": {"0": {"color": "red", "text": "FAIL"}}, "type": "value"},
                                {"options": {"1": {"color": "green", "text": "PASS"}}, "type": "value"}
                            ]
                        }
                    }
                },
                {
                    "id": 4,
                    "title": "Stress Test Gate",
                    "type": "stat",
                    "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
                    "targets": [
                        {"expr": "merid_stress_test_gate_status", "legendFormat": "Stress Gate"}
                    ],
                    "fieldConfig": {
                        "defaults": {
                            "mappings": [
                                {"options": {"0": {"color": "red", "text": "FAIL"}}, "type": "value"},
                                {"options": {"1": {"color": "green", "text": "PASS"}}, "type": "value"}
                            ]
                        }
                    }
                },
                {
                    "id": 5,
                    "title": "Production Readiness",
                    "type": "stat",
                    "gridPos": {"h": 4, "w": 6, "x": 0, "y": 16},
                    "targets": [
                        {"expr": "merid_production_readiness_status", "legendFormat": "Production Ready"}
                    ],
                    "fieldConfig": {
                        "defaults": {
                            "mappings": [
                                {"options": {"0": {"color": "red", "text": "BLOCKED"}}, "type": "value"},
                                {"options": {"1": {"color": "green", "text": "READY"}}, "type": "value"}
                            ]
                        }
                    }
                },
                {
                    "id": 6,
                    "title": "Gate Health Score",
                    "type": "stat",
                    "gridPos": {"h": 4, "w": 6, "x": 6, "y": 16},
                    "targets": [
                        {"expr": "(merid_technical_readiness_gate_status + merid_operational_readiness_gate_status + merid_cohort_gate_status + merid_stress_test_gate_status) / 4 * 100", "legendFormat": "Gate Score"}
                    ],
                    "fieldConfig": {
                        "defaults": {
                            "unit": "percent",
                            "color": {"mode": "thresholds"},
                            "thresholds": {
                                "steps": [
                                    {"color": "red", "value": 75},
                                    {"color": "yellow", "value": 90},
                                    {"color": "green", "value": 100}
                                ]
                            }
                        }
                    }
                }
            ],
            "time": {"from": "now-24h", "to": "now"},
            "refresh": "60s"
        }
    }
    return dashboard

def create_swarm_health_dashboard():
    """Create swarm health dashboard JSON"""
    dashboard = {
        "dashboard": {
            "id": None,
            "title": "MERID Swarm Health",
            "tags": ["merid", "swarm", "agents"],
            "timezone": "browser",
            "panels": [
                {
                    "id": 1,
                    "title": "Swarm Overview",
                    "type": "stat",
                    "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
                    "targets": [
                        {"expr": "merid_swarm_agent_count", "legendFormat": "Active Agents"},
                        {"expr": "merid_swarm_healthy_agents", "legendFormat": "Healthy Agents"}
                    ],
                    "fieldConfig": {
                        "defaults": {
                            "color": {"mode": "thresholds"},
                            "thresholds": {
                                "steps": [
                                    {"color": "red", "value": 0},
                                    {"color": "yellow", "value": 5},
                                    {"color": "green", "value": 10}
                                ]
                            }
                        }
                    }
                },
                {
                    "id": 2,
                    "title": "Agent Health Distribution",
                    "type": "piechart",
                    "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
                    "targets": [
                        {"expr": "sum by (health_status) (merid_swarm_agent_health)", "legendFormat": "{{health_status}}"}
                    ]
                },
                {
                    "id": 3,
                    "title": "Decision Latency",
                    "type": "graph",
                    "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
                    "targets": [
                        {"expr": "histogram_quantile(0.50, rate(merid_swarm_decision_duration_seconds_bucket[5m]))", "legendFormat": "P50 Decision Time"},
                        {"expr": "histogram_quantile(0.95, rate(merid_swarm_decision_duration_seconds_bucket[5m]))", "legendFormat": "P95 Decision Time"},
                        {"expr": "histogram_quantile(0.99, rate(merid_swarm_decision_duration_seconds_bucket[5m]))", "legendFormat": "P99 Decision Time"}
                    ],
                    "yAxes": [{"label": "Seconds", "min": 0}]
                },
                {
                    "id": 4,
                    "title": "Decision Throughput",
                    "type": "graph",
                    "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
                    "targets": [
                        {"expr": "rate(merid_swarm_decisions_total[5m])", "legendFormat": "Decisions/sec"},
                        {"expr": "rate(merid_swarm_votes_total[5m])", "legendFormat": "Votes/sec"}
                    ],
                    "yAxes": [{"label": "Per Second", "min": 0}]
                },
                {
                    "id": 5,
                    "title": "Agent Performance",
                    "type": "table",
                    "gridPos": {"h": 8, "w": 24, "x": 0, "y": 16},
                    "targets": [
                        {"expr": "merid_swarm_agent_performance", "legendFormat": "{{agent_id}}", "format": "table"}
                    ],
                    "transformations": [
                        {
                            "id": "organize",
                            "options": {
                                "excludeByName": {"Time": True, "__name__": True, "__value__": True},
                                "indexByName": {},
                                "sortByByName": {}
                            }
                        }
                    ]
                }
            ],
            "time": {"from": "now-24h", "to": "now"},
            "refresh": "15s"
        }
    }
    return dashboard

def create_infrastructure_dashboard():
    """Create infrastructure dashboard JSON"""
    dashboard = {
        "dashboard": {
            "id": None,
            "title": "MERID Infrastructure",
            "tags": ["merid", "infrastructure", "resources"],
            "timezone": "browser",
            "panels": [
                {
                    "id": 1,
                    "title": "CPU Usage",
                    "type": "graph",
                    "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
                    "targets": [
                        {"expr": "100 - (avg by (instance) (rate(node_cpu_seconds_total{mode=\"idle\"}[5m])) * 100)", "legendFormat": "CPU %"},
                        {"expr": "avg by (instance) (rate(node_cpu_seconds_total{mode=\"iowait\"}[5m]))", "legendFormat": "I/O Wait %"}
                    ],
                    "yAxes": [{"label": "Percentage", "min": 0, "max": 100}]
                },
                {
                    "id": 2,
                    "title": "Memory Usage",
                    "type": "graph",
                    "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
                    "targets": [
                        {"expr": "(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes * 100", "legendFormat": "Memory %"},
                        {"expr": "node_memory_SwapTotal_bytes > 0 and (node_memory_SwapTotal_bytes - node_memory_SwapFree_bytes) / node_memory_SwapTotal_bytes * 100 or 0", "legendFormat": "Swap %"}
                    ],
                    "yAxes": [{"label": "Percentage", "min": 0, "max": 100}]
                },
                {
                    "id": 3,
                    "title": "Disk Usage",
                    "type": "graph",
                    "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
                    "targets": [
                        {"expr": "100 - ((node_filesystem_avail_bytes{mountpoint=\"/\"} / node_filesystem_size_bytes{mountpoint=\"/\"}) * 100)", "legendFormat": "Root Disk %"},
                        {"expr": "100 - ((node_filesystem_avail_bytes{mountpoint=\"/data\"} / node_filesystem_size_bytes{mountpoint=\"/data\"}) * 100)", "legendFormat": "Data Disk %"}
                    ],
                    "yAxes": [{"label": "Percentage", "min": 0, "max": 100}]
                },
                {
                    "id": 4,
                    "title": "Network I/O",
                    "type": "graph",
                    "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
                    "targets": [
                        {"expr": "rate(node_network_receive_bytes_total[5m])", "legendFormat": "RX Bytes/sec"},
                        {"expr": "rate(node_network_transmit_bytes_total[5m])", "legendFormat": "TX Bytes/sec"}
                    ],
                    "yAxes": [{"label": "Bytes/sec", "min": 0}]
                },
                {
                    "id": 5,
                    "title": "System Load",
                    "type": "graph",
                    "gridPos": {"h": 4, "w": 6, "x": 0, "y": 16},
                    "targets": [
                        {"expr": "node_load1", "legendFormat": "1m Load"},
                        {"expr": "node_load5", "legendFormat": "5m Load"},
                        {"expr": "node_load15", "legendFormat": "15m Load"}
                    ],
                    "yAxes": [{"label": "Load Average", "min": 0}]
                },
                {
                    "id": 6,
                    "title": "Uptime",
                    "type": "stat",
                    "gridPos": {"h": 4, "w": 6, "x": 6, "y": 16},
                    "targets": [
                        {"expr": "time() - node_boot_time_seconds", "legendFormat": "Uptime"}
                    ],
                    "fieldConfig": {
                        "defaults": {
                            "unit": "s",
                            "color": {"mode": "thresholds"},
                            "thresholds": {
                                "steps": [
                                    {"color": "green", "value": 86400},
                                    {"color": "yellow", "value": 259200},
                                    {"color": "red", "value": 864000}
                                ]
                            }
                        }
                    }
                },
                {
                    "id": 7,
                    "title": "Process Count",
                    "type": "stat",
                    "gridPos": {"h": 4, "w": 6, "x": 12, "y": 16},
                    "targets": [
                        {"expr": "node_processes", "legendFormat": "Processes"}
                    ],
                    "fieldConfig": {
                        "defaults": {
                            "color": {"mode": "thresholds"},
                            "thresholds": {
                                "steps": [
                                    {"color": "green", "value": 100},
                                    {"color": "yellow", "value": 200},
                                    {"color": "red", "value": 500}
                                ]
                            }
                        }
                    }
                },
                {
                    "id": 8,
                    "title": "File Descriptors",
                    "type": "stat",
                    "gridPos": {"h": 4, "w": 6, "x": 18, "y": 16},
                    "targets": [
                        {"expr": "node_filefd_allocated", "legendFormat": "FD Used"},
                        {"expr": "node_filefd_maximum", "legendFormat": "FD Max"}
                    ],
                    "fieldConfig": {
                        "defaults": {
                            "color": {"mode": "thresholds"},
                            "thresholds": {
                                "steps": [
                                    {"color": "green", "value": 1000},
                                    {"color": "yellow", "value": 5000},
                                    {"color": "red", "value": 10000}
                                ]
                            }
                        }
                    }
                }
            ],
            "time": {"from": "now-24h", "to": "now"},
            "refresh": "30s"
        }
    }
    return dashboard

def write_dashboard(dashboard_name: str, dashboard: dict):
    """Write dashboard JSON to file"""
    output_dir = Path("monitoring/grafana-dashboards")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = output_dir / f"{dashboard_name}.json"
    json_str = json.dumps(dashboard, indent=2)
    output_file.write_text(json_str, encoding="utf-8")
    print(f"Created dashboard: {output_file}")

def main():
    """Create remaining Grafana dashboards"""
    dashboards = [
        ("governance-gates", create_governance_gates_dashboard()),
        ("swarm-health", create_swarm_health_dashboard()),
        ("infrastructure", create_infrastructure_dashboard()),
    ]
    
    for name, dashboard in dashboards:
        write_dashboard(name, dashboard)
    
    print("Remaining Grafana dashboards created successfully!")

if __name__ == "__main__":
    main()
