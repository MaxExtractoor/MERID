#!/usr/bin/env python3
"""
Create Grafana dashboards for MERID monitoring
Week 2: Production Operations Gate - Evidence Artifact
Date: 2026-01-26
"""

import json
from pathlib import Path

def create_system_health_dashboard():
    """Create system health dashboard JSON"""
    dashboard = {
        "dashboard": {
            "id": None,
            "title": "MERID System Health",
            "tags": ["merid", "system", "health"],
            "timezone": "browser",
            "panels": [
                {
                    "id": 1,
                    "title": "System Overview",
                    "type": "stat",
                    "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
                    "targets": [
                        {"expr": "up{job=\"merid-api\"}", "legendFormat": "API Status"}
                    ],
                    "fieldConfig": {
                        "defaults": {
                            "color": {"mode": "thresholds"},
                            "thresholds": {
                                "steps": [
                                    {"color": "red", "value": 0},
                                    {"color": "green", "value": 1}
                                ]
                            }
                        }
                    }
                },
                {
                    "id": 2,
                    "title": "API Error Rate",
                    "type": "graph",
                    "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
                    "targets": [
                        {"expr": "rate(http_requests_total{job=\"merid-api\",status=~\"5..\"}[5m])", "legendFormat": "5xx Errors"},
                        {"expr": "rate(http_requests_total{job=\"merid-api\",status=~\"4..\"}[5m])", "legendFormat": "4xx Errors"}
                    ],
                    "yAxes": [{"label": "Requests/sec", "min": 0}]
                },
                {
                    "id": 3,
                    "title": "Response Time",
                    "type": "graph",
                    "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
                    "targets": [
                        {"expr": "histogram_quantile(0.50, rate(http_request_duration_seconds_bucket{job=\"merid-api\"}[5m]))", "legendFormat": "50th percentile"},
                        {"expr": "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{job=\"merid-api\"}[5m]))", "legendFormat": "95th percentile"},
                        {"expr": "histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{job=\"merid-api\"}[5m]))", "legendFormat": "99th percentile"}
                    ],
                    "yAxes": [{"label": "Seconds", "min": 0}]
                },
                {
                    "id": 4,
                    "title": "System Resources",
                    "type": "graph",
                    "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
                    "targets": [
                        {"expr": "100 - (avg by (instance) (rate(node_cpu_seconds_total{mode=\"idle\"}[5m])) * 100)", "legendFormat": "CPU Usage %"},
                        {"expr": "(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes * 100", "legendFormat": "Memory Usage %"}
                    ],
                    "yAxes": [{"label": "Percentage", "min": 0, "max": 100}]
                },
                {
                    "id": 5,
                    "title": "Database Health",
                    "type": "stat",
                    "gridPos": {"h": 4, "w": 6, "x": 0, "y": 16},
                    "targets": [
                        {"expr": "up{job=\"neo4j\"}", "legendFormat": "Neo4j"}
                    ],
                    "fieldConfig": {
                        "defaults": {
                            "color": {"mode": "thresholds"},
                            "thresholds": {
                                "steps": [
                                    {"color": "red", "value": 0},
                                    {"color": "green", "value": 1}
                                ]
                            }
                        }
                    }
                },
                {
                    "id": 6,
                    "title": "Cache Health",
                    "type": "stat",
                    "gridPos": {"h": 4, "w": 6, "x": 6, "y": 16},
                    "targets": [
                        {"expr": "up{job=\"redis\"}", "legendFormat": "Redis"}
                    ],
                    "fieldConfig": {
                        "defaults": {
                            "color": {"mode": "thresholds"},
                            "thresholds": {
                                "steps": [
                                    {"color": "red", "value": 0},
                                    {"color": "green", "value": 1}
                                ]
                            }
                        }
                    }
                },
                {
                    "id": 7,
                    "title": "Active Alerts",
                    "type": "stat",
                    "gridPos": {"h": 4, "w": 6, "x": 12, "y": 16},
                    "targets": [
                        {"expr": "ALERTS_FOR_STATE{state=\"firing\"}", "legendFormat": "Firing Alerts"}
                    ],
                    "fieldConfig": {
                        "defaults": {
                            "color": {"mode": "thresholds"},
                            "thresholds": {
                                "steps": [
                                    {"color": "green", "value": 0},
                                    {"color": "yellow", "value": 1},
                                    {"color": "red", "value": 5}
                                ]
                            }
                        }
                    }
                },
                {
                    "id": 8,
                    "title": "Request Rate",
                    "type": "graph",
                    "gridPos": {"h": 4, "w": 6, "x": 18, "y": 16},
                    "targets": [
                        {"expr": "rate(http_requests_total{job=\"merid-api\"}[5m])", "legendFormat": "Requests/sec"}
                    ],
                    "yAxes": [{"label": "Requests/sec", "min": 0}]
                }
            ],
            "time": {"from": "now-1h", "to": "now"},
            "refresh": "30s"
        }
    }
    return dashboard

