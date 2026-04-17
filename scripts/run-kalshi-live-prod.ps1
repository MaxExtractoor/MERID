$ErrorActionPreference = "Stop"

# Usage:
#   ./scripts/run-kalshi-live-prod.ps1 -Command "py -m merid.loop"
param(
  [Parameter(Mandatory = $true)]
  [string]$Command
)

& "$PSScriptRoot/run-with-env.ps1" -EnvFile "$PSScriptRoot/../.env.kalshi-live-prod" -Command $Command
