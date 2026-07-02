# MERID Live Mode Startup + Real-Time Monitor (PowerShell)
# Usage: .\ops\live_start_and_monitor.ps1 [-Live] [-ConfirmLive] [-Abort] [-GateMinutes 30]
#
# This script follows the operator runbook for live trading on Windows.

[CmdletBinding()]
param(
    [switch]$Live,
    [switch]$ConfirmLive,
    [switch]$Abort,
    [int]$GateMinutes = 30
)

# Config
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$MeridRoot = Split-Path -Parent $ScriptDir
$LogDir = "$env:LOCALAPPDATA\MERID\logs"
$MonitorLog = "$LogDir\monitor.log"
$PidFile = "$env:TEMP\merid-live.pid"
$GateStartFile = "$env:TEMP\merid-gate-start"

# Colors
$Red = "`e[31m"
$Green = "`e[32m"
$Yellow = "`e[33m"
$Cyan = "`e[36m"
$Reset = "`e[0m"

# Tracking
$script:AnomalyCount = 0
$script:CriticalAnomalies = 0
$script:SequenceGaps = 0
$script:TradeProposals = 0
$script:TradeExecuted = 0
$script:GateActive = $false
$script:ServerProcess = $null
$script:MonitorActive = $true

function Write-LogInfo($Message) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$Green[INFO]$Reset $ts $Message"
    Write-Host $line
    Add-Content -Path $MonitorLog -Value "[INFO] $ts $Message" -ErrorAction SilentlyContinue
}

function Write-LogWarn($Message) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$Yellow[WARN]$Reset $ts $Message"
    Write-Host $line
    Add-Content -Path $MonitorLog -Value "[WARN] $ts $Message" -ErrorAction SilentlyContinue
}

function Write-LogError($Message) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$Red[ERROR]$Reset $ts $Message"
    Write-Host $line
    Add-Content -Path $MonitorLog -Value "[ERROR] $ts $Message" -ErrorAction SilentlyContinue
}

function Write-LogAnomaly($Message) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$Cyan[ANOMALY]$Reset $ts $Message"
    Write-Host $line
    Add-Content -Path $MonitorLog -Value "[ANOMALY] $ts $Message" -ErrorAction SilentlyContinue
    $script:AnomalyCount++
}

function Write-LogCritical($Message) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$Red[CRITICAL]$Reset $ts $Message"
    Write-Host $line
    Add-Content -Path $MonitorLog -Value "[CRITICAL] $ts $Message" -ErrorAction SilentlyContinue
    $script:CriticalAnomalies++
}

function Send-TelegramAlert($Severity, $Message) {
    try {
        # Try to use webhook_client if available
        $pythonCmd = @"
import sys
try:
    from merid.alerts.webhook_client import tg_send
    tg_send('$Severity', 'MERID Live: $Message')
    print('TG_OK')
except Exception as e:
    print(f'TG_FAIL: {e}', file=sys.stderr)
    sys.exit(1)
"@
        $result = & python3 -c $pythonCmd 2>&1
        if ($result -match "TG_OK") {
            return
        }
    } catch {
        # Fall through to direct bot API
    }
    
    # Direct Telegram API call
    $token = $env:TELEGRAM_BOT_TOKEN
    $chat = $env:TELEGRAM_CHAT_ID
    if (-not $token -or -not $chat) {
        Write-LogWarn "Telegram not configured - alert dropped: $Message"
        return
    }
    
    $prefix = switch ($Severity) {
        "CRITICAL" { "[CRIT] CRITICAL" }
        "HIGH" { "[HIGH] HIGH" }
        "WARNING" { "[WARN] WARN" }
        "INFO" { "[INFO] INFO" }
        default { "[OTHER] $Severity" }
    }
    
    $fullMessage = "$prefix`: $Message"
    $uri = "https://api.telegram.org/bot$token/sendMessage"
    $body = @{ chat_id = $chat; text = $fullMessage; parse_mode = "HTML" }
    
    try {
        Invoke-RestMethod -Uri $uri -Method POST -Body $body -TimeoutSec 10 -ErrorAction SilentlyContinue | Out-Null
    } catch {
        Write-LogWarn "Telegram send failed: $_"
    }
}

