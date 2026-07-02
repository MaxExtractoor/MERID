"""
Performance Monitoring with Prometheus & Grafana on ECS Fargate

Complete monitoring solution for Kalshi stack with Prometheus metrics and Grafana dashboards.
"""

from prometheus_client import Counter, Histogram, Gauge, generate_latest, CollectorRegistry
from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
from typing import Dict, Any, Optional
import time
import logging
import asyncio
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# Prometheus metrics
REGISTRY = CollectorRegistry()

# API metrics
API_REQUESTS_TOTAL = Counter(
    'api_requests_total',
    'Total API requests',
    ['method', 'endpoint', 'status'],
    registry=REGISTRY
)

API_REQUEST_LATENCY = Histogram(
    'api_request_latency_seconds',
    'API request latency',
    ['method', 'endpoint'],
    registry=REGISTRY
)

API_ACTIVE_CONNECTIONS = Gauge(
    'api_active_connections',
    'Number of active connections',
    registry=REGISTRY
)

# Kalshi-specific metrics
KELLY_FRACTION_GAUGE = Gauge(
    'kelly_fraction_current',
    'Current Kelly fraction',
    ['strategy_type'],
    registry=REGISTRY
)

VIX_VALUE_GAUGE = Gauge(
    'vix_value_current',
    'Current VIX value',
    registry=REGISTRY
)

VIX_RANK_GAUGE = Gauge(
    'vix_rank_current',
    'Current VIX rank percentile',
    registry=REGISTRY
)

ALERTS_TOTAL = Counter(
    'alerts_total',
    'Total alerts triggered',
    ['alert_type', 'severity'],
    registry=REGISTRY
)

WEBSOCKET_CONNECTIONS = Gauge(
    'websocket_connections_active',
    'Active WebSocket connections',
    ['market'],
    registry=REGISTRY
)

WEBSOCKET_RECONNECTS = Counter(
    'websocket_reconnects_total',
    'Total WebSocket reconnections',
    ['market', 'reason'],
    registry=REGISTRY

)

# Business metrics
POSITION_SIZE_GAUGE = Gauge(
    'position_size_current',
    'Current position size',
    ['asset', 'strategy'],
    registry=REGISTRY
)

PNL_TOTAL = Gauge(
    'pnl_total',
    'Total PnL',
    ['strategy'],
    registry=REGISTRY
)

RISK_OF_RUIN_GAUGE = Gauge(
    'risk_of_ruin_current',
    'Current risk of ruin',
    ['strategy'],
    registry=REGISTRY
)

class PrometheusMetrics:
    """
    Prometheus metrics collector for Kalshi application.
    """
    
    def __init__(self):
        self.start_time = time.time()
        self.request_count = 0
        
    def record_api_request(self, method: str, endpoint: str, status_code: int, latency: float):
        """Record API request metrics."""
        API_REQUESTS_TOTAL.labels(
            method=method,
            endpoint=endpoint,
            status=str(status_code)
        ).inc()
        
        API_REQUEST_LATENCY.labels(
            method=method,
            endpoint=endpoint
        ).observe(latency)
        
        self.request_count += 1
    
    def update_kelly_metrics(self, base_kelly: float, hybrid_fraction: float, strategy: str = "hybrid"):
        """Update Kelly-related metrics."""
        KELLY_FRACTION_GAUGE.labels(strategy_type="base").set(base_kelly)
        KELLY_FRACTION_GAUGE.labels(strategy_type=strategy).set(hybrid_fraction)
    
    def update_vix_metrics(self, vix_value: float, vix_rank: float):
        """Update VIX-related metrics."""
        VIX_VALUE_GAUGE.set(vix_value)
        VIX_RANK_GAUGE.set(vix_rank)
    
    def record_alert(self, alert_type: str, severity: str):
        """Record alert metrics."""
        ALERTS_TOTAL.labels(alert_type=alert_type, severity=severity).inc()
    
    def update_websocket_metrics(self, market: str, connections: int):
        """Update WebSocket metrics."""
        WEBSOCKET_CONNECTIONS.labels(market=market).set(connections)
    
    def record_websocket_reconnect(self, market: str, reason: str):
        """Record WebSocket reconnection."""
        WEBSOCKET_RECONNECTS.labels(market=market, reason=reason).inc()
    
    def update_position_metrics(self, asset: str, strategy: str, size: float):
        """Update position metrics."""
        POSITION_SIZE_GAUGE.labels(asset=asset, strategy=strategy).set(size)
    
    def update_pnl(self, strategy: str, pnl: float):
        """Update PnL metrics."""
        PNL_TOTAL.labels(strategy=strategy).set(pnl)
    
    def update_risk_metrics(self, strategy: str, risk_of_ruin: float):
        """Update risk metrics."""
        RISK_OF_RUIN_GAUGE.labels(strategy=strategy).set(risk_of_ruin)
    
    def get_metrics(self) -> str:
        """Get all metrics in Prometheus format."""
        return generate_latest(REGISTRY)

