"""
src/workers/resource_monitor.py
================================
Resource Usage Monitor.

Periodically queries host CPU/RAM metrics and triggers warnings if thresholds
are exceeded.
"""

from __future__ import annotations

import logging
import os
import psutil
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


class ResourceMonitor:
    """
    Monitors process and host CPU and memory consumption.
    """

    def __init__(self, cpu_threshold: float = 85.0, ram_threshold: float = 90.0) -> None:
        self.cpu_threshold = cpu_threshold
        self.ram_threshold = ram_threshold
        self._process = psutil.Process(os.getpid())

    def get_metrics(self) -> Tuple[float, float, float]:
        """
        Query system resource consumption.
        
        Returns:
            Tuple of (host_cpu_percentage, host_ram_percentage, process_memory_mb).
        """
        try:
            host_cpu = psutil.cpu_percent(interval=None)
            host_ram = psutil.virtual_memory().percent
            
            # Process private memory (Resident Set Size)
            rss = self._process.memory_info().rss
            process_mb = rss / (1024 * 1024)
            
            return host_cpu, host_ram, process_mb
        except Exception as e:
            logger.warning(f"[ResourceMonitor] Failed to fetch hardware stats: {e}")
            return 0.0, 0.0, 0.0

    def check_thresholds(self) -> Dict[str, str]:
        """
        Inspect limits and return warning alerts if limits are exceeded.
        """
        host_cpu, host_ram, process_mb = self.get_metrics()
        warnings = {}

        if host_cpu > self.cpu_threshold:
            msg = f"High CPU usage warning: {host_cpu}% (threshold: {self.cpu_threshold}%)"
            warnings["cpu"] = msg
            logger.warning(f"[ResourceMonitor] {msg}")

        if host_ram > self.ram_threshold:
            msg = f"High RAM usage warning: {host_ram}% (threshold: {self.ram_threshold}%)"
            warnings["ram"] = msg
            logger.warning(f"[ResourceMonitor] {msg}")

        return warnings