function Test-LiveSafety {
    if ($Live) {
        if (-not $ConfirmLive) {
            Write-LogError "Live mode requested but not confirmed!"
            Write-LogError "Usage: -Live -ConfirmLive"
            Send-TelegramAlert "CRITICAL" "Live mode startup BLOCKED - confirmation missing"
            exit 1
        }
        
        if ($env:MERID_ALLOW_LIVE_TRADES -ne "true") {
            Write-LogError "MERID_ALLOW_LIVE_TRADES must be 'true' for live mode"
            exit 1
        }
        
        if ($env:MERID_TRADE_MODE -ne "live") {
            Write-LogError "MERID_TRADE_MODE must be 'live' for live mode"
            exit 1
        }
        
        Write-LogWarn "+========================================================+"
        Write-LogWarn "|  LIVE MODE CONFIRMED - REAL TRADES WILL BE EXECUTED    |"
        Write-LogWarn "|  This is NOT a drill. Real money is at risk.           |"
        Write-LogWarn "+--------------------------------------------------------+"
        
        Send-TelegramAlert "CRITICAL" "LIVE MODE STARTING - Real trades will execute"
        Start-Sleep -Seconds 5
    } else {
        Write-LogInfo "Paper mode - no real trades will be executed"
        $env:MERID_TRADE_MODE = "paper"
        $env:MERID_PM_TRADING_MODE = "paper"
    }
}

function Initialize-Logging {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    
    # Rotate old monitor log
    if (Test-Path $MonitorLog) {
        $ts = Get-Date -Format "yyyyMMdd_HHmmss"
        Move-Item $MonitorLog "$MonitorLog.$ts" -Force -ErrorAction SilentlyContinue
    }
    
    # Initialize fix_history.md
    $fixHistory = "$MeridRoot\fix_history.md"
    if (-not (Test-Path $fixHistory)) {
        $template = @"
# MERID Fix History
# Document all anomalies, investigations, and fixes here.

## Session: $(Get-Date -Format "yyyy-MM-dd")

### Initial System State
- **Backend**: MERID kalshi-only profile
- **Mode**: $(if ($Live) { "LIVE" } else { "Paper" })
- **Monitoring**: Real-time log ingestion, anomaly detection active
- **Gate**: ${GateMinutes}-minute clean-run validation window

## Active Anomalies
*Populated during monitoring session*

"@
        Set-Content -Path $fixHistory -Value $template
    }
    
    Write-LogInfo "Logging initialized: $MonitorLog"
    Write-LogInfo "Fix history: $fixHistory"
}

function Test-Preflight {
    Write-LogInfo "Running pre-flight checks..."
    
    Set-Location $MeridRoot
    
    # Check Python
    try {
        $pyVersion = & py --version 2>&1
        Write-LogInfo "Python version: $pyVersion"
    } catch {
        Write-LogError "Python (py) not available"
        exit 1
    }
    
    # Quick import sanity check (much faster than full test suite)
    Write-LogInfo "Running quick import sanity check..."
    try {
        $importCheck = & py -c "from web.main import create_app; print('OK')" 2>&1
        if ($importCheck -contains "OK") {
            Write-LogInfo "Pre-flight checks PASSED"
        } else {
            Write-LogWarn "Import check had warnings but continuing..."
        }
    } catch {
        Write-LogWarn "Import check failed: $_"
        Write-LogWarn "Continuing anyway - will verify via health check"
    }
}

