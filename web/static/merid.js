// MERID Trading Dashboard - JavaScript Implementation

// Global state
let currentView = 'overview';
let charts = {};
let updateIntervals = {};
let mobileMenuOpen = false;

// Mock data - replace with real API calls
const mockData = {
    watchlist: [
        { symbol: 'BTC/USD', price: 43256.78, change: 2.34, volume: '1.2B' },
        { symbol: 'ETH/USD', price: 2245.12, change: -1.23, volume: '890M' },
        { symbol: 'SOL/USD', price: 98.45, change: 5.67, volume: '445M' },
        { symbol: 'AAPL', price: 178.92, change: 0.45, volume: '52M' },
        { symbol: 'NVDA', price: 485.23, change: 3.21, volume: '38M' }
    ],
    positions: [
        { symbol: 'BTC/USD', side: 'LONG', size: 0.25, entry: 42150, current: 43256, pnl: '+$276.50' },
        { symbol: 'ETH/USD', side: 'SHORT', size: 5.0, entry: 2280, current: 2245, pnl: '+$175.00' },
        { symbol: 'NVDA', side: 'LONG', size: 100, entry: 475.20, current: 485.23, pnl: '+$1,003.00' }
    ],
    apiStatus: [
        { name: 'Alpaca', category: 'Trading', status: 'online', responseTime: 45, errorRate: 0.1 },
        { name: 'Binance', category: 'Trading', status: 'online', responseTime: 23, errorRate: 0.05 },
        { name: 'Coinbase', category: 'Trading', status: 'degraded', responseTime: 234, errorRate: 2.3 },
        { name: 'CoinGecko', category: 'Market Data', status: 'online', responseTime: 67, errorRate: 0.1 }
    ],
    riskAlerts: [
        { time: '2m ago', severity: 'medium', type: 'MARGIN_WARNING', description: 'Margin usage approaching 80%', status: 'active' },
        { time: '15m ago', severity: 'low', type: 'LATENCY_SPIKE', description: 'API latency increased', status: 'acknowledged' },
        { time: '1h ago', severity: 'high', type: 'POSITION_LIMIT', description: 'BTC position near limit', status: 'resolved' }
    ],
    pinnedMarkets: [
        { title: 'BTC > $45k by Dec 31', platform: 'Polymarket', yesProb: 65, noProb: 35, volume: '$2.1M' },
        { title: 'Fed Rate Cut in March', platform: 'Kalshi', yesProb: 72, noProb: 28, volume: '$890K' },
        { title: 'ETH > $3k by Q1 2024', platform: 'Polymarket', yesProb: 58, noProb: 42, volume: '$1.3M' },
        { title: 'S&P 500 > 5,000', platform: 'Kalshi', yesProb: 45, noProb: 55, volume: '$670K' }
    ]
};

// Initialize the application
document.addEventListener('DOMContentLoaded', function() {
    initializeLucideIcons();
    setupEventListeners();
    initializeCharts();
    loadInitialData();
    startRealTimeUpdates();
});

// Initialize Lucide icons
function initializeLucideIcons() {
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
}

// Setup event listeners
function setupEventListeners() {
    // Navigation
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', function() {
            const view = this.dataset.view;
            switchView(view);
        });
    });

    // Mobile menu toggle
    const mobileMenuToggle = document.getElementById('mobile-menu-toggle');
    if (mobileMenuToggle) {
        mobileMenuToggle.addEventListener('click', toggleMobileMenu);
    }

    // Theme toggle
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', toggleTheme);
    }

    // Search functionality
    const searchInput = document.querySelector('.search-input');
    if (searchInput) {
        searchInput.addEventListener('input', handleSearch);
    }

    // Close mobile menu when clicking outside
    document.addEventListener('click', function(e) {
        const sidebar = document.getElementById('sidebar');
        const mobileToggle = document.getElementById('mobile-menu-toggle');
        
        if (mobileMenuOpen && 
            !sidebar.contains(e.target) && 
            !mobileToggle.contains(e.target)) {
            closeMobileMenu();
        }
    });
}

// Switch between views
function switchView(viewName) {
    // Hide all views
    document.querySelectorAll('.view').forEach(view => {
        view.classList.remove('active');
    });

    // Show selected view
    const selectedView = document.getElementById(`view-${viewName}`);
    if (selectedView) {
        selectedView.classList.add('active');
    }

    // Update navigation
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
    });
    
    const activeNavItem = document.querySelector(`[data-view="${viewName}"]`);
    if (activeNavItem) {
        activeNavItem.classList.add('active');
    }

    currentView = viewName;

    // Load view-specific data
    loadViewData(viewName);

    // Close mobile menu
    closeMobileMenu();
}

