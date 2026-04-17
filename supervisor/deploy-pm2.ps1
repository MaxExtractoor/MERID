# MERID PM2 Supervisor Deployment Script
# Run this to promote foreground process to persistent supervisor

$ErrorActionPreference = "Stop"
Write-Host "=== MERID PM2 Supervisor Deployment ===" -ForegroundColor Cyan

# Check if pm2 is installed
try {
    $pm2 = Get-Command pm2 -ErrorAction Stop
    Write-Host "✅ PM2 found: $($pm2.Source)" -ForegroundColor Green
} catch {
    Write-Host "Installing PM2..." -ForegroundColor Yellow
    npm install -g pm2
}

# Stop any existing merid-api processes
Write-Host "Stopping existing merid-api processes..." -ForegroundColor Yellow
pm2 stop merid-api 2>$null
pm2 delete merid-api 2>$null

# Start with PM2
Write-Host "Starting MERID with PM2..." -ForegroundColor Green
pm2 start supervisor/merid-service.json

# Show status
Write-Host "`n=== PM2 Status ===" -ForegroundColor Cyan
pm2 status

Write-Host "`n=== Commands to manage ===" -ForegroundColor Yellow
Write-Host "  pm2 logs merid-api          # View logs"
Write-Host "  pm2 monit                     # Monitor UI"
Write-Host "  pm2 stop merid-api            # Stop service"
Write-Host "  pm2 restart merid-api         # Restart service"
Write-Host "  pm2 save                      # Save config for auto-start"

# Save PM2 config for auto-start on boot
pm2 save

Write-Host "`n✅ MERID deployed to PM2 supervisor" -ForegroundColor Green
