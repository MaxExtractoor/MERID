@echo off
cd /d c:\Dev\MERID

REM Create virtual environment if it doesn't exist
if not exist ".venv" (
    py -3.11 -m venv .venv
)

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Install dependencies
pip install -e . >nul 2>&1
pip install pytest fastapi httpx >nul 2>&1

REM Set environment variable to disable plugin autoloading
set PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

REM Run risk tests
echo Running risk enforcement tests...
pytest tests/risk/test_unified_risk_enforcement.py -vv --tb=short -p no:langsmith -p no:charset_normalizer > test_output_risk.txt 2>&1
echo Risk tests exit code: %ERRORLEVEL%

REM Run scenario tests
echo Running scenario tests...
pytest tests/scenario/test_pass9_scenarios.py -vv --tb=short -p no:langsmith -p no:charset_normalizer > test_output_scenario.txt 2>&1
echo Scenario tests exit code: %ERRORLEVEL%

echo.
echo Test complete. Check test_output_risk.txt and test_output_scenario.txt for results.
