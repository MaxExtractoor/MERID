// MERID Perps Trading Interface

let currentAsset = 'BTC';
let currentSide = 'long';
let currentOrderType = 'market';
let currentLeverage = 1;
let chart = null;
let paperTradingMode = true; // Paper trading enabled by default
let userId = localStorage.getItem('merid_user_id') || (() => {
    const id = 'user_' + Date.now().toString(36) + '_' + crypto.randomUUID().slice(0, 8);
    localStorage.setItem('merid_user_id', id);
    return id;
})();

// WebSocket connections
let priceWs = null;
let tradeWs = null;
let agentWs = null;
let positionWs = null;

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
    initializeChart();
    initializeWebSockets();
    setupEventListeners();
    loadPositions();
    updateRiskMetrics();
});

// Initialize TradingView-style chart
function initializeChart() {
    const chartContainer = document.getElementById('trading-chart');
    
    chart = LightweightCharts.createChart(chartContainer, {
        width: chartContainer.clientWidth,
        height: chartContainer.clientHeight,
        layout: {
            background: { color: '#0a0a0f' },
            textColor: '#e0e0e0',
        },
        grid: {
            vertLines: { color: 'rgba(16, 185, 129, 0.1)' },
            horzLines: { color: 'rgba(16, 185, 129, 0.1)' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
        },
        rightPriceScale: {
            borderColor: 'rgba(16, 185, 129, 0.3)',
        },
        timeScale: {
            borderColor: 'rgba(16, 185, 129, 0.3)',
            timeVisible: true,
            secondsVisible: false,
        },
    });

    const candlestickSeries = chart.addCandlestickSeries({
        upColor: '#10b981',
        downColor: '#ff0055',
        borderDownColor: '#ff0055',
        borderUpColor: '#10b981',
        wickDownColor: '#ff0055',
        wickUpColor: '#10b981',
    });

    // Fetch real candlestick data from API
    fetchCandlestickData(currentSymbol).then(data => {
        if (data.length > 0) {
            candlestickSeries.setData(data);
        }
    });

    // Auto-resize
    window.addEventListener('resize', () => {
        chart.resize(chartContainer.clientWidth, chartContainer.clientHeight);
    });
}

// Fetch real candlestick data from API
async function fetchCandlestickData(symbol = 'BTC/USDT', timeframe = '1h', limit = 100) {
    try {
        const response = await fetch(`/api/v1/data/ohlcv?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}&limit=${limit}`);
        const result = await response.json();
        
        if (result.data && result.data.length > 0) {
            return result.data.map(candle => ({
                time: candle.time,
                open: candle.open,
                high: candle.high,
                low: candle.low,
                close: candle.close,
            }));
        }
    } catch (e) {
        console.error('Failed to fetch OHLCV data:', e);
    }
    
    // Return empty array if fetch fails - chart will show no data
    return [];
}

// Initialize WebSocket connections
function initializeWebSockets() {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsHost = window.location.host;

    // Price stream
    priceWs = new WebSocket(`${wsProtocol}//${wsHost}/ws/prices`);
    priceWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        updatePriceTicker(data);
    };

    // Trade stream
    tradeWs = new WebSocket(`${wsProtocol}//${wsHost}/ws/trades`);
    tradeWs.onmessage = (event) => {
        const trade = JSON.parse(event.data);
        addTradeToStream(trade);
    };

    // Agent stream
    agentWs = new WebSocket(`${wsProtocol}//${wsHost}/ws/agents`);
    agentWs.onmessage = (event) => {
        const decision = JSON.parse(event.data);
        addAgentDecisionToStream(decision);
        updateAgentRecommendations(decision);
    };

    // Position stream
    positionWs = new WebSocket(`${wsProtocol}//${wsHost}/ws/positions`);
    positionWs.onmessage = (event) => {
        const positions = JSON.parse(event.data);
        updatePositions(positions);
    };
}

