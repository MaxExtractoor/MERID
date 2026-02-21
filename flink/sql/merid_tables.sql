-- =============================================================================
-- MERID Flink SQL Table Definitions
-- 
-- Event-time windowed streaming tables for trading data processing.
-- Uses watermarks for proper out-of-order event handling.
--
-- Run with: docker exec -it merid-flink-sql bin/sql-client.sh -f /opt/flink/sql/merid_tables.sql
-- =============================================================================

-- =============================================================================
-- CONFIGURATION
-- =============================================================================

SET 'execution.runtime-mode' = 'streaming';
SET 'table.exec.state.ttl' = '86400000';  -- 24h state retention
SET 'pipeline.auto-watermark-interval' = '200ms';

-- =============================================================================
-- SOURCE TABLES: Raw Price Ticks from Kafka
-- =============================================================================

-- BTC/USD from Kraken
CREATE TABLE IF NOT EXISTS ticks_kraken_btcusd (
    symbol        STRING,
    venue         STRING,
    price         DOUBLE,
    volume        DOUBLE,
    bid           DOUBLE,
    ask           DOUBLE,
    event_time    TIMESTAMP(3),
    -- Watermark: allow 2 seconds of out-of-order data
    WATERMARK FOR event_time AS event_time - INTERVAL '2' SECOND
) WITH (
    'connector' = 'kafka',
    'topic' = 'prices.kraken.BTCUSD',
    'properties.bootstrap.servers' = 'redpanda:9092',
    'properties.group.id' = 'flink-sql-ticks-btcusd',
    'format' = 'json',
    'json.timestamp-format.standard' = 'ISO-8601',
    'json.fail-on-missing-field' = 'false',
    'json.ignore-parse-errors' = 'true',
    'scan.startup.mode' = 'latest-offset'
);

-- ETH/USD from Kraken
CREATE TABLE IF NOT EXISTS ticks_kraken_ethusd (
    symbol        STRING,
    venue         STRING,
    price         DOUBLE,
    volume        DOUBLE,
    bid           DOUBLE,
    ask           DOUBLE,
    event_time    TIMESTAMP(3),
    WATERMARK FOR event_time AS event_time - INTERVAL '2' SECOND
) WITH (
    'connector' = 'kafka',
    'topic' = 'prices.kraken.ETHUSD',
    'properties.bootstrap.servers' = 'redpanda:9092',
    'properties.group.id' = 'flink-sql-ticks-ethusd',
    'format' = 'json',
    'json.timestamp-format.standard' = 'ISO-8601',
    'json.fail-on-missing-field' = 'false',
    'json.ignore-parse-errors' = 'true',
    'scan.startup.mode' = 'latest-offset'
);

-- BTC/USDT from Binance
CREATE TABLE IF NOT EXISTS ticks_binance_btcusdt (
    symbol        STRING,
    venue         STRING,
    price         DOUBLE,
    volume        DOUBLE,
    bid           DOUBLE,
    ask           DOUBLE,
    event_time    TIMESTAMP(3),
    WATERMARK FOR event_time AS event_time - INTERVAL '2' SECOND
) WITH (
    'connector' = 'kafka',
    'topic' = 'prices.binance.BTCUSDT',
    'properties.bootstrap.servers' = 'redpanda:9092',
    'properties.group.id' = 'flink-sql-ticks-binance-btc',
    'format' = 'json',
    'json.timestamp-format.standard' = 'ISO-8601',
    'json.fail-on-missing-field' = 'false',
    'json.ignore-parse-errors' = 'true',
    'scan.startup.mode' = 'latest-offset'
);

-- =============================================================================
-- SINK TABLES: 1-Minute OHLCV Bars
-- =============================================================================

-- 1-minute bars for BTC/USD
CREATE TABLE IF NOT EXISTS bars_1m_kraken_btcusd (
    symbol        STRING,
    venue         STRING,
    window_start  TIMESTAMP(3),
    window_end    TIMESTAMP(3),
    open_price    DOUBLE,
    high_price    DOUBLE,
    low_price     DOUBLE,
    close_price   DOUBLE,
    volume        DOUBLE,
    tick_count    BIGINT,
    vwap          DOUBLE,
    PRIMARY KEY (symbol, window_end) NOT ENFORCED
) WITH (
    'connector' = 'upsert-kafka',
    'topic' = 'bars.1m.kraken.BTCUSD',
    'properties.bootstrap.servers' = 'redpanda:9092',
    'key.format' = 'json',
    'value.format' = 'json'
);

