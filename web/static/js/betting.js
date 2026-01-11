// MERID Betting System

let userId = localStorage.getItem('merid_user_id') || (() => {
    const id = 'user_' + Date.now().toString(36) + '_' + crypto.randomUUID().slice(0, 8);
    localStorage.setItem('merid_user_id', id);
    return id;
})();
let selectedBlock = null;
let selectedPrediction = null;
let upcomingBlocks = [];

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    loadUserBalance();
    loadUpcomingBlocks();
    loadUserStats();
    loadLeaderboard();
    
    // Auto-refresh every 10 seconds
    setInterval(() => {
        loadUpcomingBlocks();
        loadUserBalance();
    }, 10000);
});

// Setup event listeners
function setupEventListeners() {
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
}

// Load user balance
async function loadUserBalance() {
    try {
        const response = await fetch(`/api/v1/betting/user/${userId}/balance`);
        const data = await response.json();
        
        document.getElementById('user-balance').textContent = `$${data.balance.toFixed(2)}`;
    } catch (error) {
        console.error('Failed to load balance:', error);
    }
}

// Load upcoming blocks
async function loadUpcomingBlocks() {
    try {
        const response = await fetch('/api/v1/betting/pools/active');
        const data = await response.json();
        
        // Use real API data
        if (data.pools && Array.isArray(data.pools)) {
            upcomingBlocks = data.pools.map(pool => ({
                block_index: pool.block_index || pool.id || 0,
                total_pool: pool.total_pool || pool.pool_size || 0,
                total_bets: pool.total_bets || pool.bet_count || 0,
                locked: pool.locked || pool.is_locked || false,
                settled: pool.settled || pool.is_settled || false,
                distribution: pool.distribution || {}
            }));
        } else if (Array.isArray(data)) {
            upcomingBlocks = data.map(pool => ({
                block_index: pool.block_index || pool.id || 0,
                total_pool: pool.total_pool || pool.pool_size || 0,
                total_bets: pool.total_bets || pool.bet_count || 0,
                locked: pool.locked || pool.is_locked || false,
                settled: pool.settled || pool.is_settled || false,
                distribution: pool.distribution || {}
            }));
        } else {
            upcomingBlocks = [];
        }
        
        renderUpcomingBlocks(upcomingBlocks);
    } catch (error) {
        console.error('Failed to load blocks:', error);
        upcomingBlocks = [];
        renderUpcomingBlocks(upcomingBlocks);
    }
}

// Render upcoming blocks
function renderUpcomingBlocks(blocks) {
    const container = document.getElementById('blocks-list');
    
    if (blocks.length === 0) {
        container.innerHTML = '<div class="empty-state">No upcoming blocks</div>';
        return;
    }
    
    container.innerHTML = blocks.map(block => `
        <div class="block-card ${block.locked ? 'locked' : ''} ${selectedBlock?.block_index === block.block_index ? 'active' : ''}" 
             onclick="${block.locked ? '' : `selectBlock(${block.block_index})`}">
            <div class="block-header">
                <span class="block-index">Block #${block.block_index}</span>
                <span class="block-status ${block.locked ? 'locked' : 'open'}">
                    ${block.locked ? 'LOCKED' : 'OPEN'}
                </span>
            </div>
            <div class="block-pool-info">
                <div class="pool-stat">
                    <span class="pool-label">Total Pool</span>
                    <span class="pool-value">$${block.total_pool.toFixed(2)}</span>
                </div>
                <div class="pool-stat">
                    <span class="pool-label">Total Bets</span>
                    <span class="pool-value">${block.total_bets}</span>
                </div>
            </div>
        </div>
    `).join('');
}

// Select block
function selectBlock(blockIndex) {
    selectedBlock = upcomingBlocks.find(b => b.block_index === blockIndex);
    
    if (!selectedBlock) return;
    
    renderUpcomingBlocks(upcomingBlocks);
    renderBettingInterface(selectedBlock);
}

