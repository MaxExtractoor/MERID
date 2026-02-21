# Self-Hosted Execution Architecture

## Overview

MERID now supports a complete self-hosted execution infrastructure that eliminates dependencies on external brokers like Alpaca for paper trading. This architecture provides:

- **Execution Simulator**: Full broker-like functionality with order matching, risk management, and P&L tracking
- **Market Data Ingestor**: Live data from crypto exchanges (Binance, Kraken) and replay capabilities
- **Venue Adapter System**: Swappable connections between simulator, external brokers, and direct exchange connectivity
- **MERID Integration**: Seamless adapter that connects MERID's trading system to self-hosted execution

## Architecture Components

### 1. Execution Simulator (`execution/simulator.py`)
- **Order Management**: Submit, cancel, and track orders with full lifecycle
- **Position Tracking**: Real-time position and P&L calculation
- **Risk Management**: Configurable limits for notional, position size, and margin
- **Order Book**: Simple limit order book with price-time priority
- **Account Management**: Multi-account support with cash and buying power tracking

### 2. Venue Adapter System (`execution/venue_adapter.py`)
- **Unified Interface**: Common API for all execution venues
- **Swappable Connections**: Easy switching between simulator, brokers, and direct exchanges
- **Venue Manager**: Orchestrate multiple venue connections simultaneously
- **Event Streaming**: Real-time order, position, and account updates

### 3. Market Data Ingestor (`execution/market_data_ingestor.py`)
- **Live Feeds**: WebSocket connections to Binance, Kraken, and other exchanges
- **Replay Support**: Historical data replay with configurable speed
- **Normalization**: Unified market data format across all sources
- **Real-time Publishing**: Immediate updates to execution simulator

### 4. Execution Service (`execution/service.py`)
- **REST API**: Complete broker-like API for order management
- **WebSocket**: Real-time market data and order updates
- **Health Monitoring**: Service health and status endpoints
- **Multi-account**: Support for multiple trading accounts

### 5. MERID Integration (`trading/merid_adapter.py`)
- **Drop-in Replacement**: Replaces external broker adapters
- **API Compatibility**: Same interface as existing paper trading engines
- **Configuration**: Easy switching between execution modes
- **Error Handling**: Robust error handling and reconnection logic

## Usage

### Self-Hosted Paper Trading

```bash
# Start MERID with self-hosted execution
python start_merid.py --execution-mode self_hosted --mode paper

# Or start execution service separately
python -m execution.service --mode sim
```

### External Broker Mode (Default)

```bash
# Use external brokers (Alpaca, etc.)
python start_merid.py --execution-mode external --mode paper
```

### Configuration Options

```bash
# Execution service URL
--execution-service-url http://127.0.0.1:8012

# Trading parameters
--symbols AAPL,MSFT
--strategies drift
--venues alpaca
--notional 1000
--session-duration 1800
```

## API Endpoints

### Execution Service (Port 8012)

#### Account Management
- `POST /accounts` - Create trading account
- `GET /accounts/{account_id}` - Get account information

#### Order Management
- `POST /orders` - Submit order
- `DELETE /orders/{order_id}` - Cancel order
- `GET /orders` - Get orders (with optional status filter)

#### Position Management
- `GET /positions` - Get current positions

#### Market Data
- `POST /market-data` - Update market data (for testing)
- `WebSocket /ws/market-data/{account_id}` - Real-time updates

#### Health
- `GET /health` - Service health status

### MERID Integration

The `MeridPaperTradingEngine` provides the same interface as external brokers:

```python
from trading.merid_adapter import get_paper_engine

engine = get_paper_engine()
await engine.start()

# Place order
order = await engine.place_order(
    symbol="BTCUSDT",
    side="buy",
    order_type="market",
    quantity=0.1
)

# Get positions
positions = await engine.get_positions()

# Get portfolio
portfolio = await engine.get_portfolio()
```

## Market Data Sources

### Supported Exchanges
- **Binance**: WebSocket and REST API for spot and futures markets
- **Kraken**: WebSocket and REST API for spot markets
- **Coinbase**: WebSocket and REST API for spot markets

### Data Types
- **Ticker Data**: Last price, bid/ask, volume
- **Order Book**: Level 2 market depth (planned)
- **Trades**: Recent trade history (planned)

