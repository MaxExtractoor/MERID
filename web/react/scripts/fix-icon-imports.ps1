# Fix broken `from './'` imports (and any remaining `from 'lucide-react'`)
# by computing the correct relative path to src/ui/icons for each file.
param(
  [string]$Root = "src"
)

function Get-RelPath($fromDir, $toPath) {
  $fromUri = New-Object Uri(($fromDir.TrimEnd('\') + '\'))
  $toUri = New-Object Uri($toPath)
  $rel = $fromUri.MakeRelativeUri($toUri).ToString()
  $rel = [Uri]::UnescapeDataString($rel)
  if (-not $rel.StartsWith('../') -and -not $rel.StartsWith('./')) {
    $rel = './' + $rel
  }
  return $rel
}

$srcRoot = (Resolve-Path $Root).Path
$iconsTarget = Join-Path $srcRoot "ui\icons"

$files = Get-ChildItem -Path $srcRoot -Recurse -Include *.ts,*.tsx | Where-Object {
  $_.FullName -notmatch 'icons\.ts$' -and
  $_.FullName -notmatch '__tests__' -and
  $_.FullName -notmatch '\.test\.'
}

foreach ($f in $files) {
  $content = Get-Content -Raw $f.FullName
  $hasBroken = $content -match "import\s*\{[^}]+\}\s*from\s*['""]\./['""]"
  $hasLucide = $content -match "from\s*['""]lucide-react['""]"
  if (-not ($hasBroken -or $hasLucide)) { continue }

  $fileDir = Split-Path -Parent $f.FullName
  $rel = Get-RelPath $fileDir $iconsTarget
  $rel = $rel -replace '\\', '/'

  # Only replace if the `from './'` import is our known icon import pattern
  # (has braces with icon names on the preceding line or same line)
  $newContent = $content
  # Replace `from 'lucide-react'` first (safe)
  $newContent = $newContent -replace "from\s*['""]lucide-react['""]", "from '$rel'"
  # Replace `from './'` where we broke it
  $newContent = $newContent -replace "from\s*['""]\./['""]", "from '$rel'"

  if ($newContent -ne $content) {
    Set-Content -NoNewline -Path $f.FullName -Value $newContent
    Write-Host "Updated: $($f.FullName) -> from '$rel'"
  }
}
