"""
src/workers/worker_manager.py
==============================
Worker Lifecycle Manager.

Manages creation, execution, graceful termination, and recovery of active
worker processes, monitoring heartbeats to restart stalled loops.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional
from .worker import Worker
from .queue_manager import QueueManager
from .heartbeat import HeartbeatSystem
from .worker_metrics import WorkerMetrics
from ..config.ai_config import ai_config

logger = logging.getLogger(__name__)


class WorkerManager:
    """
    Creates and monitors workers.
    """

    def __init__(
        self,
        queue_mgr: QueueManager,
        heartbeat_sys: HeartbeatSystem,
        metrics: WorkerMetrics,
        process_callback: Callable[[Dict[str, Any]], asyncio.Future[Dict[str, Any]]],
        worker_count: Optional[int] = None,
    ) -> None:
        self.queue_mgr = queue_mgr
        self.heartbeat_sys = heartbeat_sys
        self.metrics = metrics
        self.process_callback = process_callback
        self.worker_count = worker_count or ai_config.worker_count
        
        self.workers: Dict[str, Worker] = {}
        self._monitor_task: Optional[asyncio.Task] = None
        self._stopped = False

    def start_workers(self) -> None:
        """Spawn and start worker processes."""
        self._stopped = False
        for i in range(self.worker_count):
            worker_id = f"W-{i:02d}"
            self._spawn_worker(worker_id)
        
        # Start background health checker
        self._monitor_task = asyncio.create_task(self._worker_health_monitor())
        logger.info(f"[WorkerManager] Spawned and started {self.worker_count} workers.")

    def _spawn_worker(self, worker_id: str) -> None:
        """Create and register a single worker."""
        worker = Worker(
            worker_id=worker_id,
            queue_mgr=self.queue_mgr,
            heartbeat_sys=self.heartbeat_sys,
            metrics=self.metrics,
            process_callback=self.process_callback,
        )
        self.workers[worker_id] = worker
        worker.start()

    async def restart_worker(self, worker_id: str) -> None:
        """Gracefully terminate a worker and spawn a fresh replacement."""
        logger.warning(f"[WorkerManager] Restarting worker '{worker_id}'...")
        worker = self.workers.get(worker_id)
        if worker:
            await worker.stop()
            self.workers.pop(worker_id, None)

        await self.metrics.record_worker_restart()
        # Spawn replacement
        self._spawn_worker(worker_id)
        logger.info(f"[WorkerManager] Worker '{worker_id}' has been successfully restarted.")

    async def stop_workers(self) -> None:
        """Shutdown all worker processes gracefully."""
        self._stopped = True
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        logger.info(f"[WorkerManager] Stopping {len(self.workers)} workers...")
        stop_tasks = [worker.stop() for worker in self.workers.values()]
        await asyncio.gather(*stop_tasks)
        self.workers.clear()
        logger.info("[WorkerManager] All workers stopped.")

    async def _worker_health_monitor(self) -> None:
        """Periodic loop checking heartbeats and updating utility metrics."""
        try:
            while not self._stopped:
                await asyncio.sleep(ai_config.heartbeat_interval)
                
                # Check utilization metrics
                total = len(self.workers)
                busy = sum(1 for w in self.workers.values() if w.status == "busy")
                q_size = self.queue_mgr.queue_size
                await self.metrics.update_utilization(busy_workers=busy, total_workers=total, current_queue=q_size)

                # Scan heartbeats for stalled workers
                stalled = self.heartbeat_sys.check_stalled_workers()
                for worker_id in stalled:
                    logger.error(f"[WorkerManager] Stalled worker detected: '{worker_id}'. Triggering recovery...")
                    # Recover worker asynchronously
                    asyncio.create_task(self.restart_worker(worker_id))

        except asyncio.CancelledError:
            pass

    def scale_workers(self, new_count: int) -> None:
        """
        Dynamically adjust worker count at runtime.
        """
        if new_count <= 0:
            logger.error("[WorkerManager] Scale target must be greater than 0.")
            return

        current_count = len(self.workers)
        if new_count == current_count:
            return

        logger.info(f"[WorkerManager] Scaling workers: {current_count} -> {new_count}")

        if new_count > current_count:
            # Scale up: spawn extra workers
            for i in range(current_count, new_count):
                worker_id = f"W-{i:02d}"
                self._spawn_worker(worker_id)
        else:
            # Scale down: stop and remove excess workers
            for i in range(new_count, current_count):
                worker_id = f"W-{i:02d}"
                worker = self.workers.pop(worker_id, None)
                if worker:
                    # Run shutdown task in background
                    asyncio.create_task(worker.stop())

        self.worker_count = new_count
        logger.info(f"[WorkerManager] Worker pool scaled. Active count: {len(self.workers)}")