### Replay Capabilities
- **CSV Files**: Historical tick/quote data in CSV format
- **Configurable Speed**: Real-time or accelerated replay
- **Multiple Symbols**: Replay multiple symbols simultaneously

## Risk Management

### Default Limits
- **Max Order Notional**: $50,000
- **Max Position per Symbol**: 1,000 units
- **Max Daily Loss**: $10,000
- **Margin Requirement**: 50%

### Risk Checks
- Pre-trade validation for all orders
- Position size limits
- Buying power validation
- Daily loss limits

## Configuration

### Environment Variables
```bash
# Execution mode (self_hosted or external)
MERID_EXECUTION_MODE=self_hosted

# Execution service URL
MERID_EXECUTION_SERVICE_URL=http://127.0.0.1:8012

# Market data sources
BINANCE_API_KEY=your_api_key
BINANCE_SECRET_KEY=your_secret_key
KRaken_API_KEY=your_api_key
```

### Settings
```python
# Risk management settings
risk_limits = {
    "max_notional_per_order": 50000.0,
    "max_position_per_symbol": 1000.0,
    "max_daily_loss": 10000.0,
    "margin_requirement": 0.5
}

# Market data settings
market_data_config = {
    "replay_speed": 1.0,  # 1.0 = real-time
    "poll_interval": 5.0,  # REST polling interval
    "websocket_timeout": 30.0
}
```

## Migration Guide

### From External Brokers
1. **Install Dependencies**: Ensure all required packages are installed
2. **Update Configuration**: Set execution mode to `self_hosted`
3. **Test Integration**: Use existing MERID paper trading scripts
4. **Validate Results**: Compare results with external broker mode

### Testing
```bash
# Test execution service
curl http://127.0.0.1:8012/health

# Test account creation
curl -X POST http://127.0.0.1:8012/accounts \
  -H "Content-Type: application/json" \
  -d '{"account_id": "test", "initial_cash": 100000}'

# Test order submission
curl -X POST http://127.0.0.1:8012/orders \
  -H "Content-Type: application/json" \
  -d '{"account_id": "test", "symbol": "BTCUSDT", "side": "buy", "order_type": "market", "quantity": 0.1}'
```

## Benefits

### Self-Hosted Mode
- **No External Dependencies**: Complete control over execution infrastructure
- **Cost Effective**: No broker fees for paper trading
- **Customizable**: Tailor risk rules and order types to specific needs
- **Privacy**: All trading data stays within your infrastructure

### Hybrid Architecture
- **Swappable Venues**: Easy switching between simulator and live brokers
- **Unified Interface**: Same MERID code works with all execution modes
- **Gradual Migration**: Start with simulator, move to live when ready
- **Risk Isolation**: Test strategies safely before deploying with real capital

## Future Enhancements

### Planned Features
- **FIX Protocol Support**: Direct exchange connectivity for institutional trading
- **Advanced Order Types**: Iceberg, TWAP, VWAP, and conditional orders
- **Portfolio Margin**: Sophisticated margin calculations for complex portfolios
- **Performance Optimization**: Low-latency execution for high-frequency trading
- **Multi-Asset Support**: Stocks, options, futures, and crypto in unified interface

### Integration Points
- **Direct Exchange APIs**: Additional crypto and traditional market exchanges
- **Data Vendors**: Professional market data feeds (Bloomberg, Reuters)
- **Risk Systems**: Integration with third-party risk management systems
- **Compliance**: Regulatory reporting and audit trail capabilities

## Troubleshooting

### Common Issues
1. **Execution Service Not Starting**: Check port availability and dependencies
2. **Market Data Connection Issues**: Verify API keys and network connectivity
3. **Order Rejection**: Check risk limits and account balance
4. **WebSocket Disconnections**: Monitor network stability and reconnection logic

### Debugging
```bash
# Check service health
curl http://127.0.0.1:8012/health

# View service logs
tail -f logs/execution_service.log

# Test market data connection
python -c "from execution.market_data_ingestor import get_market_data_ingestor; ingestor = get_market_data_ingestor(); ingestor.start()"
```

This self-hosted execution architecture provides MERID with complete control over trading infrastructure while maintaining the same interfaces and usability as external broker solutions.
