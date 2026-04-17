# Seed Baseline Reality Assertions - Simple Version

$baseUrl = "http://localhost:8000"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "SEEDING BASELINE REALITY ASSERTIONS" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$timestamp = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()

# Market assertions
$marketBtc = @{
    domain = "market"
    description = "BTC/USD price feed operational (bootstrap)"
    confidence = 0.6
    provenance_score = 0.5
    regime_compatibility = 0.7
    decay_rate = 0.0001
    validity_window = 3600.0
    sources = @(@{
        source_id = "bootstrap"
        module_id = "system_init"
        evidence_hash = "baseline_market_btc"
        weight = 1.0
        timestamp = $timestamp
    })
} | ConvertTo-Json -Depth 10

$marketEth = @{
    domain = "market"
    description = "ETH/USD price feed operational (bootstrap)"
    confidence = 0.6
    provenance_score = 0.5
    regime_compatibility = 0.7
    decay_rate = 0.0001
    validity_window = 3600.0
    sources = @(@{
        source_id = "bootstrap"
        module_id = "system_init"
        evidence_hash = "baseline_market_eth"
        weight = 1.0
        timestamp = $timestamp
    })
} | ConvertTo-Json -Depth 10

# Execution assertions
$execEngine = @{
    domain = "execution"
    description = "Execution engine initialized and ready (bootstrap)"
    confidence = 0.7
    provenance_score = 0.6
    regime_compatibility = 0.8
    decay_rate = 0.00005
    validity_window = 7200.0
    sources = @(@{
        source_id = "bootstrap"
        module_id = "execution_engine"
        evidence_hash = "baseline_execution"
        weight = 1.0
        timestamp = $timestamp
    })
} | ConvertTo-Json -Depth 10

$execRouting = @{
    domain = "execution"
    description = "Order routing available (bootstrap)"
    confidence = 0.65
    provenance_score = 0.6
    regime_compatibility = 0.75
    decay_rate = 0.0001
    validity_window = 3600.0
    sources = @(@{
        source_id = "bootstrap"
        module_id = "execution_engine"
        evidence_hash = "baseline_routing"
        weight = 1.0
        timestamp = $timestamp
    })
} | ConvertTo-Json -Depth 10

# Treasury assertions
$treasuryState = @{
    domain = "treasury"
    description = "Treasury state tracking operational (bootstrap)"
    confidence = 0.7
    provenance_score = 0.65
    regime_compatibility = 0.8
    decay_rate = 0.00005
    validity_window = 7200.0
    sources = @(@{
        source_id = "bootstrap"
        module_id = "treasury_monitor"
        evidence_hash = "baseline_treasury"
        weight = 1.0
        timestamp = $timestamp
    })
} | ConvertTo-Json -Depth 10

$treasuryPortfolio = @{
    domain = "treasury"
    description = "Portfolio balance tracking available (bootstrap)"
    confidence = 0.65
    provenance_score = 0.6
    regime_compatibility = 0.75
    decay_rate = 0.0001
    validity_window = 3600.0
    sources = @(@{
        source_id = "bootstrap"
        module_id = "treasury_monitor"
        evidence_hash = "baseline_portfolio"
        weight = 1.0
        timestamp = $timestamp
    })
} | ConvertTo-Json -Depth 10

$assertions = @(
    @{name="Market BTC"; json=$marketBtc},
    @{name="Market ETH"; json=$marketEth},
    @{name="Execution Engine"; json=$execEngine},
    @{name="Execution Routing"; json=$execRouting},
    @{name="Treasury State"; json=$treasuryState},
    @{name="Treasury Portfolio"; json=$treasuryPortfolio}
)

$registered = 0
$failed = 0

foreach ($item in $assertions) {
    try {
        $response = Invoke-RestMethod -Uri "$baseUrl/api/v1/reality/assertions/register" -Method Post -Body $item.json -ContentType "application/json" -ErrorAction Stop
        Write-Host "✓ Registered: $($item.name)" -ForegroundColor Green
        Write-Host "  ID: $($response.assertion_id)" -ForegroundColor Gray
        $registered++
    }
    catch {
        Write-Host "✗ Failed: $($item.name)" -ForegroundColor Red
        Write-Host "  Error: $($_.Exception.Message)" -ForegroundColor Red
        $failed++
    }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "COMPLETE: $registered registered, $failed failed" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Check status
try {
    $status = Invoke-RestMethod -Uri "$baseUrl/api/v1/reality/blindness" -Method Get -ErrorAction Stop
    if ($status.is_blind) {
        Write-Host "⚠️  BLINDNESS MODE: $($status.reason)" -ForegroundColor Yellow
    } else {
        Write-Host "✓ OPERATIONAL: $($status.reason)" -ForegroundColor Green
    }
}
catch {
    Write-Host "⚠️  Status check failed" -ForegroundColor Yellow
}
