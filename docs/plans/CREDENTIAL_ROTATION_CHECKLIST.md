# Credential Rotation Checklist (T-006)

**Status:** URGENT — All credentials below should be assumed compromised.  
**Reason:** `.env` (277 lines) and `.env.backup` (429 lines) contain plaintext secrets on disk.  
**Date:** 2026-02-22  

## Credentials Requiring Immediate Rotation

### 1. Kalshi API Keys
- [ ] Regenerate Kalshi API key pair at https://kalshi.com/account/api
- [ ] Update `KALSHI_API_KEY_ID` in secrets manager
- [ ] Generate new RSA key pair, store in encrypted vault (NOT in repo)
- [ ] Update `KALSHI_PRIVATE_KEY_PATH` / `KALSHI_PRIVATE_KEY_PEM`

### 2. Exchange Credentials
- [ ] **Binance US** — Rotate `BINANCE_API_KEY`, `BINANCE_SECRET`
- [ ] **Coinbase** — Rotate `COINBASE_API_KEY`, `COINBASE_SECRET`
- [ ] **Kraken** — Rotate `KRAKEN_API_KEY`, `KRAKEN_SECRET`
- [ ] **OKX** — Rotate `OKX_API_KEY`, `OKX_SECRET`, `OKX_PASSPHRASE`
- [ ] **Alpaca** — Rotate `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`

### 3. LLM API Keys
- [ ] **Claude/Anthropic** — Rotate `ANTHROPIC_API_KEY`
- [ ] **OpenAI** — Rotate `OPENAI_API_KEY`
- [ ] **DeepSeek** — Rotate `DEEPSEEK_API_KEY`

### 4. Database Passwords
- [ ] **Neo4j** — Change password (was `F@tc0ck42069` in plaintext)
- [ ] **MongoDB** — Rotate `MONGO_URI` credentials
- [ ] **Redis** — Rotate `REDIS_PASSWORD`
- [ ] **Supabase** — Rotate `SUPABASE_KEY` and `SUPABASE_JWT_SECRET`

### 5. OAuth / Social Tokens
- [ ] **Twitter/X** — Rotate full OAuth flow tokens (`TWITTER_API_KEY`, `TWITTER_API_SECRET`, `TWITTER_ACCESS_TOKEN`, `TWITTER_ACCESS_SECRET`)
- [ ] **Telegram** — Rotate `TELEGRAM_BOT_TOKEN`

### 6. Infrastructure
- [ ] **NATS** — Rotate `NATS_TOKEN` if configured
- [ ] **Grafana** — Rotate `GRAFANA_API_KEY`

## Post-Rotation Steps

1. **Delete `.env.backup`** from disk after rotation
2. **Move to secrets manager:**
   - Option A: HashiCorp Vault (recommended for production)
   - Option B: AWS Secrets Manager / GCP Secret Manager
   - Option C: Encrypted `.env.enc` with `python-dotenv` + `cryptography` (minimum viable)
3. **Verify `.gitignore`** covers all secret patterns (already confirmed: `*.pem`, `.env`, `.env.*`)
4. **Run `git filter-repo`** to purge any historical secret commits:
   ```bash
   git filter-repo --path .env --invert-paths
   git filter-repo --path .env.backup --invert-paths
   git filter-repo --path kalshi_private_key.pem --invert-paths
   ```
5. **Force-push** and notify all collaborators to re-clone

## Environment Variable Reference

All secrets should be loaded via `python-dotenv` from an encrypted source.
The `.env` file on disk should contain ONLY non-secret configuration.
Secret values should reference a vault path or be injected at runtime.
