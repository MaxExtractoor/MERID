# Seed Baseline Reality Assertions
# PowerShell script to register baseline assertions via REST API

$baseUrl = "http://localhost:8000"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "SEEDING BASELINE REALITY ASSERTIONS" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$assertions = @(
    @{
        domain = "market"
        description = "BTC/USD price feed operational (bootstrap)"
        confidence = 0.6
        provenance_score = 0.5
        regime_compatibility = 0.7
        decay_rate = 0.0001
        validity_window = 3600.0
        sources = @(
            @{
                source_id = "bootstrap"
                module_id = "system_init"
                evidence_hash = "baseline_market_btc"
                weight = 1.0
                timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            }
        )
    },
    @{
        domain = "market"
        description = "ETH/USD price feed operational (bootstrap)"
        confidence = 0.6
        provenance_score = 0.5
        regime_compatibility = 0.7
        decay_rate = 0.0001
        validity_window = 3600.0
        sources = @(
            @{
                source_id = "bootstrap"
                module_id = "system_init"
                evidence_hash = "baseline_market_eth"
                weight = 1.0
                timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            }
        )
    },
    @{
        domain = "execution"
        description = "Execution engine initialized and ready (bootstrap)"
        confidence = 0.7
        provenance_score = 0.6
        regime_compatibility = 0.8
        decay_rate = 0.00005
        validity_window = 7200.0
        sources = @(
            @{
                source_id = "bootstrap"
                module_id = "execution_engine"
                evidence_hash = "baseline_execution"
                weight = 1.0
                timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            }
        )
    },
    @{
        domain = "execution"
        description = "Order routing available (bootstrap)"
        confidence = 0.65
        provenance_score = 0.6
        regime_compatibility = 0.75
        decay_rate = 0.0001
        validity_window = 3600.0
        sources = @(
            @{
                source_id = "bootstrap"
                module_id = "execution_engine"
                evidence_hash = "baseline_routing"
                weight = 1.0
                timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            }
        )
    },
    @{
        domain = "treasury"
        description = "Treasury state tracking operational (bootstrap)"
        confidence = 0.7
        provenance_score = 0.65
        regime_compatibility = 0.8
        decay_rate = 0.00005
        validity_window = 7200.0
        sources = @(
            @{
                source_id = "bootstrap"
                module_id = "treasury_monitor"
                evidence_hash = "baseline_treasury"
                weight = 1.0
                timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            }
        )
    },
    @{
        domain = "treasury"
        description = "Portfolio balance tracking available (bootstrap)"
        confidence = 0.65
        provenance_score = 0.6
        regime_compatibility = 0.75
        decay_rate = 0.0001
        validity_window = 3600.0
        sources = @(
            @{
                source_id = "bootstrap"
                module_id = "treasury_monitor"
                evidence_hash = "baseline_portfolio"
                weight = 1.0
                timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            }
        )
    }
)

$registered = 0
$failed = 0

foreach ($assertion in $assertions) {
    try {
        $json = $assertion | ConvertTo-Json -Depth 10
        $response = Invoke-RestMethod -Uri "$baseUrl/api/v1/reality/assertions/register" -Method Post -Body $json -ContentType "application/json"
        
        Write-Host "✓ Registered: $($assertion.domain) - $($assertion.description)" -ForegroundColor Green
        Write-Host "  ID: $($response.assertion_id)" -ForegroundColor Gray
        $registered++
    }
    catch {
        Write-Host "✗ Failed: $($assertion.domain) - $($_.Exception.Message)" -ForegroundColor Red
        $failed++
    }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "SEEDING COMPLETE: $registered registered, $failed failed" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Check blindness status
try {
    $status = Invoke-RestMethod -Uri "$baseUrl/api/v1/reality/blindness" -Method Get
    
    if ($status.is_blind) {
        Write-Host "⚠️  SYSTEM STILL IN BLINDNESS MODE: $($status.reason)" -ForegroundColor Yellow
    }
    else {
        Write-Host "✓ SYSTEM OPERATIONAL: $($status.reason)" -ForegroundColor Green
    }
}
catch {
    Write-Host "⚠️  Could not check blindness status: $($_.Exception.Message)" -ForegroundColor Yellow
}

Write-Host ""
