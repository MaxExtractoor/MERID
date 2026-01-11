// MERID Prediction Markets Interface

let selectedMarket = null;
let selectedOutcome = null;
let markets = [];
let arbitrageOpportunities = [];

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    loadMarkets();
    scanArbitrage();
});

// Setup event listeners
function setupEventListeners() {
    // Search
    document.getElementById('market-search').addEventListener('input', (e) => {
        filterMarkets(e.target.value);
    });

    // Filters
    document.getElementById('category-filter').addEventListener('change', loadMarkets);
    document.getElementById('platform-filter').addEventListener('change', loadMarkets);

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

// Load markets
async function loadMarkets() {
    const category = document.getElementById('category-filter').value;
    const platform = document.getElementById('platform-filter').value;

    try {
        const response = await fetch(`/api/v1/trading/markets/list?platform=${platform}&category=${category}`);
        const data = await response.json();

        // Mock data for demonstration
        markets = [
            {
                id: 'btc-50k-2024',
                title: 'Will Bitcoin reach $50,000 by end of 2024?',
                platform: 'polymarket',
                category: 'crypto',
                outcomes: [
                    { name: 'Yes', odds: 0.65, volume: 125000 },
                    { name: 'No', odds: 0.35, volume: 75000 }
                ],
                description: 'This market resolves to YES if Bitcoin (BTC) trades at or above $50,000 on any major exchange before December 31, 2024 23:59:59 UTC.',
                totalVolume: 200000,
                endDate: '2024-12-31'
            },
            {
                id: 'eth-etf-approval',
                title: 'Will Ethereum ETF be approved in 2024?',
                platform: 'polymarket',
                category: 'crypto',
                outcomes: [
                    { name: 'Yes', odds: 0.72, volume: 180000 },
                    { name: 'No', odds: 0.28, volume: 70000 }
                ],
                description: 'Resolves YES if SEC approves spot Ethereum ETF by end of 2024.',
                totalVolume: 250000,
                endDate: '2024-12-31'
            },
            {
                id: 'sol-100-2024',
                title: 'Solana to $100 in 2024?',
                platform: 'manifold',
                category: 'crypto',
                outcomes: [
                    { name: 'Yes', odds: 0.58, volume: 95000 },
                    { name: 'No', odds: 0.42, volume: 65000 }
                ],
                description: 'Will SOL reach $100 before end of 2024?',
                totalVolume: 160000,
                endDate: '2024-12-31'
            }
        ];

        renderMarkets(markets);
    } catch (error) {
        console.error('Failed to load markets:', error);
    }
}

// Render markets list
function renderMarkets(marketsList) {
    const container = document.getElementById('markets-list');
    
    if (marketsList.length === 0) {
        container.innerHTML = '<div class="empty-state">No markets found</div>';
        return;
    }

    container.innerHTML = marketsList.map(market => `
        <div class="market-card" data-market-id="${market.id}" onclick="selectMarket('${market.id}')">
            <div class="market-header">
                <div class="market-title">${market.title}</div>
                <div class="market-platform">${market.platform}</div>
            </div>
            <div class="market-odds">
                ${market.outcomes.map(outcome => `
                    <div class="odds-item">
                        <span class="odds-label">${outcome.name}</span>
                        <span class="odds-value">${(outcome.odds * 100).toFixed(0)}%</span>
                    </div>
                `).join('')}
            </div>
        </div>
    `).join('');
}

// Filter markets
function filterMarkets(query) {
    const filtered = markets.filter(m => 
        m.title.toLowerCase().includes(query.toLowerCase())
    );
    renderMarkets(filtered);
}

// Select market
function selectMarket(marketId) {
    selectedMarket = markets.find(m => m.id === marketId);
    
    if (!selectedMarket) return;

    // Update active state
    document.querySelectorAll('.market-card').forEach(card => {
        card.classList.remove('active');
    });
    document.querySelector(`[data-market-id="${marketId}"]`).classList.add('active');

    // Render market details
    renderMarketDetails(selectedMarket);
    
    // Render trade form
    renderTradeForm(selectedMarket);
}

// Render market details
function renderMarketDetails(market) {
    const container = document.getElementById('market-details');
    
    container.innerHTML = `
        <div class="market-detail-header">
            <h2 class="market-detail-title">${market.title}</h2>
            <div class="market-meta">
                <span><strong>Platform:</strong> ${market.platform}</span>
                <span><strong>Volume:</strong> $${market.totalVolume.toLocaleString()}</span>
                <span><strong>Ends:</strong> ${market.endDate}</span>
            </div>
        </div>

        <div class="market-description">
            <p>${market.description}</p>
        </div>

        <div class="outcomes-section">
            <h3>Outcomes</h3>
            ${market.outcomes.map(outcome => `
                <div class="outcome-card">
                    <div class="outcome-header">
                        <span class="outcome-name">${outcome.name}</span>
                        <span class="outcome-odds">${(outcome.odds * 100).toFixed(1)}%</span>
                    </div>
                    <div class="outcome-volume">Volume: $${outcome.volume.toLocaleString()}</div>
                </div>
            `).join('')}
        </div>

        <div class="cross-platform-section">
            <h3>Cross-Platform Comparison</h3>
            <div class="platform-comparison">
                <div class="platform-item">
                    <span class="platform-name">Polymarket</span>
                    <span class="platform-odds">${(market.outcomes[0].odds * 100).toFixed(1)}%</span>
                </div>
                <div class="platform-item">
                    <span class="platform-name">Manifold</span>
                    <span class="platform-odds">${((market.outcomes[0].odds - 0.03) * 100).toFixed(1)}%</span>
                </div>
                <div class="platform-item">
                    <span class="platform-name">Augur</span>
                    <span class="platform-odds">${((market.outcomes[0].odds + 0.02) * 100).toFixed(1)}%</span>
                </div>
            </div>
        </div>
    `;
}

// Render trade form
function renderTradeForm(market) {
    const container = document.getElementById('trade-form-content');
    
    container.innerHTML = `
        <div class="outcome-selector">
            ${market.outcomes.map((outcome, idx) => `
                <button class="outcome-btn ${idx === 0 ? 'active' : ''}" 
                        data-outcome="${outcome.name}"
                        onclick="selectOutcome('${outcome.name}', ${outcome.odds})">
                    <span class="outcome-btn-name">${outcome.name}</span>
                    <span class="outcome-btn-odds">${(outcome.odds * 100).toFixed(1)}%</span>
                </button>
            `).join('')}
        </div>

        <div class="trade-amount">
            <label for="trade-size">Amount (USD)</label>
            <input type="number" id="trade-size" value="100" min="1" step="1" oninput="updateTradeSummary()">
        </div>

        <div class="trade-summary">
            <div class="summary-row">
                <span>Stake:</span>
                <span id="summary-stake">$100.00</span>
            </div>
            <div class="summary-row">
                <span>Potential Return:</span>
                <span id="summary-return">$153.85</span>
            </div>
            <div class="summary-row">
                <span>Potential Profit:</span>
                <span id="summary-profit">$53.85</span>
            </div>
        </div>

        <button class="btn-execute-trade" onclick="executeTrade()">
            <span class="icon-trading"></span> Execute Trade
        </button>
    `;

    selectedOutcome = market.outcomes[0];
    updateTradeSummary();
}

// Select outcome
function selectOutcome(outcomeName, odds) {
    selectedOutcome = { name: outcomeName, odds: odds };
    
    document.querySelectorAll('.outcome-btn').forEach(btn => {
        btn.classList.remove('active');
    });
    event.target.closest('.outcome-btn').classList.add('active');
    
    updateTradeSummary();
}

// Update trade summary
function updateTradeSummary() {
    if (!selectedOutcome) return;

    const stake = parseFloat(document.getElementById('trade-size').value) || 0;
    const potentialReturn = stake / selectedOutcome.odds;
    const potentialProfit = potentialReturn - stake;

    document.getElementById('summary-stake').textContent = `$${stake.toFixed(2)}`;
    document.getElementById('summary-return').textContent = `$${potentialReturn.toFixed(2)}`;
    document.getElementById('summary-profit').textContent = `$${potentialProfit.toFixed(2)}`;
}

// Execute trade
async function executeTrade() {
    if (!selectedMarket || !selectedOutcome) {
        alert('Please select a market and outcome');
        return;
    }

    const stake = parseFloat(document.getElementById('trade-size').value);
    
    if (!stake || stake < 1) {
        alert('Minimum stake is $1');
        return;
    }

    try {
        const response = await fetch('/api/v1/trading/markets/trade', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                market_id: selectedMarket.id,
                outcome: selectedOutcome.name,
                size_usd: stake,
                platform: selectedMarket.platform
            })
        });

        const result = await response.json();

        if (response.ok) {
            alert(`Trade executed!\nMarket: ${selectedMarket.title}\nOutcome: ${selectedOutcome.name}\nStake: $${stake}`);
            loadPositions();
        } else {
            alert(`Trade failed: ${result.detail || 'Unknown error'}`);
        }
    } catch (error) {
        console.error('Trade execution error:', error);
        alert('Failed to execute trade. Please try again.');
    }
}

