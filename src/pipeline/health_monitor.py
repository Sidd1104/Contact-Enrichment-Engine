"""
src/pipeline/health_monitor.py
==============================
Monitors system resources (CPU, RAM) and pipeline status (queue depth, workers, database).
Logs telemetry warnings if thresholds are exceeded.
"""

from __future__ import annotations

import socket
import logging
import psutil
from typing import Dict, Any, Tuple

from .pipeline_context import PipelineContext

logger = logging.getLogger(__name__)


class HealthMonitor:
    """
    Monitors engine and system resource boundaries.
    """

    def __init__(
        self,
        cpu_threshold: float = 85.0,
        ram_threshold: float = 90.0,
        api_check_host: str = "tavily.com"
    ) -> None:
        self.cpu_threshold = cpu_threshold
        self.ram_threshold = ram_threshold
        self.api_check_host = api_check_host

    def check_api_availability(self) -> bool:
        """Checks general network availability to APIs by resolving Tavily host."""
        try:
            # Short 2-second timeout
            socket.setdefaulttimeout(2.0)
            socket.gethostbyname(self.api_check_host)
            return True
        except Exception:
            return False

    def perform_health_check(
        self,
        context: PipelineContext,
        queue_size: int = 0,
        db_alive: bool = True,
        browser_active: bool = True
    ) -> Dict[str, Any]:
        """
        Samples resource usage and adds warnings to the pipeline context.
        """
        # 1. Fetch system metrics via psutil
        cpu_usage = psutil.cpu_percent(interval=None)
        ram_usage = psutil.virtual_memory().percent

        # 2. Check internet/API
        api_ok = self.check_api_availability()

        # 3. Compile report dict
        report = {
            "cpu_usage_percent": cpu_usage,
            "ram_usage_percent": ram_usage,
            "api_availability": api_ok,
            "database_ok": db_alive,
            "browser_active": browser_active,
            "queue_depth": queue_size
        }

        # 4. Analyze boundaries and log warnings to context
        if cpu_usage > self.cpu_threshold:
            msg = f"High CPU utilization: {cpu_usage}% (Threshold: {self.cpu_threshold}%)"
            context.log_warning(msg)
            logger.warning(f"[HealthMonitor] {msg}")

        if ram_usage > self.ram_threshold:
            msg = f"High memory utilization: {ram_usage}% (Threshold: {self.ram_threshold}%)"
            context.log_warning(msg)
            logger.warning(f"[HealthMonitor] {msg}")

        if not api_ok:
            msg = f"API hosts unreachable. Check network connection."
            context.log_warning(msg)
            logger.warning(f"[HealthMonitor] {msg}")

        if not db_alive:
            msg = "Database connection lost or queries failing."
            context.log_error(msg)
            logger.error(f"[HealthMonitor] {msg}")

        # Update context metrics directly
        context.set_value("queue_depth", queue_size)

        return report
