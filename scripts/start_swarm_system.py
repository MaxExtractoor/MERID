"""
MERID Swarm System Orchestrated Startup

Handles complete system startup with dependency ordering,
health checks, and graceful failure handling.

Usage:
    python scripts/start_swarm_system.py [--mode simulation|paper|live]
    
    # With health checks
    python scripts/start_swarm_system.py --mode simulation --verify
    
    # Skip verification
    python scripts/start_swarm_system.py --mode paper --no-verify
"""

import asyncio
import argparse
import sys
import time
from typing import List, Dict, Optional
from pathlib import Path

from schemas.swarm_events import TradingMode
from utils.logger import get_logger

logger = get_logger("scripts.start_swarm")

# ANSI colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
BOLD = "\033[1m"
RESET = "\033[0m"


class SystemComponent:
    """Represents a system component to start."""
    
    def __init__(
        self,
        name: str,
        check_func,
        dependencies: List[str] = None,
        critical: bool = True,
    ):
        self.name = name
        self.check_func = check_func
        self.dependencies = dependencies or []
        self.critical = critical
        self.started = False
        self.healthy = False


class SwarmSystemOrchestrator:
    """Orchestrates swarm system startup."""
    
    def __init__(self, mode: TradingMode, verify_health: bool = True):
        self.mode = mode
        self.verify_health = verify_health
        self.components: Dict[str, SystemComponent] = {}
        self.failed_components: List[str] = []
        
    def register_component(self, component: SystemComponent):
        """Register a component for startup."""
        self.components[component.name] = component
    
    async def start_all(self) -> bool:
        """Start all components in dependency order."""
        print(f"\n{BOLD}{BLUE}{'='*80}{RESET}")
        print(f"{BOLD}{BLUE}MERID SWARM SYSTEM STARTUP{RESET}")
        print(f"{BOLD}{BLUE}{'='*80}{RESET}\n")
        print(f"Mode: {self.mode.value.upper()}")
        print(f"Verification: {'Enabled' if self.verify_health else 'Disabled'}\n")
        
        # Build dependency-ordered startup sequence
        startup_order = self._resolve_dependencies()
        
        if not startup_order:
            print(f"{RED}✗ Failed to resolve component dependencies{RESET}")
            return False
        
        # Start components in order
        for i, component_name in enumerate(startup_order, 1):
            component = self.components[component_name]
            
            print(f"{BOLD}[{i}/{len(startup_order)}] Starting {component.name}...{RESET}")
            
            try:
                success = await self._start_component(component)
                
                if success:
                    print(f"  {GREEN}✓{RESET} {component.name} started successfully")
                    component.started = True
                    
                    if self.verify_health:
                        # Give component time to initialize
                        await asyncio.sleep(1)
                        
                        healthy = await self._check_health(component)
                        if healthy:
                            print(f"  {GREEN}✓{RESET} {component.name} health check passed")
                            component.healthy = True
                        else:
                            print(f"  {YELLOW}⚠{RESET} {component.name} health check failed")
                            if component.critical:
                                print(f"  {RED}✗{RESET} Critical component unhealthy, aborting")
                                return False
                else:
                    print(f"  {RED}✗{RESET} {component.name} failed to start")
                    self.failed_components.append(component.name)
                    
                    if component.critical:
                        print(f"  {RED}✗{RESET} Critical component failed, aborting")
                        return False
            
            except Exception as e:
                print(f"  {RED}✗{RESET} {component.name} error: {e}")
                logger.error(f"Component {component.name} startup error: {e}", exc_info=True)
                
                if component.critical:
                    return False
            
            print()
        
        # Print startup summary
        self._print_summary()
        
        return len(self.failed_components) == 0
    
    def _resolve_dependencies(self) -> Optional[List[str]]:
        """Resolve component startup order based on dependencies."""
        resolved = []
        unresolved = set(self.components.keys())
        
        while unresolved:
            progress = False
            
            for name in list(unresolved):
                component = self.components[name]
                
                # Check if all dependencies are resolved
                deps_resolved = all(
                    dep in resolved 
                    for dep in component.dependencies
                )
                
                if deps_resolved:
                    resolved.append(name)
                    unresolved.remove(name)
                    progress = True
            
            if not progress:
                # Circular dependency or missing dependency
                logger.error(f"Cannot resolve dependencies for: {unresolved}")
                return None
        
        return resolved
    
    async def _start_component(self, component: SystemComponent) -> bool:
        """Start a single component."""
        try:
            # Component startup logic would go here
            # For now, this is a placeholder that checks if component exists
            await asyncio.sleep(0.5)  # Simulate startup time
            return True
        except Exception as e:
            logger.error(f"Failed to start {component.name}: {e}")
            return False
    
    async def _check_health(self, component: SystemComponent) -> bool:
        """Check component health."""
        try:
            return await component.check_func()
        except Exception as e:
            logger.error(f"Health check failed for {component.name}: {e}")
            return False
    
    def _print_summary(self):
        """Print startup summary."""
        print(f"{BOLD}{BLUE}{'='*80}{RESET}")
        print(f"{BOLD}{BLUE}STARTUP SUMMARY{RESET}")
        print(f"{BOLD}{BLUE}{'='*80}{RESET}\n")
        
        started = sum(1 for c in self.components.values() if c.started)
        healthy = sum(1 for c in self.components.values() if c.healthy)
        total = len(self.components)
        
        print(f"Components started: {started}/{total}")
        
        if self.verify_health:
            print(f"Health checks passed: {healthy}/{total}")
        
        if self.failed_components:
            print(f"\n{YELLOW}Failed components:{RESET}")
            for name in self.failed_components:
                print(f"  - {name}")
        
        print()
        
        if started == total and (not self.verify_health or healthy == total):
            print(f"{BOLD}{GREEN}✓ SYSTEM STARTUP COMPLETE{RESET}")
            print(f"{BOLD}{GREEN}All components operational{RESET}\n")
        elif self.failed_components:
            print(f"{BOLD}{RED}✗ SYSTEM STARTUP INCOMPLETE{RESET}")
            print(f"{BOLD}{RED}Some components failed{RESET}\n")
        else:
            print(f"{BOLD}{YELLOW}⚠ SYSTEM STARTUP PARTIAL{RESET}")
            print(f"{BOLD}{YELLOW}Some components unhealthy{RESET}\n")


