// MERID Production Dashboard JavaScript

// Global state
let charts = {};
let currentSection = 'dashboard';
let miningInterval = null;
let refreshInterval = null;
let latestBlock = null;

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
    initializeCharts();
    loadDashboardData();
    startAutoRefresh();
    setupEventListeners();
});

// Section Navigation
function showSection(sectionName) {
    // Hide all sections
    document.querySelectorAll('.content-section').forEach(section => {
        section.classList.remove('active');
    });
    
    // Show selected section
    const section = document.getElementById(`section-${sectionName}`);
    if (section) {
        section.classList.add('active');
        currentSection = sectionName;
    }
    
    // Update sidebar active state
    document.querySelectorAll('.sidebar-link').forEach(link => {
        link.classList.remove('active');
    });
    event.target.classList.add('active');
    
    // Load section-specific data
    loadSectionData(sectionName);
}

// Initialize Charts
function initializeCharts() {
    // Value Trend Chart
    const valueTrendCtx = document.getElementById('value-trend-chart');
    if (valueTrendCtx) {
        charts.valueTrend = new Chart(valueTrendCtx.getContext('2d'), {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'Block Score',
                    data: [],
                    borderColor: 'rgba(16, 185, 129, 1)',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100,
                        grid: { color: 'rgba(255, 255, 255, 0.1)' },
                        ticks: { color: '#e0e0e0' }
                    },
                    x: {
                        grid: { color: 'rgba(255, 255, 255, 0.1)' },
                        ticks: { color: '#e0e0e0' }
                    }
                },
                plugins: {
                    legend: { labels: { color: '#e0e0e0' } }
                }
            }
        });
    }
    
    // Agent Performance Chart
    const agentPerfCtx = document.getElementById('agent-performance-chart');
    if (agentPerfCtx) {
        charts.agentPerformance = new Chart(agentPerfCtx.getContext('2d'), {
            type: 'bar',
            data: {
                labels: [],
                datasets: [{
                    label: 'Accuracy %',
                    data: [],
                    backgroundColor: 'rgba(16, 185, 129, 0.6)',
                    borderColor: 'rgba(16, 185, 129, 1)',
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100,
                        grid: { color: 'rgba(255, 255, 255, 0.1)' },
                        ticks: { color: '#e0e0e0' }
                    },
                    x: {
                        grid: { color: 'rgba(255, 255, 255, 0.1)' },
                        ticks: { color: '#e0e0e0' }
                    }
                },
                plugins: {
                    legend: { labels: { color: '#e0e0e0' } }
                }
            }
        });
    }
}

// Load Dashboard Data
async function loadDashboardData() {
    try {
        // Load mining status
        const statusResponse = await fetch('/api/v1/mining/status');
        const statusData = await statusResponse.json();
        
        if (statusData.latest_block) {
            updateLatestBlock(statusData.latest_block, statusData.latest_value_metrics);
            updateKPIs(statusData);
        }
        
        // Load agent performance
        const agentResponse = await fetch('/api/v1/reflection/summary');
        const agentData = await agentResponse.json();
        updateAgentPerformance(agentData);
        
    } catch (error) {
        console.error('Failed to load dashboard data:', error);
    }
}

// Update KPIs
function updateKPIs(data) {
    if (data.latest_block) {
        const block = data.latest_block;
        const metrics = data.latest_value_metrics;
        
        document.getElementById('kpi-blocks').textContent = block.index + 1;
        document.getElementById('kpi-agents').textContent = block.consensus.agent_participation || 8;
        
        if (metrics) {
            document.getElementById('kpi-score').textContent = metrics.overall_score.toFixed(1);
            const gradeElement = document.querySelector('#kpi-score + .kpi-change');
            if (gradeElement) {
                gradeElement.textContent = `Grade: ${metrics.value_grade}`;
            }
        }
        
        if (block.consensus) {
            const consensusPercent = (block.consensus.confidence * 100).toFixed(1);
            document.getElementById('kpi-consensus').textContent = `${consensusPercent}%`;
        }
    }
}