def create_api_performance_dashboard():
    """Create API performance dashboard JSON"""
    dashboard = {
        "dashboard": {
            "id": None,
            "title": "MERID API Performance",
            "tags": ["merid", "api", "performance"],
            "timezone": "browser",
            "panels": [
                {
                    "id": 1,
                    "title": "Request Rate",
                    "type": "graph",
                    "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
                    "targets": [
                        {"expr": "rate(http_requests_total{job=\"merid-api\"}[5m])", "legendFormat": "Total Requests"},
                        {"expr": "rate(http_requests_total{job=\"merid-api\",status=~\"2..\"}[5m])", "legendFormat": "Success Requests"}
                    ],
                    "yAxes": [{"label": "Requests/sec", "min": 0}]
                },
                {
                    "id": 2,
                    "title": "Response Time Percentiles",
                    "type": "graph",
                    "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
                    "targets": [
                        {"expr": "histogram_quantile(0.50, rate(http_request_duration_seconds_bucket{job=\"merid-api\"}[5m]))", "legendFormat": "P50"},
                        {"expr": "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{job=\"merid-api\"}[5m]))", "legendFormat": "P95"},
                        {"expr": "histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{job=\"merid-api\"}[5m]))", "legendFormat": "P99"}
                    ],
                    "yAxes": [{"label": "Seconds", "min": 0}]
                },
                {
                    "id": 3,
                    "title": "Error Rate by Status",
                    "type": "graph",
                    "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
                    "targets": [
                        {"expr": "rate(http_requests_total{job=\"merid-api\",status=\"500\"}[5m])", "legendFormat": "500 Server Error"},
                        {"expr": "rate(http_requests_total{job=\"merid-api\",status=\"503\"}[5m])", "legendFormat": "503 Service Unavailable"},
                        {"expr": "rate(http_requests_total{job=\"merid-api\",status=\"504\"}[5m])", "legendFormat": "504 Gateway Timeout"}
                    ],
                    "yAxes": [{"label": "Errors/sec", "min": 0}]
                },
                {
                    "id": 4,
                    "title": "Response Time Distribution",
                    "type": "heatmap",
                    "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
                    "targets": [
                        {"expr": "rate(http_request_duration_seconds_bucket{job=\"merid-api\"}[5m])", "legendFormat": "{{le}}"}
                    ]
                },
                {
                    "id": 5,
                    "title": "API Health Score",
                    "type": "stat",
                    "gridPos": {"h": 4, "w": 6, "x": 0, "y": 16},
                    "targets": [
                        {"expr": "rate(http_requests_total{job=\"merid-api\",status=~\"2..\"}[5m]) / rate(http_requests_total{job=\"merid-api\"}[5m]) * 100", "legendFormat": "Success Rate"}
                    ],
                    "fieldConfig": {
                        "defaults": {
                            "unit": "percent",
                            "color": {"mode": "thresholds"},
                            "thresholds": {
                                "steps": [
                                    {"color": "red", "value": 95},
                                    {"color": "yellow", "value": 98},
                                    {"color": "green", "value": 99}
                                ]
                            }
                        }
                    }
                },
                {
                    "id": 6,
                    "title": "Average Response Time",
                    "type": "stat",
                    "gridPos": {"h": 4, "w": 6, "x": 6, "y": 16},
                    "targets": [
                        {"expr": "histogram_quantile(0.50, rate(http_request_duration_seconds_bucket{job=\"merid-api\"}[5m]))", "legendFormat": "P50 Response Time"}
                    ],
                    "fieldConfig": {
                        "defaults": {
                            "unit": "s",
                            "color": {"mode": "thresholds"},
                            "thresholds": {
                                "steps": [
                                    {"color": "green", "value": 0.5},
                                    {"color": "yellow", "value": 1.0},
                                    {"color": "red", "value": 2.0}
                                ]
                            }
                        }
                    }
                }
            ],
            "time": {"from": "now-24h", "to": "now"},
            "refresh": "15s"
        }
    }
    return dashboard