// Scan for arbitrage opportunities
async function scanArbitrage() {
    try {
        const response = await fetch('/api/v1/trading/arbitrage/scan?venues=polymarket,manifold,augur&assets=BTC,ETH,SOL');
        const data = await response.json();

        // Mock arbitrage opportunities
        arbitrageOpportunities = [
            {
                id: 'arb-btc-50k',
                market: 'BTC $50k by 2024',
                platformA: 'Polymarket',
                platformB: 'Manifold',
                oddsA: 0.65,
                oddsB: 0.62,
                spreadBps: 300,
                netProfit: 45.20
            },
            {
                id: 'arb-eth-etf',
                market: 'ETH ETF Approval',
                platformA: 'Polymarket',
                platformB: 'Augur',
                oddsA: 0.72,
                oddsB: 0.69,
                spreadBps: 280,
                netProfit: 38.50
            }
        ];

        renderArbitrageOpportunities(arbitrageOpportunities);
    } catch (error) {
        console.error('Failed to scan arbitrage:', error);
    }
}

// Render arbitrage opportunities
function renderArbitrageOpportunities(opportunities) {
    const container = document.getElementById('arbitrage-list');
    
    if (opportunities.length === 0) {
        container.innerHTML = '<div class="empty-state">No opportunities found</div>';
        return;
    }

    container.innerHTML = opportunities.map(opp => `
        <div class="arbitrage-card" onclick="executeArbitrage('${opp.id}')">
            <div class="arb-header">
                <span class="arb-market">${opp.market}</span>
                <span class="arb-profit">+$${opp.netProfit.toFixed(2)}</span>
            </div>
            <div class="arb-details">
                <div>
                    <div class="arb-platform">${opp.platformA}</div>
                    <div class="arb-odds">${(opp.oddsA * 100).toFixed(1)}%</div>
                </div>
                <div>
                    <div class="arb-platform">${opp.platformB}</div>
                    <div class="arb-odds">${(opp.oddsB * 100).toFixed(1)}%</div>
                </div>
            </div>
        </div>
    `).join('');
}

