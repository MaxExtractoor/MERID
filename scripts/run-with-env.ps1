$ErrorActionPreference = "Stop"

param(
  [Parameter(Mandatory = $true)]
  [string]$EnvFile,

  [Parameter(Mandatory = $true)]
  [string]$Command
)

if (-not (Test-Path -LiteralPath $EnvFile)) {
  throw "Env file not found: $EnvFile"
}

function Set-EnvFromFile([string]$Path) {
  Get-Content -LiteralPath $Path | ForEach-Object {
    $line = $_.Trim()
    if ($line.Length -eq 0) { return }
    if ($line.StartsWith("#")) { return }

    $idx = $line.IndexOf("=")
    if ($idx -lt 1) { return }

    $k = $line.Substring(0, $idx).Trim()
    $v = $line.Substring($idx + 1).Trim()

    # Strip surrounding quotes if present
    if (($v.StartsWith('"') -and $v.EndsWith('"')) -or ($v.StartsWith("'") -and $v.EndsWith("'"))) {
      $v = $v.Substring(1, $v.Length - 2)
    }

    [System.Environment]::SetEnvironmentVariable($k, $v, "Process") | Out-Null
  }
}

Set-EnvFromFile -Path $EnvFile
Write-Host "Loaded env from $EnvFile"
Write-Host "Running: $Command"

Invoke-Expression $Command
