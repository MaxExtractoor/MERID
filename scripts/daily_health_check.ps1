# MERID Daily Health Check Script for Windows PowerShell
# Run via Task Scheduler every 4 hours

param(
    [string]$LogDir = "$env:MERID_LOG_DIR",
    [string]$DataDir = "$env:MERID_DATA_DIR",
    [string]$ApiUrl = $env:MERID_API_URL
)

# Defaults
if (-not $LogDir) { $LogDir = "logs" }
if (-not $DataDir) { $DataDir = "data" }
if (-not $ApiUrl) { $ApiUrl = "http://localhost:8011" }

$Api = "$ApiUrl/api/v1"
$LogFile = "$LogDir\daily_health_$(Get-Date -Format 'yyyyMMdd').log"
$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$TelegramToken = $env:TELEGRAM_BOT_TOKEN
$TelegramChat = $env:TELEGRAM_CHAT_ID

# Ensure directories exist
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

function Write-Log($Message) {
    $entry = "[$Timestamp] $Message"
    Write-Host $entry
    Add-Content -Path $LogFile -Value $entry
}

function Send-Telegram($Message) {
    if ($TelegramToken -and $TelegramChat) {
        try {
            $uri = "https://api.telegram.org/bot$TelegramToken/sendMessage"
            $body = @{
                chat_id = $TelegramChat
                text = $Message
                parse_mode = "Markdown"
            } | ConvertTo-Json
            
            Invoke-RestMethod -Uri $uri -Method Post -Body $body -ContentType "application/json" | Out-Null
        } catch {
            Write-Log "Failed to send Telegram alert: $_"
        }
    }
}

Write-Log "=== Daily Health Check ==="
$Alerts = @()

# 1. Check if server is running
Write-Log "[1/6] Checking server status..."
try {
    $response = Invoke-RestMethod -Uri "$Api/system/ping" -TimeoutSec 5
    Write-Log "Server running: OK"
} catch {
    Write-Log "Server NOT RESPONDING"
    Send-Telegram "🚨 *MERID ALERT* Server not responding at $Timestamp"
    exit 1
}

# 2. Check kill switch status
Write-Log "[2/6] Checking kill switch..."
try {
    $response = Invoke-RestMethod -Uri "$Api/system/kill-switch" -TimeoutSec 5
    if ($response.active) {
        Write-Log "KILL SWITCH ACTIVE"
        Send-Telegram "⚠️ *MERID WARNING* Kill switch is ACTIVE at $Timestamp"
        $Alerts += "KillSwitch"
    } else {
        Write-Log "Kill switch clear"
    }
} catch {
    Write-Log "Kill switch status unknown"
}

# 3. Check execution lag
Write-Log "[3/6] Checking execution lag..."
try {
    $response = Invoke-RestMethod -Uri "$Api/health/execution-lag" -TimeoutSec 5
    $lag = $response.lag_ms
    
    if ($lag -gt 500) {
        Write-Log "HIGH LAG: ${lag}ms (threshold: 500ms)"
        Send-Telegram "⚠️ *MERID WARNING* Execution lag: ${lag}ms at $Timestamp"
        $Alerts += "HighLag"
    } elseif ($lag -gt 300) {
        Write-Log "Elevated lag: ${lag}ms (watching)"
    } else {
        Write-Log "Lag OK: ${lag}ms"
    }
} catch {
    Write-Log "Could not fetch lag status"
}

# 4. Check bankroll status
Write-Log "[4/6] Checking bankroll..."
try {
    $response = Invoke-RestMethod -Uri "$Api/kalshi/continuous-trader/status" -TimeoutSec 5
    $totalValue = $response.total_value_cents
    $drawdown = $response.drawdown_pct
    
    Write-Log "Bankroll: `$$([math]::Round($totalValue/100, 2)) | Drawdown: $([math]::Round($drawdown, 2))%"
    
    if ($drawdown -gt 12) {
        Send-Telegram "⚠️ *MERID WARNING* Drawdown at $([math]::Round($drawdown, 1))% at $Timestamp"
        $Alerts += "HighDrawdown"
    }
} catch {
    Write-Log "Could not fetch bankroll status"
}

# 5. Check recent fills
Write-Log "[5/6] Checking recent fills..."
$dbPath = "$DataDir\kalshi_fills.db"
if (Test-Path $dbPath) {
    try {
        # Note: Requires SQLite module or external tool
        # This is a simplified check
        Write-Log "Fill database exists"
    } catch {
        Write-Log "Error checking fills: $_"
    }
} else {
    Write-Log "Fill database not found"
}

# 6. Summary
Write-Log "=== Summary ==="
if ($Alerts.Count -eq 0) {
    Write-Log "All systems nominal"
    exit 0
} else {
    Write-Log "Alerts: $($Alerts -join '; ')"
    exit 1
}
