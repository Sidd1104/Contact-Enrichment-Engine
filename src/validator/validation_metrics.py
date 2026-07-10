"""
src/validator/validation_metrics.py
====================================
Tracks and serializes telemetry data regarding validation rates and duplicates removed.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)


class ValidationMetrics:
    """
    Measures count of validated contacts, deduplication impact, and average latencies.
    """

    def __init__(self, filepath: str = "logs/validation_metrics.json") -> None:
        self.filepath = Path(filepath)
        
        self.validated_emails = 0
        self.validated_phones = 0
        self.duplicates_removed = 0
        self.total_validation_time = 0.0
        self.sessions_count = 0

        self.load()

    def load(self) -> None:
        """Loads state from file if it exists."""
        if self.filepath.exists():
            try:
                with open(self.filepath, "r") as f:
                    data = json.load(f)
                
                counts = data.get("counts", {})
                self.validated_emails = counts.get("validated_emails", 0)
                self.validated_phones = counts.get("validated_phones", 0)
                self.duplicates_removed = counts.get("duplicates_removed", 0)

                perf = data.get("performance", {})
                self.total_validation_time = perf.get("total_validation_time", 0.0)
                self.sessions_count = perf.get("sessions_count", 0)
            except Exception as e:
                logger.warning(f"Could not load validation metrics: {e}. Starting fresh.")

    def record_validated(self, emails: int, phones: int) -> None:
        self.validated_emails += emails
        self.validated_phones += phones

    def record_duplicates_removed(self, count: int) -> None:
        self.duplicates_removed += count

    def record_session(self, latency: float) -> None:
        self.total_validation_time += latency
        self.sessions_count += 1

    def generate_report(self) -> Dict[str, Any]:
        """Calculates derived metrics and returns a report dictionary."""
        avg_time = (self.total_validation_time / self.sessions_count) if self.sessions_count > 0 else 0.0
        
        return {
            "counts": {
                "validated_emails": self.validated_emails,
                "validated_phones": self.validated_phones,
                "duplicates_removed": self.duplicates_removed
            },
            "performance": {
                "total_validation_time": round(self.total_validation_time, 3),
                "sessions_count": self.sessions_count,
                "average_validation_time_seconds": round(avg_time, 3)
            }
        }

    def save(self) -> None:
        """Saves current report to json file."""
        report = self.generate_report()
        try:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(self.filepath, "w") as f:
                json.dump(report, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save validation metrics: {e}")
