"""
src/workers/task.py
====================
System Task Models.

Defines Pydantic structures for tasks processed by the asynchronous worker pool.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class Task(BaseModel):
    """
    Representation of a single record processing task.
    """
    task_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Globally unique task identifier."
    )
    record_data: Dict[str, Any] = Field(
        description="Standardized input record from Import Engine."
    )
    priority: int = Field(
        default=0,
        description="Task priority. Higher numbers are pulled first."
    )
    status: str = Field(
        default="pending",
        description="Task lifecycle state: 'pending', 'running', 'completed', 'failed'."
    )
    retry_count: int = Field(
        default=0,
        description="Number of retries attempted so far."
    )
    max_retries: int = Field(
        default=3,
        description="Maximum retries before marking task as failed."
    )
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when task was created."
    )
    started_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when task processing started."
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when task processing finished."
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error description if task failed."
    )

    def mark_started(self) -> None:
        """Move task state to running."""
        self.status = "running"
        self.started_at = datetime.now()

    def mark_completed(self, updated_record: Dict[str, Any]) -> None:
        """Move task state to completed and update payload."""
        self.status = "completed"
        self.completed_at = datetime.now()
        self.record_data = updated_record
        self.error_message = None

    def mark_failed(self, error: str) -> None:
        """Mark task as failed and register error."""
        self.status = "failed"
        self.completed_at = datetime.now()
        self.error_message = error