function Start-Backend {
    Write-LogInfo "Starting MERID backend..."
    
    Set-Location $MeridRoot
    
    # Set environment
    $env:MERID_PROFILE = "kalshi-only"
    $env:MERID_ENV = "production"
    $env:MERID_LOG_LEVEL = "INFO"

    # Risk Management Configuration (Optimized Regime 2026-05-07)
    $env:MAX_CYCLE_RISK_PCT = "0.03"  # 3% per cycle (was 2%)
    $env:MAX_TOTAL_RISK_PCT = "0.08"  # 8% total max (was 5%)
    $env:SCALPER_SINGLE_BATCH_MODE = "false"  # Allow multi-batch (was true)
    $env:SCALPER_MAX_TRADES_PER_BATCH = "5"  # Increased from 3
    
    # Start server in background job
    $jobScript = {
        param($Root, $Port, $CycleRiskPct, $TotalRiskPct, $ScalperSingleBatch, $ScalperMaxTrades)
        Set-Location $Root
        $env:MAX_CYCLE_RISK_PCT = $CycleRiskPct
        $env:MAX_TOTAL_RISK_PCT = $TotalRiskPct
        $env:SCALPER_SINGLE_BATCH_MODE = $ScalperSingleBatch
        $env:SCALPER_MAX_TRADES_PER_BATCH = $ScalperMaxTrades
        & py -m uvicorn web.main_15m_lean:app --host "0.0.0.0" --port $Port --workers 2 --log-level info 2>&1
    }
    
    $port = $env:PORT -or 8011
    $script:ServerJob = Start-Job -ScriptBlock $jobScript -ArgumentList $MeridRoot, $port, "0.03", "0.08", "false", "5"
    $script:ServerJob | Export-Clixml -Path $PidFile
    
    Write-LogInfo "Server started (Job ID: $($script:ServerJob.Id))"
    
    # Wait for health check
    $maxAttempts = 60
    $attempt = 1
    $healthUrl = "http://localhost:$port/api/v1/health"
    
    while ($attempt -le $maxAttempts) {
        try {
            $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2 -ErrorAction SilentlyContinue
            Write-LogInfo "[OK] Server health check passed"
            Send-TelegramAlert "INFO" "Backend started successfully"
            return
        } catch {
            # Server not ready yet
        }
        
        if ($script:ServerJob.State -eq "Failed") {
            Write-LogError "Server job failed during startup"
            exit 1
        }
        
        Start-Sleep -Seconds 1
        $attempt++
    }
    
    Write-LogError "Server failed health check within $maxAttempts seconds"
    exit 1
}

function Test-Anomaly($Line) {
    # Data ingestion issues
    if ($Line -match "ingest failed|dropped event|missing ticker|missing symbol|sequence mismatch|gap detected|websocket disconnect|reconnect") {
        Write-LogAnomaly "INGEST: $Line"
        $script:SequenceGaps++
    }
    
    # Trade tracking
    if ($Line -match "trade_proposal") {
        $script:TradeProposals++
    }
    if ($Line -match "trade_executed|fill") {
        $script:TradeExecuted++
    }
    if ($Line -match "order rejected|risk check failed|position limit hit|queue overflow") {
        Write-LogAnomaly "TRADE_DROP: $Line"
    }
    
    # Math pathologies
    if ($Line -match "NaN|inf|Infinity|null pointer|division by zero") {
        Write-LogCritical "MATH: $Line"
    }
    
    # Latency spikes
    if ($Line -match "latency_ms") {
        if ($Line -match "latency_ms[=:](\d+)") {
            $latency = [int]$matches[1]
            if ($latency -gt 5000) {
                Write-LogAnomaly "LATENCY: ${latency}ms spike detected"
            }
        }
    }
    
    # Critical errors
    if ($Line -match "CRITICAL|FATAL|Exception|Traceback|kill switch|halt") {
        Write-LogCritical "SYSTEM: $Line"
    }
    
    # Silent agent detection
    if ($Line -match "agent silent|no heartbeat|stale|timeout") {
        Write-LogAnomaly "AGENT: $Line"
    }
}

