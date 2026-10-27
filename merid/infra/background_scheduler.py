"""Background Work Scheduler — Decouples heavy tasks from main event loop.

Provides:
- ThreadPool for CPU-bound work
- Async task scheduling for I/O-bound work
- Rate limiting and single-job-at-a-time guarantees
- Metrics and health checks for background workers

Usage:
    scheduler = BackgroundScheduler(max_workers=4)
    scheduler.start()
    
    # Schedule heavy feature extraction
    scheduler.submit_cpu("feature_update", lambda: compute_features())
    
    # Schedule async consensus
    scheduler.submit_io("consensus", run_consensus_aggregator())
    
    # Check health
    status = scheduler.health_check()
"""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Any, Set
from functools import wraps

from utils.logger import get_logger

logger = get_logger("merid.infra.background_scheduler")


class JobType(Enum):
    CPU = "cpu"  # CPU-bound: run in thread pool
    IO = "io"    # I/O-bound: run as async task


@dataclass
class Job:
    """Background job definition."""
    name: str
    job_type: JobType
    func: Callable
    interval_seconds: float  # Periodic interval (0 = one-shot)
    last_run: float = field(default=0.0)
    running: bool = field(default=False)
    error_count: int = field(default=0)
    success_count: int = field(default=0)
    last_error: Optional[str] = None


@dataclass
class JobStatus:
    """Job runtime status."""
    name: str
    state: str  # "idle", "running", "error"
    last_run: Optional[float]
    next_run: Optional[float]
    error_count: int
    success_count: int
    last_error: Optional[str]


