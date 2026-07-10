"""
src/workers/progress_tracker.py
================================
Ingestion Progress Tracker.

Monitors queue sizes and tasks processed, computes estimated time
of completion (ETC), and persists state to disk.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_PROGRESS_FILE = Path("data/temp/worker_progress.json")


class ProgressTracker:
    """
    Computes processing progression and remaining timeline.
    """

    def __init__(self, progress_file: Optional[str | Path] = None) -> None:
        self.progress_file = Path(progress_file) if progress_file else DEFAULT_PROGRESS_FILE
        self.progress_file.parent.mkdir(parents=True, exist_ok=True)
        self.start_time = time.time()

    def update_progress(
        self,
        total_tasks: int,
        completed_tasks: int,
        failed_tasks: int,
        running_tasks: int,
        queue_size: int,
    ) -> Dict[str, Any]:
        """
        Calculate metrics, save to JSON, and return statistics.
        """
        processed = completed_tasks + failed_tasks
        elapsed_time = time.time() - self.start_time

        # Calculate processing rate (tasks/sec)
        rate = processed / elapsed_time if elapsed_time > 0 and processed > 0 else 0.0
        
        # Calculate Estimated Remaining Time
        remaining_tasks = total_tasks - processed
        etc_seconds = (remaining_tasks / rate) if rate > 0 else 0.0
        
        # Format HMS string
        etc_h = int(etc_seconds // 3600)
        etc_m = int((etc_seconds % 3600) // 60)
        etc_s = int(etc_seconds % 60)
        etc_hms = f"{etc_h:02d}:{etc_m:02d}:{etc_s:02d}" if rate > 0 else "00:00:00"

        progress_percent = (processed / total_tasks * 100.0) if total_tasks > 0 else 0.0

        report = {
            "progress": {
                "percentage_completed": round(progress_percent, 2),
                "total_tasks": total_tasks,
                "processed_tasks": processed,
                "completed_tasks": completed_tasks,
                "failed_tasks": failed_tasks,
                "running_tasks": running_tasks,
                "queue_size": queue_size,
            },
            "speed": {
                "elapsed_seconds": round(elapsed_time, 2),
                "tasks_per_second": round(rate, 3),
                "estimated_remaining_seconds": round(etc_seconds, 2),
                "estimated_remaining_hms": etc_hms,
            }
        }

        try:
            with open(self.progress_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=4)
        except Exception as e:
            logger.error(f"[ProgressTracker] Failed to write progress file: {e}")

        return report

    def clear(self) -> None:
        """Reset speed metrics."""
        self.start_time = time.time()
        if self.progress_file.exists():
            try:
                self.progress_file.unlink()
            except Exception:
                pass
