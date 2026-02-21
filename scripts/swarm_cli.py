#!/usr/bin/env python
"""
MERID Dev Swarm CLI

Command-line interface for managing the Dev Swarm.

Usage:
    python scripts/swarm_cli.py status
    python scripts/swarm_cli.py list-tasks
    python scripts/swarm_cli.py create-task --file task.json
    python scripts/swarm_cli.py cancel-task <task_id>
    python scripts/swarm_cli.py stats
    python scripts/swarm_cli.py compact-storage
"""

import asyncio
import sys
import json
import argparse
from pathlib import Path
from typing import Optional
import httpx
from rich.console import Console
from rich.table import Table
from rich import print as rprint

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.dev_swarm import create_merid_dev_swarm, DevTask

API_BASE = "http://localhost:8000/api/dev-swarm"
console = Console()


async def get_status():
    """Get swarm health status."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_BASE}/health", timeout=5.0)
            
            if response.status_code == 200:
                data = response.json()
                
                table = Table(title="Dev Swarm Health Status")
                table.add_column("Check", style="cyan")
                table.add_column("Status", style="green")
                
                table.add_row("API Status", data.get("status", "unknown"))
                table.add_row("Active Tasks", str(data.get("active_tasks", 0)))
                table.add_row("Agents", str(data.get("agents", 0)))
                table.add_row("Timestamp", data.get("timestamp", "N/A"))
                
                console.print(table)
                
                if data.get("checks"):
                    console.print("\n[bold]Health Checks:[/bold]")
                    for check, passed in data["checks"].items():
                        status = "✓" if passed else "✗"
                        color = "green" if passed else "red"
                        console.print(f"  [{color}]{status}[/{color}] {check}")
                
                return 0
            else:
                console.print(f"[red]Error: HTTP {response.status_code}[/red]")
                return 1
                
    except Exception as e:
        console.print(f"[red]Connection failed: {e}[/red]")
        console.print("[yellow]Is the backend running?[/yellow]")
        return 1


async def list_tasks(status_filter: Optional[str] = None, limit: int = 20):
    """List tasks."""
    try:
        params = {"limit": limit}
        if status_filter:
            params["status"] = status_filter
        
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_BASE}/tasks", params=params, timeout=10.0)
            
            if response.status_code == 200:
                data = response.json()
                tasks = data.get("tasks", [])
                
                if not tasks:
                    console.print("[yellow]No tasks found[/yellow]")
                    return 0
                
                table = Table(title=f"Dev Swarm Tasks ({data['total']} total)")
                table.add_column("ID", style="cyan", no_wrap=True)
                table.add_column("Status", style="green")
                table.add_column("Description", style="white")
                table.add_column("Files", justify="right")
                table.add_column("Cost", justify="right")
                table.add_column("Duration", justify="right")
                
                for task in tasks:
                    task_id = task["task_id"][:16] + "..."
                    status = task["status"]
                    desc = task["description"][:40] + "..." if len(task["description"]) > 40 else task["description"]
                    files = str(len(task["target_files"]))
                    cost = f"${task['cost_usd']:.2f}"
                    
                    duration = "N/A"
                    if task.get("duration_seconds"):
                        dur = task["duration_seconds"]
                        if dur < 60:
                            duration = f"{dur:.0f}s"
                        elif dur < 3600:
                            duration = f"{dur/60:.1f}m"
                        else:
                            duration = f"{dur/3600:.1f}h"
                    
                    # Color code status
                    status_colored = status
                    if status == "completed":
                        status_colored = f"[green]{status}[/green]"
                    elif status == "failed":
                        status_colored = f"[red]{status}[/red]"
                    elif status == "running":
                        status_colored = f"[blue]{status}[/blue]"
                    elif status == "timeout":
                        status_colored = f"[yellow]{status}[/yellow]"
                    
                    table.add_row(task_id, status_colored, desc, files, cost, duration)
                
                console.print(table)
                return 0
            else:
                console.print(f"[red]Error: HTTP {response.status_code}[/red]")
                return 1
                
    except Exception as e:
        console.print(f"[red]Failed to list tasks: {e}[/red]")
        return 1


async def create_task_from_file(file_path: str):
    """Create task from JSON file."""
    try:
        with open(file_path, 'r') as f:
            task_data = json.load(f)
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{API_BASE}/tasks",
                json=task_data,
                timeout=10.0
            )
            
            if response.status_code == 201:
                task = response.json()
                console.print(f"[green]✓ Task created: {task['task_id']}[/green]")
                console.print(f"  Description: {task['description']}")
                console.print(f"  Status: {task['status']}")
                return 0
            else:
                error = response.json().get("detail", "Unknown error")
                console.print(f"[red]Failed to create task: {error}[/red]")
                return 1
                
    except FileNotFoundError:
        console.print(f"[red]File not found: {file_path}[/red]")
        return 1
    except json.JSONDecodeError:
        console.print(f"[red]Invalid JSON in file: {file_path}[/red]")
        return 1
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return 1


async def cancel_task(task_id: str):
    """Cancel a running task."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.delete(f"{API_BASE}/tasks/{task_id}", timeout=5.0)
            
            if response.status_code == 200:
                console.print(f"[green]✓ Task {task_id} cancelled[/green]")
                return 0
            elif response.status_code == 404:
                console.print(f"[yellow]Task {task_id} not found or not running[/yellow]")
                return 1
            else:
                console.print(f"[red]Error: HTTP {response.status_code}[/red]")
                return 1
                
    except Exception as e:
        console.print(f"[red]Failed to cancel task: {e}[/red]")
        return 1