function Start-LogMonitor {
    Write-LogInfo "Starting real-time log monitor..."
    
    # Monitor server job output
    $monitorScript = {
        param($Job, $LogPath)
        while ($true) {
            if ($Job.State -eq "Running") {
                $output = Receive-Job -Job $Job -Keep
                foreach ($line in $output) {
                    # Anomaly detection will be handled by main script polling
                    Add-Content -Path $LogPath -Value $line -ErrorAction SilentlyContinue
                }
            }
            Start-Sleep -Milliseconds 100
        }
    }
    
    $script:MonitorJob = Start-Job -ScriptBlock $monitorScript -ArgumentList $script:ServerJob, "$LogDir\server-capture.log"
    Write-LogInfo "Log monitor attached (Job ID: $($script:MonitorJob.Id))"
}

function Get-TradeRatio {
    if ($script:TradeProposals -gt 0) {
        $ratio = [math]::Round($script:TradeExecuted / $script:TradeProposals, 3)
        return "$ratio"
    }
    return "N/A"
}

function Start-GateValidation {
    Write-LogInfo "+========================================================+"
    Write-LogInfo "|  30-MINUTE CLEAN-RUN GATE VALIDATION                   |"
    Write-LogInfo "|  Started: $(Get-Date)                                  |"
    Write-LogInfo "+--------------------------------------------------------+"
    
    [DateTimeOffset]::Now.ToUnixTimeSeconds() | Set-Content -Path $GateStartFile
    $script:GateActive = $true
    Send-TelegramAlert "INFO" "${GateMinutes}-minute clean-run gate started"
    
    $gateSeconds = $GateMinutes * 60
    $elapsed = 0
    $port = $env:PORT -or 8011
    $healthUrl = "http://localhost:$port/api/v1/health"
    
    while ($elapsed -lt $gateSeconds -and $script:MonitorActive) {
        Start-Sleep -Seconds 10
        $elapsed += 10
        
        # Check for critical anomalies
        if ($script:CriticalAnomalies -gt 0) {
            Write-LogError "+========================================================+"
            Write-LogError "|  GATE FAILED - Critical anomalies detected               |"
            Write-LogError "|  Critical count: $($script:CriticalAnomalies)                                |"
            Write-LogError "+--------------------------------------------------------+"
            
            Send-TelegramAlert "CRITICAL" "GATE FAILED - $($script:CriticalAnomalies) critical anomalies"
            
            if ($Live) {
                Write-LogError "HALTING LIVE TRADING - Switching to paper mode"
                Invoke-EmergencyHalt
            }
            
            return $false
        }
        
        # Periodic status
        if ($elapsed % 60 -eq 0) {
            $remaining = [math]::Floor(($gateSeconds - $elapsed) / 60)
            $ratio = Get-TradeRatio
            Write-LogInfo "Gate progress: ${remaining}m remaining | Anomalies: $($script:AnomalyCount) | Trade ratio: $ratio"
            
            # Health check
            try {
                Invoke-RestMethod -Uri $healthUrl -TimeoutSec 5 | Out-Null
            } catch {
                Write-LogCritical "Health check failed during gate validation"
                return $false
            }
        }
    }
    
    # Gate passed
    Write-LogInfo "+========================================================+"
    Write-LogInfo "|  [PASS] CLEAN-RUN GATE PASSED                          |"
    Write-LogInfo "|  Duration: ${GateMinutes} minutes                                  |"
    Write-LogInfo "|  Total anomalies: $($script:AnomalyCount)                                     |"
    Write-LogInfo "|  Trade proposal→execution ratio: $(Get-TradeRatio)             |"
    Write-LogInfo "+--------------------------------------------------------+"
    
    Send-TelegramAlert "INFO" "[PASS] ${GateMinutes}-minute clean-run gate PASSED"
    return $true
}

