-- =============================================================================
-- MERID PostgreSQL Schema
-- 
-- Tables for trading analytics:
-- - trades_executed: All executed trades
-- - bars_1m_*: 1-minute OHLCV bars per symbol
-- - agent_decisions: Agent trading decisions for audit
-- - risk_alerts: Risk management alerts
-- =============================================================================

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- =============================================================================
-- TRADES
-- =============================================================================

CREATE TABLE IF NOT EXISTS trades_executed (
    trade_id        TEXT PRIMARY KEY,
    symbol          TEXT NOT NULL,
    venue           TEXT NOT NULL,
    side            TEXT NOT NULL,  -- 'buy' or 'sell'
    price           DOUBLE PRECISION NOT NULL,
    quantity        DOUBLE PRECISION NOT NULL,
    notional        DOUBLE PRECISION,
    fee             DOUBLE PRECISION DEFAULT 0,
    agent_id        TEXT,
    trader_type     TEXT,  -- 'agent' or 'human'
    order_id        TEXT,
    is_simulated    BOOLEAN DEFAULT FALSE,
    executed_at     TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades_executed(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_agent ON trades_executed(agent_id);
CREATE INDEX IF NOT EXISTS idx_trades_executed_at ON trades_executed(executed_at DESC);

-- =============================================================================
-- BARS (1-minute OHLCV)
-- =============================================================================

CREATE TABLE IF NOT EXISTS bars_1m (
    symbol          TEXT NOT NULL,
    venue           TEXT NOT NULL,
    window_start    TIMESTAMPTZ NOT NULL,
    window_end      TIMESTAMPTZ NOT NULL,
    open_price      DOUBLE PRECISION,
    high_price      DOUBLE PRECISION,
    low_price       DOUBLE PRECISION,
    close_price     DOUBLE PRECISION,
    volume          DOUBLE PRECISION,
    vwap            DOUBLE PRECISION,
    tick_count      INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (symbol, window_end)
);

-- Convert to TimescaleDB hypertable for better time-series performance
SELECT create_hypertable('bars_1m', 'window_end', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_bars_symbol_time ON bars_1m(symbol, window_end DESC);

-- =============================================================================
-- AGENT DECISIONS
-- =============================================================================

CREATE TABLE IF NOT EXISTS agent_decisions (
    decision_id     TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL,
    role            TEXT,
    symbol          TEXT NOT NULL,
    vote            TEXT NOT NULL,  -- 'BULL', 'BEAR', 'NEUTRAL', 'HOLD'
    confidence      DOUBLE PRECISION,
    reasoning       TEXT,
    price_target    DOUBLE PRECISION,
    consensus_score DOUBLE PRECISION,
    decided_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_decisions_agent ON agent_decisions(agent_id);
CREATE INDEX IF NOT EXISTS idx_decisions_symbol ON agent_decisions(symbol);
CREATE INDEX IF NOT EXISTS idx_decisions_time ON agent_decisions(decided_at DESC);

-- =============================================================================
-- RISK ALERTS
-- =============================================================================

CREATE TABLE IF NOT EXISTS risk_alerts (
    alert_id        TEXT PRIMARY KEY,
    alert_type      TEXT NOT NULL,  -- 'drawdown', 'exposure', 'volatility', etc.
    severity        TEXT NOT NULL,  -- 'info', 'warning', 'critical'
    agent_id        TEXT,
    symbol          TEXT,
    message         TEXT NOT NULL,
    current_value   DOUBLE PRECISION,
    threshold       DOUBLE PRECISION,
    acknowledged    BOOLEAN DEFAULT FALSE,
    alerted_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_type ON risk_alerts(alert_type);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON risk_alerts(severity);
CREATE INDEX IF NOT EXISTS idx_alerts_time ON risk_alerts(alerted_at DESC);

-- =============================================================================
-- AGENT PERFORMANCE (for consensus weighting)
-- =============================================================================

CREATE TABLE IF NOT EXISTS agent_performance (
    agent_id        TEXT PRIMARY KEY,
    role            TEXT,
    total_trades    INTEGER DEFAULT 0,
    winning_trades  INTEGER DEFAULT 0,
    total_pnl       DOUBLE PRECISION DEFAULT 0,
    sharpe_ratio    DOUBLE PRECISION,
    max_drawdown    DOUBLE PRECISION,
    prediction_accuracy DOUBLE PRECISION,
    consensus_weight DOUBLE PRECISION DEFAULT 1.0,
    last_updated    TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- VIEWS
-- =============================================================================

-- Recent trades summary
CREATE OR REPLACE VIEW v_recent_trades AS
SELECT 
    symbol,
    COUNT(*) as trade_count,
    SUM(CASE WHEN side = 'buy' THEN quantity ELSE 0 END) as total_bought,
    SUM(CASE WHEN side = 'sell' THEN quantity ELSE 0 END) as total_sold,
    AVG(price) as avg_price,
    SUM(notional) as total_notional
FROM trades_executed
WHERE executed_at > NOW() - INTERVAL '24 hours'
GROUP BY symbol;

-- Agent performance leaderboard
CREATE OR REPLACE VIEW v_agent_leaderboard AS
SELECT 
    agent_id,
    role,
    total_trades,
    ROUND(winning_trades::numeric / NULLIF(total_trades, 0) * 100, 2) as win_rate_pct,
    ROUND(total_pnl::numeric, 2) as total_pnl,
    ROUND(sharpe_ratio::numeric, 2) as sharpe,
    ROUND(max_drawdown::numeric * 100, 2) as max_dd_pct,
    ROUND(consensus_weight::numeric, 2) as weight
FROM agent_performance
ORDER BY sharpe_ratio DESC NULLS LAST;

-- =============================================================================
-- FUNCTIONS
-- =============================================================================

-- Function to update agent performance from trades
CREATE OR REPLACE FUNCTION update_agent_performance()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO agent_performance (agent_id, total_trades, last_updated)
    VALUES (NEW.agent_id, 1, NOW())
    ON CONFLICT (agent_id) DO UPDATE
    SET total_trades = agent_performance.total_trades + 1,
        last_updated = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to update performance on new trade
DROP TRIGGER IF EXISTS trg_update_agent_performance ON trades_executed;
CREATE TRIGGER trg_update_agent_performance
AFTER INSERT ON trades_executed
FOR EACH ROW
WHEN (NEW.agent_id IS NOT NULL)
EXECUTE FUNCTION update_agent_performance();
