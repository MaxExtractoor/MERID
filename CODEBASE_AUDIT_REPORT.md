# MERID Codebase Audit Report

**Generated**: 2026-01-16T02:36:29.557949

## Summary

- **Files Scanned**: 837
- **Lines Scanned**: 222213
- **Total Findings**: 267

### By Severity

- **Critical**: 0
- **High**: 19
- **Medium**: 122
- **Low**: 126

### By Category

- **documentation**: 126
- **fake_code**: 122
- **security**: 19

## Findings

### HIGH Severity

#### flutter\engine\src\build\android\gyp\util\build_utils.py:77

- **Category**: security
- **Description**: Use of eval(): return ast.literal_eval(gn_string)
- **Recommendation**: Review and secure implementation

#### flutter\engine\src\build\toolchain\win\tool_wrapper.py:189

- **Category**: security
- **Description**: Shell injection risk: return subprocess.call(args, shell=True, env=env, cwd=dirname)
- **Recommendation**: Review and secure implementation

#### flutter\engine\src\flutter\ci\scan_deps.py:66

- **Category**: security
- **Description**: Use of exec(): exec(deps_content, global_scope, local_scope)
- **Recommendation**: Review and secure implementation

#### flutter\engine\src\tools\dart\create_updated_flutter_deps.py:49

- **Category**: security
- **Description**: Use of exec(): exec(deps_content, global_scope, local_scope)
- **Recommendation**: Review and secure implementation

#### lib\agents\weather-agent.py:7

- **Category**: security
- **Description**: Hardcoded API key: api_key = "your_openweather_key"
- **Recommendation**: Review and secure implementation

#### lib\merid\relay.py:11

- **Category**: security
- **Description**: Hardcoded API key: local_client = OpenAI(base_url='http://localhost:11434/v1/', api_key='ollama')
- **Recommendation**: Review and secure implementation

#### qa\codebase_audit_engine.py:66

- **Category**: security
- **Description**: Use of eval(): (r'eval\s*\(', "Use of eval()"),
- **Recommendation**: Review and secure implementation

#### qa\codebase_audit_engine.py:67

- **Category**: security
- **Description**: Use of exec(): (r'exec\s*\(', "Use of exec()"),
- **Recommendation**: Review and secure implementation

#### security\automated_compliance_checker.py:41

- **Category**: security
- **Description**: Use of eval(): """Safely evaluate compliance rule expression without eval()."""
- **Recommendation**: Review and secure implementation

#### swarm\collaborative_swarm_guardrails.py:211

- **Category**: security
- **Description**: Use of eval(): ("eval(", "Use of eval()"),
- **Recommendation**: Review and secure implementation

#### swarm\collaborative_swarm_guardrails.py:212

- **Category**: security
- **Description**: Use of exec(): ("exec(", "Use of exec()"),
- **Recommendation**: Review and secure implementation

#### swarm\collaborative_swarm_guardrails.py:214

- **Category**: security
- **Description**: Direct system call: ("os.system(", "Direct system calls"),
- **Recommendation**: Review and secure implementation

#### swarm\collaborative_swarm_guardrails.py:216

- **Category**: security
- **Description**: Unsafe deserialization: ("pickle.loads(", "Unsafe deserialization"),
- **Recommendation**: Review and secure implementation

#### swarm\llm_gateway.py:227

- **Category**: security
- **Description**: Hardcoded API key: api_key="sk-...",  # Mock
- **Recommendation**: Review and secure implementation

#### swarm\llm_gateway.py:241

- **Category**: security
- **Description**: Hardcoded API key: api_key="sk-ant-...",  # Mock
- **Recommendation**: Review and secure implementation

#### swarm\llm_gateway.py:255

- **Category**: security
- **Description**: Hardcoded API key: api_key="local",
- **Recommendation**: Review and secure implementation

#### tests\test_security_fixes.py:70

