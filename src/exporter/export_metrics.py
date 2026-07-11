"""
src/exporter/export_metrics.py
==============================
Tracks and persists performance and row metrics for data exports.
Saves metrics telemetry in logs/export_metrics.json.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)


class ExportMetrics:
    """
    Manages performance counters for export jobs.
    """

    def __init__(self, filepath: str = "logs/export_metrics.json") -> None:
        self.filepath = Path(filepath)
        self.export_duration = 0.0
        self.rows_exported = 0
        self.failed_exports = 0
        self.exports_count = 0
        self.format_counts = {"csv": 0, "excel": 0, "report": 0}
        
        self.load()

    def load(self) -> None:
        """Loads state from file if it exists, enabling cumulative metrics."""
        if self.filepath.exists():
            try:
                with open(self.filepath, "r") as f:
                    data = json.load(f)
                
                counts = data.get("counts", {})
                self.rows_exported = counts.get("rows_exported", 0)
                self.failed_exports = counts.get("failed_exports", 0)
                self.exports_count = counts.get("exports_count", 0)
                self.format_counts = counts.get("format_counts", {"csv": 0, "excel": 0, "report": 0})

                perf = data.get("performance", {})
                self.export_duration = perf.get("total_export_duration_seconds", 0.0)
            except Exception as e:
                logger.warning(f"Could not load export metrics: {e}. Starting fresh.")

    def record_export(self, format_type: str, rows: int, duration: float) -> None:
        """Records a successful export execution details."""
        self.exports_count += 1
        self.rows_exported += rows
        self.export_duration += duration
        
        fmt = format_type.lower()
        if fmt in self.format_counts:
            self.format_counts[fmt] += 1
        else:
            self.format_counts[fmt] = 1

    def record_failure(self) -> None:
        """Records an export failure."""
        self.failed_exports += 1

    def save(self) -> None:
        """Saves telemetry to disk."""
        try:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            
            avg_speed = (self.rows_exported / self.export_duration) if self.export_duration > 0 else 0.0
            
            report = {
                "counts": {
                    "exports_count": self.exports_count,
                    "rows_exported": self.rows_exported,
                    "failed_exports": self.failed_exports,
                    "format_counts": self.format_counts
                },
                "performance": {
                    "total_export_duration_seconds": round(self.export_duration, 3),
                    "average_export_speed_rows_per_sec": round(avg_speed, 2)
                }
            }
            
            with open(self.filepath, "w") as f:
                json.dump(report, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save export metrics: {e}")
