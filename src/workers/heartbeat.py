"""
src/workers/heartbeat.py
========================
Worker Heartbeat System.

Tracks active workers, receives periodic heartbeats, and provides
monitors to detect stalled tasks.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class HeartbeatMessage(BaseModel):
    """
    Heartbeat frame data sent by active workers.
    """
    worker_id: str = Field(description="Unique worker loop ID.")
    status: str = Field(description="Worker state: 'idle', 'busy', 'stalled'.")
    current_task_id: Optional[str] = Field(default=None, description="Current task UUID.")
    uptime: float = Field(description="Seconds worker has been running.")
    last_activity: float = Field(default_factory=time.time, description="Epoch timestamp of last action.")
    memory_usage_mb: float = Field(default=0.0, description="Estimated memory consumption.")


class HeartbeatSystem:
    """
    Registry receiving and validating worker heartbeats.
    """

    def __init__(self, stall_timeout: float = 10.0) -> None:
        self.stall_timeout = stall_timeout
        self._registry: Dict[str, HeartbeatMessage] = {}

    def register_heartbeat(self, hb: HeartbeatMessage) -> None:
        """Register worker heartbeat update."""
        self._registry[hb.worker_id] = hb
        logger.debug(f"[HeartbeatSystem] Heartbeat received from {hb.worker_id}: status={hb.status}")

    def get_worker_status(self, worker_id: str) -> Optional[HeartbeatMessage]:
        """Fetch worker status metadata."""
        return self._registry.get(worker_id)

    def check_stalled_workers(self) -> list[str]:
        """
        Scan registry and return list of worker IDs that have not sent a heartbeat
        within the stall_timeout duration.
        """
        now = time.time()
        stalled = []
        for worker_id, hb in self._registry.items():
            if hb.status == "stalled":
                stalled.append(worker_id)
                continue

            if now - hb.last_activity > self.stall_timeout:
                hb.status = "stalled"
                stalled.append(worker_id)
                logger.warning(
                    f"[HeartbeatSystem] Worker '{worker_id}' is marked stalled. "
                    f"Last activity was {now - hb.last_activity:.1f}s ago."
                )
        return stalled

    def deregister_worker(self, worker_id: str) -> None:
        """Remove worker from registry on shutdown."""
        self._registry.pop(worker_id, None)

    def clear(self) -> None:
        """Reset registry."""
        self._registry.clear()