// Render betting interface
function renderBettingInterface(block) {
    const container = document.getElementById('betting-content');
    
    container.innerHTML = `
        <div class="betting-header">
            <h2 class="betting-title">Block #${block.block_index}</h2>
            <p class="betting-subtitle">Place your bet on the consensus outcome</p>
        </div>

        <div class="pool-overview">
            <h3>Pool Overview</h3>
            <div class="pool-stats">
                <div class="pool-stat-card">
                    <span class="pool-stat-label">Total Pool</span>
                    <span class="pool-stat-value">$${block.total_pool.toFixed(0)}</span>
                </div>
                <div class="pool-stat-card">
                    <span class="pool-stat-label">Total Bets</span>
                    <span class="pool-stat-value">${block.total_bets}</span>
                </div>
                <div class="pool-stat-card">
                    <span class="pool-stat-label">House Cut</span>
                    <span class="pool-stat-value">5%</span>
                </div>
            </div>
        </div>

        <div class="prediction-options">
            <h3>Select Prediction</h3>
            <div class="prediction-grid">
                <button class="prediction-btn active" onclick="selectPrediction('approved')">
                    <span class="prediction-label">Approved</span>
                    <span class="prediction-odds">Consensus approves block</span>
                    <span class="prediction-current">Pool: $${(block.distribution['approved'] || 0).toFixed(0)}</span>
                </button>
                <button class="prediction-btn" onclick="selectPrediction('rejected')">
                    <span class="prediction-label">Rejected</span>
                    <span class="prediction-odds">Consensus rejects block</span>
                    <span class="prediction-current">Pool: $${(block.distribution['rejected'] || 0).toFixed(0)}</span>
                </button>
                <button class="prediction-btn" onclick="selectPrediction('high_confidence')">
                    <span class="prediction-label">High Confidence</span>
                    <span class="prediction-odds">Confidence ≥ 75%</span>
                    <span class="prediction-current">Pool: $${(block.distribution['high_confidence'] || 0).toFixed(0)}</span>
                </button>
                <button class="prediction-btn" onclick="selectPrediction('low_confidence')">
                    <span class="prediction-label">Low Confidence</span>
                    <span class="prediction-odds">Confidence < 50%</span>
                    <span class="prediction-current">Pool: $${(block.distribution['low_confidence'] || 0).toFixed(0)}</span>
                </button>
            </div>
        </div>

        <div class="bet-form">
            <h3>Bet Amount</h3>
            <div class="form-group">
                <label for="stake-amount">Stake (USD)</label>
                <input type="number" id="stake-amount" value="10" min="1" max="10000" step="1" 
                       class="form-input" oninput="updateBetSummary()">
                <div class="quick-stakes">
                    <button class="quick-stake-btn" onclick="setStake(10)">$10</button>
                    <button class="quick-stake-btn" onclick="setStake(50)">$50</button>
                    <button class="quick-stake-btn" onclick="setStake(100)">$100</button>
                    <button class="quick-stake-btn" onclick="setStake(500)">$500</button>
                </div>
            </div>
        </div>

        <div class="bet-summary">
            <div class="summary-row">
                <span>Your Stake:</span>
                <span id="summary-stake">$10.00</span>
            </div>
            <div class="summary-row">
                <span>Current Odds:</span>
                <span id="summary-odds">2.5x</span>
            </div>
            <div class="summary-row">
                <span>Potential Payout:</span>
                <span id="summary-payout">$25.00</span>
            </div>
        </div>

        <button class="btn-place-bet" onclick="placeBet()">
            <span class="icon-betting"></span> Place Bet
        </button>
    `;
    
    selectedPrediction = 'approved';
    updateBetSummary();
}