- **Category**: security
- **Description**: Use of eval(): """Test safe compliance rule evaluation without eval()."""
- **Recommendation**: Review and secure implementation

#### tests\test_security_fixes.py:151

- **Category**: security
- **Description**: Use of eval(): "eval('1+1')",
- **Recommendation**: Review and secure implementation

#### tests\test_security_fixes.py:152

- **Category**: security
- **Description**: Use of exec(): "exec('print(1)')",
- **Recommendation**: Review and secure implementation

### MEDIUM Severity

#### agents\agent_framework.py:214

- **Category**: fake_code
- **Description**: TODO marker: average_latency_ms=0.0,  # TODO: Track latency
- **Recommendation**: Complete implementation or remove placeholder

#### agents\agent_framework.py:120

- **Category**: fake_code
- **Description**: Empty function: make_decision
- **Recommendation**: Implement function or document why it's empty

#### agents\interface.py:350

- **Category**: fake_code
- **Description**: Not implemented: raise NotImplementedError
- **Recommendation**: Complete implementation or remove placeholder

#### agents\interface.py:363

- **Category**: fake_code
- **Description**: Not implemented: raise NotImplementedError
- **Recommendation**: Complete implementation or remove placeholder

#### agents\interface.py:379

- **Category**: fake_code
- **Description**: Not implemented: raise NotImplementedError
- **Recommendation**: Complete implementation or remove placeholder

#### agents\interface.py:392

- **Category**: fake_code
- **Description**: Not implemented: raise NotImplementedError
- **Recommendation**: Complete implementation or remove placeholder

#### agents\unified_decision_layer.py:353

- **Category**: fake_code
- **Description**: TODO marker: "weight": 1.0,  # TODO: Calculate based on performance
- **Recommendation**: Complete implementation or remove placeholder

#### agents\core\news_analyst.py:95

- **Category**: fake_code
- **Description**: HACK marker: "bearish", "crash", "dump", "plunge", "ban", "regulation", "hack",
- **Recommendation**: Complete implementation or remove placeholder

#### agents\core\news_analyst.py:102

- **Category**: fake_code
- **Description**: HACK marker: "sec", "regulation", "ban", "etf", "approval", "hack", "exploit",
- **Recommendation**: Complete implementation or remove placeholder

#### agents\core\news_analyst.py:420

- **Category**: fake_code
- **Description**: HACK marker: if any(word in text for word in ["hack", "exploit", "scam", "fraud", "security"]):
- **Recommendation**: Complete implementation or remove placeholder

#### agents\streaming\news_analyst.py:31

- **Category**: fake_code
- **Description**: HACK marker: 'sec', 'regulation', 'ban', 'hack', 'exploit', 'etf',
- **Recommendation**: Complete implementation or remove placeholder

#### backup\recovery.py:149

- **Category**: fake_code
- **Description**: Empty function: _register_default_handlers
- **Recommendation**: Implement function or document why it's empty

#### backup\snapshot.py:158

- **Category**: fake_code
- **Description**: Empty function: _register_default_collectors
- **Recommendation**: Implement function or document why it's empty

#### core\cache_manager.py:385

- **Category**: fake_code
- **Description**: Empty function: decorator
- **Recommendation**: Implement function or document why it's empty

#### core\health_probes.py:66

- **Category**: fake_code
- **Description**: Empty function: check
- **Recommendation**: Implement function or document why it's empty

#### core\performance_tracker.py:343

- **Category**: fake_code
- **Description**: Empty function: decorator
- **Recommendation**: Implement function or document why it's empty

#### core\strategy_versioning.py:152

- **Category**: fake_code
- **Description**: Empty function: _deregister_social_assets
- **Recommendation**: Implement function or document why it's empty

#### core\validation\base.py:26

- **Category**: fake_code
- **Description**: Not implemented: raise NotImplementedError
- **Recommendation**: Complete implementation or remove placeholder

#### defi\aave.py:477

