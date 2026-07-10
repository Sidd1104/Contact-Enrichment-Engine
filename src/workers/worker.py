"""
src/workers/worker.py
======================
Async Worker Loop.

Implements the async task processing loop. Fetches tasks, manages heartbeats,
and handles errors and retries.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Callable, Dict, Optional
from .task import Task
from .queue_manager import QueueManager
from .heartbeat import HeartbeatMessage, HeartbeatSystem
from .worker_metrics import WorkerMetrics
from ..config.ai_config import ai_config

logger = logging.getLogger(__name__)


class Worker:
    """
    Asynchronous worker processing queue tasks.
    """

    def __init__(
        self,
        worker_id: str,
        queue_mgr: QueueManager,
        heartbeat_sys: HeartbeatSystem,
        metrics: WorkerMetrics,
        process_callback: Callable[[Dict[str, Any]], asyncio.Future[Dict[str, Any]]],
    ) -> None:
        self.worker_id = worker_id
        self.queue_mgr = queue_mgr
        self.heartbeat_sys = heartbeat_sys
        self.metrics = metrics
        self.process_callback = process_callback
        
        self.status = "idle"
        self.current_task: Optional[Task] = None
        self.start_time = time.time()
        self.last_activity = time.time()
        self._run_task: Optional[asyncio.Task] = None
        self._hb_task: Optional[asyncio.Task] = None
        self._stopped = False

    def start(self) -> None:
        """Start the worker execution loops."""
        self._stopped = False
        self._run_task = asyncio.create_task(self._worker_loop(), name=f"worker_{self.worker_id}")
        self._hb_task = asyncio.create_task(self._heartbeat_loop(), name=f"worker_hb_{self.worker_id}")
        logger.info(f"[Worker: {self.worker_id}] Started.")

    async def stop(self) -> None:
        """Stop worker loops gracefully."""
        self._stopped = True
        self.status = "idle"
        
        # Cancel loops
        if self._run_task:
            self._run_task.cancel()
        if self._hb_task:
            self._hb_task.cancel()

        # Safely put currently processing task back in pending if needed
        if self.current_task and self.current_task.status == "running":
            logger.info(f"[Worker: {self.worker_id}] Returning active task '{self.current_task.task_id}' back to queue on stop.")
            await self.queue_mgr.fail_task(self.current_task.task_id, "Worker stopped gracefully.")

        self.heartbeat_sys.deregister_worker(self.worker_id)
        logger.info(f"[Worker: {self.worker_id}] Stopped.")

    async def _emit_heartbeat(self) -> None:
        """Broadcast status update frame."""
        import os
        import psutil
        
        # Estimate memory
        try:
            mem = psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
        except Exception:
            mem = 0.0

        hb = HeartbeatMessage(
            worker_id=self.worker_id,
            status=self.status,
            current_task_id=self.current_task.task_id if self.current_task else None,
            uptime=time.time() - self.start_time,
            last_activity=self.last_activity,
            memory_usage_mb=mem
        )
        self.heartbeat_sys.register_heartbeat(hb)

    async def _heartbeat_loop(self) -> None:
        """Periodic heartbeat broadcast loop."""
        try:
            while not self._stopped:
                await self._emit_heartbeat()
                await asyncio.sleep(ai_config.heartbeat_interval)
        except asyncio.CancelledError:
            pass

    async def _worker_loop(self) -> None:
        """Main pull-execute-complete loop."""
        try:
            while not self._stopped:
                self.status = "idle"
                self.current_task = None
                await self._emit_heartbeat()

                # 1. Fetch next task (blocks until available)
                task = await self.queue_mgr.get_next_task()
                if not task:
                    await asyncio.sleep(0.1)
                    continue

                # 2. Process task
                self.status = "busy"
                self.current_task = task
                self.last_activity = time.time()
                await self._emit_heartbeat()

                logger.info(f"[Worker: {self.worker_id}] Processing task '{task.task_id}' (NPI: {task.record_data.get('npi')})")
                task_start = time.monotonic()

                try:
                    # Invoke actual processing callback
                    updated_record = await self.process_callback(task.record_data)
                    
                    # Complete task
                    await self.queue_mgr.complete_task(task.task_id, updated_record)
                    duration = time.monotonic() - task_start
                    
                    await self.metrics.record_task_completion(
                        success=True,
                        duration=duration,
                        retries=task.retry_count
                    )
                    logger.info(f"[Worker: {self.worker_id}] Task '{task.task_id}' succeeded in {duration:.2f}s.")
                    
                except Exception as e:
                    # Task processing failed
                    duration = time.monotonic() - task_start
                    err_msg = f"{type(e).__name__}: {e}"
                    logger.error(f"[Worker: {self.worker_id}] Task '{task.task_id}' failed: {err_msg}")
                    
                    # Move to fail manager (which handles retries)
                    await self.queue_mgr.fail_task(task.task_id, err_msg)
                    
                    await self.metrics.record_task_completion(
                        success=False,
                        duration=duration,
                        retries=task.retry_count
                    )

                finally:
                    # Acknowledge queue item
                    self.queue_mgr.task_done()
                    self.last_activity = time.time()
                    self.current_task = None

        except asyncio.CancelledError:
            pass