// Select prediction
function selectPrediction(prediction) {
    selectedPrediction = prediction;
    
    document.querySelectorAll('.prediction-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    event.target.closest('.prediction-btn').classList.add('active');
    
    updateBetSummary();
}

// Set stake
function setStake(amount) {
    document.getElementById('stake-amount').value = amount;
    updateBetSummary();
}

// Update bet summary
function updateBetSummary() {
    if (!selectedBlock || !selectedPrediction) return;
    
    const stake = parseFloat(document.getElementById('stake-amount').value) || 0;
    const predictionPool = selectedBlock.distribution[selectedPrediction] || 0;
    const otherPools = Object.entries(selectedBlock.distribution)
        .filter(([key]) => key !== selectedPrediction)
        .reduce((sum, [, value]) => sum + value, 0);
    
    // Calculate odds
    const totalPool = selectedBlock.total_pool;
    const odds = totalPool > 0 ? (totalPool / (predictionPool + stake)) : 1.0;
    
    // Potential payout
    const potentialPayout = stake * odds;
    
    document.getElementById('summary-stake').textContent = `$${stake.toFixed(2)}`;
    document.getElementById('summary-odds').textContent = `${odds.toFixed(2)}x`;
    document.getElementById('summary-payout').textContent = `$${potentialPayout.toFixed(2)}`;
}

// Place bet
async function placeBet() {
    if (!selectedBlock || !selectedPrediction) {
        alert('Please select a block and prediction');
        return;
    }
    
    const stake = parseFloat(document.getElementById('stake-amount').value);
    
    if (!stake || stake < 1) {
        alert('Minimum stake is $1');
        return;
    }
    
    try {
        const response = await fetch('/api/v1/betting/place', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: userId,
                block_index: selectedBlock.block_index,
                prediction: selectedPrediction,
                stake_amount: stake
            })
        });
        
        const result = await response.json();
        
        if (response.ok) {
            alert(`Bet placed successfully!\nBlock: #${selectedBlock.block_index}\nPrediction: ${selectedPrediction}\nStake: $${stake}\nOdds: ${result.odds.toFixed(2)}x\nPotential Payout: $${result.potential_payout.toFixed(2)}`);
            loadUserBalance();
            loadUpcomingBlocks();
            loadMyBets();
        } else {
            alert(`Failed to place bet: ${result.detail || 'Unknown error'}`);
        }
    } catch (error) {
        console.error('Bet placement error:', error);
        alert('Failed to place bet. Please try again.');
    }
}

// Load my bets
async function loadMyBets() {
    try {
        const response = await fetch(`/api/v1/betting/user/${userId}/stats`);
        const data = await response.json();
        
        // Update summary
        document.getElementById('active-bets').textContent = data.total_bets || 0;
        document.getElementById('total-wagered').textContent = `$${(data.total_wagered || 0).toFixed(2)}`;
        
        // Use real API data for bets
        let bets = [];
        if (data.bets && Array.isArray(data.bets)) {
            bets = data.bets.map(bet => ({
                block_index: bet.block_index || bet.block_id || 0,
                prediction: bet.prediction || bet.outcome || 'Unknown',
                stake: bet.stake || bet.amount || 0,
                odds: bet.odds || bet.multiplier || 1,
                potential: bet.potential || (bet.stake * bet.odds) || 0,
                status: bet.status || 'pending'
            }));
        } else if (data.active_bets && Array.isArray(data.active_bets)) {
            bets = data.active_bets.map(bet => ({
                block_index: bet.block_index || bet.block_id || 0,
                prediction: bet.prediction || bet.outcome || 'Unknown',
                stake: bet.stake || bet.amount || 0,
                odds: bet.odds || bet.multiplier || 1,
                potential: bet.potential || (bet.stake * bet.odds) || 0,
                status: bet.status || 'pending'
            }));
        }
        
        const container = document.getElementById('my-bets-list');
        
        if (bets.length === 0) {
            container.innerHTML = '<div class="empty-state">No active bets</div>';
            return;
        }
        
        container.innerHTML = bets.map(bet => `
            <div class="bet-card">
                <div class="bet-block">Block #${bet.block_index}</div>
                <div class="bet-prediction">${bet.prediction}</div>
                <div class="bet-details">
                    <div class="bet-detail">
                        <span class="detail-label">Stake:</span>
                        <span class="detail-value">$${bet.stake.toFixed(2)}</span>
                    </div>
                    <div class="bet-detail">
                        <span class="detail-label">Odds:</span>
                        <span class="detail-value">${bet.odds.toFixed(2)}x</span>
                    </div>
                    <div class="bet-detail">
                        <span class="detail-label">Potential:</span>
                        <span class="detail-value">$${bet.potential.toFixed(2)}</span>
                    </div>
                    <div class="bet-detail">
                        <span class="detail-label">Status:</span>
                        <span class="detail-value">${bet.status}</span>
                    </div>
                </div>
            </div>
        `).join('');
    } catch (error) {
        console.error('Failed to load bets:', error);
    }
}

