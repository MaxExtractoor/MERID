@echo off
cd c:\Dev\MERID
call .venv\Scripts\activate.bat
set PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
.venv\Scripts\python.exe -m pytest tests/risk/test_unified_risk_enforcement.py -vv --tb=short -p no:langsmith -p no:charset_normalizer > risk_results.txt 2>&1
echo Risk tests exit code: %ERRORLEVEL%
.venv\Scripts\python.exe -m pytest tests/scenario/test_pass9_scenarios.py -vv --tb=short -p no:langsmith -p no:charset_normalizer > scenario_results.txt 2>&1
echo Scenario tests exit code: %ERRORLEVEL%
