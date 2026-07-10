"""
src/importer/statistics.py
===========================
Importer Statistics Module.

Calculates data density stats, duplication estimates, batch calculations,
and estimated enrichment execution timelines. Writes stats to JSON.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Default stats output destination
DEFAULT_STATS_FILE = Path("logs/import_statistics.json")


class ImportStatistics:
    """
    Tracks and exports ingestion statistics.
    """

    def __init__(self, stats_file: Optional[Path] = None) -> None:
        self.stats_file = stats_file or DEFAULT_STATS_FILE
        self.stats_file.parent.mkdir(parents=True, exist_ok=True)

    def generate_report(
        self,
        file_name: str,
        sheet_name: str,
        total_records: int,
        completed_records: int,
        queued_records: int,
        duplicates_count: int,
        batch_size: int,
        estimated_sec_per_record: float = 1.5,
    ) -> Dict[str, Any]:
        """
        Build the quality and size report, and write it to a JSON file.
        """
        # Calculate batches
        if queued_records == 0:
            batch_count = 0
        else:
            batch_count = (queued_records + batch_size - 1) // batch_size

        # Estimate processing time
        est_total_seconds = queued_records * estimated_sec_per_record
        est_hours = int(est_total_seconds // 3600)
        est_minutes = int((est_total_seconds % 3600) // 60)
        est_seconds = int(est_total_seconds % 60)

        time_str = f"{est_hours:02d}:{est_minutes:02d}:{est_seconds:02d}"

        report = {
            "dataset": {
                "file_name": file_name,
                "sheet_name": sheet_name,
            },
            "counts": {
                "total_records": total_records,
                "completed_records": completed_records,
                "eligible_records": queued_records,
                "duplicates_skipped": duplicates_count,
                "queue_size": queued_records,
            },
            "batching": {
                "batch_size": batch_size,
                "batch_count": batch_count,
            },
            "estimation": {
                "processing_rate_sec_per_record": estimated_sec_per_record,
                "estimated_processing_seconds": round(est_total_seconds, 2),
                "estimated_processing_hms": time_str,
            }
        }

        try:
            with open(self.stats_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=4)
            logger.info(f"[ImportStatistics] Statistics report saved to {self.stats_file.name}")
        except Exception as e:
            logger.error(f"[ImportStatistics] Failed to save stats report to {self.stats_file}: {e}")

        return report
