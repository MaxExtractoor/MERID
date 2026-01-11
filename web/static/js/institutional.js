/**
 * MERID Institutional Control Center - JavaScript
 * Bloomberg Terminal-inspired real-time dashboard
 */

// ============================================
// GLOBAL STATE
// ============================================

const state = {
    currentSection: 'systems',
    refreshInterval: null,
    charts: {},
    isLocked: false,
};

// ============================================
// INITIALIZATION
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initCharts();
    startClock();
    refreshAll();
    
    // Auto-refresh every 5 seconds
    state.refreshInterval = setInterval(refreshAll, 5000);
});

// ============================================
// NAVIGATION
// ============================================

function initNavigation() {
    const links = document.querySelectorAll('.sidebar-link');
    
    links.forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const section = link.dataset.section;
            navigateToSection(section);
        });
    });
}

function navigateToSection(sectionId) {
    // Update sidebar
    document.querySelectorAll('.sidebar-link').forEach(link => {
        link.classList.remove('active');
        if (link.dataset.section === sectionId) {
            link.classList.add('active');
        }
    });
    
    // Update content
    document.querySelectorAll('.content-section').forEach(section => {
        section.classList.remove('active');
    });
    
    const targetSection = document.getElementById(sectionId);
    if (targetSection) {
        targetSection.classList.add('active');
    }
    
    state.currentSection = sectionId;
}

// ============================================
// CLOCK
// ============================================

function startClock() {
    updateClock();
    setInterval(updateClock, 1000);
}

function updateClock() {
    const now = new Date();
    const utc = now.toISOString().substr(11, 8);
    document.getElementById('utc-time').textContent = utc;
}

// ============================================
// DATA FETCHING
// ============================================

async function fetchAPI(endpoint) {
    try {
        const response = await fetch(`/api/v1/institutional${endpoint}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error(`API Error (${endpoint}):`, error);
        return null;
    }
}

async function refreshAll() {
    await Promise.all([
        refreshSystemsStatus(),
        refreshIntents(),
        refreshVault(),
        refreshShadow(),
        refreshRisk(),
        refreshLockdown(),
    ]);
}

// ============================================
// SYSTEMS STATUS
// ============================================

async function refreshSystemsStatus() {
    const data = await fetchAPI('/systems/status');
    if (!data) return;
    
    // Update global status
    const globalStatus = document.getElementById('global-status');
    const statusDot = globalStatus.querySelector('.status-dot');
    const statusText = globalStatus.querySelector('.status-text');
    
    if (data.global_status === 'locked') {
        statusDot.className = 'status-dot status-danger';
        statusText.textContent = 'LOCKED';
        state.isLocked = true;
    } else {
        statusDot.className = 'status-dot status-operational';
        statusText.textContent = 'OPERATIONAL';
        state.isLocked = false;
    }
    
    // Update lockdown button
    const lockdownBtn = document.getElementById('lockdown-btn');
    if (state.isLocked) {
        lockdownBtn.innerHTML = '<span class="btn-icon">&#10003;</span> RELEASE';
        lockdownBtn.classList.remove('nav-btn-warning');
        lockdownBtn.classList.add('nav-btn');
    } else {
        lockdownBtn.innerHTML = '<span class="btn-icon">&#9888;</span> LOCKDOWN';
        lockdownBtn.classList.add('nav-btn-warning');
    }
    
    // Update individual systems
    data.systems.forEach(system => {
        const card = document.querySelector(`.system-card[data-system="${system.system_id}"]`);
        if (!card) return;
        
        const healthEl = card.querySelector(`#${system.system_id.replace('-', '')}-health, [id$="-health"]`);
        const violationsEl = card.querySelector(`[id$="-violations"]`);
        const statusIndicator = card.querySelector('.status-indicator');
        
        // Update health
        const healthPct = Math.round(system.health_score * 100);
        if (healthEl) {
            healthEl.textContent = `${healthPct}%`;
        }
        
        // Update violations
        if (violationsEl) {
            violationsEl.textContent = system.violations_24h;
            if (system.violations_24h > 0) {
                violationsEl.style.color = 'var(--accent-danger)';
            }
        }
        
        // Update status indicator
        if (statusIndicator) {
            if (system.status === 'locked') {
                statusIndicator.className = 'status-indicator offline';
            } else if (system.health_score < 0.8) {
                statusIndicator.className = 'status-indicator degraded';
            } else {
                statusIndicator.className = 'status-indicator operational';
            }
        }
    });
}

