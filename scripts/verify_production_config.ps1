# MERID Production Configuration Verifier
# Validates all critical environment variables are set correctly
#
# Usage:
#   .\scripts\verify_production_config.ps1

$ErrorActionPreference = "Continue"

Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  MERID PRODUCTION CONFIGURATION VERIFICATION" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

$CriticalVars = @(
    @{ Name = "USE_TOPN_ALLOCATOR"; Required = "true"; Critical = $true },
    @{ Name = "MAX_CYCLE_RISK_PCT"; Required = "0.01"; Critical = $true },
    @{ Name = "MAX_TOTAL_RISK_PCT"; Required = "0.02"; Critical = $true },
    @{ Name = "KALSHI_TRADER_MAX_RISKABLE_USD"; Required = "0"; Critical = $true },
    @{ Name = "KALSHI_TRADER_MIN_OP_BALANCE_USD"; Required = "0"; Critical = $true },
    @{ Name = "KALSHI_TRADER_DD_HALT"; Required = "0.15"; Critical = $true },
    @{ Name = "KALSHI_TRADER_DD_REDUCE"; Required = "0.08"; Critical = $true },
    @{ Name = "MERID_TOTAL_CAPITAL_USD"; Required = "-1"; Critical = $true },
    @{ Name = "KALSHI_CT_DRY_RUN"; Required = "false"; Critical = $true },
    @{ Name = "KALSHI_CT_LIVE_MODE"; Required = "true"; Critical = $true }
)

$Warnings = @(
    @{ Name = "KALSHI_API_KEY"; Required = "set"; Critical = $false },
    @{ Name = "KALSHI_PRIVATE_KEY"; Required = "path"; Critical = $false }
)

$allPassed = $true
$criticalCount = 0
$criticalPassed = 0

foreach ($var in $CriticalVars) {
    $criticalCount++
    $value = [Environment]::GetEnvironmentVariable($var.Name)
    $expected = $var.Required
    
    if ([string]::IsNullOrEmpty($value)) {
        Write-Host "[✗] $($var.Name): NOT SET (expected: $expected)" -ForegroundColor Red
        $allPassed = $false
    } elseif ($value -eq $expected) {
        Write-Host "[✓] $($var.Name): $value" -ForegroundColor Green
        $criticalPassed++
    } else {
        Write-Host "[!] $($var.Name): $value (expected: $expected)" -ForegroundColor Yellow
        $allPassed = $false
    }
}

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  API CREDENTIALS CHECK" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

foreach ($var in $Warnings) {
    $value = [Environment]::GetEnvironmentVariable($var.Name)
    
    if ([string]::IsNullOrEmpty($value)) {
        Write-Host "[!] $($var.Name): NOT SET" -ForegroundColor Yellow
    } else {
        $masked = if ($value.Length -gt 10) { $value.Substring(0, 4) + "..." + $value.Substring($value.Length - 4) } else { "***" }
        Write-Host "[✓] $($var.Name): $masked" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  DYNAMIC RISK CURVE VERIFICATION" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

$maxRiskable = [Environment]::GetEnvironmentVariable("KALSHI_TRADER_MAX_RISKABLE_USD")
$minOpBalance = [Environment]::GetEnvironmentVariable("KALSHI_TRADER_MIN_OP_BALANCE_USD")
$ddHalt = [Environment]::GetEnvironmentVariable("KALSHI_TRADER_DD_HALT")
$ddReduce = [Environment]::GetEnvironmentVariable("KALSHI_TRADER_DD_REDUCE")
$useTopN = [Environment]::GetEnvironmentVariable("USE_TOPN_ALLOCATOR")

if ($maxRiskable -eq "0" -and $minOpBalance -eq "0") {
    Write-Host "[✓] Dynamic risk scaling: ENABLED" -ForegroundColor Green
    Write-Host "    max_riskable_usd scales: 100% -> 50% with drawdown" -ForegroundColor Gray
    Write-Host "    min_op_balance unified: peak x (1 - $ddHalt)" -ForegroundColor Gray
    Write-Host "    Halt at drawdown: $([float]$ddHalt * 100)%" -ForegroundColor Gray
} elseif ($maxRiskable -ne "0") {
    Write-Host "[!] Static max_riskable_usd ceiling: $maxRiskable" -ForegroundColor Yellow
    Write-Host "    Dynamic scaling applies within this ceiling" -ForegroundColor Gray
}

if ($useTopN -eq "true") {
    Write-Host "[✓] Top-N allocator: ENABLED (primary defense against oversizing)" -ForegroundColor Green
} else {
    Write-Host "[✗] Top-N allocator: DISABLED (CRITICAL RISK!)" -ForegroundColor Red -BackgroundColor Black
    $allPassed = $false
}

Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  VERIFICATION RESULT" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

if ($allPassed -and $criticalPassed -eq $criticalCount) {
    Write-Host "  [✓✓✓] ALL CRITICAL CHECKS PASSED — READY FOR PRODUCTION" -ForegroundColor Green -BackgroundColor Black
    Write-Host ""
    Write-Host "  Dynamic Risk Curve:" -ForegroundColor White
    Write-Host "    0% DD  -> 100% scale -> Full equity for sizing" -ForegroundColor Green
    Write-Host "    8% DD  -> 73% scale  -> Sizing reduction starts" -ForegroundColor Yellow
    Write-Host "    15% DD -> 50% scale  -> HALT (unified trigger)" -ForegroundColor Red
    Write-Host ""
    exit 0
} else {
    Write-Host "  [✗✗✗] VERIFICATION FAILED — Fix before restart" -ForegroundColor Red -BackgroundColor Black
    Write-Host "  Passed: $criticalPassed / $criticalCount critical checks" -ForegroundColor Yellow
    exit 1
}
