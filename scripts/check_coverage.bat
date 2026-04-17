@echo off
REM Quick coverage check script for MERID (Windows)

echo Running Tier 1 coverage check (95%% threshold)...
pytest --cov-config=.coveragerc ^
  --cov=trading/execution --cov=merid/event_venues ^
  --cov-report=term-missing ^
  --cov-fail-under=95 tests/

if %ERRORLEVEL% neq 0 (
  echo Tier 1 coverage check failed!
  exit /b 1
)

echo Running Tier 2 coverage check (85%% threshold)...
pytest --cov-config=.coveragerc ^
  --cov=core --cov=trading/router ^
  --cov-report=term-missing ^
  --cov-fail-under=85 tests/

if %ERRORLEVEL% neq 0 (
  echo Tier 2 coverage check failed!
  exit /b 1
)

echo Coverage checks complete!
