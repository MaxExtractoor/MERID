"""
MERID Multi-Service Startup Script
Starts all 4 services on their designated ports with production infrastructure.
"""
import asyncio
import argparse
import multiprocessing
import signal
import sys
import time
from typing import List

import uvicorn

from config.ports import (
    USER_UI_PORT,
    AGENT_MESH_PORT,
    OPS_ADMIN_PORT,
    TELEMETRY_PORT,
    get_binding,
)
from core.production_init import initialize_production_infrastructure, shutdown_production_infrastructure
from utils.logger import get_logger

logger = get_logger("merid.startup")

# Process tracking
_processes: List[multiprocessing.Process] = []

# Global configuration
_execution_mode = "external"  # "self_hosted" or "external"
_execution_service_url = "http://127.0.0.1:8012"


def run_user_ui():
    """Run User UI service on port 3000."""
    from web.user_app import app
    binding = get_binding("user_ui")
    logger.info(f"Starting User UI on {binding}:{USER_UI_PORT}")
    uvicorn.run(app, host=binding, port=USER_UI_PORT, log_level="info")


def run_agent_mesh():
    """Run Agent Mesh service on port 8080."""
    from web.agent_app import app
    binding = get_binding("agent_mesh")
    logger.info(f"Starting Agent Mesh on {binding}:{AGENT_MESH_PORT}")
    uvicorn.run(app, host=binding, port=AGENT_MESH_PORT, log_level="info")


def run_ops_admin():
    """Run Ops/Admin service on port 9090."""
    from web.ops_app import app
    binding = get_binding("ops_admin")
    logger.info(f"Starting Ops/Admin on {binding}:{OPS_ADMIN_PORT}")
    uvicorn.run(app, host=binding, port=OPS_ADMIN_PORT, log_level="info")


def run_telemetry():
    """Run Telemetry service on port 9091."""
    from web.metrics_app import app
    binding = get_binding("telemetry")
    logger.info(f"Starting Telemetry on {binding}:{TELEMETRY_PORT}")
    uvicorn.run(app, host=binding, port=TELEMETRY_PORT, log_level="info")


def run_execution_service():
    """Run self-hosted execution service on port 8012."""
    from execution.service import get_execution_service
    binding = "127.0.0.1"  # Local only for execution service
    port = 8012
    logger.info(f"Starting Execution Service on {binding}:{port}")
    
    service = get_execution_service()
    service.run(binding, port)


def shutdown_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info("Shutdown signal received, stopping all services...")
    
    # Stop service processes
    for process in _processes:
        if process.is_alive():
            logger.info(f"Terminating process {process.name} (PID: {process.pid})")
            process.terminate()
    
    # Wait for processes to terminate
    time.sleep(2)
    
    # Force kill if still alive
    for process in _processes:
        if process.is_alive():
            logger.warning(f"Force killing process {process.name} (PID: {process.pid})")
            process.kill()
    
    logger.info("All services stopped")
    
    # Shutdown production infrastructure
    shutdown_production_infrastructure()
    
    sys.exit(0)


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="MERID Multi-Service Startup")
    parser.add_argument("--execution-mode", choices=["external", "self_hosted"], 
                       default="external", help="Execution mode (external brokers or self-hosted)")
    parser.add_argument("--execution-service-url", default="http://127.0.0.1:8012",
                       help="URL for self-hosted execution service")
    parser.add_argument("--mode", choices=["paper", "live"], default="paper",
                       help="Trading mode")
    parser.add_argument("--symbols", help="Trading symbols (comma-separated)")
    parser.add_argument("--strategies", help="Trading strategies (comma-separated)")
    parser.add_argument("--venues", help="Trading venues (comma-separated)")
    parser.add_argument("--notional", type=float, help="Notional amount")
    parser.add_argument("--session-duration", type=int, help="Session duration in seconds")
    
    return parser.parse_args()


