"""
src/workers/worker_pool.py
===========================
Worker Pool Coordinator.

Integrates QueueManager, WorkerManager, TaskDispatcher, heartbeats, progress,
and resource metrics into a unified, clean execution engine.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional
from .queue_manager import QueueManager
from .worker_manager import WorkerManager
from .task_dispatcher import TaskDispatcher
from .heartbeat import HeartbeatSystem
from .worker_metrics import WorkerMetrics
from .progress_tracker import ProgressTracker
from .resource_monitor import ResourceMonitor
from .graceful_shutdown import ShutdownHandler

logger = logging.getLogger(__name__)


class WorkerPool:
    """
    Primary coordinator for asynchronous worker tasks.
    """

    def __init__(
        self,
        process_callback: Callable[[Dict[str, Any]], asyncio.Future[Dict[str, Any]]],
        worker_count: Optional[int] = None,
        state_file: Optional[str] = None,
        metrics_file: Optional[str] = None,
    ) -> None:
        self.queue_mgr = QueueManager(state_file)
        self.heartbeat_sys = HeartbeatSystem(stall_timeout=10.0)
        self.metrics = WorkerMetrics(metrics_file)
        self.progress = ProgressTracker()
        self.resource_mon = ResourceMonitor()
        self.dispatcher = TaskDispatcher(self.queue_mgr)
        
        self.manager = WorkerManager(
            queue_mgr=self.queue_mgr,
            heartbeat_sys=self.heartbeat_sys,
            metrics=self.metrics,
            process_callback=process_callback,
            worker_count=worker_count
        )
        
        self.shutdown_handler = ShutdownHandler()
        self._progress_task: Optional[asyncio.Task] = None
        self._resource_task: Optional[asyncio.Task] = None
        self._stopped = False
        
        # Register shutdown cleanups
        self.shutdown_handler.register_cleanup(self.shutdown)
        self.shutdown_handler.register_signals()

    async def start(self) -> None:
        """Start all worker loops, monitors, and checkers."""
        self._stopped = False
        
        # Load any previous serialized state if exists
        await self.queue_mgr.load_state()

        # Start workers
        self.manager.start_workers()
        
        # Start background trackers
        self._progress_task = asyncio.create_task(self._progress_loop())
        self._resource_task = asyncio.create_task(self._resource_loop())
        
        logger.info("[WorkerPool] Pipeline started.")

    async def shutdown(self) -> None:
        """Shutdown all loops, monitors, and save state."""
        if self._stopped:
            return
        self._stopped = True

        logger.warning("[WorkerPool] Shutting down pool coordinator...")

        # Cancel monitors
        if self._progress_task:
            self._progress_task.cancel()
        if self._resource_task:
            self._resource_task.cancel()

        # Stop workers
        await self.manager.stop_workers()

        # Save queue states
        await self.queue_mgr.save_state()
        
        logger.info("[WorkerPool] Coordinator shutdown complete.")

    async def join(self) -> None:
        """
        Block execution until all queued tasks are fully processed.
        """
        logger.info("[WorkerPool] Waiting for all tasks to complete...")
        # PriorityQueue join blocks until qsize == 0 and all items acknowledged via task_done
        # We poll queue status while verifying all running tasks are empty
        while True:
            q_size = self.queue_mgr.queue_size
            running = len(self.queue_mgr.running_tasks)
            pending = len(self.queue_mgr.pending_tasks)
            
            if q_size == 0 and running == 0 and pending == 0:
                break
                
            await asyncio.sleep(0.5)

        logger.info("[WorkerPool] All tasks finished. Commencing cleanup...")
        await self.shutdown()
        # Clean state file upon successful completion
        self.queue_mgr.clear_state_file()

    async def _progress_loop(self) -> None:
        """Periodically refresh speed progress json updates."""
        try:
            while not self._stopped:
                await asyncio.sleep(2.0)
                
                total = self.queue_mgr.total_tasks_count
                completed = len(self.queue_mgr.completed_tasks)
                failed = len(self.queue_mgr.failed_tasks)
                running = len(self.queue_mgr.running_tasks)
                q_size = self.queue_mgr.queue_size

                if total > 0:
                    report = self.progress.update_progress(
                        total_tasks=total,
                        completed_tasks=completed,
                        failed_tasks=failed,
                        running_tasks=running,
                        queue_size=q_size
                    )
                    logger.info(
                        f"[Progress] {report['progress']['percentage_completed']}% | "
                        f"Rate: {report['speed']['tasks_per_second']} t/s | "
                        f"ETC: {report['speed']['estimated_remaining_hms']}"
                    )
        except asyncio.CancelledError:
            pass

    async def _resource_loop(self) -> None:
        """Periodically check hardware pressures."""
        try:
            while not self._stopped:
                await asyncio.sleep(5.0)
                self.resource_mon.check_thresholds()
        except asyncio.CancelledError:
            pass