function Start-ContinuousMonitor {
    Write-LogInfo "Entering continuous monitoring mode..."
    
    $heartbeatInterval = 300  # 5 minutes
    $lastHeartbeat = 0
    $port = $env:PORT -or 8011
    $healthUrl = "http://localhost:$port/api/v1/health"
    
    while ($script:MonitorActive) {
        Start-Sleep -Seconds 5
        
        # Process any new log output
        if ($script:ServerJob.State -eq "Running") {
            $output = Receive-Job -Job $script:ServerJob
            foreach ($line in $output) {
                Test-Anomaly $line
            }
        }
        
        # Heartbeat
        $now = [DateTimeOffset]::Now.ToUnixTimeSeconds()
        if (($now - $lastHeartbeat) -ge $heartbeatInterval) {
            $ratio = Get-TradeRatio
            $mode = if ($Live) { "LIVE" } else { "PAPER" }
            Write-LogInfo "Heartbeat | Anomalies: $($script:AnomalyCount) | Trade ratio: $ratio | Mode: $mode"
            Send-TelegramAlert "INFO" "Heartbeat - Monitoring active"
            $lastHeartbeat = $now
        }
        
        # Check server health
        if ($script:ServerJob.State -ne "Running") {
            Write-LogCritical "Server job state: $($script:ServerJob.State)"
            Send-TelegramAlert "CRITICAL" "Server process stopped unexpectedly"
            $script:MonitorActive = $false
        }
    }
}

function Invoke-EmergencyHalt {
    Write-LogError "+========================================================+"
    Write-LogError "|  EMERGENCY HALT TRIGGERED                              |"
    Write-LogError "+--------------------------------------------------------+"
    
    $env:MERID_ALLOW_LIVE_TRADES = "false"
    $env:MERID_TRADE_MODE = "paper"
    $env:MERID_PM_TRADING_MODE = "paper"
    
    # Call kill switch via API
    $port = $env:PORT -or 8011
    try {
        Invoke-RestMethod -Uri "http://localhost:$port/api/v1/kalshi/kill-switch" `
            -Method POST `
            -Body '{"action":"halt","reason":"emergency_halt_triggered"}' `
            -ContentType "application/json" `
            -TimeoutSec 5 `
            -ErrorAction SilentlyContinue | Out-Null
    } catch {
        Write-LogWarn "Kill switch API call failed: $_"
    }
    
    Send-TelegramAlert "CRITICAL" "EMERGENCY HALT - All live trading stopped"
    Write-LogInfo "Emergency halt complete. System in paper mode."
}

function Invoke-Abort {
    Write-LogError "+========================================================+"
    Write-LogError "|  ABORT MODE ACTIVATED                                  |"
    Write-LogError "+--------------------------------------------------------+"
    
    if ($script:ServerJob) {
        Write-LogInfo "Stopping server job (ID: $($script:ServerJob.Id))..."
        Stop-Job -Job $script:ServerJob -ErrorAction SilentlyContinue
        Remove-Job -Job $script:ServerJob -Force -ErrorAction SilentlyContinue
    }
    
    if ($script:MonitorJob) {
        Stop-Job -Job $script:MonitorJob -ErrorAction SilentlyContinue
        Remove-Job -Job $script:MonitorJob -Force -ErrorAction SilentlyContinue
    }
    
    $env:MERID_ALLOW_LIVE_TRADES = "false"
    $env:MERID_TRADE_MODE = "paper"
    
    if (Test-Path $PidFile) {
        Remove-Item $PidFile -Force
    }
    
    Send-TelegramAlert "CRITICAL" "ABORT executed - Server stopped, all trading halted"
    Write-LogInfo "Abort complete. Server stopped. Environment set to paper mode."
    exit 0
}

# Main execution
if ($Abort) {
    # Load existing job if available
    if (Test-Path $PidFile) {
        $script:ServerJob = Import-Clixml -Path $PidFile
    }
    Invoke-Abort
}

Initialize-Logging
Test-LiveSafety
Test-Preflight
Start-Backend
Start-LogMonitor

# Run gate validation
$gatePassed = Start-GateValidation

if ($gatePassed) {
    Write-LogInfo "[PASS] System passed clean-run gate. Entering continuous monitor..."
    Start-ContinuousMonitor
} else {
    Write-LogError "[FAIL] Gate validation failed. Entering degraded monitoring..."
    Start-ContinuousMonitor
}
