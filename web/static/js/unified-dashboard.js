// MERID Unified Dashboard JavaScript

// Global state
let mainPriceChart = null;
let portfolioChart = null;
let agentActivityChart = null;
let priceHistory = { 'BTC/USDT': [], 'ETH/USDT': [], 'SOL/USDT': [], 'AVAX/USDT': [] };
let selectedSymbol = 'BTC/USDT';
let allSignals = [];
let lastPrices = {};

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    initCharts();
    initNavigation();
    initChartControls();
    startIntelligence();
    
    // Initial data fetch
    refreshAll();
    
    // Set up polling intervals
    setInterval(fetchRealtimeData, 2000);
    setInterval(fetchIntelligence, 15000);
    setInterval(fetchAgents, 10000);
    setInterval(updateTime, 1000);
});

// Navigation
function initNavigation() {
    document.querySelectorAll('.sidebar-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const section = link.dataset.section;
            
            document.querySelectorAll('.sidebar-link').forEach(l => l.classList.remove('active'));
            link.classList.add('active');
            
            document.querySelectorAll('.content-section').forEach(s => s.classList.remove('active'));
            document.getElementById(section).classList.add('active');
            
            // Trigger section-specific refresh
            refreshSection(section);
        });
    });
}

// Refresh section data when navigating
function refreshSection(section) {
    switch(section) {
        case 'predictions':
            refreshPredictions();
            break;
        case 'agents':
            fetchAgents();
            refreshMesh();
            break;
        case 'consensus':
            refreshConsensus();
            break;
        case 'simulation':
            refreshSimulation();
            break;
        case 'audit':
            refreshAudit();
            break;
        case 'execution':
            refreshExecution();
            break;
        case 'analytics':
            refreshAnalytics();
            break;
        case 'portfolio':
            refreshPortfolio();
            break;
        case 'backtest':
            refreshBacktest();
            break;
        case 'alerts':
            refreshAlerts();
            break;
        case 'arbitrage':
            refreshArbitrage();
            break;
        case 'dashboard':
            fetchPrices();
            fetchIntelligence();
            break;
    }
}

// Chart Controls
function initChartControls() {
    document.querySelectorAll('.chart-controls button').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.chart-controls button').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
        });
    });
}

// Symbol Selection
function selectSymbol(symbol) {
    selectedSymbol = symbol;
    
    document.querySelectorAll('.price-ticker').forEach(t => {
        t.classList.toggle('active', t.dataset.symbol === symbol);
    });
    
    document.getElementById('main-chart-symbol').textContent = symbol;
    updateMainChart();
}

// Initialize Charts
function initCharts() {
    // Main Price Chart
    const mainCtx = document.getElementById('main-price-chart');
    if (mainCtx) {
        mainPriceChart = new Chart(mainCtx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'Price',
                    data: [],
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    fill: true,
                    tension: 0.4,
                    pointRadius: 0,
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { intersect: false, mode: 'index' },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: 'rgba(0,0,0,0.8)',
                        titleColor: '#fff',
                        bodyColor: '#10b981',
                        padding: 12,
                        displayColors: false,
                        callbacks: {
                            label: (ctx) => `$${ctx.parsed.y.toLocaleString(undefined, {minimumFractionDigits: 2})}`
                        }
                    }
                },
                scales: {
                    x: { display: false },
                    y: {
                        grid: { color: 'rgba(255,255,255,0.05)', drawBorder: false },
                        ticks: { color: '#666', callback: (v) => '$' + v.toLocaleString() }
                    }
                }
            }
        });
    }

    // Portfolio Chart
    const portfolioCtx = document.getElementById('portfolio-chart');
    if (portfolioCtx) {
        portfolioChart = new Chart(portfolioCtx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'Portfolio',
                    data: [],
                    borderColor: '#00d4aa',
                    backgroundColor: 'rgba(0, 212, 170, 0.1)',
                    fill: true,
                    tension: 0.4,
                    pointRadius: 0,
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { display: false },
                    y: {
                        grid: { color: 'rgba(255,255,255,0.05)', drawBorder: false },
                        ticks: { color: '#666', callback: (v) => '$' + (v/1000) + 'k' }
                    }
                }
            }
        });
        
        // Initialize with sample data
        const now = Date.now();
        const labels = [];
        const data = [];
        for (let i = 30; i >= 0; i--) {
            labels.push(new Date(now - i * 60000).toLocaleTimeString());
            data.push(100000 + Math.random() * 1000 - 500);
        }
        portfolioChart.data.labels = labels;
        portfolioChart.data.datasets[0].data = data;
        portfolioChart.update('none');
    }

    // Agent Activity Chart
    const agentCtx = document.getElementById('agent-activity-chart');
    if (agentCtx) {
        agentActivityChart = new Chart(agentCtx, {
            type: 'bar',
            data: {
                labels: ['Strategy', 'Risk', 'Execution', 'Treasury', 'Intel', 'Governance'],
                datasets: [{
                    label: 'Actions',
                    data: [12, 8, 15, 5, 20, 3],
                    backgroundColor: [
                        'rgba(139, 92, 246, 0.6)',
                        'rgba(239, 68, 68, 0.6)',
                        'rgba(14, 165, 233, 0.6)',
                        'rgba(245, 158, 11, 0.6)',
                        'rgba(16, 185, 129, 0.6)',
                        'rgba(99, 102, 241, 0.6)'
                    ],
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: '#666', font: { size: 10 } }
                    },
                    y: {
                        grid: { color: 'rgba(255,255,255,0.05)', drawBorder: false },
                        ticks: { color: '#666' }
                    }
                }
            }
        });
    }
}

// Update main chart with selected symbol
function updateMainChart() {
    if (!mainPriceChart) return;
    
    const history = priceHistory[selectedSymbol] || [];
    const labels = history.map((_, i) => i);
    const data = history.map(p => p.price);
    
    mainPriceChart.data.labels = labels;
    mainPriceChart.data.datasets[0].data = data;
    
    // Update color based on trend
    const isUp = data.length > 1 && data[data.length - 1] >= data[0];
    mainPriceChart.data.datasets[0].borderColor = isUp ? '#10b981' : '#ef4444';
    mainPriceChart.data.datasets[0].backgroundColor = isUp ? 'rgba(16, 185, 129, 0.1)' : 'rgba(239, 68, 68, 0.1)';
    
    mainPriceChart.update('none');
}

// Start intelligence layer
async function startIntelligence() {
    try {
        await fetch('/api/v1/institutional/intelligence/start', { method: 'POST' });
    } catch (e) {
        console.error('Failed to start intelligence:', e);
    }
}

// Refresh all data
function refreshAll() {
    fetchRealtimeData();
    fetchIntelligence();
    fetchAgents();
    updateTime();
}

// Fetch prices from live price feed
async function fetchPrices() {
    try {
        const response = await fetch('/api/v1/institutional/realtime/stream');
        const data = await response.json();
        
        if (data.prices) updatePrices(data.prices);
        
    } catch (error) {
        console.error('Failed to fetch prices:', error);
    }
}

// Fetch real-time data
async function fetchRealtimeData() {
    try {
        const response = await fetch('/api/v1/institutional/realtime/stream');
        const data = await response.json();
        
        if (data.prices) updatePrices(data.prices);
        if (data.divergence) updateDivergence(data.divergence);
        if (data.guardian) updateGuardian(data.guardian);
        
    } catch (error) {
        console.error('Failed to fetch realtime data:', error);
    }
}

// Update prices display
function updatePrices(prices) {
    const symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'AVAX/USDT'];
    const ids = ['btc', 'eth', 'sol', 'avax'];
    
    symbols.forEach((symbol, i) => {
        const priceData = prices[symbol];
        if (priceData) {
            const priceEl = document.getElementById(`price-${ids[i]}`);
            const changeEl = document.getElementById(`change-${ids[i]}`);
            
            if (priceEl) {
                const price = priceData.price;
                const formatted = price >= 1000 
                    ? `$${price.toLocaleString(undefined, {maximumFractionDigits: 0})}`
                    : `$${price.toFixed(2)}`;
                priceEl.textContent = formatted;
                
                // Flash effect on price change
                const oldPrice = lastPrices[symbol];
                if (oldPrice && oldPrice !== price) {
                    priceEl.classList.remove('up', 'down');
                    priceEl.classList.add(price > oldPrice ? 'up' : 'down');
                }
                lastPrices[symbol] = price;
            }
            
            if (changeEl && priceData.change_24h !== undefined) {
                const change = priceData.change_24h;
                changeEl.textContent = `${change >= 0 ? '+' : ''}${change.toFixed(1)}%`;
                changeEl.className = `change ${change >= 0 ? 'positive' : 'negative'}`;
            }
            
            // Store price history
            if (!priceHistory[symbol]) priceHistory[symbol] = [];
            priceHistory[symbol].push({ price: priceData.price, time: Date.now() });
            if (priceHistory[symbol].length > 100) priceHistory[symbol].shift();
        }
    });
    
    // Update main chart
    if (prices[selectedSymbol]) {
        const p = prices[selectedSymbol];
        document.getElementById('main-chart-price').textContent = 
            p.price >= 1000 ? `$${p.price.toLocaleString(undefined, {maximumFractionDigits: 0})}` : `$${p.price.toFixed(2)}`;
        
        const changeEl = document.getElementById('main-chart-change');
        if (p.change_24h !== undefined) {
            changeEl.textContent = `${p.change_24h >= 0 ? '+' : ''}${p.change_24h.toFixed(1)}%`;
            changeEl.className = `chart-change ${p.change_24h >= 0 ? 'positive' : 'negative'}`;
        }
    }
    
    updateMainChart();
}

// Update divergence display
function updateDivergence(divergence) {
    const scoreEl = document.getElementById('div-score');
    const statusEl = document.getElementById('div-status');
    const statDivEl = document.getElementById('stat-divergence');
    const pctEl = document.getElementById('divergence-pct');
    
    const pct = divergence.percentage || 0;
    const formatted = `${pct.toFixed(1)}%`;
    
    if (scoreEl) {
        scoreEl.textContent = formatted;
        scoreEl.className = 'divergence-score ' + (pct < 5 ? 'nominal' : pct < 15 ? 'alert' : 'critical');
    }
    
    if (statusEl) {
        statusEl.textContent = pct < 5 ? 'NOMINAL' : pct < 15 ? 'ELEVATED' : 'CRITICAL';
    }
    
    if (statDivEl) statDivEl.textContent = formatted;
    if (pctEl) pctEl.textContent = formatted;
}

// Update guardian display
function updateGuardian(guardian) {
    const stateEl = document.getElementById('guardian-state');
    const threatEl = document.getElementById('guardian-threat');
    
    if (stateEl) stateEl.textContent = guardian.state || 'IDLE';
    if (threatEl) {
        threatEl.textContent = guardian.threat_level || 'NONE';
        threatEl.className = 'value threat-' + (guardian.threat_level || 'none').toLowerCase();
    }
}

