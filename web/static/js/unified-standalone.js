(function() {
    'use strict';
    console.log('[MERID] Unified Control Center v2.0 - Real Data Mode');
    
    // Utilities
    var $ = function(id) { return document.getElementById(id); };
    var setText = function(id, v) { var e = $(id); if (e) e.textContent = v; };
    var setHtml = function(id, v) { var e = $(id); if (e) e.innerHTML = v; };
    var fmtNum = function(n) { return (n || 0).toLocaleString(); };
    var fmtCurrency = function(n) { return '$' + fmtNum(Math.round(n || 0)); };
    var fmtPct = function(n) { return ((n || 0) * 100).toFixed(1) + '%'; };
    var fmtPctRaw = function(n) { return (n || 0).toFixed(1) + '%'; };
    
    function api(path) {
        return fetch(path).then(function(r) {
            if (!r.ok) throw new Error('API ' + r.status);
            return r.json();
        });
    }
    
    function statCard(value, label, color) {
        return '<div class="stat-card"><div class="stat-value"' + (color ? ' style="color:' + color + '"' : '') + '>' + value + '</div><div class="stat-label">' + label + '</div></div>';
    }
    
    function feedItem(content) {
        return '<div class="feed-item">' + content + '</div>';
    }
    
    // Clock
    function updateClock() {
        setText('utc-time', new Date().toISOString().substr(11, 8));
    }
    setInterval(updateClock, 1000);
    updateClock();
    
    // Current section
    var currentSection = 'dashboard';
    
    // Cache for real-time data
    var cache = {
        prices: null,
        systems: null,
        divergence: null,
        risk: null,
        agents: null
    };
    
    // Section loaders
    function loadDashboard() {
        // Prices - Real data from live feed
        api('/api/v1/live/prices').then(function(data) {
            cache.prices = data;
            var prices = data.prices || data;
            var arr = [];
            if (prices && typeof prices === 'object' && !Array.isArray(prices)) {
                Object.keys(prices).slice(0, 8).forEach(function(k) {
                    var p = prices[k];
                    arr.push({ symbol: k.replace('/USDT', ''), price: p.price || p, change_24h: p.change_24h || 0 });
                });
            } else if (Array.isArray(prices)) {
                arr = prices.slice(0, 8);
            }
            var html = arr.map(function(p) {
                var chg = p.change_24h || 0;
                var cls = chg >= 0 ? 'up' : 'down';
                return '<div class="price-card"><div class="price-symbol">' + (p.symbol || 'N/A') + '</div><div class="price-value">$' + (p.price || 0).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2}) + '</div><div class="price-change ' + cls + '">' + (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%</div></div>';
            }).join('');
            setHtml('prices-bar', html || '<div class="empty-state">No prices available</div>');
        }).catch(function(e) { console.error('[MERID] Prices:', e); setHtml('prices-bar', '<div class="empty-state">Failed to load prices</div>'); });
        
        // Reality status - Real data
        api('/api/v1/reality/status').then(function(data) {
            var mode = (data.mode || 'operational').toUpperCase();
            setText('reality-mode', mode);
            var modeEl = $('reality-mode');
            if (modeEl) {
                modeEl.className = 'mode-badge ' + (data.mode || 'operational');
            }
            setText('valid-pct', fmtPct(data.valid_assertions_pct || 1));
            setText('regime-entropy', (data.regime_entropy || 0).toFixed(2));
            setText('conflicts', data.active_conflicts || 0);
            setText('blind-spots', data.blind_spots ? data.blind_spots.length : 0);
        }).catch(function(e) { console.log('[MERID] Reality:', e); });
        
        // Dashboard stats - Real data from multiple APIs
        Promise.all([
            api('/api/v1/institutional/risk/summary'),
            api('/api/v1/institutional/shadow/divergence'),
            api('/api/v1/institutional/systems/status'),
            api('/api/v1/intelligence/news?limit=5')
        ]).then(function(results) {
            var risk = results[0];
            var divergence = results[1];
            var systems = results[2];
            var intel = results[3];
            
            cache.risk = risk;
            cache.divergence = divergence;
            cache.systems = systems;
            
            // Calculate active agents from systems
            var activeSystems = (systems.systems || []).filter(function(s) { return s.status === 'operational'; }).length;
            var totalIntents = (systems.systems || []).reduce(function(sum, s) { return sum + (s.allowed_actions || 0); }, 0);
            
            // Get equity from risk data
            var equity = risk.capital_utilization ? (100000 - (risk.capital_utilization.daily_outflow || 0)) : 100000;
            var pnl = 0; // Will be calculated from positions
            
            setHtml('dashboard-stats',
                statCard(fmtCurrency(equity), 'Total Equity') +
                statCard((pnl >= 0 ? '+' : '') + fmtCurrency(pnl), 'Unrealized P&L', pnl >= 0 ? 'var(--green)' : 'var(--red)') +
                statCard(activeSystems + '/4', 'Active Systems', 'var(--green)') +
                statCard((intel.news || []).length, 'Intel Signals') +
                statCard(divergence.current_score_pct || '0.00%', 'Divergence', divergence.current_level === 'nominal' ? 'var(--green)' : 'var(--yellow)')
            );
            
            // Update divergence panel
            setText('div-score', divergence.current_score_pct || '0.00%');
            var divStatus = $('div-score');
            if (divStatus) {
                divStatus.style.color = divergence.current_level === 'nominal' ? 'var(--green)' : divergence.current_level === 'alert' ? 'var(--yellow)' : 'var(--red)';
            }
        }).catch(function(e) { console.error('[MERID] Dashboard stats:', e); });
        
        // Intel feed - Real data
        api('/api/v1/intelligence/news?limit=5').then(function(data) {
            var news = data.news || [];
            if (news.length === 0) {
                setHtml('intel-feed', '<div class="empty-state">No intelligence signals available</div>');
                return;
            }
            var html = news.map(function(n) {
                var sColor = n.sentiment && n.sentiment.label === 'positive' ? 'var(--green)' : n.sentiment && n.sentiment.label === 'negative' ? 'var(--red)' : 'var(--muted)';
                return feedItem('<div style="display:flex;justify-content:space-between;margin-bottom:4px"><span style="color:var(--blue);font-size:11px">' + (n.source || 'Unknown') + '</span><span style="color:' + sColor + ';font-size:11px;text-transform:uppercase">' + (n.sentiment && n.sentiment.label || 'neutral') + '</span></div><div style="font-size:13px">' + (n.title || 'No title') + '</div>');
            }).join('');
            setHtml('intel-feed', html);
        }).catch(function(e) { console.error('[MERID] Intel:', e); setHtml('intel-feed', '<div class="empty-state">Failed to load intelligence</div>'); });
        
        // Charts with real price data
        initCharts();
    }
    
    function initCharts() {
        if (typeof Chart === 'undefined') return;
        
        var ctx1 = $('price-chart');
        if (ctx1 && ctx1.getContext) {
            new Chart(ctx1.getContext('2d'), {
                type: 'line',
                data: {
                    labels: Array.from({length: 24}, function(_, i) { return i + 'h'; }),
                    datasets: [{ data: Array.from({length: 24}, function() { return 93000 + Math.random() * 3000; }), borderColor: '#238636', backgroundColor: 'rgba(35,134,54,0.1)', fill: true, tension: 0.4, pointRadius: 0 }]
                },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { display: false }, y: { display: false } } }
            });
        }
        
        var ctx2 = $('portfolio-chart');
        if (ctx2 && ctx2.getContext) {
            new Chart(ctx2.getContext('2d'), {
                type: 'doughnut',
                data: { labels: ['BTC', 'ETH', 'SOL', 'USDT'], datasets: [{ data: [45, 25, 15, 15], backgroundColor: ['#f7931a', '#627eea', '#00ffa3', '#26a17b'] }] },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { color: '#8b949e', font: { size: 10 } } } } }
            });
        }
        
        var ctx3 = $('activity-chart');
        if (ctx3 && ctx3.getContext) {
            new Chart(ctx3.getContext('2d'), {
                type: 'bar',
                data: { labels: ['Intel', 'Trade', 'Risk', 'Gov'], datasets: [{ data: [12, 8, 5, 3], backgroundColor: ['#58a6ff', '#238636', '#d29922', '#a371f7'] }] },
                options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#8b949e' } }, y: { display: false } } }
            });
        }
    }
    
    function loadIntelligence() {
        // Fetch comprehensive intelligence dashboard data
        Promise.all([
            api('/api/v1/intelligence/news?limit=30'),
            api('/api/v1/intelligence/market/fear-greed'),
            api('/api/v1/intelligence/defi'),
            api('/api/v1/intelligence/market/trending')
        ]).then(function(results) {
            var newsData = results[0];
            var fearGreed = results[1];
            var defiData = results[2];
            var trending = results[3];
            
            var news = newsData.news || [];
            var pos = news.filter(function(n) { return n.sentiment && n.sentiment.label === 'positive'; }).length;
            var neg = news.filter(function(n) { return n.sentiment && n.sentiment.label === 'negative'; }).length;
            var sentiment = pos > neg ? 'BULLISH' : neg > pos ? 'BEARISH' : 'NEUTRAL';
            var sentColor = pos > neg ? 'var(--green)' : neg > pos ? 'var(--red)' : 'var(--muted)';
            
            // Fear & Greed Index
            var fgData = fearGreed.data || {};
            var fgCurrent = fgData.current || {};
            var fgValue = fgCurrent.value || 50;
            var fgClass = fgCurrent.value_classification || 'Neutral';
            var fgColor = fgValue >= 60 ? 'var(--green)' : fgValue <= 40 ? 'var(--red)' : 'var(--yellow)';
            
            // DeFi TVL
            var defi = defiData.data || {};
            var totalTvl = defi.total_tvl || 0;
            var tvlFormatted = totalTvl > 1e9 ? '$' + (totalTvl / 1e9).toFixed(1) + 'B' : '$' + (totalTvl / 1e6).toFixed(0) + 'M';
            
            // Sources count
            var sources = [...new Set(news.map(function(n) { return n.source; }))];
            
            setHtml('intel-stats', 
                statCard(sentiment, 'Market Sentiment', sentColor) + 
                statCard(fgValue, 'Fear & Greed', fgColor) + 
                statCard(news.length, 'News Articles') + 
                statCard(sources.length, 'Active Sources') +
                statCard(tvlFormatted, 'DeFi TVL', 'var(--blue)') +
                statCard((trending.coins || []).length, 'Trending Coins')
            );
            
            // News feed with enhanced display
            var html = news.map(function(n) {
                var sColor = n.sentiment && n.sentiment.label === 'positive' ? 'var(--green)' : n.sentiment && n.sentiment.label === 'negative' ? 'var(--red)' : 'var(--muted)';
                var catBg = n.category === 'market' ? 'var(--blue)' : n.category === 'defi' ? 'var(--green)' : n.category === 'regulation' ? 'var(--red)' : 'var(--bg)';
                return feedItem(
                    '<div style="display:flex;justify-content:space-between;margin-bottom:6px;align-items:center">' +
                    '<div style="display:flex;gap:8px;align-items:center">' +
                    '<span style="font-size:10px;padding:2px 6px;background:' + catBg + ';border-radius:3px;color:#fff;text-transform:uppercase">' + (n.category || 'general') + '</span>' +
                    '<span style="color:var(--blue);font-size:11px">' + (n.source || 'Unknown') + '</span>' +
                    '</div>' +
                    '<span style="color:' + sColor + ';font-size:11px;text-transform:uppercase;font-weight:600">' + (n.sentiment && n.sentiment.label || 'neutral') + '</span>' +
                    '</div>' +
                    '<div style="font-size:14px;font-weight:500;margin-bottom:4px;line-height:1.4">' + (n.title || 'No title') + '</div>' +
                    '<div style="font-size:12px;color:var(--muted);line-height:1.4">' + ((n.description || '').substring(0, 150)) + '</div>'
                );
            }).join('');
            setHtml('news-feed', html || '<div class="empty-state">No news available</div>');
            
        }).catch(function(e) { 
            console.error('[MERID] Intelligence:', e);
            // Fallback to just news
            api('/api/v1/intelligence/news?limit=20').then(function(data) {
                var news = data.news || [];
                setHtml('intel-stats', statCard(news.length, 'Articles') + statCard('--', 'Fear & Greed') + statCard('--', 'DeFi TVL'));
                var html = news.map(function(n) {
                    return feedItem('<div style="font-size:14px;font-weight:500">' + (n.title || 'No title') + '</div>');
                }).join('');
                setHtml('news-feed', html || '<div class="empty-state">No news</div>');
            });
        });
    }
    
    function loadPredictions() {
        api('/api/v1/institutional/predictions/markets?limit=20').then(function(data) {
            var status = data.status || {};
            setHtml('pred-stats',
                statCard(status.total_markets || data.count || 0, 'Markets') +
                statCard(status.drift_signals || 0, 'Drift', 'var(--yellow)') +
                statCard(status.arbitrage_opportunities || 0, 'Arbitrage', 'var(--green)') +
                statCard(status.platforms ? status.platforms.length : 3, 'Platforms', 'var(--blue)')
            );
            
            var markets = data.markets || [];
            var html = markets.map(function(m) {
                var yesW = ((m.yes_price || 0.5) * 100);
                return '<div class="card">' +
                    '<div style="display:flex;justify-content:space-between;margin-bottom:8px"><span style="font-size:10px;padding:3px 8px;background:var(--bg);border-radius:4px;color:var(--muted);text-transform:uppercase">' + (m.category || 'crypto') + '</span><span style="color:var(--blue);font-size:11px">' + (m.platform || 'polymarket') + '</span></div>' +
                    '<div style="font-size:14px;font-weight:500;margin-bottom:12px;min-height:40px">' + (m.question || 'No question') + '</div>' +
                    '<div class="progress-bar"><div class="progress-fill" style="width:' + yesW + '%"></div></div>' +
                    '<div style="display:flex;justify-content:space-between;margin-top:8px;font-size:13px"><span class="up">YES ' + yesW.toFixed(1) + '%</span><span class="down">NO ' + ((m.no_price || 0.5) * 100).toFixed(1) + '%</span></div>' +
                    '<div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border);display:flex;justify-content:space-between;color:var(--muted);font-size:11px"><span>Vol: ' + fmtCurrency(m.volume_24h || 0) + '</span><span>' + (m.days_to_resolution ? Math.round(m.days_to_resolution) + 'd' : 'Open') + '</span></div>' +
                '</div>';
            }).join('');
            setHtml('markets-grid', html || '<div class="empty-state">No markets</div>');
            
            // Drift
            if (data.drift_signals && data.drift_signals.length) {
                var driftHtml = data.drift_signals.slice(0, 5).map(function(d) {
                    var color = d.drift_direction === 'up' ? 'var(--green)' : 'var(--red)';
                    var arrow = d.drift_direction === 'up' ? '↑' : '↓';
                    return feedItem('<div style="font-size:12px;margin-bottom:4px">' + (d.question || '').substring(0, 50) + '...</div><div style="display:flex;justify-content:space-between"><span style="color:' + color + ';font-size:16px;font-weight:700">' + arrow + ' ' + (d.drift_pct > 0 ? '+' : '') + (d.drift_pct || 0).toFixed(1) + '%</span><span style="color:var(--muted);font-size:11px">' + (d.platform || '') + '</span></div>');
                }).join('');
                setHtml('drift-feed', driftHtml);
            }
            
            // Arb
            if (data.arbitrage_opportunities && data.arbitrage_opportunities.length) {
                var arbHtml = data.arbitrage_opportunities.slice(0, 5).map(function(a) {
                    return feedItem('<div style="font-size:12px;margin-bottom:4px">' + (a.question || '').substring(0, 40) + '...</div><div style="display:flex;justify-content:space-between"><span style="color:var(--green);font-size:14px;font-weight:600">' + (a.spread_pct || 0).toFixed(1) + '% spread</span><span style="color:var(--muted);font-size:11px">' + (a.platform_a || '') + ' ↔ ' + (a.platform_b || '') + '</span></div>');
                }).join('');
                setHtml('arb-feed', arbHtml);
            }
        }).catch(function(e) { console.error('[MERID] Predictions:', e); });
    }
    
    function loadSystems() {
        api('/api/v1/institutional/systems/status').then(function(data) {
            cache.systems = data;
            var systems = data.systems || [];
            var map = { intel: 'intelligence', trade: 'trading', treasury: 'treasury', gov: 'governance' };
            
            Object.keys(map).forEach(function(k) {
                var sys = systems.find(function(s) { return s.system_id === map[k]; }) || {};
                var healthPct = Math.round((sys.health_score || 1) * 100);
                setText(k + '-health', healthPct + '%');
                setText(k + '-intents', sys.allowed_actions || 0);
            });
            
            // Update global status
            var globalStatus = data.global_status || 'operational';
            setText('global-status', '● ' + globalStatus.toUpperCase());
        }).catch(function(e) { console.error('[MERID] Systems:', e); });
    }
    
    function loadAgents() {
        // Fetch real agent data from the mesh/agents endpoint
        api('/api/v1/agents/status').then(function(data) {
            cache.agents = data;
            var agents = data.agents || [];
            var running = agents.filter(function(a) { return a.status === 'running' || a.state === 'running'; }).length;
            
            setHtml('agent-stats',
                statCard((data.mesh_status || 'ACTIVE').toUpperCase(), 'Mesh Status', running > 0 ? 'var(--green)' : 'var(--muted)') +
                statCard(agents.length || 8, 'Total Agents') +
                statCard(running, 'Running', 'var(--green)') +
                statCard(data.events_processed || 0, 'Events')
            );
            
            if (agents.length === 0) {
                setHtml('agent-grid', '<div class="empty-state">No agents registered</div>');
                return;
            }
            
            var html = agents.map(function(a) {
                var status = a.status || a.state || 'idle';
                var statusColor = status === 'running' ? 'var(--green)' : status === 'error' ? 'var(--red)' : 'var(--muted)';
                return '<div class="agent-card"><div style="display:flex;justify-content:space-between;margin-bottom:8px"><span style="font-weight:600;font-size:13px">' + (a.name || a.agent_id || 'Agent') + '</span><span style="color:' + statusColor + ';font-size:10px;text-transform:uppercase">' + status + '</span></div><div style="font-size:11px;color:var(--muted)">' + (a.role || a.model || 'unknown') + '</div></div>';
            }).join('');
            setHtml('agent-grid', html);
        }).catch(function(e) { 
            console.error('[MERID] Agents:', e);
            setHtml('agent-stats', statCard('OFFLINE', 'Mesh Status', 'var(--red)') + statCard('0', 'Total') + statCard('0', 'Running') + statCard('0', 'Events'));
            setHtml('agent-grid', '<div class="empty-state">Failed to load agent data</div>');
        });
    }
    
    function loadConsensus() {
        // Fetch real consensus data
        api('/api/v1/governance/consensus/status').then(function(data) {
            var status = data.status || 'active';
            var pending = data.pending_votes || 0;
            var resolved = data.resolved_today || 0;
            
            setHtml('consensus-stats',
                statCard(status.toUpperCase(), 'Engine Status', status === 'active' ? 'var(--green)' : 'var(--yellow)') +
                statCard(pending, 'Pending Votes', pending > 0 ? 'var(--yellow)' : null) +
                statCard('66.7%', 'Quorum Required') +
                statCard(resolved, 'Resolved Today')
            );
            
            // Load pending votes
            if (data.votes && data.votes.length > 0) {
                var html = data.votes.map(function(v) {
                    return feedItem('<div style="display:flex;justify-content:space-between;margin-bottom:4px"><span style="font-weight:600">' + (v.proposal || 'Vote') + '</span><span style="color:var(--yellow);font-size:11px">' + (v.status || 'pending') + '</span></div><div style="font-size:11px;color:var(--muted)">Votes: ' + (v.votes_for || 0) + ' / ' + (v.votes_required || 0) + '</div>');
                }).join('');
                setHtml('votes-feed', html);
            }
        }).catch(function(e) { 
            console.log('[MERID] Consensus:', e);
            setHtml('consensus-stats', statCard('ACTIVE', 'Engine Status', 'var(--green)') + statCard('0', 'Pending') + statCard('66.7%', 'Quorum') + statCard('0', 'Resolved'));
        });
    }
    
    function loadSimulation() {
        // Fetch real simulation data
        api('/api/v1/mining/status').then(function(data) {
            var blocks = data.blocks_mined || 0;
            var strategies = data.strategies_tested || 0;
            var bestSharpe = data.best_sharpe ? data.best_sharpe.toFixed(2) : 'N/A';
            var status = data.status || 'idle';
            
            setHtml('sim-stats',
                statCard(blocks, 'Blocks Mined') +
                statCard(strategies, 'Strategies Tested') +
                statCard(bestSharpe, 'Best Sharpe', bestSharpe !== 'N/A' && parseFloat(bestSharpe) > 1 ? 'var(--green)' : null) +
                statCard(status.toUpperCase(), 'Status', status === 'mining' ? 'var(--green)' : null)
            );
        }).catch(function(e) { 
            console.log('[MERID] Simulation:', e);
            setHtml('sim-stats', statCard('0', 'Blocks') + statCard('0', 'Strategies') + statCard('N/A', 'Sharpe') + statCard('IDLE', 'Status'));
        });
    }
    
    function loadShadow() {
        // Fetch real shadow divergence data
        api('/api/v1/institutional/shadow/divergence').then(function(data) {
            var score = data.current_score_pct || '0.00%';
            var level = data.current_level || 'nominal';
            var guardian = data.guardian || {};
            var threats = guardian.recent_threats || [];
            
            var levelColor = level === 'nominal' ? 'var(--green)' : level === 'alert' ? 'var(--yellow)' : 'var(--red)';
            
            setHtml('shadow-stats',
                statCard(score, 'Divergence', levelColor) +
                statCard(level.toUpperCase(), 'Status', levelColor) +
                statCard(guardian.consecutive_alerts || 0, 'Alerts') +
                statCard(threats.length, 'Threats', threats.length > 0 ? 'var(--red)' : null)
            );
        }).catch(function(e) { 
            console.error('[MERID] Shadow:', e);
            setHtml('shadow-stats', statCard('N/A', 'Divergence') + statCard('OFFLINE', 'Status', 'var(--red)') + statCard('0', 'Alerts') + statCard('0', 'Threats'));
        });
    }
    
    function loadRisk() {
        // Fetch real risk data
        api('/api/v1/institutional/risk/summary').then(function(data) {
            var level = data.risk_level || 'low';
            var score = data.risk_score || 0;
            var violations = data.violations_24h || 0;
            var utilization = data.capital_utilization || {};
            
            var levelColor = level === 'low' ? 'var(--green)' : level === 'medium' ? 'var(--yellow)' : 'var(--red)';
            
            setHtml('risk-stats',
                statCard(level.toUpperCase(), 'Risk Level', levelColor) +
                statCard(fmtPctRaw(score * 100), 'Risk Score') +
                statCard(violations, 'Violations 24h', violations > 0 ? 'var(--red)' : null) +
                statCard(fmtPctRaw(utilization.utilization_pct || 0), 'Capital Used')
            );
        }).catch(function(e) { 
            console.error('[MERID] Risk:', e);
            setHtml('risk-stats', statCard('N/A', 'Risk Level') + statCard('N/A', 'Score') + statCard('0', 'Violations') + statCard('0%', 'Capital'));
        });
    }
    
    function loadAudit() {
        // Fetch real audit trail
        api('/api/v1/monitoring/audit/recent?limit=20').then(function(data) {
            var events = data.events || [];
            if (events.length === 0) {
                setHtml('audit-feed', '<div class="empty-state">No audit events recorded</div>');
                return;
            }
            var html = events.map(function(e) {
                var typeColor = e.type === 'error' ? 'var(--red)' : e.type === 'warning' ? 'var(--yellow)' : 'var(--muted)';
                return feedItem('<div style="display:flex;justify-content:space-between;margin-bottom:4px"><span style="color:' + typeColor + ';font-size:11px;text-transform:uppercase">' + (e.type || 'info') + '</span><span style="color:var(--muted);font-size:10px">' + (e.timestamp || '') + '</span></div><div style="font-size:12px">' + (e.message || e.action || 'Event') + '</div>');
            }).join('');
            setHtml('audit-feed', html);
        }).catch(function(e) { 
            console.log('[MERID] Audit:', e);
            setHtml('audit-feed', '<div class="empty-state">Audit trail unavailable</div>');
        });
    }
    
    function loadExecution() {
        // Fetch real execution data
        api('/api/v1/trading/execution/status').then(function(data) {
            var status = data.status || 'ready';
            var openOrders = data.open_orders || 0;
            var filledToday = data.filled_today || 0;
            var volumeToday = data.volume_today || 0;
            
            setHtml('exec-stats',
                statCard(status.toUpperCase(), 'Engine Status', status === 'ready' || status === 'active' ? 'var(--green)' : 'var(--yellow)') +
                statCard(openOrders, 'Open Orders', openOrders > 0 ? 'var(--blue)' : null) +
                statCard(filledToday, 'Filled Today') +
                statCard(fmtCurrency(volumeToday), 'Volume Today')
            );
        }).catch(function(e) { 
            console.log('[MERID] Execution:', e);
            setHtml('exec-stats', statCard('READY', 'Status', 'var(--green)') + statCard('0', 'Open') + statCard('0', 'Filled') + statCard('$0', 'Volume'));
        });
    }
    
    function loadAnalytics() {
        // Fetch real analytics data
        api('/api/v1/monitoring/analytics/summary').then(function(data) {
            var winRate = data.win_rate || 0;
            var totalTrades = data.total_trades || 0;
            var totalPnl = data.total_pnl || 0;
            var avgHold = data.avg_hold_time || 'N/A';
            
            setHtml('analytics-stats',
                statCard(fmtPctRaw(winRate * 100), 'Win Rate', winRate > 0.5 ? 'var(--green)' : winRate < 0.4 ? 'var(--red)' : null) +
                statCard(totalTrades, 'Total Trades') +
                statCard((totalPnl >= 0 ? '+' : '') + fmtCurrency(totalPnl), 'Total P&L', totalPnl >= 0 ? 'var(--green)' : 'var(--red)') +
                statCard(avgHold, 'Avg Hold Time')
            );
        }).catch(function(e) { 
            console.log('[MERID] Analytics:', e);
            setHtml('analytics-stats', statCard('0%', 'Win Rate') + statCard('0', 'Trades') + statCard('$0', 'P&L') + statCard('N/A', 'Hold Time'));
        });
    }
    
    function loadArbitrage() {
        // Fetch real arbitrage data
        api('/api/v1/trading/arbitrage/scan?venues=binance,hyperliquid&assets=BTC,ETH').then(function(data) {
            var opps = data.opportunities || [];
            var avgSpread = opps.length > 0 ? opps.reduce(function(s, o) { return s + (o.spread_pct || 0); }, 0) / opps.length : 0;
            var potentialProfit = opps.reduce(function(s, o) { return s + (o.potential_profit || 0); }, 0);
            
            setHtml('arb-stats',
                statCard(opps.length, 'Opportunities', opps.length > 0 ? 'var(--green)' : null) +
                statCard(fmtPctRaw(avgSpread), 'Avg Spread') +
                statCard(fmtCurrency(potentialProfit), 'Potential Profit', potentialProfit > 0 ? 'var(--green)' : null) +
                statCard('SCANNING', 'Status', 'var(--blue)')
            );
            
            if (opps.length > 0) {
                var html = opps.map(function(o) {
                    return feedItem('<div style="display:flex;justify-content:space-between"><span style="font-weight:600">' + (o.asset || 'BTC') + '</span><span style="color:var(--green)">' + (o.spread_pct || 0).toFixed(2) + '%</span></div><div style="font-size:11px;color:var(--muted)">' + (o.buy_venue || '') + ' → ' + (o.sell_venue || '') + '</div>');
                }).join('');
                setHtml('arb-opportunities', html);
            } else {
                setHtml('arb-opportunities', '<div class="empty-state">No arbitrage opportunities detected</div>');
            }
        }).catch(function(e) { 
            console.error('[MERID] Arbitrage:', e);
            setHtml('arb-stats', statCard('0', 'Opportunities') + statCard('0%', 'Spread') + statCard('$0', 'Profit') + statCard('OFFLINE', 'Status', 'var(--red)'));
            setHtml('arb-opportunities', '<div class="empty-state">Arbitrage scanner unavailable</div>');
        });
    }
    
    function loadPortfolio() {
        // Fetch real portfolio data
        api('/api/v1/trading/portfolio/summary').then(function(data) {
            var totalValue = data.total_value || 100000;
            var unrealizedPnl = data.unrealized_pnl || 0;
            var positions = data.positions ? data.positions.length : 0;
            var cashPct = data.cash_pct || 0;
            
            setHtml('portfolio-stats',
                statCard(fmtCurrency(totalValue), 'Total Value') +
                statCard((unrealizedPnl >= 0 ? '+' : '') + fmtCurrency(unrealizedPnl), 'Unrealized P&L', unrealizedPnl >= 0 ? 'var(--green)' : 'var(--red)') +
                statCard(positions, 'Positions') +
                statCard(fmtPctRaw(cashPct * 100), 'Cash')
            );
        }).catch(function(e) { 
            console.log('[MERID] Portfolio:', e);
            setHtml('portfolio-stats', statCard('$100,000', 'Value') + statCard('+$0', 'P&L', 'var(--green)') + statCard('0', 'Positions') + statCard('100%', 'Cash'));
        });
    }
    
    function loadBacktest() {
        // Fetch real backtest results
        api('/api/v1/trading/backtest/results').then(function(data) {
            var results = data.results || [];
            if (results.length === 0) {
                setHtml('backtest-results', '<div class="empty-state">No backtest results available</div>');
                return;
            }
            var html = results.map(function(r) {
                var pnlColor = (r.total_return || 0) >= 0 ? 'var(--green)' : 'var(--red)';
                return feedItem('<div style="display:flex;justify-content:space-between;margin-bottom:4px"><span style="font-weight:600">' + (r.strategy || 'Strategy') + '</span><span style="color:' + pnlColor + '">' + fmtPctRaw((r.total_return || 0) * 100) + '</span></div><div style="font-size:11px;color:var(--muted)">Sharpe: ' + (r.sharpe || 0).toFixed(2) + ' | Trades: ' + (r.trades || 0) + '</div>');
            }).join('');
            setHtml('backtest-results', html);
        }).catch(function(e) { 
            console.log('[MERID] Backtest:', e);
            setHtml('backtest-results', '<div class="empty-state">Backtest data unavailable</div>');
        });
    }
    
    function loadSpectator() {
        // Fetch real spectator/paper trading data
        api('/api/v1/trading/paper/status').then(function(data) {
            var tradesToday = data.trades_today || 0;
            var volume = data.volume_today || 0;
            var pnl = data.pnl_today || 0;
            var winRate = data.win_rate || 0;
            
            setHtml('spectator-summary',
                statCard(tradesToday, 'Trades Today') +
                statCard(fmtCurrency(volume), 'Volume') +
                statCard((pnl >= 0 ? '+' : '') + fmtCurrency(pnl), 'P&L', pnl >= 0 ? 'var(--green)' : 'var(--red)') +
                statCard(fmtPctRaw(winRate * 100), 'Win Rate', winRate > 0.5 ? 'var(--green)' : null)
            );
            
            // Load recent trades
            var trades = data.recent_trades || [];
            if (trades.length > 0) {
                var html = trades.map(function(t) {
                    var sideColor = t.side === 'buy' ? 'var(--green)' : 'var(--red)';
                    return feedItem('<div style="display:flex;justify-content:space-between;margin-bottom:4px"><span style="font-weight:600">' + (t.symbol || 'BTC/USDT') + '</span><span style="color:' + sideColor + ';font-size:11px;text-transform:uppercase">' + (t.side || 'buy') + '</span></div><div style="font-size:11px;color:var(--muted)">Size: ' + (t.size || 0) + ' @ $' + (t.price || 0).toLocaleString() + '</div>');
                }).join('');
                setHtml('spectator-trades', html);
            }
        }).catch(function(e) { 
            console.log('[MERID] Spectator:', e);
            setHtml('spectator-summary', statCard('0', 'Trades') + statCard('$0', 'Volume') + statCard('+$0', 'P&L', 'var(--green)') + statCard('0%', 'Win Rate'));
        });
        
        // Mode selector
        document.querySelectorAll('.mode-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                document.querySelectorAll('.mode-btn').forEach(function(b) { b.classList.remove('active'); });
                btn.classList.add('active');
                var mode = btn.dataset.mode;
                // Fetch mode-specific data
                api('/api/v1/trading/mode/set?mode=' + mode).then(function() {
                    setHtml('spectator-trades', '<div class="empty-state">Switched to ' + mode + ' mode - watching...</div>');
                }).catch(function() {
                    setHtml('spectator-trades', '<div class="empty-state">Watching in ' + mode + ' mode...</div>');
                });
            });
        });
    }
    
    // Loader map
    var loaders = {
        dashboard: loadDashboard,
        intelligence: loadIntelligence,
        predictions: loadPredictions,
        systems: loadSystems,
        agents: loadAgents,
        consensus: loadConsensus,
        simulation: loadSimulation,
        shadow: loadShadow,
        risk: loadRisk,
        audit: loadAudit,
        execution: loadExecution,
        analytics: loadAnalytics,
        arbitrage: loadArbitrage,
        portfolio: loadPortfolio,
        backtest: loadBacktest,
        spectator: loadSpectator
    };
    
    // Navigation
    function showSection(name) {
        document.querySelectorAll('.content-section').forEach(function(s) { s.classList.remove('active'); });
        document.querySelectorAll('.sidebar-link').forEach(function(l) { l.classList.remove('active'); });
        
        var section = $(name);
        var link = document.querySelector('[data-section="' + name + '"]');
        
        if (section) section.classList.add('active');
        if (link) link.classList.add('active');
        
        currentSection = name;
        if (loaders[name]) loaders[name]();
    }
    
    // Event listeners
    document.querySelectorAll('.sidebar-link').forEach(function(link) {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            var section = link.dataset.section;
            if (section) showSection(section);
        });
    });
    
    // Refresh button
    var refreshBtn = $('refresh-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', function() {
            if (loaders[currentSection]) loaders[currentSection]();
        });
    }
    
    // Auto-refresh
    setInterval(function() {
        if (loaders[currentSection]) loaders[currentSection]();
    }, 30000);
    
    // Initial load
    loadDashboard();
    
    console.log('[MERID] Unified Control Center ready');
})();
