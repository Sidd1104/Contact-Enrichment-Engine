"""
src/workers/queue_manager.py
=============================
Asynchronous Priority Queue Manager.

Maintains pending queues, tracks active tasks, handles retries, and
serializes state on graceful shutdown for recovery.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from .task import Task
from ..config.ai_config import ai_config

logger = logging.getLogger(__name__)


class QueueManager:
    """
    Manages task states and asynchronous execution buffers.
    """

    def __init__(self, state_file: Optional[str] = None) -> None:
        self.state_file = Path(state_file or ai_config.queue_state_file)
        self.max_size = ai_config.max_queue_size
        
        # Priority Queue holds tuples: (-priority, task_id)
        # Higher priority value -> negative value is lower -> popped first
        self._queue: asyncio.PriorityQueue[Tuple[int, str]] = asyncio.PriorityQueue(self.max_size)
        
        # In-memory dictionaries mapping task_id -> Task
        self.pending_tasks: Dict[str, Task] = {}
        self.running_tasks: Dict[str, Task] = {}
        self.completed_tasks: Dict[str, Task] = {}
        self.failed_tasks: Dict[str, Task] = {}
        self._lock = asyncio.Lock()

    async def add_task(self, task: Task) -> bool:
        """
        Add a task to the queue and update status maps.
        """
        async with self._lock:
            if task.task_id in self.pending_tasks or task.task_id in self.running_tasks:
                return False
            
            task.status = "pending"
            self.pending_tasks[task.task_id] = task
            
            # Priority Queue holds (-priority, task_id)
            await self._queue.put((-task.priority, task.task_id))
            logger.debug(f"[QueueManager] Added task '{task.task_id}' (priority={task.priority})")
            return True

    async def get_next_task(self) -> Optional[Task]:
        """
        Pull the next highest-priority task from the queue.
        Blocks if queue is empty.
        """
        # Pull from priority queue
        _, task_id = await self._queue.get()
        
        async with self._lock:
            task = self.pending_tasks.pop(task_id, None)
            if task:
                task.mark_started()
                self.running_tasks[task_id] = task
                logger.debug(f"[QueueManager] Dispatched task '{task_id}' to worker")
                return task
            return None

    def task_done(self) -> None:
        """Acknowledge priority queue item completion."""
        self._queue.task_done()

    async def complete_task(self, task_id: str, updated_record: Dict[str, Any]) -> None:
        """Move running task to completed status."""
        async with self._lock:
            task = self.running_tasks.pop(task_id, None)
            if task:
                task.mark_completed(updated_record)
                self.completed_tasks[task_id] = task
                logger.debug(f"[QueueManager] Completed task '{task_id}'")

    async def fail_task(self, task_id: str, error: str) -> None:
        """
        Handle task failure. If retries remain, schedules for retry;
        otherwise marks as failed.
        """
        async with self._lock:
            task = self.running_tasks.pop(task_id, None)
            if not task:
                return

            if task.retry_count < task.max_retries:
                task.retry_count += 1
                task.status = "pending"
                self.pending_tasks[task_id] = task
                
                # Push back into queue
                await self._queue.put((-task.priority, task_id))
                logger.warning(
                    f"[QueueManager] Retrying task '{task_id}' ({task.retry_count}/{task.max_retries}). "
                    f"Reason: {error}"
                )
            else:
                task.mark_failed(error)
                self.failed_tasks[task_id] = task
                logger.error(f"[QueueManager] Task '{task_id}' failed permanently after {task.max_retries} retries: {error}")

    async def save_state(self) -> None:
        """
        Serialize all pending, running, completed, and failed tasks to JSON.
        """
        async with self._lock:
            # Running tasks are converted back to pending status for safety on restart
            saved_pending = list(self.pending_tasks.values())
            for task in self.running_tasks.values():
                task.status = "pending"
                saved_pending.append(task)

            data = {
                "pending": [t.model_dump(mode="json") for t in saved_pending],
                "completed": [t.model_dump(mode="json") for t in self.completed_tasks.values()],
                "failed": [t.model_dump(mode="json") for t in self.failed_tasks.values()],
            }

            try:
                self.state_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.state_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4)
                logger.info(f"[QueueManager] Saved queue state with {len(saved_pending)} pending tasks to {self.state_file.name}")
            except Exception as e:
                logger.error(f"[QueueManager] Failed to save queue state: {e}")

    async def load_state(self) -> bool:
        """
        Load tasks from JSON and repopulate buffers.
        """
        if not self.state_file.exists():
            return False

        async with self._lock:
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                # Clear existing
                self.pending_tasks.clear()
                self.running_tasks.clear()
                self.completed_tasks.clear()
                self.failed_tasks.clear()
                
                # Drain queue
                while not self._queue.empty():
                    try:
                        self._queue.get_nowait()
                        self._queue.task_done()
                    except asyncio.QueueEmpty:
                        break

                # Restore completed & failed
                for item in data.get("completed", []):
                    t = Task.model_validate(item)
                    self.completed_tasks[t.task_id] = t
                for item in data.get("failed", []):
                    t = Task.model_validate(item)
                    self.failed_tasks[t.task_id] = t

                # Restore pending
                pending_count = 0
                for item in data.get("pending", []):
                    t = Task.model_validate(item)
                    t.status = "pending"
                    self.pending_tasks[t.task_id] = t
                    await self._queue.put((-t.priority, t.task_id))
                    pending_count += 1

                logger.info(
                    f"[QueueManager] Restored state: pending={pending_count}, "
                    f"completed={len(self.completed_tasks)}, failed={len(self.failed_tasks)}"
                )
                return True
            except Exception as e:
                logger.error(f"[QueueManager] Failed to restore queue state from {self.state_file}: {e}")
                return False

    def clear_state_file(self) -> None:
        """Delete queue state index on clean exit."""
        if self.state_file.exists():
            try:
                self.state_file.unlink()
                logger.info(f"[QueueManager] Cleared state file: {self.state_file.name}")
            except Exception as e:
                logger.error(f"[QueueManager] Failed to clear state file: {e}")

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    @property
    def total_tasks_count(self) -> int:
        return (
            len(self.pending_tasks) +
            len(self.running_tasks) +
            len(self.completed_tasks) +
            len(self.failed_tasks)
        )
