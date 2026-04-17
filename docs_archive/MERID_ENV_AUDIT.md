# MERID Environment Audit

Every environment variable referenced in the repo is cataloged below. Real secrets must stay outside git; use these placeholders with your secrets manager.

## Key Inventory

| Name | Sensitivity | Description |
| --- | --- | --- |
| AGENT_CONSENSUS_THRESHOLD | SENSITIVE | Agent orchestration parameter. |
| AGENT_DEFAULT_MODEL | LOW_RISK | Agent orchestration parameter. |
| AGENT_NUM_AGENTS | LOW_RISK | Agent orchestration parameter. |
| AGENT_VOTE_TIMEOUT | SENSITIVE | Agent orchestration parameter. |
| ALERT_CHECK_INTERVAL | SENSITIVE | Alerting throttle parameter. |
| ALERT_MAX_PER_SYMBOL | LOW_RISK | Alerting throttle parameter. |
| ALERT_RETENTION_HOURS | LOW_RISK | Alerting throttle parameter. |
| ALPHA_VANTAGE_API_KEY | HIGHLY_SENSITIVE | Configuration for alpha vantage api key. |
| APP_PASSWORD | HIGHLY_SENSITIVE | Configuration for app password. |
| CLOUD_RELAY_MODEL | SENSITIVE | Configuration for cloud relay model. |
| CONFIG_GOOGLE_LANGUAGE | SENSITIVE | Configuration for config google language. |
| CONFIG_NGINX_TEMPLATE | SENSITIVE | Configuration for config nginx template. |
| CONFIG_OPEN_SEARCH_TEMPLATE | SENSITIVE | Configuration for config open search template. |
| CONFIG_PHP_TEMPLATE | SENSITIVE | Configuration for config php template. |
| CORS_ORIGINS | SENSITIVE | Configuration for cors origins. |
| CRYPTOCOMPARE_API_KEY | HIGHLY_SENSITIVE | Configuration for cryptocompare api key. |
| CURLOPT_PROXY | SENSITIVE | Configuration for curlopt proxy. |
| CURLOPT_PROXY_ENABLED | SENSITIVE | Configuration for curlopt proxy enabled. |
| DB_HOST | SENSITIVE | Configuration for db host. |
| DB_NAME | SENSITIVE | Configuration for db name. |
| DB_PASSWORD | HIGHLY_SENSITIVE | Configuration for db password. |
| DB_POOL_SIZE | SENSITIVE | Configuration for db pool size. |
| DB_PORT | SENSITIVE | Configuration for db port. |
| DB_USER | SENSITIVE | Configuration for db user. |
| DEBUG | SENSITIVE | Configuration for debug. |
| ENABLE_BACKTESTING | LOW_RISK | Enables backtesting. |
| ENABLE_LIVE_TRADING | LOW_RISK | Enables live trading. |
| ENABLE_NEWS_MONITORING | LOW_RISK | Enables news monitoring. |
| ENABLE_PREDICTION_MARKETS | LOW_RISK | Enables prediction markets. |
| LOCAL_RELAY_MODEL | SENSITIVE | Configuration for local relay model. |
| MERID_ALERT_MIN_NOTIONAL | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_ALERT_TOPIC | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_ALLOWED_ORIGINS | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_ARKHAM_API_KEY | HIGHLY_SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_AUGUR_MOCK | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_CAPTCHA_PROVIDER | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_CAPTCHA_SECRET | HIGHLY_SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_CAPTCHA_SITEKEY | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_CAPTCHA_VERIFY_URL | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_COINGLASS_API_KEY | HIGHLY_SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_CONFIDENCE_DECAY_RATE | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_CONSENSUS_THRESHOLD | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_DASHBOARD_API_KEY | HIGHLY_SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_DEEP_MODEL | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_DEFAULT_FUNDING_RATE | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_DEFAULT_TIME_TO_RESOLUTION_HOURS | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_DRIFT_BASE_URL | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_ENABLE_AUGUR | SENSITIVE | Feature flag toggling augur. |
| MERID_ENABLE_CAPTCHA | SENSITIVE | Feature flag toggling captcha. |
| MERID_ENABLE_CHAINLINK | SENSITIVE | Feature flag toggling chainlink. |
| MERID_ENABLE_DECAY | SENSITIVE | Feature flag toggling decay. |
| MERID_ENABLE_GAMIFICATION | SENSITIVE | Feature flag toggling gamification. |
| MERID_ENABLE_HYBRID_SIM | SENSITIVE | Feature flag toggling hybrid sim. |
| MERID_ENABLE_LIQUIDATION_MONITOR | SENSITIVE | Feature flag toggling liquidation monitor. |
| MERID_ENABLE_NEWS_AGENT | SENSITIVE | Feature flag toggling news agent. |
| MERID_ENABLE_ONCHAIN_ANALYTICS | SENSITIVE | Feature flag toggling onchain analytics. |
| MERID_ENABLE_PERPS | SENSITIVE | Feature flag toggling perps. |
| MERID_ENABLE_SPAM_GUARD | SENSITIVE | Feature flag toggling spam guard. |
| MERID_ENABLE_UMA | SENSITIVE | Feature flag toggling uma. |
| MERID_ENABLE_WHALE_INTEL | SENSITIVE | Feature flag toggling whale intel. |
| MERID_ENABLE_ZKSNARK | SENSITIVE | Feature flag toggling zksnark. |
| MERID_ENV | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_EVENT_BUFFER | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_FAST_MODEL | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_FUNDING_HALF_LIFE_HOURS | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_GAMIFICATION_BASE_XP | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_GLASSNODE_API_KEY | HIGHLY_SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_GMX_BASE_URL | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_HISTORY_CACHE_SECONDS | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_HYPERLIQUID_INFO_URL | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_LINEAGE_HISTORY | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_LIQUIDATION_SYMBOLS | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_MAX_AGENTS | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_MAX_TOOL_RESULTS | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_MVRV_OVERHEAT_THRESHOLD | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_NANSEN_API_KEY | HIGHLY_SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_NEWS_SOURCES | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_NUPL_OVERHEAT_THRESHOLD | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_ORACLE_PRIVATE_KEY | HIGHLY_SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_PERP_BASIS_THRESHOLD_BPS | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_PERP_ENABLE_BINANCE | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_PERP_ENABLE_BYBIT | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_PERP_ENABLE_COINBASE | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_PERP_ENABLE_CRYPTO_COM | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_PERP_ENABLE_DRIFT | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_PERP_ENABLE_DYDX | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_PERP_ENABLE_GMX | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_PERP_ENABLE_HYPERLIQUID | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_PERP_ENABLE_PERP_PROTOCOL | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_PERP_FUNDING_THRESHOLD_BPS | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_PERP_MAX_MARKETS_PER_VENUE | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_PERP_PROTOCOL_BASE_URL | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_POLYGON_RPC | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_POLYMARKET_INTERVAL | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_POLYMARKET_MOCK | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_PRIVATE_KEY | HIGHLY_SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_REQUIRE_INTENT | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_REQUIRE_VPN_HEADER | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_REWARD_DECAY_RATE | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_SANTIMENT_API_KEY | HIGHLY_SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_SENTIMENT_BEARISH_THRESHOLD | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_SPAM_MAX_EVENTS | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_SPAM_WINDOW_SECONDS | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_TELEGRAM_ALERTS_ENABLED | SENSITIVE | Telegram integration credential or routing parameter. |
| MERID_TELEGRAM_BOT_TOKEN | HIGHLY_SENSITIVE | Telegram integration credential or routing parameter. |
| MERID_TELEGRAM_CHAT_ID | SENSITIVE | Telegram integration credential or routing parameter. |
| MERID_TELEGRAM_INTERVAL | SENSITIVE | Telegram integration credential or routing parameter. |
| MERID_THETA_HALF_LIFE_HOURS | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_TRUTH_MIN_CONFIDENCE | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_UMA_API | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_VPN_HEADER_NAME | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_VPN_HEADER_VALUE | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_WEB_CONCURRENCY | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_X_POST_INTERVAL | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_ZKSNARK_PROVER_PATH | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MERID_ZKSNARK_VK_PATH | SENSITIVE | MERID feature, telemetry, or integration parameter. |
| MESSARI_API_KEY | HIGHLY_SENSITIVE | Configuration for messari api key. |
| MY_EMAIL | SENSITIVE | Configuration for my email. |
| NEO4J_DATABASE | SENSITIVE | Neo4j database connectivity setting. |
| NEO4J_PASSWORD | HIGHLY_SENSITIVE | Neo4j database connectivity setting. |
| NEO4J_URI | SENSITIVE | Neo4j database connectivity setting. |
| NEO4J_USER | SENSITIVE | Neo4j database connectivity setting. |
| OLLAMA_API_KEY | HIGHLY_SENSITIVE | Configuration for ollama api key. |
| OLLAMA_BASE_URL | SENSITIVE | Configuration for ollama base url. |
| OLLAMA_GENERATE_ENDPOINT | SENSITIVE | Configuration for ollama generate endpoint. |
| OLLAMA_HOST | SENSITIVE | Configuration for ollama host. |
| OPENAI_API_KEY | HIGHLY_SENSITIVE | Configuration for openai api key. |
| OPEN_SEARCH_HOST | SENSITIVE | Configuration for open search host. |
| OPEN_SEARCH_HOST_FOR_NGINX | SENSITIVE | Configuration for open search host for nginx. |
| POLYMARKET_API_KEY | HIGHLY_SENSITIVE | Configuration for polymarket api key. |
| RECEIVER_EMAIL | SENSITIVE | Configuration for receiver email. |
| REDIS_URL | SENSITIVE | Configuration for redis url. |
| SEARXNG_URL | SENSITIVE | Configuration for searxng url. |
| SERPER_API_KEY | HIGHLY_SENSITIVE | Configuration for serper api key. |
| SERVER_HOST | SENSITIVE | Configuration for server host. |
| SERVER_PORT | SENSITIVE | Configuration for server port. |
| SMTP_FROM_ADDRESS | SENSITIVE | Email SMTP setting for alert dispatch. |
| SMTP_HOST | SENSITIVE | Email SMTP setting for alert dispatch. |
| SMTP_PASSWORD | HIGHLY_SENSITIVE | Email SMTP setting for alert dispatch. |
| SMTP_PORT | SENSITIVE | Email SMTP setting for alert dispatch. |
| SMTP_USER | SENSITIVE | Email SMTP setting for alert dispatch. |
| SMTP_USE_TLS | SENSITIVE | Email SMTP setting for alert dispatch. |
| SUPABASE_ANON_KEY | HIGHLY_SENSITIVE | Supabase project credential or endpoint. |
| SUPABASE_KEY | HIGHLY_SENSITIVE | Supabase project credential or endpoint. |
| SUPABASE_SERVICE_ROLE_KEY | HIGHLY_SENSITIVE | Supabase project credential or endpoint. |
| SUPABASE_URL | SENSITIVE | Supabase project credential or endpoint. |
| TELEGRAM_BOT_TOKEN | HIGHLY_SENSITIVE | Telegram integration credential or routing parameter. |
| TELEGRAM_CHAT_ID | SENSITIVE | Telegram integration credential or routing parameter. |
| TELEGRAM_TOKEN | HIGHLY_SENSITIVE | Telegram integration credential or routing parameter. |
| TOKENIZED_EQUITY_API_BASE | HIGHLY_SENSITIVE | Tokenized equity API configuration. |
| TOKENIZED_EQUITY_API_KEY | HIGHLY_SENSITIVE | Tokenized equity API configuration. |
| TRADING_COMMISSION_PCT | LOW_RISK | Trading risk/configuration parameter. |
| TRADING_INITIAL_CAPITAL | LOW_RISK | Trading risk/configuration parameter. |
| TRADING_MAX_EXPOSURE | LOW_RISK | Trading risk/configuration parameter. |
| TRADING_MAX_POSITION | LOW_RISK | Trading risk/configuration parameter. |
| TRADING_MODE | LOW_RISK | Trading risk/configuration parameter. |
| TRADING_SLIPPAGE_PCT | LOW_RISK | Trading risk/configuration parameter. |
| TRADING_STOP_LOSS_PCT | LOW_RISK | Trading risk/configuration parameter. |
| TRADING_TAKE_PROFIT_PCT | LOW_RISK | Trading risk/configuration parameter. |
| X_ACCESS_TOKEN | HIGHLY_SENSITIVE | X/Twitter API credential. |
| X_ACCESS_TOKEN_SECRET | HIGHLY_SENSITIVE | X/Twitter API credential. |
| X_API_KEY | HIGHLY_SENSITIVE | X/Twitter API credential. |
| X_API_SECRET | HIGHLY_SENSITIVE | X/Twitter API credential. |
| X_BEARER_TOKEN | HIGHLY_SENSITIVE | X/Twitter API credential. |
| X_BOT_SERVICE_TOKEN | HIGHLY_SENSITIVE | X/Twitter API credential. |
| X_CLIENT_ID | SENSITIVE | X/Twitter API credential. |
| X_CLIENT_SECRET | HIGHLY_SENSITIVE | X/Twitter API credential. |

## Safe Preview (.env.example excerpt)

```
AGENT_CONSENSUS_THRESHOLD=<AGENT_CONSENSUS_THRESHOLD_VALUE>
AGENT_DEFAULT_MODEL=
AGENT_NUM_AGENTS=
AGENT_VOTE_TIMEOUT=<AGENT_VOTE_TIMEOUT_VALUE>
ALERT_CHECK_INTERVAL=<ALERT_CHECK_INTERVAL_VALUE>
```

## Secret Rotation & Storage Guidance

1. Rotate all **HIGHLY_SENSITIVE** keys immediately (Supabase service role, Neo4j password, Telegram tokens, Twitter/X secrets, SMTP password, etc.).
2. Load secrets from a managed store (Vault, AWS/GCP/Azure Secrets, CI/CD variables) and keep `.env` for local development only.
3. Keep `tmp/` git-ignored for disposable tooling outputs; never commit runtime artifacts or raw scan results.
4. Share `.env.example` only and fill values via secure delivery when provisioning new environments.

## Additional Notes

- Full metadata (name, classification, placeholder) is stored in `tmp/env_metadata.json` for downstream automation.
- Update this audit whenever new environment variables are introduced so marketing/observability swarms stay policy-compliant.
