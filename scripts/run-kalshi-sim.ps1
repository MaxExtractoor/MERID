$ErrorActionPreference = "Stop"

# Usage:
#   ./scripts/run-kalshi-sim.ps1 -Command "py -m merid.loop"
param(
  [Parameter(Mandatory = $true)]
  [string]$Command
)

& "$PSScriptRoot/run-with-env.ps1" -EnvFile "$PSScriptRoot/../.env.kalshi-sim" -Command $Command
