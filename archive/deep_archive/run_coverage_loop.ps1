# run_coverage_loop.ps1
# Auto-activate venv, run coverage, show worst modules, repeat.

param(
    [int]$Iterations = 5
)

Write-Host "=== MERID Coverage Loop Starting (Iterations = $Iterations) ===" -ForegroundColor Cyan

# 1) Activate venv
& "$PSScriptRoot\.venv\Scripts\Activate.ps1"

for ($i = 1; $i -le $Iterations; $i++) {
    Write-Host ""
    Write-Host "=== Coverage Pass $i of $Iterations ===" -ForegroundColor Yellow

    # 2) Run tests with coverage
    pytest tests --cov=merid --cov-report=term-missing

    if ($LASTEXITCODE -ne 0) {
        Write-Host "Pytest failed (exit $LASTEXITCODE). Fix tests, then rerun the loop." -ForegroundColor Red
        break
    }

    # 3) Optional: run checklist to surface uncovered functions
    pytest --checklist-collect=merid,trading,core --checklist-report

    if ($LASTEXITCODE -ne 0) {
        Write-Host "pytest-checklist failed (exit $LASTEXITCODE). Check pytest.ini / markers." -ForegroundColor Red
        break
    }

    Write-Host "=== Pass $i complete. Adjust tests based on report, then rerun loop if needed. ===" -ForegroundColor Green
}

Write-Host "=== MERID Coverage Loop Finished ===" -ForegroundColor Cyan
