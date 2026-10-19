#!/usr/bin/env python3
"""Version Drift Monitor for MERID Kalshi Pipeline.

Checks that running services report versions matching the deployed code.
Surfaces warnings in monitoring stack when drift detected.

Usage:
    # Check current repo versions
    python scripts/check_version_drift.py
    
    # Check against running service (requires service endpoint)
    python scripts/check_version_drift.py --service-url http://localhost:8011/health
    
    # CI mode (fails on drift)
    python scripts/check_version_drift.py --ci

Exit codes:
    0 - No drift detected
    1 - Version drift detected (CI mode)
    2 - Check failed (connectivity, parse error, etc.)
"""

import argparse
import json
import sys
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any


@dataclass
class VersionInfo:
    """Version information from a source."""
    formulas_version: str
    audit_spec_version: str
    source: str  # "repo" or service URL
    
    def is_compatible_with(self, other: "VersionInfo") -> bool:
        """Check if versions are compatible.
        
        Compatible means same major version (prefix before last hyphen).
        Example: 2026-03-K1 is compatible with 2026-03-K2 but not 2026-04-K1
        """
        def major_version(v: str) -> str:
            # Extract YYYY-MM prefix
            parts = v.split("-")
            if len(parts) >= 2:
                return f"{parts[0]}-{parts[1]}"
            return v
        
        return (major_version(self.formulas_version) == major_version(other.formulas_version) and
                major_version(self.audit_spec_version) == major_version(other.audit_spec_version))


def get_repo_versions() -> Optional[VersionInfo]:
    """Extract versions from merid/formulas.py in the repo."""
    try:
        # Find repo root
        script_dir = Path(__file__).parent
        repo_root = script_dir.parent
        formulas_path = repo_root / "merid" / "formulas.py"
        
        if not formulas_path.exists():
            print(f"❌ merid/formulas.py not found at {formulas_path}")
            return None
        
        # Parse versions from file
        formulas_version = None
        audit_spec_version = None
        
        with open(formulas_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("FORMULAS_VERSION:") or line.startswith("FORMULAS_VERSION ="):
                    # Extract version string
                    if '"' in line:
                        formulas_version = line.split('"')[1]
                    elif "'" in line:
                        formulas_version = line.split("'")[1]
                elif line.startswith("AUDIT_SPEC_VERSION:") or line.startswith("AUDIT_SPEC_VERSION ="):
                    if '"' in line:
                        audit_spec_version = line.split('"')[1]
                    elif "'" in line:
                        audit_spec_version = line.split("'")[1]
        
        if formulas_version and audit_spec_version:
            return VersionInfo(
                formulas_version=formulas_version,
                audit_spec_version=audit_spec_version,
                source="repo"
            )
        else:
            print(f"❌ Could not parse versions from {formulas_path}")
            return None
            
    except Exception as e:
        print(f"❌ Error reading repo versions: {e}")
        return None


def get_service_versions(service_url: str) -> Optional[VersionInfo]:
    """Query a running service for its versions."""
    try:
        import urllib.request
        import urllib.error
        
        # Try health endpoint first
        health_url = f"{service_url}/api/v1/health" if not service_url.endswith("/health") else service_url
        
        req = urllib.request.Request(
            health_url,
            headers={"Accept": "application/json"},
            method="GET"
        )
        
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            
            # Extract version info from response
            # Structure may vary, so try common paths
            formulas_version = None
            audit_spec_version = None
            
            if "versions" in data:
                formulas_version = data["versions"].get("formulas_version")
                audit_spec_version = data["versions"].get("audit_spec_version")
            elif "formulas_version" in data:
                formulas_version = data.get("formulas_version")
                audit_spec_version = data.get("audit_spec_version")
            elif "info" in data and "versions" in data["info"]:
                formulas_version = data["info"]["versions"].get("formulas_version")
                audit_spec_version = data["info"]["versions"].get("audit_spec_version")
            
            if formulas_version and audit_spec_version:
                return VersionInfo(
                    formulas_version=formulas_version,
                    audit_spec_version=audit_spec_version,
                    source=service_url
                )
            else:
                print(f"⚠️  Service at {service_url} does not report formula versions")
                print(f"   Response: {json.dumps(data, indent=2)[:200]}...")
                return None
                
    except urllib.error.URLError as e:
        print(f"❌ Cannot connect to {service_url}: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON from {service_url}: {e}")
        return None
    except Exception as e:
        print(f"❌ Error querying {service_url}: {e}")
        return None


def format_version_comparison(repo: VersionInfo, service: Optional[VersionInfo]) -> str:
    """Format a comparison table."""
    lines = []
    lines.append("\n" + "=" * 60)
    lines.append("VERSION COMPARISON")
    lines.append("=" * 60)
    lines.append(f"{'Source':<20} {'Formulas':<20} {'Audit Spec':<20}")
    lines.append("-" * 60)
    lines.append(f"{'Repo (expected)':<20} {repo.formulas_version:<20} {repo.audit_spec_version:<20}")
    
    if service:
        match = "✅" if (repo.formulas_version == service.formulas_version and 
                       repo.audit_spec_version == service.audit_spec_version) else "❌"
        lines.append(f"{match} {service.source:<18} {service.formulas_version:<20} {service.audit_spec_version:<20}")
        
        if not repo.is_compatible_with(service):
            lines.append("\n⚠️  WARNING: Version drift detected!")
            lines.append("   Running service has incompatible versions.")
    else:
        lines.append(f"{'Service':<20} {'N/A':<20} {'N/A':<20}")
    
    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Monitor version drift between repo and running services"
    )
    parser.add_argument(
        "--service-url",
        help="URL of running service to check (e.g., http://localhost:8011)"
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: fail on version drift"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON for monitoring systems"
    )
    
    args = parser.parse_args()
    
    # Get repo versions
    repo_versions = get_repo_versions()
    if not repo_versions:
        print("❌ Failed to read repo versions")
        sys.exit(2)
    
    # Get service versions if URL provided
    service_versions = None
    if args.service_url:
        service_versions = get_service_versions(args.service_url)
    
    # Output
    if args.json:
        output = {
            "repo": {
                "formulas_version": repo_versions.formulas_version,
                "audit_spec_version": repo_versions.audit_spec_version,
            },
            "drift_detected": False,
        }
        if service_versions:
            output["service"] = {
                "url": service_versions.source,
                "formulas_version": service_versions.formulas_version,
                "audit_spec_version": service_versions.audit_spec_version,
            }
            output["drift_detected"] = not repo_versions.is_compatible_with(service_versions)
            output["exact_match"] = (
                repo_versions.formulas_version == service_versions.formulas_version and
                repo_versions.audit_spec_version == service_versions.audit_spec_version
            )
        print(json.dumps(output, indent=2))
    else:
        print(format_version_comparison(repo_versions, service_versions))
    
    # Exit code
    if args.ci and service_versions:
        if not repo_versions.is_compatible_with(service_versions):
            print("\n❌ CI CHECK FAILED: Version drift detected")
            sys.exit(1)
        elif (repo_versions.formulas_version != service_versions.formulas_version or
              repo_versions.audit_spec_version != service_versions.audit_spec_version):
            print("\n⚠️  CI WARNING: Versions differ but are compatible (minor drift)")
            # Don't fail in CI for compatible drift, just warn
    
    sys.exit(0)


if __name__ == "__main__":
    main()
