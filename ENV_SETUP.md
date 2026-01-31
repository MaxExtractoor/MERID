# MERID Environment Configuration

## Quick Setup

1. Copy the environment template:
```bash
cp .env.example .env
```

2. Fill in the required values for your environment

3. Start the system:
```bash
python main.py
```

## Key Environment Variables

### **Required for Basic Operation**
- `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` - Graph database connection
- `REDIS_URL` - Caching and session storage
- `OLLAMA_BASE_URL` - LLM service endpoint

### **Trading & Market Data**
- `COINBASE_API_KEY`, `COINBASE_API_SECRET` - Coinbase exchange
- `KRAKEN_API_KEY`, `KRAKEN_API_SECRET` - Kraken exchange
- `ALPACA_API_KEY`, `ALPACA_API_SECRET` - Alpaca trading

### **LLM & AI Services**
- `OPENAI_API_KEY` - OpenAI GPT models
- `ANTHROPIC_API_KEY` - Claude models
- `GOOGLE_API_KEY` - Google AI models

### **System Configuration**
- `CORS_ORIGINS` - Allowed frontend origins
- `LOG_LEVEL` - System logging level
- `MODE` - Trading mode (offline/simulation/live)

## Documentation Links

- **Architecture**: [MASTER_DOCUMENTATION.md](MASTER_DOCUMENTATION.md)
- **UI Hardening**: [docs/MERID_UI_HARDENING_CHECKLIST.md](docs/MERID_UI_HARDENING_CHECKLIST.md)
- **API Reference**: [web/api/](web/api/)
- **Troubleshooting**: [docs/](docs/)

## Development Notes

- Use `.env` for local development
- Never commit `.env` to version control
- All sensitive values should use your secrets manager
- See `.env.example` for complete variable list
