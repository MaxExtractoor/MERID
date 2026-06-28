"""
Test suite to enforce architectural separation between 15m stack and legacy system.

This test ensures that the 15m stack has zero dependencies on:
- Legacy merid.prediction.agent_grid modules
- Legacy web.main imports
- Any other legacy dependencies that violate the separation

The 15m stack should only use:
- merid.prediction.agent_grid_15m
- web.main_15m_lean
- Other 15m-specific modules
"""

import os
import ast
import pytest
from pathlib import Path
from typing import List, Set, Tuple


class Test15mArchitecturalSeparation:
    """Enforce clean architectural separation between 15m stack and legacy system."""

    @pytest.fixture
    def repo_root(self) -> Path:
        """Get the repository root directory."""
        return Path(__file__).parent.parent

    @pytest.fixture
    def fifteen_m_modules(self) -> Set[str]:
        """Define the canonical 15m stack modules."""
        return {
            # Core 15m entry point
            "web.main_15m_lean",
            
            # 15m API modules (direct dependencies of main_15m_lean)
            "web.api.performance_api",
            "web.api.kalshi_api",
            "web.api.kalshi_agent_grid_api", 
            "web.api.kalshi_grid_api",
            "web.api.health_api",
            "web.api.loop_api",
            "web.api.spot_debug_api",
            "web.api.paper_session_api",
            "web.api.system_endpoints",
            "web.api.agents",
            
            # 15m prediction modules
            "merid.prediction.agent_grid_15m",
            "merid.prediction.kalshi_strike_selector",
            "merid.prediction.agent_grid_config",
            
            # 15m loop modules
            "merid.loop_15m",
            
            # 15m data modules
            "data.unified_spot_service",
            
            # 15m venue modules
            "merid.event_venues.kalshi.market_state",
            "merid.event_venues.kalshi.market_selector",
            "merid.event_venues.kalshi.fills_poller",
            "merid.event_venues.kalshi.ws_bridge",
        }

    @pytest.fixture
    def forbidden_imports(self) -> Set[str]:
        """Define imports that are forbidden in 15m stack."""
        return {
            # Legacy agent grid (the main violation)
            "merid.prediction.agent_grid",
            
            # Legacy main system
            "web.main",
            
            # Legacy prediction modules
            "merid.prediction.paper_session",
            "merid.prediction.debate_store",
            "merid.prediction.unified_orchestrator",
            
            # Legacy loop modules
            "merid.loop",
            "merid.loop_main",
            
            # Legacy system modules
            "core.orchestrator",
            "core.deployment_controller",
            "core.learning",
            "core.persistence",
        }

    def _get_python_files(self, directory: Path) -> List[Path]:
        """Get all Python files in a directory."""
        return list(directory.rglob("*.py"))

    def _extract_imports(self, file_path: Path) -> List[str]:
        """Extract all import statements from a Python file."""
        imports = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.append(node.module)
                        
        except (SyntaxError, UnicodeDecodeError) as e:
            pytest.fail(f"Could not parse {file_path}: {e}")
            
        return imports

    def _is_fifteen_m_file(self, file_path: Path, fifteen_m_modules: Set[str]) -> bool:
        """Check if a file belongs to the 15m stack."""
        # Convert file path to module path
        relative_path = file_path.relative_to(Path(__file__).parent.parent)
        module_parts = list(relative_path.parts[:-1])  # Remove filename
        module_parts[-1] = module_parts[-1].replace('.py', '')
        
        # Check if this file is in a 15m module
        for fifteen_m_module in fifteen_m_modules:
            fifteen_m_parts = fifteen_m_module.split('.')
            if len(module_parts) >= len(fifteen_m_parts):
                if module_parts[:len(fifteen_m_parts)] == fifteen_m_parts:
                    return True
        
        return False

    def test_no_forbidden_imports_in_15m_stack(
        self, repo_root: Path, fifteen_m_modules: Set[str], forbidden_imports: Set[str]
    ):
        """Test that 15m stack files contain no forbidden imports."""
        
        # Get all Python files in the repo
        python_files = self._get_python_files(repo_root / "web")
        python_files.extend(self._get_python_files(repo_root / "merid"))
        python_files.extend(self._get_python_files(repo_root / "data"))
        
        violations = []
        
        for file_path in python_files:
            # Skip if not a 15m file
            if not self._is_fifteen_m_file(file_path, fifteen_m_modules):
                continue
            
            # Extract imports from the file
            imports = self._extract_imports(file_path)
            
            # Check for forbidden imports
            for imp in imports:
                for forbidden in forbidden_imports:
                    if imp.startswith(forbidden):
                        violations.append({
                            'file': str(file_path),
                            'forbidden_import': forbidden,
                            'actual_import': imp,
                        })
        
        # Assert no violations
        assert not violations, (
            f"Found {len(violations)} forbidden imports in 15m stack:\n" +
            "\n".join(
                f"  {v['file']}: imported '{v['actual_import']}' "
                f"(forbidden: '{v['forbidden_import']}')"
                for v in violations
            )
        )

    def test_fifteen_m_entry_point_exists(self, repo_root: Path):
        """Test that the 15m entry point exists and is correct."""
        entry_point = repo_root / "web" / "main_15m_lean.py"
        
        assert entry_point.exists(), "15m entry point web/main_15m_lean.py does not exist"
        
        # Check that it defines a FastAPI app
        content = entry_point.read_text(encoding='utf-8')
        assert "app = FastAPI(" in content, "15m entry point does not define FastAPI app"
        assert "title=\"Kalshi 15m Lean Stack - main_15m_lean.py\"" in content, "15m entry point has incorrect title"

    def test_fifteen_modules_use_correct_imports(
        self, repo_root: Path, fifteen_m_modules: Set[str]
    ):
        """Test that 15m modules use the correct agent_grid_15m imports."""
        
        violations = []
        
        for module in fifteen_m_modules:
            if "agent_grid" in module:
                # This should be agent_grid_15m, not agent_grid
                continue
                
            # Find the corresponding file
            module_path = Path(*module.split("."))
            if module_path.name == "main_15m_lean":
                module_path = module_path.with_name("main_15m_lean.py")
            else:
                module_path = module_path.with_suffix(".py")
                
            file_path = repo_root / module_path
            
            if not file_path.exists():
                continue
                
            # Extract imports
            imports = self._extract_imports(file_path)
            
            # Check for correct agent_grid imports
            for imp in imports:
                if imp == "merid.prediction.agent_grid":
                    violations.append({
                        'file': str(file_path),
                        'wrong_import': imp,
                        'should_be': "merid.prediction.agent_grid_15m",
                    })
        
        assert not violations, (
            f"Found {len(violations)} incorrect agent_grid imports:\n" +
            "\n".join(
                f"  {v['file']}: imported '{v['wrong_import']}' "
                f"(should be '{v['should_be']}')"
                for v in violations
            )
        )

    def test_startup_script_uses_correct_entry_point(self, repo_root: Path):
        """Test that startup script uses the correct 15m entry point."""
        startup_script = repo_root / "start_15m.ps1"
        
        assert startup_script.exists(), "start_15m.ps1 does not exist"
        
        content = startup_script.read_text()
        
        # Check that it uses the correct entry point
        assert "web.main_15m_lean:app" in content, (
            "start_15m.ps1 does not use web.main_15m_lean:app"
        )
        
        # Check that it sets the correct profile
        assert "kalshi_crypto_15m_v2" in content, (
            "start_15m.ps1 does not set kalshi_crypto_15m_v2 profile"
        )

    def test_no_legacy_main_imports(self, repo_root: Path, fifteen_m_modules: Set[str]):
        """Test that no 15m files import from legacy web.main."""
        
        violations = []
        
        for module in fifteen_m_modules:
            # Find the corresponding file
            module_path = Path(*module.split("."))
            if module_path.name == "main_15m_lean":
                module_path = module_path.with_name("main_15m_lean.py")
            else:
                module_path = module_path.with_suffix(".py")
                
            file_path = repo_root / module_path
            
            if not file_path.exists():
                continue
                
            # Extract imports
            imports = self._extract_imports(file_path)
            
            # Check for legacy main imports
            for imp in imports:
                if imp.startswith("web.main") and imp != "web.main_15m_lean":
                    violations.append({
                        'file': str(file_path),
                        'legacy_import': imp,
                    })
        
        assert not violations, (
            f"Found {len(violations)} legacy main imports:\n" +
            "\n".join(
                f"  {v['file']}: imported '{v['legacy_import']}'"
                for v in violations
            )
        )