// Update price ticker
function updatePriceTicker(data) {
    const price = data.prices[currentAsset];
    const change = data.changes_24h[currentAsset];

    document.querySelector('.ticker-price').textContent = `$${price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    
    const changeEl = document.querySelector('.ticker-change');
    changeEl.textContent = `${change > 0 ? '+' : ''}${change.toFixed(1)}%`;
    changeEl.className = `ticker-change ${change >= 0 ? 'positive' : 'negative'}`;

    // Update risk metrics
    updateRiskMetrics();
}

// Setup event listeners
function setupEventListeners() {
    // Asset selection
    document.querySelectorAll('.asset-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.asset-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentAsset = btn.dataset.asset;
            document.querySelector('.ticker-label').textContent = currentAsset;
        });
    });

    // Order type tabs
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentOrderType = btn.dataset.type;
            
            // Show/hide price inputs
            document.getElementById('limit-price-group').style.display = 
                currentOrderType === 'limit' ? 'block' : 'none';
            document.getElementById('stop-price-group').style.display = 
                currentOrderType === 'stop' ? 'block' : 'none';
        });
    });

    // Side selection
    document.querySelectorAll('.side-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.side-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentSide = btn.dataset.side;
            updateRiskMetrics();
        });
    });

    // Leverage slider
    const leverageSlider = document.getElementById('leverage');
    leverageSlider.addEventListener('input', (e) => {
        currentLeverage = parseInt(e.target.value);
        document.getElementById('leverage-display').textContent = `${currentLeverage}x`;
        updateRiskMetrics();
    });

    // Position size
    document.getElementById('position-size').addEventListener('input', updateRiskMetrics);

    // Quick amount buttons
    document.querySelectorAll('.quick-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.getElementById('position-size').value = btn.dataset.amount;
            updateRiskMetrics();
        });
    });

    // Strategy mode buttons
    document.querySelectorAll('.strategy-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.strategy-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
        });
    });

    // Panel tabs
    document.querySelectorAll('.panel-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            document.querySelectorAll('.panel-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            document.querySelectorAll('.tab-content').forEach(content => {
                content.classList.remove('active');
            });
            document.getElementById(`${tab}-tab`).classList.add('active');
        });
    });

    // Stream tabs
    document.querySelectorAll('.stream-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            const stream = btn.dataset.stream;
            document.querySelectorAll('.stream-tab').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            document.querySelectorAll('.stream-feed').forEach(feed => {
                feed.classList.remove('active');
            });
            document.getElementById(`${stream}-stream`).classList.add('active');
        });
    });
}

// Update risk metrics
function updateRiskMetrics() {
    const positionSize = parseFloat(document.getElementById('position-size').value) || 0;
    
    // Get real price from lastPrices or fetch
    const symbol = `${currentAsset}/USDT`;
    const currentPrice = window.lastPrices?.[symbol] || window.lastPrices?.[currentAsset] || 0;
    
    if (currentPrice <= 0) {
        // Fetch current price if not available
        fetch(`/api/v1/prices/current?symbol=${symbol}`)
            .then(r => r.json())
            .then(data => {
                if (data.price) {
                    window.lastPrices = window.lastPrices || {};
                    window.lastPrices[symbol] = data.price;
                    updateRiskMetrics(); // Retry with fetched price
                }
            })
            .catch(() => {});
        return;
    }
    
    // Entry price
    document.getElementById('entry-price').textContent = `$${currentPrice.toLocaleString('en-US', {minimumFractionDigits: 2})}`;
    
    // Liquidation price
    const liqPrice = currentSide === 'long' 
        ? currentPrice * (1 - 0.9 / currentLeverage)
        : currentPrice * (1 + 0.9 / currentLeverage);
    document.getElementById('liq-price').textContent = `$${liqPrice.toLocaleString('en-US', {minimumFractionDigits: 2})}`;
    
    // Slippage estimate based on position size
    const slippageBps = Math.min(10, 2 + (positionSize / 5000));
    document.getElementById('est-slippage').textContent = `${slippageBps.toFixed(1)} bps`;
    
    // Fees
    const fees = positionSize * 0.0005;
    document.getElementById('est-fees').textContent = `$${fees.toFixed(2)}`;
}

// Execute order
async function executeOrder() {
    const positionSize = parseFloat(document.getElementById('position-size').value);
    
    if (!positionSize || positionSize < 10) {
        alert('Minimum position size is $10');
        return;
    }

    if (paperTradingMode) {
        // Paper trading mode
        const orderData = {
            user_id: userId,
            asset: currentAsset,
            side: currentSide,
            size_usd: positionSize,
            order_type: currentOrderType,
            leverage: currentLeverage,
            market_type: 'perp'
        };

        try {
            const response = await fetch('/api/v1/paper/orders/place', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(orderData)
            });

            const result = await response.json();

            if (response.ok) {
                alert(`📄 PAPER TRADE EXECUTED!\nOrder ID: ${result.order_id}\nStatus: ${result.status}\nFill Price: $${result.fill_price}\n\n⚠️ This is a simulated trade`);
                loadPositions();
            } else {
                alert(`Order failed: ${result.detail || 'Unknown error'}`);
            }
        } catch (error) {
            console.error('Paper order execution error:', error);
            alert('Failed to execute paper order. Please try again.');
        }
    } else {
        // Live trading mode
        const orderData = {
            asset: currentAsset,
            side: currentSide,
            size_usd: positionSize,
            venue: 'hyperliquid'
        };

        try {
            const response = await fetch('/api/v1/trading/execute/one-click', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(orderData)
            });

            const result = await response.json();

            if (response.ok) {
                alert(`Order executed!\nOrder ID: ${result.order_id}\nStatus: ${result.status}\nFill Price: $${result.fill_price}`);
                loadPositions();
            } else {
                alert(`Order failed: ${result.detail || 'Unknown error'}`);
            }
        } catch (error) {
            console.error('Order execution error:', error);
            alert('Failed to execute order. Please try again.');
        }
    }
}

// Load positions
async function loadPositions() {
    try {
        if (paperTradingMode) {
            const response = await fetch(`/api/v1/paper/portfolio/${userId}/positions`);
            const data = await response.json();
            // Positions will be shown via WebSocket or manual refresh
        } else {
            const response = await fetch('/api/v1/trading/perps/positions');
            const data = await response.json();
        }
    } catch (error) {
        console.error('Failed to load positions:', error);
    }
}

// Toggle paper trading mode
function togglePaperTrading() {
    paperTradingMode = !paperTradingMode;
    const badge = document.getElementById('trading-mode-badge');
    const btn = document.getElementById('execute-btn');
    
    if (paperTradingMode) {
        badge.textContent = '📄 PAPER TRADING';
        badge.className = 'mode-badge paper-mode';
        btn.innerHTML = '<span class="icon-trading"></span> EXECUTE PAPER TRADE';
    } else {
        badge.textContent = '💰 LIVE TRADING';
        badge.className = 'mode-badge live-mode';
        btn.innerHTML = '<span class="icon-trading"></span> EXECUTE LIVE TRADE';
    }
}

// Update positions from WebSocket
function updatePositions(data) {
    const positionsList = document.getElementById('positions-list');
    
    if (!data.positions || data.positions.length === 0) {
        positionsList.innerHTML = '<div class="empty-state">No open positions</div>';
        return;
    }

    // Update summary
    document.getElementById('total-pnl').textContent = 
        `${data.total_pnl >= 0 ? '+' : ''}$${data.total_pnl.toFixed(2)}`;
    document.getElementById('total-pnl').className = 
        `summary-value ${data.total_pnl >= 0 ? 'positive' : 'negative'}`;
    document.getElementById('open-positions').textContent = data.total_positions;

    // Render positions
    positionsList.innerHTML = data.positions.map(pos => `
        <div class="position-card">
            <div class="position-header">
                <span class="position-asset">${pos.asset}</span>
                <span class="position-side ${pos.side}">${pos.side.toUpperCase()}</span>
            </div>
            <div class="position-details">
                <div class="position-detail">
                    <span class="detail-label">Size:</span>
                    <span class="detail-value">$${pos.size_usd.toLocaleString()}</span>
                </div>
                <div class="position-detail">
                    <span class="detail-label">Entry:</span>
                    <span class="detail-value">$${pos.entry_price.toFixed(2)}</span>
                </div>
                <div class="position-detail">
                    <span class="detail-label">Current:</span>
                    <span class="detail-value">$${pos.current_price.toFixed(2)}</span>
                </div>
                <div class="position-detail">
                    <span class="detail-label">PnL:</span>
                    <span class="detail-value ${pos.pnl >= 0 ? 'positive' : 'negative'}">
                        ${pos.pnl >= 0 ? '+' : ''}$${pos.pnl.toFixed(2)} (${pos.pnl_pct.toFixed(2)}%)
                    </span>
                </div>
                <div class="position-detail">
                    <span class="detail-label">Leverage:</span>
                    <span class="detail-value">${pos.leverage}x</span>
                </div>
                <div class="position-detail">
                    <span class="detail-label">Liq Price:</span>
                    <span class="detail-value text-danger">$${pos.liquidation_price.toFixed(2)}</span>
                </div>
            </div>
        </div>
    `).join('');
}

// Add trade to stream
function addTradeToStream(trade) {
    const stream = document.getElementById('trades-stream');
    const time = new Date(trade.timestamp * 1000).toLocaleTimeString();
    
    const item = document.createElement('div');
    item.className = 'stream-item';
    item.innerHTML = `
        <div>
            <strong>${trade.asset}</strong> ${trade.side.toUpperCase()} 
            $${trade.size_usd.toLocaleString()} @ $${trade.price.toFixed(2)}
            <span style="color: var(--merid-text-muted); margin-left: 1rem;">
                ${trade.execution_time_ms.toFixed(1)}ms | ${trade.slippage_bps.toFixed(1)} bps
            </span>
        </div>
        <span class="stream-time">${time}</span>
    `;
    
    stream.insertBefore(item, stream.firstChild);
    
    // Keep only last 20 items
    while (stream.children.length > 20) {
        stream.removeChild(stream.lastChild);
    }
}

// Add agent decision to stream
function addAgentDecisionToStream(decision) {
    const stream = document.getElementById('agents-stream');
    const time = new Date(decision.timestamp * 1000).toLocaleTimeString();
    
    const item = document.createElement('div');
    item.className = 'stream-item';
    item.innerHTML = `
        <div>
            <strong>${decision.agent_id}</strong>: ${decision.decision_type}
            <div style="font-size: 0.75rem; color: var(--merid-text-muted); margin-top: 0.25rem;">
                ${decision.reasoning[0]}
            </div>
        </div>
        <span class="stream-time">${time}</span>
    `;
    
    stream.insertBefore(item, stream.firstChild);
    
    while (stream.children.length > 20) {
        stream.removeChild(stream.lastChild);
    }
}

// Update agent recommendations
function updateAgentRecommendations(decision) {
    const recList = document.getElementById('rec-list');
    
    if (decision.decision === 'execute' && decision.data) {
        const item = document.createElement('div');
        item.className = 'rec-item';
        item.innerHTML = `
            <span class="rec-agent">${decision.agent_id}</span>
            <span class="rec-action">
                ${decision.data.asset}: ${decision.data.spread_bps.toFixed(1)} bps spread
            </span>
        `;
        
        recList.insertBefore(item, recList.firstChild);
        
        while (recList.children.length > 5) {
            recList.removeChild(recList.lastChild);
        }
    }
}

// Cleanup on unload
window.addEventListener('beforeunload', () => {
    if (priceWs) priceWs.close();
    if (tradeWs) tradeWs.close();
    if (agentWs) agentWs.close();
    if (positionWs) positionWs.close();
});