// Update Latest Block Display
function updateLatestBlock(block, metrics) {
    latestBlock = block;
    const container = document.getElementById('latest-block-showcase');
    if (!container) return;
    
    const gradeClass = metrics ? `grade-${metrics.value_grade.toLowerCase()}` : '';
    
    container.innerHTML = `
        <div class="block-showcase fade-in">
            <div class="block-header">
                <div>
                    <div class="block-index">Block #${block.index}</div>
                    <div class="block-timestamp">
                        ${new Date(block.timestamp * 1000).toLocaleString()}
                    </div>
                </div>
                ${metrics ? `<div class="block-grade ${gradeClass}">${metrics.value_grade}</div>` : ''}
            </div>
            
            <div class="block-metrics">
                <div class="metric-item">
                    <div class="metric-label">Overall Score</div>
                    <div class="metric-value">${metrics ? metrics.overall_score : 0}/100</div>
                </div>
                <div class="metric-item">
                    <div class="metric-label">Consensus</div>
                    <div class="metric-value">${(block.consensus.confidence * 100).toFixed(1)}%</div>
                </div>
                <div class="metric-item">
                    <div class="metric-label">Agents</div>
                    <div class="metric-value">${block.consensus.agent_participation}</div>
                </div>
                <div class="metric-item">
                    <div class="metric-label">Hash</div>
                    <div class="metric-value metric-value-small">${block.hash.substring(0, 12)}...</div>
                </div>
            </div>
            
            <div class="block-intelligence-section">
                <h3 class="intelligence-title">Intelligence Gathered</h3>
                <div class="grid-3">
                    <div class="metric-item">
                        <div class="metric-label">News Items</div>
                        <div class="metric-value">${block.intelligence.news_items}</div>
                    </div>
                    <div class="metric-item">
                        <div class="metric-label">Whale Signals</div>
                        <div class="metric-value">${block.intelligence.whale_signals}</div>
                    </div>
                    <div class="metric-item">
                        <div class="metric-label">Arbitrage Ops</div>
                        <div class="metric-value">${block.intelligence.arbitrage_opportunities}</div>
                    </div>
                </div>
            </div>
        </div>
    `;
}

// Update Agent Performance
function updateAgentPerformance(data) {
    if (!data.agents || data.agents.length === 0) return;
    
    const labels = data.agents.map(a => a.agent_id.split('-')[0]);
    const accuracies = data.agents.map(a => a.accuracy);
    
    if (charts.agentPerformance) {
        charts.agentPerformance.data.labels = labels;
        charts.agentPerformance.data.datasets[0].data = accuracies;
        charts.agentPerformance.update();
    }
}