- **Category**: fake_code
- **Description**: Not implemented: raise NotImplementedError("On-chain execution requires web3 setup")
- **Recommendation**: Complete implementation or remove placeholder

#### defi\aave.py:486

- **Category**: fake_code
- **Description**: Not implemented: raise NotImplementedError("On-chain execution requires web3 setup")
- **Recommendation**: Complete implementation or remove placeholder

#### defi\aave.py:488

- **Category**: fake_code
- **Description**: Empty function: _refresh_account_data
- **Recommendation**: Implement function or document why it's empty

#### defi\aave.py:492

- **Category**: fake_code
- **Description**: Empty function: _refresh_positions
- **Recommendation**: Implement function or document why it's empty

#### flutter\engine\src\build\vs_toolchain.py:83

- **Category**: fake_code
- **Description**: TODO marker: # TODO(scottmg): The order unfortunately matters in these. They should be
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\build\vs_toolchain.py:412

- **Category**: fake_code
- **Description**: TODO marker: # TODO(crbug.com/773476): remove version requirement.
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\build\android\gyp\javac.py:77

- **Category**: fake_code
- **Description**: TODO marker: # TODO(camsim99): Fix deprecations:
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\build\android\gyp\util\build_utils.py:83

- **Category**: fake_code
- **Description**: TODO marker: # TODO(cjhopman): Remove when
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\build\config\linux\sysroot_ld_path.py:8

- **Category**: fake_code
- **Description**: TODO marker: # TODO(brettw) the build/linux/sysroot_ld_path.sh script should be rewritten in
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\build\linux\sysroot_scripts\install-sysroot.py:111

- **Category**: fake_code
- **Description**: TODO marker: # TODO(thestig) Consider putting this elsewhere to avoid having to recreate
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\build\toolchain\win\setup_toolchain.py:35

- **Category**: fake_code
- **Description**: TODO marker: 'goma_.*', # TODO(scottmg): This is ugly, but needed for goma.
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\build\toolchain\win\setup_toolchain.py:259

- **Category**: fake_code
- **Description**: TODO marker: # TODO(scottmg|goma): Do we need an equivalent of
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\build\toolchain\win\tool_wrapper.py:182

- **Category**: fake_code
- **Description**: TODO marker: # TODO(scottmg): This is a temporary hack to get some specific variables
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\build\toolchain\win\tool_wrapper.py:182

- **Category**: fake_code
- **Description**: HACK marker: # TODO(scottmg): This is a temporary hack to get some specific variables
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\flutter\ci\compatibility_helper.py:16

- **Category**: fake_code
- **Description**: TODO marker: TODO: This function should be removed when the supported python
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\flutter\shell\platform\fuchsia\flutter\build\gen_debug_wrapper_main.py:43

- **Category**: fake_code
- **Description**: TODO marker: // TODO(awdavies): Use the logger instead.
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\flutter\shell\platform\fuchsia\flutter\build\gen_debug_wrapper_main.py:54

- **Category**: fake_code
- **Description**: TODO marker: // TODO(awdavies): Use the logger instead.
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\flutter\shell\platform\fuchsia\flutter\build\gen_debug_wrapper_main.py:58

- **Category**: fake_code
- **Description**: TODO marker: // TODO(awdavies): Use the logger instead.
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\flutter\sky\tools\create_embedder_framework.py:32

- **Category**: fake_code
- **Description**: TODO marker: # TODO(godofredoc): Remove after recipes v2 have landed.
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\flutter\sky\tools\create_macos_framework.py:88

- **Category**: fake_code
- **Description**: TODO marker: # TODO(cbracken): Remove the zip file from the path when outer zip is removed.
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\flutter\sky\tools\create_macos_framework.py:96

- **Category**: fake_code
- **Description**: TODO marker: # TODO(fujino): remove this once https://github.com/flutter/flutter/issues/125067 is resolved
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\flutter\sky\tools\create_macos_framework.py:102