// ============================================
// INTENTS
// ============================================

async function refreshIntents() {
    const data = await fetchAPI('/intents');
    if (!data) return;
    
    const intents = data.intents || [];
    
    // Update stats
    document.getElementById('pending-intents').textContent = intents.length;
    document.getElementById('awaiting-approval').textContent = 
        intents.filter(i => i.status === 'awaiting_approval').length;
    document.getElementById('simulating-intents').textContent = 
        intents.filter(i => i.status === 'simulating').length;
    
    // Update list
    const listEl = document.getElementById('intent-list');
    if (intents.length === 0) {
        listEl.innerHTML = '<div class="empty-state">No pending intents</div>';
        return;
    }
    
    listEl.innerHTML = intents.map(intent => `
        <div class="intent-item">
            <div class="intent-info">
                <div class="intent-type">${intent.intent_type}</div>
                <div class="intent-source">${intent.source_system}</div>
            </div>
            <div class="intent-status">
                <span class="status-badge ${intent.status}">${intent.status}</span>
            </div>
            <div class="intent-actions">
                ${intent.status === 'awaiting_approval' ? `
                    <button class="btn-sm btn-approve" onclick="approveIntent('${intent.intent_id}')">Approve</button>
                    <button class="btn-sm btn-reject" onclick="rejectIntent('${intent.intent_id}')">Reject</button>
                ` : ''}
            </div>
        </div>
    `).join('');
}

async function approveIntent(intentId) {
    await fetchAPI('/intents/action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            intent_id: intentId,
            approver_id: 'dashboard-user',
            action: 'approve'
        })
    });
    refreshIntents();
}

async function rejectIntent(intentId) {
    await fetchAPI('/intents/action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            intent_id: intentId,
            approver_id: 'dashboard-user',
            action: 'reject',
            reason: 'Rejected via dashboard'
        })
    });
    refreshIntents();
}

// ============================================
// VAULT GOVERNANCE
// ============================================

async function refreshVault() {
    const data = await fetchAPI('/vault/status');
    if (!data) return;
    
    const vault = data.vault || {};
    const firewall = data.firewall || {};
    const keyHolders = data.key_holders || [];
    
    // Update vault status
    document.getElementById('vault-status').textContent = vault.is_frozen ? 'FROZEN' : 'ACTIVE';
    document.getElementById('active-keys').textContent = `${vault.active_key_count || 0}/${vault.key_holder_count || 0}`;
    document.getElementById('pending-ops').textContent = vault.pending_operations || 0;
    
    // Update daily limits
    const dailyOutflow = firewall.daily_outflow || 0;
    const dailyLimit = firewall.daily_limit || 50000;
    document.getElementById('daily-outflow').textContent = `$${dailyOutflow.toLocaleString()}`;
    document.getElementById('daily-limit').textContent = `$${dailyLimit.toLocaleString()}`;
    
    const outflowPct = (dailyOutflow / dailyLimit) * 100;
    document.getElementById('outflow-progress').style.width = `${outflowPct}%`;
    
    // Update key holders
    const keyHoldersEl = document.getElementById('key-holders');
    keyHoldersEl.innerHTML = keyHolders.map(holder => `
        <div class="key-holder-card">
            <div class="key-holder-id">${holder.key_id}</div>
            <div class="key-holder-role">${holder.role}</div>
            <div class="key-holder-weight">Weight: ${holder.weight}</div>
        </div>
    `).join('');
    
    // Fetch and update operations
    const opsData = await fetchAPI('/vault/operations');
    if (opsData) {
        const operations = opsData.operations || [];
        const opsEl = document.getElementById('vault-operations');
        
        if (operations.length === 0) {
            opsEl.innerHTML = '<div class="empty-state">No pending operations</div>';
        } else {
            opsEl.innerHTML = operations.map(op => `
                <div class="operation-item">
                    <div class="op-info">
                        <div class="op-type">${op.operation}</div>
                        <div class="op-proposer">Proposed by: ${op.proposer}</div>
                        ${op.amount_usd ? `<div class="op-amount">$${op.amount_usd.toLocaleString()}</div>` : ''}
                    </div>
                    <div class="op-signatures">
                        <span class="sig-count">${op.signatures}/${op.required_signatures}</span>
                        <span class="sig-label">signatures</span>
                    </div>
                    <div class="op-status">
                        <span class="status-badge ${op.status}">${op.status}</span>
                    </div>
                </div>
            `).join('');
        }
    }
}