// Load view-specific data
function loadViewData(view) {
    switch(view) {
        case 'overview':
            loadOverviewData();
            break;
        case 'trading':
            loadTradingData();
            break;
        case 'agents':
            loadAgentsData();
            break;
        case 'predictions':
            loadPredictionsData();
            break;
        case 'risk':
            loadRiskData();
            break;
        case 'api':
            loadApiData();
            break;
        case 'logs':
            loadLogsData();
            break;
    }
}

// Load initial data
function loadInitialData() {
    loadOverviewData();
    loadTradingData();
    loadAgentsData();
    loadPredictionsData();
    loadRiskData();
    loadApiData();
    loadLogsData();
}

// Load overview data
function loadOverviewData() {
    populateWatchlist();
    updatePortfolioChart();
    loadRecentActivity();
}

// Load trading data
function loadTradingData() {
    populatePositions();
}

// Load agents data
function loadAgentsData() {
    updateAgentPerformanceChart();
}

// Load predictions data
function loadPredictionsData() {
    populatePinnedMarkets();
}

// Load risk data
function loadRiskData() {
    populateRiskAlerts();
}

// Load API data
function loadApiData() {
    populateApiStatus();
}

// Load logs data
function loadLogsData() {
    populateLogs();
}

// Populate watchlist table
function populateWatchlist() {
    const tbody = document.getElementById('watchlist-tbody');
    if (!tbody) return;

    tbody.innerHTML = '';
    
    mockData.watchlist.forEach(item => {
        const changeClass = item.change >= 0 ? 'text-success' : 'text-danger';
        const changePrefix = item.change >= 0 ? '+' : '';
        
        const row = document.createElement('tr');
        row.innerHTML = `
            <td><strong>${item.symbol}</strong></td>
            <td>$${item.price.toLocaleString()}</td>
            <td class="${changeClass}">${changePrefix}${item.change}%</td>
            <td>${item.volume}</td>
        `;
        tbody.appendChild(row);
    });
}

// Populate positions table
function populatePositions() {
    const tbody = document.getElementById('positions-tbody');
    if (!tbody) return;

    tbody.innerHTML = '';
    
    mockData.positions.forEach(position => {
        const sideClass = position.side === 'LONG' ? 'text-success' : 'text-danger';
        const pnlClass = position.pnl.startsWith('+') ? 'text-success' : 'text-danger';
        
        const row = document.createElement('tr');
        row.innerHTML = `
            <td><strong>${position.symbol}</strong></td>
            <td class="${sideClass}">${position.side}</td>
            <td>${position.size}</td>
            <td>$${position.entry.toLocaleString()}</td>
            <td>$${position.current.toLocaleString()}</td>
            <td class="${pnlClass}">${position.pnl}</td>
            <td>
                <button class="btn btn-secondary btn-sm">Close</button>
            </td>
        `;
        tbody.appendChild(row);
    });
}

// Populate API status table
function populateApiStatus() {
    const tbody = document.getElementById('api-status-tbody');
    if (!tbody) return;

    tbody.innerHTML = '';
    
    mockData.apiStatus.forEach(api => {
        const statusClass = api.status === 'online' ? 'text-success' : 
                          api.status === 'degraded' ? 'text-warning' : 'text-danger';
        const statusDot = api.status === 'online' ? 'online' : 
                         api.status === 'degraded' ? 'degraded' : 'offline';
        
        const row = document.createElement('tr');
        row.innerHTML = `
            <td><strong>${api.name}</strong></td>
            <td>${api.category}</td>
            <td>
                <span class="status-indicator">
                    <span class="status-dot ${statusDot}"></span>
                    ${api.status.toUpperCase()}
                </span>
            </td>
            <td>${api.responseTime}ms</td>
            <td class="${api.errorRate > 1 ? 'text-danger' : 'text-success'}">${api.errorRate}%</td>
        `;
        tbody.appendChild(row);
    });
}

