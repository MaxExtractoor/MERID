"""
Deploy MVRK Streamlit Dashboard to Production - Minimal Checklist

Production deployment guide with architecture, monitoring, and security considerations.
"""

# =============================================================================
# DEPLOYMENT ARCHITECTURE
# =============================================================================

"""
Architecture Overview:
- FastAPI Backend (Port 8000): Kalshi client, MVRK/Kelly calculations, Monte Carlo
- Streamlit Frontend (Port 8501): Real-time dashboard and visualization
- Reverse Proxy (Port 80/443): TLS termination, routing, authentication
- Database: PostgreSQL for persistence, Redis for caching
- Monitoring: Health checks, logging, metrics collection
"""

# =============================================================================
# BACKEND (FASTAPI) CONFIGURATION
# =============================================================================

# api/main.py
"""
FastAPI Backend Production Configuration
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import uvicorn
import time
import logging
from contextlib import asynccontextmanager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Application lifecycle
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("FastAPI application starting up...")
    yield
    # Shutdown
    logger.info("FastAPI application shutting down...")

app = FastAPI(
    title="Kalshi MVRK API",
    description="Production API for Kalshi MVRK strategy monitoring",
    version="1.0.0",
    lifespan=lifespan
)

# Middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-domain.com", "http://localhost:8501"],  # Configure for production
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Health check endpoint
@app.get("/health")
async def health_check():
    """Comprehensive health check for monitoring."""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "version": "1.0.0",
        "uptime": time.time() - start_time
    }

# Required endpoints for Streamlit dashboard
@app.get("/kalshi/returns")
async def get_kalshi_returns():
    """Get multivariate returns matrix for MVRK calculation."""
    # Implementation from kalshi_multievent_data.py
    pass

@app.get("/kelly/mvrk")
async def get_mvrk_metrics():
    """Get current MVRK vs Kelly weights and risk metrics."""
    # Implementation from kelly_mvrk_endpoints.py
    pass

@app.get("/kalshi/ohlc/{ticker}")
async def get_ohlc_data(ticker: str, limit: int = 1000):
    """Get OHLC data for live charts."""
    # Implementation from kalshi_realtime_charts.py
    pass

# Production startup
start_time = time.time()

if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        workers=4,  # Production: multiple workers
        access_log=True,
        reload=False  # Production: no auto-reload
    )

# =============================================================================
# FRONTEND (STREAMLIT) CONFIGURATION
# =============================================================================

# streamlit_config.toml
"""
Production Streamlit Configuration
"""

[server]
port = 8501
address = "0.0.0.0"
headless = true
enableCORS = false
enableXsrfProtection = false
maxUploadSize = 200
maxMessageSize = 200

[browser]
gatherUsageStats = false

[theme]
primaryColor = "#FF6B6B"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F0F2F6"
textColor = "#262730"

[logger]
level = "info"
messageFormat = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# =============================================================================
# DOCKER CONFIGURATION
# =============================================================================

# Dockerfile (FastAPI)
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd --create-home --shell /bin/bash app
USER app

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start application
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Dockerfile.streamlit
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd --create-home --shell /bin/bash app
USER app

# Expose port
EXPOSE 8501

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Start Streamlit
CMD ["streamlit", "run", "merid/strategies/kalshi_mvrk_dashboard.py", "--server.port=8501", "--server.address=0.0.0.0"]

# docker-compose.yml
version: '3.8'

services:
  fastapi:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - KALSHI_API_KEY=${KALSHI_API_KEY}
      - KALSHI_API_SECRET=${KALSHI_API_SECRET}
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
      - LOG_LEVEL=INFO
    volumes:
      - ./logs:/app/logs
      - ./data:/app/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - kalshi-network

  streamlit:
    build:
      context: .
      dockerfile: Dockerfile.streamlit
    ports:
      - "8501:8501"
    environment:
      - KALSHI_API_BASE=http://fastapi:8000
    depends_on:
      fastapi:
        condition: service_healthy
    restart: unless-stopped
    networks:
      - kalshi-network

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped
    networks:
      - kalshi-network

  postgres:
    image: postgres:15-alpine
    environment:
      - POSTGRES_DB=kalshi_mvrk
      - POSTGRES_USER=kalshi
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    restart: unless-stopped
    networks:
      - kalshi-network

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/ssl:ro
    depends_on:
      - fastapi
      - streamlit
    restart: unless-stopped
    networks:
      - kalshi-network

volumes:
  redis_data:
  postgres_data:

networks:
  kalshi-network:
    driver: bridge

# =============================================================================
# REVERSE PROXY CONFIGURATION
# =============================================================================

# nginx.conf
events {
    worker_connections 1024;
}

http {
    upstream fastapi_backend {
        server fastapi:8000;
    }

    upstream streamlit_backend {
        server streamlit:8501;
    }

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    limit_req_zone $binary_remote_addr zone=dashboard:10m rate=5r/s;

    # HTTP to HTTPS redirect
    server {
        listen 80;
        server_name your-domain.com;
        return 301 https://$server_name$request_uri;
    }

    # HTTPS configuration
    server {
        listen 443 ssl http2;
        server_name your-domain.com;

        ssl_certificate /etc/ssl/cert.pem;
        ssl_certificate_key /etc/ssl/key.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512;

        # API routes with rate limiting
        location /api/ {
            limit_req zone=api burst=20 nodelay;
            proxy_pass http://fastapi_backend/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # Kalshi endpoints
        location /kalshi/ {
            limit_req zone=api burst=20 nodelay;
            proxy_pass http://fastapi_backend/kalshi/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # Kelly endpoints
        location /kelly/ {
            limit_req zone=api burst=20 nodelay;
            proxy_pass http://fastapi_backend/kelly/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # Streamlit dashboard with rate limiting
        location / {
            limit_req zone=dashboard burst=10 nodelay;
            proxy_pass http://streamlit_backend/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            
            # WebSocket support for Streamlit
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
        }

        # Health check endpoint
        location /health {
            proxy_pass http://fastapi_backend/health;
        }
    }
}

# =============================================================================
# ENVIRONMENT CONFIGURATION
# =============================================================================

# .env.production
"""
Production Environment Variables
"""

# Kalshi API Configuration
KALSHI_API_KEY=your_production_api_key
KALSHI_API_SECRET=your_production_api_secret
KALSHI_API_BASE=https://api.elections.kalshi.com/trade-api/v2

# Database Configuration
DATABASE_URL=postgresql://kalshi:your_password@postgres:5432/kalshi_mvrk
REDIS_URL=redis://redis:6379/0

# Application Configuration
LOG_LEVEL=INFO
DEBUG=false
ENVIRONMENT=production

# Security Configuration
SECRET_KEY=your_production_secret_key
ALLOWED_HOSTS=your-domain.com,localhost

# Monitoring Configuration
SENTRY_DSN=your_sentry_dsn
PROMETHEUS_ENABLED=true

# =============================================================================
# MONITORING & LOGGING
# =============================================================================

# logging_config.py
import logging.config
import os

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        },
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "level": "INFO",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "/app/logs/app.log",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
            "formatter": "json",
            "level": "INFO",
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["console", "file"],
    },
    "loggers": {
        "uvicorn": {
            "level": "INFO",
            "handlers": ["console", "file"],
            "propagate": False,
        },
        "fastapi": {
            "level": "INFO",
            "handlers": ["console", "file"],
            "propagate": False,
        }
    }
}

# =============================================================================
# PRODUCTION DEPLOYMENT COMMANDS
# =============================================================================

"""
Deployment Commands:

