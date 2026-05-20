# MERID Health Check Script
# Returns 0 if healthy, 1 if unhealthy

param(
    [string]$BaseUrl = "http://127.0.0.1:8011",
    [int]$TimeoutSec = 5
)

try {
    $response = Invoke-RestMethod -Uri "$BaseUrl/api/v1/system/health" -TimeoutSec $TimeoutSec
    
    # Check for critical services down
    if ($response.dependency_health.any_critical_down) {
        Write-Error "CRITICAL: Some dependencies are down"
        exit 1
    }
    
    Write-Host "✅ MERID is healthy" -ForegroundColor Green
    Write-Host "   Dependencies: $($response.dependency_health.healthy) healthy, $($response.dependency_health.degraded) degraded, $($response.dependency_health.down) down"
    exit 0
} catch {
    Write-Error "❌ Health check failed: $_"
    exit 1
}