// ============================================
// SHADOW MERID
// ============================================

async function refreshShadow() {
    const data = await fetchAPI('/shadow/status');
    if (!data || data.status === 'unavailable') {
        return;
    }
    
    const portfolio = data.portfolio || {};
    const performance = data.performance || {};
    const divergence = data.divergence || {};
    
    // Update shadow metrics
    document.getElementById('shadow-equity').textContent = `$${(portfolio.equity || 100000).toLocaleString()}`;
    
    const pnl = portfolio.total_pnl || 0;
    const pnlEl = document.getElementById('shadow-pnl');
    pnlEl.textContent = `${pnl >= 0 ? '+' : ''}$${pnl.toLocaleString()}`;
    pnlEl.className = `value ${pnl >= 0 ? 'positive' : 'negative'}`;
    
    document.getElementById('shadow-positions').textContent = portfolio.positions || 0;
    
    // Update shadow stats
    document.getElementById('shadow-trades').textContent = performance.total_trades || 0;
    document.getElementById('shadow-winrate').textContent = `${((performance.win_rate || 0) * 100).toFixed(1)}%`;
    document.getElementById('shadow-drawdown').textContent = `${((performance.max_drawdown || 0) * 100).toFixed(1)}%`;
    document.getElementById('shadow-divergences').textContent = divergence.divergent_executions || 0;
    
    // Update divergence
    const divergencePct = ((divergence.divergence_rate || 0) * 100).toFixed(1);
    document.getElementById('divergence-pct').textContent = `${divergencePct}%`;
    
    // Fetch enhanced divergence data
    const divData = await fetchAPI('/shadow/divergence');
    if (divData) {
        document.getElementById('divergence-pct').textContent = divData.current_score_pct || '0%';
        
        // Update guardian status
        const guardian = divData.guardian || {};
        const guardianStateEl = document.getElementById('guardian-state');
        if (guardianStateEl) {
            guardianStateEl.textContent = (guardian.state || 'idle').toUpperCase();
        }
        
        const guardianAlertsEl = document.getElementById('guardian-alerts');
        if (guardianAlertsEl) {
            guardianAlertsEl.textContent = guardian.consecutive_alerts || 0;
        }
    }
    
    // Fetch Aave status
    const aaveData = await fetchAPI('/treasury/aave/status');
    if (aaveData) {
        const status = aaveData.status || {};
        const aaveSuppliedEl = document.getElementById('aave-supplied');
        if (aaveSuppliedEl) {
            aaveSuppliedEl.textContent = `$${(status.total_supplied_usd || 0).toLocaleString()}`;
        }
        
        const aaveHealthEl = document.getElementById('aave-health');
        if (aaveHealthEl) {
            aaveHealthEl.textContent = (status.health_factor || 10).toFixed(1);
        }
    }
}

// ============================================
// RISK & COMPLIANCE
// ============================================

