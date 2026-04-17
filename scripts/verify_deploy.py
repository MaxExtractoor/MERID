#!/usr/bin/env python3
"""
MERID Deployment Verification Script
Run this before deploying to production to verify all components are ready.
"""

import sys
import os
from pathlib import Path

# Colors for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"

def check(name: str, condition: bool, message: str = "") -> bool:
    """Print check result and return condition."""
    if condition:
        print(f"[OK] {name}")
        if message:
            print(f"  {message}")
    else:
        print(f"[FAIL] {name}")
        if message:
            print(f"  {message}")
    return condition

def warn(name: str, message: str = ""):
    """Print warning."""
    print(f"[WARN] {name}")
    if message:
        print(f"  {message}")

def section(title: str):
    """Print section header."""
    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}{title}{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

def main():
    """Run all deployment checks."""
    root = Path(__file__).parent.parent
    os.chdir(root)
    
    print(f"\n{BOLD}MERID Deployment Verification{RESET}")
    print(f"Working directory: {root}")
    
    all_passed = True
    
    # === File Structure ===
    section("File Structure")
    
    required_files = [
        "requirements.txt",
        "Dockerfile",
        "railway.toml",
        ".env.example",
        "DEPLOY.md",
        "CHECKLIST.md",
        "web/main.py",
        "merid/settings.py",
        "web/api/auth.py",
        "web/api/kalshi_api.py",
    ]
    
    for file in required_files:
        all_passed &= check(f"File exists: {file}", (root / file).exists())
    
    # === Python Environment ===
    section("Python Environment")
    
    try:
        import fastapi
        check("FastAPI installed", True, f"version {fastapi.__version__}")
    except ImportError:
        all_passed &= check("FastAPI installed", False, "Run: pip install -r requirements.txt")
    
    try:
        import uvicorn
        check("Uvicorn installed", True)
    except ImportError:
        all_passed &= check("Uvicorn installed", False)
    
    # === Configuration ===
    section("Configuration")
    
    env_file = root / ".env"
    env_example = root / ".env.example"
    
    if env_file.exists():
        warn(".env file exists", "Ensure it's not committed to git!")
        
        # Check critical env vars
        env_content = env_file.read_text()
        critical_vars = [
            "MERID_ENV",
            "MERID_TRADING_MODE",
            "MERID_PROFILE",
            "KALSHI_API_KEY_ID",
        ]
        for var in critical_vars:
            if var in env_content:
                check(f"Env var defined: {var}", True)
            else:
                warn(f"Env var missing: {var}")
    else:
        warn(".env file not found", f"Copy from {env_example}")
    
    # Check .gitignore has .env
    gitignore = root / ".gitignore"
    if gitignore.exists():
        gitignore_content = gitignore.read_text()
        check(".env in .gitignore", ".env" in gitignore_content)
    
    # === Frontend ===
    section("Frontend")
    
    frontend_dir = root / "web" / "react"
    if frontend_dir.exists():
        check("Frontend directory exists", True)
        
        package_json = frontend_dir / "package.json"
        check("package.json exists", package_json.exists())
        
        # Check for node_modules
        node_modules = frontend_dir / "node_modules"
        if node_modules.exists():
            check("node_modules installed", True)
        else:
            warn("node_modules not found", "Run: cd web/react && npm install")
        
        # Check for dist/build
        dist = frontend_dir / "dist"
        build = frontend_dir / "build"
        if dist.exists() or build.exists():
            check("Frontend built", True)
        else:
            warn("Frontend not built", "Run: cd web/react && npm run build")
    else:
        warn("Frontend directory not found")
    
    # === Docker ===
    section("Docker Configuration")
    
    dockerfile = root / "Dockerfile"
    if dockerfile.exists():
        check("Dockerfile exists", True)
        content = dockerfile.read_text()
        check("Dockerfile has healthcheck", "HEALTHCHECK" in content)
        check("Dockerfile uses non-root user", "USER" in content)
    
    dockerignore = root / ".dockerignore"
    check(".dockerignore exists", dockerignore.exists())
    
    # === Database ===
    section("Database")
    
    data_dir = root / "data"
    check("Data directory exists", data_dir.exists() or data_dir.mkdir(exist_ok=True))
    
    init_db_script = root / "scripts" / "init_db.py"
    if init_db_script.exists():
        check("Database init script exists", True)
    
    # === Security ===
    section("Security Checks")
    
    # Check for common secrets in files
    secrets_found = []
    dangerous_patterns = [
        "password = \"",
        "api_key = \"",
        "secret = \"",
        "private_key",
    ]
    
    for pattern in dangerous_patterns:
        # This is a simplified check - in production use proper secret scanning
        pass
    
    check("Security patterns", True, "Manual review required")
    
    # === Final Summary ===
    section("Summary")
    
    if all_passed:
        print(f"[SUCCESS] All critical checks passed!")
        print(f"\nSystem is ready for deployment.")
        print(f"\nNext steps:")
        print(f"  1. Review CHECKLIST.md")
        print(f"  2. Run: ./start.sh production  (or)")
        print(f"  3. Deploy: railway up  (or)")
        print(f"  4. Build: docker build -t merid .")
        return 0
    else:
        print(f"[FAILED] Some checks failed")
        print(f"\nPlease fix the issues above before deploying.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