- **Category**: fake_code
- **Description**: TODO marker: # TODO(cbracken): Move these files to inner zip before removing the outer zip.
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\flutter\testing\run_tests.py:549

- **Category**: fake_code
- **Description**: TODO marker: # TODO(https://github.com/flutter/flutter/issues/123733): Remove this allowlist.
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\flutter\testing\run_tests.py:559

- **Category**: fake_code
- **Description**: TODO marker: # TODO(matanlurey): https://github.com/flutter/flutter/issues/134852; enable
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\flutter\testing\run_tests.py:583

- **Category**: fake_code
- **Description**: TODO marker: # TODO(https://github.com/flutter/flutter/issues/145036)
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\flutter\testing\run_tests.py:584

- **Category**: fake_code
- **Description**: TODO marker: # TODO(https://github.com/flutter/flutter/issues/142642)
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\flutter\testing\run_tests.py:710

- **Category**: fake_code
- **Description**: TODO marker: # TODO ricardoamador: remove this check when python 2 is deprecated.
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\flutter\testing\fuchsia\run_tests.py:102

- **Category**: fake_code
- **Description**: TODO marker: # TODO(zijiehe-google-com): Run all tests in release build,
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\flutter\tools\fuchsia\build_fuchsia_artifacts.py:218

- **Category**: fake_code
- **Description**: TODO marker: # TODO ricardoamador: remove this check when python 2 is deprecated.
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\flutter\tools\fuchsia\build_fuchsia_artifacts.py:373

- **Category**: fake_code
- **Description**: HACK marker: 'with optimized builds. This is a hack to allow infra to make '
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\flutter\tools\fuchsia\build_fuchsia_artifacts.py:377

- **Category**: fake_code
- **Description**: TODO marker: # TODO(http://fxb/110639): Deprecate this in favor of multiple runtime parameters
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\flutter\tools\fuchsia\build_fuchsia_artifacts.py:408

- **Category**: fake_code
- **Description**: HACK marker: # This is a hack. The recipe for building and uploading Fuchsia to CIPD
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\flutter\tools\fuchsia\build_fuchsia_artifacts.py:414

- **Category**: fake_code
- **Description**: TODO marker: # TODO(akbiggs): Consolidate Fuchsia's building and copying logic to
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\flutter\tools\fuchsia\copy_debug_symbols.py:114

- **Category**: fake_code
- **Description**: TODO marker: # TODO(dnfield): use exist_ok when we upgrade to python 3, rather than try
- **Recommendation**: Complete implementation or remove placeholder

#### flutter\engine\src\flutter\tools\fuchsia\dart\gen_dart_package_config.py:95

- **Category**: fake_code
- **Description**: TODO marker: # TODO(fxbug.dev/56428): enable once we sort out our duplicate packages
- **Recommendation**: Complete implementation or remove placeholder

#### integration\integration_wiring.py:347

- **Category**: fake_code
- **Description**: Empty function: wire_to_orchestration
- **Recommendation**: Implement function or document why it's empty

#### integration\integration_wiring.py:381

- **Category**: fake_code
- **Description**: Empty function: wire_to_dashboard
- **Recommendation**: Implement function or document why it's empty

#### integration\integration_wiring.py:416

- **Category**: fake_code
- **Description**: Empty function: wire_to_deployment
- **Recommendation**: Implement function or document why it's empty

#### integration\integration_wiring.py:450

- **Category**: fake_code
- **Description**: Empty function: wire_secure_channel
- **Recommendation**: Implement function or document why it's empty

#### integration\integration_wiring.py:487

- **Category**: fake_code
- **Description**: Empty function: wire_canary_automation
- **Recommendation**: Implement function or document why it's empty

#### learning\marl\base.py:281

- **Category**: fake_code
- **Description**: Not implemented: raise NotImplementedError
- **Recommendation**: Complete implementation or remove placeholder

#### learning\marl\base.py:285

