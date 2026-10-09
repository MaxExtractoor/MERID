# Micro Momentum Scalping Environment Variables
# Run this before starting the agent grid

# Scalping thresholds
$env:MERID_PM_MIN_EDGE_EARLY="0.018"     # 1.8% - aggressive scalping
$env:MERID_PM_MIN_EDGE_MID="0.015"       # 1.5%
$env:MERID_PM_MIN_EDGE_LATE="0.012"      # 1.2%
$env:MERID_PM_MIN_EDGE_TERMINAL="0.018"  # 1.8%
$env:MERID_PM_MIN_CONFIDENCE="0.42"      # slightly lower confidence
$env:MERID_PM_MM_MAX_SPREAD_CENTS="5"     # ensure 5c spread max

# OLD-HARDWARE FIX (2026-04-29): Relaxed thresholds for slow computers
$env:KALSHI_LOOP_LAG_HEALTHY_MS="3000"      # 3s warning threshold
$env:KALSHI_LOOP_LAG_DEGRADE_MS="8000"      # 8s degraded threshold  
$env:KALSHI_LOOP_LAG_HALT_MS="15000"         # 15s halt threshold
$env:KALSHI_LOOP_LAG_DEGRADED_CONSECUTIVE="15"  # 15 breaches before degraded
$env:KALSHI_LOOP_LAG_HALT_CONSECUTIVE="20"      # 20 breaches before halt

Write-Host "Micro-scalping environment set:" -ForegroundColor Green
Write-Host "  Edge thresholds: 1.8%/1.5%/1.2%/1.8%" -ForegroundColor Cyan
Write-Host "  Confidence: 0.42" -ForegroundColor Cyan
Write-Host "  Max spread: 5c" -ForegroundColor Cyan
Write-Host "  Loop lag: 3s/8s/15s (OLD-HARDWARE FIX)" -ForegroundColor Cyan
Write-Host ""
Write-Host "Start the agent grid with: python -m merid.prediction.agent_grid" -ForegroundColor Yellow
