# MERID Cognitive Core - Python Backend

## Overview

Python-based cognitive engine for MERID v2.0 decision organism.

## Components

### Agents (6 Independent Observers)
- **Logic Agent**: Bayesian reasoning, formal logic
- **Intuition Agent**: Pattern recognition, regime detection
- **Adversarial Agent**: Game theory, MEV modeling, manipulation detection
- **Market Structure Agent**: Liquidity, slippage, microstructure
- **Simulation Agent**: Monte Carlo orchestration
- **Governance Agent**: Charter enforcement, SLP-1 triggers

### Core Systems
- **Bayesian Core**: Probabilistic reasoning engine
- **Monte Carlo**: Fat-tailed simulations
- **Risk Models**: Kelly criterion, tail risk (VaR/CVaR)
- **Spine Bus**: Message routing, arbitration, distillation
- **Governance**: Charter-as-code, lockdown mechanisms

### Data Pipelines
- Normalized schema (Datum with decay/confidence)
- Mock generators for testing
- Production-ready interfaces (onchain, markets, social, news)

### IPC Layer
- Flask REST API (localhost:8080)
- Request/response schemas
- Background scheduler
- WebSocket for real-time alerts

## Installation

```bash
cd cognitive_core
pip install -e .
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy cognitive_core

# Code formatting
black cognitive_core
```

## Architecture

```
Flutter UI (localhost:8080) 
    ↓
Flask IPC Server
    ↓
Spine Bus Arbitrator
    ↓
Agent Council (6 parallel agents)
    ↓
Memory Snapshot (read-only data view)
```

## Usage

See `examples/telegram_flow.py` for end-to-end example.

## Charter Compliance

All outputs pass through Distillation Gate:
- Verdict (≤5 lines)
- Confidence (0-100%)
- Key drivers
- Primary risks
- Counterfactuals
- Agent dissent
- Next human decision

No autonomous execution. Human primacy enforced.

## License

Proprietary - Part of MERID v2.0
