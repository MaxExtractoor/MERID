# MERID Production Configuration Loader
# Dynamically sets environment variables for coherent risk scaling
# 
# Usage:
#   .\scripts\configure_production.ps1
#   # Or dot-source to persist in current session:
#   . .\scripts\configure_production.ps1

$ErrorActionPreference = "Stop"

Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  MERID PRODUCTION CONFIGURATION — Dynamic Risk Scaling (Option B)" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# ═══════════════════════════════════════════════════════════════════════════
# TOP-N ALLOCATOR — 1-2% Cycle Risk Cap
# ═══════════════════════════════════════════════════════════════════════════
$env:USE_TOPN_ALLOCATOR = "true"
$env:MAX_CYCLE_RISK_PCT = "0.01"
$env:MAX_TOTAL_RISK_PCT = "0.02"

Write-Host "[✓] Top-N Allocator: ENABLED" -ForegroundColor Green
Write-Host "    MAX_CYCLE_RISK_PCT: 1% (conservative)" -ForegroundColor Gray
Write-Host "    MAX_TOTAL_RISK_PCT: 2% (portfolio cap)" -ForegroundColor Gray
Write-Host ""

# ═══════════════════════════════════════════════════════════════════════════
# DYNAMIC RISK SCALING — Drawdown-Based
# ═══════════════════════════════════════════════════════════════════════════
$env:KALSHI_TRADER_MAX_RISKABLE_USD = "0"
$env:KALSHI_TRADER_MIN_OP_BALANCE_USD = "0"
$env:KALSHI_TRADER_DD_HALT = "0.15"
$env:KALSHI_TRADER_DD_REDUCE = "0.08"

Write-Host "[✓] Dynamic Risk Scaling: ENABLED" -ForegroundColor Green
Write-Host "    max_riskable_usd: Dynamic (scales 100% → 50% with drawdown)" -ForegroundColor Gray
Write-Host "    min_op_balance: Dynamic (peak × 0.85 at 15% DD)" -ForegroundColor Gray
Write-Host "    drawdown_halt: 15% (unified halt trigger)" -ForegroundColor Gray
Write-Host "    drawdown_reduce: 8% (sizing reduction starts)" -ForegroundColor Gray
Write-Host ""

# ═══════════════════════════════════════════════════════════════════════════
# CAPITAL SOURCE
# ═══════════════════════════════════════════════════════════════════════════
$env:MERID_TOTAL_CAPITAL_USD = "-1"

Write-Host "[✓] Capital Source: Auto-fetch from Kalshi API" -ForegroundColor Green
Write-Host ""

# ═══════════════════════════════════════════════════════════════════════════
# PER-TRADE RISK LIMITS
# ═══════════════════════════════════════════════════════════════════════════
$env:KALSHI_TRADER_RISK_PCT = "0.02"
$env:KALSHI_TRADER_KELLY_FRAC = "0.20"
$env:KALSHI_TRADER_MAX_PRICE = "65"
$env:KALSHI_TRADER_MIN_PRICE = "2"

Write-Host "[✓] Per-Trade Limits: Configured" -ForegroundColor Green
Write-Host "    Risk per trade: 2% of effective equity (unified cycle risk)" -ForegroundColor Gray
Write-Host "    Kelly fraction: 20% (fifth-Kelly conservative)" -ForegroundColor Gray
Write-Host "    Price range: 2¢ - 65¢" -ForegroundColor Gray
Write-Host ""

# ═══════════════════════════════════════════════════════════════════════════
# POSITION & EXPOSURE LIMITS
# ═══════════════════════════════════════════════════════════════════════════
$env:KALSHI_TRADER_MAX_POSITION_PER_MARKET = "3"
$env:KALSHI_TRADER_MAX_OPEN_POSITIONS = "3"
$env:KALSHI_TRADER_GLOBAL_EXPOSURE = "0.50"
$env:KALSHI_TRADER_EXPOSURE_DEFAULT = "0.20"

Write-Host "[✓] Position Limits: Configured" -ForegroundColor Green
Write-Host "    Max per market: 3 contracts" -ForegroundColor Gray
Write-Host "    Max open positions: 3 markets" -ForegroundColor Gray
Write-Host "    Global exposure: 50% of equity" -ForegroundColor Gray
Write-Host "    Per-asset exposure: 20% default" -ForegroundColor Gray
Write-Host ""

# ═══════════════════════════════════════════════════════════════════════════
# SAFETY FLOORS
# ═══════════════════════════════════════════════════════════════════════════
$env:KALSHI_TRADER_MIN_BALANCE_CENTS = "300"
$env:KALSHI_TRADER_MIN_ASSET_CAP_CENTS = "100"

Write-Host "[✓] Safety Floors: Configured" -ForegroundColor Green
Write-Host "    Min balance: $3.00 reserve" -ForegroundColor Gray
Write-Host "    Min asset cap: $1.00 floor" -ForegroundColor Gray
Write-Host ""

# ═══════════════════════════════════════════════════════════════════════════
# CYCLE TIMING
# ═══════════════════════════════════════════════════════════════════════════
$env:KALSHI_CT_INTERVAL_SECONDS = "15"
$env:KALSHI_CT_ORDER_TIMEOUT_SECONDS = "10"

Write-Host "[✓] Cycle Timing: 15-second intervals, 10s order timeout" -ForegroundColor Green
Write-Host ""

# ═══════════════════════════════════════════════════════════════════════════
# LIVE MODE
# ═══════════════════════════════════════════════════════════════════════════
$env:KALSHI_CT_DRY_RUN = "false"
$env:KALSHI_CT_LIVE_MODE = "true"

Write-Host "[✓] Mode: LIVE TRADING" -ForegroundColor Yellow -BackgroundColor Black
Write-Host ""

# ═══════════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════════
Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  DYNAMIC RISK CURVE" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Drawdown    Scale    Effective Equity (example: $100k peak)" -ForegroundColor White
Write-Host "  ─────────────────────────────────────────────────────────────" -ForegroundColor Gray
Write-Host "     0%       100%     $100,000 (full)" -ForegroundColor Green
Write-Host "     5%        83%      $83,333 (reduced)" -ForegroundColor Yellow
Write-Host "    10%        67%      $66,667 (reduced)" -ForegroundColor Yellow
Write-Host "    15%        50%      $50,000 (HALT threshold)" -ForegroundColor Red
Write-Host "    20%+       50%      $50,000 (floor, halted)" -ForegroundColor Red
Write-Host ""
Write-Host "  Halt trigger: Live equity < $85,000 (85% of peak at 15% DD)" -ForegroundColor Red
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Ready for production restart" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
