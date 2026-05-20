# MERID Dependencies

**Date:** 2026-05-13
**Purpose:** Document core dependencies and their usage

## Core Dependencies

### Python 3.10+
**Required:** Yes
**Purpose:** Runtime environment

### FastAPI
**Version:** ^0.104.0
**Required:** Yes
**Purpose:** Web framework for API endpoints
**Usage:**
- `web/main.py` - Main application
- `web/api/*` - API route handlers
- Web server for Kalshi trading UI

### httpx
**Version:** ^0.24.0
**Required:** Yes
**Purpose:** Async HTTP client
**Usage:**
- Kalshi API client
- External API calls
- Webhook deliveries

### Pydantic
**Version:** ^2.0.0
**Required:** Yes
**Purpose:** Data validation and settings
**Usage:**
- Configuration validation
- API request/response models
- Settings management

### PyYAML
**Version:** ^6.0.0
**Required:** Yes
**Purpose:** YAML configuration parsing
**Usage:**
- Profile configuration loading
- Agent grid configuration
- Risk limits configuration

## Logging Dependencies

### structlog
**Version:** ^23.0.0
**Required:** Yes
**Purpose:** Structured logging
**Usage:**
- Core logging infrastructure
- Context-aware logging
- JSON log formatting

## Kalshi-Specific Dependencies

### WebSockets
**Version:** ^12.0
**Required:** Yes
**Purpose:** Real-time market data
**Usage:**
- Kalshi WebSocket connection
- Market state updates
- Order status updates

## Data Processing

### numpy
**Version:** ^1.24.0
**Required:** Yes
**Purpose:** Numerical computing
**Usage:**
- Signal processing
- Risk calculations
- Performance metrics

### pandas
**Version:** ^2.0.0
**Required:** Yes
**Purpose:** Data manipulation
**Usage:**
- Time series analysis
- Backtesting
- Performance reporting

### scipy
**Version:** ^1.10.0
**Required:** Yes
**Purpose:** Scientific computing
**Usage:**
- Statistical calculations
- Optimization
- Signal analysis

## Testing Dependencies

### pytest
**Version:** ^7.4.0
**Required:** Yes
**Purpose:** Test framework
**Usage:**
- Unit tests
- Integration tests
- Test discovery

### pytest-asyncio
**Version:** ^0.21.0
**Required:** Yes
**Purpose:** Async test support
**Usage:**
- Testing async functions
- WebSocket tests
- API endpoint tests

### pytest-cov
**Version:** ^4.1.0
**Required:** No (development)
**Purpose:** Test coverage
**Usage:**
- Coverage reporting
- Coverage thresholds

## Security Dependencies

### cryptography
**Version:** ^41.0.0
**Required:** Yes
**Purpose:** Cryptographic operations
**Usage:**
- Key management
- Secure communication
- Data encryption

## Alerting Dependencies

### httpx
**Version:** ^0.24.0 (already listed)
**Required:** Yes (for alerting)
**Purpose:** Alert delivery
**Usage:**
- Slack webhook calls
- PagerDuty API calls
- Twilio SMS delivery

## Optional Dependencies

### torch
**Version:** ^2.0.0
**Required:** No (conditional)
**Purpose:** Machine learning
**Usage:**
- Neural network models
- Deep learning agents
- Only loaded when TORCH_AVAILABLE

### gymnasium
**Version:** ^0.29.0
**Required:** No (conditional)
**Purpose:** Reinforcement learning
**Usage:**
- RL environments
- Swarm training
- Only loaded when gym available

## Development Dependencies

### black
**Version:** ^23.0.0
**Required:** No (development)
**Purpose:** Code formatting
**Usage:**
- Consistent code style
- Pre-commit hooks

### mypy
**Version:** ^1.5.0
**Required:** No (development)
**Purpose:** Type checking
**Usage:**
- Static type analysis
- Type hints validation

### ruff
**Version:** ^0.1.0
**Required:** No (development)
**Purpose:** Linting
**Usage:**
- Code quality checks
- Fast linting

## Dependency Management

### Installation
```bash
# Core dependencies
pip install -r requirements.txt

# Development dependencies
pip install -r requirements-dev.txt
```

### Version Updates
- Use semantic versioning (^) for compatible updates
- Pin exact versions for critical security dependencies
- Review updates before applying

### Security Scanning
- Run `pip-audit` regularly
- Review CVE reports
- Update dependencies with security patches

## Dependency Health

### Current Status
- All core dependencies up to date
- No known security vulnerabilities
- Optional dependencies properly guarded

### Monitoring
- Monitor dependency updates
- Review deprecation notices
- Plan migration for deprecated packages

## Dependency Conflicts

### Known Conflicts
None currently reported.

### Resolution Strategy
- Use virtual environments to isolate dependencies
- Pin versions in requirements.txt
- Use dependency resolver for conflicts

## External Service Dependencies

### Kalshi API
**Required:** Yes (for trading)
**Purpose:** Trading venue
**Usage:**
- Market data
- Order submission
- Account management

### CoinGecko API
**Required:** Yes (fallback)
**Purpose:** Price data
**Usage:**
- Spot price fallback
- Market data backup

### Coinbase API
**Required:** Yes (fallback)
**Purpose:** Price data
**Usage:**
- Spot price fallback
- Market data backup

## System Dependencies

### Redis
**Required:** No (legacy, not used in Kalshi-only mode)
**Purpose:** Caching
**Status:** Not used in Kalshi-only configuration

### Neo4j
**Required:** No (legacy, not used in Kalshi-only mode)
**Purpose:** Graph database
**Status:** Not used in Kalshi-only configuration

## Dependency Removal History

### Removed Dependencies (Kalshi Pivot 2026-02-21)
- blockchain (not needed for Kalshi-only)
- web3 (not needed for Kalshi-only)
- ccxt (multi-exchange, not needed)
- Polymarket SDK (not needed)
- ML/RL frameworks (torch, gym, stable-baselines3) - made optional
- Web scraping libraries (not needed)
- Social media libraries (not needed)
- Workflow orchestration (not needed)

### Rationale
Kalshi pivot to single-venue trading reduced dependency footprint significantly. Removed dependencies were for multi-exchange, blockchain, and ML features not needed for Kalshi prediction market trading.

## Dependency Best Practices

1. **Minimal Dependencies:** Keep dependency footprint small
2. **Clear Purpose:** Each dependency must have clear usage
3. **Security First:** Monitor and update security patches
4. **Version Pinning:** Pin versions for reproducibility
5. **Guarded Loading:** Optional dependencies guarded with try/except
6. **Regular Updates:** Review and update dependencies regularly
7. **Documentation:** Document purpose and usage for each dependency
