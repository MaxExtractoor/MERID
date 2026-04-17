# Deployment Guide for Kalshi MVRK Streamlit App

## Production Deployment Steps

This guide provides minimal production deployment steps for the Kalshi MVRK Streamlit dashboard.

### 1. Package Layout

```
merid/
├── kalshi/                    # API client, event bus, MVRK/Kelly modules
│   ├── __init__.py
│   ├── client.py              # Kalshi API client
│   ├── events.py              # Event bus integration
│   └── mvrk.py                # MVRK strategy implementation
├── api/                       # FastAPI app
│   ├── __init__.py
│   ├── main.py                # FastAPI application
│   ├── kalshi_endpoints.py    # Kalshi-specific endpoints
│   └── kelly_endpoints.py     # Kelly/MVRK endpoints
├── strategies/                # Strategy modules
│   ├── kalshi_mvrk_dashboard.py    # Streamlit dashboard
│   ├── kalshi_multievent_data.py   # Data fetching
│   ├── mvrk_kalshi.py              # MVRK implementation
│   └── backtest_mvrk_vs_half_kelly.py  # Backtesting
├── requirements.txt           # Python dependencies
├── .env.example              # Environment variables template
└── docker-compose.yml        # Container orchestration
```

### 2. FastAPI Server Configuration

Create `api/main.py`:

```python
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os

app = FastAPI(
    title="Kalshi MVRK API",
    description="API for Kalshi MVRK strategy monitoring",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": time.time()}

# Import endpoints
from api.kalshi_endpoints import router as kalshi_router
from api.kelly_endpoints import router as kelly_router

app.include_router(kalshi_router, prefix="/kalshi")
app.include_router(kelly_router, prefix="/kelly")

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        workers=2,
        reload=False  # Set to True for development
    )
```

### 3. Environment Configuration

Create `.env` file (development):

```bash
# Kalshi API Configuration
KALSHI_API_KEY=your_api_key_here
KALSHI_API_SECRET=your_api_secret_here
KALSHI_API_BASE=https://api.elections.kalshi.com/trade-api/v2

# Database Configuration
DATABASE_URL=postgresql://user:password@localhost:5432/kalshi_mvrk

# Redis Configuration (for caching)
REDIS_URL=redis://localhost:6379/0

# Application Configuration
LOG_LEVEL=INFO
DEBUG=false
ENVIRONMENT=development
```

### 4. FastAPI Server Startup

```bash
# Install dependencies
pip install -r requirements.txt

# Start FastAPI server
uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 2

# Or using gunicorn for production:
gunicorn api.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### 5. Streamlit App Configuration

Create `streamlit_config.toml`:

```toml
[server]
port = 8501
address = "0.0.0.0"
headless = true
enableCORS = false
enableXsrfProtection = false

[browser]
gatherUsageStats = false

[theme]
primaryColor = "#FF6B6B"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F0F2F6"
textColor = "#262730"
```

### 6. Streamlit App Startup

```bash
# Set environment variable
export KALSHI_API_BASE="http://localhost:8000"

# Start Streamlit app
streamlit run merid/strategies/kalshi_mvrk_dashboard.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --config streamlit_config.toml
```

### 7. Docker Configuration

Create `Dockerfile` for FastAPI:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
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

# Start application
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Create `Dockerfile.streamlit` for Streamlit:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
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

# Start Streamlit
CMD ["streamlit", "run", "merid/strategies/kalshi_mvrk_dashboard.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

Create `docker-compose.yml`:

```yaml
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
    volumes:
      - ./logs:/app/logs
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  streamlit:
    build:
      context: .
      dockerfile: Dockerfile.streamlit
    ports:
      - "8501:8501"
    environment:
      - KALSHI_API_BASE=http://fastapi:8000
    depends_on:
      - fastapi
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped

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

volumes:
  redis_data:
  postgres_data:
```

### 8. Reverse Proxy Configuration

#### Nginx Configuration

Create `nginx.conf`:

```nginx
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

        ssl_certificate /etc/ssl/certs/your-cert.pem;
        ssl_certificate_key /etc/ssl/private/your-key.pem;

        # API routes
        location /api/ {
            proxy_pass http://fastapi_backend/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # Kalshi endpoints
        location /kalshi/ {
            proxy_pass http://fastapi_backend/kalshi/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # Kelly endpoints
        location /kelly/ {
            proxy_pass http://fastapi_backend/kelly/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # Streamlit dashboard
        location / {
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
    }
}
```

#### Caddy Configuration

Create `Caddyfile`:

```caddyfile
your-domain.com {
    encode gzip

    # API routes
    handle /api/* {
        reverse_proxy fastapi:8000
    }

    # Kalshi endpoints
    handle /kalshi/* {
        reverse_proxy fastapi:8000
    }

    # Kelly endpoints
    handle /kelly/* {
        reverse_proxy fastapi:8000
    }

    # Streamlit dashboard (default)
    handle {
        reverse_proxy streamlit:8501
    }
}

# HTTP to HTTPS redirect
http://your-domain.com {
    redir https://{host}{uri}
}
```

### 9. Production Deployment Commands

```bash
# Build and start with Docker Compose
docker-compose up -d --build

# Check service status
docker-compose ps

# View logs
docker-compose logs -f fastapi
docker-compose logs -f streamlit

# Scale services
docker-compose up -d --scale fastapi=3

# Update services
docker-compose pull
docker-compose up -d
```

### 10. Monitoring and Logging

#### Health Checks

Add to FastAPI `api/main.py`:

```python
from fastapi import HTTPException
import time
import psutil

@app.get("/health/detailed")
async def detailed_health_check():
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "cpu_percent": psutil.cpu_percent(),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_usage": psutil.disk_usage('/').percent,
        "active_connections": len(psutil.net_connections()),
    }
```

#### Logging Configuration

Create `logging_config.py`:

```python
import logging.config

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        },
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
            "formatter": "default",
            "level": "INFO",
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["console", "file"],
    },
}
```

### 11. Security Considerations

- **API Keys**: Store in environment variables or secret manager
- **HTTPS**: Always use HTTPS in production
- **CORS**: Configure specific origins instead of "*"
- **Rate Limiting**: Implement rate limiting on API endpoints
- **Authentication**: Add JWT or OAuth2 for protected endpoints
- **Input Validation**: Validate all API inputs
- **SQL Injection**: Use parameterized queries
- **XSS Protection**: Sanitize user inputs

### 12. Performance Optimization

- **Caching**: Use Redis for frequently accessed data
- **Database Indexing**: Add indexes for common queries
- **Connection Pooling**: Configure database connection pools
- **Load Balancing**: Use multiple FastAPI workers
- **CDN**: Serve static assets via CDN
- **Compression**: Enable gzip compression

### 13. Backup and Recovery

- **Database Backups**: Regular automated backups
- **Configuration Backups**: Version control configuration files
- **Log Rotation**: Implement log rotation policies
- **Monitoring**: Set up alerts for service downtime
- **Disaster Recovery**: Document recovery procedures

### 14. Development Workflow

```bash
# Development setup
git clone <repository>
cd merid
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Run tests
pytest tests/

# Development servers
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
streamlit run merid/strategies/kalshi_mvrk_dashboard.py --server.port 8501

# Code quality
black merid/
flake8 merid/
mypy merid/
```

This deployment guide provides a complete production-ready setup for the Kalshi MVRK Streamlit dashboard with FastAPI backend, following modern DevOps best practices.
