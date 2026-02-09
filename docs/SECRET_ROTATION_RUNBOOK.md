# Secret Rotation Runbook

## Status

- `.gitignore` expanded to 103 entries — secrets, DBs, build artifacts, IDE files all covered
- `kalshi_private_key.pem` and `.env.backup` are **no longer tracked** in the git index
- History purge still needed before any public/shared push

## Step 1: Purge from git history

```bash
# Option A: BFG Repo-Cleaner (faster)
java -jar bfg.jar --delete-files kalshi_private_key.pem .
java -jar bfg.jar --delete-files .env.backup .
git reflog expire --expire=now --all && git gc --prune=now --aggressive
git push --force

# Option B: git filter-repo
git filter-repo --path kalshi_private_key.pem --invert-paths
git filter-repo --path .env.backup --invert-paths
git push --force
```

## Step 2: Rotate ALL keys that ever touched git

| Service | Action | Priority |
|---------|--------|----------|
| **Kalshi** | Generate new API key pair in Kalshi dashboard, update `.env` | CRITICAL |
| **Binance** | Rotate API key + secret | HIGH |
| **Coinbase** | Rotate API key + secret | HIGH |
| **Kraken** | Rotate API key + private key | HIGH |
| **OKX** | Rotate API key + secret + passphrase | HIGH |
| **Alpaca** | Rotate paper trading key + secret | HIGH |
| **Twitter/X** | Rotate OAuth tokens + bearer | HIGH |
| **Telegram** | Rotate bot token via @BotFather | HIGH |
| **Polygon** | Rotate API key | MEDIUM |
| **Finnhub** | Rotate API key | MEDIUM |
| **Messari** | Rotate API key | MEDIUM |
| **Alpha Vantage** | Rotate API key | MEDIUM |
| **The Graph** | Rotate API key | MEDIUM |
| **Nansen** | Rotate API key | MEDIUM |

## Step 3: Verify

```bash
# Confirm no secrets in tracked files
git ls-files | Select-String -Pattern "\.pem|\.env|private_key|secret|password"

# Confirm .gitignore catches new patterns
echo "test.pem" > test.pem
git status  # should show nothing new
rm test.pem
```

## Going forward

- All secrets via `.env` (gitignored) or a secrets manager (Vault, AWS SSM, etc.)
- Never commit credentials, even temporarily
- CI should run `git secrets --scan` or `trufflehog` as a pre-commit hook