- **Category**: fake_code
- **Description**: Not implemented: raise NotImplementedError
- **Recommendation**: Complete implementation or remove placeholder

#### learning\marl\base.py:199

- **Category**: fake_code
- **Description**: Empty function: get_log_prob
- **Recommendation**: Implement function or document why it's empty

#### learning\marl\base.py:275

- **Category**: fake_code
- **Description**: Empty function: get_global_state
- **Recommendation**: Implement function or document why it's empty

#### monitoring\health_checker.py:124

- **Category**: fake_code
- **Description**: Empty function: _init_default_checks
- **Recommendation**: Implement function or document why it's empty

#### monitoring\intelligence_layer.py:130

- **Category**: fake_code
- **Description**: HACK marker: "hack", "exploit", "ban", "regulation", "lawsuit", "sec",
- **Recommendation**: Complete implementation or remove placeholder

#### monitoring\liquidation_monitor.py:108

- **Category**: fake_code
- **Description**: Not implemented: raise NotImplementedError
- **Recommendation**: Complete implementation or remove placeholder

#### monitoring\liquidation_monitor.py:111

- **Category**: fake_code
- **Description**: Not implemented: raise NotImplementedError
- **Recommendation**: Complete implementation or remove placeholder

#### monitoring\news_feeds.py:132

- **Category**: fake_code
- **Description**: HACK marker: high_keywords = ["breaking", "sec", "regulation", "hack", "exploit", "etf", "bitcoin", "ethereum"]
- **Recommendation**: Complete implementation or remove placeholder

#### monitoring\prediction_markets.py:276

- **Category**: fake_code
- **Description**: Not implemented: raise NotImplementedError
- **Recommendation**: Complete implementation or remove placeholder

#### monitoring\prediction_markets.py:280

- **Category**: fake_code
- **Description**: Not implemented: raise NotImplementedError
- **Recommendation**: Complete implementation or remove placeholder

#### notifications\channels.py:99

- **Category**: fake_code
- **Description**: Empty function: validate_recipient
- **Recommendation**: Implement function or document why it's empty

#### oracles\base_oracle.py:223

- **Category**: fake_code
- **Description**: Not implemented: raise NotImplementedError
- **Recommendation**: Complete implementation or remove placeholder

#### oracles\base_oracle.py:228

- **Category**: fake_code
- **Description**: Not implemented: raise NotImplementedError
- **Recommendation**: Complete implementation or remove placeholder

#### oracles\base_oracle.py:233

- **Category**: fake_code
- **Description**: Not implemented: raise NotImplementedError
- **Recommendation**: Complete implementation or remove placeholder

#### plugins\plugin_base.py:135

- **Category**: fake_code
- **Description**: Empty function: on_disable
- **Recommendation**: Implement function or document why it's empty

#### plugins\plugin_registry.py:184

- **Category**: fake_code
- **Description**: Empty function: get_dependency_tree
- **Recommendation**: Implement function or document why it's empty

#### qa\codebase_audit_engine.py:42

- **Category**: fake_code
- **Description**: TODO marker: - Fake code detection (TODO, FIXME, pass-only functions)
- **Recommendation**: Complete implementation or remove placeholder

#### qa\codebase_audit_engine.py:42

- **Category**: fake_code
- **Description**: FIXME marker: - Fake code detection (TODO, FIXME, pass-only functions)
- **Recommendation**: Complete implementation or remove placeholder

#### qa\codebase_audit_engine.py:56

- **Category**: fake_code
- **Description**: TODO marker: (r'\bTODO\b', "TODO marker"),
- **Recommendation**: Complete implementation or remove placeholder

#### qa\codebase_audit_engine.py:57

- **Category**: fake_code
- **Description**: FIXME marker: (r'\bFIXME\b', "FIXME marker"),
- **Recommendation**: Complete implementation or remove placeholder

#### qa\codebase_audit_engine.py:58

- **Category**: fake_code
- **Description**: XXX marker: (r'\bXXX\b', "XXX marker"),
- **Recommendation**: Complete implementation or remove placeholder