// Populate risk alerts table
function populateRiskAlerts() {
    const tbody = document.getElementById('risk-alerts-tbody');
    if (!tbody) return;

    tbody.innerHTML = '';
    
    mockData.riskAlerts.forEach(alert => {
        const severityClass = alert.severity === 'high' ? 'text-danger' : 
                             alert.severity === 'medium' ? 'text-warning' : 'text-success';
        const statusClass = alert.status === 'active' ? 'text-danger' : 
                           alert.status === 'acknowledged' ? 'text-warning' : 'text-success';
        
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${alert.time}</td>
            <td class="${severityClass}">${alert.severity.toUpperCase()}</td>
            <td>${alert.type}</td>
            <td>${alert.description}</td>
            <td class="${statusClass}">${alert.status.toUpperCase()}</td>
        `;
        tbody.appendChild(row);
    });
}

// Populate pinned markets
function populatePinnedMarkets() {
    const container = document.getElementById('pinned-markets');
    if (!container) return;

    container.innerHTML = '';
    
    mockData.pinnedMarkets.forEach(market => {
        const platformClass = market.platform === 'Polymarket' ? 'text-blue-400' : 'text-purple-400';
        
        const marketCard = document.createElement('div');
        marketCard.className = 'metric-card';
        marketCard.innerHTML = `
            <div class="flex justify-between items-center mb-2">
                <span class="text-xs ${platformClass}">${market.platform}</span>
                <button class="icon-button" title="Pin market">
                    <i data-lucide="pin"></i>
                </button>
            </div>
            <div class="text-sm font-medium mb-2">${market.title}</div>
            <div class="mb-2">
                <div class="flex justify-between text-xs mb-1">
                    <span class="text-success">Yes: ${market.yesProb}%</span>
                    <span class="text-danger">No: ${market.noProb}%</span>
                </div>
                <div class="w-full bg-gray-700 rounded-full h-2">
                    <div class="bg-green-500 h-2 rounded-full" style="width: ${market.yesProb}%"></div>
                </div>
            </div>
            <div class="text-xs text-muted">Volume: ${market.volume}</div>
        `;
        container.appendChild(marketCard);
    });

    // Re-initialize icons for new elements
    initializeLucideIcons();
}

// Load recent activity
function loadRecentActivity() {
    const container = document.getElementById('recent-activity');
    if (!container) return;

    const activities = [
        { time: '2m ago', action: 'BUY BTC/USD', size: '0.1', price: '$43,256' },
        { time: '5m ago', action: 'SELL ETH/USD', size: '2.5', price: '$2,245' },
        { time: '12m ago', action: 'BUY NVDA', size: '50', price: '$485.23' },
        { time: '18m ago', action: 'SELL AAPL', size: '25', price: '$178.95' }
    ];

    container.innerHTML = '';
    
    activities.forEach(activity => {
        const activityEl = document.createElement('div');
        activityEl.className = 'flex justify-between items-center py-2 border-b border-gray-700';
        activityEl.innerHTML = `
            <div>
                <div class="font-medium text-sm">${activity.action}</div>
                <div class="text-xs text-muted">${activity.size} @ ${activity.price}</div>
            </div>
            <div class="text-xs text-muted">${activity.time}</div>
        `;
        container.appendChild(activityEl);
    });
}

// Load logs
function loadLogs() {
    const container = document.getElementById('logs-container');
    if (!container) return;

    const logs = [
        { time: '13:45:23', level: 'INFO', message: 'Trend agent executed BUY order for BTC/USD' },
        { time: '13:44:12', level: 'WARNING', message: 'API latency spike detected for Coinbase' },
        { time: '13:43:01', level: 'INFO', message: 'Portfolio P&L updated: +$12,847.32' },
        { time: '13:42:55', level: 'ERROR', message: 'Failed to fetch data from Nansen API' },
        { time: '13:41:33', level: 'INFO', message: 'Risk monitor: All systems within limits' }
    ];

    container.innerHTML = '';
    
    logs.forEach(log => {
        const levelClass = log.level === 'ERROR' ? 'text-danger' : 
                         log.level === 'WARNING' ? 'text-warning' : 'text-success';
        
        const logEl = document.createElement('div');
        logEl.className = 'flex items-start gap-3 py-2 border-b border-gray-700 font-mono text-sm';
        logEl.innerHTML = `
            <span class="text-muted">${log.time}</span>
            <span class="${levelClass}">${log.level}</span>
            <span>${log.message}</span>
        `;
        container.appendChild(logEl);
    });
}

// Initialize charts
function initializeCharts() {
    initializePortfolioChart();
    initializeAgentPerformanceChart();
}

// Initialize portfolio chart
function initializePortfolioChart() {
    const ctx = document.getElementById('portfolio-chart');
    if (!ctx) return;

    charts.portfolio = new Chart(ctx.getContext('2d'), {
        type: 'line',
        data: {
            labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
            datasets: [{
                label: 'Portfolio Value',
                data: [545000, 548000, 542000, 551000, 558000, 562000, 562847],
                borderColor: '#10b981',
                backgroundColor: 'rgba(16, 185, 129, 0.1)',
                borderWidth: 2,
                tension: 0.4,
                fill: true
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: {
                    grid: { color: '#2a2a2a' },
                    ticks: { color: '#a0a0a0' }
                },
                x: {
                    grid: { color: '#2a2a2a' },
                    ticks: { color: '#a0a0a0' }
                }
            }
        }
    });
}

// Initialize agent performance chart
function initializeAgentPerformanceChart() {
    const ctx = document.getElementById('agent-performance-chart');
    if (!ctx) return;

    charts.agentPerformance = new Chart(ctx.getContext('2d'), {
        type: 'bar',
        data: {
            labels: ['Trend', 'Arbitrage', 'Risk', 'Skeptic', 'Synthesizer'],
            datasets: [{
                label: 'P&L Contribution',
                data: [2340, 5670, -890, 1230, 3450],
                backgroundColor: [
                    'rgba(16, 185, 129, 0.7)',
                    'rgba(16, 185, 129, 0.7)',
                    'rgba(239, 68, 68, 0.7)',
                    'rgba(16, 185, 129, 0.7)',
                    'rgba(16, 185, 129, 0.7)'
                ],
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: {
                    grid: { color: '#2a2a2a' },
                    ticks: { color: '#a0a0a0' }
                },
                x: {
                    grid: { color: '#2a2a2a' },
                    ticks: { color: '#a0a0a0' }
                }
            }
        }
    });
}

// Update portfolio chart
function updatePortfolioChart() {
    if (charts.portfolio) {
        // Simulate real-time data update
        const newData = charts.portfolio.data.datasets[0].data.map(val => 
            val + (Math.random() - 0.5) * 1000
        );
        charts.portfolio.data.datasets[0].data = newData;
        charts.portfolio.update('none');
    }
}

// Update agent performance chart
function updateAgentPerformanceChart() {
    if (charts.agentPerformance) {
        // Simulate real-time data update
        const newData = charts.agentPerformance.data.datasets[0].data.map(val => 
            val + (Math.random() - 0.5) * 100
        );
        charts.agentPerformance.data.datasets[0].data = newData;
        charts.agentPerformance.update('none');
    }
}

// Start real-time updates
function startRealTimeUpdates() {
    // Update data every 5 seconds
    updateIntervals.data = setInterval(() => {
        updateRealTimeData();
    }, 5000);

    // Update charts every 3 seconds
    updateIntervals.charts = setInterval(() => {
        updatePortfolioChart();
        if (currentView === 'agents') {
            updateAgentPerformanceChart();
        }
    }, 3000);

    // Update time every second
    updateIntervals.time = setInterval(() => {
        updateCurrentTime();
    }, 1000);
}

// Update real-time data
function updateRealTimeData() {
    // Simulate price updates
    mockData.watchlist.forEach(item => {
        item.price *= (1 + (Math.random() - 0.5) * 0.001);
        item.change += (Math.random() - 0.5) * 0.1;
    });

    // Update current view data
    loadViewData(currentView);
}

// Update current time display
function updateCurrentTime() {
    // Update any time displays if needed
}

// Toggle mobile menu
function toggleMobileMenu() {
    const sidebar = document.getElementById('sidebar');
    if (sidebar) {
        mobileMenuOpen = !mobileMenuOpen;
        if (mobileMenuOpen) {
            sidebar.classList.add('open');
        } else {
            sidebar.classList.remove('open');
        }
    }
}

// Close mobile menu
function closeMobileMenu() {
    const sidebar = document.getElementById('sidebar');
    if (sidebar && mobileMenuOpen) {
        sidebar.classList.remove('open');
        mobileMenuOpen = false;
    }
}

// Toggle theme
function toggleTheme() {
    const html = document.documentElement;
    const currentTheme = html.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    
    html.setAttribute('data-theme', newTheme);
    
    // Update theme icon
    const themeIcon = document.querySelector('#theme-toggle i');
    if (themeIcon) {
        themeIcon.setAttribute('data-lucide', newTheme === 'dark' ? 'moon' : 'sun');
        initializeLucideIcons();
    }
    
    // Save preference
    localStorage.setItem('theme', newTheme);
}

// Handle search
function handleSearch(e) {
    const query = e.target.value.toLowerCase();
    
    // Implement search functionality
    console.log('Search query:', query);
}

// API functions (replace with real API calls)
async function fetchPortfolioSummary() {
    try {
        const response = await fetch('/api/v1/portfolio/summary');
        return await response.json();
    } catch (error) {
        console.error('Failed to fetch portfolio summary:', error);
        return null;
    }
}

async function fetchPositions() {
    try {
        const response = await fetch('/api/v1/positions');
        return await response.json();
    } catch (error) {
        console.error('Failed to fetch positions:', error);
        return [];
    }
}

async function fetchApiStatus() {
    try {
        const response = await fetch('/api/v1/api-status');
        return await response.json();
    } catch (error) {
        console.error('Failed to fetch API status:', error);
        return null;
    }
}

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    // Clear all intervals
    Object.values(updateIntervals).forEach(interval => {
        clearInterval(interval);
    });
});

// Export functions for external use if needed
window.MeridDashboard = {
    switchView,
    toggleTheme,
    fetchPortfolioSummary,
    fetchPositions,
    fetchApiStatus
};