async function refreshRisk() {
    const data = await fetchAPI('/risk/summary');
    if (!data) return;
    
    // Update risk score
    const riskScore = (data.risk_score || 0) * 100;
    document.getElementById('risk-score').textContent = `${riskScore.toFixed(0)}%`;
    
    // Update risk arc
    const arc = document.getElementById('risk-arc');
    if (arc) {
        const dashOffset = 251.2 - (riskScore / 100 * 251.2);
        arc.style.strokeDashoffset = dashOffset;
    }
    
    // Update risk level badge
    const riskBadge = document.getElementById('risk-level');
    riskBadge.textContent = (data.risk_level || 'low').toUpperCase();
    riskBadge.className = `risk-badge risk-${data.risk_level || 'low'}`;
    
    // Update risk factors
    document.getElementById('lockdown-factor').textContent = data.lockdown_active ? 'Active' : 'Inactive';
    document.getElementById('lockdown-factor').className = `factor-value ${data.lockdown_active ? 'danger' : 'good'}`;
    
    document.getElementById('violations-factor').textContent = data.violations_24h || 0;
    document.getElementById('violations-factor').className = `factor-value ${data.violations_24h > 0 ? 'warning' : 'good'}`;
    
    const capitalUtil = data.capital_utilization || {};
    document.getElementById('capital-factor').textContent = `${(capitalUtil.utilization_pct || 0).toFixed(1)}%`;
    
    document.getElementById('compliance-factor').textContent = data.compliance_status === 'compliant' ? 'Compliant' : 'Violations';
    document.getElementById('compliance-factor').className = `factor-value ${data.compliance_status === 'compliant' ? 'good' : 'danger'}`;
    
    // Update violations chart
    updateViolationsChart(data.violations_by_type || {});
}

// ============================================
// LOCKDOWN
// ============================================

async function refreshLockdown() {
    const data = await fetchAPI('/lockdown/status');
    if (!data) return;
    
    const lockdown = data.lockdown || {};
    const circuits = data.circuits || {};
    
    // Update circuits grid
    const circuitsGrid = document.getElementById('circuits-grid');
    const circuitEntries = Object.entries(circuits);
    
    if (circuitEntries.length === 0) {
        circuitsGrid.innerHTML = '<div class="empty-state">No circuit breakers configured</div>';
    } else {
        circuitsGrid.innerHTML = circuitEntries.map(([name, circuit]) => `
            <div class="circuit-card">
                <div class="circuit-name">${name}</div>
                <div class="circuit-state ${circuit.state}">${circuit.state}</div>
                <div class="circuit-stats">
                    <span>Failures: ${circuit.failure_count || 0}</span>
                    <span>Calls: ${circuit.total_calls || 0}</span>
                </div>
            </div>
        `).join('');
    }
}

function toggleLockdown() {
    if (state.isLocked) {
        releaseLockdown();
    } else {
        document.getElementById('lockdown-modal').classList.add('active');
    }
}

function closeLockdownModal() {
    document.getElementById('lockdown-modal').classList.remove('active');
}

async function confirmLockdown() {
    const level = document.querySelector('input[name="lockdown-level"]:checked').value;
    const reason = document.getElementById('lockdown-reason').value || 'Manual lockdown via dashboard';
    
    try {
        const response = await fetch('/api/v1/institutional/lockdown', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'trigger',
                level: level,
                reason: reason,
                triggered_by: 'human:dashboard-user'
            })
        });
        
        if (response.ok) {
            closeLockdownModal();
            refreshAll();
        }
    } catch (error) {
        console.error('Lockdown error:', error);
    }
}

async function releaseLockdown() {
    if (!confirm('Are you sure you want to release the lockdown?')) {
        return;
    }
    
    try {
        const response = await fetch('/api/v1/institutional/lockdown', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'release',
                triggered_by: 'human:dashboard-user',
                reason: 'Manual release via dashboard'
            })
        });
        
        if (response.ok) {
            refreshAll();
        }
    } catch (error) {
        console.error('Release error:', error);
    }
}

// ============================================
// CHARTS
// ============================================

