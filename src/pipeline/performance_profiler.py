"""
src/pipeline/performance_profiler.py
====================================
Measures performance speeds, throughput rates, and latency distributions for the stages.
Provides a context manager for timing individual pipeline phases.
"""

from __future__ import annotations

import time
import logging
from contextlib import contextmanager
from typing import Generator

from .pipeline_context import PipelineContext

logger = logging.getLogger(__name__)


class PerformanceProfiler:
    """
    Measures pipeline speeds and logs telemetries to context.
    """

    @staticmethod
    @contextmanager
    def profile_stage(context: PipelineContext, stage_name: str) -> Generator[None, None, None]:
        """
        Context manager to measure the latency of a specific stage and record it to context.
        
        Usage:
            with PerformanceProfiler.profile_stage(context, "search"):
                await search_manager.resolve(...)
        """
        start = time.perf_counter()
        yield
        duration = time.perf_counter() - start
        
        # Match stage to context accumulation variable
        mapping = {
            "search": "search_time",
            "scraping": "scraping_time",
            "validation": "validation_time",
            "ai": "ai_time",
            "db": "db_time",
            "export": "export_time"
        }
        
        normalized_stage = stage_name.lower().strip()
        if normalized_stage in mapping:
            context.update_metrics(**{mapping[normalized_stage]: duration})
            logger.debug(f"[Profiler] Stage '{stage_name}' execution completed in {duration:.3f}s")
        else:
            logger.warning(f"[Profiler] Unknown stage profiled: {stage_name}")