#### qa\codebase_audit_engine.py:59

- **Category**: fake_code
- **Description**: HACK marker: (r'\bHACK\b', "HACK marker"),
- **Recommendation**: Complete implementation or remove placeholder

#### qa\codebase_audit_engine.py:61

- **Category**: fake_code
- **Description**: Not implemented: (r'raise NotImplementedError', "Not implemented"),
- **Recommendation**: Complete implementation or remove placeholder

#### qa\release_orchestrator.py:118

- **Category**: fake_code
- **Description**: TODO marker: (r'#\s*TODO', 'TODO comment'),
- **Recommendation**: Complete implementation or remove placeholder

#### qa\release_orchestrator.py:119

- **Category**: fake_code
- **Description**: TODO marker: (r'//\s*TODO', 'TODO comment'),
- **Recommendation**: Complete implementation or remove placeholder

#### qa\release_orchestrator.py:120

- **Category**: fake_code
- **Description**: FIXME marker: (r'#\s*FIXME', 'FIXME comment'),
- **Recommendation**: Complete implementation or remove placeholder

#### qa\release_orchestrator.py:121

- **Category**: fake_code
- **Description**: FIXME marker: (r'//\s*FIXME', 'FIXME comment'),
- **Recommendation**: Complete implementation or remove placeholder

#### qa\release_orchestrator.py:625

- **Category**: fake_code
- **Description**: TODO marker: description="No TODO/FIXME in production code",
- **Recommendation**: Complete implementation or remove placeholder

#### qa\release_orchestrator.py:625

- **Category**: fake_code
- **Description**: FIXME marker: description="No TODO/FIXME in production code",
- **Recommendation**: Complete implementation or remove placeholder

#### social\x_bot_interface.py:85

- **Category**: fake_code
- **Description**: HACK marker: if any(token in text for token in ["exploit", "hack", "rug", "down", "stuck"]):
- **Recommendation**: Complete implementation or remove placeholder

#### streams\base_stream.py:235

- **Category**: fake_code
- **Description**: Not implemented: raise NotImplementedError
- **Recommendation**: Complete implementation or remove placeholder

#### streams\base_stream.py:559

- **Category**: fake_code
- **Description**: Not implemented: raise NotImplementedError
- **Recommendation**: Complete implementation or remove placeholder

#### streams\base_stream.py:569

- **Category**: fake_code
- **Description**: Not implemented: raise NotImplementedError
- **Recommendation**: Complete implementation or remove placeholder

#### streams\base_stream.py:582

- **Category**: fake_code
- **Description**: Not implemented: raise NotImplementedError
- **Recommendation**: Complete implementation or remove placeholder

#### streams\base_stream.py:598

- **Category**: fake_code
- **Description**: Not implemented: raise NotImplementedError
- **Recommendation**: Complete implementation or remove placeholder

#### streams\news_stream.py:191

- **Category**: fake_code
- **Description**: HACK marker: 'hack', 'scam', 'fraud', 'loss', 'decline', 'plunge',
- **Recommendation**: Complete implementation or remove placeholder

#### swarm\collaborative_swarm_guardrails.py:173

- **Category**: fake_code
- **Description**: TODO marker: if "TODO" in code or "FIXME" in code:
- **Recommendation**: Complete implementation or remove placeholder

#### swarm\collaborative_swarm_guardrails.py:173

- **Category**: fake_code
- **Description**: FIXME marker: if "TODO" in code or "FIXME" in code:
- **Recommendation**: Complete implementation or remove placeholder

#### swarm\collaborative_swarm_guardrails.py:174

- **Category**: fake_code
- **Description**: TODO marker: issues.append("Contains TODO/FIXME markers")
- **Recommendation**: Complete implementation or remove placeholder

#### swarm\collaborative_swarm_guardrails.py:174

