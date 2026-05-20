# Fix environment variable for MERID slow action budget
Write-Host "=== Checking MERID_LOOP_SLOW_ACTION_BUDGET_MS ===" -ForegroundColor Yellow

# Check User scope
$userVal = [Environment]::GetEnvironmentVariable('MERID_LOOP_SLOW_ACTION_BUDGET_MS', 'User')
Write-Host "User scope: $userVal"

# Check Machine scope  
$machineVal = [Environment]::GetEnvironmentVariable('MERID_LOOP_SLOW_ACTION_BUDGET_MS', 'Machine')
Write-Host "Machine scope: $machineVal"

# Check current session
Write-Host "Current session: $env:MERID_LOOP_SLOW_ACTION_BUDGET_MS"

Write-Host "`n=== Removing MERID_LOOP_SLOW_ACTION_BUDGET_MS ===" -ForegroundColor Green

# Remove from User environment
if ($userVal) {
    [Environment]::SetEnvironmentVariable('MERID_LOOP_SLOW_ACTION_BUDGET_MS', $null, 'User')
    Write-Host "Removed from User environment" -ForegroundColor Green
}

# Remove from Machine environment
if ($machineVal) {
    [Environment]::SetEnvironmentVariable('MERID_LOOP_SLOW_ACTION_BUDGET_MS', $null, 'Machine')
    Write-Host "Removed from Machine environment" -ForegroundColor Green
}

# Clear current session
Remove-Item Env:\MERID_LOOP_SLOW_ACTION_BUDGET_MS -ErrorAction SilentlyContinue
Write-Host "Cleared current session" -ForegroundColor Green

Write-Host "`n=== Verification ===" -ForegroundColor Yellow
$userCheck = [Environment]::GetEnvironmentVariable('MERID_LOOP_SLOW_ACTION_BUDGET_MS', 'User')
$machineCheck = [Environment]::GetEnvironmentVariable('MERID_LOOP_SLOW_ACTION_BUDGET_MS', 'Machine')
Write-Host "User: $(if($userCheck){$userCheck}else{'(not set)'})"
Write-Host "Machine: $(if($machineCheck){$machineCheck}else{'(not set)'})"
Write-Host "Session: $(if($env:MERID_LOOP_SLOW_ACTION_BUDGET_MS){$env:MERID_LOOP_SLOW_ACTION_BUDGET_MS}else{'(not set)'})"

Write-Host "`n=== DONE ===" -ForegroundColor Green
Write-Host "Restart your terminal and MERID server for changes to take effect"

# Also check for any other MERID env vars that might be set incorrectly
Write-Host "`n=== Other MERID env vars ===" -ForegroundColor Cyan
Get-ChildItem Env: | Where-Object { $_.Name -like "MERID*" } | Format-Table Name, Value -AutoSize
