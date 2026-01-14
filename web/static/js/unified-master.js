/**
 * MERID Unified Control Center - Master Section Loader
 * Handles all sections from Predictions to Spectator
 * NO DEPENDENCIES - Completely standalone
 */

(function() {
    'use strict';
    console.log('[MERID] Unified Control Center initializing...');
    
    var API_BASE = window.location.origin;
    if (!API_BASE.includes(':')) {
        // Browsers default to 80; ensure we hit FastAPI on 8001
        API_BASE = 'http://127.0.0.1:8001';
    }
    if (API_BASE.endsWith('/')) API_BASE = API_BASE.slice(0, -1);
    console.log('[MERID] Using API base:', API_BASE);
    
    // ============================================
    // UTILITIES
    // ============================================
    function $(id) { return document.getElementById(id); }
    function $$(sel) { return document.querySelectorAll(sel); }
    
    function render(id, html) {
        var el = $(id);
        if (el) { el.innerHTML = html; return true; }
        return false;
    }
    
    function fmt(n) {
        if (n >= 1e9) return (n/1e9).toFixed(1) + 'B';
        if (n >= 1e6) return (n/1e6).toFixed(1) + 'M';
        if (n >= 1e3) return (n/1e3).toFixed(1) + 'K';
        return n.toFixed(2);
    }
    
    function fmtCurrency(n) { return '$' + fmt(n); }
    
    function api(path) {
        var url = path.startsWith('http') ? path : API_BASE + path;
        return fetch(url).then(function(r) { return r.json(); }).catch(function(e) {
            console.error('[API]', path, e);
            return null;
        });
    }
    
    // ============================================
    // SECTION LOADERS
    // ============================================
    
    // PREDICTIONS
    function loadPredictions() {
        console.log('[MERID] Loading Predictions...');
        api('/api/v1/institutional/predictions/markets?limit=30').then(function(data) {
            if (data && data.markets && data.markets.length) {
                var html = data.markets.map(function(m) {
                    return '<div style="background:#161b22;border:1px solid #30363d;border-radius:6px;padding:16px;margin-bottom:12px;">' +
                        '<div style="display:flex;justify-content:space-between;margin-bottom:8px;">' +
                            '<span style="color:#8b949e;font-size:11px;text-transform:uppercase;background:#21262d;padding:2px 6px;border-radius:3px;">' + (m.category||'crypto') + '</span>' +
                            '<span style="color:#8b949e;font-size:11px;">Vol: ' + fmtCurrency(m.volume_24h||0) + '</span>' +
                        '</div>' +
                        '<div style="color:#e6edf3;font-size:14px;font-weight:500;margin-bottom:12px;">' + m.question + '</div>' +
                        '<div style="background:#21262d;border-radius:4px;height:6px;overflow:hidden;margin-bottom:8px;">' +
                            '<div style="background:#238636;height:100%;width:' + ((m.yes_price||0.5)*100) + '%;"></div>' +
                        '</div>' +
                        '<div style="display:flex;justify-content:space-between;font-size:12px;">' +
                            '<span style="color:#238636;font-weight:600;">YES ' + ((m.yes_price||0.5)*100).toFixed(1) + '%</span>' +
                            '<span style="color:#f85149;font-weight:600;">NO ' + ((m.no_price||0.5)*100).toFixed(1) + '%</span>' +
                        '</div>' +
                    '</div>';
                }).join('');
                render('predictions-list', html);
                render('predictions-feed', html);
            }
        });
        
        // Drift
        api('/api/v1/institutional/predictions/drift').then(function(drift) {
            if (drift && drift.signals && drift.signals.length) {
                var html = drift.signals.map(function(s) {
                    var color = s.drift_pct > 0 ? '#238636' : '#f85149';
                    var sign = s.drift_pct > 0 ? '+' : '';
                    return '<div style="padding:10px 0;border-bottom:1px solid #21262d;">' +
                        '<div style="color:#e6edf3;font-size:13px;margin-bottom:4px;">' + (s.question||'').substring(0,50) + '...</div>' +
                        '<span style="color:' + color + ';font-weight:600;">' + sign + (s.drift_pct||0).toFixed(1) + '%</span>' +
                    '</div>';
                }).join('');
                render('drift-feed', html);
            }
        });
        
        // Arbitrage
        api('/api/v1/institutional/predictions/arbitrage').then(function(arb) {
            if (arb && arb.opportunities && arb.opportunities.length) {
                var html = arb.opportunities.map(function(o) {
                    return '<div style="padding:10px 0;border-bottom:1px solid #21262d;">' +
                        '<div style="color:#e6edf3;font-size:13px;margin-bottom:4px;">' + (o.question||'').substring(0,50) + '...</div>' +
                        '<span style="color:#238636;font-weight:600;">Spread: ' + (o.spread_pct||0).toFixed(2) + '%</span>' +
                    '</div>';
                }).join('');
                render('arb-feed', html);
            }
        });
    }
    
    // INTELLIGENCE
    function loadIntelligence() {
        console.log('[MERID] Loading Intelligence...');
        api('/api/v1/intelligence/news?limit=15').then(function(data) {
            if (data && data.news && data.news.length) {
                var html = data.news.map(function(n) {
                    var sentimentColor = '#8b949e';
                    if (n.sentiment && n.sentiment.label === 'positive') sentimentColor = '#238636';
                    if (n.sentiment && n.sentiment.label === 'negative') sentimentColor = '#f85149';
                    return '<div style="background:#161b22;border:1px solid #30363d;border-radius:6px;padding:16px;margin-bottom:12px;">' +
                        '<div style="display:flex;justify-content:space-between;margin-bottom:8px;">' +
                            '<span style="color:#58a6ff;font-size:11px;">' + n.source + '</span>' +
                            '<span style="color:' + sentimentColor + ';font-size:11px;text-transform:uppercase;">' + (n.sentiment && n.sentiment.label || 'neutral') + '</span>' +
                        '</div>' +
                        '<div style="color:#e6edf3;font-size:14px;font-weight:500;margin-bottom:8px;">' + n.title + '</div>' +
                        '<div style="color:#8b949e;font-size:13px;">' + (n.description||'').substring(0,120) + '...</div>' +
                    '</div>';
                }).join('');
                render('news-feed-list', html);
            }
        });
    }
    
    // FOUR SYSTEMS
    function loadSystems() {
        console.log('[MERID] Loading Systems...');
        api('/api/v1/institutional/systems/status').then(function(data) {
            if (data && data.systems) {
                data.systems.forEach(function(s) {
                    var prefix = s.system_id === 'intelligence' ? 'intel' : s.system_id;
                    var healthEl = $(prefix + '-health');
                    var intentsEl = $(prefix + '-intents');
                    if (healthEl) healthEl.textContent = Math.round((s.health_score||1)*100) + '%';
                    if (intentsEl) intentsEl.textContent = s.allowed_actions || 0;
                });
            }
        });
    }
    
    // AGENTS
    function loadAgents() {
        console.log('[MERID] Loading Agents...');
        api('/api/v1/institutional/mesh/status').then(function(data) {
            if (data && data.agents && data.agents.length) {
                var html = data.agents.map(function(a) {
                    var statusColor = a.running ? '#238636' : '#f85149';
                    var statusText = a.running ? 'RUNNING' : 'STOPPED';
                    return '<div style="background:#161b22;border:1px solid #30363d;border-radius:6px;padding:16px;margin-bottom:12px;display:flex;align-items:center;gap:12px;">' +
                        '<div style="width:40px;height:40px;background:#238636;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:18px;">🤖</div>' +
                        '<div style="flex:1;">' +
                            '<div style="color:#e6edf3;font-weight:600;font-size:14px;">' + a.agent_id + '</div>' +
                            '<div style="color:#8b949e;font-size:12px;">' + a.model + '</div>' +
                        '</div>' +
                        '<div style="padding:4px 8px;border-radius:4px;background:' + statusColor + ';color:#fff;font-size:11px;font-weight:600;">' + statusText + '</div>' +
                    '</div>';
                }).join('');
                render('agents-grid', html);
                
                var totalEl = $('mesh-total');
                var statusEl = $('mesh-status');
                if (totalEl) totalEl.textContent = data.agents.length;
                if (statusEl) statusEl.textContent = data.running ? 'RUNNING' : 'IDLE';
            }
        });
    }
    
    // CONSENSUS
    function loadConsensus() {
        console.log('[MERID] Loading Consensus...');
        api('/api/v1/institutional/consensus/status').then(function(data) {
            if (data) {
                var statusEl = $('consensus-status');
                var votesEl = $('consensus-votes');
                var quorumEl = $('consensus-quorum');
                if (statusEl) statusEl.textContent = data.running ? 'RUNNING' : 'IDLE';
                if (votesEl) votesEl.textContent = data.pending_votes || 0;
                if (quorumEl) quorumEl.textContent = Math.round((data.quorum_threshold||0.67)*100) + '%';
            }
        });
    }
    
    // SIMULATION
    function loadSimulation() {
        console.log('[MERID] Loading Simulation...');
        api('/api/v1/institutional/simulation/status').then(function(data) {
            if (data) {
                var statusEl = $('sim-status');
                var blockEl = $('sim-block');
                if (statusEl) statusEl.textContent = data.running ? 'MINING' : 'IDLE';
                if (blockEl) blockEl.textContent = data.current_block || 0;
            }
        });
    }
    
    // SHADOW MERID
    function loadShadow() {
        console.log('[MERID] Loading Shadow...');
        api('/api/v1/institutional/shadow/status').then(function(data) {
            if (data && data.portfolio) {
                var balEl = $('shadow-balance');
                var pnlEl = $('shadow-pnl');
                if (balEl) balEl.textContent = fmtCurrency(data.portfolio.balance || 100000);
                if (pnlEl) pnlEl.textContent = fmtCurrency(data.portfolio.total_pnl || 0);
            }
        });
    }
    
    // RISK
    function loadRisk() {
        console.log('[MERID] Loading Risk...');
        api('/api/v1/dashboard/risk/metrics').then(function(data) {
            if (data) {
                var scoreEl = $('risk-score');
                var varEl = $('risk-var');
                var ddEl = $('risk-drawdown');
                if (scoreEl) scoreEl.textContent = (data.risk_score || 0).toFixed(1);
                if (varEl) varEl.textContent = fmtCurrency(data.var_95 || 0);
                if (ddEl) ddEl.textContent = (data.max_drawdown || 0).toFixed(2) + '%';
            }
        });
    }
    
    // AUDIT
    function loadAudit() {
        console.log('[MERID] Loading Audit...');
        api('/api/v1/institutional/audit/recent?limit=10').then(function(data) {
            if (data && data.entries && data.entries.length) {
                var html = data.entries.map(function(e) {
                    return '<div style="padding:10px 0;border-bottom:1px solid #21262d;">' +
                        '<div style="display:flex;justify-content:space-between;margin-bottom:4px;">' +
                            '<span style="color:#58a6ff;font-size:11px;">' + e.event_type + '</span>' +
                            '<span style="color:#8b949e;font-size:11px;">#' + e.sequence + '</span>' +
                        '</div>' +
                        '<div style="color:#8b949e;font-size:12px;">' + e.source + '</div>' +
                    '</div>';
                }).join('');
                render('audit-feed', html);
            }
        });
    }
    
    // EXECUTION
    function loadExecution() {
        console.log('[MERID] Loading Execution...');
        api('/api/v1/dashboard/execution/stats').then(function(data) {
            if (data) {
                var modeEl = $('exec-mode');
                var posEl = $('exec-positions');
                if (modeEl) modeEl.textContent = (data.mode || 'PAPER').toUpperCase();
                if (posEl) posEl.textContent = data.positions ? data.positions.open : 0;
            }
        });
    }
    
    // ANALYTICS
    function loadAnalytics() {
        console.log('[MERID] Loading Analytics...');
        // Placeholder
    }
    
    // ARBITRAGE
    function loadArbitrage() {
        console.log('[MERID] Loading Arbitrage...');
        api('/api/v1/institutional/predictions/arbitrage').then(function(data) {
            if (data && data.opportunities && data.opportunities.length) {
                var html = data.opportunities.map(function(o) {
                    return '<div style="background:#161b22;border:1px solid #30363d;border-radius:6px;padding:16px;margin-bottom:12px;">' +
                        '<div style="color:#e6edf3;font-size:14px;margin-bottom:8px;">' + o.question + '</div>' +
                        '<div style="display:flex;gap:16px;">' +
                            '<span style="color:#8b949e;font-size:12px;">' + o.platform_a + ' vs ' + o.platform_b + '</span>' +
                            '<span style="color:#238636;font-weight:600;">Spread: ' + (o.spread_pct||0).toFixed(2) + '%</span>' +
                        '</div>' +
                    '</div>';
                }).join('');
                render('arbitrage-list', html);
            }
        });
    }
    
    // PORTFOLIO
    function loadPortfolio() {
        console.log('[MERID] Loading Portfolio...');
        api('/api/v1/dashboard/portfolio/summary').then(function(data) {
            if (data) {
                var valEl = $('portfolio-value');
                var pnlEl = $('portfolio-pnl');
                if (valEl) valEl.textContent = fmtCurrency(data.total_value || 100000);
                if (pnlEl) pnlEl.textContent = fmtCurrency(data.total_pnl || 0);
            }
        });
    }
    
    // ============================================
    // NAVIGATION HANDLER
    // ============================================
    var sectionLoaders = {
        'predictions': loadPredictions,
        'intelligence': loadIntelligence,
        'systems': loadSystems,
        'agents': loadAgents,
        'consensus': loadConsensus,
        'simulation': loadSimulation,
        'shadow': loadShadow,
        'risk': loadRisk,
        'audit': loadAudit,
        'execution': loadExecution,
        'analytics': loadAnalytics,
        'arbitrage': loadArbitrage,
        'portfolio': loadPortfolio
    };
    
    function handleNavigation(section) {
        console.log('[MERID] Navigating to:', section);
        
        // Update sidebar active state
        $$('.sidebar-link').forEach(function(l) { l.classList.remove('active'); });
        var activeLink = document.querySelector('[data-section="' + section + '"]');
        if (activeLink) activeLink.classList.add('active');
        
        // Show/hide sections
        $$('.content-section').forEach(function(s) { s.classList.remove('active'); });
        var targetSection = $(section);
        if (targetSection) targetSection.classList.add('active');
        
        // Load section data
        var loader = sectionLoaders[section];
        if (loader) {
            setTimeout(loader, 50);
        }
    }
    
    // ============================================
    // INITIALIZATION
    // ============================================
    document.addEventListener('DOMContentLoaded', function() {
        console.log('[MERID] DOM Ready - Setting up navigation...');
        
        // Bind sidebar clicks
        $$('.sidebar-link').forEach(function(link) {
            link.addEventListener('click', function(e) {
                e.preventDefault();
                var section = this.getAttribute('data-section');
                handleNavigation(section);
            });
        });
        
        console.log('[MERID] Unified Control Center ready!');
    });
    
    // Expose for debugging
    window.MERID = { 
        loadPredictions: loadPredictions, 
        loadIntelligence: loadIntelligence, 
        loadAgents: loadAgents, 
        loadSystems: loadSystems, 
        handleNavigation: handleNavigation 
    };
})();