// Load user stats
async function loadUserStats() {
    try {
        const response = await fetch(`/api/v1/betting/user/${userId}/stats`);
        const data = await response.json();
        
        document.getElementById('win-rate').textContent = `${(data.win_rate_pct || 0).toFixed(1)}%`;
        document.getElementById('total-bets').textContent = data.total_bets || 0;
        document.getElementById('total-won').textContent = `$${(data.total_won || 0).toFixed(2)}`;
        
        const netProfit = (data.total_won || 0) - (data.total_wagered || 0);
        const netProfitEl = document.getElementById('net-profit');
        netProfitEl.textContent = `${netProfit >= 0 ? '+' : ''}$${netProfit.toFixed(2)}`;
        netProfitEl.className = `stat-value ${netProfit >= 0 ? 'positive' : 'negative'}`;
    } catch (error) {
        console.error('Failed to load stats:', error);
    }
}

// Load leaderboard
async function loadLeaderboard() {
    try {
        const response = await fetch('/api/v1/betting/leaderboard?limit=10');
        const data = await response.json();
        
        const container = document.getElementById('leaderboard-list');
        
        if (!data.leaderboard || data.leaderboard.length === 0) {
            container.innerHTML = '<div class="empty-state">No leaderboard data</div>';
            return;
        }
        
        container.innerHTML = data.leaderboard.map((user, idx) => `
            <div class="leaderboard-item">
                <span class="leaderboard-rank">#${idx + 1}</span>
                <span class="leaderboard-user">${user.user_id}</span>
                <span class="leaderboard-profit ${user.net_profit >= 0 ? 'positive' : 'negative'}">
                    ${user.net_profit >= 0 ? '+' : ''}$${user.net_profit.toFixed(2)}
                </span>
            </div>
        `).join('');
    } catch (error) {
        console.error('Failed to load leaderboard:', error);
    }
}

// Refresh blocks
function refreshBlocks() {
    loadUpcomingBlocks();
}

// Show deposit modal
function showDepositModal() {
    document.getElementById('deposit-modal').classList.add('active');
}

// Close deposit modal
function closeDepositModal() {
    document.getElementById('deposit-modal').classList.remove('active');
}

// Deposit
async function deposit() {
    const amount = parseFloat(document.getElementById('deposit-amount').value);
    
    if (!amount || amount < 1) {
        alert('Minimum deposit is $1');
        return;
    }
    
    try {
        const response = await fetch('/api/v1/betting/deposit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: userId,
                amount: amount
            })
        });
        
        const result = await response.json();
        
        if (response.ok) {
            alert(`Deposited $${amount.toFixed(2)} successfully!\nNew balance: $${result.new_balance.toFixed(2)}`);
            closeDepositModal();
            loadUserBalance();
        } else {
            alert(`Deposit failed: ${result.detail || 'Unknown error'}`);
        }
    } catch (error) {
        console.error('Deposit error:', error);
        alert('Failed to deposit. Please try again.');
    }
}
