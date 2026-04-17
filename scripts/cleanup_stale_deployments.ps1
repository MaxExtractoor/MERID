<# 
.SYNOPSIS
    Clean up stale GitHub deployment records for MaxExtractoor/MERID.
.DESCRIPTION
    Lists all deployments, marks them inactive, then deletes them.
    Requires a GitHub Personal Access Token with repo scope.
    Generate one at: https://github.com/settings/tokens/new?scopes=repo
.USAGE
    $env:GH_TOKEN = "ghp_yourtoken"; .\scripts\cleanup_stale_deployments.ps1
#>
param(
    [string]$Token = $env:GH_TOKEN,
    [switch]$Force
)

$Owner = "MaxExtractoor"
$Repo = "MERID"
$BaseUrl = "https://api.github.com/repos/$Owner/$Repo"

if (-not $Token) {
    Write-Host "No token found. Set `$env:GH_TOKEN or pass -Token <pat>" -ForegroundColor Red
    Write-Host "Generate one at: https://github.com/settings/tokens/new?scopes=repo" -ForegroundColor Yellow
    exit 1
}
$plainToken = $Token

$headers = @{
    Authorization = "token $plainToken"
    Accept        = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

# --- List all deployments (paginated) ---
Write-Host "`n=== Fetching deployments ===" -ForegroundColor Cyan
$allDeployments = @()
$page = 1
do {
    $url = "$BaseUrl/deployments?per_page=100&page=$page"
    try {
        $batch = Invoke-RestMethod -Uri $url -Headers $headers -Method Get
    } catch {
        Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "Make sure your PAT has 'repo' scope." -ForegroundColor Yellow
        exit 1
    }
    $allDeployments += $batch
    $page++
} while ($batch.Count -eq 100)

Write-Host "Found $($allDeployments.Count) deployment(s)" -ForegroundColor White

if ($allDeployments.Count -eq 0) {
    Write-Host "Nothing to clean up!" -ForegroundColor Green
    exit 0
}

# --- Show summary ---
$envGroups = $allDeployments | Group-Object { $_.environment } | Sort-Object Count -Descending
foreach ($g in $envGroups) {
    Write-Host "  Environment '$($g.Name)': $($g.Count) deployments" -ForegroundColor Gray
}

if (-not $Force) {
    $confirm = Read-Host "`nDelete ALL $($allDeployments.Count) deployment records? (yes/no)"
    if ($confirm -ne "yes") {
        Write-Host "Aborted." -ForegroundColor Yellow
        exit 0
    }
} else {
    Write-Host "`nForce mode: deleting all $($allDeployments.Count) deployment records..." -ForegroundColor Yellow
}

# --- Mark each deployment inactive, then delete ---
$deleted = 0
$failed = 0
foreach ($dep in $allDeployments) {
    $id = $dep.id
    $env = $dep.environment
    
    # Step 1: Create an "inactive" status so GitHub allows deletion
    try {
        $statusUrl = "$BaseUrl/deployments/$id/statuses"
        $body = @{ state = "inactive" } | ConvertTo-Json
        Invoke-RestMethod -Uri $statusUrl -Headers $headers -Method Post -Body $body -ContentType "application/json" | Out-Null
    } catch {
        # May fail if already inactive — that's fine
    }

    # Step 2: Delete the deployment
    try {
        $delUrl = "$BaseUrl/deployments/$id"
        Invoke-RestMethod -Uri $delUrl -Headers $headers -Method Delete | Out-Null
        $deleted++
        Write-Host "  Deleted deployment $id ($env)" -ForegroundColor Green
    } catch {
        $failed++
        Write-Host "  Failed to delete $id ($env): $($_.Exception.Message)" -ForegroundColor Red
    }
}

Write-Host "`n=== Done ===" -ForegroundColor Cyan
Write-Host "Deleted: $deleted  |  Failed: $failed" -ForegroundColor White
