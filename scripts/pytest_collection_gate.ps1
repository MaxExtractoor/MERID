# Fail-fast pytest collection over the full tests/ tree (matches CI pytest-collection-gate).
# Exits non-zero on the first collection error — use to drive down import/bitrot debt.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
py -m pytest tests/ `
    --ignore=tests/ChatGPT --ignore=tests/Grok --ignore=tests/Perplexity --ignore=tests/Final_Draft `
    --collect-only --maxfail=1 -q