- **Category**: fake_code
- **Description**: FIXME marker: issues.append("Contains TODO/FIXME markers")
- **Recommendation**: Complete implementation or remove placeholder

#### swarm\design_linter.py:50

- **Category**: fake_code
- **Description**: Empty function: _register_default_rules
- **Recommendation**: Implement function or document why it's empty

### LOW Severity

#### autonomous_soak_test.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### merid_app.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### run_tests.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### startup.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### startup_minimal.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### agents\base_agent.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### agents\meta_agent.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### agents\strategy_agent.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### agents\polymarket\graphql_scanner.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### backtesting\replay.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### core\cache.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### core\env.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### core\orchestrator.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### core\state.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### core\validation\engine.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### core\validation\onchain.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### core\validation\polymarket.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### db\neo4j.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\clobber.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\compiler_version.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\find_depot_tools.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\gn_helpers.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\gn_run_malioc.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\vs_toolchain.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\android\gyp\create_flutter_jar.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\android\gyp\jar.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\android\gyp\javac.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\android\gyp\util\build_utils.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\android\gyp\util\md5_check.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\config\linux\pkg-config.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\config\mac\mac_app.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\config\mac\package_framework.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\linux\install-chromeos-fonts.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\linux\rewrite_dirs.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\linux\sysroot_scripts\install-sysroot.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\mac\change_mach_o_flags.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\mac\darwin_sdk.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\mac\tweak_info_plist.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\toolchain\clang_static_analyzer_wrapper.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\toolchain\wrapper_utils.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\toolchain\darwin\swiftc.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\toolchain\win\setup_toolchain.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\build\toolchain\win\tool_wrapper.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\build\copy_info_plist.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\build\generate_coverage.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\build\git_revision.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\build\zip.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\build\dart\internal\gen_executable_call.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\build\dart\tools\dart_pkg.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\build\secondary\third_party\protobuf\protoc_wrapper.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\ci\scan_deps.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\impeller\tools\malioc_cores.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\impeller\tools\malioc_diff.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\impeller\tools\metal_library.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\impeller\tools\xxd.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\shell\platform\fuchsia\flutter\build\asset_package.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\shell\platform\fuchsia\flutter\build\gen_debug_wrapper_main.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\sky\tools\create_embedder_framework.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\sky\tools\create_ios_framework.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\sky\tools\create_macos_binary.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\sky\tools\create_macos_framework.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\sky\tools\create_macos_gen_snapshots.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\sky\tools\create_xcframework.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\sky\tools\sky_utils.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\testing\android_systrace_test.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\testing\run_tests.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\testing\xvfb.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\testing\android\native_activity\native_activity_apk.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\testing\benchmark\displaylist_benchmark_parser.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\testing\fuchsia\run_tests.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\testing\fuchsia\run_tests_test.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\testing\rules\run_gradle.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\android_illegal_imports.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\dia_dll.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\download_fuchsia_sdk.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\gen_android_buildconfig.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\gen_docs.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\gen_test_font.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\gn_test.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\pub_get_offline.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\androidx\generate_pom_file.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\font_subset\test.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\fuchsia\build_fuchsia_artifacts.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\fuchsia\copy_debug_symbols.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\fuchsia\make_build_info.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\fuchsia\merge_and_upload_debug_symbols.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\fuchsia\parse_manifest.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\fuchsia\upload_to_symbol_server.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\fuchsia\with_envs.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\fuchsia\dart\gen_dart_package_config.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\fuchsia\dart\verify_sources.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\fuchsia\dart\kernel\convert_manifest_to_json.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\githooks\setup.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\javadoc\gen_javadoc.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\flutter\tools\luci\build.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### flutter\engine\src\tools\dart\create_updated_flutter_deps.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### hardening\chaos.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### hardening\watchdog.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### interfaces\automation.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

#### lib\agents\rag_agent.py:1

- **Category**: documentation
- **Description**: Missing module docstring
- **Recommendation**: Add module-level docstring

