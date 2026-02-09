# MERID Local Development Guide

## Quick Start

```bash
# Run the setup script
./scripts/setup-local-dev.sh

# Or manually start services
docker-compose up -d postgres redis neo4j ollama wiremock prometheus grafana

# Pull an LLM model
docker exec merid-ollama ollama pull llama3

# Start MERID API
uvicorn web.main:app --host 0.0.0.0 --port 8000 --reload

# Start React dashboard (in another terminal)
cd web/react && npm run dev
```

## Services

| Service | URL | Credentials | Purpose |
|---------|-----|-------------|---------|
| MERID API | http://localhost:8000 | - | FastAPI backend |
| React Dashboard | http://localhost:5173 | - | Frontend UI (Vite dev server) |
| Neo4j | http://localhost:7474 | neo4j/merid | Graph database |
| PostgreSQL | localhost:5432 | merid/merid_local_dev | Relational data (optional, not currently used) |
| Redis | localhost:6379 | - | Cache & pub/sub |
| Prometheus | http://localhost:9090 | - | Metrics |
| Grafana | http://localhost:3001 | admin/merid_local | Dashboards |
| Jaeger | http://localhost:16686 | - | Tracing |
| WireMock | http://localhost:8080 | - | Mock APIs |
| Ollama | http://localhost:11434 | - | Local LLMs |
| Portainer | http://localhost:9000 | - | Container UI |

## Environment Variables

Create `.env.local`:

```bash
# LLM
OLLAMA_BASE_URL=http://localhost:11434
DEEPSEEK_API_KEY=your_key

# Databases
DATABASE_URL=postgresql://merid:merid_local_dev@localhost:5432/merid
REDIS_URL=redis://localhost:6379
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=merid

# Mock Brokers
ALPACA_API_KEY=mock_alpaca_key
ALPACA_SECRET_KEY=mock_alpaca_secret
ALPACA_BASE_URL=http://localhost:8080
KALSHI_API_KEY=mock_kalshi_key
KALSHI_BASE_URL=http://localhost:8080
```

## Running Tests

```bash
# Golden path suite (490 tests)
make golden-path

# Full preflight (tests + readiness + drift + risk context)
make preflight

# Unit tests directly
pytest tests/ -v --tb=short
```

## Mock Broker APIs

WireMock provides mock responses for:
- Alpaca Trading API (`/v2/account`, `/v2/orders`, `/v2/positions`)
- Kalshi API
- Polygon market data

Access mock admin UI at http://localhost:8080/__admin/

## Pulling Ollama Models

```bash
# Pull Llama 3
docker exec merid-ollama ollama pull llama3

# Pull CodeLlama
docker exec merid-ollama ollama pull codellama

# Pull Gemma
docker exec merid-ollama ollama pull gemma:7b

# List available models
docker exec merid-ollama ollama list
```

## Troubleshooting

### Port Conflicts

If ports are already in use, modify `docker-compose.yml` port mappings:

```yaml
ports:
  - "8001:8000"  # Use 8001 instead of 8000
```

### Database Reset

```bash
# Reset PostgreSQL
docker-compose down postgres
docker volume rm merid_postgres_data
docker-compose up -d postgres

# Reset Neo4j
docker-compose down neo4j
docker volume rm merid_neo4j_data
docker-compose up -d neo4j
```

### Ollama GPU Support (Linux)

```yaml
ollama:
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

### Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f merid-api
docker-compose logs -f ollama
```

## Production Parity

Local dev mirrors production via:
- Same Docker images (PostgreSQL 16, Redis 7, Neo4j 5)
- Same FastAPI/Uvicorn configuration
- Same environment variable names
- Same Prometheus metrics endpoints

Deploy to production:
```bash
# GitHub Actions handles deployment
git push origin main
```