class BackgroundScheduler:
    """Schedules and manages background work.
    
    Key features:
    - Thread pool for CPU-bound work (feature extraction, arb scans)
    - Async task scheduling for I/O-bound work (consensus, API calls)
    - Rate limiting: ensures only one instance of each job runs at a time
    - Health checks: tracks job success/failure rates
    - Graceful shutdown: cancels pending tasks and waits for running ones
    """
    
    def __init__(
        self,
        max_workers: int = 4,
        thread_prefix: str = "bg-worker",
        io_concurrency: int = 10,
    ):
        self._max_workers = max_workers
        self._thread_prefix = thread_prefix
        self._io_concurrency = io_concurrency
        
        # Thread pool for CPU-bound work
        self._thread_pool: Optional[ThreadPoolExecutor] = None
        
        # IO task management
        self._io_semaphore: Optional[asyncio.Semaphore] = None
        self._io_tasks: Set[asyncio.Task] = set()
        
        # Job registry
        self._jobs: Dict[str, Job] = {}
        self._job_lock = threading.Lock()
        
        # Lifecycle
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._scheduler_task: Optional[asyncio.Task] = None
        
        # Metrics
        self._started_at: Optional[float] = None
    
    # ── Lifecycle ──────────────────────────────────────────────────────
    
    async def start(self) -> None:
        """Start the background scheduler."""
        if self._running:
            return
        
        self._thread_pool = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix=self._thread_prefix,
        )
        self._io_semaphore = asyncio.Semaphore(self._io_concurrency)
        self._shutdown_event.clear()
        self._started_at = time.time()
        self._running = True
        
        # Start periodic scheduler
        self._scheduler_task = asyncio.create_task(
            self._scheduler_loop(),
            name="background-scheduler"
        )
        
        logger.info(
            "BackgroundScheduler started (workers=%d, io_concurrency=%d)",
            self._max_workers,
            self._io_concurrency,
        )
    
    async def stop(self, timeout: float = 30.0) -> None:
        """Stop the scheduler gracefully.
        
        Args:
            timeout: Seconds to wait for running jobs to complete
        """
        if not self._running:
            return
        
        self._running = False
        self._shutdown_event.set()
        
        # Cancel scheduler loop
        if self._scheduler_task and not self._scheduler_task.done():
            self._scheduler_task.cancel()
            try:
                await asyncio.wait_for(self._scheduler_task, timeout=1.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        
        # Cancel pending IO tasks
        for task in list(self._io_tasks):
            if not task.done():
                task.cancel()
        
        if self._io_tasks:
            done, pending = await asyncio.wait(
                self._io_tasks,
                timeout=timeout,
                return_when=asyncio.ALL_COMPLETED,
            )
            for task in pending:
                task.cancel()
        
        # Shutdown thread pool
        if self._thread_pool:
            self._thread_pool.shutdown(wait=True)
        
        logger.info("BackgroundScheduler stopped")
    
    # ── Job Registration ─────────────────────────────────────────────
    
    def register_cpu_job(
        self,
        name: str,
        func: Callable[[], Any],
        interval_seconds: float = 0,
    ) -> None:
        """Register a CPU-bound periodic job.
        
        Args:
            name: Unique job identifier
            func: Callable to execute (runs in thread pool)
            interval_seconds: Run periodically (0 = manual trigger only)
        """
        with self._job_lock:
            self._jobs[name] = Job(
                name=name,
                job_type=JobType.CPU,
                func=func,
                interval_seconds=interval_seconds,
            )
        logger.debug("Registered CPU job: %s (interval=%.1fs)", name, interval_seconds)
    
    def register_io_job(
        self,
        name: str,
        coro_factory: Callable[[], asyncio.Coroutine],
        interval_seconds: float = 0,
    ) -> None:
        """Register an I/O-bound periodic job.
        
        Args:
            name: Unique job identifier
            coro_factory: Callable returning a coroutine (runs as async task)
            interval_seconds: Run periodically (0 = manual trigger only)
        """
        with self._job_lock:
            self._jobs[name] = Job(
                name=name,
                job_type=JobType.IO,
                func=coro_factory,
                interval_seconds=interval_seconds,
            )
        logger.debug("Registered IO job: %s (interval=%.1fs)", name, interval_seconds)
    
    def unregister_job(self, name: str) -> bool:
        """Unregister a job. Returns True if found and removed."""
        with self._job_lock:
            if name in self._jobs:
                del self._jobs[name]
                return True
            return False
    
    # ── Manual Triggering ────────────────────────────────────────────
    
    def submit_cpu(self, name: str, func: Optional[Callable] = None) -> bool:
        """Submit a one-off CPU job immediately.
        
        Args:
            name: Job name (for tracking; uses registered func if func=None)
            func: Optional override function
        
        Returns:
            True if submitted successfully
        """
        if not self._running or not self._thread_pool:
            return False
        
        target_func = func
        with self._job_lock:
            if name in self._jobs and func is None:
                target_func = self._jobs[name].func
        
        if target_func is None:
            logger.warning("Cannot submit CPU job %s: no function provided", name)
            return False
        
        # Submit to thread pool
        future = self._thread_pool.submit(self._run_cpu_job, name, target_func)
        future.add_done_callback(lambda f: self._on_cpu_done(name, f))
        return True
    
    async def submit_io(
        self,
        name: str,
        coro: Optional[asyncio.Coroutine] = None,
    ) -> bool:
        """Submit a one-off IO job immediately.
        
        Args:
            name: Job name (for tracking)
            coro: Coroutine to execute (if None, uses registered coro_factory)
        
        Returns:
            True if submitted successfully
        """
        if not self._running:
            return False
        
        coro_factory = None
        with self._job_lock:
            if name in self._jobs and coro is None:
                coro_factory = self._jobs[name].func
        
        if coro is None and coro_factory is None:
            logger.warning("Cannot submit IO job %s: no coroutine provided", name)
            return False
        
        target_coro = coro if coro is not None else coro_factory()
        
        # Create task with semaphore for concurrency control
        async def wrapped():
            if self._io_semaphore:
                async with self._io_semaphore:
                    return await self._run_io_job(name, target_coro)
            else:
                return await self._run_io_job(name, target_coro)
        
        task = asyncio.create_task(wrapped(), name=f"bg-io-{name}")
        self._io_tasks.add(task)
        task.add_done_callback(lambda t: self._io_tasks.discard(t))
        return True
    
    # ── Scheduling ───────────────────────────────────────────────────
    
    async def _scheduler_loop(self) -> None:
        """Main scheduler loop for periodic jobs."""
        while self._running and not self._shutdown_event.is_set():
            try:
                now = time.time()
                
                with self._job_lock:
                    jobs = list(self._jobs.values())
                
                for job in jobs:
                    if job.interval_seconds <= 0:
                        continue  # Manual trigger only
                    
                    if job.running:
                        continue  # Still running from last iteration
                    
                    if now - job.last_run >= job.interval_seconds:
                        # Time to run
                        if job.job_type == JobType.CPU:
                            self._schedule_cpu_job(job)
                        else:
                            await self._schedule_io_job(job)
                
                # Wait for next check interval
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=1.0  # Check every second
                    )
                except asyncio.TimeoutError:
                    pass  # Normal - continue loop
                    
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Scheduler loop error: %s", exc)
                await asyncio.sleep(1.0)
    
    def _schedule_cpu_job(self, job: Job) -> None:
        """Schedule a CPU job in thread pool."""
        if not self._thread_pool:
            return
        
        job.running = True
        future = self._thread_pool.submit(self._run_cpu_job, job.name, job.func)
        future.add_done_callback(lambda f: self._on_cpu_done(job.name, f))
    
    async def _schedule_io_job(self, job: Job) -> None:
        """Schedule an IO job as async task."""
        job.running = True
        
        async def wrapped():
            if self._io_semaphore:
                async with self._io_semaphore:
                    return await self._run_io_job(job.name, job.func())
            else:
                return await self._run_io_job(job.name, job.func())
        
        task = asyncio.create_task(wrapped(), name=f"bg-periodic-{job.name}")
        self._io_tasks.add(task)
        task.add_done_callback(lambda t: self._on_io_done(job.name, t))
    
    # ── Job Execution ────────────────────────────────────────────────
    
    def _run_cpu_job(self, name: str, func: Callable) -> Any:
        """Execute CPU job and track metrics."""
        start = time.time()
        try:
            result = func()
            elapsed = time.time() - start
            logger.debug("CPU job %s completed in %.3fs", name, elapsed)
            return result
        except Exception as exc:
            elapsed = time.time() - start
            logger.warning("CPU job %s failed after %.3fs: %s", name, elapsed, exc)
            raise
    
    def _on_cpu_done(self, name: str, future) -> None:
        """Handle CPU job completion."""
        with self._job_lock:
            if name not in self._jobs:
                return
            job = self._jobs[name]
            job.running = False
            job.last_run = time.time()
            
            try:
                future.result()
                job.success_count += 1
                job.last_error = None
            except Exception as exc:
                job.error_count += 1
                job.last_error = str(exc)
    
    async def _run_io_job(self, name: str, coro) -> Any:
        """Execute IO job and track metrics."""
        start = time.time()
        try:
            result = await coro
            elapsed = time.time() - start
            logger.debug("IO job %s completed in %.3fs", name, elapsed)
            return result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            elapsed = time.time() - start
            logger.warning("IO job %s failed after %.3fs: %s", name, elapsed, exc)
            raise
    
    def _on_io_done(self, name: str, task: asyncio.Task) -> None:
        """Handle IO job completion."""
        with self._job_lock:
            if name not in self._jobs:
                return
            job = self._jobs[name]
            job.running = False
            job.last_run = time.time()
            
            try:
                task.result()
                job.success_count += 1
                job.last_error = None
            except asyncio.CancelledError:
                pass  # Not counted as error
            except Exception as exc:
                job.error_count += 1
                job.last_error = str(exc)
    
    # ── Health & Metrics ──────────────────────────────────────────────
    
    def get_job_status(self, name: str) -> Optional[JobStatus]:
        """Get status of a specific job."""
        with self._job_lock:
            if name not in self._jobs:
                return None
            job = self._jobs[name]
            
            now = time.time()
            next_run = None
            if job.interval_seconds > 0 and not job.running:
                next_run = job.last_run + job.interval_seconds if job.last_run > 0 else now
            
            return JobStatus(
                name=job.name,
                state="running" if job.running else ("error" if job.last_error else "idle"),
                last_run=job.last_run if job.last_run > 0 else None,
                next_run=next_run,
                error_count=job.error_count,
                success_count=job.success_count,
                last_error=job.last_error,
            )
    
    def get_all_status(self) -> List[JobStatus]:
        """Get status of all registered jobs."""
        with self._job_lock:
            return [self.get_job_status(name) for name in self._jobs.keys()]
    
    def health_check(self) -> Dict[str, Any]:
        """Overall scheduler health."""
        uptime = time.time() - self._started_at if self._started_at else 0
        
        with self._job_lock:
            total_jobs = len(self._jobs)
            running_jobs = sum(1 for j in self._jobs.values() if j.running)
            total_errors = sum(j.error_count for j in self._jobs.values())
            total_success = sum(j.success_count for j in self._jobs.values())
        
        io_tasks_active = len([t for t in self._io_tasks if not t.done()])
        
        return {
            "healthy": self._running,
            "running": self._running,
            "uptime_seconds": round(uptime, 1),
            "jobs": {
                "total": total_jobs,
                "running": running_jobs,
            },
            "executions": {
                "success": total_success,
                "errors": total_errors,
                "success_rate": total_success / (total_success + total_errors) if (total_success + total_errors) > 0 else 1.0,
            },
            "io_tasks_active": io_tasks_active,
            "thread_pool": {
                "max_workers": self._max_workers,
            } if self._thread_pool else None,
        }