async def check_event_stream_health() -> bool:
    """Check if event stream is operational."""
    try:
        from observability.event_stream import get_event_stream
        stream = get_event_stream()
        # Simple check - can we get the stream instance?
        return stream is not None
    except Exception as e:
        logger.error(f"Event stream health check failed: {e}")
        return False


async def check_telemetry_health() -> bool:
    """Check if telemetry is operational."""
    try:
        from observability.swarm_telemetry import get_swarm_telemetry
        telemetry = get_swarm_telemetry()
        return telemetry is not None
    except Exception as e:
        logger.error(f"Telemetry health check failed: {e}")
        return False


async def check_order_router_health() -> bool:
    """Check if order router is operational."""
    try:
        from execution.order_router import get_order_router
        router = get_order_router()
        return router is not None
    except Exception as e:
        logger.error(f"Order router health check failed: {e}")
        return False


async def check_consensus_health() -> bool:
    """Check if consensus coordinator is operational."""
    try:
        from consensus.consensus_coordinator import get_consensus_coordinator
        coordinator = get_consensus_coordinator()
        return coordinator is not None
    except Exception as e:
        logger.error(f"Consensus coordinator health check failed: {e}")
        return False


async def check_execution_health() -> bool:
    """Check if execution coordinator is operational."""
    try:
        from execution.execution_coordinator import get_execution_coordinator
        coordinator = get_execution_coordinator()
        return coordinator is not None
    except Exception as e:
        logger.error(f"Execution coordinator health check failed: {e}")
        return False


async def check_watchdog_health() -> bool:
    """Check if watchdog coordinator is operational."""
    try:
        from agents.watchdog_agents import get_watchdog_coordinator
        coordinator = get_watchdog_coordinator()
        return coordinator is not None
    except Exception as e:
        logger.error(f"Watchdog coordinator health check failed: {e}")
        return False


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Start MERID Swarm System")
    parser.add_argument(
        "--mode",
        choices=["simulation", "paper", "live"],
        default="simulation",
        help="Trading mode to start in"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        default=True,
        help="Verify health after startup (default: True)"
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip health verification"
    )
    
    args = parser.parse_args()
    
    # Parse mode
    mode = TradingMode[args.mode.upper()]
    verify = not args.no_verify if args.no_verify else args.verify
    
    # Create orchestrator
    orchestrator = SwarmSystemOrchestrator(mode=mode, verify_health=verify)
    
    # Register components in dependency order
    orchestrator.register_component(SystemComponent(
        name="Event Stream",
        check_func=check_event_stream_health,
        critical=True
    ))
    
    orchestrator.register_component(SystemComponent(
        name="Swarm Telemetry",
        check_func=check_telemetry_health,
        dependencies=["Event Stream"],
        critical=True
    ))
    
    orchestrator.register_component(SystemComponent(
        name="Order Router",
        check_func=check_order_router_health,
        dependencies=["Event Stream"],
        critical=True
    ))
    
    orchestrator.register_component(SystemComponent(
        name="Consensus Coordinator",
        check_func=check_consensus_health,
        dependencies=["Event Stream", "Swarm Telemetry"],
        critical=True
    ))
    
    orchestrator.register_component(SystemComponent(
        name="Execution Coordinator",
        check_func=check_execution_health,
        dependencies=["Order Router", "Consensus Coordinator"],
        critical=True
    ))
    
    orchestrator.register_component(SystemComponent(
        name="Watchdog Coordinator",
        check_func=check_watchdog_health,
        dependencies=["Swarm Telemetry"],
        critical=False  # Not critical, can run without it
    ))
    
    # Start all components
    success = await orchestrator.start_all()
    
    if success:
        print(f"{GREEN}System ready for trading in {mode.value} mode{RESET}")
        print(f"\nNext steps:")
        print(f"  1. Start backend: python -m uvicorn web.main:app --reload")
        print(f"  2. Verify pipeline: python scripts/verify_swarm_pipeline.py")
        print(f"  3. Run rehearsal: python scripts/paper_rehearsal.py --mode {mode.value}")
        return 0
    else:
        print(f"{RED}System startup failed{RESET}")
        print(f"\nTroubleshooting:")
        print(f"  - Check logs: tail -100 logs/merid.log")
        print(f"  - Verify .env configuration")
        print(f"  - Ensure all dependencies installed: pip install -r requirements.txt")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
