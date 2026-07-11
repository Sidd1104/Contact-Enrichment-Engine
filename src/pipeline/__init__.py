"""
src/pipeline/
=============
Master Pipeline Orchestrator package coordinates startup validation, config profiles,
concurrency worker pools, event dispatching, health monitoring, curses dashboard redrawing,
graceful exits, and ingestion benchmarks.
"""

from __future__ import annotations

from .configuration_profiles import PipelineProfile, get_profile
from .pipeline_state import PipelineState
from .pipeline_events import PipelineEventBus, PipelineEventType
from .pipeline_context import PipelineContext
from .pipeline_metrics import PipelineMetrics
from .health_monitor import HealthMonitor
from .performance_profiler import PerformanceProfiler
from .startup_validator import StartupValidator
from .shutdown_manager import ShutdownManager
from .dashboard import Dashboard
from .pipeline_orchestrator import PipelineOrchestrator
from .pipeline_runner import PipelineRunner
from .benchmark import PipelineBenchmark
from .pipeline_manager import PipelineManager

__all__ = [
    "PipelineProfile",
    "get_profile",
    "PipelineState",
    "PipelineEventBus",
    "PipelineEventType",
    "PipelineContext",
    "PipelineMetrics",
    "HealthMonitor",
    "PerformanceProfiler",
    "StartupValidator",
    "ShutdownManager",
    "Dashboard",
    "PipelineOrchestrator",
    "PipelineRunner",
    "PipelineBenchmark",
    "PipelineManager",
]