// Fetch intelligence data
async function fetchIntelligence() {
    try {
        const [signalsRes, sentimentRes, alertsRes] = await Promise.all([
            fetch('/api/v1/institutional/intelligence/signals'),
            fetch('/api/v1/institutional/intelligence/sentiment'),
            fetch('/api/v1/institutional/intelligence/alerts')
        ]);
        
        const signals = await signalsRes.json();
        const sentiment = await sentimentRes.json();
        const alerts = await alertsRes.json();
        
        allSignals = signals.signals || [];
        
        // Update signal count
        document.getElementById('stat-signals').textContent = allSignals.length;
        
        // Update sentiment
        updateSentiment(sentiment);
        
        // Update feeds
        renderIntelFeed(document.getElementById('intel-feed'), allSignals.slice(0, 10));
        renderIntelFeed(document.getElementById('full-intel-feed'), allSignals);
        
        // Update alerts
        renderAlerts(alerts.alerts || []);
        
    } catch (error) {
        console.error('Failed to fetch intelligence:', error);
    }
}

// Update sentiment display
function updateSentiment(sentiment) {
    const sentimentEl = document.getElementById('market-sentiment');
    const scoreEl = document.getElementById('sentiment-score');
    
    if (sentimentEl) {
        const label = sentiment.label || 'NEUTRAL';
        sentimentEl.textContent = label.replace('_', ' ');
        sentimentEl.className = 'sentiment-value ' + label.toLowerCase();
    }
    
    if (scoreEl) {
        scoreEl.textContent = `Score: ${(sentiment.score || 0).toFixed(2)}`;
    }
}