-- 1-minute bars for ETH/USD
CREATE TABLE IF NOT EXISTS bars_1m_kraken_ethusd (
    symbol        STRING,
    venue         STRING,
    window_start  TIMESTAMP(3),
    window_end    TIMESTAMP(3),
    open_price    DOUBLE,
    high_price    DOUBLE,
    low_price     DOUBLE,
    close_price   DOUBLE,
    volume        DOUBLE,
    tick_count    BIGINT,
    vwap          DOUBLE,
    PRIMARY KEY (symbol, window_end) NOT ENFORCED
) WITH (
    'connector' = 'upsert-kafka',
    'topic' = 'bars.1m.kraken.ETHUSD',
    'properties.bootstrap.servers' = 'redpanda:9092',
    'key.format' = 'json',
    'value.format' = 'json'
);

-- =============================================================================
-- SINK TABLES: Enriched Features
-- =============================================================================

-- Enriched features with rolling metrics
CREATE TABLE IF NOT EXISTS features_kraken_btcusd (
    symbol          STRING,
    venue           STRING,
    window_end      TIMESTAMP(3),
    -- OHLCV
    open_price      DOUBLE,
    high_price      DOUBLE,
    low_price       DOUBLE,
    close_price     DOUBLE,
    volume          DOUBLE,
    -- Derived
    vwap            DOUBLE,
    return_pct      DOUBLE,
    range_pct       DOUBLE,
    tick_count      BIGINT,
    -- Metadata
    processed_at    TIMESTAMP(3),
    PRIMARY KEY (symbol, window_end) NOT ENFORCED
) WITH (
    'connector' = 'upsert-kafka',
    'topic' = 'features.kraken.BTCUSD',
    'properties.bootstrap.servers' = 'redpanda:9092',
    'key.format' = 'json',
    'value.format' = 'json'
);

-- =============================================================================
-- STREAMING JOBS: 1-Minute Bar Aggregation
-- =============================================================================

-- BTC/USD 1-minute bars
INSERT INTO bars_1m_kraken_btcusd
SELECT
    symbol,
    venue,
    WINDOW_START AS window_start,
    WINDOW_END AS window_end,
    FIRST_VALUE(price) AS open_price,
    MAX(price) AS high_price,
    MIN(price) AS low_price,
    LAST_VALUE(price) AS close_price,
    SUM(volume) AS volume,
    COUNT(*) AS tick_count,
    CASE 
        WHEN SUM(volume) > 0 THEN SUM(price * volume) / SUM(volume)
        ELSE LAST_VALUE(price)
    END AS vwap
FROM TABLE(
    TUMBLE(TABLE ticks_kraken_btcusd, DESCRIPTOR(event_time), INTERVAL '1' MINUTE)
)
GROUP BY symbol, venue, WINDOW_START, WINDOW_END;

-- ETH/USD 1-minute bars
INSERT INTO bars_1m_kraken_ethusd
SELECT
    symbol,
    venue,
    WINDOW_START AS window_start,
    WINDOW_END AS window_end,
    FIRST_VALUE(price) AS open_price,
    MAX(price) AS high_price,
    MIN(price) AS low_price,
    LAST_VALUE(price) AS close_price,
    SUM(volume) AS volume,
    COUNT(*) AS tick_count,
    CASE 
        WHEN SUM(volume) > 0 THEN SUM(price * volume) / SUM(volume)
        ELSE LAST_VALUE(price)
    END AS vwap
FROM TABLE(
    TUMBLE(TABLE ticks_kraken_ethusd, DESCRIPTOR(event_time), INTERVAL '1' MINUTE)
)
GROUP BY symbol, venue, WINDOW_START, WINDOW_END;

-- =============================================================================
-- STREAMING JOBS: Feature Enrichment
-- =============================================================================

-- BTC/USD enriched features (5-minute window for volatility)
INSERT INTO features_kraken_btcusd
SELECT
    symbol,
    venue,
    WINDOW_END AS window_end,
    FIRST_VALUE(price) AS open_price,
    MAX(price) AS high_price,
    MIN(price) AS low_price,
    LAST_VALUE(price) AS close_price,
    SUM(volume) AS volume,
    CASE 
        WHEN SUM(volume) > 0 THEN SUM(price * volume) / SUM(volume)
        ELSE LAST_VALUE(price)
    END AS vwap,
    -- Return percentage
    CASE 
        WHEN FIRST_VALUE(price) > 0 
        THEN (LAST_VALUE(price) - FIRST_VALUE(price)) / FIRST_VALUE(price)
        ELSE 0
    END AS return_pct,
    -- Range percentage (high-low / low)
    CASE 
        WHEN MIN(price) > 0 
        THEN (MAX(price) - MIN(price)) / MIN(price)
        ELSE 0
    END AS range_pct,
    COUNT(*) AS tick_count,
    CURRENT_TIMESTAMP AS processed_at
FROM TABLE(
    TUMBLE(TABLE ticks_kraken_btcusd, DESCRIPTOR(event_time), INTERVAL '1' MINUTE)
)
GROUP BY symbol, venue, WINDOW_START, WINDOW_END;
