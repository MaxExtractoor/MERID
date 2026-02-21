# Phase 0 Trial Start PowerShell Script
# Start the 6-week Phase 0 trial

# Set up environment
& .\setup-phase0-env.ps1

Write-Host "Starting Phase 0 trial..."
Write-Host ""

# Start the trial
try {
    $body = '{"duration_weeks": 6}' | ConvertTo-Json
    $response = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/phase0/trial/start" -Method POST -ContentType "application/json" -Body $body
    
    Write-Host "✅ Phase 0 trial started successfully!"
    Write-Host "Response:"
    $response | ConvertTo-Json -Depth 10
    
} catch {
    Write-Host "❌ Failed to start Phase 0 trial"
    Write-Host "Error: $($_.Exception.Message)"
    exit 1
}

Write-Host ""
Write-Host "Verifying trial status..."
try {
    $status = Invoke-RestMethod -Uri "http://localhost:8000/api/v1/phase0/trial/status" -Method GET
    Write-Host "✅ Trial status verified:"
    $status | ConvertTo-Json -Depth 10
} catch {
    Write-Host "❌ Failed to verify trial status"
    Write-Host "Error: $($_.Exception.Message)"
    exit 1
}

Write-Host ""
Write-Host "🎯 Phase 0 trial is now active!"
Write-Host "Next steps:"
Write-Host "1. Schedule weekly 30-minute governance meetings"
Write-Host "2. Use weekly_phase0_status.sh for weekly status checks"
Write-Host "3. Use record_decisions.sh for weekly decision recording"
Write-Host "4. Run complete_trial.sh after 6 weeks"