def main():
    """Start all MERID services."""
    args = parse_arguments()
    
    # Set global configuration
    global _execution_mode, _execution_service_url
    _execution_mode = args.execution_mode
    _execution_service_url = args.execution_service_url
    
    logger.info("=" * 80)
    logger.info("MERID Multi-Service Startup")
    logger.info("=" * 80)
    logger.info(f"Execution Mode: {_execution_mode}")
    if _execution_mode == "self_hosted":
        logger.info(f"Execution Service: {_execution_service_url}")
    logger.info("")
    
    # Initialize production infrastructure
    logger.info("Initializing production infrastructure...")
    try:
        initialize_production_infrastructure()
    except Exception as exc:
        logger.error(f"Failed to initialize production infrastructure: {exc}")
        sys.exit(1)
    
    # Start execution service if using self-hosted mode
    if _execution_mode == "self_hosted":
        logger.info("Starting self-hosted execution service...")
        try:
            process = multiprocessing.Process(target=run_execution_service, name="Execution Service")
            process.start()
            _processes.append(process)
            logger.info(f"✓ Started Execution Service (PID: {process.pid})")
            time.sleep(2)  # Give execution service time to start
        except Exception as exc:
            logger.error(f"Failed to start execution service: {exc}")
            sys.exit(1)
    
    logger.info("")
    logger.info("Starting 4 services:")
    logger.info(f"  1. User UI        - {get_binding('user_ui')}:{USER_UI_PORT}")
    logger.info(f"  2. Agent Mesh     - {get_binding('agent_mesh')}:{AGENT_MESH_PORT} (localhost only)")
    logger.info(f"  3. Ops/Admin      - {get_binding('ops_admin')}:{OPS_ADMIN_PORT} (localhost only)")
    logger.info(f"  4. Telemetry      - {get_binding('telemetry')}:{TELEMETRY_PORT} (localhost only)")
    logger.info("")
    logger.info("Press Ctrl+C to stop all services")
    logger.info("=" * 80)
    logger.info("")
    
    # Register signal handlers
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
    
    # Start each service in its own process
    services = [
        ("User UI", run_user_ui),
        ("Agent Mesh", run_agent_mesh),
        ("Ops/Admin", run_ops_admin),
        ("Telemetry", run_telemetry),
    ]
    
    for name, target in services:
        process = multiprocessing.Process(target=target, name=name)
        process.start()
        _processes.append(process)
        logger.info(f"✓ Started {name} (PID: {process.pid})")
        time.sleep(0.5)  # Stagger startup
    
    logger.info("")
    logger.info("=" * 80)
    logger.info("All services started successfully!")
    logger.info("")
    logger.info("Access points:")
    logger.info(f"  • Dashboard:      http://{get_binding('user_ui')}:{USER_UI_PORT}/dashboard")
    logger.info(f"  • Institutional:  http://{get_binding('user_ui')}:{USER_UI_PORT}/institutional")
    logger.info(f"  • Agent Mesh:     http://{get_binding('agent_mesh')}:{AGENT_MESH_PORT}/health")
    logger.info(f"  • Ops/Admin:      http://{get_binding('ops_admin')}:{OPS_ADMIN_PORT}/health")
    logger.info(f"  • Metrics:        http://{get_binding('telemetry')}:{TELEMETRY_PORT}/metrics")
    if _execution_mode == "self_hosted":
        logger.info(f"  • Execution:      {_execution_service_url}/health")
    logger.info("=" * 80)
    logger.info("")
    
    # Keep main process alive
    try:
        while True:
            # Check if any process died
            for process in _processes:
                if not process.is_alive():
                    logger.error(f"Service {process.name} died unexpectedly!")
                    shutdown_handler(None, None)
            time.sleep(5)
    except KeyboardInterrupt:
        shutdown_handler(None, None)


if __name__ == "__main__":
    # Required for Windows multiprocessing
    multiprocessing.freeze_support()
    main()