function initCharts() {
    // Violations Chart
    const violationsCtx = document.getElementById('violations-chart');
    if (violationsCtx) {
        state.charts.violations = new Chart(violationsCtx.getContext('2d'), {
            type: 'bar',
            data: {
                labels: [],
                datasets: [{
                    label: 'Violations',
                    data: [],
                    backgroundColor: 'rgba(239, 68, 68, 0.6)',
                    borderColor: 'rgba(239, 68, 68, 1)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { color: '#a0a0b0' }
                    },
                    x: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { color: '#a0a0b0' }
                    }
                },
                plugins: {
                    legend: { display: false }
                }
            }
        });
    }
    
    // Latency Chart
    const latencyCtx = document.getElementById('latency-chart');
    if (latencyCtx) {
        state.charts.latency = new Chart(latencyCtx.getContext('2d'), {
            type: 'line',
            data: {
                labels: Array.from({length: 20}, (_, i) => `${i * 5}s`),
                datasets: [{
                    label: 'Latency (ms)',
                    data: Array.from({length: 20}, () => Math.random() * 50 + 10),
                    borderColor: 'rgba(0, 212, 170, 1)',
                    backgroundColor: 'rgba(0, 212, 170, 0.1)',
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
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { color: '#a0a0b0' }
                    },
                    x: {
                        grid: { color: 'rgba(255, 255, 255, 0.05)' },
                        ticks: { color: '#a0a0b0' }
                    }
                },
                plugins: {
                    legend: { display: false }
                }
            }
        });
    }
}

function updateViolationsChart(violationsByType) {
    if (!state.charts.violations) return;
    
    const labels = Object.keys(violationsByType);
    const data = Object.values(violationsByType);
    
    state.charts.violations.data.labels = labels;
    state.charts.violations.data.datasets[0].data = data;
    state.charts.violations.update();
}

// ============================================
// UTILITY FUNCTIONS
// ============================================

function formatNumber(num) {
    if (num >= 1000000) {
        return (num / 1000000).toFixed(1) + 'M';
    }
    if (num >= 1000) {
        return (num / 1000).toFixed(1) + 'K';
    }
    return num.toString();
}

function formatTimestamp(ts) {
    if (!ts) return '--';
    return new Date(ts * 1000).toLocaleString();
}

function formatDuration(seconds) {
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
    return `${Math.floor(seconds / 86400)}d`;
}

// ============================================
// SHADOW GUARDIAN ACTIONS
// ============================================

async function triggerReplay() {
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = 'Running...';
    
    try {
        const response = await fetch('/api/v1/institutional/shadow/replay', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                blocks: 5,
                noise_pct: 0.05,
                runs: 3
            })
        });
        
        const data = await response.json();
        
        if (data.passed) {
            alert(`Replay completed successfully!\nResilience Score: ${(data.resilience_score * 100).toFixed(1)}%`);
        } else {
            alert(`Replay detected issues!\nResilience Score: ${(data.resilience_score * 100).toFixed(1)}%\nAnomalies: ${data.anomalies.length}`);
        }
    } catch (error) {
        console.error('Replay error:', error);
        alert('Failed to run replay');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Run Replay';
    }
}

async function runStressTest() {
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = 'Testing...';
    
    try {
        const response = await fetch('/api/v1/institutional/shadow/stress-test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                severity: 'medium',
                duration: 3.0
            })
        });
        
        const data = await response.json();
        const stats = data.detection_stats || {};
        
        alert(`Stress Test Complete!\nAttacks Run: ${data.attacks_run}\nDetection Rate: ${((stats.detection_rate || 0) * 100).toFixed(1)}%`);
        
        refreshShadow();
    } catch (error) {
        console.error('Stress test error:', error);
        alert('Failed to run stress test');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Stress Test';
    }
}

async function stashProfits() {
    const btn = event.target;
    btn.disabled = true;
    btn.textContent = 'Stashing...';
    
    try {
        const response = await fetch('/api/v1/institutional/treasury/stash-profits', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                profit_usd: 1000.0,
                allocation_ratio: 0.3
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            alert(`Profits stashed successfully!\nAmount: $${data.amount_stashed.toFixed(2)}\nHealth Factor: ${data.health_factor.toFixed(2)}`);
            refreshShadow();
        } else {
            alert(`Stash failed: ${data.reason || 'Unknown error'}`);
        }
    } catch (error) {
        console.error('Stash error:', error);
        alert('Failed to stash profits');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Stash Profits';
    }
}
