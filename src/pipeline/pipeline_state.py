"""
src/pipeline/pipeline_state.py
==============================
Defines the pipeline state tracking enum.
"""

from __future__ import annotations

from enum import Enum


class PipelineState(str, Enum):
    """
    State machine values for the Pipeline Orchestrator.
    """
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"