# Global metrics instance
metrics = PrometheusMetrics()

def create_prometheus_middleware(app: FastAPI):
    """
    Create Prometheus middleware for FastAPI application.
    """
    
    @app.middleware("http")
    async def prometheus_middleware(request: Request, call_next):
        start_time = time.time()
        
        # Increment active connections
        API_ACTIVE_CONNECTIONS.inc()
        
        try:
            response = await call_next(request)
            
            # Record metrics
            latency = time.time() - start_time
            metrics.record_api_request(
                method=request.method,
                endpoint=request.url.path,
                status_code=response.status_code,
                latency=latency
            )
            
            return response
            
        finally:
            # Decrement active connections
            API_ACTIVE_CONNECTIONS.dec()
    
    @app.get("/metrics")
    async def metrics_endpoint():
        """Prometheus metrics endpoint."""
        return PlainTextResponse(
            metrics.get_metrics(),
            media_type="text/plain; version=0.0.4; charset=utf-8"
        )

class GrafanaDashboardConfig:
    """
    Grafana dashboard configuration for Kalshi monitoring.
    """
    
    @staticmethod
    def create_kelly_dashboard() -> Dict[str, Any]:
        """Create Kelly monitoring dashboard configuration."""
        return {
            "dashboard": {
                "title": "Kalshi Kelly Strategy Monitoring",
                "panels": [
                    {
                        "title": "Kelly Fraction",
                        "type": "stat",
                        "targets": [
                            {
                                "expr": "kelly_fraction_current{strategy_type=\"hybrid\"}",
                                "legendFormat": "Hybrid Kelly"
                            },
                            {
                                "expr": "kelly_fraction_current{strategy_type=\"base\"}",
                                "legendFormat": "Base Kelly"
                            }
                        ],
                        "fieldConfig": {
                            "defaults": {
                                "unit": "short",
                                "min": 0,
                                "max": 1
                            }
                        }
                    },
                    {
                        "title": "VIX Metrics",
                        "type": "stat",
                        "targets": [
                            {
                                "expr": "vix_value_current",
                                "legendFormat": "VIX Value"
                            },
                            {
                                "expr": "vix_rank_current",
                                "legendFormat": "VIX Rank"
                            }
                        ],
                        "fieldConfig": {
                            "defaults": {
                                "unit": "short",
                                "min": 0
                            }
                        }
                    },
                    {
                        "title": "API Request Rate",
                        "type": "graph",
                        "targets": [
                            {
                                "expr": "rate(api_requests_total[5m])",
                                "legendFormat": "{{method}} {{endpoint}}"
                            }
                        ]
                    },
                    {
                        "title": "API Latency",
                        "type": "graph",
                        "targets": [
                            {
                                "expr": "histogram_quantile(0.95, rate(api_request_latency_seconds_bucket[5m]))",
                                "legendFormat": "95th percentile"
                            },
                            {
                                "expr": "histogram_quantile(0.50, rate(api_request_latency_seconds_bucket[5m]))",
                                "legendFormat": "50th percentile"
                            }
                        ]
                    },
                    {
                        "title": "Alerts",
                        "type": "graph",
                        "targets": [
                            {
                                "expr": "rate(alerts_total[5m])",
                                "legendFormat": "{{alert_type}} {{severity}}"
                            }
                        ]
                    }
                ]
            }
        }
    
    @staticmethod
    def create_system_dashboard() -> Dict[str, Any]:
        """Create system monitoring dashboard configuration."""
        return {
            "dashboard": {
                "title": "Kalshi System Monitoring",
                "panels": [
                    {
                        "title": "Active Connections",
                        "type": "stat",
                        "targets": [
                            {
                                "expr": "api_active_connections",
                                "legendFormat": "API Connections"
                            },
                            {
                                "expr": "websocket_connections_active",
                                "legendFormat": "WebSocket Connections"
                            }
                        ]
                    },
                    {
                        "title": "WebSocket Reconnections",
                        "type": "graph",
                        "targets": [
                            {
                                "expr": "rate(websocket_reconnects_total[5m])",
                                "legendFormat": "{{market}} {{reason}}"
                            }
                        ]
                    },
                    {
                        "title": "Position Sizes",
                        "type": "graph",
                        "targets": [
                            {
                                "expr": "position_size_current",
                                "legendFormat": "{{asset}} {{strategy}}"
                            }
                        ]
                    },
                    {
                        "title": "PnL",
                        "type": "graph",
                        "targets": [
                            {
                                "expr": "pnl_total",
                                "legendFormat": "{{strategy}}"
                            }
                        ]
                    },
                    {
                        "title": "Risk of Ruin",
                        "type": "gauge",
                        "targets": [
                            {
                                "expr": "risk_of_ruin_current",
                                "legendFormat": "{{strategy}}"
                            }
                        ]
                    }
                ]
            }
        }