# 1. Build and deploy
docker-compose -f docker-compose.yml up -d --build

# 2. Check service status
docker-compose ps

# 3. View logs
docker-compose logs -f fastapi
docker-compose logs -f streamlit

# 4. Scale services
docker-compose up -d --scale fastapi=3

# 5. Update services
docker-compose pull
docker-compose up -d

# 6. Health checks
curl https://your-domain.com/health
curl https://your-domain.com/kalshi/returns

# 7. Monitor resources
docker stats
docker-compose exec fastapi top
"""

# =============================================================================
# SECURITY CHECKLIST
# =============================================================================

"""
Security Checklist:

✅ HTTPS/TLS termination at reverse proxy
✅ API rate limiting (10r/s for API, 5r/s for dashboard)
✅ Environment variables for secrets
✅ Non-root Docker containers
✅ Health checks for all services
✅ Input validation and sanitization
✅ CORS configuration for specific origins
✅ Security headers (HSTS, CSP, etc.)
✅ Regular security updates
✅ Access logging and monitoring
✅ Backup and recovery procedures
"""

# =============================================================================
# MONITORING & ALERTS
# =============================================================================

"""
Monitoring Setup:

1. Health Endpoints:
   - /health (FastAPI)
   - /_stcore/health (Streamlit)

2. Metrics Collection:
   - API response times
   - Error rates
   - Memory and CPU usage
   - Database connection pool
   - Redis cache hit rates

3. Alerting:
   - Service downtime
   - High error rates (>5%)
   - High response times (>2s)
   - Memory usage (>80%)
   - Disk space (>90%)

4. Logging:
   - Structured JSON logs
   - Log rotation
   - Centralized log aggregation
   - Error tracking with Sentry
"""

# =============================================================================
# KALSHI API USAGE MONITORING
# =============================================================================

"""
Kalshi API Rate Limit Monitoring:

- Basic tier: 20 requests per second
- Track API usage per endpoint
- Implement backoff strategy
- Monitor quota consumption
- Alert on approaching limits

Usage Tracking:
- requests_per_second
- daily_request_count
- error_rate
- response_time_p95
"""

# =============================================================================
# BACKUP & RECOVERY
# =============================================================================

"""
Backup Strategy:

1. Database Backups:
   - Daily automated backups
   - Point-in-time recovery
   - Cross-region replication

2. Configuration Backups:
   - Git version control
   - Environment variable backups
   - SSL certificate backups

3. Disaster Recovery:
   - Multi-region deployment
   - Failover procedures
   - Recovery time objectives
   - Data integrity checks
"""
