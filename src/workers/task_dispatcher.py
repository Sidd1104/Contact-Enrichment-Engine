"""
src/workers/task_dispatcher.py
===============================
Task Ingestion and Dispatcher.

Splits incoming Import Engine record batches into system Task instances
and schedules them inside the priority queue.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List
from .task import Task
from .queue_manager import QueueManager

logger = logging.getLogger(__name__)


class TaskDispatcher:
    """
    Ingests and queues record processing tasks.
    """

    def __init__(self, queue_mgr: QueueManager) -> None:
        self.queue_mgr = queue_mgr

    async def dispatch_batch(self, batch_records: List[Dict[str, Any]]) -> List[str]:
        """
        Convert record dicts into Tasks and push to QueueManager.
        
        Priority Heuristics:
          - Records missing BOTH email and phone are given higher priority (priority=10).
          - Records missing only email or phone are given normal priority (priority=5).
        """
        task_ids = []
        for record in batch_records:
            # Determine priority
            email = record.get("email", "").strip()
            phone = record.get("phone", "").strip()
            
            missing_email = not email or email.lower() in ("nan", "none", "n/a", "-")
            missing_phone = not phone or phone.lower() in ("nan", "none", "n/a", "-")

            if missing_email and missing_phone:
                priority = 10  # Urgent priority: missing both
            else:
                priority = 5   # Standard priority: missing only one

            task = Task(
                record_data=record,
                priority=priority,
                max_retries=3
            )
            
            success = await self.queue_mgr.add_task(task)
            if success:
                task_ids.append(task.task_id)

        logger.info(f"[TaskDispatcher] Dispatched {len(task_ids)} records to queue manager.")
        return task_ids
