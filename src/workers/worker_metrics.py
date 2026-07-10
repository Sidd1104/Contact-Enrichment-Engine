"""
src/workers/worker_metrics.py
==============================
Worker Pool Metrics.

Tracks active throughput, worker utility rates, task durations,
failures, and restarts, exporting logs/worker_metrics.json.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, Optional
from ..config.ai_config import ai_config

logger = logging.getLogger(__name__)

DEFAULT_METRICS_FILE = Path("logs/worker_metrics.json")


class WorkerMetrics:
    """
    Manages telemetry stats for worker pools.
    """

    def __init__(self, metrics_file: Optional[str | Path] = None) -> None:
        self.metrics_file = Path(metrics_file) if metrics_file else DEFAULT_METRICS_FILE
        self.metrics_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        
        # Telemetry variables
        self.tasks_processed = 0
        self.tasks_succeeded = 0
        self.tasks_failed = 0
        self.total_retries = 0
        self.worker_restarts = 0
        self.total_task_duration = 0.0
        self.peak_concurrency = 0
        self.utilization_sum = 0.0  # running busy count summation
        self.utilization_points = 0

    async def record_task_completion(self, success: bool, duration: float, retries: int) -> None:
        """
        Record final task execution metrics.
        """
        async with self._lock:
            self.tasks_processed += 1
            if success:
                self.tasks_succeeded += 1
            else:
                self.tasks_failed += 1
            self.total_task_duration += duration
            self.total_retries += retries
            await self._save_metrics()

    async def record_worker_restart(self) -> None:
        """Record worker crash recovery event."""
        async with self._lock:
            self.worker_restarts += 1
            await self._save_metrics()

    async def update_utilization(self, busy_workers: int, total_workers: int, current_queue: int) -> None:
        """
        Periodically record concurrency metrics.
        """
        async with self._lock:
            if total_workers > 0:
                utilization = busy_workers / total_workers
                self.utilization_sum += utilization
                self.utilization_points += 1

            if busy_workers > self.peak_concurrency:
                self.peak_concurrency = busy_workers

            await self._save_metrics()

    async def _save_metrics(self) -> None:
        """Write metrics to JSON file."""
        avg_duration = 0.0
        if self.tasks_processed > 0:
            avg_duration = self.total_task_duration / self.tasks_processed

        avg_utilization = 0.0
        if self.utilization_points > 0:
            avg_utilization = self.utilization_sum / self.utilization_points

        report = {
            "summary": {
                "tasks_processed": self.tasks_processed,
                "tasks_succeeded": self.tasks_succeeded,
                "tasks_failed": self.tasks_failed,
                "total_retries": self.total_retries,
                "worker_restarts": self.worker_restarts,
                "average_task_duration_seconds": round(avg_duration, 3),
                "average_worker_utilization_ratio": round(avg_utilization, 4),
                "peak_concurrency_workers": self.peak_concurrency,
            }
        }

        try:
            with open(self.metrics_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=4)
        except Exception as e:
            logger.error(f"[WorkerMetrics] Failed to save worker metrics: {e}")

    async def clear(self) -> None:
        """Reset metrics data."""
        async with self._lock:
            self.tasks_processed = 0
            self.tasks_succeeded = 0
            self.tasks_failed = 0
            self.total_retries = 0
            self.worker_restarts = 0
            self.total_task_duration = 0.0
            self.peak_concurrency = 0
            self.utilization_sum = 0.0
            self.utilization_points = 0
            await self._save_metrics()
            logger.info("[WorkerMetrics] Metrics cleared.")