// Render intelligence feed
function renderIntelFeed(container, signals) {
    if (!container) return;
    
    if (!signals || signals.length === 0) {
        container.innerHTML = '<div class="empty-state">No signals yet</div>';
        return;
    }
    
    container.innerHTML = signals.map(signal => {
        const sentiment = (signal.sentiment || 'neutral').toLowerCase();
        const strength = signal.strength || 'moderate';
        const strengthIcon = {
            'weak': '○',
            'moderate': '◐',
            'strong': '●',
            'critical': '◉'
        }[strength.toLowerCase()] || '○';
        
        return `
            <div class="intel-signal ${sentiment}">
                <div class="strength-badge">${strengthIcon}</div>
                <div class="signal-content">
                    <div class="signal-headline">${escapeHtml(signal.headline || signal.message || 'Signal')}</div>
                    <div class="signal-meta">
                        <span class="signal-type">${signal.signal_type || signal.source || 'unknown'}</span>
                        ${signal.symbols ? `<span class="signal-symbols">${signal.symbols.join(', ')}</span>` : ''}
                        <span>${formatTime(signal.timestamp)}</span>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

// Render alerts
function renderAlerts(alerts) {
    const container = document.getElementById('alerts-list');
    const countEl = document.getElementById('alerts-count');
    
    if (countEl) countEl.textContent = alerts.length;
    
    if (!container) return;
    
    if (!alerts || alerts.length === 0) {
        container.innerHTML = '<div class="empty-state">No active alerts</div>';
        return;
    }
    
    container.innerHTML = alerts.map(alert => `
        <div class="alert-item">
            <span class="alert-icon">⚠</span>
            <span class="alert-message">${escapeHtml(alert.message || alert.headline)}</span>
            <span class="alert-time">${formatTime(alert.timestamp)}</span>
        </div>
    `).join('');
}

// Filter signals
function filterSignals() {
    const filter = document.getElementById('signal-filter').value;
    const filtered = filter === 'all' 
        ? allSignals 
        : allSignals.filter(s => {
            const type = (s.signal_type || s.type || '').toLowerCase();
            return type === filter || type.includes(filter);
        });
    
    renderIntelFeed(document.getElementById('full-intel-feed'), filtered);
}

// Fetch agents
async function fetchAgents() {
    try {
        const response = await fetch('/api/v1/institutional/mesh/status');
        const data = await response.json();
        
        const agents = data.agents || [];
        
        // Update counts
        const statAgents = document.getElementById('stat-agents');
        if (statAgents) statAgents.textContent = agents.length;
        
        const totalAgents = document.getElementById('total-agents');
        if (totalAgents) totalAgents.textContent = agents.length;
        
        const runningAgents = document.getElementById('running-agents');
        if (runningAgents) runningAgents.textContent = agents.filter(a => a.running).length;
        
        // Render grid
        renderAgentsGrid(agents);
        
    } catch (error) {
        console.error('Failed to fetch agents:', error);
    }
}

// Render agents grid
function renderAgentsGrid(agents) {
    const container = document.getElementById('agents-grid');
    if (!container) return;
    
    if (!agents || agents.length === 0) {
        container.innerHTML = '<div class="empty-state">No agents registered</div>';
        return;
    }
    
    const agentIcons = {
        'market-analyst': '📊',
        'news-analyst': '📰',
        'risk-agent': '🛡️',
        'skeptic-agent': '🤔',
        'synthesizer-agent': '🔗',
        'strategy-agent': '♟️',
        'archivist-agent': '📚',
        'meta-audit-agent': '📋'
    };
    
    container.innerHTML = agents.map(agent => {
        const status = agent.running ? 'running' : 'stopped';
        const agentId = agent.agent_id || '';
        const iconKey = Object.keys(agentIcons).find(k => agentId.includes(k)) || '';
        const icon = agentIcons[iconKey] || '🤖';
        const name = agentId.replace(/-\d+$/, '').replace(/-/g, ' ');
        
        return `
            <div class="agent-card ${status}">
                <div class="agent-info">
                    <div class="agent-avatar">${icon}</div>
                    <div>
                        <div class="agent-name">${name}</div>
                        <div class="agent-role">${agent.model || 'Agent'}</div>
                    </div>
                </div>
                <span class="agent-status ${status}">${status.toUpperCase()}</span>
            </div>
        `;
    }).join('');
}

// Update time display
function updateTime() {
    const el = document.getElementById('utc-time');
    if (el) {
        el.textContent = new Date().toISOString().slice(11, 19);
    }
}

// Lockdown functions
function toggleLockdown() {
    document.getElementById('lockdown-modal').classList.add('active');
}

function closeLockdownModal() {
    document.getElementById('lockdown-modal').classList.remove('active');
}

async function confirmLockdown() {
    const level = document.querySelector('input[name="lockdown-level"]:checked')?.value || 'full';
    
    try {
        await fetch('/api/v1/institutional/lockdown', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ level })
        });
        closeLockdownModal();
        alert('System lockdown initiated');
    } catch (e) {
        alert('Lockdown failed: ' + e.message);
    }
}

// Shadow functions
async function triggerReplay() {
    try {
        await fetch('/api/v1/institutional/shadow/replay', { method: 'POST' });
        alert('Shadow replay triggered');
    } catch (e) {
        alert('Replay failed: ' + e.message);
    }
}

async function runStressTest() {
    try {
        await fetch('/api/v1/institutional/shadow/stress', { method: 'POST' });
        alert('Stress test initiated');
    } catch (e) {
        alert('Stress test failed: ' + e.message);
    }
}

// ============================================
// PREDICTION MARKETS
// ============================================

async function startPredictions() {
    try {
        await fetch('/api/v1/institutional/predictions/start', { method: 'POST' });
        refreshPredictions();
    } catch (e) {
        console.error('Failed to start predictions:', e);
    }
}

async function refreshPredictions() {
    await Promise.all([
        fetchPredictionMarkets(),
        fetchDriftSignals(),
        fetchArbitrageOpps(),
        fetchUrgentMarkets()
    ]);
}

async function fetchPredictionMarkets() {
    try {
        const category = document.getElementById('market-category')?.value || 'all';
        const url = category === 'all' 
            ? '/api/v1/institutional/predictions/markets'
            : `/api/v1/institutional/predictions/markets?category=${category}`;
        
        const response = await fetch(url);
        const data = await response.json();
        
        document.getElementById('pred-markets').textContent = data.count || 0;
        renderMarketsFeed(data.markets || []);
    } catch (e) {
        console.error('Failed to fetch prediction markets:', e);
    }
}

async function fetchDriftSignals() {
    try {
        const response = await fetch('/api/v1/institutional/predictions/drift');
        const data = await response.json();
        
        document.getElementById('pred-drift').textContent = data.count || 0;
        renderDriftFeed(data.signals || []);
    } catch (e) {
        console.error('Failed to fetch drift signals:', e);
    }
}

async function fetchArbitrageOpps() {
    try {
        const response = await fetch('/api/v1/institutional/predictions/arbitrage');
        const data = await response.json();
        
        document.getElementById('pred-arb').textContent = data.count || 0;
        renderArbFeed(data.opportunities || []);
    } catch (e) {
        console.error('Failed to fetch arbitrage:', e);
    }
}

async function fetchUrgentMarkets() {
    try {
        const response = await fetch('/api/v1/institutional/predictions/urgent');
        const data = await response.json();
        
        document.getElementById('pred-urgent').textContent = data.count || 0;
        renderDecayFeed(data.markets || []);
    } catch (e) {
        console.error('Failed to fetch urgent markets:', e);
    }
}

function renderMarketsFeed(markets) {
    const container = document.getElementById('markets-feed');
    if (!container) return;
    
    if (!markets || markets.length === 0) {
        container.innerHTML = '<div class="empty-state">No markets loaded</div>';
        return;
    }
    
    container.innerHTML = markets.slice(0, 20).map(m => `
        <div class="intel-signal neutral">
            <div class="strength-badge">${(m.implied_probability * 100).toFixed(0)}%</div>
            <div class="signal-content">
                <div class="signal-headline">${escapeHtml(m.question.slice(0, 80))}${m.question.length > 80 ? '...' : ''}</div>
                <div class="signal-meta">
                    <span class="signal-type">${m.platform}</span>
                    <span class="signal-symbols">${m.category}</span>
                    <span>Vol: $${formatNumber(m.volume_24h)}</span>
                    ${m.days_to_resolution ? `<span>${m.days_to_resolution.toFixed(1)}d left</span>` : ''}
                </div>
            </div>
        </div>
    `).join('');
}

function renderDriftFeed(signals) {
    const container = document.getElementById('drift-feed');
    if (!container) return;
    
    if (!signals || signals.length === 0) {
        container.innerHTML = '<div class="empty-state">No drift signals</div>';
        return;
    }
    
    container.innerHTML = signals.map(s => {
        const isUp = s.drift_direction === 'up';
        return `
            <div class="intel-signal ${isUp ? 'bullish' : 'bearish'}">
                <div class="strength-badge">${isUp ? '↑' : '↓'}</div>
                <div class="signal-content">
                    <div class="signal-headline">${escapeHtml(s.question.slice(0, 60))}...</div>
                    <div class="signal-meta">
                        <span class="signal-type">${s.platform}</span>
                        <span style="color: ${isUp ? '#10b981' : '#ef4444'}; font-weight: 600;">
                            ${s.drift_pct >= 0 ? '+' : ''}${s.drift_pct.toFixed(1)}%
                        </span>
                        <span>${(s.old_probability * 100).toFixed(0)}% → ${(s.new_probability * 100).toFixed(0)}%</span>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function renderArbFeed(opportunities) {
    const container = document.getElementById('arb-feed');
    if (!container) return;
    
    if (!opportunities || opportunities.length === 0) {
        container.innerHTML = '<div class="empty-state">No arbitrage found</div>';
        return;
    }
    
    container.innerHTML = opportunities.map(o => `
        <div style="background: rgba(16,185,129,0.1); border: 1px solid rgba(16,185,129,0.3); border-radius: 8px; padding: 12px; margin-bottom: 8px;">
            <div style="font-size: 12px; color: #fff; margin-bottom: 8px;">${escapeHtml(o.question.slice(0, 50))}...</div>
            <div style="display: flex; justify-content: space-between; font-size: 11px;">
                <span>${o.platform_a}: ${(o.prob_a * 100).toFixed(0)}%</span>
                <span style="color: #10b981; font-weight: 700;">${o.spread_pct.toFixed(1)}% spread</span>
                <span>${o.platform_b}: ${(o.prob_b * 100).toFixed(0)}%</span>
            </div>
            <div style="font-size: 10px; color: #666; margin-top: 4px;">
                Edge: ${(o.potential_edge * 100).toFixed(2)}% | Liq: $${formatNumber(o.liquidity_constraint)}
            </div>
        </div>
    `).join('');
}

function renderDecayFeed(markets) {
    const container = document.getElementById('decay-feed');
    if (!container) return;
    
    if (!markets || markets.length === 0) {
        container.innerHTML = '<div class="empty-state">No urgent markets</div>';
        return;
    }
    
    container.innerHTML = markets.map(item => {
        const m = item.market;
        const d = item.decay;
        const urgencyColor = {
            'critical': '#ef4444',
            'high': '#f59e0b',
            'medium': '#eab308',
            'low': '#10b981'
        }[d.exit_urgency] || '#666';
        
        return `
            <div style="background: rgba(239,68,68,0.1); border-left: 3px solid ${urgencyColor}; padding: 10px; margin-bottom: 8px; border-radius: 0 6px 6px 0;">
                <div style="font-size: 12px; color: #fff; margin-bottom: 4px;">${escapeHtml(m.question.slice(0, 50))}...</div>
                <div style="display: flex; gap: 12px; font-size: 10px; color: #888;">
                    <span style="color: ${urgencyColor}; font-weight: 600;">${d.exit_urgency.toUpperCase()}</span>
                    <span>${d.days_remaining.toFixed(1)} days</span>
                    <span>Decay: ${(d.decay_factor * 100).toFixed(0)}%</span>
                </div>
            </div>
        `;
    }).join('');
}

function filterMarkets() {
    fetchPredictionMarkets();
}

function formatNumber(num) {
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return num.toFixed(0);
}

// ============================================
// CONSENSUS ENGINE
// ============================================

async function startConsensus() {
    try {
        await fetch('/api/v1/institutional/consensus/start', { method: 'POST' });
        refreshConsensus();
    } catch (e) {
        console.error('Failed to start consensus:', e);
    }
}

async function refreshConsensus() {
    await Promise.all([
        fetchConsensusStatus(),
        fetchPendingVotes()
    ]);
}

async function fetchConsensusStatus() {
    try {
        const response = await fetch('/api/v1/institutional/consensus/status');
        const data = await response.json();
        
        document.getElementById('consensus-status').textContent = data.running ? 'RUNNING' : 'IDLE';
        document.getElementById('consensus-votes').textContent = data.pending_votes || 0;
        document.getElementById('consensus-quorum').textContent = `${(data.quorum_threshold * 100).toFixed(0)}%`;
        document.getElementById('consensus-interval').textContent = `${data.consensus_interval}s`;
        
        // Render trust scores
        renderTrustScores(data.trust_scores || {});
    } catch (e) {
        console.error('Failed to fetch consensus status:', e);
    }
}

async function fetchPendingVotes() {
    try {
        const response = await fetch('/api/v1/institutional/consensus/votes');
        const data = await response.json();
        
        renderVotesFeed(data.votes || []);
    } catch (e) {
        console.error('Failed to fetch votes:', e);
    }
}

function renderVotesFeed(votes) {
    const container = document.getElementById('votes-feed');
    if (!container) return;
    
    if (!votes || votes.length === 0) {
        container.innerHTML = '<div class="empty-state">No pending votes</div>';
        return;
    }
    
    container.innerHTML = votes.map(v => {
        const signalColor = v.signal === 'bullish' ? '#10b981' : v.signal === 'bearish' ? '#ef4444' : '#6366f1';
        return `
            <div class="intel-signal" style="border-left-color: ${signalColor};">
                <div class="strength-badge">${(v.confidence * 100).toFixed(0)}%</div>
                <div class="signal-content">
                    <div class="signal-headline">${escapeHtml(v.agent_id)}</div>
                    <div class="signal-meta">
                        <span class="signal-type">${v.proposal}</span>
                        <span style="color: ${signalColor}; font-weight: 600;">${v.signal.toUpperCase()}</span>
                        <span>Weight: ${v.weight.toFixed(2)}</span>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function renderTrustScores(scores) {
    const container = document.getElementById('trust-scores');
    if (!container) return;
    
    const entries = Object.entries(scores);
    if (entries.length === 0) {
        container.innerHTML = '<div class="empty-state">No trust data</div>';
        return;
    }
    
    container.innerHTML = entries.map(([agent, score]) => `
        <div class="trust-score-row">
            <span class="trust-agent">${escapeHtml(agent)}</span>
            <span class="trust-value ${score >= 0.8 ? 'high' : score >= 0.5 ? 'medium' : 'low'}">${(score * 100).toFixed(0)}%</span>
        </div>
    `).join('');
}

// ============================================
// SIMULATION MINING
// ============================================

async function startSimulation() {
    try {
        await fetch('/api/v1/institutional/simulation/start', { method: 'POST' });
        refreshSimulation();
    } catch (e) {
        console.error('Failed to start simulation:', e);
    }
}

async function refreshSimulation() {
    await Promise.all([
        fetchSimulationStatus(),
        fetchSimulationChain(),
        fetchSimulationStrategies()
    ]);
}

async function fetchSimulationStatus() {
    try {
        const response = await fetch('/api/v1/institutional/simulation/status');
        const data = await response.json();
        
        document.getElementById('sim-status').textContent = data.running ? 'MINING' : 'IDLE';
        document.getElementById('sim-block').textContent = data.current_block || 0;
        document.getElementById('sim-interval').textContent = `${data.block_interval}s`;
        document.getElementById('sim-pending').textContent = data.pending_decisions || 0;
    } catch (e) {
        console.error('Failed to fetch simulation status:', e);
    }
}

async function fetchSimulationChain() {
    try {
        const response = await fetch('/api/v1/institutional/simulation/chain?limit=10');
        const data = await response.json();
        
        renderBlocksFeed(data.blocks || []);
    } catch (e) {
        console.error('Failed to fetch chain:', e);
    }
}

async function fetchSimulationStrategies() {
    try {
        const response = await fetch('/api/v1/institutional/simulation/strategies');
        const data = await response.json();
        
        renderStrategiesFeed(data.strategies || []);
    } catch (e) {
        console.error('Failed to fetch strategies:', e);
    }
}

function renderBlocksFeed(blocks) {
    const container = document.getElementById('blocks-feed');
    if (!container) return;
    
    if (!blocks || blocks.length === 0) {
        container.innerHTML = '<div class="empty-state">No blocks mined yet</div>';
        return;
    }
    
    container.innerHTML = blocks.map(b => `
        <div class="block-card">
            <div class="block-header">
                <span class="block-number">#${b.block}</span>
                <span class="block-hash">${b.block_hash}</span>
            </div>
            <div class="block-metrics">
                <div class="block-metric">
                    <span class="metric-label">Work</span>
                    <span class="metric-value">${b.useful_work.toFixed(1)}</span>
                </div>
                <div class="block-metric">
                    <span class="metric-label">Reward</span>
                    <span class="metric-value positive">${b.reward.toFixed(2)}</span>
                </div>
                <div class="block-metric">
                    <span class="metric-label">Winner</span>
                    <span class="metric-value">${b.winning_strategy.replace('_strategy', '')}</span>
                </div>
            </div>
        </div>
    `).join('');
}

function renderStrategiesFeed(strategies) {
    const container = document.getElementById('strategies-feed');
    if (!container) return;
    
    if (!strategies || strategies.length === 0) {
        container.innerHTML = '<div class="empty-state">No strategies tracked</div>';
        return;
    }
    
    container.innerHTML = strategies.map((s, i) => `
        <div class="strategy-row">
            <span class="strategy-rank">${i + 1}</span>
            <span class="strategy-name">${escapeHtml(s.name.replace('_strategy', ''))}</span>
            <span class="strategy-stats">
                <span class="stat">${s.decisions} decisions</span>
                <span class="stat">${s.avg_confidence.toFixed(1)}% avg</span>
            </span>
        </div>
    `).join('');
}

// ============================================
// AUDIT TRAIL
// ============================================

async function refreshAudit() {
    await Promise.all([
        fetchAuditStatus(),
        fetchAuditEntries()
    ]);
}

async function fetchAuditStatus() {
    try {
        const response = await fetch('/api/v1/institutional/audit/status');
        const data = await response.json();
        
        document.getElementById('audit-status').textContent = data.running ? 'RECORDING' : 'IDLE';
        document.getElementById('audit-entries').textContent = data.total_entries || 0;
        document.getElementById('audit-sequence').textContent = data.sequence || 0;
        document.getElementById('audit-hash').textContent = data.last_hash || 'genesis';
        document.getElementById('audit-storage').textContent = data.storage_path || 'data/audit';
    } catch (e) {
        console.error('Failed to fetch audit status:', e);
    }
}

async function fetchAuditEntries() {
    try {
        const response = await fetch('/api/v1/institutional/audit/recent?limit=20');
        const data = await response.json();
        
        renderAuditFeed(data.entries || []);
    } catch (e) {
        console.error('Failed to fetch audit entries:', e);
    }
}

async function verifyAuditChain() {
    try {
        const response = await fetch('/api/v1/institutional/audit/verify');
        const data = await response.json();
        
        const el = document.getElementById('audit-verified');
        if (data.valid) {
            el.textContent = 'VALID';
            el.className = 'stat-value positive';
        } else {
            el.textContent = 'INVALID';
            el.className = 'stat-value negative';
        }
        
        alert(data.message + ` (${data.entries_verified} entries)`);
    } catch (e) {
        console.error('Failed to verify audit chain:', e);
    }
}

function renderAuditFeed(entries) {
    const container = document.getElementById('audit-feed');
    if (!container) return;
    
    if (!entries || entries.length === 0) {
        container.innerHTML = '<div class="empty-state">No audit entries</div>';
        return;
    }
    
    container.innerHTML = entries.map(e => {
        const typeColor = {
            'consensus_decision': '#10b981',
            'block_mined': '#00d4aa',
            'price_signal': '#6366f1',
            'news_impact': '#f59e0b'
        }[e.event_type] || '#888';
        
        return `
            <div class="audit-entry">
                <div class="audit-header">
                    <span class="audit-seq">#${e.sequence}</span>
                    <span class="audit-type" style="color: ${typeColor}">${e.event_type}</span>
                    <span class="audit-time">${formatTime(e.timestamp * 1000)}</span>
                </div>
                <div class="audit-details">
                    <span class="audit-source">${e.source}</span>
                    <span class="audit-hash">${e.entry_hash.slice(0, 12)}...</span>
                </div>
            </div>
        `;
    }).join('');
}

// ============================================
// EXECUTION ENGINE
// ============================================

async function refreshExecution() {
    await Promise.all([
        fetchExecutionStatus(),
        fetchExecutionPositions(),
        fetchExecutionHistory()
    ]);
}

async function fetchExecutionStatus() {
    try {
        const response = await fetch('/api/v1/institutional/execution/status');
        const data = await response.json();
        
        document.getElementById('exec-mode').textContent = (data.mode || 'paper').toUpperCase();
        document.getElementById('exec-equity').textContent = formatCurrency(data.equity || 100000);
        document.getElementById('exec-pnl').textContent = formatCurrency(data.unrealized_pnl || 0);
        document.getElementById('exec-positions').textContent = data.open_positions || 0;
        document.getElementById('exec-balance').textContent = formatCurrency(data.balance || 100000);
        document.getElementById('exec-exposure').textContent = formatCurrency(data.total_exposure || 0);
        document.getElementById('exec-realized').textContent = formatCurrency(data.realized_pnl || 0);
        
        // Color P&L
        const pnlEl = document.getElementById('exec-pnl');
        pnlEl.className = 'stat-value ' + ((data.unrealized_pnl || 0) >= 0 ? 'positive' : 'negative');
    } catch (e) {
        console.error('Failed to fetch execution status:', e);
    }
}

async function fetchExecutionPositions() {
    try {
        const response = await fetch('/api/v1/institutional/execution/positions');
        const data = await response.json();
        
        renderPositionsFeed(data.positions || []);
    } catch (e) {
        console.error('Failed to fetch positions:', e);
    }
}

async function fetchExecutionHistory() {
    try {
        const response = await fetch('/api/v1/institutional/execution/history?limit=10');
        const data = await response.json();
        
        renderOrdersFeed(data.orders || []);
    } catch (e) {
        console.error('Failed to fetch order history:', e);
    }
}

function renderPositionsFeed(positions) {
    const container = document.getElementById('positions-feed');
    if (!container) return;
    
    if (!positions || positions.length === 0) {
        container.innerHTML = '<div class="empty-state">No open positions</div>';
        return;
    }
    
    container.innerHTML = positions.map(p => {
        const pnlClass = p.unrealized_pnl >= 0 ? 'positive' : 'negative';
        const sideClass = p.side === 'long' ? 'long' : 'short';
        
        return `
            <div class="position-card">
                <div class="position-header">
                    <span class="position-symbol">${p.symbol}</span>
                    <span class="position-side ${sideClass}">${p.side.toUpperCase()}</span>
                </div>
                <div class="position-metrics">
                    <div class="position-metric">
                        <span class="metric-label">Qty</span>
                        <span class="metric-value">${p.quantity.toFixed(4)}</span>
                    </div>
                    <div class="position-metric">
                        <span class="metric-label">Entry</span>
                        <span class="metric-value">${formatCurrency(p.entry_price)}</span>
                    </div>
                    <div class="position-metric">
                        <span class="metric-label">P&L</span>
                        <span class="metric-value ${pnlClass}">${formatCurrency(p.unrealized_pnl)}</span>
                    </div>
                </div>
                <div class="position-stops">
                    <span class="stop-label">SL: ${p.stop_loss ? formatCurrency(p.stop_loss) : '-'}</span>
                    <span class="stop-label">TP: ${p.take_profit ? formatCurrency(p.take_profit) : '-'}</span>
                </div>
            </div>
        `;
    }).join('');
}

function renderOrdersFeed(orders) {
    const container = document.getElementById('orders-feed');
    if (!container) return;
    
    if (!orders || orders.length === 0) {
        container.innerHTML = '<div class="empty-state">No orders</div>';
        return;
    }
    
    container.innerHTML = orders.map(o => {
        const sideClass = o.side === 'buy' ? 'long' : 'short';
        
        return `
            <div class="order-row">
                <span class="order-symbol">${o.symbol}</span>
                <span class="order-side ${sideClass}">${o.side.toUpperCase()}</span>
                <span class="order-qty">${o.quantity.toFixed(4)}</span>
                <span class="order-price">${formatCurrency(o.filled_price)}</span>
                <span class="order-status">${o.status}</span>
            </div>
        `;
    }).join('');
}

function formatCurrency(value) {
    if (value === null || value === undefined) return '-';
    const sign = value >= 0 ? '' : '-';
    return sign + '$' + Math.abs(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// ============================================
// STREAMING AGENT MESH
// ============================================

async function refreshMesh() {
    await fetchMeshStatus();
}

async function fetchMeshStatus() {
    try {
        const response = await fetch('/api/v1/institutional/mesh/status');
        const data = await response.json();
        
        document.getElementById('mesh-status').textContent = data.running ? 'RUNNING' : 'IDLE';
        document.getElementById('mesh-total').textContent = data.total_agents || 0;
        
        const agents = data.agents || [];
        const runningCount = agents.filter(a => a.running).length;
        document.getElementById('mesh-running').textContent = runningCount;
        
        renderMeshGrid(agents);
    } catch (e) {
        console.error('Failed to fetch mesh status:', e);
    }
}

function renderMeshGrid(agents) {
    const container = document.getElementById('mesh-grid');
    if (!container) return;
    
    if (!agents || agents.length === 0) {
        container.innerHTML = '<div class="empty-state">No agents in mesh</div>';
        return;
    }
    
    const agentRoles = {
        'market-analyst': { icon: '📊', name: 'Market Analyst', desc: 'TA + momentum' },
        'news-analyst': { icon: '📰', name: 'News Analyst', desc: 'Narrative impact' },
        'risk-agent': { icon: '🛡️', name: 'Risk Agent', desc: 'VETO power' },
        'skeptic-agent': { icon: '🤔', name: 'Skeptic', desc: 'Adversarial check' },
        'synthesizer-agent': { icon: '🔗', name: 'Synthesizer', desc: 'Cross-agent merge' },
        'strategy-agent': { icon: '♟️', name: 'Strategy', desc: 'Trade structuring' },
        'archivist-agent': { icon: '📚', name: 'Archivist', desc: 'State memory' },
        'meta-audit-agent': { icon: '📋', name: 'Meta-Audit', desc: 'Performance tracking' },
    };
    
    container.innerHTML = agents.map(a => {
        const roleKey = Object.keys(agentRoles).find(k => a.agent_id.includes(k)) || '';
        const role = agentRoles[roleKey] || { icon: '🤖', name: a.agent_id, desc: '' };
        const statusClass = a.running ? 'running' : 'stopped';
        
        return `
            <div class="mesh-agent ${statusClass}">
                <div class="agent-icon">${role.icon}</div>
                <div class="agent-info">
                    <div class="agent-name">${role.name}</div>
                    <div class="agent-desc">${role.desc}</div>
                </div>
                <div class="agent-status ${statusClass}">${a.running ? 'RUNNING' : 'STOPPED'}</div>
            </div>
        `;
    }).join('');
}

// ============================================
// PERFORMANCE ANALYTICS
// ============================================

async function refreshAnalytics() {
    await Promise.all([
        fetchAnalyticsSummary(),
        fetchAnalyticsTrades()
    ]);
}

async function fetchAnalyticsSummary() {
    try {
        const response = await fetch('/api/v1/institutional/analytics/summary');
        const data = await response.json();
        
        document.getElementById('analytics-trades').textContent = data.total_trades || 0;
        document.getElementById('analytics-winrate').textContent = (data.win_rate || 0).toFixed(1) + '%';
        document.getElementById('analytics-pnl').textContent = formatCurrency(data.total_pnl || 0);
        document.getElementById('analytics-drawdown').textContent = (data.max_drawdown || 0).toFixed(1) + '%';
        document.getElementById('analytics-pf').textContent = (data.profit_factor || 0).toFixed(2);
        document.getElementById('analytics-avgwin').textContent = formatCurrency(data.average_win || 0);
        document.getElementById('analytics-avgloss').textContent = formatCurrency(data.average_loss || 0);
        document.getElementById('analytics-largestwin').textContent = formatCurrency(data.largest_win || 0);
        document.getElementById('analytics-largestloss').textContent = formatCurrency(data.largest_loss || 0);
        
        // Color P&L
        const pnlEl = document.getElementById('analytics-pnl');
        pnlEl.className = 'stat-value ' + ((data.total_pnl || 0) >= 0 ? 'positive' : 'negative');
    } catch (e) {
        console.error('Failed to fetch analytics summary:', e);
    }
}

async function fetchAnalyticsTrades() {
    try {
        const response = await fetch('/api/v1/institutional/analytics/trades?limit=10');
        const data = await response.json();
        
        renderAnalyticsTrades(data.trades || []);
    } catch (e) {
        console.error('Failed to fetch analytics trades:', e);
    }
}

function renderAnalyticsTrades(trades) {
    const container = document.getElementById('analytics-trades-feed');
    if (!container) return;
    
    if (!trades || trades.length === 0) {
        container.innerHTML = '<div class="empty-state">No trades recorded</div>';
        return;
    }
    
    container.innerHTML = trades.map(t => {
        const pnlClass = t.pnl >= 0 ? 'positive' : 'negative';
        const sideClass = t.side === 'long' ? 'long' : 'short';
        
        return `
            <div class="trade-row">
                <div class="trade-info">
                    <span class="trade-symbol">${t.symbol}</span>
                    <span class="trade-side ${sideClass}">${t.side.toUpperCase()}</span>
                </div>
                <div class="trade-prices">
                    <span class="trade-entry">${formatCurrency(t.entry_price)}</span>
                    <span class="trade-arrow">→</span>
                    <span class="trade-exit">${formatCurrency(t.exit_price)}</span>
                </div>
                <div class="trade-pnl ${pnlClass}">${formatCurrency(t.pnl)} (${t.pnl_pct.toFixed(2)}%)</div>
            </div>
        `;
    }).join('');
}

// ============================================
// PORTFOLIO MANAGEMENT
// ============================================

async function refreshPortfolio() {
    await Promise.all([
        fetchPortfolioSummary(),
        fetchPortfolioHoldings(),
        fetchPortfolioRebalance()
    ]);
}

async function fetchPortfolioSummary() {
    try {
        const response = await fetch('/api/v1/institutional/portfolio/summary');
        const data = await response.json();
        
        document.getElementById('portfolio-value').textContent = formatCurrency(data.total_value || 0);
        document.getElementById('portfolio-cash').textContent = formatCurrency(data.cash || 0);
        document.getElementById('portfolio-invested').textContent = formatCurrency(data.invested || 0);
        
        const pnlEl = document.getElementById('portfolio-pnl');
        pnlEl.textContent = formatCurrency(data.pnl || 0);
        pnlEl.className = 'stat-value ' + ((data.pnl || 0) >= 0 ? 'positive' : 'negative');
    } catch (e) {
        console.error('Failed to fetch portfolio summary:', e);
    }
}

async function fetchPortfolioHoldings() {
    try {
        const response = await fetch('/api/v1/institutional/portfolio/holdings');
        const data = await response.json();
        
        const container = document.getElementById('portfolio-holdings');
        if (!data.holdings || data.holdings.length === 0) {
            container.innerHTML = '<div class="empty-state">No positions</div>';
            return;
        }
        
        container.innerHTML = data.holdings.map(h => `
            <div class="holding-row">
                <div class="holding-symbol">${h.symbol}</div>
                <div class="holding-qty">${h.quantity.toFixed(4)}</div>
                <div class="holding-value">${formatCurrency(h.market_value)}</div>
                <div class="holding-pnl ${h.pnl >= 0 ? 'positive' : 'negative'}">${formatCurrency(h.pnl)} (${h.pnl_pct.toFixed(2)}%)</div>
            </div>
        `).join('');
    } catch (e) {
        console.error('Failed to fetch portfolio holdings:', e);
    }
}

async function fetchPortfolioRebalance() {
    try {
        const response = await fetch('/api/v1/institutional/portfolio/rebalance');
        const data = await response.json();
        
        const container = document.getElementById('portfolio-rebalance');
        if (!data.orders || data.orders.length === 0) {
            container.innerHTML = '<div class="empty-state">Portfolio is balanced</div>';
            return;
        }
        
        container.innerHTML = data.orders.map(o => `
            <div class="rebalance-row">
                <span class="rebalance-action ${o.action}">${o.action.toUpperCase()}</span>
                <span class="rebalance-symbol">${o.symbol}</span>
                <span class="rebalance-qty">${o.quantity.toFixed(4)}</span>
                <span class="rebalance-value">${formatCurrency(o.estimated_value)}</span>
            </div>
        `).join('');
    } catch (e) {
        console.error('Failed to fetch rebalance orders:', e);
    }
}

// ============================================
// BACKTESTING
// ============================================

async function refreshBacktest() {
    await fetchBacktestHistory();
}

async function runBacktest() {
    const strategy = document.getElementById('backtest-strategy').value;
    const symbol = document.getElementById('backtest-symbol').value;
    const days = document.getElementById('backtest-days').value;
    
    const resultsContainer = document.getElementById('backtest-results');
    resultsContainer.innerHTML = '<div class="loading">Running backtest...</div>';
    
    try {
        const response = await fetch(`/api/v1/institutional/backtest/run?strategy=${strategy}&symbol=${encodeURIComponent(symbol)}&days=${days}`, {
            method: 'POST'
        });
        const data = await response.json();
        
        if (data.status === 'completed' && data.result) {
            const r = data.result;
            resultsContainer.innerHTML = `
                <div class="backtest-result-card">
                    <div class="result-header">${r.strategy_name} - ${r.duration_days} days</div>
                    <div class="result-metrics">
                        <div class="result-metric">
                            <span class="metric-label">Return</span>
                            <span class="metric-value ${r.total_return_pct >= 0 ? 'positive' : 'negative'}">${r.total_return_pct.toFixed(2)}%</span>
                        </div>
                        <div class="result-metric">
                            <span class="metric-label">Sharpe</span>
                            <span class="metric-value">${r.sharpe_ratio.toFixed(2)}</span>
                        </div>
                        <div class="result-metric">
                            <span class="metric-label">Max DD</span>
                            <span class="metric-value negative">${r.max_drawdown_pct.toFixed(2)}%</span>
                        </div>
                        <div class="result-metric">
                            <span class="metric-label">Win Rate</span>
                            <span class="metric-value">${r.win_rate.toFixed(1)}%</span>
                        </div>
                        <div class="result-metric">
                            <span class="metric-label">Trades</span>
                            <span class="metric-value">${r.total_trades}</span>
                        </div>
                        <div class="result-metric">
                            <span class="metric-label">Profit Factor</span>
                            <span class="metric-value">${r.profit_factor.toFixed(2)}</span>
                        </div>
                    </div>
                </div>
            `;
        } else {
            resultsContainer.innerHTML = `<div class="error-state">Backtest failed: ${data.error || 'Unknown error'}</div>`;
        }
        
        await fetchBacktestHistory();
    } catch (e) {
        console.error('Failed to run backtest:', e);
        resultsContainer.innerHTML = '<div class="error-state">Failed to run backtest</div>';
    }
}

async function fetchBacktestHistory() {
    try {
        const response = await fetch('/api/v1/institutional/backtest/results');
        const data = await response.json();
        
        const container = document.getElementById('backtest-history');
        if (!data.results || data.results.length === 0) {
            container.innerHTML = '<div class="empty-state">No previous backtests</div>';
            return;
        }
        
        container.innerHTML = data.results.slice(0, 10).map(r => `
            <div class="backtest-history-row">
                <span class="bt-strategy">${r.strategy_name}</span>
                <span class="bt-return ${r.total_return_pct >= 0 ? 'positive' : 'negative'}">${r.total_return_pct.toFixed(2)}%</span>
                <span class="bt-trades">${r.total_trades} trades</span>
                <span class="bt-sharpe">Sharpe: ${r.sharpe_ratio.toFixed(2)}</span>
            </div>
        `).join('');
    } catch (e) {
        console.error('Failed to fetch backtest history:', e);
    }
}

// ============================================
// ALERTS & NOTIFICATIONS
// ============================================

async function refreshAlerts() {
    await Promise.all([
        fetchAlertsSummary(),
        fetchAlertsList(),
        fetchNotifications()
    ]);
}

async function fetchAlertsSummary() {
    try {
        const response = await fetch('/api/v1/institutional/alerts/summary');
        const data = await response.json();
        
        document.getElementById('alerts-active').textContent = data.active_alerts || 0;
        document.getElementById('alerts-triggered').textContent = data.triggered_alerts || 0;
        document.getElementById('alerts-unread').textContent = data.unread_notifications || 0;
    } catch (e) {
        console.error('Failed to fetch alerts summary:', e);
    }
}

async function fetchAlertsList() {
    try {
        const response = await fetch('/api/v1/institutional/alerts?status=active');
        const data = await response.json();
        
        const container = document.getElementById('alerts-list');
        if (!data.alerts || data.alerts.length === 0) {
            container.innerHTML = '<div class="empty-state">No active alerts</div>';
            return;
        }
        
        container.innerHTML = data.alerts.map(a => `
            <div class="alert-row">
                <span class="alert-type">${a.alert_type}</span>
                <span class="alert-message">${a.message}</span>
                <button class="btn btn-sm btn-danger" onclick="deleteAlert('${a.alert_id}')">Delete</button>
            </div>
        `).join('');
    } catch (e) {
        console.error('Failed to fetch alerts:', e);
    }
}

async function fetchNotifications() {
    try {
        const response = await fetch('/api/v1/institutional/notifications');
        const data = await response.json();
        
        const container = document.getElementById('notifications-list');
        if (!data.notifications || data.notifications.length === 0) {
            container.innerHTML = '<div class="empty-state">No notifications</div>';
            return;
        }
        
        container.innerHTML = data.notifications.slice(0, 20).map(n => `
            <div class="notification-row ${n.read ? 'read' : 'unread'}">
                <span class="notif-priority ${n.priority}">${n.priority}</span>
                <span class="notif-message">${n.message}</span>
                <span class="notif-time">${formatTime(n.timestamp * 1000)}</span>
            </div>
        `).join('');
    } catch (e) {
        console.error('Failed to fetch notifications:', e);
    }
}

async function createAlert() {
    const symbol = document.getElementById('alert-symbol').value;
    const direction = document.getElementById('alert-direction').value;
    const price = document.getElementById('alert-price').value;
    
    if (!price) {
        alert('Please enter a target price');
        return;
    }
    
    try {
        const response = await fetch(`/api/v1/institutional/alerts/price?symbol=${encodeURIComponent(symbol)}&target_price=${price}&direction=${direction}`, {
            method: 'POST'
        });
        const data = await response.json();
        
        if (data.status === 'created') {
            document.getElementById('alert-price').value = '';
            await refreshAlerts();
        } else {
            alert('Failed to create alert: ' + (data.error || 'Unknown error'));
        }
    } catch (e) {
        console.error('Failed to create alert:', e);
    }
}

async function deleteAlert(alertId) {
    try {
        await fetch(`/api/v1/institutional/alerts/${alertId}`, { method: 'DELETE' });
        await refreshAlerts();
    } catch (e) {
        console.error('Failed to delete alert:', e);
    }
}

async function markAllRead() {
    try {
        await fetch('/api/v1/institutional/notifications/read-all', { method: 'POST' });
        await refreshAlerts();
    } catch (e) {
        console.error('Failed to mark all read:', e);
    }
}

// ============================================
// ARBITRAGE FUNCTIONS
// ============================================

async function refreshArbitrage() {
    try {
        // Fetch status
        const statusRes = await fetch('/api/v1/arbitrage/status');
        const status = await statusRes.json();
        
        // Update stats
        document.getElementById('arb-opportunities').textContent = status.recent_opportunities_count || 0;
        
        // Count active scanners
        const scanners = status.scanners || {};
        const activeCount = Object.values(scanners).filter(s => s.state === 'running').length;
        document.getElementById('arb-scanners-active').textContent = `${activeCount}/4`;
        
        // Update execution status
        const gate = status.execution_gate || {};
        const execEnabled = gate.execution_enabled;
        const execEl = document.getElementById('arb-execution-status');
        execEl.textContent = execEnabled ? 'ENABLED' : 'DISABLED';
        execEl.className = 'stat-value ' + (execEnabled ? 'positive' : 'warning');
        
        // Update gate info
        document.getElementById('gate-enabled').textContent = execEnabled ? 'YES' : 'NO';
        document.getElementById('gate-enabled').className = 'badge ' + (execEnabled ? 'badge-success' : 'badge-danger');
        
        const killSwitch = gate.kill_switch_active;
        document.getElementById('gate-killswitch').textContent = killSwitch ? 'ON' : 'OFF';
        document.getElementById('gate-killswitch').className = 'badge ' + (killSwitch ? 'badge-danger' : 'badge-success');
        
        document.getElementById('gate-daily-exec').textContent = 
            `${gate.daily_executions || 0}/${gate.limits?.max_daily_executions || 100}`;
        document.getElementById('gate-daily-vol').textContent = 
            `$${(gate.daily_volume_usd || 0).toLocaleString()}`;
        
        // Update scanner statuses
        updateScannerList(scanners);
        
        // Fetch opportunities
        const oppsRes = await fetch('/api/v1/arbitrage/opportunities?limit=20');
        const oppsData = await oppsRes.json();
        
        // Calculate total potential profit
        const totalProfit = (oppsData.opportunities || [])
            .reduce((sum, o) => sum + (o.net_profit_usd || 0), 0);
        document.getElementById('arb-potential-profit').textContent = `$${totalProfit.toFixed(2)}`;
        
        // Render opportunities
        renderOpportunities(oppsData.opportunities || []);
        
    } catch (e) {
        console.error('Failed to refresh arbitrage:', e);
    }
}

function updateScannerList(scanners) {
    const scannerNames = {
        'cross_cex': 'Cross-CEX',
        'dex_cex': 'DEX-CEX',
        'perp_spot': 'Perp-Spot',
        'funding_rate': 'Funding Rate'
    };
    
    const container = document.getElementById('arb-scanners');
    if (!container) return;
    
    container.innerHTML = Object.entries(scanners).map(([key, scanner]) => {
        const state = scanner.state || 'stopped';
        const isRunning = state === 'running';
        const scannerId = scanner.scanner_id || key + '_scanner';
        const name = scannerNames[key] || key;
        const metrics = scanner.metrics || {};
        
        return `
            <div class="scanner-item">
                <div class="scanner-info">
                    <span class="scanner-name">${name}</span>
                    <span class="scanner-stats">
                        ${metrics.opportunities_found || 0} found | 
                        ${metrics.profitable_opportunities || 0} profitable
                    </span>
                </div>
                <span class="scanner-status ${isRunning ? 'running' : 'stopped'}">${state.toUpperCase()}</span>
                <button class="btn btn-xs" onclick="toggleScanner('${scannerId}')">${isRunning ? 'Stop' : 'Start'}</button>
            </div>
        `;
    }).join('');
}

function renderOpportunities(opportunities) {
    const container = document.getElementById('arb-opportunities-list');
    if (!container) return;
    
    if (!opportunities || opportunities.length === 0) {
        container.innerHTML = '<div class="empty-state">No opportunities detected. Start scanners to begin.</div>';
        return;
    }
    
    container.innerHTML = opportunities.map(opp => {
        const profit = opp.net_profit_usd || 0;
        const margin = opp.profit_margin_pct || 0;
        const type = opp.arb_type || 'unknown';
        const canExec = opp.can_execute;
        
        const legs = (opp.legs || []).map(leg => 
            `${leg.side.toUpperCase()} ${leg.quantity?.toFixed(4)} @ ${leg.venue}`
        ).join(' → ');
        
        return `
            <div class="opportunity-card ${canExec ? 'executable' : ''}">
                <div class="opp-header">
                    <span class="opp-type">${type.replace('_', '-').toUpperCase()}</span>
                    <span class="opp-profit positive">+$${profit.toFixed(2)} (${margin.toFixed(3)}%)</span>
                </div>
                <div class="opp-legs">${legs}</div>
                <div class="opp-meta">
                    <span>Risk: ${((opp.execution_risk || 0) * 100).toFixed(0)}%</span>
                    <span>Liquidity: ${((opp.liquidity_score || 0) * 100).toFixed(0)}%</span>
                    ${opp.notes ? `<span class="opp-notes">${opp.notes}</span>` : ''}
                </div>
            </div>
        `;
    }).join('');
}

async function toggleScanner(scannerId) {
    try {
        // Get current status
        const statusRes = await fetch(`/api/v1/arbitrage/scanners/${scannerId}`);
        const status = await statusRes.json();
        
        const isRunning = status.state === 'running';
        const action = isRunning ? 'stop' : 'start';
        
        await fetch(`/api/v1/arbitrage/scanners/${scannerId}/${action}`, { method: 'POST' });
        
        // Refresh after short delay
        setTimeout(refreshArbitrage, 500);
    } catch (e) {
        console.error('Failed to toggle scanner:', e);
        alert('Failed to toggle scanner: ' + e.message);
    }
}

async function startAllScanners() {
    try {
        await fetch('/api/v1/arbitrage/start-all', { method: 'POST' });
        setTimeout(refreshArbitrage, 1000);
    } catch (e) {
        console.error('Failed to start scanners:', e);
        alert('Failed to start scanners: ' + e.message);
    }
}

async function stopAllScanners() {
    try {
        await fetch('/api/v1/arbitrage/stop-all', { method: 'POST' });
        setTimeout(refreshArbitrage, 500);
    } catch (e) {
        console.error('Failed to stop scanners:', e);
        alert('Failed to stop scanners: ' + e.message);
    }
}

async function activateKillSwitch() {
    const reason = prompt('Enter reason for kill switch activation:');
    if (!reason) return;
    
    try {
        await fetch('/api/v1/arbitrage/gate/kill-switch/activate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reason })
        });
        alert('Kill switch activated');
        refreshArbitrage();
    } catch (e) {
        console.error('Failed to activate kill switch:', e);
        alert('Failed to activate kill switch: ' + e.message);
    }
}

// ============================================
// UTILITY FUNCTIONS
// ============================================

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTime(timestamp) {
    if (!timestamp) return '';
    const date = new Date(timestamp);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// ============================================
// NEW FEATURES - OPERATIONS SECTION
// ============================================

// Monitoring
async function refreshMonitoring() {
    try {
        const [dashboardRes, healthChecksRes] = await Promise.all([
            fetch('/api/v1/monitoring/dashboard'),
            fetch('/api/v1/monitoring/health/checks')
        ]);
        
        const dashboard = await dashboardRes.json();
        const healthChecks = await healthChecksRes.json();
        
        // Update stats from system data
        const system = dashboard.system;
        if (system) {
            if (system.cpu_percent !== undefined) {
                document.getElementById('mon-cpu').textContent = system.cpu_percent.toFixed(1) + '%';
            }
            if (system.memory_percent !== undefined) {
                document.getElementById('mon-memory').textContent = system.memory_percent.toFixed(1) + '%';
            }
            if (system.disk_percent !== undefined) {
                document.getElementById('mon-disk').textContent = system.disk_percent.toFixed(1) + '%';
            }
        } else {
            document.getElementById('mon-cpu').textContent = '--';
            document.getElementById('mon-memory').textContent = '--';
            document.getElementById('mon-disk').textContent = '--';
        }
        
        // Health status
        const health = dashboard.health;
        const healthStatus = health?.status || 'unknown';
        const healthEl = document.getElementById('mon-health');
        healthEl.textContent = healthStatus.toUpperCase();
        healthEl.className = `stat-value ${healthStatus === 'healthy' ? 'positive' : healthStatus === 'unhealthy' ? 'negative' : ''}`;
        
        // Render health checks
        const healthList = document.getElementById('health-checks-list');
        if (healthList) {
            const checks = healthChecks.checks || healthChecks;
            if (checks && Object.keys(checks).length > 0) {
                healthList.innerHTML = Object.entries(checks).map(([name, check]) => `
                    <div class="health-item">
                        <span class="health-name">${name}</span>
                        <span class="health-status ${check.status || 'unknown'}">${(check.status || 'unknown').toUpperCase()}</span>
                    </div>
                `).join('');
            } else {
                healthList.innerHTML = '<div class="empty-state">No health checks configured</div>';
            }
        }
        
        // Render metrics from dashboard
        const metricsList = document.getElementById('perf-metrics-list');
        if (metricsList) {
            const perf = dashboard.performance;
            const metricsSummary = dashboard.metrics_summary;
            const metricsData = [
                ['Total Trades', perf?.total_trades || 0],
                ['Win Rate', (perf?.win_rate || 0).toFixed(1) + '%'],
                ['Total P&L', '$' + (perf?.total_pnl || 0).toFixed(2)],
                ['Current Equity', '$' + (perf?.current_equity || 100000).toLocaleString()],
                ['Max Drawdown', (perf?.max_drawdown_pct || 0).toFixed(2) + '%'],
                ['HTTP Requests', metricsSummary?.http_requests || 0],
                ['WS Connections', metricsSummary?.ws_connections || 0],
                ['Total Metrics', metricsSummary?.total_metrics || 0],
            ];
            metricsList.innerHTML = metricsData.map(([name, value]) => `
                <div class="metric-item">
                    <span class="metric-name">${name}</span>
                    <span class="metric-value">${value}</span>
                </div>
            `).join('');
        }
    } catch (e) {
        console.error('Failed to refresh monitoring:', e);
    }
}

// Rate Limiting
async function refreshRateLimits() {
    try {
        const [statusRes, rulesRes, blockedRes] = await Promise.all([
            fetch('/api/v1/ratelimit/status'),
            fetch('/api/v1/ratelimit/rules'),
            fetch('/api/v1/ratelimit/blocked')
        ]);
        
        const status = await statusRes.json();
        const rules = await rulesRes.json();
        const blocked = await blockedRes.json();
        
        // Rules is an object with rule_id keys
        const rulesArr = Object.entries(rules);
        
        // Update stats
        document.getElementById('rl-total-rules').textContent = rulesArr.length;
        document.getElementById('rl-blocked').textContent = blocked.count || Object.keys(blocked.blocked || blocked).length || 0;
        document.getElementById('rl-throttled').textContent = status.throttled_count || 0;
        document.getElementById('rl-requests').textContent = status.total_requests || '--';
        
        // Render rules
        const rulesList = document.getElementById('ratelimit-rules-list');
        if (rulesList) {
            rulesList.innerHTML = rulesArr.length > 0 ? rulesArr.map(([id, rule]) => `
                <div class="rule-item">
                    <span class="rule-name">${id}</span>
                    <span class="rule-limit">${rule.requests_per_minute || '--'}/min</span>
                </div>
            `).join('') : '<div class="empty-state">No rules configured</div>';
        }
        
        // Render blocked
        const blockedList = document.getElementById('blocked-list');
        if (blockedList) {
            const blockedItems = blocked.blocked || Object.entries(blocked);
            if (Array.isArray(blockedItems) && blockedItems.length > 0) {
                blockedList.innerHTML = blockedItems.slice(0, 10).map(item => {
                    const id = item.identifier || item[0] || item;
                    const until = item.until || item[1]?.until;
                    return `
                        <div class="blocked-item">
                            <span class="blocked-id">${id}</span>
                            <span class="blocked-until">${until ? new Date(until * 1000).toLocaleTimeString() : '--'}</span>
                        </div>
                    `;
                }).join('');
            } else {
                blockedList.innerHTML = '<div class="empty-state">No blocked identifiers</div>';
            }
        }
    } catch (e) {
        console.error('Failed to refresh rate limits:', e);
    }
}

// Backup
async function refreshBackup() {
    try {
        const [statusRes, snapshotsRes, schedulesRes, recoveryRes] = await Promise.all([
            fetch('/api/v1/backup/status'),
            fetch('/api/v1/backup/snapshots'),
            fetch('/api/v1/backup/schedules'),
            fetch('/api/v1/backup/recovery/points')
        ]);
        
        const status = await statusRes.json();
        const snapshots = await snapshotsRes.json();
        const schedules = await schedulesRes.json();
        const recovery = await recoveryRes.json();
        
        // Update stats
        document.getElementById('backup-total').textContent = snapshots.count || 0;
        document.getElementById('backup-last').textContent = status.last_backup ? 
            new Date(status.last_backup * 1000).toLocaleDateString() : 'Never';
        document.getElementById('backup-schedules').textContent = Object.keys(schedules).length || 0;
        document.getElementById('backup-recovery').textContent = recovery.count || 0;
        
        // Render snapshots
        const snapshotsList = document.getElementById('snapshots-list');
        if (snapshotsList && snapshots.snapshots) {
            snapshotsList.innerHTML = snapshots.snapshots.slice(0, 5).map(snap => `
                <div class="snapshot-item">
                    <span class="snapshot-id">${snap.snapshot_id?.substring(0, 8) || '--'}...</span>
                    <span class="snapshot-type">${snap.snapshot_type || 'full'}</span>
                    <span class="snapshot-time">${snap.created_at ? new Date(snap.created_at * 1000).toLocaleString() : '--'}</span>
                </div>
            `).join('') || '<div class="empty-state">No snapshots</div>';
        }
        
        // Render schedules
        const schedulesList = document.getElementById('backup-schedules-list');
        if (schedulesList) {
            const schedArr = Object.entries(schedules);
            schedulesList.innerHTML = schedArr.length > 0 ? schedArr.map(([id, sched]) => `
                <div class="schedule-item">
                    <span class="schedule-name">${sched.name || id}</span>
                    <span class="schedule-interval">${sched.interval_hours || '--'}h</span>
                    <span class="schedule-status ${sched.enabled ? 'active' : 'inactive'}">${sched.enabled ? 'Active' : 'Inactive'}</span>
                </div>
            `).join('') : '<div class="empty-state">No schedules</div>';
        }
    } catch (e) {
        console.error('Failed to refresh backup:', e);
    }
}

async function createSnapshot() {
    try {
        const res = await fetch('/api/v1/backup/snapshots', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ snapshot_type: 'full', description: 'Manual snapshot' })
        });
        if (res.ok) {
            alert('Snapshot created successfully');
            refreshBackup();
        }
    } catch (e) {
        console.error('Failed to create snapshot:', e);
        alert('Failed to create snapshot');
    }
}

// Plugins
async function refreshPlugins() {
    try {
        const statusRes = await fetch('/api/v1/plugins/status');
        const status = await statusRes.json();
        
        // Extract data from status response
        const loader = status.loader || {};
        const hooks = status.hooks || {};
        const sandbox = status.sandbox || {};
        
        // Update stats
        document.getElementById('plugins-installed').textContent = loader.loaded_count || 0;
        document.getElementById('plugins-active').textContent = loader.running_count || 0;
        document.getElementById('plugins-hooks').textContent = hooks.total_hooks || 0;
        document.getElementById('plugins-sandbox').textContent = sandbox.active_sandboxes !== undefined ? 
            (sandbox.active_sandboxes > 0 ? 'Active' : 'Ready') : 'Ready';
        
        // Render plugins
        const pluginsList = document.getElementById('plugins-list');
        if (pluginsList) {
            const plugins = loader.plugins || {};
            const pluginsArr = Object.entries(plugins);
            pluginsList.innerHTML = pluginsArr.length > 0 ? pluginsArr.map(([id, p]) => `
                <div class="plugin-item">
                    <span class="plugin-name">${p.name || id}</span>
                    <span class="plugin-version">${p.version || '--'}</span>
                    <span class="plugin-status ${p.running ? 'active' : 'inactive'}">${p.running ? 'Running' : 'Loaded'}</span>
                </div>
            `).join('') : '<div class="empty-state">No plugins installed</div>';
        }
        
        // Render hooks from status
        const hooksList = document.getElementById('hooks-list');
        if (hooksList) {
            const hooksData = hooks.hooks || {};
            const hooksArr = Object.entries(hooksData);
            hooksList.innerHTML = hooksArr.length > 0 ? hooksArr.slice(0, 10).map(([id, h]) => `
                <div class="hook-item">
                    <span class="hook-name">${h.name || id}</span>
                    <span class="hook-handlers">${h.handler_count || 0} handlers</span>
                </div>
            `).join('') : '<div class="empty-state">No hooks registered</div>';
        }
    } catch (e) {
        console.error('Failed to refresh plugins:', e);
    }
}

async function discoverPlugins() {
    try {
        const res = await fetch('/api/v1/plugins/discover', { method: 'POST' });
        const data = await res.json();
        alert(`Discovered ${data.discovered || 0} plugins`);
        refreshPlugins();
    } catch (e) {
        console.error('Failed to discover plugins:', e);
    }
}

// Compliance
async function refreshCompliance() {
    try {
        const statusRes = await fetch('/api/v1/compliance/status');
        const status = await statusRes.json();
        
        // Extract data from status
        const auditStats = status.audit_stats || {};
        const txStats = status.transaction_stats || {};
        const reportGen = status.report_generator || {};
        const retention = status.retention_manager || {};
        
        // Update stats
        document.getElementById('comp-entries').textContent = auditStats.total_events || 0;
        document.getElementById('comp-transactions').textContent = txStats.total_transactions || 0;
        document.getElementById('comp-reports').textContent = reportGen.generated_reports || 0;
        document.getElementById('comp-retention').textContent = '2555';
        
        // Render audit info
        const auditList = document.getElementById('audit-entries-list');
        if (auditList) {
            const categories = auditStats.events_by_category || {};
            const catArr = Object.entries(categories);
            if (catArr.length > 0) {
                auditList.innerHTML = catArr.map(([cat, count]) => `
                    <div class="audit-item">
                        <span class="audit-action">${cat}</span>
                        <span class="audit-time">${count} events</span>
                    </div>
                `).join('');
            } else {
                auditList.innerHTML = `
                    <div class="audit-item">
                        <span class="audit-action">Total Events</span>
                        <span class="audit-time">${auditStats.total_events || 0}</span>
                    </div>
                    <div class="audit-item">
                        <span class="audit-action">Last Hash</span>
                        <span class="audit-time">${auditStats.last_hash || 'genesis'}</span>
                    </div>
                `;
            }
        }
        
        // Render report configs
        const reportsList = document.getElementById('compliance-reports-list');
        if (reportsList) {
            const configs = reportGen.configs || {};
            const configArr = Object.entries(configs);
            reportsList.innerHTML = configArr.length > 0 ? configArr.slice(0, 5).map(([id, cfg]) => `
                <div class="report-item">
                    <span class="report-type">${cfg.name || id}</span>
                    <span class="report-date">${cfg.auto_generate ? 'Auto' : 'Manual'}</span>
                </div>
            `).join('') : '<div class="empty-state">No report configs</div>';
        }
    } catch (e) {
        console.error('Failed to refresh compliance:', e);
    }
}

async function generateReport() {
    const reportType = prompt('Enter report type (daily, weekly, monthly, annual):');
    if (!reportType) return;
    
    try {
        const res = await fetch('/api/v1/compliance/reports/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ report_type: reportType })
        });
        if (res.ok) {
            alert('Report generation started');
            refreshCompliance();
        }
    } catch (e) {
        console.error('Failed to generate report:', e);
        alert('Failed to generate report');
    }
}

// Wallet
async function refreshWallet() {
    try {
        const statusRes = await fetch('/api/v1/wallet/status');
        const status = await statusRes.json();
        
        // Extract data from status
        const keyManager = status.key_manager || {};
        const vaultManager = status.vault_manager || {};
        const walletConnect = status.wallet_connect || {};
        const hardwareWallet = status.hardware_wallet || {};
        
        // Update stats
        document.getElementById('wallet-vaults').textContent = vaultManager.total_vaults || 0;
        document.getElementById('wallet-keys').textContent = keyManager.total_keys || 0;
        document.getElementById('wallet-sessions').textContent = walletConnect.total_sessions || 0;
        document.getElementById('wallet-hw').textContent = hardwareWallet.connected_devices || 0;
        
        // Render vaults
        const vaultsList = document.getElementById('vaults-list');
        if (vaultsList) {
            const vaults = vaultManager.vaults || {};
            const vaultsArr = Object.entries(vaults);
            vaultsList.innerHTML = vaultsArr.length > 0 ? vaultsArr.map(([id, v]) => `
                <div class="vault-item">
                    <span class="vault-name">${v.name || id}</span>
                    <span class="vault-type">${v.vault_type || 'standard'}</span>
                    <span class="vault-keys">$${(v.total_value_usd || 0).toLocaleString()}</span>
                </div>
            `).join('') : '<div class="empty-state">No vaults</div>';
        }
        
        // Render WalletConnect sessions
        const sessionsList = document.getElementById('wc-sessions-list');
        if (sessionsList) {
            const sessions = walletConnect.sessions || [];
            sessionsList.innerHTML = sessions.length > 0 ? sessions.map(s => `
                <div class="session-item">
                    <span class="session-peer">${s.peer_name || s.topic?.substring(0, 8) || '--'}</span>
                    <span class="session-chain">${s.chain || '--'}</span>
                </div>
            `).join('') : '<div class="empty-state">No active sessions</div>';
        }
    } catch (e) {
        console.error('Failed to refresh wallet:', e);
    }
}

// Update refreshSection to include new sections
const originalRefreshSection = refreshSection;
refreshSection = function(section) {
    switch(section) {
        case 'monitoring':
            refreshMonitoring();
            break;
        case 'ratelimit':
            refreshRateLimits();
            break;
        case 'backup':
            refreshBackup();
            break;
        case 'plugins':
            refreshPlugins();
            break;
        case 'compliance':
            refreshCompliance();
            break;
        case 'wallet':
            refreshWallet();
            break;
        case 'treasury':
            refreshTreasury();
            break;
        case 'sniping':
            refreshSniping();
            break;
        case 'recovery':
            refreshRecovery();
            break;
        default:
            originalRefreshSection(section);
    }
};

// Treasury Section
async function refreshTreasury() {
    try {
        const statusRes = await fetch('/api/v1/treasury/status');
        const status = await statusRes.json();
        
        // Update stats
        const yieldEl = document.getElementById('treasury-yield-sources');
        const agentsEl = document.getElementById('treasury-agents');
        const proposalsEl = document.getElementById('treasury-proposals');
        const drawdownEl = document.getElementById('treasury-drawdown');
        
        if (yieldEl) yieldEl.textContent = status.yield_sources || 0;
        if (agentsEl) agentsEl.textContent = status.active_agents || 0;
        if (proposalsEl) proposalsEl.textContent = status.active_proposals || 0;
        if (drawdownEl) {
            const dd = status.drawdown || {};
            drawdownEl.textContent = `${(dd.current_drawdown_pct || 0).toFixed(2)}%`;
            drawdownEl.className = dd.state === 'normal' ? 'stat-value' : 'stat-value warning';
        }
        
        // Render top yield sources
        const sourcesList = document.getElementById('yield-sources-list');
        if (sourcesList && status.top_sources) {
            sourcesList.innerHTML = status.top_sources.map(s => `
                <div class="yield-source-item">
                    <span class="source-name">${s.protocol} - ${s.asset}</span>
                    <span class="source-apy">${s.current_apy.toFixed(2)}% APY</span>
                    <span class="source-risk risk-${s.risk_tier}">${s.risk_tier.replace('tier_', 'T')}</span>
                </div>
            `).join('');
        }
        
        // Render drawdown status
        const drawdownStatus = document.getElementById('drawdown-status');
        if (drawdownStatus && status.drawdown) {
            const dd = status.drawdown;
            drawdownStatus.innerHTML = `
                <div class="drawdown-info">
                    <div class="dd-state state-${dd.state}">${dd.state.toUpperCase()}</div>
                    <div class="dd-metrics">
                        <span>Peak: $${(dd.peak_value_usd || 0).toLocaleString()}</span>
                        <span>Current: $${(dd.current_value_usd || 0).toLocaleString()}</span>
                        <span>Drawdown: ${(dd.current_drawdown_pct || 0).toFixed(2)}%</span>
                    </div>
                    ${dd.paused ? '<div class="dd-paused">PAUSED</div>' : ''}
                </div>
            `;
        }
    } catch (e) {
        console.error('Failed to refresh treasury:', e);
    }
}

// Sniping Section
async function refreshSniping() {
    try {
        const statusRes = await fetch('/api/v1/sniping/status');
        const status = await statusRes.json();
        
        // Update stats
        const alertsEl = document.getElementById('sniping-alerts');
        const tokensEl = document.getElementById('sniping-tokens');
        const rejectedEl = document.getElementById('sniping-rejected');
        const modeEl = document.getElementById('sniping-mode');
        
        if (alertsEl) alertsEl.textContent = status.active_alerts || 0;
        if (tokensEl) tokensEl.textContent = status.detected_tokens || 0;
        if (rejectedEl) rejectedEl.textContent = status.rejected_tokens || 0;
        if (modeEl) {
            modeEl.textContent = status.mode || 'ALERT_ONLY';
            modeEl.className = status.execution_enabled ? 'stat-value danger' : 'stat-value safe';
        }
        
        // Fetch and render alerts
        const alertsRes = await fetch('/api/v1/sniping/alerts?limit=10');
        const alertsData = await alertsRes.json();
        
        const alertsList = document.getElementById('sniping-alerts-list');
        if (alertsList && alertsData.alerts) {
            alertsList.innerHTML = alertsData.alerts.length > 0 ? alertsData.alerts.map(a => `
                <div class="snipe-alert alert-${a.risk_level}">
                    <div class="alert-header">
                        <span class="alert-symbol">${a.token_symbol}</span>
                        <span class="alert-risk risk-${a.risk_level}">${a.risk_level.toUpperCase()}</span>
                        <span class="alert-score">Score: ${a.opportunity_score.toFixed(0)}</span>
                    </div>
                    <div class="alert-body">
                        <span class="alert-type">${a.alert_type}</span>
                        <span class="alert-chain">${a.chain}</span>
                    </div>
                    <div class="alert-action">${a.recommended_action}</div>
                </div>
            `).join('') : '<div class="empty-state">No active alerts</div>';
        }
    } catch (e) {
        console.error('Failed to refresh sniping:', e);
    }
}

// Recovery Section
async function refreshRecovery() {
    try {
        const statusRes = await fetch('/api/v1/recovery/status');
        const status = await statusRes.json();
        
        // Update stats
        const stateEl = document.getElementById('recovery-state');
        const frozenEl = document.getElementById('recovery-frozen');
        const quarantinedEl = document.getElementById('recovery-quarantined');
        const pointsEl = document.getElementById('recovery-points');
        
        if (stateEl) {
            stateEl.textContent = status.system_state || 'healthy';
            stateEl.className = `stat-value state-${status.system_state}`;
        }
        if (frozenEl) {
            const frozen = status.capital_freeze?.frozen || false;
            frozenEl.textContent = frozen ? 'YES' : 'NO';
            frozenEl.className = frozen ? 'stat-value danger' : 'stat-value safe';
        }
        if (quarantinedEl) quarantinedEl.textContent = status.agent_quarantine?.quarantined_count || 0;
        if (pointsEl) pointsEl.textContent = status.recovery_points || 0;
        
        // Render partial boot status
        const bootStatus = document.getElementById('partial-boot-status');
        if (bootStatus && status.partial_boot) {
            const pb = status.partial_boot;
            bootStatus.innerHTML = `
                <div class="boot-mode">Mode: ${pb.boot_mode}</div>
                <div class="boot-components">
                    <span>Failed: ${pb.failed_components?.length || 0}</span>
                    <span>Bootable: ${pb.bootable_components?.length || 0}</span>
                </div>
            `;
        }
        
        // Render shadow promotion status
        const shadowStatus = document.getElementById('shadow-status');
        if (shadowStatus && status.shadow_promotion) {
            const sp = status.shadow_promotion;
            shadowStatus.innerHTML = `
                <div class="shadow-mode mode-${sp.mode}">${sp.mode.toUpperCase()}</div>
                <div class="shadow-info">
                    ${sp.is_shadow ? 'Running in shadow mode' : 'Running as PRIMARY'}
                </div>
            `;
        }
        
        // Render anomalies
        const anomaliesList = document.getElementById('anomalies-list');
        if (anomaliesList && status.capital_freeze?.recent_anomalies) {
            const anomalies = status.capital_freeze.recent_anomalies;
            anomaliesList.innerHTML = anomalies.length > 0 ? anomalies.slice(0, 5).map(a => `
                <div class="anomaly-item severity-${a.severity}">
                    <span class="anomaly-type">${a.event_type}</span>
                    <span class="anomaly-severity">${a.severity.toUpperCase()}</span>
                    <span class="anomaly-action">${a.action_taken || 'none'}</span>
                </div>
            `).join('') : '<div class="empty-state">No anomalies detected</div>';
        }
    } catch (e) {
        console.error('Failed to refresh recovery:', e);
    }
}

// Enhanced streaming - increase polling frequency and add more data sources
function startEnhancedStreaming() {
    // Faster intelligence polling
    setInterval(fetchIntelligence, 5000);  // Every 5 seconds instead of 15
    
    // Add prediction market streaming
    setInterval(fetchPredictionMarkets, 10000);
    
    // Add arbitrage opportunities streaming
    setInterval(fetchArbitrageOpportunities, 8000);
    
    // Add agent activity streaming
    setInterval(fetchAgentActivity, 6000);
}

async function fetchPredictionMarkets() {
    try {
        const res = await fetch('/api/v1/prediction/markets');
        const data = await res.json();
        
        const container = document.getElementById('prediction-markets-feed');
        if (container && data.markets) {
            const markets = data.markets.slice(0, 10);
            container.innerHTML = markets.map(m => `
                <div class="prediction-market">
                    <div class="market-question">${m.question || m.title || 'Unknown'}</div>
                    <div class="market-odds">
                        <span class="odds-yes">${((m.yes_price || m.probability || 0) * 100).toFixed(1)}%</span>
                        <span class="odds-volume">Vol: $${((m.volume || 0) / 1000).toFixed(1)}K</span>
                    </div>
                </div>
            `).join('');
        }
    } catch (e) {
        // Silently fail - endpoint may not exist
    }
}

async function fetchArbitrageOpportunities() {
    try {
        const res = await fetch('/api/v1/arbitrage/opportunities');
        const data = await res.json();
        
        const container = document.getElementById('arbitrage-opportunities-feed');
        if (container && data.opportunities) {
            const opps = data.opportunities.slice(0, 5);
            container.innerHTML = opps.length > 0 ? opps.map(o => `
                <div class="arb-opportunity type-${o.type}">
                    <div class="arb-pair">${o.symbol || 'Unknown'}</div>
                    <div class="arb-spread">${(o.spread_bps || 0).toFixed(1)} bps</div>
                    <div class="arb-profit">$${(o.expected_profit_usd || 0).toFixed(2)}</div>
                </div>
            `).join('') : '<div class="empty-state">No opportunities</div>';
        }
    } catch (e) {
        // Silently fail
    }
}

async function fetchAgentActivity() {
    try {
        const res = await fetch('/api/v1/agents/activity');
        const data = await res.json();
        
        const container = document.getElementById('agent-activity-feed');
        if (container && data.activities) {
            const activities = data.activities.slice(0, 8);
            container.innerHTML = activities.length > 0 ? activities.map(a => `
                <div class="agent-activity">
                    <span class="agent-name">${a.agent_id || 'Agent'}</span>
                    <span class="agent-action">${a.action || a.type || 'idle'}</span>
                    <span class="agent-time">${formatTime(a.timestamp)}</span>
                </div>
            `).join('') : '<div class="empty-state">No recent activity</div>';
        }
    } catch (e) {
        // Silently fail
    }
}

// Start enhanced streaming on load
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(startEnhancedStreaming, 2000);
});