def create_database_health_dashboard():
    """Create database health dashboard JSON"""
    dashboard = {
        "dashboard": {
            "id": None,
            "title": "MERID Database Health",
            "tags": ["merid", "database", "health"],
            "timezone": "browser",
            "panels": [
                {
                    "id": 1,
                    "title": "Database Status",
                    "type": "stat",
                    "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
                    "targets": [
                        {"expr": "up{job=\"neo4j\"}", "legendFormat": "Neo4j"},
                        {"expr": "up{job=\"redis\"}", "legendFormat": "Redis"}
                    ],
                    "fieldConfig": {
                        "defaults": {
                            "color": {"mode": "thresholds"},
                            "thresholds": {
                                "steps": [
                                    {"color": "red", "value": 0},
                                    {"color": "green", "value": 1}
                                ]
                            }
                        }
                    }
                },
                {
                    "id": 2,
                    "title": "Connection Pool Usage",
                    "type": "graph",
                    "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
                    "targets": [
                        {"expr": "neo4j_database_pool_active", "legendFormat": "Active Connections"},
                        {"expr": "neo4j_database_pool_max", "legendFormat": "Max Connections"},
                        {"expr": "neo4j_database_pool_idle", "legendFormat": "Idle Connections"}
                    ],
                    "yAxes": [{"label": "Connections", "min": 0}]
                },
                {
                    "id": 3,
                    "title": "Query Performance",
                    "type": "graph",
                    "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
                    "targets": [
                        {"expr": "rate(neo4j_database_query_total[5m])", "legendFormat": "Queries/sec"},
                        {"expr": "histogram_quantile(0.95, rate(neo4j_database_query_duration_seconds_bucket[5m]))", "legendFormat": "P95 Query Time"}
                    ],
                    "yAxes": [{"label": "Value", "min": 0}]
                },
                {
                    "id": 4,
                    "title": "Redis Performance",
                    "type": "graph",
                    "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
                    "targets": [
                        {"expr": "rate(redis_commands_total[5m])", "legendFormat": "Commands/sec"},
                        {"expr": "redis_connected_clients", "legendFormat": "Connected Clients"},
                        {"expr": "redis_used_memory / redis_memory_max_bytes * 100", "legendFormat": "Memory Usage %"}
                    ],
                    "yAxes": [{"label": "Value", "min": 0}]
                },
                {
                    "id": 5,
                    "title": "Database Size",
                    "type": "stat",
                    "gridPos": {"h": 4, "w": 6, "x": 0, "y": 16},
                    "targets": [
                        {"expr": "neo4j_database_size_bytes", "legendFormat": "Neo4j Size"}
                    ],
                    "fieldConfig": {
                        "defaults": {
                            "unit": "bytes",
                            "color": {"mode": "thresholds"},
                            "thresholds": {
                                "steps": [
                                    {"color": "green", "value": 0},
                                    {"color": "yellow", "value": 10737418240},  # 10GB
                                    {"color": "red", "value": 21474836480}      # 20GB
                                ]
                            }
                        }
                    }
                },
                {
                    "id": 6,
                    "title": "Cache Hit Rate",
                    "type": "stat",
                    "gridPos": {"h": 4, "w": 6, "x": 6, "y": 16},
                    "targets": [
                        {"expr": "rate(redis_keyspace_hits_total[5m]) / (rate(redis_keyspace_hits_total[5m]) + rate(redis_keyspace_misses_total[5m])) * 100", "legendFormat": "Hit Rate"}
                    ],
                    "fieldConfig": {
                        "defaults": {
                            "unit": "percent",
                            "color": {"mode": "thresholds"},
                            "thresholds": {
                                "steps": [
                                    {"color": "red", "value": 80},
                                    {"color": "yellow", "value": 90},
                                    {"color": "green", "value": 95}
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
    """Create all Grafana dashboards"""
    dashboards = [
        ("system-health", create_system_health_dashboard()),
        ("api-performance", create_api_performance_dashboard()),
        ("database-health", create_database_health_dashboard()),
    ]
    
    for name, dashboard in dashboards:
        write_dashboard(name, dashboard)
    
    print("All Grafana dashboards created successfully!")

if __name__ == "__main__":
    main()