async def show_stats():
    """Show swarm statistics."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_BASE}/stats", timeout=5.0)
            
            if response.status_code == 200:
                stats = response.json()
                
                table = Table(title="Dev Swarm Statistics")
                table.add_column("Metric", style="cyan")
                table.add_column("Value", style="green")
                
                table.add_row("Active Tasks", str(stats["active_tasks"]))
                table.add_row("Total Tasks", str(stats["total_tasks"]))
                table.add_row("Completed", str(stats["completed"]))
                table.add_row("Failed", str(stats["failed"]))
                table.add_row("Timeout", str(stats["timeout"]))
                table.add_row("Cancelled", str(stats["cancelled"]))
                table.add_row("Success Rate", f"{stats['success_rate']*100:.1f}%")
                table.add_row("Avg Duration", f"{stats['avg_duration_seconds']:.1f}s")
                table.add_row("Daily Cost", f"${stats['daily_cost_usd']:.2f}")
                table.add_row("Budget Remaining", f"${stats['cost_budget_remaining']:.2f}")
                
                console.print(table)
                return 0
            else:
                console.print(f"[red]Error: HTTP {response.status_code}[/red]")
                return 1
                
    except Exception as e:
        console.print(f"[red]Failed to get stats: {e}[/red]")
        return 1


async def compact_storage_local():
    """Compact storage locally (requires direct access)."""
    try:
        console.print("[yellow]Loading swarm...[/yellow]")
        swarm = create_merid_dev_swarm()
        
        console.print("[yellow]Compacting storage...[/yellow]")
        success = swarm.compact_storage(keep_recent=1000)
        
        if success:
            stats = swarm.get_storage_stats()
            console.print(f"[green]✓ Storage compacted[/green]")
            console.print(f"  Kept: 1000 most recent tasks")
            if stats.get("tasks_file_size_bytes"):
                size_mb = stats["tasks_file_size_bytes"] / 1024 / 1024
                console.print(f"  Storage size: {size_mb:.2f} MB")
            return 0
        else:
            console.print("[red]Compaction failed (see logs)[/red]")
            return 1
            
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return 1


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="MERID Dev Swarm CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Status command
    subparsers.add_parser("status", help="Get swarm health status")
    
    # List tasks command
    list_parser = subparsers.add_parser("list-tasks", help="List tasks")
    list_parser.add_argument("--status", help="Filter by status")
    list_parser.add_argument("--limit", type=int, default=20, help="Max tasks to show")
    
    # Create task command
    create_parser = subparsers.add_parser("create-task", help="Create a new task")
    create_parser.add_argument("--file", required=True, help="JSON file with task definition")
    
    # Cancel task command
    cancel_parser = subparsers.add_parser("cancel-task", help="Cancel a running task")
    cancel_parser.add_argument("task_id", help="Task ID to cancel")
    
    # Stats command
    subparsers.add_parser("stats", help="Show swarm statistics")
    
    # Compact storage command
    subparsers.add_parser("compact-storage", help="Compact task storage")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Execute command
    if args.command == "status":
        return asyncio.run(get_status())
    elif args.command == "list-tasks":
        return asyncio.run(list_tasks(args.status, args.limit))
    elif args.command == "create-task":
        return asyncio.run(create_task_from_file(args.file))
    elif args.command == "cancel-task":
        return asyncio.run(cancel_task(args.task_id))
    elif args.command == "stats":
        return asyncio.run(show_stats())
    elif args.command == "compact-storage":
        return asyncio.run(compact_storage_local())
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
