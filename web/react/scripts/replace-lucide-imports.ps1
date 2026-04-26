# Replace direct lucide-react imports with centralized icons module
param(
  [string]$Root = "src"
)

$srcRoot = Resolve-Path $Root
$iconsPath = Join-Path $srcRoot "ui\icons.ts"

$files = Get-ChildItem -Path $srcRoot -Recurse -Include *.ts,*.tsx | Where-Object {
  $_.FullName -notmatch 'icons\.ts$' -and
  $_.FullName -notmatch '__tests__' -and
  $_.FullName -notmatch '\.test\.'
}

foreach ($f in $files) {
  $content = Get-Content -Raw $f.FullName
  if ($content -notmatch "from ['""]lucide-react['""]") { continue }

  # Compute relative path from file to ui/icons
  $fileDir = Split-Path -Parent $f.FullName
  $rel = [System.IO.Path]::GetRelativePath($fileDir, (Join-Path $srcRoot "ui\icons"))
  $rel = $rel -replace '\\', '/'
  if (-not $rel.StartsWith('.')) { $rel = './' + $rel }
  # Strip .ts extension if accidentally included
  $rel = $rel -replace '\.ts$', ''

  $newContent = $content -replace "from ['""]lucide-react['""]", "from '$rel'"

  if ($newContent -ne $content) {
    Set-Content -NoNewline -Path $f.FullName -Value $newContent
    Write-Host "Updated: $($f.FullName) -> from '$rel'"
  }
}