# Prometheus configuration for ECS
PROMETHEUS_CONFIG = """
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'kalshi-api'
    metrics_path: /metrics
    static_configs:
      - targets: ['kalshi-api:8011']
    scrape_interval: 10s
    metrics_path: /metrics

  - job_name: 'kalshi-dashboard'
    metrics_path: /metrics
    static_configs:
      - targets: ['kalshi-dashboard:8501']
    scrape_interval: 30s

  - job_name: 'ecs-metrics'
    ec2_sd_configs:
      - region: us-east-1
        port: 9100
    relabel_configs:
      - source_labels: [__meta_ec2_tag_Name]
        regex: kalshi-.*
        action: keep
"""

# Grafana Agent configuration for ECS
GRAFANA_AGENT_CONFIG = """
integrations:
  prometheus_remote_write:
    - url: https://prometheus-us-east-1.grafana.net/api/prom/push
      basic_auth:
        username: ${GRAFANA_CLOUD_USERNAME}
        password: ${GRAFANA_CLOUD_API_KEY}

prometheus:
  global:
    scrape_interval: 15s
  configs:
    - job_name: 'kalshi-api'
      static_configs:
        - targets: ['localhost:8011']
      metrics_path: /metrics
      relabel_configs:
        - source_labels: [__address__]
          target_label: instance
          replacement: 'kalshi-api'
    - job_name: 'kalshi-dashboard'
      static_configs:
        - targets: ['localhost:8501']
      metrics_path: /metrics
      relabel_configs:
        - source_labels: [__address__]
          target_label: instance
          replacement: 'kalshi-dashboard'

logs:
  positions:
    filename: /tmp/positions.yaml
  configs:
    - name: kalshi-logs
      clients:
        - url: http://localhost:3500
          tenant: default
    scrape_configs:
      - job_name: kalshi-logs
        static_configs:
          - targets:
              - localhost
        labels:
          job: kalshi-logs
          __path__: /var/log/app/*.log
"""

# Docker Compose monitoring service
MONITORING_DOCKER_COMPOSE = """
version: "3.9"
services:
  prometheus:
    image: prom/prometheus:latest
    container_name: kalshi-prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/etc/prometheus/console_libraries'
      - '--web.console.templates=/etc/prometheus/consoles'
      - '--storage.tsdb.retention.time=200h'
      - '--web.enable-lifecycle'
    restart: unless-stopped
    networks:
      - kalshi-network

  grafana:
    image: grafana/grafana:latest
    container_name: kalshi-grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD:-admin}
      - GF_INSTALL_PLUGINS=grafana-piechart-panel
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
    depends_on:
      - prometheus
    restart: unless-stopped
    networks:
      - kalshi-network

  grafana-agent:
    image: grafana/agent:latest
    container_name: kalshi-grafana-agent
    volumes:
      - ./grafana-agent.yaml:/etc/agent/agent.yaml:ro
    depends_on:
      - api
      - streamlit
    restart: unless-stopped
    networks:
      - kalshi-network

volumes:
  prometheus_data:
  grafana_data:

networks:
  kalshi-network:
    external: true
"""

# Example usage in FastAPI application:
"""
from fastapi import FastAPI
from prometheus_client import Counter, Histogram
import time

app = FastAPI()

# Create metrics
REQUESTS = Counter('requests_total', 'Total requests', ['method', 'endpoint'])
LATENCY = Histogram('request_latency_seconds', 'Request latency')

@app.middleware("http")
async def metrics_middleware(request, call_next):
    start_time = time.time()
    response = await call_next(request)
    latency = time.time() - start_time
    
    REQUESTS.labels(method=request.method, endpoint=request.url.path).inc()
    LATENCY.observe(latency)
    
    return response

@app.get("/metrics")
async def metrics():
    from prometheus_client import generate_latest
    return Response(generate_latest(), media_type="text/plain")

# Update custom metrics
@app.get("/update-kelly")
async def update_kelly(kelly_fraction: float):
    KELLY_FRACTION_GAUGE.set(kelly_fraction)
    return {"status": "updated"}
"""

# Example usage in Streamlit:
"""
import streamlit as st
from prometheus_client import Counter, Gauge, generate_latest
from fastapi.responses import Response
import time

# Create Streamlit metrics
STREAMLIT_SESSIONS = Counter('streamlit_sessions_total', 'Total Streamlit sessions')
STREAMLIT_INTERACTIONS = Counter('streamlit_interactions_total', 'Total Streamlit interactions', ['action'])

# Update metrics
STREAMLIT_SESSIONS.inc()
STREAMLIT_INTERACTIONS.labels(action='button_click').inc()

# Metrics endpoint for Streamlit
def create_metrics_endpoint():
    @st.cache_resource
    def get_metrics():
        return generate_latest()
    
    return get_metrics()

# In Streamlit app, you can expose metrics via a separate FastAPI endpoint
# or use Grafana Agent to scrape the application directly.
"""
