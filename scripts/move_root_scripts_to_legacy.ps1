# Move root-level one-shot/historical scripts to scripts/legacy/
# Run from repo root: powershell -File scripts/move_root_scripts_to_legacy.ps1

$legacyDir = "scripts/legacy"
if (-not (Test-Path $legacyDir)) { New-Item -ItemType Directory -Path $legacyDir | Out-Null }

# Patterns to move (one-shot scripts, NOT core entry points)
$patterns = @(
    "test_*.py",
    "generate_*.py",
    "run_phase*.py",
    "run_week*.py",
    "run_batch*.py",
    "run_*_experiment*.py",
    "run_hardening*.py",
    "run_stress*.py",
    "run_tests.py",
    "run_fault_injection.py",
    "run_config_refactor_pilot.py",
    "run_feature_flag_experiment.py",
    "run_no_thrash_weekly_review.py",
    "run_weekly_strict_review.py",
    "run_single_topology_experiment.py",
    "run_tiny_experiments.py",
    "backfill_phase*.py",
    "phase*_playbook.py",
    "phase*_planning.py",
    "complete_*.py",
    "debug_*.py",
    "demo_*.py",
    "design_*.py",
    "diagnose_*.py",
    "extend_*.py",
    "implement_*.py",
    "initialize_*.py",
    "inspect_*.py",
    "integrate_*.py",
    "weekly_review*.py",
    "analyze_results.py",
    "check_actual_status.py",
    "check_analytics.py",
    "clean_test.py",
    "create_fast_agent.py",
    "create_favicon.py",
    "create_scaling_plan.py",
    "critical_syntax_scanner.py",
    "define_official_roadmap.py",
    "deploy_slo_changes.py",
    "ensure_strategy_policy_accuracy_column.py",
    "monitor_production_dashboard.py",
    "neo4j_schema_fix.py",
    "neo4j_writer.py",
    "optimize_agent_performance.py",
    "remove_mock_data.py",
    "robustness_*.py",
    "setup_shadow_database.py",
    "simple_robustness_test.py",
    "simple_test.py",
    "simple_test_agent.py",
    "simple_tracker.py",
    "simple_validation.py",
    "syntax_error_fixer.py",
    "syntax_scanner.py",
    "track_execution.py",
    "track_quarter_goals.py",
    "validate_imports.py",
    "validate_live_integration.py",
    "validate_live_only_mode.py",
    "verify_favicon.py",
    "verify_system.py",
    "autonomous_soak_test.py",
    "audit_endpoints.py",
    "production_test.py",
    "extended_test.py",
    "final_comprehensive_test.py",
    "IMPLEMENTATION-OPTION-*.py"
)

# Exclude core entry points that should stay at root
$exclude = @(
    "conftest.py",
    "conftest_cohesive.py",
    "conftest_production.py",
    "conftest_threaded.py",
    "gunicorn_conf.py",
    "gunicorn_forkserver_conf.py",
    "main.py",
    "merid_api.py",
    "merid_app.py",
    "merid_bootstrap.py",
    "merid_logging.py",
    "merid_logging_config.py",
    "merid_logging_queue.py",
    "merid_metrics.py",
    "meridctl.py",
    "meridctl_logging_only.py",
    "meridctl_simple.py",
    "my_gunicorn_logger.py",
    "sitecustomize.py",
    "start_merid.py",
    "startup.py",
    "startup_minimal.py",
    "tools.py",
    "tmp_np.py"
)

$moved = 0
foreach ($pattern in $patterns) {
    $files = Get-ChildItem -Path "." -Name $pattern -File -Depth 0 2>$null
    foreach ($file in $files) {
        if ($exclude -contains $file) { continue }
        if (Test-Path $file) {
            git mv $file "$legacyDir/$file"
            $moved++
        }
    }
}

Write-Host "Moved $moved files to $legacyDir/"
Write-Host "Review with: git status"
Write-Host "Commit with: git commit -m 'chore: move legacy root scripts to scripts/legacy/'"