// Execute arbitrage
async function executeArbitrage(oppId) {
    const opp = arbitrageOpportunities.find(o => o.id === oppId);
    
    if (!opp) return;

    if (confirm(`Execute arbitrage on ${opp.market}?\nExpected profit: $${opp.netProfit.toFixed(2)}`)) {
        try {
            const response = await fetch(`/api/v1/trading/arbitrage/execute/${oppId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ auto_execute: true })
            });

            const result = await response.json();

            if (response.ok) {
                alert(`Arbitrage executed!\nProfit: $${result.actual_profit || opp.netProfit}`);
                scanArbitrage();
            } else {
                alert(`Execution failed: ${result.detail || 'Unknown error'}`);
            }
        } catch (error) {
            console.error('Arbitrage execution error:', error);
            alert('Failed to execute arbitrage. Please try again.');
        }
    }
}

// Load positions
async function loadPositions() {
    try {
        const response = await fetch('/api/v1/trading/markets/positions');
        const data = await response.json();
        
        // Mock positions
        const positions = [
            {
                market: 'BTC $50k by 2024',
                outcome: 'Yes',
                stake: 100,
                currentValue: 115,
                odds: 0.65
            }
        ];

        renderPositions(positions);
    } catch (error) {
        console.error('Failed to load positions:', error);
    }
}

// Render positions
function renderPositions(positions) {
    const container = document.getElementById('positions-list');
    
    if (positions.length === 0) {
        container.innerHTML = '<div class="empty-state">No open positions</div>';
        return;
    }

    const totalValue = positions.reduce((sum, pos) => sum + pos.currentValue, 0);
    document.getElementById('total-value').textContent = `$${totalValue.toFixed(2)}`;
    document.getElementById('position-count').textContent = positions.length;

    container.innerHTML = positions.map(pos => `
        <div class="position-card">
            <div class="position-market">${pos.market}</div>
            <div class="position-outcome">${pos.outcome}</div>
            <div class="position-stats">
                <div class="position-stat">
                    <span class="stat-label">Stake:</span>
                    <span class="stat-value">$${pos.stake.toFixed(2)}</span>
                </div>
                <div class="position-stat">
                    <span class="stat-label">Value:</span>
                    <span class="stat-value">$${pos.currentValue.toFixed(2)}</span>
                </div>
                <div class="position-stat">
                    <span class="stat-label">P&L:</span>
                    <span class="stat-value ${pos.currentValue >= pos.stake ? 'positive' : 'negative'}">
                        ${pos.currentValue >= pos.stake ? '+' : ''}$${(pos.currentValue - pos.stake).toFixed(2)}
                    </span>
                </div>
                <div class="position-stat">
                    <span class="stat-label">Odds:</span>
                    <span class="stat-value">${(pos.odds * 100).toFixed(1)}%</span>
                </div>
            </div>
        </div>
    `).join('');
}