// Mine Block
async function mineBlock() {
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = '⛏️ Mining...';
    
    const statusBadge = document.getElementById('mining-status-text');
    statusBadge.textContent = 'MINING';
    statusBadge.className = 'status-badge status-mining';
    
    try {
        const response = await fetch('/api/v1/mining/mine', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        
        const data = await response.json();
        
        if (data.status === 'mining_started') {
            startMiningPoll();
        }
    } catch (error) {
        console.error('Mining error:', error);
        statusBadge.textContent = 'ERROR';
        statusBadge.className = 'status-badge status-idle';
    } finally {
        btn.disabled = false;
        btn.textContent = '⛏️ Start Mining';
    }
}

// Poll Mining Status
function startMiningPoll() {
    if (miningInterval) clearInterval(miningInterval);
    
    let progress = 0;
    const progressFill = document.getElementById('mining-progress-fill');
    const progressText = document.getElementById('mining-progress-text');
    
    miningInterval = setInterval(async () => {
        try {
            const response = await fetch('/api/v1/mining/status');
            const data = await response.json();
            
            if (!data.mining_in_progress && data.latest_block) {
                clearInterval(miningInterval);
                
                const statusBadge = document.getElementById('mining-status-text');
                statusBadge.textContent = 'COMPLETE';
                statusBadge.className = 'status-badge status-complete';
                
                progressFill.style.width = '100%';
                progressText.textContent = '100%';
                
                updateLatestBlock(data.latest_block, data.latest_value_metrics);
                updateKPIs(data);
                
                setTimeout(() => {
                    statusBadge.textContent = 'IDLE';
                    statusBadge.className = 'status-badge status-idle';
                    progressFill.style.width = '0%';
                    progressText.textContent = '0%';
                }, 3000);
            } else if (data.mining_in_progress) {
                progress = Math.min(progress + 10, 90);
                progressFill.style.width = progress + '%';
                progressText.textContent = progress + '%';
            }
        } catch (error) {
            console.error('Status poll error:', error);
        }
    }, 1000);
}

// Update Mining Config
async function updateMiningConfig() {
    const difficulty = document.getElementById('difficulty-input').value;
    const confidence = document.getElementById('confidence-input').value;
    
    try {
        const response = await fetch(`/api/v1/mining/difficulty?difficulty=${difficulty}&min_confidence=${confidence}`, {
            method: 'POST'
        });
        
        if (response.ok) {
            alert('Mining configuration updated successfully!');
        }
    } catch (error) {
        console.error('Config update error:', error);
        alert('Failed to update configuration');
    }
}

// Refresh Dashboard
function refreshDashboard() {
    loadDashboardData();
}

// Refresh Agents
async function refreshAgents() {
    try {
        const response = await fetch('/api/v1/reflection/summary');
        const data = await response.json();
        
        const grid = document.getElementById('agents-grid');
        if (!grid) return;
        
        grid.innerHTML = '';
        
        data.agents.forEach(agent => {
            const card = document.createElement('div');
            card.className = 'agent-card';
            card.innerHTML = `
                <div class="agent-header">
                    <span class="agent-name">${agent.agent_id}</span>
                    <span class="status-indicator status-active"></span>
                </div>
                <div class="agent-stats">
                    <div class="agent-stat">
                        <div class="agent-stat-label">Accuracy</div>
                        <div class="agent-stat-value">${agent.accuracy.toFixed(1)}%</div>
                    </div>
                    <div class="agent-stat">
                        <div class="agent-stat-label">Decisions</div>
                        <div class="agent-stat-value">${agent.total_decisions}</div>
                    </div>
                    <div class="agent-stat">
                        <div class="agent-stat-label">Reality Gap</div>
                        <div class="agent-stat-value">${agent.avg_reality_gap.toFixed(2)}%</div>
                    </div>
                    <div class="agent-stat">
                        <div class="agent-stat-label">Learnings</div>
                        <div class="agent-stat-value">${agent.recent_learnings}</div>
                    </div>
                </div>
            `;
            grid.appendChild(card);
        });
    } catch (error) {
        console.error('Failed to refresh agents:', error);
    }
}

// Load Section Data
function loadSectionData(sectionName) {
    switch(sectionName) {
        case 'agents':
            refreshAgents();
            break;
        case 'blocks':
            loadBlocksExplorer();
            break;
        case 'dashboard':
            loadDashboardData();
            break;
    }
}

// Load Blocks Explorer
async function loadBlocksExplorer() {
    const grid = document.getElementById('blocks-list');
    if (!grid) return;
    
    try {
        const response = await fetch('/api/v1/mining/blocks?limit=20');
        const data = await response.json();
        
        if (data.blocks && data.blocks.length > 0) {
            grid.innerHTML = data.blocks.map(block => `
                <div class="block-item">
                    <div class="block-index">#${block.block_index || block.index || 0}</div>
                    <div class="block-hash">${(block.hash || '').substring(0, 12)}...</div>
                    <div class="block-score">${(block.score || 0).toFixed(1)}</div>
                    <div class="block-time">${formatTimestamp(block.timestamp || Date.now()/1000)}</div>
                </div>
            `).join('');
        } else {
            grid.innerHTML = '<div class="empty-state">No blocks mined yet</div>';
        }
    } catch (error) {
        console.error('Failed to load blocks:', error);
        grid.innerHTML = '<div class="empty-state">Failed to load blocks</div>';
    }
}

// Toggle Settings
function toggleSettings() {
    const panel = document.getElementById('settings-panel');
    panel.classList.toggle('active');
}

// Toggle Notifications
function toggleNotifications() {
    const panel = document.getElementById('notifications-panel');
    if (panel) {
        panel.classList.toggle('active');
        if (panel.classList.contains('active')) {
            loadNotifications();
        }
    }
}

// Load Notifications
async function loadNotifications() {
    try {
        const response = await fetch('/api/v1/notifications/recent?limit=10');
        const data = await response.json();
        
        const list = document.getElementById('notifications-list');
        if (list && data.notifications) {
            list.innerHTML = data.notifications.length > 0 
                ? data.notifications.map(n => `
                    <div class="notification-item ${n.read ? '' : 'unread'}">
                        <span class="notification-icon">${n.type === 'alert' ? '⚠️' : n.type === 'success' ? '✅' : 'ℹ️'}</span>
                        <span class="notification-message">${n.message || n.title}</span>
                        <span class="notification-time">${formatRelativeTime(n.timestamp)}</span>
                    </div>
                `).join('')
                : '<div class="empty-state">No notifications</div>';
        }
    } catch (e) {
        console.debug('Notifications not available');
    }
}

// Format relative time
function formatRelativeTime(timestamp) {
    const ts = timestamp < 1e12 ? timestamp * 1000 : timestamp;
    const diff = Date.now() - ts;
    if (diff < 60000) return 'just now';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    return `${Math.floor(diff / 86400000)}d ago`;
}

// Toggle User Menu
function toggleUserMenu() {
    const menu = document.getElementById('user-menu');
    if (menu) {
        menu.classList.toggle('active');
    }
}

// Auto Refresh
function startAutoRefresh() {
    const autoRefreshCheckbox = document.getElementById('auto-refresh');
    if (autoRefreshCheckbox && autoRefreshCheckbox.checked) {
        refreshInterval = setInterval(() => {
            if (currentSection === 'dashboard') {
                loadDashboardData();
            }
        }, 30000); // 30 seconds
    }
}

// Setup Event Listeners
function setupEventListeners() {
    // Global search
    const searchBar = document.getElementById('global-search');
    if (searchBar) {
        searchBar.addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase();
            // Implement search logic
            console.log('Searching for:', query);
        });
    }
}

// Utility Functions
function formatTimestamp(timestamp) {
    return new Date(timestamp * 1000).toLocaleString();
}

function formatHash(hash) {
    return hash.substring(0, 12) + '...';
}
