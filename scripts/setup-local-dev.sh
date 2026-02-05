#!/bin/bash
# MERID Local Development Setup Script
# Usage: ./scripts/setup-local-dev.sh

set -e

echo "🚀 Setting up MERID local development environment..."

# Check prerequisites
echo "📋 Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

echo "✅ Docker and Docker Compose found"

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p docker/wiremock/mappings
mkdir -p docker/wiremock/__files
mkdir -p docker/grafana/dashboards
mkdir -p docker/prometheus
echo "✅ Directories created"

# Create .env.local if it doesn't exist
if [ ! -f .env.local ]; then
    echo "📝 Creating .env.local..."
    cat > .env.local << 'EOF'
# Local Development Environment Variables
OLLAMA_BASE_URL=http://localhost:11434
DATABASE_URL=postgresql://merid:merid_local_dev@localhost:5432/merid
REDIS_URL=redis://localhost:6379
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=merid
PROMETHEUS_PUSHGATEWAY=localhost:9091
ALPACA_API_KEY=mock_alpaca_key
ALPACA_SECRET_KEY=mock_alpaca_secret
ALPACA_BASE_URL=http://localhost:8080
KALSHI_API_KEY=mock_kalshi_key
KALSHI_BASE_URL=http://localhost:8080
EOF
    echo "✅ .env.local created"
fi

# Pull images
echo "🐳 Pulling Docker images..."
docker-compose pull
echo "✅ Images pulled"

# Start core services
echo "🚀 Starting core services..."
docker-compose up -d postgres redis neo4j ollama wiremock prometheus grafana jaeger portainer
echo "✅ Core services started"

# Wait for services to be ready
echo "⏳ Waiting for services to be ready..."
sleep 10

echo ""
echo "🎉 MERID local development environment is ready!"
echo ""
echo "📍 Access points:"
echo "  - MERID API:       http://localhost:8000"
echo "  - React Dashboard: http://localhost:3000"
echo "  - Neo4j Browser:   http://localhost:7474 (neo4j/merid)"
echo "  - Redis:           localhost:6379"
echo "  - PostgreSQL:      localhost:5432 (merid/merid_local_dev)"
echo "  - Prometheus:      http://localhost:9090"
echo "  - Grafana:         http://localhost:3001 (admin/merid_local)"
echo "  - Jaeger:          http://localhost:16686"
echo "  - Portainer:       http://localhost:9000"
echo "  - WireMock:        http://localhost:8080"
echo "  - Ollama:          http://localhost:11434"
echo ""
echo "📚 Useful commands:"
echo "  - Start all:       docker-compose up -d"
echo "  - Stop all:        docker-compose down"
echo "  - View logs:       docker-compose logs -f [service]"
echo "  - Pull Ollama model: docker exec merid-ollama ollama pull llama3"
echo ""
