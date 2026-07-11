"""
src/pipeline/pipeline_context.py
================================
Maintains runtime state and configurations thread-safely throughout pipeline execution.
"""

from __future__ import annotations

import time
import threading
from typing import Dict, Any, Optional, List
from .pipeline_state import PipelineState
from .configuration_profiles import PipelineProfile, get_profile


class PipelineContext:
    """
    Thread-safe context storing runtime state variables, metrics,
    and statistics for monitoring, performance analysis, and checkpoint recovery.
    """

    def __init__(self, profile_name: str = "production", custom_settings: Optional[Dict[str, Any]] = None) -> None:
        self._lock = threading.Lock()
        
        # Load profile configurations
        self.profile = get_profile(profile_name)
        if custom_settings:
            # Dynamically override profile defaults
            for key, val in custom_settings.items():
                if hasattr(self.profile, key):
                    setattr(self.profile, key, val)
                    
        # State machine
        self._state = PipelineState.IDLE
        
        # Runtime tracking variables
        self.start_time: float = 0.0
        self.end_time: float = 0.0
        self.last_activity_time: float = 0.0
        
        self.current_batch_index: int = 0
        self.total_batches: int = 0
        self.total_records: int = 0
        self.processed_records: int = 0
        
        self.active_workers: int = 0
        self.queue_depth: int = 0
        
        # Ingestion metrics counters
        self.success_count: int = 0
        self.failed_count: int = 0
        self.retry_count: int = 0
        self.duplicate_count: int = 0
        
        self.emails_found: int = 0
        self.phones_found: int = 0
        self.ai_calls: int = 0
        self.ai_avoided: int = 0
        self.browser_launches: int = 0
        
        # Telemetry durations by stage (accumulated)
        self.search_time: float = 0.0
        self.scraping_time: float = 0.0
        self.validation_time: float = 0.0
        self.ai_time: float = 0.0
        self.db_time: float = 0.0
        self.export_time: float = 0.0
        
        # Errors log
        self.warnings: List[str] = []
        self.errors: List[str] = []
        self.processed_rows_log: List[Dict[str, Any]] = []

    @property
    def state(self) -> PipelineState:
        with self._lock:
            return self._state

    @state.setter
    def state(self, new_state: PipelineState) -> None:
        with self._lock:
            self._state = new_state
            self.last_activity_time = time.time()

    def update_metrics(self, **kwargs: Any) -> None:
        """Updates numeric counter fields thread-safely."""
        with self._lock:
            for key, val in kwargs.items():
                if hasattr(self, key):
                    current_val = getattr(self, key)
                    if isinstance(current_val, (int, float)):
                        setattr(self, key, current_val + val)
                    else:
                        setattr(self, key, val)
            self.last_activity_time = time.time()

    def set_value(self, key: str, value: Any) -> None:
        """Sets a context value thread-safely."""
        with self._lock:
            if hasattr(self, key):
                setattr(self, key, value)
            self.last_activity_time = time.time()

    def get_value(self, key: str) -> Any:
        """Gets a context value thread-safely."""
        with self._lock:
            return getattr(self, key, None)

    def log_warning(self, msg: str) -> None:
        with self._lock:
            self.warnings.append(msg)
            # Keep log capped to prevent memory bloat
            if len(self.warnings) > 100:
                self.warnings.pop(0)

    def log_error(self, msg: str) -> None:
        with self._lock:
            self.errors.append(msg)
            if len(self.errors) > 100:
                self.errors.pop(0)

    def log_processed_row(self, row_number: int, name: str, status: str, details: str) -> None:
        """Logs processed row outcome thread-safely."""
        with self._lock:
            self.processed_rows_log.append({
                "row": row_number,
                "name": name,
                "status": status,
                "details": details
            })
            if len(self.processed_rows_log) > 5:
                self.processed_rows_log.pop(0)

    def get_all_stats(self) -> Dict[str, Any]:
        """Returns a snapshot dictionary copy of all variables."""
        with self._lock:
            elapsed = 0.0
            if self.start_time > 0:
                if self.end_time > 0:
                    elapsed = self.end_time - self.start_time
                else:
                    elapsed = time.time() - self.start_time

            return {
                "profile": self.profile.model_dump(),
                "state": self._state.value,
                "elapsed_time_seconds": round(elapsed, 2),
                "current_batch_index": self.current_batch_index,
                "total_batches": self.total_batches,
                "total_records": self.total_records,
                "processed_records": self.processed_records,
                "active_workers": self.active_workers,
                "queue_depth": self.queue_depth,
                "success_count": self.success_count,
                "failed_count": self.failed_count,
                "retry_count": self.retry_count,
                "duplicate_count": self.duplicate_count,
                "emails_found": self.emails_found,
                "phones_found": self.phones_found,
                "ai_calls": self.ai_calls,
                "ai_avoided": self.ai_avoided,
                "browser_launches": self.browser_launches,
                "durations": {
                    "search": round(self.search_time, 2),
                    "scraping": round(self.scraping_time, 2),
                    "validation": round(self.validation_time, 2),
                    "ai": round(self.ai_time, 2),
                    "db": round(self.db_time, 2),
                    "export": round(self.export_time, 2)
                },
                "warnings_count": len(self.warnings),
                "errors_count": len(self.errors),
                "warnings": list(self.warnings),
                "errors": list(self.errors),
                "processed_rows_log": list(self.processed_rows_log)
            }