# ── Global Instance ────────────────────────────────────────────────────

_background_scheduler: Optional[BackgroundScheduler] = None
_scheduler_lock = threading.Lock()


def get_background_scheduler() -> BackgroundScheduler:
    """Get or create global BackgroundScheduler instance."""
    global _background_scheduler
    
    if _background_scheduler is not None:
        return _background_scheduler
    
    with _scheduler_lock:
        if _background_scheduler is not None:
            return _background_scheduler
        
        _background_scheduler = BackgroundScheduler()
        return _background_scheduler


def reset_background_scheduler() -> None:
    """Reset the global scheduler (for testing)."""
    global _background_scheduler
    with _scheduler_lock:
        _background_scheduler = None


# ── Convenience Decorators ─────────────────────────────────────────────

def background_cpu_job(interval_seconds: float = 0):
    """Decorator to register a function as a CPU-bound background job.
    
    Usage:
        @background_cpu_job(interval_seconds=60)
        def update_features():
            compute_expensive_features()
    """
    def decorator(func: Callable):
        scheduler = get_background_scheduler()
        scheduler.register_cpu_job(
            name=func.__name__,
            func=func,
            interval_seconds=interval_seconds,
        )
        return func
    return decorator


def background_io_job(interval_seconds: float = 0):
    """Decorator to register a coroutine as an I/O-bound background job.
    
    Usage:
        @background_io_job(interval_seconds=30)
        async def run_consensus():
            await aggregate_opinions()
    """
    def decorator(coro_func):
        scheduler = get_background_scheduler()
        
        def wrapper():
            return coro_func()
        
        scheduler.register_io_job(
            name=coro_func.__name__,
            coro_factory=wrapper,
            interval_seconds=interval_seconds,
        )
        return coro_func
    return decorator
